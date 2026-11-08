import pandas as pd

from src.core import shopee_fee as fee


def test_margin_with_caps_and_order_fee():
    inp = fee.Inputs(harga=1_000_000, admin_pct=11.7, hpp=500_000, iklan=20_000)
    # admin 117.000 + bayar 18.000 + pajak 5.000 + GOX 0 + promo 45.000 + live 20.000 (maks) + asuransi 5.000 + proses 1.250
    assert round(fee.shopee_fees(inp)) == 211_250
    value, pct = fee.margin(inp)
    assert round(value) == 1_000_000 - 211_250 - 20_000 - 500_000
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
