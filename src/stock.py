from __future__ import annotations

import numpy as np
import pandas as pd

from src.aggregate import dense_item_series
from src.core.inventory import inventory_decision


def recommend_stock(
    history: pd.DataFrame,
    combined: pd.DataFrame,
    period: str,
    service_level_z: float = 1.65,
    horizon_steps: int = 1,
    lead_time_days: float = 7.0,
    service_level_pct: float | None = None,
    lead_time_sigma: float = 0.0,
    source_type: str = "local",
    lead_time_max: float | None = None,
) -> pd.DataFrame:
    """Stok = prediksi permintaan + safety stock berbasis lead time.

    Rumus lama memakai akar jumlah hari periode prediksi. Fase 3 menggantinya
    dengan lead time lokal: SS = Z x sigma_D x sqrt(L_lokal).
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
        pct = float(service_level_pct) if service_level_pct is not None else _z_to_service_level(float(service_level_z))
        decision = inventory_decision(
            forecast_qty=forecast_qty,
            current_stock=0.0,
            sigma_d=sigma,
            service_level_pct=pct,
            horizon_days=steps,
            lead_time_days=lead_time_days,
            sigma_l=lead_time_sigma,
            source_type=source_type,
            l_max=lead_time_max,
        )
        safety = decision.safety_stock
        suggested = max(np.ceil(decision.kebutuhan), 0)
        rows.append(
            {
                "item_key": item["item_key"],
                "item_label": item["item_label"],
                "pred_qty": forecast_qty,
                "pred_sales": float(item["pred_sales"]),
                "sigma_qty": sigma,
                "safety_stock": safety,
                "kebutuhan": decision.kebutuhan,
                "rop": decision.rop,
                "hari_cukup": decision.hari_cukup,
                "status_stok": decision.status_stok,
                "stok_disarankan": int(suggested),
                "model_qty": item.get("model_qty", ""),
                "rank_qty": item["rank_qty"],
                "rank_sales": item["rank_sales"],
                "rank_komposit": item["rank_komposit"],
            }
        )
    return pd.DataFrame(rows).sort_values(["rank_komposit", "rank_qty"])


def _z_to_service_level(z: float) -> float:
    try:
        from statistics import NormalDist

        return float(NormalDist().cdf(float(z)) * 100)
    except Exception:
        return 95.0
