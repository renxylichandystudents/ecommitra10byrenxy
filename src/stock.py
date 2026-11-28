from __future__ import annotations

import numpy as np
import pandas as pd

from src.aggregate import dense_item_series


def stock_priority(suggested: float, reorder: float, actual: float | None) -> str:
    """Prioritas restock: tinggi / sedang / pantau."""
    try:
        suggested = float(suggested)
    except (TypeError, ValueError):
        suggested = 0.0
    if not np.isfinite(suggested):
        suggested = 0.0
    try:
        reorder = float(max(reorder, 0.0))
    except (TypeError, ValueError):
        reorder = 0.0
    if not np.isfinite(reorder):
        reorder = 0.0
    if actual is None:
        usable_actual = None
    else:
        try:
            usable_actual = float(actual)
        except (TypeError, ValueError):
            usable_actual = None
        if usable_actual is not None and not np.isfinite(usable_actual):
            usable_actual = None
    if usable_actual is None:
        if suggested <= 0:
            return "pantau"
        if suggested >= 20:
            return "tinggi"
        if suggested >= 5:
            return "sedang"
        return "pantau"
    actual_val = float(max(usable_actual, 0.0))
    if suggested <= 0:
        return "pantau"
    coverage = actual_val / suggested
    if reorder <= 0 or coverage >= 1.0:
        return "pantau"
    if coverage < 0.35 or reorder >= suggested * 0.5:
        return "tinggi"
    if coverage < 0.7 or reorder >= suggested * 0.2:
        return "sedang"
    return "pantau"


def _parse_actual_map(actual_stock: dict[str, float] | pd.Series | None) -> dict[str, float]:
    actual_map: dict[str, float] = {}
    if isinstance(actual_stock, pd.Series):
        items = actual_stock.items()
    elif isinstance(actual_stock, dict):
        items = actual_stock.items()
    else:
        return actual_map
    for key, value in items:
        if value is None or (isinstance(value, float) and not np.isfinite(value)):
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(parsed):
            continue
        actual_map[str(key)] = parsed
    return actual_map


def recommend_stock(
    history: pd.DataFrame,
    combined: pd.DataFrame,
    period: str,
    service_level_z: float = 1.65,
    horizon_steps: int = 1,
    actual_stock: dict[str, float] | pd.Series | None = None,
) -> pd.DataFrame:
    """Stok = prediksi tren + safety stock.

    Safety stock menutup selisih penjualan harian terhadap tren, lalu diskalakan
    sepanjang periode yang dipilih. Persentase dari user mengatur besar cadangan itu.
    Bila stok aktual diisi: reorder = max(0, disarankan − aktual).
    """
    columns = [
        "item_key",
        "item_label",
        "pred_qty",
        "pred_sales",
        "sigma_qty",
        "safety_stock",
        "stok_disarankan",
        "stok_aktual",
        "reorder",
        "prioritas",
        "model_qty",
        "rank_qty",
        "rank_sales",
        "rank_komposit",
    ]
    if combined is None or combined.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    if history is None or history.empty or "item_key" not in history.columns:
        hist_map = {}
    else:
        hist_map = {key: grp for key, grp in history.groupby("item_key")}
    actual_map = _parse_actual_map(actual_stock)

    for _, item in combined.iterrows():
        sigma = float(item["error_sigma"]) if "error_sigma" in item and pd.notna(item["error_sigma"]) else 0.0
        if not np.isfinite(sigma):
            sigma = 0.0
        if sigma <= 0:
            hist = hist_map.get(item["item_key"])
            if hist is not None and not hist.empty:
                dense = dense_item_series(hist, period)
                if len(dense) > 1 and "qty" in dense.columns:
                    sigma = float(np.std(dense["qty"].to_numpy(dtype=float), ddof=1))
                    if not np.isfinite(sigma):
                        sigma = 0.0
        try:
            forecast_qty = float(item.get("pred_qty", 0.0) or 0.0)
        except (TypeError, ValueError):
            forecast_qty = 0.0
        if not np.isfinite(forecast_qty):
            forecast_qty = 0.0
        try:
            pred_sales = float(item.get("pred_sales", 0.0) or 0.0)
        except (TypeError, ValueError):
            pred_sales = 0.0
        if not np.isfinite(pred_sales):
            pred_sales = 0.0
        steps = max(int(horizon_steps), 1)
        try:
            z = float(service_level_z)
        except (TypeError, ValueError):
            z = 0.0
        if not np.isfinite(z):
            z = 0.0
        safety = z * sigma * np.sqrt(steps)
        if not np.isfinite(safety):
            safety = 0.0
        suggested = int(max(np.ceil(forecast_qty + safety), 0))
        key = str(item["item_key"])
        has_actual = key in actual_map
        actual = float(max(actual_map[key], 0.0)) if has_actual else None
        reorder = int(max(0, suggested - int(actual))) if has_actual else None
        rows.append(
            {
                "item_key": item["item_key"],
                "item_label": item.get("item_label", ""),
                "pred_qty": forecast_qty,
                "pred_sales": pred_sales,
                "sigma_qty": sigma,
                "safety_stock": safety,
                "stok_disarankan": suggested,
                "stok_aktual": actual if has_actual else np.nan,
                "reorder": reorder if has_actual else np.nan,
                "prioritas": stock_priority(suggested, float(reorder or 0), actual),
                "model_qty": item.get("model_qty", ""),
                "rank_qty": item.get("rank_qty", np.nan),
                "rank_sales": item.get("rank_sales", np.nan),
                "rank_komposit": item.get("rank_komposit", np.nan),
            }
        )
    result = pd.DataFrame(rows)
    sort_cols = [c for c in ("rank_komposit", "rank_qty") if c in result.columns]
    if sort_cols:
        return result.sort_values(sort_cols)
    return result
