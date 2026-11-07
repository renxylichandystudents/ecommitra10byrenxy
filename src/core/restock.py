"""Rekomendasi ber-SKU dan tabel restock prioritas (Revisi Final 2C & 4A).

  restock    = max(0, prediksi_window + SS − stok Site 10037)
  ambil dari DC = restock dipenuhi dulu dari Site 10062 (DC Cikupa), lalu Site 10036 (DC Cipeucang); sisanya PO supplier
  stok_habis = hari_ini + floor(stok_dc / prediksi_harian)   (prediksi harian 0 → tidak habis)
  status     = Kosong bila stok 0; Kurang bila stok < prediksi + SS; selain itu Aman
  pic        = restock lokal → Team DC; ada PO impor terbuka → Team IC/MD; harga/iklan → E-commerce
  prioritas  = 1: stok habis ≤ 3 hari atau Kosong; 2: margin minus / batal tinggi; 3: lainnya
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.core.decision_table import stock_need

RECORD_COLUMNS = ("prioritas", "tindakan", "sku", "nama", "varian", "stok", "kebutuhan", "restock", "ambil_dc", "tenggat", "pic", "alasan")
CANCEL_HIGH_PCT = 15.0


def _dc(row, code: str):
    value = row.get(f"stok_{code}")
    return None if value is None or pd.isna(value) else float(value)


def _num(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def stock_out_date(stok: float, daily: float, today: date) -> date | None:
    if daily <= 0:
        return None
    return today + timedelta(days=int(math.floor(max(stok, 0.0) / daily)))


def open_po_map(import_po: pd.DataFrame | None) -> dict[str, dict]:
    """PO impor terbuka per SKU: {sku: {"no_po", "qty", "eta"}} (status selain Diterima DC)."""
    if import_po is None or import_po.empty:
        return {}
    work = import_po.loc[import_po["status"].astype(str) != "Diterima DC"].copy()
    if work.empty:
        return {}
    work["eta"] = pd.to_datetime(work["eta_terbaru"].fillna(work.get("eta_rencana")), errors="coerce").dt.date
    out = {}
    for sku, part in work.sort_values("eta").groupby(work["sku"].astype(str)):
        first = part.iloc[0]
        out[sku] = {"no_po": str(first["no_po"]), "qty": float(part["qty"].sum()), "eta": first["eta"]}
    return out


def restock_priority(table: pd.DataFrame, today: date, *, po: dict[str, dict] | None = None) -> pd.DataFrame:
    """Tabel "Kebutuhan restock prioritas". Urut stok habis naik, lalu restock turun."""
    columns = ["Rank", "sku", "Produk", "Varian", "Stok Site 10037", "Prediksi", "SS", "Restock", "Stok Site 10062", "Stok Site 10036", "Ambil dari DC", "Stok habis", "Status", "Inbound", "_habis", "_pred_harian", "_sales_harian"]
    if table is None or table.empty:
        return pd.DataFrame(columns=columns)
    po = po or {}
    rows = []
    for _, row in table.iterrows():
        known = bool(row.get("ada_data_stok", False))
        if not known:
            continue
        stok = _num(row.get("stok"))
        pred = _num(row.get("m_qty"))
        ss = _num(row.get("ss"))
        daily = _num(row.get("pred_harian"))
        need = stock_need(row)
        restock = max(0.0, math.ceil(need - stok))
        habis = stock_out_date(stok, daily, today)
        if stok <= 0:
            status = "Kosong"
        elif stok < need:
            status = "Kurang"
        else:
            status = "Aman"
        inbound = po.get(str(row.get("sku")))
        rows.append(
            {
                "Rank": row.get("peringkat"),
                "sku": str(row.get("sku", "")),
                "Produk": str(row.get("product_name", "")),
                "Varian": str(row.get("variasi_tampil", "") or ""),
                "Stok Site 10037": stok,
                "Prediksi": pred,
                "SS": ss,
                "Restock": restock,
                "Stok Site 10062": _dc(row, "10062"),
                "Stok Site 10036": _dc(row, "10036"),
                "Ambil dari DC": str(row.get("sumber_restock", "") or ""),
                "Stok habis": habis,
                "Status": status,
                "Inbound": f"{inbound['no_po']} · {inbound['eta'].strftime('%d/%m/%Y') if inbound.get('eta') else 'ETA belum ada'}" if inbound else "",
                "_habis": habis or date.max,
                "_pred_harian": daily,
                "_sales_harian": daily * _num(row.get("harga_bersih")),
            }
        )
    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        return frame
    # Prioritas untuk user: Kosong → Kurang → Aman → tanpa data; lalu stok habis paling cepat, lalu restock terbesar.
    order = {"Kosong": 0, "Kurang": 1, "Aman": 2}
    frame["_prioritas"] = frame["Status"].map(lambda s: order.get(str(s).split(" · ")[0], 3))
    return frame.sort_values(["_prioritas", "_habis", "Restock"], ascending=[True, True, False]).drop(columns="_prioritas").reset_index(drop=True)


def recommendation_records(
    table: pd.DataFrame,
    today: date,
    *,
    po: dict[str, dict] | None = None,
    margin_pct: dict[str, float] | None = None,
    advice: dict[str, str] | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """Rekomendasi = record terstruktur ber-SKU; Laporan & unduhan dibaca dari record yang sama."""
    if table is None or table.empty:
        return pd.DataFrame(columns=list(RECORD_COLUMNS))
    po = po or {}
    margin_pct = margin_pct or {}
    advice = advice or {}
    out = []
    for _, row in table.iterrows():
        sku = str(row.get("sku", ""))
        known = bool(row.get("ada_data_stok", False))
        stok = _num(row.get("stok")) if known else None
        need = stock_need(row)
        daily = _num(row.get("pred_harian"))
        restock = max(0.0, math.ceil(need - stok)) if known else None
        habis = stock_out_date(stok, daily, today) if known else None
        tenggat = "Segera" if known and (stok <= 0 or (habis is not None and habis <= today)) else (habis.strftime("%d/%m/%Y") if habis else "-")
        margin = margin_pct.get(sku)
        cancel = _num(row.get("batal_pct"))
        reasons = []
        if known and (stok <= 0 or (habis is not None and (habis - today).days <= 3)):
            prioritas = 1
            reasons.append("stok habis ≤ 3 hari" if stok > 0 else "stok kosong")
        elif (margin is not None and np.isfinite(margin) and margin < 0) or cancel > CANCEL_HIGH_PCT:
            prioritas = 2
        else:
            prioritas = 3
        if margin is not None and np.isfinite(margin) and margin < 0:
            reasons.append(f"margin minus {margin:.1f}%".replace(".", ","))
        if cancel > CANCEL_HIGH_PCT:
            reasons.append(f"batal {cancel:.0f}%")
        if restock and restock > 0:
            tindakan = "Restock"
            pic = "Team IC/MD" if sku in po else "Team DC"
            if sku in po:
                reasons.append(f"PO {po[sku]['no_po']} terbuka")
        elif margin is not None and np.isfinite(margin) and margin < 0:
            tindakan, pic = "Tinjau harga", "E-commerce"
        elif cancel > CANCEL_HIGH_PCT:
            tindakan, pic = "Kejar bayar / cek batal", "E-commerce"
        else:
            tindakan, pic = "Optimasi iklan & listing", "E-commerce"
        if sku in advice:
            reasons.append(advice[sku])
        out.append(
            {
                "prioritas": prioritas,
                "tindakan": tindakan,
                "sku": sku,
                "nama": str(row.get("product_name", "")),
                "varian": str(row.get("variasi_tampil", "") or ""),
                "stok": stok,
                "kebutuhan": math.ceil(need),
                "restock": restock,
                "ambil_dc": str(row.get("sumber_restock", "") or "") if restock else "",
                "tenggat": tenggat,
                "pic": pic,
                "alasan": "; ".join(reasons) if reasons else "-",
            }
        )
    frame = pd.DataFrame(out, columns=list(RECORD_COLUMNS))
    frame = frame.sort_values(["prioritas", "restock"], ascending=[True, False], na_position="last").reset_index(drop=True)
    return frame.head(limit) if limit else frame


PRIORITY_WORDS = {1: "1 · Mendesak", 2: "2 · Penting", 3: "3 · Biasa"}


def records_display(records: pd.DataFrame) -> pd.DataFrame:
    """Kolom tampilan + nomor urut (prioritas 1–3 adalah tingkat, urutan di dalamnya = restock terbesar)."""
    records = records.copy()
    if "prioritas" in records.columns:
        records["prioritas"] = records["prioritas"].map(lambda v: PRIORITY_WORDS.get(int(v), v) if pd.notna(v) else v)
    records.insert(0, "No", range(1, len(records) + 1))
    return records.rename(
        columns={
            "prioritas": "Prioritas",
            "tindakan": "Tindakan",
            "sku": "SKU",
            "nama": "Produk",
            "varian": "Varian",
            "stok": "Stok Site 10037",
            "kebutuhan": "Kebutuhan",
            "restock": "Restock",
            "ambil_dc": "Ambil dari DC",
            "tenggat": "Tenggat",
            "pic": "PIC",
            "alasan": "Alasan",
        }
    )
