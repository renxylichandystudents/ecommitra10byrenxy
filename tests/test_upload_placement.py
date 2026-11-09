"""Satu tempat unggah stok/margin (Upload data), format replenishment DC, dan template target dari Januari."""

from __future__ import annotations

from datetime import date

import pandas as pd

from auth.permissions import can
from src.core import gudang
from src.core import targets as T
from src.core.access import ECOMMERCE_SPECIALIST, SUPER_USER, TEAM_DC, TEAM_ICMD
from src.core.dc_stock import latest_site_stock, site_codes_in
from src.core.schemas import SOURCE_SPECS, canonicalize_frame, find_columns


def _repl_report(site: str) -> pd.DataFrame:
    return pd.DataFrame({
        "Site No": [site, site],
        "Site Name": ["DC", "DC"],
        "Item No": ["300002038", "100024295"],
        "Item Name": ["Semen", "Keramik"],
        "Stock On Hand": [120, 45],
        "Minimum Stock": [10, 10],
        "Outstanding PO": [0, 5],
        "Quantity PO": [0, 0],
    })


def test_laporan_replenishment_dc_dibaca_dari_stock_on_hand():
    spec = SOURCE_SPECS["stock_10062"]
    frame = _repl_report("10062")
    mapping = find_columns(frame.columns, spec)
    assert mapping["qty"] == "Stock On Hand"
    assert mapping["store_code"] == "Site No"
    canonical, _ = canonicalize_frame(frame, spec)
    assert site_codes_in(canonical) == ["10062"]
    stock = latest_site_stock(canonical).set_index("sku")["qty"]
    assert stock.to_dict() == {"300002038": 120.0, "100024295": 45.0}


def test_unggahan_lama_qty_dari_quantity_po_dipulihkan_dari_stock_on_hand():
    stored = _repl_report("10036").assign(qty=0, sku=lambda f: f["Item No"], _submitted_at="2026-11-09T19:07:00")
    stock = latest_site_stock(stored).set_index("sku")["qty"]
    assert stock.sum() == 165.0


def test_replenishment_mencatat_site_di_file():
    header = ["Site No", "Item No", "Item Name", "Stock On Hand", "Minimum Stock", "Maximum Stock"]
    raw = pd.DataFrame([["Replenishment Calculation by Date"] + [None] * 5, header, ["10062", "300002038", "Semen", 5, 1, 9]])
    repl, _ = gudang.parse_replenishment(raw)
    assert repl.attrs["sites"] == ["10062"]
    assert "site" not in repl.columns


def test_unggah_stok_untuk_team_dc_tanpa_buka_data_latih():
    assert can(TEAM_DC, "unggah_stok") and not can(TEAM_DC, "ubah_data_latih")
    assert can(SUPER_USER, "unggah_stok") and can(ECOMMERCE_SPECIALIST, "unggah_stok")
    assert not can(TEAM_ICMD, "unggah_stok")


def test_template_target_mulai_januari_dan_berisi_target_tersimpan():
    frame = T.template_frame(date(2026, 11, 9), {"2026-11": 5e9, "2025-12": 1e9})
    assert frame["Bulan"].iloc[0] == "2025-12"
    assert "2026-01" in frame["Bulan"].tolist() and frame["Bulan"].iloc[-1] == "2027-12"
    by_month = dict(zip(frame["Bulan"], frame["Target (Rp)"]))
    assert by_month["2026-11"] == 5e9
    assert pd.isna(by_month["2026-03"])


def test_baris_target_kosong_dilewati():
    raw = pd.DataFrame({"Bulan": ["2026-01", "2026-02", "2026-03"], "Target (Rp)": [None, "2.000.000.000", ""]})
    out = T.parse_target_file(raw)
    assert out["periode"].tolist() == ["2026-02"]
