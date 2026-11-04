"""Data performa toko Shopee: satu baris per hari, angka format Indonesia jadi numerik.

Ekspor Shopee memuat baris total bulanan ("01-10-2026-31-10-2026") dan header berulang di bawah
header utama. Baris seperti itu bukan data harian dan harus dibuang sebelum dijumlah/dirata-rata.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import pandas as pd

from src.core.schemas import PERFORMANCE_ALIASES

NUMERIC_FIELDS = tuple(field for field in PERFORMANCE_ALIASES if field != "date")
_DAY_FIRST = re.compile(r"^\d{1,2}[-/.]\d{1,2}[-/.]\d{4}$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}([ T].*)?$")


def parse_day(series: pd.Series) -> pd.Series:
    """Tanggal tunggal (dd-mm-yyyy, yyyy-mm-dd, atau sel tanggal Excel). Rentang/teks lain jadi NaT."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce").dt.normalize()
    out = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    stamps = series.map(lambda value: isinstance(value, (datetime, date)))
    if stamps.any():
        out.loc[stamps] = pd.to_datetime(series.loc[stamps], errors="coerce")
    text = series.loc[~stamps].astype(str).str.strip()
    day_first = text.str.match(_DAY_FIRST)
    if day_first.any():
        normalized = text.loc[day_first].str.replace(r"[/.]", "-", regex=True)
        out.loc[normalized.index] = pd.to_datetime(normalized, format="%d-%m-%Y", errors="coerce")
    iso = text.str.match(_ISO) & ~day_first
    if iso.any():
        out.loc[iso[iso].index] = pd.to_datetime(text.loc[iso].str[:10], format="%Y-%m-%d", errors="coerce")
    return out.dt.normalize()


def _token(value: object) -> float:
    from src.ingest import _parse_number_token

    if isinstance(value, str):
        value = value.replace("%", "")
    return _parse_number_token(value)


def perf_number(series: pd.Series) -> pd.Series:
    """Angka performa: '165.841.669' -> 165841669, '727.375,74' -> 727375.74, '1,40%' -> 1.40 (persen)."""
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    return series.map(_token).astype(float)


def is_daily_row(frame: pd.DataFrame, date_column: str) -> pd.Series:
    """True untuk baris harian; False untuk total bulanan, header berulang, atau tanggal kosong."""
    if date_column not in frame.columns:
        return pd.Series(True, index=frame.index)
    return parse_day(frame[date_column]).notna()


def clean_performance(frame: pd.DataFrame | None) -> pd.DataFrame:
    """Kolom kanonik 'date' jadi tanggal, kolom angka jadi float, satu baris per tanggal (unggahan terbaru menang)."""
    if frame is None or frame.empty or "date" not in frame.columns:
        return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    work = frame.copy()
    work["date"] = parse_day(work["date"])
    work = work.loc[work["date"].notna()]
    for field in NUMERIC_FIELDS:
        if field in work.columns:
            work[field] = perf_number(work[field])
    order = "_submitted_at" if "_submitted_at" in work.columns else None
    if order:
        work = work.sort_values(order, kind="stable")
    work = work.drop_duplicates("date", keep="last").sort_values("date")
    return work.reset_index(drop=True)
