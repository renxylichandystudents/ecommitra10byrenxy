import io

import numpy as np
import pandas as pd

from src.core import margin_file as mf


def _book() -> bytes:
    nas = [["Year - Month - Date", 10, None, None, None, None], ["Adjustment", "No", None, None, None, None], [None] * 6,
           ["Item Code", "Item Name", "Sales Include Tax - FACTTRANSACTION", "Sales Exclude Tax", "Gross Margin Value", "Gross Margin (Percentage)"],
           ["0100000001", "A", 110.0, 100.0, 20.0, 0.2], ["0100000002", "B", 220.0, 200.0, 60.0, 0.3], ["0100000003", "C", 11.0, 10.0, -50.0, -5.0],
           ["0100000004", "D", 0.0, 0.0, 0.0, 0.0], ["Grand Total", None, 341.0, 310.0, 30.0, 0.1]]
    shp = [["Year - Month - Date", 2026, None, None, None, None], ["Adjustment", "No", None, None, None, None], ["Customer Name", "SHOPEE - EC", None, None, None, None],
           [None] * 6, ["Item Code", "Item Name", "Sales Include Tax - FACTTRANSACTION", "Sales Exclude Tax", "Gross Margin Value", "Gross Margin (Percentage)"],
           ["0100000001", "A", 1100.0, 1000.0, 330.0, 0.33], ["0100000005", "E", 550.0, 500.0, -2000.0, -4.0], ["Grand Total", None, 1650.0, 1500.0, -1670.0, -1.1]]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as writer:
        pd.DataFrame(nas).to_excel(writer, sheet_name="Margin Nasional", header=False, index=False)
        pd.DataFrame(shp).to_excel(writer, sheet_name="Margin Shopee", header=False, index=False)
    return buf.getvalue()


def test_read_and_lookup():
    parsed = mf.read_margin_workbook(_book())
    assert parsed["periode"] == "Oktober 2026"
    shopee, nas = parsed["sheets"]["shopee"]["items"], parsed["sheets"]["nasional"]["items"]
    assert set(shopee["sku"]) == {"100000001", "100000005"} and "100000004" not in set(nas["sku"])
    look = mf.lookup(shopee, nas).set_index("sku")
    # A dari Shopee: 330 / 1100 = 30% dari harga termasuk pajak; file 33% dari exclude
    assert round(look.loc["100000001", "margin_kotor_pct"], 6) == 30.0 and look.loc["100000001", "sumber"] == "Shopee"
    assert round(look.loc["100000001", "margin_file_pct"], 6) == 33.0
    # B hanya di nasional
    assert look.loc["100000002", "sumber"] == "Nasional"
    # C tidak wajar di nasional & tidak ada di Shopee → tidak dipakai; E tidak wajar di Shopee, tidak ada cadangan → ditandai
    assert "100000003" not in look.index
    assert np.isnan(look.loc["100000005", "margin_kotor_pct"]) and "tidak wajar" in look.loc["100000005", "catatan"]
    assert round(mf.store_average(shopee), 6) == 30.0
    assert mf.sku_key("0200012180") == "200012180"
    assert mf.classify(-1, 10) == "Rugi" and mf.classify(5, 10) == "Rendah" and mf.classify(12, 10) == "Tinggi" and mf.classify(np.nan, 10) == "Tanpa data"


def test_report_period_and_inactive():
    from src.core import margin_report as mr

    shopee = pd.DataFrame({"sku": ["1", "2", "3"], "item_code": ["01", "02", "03"], "nama": ["A", "B", "C"],
                           "sales_incl": [1100.0, 1100.0, 1100.0], "sales_excl": [1000.0, 1000.0, 1000.0], "gm_value": [550.0, 88.0, 440.0]})
    look = mf.lookup(shopee, None)
    orders = pd.DataFrame({
        "order_time": pd.to_datetime(["2026-09-05", "2026-10-03", "2026-10-04", "2026-10-05", "2026-06-01", "2026-08-20"]),
        "sku": ["1", "1", "2", "9", "3", "3"], "qty": [1, 2, 1, 1, 1, 1], "sales": [100_000, 200_000, 100_000, 50_000, 100_000, 100_000],
        "status": ["Selesai"] * 6, "product_name": ["A", "A", "B", "X", "C", "C"],
    })
    period = mr.sales_by_sku(orders, pd.Timestamp("2026-10-01").date(), pd.Timestamp("2026-10-31").date())
    assert set(period["sku"]) == {"1", "2", "9"} and float(period.loc[period["sku"] == "1", "penjualan"].iloc[0]) == 200_000
    rep = mr.build(period, look, programs={}, order_fee=0, admin={"1": 10, "2": 10, "9": 10})
    status = dict(zip(rep["sku"], rep["status"]))
    assert status["1"] == "Tinggi" and status["2"] == "Rugi" and status["9"] == "Tanpa data margin"
    a = rep.loc[rep["sku"] == "1"].iloc[0]
    assert round(a["kotor_rp"]) == 100_000 and round(a["bersih_rp"]) == 80_000
    hist = mr.sales_by_sku(orders)
    off = mr.inactive_impact(hist.loc[hist["sku"] == "3"], look, acuan_pct=10.0, programs={}, order_fee=0, admin={"3": 10})
    row = off.iloc[0]
    assert row["bulan"] == 3 and round(row["dampak_bulan"]) == round((200_000 * 0.4 - 20_000) / 3)
