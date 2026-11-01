"""Model prediksi permintaan per SKU dan ensemble berbobot walk-forward.

Semua model menerima matriks penjualan harian (SKU × tanggal, hari tanpa transaksi = 0)
dan mengembalikan total QTY untuk `horizon` hari setelah tanggal terakhir matriks.
Hari stok kosong (permintaan tersensor) bernilai NaN dan tidak dihitung sebagai permintaan rendah.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.core.preprocessing import promo_flag

MODEL_LEVEL = "Level terkini"
MODEL_MA = "Moving Average 28"
MODEL_ES = "Exponential Smoothing"
MODEL_GBM = "XGBoost global"
MODEL_GBM_FALLBACK = "Gradient Boosting global"
MODEL_PROPHET = "Prophet"
MODEL_LSTM = "LSTM"
MODEL_ENSEMBLE = "Ensemble"
GBM_TARGET_DAYS = 28


@dataclass
class DemandMatrix:
    keys: list[str]
    dates: pd.DatetimeIndex
    values: np.ndarray  # float, NaN = tersensor (stok kosong)

    @property
    def filled(self) -> np.ndarray:
        return np.nan_to_num(self.values, nan=0.0)

    def cut(self, end_index: int) -> "DemandMatrix":
        return DemandMatrix(self.keys, self.dates[:end_index], self.values[:, :end_index])


@dataclass
class ModelAvailability:
    active: dict[str, str] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)


def build_demand_matrix(
    base_history: pd.DataFrame,
    *,
    zero_since: dict[str, pd.Timestamp] | None = None,
    end: pd.Timestamp | None = None,
) -> DemandMatrix:
    """Pivot riwayat harian per SKU; hari kosong = 0, hari stok habis = NaN."""
    if base_history is None or base_history.empty:
        return DemandMatrix([], pd.DatetimeIndex([]), np.zeros((0, 0)))
    work = base_history[["item_key", "period_start", "qty"]].copy()
    work["period_start"] = pd.to_datetime(work["period_start"]).dt.normalize()
    last = pd.Timestamp(end).normalize() if end is not None else work["period_start"].max()
    dates = pd.date_range(work["period_start"].min(), last, freq="D")
    pivot = work.pivot_table(index="item_key", columns="period_start", values="qty", aggfunc="sum", fill_value=0.0)
    pivot = pivot.reindex(columns=dates, fill_value=0.0)
    values = pivot.to_numpy(dtype=float)
    keys = [str(key) for key in pivot.index]
    if zero_since:
        position = {key: index for index, key in enumerate(keys)}
        for key, since in zero_since.items():
            row = position.get(str(key))
            if row is None or since is None or pd.isna(since):
                continue
            start = dates.searchsorted(pd.Timestamp(since).normalize())
            tail = values[row, start:]
            # Hari stok habis tanpa penjualan dianggap tersensor, bukan permintaan nol.
            values[row, start:] = np.where(tail > 0, tail, np.nan)
    return DemandMatrix(keys, dates, values)


def _weekday_profile(matrix: DemandMatrix) -> np.ndarray:
    profile = np.ones(7)
    if matrix.values.size == 0:
        return profile
    total = matrix.filled.sum(axis=0)
    if len(total) >= 8:
        total = np.minimum(total, np.quantile(total, 0.90))
    frame = pd.DataFrame({"qty": total, "dow": matrix.dates.dayofweek})
    means = frame.groupby("dow")["qty"].mean()
    for dow, value in means.items():
        profile[int(dow)] = float(value)
    mean = profile.mean()
    return profile / mean if mean > 0 else np.ones(7)


def forecast_level(matrix: DemandMatrix, horizon: int) -> np.ndarray:
    """Level terkini (metode lama) per SKU, rumus dari src.forecast tidak diubah."""
    from src.forecast import _robust_forecast

    if matrix.values.size == 0:
        return np.zeros(len(matrix.keys))
    weekday = _weekday_profile(matrix)
    start = matrix.dates[0]
    out = np.zeros(len(matrix.keys))
    origin = matrix.dates[-1] + pd.Timedelta(days=1)
    for row in range(len(matrix.keys)):
        series = matrix.values[row]
        valid = ~np.isnan(series)
        if not valid.any():
            continue
        last_valid = int(np.flatnonzero(valid)[-1]) + 1
        clean = np.nan_to_num(series[:last_valid], nan=0.0)
        if clean.sum() <= 0:
            continue
        out[row] = _robust_forecast(clean, start, horizon, weekday, forecast_start=origin)
    return out


def forecast_moving_average(matrix: DemandMatrix, horizon: int, window: int = 28) -> np.ndarray:
    if matrix.values.size == 0:
        return np.zeros(len(matrix.keys))
    recent = matrix.values[:, -window:]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        rate = np.nanmean(recent, axis=1)
    return np.nan_to_num(rate, nan=0.0) * horizon


def forecast_exponential(matrix: DemandMatrix, horizon: int, alpha: float = 0.1) -> np.ndarray:
    """Simple exponential smoothing per SKU (vektor), level × horizon."""
    if matrix.values.size == 0:
        return np.zeros(len(matrix.keys))
    level = None
    for column in range(matrix.values.shape[1]):
        value = matrix.values[:, column]
        if level is None:
            level = np.nan_to_num(value, nan=0.0)
            continue
        observed = ~np.isnan(value)
        level = np.where(observed, alpha * np.nan_to_num(value) + (1 - alpha) * level, level)
    return np.maximum(level, 0.0) * horizon


def _gbm_regressor():
    try:
        from xgboost import XGBRegressor

        model = XGBRegressor(
            n_estimators=220,
            max_depth=5,
            learning_rate=0.06,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="reg:squarederror",
            n_jobs=2,
            verbosity=0,
        )
        return model, MODEL_GBM
    except Exception:
        from sklearn.ensemble import HistGradientBoostingRegressor

        return HistGradientBoostingRegressor(max_iter=220, learning_rate=0.06, max_depth=6, random_state=42), MODEL_GBM_FALLBACK


def _features_at(filled: np.ndarray, valid: np.ndarray, end: int, dates: pd.DatetimeIndex, target_days: int) -> np.ndarray:
    """Fitur per SKU pada titik potong `end` (eksklusif): lag, rolling, kalender promo jendela target."""

    def window_mean(days: int, offset: int = 0) -> np.ndarray:
        lo = max(end - offset - days, 0)
        hi = max(end - offset, 0)
        if hi <= lo:
            return np.zeros(filled.shape[0])
        part = filled[:, lo:hi]
        seen = valid[:, lo:hi].sum(axis=1)
        return np.where(seen > 0, part.sum(axis=1) / np.maximum(seen, 1), 0.0)

    lag1 = filled[:, end - 1] if end >= 1 else np.zeros(filled.shape[0])
    m7 = window_mean(7)
    m14 = window_mean(14)
    m28 = window_mean(28)
    m28_prev = window_mean(28, 28)
    m90 = window_mean(90)
    lo = max(end - 28, 0)
    std28 = filled[:, lo:end].std(axis=1) if end > lo else np.zeros(filled.shape[0])
    active28 = (filled[:, lo:end] > 0).sum(axis=1) / 28.0
    stock_ok = valid[:, end - 1].astype(float) if end >= 1 else np.ones(filled.shape[0])
    future = pd.date_range(dates[0] + pd.Timedelta(days=end), periods=target_days, freq="D")
    promo_share = float(promo_flag(pd.Series(future)).mean())
    month = float(future[0].month)
    n = filled.shape[0]
    return np.column_stack(
        [
            lag1,
            m7,
            m14,
            m28,
            m28_prev,
            m90,
            std28,
            active28,
            stock_ok,
            np.full(n, promo_share),
            np.full(n, month),
            m28 - m28_prev,
        ]
    )


def forecast_global_gbm(matrix: DemandMatrix, horizon: int, *, max_rows: int = 120_000) -> tuple[np.ndarray, str]:
    """Model global satu untuk semua SKU (direct): prediksi laju harian 28 hari ke depan × horizon."""
    keys = len(matrix.keys)
    days = matrix.values.shape[1] if matrix.values.size else 0
    target = GBM_TARGET_DAYS
    if keys == 0 or days < target + 35:
        return forecast_moving_average(matrix, horizon), MODEL_MA
    filled = matrix.filled
    valid = ~np.isnan(matrix.values)
    active = filled[:, -90:].sum(axis=1) > 0
    cutoffs = list(range(days - target, 35, -7))[:30]
    x_parts, y_parts = [], []
    rng = np.random.default_rng(42)
    for cut in cutoffs:
        feats = _features_at(filled, valid, cut, matrix.dates, target)
        future = filled[:, cut : cut + target]
        seen = valid[:, cut : cut + target].sum(axis=1)
        y = np.where(seen > 0, future.sum(axis=1) / np.maximum(seen, 1), np.nan)
        keep = active & ~np.isnan(y) & (feats[:, 5] > 0)
        x_parts.append(feats[keep])
        y_parts.append(y[keep])
    x = np.vstack(x_parts) if x_parts else np.zeros((0, 12))
    y = np.concatenate(y_parts) if y_parts else np.zeros(0)
    if len(y) < 200:
        return forecast_moving_average(matrix, horizon), MODEL_MA
    if len(y) > max_rows:
        pick = rng.choice(len(y), size=max_rows, replace=False)
        x, y = x[pick], y[pick]
    model, name = _gbm_regressor()
    try:
        model.fit(x, y)
        rate = model.predict(_features_at(filled, valid, days, matrix.dates, target))
    except Exception:
        return forecast_moving_average(matrix, horizon), MODEL_MA
    rate = np.maximum(np.nan_to_num(rate, nan=0.0), 0.0)
    rate = np.where(filled[:, -90:].sum(axis=1) > 0, rate, 0.0)
    return rate * horizon, name


FEATURE_LABELS = (
    "Penjualan kemarin (lag 1)",
    "Rata-rata 7 hari",
    "Rata-rata 14 hari",
    "Rata-rata 28 hari",
    "Rata-rata 28 hari sebelumnya",
    "Rata-rata 90 hari",
    "Variasi 28 hari",
    "Porsi hari aktif 28 hari",
    "Stok tersedia kemarin",
    "Porsi hari promo ke depan",
    "Bulan",
    "Perubahan level 28 hari",
)


def feature_importance(matrix: DemandMatrix, *, max_rows: int = 30_000) -> tuple[pd.DataFrame, str]:
    """Kepentingan fitur model global: SHAP bila terpasang, selain itu permutation importance."""
    days = matrix.values.shape[1] if matrix.values.size else 0
    target = GBM_TARGET_DAYS
    empty = pd.DataFrame(columns=["Fitur", "Kepentingan"])
    if not matrix.keys or days < target + 35:
        return empty, "riwayat harian belum cukup untuk model global"
    filled = matrix.filled
    valid = ~np.isnan(matrix.values)
    active = filled[:, -90:].sum(axis=1) > 0
    x_parts, y_parts = [], []
    for cut in list(range(days - target, 35, -7))[:20]:
        feats = _features_at(filled, valid, cut, matrix.dates, target)
        future = filled[:, cut : cut + target]
        seen = valid[:, cut : cut + target].sum(axis=1)
        y = np.where(seen > 0, future.sum(axis=1) / np.maximum(seen, 1), np.nan)
        keep = active & ~np.isnan(y) & (feats[:, 5] > 0)
        x_parts.append(feats[keep])
        y_parts.append(y[keep])
    x = np.vstack(x_parts) if x_parts else np.zeros((0, 12))
    y = np.concatenate(y_parts) if y_parts else np.zeros(0)
    if len(y) < 200:
        return empty, "baris latih model global < 200"
    rng = np.random.default_rng(7)
    if len(y) > max_rows:
        pick = rng.choice(len(y), size=max_rows, replace=False)
        x, y = x[pick], y[pick]
    model, _name = _gbm_regressor()
    model.fit(x, y)
    sample = x[rng.choice(len(x), size=min(len(x), 3000), replace=False)]
    try:
        import shap  # type: ignore

        values = shap.TreeExplainer(model).shap_values(sample)
        score = np.abs(values).mean(axis=0)
        method = "SHAP (rata-rata |nilai SHAP|)"
    except Exception:
        from sklearn.inspection import permutation_importance

        y_sample = model.predict(sample)
        result = permutation_importance(model, sample, y_sample, n_repeats=3, random_state=7)
        score = np.maximum(result.importances_mean, 0)
        method = "Permutation importance (SHAP tidak terpasang)"
    total = float(score.sum()) or 1.0
    frame = pd.DataFrame({"Fitur": list(FEATURE_LABELS), "Kepentingan": score / total * 100})
    return frame.sort_values("Kepentingan", ascending=False).reset_index(drop=True), method


def forecast_prophet_share(matrix: DemandMatrix, horizon: int) -> tuple[np.ndarray | None, str]:
    """Prophet pada total toko (musiman, promo), lalu dibagi ke SKU menurut porsi 28 hari terakhir."""
    try:
        from prophet import Prophet  # type: ignore
    except Exception:
        return None, "library prophet tidak terpasang"
    days = matrix.values.shape[1] if matrix.values.size else 0
    if days < 60:
        return None, "riwayat harian < 60 hari"
    total = matrix.filled.sum(axis=0)
    frame = pd.DataFrame({"ds": matrix.dates, "y": total})
    frame["promo"] = promo_flag(frame["ds"]).astype(float)
    try:
        model = Prophet(weekly_seasonality=True, yearly_seasonality=days >= 365, daily_seasonality=False)
        model.add_regressor("promo")
        model.fit(frame)
        future = model.make_future_dataframe(periods=horizon, include_history=False)
        future["promo"] = promo_flag(future["ds"]).astype(float)
        store_total = float(np.maximum(model.predict(future)["yhat"].to_numpy(), 0).sum())
    except Exception as exc:  # noqa: BLE001
        return None, f"Prophet gagal dilatih: {exc}"
    recent = matrix.filled[:, -28:].sum(axis=1)
    share = recent / recent.sum() if recent.sum() > 0 else np.zeros(len(recent))
    return share * store_total, MODEL_PROPHET


def lstm_status(days: int, horizon: int) -> str | None:
    """LSTM/TFT hanya untuk horizon panjang dengan riwayat ≥ 2× horizon dan library tersedia."""
    if horizon <= 31:
        return "hanya dipakai untuk Quartal/Semester/Tahun"
    if days < 2 * horizon:
        return f"riwayat {days} hari < 2× horizon ({2 * horizon} hari)"
    try:
        import torch  # type: ignore  # noqa: F401
    except Exception:
        try:
            import tensorflow  # type: ignore  # noqa: F401
        except Exception:
            return "PyTorch/TensorFlow tidak terpasang"
    return None


def model_forecasts(matrix: DemandMatrix, horizon: int) -> tuple[dict[str, np.ndarray], ModelAvailability]:
    availability = ModelAvailability()
    out: dict[str, np.ndarray] = {}
    out[MODEL_LEVEL] = forecast_level(matrix, horizon)
    availability.active[MODEL_LEVEL] = "metode lama, level 28 hari terakhir"
    out[MODEL_MA] = forecast_moving_average(matrix, horizon)
    availability.active[MODEL_MA] = "rata-rata 28 hari terakhir"
    out[MODEL_ES] = forecast_exponential(matrix, horizon)
    availability.active[MODEL_ES] = "simple exponential smoothing α = 0,1"
    gbm, name = forecast_global_gbm(matrix, horizon)
    if name in {MODEL_GBM, MODEL_GBM_FALLBACK}:
        out[name] = gbm
        note = "fitur lag 1/7/14/28, rolling, kalender promo, flag stok"
        if name == MODEL_GBM_FALLBACK:
            note += "; XGBoost tidak bisa dimuat, memakai HistGradientBoosting scikit-learn"
            availability.skipped[MODEL_GBM] = "library xgboost tidak bisa dimuat, diganti Gradient Boosting scikit-learn"
        availability.active[name] = note
    else:
        availability.skipped[MODEL_GBM] = "riwayat harian < 63 hari atau sampel latih < 200"
    prophet, note = forecast_prophet_share(matrix, horizon)
    if prophet is not None:
        out[MODEL_PROPHET] = prophet
        availability.active[MODEL_PROPHET] = "total toko + regresor promo, dibagi ke SKU"
    else:
        availability.skipped[MODEL_PROPHET] = note
    days = matrix.values.shape[1] if matrix.values.size else 0
    lstm_note = lstm_status(days, horizon)
    availability.skipped[MODEL_LSTM] = lstm_note or "disiapkan, belum diaktifkan pada versi ini"
    try:
        import lightgbm  # type: ignore  # noqa: F401
    except Exception:
        availability.skipped["LightGBM"] = "library lightgbm tidak terpasang; peran model global diisi XGBoost/Gradient Boosting"
    return out, availability


ENSEMBLE_MEMBERS = (MODEL_GBM, MODEL_GBM_FALLBACK, MODEL_PROPHET, MODEL_MA, MODEL_LEVEL)


def ensemble_weights(scores: dict[str, float]) -> dict[str, float]:
    """Bobot invers WAPE walk-forward untuk anggota ensemble yang tersedia."""
    members = {name: wape for name, wape in scores.items() if name in ENSEMBLE_MEMBERS and np.isfinite(wape)}
    if not members:
        return {MODEL_LEVEL: 1.0}
    inverse = {name: 1.0 / max(wape, 1e-3) for name, wape in members.items()}
    total = sum(inverse.values())
    return {name: value / total for name, value in inverse.items()}


def blend(forecasts: dict[str, np.ndarray], weights: dict[str, float]) -> np.ndarray:
    size = len(next(iter(forecasts.values()))) if forecasts else 0
    out = np.zeros(size)
    used = 0.0
    for name, weight in weights.items():
        if name in forecasts:
            out += weight * forecasts[name]
            used += weight
    return out / used if used > 0 else out
