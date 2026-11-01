"""Time series cross-validation (walk-forward) untuk prediksi permintaan per SKU."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.core.ensemble import (
    MODEL_ENSEMBLE,
    MODEL_LEVEL,
    DemandMatrix,
    blend,
    ensemble_weights,
    model_forecasts,
)

MAPE_TARGET_PCT = 15.0


def mape(actual: np.ndarray, pred: np.ndarray) -> float:
    """MAPE hanya pada nilai aktual > 0 (tidak terdefinisi pada aktual 0)."""
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    mask = actual > 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs(actual[mask] - pred[mask]) / actual[mask]) * 100)


def rmse(actual: np.ndarray, pred: np.ndarray) -> float:
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    if len(actual) == 0:
        return float("nan")
    return float(np.sqrt(np.mean((actual - pred) ** 2)))


def wape(actual: np.ndarray, pred: np.ndarray) -> float:
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    denom = float(np.abs(actual).sum())
    if denom <= 0:
        return float("nan")
    return float(np.abs(actual - pred).sum() / denom * 100)


def bias_pct(actual: np.ndarray, pred: np.ndarray) -> float:
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    denom = float(actual.sum())
    if denom <= 0:
        return float("nan")
    return float((pred.sum() - denom) / denom * 100)


def top_n_hits(actual: np.ndarray, pred: np.ndarray, n: int = 50) -> int:
    count = min(n, len(actual))
    if count == 0:
        return 0
    top_actual = set(np.argsort(-np.asarray(actual))[:count])
    top_pred = set(np.argsort(-np.asarray(pred))[:count])
    return len(top_actual & top_pred)


@dataclass
class WalkForwardResult:
    horizon: int
    folds: int
    metrics: pd.DataFrame  # per model: MAPE SKU, MAPE agregat, RMSE, WAPE, Bias, Top 50
    fold_detail: pd.DataFrame
    weights: dict[str, float]
    notes: list[str] = field(default_factory=list)


def _fold_cutoffs(days: int, horizon: int, folds: int, min_train: int = 35) -> list[int]:
    cutoffs = []
    for k in range(folds, 0, -1):
        cut = days - k * horizon
        if cut >= min_train:
            cutoffs.append(cut)
    return cutoffs


def walk_forward(matrix: DemandMatrix, horizon: int, *, folds: int = 3, top_n: int = 50) -> WalkForwardResult:
    """Latih pada data s.d. titik potong, uji `horizon` hari berikutnya; ulangi per fold."""
    days = matrix.values.shape[1] if matrix.values.size else 0
    horizon = max(int(horizon), 1)
    cutoffs = _fold_cutoffs(days, horizon, folds)
    notes: list[str] = []
    if not cutoffs:
        notes.append(f"Riwayat {days} hari belum cukup untuk walk-forward horizon {horizon} hari (butuh ≥ {35 + horizon} hari).")
        empty = pd.DataFrame(columns=["Model", "MAPE SKU (%)", "MAPE agregat (%)", "RMSE", "WAPE (%)", "Bias (%)", f"Top {top_n} tepat"])
        return WalkForwardResult(horizon, 0, empty, pd.DataFrame(), {MODEL_LEVEL: 1.0}, notes)
    rows = []
    collected: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
    for cut in cutoffs:
        train = matrix.cut(cut)
        actual = matrix.filled[:, cut : cut + horizon].sum(axis=1)
        forecasts, _availability = model_forecasts(train, horizon)
        fold_scores = {name: wape(actual, pred) for name, pred in forecasts.items()}
        forecasts[MODEL_ENSEMBLE] = blend(forecasts, ensemble_weights(fold_scores))
        for name, pred in forecasts.items():
            collected.setdefault(name, []).append((actual, pred))
            rows.append(
                {
                    "Fold": f"s.d. {matrix.dates[cut - 1].date()}",
                    "Model": name,
                    "WAPE (%)": wape(actual, pred),
                    "MAPE agregat (%)": mape(np.array([actual.sum()]), np.array([pred.sum()])),
                }
            )
    summary = []
    for name, pairs in collected.items():
        actual = np.concatenate([pair[0] for pair in pairs])
        pred = np.concatenate([pair[1] for pair in pairs])
        agg_actual = np.array([pair[0].sum() for pair in pairs])
        agg_pred = np.array([pair[1].sum() for pair in pairs])
        hits = [top_n_hits(pair[0], pair[1], top_n) for pair in pairs]
        summary.append(
            {
                "Model": name,
                "MAPE SKU (%)": mape(actual, pred),
                "MAPE agregat (%)": mape(agg_actual, agg_pred),
                "RMSE": rmse(actual, pred),
                "WAPE (%)": wape(actual, pred),
                "Bias (%)": bias_pct(actual, pred),
                f"Top {top_n} tepat": float(np.mean(hits)) if hits else float("nan"),
            }
        )
    metrics = pd.DataFrame(summary).sort_values("WAPE (%)").reset_index(drop=True)
    scores = {row["Model"]: row["WAPE (%)"] for row in summary if row["Model"] != MODEL_ENSEMBLE}
    weights = ensemble_weights(scores)
    return WalkForwardResult(horizon, len(cutoffs), metrics, pd.DataFrame(rows), weights, notes)


def evaluation_horizons(period_days: int, history_days: int) -> list[int]:
    """Horizon uji: 7 dan 28 hari, ditambah horizon periode bila riwayat cukup untuk 2 fold."""
    out = [7, 28]
    if period_days > 28 and history_days >= 35 + 2 * period_days:
        out.append(int(period_days))
    return [h for h in out if history_days >= 35 + h]
