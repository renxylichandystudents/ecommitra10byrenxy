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


def test_portfolio_priority_by_leak():
    rows = pd.DataFrame([
        {"sku": "A", "nama": "a", "kategori": "x", "harga": 100_000, "diskon_unit": 0, "voucher_unit": 0, "admin_pct": 11.7, "affiliate_pct": 0,
         "iklan_unit": 30_000, "roas": 3.3, "qty_30": 10, "omzet_30": 1_000_000, "ukuran_khusus": False},
        {"sku": "B", "nama": "b", "kategori": "x", "harga": 100_000, "diskon_unit": 0, "voucher_unit": 0, "admin_pct": 11.7, "affiliate_pct": 0,
         "iklan_unit": 20_000, "roas": 5, "qty_30": 100, "omzet_30": 10_000_000, "ukuran_khusus": False},
        {"sku": "C", "nama": "c", "kategori": "x", "harga": 100_000, "diskon_unit": 0, "voucher_unit": 0, "admin_pct": 11.7, "affiliate_pct": 0,
         "iklan_unit": 0, "roas": float("nan"), "qty_30": 1, "omzet_30": 100_000, "ukuran_khusus": False},
    ])
    out = fee.portfolio(rows, programs=fee.DEFAULT_PROGRAMS, order_fee=1250, limit_pct=30)
    assert out["sku"].tolist()[:2] == ["B", "A"]  # B bocor lebih besar karena omzetnya besar
    assert out.iloc[0]["status"] == "Melebihi batas"
    assert "iklan" in out.iloc[0]["perbaikan"]
