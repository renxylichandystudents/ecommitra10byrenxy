from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX

from src.aggregate import PERIOD_SPECS, dense_item_series, next_period_start, period_label

try:
    from xgboost import XGBRegressor
except Exception:  # pragma: no cover - optional at runtime
    XGBRegressor = None


@dataclass
class ModelResult:
    name: str
    forecast: float
    mae: float
    rmse: float
    mape: float
    fitted: bool
    note: str = ""


@dataclass
class ItemForecast:
    item_key: str
    item_label: str
    metric: str
    best_model: str
    forecast: float
    mae: float
    rmse: float
    mape: float
    history_points: int
    next_period: str
    candidates: list[ModelResult]


def _whole_units(forecast: float, values: np.ndarray, steps: int, metric: str) -> float:
    """Prediksi qty dan omzet dibulatkan. Qty yang pernah terjual tidak boleh 0."""
    total = float(np.sum(values)) if len(values) else 0.0
    value = float(forecast)
    if total > 0 and value <= 0:
        value = total / max(len(values), 1) * max(int(steps), 1)
    rounded = int(np.floor(value + 0.5))
    if metric == "qty" and total > 0 and rounded < 1:
        rounded = 1
    return float(max(rounded, 0))


def _safe_mape(actual: np.ndarray, pred: np.ndarray) -> float:
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    mask = actual != 0
    if not mask.any():
        return float(np.mean(np.abs(pred - actual)))
    return float(np.mean(np.abs((actual[mask] - pred[mask]) / actual[mask])) * 100)


def _metrics(actual: np.ndarray, pred: np.ndarray) -> tuple[float, float, float]:
    mae = float(mean_absolute_error(actual, pred))
    rmse = float(np.sqrt(mean_squared_error(actual, pred)))
    mape = _safe_mape(actual, pred)
    return mae, rmse, mape


def _holdout_size(n: int) -> int:
    if n < 4:
        return 1
    return max(1, min(4, n // 4))


def _roll_seasonal(values: np.ndarray, season: int, steps: int) -> float:
    if len(values) == 0:
        return 0.0
    season_use = season if season > 1 and len(values) > season else 1
    history = [float(value) for value in values]
    total = 0.0
    for _ in range(max(int(steps), 1)):
        nxt = max(history[-season_use], 0.0)
        total += nxt
        history.append(nxt)
    return total


def _naive_forecast(values: np.ndarray, season: int, steps: int = 1) -> ModelResult:
    if len(values) < 2:
        level = float(values[-1]) if len(values) else 0.0
        pred = level * max(int(steps), 1)
        return ModelResult("Naive", pred, 0.0, 0.0, 0.0, True, "titik data terlalu sedikit")
    hold = _holdout_size(len(values))
    train, test = values[:-hold], values[-hold:]
    season_use = season if len(train) > season else 1
    preds = []
    history = list(train)
    for _ in test:
        preds.append(history[-season_use])
        history.append(history[-season_use])
    mae, rmse, mape = _metrics(test, np.array(preds))
    forecast = _roll_seasonal(values, season_use, steps)
    name = "Seasonal Naive" if season_use > 1 else "Naive"
    return ModelResult(name, max(forecast, 0.0), mae, rmse, mape, True)


def _roll_average(values: np.ndarray, steps: int, window: int = 3) -> float:
    if len(values) == 0:
        return 0.0
    history = [float(value) for value in values]
    total = 0.0
    for _ in range(max(int(steps), 1)):
        nxt = max(float(np.mean(history[-window:])), 0.0)
        total += nxt
        history.append(nxt)
    return total


def _moving_average(values: np.ndarray, steps: int = 1, window: int = 3) -> ModelResult:
    if len(values) < 2:
        level = float(values[-1]) if len(values) else 0.0
        return ModelResult("Moving Average", level * max(int(steps), 1), 0.0, 0.0, 0.0, True)
    hold = _holdout_size(len(values))
    preds = []
    for i in range(len(values) - hold, len(values)):
        start = max(0, i - window)
        preds.append(np.mean(values[start:i]) if i > start else values[i - 1])
    mae, rmse, mape = _metrics(values[-hold:], np.array(preds))
    forecast = _roll_average(values, steps, window)
    return ModelResult("Moving Average", max(forecast, 0.0), mae, rmse, mape, True)


def _holt_winters(values: np.ndarray, season: int, steps: int = 1) -> ModelResult | None:
    n = len(values)
    if n < 6:
        return None
    hold = _holdout_size(n)
    train = values[:-hold]
    seasonal = n >= max(2 * season, season + 4) and season > 1
    configs = []
    if seasonal:
        configs.extend(
            [
                dict(trend="add", seasonal="add", seasonal_periods=season),
                dict(trend="add", seasonal="mul", seasonal_periods=season),
            ]
        )
    configs.append(dict(trend="add", seasonal=None, seasonal_periods=None))
    best: ModelResult | None = None
    for cfg in configs:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = ExponentialSmoothing(train, initialization_method="estimated", **cfg)
                fit = model.fit(optimized=True)
                pred = np.asarray(fit.forecast(hold))
                pred = np.nan_to_num(pred, nan=0.0)
                mae, rmse, mape = _metrics(values[-hold:], pred)
                full = ExponentialSmoothing(values, initialization_method="estimated", **cfg).fit(optimized=True)
                path = np.clip(np.nan_to_num(np.asarray(full.forecast(max(int(steps), 1))), nan=0.0), 0, None)
                forecast = float(path.sum())
            name = "Holt-Winters" if cfg["seasonal"] else "Holt Linear"
            candidate = ModelResult(name, max(forecast, 0.0), mae, rmse, mape, True)
            if best is None or candidate.mape < best.mape:
                best = candidate
        except Exception:
            continue
    return best


def _sarima(values: np.ndarray, season: int, steps: int = 1) -> ModelResult | None:
    n = len(values)
    if n < 8:
        return None
    hold = _holdout_size(n)
    train = values[:-hold]
    orders = [(1, 1, 1), (0, 1, 1), (1, 0, 1)]
    seasonal_orders = [(0, 0, 0, 0)]
    if season > 1 and n >= (season * 2 + 4):
        seasonal_orders.append((1, 1, 0, season))
        seasonal_orders.append((0, 1, 1, season))
    best: ModelResult | None = None
    for order in orders:
        for seasonal_order in seasonal_orders:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    model = SARIMAX(
                        train,
                        order=order,
                        seasonal_order=seasonal_order,
                        enforce_stationarity=False,
                        enforce_invertibility=False,
                    )
                    fit = model.fit(disp=False)
                    pred = np.asarray(fit.forecast(hold))
                    pred = np.nan_to_num(pred, nan=0.0)
                    mae, rmse, mape = _metrics(values[-hold:], pred)
                    full = SARIMAX(
                        values,
                        order=order,
                        seasonal_order=seasonal_order,
                        enforce_stationarity=False,
                        enforce_invertibility=False,
                    ).fit(disp=False)
                    path = np.clip(
                        np.nan_to_num(np.asarray(full.forecast(max(int(steps), 1))), nan=0.0),
                        0,
                        None,
                    )
                    forecast = float(path.sum())
                name = "SARIMA" if seasonal_order[-1] else "ARIMA"
                candidate = ModelResult(name, max(forecast, 0.0), mae, rmse, mape, True)
                if best is None or candidate.mape < best.mape:
                    best = candidate
            except Exception:
                continue
    return best


def _make_lag_frame(values: np.ndarray, lags: int) -> tuple[np.ndarray, np.ndarray] | None:
    if len(values) <= lags + 2:
        return None
    rows = []
    targets = []
    for i in range(lags, len(values)):
        rows.append(values[i - lags : i])
        targets.append(values[i])
    return np.asarray(rows), np.asarray(targets)


def _xgboost_forecast(values: np.ndarray, steps: int = 1) -> ModelResult | None:
    if XGBRegressor is None or len(values) < 10:
        return None
    lags = min(6, max(3, len(values) // 4))
    packed = _make_lag_frame(values, lags)
    if packed is None:
        return None
    x, y = packed
    hold = max(1, min(3, len(y) // 5))
    x_train, y_train = x[:-hold], y[:-hold]
    x_test, y_test = x[-hold:], y[-hold:]
    if len(y_train) < 4:
        return None
    try:
        model = XGBRegressor(
            n_estimators=120,
            max_depth=3,
            learning_rate=0.08,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="reg:squarederror",
            n_jobs=1,
            verbosity=0,
        )
        model.fit(x_train, y_train)
        pred = model.predict(x_test)
        mae, rmse, mape = _metrics(y_test, pred)
        full = XGBRegressor(
            n_estimators=120,
            max_depth=3,
            learning_rate=0.08,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="reg:squarederror",
            n_jobs=1,
            verbosity=0,
        )
        full.fit(x, y)
        history = [float(value) for value in values]
        total = 0.0
        for _ in range(max(int(steps), 1)):
            latest = np.asarray(history[-lags:], dtype=float).reshape(1, -1)
            nxt = float(max(full.predict(latest)[0], 0.0))
            total += nxt
            history.append(nxt)
        return ModelResult("XGBoost", total, mae, rmse, mape, True)
    except Exception:
        return None


def forecast_series(
    values: np.ndarray,
    period: str,
    steps: int = 1,
) -> tuple[ModelResult, list[ModelResult]]:
    spec = PERIOD_SPECS[period]
    series = np.asarray(values, dtype=float)
    candidates: list[ModelResult] = [
        _naive_forecast(series, spec.season_length, steps),
        _moving_average(series, steps),
    ]
    holt = _holt_winters(series, spec.season_length, steps)
    if holt is not None:
        candidates.append(holt)
    # SARIMA dan XGBoost terlalu berat untuk deret harian ratusan SKU.
    if period != "hari":
        sarima = _sarima(series, spec.season_length, steps)
        if sarima is not None:
            candidates.append(sarima)
        boosted = _xgboost_forecast(series, steps)
        if boosted is not None:
            candidates.append(boosted)
    scored = [c for c in candidates if c.fitted]
    best = min(scored, key=lambda c: (c.mape, c.rmse, c.mae))
    return best, scored


def _expected_unit_price(item_hist: pd.DataFrame, period: str, steps: int) -> tuple[float, str]:
    """Harga yang dipakai pembeli Shopee: omzet histori dibagi qty, bukan model omzet terpisah.

    Harga setelah diskon biasanya stabil. Kalau lonjakannya kecil, prediksi omzet
    memakai harga transaksi terakhir supaya omzet bergerak searah dengan qty.
    Kalau harga benar-benar berubah, model harga hanya menggeser sedikit.
    """
    if item_hist is None or item_hist.empty:
        return 0.0, "Tanpa harga"
    dense = dense_item_series(item_hist, period)
    qty = dense["qty"].to_numpy(dtype=float)
    sales = dense["sales"].to_numpy(dtype=float)
    positive = qty > 0
    if not positive.any():
        return 0.0, "Tanpa harga"
    sold_at = np.flatnonzero(positive)
    latest = float(sales[sold_at[-1]] / qty[sold_at[-1]])
    window = 7 if period == "hari" else 3
    recent_at = sold_at[-window:]
    recent = float(sales[recent_at].sum() / qty[recent_at].sum())
    anchor = recent if recent > 0 else latest
    observed = sales[positive] / qty[positive]
    mean = float(np.mean(observed))
    cv = float(np.std(observed) / mean) if mean else 0.0
    if period == "hari" or len(observed) < 4 or cv < 0.08:
        return anchor, "Harga rata-rata"
    filled = pd.Series(np.divide(sales, qty, out=np.full_like(sales, np.nan), where=positive)).ffill().bfill()
    best, _ = forecast_series(filled.to_numpy(dtype=float), period, steps)
    model_price = float(best.forecast) / max(int(steps), 1)
    if not np.isfinite(model_price) or model_price <= 0:
        model_price = anchor
    model_price = float(np.clip(model_price, anchor * 0.7, anchor * 1.3))
    return float(0.7 * anchor + 0.3 * model_price), f"Harga {best.name}"


def forecast_revenue(
    history: pd.DataFrame,
    qty_fc: pd.DataFrame,
    period: str,
    steps: int = 1,
    next_label: str | None = None,
) -> pd.DataFrame:
    """Omzet periode depan = prediksi qty × harga jual rata-rata SKU itu."""
    hist_map = {key: grp for key, grp in history.groupby("item_key")}
    horizon = max(int(steps), 1)
    label = next_label or (qty_fc["next_period"].iloc[0] if not qty_fc.empty else "")
    records = []
    for _, item in qty_fc.iterrows():
        price, method = _expected_unit_price(hist_map.get(item["item_key"]), period, horizon)
        pred_qty = float(item["forecast"])
        pred_sales = float(max(int(np.floor(pred_qty * price + 0.5)), 0))
        records.append(
            {
                "item_key": item["item_key"],
                "item_label": item["item_label"],
                "metric": "sales",
                "best_model": method,
                "forecast": pred_sales,
                "mae": 0.0,
                "rmse": 0.0,
                "mape": 0.0,
                "history_points": int(item.get("history_points", 0)),
                "next_period": label,
                "horizon_steps": horizon,
            }
        )
    return pd.DataFrame.from_records(records)


def _report_window_days(history: pd.DataFrame) -> int:
    start = pd.Timestamp(history["period_start"].min()).normalize()
    end = pd.Timestamp(history["period_start"].max()).normalize()
    return max(int((end - start).days) + 1, 1)


PHI = 0.985
ROBUST_MIN_DAYS = 28
ROBUST_SHIFT = 0.15


def _dense_incomplete_tail(series: np.ndarray) -> bool:
    """Hari terakhir yang terpotong pada laporan padat, bukan hari nol SKU yang jarang laku."""
    series = np.asarray(series, dtype=float)
    if len(series) < 8 or float(np.mean(series > 0)) < 0.7:
        return False
    median = float(np.median(series[:-1]))
    return median > 0 and float(series[-1]) < 0.30 * median


def _cap_positive_spikes(series: np.ndarray) -> np.ndarray:
    """Potong hari yang jauh di atas penjualan biasa. Hari nol tetap nol."""
    series = np.asarray(series, dtype=float).copy()
    positive = series[series > 0]
    if len(positive) < 4:
        return series
    cap = float(np.quantile(positive, 0.90))
    if cap <= 0:
        return series
    return np.minimum(series, cap)


def _theil_sen_slope(series: np.ndarray) -> float:
    """Kemiringan median dari pasangan hari. Satu hari ekstrem tidak menggeser garis."""
    n = len(series)
    if n < 7:
        return 0.0
    stride = 1 if n <= 48 else max(1, n // 48)
    slopes: list[float] = []
    for left in range(0, n - 1, stride):
        base = float(series[left])
        for right in range(left + stride, n, stride):
            slopes.append((float(series[right]) - base) / (right - left))
    if not slopes:
        return 0.0
    return float(np.median(slopes))


def _limit_damped_slope(level: float, slope: float, horizon: int) -> float:
    """Redaman tidak boleh menjatuhkan atau menaikkan hari terjauh lebih dari 15% level."""
    if level <= 0 or slope == 0:
        return 0.0
    horizon = max(int(horizon), 1)
    multiplier = (1 - PHI**horizon) / (1 - PHI)
    if multiplier <= 0:
        return 0.0
    limit = ROBUST_SHIFT * level
    growth = slope * multiplier
    if abs(growth) <= limit:
        return float(slope)
    return float(np.sign(slope) * limit / multiplier)


def _robust_state(series: np.ndarray, horizon: int) -> tuple[float, float]:
    """Level tahan lonjakan dan kemiringan yang hanya hidup bila riwayatnya cukup."""
    raw = np.asarray(series, dtype=float)
    if len(raw) == 0:
        return 0.0, 0.0
    used = raw[:-1] if _dense_incomplete_tail(raw) else raw
    clean = _cap_positive_spikes(used)
    if len(clean) == 0 or float(clean.sum()) <= 0:
        return 0.0, 0.0
    level = float(clean.mean())
    if len(clean) < ROBUST_MIN_DAYS or level <= 0:
        return level, 0.0
    slope = _theil_sen_slope(clean) * min(1.0, len(clean) / 56.0)
    return level, _limit_damped_slope(level, slope, horizon)


def _series_end(series: np.ndarray, start: pd.Timestamp) -> pd.Timestamp:
    last_index = len(series) - (2 if _dense_incomplete_tail(series) else 1)
    return pd.Timestamp(start).normalize() + pd.Timedelta(days=max(last_index, 0))


def _project_path(
    series: np.ndarray,
    series_start: pd.Timestamp,
    dates: pd.DatetimeIndex,
    weekday: np.ndarray,
    horizon: int,
) -> np.ndarray:
    dates = pd.DatetimeIndex(dates)
    length = len(dates)
    level, slope = _robust_state(series, horizon)
    if length == 0 or level <= 0:
        return np.zeros(length, dtype=float)
    end = _series_end(series, series_start)
    path = np.empty(length, dtype=float)
    for index, day in enumerate(dates):
        stamp = pd.Timestamp(day).normalize()
        step = max(int((stamp - end).days), 1)
        growth = slope * ((1 - PHI**step) / (1 - PHI))
        factor = float(weekday[int(stamp.dayofweek)])
        path[index] = max(0.0, (level + growth) * factor)
    return path


def _weekday_profile(history: pd.DataFrame) -> np.ndarray:
    """Pola belanja per hari dalam seminggu. Lonjakan dan hari terakhir yang terpotong tidak masuk."""
    profile = np.ones(7, dtype=float)
    if history.empty:
        return profile
    daily = history.groupby(pd.to_datetime(history["period_start"]).dt.normalize())["qty"].sum().sort_index()
    values = daily.to_numpy(dtype=float)
    if _dense_incomplete_tail(values):
        daily = daily.iloc[:-1]
        values = daily.to_numpy(dtype=float)
    if len(values) >= 8:
        cap = float(np.quantile(values, 0.90))
        values = np.minimum(values, max(cap, 0.0))
    if len(values) == 0:
        return profile
    frame = pd.DataFrame({"qty": values, "dow": pd.to_datetime(daily.index).dayofweek})
    means = frame.groupby("dow")["qty"].mean()
    for dow, value in means.items():
        profile[int(dow)] = float(value)
    average = float(profile.mean())
    if average > 0:
        profile = profile / average
    return profile


def _trend_state(series: np.ndarray) -> tuple[float, float]:
    """Level harian dan kemiringan tren. Lonjakan ekstrem tidak ikut menarik garis tren."""
    length = len(series)
    total = float(series.sum())
    level = total / length if length else 0.0
    if length < 7 or total <= 0:
        return level, 0.0
    cap = float(np.quantile(series, 0.95)) if length >= 8 else float(series.max())
    capped = np.minimum(series, max(cap, 0.0))
    if length >= 14:
        mid = length // 2
        slope = (float(capped[mid:].mean()) - float(capped[:mid].mean())) / max(mid, 1)
    else:
        earlier = float(capped[:-7].mean()) if length > 7 else level
        slope = (float(capped[-7:].mean()) - earlier) / 7.0
    return level, slope


def residual_sigma(
    daily_qty: np.ndarray,
    start: pd.Timestamp,
    weekday: np.ndarray,
    horizon: int | None = None,
) -> float:
    """Simpangan penjualan harian terhadap tren robust. Lonjakan tetap di residual, jadi safety stock menutupnya."""
    series = np.asarray(daily_qty, dtype=float)
    if len(series) < 2 or float(series.sum()) <= 0:
        return 0.0
    used = series[:-1] if _dense_incomplete_tail(series) else series
    if len(used) < 2:
        return 0.0
    level, slope = _robust_state(series, max(int(horizon or len(used)), 1))
    origin = pd.Timestamp(start).normalize()
    center = (len(used) - 1) / 2.0
    fitted = np.empty(len(used), dtype=float)
    for index in range(len(used)):
        day = origin + pd.Timedelta(days=index)
        growth = slope * (index - center)
        factor = float(weekday[int(day.dayofweek)])
        fitted[index] = max(0.0, (level + growth) * factor)
    return float(np.std(used - fitted, ddof=1))


def _trend_forecast(
    daily_qty: np.ndarray,
    start: pd.Timestamp,
    horizon: int,
    weekday: np.ndarray,
    forecast_start: pd.Timestamp | None = None,
) -> float:
    """Prediksi dari perilaku harian: level, tren naik/turun, dan hari ramai.

    Lonjakan satu hari tidak digandakan. Tren paruh akhir terhadap paruh awal
    menggeser periode depan, dengan redaman supaya proyeksi setahun tidak meledak.
    """
    series = np.asarray(daily_qty, dtype=float)
    length = len(series)
    horizon = max(int(horizon), 1)
    if length == 0:
        return 0.0
    total = float(series.sum())
    if total <= 0:
        return 0.0
    level, slope = _trend_state(series)
    end = pd.Timestamp(start).normalize() + pd.Timedelta(days=length - 1)
    origin = pd.Timestamp(forecast_start).normalize() if forecast_start is not None else end + pd.Timedelta(days=1)
    if origin <= end:
        origin = end + pd.Timedelta(days=1)
    forecast = 0.0
    for offset in range(horizon):
        day = origin + pd.Timedelta(days=offset)
        step = max(int((day - end).days), 1)
        growth = slope * ((1 - PHI**step) / (1 - PHI))
        factor = float(weekday[int(day.dayofweek)])
        forecast += max(0.0, (level + growth) * factor)
    run_rate = level * horizon
    return float(np.clip(forecast, run_rate * 0.25, max(run_rate * 4.0, 1.0)))


def _robust_forecast(
    daily_qty: np.ndarray,
    start: pd.Timestamp,
    horizon: int,
    weekday: np.ndarray,
    forecast_start: pd.Timestamp | None = None,
) -> float:
    """Prediksi permintaan yang tidak ikut jatuh hanya karena jendela laporannya pendek.

    Level memakai hari yang sudah dipotong lonjakannya. Kemiringan baru dipakai
    bila riwayat minimal 28 hari, dan redaman tidak boleh menggeser hari terjauh
    lebih dari 15% level. Hari terakhir yang terpotong tidak menarik garis.
    """
    series = np.asarray(daily_qty, dtype=float)
    horizon = max(int(horizon), 1)
    if len(series) == 0 or float(series.sum()) <= 0:
        return 0.0
    end = _series_end(series, start)
    origin = pd.Timestamp(forecast_start).normalize() if forecast_start is not None else end + pd.Timedelta(days=1)
    if origin <= end:
        origin = end + pd.Timedelta(days=1)
    dates = pd.date_range(origin, periods=horizon, freq="D")
    total = float(_project_path(series, start, dates, weekday, horizon).sum())
    level, _slope = _robust_state(series, horizon)
    run_rate = level * horizon
    if run_rate <= 0:
        return total
    return float(np.clip(total, run_rate * 0.6, max(run_rate * 1.6, 1.0)))


def forecast_calendar(
    daily_qty: np.ndarray,
    series_start: pd.Timestamp,
    dates: pd.DatetimeIndex,
    weekday: np.ndarray,
    target_total: float,
) -> np.ndarray:
    """Sebar prediksi pada tanggal kalender. Jumlahnya sama dengan prediksi periode."""
    dates = pd.DatetimeIndex(dates)
    length = len(dates)
    if length == 0 or float(target_total) <= 0:
        return np.zeros(length, dtype=float)
    series = np.asarray(daily_qty, dtype=float)
    if len(series) == 0 or float(series.sum()) <= 0:
        return np.full(length, float(target_total) / length)
    path = _project_path(series, series_start, dates, weekday, length)
    raw = float(path.sum())
    if raw <= 0:
        return np.full(length, float(target_total) / length)
    return path * (float(target_total) / raw)


def compare_daily_algorithms(history: pd.DataFrame) -> pd.DataFrame:
    """Bandingkan algoritma pada total penjualan harian. Tren harian yang dipakai di prediksi."""
    if history.empty or "period_start" not in history.columns or "qty" not in history.columns:
        return pd.DataFrame()
    dates = pd.to_datetime(history["period_start"]).dt.normalize()
    daily = history.assign(_day=dates).groupby("_day", as_index=True)["qty"].sum().sort_index()
    if daily.empty:
        return pd.DataFrame()
    calendar = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    series = daily.reindex(calendar, fill_value=0.0).to_numpy(dtype=float)
    length = len(series)
    if length < 8:
        return pd.DataFrame()
    hold = 7 if length >= 21 else max(2, length // 5)
    train = series[:-hold]
    actual_total = float(series[-hold:].sum())
    train_start = pd.Timestamp(calendar[0])
    forecast_start = pd.Timestamp(calendar[-hold])
    train_hist = pd.DataFrame({"period_start": calendar[:-hold], "qty": train})
    weekday = _weekday_profile(train_hist)

    def gap(pred_total: float) -> float:
        if actual_total <= 0:
            return abs(float(pred_total))
        return abs(actual_total - float(pred_total)) / actual_total * 100

    rows: list[dict[str, object]] = []
    robust_total = _robust_forecast(train, train_start, hold, weekday, forecast_start=forecast_start)
    rows.append(
        {
            "Algoritma": "Tren robust",
            "Perkiraan ujian": round(robust_total, 1),
            "Actual ujian": round(actual_total, 1),
            "Selisih (%)": round(gap(robust_total), 1),
            "Peran": "Dipakai",
        }
    )
    trend_total = _trend_forecast(train, train_start, hold, weekday, forecast_start=forecast_start)
    rows.append(
        {
            "Algoritma": "Tren harian",
            "Perkiraan ujian": round(trend_total, 1),
            "Actual ujian": round(actual_total, 1),
            "Selisih (%)": round(gap(trend_total), 1),
            "Peran": "Pembanding",
        }
    )
    naive = float(train[-1] * hold)
    rows.append(
        {
            "Algoritma": "Naive",
            "Perkiraan ujian": round(naive, 1),
            "Actual ujian": round(actual_total, 1),
            "Selisih (%)": round(gap(naive), 1),
            "Peran": "Pembanding",
        }
    )
    window = min(7, len(train))
    moving = float(np.mean(train[-window:]) * hold)
    rows.append(
        {
            "Algoritma": "Moving Average",
            "Perkiraan ujian": round(moving, 1),
            "Actual ujian": round(actual_total, 1),
            "Selisih (%)": round(gap(moving), 1),
            "Peran": "Pembanding",
        }
    )
    builders = [lambda: _holt_winters(train, 7, hold)]
    if 12 <= len(train) <= 90:
        builders.extend([lambda: _sarima(train, 7, hold), lambda: _xgboost_forecast(train, hold)])
    for builder in builders:
        try:
            result = builder()
        except Exception:
            result = None
        if result is None or not result.fitted:
            continue
        rows.append(
            {
                "Algoritma": result.name,
                "Perkiraan ujian": round(float(result.forecast), 1),
                "Actual ujian": round(actual_total, 1),
                "Selisih (%)": round(gap(float(result.forecast)), 1),
                "Peran": "Pembanding",
            }
        )
    table = pd.DataFrame(rows).sort_values(["Selisih (%)", "Algoritma"]).reset_index(drop=True)
    return table


def forecast_items(
    history: pd.DataFrame,
    period: str,
    metric: str,
    min_points: int | None = None,
    progress_callback=None,
    steps: int = 1,
    next_label: str | None = None,
    forecast_start: pd.Timestamp | None = None,
) -> pd.DataFrame:
    spec = PERIOD_SPECS[period]
    threshold = min_points if min_points is not None else spec.min_points
    horizon = max(int(steps), 1)
    if next_label is None:
        last_start = history["period_start"].max()
        nxt = next_period_start(last_start, period)
        next_label = period_label(nxt, period)
    rows: list[ItemForecast] = []
    error_sigma: dict[str, float] = {}
    groups = list(history.groupby("item_key", sort=False))
    total = max(len(groups), 1)
    short_window = period == "hari" and not history.empty
    window_days = _report_window_days(history) if short_window else 1
    calendar = (
        pd.date_range(
            pd.Timestamp(history["period_start"].min()).normalize(),
            pd.Timestamp(history["period_start"].max()).normalize(),
            freq="D",
        )
        if short_window
        else pd.DatetimeIndex([])
    )
    weekday = _weekday_profile(history) if short_window else np.ones(7)
    for idx, (item_key, item_hist) in enumerate(groups):
        if progress_callback:
            progress_callback((idx + 1) / total)
        if short_window:
            sold = float(item_hist["qty"].sum())
            by_day = item_hist.groupby(pd.to_datetime(item_hist["period_start"]).dt.normalize())["qty"].sum()
            daily = by_day.reindex(calendar, fill_value=0.0).to_numpy(dtype=float)
            raw = _robust_forecast(daily, calendar[0], horizon, weekday, forecast_start=forecast_start)
            error_sigma[item_key] = residual_sigma(daily, calendar[0], weekday, horizon=horizon)
            forecast_value = float(max(int(np.floor(raw + 0.5)), 1 if sold > 0 else 0))
            rows.append(
                ItemForecast(
                    item_key=item_key,
                    item_label=str(item_hist["item_label"].iloc[0]),
                    metric=metric,
                    best_model="Tren robust",
                    forecast=forecast_value,
                    mae=0.0,
                    rmse=0.0,
                    mape=0.0,
                    history_points=window_days,
                    next_period=next_label,
                    candidates=[
                        ModelResult(
                            "Tren robust",
                            forecast_value,
                            0.0,
                            0.0,
                            0.0,
                            True,
                            "level tahan lonjakan, kemiringan hanya bila riwayat cukup",
                        )
                    ],
                )
            )
            continue
        dense = dense_item_series(item_hist, period)
        values = dense[metric].to_numpy(dtype=float)
        if len(values) < 2:
            level = float(values[-1]) if len(values) else 0.0
            best = ModelResult("Baseline periode", level * horizon, 0.0, 0.0, 0.0, True, "histori pendek")
            candidates = [best]
        elif len(values) < threshold:
            candidates = [
                _naive_forecast(values, spec.season_length, horizon),
                _moving_average(values, horizon),
            ]
            best = min(candidates, key=lambda c: (c.mape, c.rmse))
        else:
            best, candidates = forecast_series(values, period, horizon)
        forecast_value = _whole_units(best.forecast, values, horizon, metric)
        if forecast_value != best.forecast and float(np.sum(values)) > 0 and best.forecast <= 0:
            best = ModelResult(
                "Rata-rata periode",
                forecast_value,
                best.mae,
                best.rmse,
                best.mape,
                True,
                "model terpilih jatuh di hari kosong",
            )
        rows.append(
            ItemForecast(
                item_key=item_key,
                item_label=str(item_hist["item_label"].iloc[0]),
                metric=metric,
                best_model=best.name,
                forecast=forecast_value,
                mae=best.mae,
                rmse=best.rmse,
                mape=best.mape,
                history_points=int(len(values)),
                next_period=next_label,
                candidates=candidates,
            )
        )
    records = []
    for row in rows:
        records.append(
            {
                "item_key": row.item_key,
                "item_label": row.item_label,
                "metric": row.metric,
                "best_model": row.best_model,
                "forecast": row.forecast,
                "mae": row.mae,
                "rmse": row.rmse,
                "mape": row.mape,
                "history_points": row.history_points,
                "next_period": row.next_period,
                "horizon_steps": horizon,
                "error_sigma": float(error_sigma.get(row.item_key, 0.0)),
            }
        )
    result = pd.DataFrame.from_records(records)
    result.attrs["details"] = {row.item_key: row for row in rows}
    return result
