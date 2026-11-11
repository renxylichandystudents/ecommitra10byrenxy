"""Satu jendela prediksi dan label periode dinamis (Revisi Final 2B)."""

from __future__ import annotations

from datetime import date

import pandas as pd

PERIOD_MONTHS = {"bulan": 1, "kuartal": 3, "semester": 6, "tahun": 12}
MONTHS_SHORT = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")


ROMAN = ("I", "II", "III", "IV")


def calendar_period(period: str, day: date) -> tuple[date, date, str]:
    """Periode kalender yang memuat `day`: kuartal Jan–Mar/Apr–Jun/Jul–Sep/Okt–Des, semester Jan–Jun/Jul–Des, tahun Jan–Des."""
    if period == "kuartal":
        index = (day.month - 1) // 3
        first_month = index * 3 + 1
        start = date(day.year, first_month, 1)
        end = (pd.Timestamp(start) + pd.DateOffset(months=3) - pd.Timedelta(days=1)).date()
        label = f"Kuartal {ROMAN[index]} {day.year} ({MONTHS_SHORT[first_month - 1]}–{MONTHS_SHORT[first_month + 1]})"
        return start, end, label
    if period == "semester":
        half = 0 if day.month <= 6 else 1
        start = date(day.year, 1 if half == 0 else 7, 1)
        end = date(day.year, 6, 30) if half == 0 else date(day.year, 12, 31)
        label = f"Semester {half + 1} {day.year} ({'Jan–Jun' if half == 0 else 'Jul–Des'})"
        return start, end, label
    if period == "tahun":
        return date(day.year, 1, 1), date(day.year, 12, 31), f"Tahun {day.year}"
    start = date(day.year, day.month, 1)
    return start, (pd.Timestamp(start) + pd.offsets.MonthEnd(0)).date(), month_year(day)


def previous_calendar_period(period: str, day: date) -> tuple[date, date, str]:
    start, _end, _label = calendar_period(period, day)
    return calendar_period(period, (pd.Timestamp(start) - pd.Timedelta(days=1)).date())


def prediction_window(period: str, today: date) -> tuple[date, date]:
    """Jendela prediksi. Bulan: 30 hari ke depan (2 Nov → 2 Nov – 1 Des). Kuartal/Semester/Tahun: dari hari ini
    sampai akhir periode kalender (7 Nov 2026, Kuartal → 7 Nov – 31 Des 2026 = sisa Kuartal IV)."""
    if period in {"kuartal", "semester", "tahun"}:
        return today, calendar_period(period, today)[1]
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

    - "prediksi": "Prediksi 30 hari (11 Nov – 10 Des 2026)" (jendela prediksi bulan, bukan bulan kalender)
    - "aktual_bulan": "Aktual Okt 2026" (bulan penuh terakhir)
    - "aktual_hari": "Aktual 27 Okt 2026" (hari terakhir transaksi)
    - "bulan_lalu": "Tanggal sama bulan lalu (2 Okt 2026)"
    """
    if kind == "prediksi":
        lo, hi = prediction_window("bulan", day)
        head = f"{lo.day} {MONTHS_SHORT[lo.month - 1]}" + (f" {lo.year}" if lo.year != hi.year else "")
        return f"Prediksi {(hi - lo).days + 1} hari ({head} – {short_date(hi)})"
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
