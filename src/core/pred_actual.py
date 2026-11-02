"""Prediksi vs aktual harian per SKU (Revisi Final 4B).

  pct = aktual_qty / pred_qty
  Melebihi > 105%, Tercapai 95–105%, Hampir 80–95%, Tidak < 80%  (pred 0 & aktual > 0 → Melebihi)
  Penyebab: stok D = 0 → "Stok kosong"; stok < pred → "Stok tinggal N"; biaya iklan D < 50% rata-rata 7 hari
            → "Iklan turun"; harga D > rata-rata 7 hari + 5% → "Harga naik"; selain itu "—"
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

STATUS_ORDER = ("Melebihi", "Tercapai", "Hampir", "Tidak")


def achievement_status(actual: float, pred: float) -> str:
    if pred <= 0:
        return "Melebihi" if actual > 0 else "Tercapai"
    pct = actual / pred
    if pct > 1.05:
        return "Melebihi"
    if pct >= 0.95:
        return "Tercapai"
    if pct >= 0.80:
        return "Hampir"
    return "Tidak"


def cause(*, stock: float | None, pred: float, ad_cost_day: float | None, ad_cost_avg7: float | None, price_day: float | None, price_avg7: float | None) -> str:
    if stock is not None and np.isfinite(stock):
        if stock <= 0:
            return "Stok kosong"
        if stock < pred:
            return f"Stok tinggal {int(stock)}"
    if ad_cost_day is not None and ad_cost_avg7 and ad_cost_avg7 > 0 and ad_cost_day < 0.5 * ad_cost_avg7:
        return "Iklan turun"
    if price_day is not None and price_avg7 and price_avg7 > 0 and price_day > price_avg7 * 1.05:
        return "Harga naik"
    return "—"


def pick_snapshot(runs: pd.DataFrame, actual_day: date) -> int | None:
    """Run terakhir yang dibuat SEBELUM tanggal aktual D (created_at < D)."""
    if runs is None or runs.empty:
        return None
    stamps = pd.to_datetime(runs["run_at"], errors="coerce")
    eligible = runs.loc[stamps < pd.Timestamp(actual_day)]
    if eligible.empty:
        return None
    return int(eligible.loc[pd.to_datetime(eligible["run_at"]).idxmax(), "id"])


def daily_comparison(
    snapshot: pd.DataFrame,
    lines: pd.DataFrame,
    day: date,
    *,
    stock_by_sku: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Baris per SKU untuk tanggal D: prediksi (snapshot) vs aktual bersih (QTY & omzet)."""
    columns = ["sku", "varian", "pred_qty", "pred_sales", "aktual_qty", "aktual_sales", "pct", "status", "penyebab"]
    if snapshot is None or snapshot.empty:
        return pd.DataFrame(columns=columns)
    snap = snapshot.copy()
    snap["tanggal"] = pd.to_datetime(snap["tanggal"], errors="coerce").dt.date
    snap = snap.loc[snap["tanggal"] == day]
    if snap.empty:
        return pd.DataFrame(columns=columns)
    actual = pd.DataFrame(columns=["sku", "aktual_qty", "aktual_sales", "harga"])
    price7 = {}
    if lines is not None and not lines.empty:
        times = pd.to_datetime(lines["order_time"], errors="coerce").dt.date
        today_lines = lines.loc[times == day]
        actual = today_lines.groupby(today_lines["sku"].astype(str)).agg(aktual_qty=("qty", "sum"), aktual_sales=("sales", "sum")).reset_index()
        actual["harga"] = actual["aktual_sales"] / actual["aktual_qty"].replace(0, np.nan)
        week = lines.loc[(times < day) & (times >= day - timedelta(days=7))]
        if not week.empty:
            grouped = week.groupby(week["sku"].astype(str)).agg(q=("qty", "sum"), s=("sales", "sum"))
            price7 = (grouped["s"] / grouped["q"].replace(0, np.nan)).to_dict()
    merged = snap.groupby(snap["sku"].astype(str)).agg(varian=("varian", "first"), pred_qty=("pred_qty", "sum"), pred_sales=("pred_sales", "sum")).reset_index()
    merged = merged.merge(actual, on="sku", how="left")
    merged[["aktual_qty", "aktual_sales"]] = merged[["aktual_qty", "aktual_sales"]].fillna(0.0)
    stock_by_sku = stock_by_sku or {}
    merged["pct"] = np.where(merged["pred_qty"] > 0, merged["aktual_qty"] / merged["pred_qty"].replace(0, np.nan) * 100, np.nan)
    merged["status"] = [achievement_status(a, p) for a, p in zip(merged["aktual_qty"], merged["pred_qty"])]
    merged["penyebab"] = [
        cause(
            stock=stock_by_sku.get(sku),
            pred=p,
            ad_cost_day=None,
            ad_cost_avg7=None,
            price_day=h if pd.notna(h) else None,
            price_avg7=price7.get(sku),
        )
        if status in {"Hampir", "Tidak"}
        else "—"
        for sku, p, h, status in zip(merged["sku"], merged["pred_qty"], merged.get("harga", pd.Series(np.nan, index=merged.index)), merged["status"])
    ]
    return merged[columns]


def lost_sales_from_stock(rows: pd.DataFrame) -> float:
    """Potensi omzet hilang = Σ max(0, pred_sales − aktual_sales) untuk SKU stok kosong."""
    if rows is None or rows.empty:
        return 0.0
    mask = rows["penyebab"].astype(str).str.startswith("Stok")
    gap = (rows.loc[mask, "pred_sales"] - rows.loc[mask, "aktual_sales"]).clip(lower=0)
    return float(gap.sum())
