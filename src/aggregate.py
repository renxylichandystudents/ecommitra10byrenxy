from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


PERIOD_OPTIONS = ("bulan", "kuartal", "semester", "tahun")


@dataclass(frozen=True)
class PeriodSpec:
    key: str
    freq: str
    label: str
    min_points: int
    season_length: int


PERIOD_SPECS: dict[str, PeriodSpec] = {
    "bulan": PeriodSpec("bulan", "MS", "Bulan", min_points=8, season_length=12),
    "kuartal": PeriodSpec("kuartal", "QS", "Kuartal", min_points=6, season_length=4),
    "semester": PeriodSpec("semester", "2QS", "Semester", min_points=4, season_length=2),
    "tahun": PeriodSpec("tahun", "YS", "Tahun", min_points=3, season_length=1),
    "hari": PeriodSpec("hari", "D", "Hari", min_points=8, season_length=7),
}

HORIZON_MONTHS = {"bulan": 1, "kuartal": 3, "semester": 6, "tahun": 12}
HORIZON_DAYS = {"bulan": 30, "kuartal": 91, "semester": 182, "tahun": 365}
HORIZON_TEXT = {
    "bulan": "1 bulan ke depan",
    "kuartal": "1 kuartal (3 bulan) ke depan",
    "semester": "1 semester (6 bulan) ke depan",
    "tahun": "1 tahun ke depan",
}


def forecast_grain(order_times: pd.Series, period: str) -> tuple[str, int]:
    """Pilih butir deret dan jumlah langkah agar prediksi sepanjang periode yang dipilih.

    Laporan dengan minimal 3 bulan dipakai bulanan (musim lebih stabil).
    Laporan yang lebih pendek dihitung harian, lalu dijumlahkan sepanjang periode.
    """
    months = pd.to_datetime(order_times).dt.to_period("M").nunique()
    if months >= 3:
        return "bulan", HORIZON_MONTHS[period]
    return "hari", HORIZON_DAYS[period]


def period_start(series: pd.Series, period: str) -> pd.Series:
    dates = pd.to_datetime(series)
    if period == "hari":
        return dates.dt.floor("D")
    if period == "bulan":
        return dates.dt.to_period("M").dt.to_timestamp()
    if period == "kuartal":
        return dates.dt.to_period("Q").dt.to_timestamp()
    if period == "semester":
        month = dates.dt.month
        start_month = month.map(lambda m: 1 if m <= 6 else 7)
        return pd.to_datetime(dict(year=dates.dt.year, month=start_month, day=1))
    if period == "tahun":
        return dates.dt.to_period("Y").dt.to_timestamp()
    raise ValueError(f"Periode tidak dikenali: {period}")


def period_label(ts: pd.Timestamp, period: str) -> str:
    stamp = pd.Timestamp(ts)
    if period == "hari":
        return stamp.strftime("%Y-%m-%d")
    if period == "bulan":
        return stamp.strftime("%Y-%m")
    if period == "kuartal":
        return f"{stamp.year}-Q{stamp.quarter}"
    if period == "semester":
        half = 1 if stamp.month <= 6 else 2
        return f"{stamp.year}-S{half}"
    if period == "tahun":
        return str(stamp.year)
    return str(stamp.date())


def next_period_start(last_start: pd.Timestamp, period: str) -> pd.Timestamp:
    stamp = pd.Timestamp(last_start)
    if period == "hari":
        return stamp + pd.Timedelta(days=1)
    if period == "bulan":
        return stamp + pd.offsets.MonthBegin(1)
    if period == "kuartal":
        return stamp + pd.offsets.QuarterBegin(startingMonth=1)
    if period == "semester":
        return stamp + pd.DateOffset(months=6)
    if period == "tahun":
        return stamp + pd.DateOffset(years=1)
    raise ValueError(f"Periode tidak dikenali: {period}")


def aggregate_item_periods(df: pd.DataFrame, period: str) -> pd.DataFrame:
    work = df.copy()
    work["period_start"] = period_start(work["order_time"], period)
    grouped = (
        work.groupby(["item_key", "item_label", "period_start"], as_index=False)
        .agg(qty=("qty", "sum"), sales=("sales", "sum"), orders=("order_id", "nunique"))
        .sort_values(["item_key", "period_start"])
    )
    grouped["period_label"] = grouped["period_start"].map(lambda ts: period_label(ts, period))
    return grouped


def dense_item_series(item_history: pd.DataFrame, period: str) -> pd.DataFrame:
    if item_history.empty:
        return item_history
    start = item_history["period_start"].min()
    end = item_history["period_start"].max()
    if period == "hari":
        idx = pd.date_range(start, end, freq="D")
    elif period == "bulan":
        idx = pd.date_range(start, end, freq="MS")
    elif period == "kuartal":
        idx = pd.date_range(start, end, freq="QS")
    elif period == "semester":
        stamps = []
        cursor = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        while cursor <= end_ts:
            stamps.append(cursor)
            cursor = cursor + pd.DateOffset(months=6)
        idx = pd.DatetimeIndex(stamps)
    else:
        idx = pd.date_range(start, end, freq="YS")

    base = item_history.set_index("period_start")
    filled = base.reindex(idx)
    filled["item_key"] = item_history["item_key"].iloc[0]
    filled["item_label"] = item_history["item_label"].iloc[0]
    filled["qty"] = filled["qty"].fillna(0.0)
    filled["sales"] = filled["sales"].fillna(0.0)
    filled["orders"] = filled["orders"].fillna(0)
    filled = filled.reset_index().rename(columns={"index": "period_start"})
    filled["period_label"] = filled["period_start"].map(lambda ts: period_label(ts, period))
    return filled


def catalog_from_orders(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(["item_key", "item_label"], as_index=False)
        .agg(
            sku=("sku", "first"),
            product_name=("product_name", "first"),
            variation=("variation", "first"),
        )
        .sort_values("item_label")
    )
