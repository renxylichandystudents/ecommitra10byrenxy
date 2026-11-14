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
from collections.abc import Callable
from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.core.dc_stock import dc_take_label
from src.core.decision_table import MAX_COVER_DAYS, stock_need

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


def _day(value) -> date | None:
    if value is None or (not isinstance(value, date) and pd.isna(value)):
        return None
    stamp = pd.Timestamp(value)
    return stamp.date() if pd.notna(stamp) else None


def stock_out_date(stok: float, daily: float, today: date) -> date | None:
    if daily <= 0:
        return None
    days = math.floor(max(stok, 0.0) / daily)
    return today + timedelta(days=int(days)) if days <= MAX_COVER_DAYS else None


def empty_loss(since: date | None, today: date, daily_qty: float, price: float, *, day_weight: Callable[[date], float] | None = None,
               sold_qty: float = 0.0, sold_sales: float = 0.0, month_first: date | None = None,
               sold_month: tuple[float, float] = (0.0, 0.0)) -> dict:
    """Penjualan yang hilang selama stok kosong: hari `since` s.d. kemarin (hari ini masih berjalan).

    Permintaan tiap hari = laju prediksi harian × pola hari (sama dengan Pantauan harian); hilang = permintaan − terjual
    pada hari-hari itu (minimal 0). `month_first` memberi bagian yang jatuh di bulan berjalan (relevan untuk target)."""
    out = {"hari": 0, "qty": 0.0, "sales": 0.0, "qty_bulan": 0.0, "sales_bulan": 0.0}
    end = today - timedelta(days=1)
    if since is None or since > end or daily_qty <= 0:
        return out
    days = [since + timedelta(days=i) for i in range((end - since).days + 1)]
    weights = [float(day_weight(d)) if day_weight else 1.0 for d in days]
    demand = daily_qty * sum(weights)
    out["hari"] = len(days)
    out["qty"] = max(demand - max(sold_qty, 0.0), 0.0)
    out["sales"] = max(demand * price - max(sold_sales, 0.0), 0.0)
    if month_first is not None:
        month_demand = daily_qty * sum(w for d, w in zip(days, weights) if d >= month_first)
        out["qty_bulan"] = max(month_demand - max(sold_month[0], 0.0), 0.0)
        out["sales_bulan"] = max(month_demand * price - max(sold_month[1], 0.0), 0.0)
    return out


def _sold_since(orders: pd.DataFrame | None) -> pd.DataFrame | None:
    """QTY & sales per (item_key, tanggal) untuk mengurangkan penjualan yang tetap terjadi selama status kosong."""
    if orders is None or orders.empty or "item_key" not in orders.columns:
        return None
    day = pd.to_datetime(orders["order_time"], errors="coerce").dt.date
    sales = orders["sales"] if "sales" in orders.columns else pd.Series(0.0, index=orders.index)
    frame = pd.DataFrame({"item_key": orders["item_key"].astype(str), "day": day, "qty": pd.to_numeric(orders["qty"], errors="coerce").fillna(0.0),
                          "sales": pd.to_numeric(sales, errors="coerce").fillna(0.0)}).dropna(subset=["day"])
    return frame.groupby(["item_key", "day"], as_index=False)[["qty", "sales"]].sum()


def _sold_between(sold: pd.DataFrame | None, key: str, lo: date | None, hi: date) -> tuple[float, float]:
    if sold is None or lo is None or lo > hi:
        return 0.0, 0.0
    part = sold.loc[(sold["item_key"] == key) & (sold["day"] >= lo) & (sold["day"] <= hi)]
    return float(part["qty"].sum()), float(part["sales"].sum())


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


def restock_priority(table: pd.DataFrame, today: date, *, po: dict[str, dict] | None = None, orders: pd.DataFrame | None = None,
                     day_weight: Callable[[date], float] | None = None, through: date | None = None) -> pd.DataFrame:
    """Tabel "Kebutuhan restock prioritas": kosong + ada stok DC dulu, lalu dampak omzet (sales value & QTY) terbesar.

    SKU Kosong juga diberi penjualan yang sudah hilang sejak kosong (`empty_loss`), total dan bagian bulan berjalan,
    dihitung s.d. `through` (hari penuh terakhir data latih; bawaan kemarin)."""
    columns = ["Rank", "sku", "Produk", "Varian", "Stok Site 10037", "Prediksi", "SS", "Restock", "Stok Site 10062", "Stok Site 10036", "Ambil dari DC", "Stok habis", "Status", "Inbound", "Potensi sales hilang", "Potensi QTY hilang",
               "Hari kosong", "QTY hilang sejak kosong", "Sales hilang sejak kosong", "Sales hilang bulan ini", "_habis", "_pred_harian", "_sales_harian",
               "_kosong_sejak", "_lama_kosong", "_kosong_sejak_awal"]
    if table is None or table.empty:
        return pd.DataFrame(columns=columns)
    po = po or {}
    sold = _sold_since(orders)
    month_first = today.replace(day=1)
    yesterday = through or today - timedelta(days=1)
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
        price = _num(row.get("harga_bersih"))
        # Unit prediksi periode yang tidak tertutup stok Site 10037 = penjualan yang hilang bila tidak direstock.
        loss_qty = max(0.0, pred - max(stok, 0.0))
        since = _day(row.get("zero_since")) if status == "Kosong" else None
        key = str(row.get("item_key", row.get("sku", "")))
        lost = None
        if since:
            sold_qty, sold_sales = _sold_between(sold, key, since, yesterday)
            lost = empty_loss(since, yesterday + timedelta(days=1), daily, price, day_weight=day_weight, month_first=month_first, sold_qty=sold_qty, sold_sales=sold_sales,
                              sold_month=_sold_between(sold, key, max(since, month_first), yesterday))
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
                "Ambil dari DC": dc_take_label(row),
                "Stok habis": habis,
                "Status": status,
                "Inbound": f"{inbound['no_po']} · {inbound['eta'].strftime('%d/%m/%Y') if inbound.get('eta') else 'ETA belum ada'}" if inbound else "",
                "Potensi sales hilang": loss_qty * price,
                "Potensi QTY hilang": loss_qty,
                "Hari kosong": lost["hari"] if lost else np.nan,
                "QTY hilang sejak kosong": lost["qty"] if lost else np.nan,
                "Sales hilang sejak kosong": lost["sales"] if lost else np.nan,
                "Sales hilang bulan ini": lost["sales_bulan"] if lost else np.nan,
                "_habis": habis or date.max,
                "_pred_harian": daily,
                "_sales_harian": daily * _num(row.get("harga_bersih")),
                "_kosong_sejak": since,
                "_lama_kosong": _num(row.get("lama_kosong_hari")) if status == "Kosong" and pd.notna(row.get("lama_kosong_hari")) else None,
                "_kosong_sejak_awal": bool(row.get("kosong_sejak_awal", False)) if status == "Kosong" else False,
            }
        )
    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        return frame
    # Prioritas untuk user:
    # 1) Kosong tapi ada stok di Site 10062/10036 (bisa langsung ditransfer), 2) Kosong tanpa stok DC (PO),
    # 3) Kurang dengan stok DC, 4) Kurang tanpa stok DC, 5) Aman.
    # Dalam tiap kelompok: dampak omzet terbesar = rata-rata skor potensi loss sales value dan potensi loss QTY.
    dc_total = frame["Stok Site 10062"].map(_num) + frame["Stok Site 10036"].map(_num)
    has_dc = dc_total.gt(0)
    status = frame["Status"].astype(str).str.split(" · ").str[0]
    base = status.map({"Kosong": 0, "Kurang": 2, "Aman": 4}).fillna(5)
    frame["_prioritas"] = base + ((status != "Aman") & ~has_dc).astype(int)

    def _scale(values: pd.Series) -> pd.Series:
        top = float(values.max()) if len(values) else 0.0
        return values / top if top > 0 else values * 0.0

    # SKU Kosong: dampak = yang akan hilang + yang sudah hilang sejak kosong, jadi Top 50 yang lama kosong naik ke atas.
    sales_impact = frame["Potensi sales hilang"].astype(float) + frame["Sales hilang sejak kosong"].astype(float).fillna(0.0)
    qty_impact = frame["Potensi QTY hilang"].astype(float) + frame["QTY hilang sejak kosong"].astype(float).fillna(0.0)
    frame["_dampak"] = 0.5 * _scale(sales_impact) + 0.5 * _scale(qty_impact)
    frame = frame.sort_values(["_prioritas", "_dampak", "_habis"], ascending=[True, False, True])
    return frame.drop(columns=["_prioritas", "_dampak"]).reset_index(drop=True)


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
                "ambil_dc": dc_take_label(row) if restock else "",
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
