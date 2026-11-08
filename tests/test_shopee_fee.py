import pandas as pd

from src.core import shopee_fee as fee


def test_margin_with_caps_and_order_fee():
    inp = fee.Inputs(harga=1_000_000, admin_pct=11.7, hpp=500_000, iklan=20_000)
    # admin 117.000 + bayar 18.000 + pajak 5.000 + GOX 40.000 (maks) + promo 45.000 + live 20.000 + video 20.000 + asuransi 5.000 + proses 1.250
    assert round(fee.shopee_fees(inp)) == 271_250
    big = fee.Inputs(harga=1_000_000, admin_pct=11.7, ukuran_khusus=True)
    assert round(fee.shopee_fees(big) - fee.shopee_fees(fee.Inputs(harga=1_000_000, admin_pct=11.7))) == 20_000
    value, pct = fee.margin(inp)
    assert round(value) == 1_000_000 - 271_250 - 20_000 - 500_000
    assert fee.min_price(inp, 0) <= 1_000_000


def test_affiliate_and_breakeven():
    inp = fee.Inputs(harga=100_000, hpp=80_000, affiliate_pct=5, affiliate_on=True)
    value, _ = fee.margin(inp)
    off, _ = fee.margin(fee.Inputs(harga=100_000, hpp=80_000))
    assert round(off - value) == 5_000
    bep = fee.min_price(inp, 0)
    v_bep, _ = fee.margin(fee.Inputs(harga=bep, hpp=80_000, affiliate_pct=5, affiliate_on=True))
    assert v_bep >= 0 and v_bep < 200


def test_parse_affiliate_and_suggest():
    raw = pd.DataFrame([["x", "id", None], ["Produk ID", "Nama Produk", "Persentase Komisi"], ["Tidak perlu", "", "Wajib"], ["123456789", "Kloset Duduk Tidy", "5"]])
    out = fee.parse_affiliate(raw)
    assert out.iloc[0]["product_code"] == "123456789" and out.iloc[0]["komisi_pct"] == 5
    fees = fee.load_category_fees()
    idx = fee.suggest_category("Kloset Duduk Tidy FSA0089 Closet One Piece", fees)
    assert fees.loc[idx, "sub_kategori"] == "Kamar Mandi"


def _row(sku, iklan, qty, kotor, **extra):
    base = {"sku": sku, "nama": sku.lower(), "kategori": "x", "harga": 100_000, "diskon_unit": 0, "voucher_unit": 0, "admin_pct": 11.7,
            "affiliate_pct": 0, "iklan_unit": iklan, "roas": 100_000 / iklan if iklan else float("nan"), "qty_30": qty, "omzet_30": qty * 100_000,
            "ukuran_khusus": False, "margin_kotor_pct": kotor, "pajak_share": 1 - 1 / 1.1, "sumber": "Shopee"}
    base.update(extra)
    return base


def test_portfolio_status_and_priority():
    rows = pd.DataFrame([
        _row("A", 30_000, 1, 35.0),            # iklan 30% → rugi besar per unit, omzet kecil
        _row("B", 5_000, 30, 35.0),           # rugi tipis tapi omzet besar → kerugian Rp terbesar
        _row("C", 0, 50, 45.0),                # tanpa iklan, margin tinggi
        _row("D", 0, 50, 33.0),                # untung tipis → rendah
        _row("E", 0, 5, float("nan"), sumber=""),  # tidak ada di file → rata-rata toko
    ])
    out = fee.portfolio(rows, programs=fee.DEFAULT_PROGRAMS, order_fee=1250, fallback_kotor_pct=float("nan"))
    assert out["sku"].tolist()[:2] == ["B", "A"]
    assert out.iloc[0]["status"] == "Rugi" and "iklan" in out.iloc[0]["perbaikan"].lower()
    status = dict(zip(out["sku"], out["status"]))
    assert status["C"] == "Tinggi" and status["D"] == "Rendah" and status["E"] == "Tanpa data"
    acuan = out.attrs["acuan_pct"]
    assert out.loc[out["sku"] == "D", "bersih_pct"].iloc[0] < acuan < out.loc[out["sku"] == "C", "bersih_pct"].iloc[0]
    # Kotor 45% (harga termasuk pajak) − potongan Shopee ≈ margin bersih C
    c = out.loc[out["sku"] == "C"].iloc[0]
    assert abs(c["kotor_pct"] - c["shopee_pct"] - c["bersih_pct"]) < 1e-6
    filled = fee.portfolio(rows, programs=fee.DEFAULT_PROGRAMS, order_fee=1250, fallback_kotor_pct=40.0)
    assert filled.loc[filled["sku"] == "E", "sumber"].iloc[0] == "Rata-rata toko"


def test_modal_stays_fixed_when_price_changes():
    inp = fee.Inputs(harga=100_000, admin_pct=10, programs={}, order_fee=0, pajak_share=0.1, hpp=60_000)
    assert round(fee.kotor_pct(inp), 6) == 30.0
    higher = fee.margin(fee.Inputs(harga=120_000, admin_pct=10, programs={}, order_fee=0, pajak_share=0.1, hpp=60_000))[0]
    assert round(higher) == round(120_000 * 0.9 - 60_000 - 12_000)
    rows = fee.breakdown(inp)
    assert rows["Komponen"].iloc[-1] == "Margin bersih" and round(rows.loc[rows["Komponen"] == "Margin kotor", "Rp per unit"].iloc[0]) == 30_000
    notes = fee.analysis(inp, target_pct=15)
    assert notes[0][0] == "ok"
