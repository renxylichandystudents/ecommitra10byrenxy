import pandas as pd

from src.activity import region_summary, region_total_row


def test_invoice_columns_add_up_and_sales_share():
    lines = pd.DataFrame({
        "order_id": [1, 2, 3, 4, 5], "province": ["JAWA BARAT"] * 3 + ["BANTEN"] * 2, "qty": [1, 2, 1, 3, 1],
        "returned_qty": [0, 0, 1, 0, 0], "cancelled": [False, True, False, False, False],
        "menunggu": [False, False, False, True, False], "unit_price": [100, 100, 100, 50, 50],
    })
    table = region_summary(lines, "province")
    parts = table[["Invoice bersih", "Invoice batal", "Invoice retur penuh", "Invoice Belum Bayar"]].sum(axis=1)
    assert (parts == table["Invoice total"]).all()
    assert list(table["Kontribusi sales bersih"].round(1)) == [66.7, 33.3]
    total = region_total_row(table, "Provinsi").iloc[0]
    assert total["Rank"] == "" and total["Invoice Belum Bayar"] == 1 and total["Sales bersih"] == 150
