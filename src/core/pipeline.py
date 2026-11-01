"""Rangkaian prediksi: model per SKU → walk-forward → ensemble → harga 4 minggu."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from src.core.ensemble import (
    MODEL_ENSEMBLE,
    MODEL_LEVEL,
    ModelAvailability,
    blend,
    build_demand_matrix,
    model_forecasts,
)
from src.core.evaluation import WalkForwardResult, evaluation_horizons, walk_forward
from src.core.inventory import average_net_price_last_4_weeks


@dataclass
class DemandOutcome:
    per_model: pd.DataFrame  # item_key + satu kolom per model + Ensemble
    weights: dict[str, float]
    availability: ModelAvailability
    evaluations: list[WalkForwardResult] = field(default_factory=list)
    censored_skus: int = 0
    evaluated_skus: int = 0
    history_days: int = 0


def _evaluation_subset(matrix, limit: int):
    """SKU aktif 90 hari terakhir, dibatasi `limit` SKU dengan penjualan terbesar agar evaluasi tetap cepat."""
    if matrix.values.size == 0:
        return matrix
    recent = matrix.filled[:, -90:].sum(axis=1)
    order = np.argsort(-recent)
    keep = [index for index in order[:limit] if recent[index] > 0]
    if not keep:
        return matrix
    keep = sorted(keep)
    from src.core.ensemble import DemandMatrix

    return DemandMatrix([matrix.keys[i] for i in keep], matrix.dates, matrix.values[keep])


def run_demand_models(
    base_history: pd.DataFrame,
    *,
    horizon: int,
    zero_since: dict[str, pd.Timestamp] | None = None,
    eval_limit: int = 800,
    progress=None,
) -> DemandOutcome:
    matrix = build_demand_matrix(base_history, zero_since=zero_since)
    days = matrix.values.shape[1] if matrix.values.size else 0
    censored = int(np.isnan(matrix.values).any(axis=1).sum()) if matrix.values.size else 0
    subset = _evaluation_subset(matrix, eval_limit)
    evaluations: list[WalkForwardResult] = []
    horizons = evaluation_horizons(horizon, days)
    for index, eval_h in enumerate(horizons):
        if progress:
            progress(0.1 + 0.6 * index / max(len(horizons), 1), f"Walk-forward horizon {eval_h} hari")
        evaluations.append(walk_forward(subset, eval_h))
    # Bobot ensemble dari horizon uji yang paling dekat dengan periode prediksi.
    weights = {MODEL_LEVEL: 1.0}
    if evaluations:
        closest = min(evaluations, key=lambda result: abs(result.horizon - horizon))
        weights = closest.weights
    if progress:
        progress(0.8, "Melatih model akhir dan menyusun ensemble")
    forecasts, availability = model_forecasts(matrix, horizon)
    forecasts[MODEL_ENSEMBLE] = blend(forecasts, weights)
    per_model = pd.DataFrame({"item_key": matrix.keys})
    for name, values in forecasts.items():
        per_model[name] = values
    return DemandOutcome(
        per_model=per_model,
        weights=weights,
        availability=availability,
        evaluations=evaluations,
        censored_skus=censored,
        evaluated_skus=len(subset.keys),
        history_days=days,
    )


def outcome_with_weights(
    base_history: pd.DataFrame,
    *,
    horizon: int,
    weights: dict[str, float],
    zero_since: dict[str, pd.Timestamp] | None = None,
) -> DemandOutcome:
    """Model akhir dengan bobot yang sudah diuji (tanpa walk-forward ulang), untuk prediksi pada tanggal lampau."""
    matrix = build_demand_matrix(base_history, zero_since=zero_since)
    forecasts, availability = model_forecasts(matrix, horizon)
    forecasts[MODEL_ENSEMBLE] = blend(forecasts, weights or {MODEL_LEVEL: 1.0})
    per_model = pd.DataFrame({"item_key": matrix.keys})
    for name, values in forecasts.items():
        per_model[name] = values
    return DemandOutcome(per_model=per_model, weights=weights, availability=availability)


def apply_ensemble(qty_fc: pd.DataFrame, outcome: DemandOutcome) -> pd.DataFrame:
    """Ganti prediksi QTY dengan ensemble; nilai Level terkini disimpan di `forecast_level`."""
    if qty_fc is None or qty_fc.empty or outcome.per_model.empty:
        return qty_fc
    out = qty_fc.copy()
    out["forecast_level"] = out["forecast"].astype(float)
    blended = outcome.per_model.set_index("item_key")[MODEL_ENSEMBLE]
    values = out["item_key"].astype(str).map(blended)
    has = values.notna()
    sold = out["forecast_level"] > 0
    rounded = np.floor(values.fillna(0.0) + 0.5)
    rounded = np.where(sold & (rounded < 1), 1, rounded)
    out.loc[has, "forecast"] = rounded[has.to_numpy()]
    out.loc[has, "best_model"] = MODEL_ENSEMBLE
    return out


def apply_recent_price(
    combined: pd.DataFrame,
    orders: pd.DataFrame,
    *,
    today: date,
) -> pd.DataFrame:
    """Prediksi sales = prediksi QTY × harga jual bersih rata-rata 4 minggu terakhir per SKU.

    SKU yang tidak laku 4 minggu terakhir memakai harga dari prediksi sales lama (rata-rata riwayat).
    """
    if combined is None or combined.empty:
        return combined
    out = combined.copy()
    price = average_net_price_last_4_weeks(orders, as_of=today)
    old_price = np.where(out["pred_qty"].astype(float) > 0, out["pred_sales"].astype(float) / out["pred_qty"].astype(float).replace(0, np.nan), np.nan)
    out["harga_lama"] = old_price
    out = out.merge(price, on="item_key", how="left")
    unit = out["avg_net_price_4w"].where(out["avg_net_price_4w"].fillna(0) > 0, out["harga_lama"]).fillna(0.0)
    out["harga_bersih_4w"] = unit
    out["pred_sales"] = np.floor(out["pred_qty"].astype(float).clip(lower=0) * unit + 0.5)
    out["model_sales"] = "QTY × harga bersih 4 minggu"
    return out.drop(columns=["harga_lama"])


def model_comparison_frame(outcome: DemandOutcome) -> pd.DataFrame:
    """Tabel perbandingan model untuk tab Evaluasi model (semua horizon uji)."""
    frames = []
    for result in outcome.evaluations:
        if result.metrics.empty:
            continue
        part = result.metrics.copy()
        part.insert(0, "Horizon (hari)", result.horizon)
        part["Bobot ensemble"] = part["Model"].map(result.weights).fillna(0.0)
        frames.append(part)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
