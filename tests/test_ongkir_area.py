"""Saran harga ongkir Area Provinsi: +15% integer, harga terisi tetap, unduhan Excel."""

from __future__ import annotations

from io import BytesIO

import openpyxl
import pandas as pd

from src.core import ongkir_area as OA


def test_normalize_area_key_kabupaten_variants():
    assert OA.normalize_area_key("Kabupaten Bekasi") == "KAB. BEKASI"
    assert OA.normalize_area_key("KAB. BEKASI") == "KAB. BEKASI"
    assert OA.normalize_area_key("KOTA JAKARTA SELATAN") == "KOTA JAKARTA SELATAN"
    assert OA.normalize_area_key("") == ""


def test_suggest_price_markup_integer():
    assert OA.suggest_price(100_000) == 115_000
    assert OA.suggest_price(100_001) == 115_001  # round(100001*1.15)=115001.15 → 115001
    assert OA.suggest_price(143_000) == 164_450
    assert OA.suggest_price(float("nan")) is None


def test_order_shipping_median_prefers_estimated():
    raw = pd.DataFrame(
        {
            "No. Pesanan": ["A", "A", "B", "C"],
            "Waktu Pesanan Dibuat": ["2026-10-01 10:00"] * 4,
            "Nama Produk": ["Cat"] * 4,
            "Jumlah": [1, 1, 1, 1],
            "Harga Setelah Diskon": [50_000] * 4,
            "Status Pesanan": ["Selesai"] * 4,
            "Provinsi": ["BANTEN"] * 4,
            "Kota/Kabupaten": ["KAB. TANGERANG"] * 4,
            "Perkiraan Ongkos Kirim": [100_000, 100_000, 120_000, 80_000],
            "Ongkos Kirim Dibayar Pembeli": [10_000] * 4,
            "Estimasi Potongan Biaya Pengiriman": [5_000] * 4,
        }
    )
    by_city = OA.order_shipping_by_city(raw)
    assert len(by_city) == 1
    assert by_city.iloc[0]["area_key"] == "KAB. TANGERANG"
    # median of 100k, 120k, 80k = 100k (one value per order)
    assert by_city.iloc[0]["Ongkir median"] == 100_000
    assert by_city.iloc[0]["Invoice"] == 3


def test_build_suggestions_preserves_filled():
    template = pd.DataFrame(
        {
            "block": [0, 0, 0],
            "row": [2, 3, 4],
            "prov_col": [1, 1, 1],
            "area_col": [2, 2, 2],
            "ongkir_col": [3, 3, 3],
            "Provinsi": ["BANTEN", "BANTEN", "DKI JAKARTA"],
            "Area": ["KAB. TANGERANG", "KOTA SERANG", "KOTA JAKARTA BARAT"],
            "area_key": ["KAB. TANGERANG", "KOTA SERANG", "KOTA JAKARTA BARAT"],
            "Ongkir terisi": [207_000.0, None, None],
        }
    )
    shipping = pd.DataFrame(
        {
            "area_key": ["KAB. TANGERANG", "KOTA JAKARTA BARAT"],
            "Provinsi": ["BANTEN", "DKI JAKARTA"],
            "Kota/Kabupaten": ["KAB. TANGERANG", "KOTA JAKARTA BARAT"],
            "Ongkir median": [100_000.0, 200_000.0],
            "Invoice": [5, 2],
        }
    )
    out = OA.build_suggestions(template, shipping)
    by_area = out.set_index("Area")
    assert by_area.loc["KAB. TANGERANG", "Status"] == "Tetap (sudah diisi)"
    assert by_area.loc["KAB. TANGERANG", "Ongkir usulan"] == 207_000
    assert by_area.loc["KOTA JAKARTA BARAT", "Status"] == "Saran dari transaksi"
    assert by_area.loc["KOTA JAKARTA BARAT", "Saran ongkir"] == 230_000
    assert by_area.loc["KOTA JAKARTA BARAT", "Ongkir usulan"] == 230_000
    assert by_area.loc["KOTA SERANG", "Status"] == "Belum ada data transaksi"
    assert by_area.loc["KOTA SERANG", "Ongkir usulan"] is None


def _mini_template_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"], ws["B1"], ws["C1"] = "Provinsi", "Area", "Ongkir"
    ws["A2"], ws["B2"], ws["C2"] = "BANTEN", "KAB. TANGERANG", 207000
    ws["A3"], ws["B3"] = None, "KOTA SERANG"
    ws["A4"], ws["B4"] = None, "KOTA CILEGON"
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_and_export_preserves_filled_fills_rest():
    raw_bytes = _mini_template_bytes()
    template = OA.parse_area_template(raw_bytes)
    assert len(template) == 3
    filled = template.loc[template["Area"].str.contains("TANGERANG", case=False)]
    assert float(filled.iloc[0]["Ongkir terisi"]) == 207_000

    shipping = pd.DataFrame(
        {
            "area_key": ["KOTA SERANG", "KOTA CILEGON"],
            "Ongkir median": [100_000.0, 200_000.0],
            "Invoice": [3, 1],
        }
    )
    suggestions = OA.build_suggestions(template, shipping)
    exported = OA.export_area_excel(suggestions, template_source=raw_bytes)
    wb = openpyxl.load_workbook(BytesIO(exported), data_only=True)
    ws = wb.active
    assert ws["C2"].value == 207000  # tetap
    assert ws["C3"].value == 115000  # 100k × 1.15
    assert ws["C4"].value == 230000  # 200k × 1.15


def test_default_template_parses_and_keeps_user_fills():
    assert OA.DEFAULT_TEMPLATE.is_file()
    template = OA.parse_area_template(OA.DEFAULT_TEMPLATE)
    assert len(template) >= 400
    filled = template["Ongkir terisi"].notna().sum()
    assert filled == 13
    # Sample filled area must stay "Tetap" even if transaksi suggests differently.
    shipping = pd.DataFrame(
        {
            "area_key": [OA.normalize_area_key("KOTA TANGERANG")],
            "Ongkir median": [1.0],
            "Invoice": [1],
        }
    )
    out = OA.build_suggestions(template, shipping)
    row = out.loc[out["area_key"] == "KOTA TANGERANG"].iloc[0]
    assert row["Status"] == "Tetap (sudah diisi)"
    assert int(row["Ongkir usulan"]) == 143_000
