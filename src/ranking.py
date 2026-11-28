from __future__ import annotations

import numpy as np
import pandas as pd

from src.aggregate import period_label


def unique_rank(frame: pd.DataFrame, primary: str, tie_breaks: list[str]) -> pd.DataFrame:
    """Peringkat 1..n tanpa angka kembar. Seri dipecah dari kolom cadangan, lalu item_key."""
    if frame is None or frame.empty:
        out = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
        if "peringkat" not in out.columns:
            out["peringkat"] = pd.Series(dtype=int)
        return out
    missing = [col for col in [primary, *tie_breaks, "item_key"] if col not in frame.columns]
    if missing:
        out = frame.copy()
        out["peringkat"] = np.arange(1, len(out) + 1)
        return out
    ordered = frame.sort_values(
        [primary, *tie_breaks, "item_key"],
        ascending=[False, *([False] * len(tie_breaks)), True],
        kind="mergesort",
    ).copy()
    ordered["peringkat"] = np.arange(1, len(ordered) + 1)
    return ordered


def rank_from_orders(orders: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Peringkat terlaris dari seluruh baris laporan, bukan hanya periode terakhir.

    Urutan utama adalah qty atau omzet tertinggi. Jika nilainya sama, pemecah seri
    memakai metrik satunya, jumlah pesanan, lalu waktu pesanan terbaru.
    """
    if orders.empty:
        return pd.DataFrame()
    stats = orders.groupby("item_key", as_index=False).agg(
        item_label=("item_label", "first"),
        product_name=("product_name", "first"),
        variation=("variation", "first"),
        sku=("sku", "first"),
        qty_total=("qty", "sum"),
        sales_total=("sales", "sum"),
        n_orders=("order_id", "nunique"),
        last_order=("order_time", "max"),
    )
    primary = "qty_total" if metric == "qty" else "sales_total"
    secondary = "sales_total" if metric == "qty" else "qty_total"
    return unique_rank(stats, primary, [secondary, "n_orders", "last_order"])


def historical_bestsellers(history: pd.DataFrame, period: str, period_start, top_n: int = 10) -> pd.DataFrame:
    empty = pd.DataFrame(
        columns=["item_key", "item_label", "qty", "sales", "peringkat", "rank_qty", "rank_sales", "period_label"]
    )
    if history is None or history.empty or "period_start" not in history.columns:
        return empty
    subset = history[history["period_start"] == period_start].copy()
    if subset.empty:
        return empty
    by_qty = unique_rank(subset, "qty", ["sales"])
    by_sales = unique_rank(subset, "sales", ["qty"])[["item_key", "peringkat"]].rename(
        columns={"peringkat": "rank_sales"}
    )
    by_qty = by_qty.merge(by_sales, on="item_key", how="left")
    by_qty["rank_qty"] = by_qty["peringkat"]
    by_qty["period_label"] = period_label(period_start, period)
    return by_qty.sort_values("rank_qty").head(top_n)


def combine_forecasts(qty_fc: pd.DataFrame, sales_fc: pd.DataFrame) -> pd.DataFrame:
    empty = pd.DataFrame(
        columns=[
            "item_key",
            "item_label",
            "pred_qty",
            "pred_sales",
            "model_qty",
            "model_sales",
            "mape_qty",
            "mape_sales",
            "mae_qty",
            "mae_sales",
            "rmse_qty",
            "rmse_sales",
            "rank_qty",
            "rank_sales",
            "rank_komposit",
            "skor_komposit",
            "next_period",
            "error_sigma",
            "history_points",
            "horizon_steps",
        ]
    )
    qty_empty = qty_fc is None or qty_fc.empty
    sales_empty = sales_fc is None or sales_fc.empty
    if qty_empty and sales_empty:
        return empty
    qty = (qty_fc if not qty_empty else pd.DataFrame()).rename(
        columns={
            "forecast": "pred_qty",
            "best_model": "model_qty",
            "mape": "mape_qty",
            "mae": "mae_qty",
            "rmse": "rmse_qty",
        }
    )
    sales = (sales_fc if not sales_empty else pd.DataFrame()).rename(
        columns={
            "forecast": "pred_sales",
            "best_model": "model_sales",
            "mape": "mape_sales",
            "mae": "mae_sales",
            "rmse": "rmse_sales",
        }
    )
    sales_cols = [c for c in ("item_key", "pred_sales", "model_sales", "mape_sales", "mae_sales", "rmse_sales") if c in sales.columns]
    if qty.empty:
        merged = sales.copy()
        if "pred_qty" not in merged.columns:
            merged["pred_qty"] = 0.0
    elif not sales_cols or "item_key" not in sales_cols:
        merged = qty.copy()
        if "pred_sales" not in merged.columns:
            merged["pred_sales"] = 0.0
    else:
        merged = qty.merge(sales[sales_cols], on="item_key", how="outer")
    if merged.empty:
        return empty
    merged["pred_qty"] = merged["pred_qty"].fillna(0.0) if "pred_qty" in merged.columns else 0.0
    merged["pred_sales"] = merged["pred_sales"].fillna(0.0) if "pred_sales" in merged.columns else 0.0
    if "item_key" not in merged.columns:
        return empty
    by_qty = unique_rank(merged, "pred_qty", ["pred_sales"])[["item_key", "peringkat"]].rename(
        columns={"peringkat": "rank_qty"}
    )
    by_sales = unique_rank(merged, "pred_sales", ["pred_qty"])[["item_key", "peringkat"]].rename(
        columns={"peringkat": "rank_sales"}
    )
    merged = merged.drop(columns=[col for col in ("rank_qty", "rank_sales", "peringkat") if col in merged.columns])
    merged = merged.merge(by_qty, on="item_key", how="left").merge(by_sales, on="item_key", how="left")
    qty_norm = _minmax(merged["pred_qty"])
    sales_norm = _minmax(merged["pred_sales"])
    merged["skor_komposit"] = 0.5 * qty_norm + 0.5 * sales_norm
    by_score = unique_rank(merged, "skor_komposit", ["pred_sales", "pred_qty"])[["item_key", "peringkat"]].rename(
        columns={"peringkat": "rank_komposit"}
    )
    merged = merged.drop(columns=["peringkat"], errors="ignore").merge(by_score, on="item_key", how="left")
    fallback_period = ""
    if not sales_empty and "next_period" in sales_fc.columns and not sales_fc.empty:
        fallback_period = sales_fc["next_period"].iloc[0]
    elif "next_period" in merged.columns and merged["next_period"].notna().any():
        fallback_period = merged["next_period"].dropna().iloc[0]
    if "next_period" in merged.columns:
        merged["next_period"] = merged["next_period"].fillna(fallback_period)
    else:
        merged["next_period"] = fallback_period
    return merged.sort_values(["rank_komposit", "rank_sales", "rank_qty"])


def model_leaderboard(qty_fc: pd.DataFrame, sales_fc: pd.DataFrame) -> pd.DataFrame:
    """Ringkas MAPE/RMSE per model. Kosongkan jika metrik masih nol palsu (tanpa holdout)."""
    frames = []
    for metric, frame, col in (
        ("qty", qty_fc, "best_model"),
        ("sales", sales_fc, "best_model"),
    ):
        if frame is None or frame.empty or "mape" not in frame.columns:
            continue
        # Omzet = qty × harga; jangan tampilkan leaderboard sales dengan MAPE 0 palsu.
        if metric == "sales" and float(frame["mape"].fillna(0).sum()) <= 0:
            continue
        if metric == "qty" and float(frame["mape"].fillna(0).abs().sum()) <= 0 and float(frame["rmse"].fillna(0).sum()) <= 0:
            continue
        summary = (
            frame.groupby(col, as_index=False)
            .agg(jumlah_sku=("item_key", "nunique"), mape_rata=("mape", "mean"), rmse_rata=("rmse", "mean"))
            .assign(metrik=metric)
            .rename(columns={col: "model"})
        )
        frames.append(summary)
    if not frames:
        return pd.DataFrame()
    board = pd.concat(frames, ignore_index=True)
    return board.sort_values(["metrik", "mape_rata"])


def _minmax(series: pd.Series) -> pd.Series:
    if series is None or len(series) == 0:
        return pd.Series(dtype=float)
    lo, hi = series.min(), series.max()
    if pd.isna(lo) or pd.isna(hi) or hi == lo:
        return pd.Series([1.0] * len(series), index=series.index)
    return (series - lo) / (hi - lo)
