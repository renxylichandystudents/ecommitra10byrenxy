from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import NormalDist

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class InventoryResult:
    forecast_qty: float
    safety_stock: float
    kebutuhan: float
    current_stock: float
    selisih_stok: float
    selisih_pct: float
    status_stok: str
    below_safety_stock: bool
    hari_cukup: float
    rop: float


def service_level_to_z(percent: float) -> float:
    level = float(percent)
    if level <= 0:
        return 0.0
    if level >= 100:
        return NormalDist().inv_cdf(0.999) * (level / 100.0)
    return NormalDist().inv_cdf(level / 100.0)


def safety_stock_general(
    *,
    z: float,
    d_avg: float,
    sigma_d: float,
    l_avg: float,
    sigma_l: float,
) -> float:
    value = float(z) * np.sqrt(max(float(l_avg), 0.0) * float(sigma_d) ** 2 + float(d_avg) ** 2 * float(sigma_l) ** 2)
    return float(max(value, 0.0))


def safety_stock_local(*, z: float, sigma_d: float, lead_time_days: float) -> float:
    return float(max(float(z) * float(sigma_d) * np.sqrt(max(float(lead_time_days), 0.0)), 0.0))


def safety_stock_import(*, l_max: float, l_avg: float, d_avg: float) -> float:
    return float(max((float(l_max) - float(l_avg)) * float(d_avg), 0.0))


def reorder_point(*, d_avg: float, l_avg: float, safety_stock: float) -> float:
    return float(max(float(d_avg) * float(l_avg) + float(safety_stock), 0.0))


def inventory_status(current_stock: float, kebutuhan: float, safety_stock: float) -> tuple[str, bool]:
    stock = float(current_stock)
    need = max(float(kebutuhan), 0.0)
    ss = max(float(safety_stock), 0.0)
    below_ss = stock < ss
    if stock <= 0:
        return "Kosong", below_ss
    if need <= 0:
        return ("di bawah SS" if below_ss else "Aman"), below_ss
    gap = need - stock
    if gap <= 0:
        return ("di bawah SS" if below_ss else "Aman"), below_ss
    shortage_pct = gap / need
    if shortage_pct <= 0.10:
        return ("Tipis · di bawah SS" if below_ss else "Tipis"), below_ss
    return ("Kurang · di bawah SS" if below_ss else "Kurang"), below_ss


def days_cover(current_stock: float, daily_avg: float) -> float:
    demand = float(daily_avg)
    if demand <= 0:
        return float("inf") if float(current_stock) > 0 else 0.0
    return float(max(float(current_stock), 0.0) / demand)


def inventory_decision(
    *,
    forecast_qty: float,
    current_stock: float,
    sigma_d: float,
    service_level_pct: float,
    horizon_days: int,
    lead_time_days: float = 7.0,
    sigma_l: float = 0.0,
    source_type: str = "local",
    l_max: float | None = None,
) -> InventoryResult:
    horizon = max(int(horizon_days), 1)
    forecast = max(float(forecast_qty), 0.0)
    d_avg = forecast / horizon
    z = service_level_to_z(service_level_pct)
    if source_type == "import":
        ss = safety_stock_import(l_max=float(l_max or lead_time_days), l_avg=lead_time_days, d_avg=d_avg)
    elif sigma_l > 0:
        ss = safety_stock_general(z=z, d_avg=d_avg, sigma_d=sigma_d, l_avg=lead_time_days, sigma_l=sigma_l)
    else:
        ss = safety_stock_local(z=z, sigma_d=sigma_d, lead_time_days=lead_time_days)
    need = forecast + ss
    stock = max(float(current_stock), 0.0)
    gap = stock - need
    pct = gap / need if need > 0 else 0.0
    status, below_ss = inventory_status(stock, need, ss)
    cover = days_cover(stock, d_avg)
    rop = reorder_point(d_avg=d_avg, l_avg=lead_time_days, safety_stock=ss)
    return InventoryResult(
        forecast_qty=forecast,
        safety_stock=ss,
        kebutuhan=need,
        current_stock=stock,
        selisih_stok=gap,
        selisih_pct=pct,
        status_stok=status,
        below_safety_stock=below_ss,
        hari_cukup=cover,
        rop=rop,
    )


def current_month_forecast(actual_to_yesterday: float, predicted_remaining: float) -> float:
    actual = max(float(actual_to_yesterday), 0.0)
    remaining = max(float(predicted_remaining), 0.0)
    return max(actual + remaining, actual)


def rolling_horizon(today: date, months: int) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    start = pd.Timestamp(today).normalize()
    end = start + pd.DateOffset(months=int(months)) - pd.Timedelta(days=1)
    return start, end, int((end - start).days) + 1


def average_net_price_last_4_weeks(
    orders: pd.DataFrame,
    *,
    sku_col: str = "item_key",
    date_col: str = "order_time",
    qty_col: str = "qty",
    sales_col: str = "sales",
    as_of: date | None = None,
) -> pd.DataFrame:
    columns = [sku_col, "avg_net_price_4w"]
    if orders is None or orders.empty or not {sku_col, date_col, qty_col, sales_col} <= set(orders.columns):
        return pd.DataFrame(columns=columns)
    work = orders.copy()
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    end = pd.Timestamp(as_of or date.today()).normalize()
    last_data = work[date_col].max()
    if pd.notna(last_data):
        end = min(end, pd.Timestamp(last_data).normalize() + pd.Timedelta(days=1))
    start = end - pd.Timedelta(days=28)
    work = work.loc[work[date_col].between(start, end, inclusive="left")]
    if work.empty:
        return pd.DataFrame(columns=columns)
    grouped = work.groupby(sku_col, as_index=False).agg(qty=(qty_col, "sum"), sales=(sales_col, "sum"))
    grouped["avg_net_price_4w"] = np.where(grouped["qty"].gt(0), grouped["sales"] / grouped["qty"], 0.0)
    return grouped[[sku_col, "avg_net_price_4w"]]


def predict_sales_from_qty(forecast_qty: pd.DataFrame, price_4w: pd.DataFrame, *, sku_col: str = "item_key") -> pd.DataFrame:
    if forecast_qty is None or forecast_qty.empty:
        return pd.DataFrame()
    out = forecast_qty.copy()
    price = price_4w[[sku_col, "avg_net_price_4w"]] if price_4w is not None and not price_4w.empty else pd.DataFrame(columns=[sku_col, "avg_net_price_4w"])
    out = out.merge(price, on=sku_col, how="left")
    out["avg_net_price_4w"] = out["avg_net_price_4w"].fillna(0.0)
    qty_col = "pred_qty" if "pred_qty" in out.columns else ("forecast" if "forecast" in out.columns else None)
    if qty_col is None:
        out["pred_sales"] = 0.0
    else:
        out["pred_sales"] = out[qty_col].astype(float).clip(lower=0) * out["avg_net_price_4w"]
    return out


def stock_zero_duration(stock_snapshots: pd.DataFrame, *, sku_col: str = "sku", stock_col: str = "stock_dc_cikupa", today: date | None = None) -> pd.DataFrame:
    if stock_snapshots is None or stock_snapshots.empty or "_submitted_at" not in stock_snapshots.columns:
        return pd.DataFrame(columns=[sku_col, "zero_since", "lama_kosong_hari"])
    work = stock_snapshots.copy()
    work["_submitted_at"] = pd.to_datetime(work["_submitted_at"], errors="coerce")
    work[stock_col] = pd.to_numeric(work[stock_col], errors="coerce").fillna(0.0)
    work = work.dropna(subset=["_submitted_at"]).sort_values([sku_col, "_submitted_at"])
    ref = pd.Timestamp(today or date.today()).normalize()
    rows: list[dict[str, object]] = []
    for sku, group in work.groupby(sku_col, sort=False):
        if group.empty or float(group.iloc[-1][stock_col]) > 0:
            continue
        zero_rows = []
        for _, row in group.iloc[::-1].iterrows():
            if float(row[stock_col]) > 0:
                break
            zero_rows.append(row)
        if not zero_rows:
            continue
        since = min(pd.Timestamp(row["_submitted_at"]).normalize() for row in zero_rows)
        rows.append({sku_col: sku, "zero_since": since.date(), "lama_kosong_hari": max(int((ref - since).days), 0)})
    return pd.DataFrame(rows)

