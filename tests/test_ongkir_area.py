"""Saran harga ongkir Area Provinsi: berat dikenakan, +15% integer, harga terisi tetap."""

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
    assert OA.suggest_price(100_001) == 115_001
    assert OA.suggest_price(143_000) == 164_450
    assert OA.suggest_price(float("nan")) is None


def test_volumetric_and_chargeable_kg():
    # 40×20×20 / 6000 = 2,666… kg (Shopee Reguler/Hemat Kargo; contoh edukasi ≈2,6)
    assert abs(OA.volumetric_kg(40, 20, 20) - (40 * 20 * 20 / 6000)) < 1e-12
    vol = OA.volumetric_kg(40, 20, 20)
    assert OA.chargeable_kg(1.3, vol) == vol  # volumetrik menang
    assert OA.chargeable_kg(4.0, 1.3) == 4.0  # aktual menang
    assert pd.isna(OA.chargeable_kg(None, None))


def test_chargeable_weight_changes_median_vs_raw_fee():
    """Paket ringan + berat: median ongkir mentah menyesatkan; rumus Rp/kg × median kg lebih tepat."""
    raw = pd.DataFrame(
        {
            "No. Pesanan": ["L1", "H1", "H2"],
            "Waktu Pesanan Dibuat": ["2026-10-01 10:00"] * 3,
            "Nama Produk": ["Cat"] * 3,
            "Jumlah": [1, 1, 1],
            "Harga Setelah Diskon": [50_000] * 3,
            "Status Pesanan": ["Selesai"] * 3,
            "Provinsi": ["BANTEN"] * 3,
            "Kota/Kabupaten": ["KAB. TANGERANG"] * 3,
            "Perkiraan Ongkos Kirim": [20_000, 200_000, 220_000],
            "Total Berat": [1000, 20000, 22000],  # gram → 1 / 20 / 22 kg
        }
    )
    # Median ongkir mentah = 200_000 (tertarik paket ringan 20rb).
    # Rate: 20000, 10000, 10000 → median rate 10000; median kg = 20; dasar = 200_000.
    by_city = OA.order_shipping_by_city(raw)
    assert len(by_city) == 1
    assert by_city.iloc[0]["Metode"] == "berat_dikenakan"
    assert by_city.iloc[0]["Ongkir median"] == 200_000
    assert by_city.iloc[0]["Berat dikenakan median (kg)"] == 20.0
    assert by_city.iloc[0]["Rp per kg median"] == 10_000
    # Saran = 200000 × 1.15
    out = OA.build_suggestions(
        pd.DataFrame(
            {
                "block": [0],
                "row": [2],
                "ongkir_col": [3],
                "Provinsi": ["BANTEN"],
                "Area": ["KAB. TANGERANG"],
                "area_key": ["KAB. TANGERANG"],
                "Ongkir terisi": [None],
            }
        ),
        by_city,
    )
    assert out.iloc[0]["Saran ongkir"] == 230_000


def test_volumetric_from_carton_beats_lighter_actual():
    """Aktual 1,3 kg tapi karton 40×20×20 → chargeable 2,6 kg (aturan Shopee)."""
    raw = pd.DataFrame(
        {
            "No. Pesanan": ["V1"],
            "Waktu Pesanan Dibuat": ["2026-10-01 10:00"],
            "Nama Produk": ["Closet"],
            "Nomor Referensi SKU": ["FSA0089"],
            "Jumlah": [1],
            "Harga Setelah Diskon": [500_000],
            "Status Pesanan": ["Selesai"],
            "Provinsi": ["DKI JAKARTA"],
            "Kota/Kabupaten": ["KOTA JAKARTA SELATAN"],
            "Perkiraan Ongkos Kirim": [26_666.666666666668],
            "Total Berat": [1300],  # 1,3 kg
        }
    )
    cartons = pd.DataFrame(
        {
            "sku": ["FSA0089"],
            "varian": [""],
            "panjang_cm": [40],
            "lebar_cm": [20],
            "tinggi_cm": [20],
            "isi_per_karton": [1],
        }
    )
    lines = OA.order_shipping_lines(raw, cartons=cartons)
    vol = 40 * 20 * 20 / 6000
    assert abs(lines.iloc[0]["actual_kg"] - 1.3) < 1e-9
    assert abs(lines.iloc[0]["volumetric_kg"] - vol) < 1e-9
    assert abs(lines.iloc[0]["chargeable_kg"] - vol) < 1e-9
    assert abs(lines.iloc[0]["rate_per_kg"] - 10_000) < 1e-6


def test_fallback_without_weight_keeps_fee_median():
    raw = pd.DataFrame(
        {
            "No. Pesanan": ["A", "B", "C"],
            "Waktu Pesanan Dibuat": ["2026-10-01 10:00"] * 3,
            "Nama Produk": ["Cat"] * 3,
            "Jumlah": [1, 1, 1],
            "Harga Setelah Diskon": [50_000] * 3,
            "Status Pesanan": ["Selesai"] * 3,
            "Provinsi": ["BANTEN"] * 3,
            "Kota/Kabupaten": ["KAB. TANGERANG"] * 3,
            "Perkiraan Ongkos Kirim": [100_000, 120_000, 80_000],
        }
    )
    by_city = OA.order_shipping_by_city(raw)
    assert by_city.iloc[0]["Metode"] == "ongkir_saja"
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
            "Berat dikenakan median (kg)": [10.0, 20.0],
            "Rp per kg median": [10_000.0, 10_000.0],
            "Metode": ["berat_dikenakan", "berat_dikenakan"],
        }
    )
    out = OA.build_suggestions(template, shipping)
    by_area = out.set_index("Area")
    assert by_area.loc["KAB. TANGERANG", "Status"] == "Tetap (sudah diisi)"
    assert by_area.loc["KAB. TANGERANG", "Ongkir usulan"] == 207_000
    assert by_area.loc["KOTA JAKARTA BARAT", "Status"] == "Saran dari transaksi"
    assert by_area.loc["KOTA JAKARTA BARAT", "Saran ongkir"] == 230_000
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
    shipping = pd.DataFrame(
        {
            "area_key": ["KOTA SERANG", "KOTA CILEGON"],
            "Ongkir median": [100_000.0, 200_000.0],
            "Invoice": [3, 1],
            "Metode": ["ongkir_saja", "ongkir_saja"],
        }
    )
    suggestions = OA.build_suggestions(template, shipping)
    exported = OA.export_area_excel(suggestions, template_source=raw_bytes)
    wb = openpyxl.load_workbook(BytesIO(exported), data_only=True)
    ws = wb.active
    assert ws["C2"].value == 207000
    assert ws["C3"].value == 115000
    assert ws["C4"].value == 230000


def test_default_template_parses_and_keeps_user_fills():
    assert OA.DEFAULT_TEMPLATE.is_file()
    template = OA.parse_area_template(OA.DEFAULT_TEMPLATE)
    assert len(template) >= 400
    assert template["Ongkir terisi"].notna().sum() == 13
    shipping = pd.DataFrame(
        {
            "area_key": [OA.normalize_area_key("KOTA TANGERANG")],
            "Ongkir median": [1.0],
            "Invoice": [1],
            "Metode": ["ongkir_saja"],
        }
    )
    out = OA.build_suggestions(template, shipping)
    row = out.loc[out["area_key"] == "KOTA TANGERANG"].iloc[0]
    assert row["Status"] == "Tetap (sudah diisi)"
    assert int(row["Ongkir usulan"]) == 143_000
