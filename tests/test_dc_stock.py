"""Stok Site 10062 (DC Cikupa) & 10036 (DC Cipeucang) sebagai sumber pengisian Site 10037."""

from __future__ import annotations

import io
import tempfile
from datetime import date

import pandas as pd

from src.core.dc_stock import attach_dc_stock, latest_site_stock, site_codes_in, transfer_plan, transfer_text
from src.core.decision_table import build_decision_table
from src.core.restock import recommendation_records, records_display
from src.core.schemas import SOURCE_SPECS, canonicalize_frame, validation_report
from src.core.storage import LocalDataStore, read_upload_file


def _erp_report(site: str, name: str, rows: list[tuple[str, int, str]]) -> bytes:
    """Bentuk laporan "Stock Qty and Value": 3 baris judul, lalu header di baris ke-4."""
    header = ["Store Code", "Store Name", "Item No", "Item Name", "Type", "Quantity", "Blocked", "UoM"]
    body = [[site, name, item, f"Item {item}", "RETAIL", qty, blocked, "PCS"] for item, qty, blocked in rows]
    preamble = [["UserID: MITRA10HO\\user"] + [None] * 7, ["Stock Qty and Value"] + [None] * 7, [f"Site: {site} - {name}"] + [None] * 7]
    frame = pd.DataFrame(preamble + [header] + body)
    buffer = io.BytesIO()
    frame.to_excel(buffer, index=False, header=False)
    return buffer.getvalue()


def test_baca_laporan_erp_dan_sku_tanpa_nol_depan():
    spec = SOURCE_SPECS["stock_10062"]
    raw = read_upload_file(_erp_report("10062", "DC CIKUPA", [("0200019936", 30, "No"), ("0040030033", 5, "Yes")]), "ckp.xlsx", spec)
    assert validation_report(raw, spec)["status"] == "Siap"
    frame, _ = canonicalize_frame(raw, spec)
    assert site_codes_in(frame) == ["10062"]
    stock = latest_site_stock(frame).set_index("sku")["qty"].to_dict()
    assert stock == {"200019936": 30.0, "40030033": 0.0}  # Blocked = Yes tidak dihitung


def test_urutan_ambil_10062_lalu_10036_lalu_po():
    take, rest = transfer_plan(50, {"10062": 30, "10036": 10})
    assert take == {"10062": 30, "10036": 10} and rest == 10
    assert transfer_text(50, take, rest, True) == "Ambil 30 dari Site 10062 + 10 dari Site 10036 · kurang 10 → PO supplier"
    take, rest = transfer_plan(8, {"10062": 0, "10036": 20})
    assert take == {"10036": 8} and rest == 0
    take, rest = transfer_plan(5, {"10062": 0, "10036": 0})
    assert transfer_text(5, take, rest, True).startswith("Stok Site 10062 & 10036 kosong")
    assert transfer_text(5, {}, 5, False) == "Unggah stok Site 10062/10036"


def test_tabel_keputusan_dan_record_restock_memuat_ambil_dari_dc():
    view = pd.DataFrame(
        {
            "item_key": ["A", "B"],
            "sku": ["200019936", "40030033"],
            "product_name": ["Kloset", "Keran"],
            "pred_qty": [300.0, 30.0],
            "pred_sales": [3_000_000.0, 300_000.0],
            "safety_stock": [20.0, 5.0],
        }
    )
    shopee = pd.DataFrame({"sku": ["200019936", "40030033"], "stock_dc_cikupa": [10, 100]})
    dc = {
        "stock_10062": pd.DataFrame({"sku": ["200019936"], "qty": [200], "blocked": ["No"]}),
        "stock_10036": pd.DataFrame({"sku": ["200019936"], "qty": [500], "blocked": ["No"]}),
    }
    table = build_decision_table(view, period="bulan", today=date(2026, 11, 7), horizon_days=30, stock_frame=shopee, dc_frames=dc)
    row = table.set_index("sku").loc["200019936"]
    shortfall = row["m_butuh"] - 10
    assert row["stok_10062"] == 200 and row["stok_10036"] == 500
    assert row["ambil_10062"] == 200 and row["ambil_10036"] == shortfall - 200
    assert row["sumber_restock"].startswith("Ambil 200 dari Site 10062 + ")
    assert table.set_index("sku").loc["40030033", "sumber_restock"] == ""  # stok cukup
    records = records_display(recommendation_records(table, date(2026, 11, 7)))
    assert "Ambil dari DC" in records.columns and "Stok Site 10037" in records.columns


def test_tanpa_file_dc_kolom_kosong():
    out = attach_dc_stock(pd.DataFrame({"sku": ["1"]}), None)
    assert out["stok_10062"].isna().all() and not bool(out["ada_data_10062"].iat[0])


def test_snapshot_dc_disimpan_maksimal_empat():
    with tempfile.TemporaryDirectory() as root:
        store = LocalDataStore(root)
        for day in range(1, 7):
            frame = pd.DataFrame({"Item No": ["0200019936"], "Quantity": [day], "Store Code": ["10036"]})
            store.submit_source("stock_10036", frame, submitted_at=f"2026-11-0{day}T08:00:00")
        stored = store.read_source("stock_10036")
        assert stored["_submitted_at"].nunique() == 4
        assert latest_site_stock(stored)["qty"].tolist() == [6.0]
