from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from src.core.inventory import average_net_price_last_4_weeks, current_month_forecast, predict_sales_from_qty, rolling_horizon


HORIZON_MONTHS = {"bulan": 1, "kuartal": 3, "semester": 6, "tahun": 12}


@dataclass(frozen=True)
class ForecastHorizon:
    period: str
    start: pd.Timestamp
    end: pd.Timestamp
    days: int
    label: str


def horizon_for_period(period: str, today: date | None = None) -> ForecastHorizon:
    if period not in HORIZON_MONTHS:
        raise ValueError(f"Periode tidak dikenali: {period}")
    ref = today or date.today()
    start, end, days = rolling_horizon(ref, HORIZON_MONTHS[period])
    label = f"{start.date()} - {end.date()}"
    return ForecastHorizon(period=period, start=start, end=end, days=days, label=label)


def current_month_projection(
    orders: pd.DataFrame,
    daily_forecast: pd.DataFrame,
    *,
    today: date | None = None,
    sku_col: str = "item_key",
    order_date_col: str = "order_time",
    qty_col: str = "qty",
    forecast_date_col: str = "date",
    forecast_qty_col: str = "pred_qty",
) -> pd.DataFrame:
    """Prediksi bulan kalender berjalan = realisasi 1 s.d. kemarin + prediksi sisa bulan."""
    ref = pd.Timestamp(today or date.today()).normalize()
    month_start = ref.replace(day=1)
    yesterday = ref - pd.Timedelta(days=1)
    if orders is None or orders.empty or sku_col not in orders.columns:
        actual = pd.DataFrame(columns=[sku_col, "actual_month_to_yesterday"])
    else:
        work = orders.copy()
        work[order_date_col] = pd.to_datetime(work[order_date_col], errors="coerce")
        work = work.loc[work[order_date_col].between(month_start, yesterday, inclusive="both")]
        actual = work.groupby(sku_col, as_index=False).agg(actual_month_to_yesterday=(qty_col, "sum"))
    if daily_forecast is None or daily_forecast.empty or sku_col not in daily_forecast.columns:
        remaining = pd.DataFrame(columns=[sku_col, "pred_remaining_month"])
    else:
        future = daily_forecast.copy()
        future[forecast_date_col] = pd.to_datetime(future[forecast_date_col], errors="coerce")
        month_end = month_start + pd.offsets.MonthEnd(0)
        future = future.loc[future[forecast_date_col].between(ref, month_end, inclusive="both")]
        remaining = future.groupby(sku_col, as_index=False).agg(pred_remaining_month=(forecast_qty_col, "sum"))
    merged = actual.merge(remaining, on=sku_col, how="outer").fillna(0.0)
    merged["pred_bulan_ini"] = [
        current_month_forecast(actual_value, remaining_value)
        for actual_value, remaining_value in zip(
            merged["actual_month_to_yesterday"],
            merged["pred_remaining_month"],
        )
    ]
    return merged


def enforce_month_forecast_floor(
    forecast: pd.DataFrame,
    actual: pd.DataFrame,
    *,
    sku_col: str = "item_key",
    forecast_col: str = "pred_bulan_ini",
    actual_col: str = "actual_month_to_yesterday",
) -> pd.DataFrame:
    if forecast is None or forecast.empty:
        return pd.DataFrame()
    out = forecast.copy()
    if actual is not None and not actual.empty:
        out = out.merge(actual[[sku_col, actual_col]], on=sku_col, how="left")
    if actual_col not in out.columns:
        out[actual_col] = 0.0
    out[forecast_col] = np.maximum(out[forecast_col].astype(float), out[actual_col].fillna(0.0).astype(float))
    return out


def sales_forecast_from_recent_price(
    orders: pd.DataFrame,
    qty_forecast: pd.DataFrame,
    *,
    today: date | None = None,
    sku_col: str = "item_key",
) -> pd.DataFrame:
    price = average_net_price_last_4_weeks(orders, sku_col=sku_col, as_of=today)
    return predict_sales_from_qty(qty_forecast, price, sku_col=sku_col)


def forecast_snapshot_frame(frame: pd.DataFrame, *, run_date: date | None = None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out["run_date"] = pd.Timestamp(run_date or date.today()).date().isoformat()
    expected = ["run_date", "item_key", "item_label", "pred_qty", "pred_sales", "safety_stock", "kebutuhan", "rop"]
    for column in expected:
        if column not in out.columns:
            out[column] = 0 if column not in {"run_date", "item_key", "item_label"} else ""
    return out[expected].copy()

