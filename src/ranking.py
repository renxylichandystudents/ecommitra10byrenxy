from __future__ import annotations

import numpy as np
import pandas as pd

from src.aggregate import period_label


def unique_rank(frame: pd.DataFrame, primary: str, tie_breaks: list[str]) -> pd.DataFrame:
    """Peringkat 1..n tanpa angka kembar. Seri dipecah dari kolom cadangan, lalu item_key."""
    ordered = frame.sort_values(
        [primary, *tie_breaks, "item_key"],
        ascending=[False, *([False] * len(tie_breaks)), True],
        kind="mergesort",
    ).copy()
    ordered["peringkat"] = np.arange(1, len(ordered) + 1)
    return ordered


def excluded_item_mask(frame: pd.DataFrame, rules: dict | None = None) -> pd.Series:
    """True untuk SKU jasa/biaya (config `sku_dikecualikan`) yang bukan produk untuk diprediksi."""
    if frame is None or frame.empty:
        return pd.Series(False, index=frame.index if frame is not None else [])
    if rules is None:
        try:
            from src.core.config import default_params

            rules = default_params().get("sku_dikecualikan", {}) or {}
        except Exception:
            rules = {}
    skus = {str(code).strip() for code in rules.get("sku", []) or [] if str(code).strip()}
    words = [str(word).strip().lower() for word in rules.get("kata_kunci_nama", []) or [] if str(word).strip()]
    mask = pd.Series(False, index=frame.index)
    if skus and "sku" in frame.columns:
        mask |= frame["sku"].fillna("").astype(str).str.strip().isin(skus)
    if words and "product_name" in frame.columns:
        names = frame["product_name"].fillna("").astype(str).str.lower()
        for word in words:
            mask |= names.str.contains(word, regex=False)
    return mask


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
    # Audit T3: SKU jasa/biaya (mis. Extra Packing Kayu Tambahan) tidak ikut peringkat.
    stats = stats.loc[~excluded_item_mask(stats)].reset_index(drop=True)
    if stats.empty:
        return pd.DataFrame()
    primary = "qty_total" if metric == "qty" else "sales_total"
    secondary = "sales_total" if metric == "qty" else "qty_total"
    return unique_rank(stats, primary, [secondary, "n_orders", "last_order"])


def historical_bestsellers(history: pd.DataFrame, period: str, period_start, top_n: int = 10) -> pd.DataFrame:
    subset = history[history["period_start"] == period_start].copy()
    if subset.empty:
        return subset
    by_qty = unique_rank(subset, "qty", ["sales"])
    by_sales = unique_rank(subset, "sales", ["qty"])[["item_key", "peringkat"]].rename(
        columns={"peringkat": "rank_sales"}
    )
    by_qty = by_qty.merge(by_sales, on="item_key", how="left")
    by_qty["rank_qty"] = by_qty["peringkat"]
    by_qty["period_label"] = period_label(period_start, period)
    return by_qty.sort_values("rank_qty").head(top_n)


def combine_forecasts(qty_fc: pd.DataFrame, sales_fc: pd.DataFrame) -> pd.DataFrame:
    qty = qty_fc.rename(
        columns={
            "forecast": "pred_qty",
            "best_model": "model_qty",
            "mape": "mape_qty",
            "mae": "mae_qty",
            "rmse": "rmse_qty",
        }
    )
    sales = sales_fc.rename(
        columns={
            "forecast": "pred_sales",
            "best_model": "model_sales",
            "mape": "mape_sales",
            "mae": "mae_sales",
            "rmse": "rmse_sales",
        }
    )
    merged = qty.merge(
        sales[["item_key", "pred_sales", "model_sales", "mape_sales", "mae_sales", "rmse_sales"]],
        on="item_key",
        how="outer",
    )
    merged["pred_qty"] = merged["pred_qty"].fillna(0.0)
    merged["pred_sales"] = merged["pred_sales"].fillna(0.0)
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
    merged["next_period"] = merged["next_period"].fillna(sales_fc["next_period"].iloc[0] if not sales_fc.empty else "")
    return merged.sort_values(["rank_komposit", "rank_sales", "rank_qty"])


def model_leaderboard(qty_fc: pd.DataFrame, sales_fc: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for metric, frame, col in (
        ("qty", qty_fc, "best_model"),
        ("sales", sales_fc, "best_model"),
    ):
        if frame.empty:
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
    lo, hi = series.min(), series.max()
    if hi == lo:
        return pd.Series([1.0] * len(series), index=series.index)
    return (series - lo) / (hi - lo)
