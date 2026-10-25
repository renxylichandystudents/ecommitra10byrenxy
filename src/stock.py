from __future__ import annotations

import numpy as np
import pandas as pd

from src.aggregate import dense_item_series


def recommend_stock(
    history: pd.DataFrame,
    combined: pd.DataFrame,
    period: str,
    service_level_z: float = 1.65,
    horizon_steps: int = 1,
) -> pd.DataFrame:
    """Stok = prediksi tren + safety stock.

    Safety stock menutup selisih penjualan harian terhadap tren, lalu diskalakan
    sepanjang periode yang dipilih. Persentase dari user mengatur besar cadangan itu.
    """
    rows = []
    if history is None or history.empty or "item_key" not in history.columns:
        hist_map = {}
    else:
        hist_map = {key: grp for key, grp in history.groupby("item_key")}
    for _, item in combined.iterrows():
        sigma = float(item["error_sigma"]) if "error_sigma" in item and pd.notna(item["error_sigma"]) else 0.0
        if sigma <= 0:
            hist = hist_map.get(item["item_key"])
            if hist is not None and not hist.empty:
                dense = dense_item_series(hist, period)
                sigma = float(np.std(dense["qty"].to_numpy(dtype=float), ddof=1)) if len(dense) > 1 else 0.0
        forecast_qty = float(item["pred_qty"])
        steps = max(int(horizon_steps), 1)
        safety = float(service_level_z) * sigma * np.sqrt(steps)
        suggested = max(np.ceil(forecast_qty + safety), 0)
        rows.append(
            {
                "item_key": item["item_key"],
                "item_label": item["item_label"],
                "pred_qty": forecast_qty,
                "pred_sales": float(item["pred_sales"]),
                "sigma_qty": sigma,
                "safety_stock": safety,
                "stok_disarankan": int(suggested),
                "model_qty": item.get("model_qty", ""),
                "rank_qty": item["rank_qty"],
                "rank_sales": item["rank_sales"],
                "rank_komposit": item["rank_komposit"],
            }
        )
    return pd.DataFrame(rows).sort_values(["rank_komposit", "rank_qty"])
