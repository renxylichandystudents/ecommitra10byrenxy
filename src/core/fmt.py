"""Format tampilan Indonesia (Revisi Final S4): 1.234 · 16,11% · Rp 1.234.567 · 2 Nov 2026 · 02/11/2026."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from src.utils.format import EMPTY, angka, persen, rupiah

MONTHS_SHORT = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")


def fmt_int(value: object) -> str:
    return angka(value)


def fmt_pct(value: object, digits: int = 2) -> str:
    """16.114 → "16,11%" (nilai sudah dalam persen)."""
    return persen(value, digits)


def fmt_rp(value: object) -> str:
    return rupiah(value)


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    stamp = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(stamp) else stamp.date()


def fmt_date(value: object) -> str:
    """"2 Nov 2026"."""
    day = _as_date(value)
    return EMPTY if day is None else f"{day.day} {MONTHS_SHORT[day.month - 1]} {day.year}"


def fmt_date_short(value: object) -> str:
    """"02/11/2026"."""
    day = _as_date(value)
    return EMPTY if day is None else day.strftime("%d/%m/%Y")
