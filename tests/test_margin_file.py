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
