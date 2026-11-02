"""Satu jendela prediksi dan label periode dinamis (Revisi Final 2B)."""

from __future__ import annotations

from datetime import date

import pandas as pd

PERIOD_MONTHS = {"bulan": 1, "kuartal": 3, "semester": 6, "tahun": 12}
MONTHS_SHORT = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")


def prediction_window(period: str, today: date) -> tuple[date, date]:
    """Jendela prediksi dari Pengaturan bisnis. Bulan, dijalankan 2 Nov 2026 → 2 Nov – 1 Des 2026."""
    months = PERIOD_MONTHS.get(period, 1)
    end = (pd.Timestamp(today) + pd.DateOffset(months=months) - pd.Timedelta(days=1)).date()
    return today, end


def window_days(period: str, today: date) -> int:
    start, end = prediction_window(period, today)
    return (end - start).days + 1


def month_year(day: date) -> str:
    return f"{MONTHS_SHORT[day.month - 1]} {day.year}"


def short_date(day: date) -> str:
    return f"{day.day} {MONTHS_SHORT[day.month - 1]} {day.year}"


def last_full_month(data_until: date) -> tuple[date, date]:
    """Bulan penuh terakhir sebelum/sama dengan `data_until` (data s.d. 31 Okt → Oktober; s.d. 27 Okt → September)."""
    stamp = pd.Timestamp(data_until)
    if (stamp + pd.Timedelta(days=1)).month != stamp.month:
        first = stamp.replace(day=1)
    else:
        first = (stamp.replace(day=1) - pd.DateOffset(months=1))
    last = first + pd.offsets.MonthEnd(0)
    return first.date(), last.date()


def same_day_last_month(day: date) -> date:
    return (pd.Timestamp(day) - pd.DateOffset(months=1)).date()


def format_period_label(kind: str, day: date) -> str:
    """Label eksplisit pengganti "Bulan ini", "Kemarin", "Bulan lalu".

    - "prediksi": "Prediksi Nov 2026" (awal jendela prediksi)
    - "aktual_bulan": "Aktual Okt 2026" (bulan penuh terakhir)
    - "aktual_hari": "Aktual 27 Okt 2026" (hari terakhir transaksi)
    - "bulan_lalu": "Tanggal sama bulan lalu (2 Okt 2026)"
    """
    if kind == "prediksi":
        return f"Prediksi {month_year(day)}"
    if kind == "aktual_bulan":
        return f"Aktual {month_year(day)}"
    if kind == "aktual_hari":
        return f"Aktual {short_date(day)}"
    if kind == "bulan_lalu":
        return f"Tanggal sama bulan lalu ({short_date(day)})"
    raise ValueError(kind)


def same_target(previous_start: date | None, previous_period: str | None, start: date, period: str) -> bool:
    """Perbandingan "dibanding prediksi kemarin" hanya sah bila target periodenya sama
    (periode prediksi sama dan jendela dimulai di bulan yang sama, mis. keduanya "Prediksi Nov 2026")."""
    if previous_start is None or previous_period != period:
        return False
    return (previous_start.year, previous_start.month) == (start.year, start.month)
