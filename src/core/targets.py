"""Target sales bulanan dan pencapaian sales aktual.

Target disimpan per bulan (tabel `sales_target`, kunci `periode` = "YYYY-MM"). Tidak ada lagi satu angka
yang berlaku untuk semua bulan: bulan tanpa target dianggap belum punya target.

Pencapaian rentang tanggal = sales aktual ÷ target rentang itu. Target rentang = jumlah target setiap bulan
yang tersentuh, dibagi per hari kalender. Dengan `weight` (pola hari Pantauan harian: Senin–Minggu, gajian,
tanggal kembar) bagian sebuah tanggal = pola tanggal itu ÷ jumlah pola sebulan; tanpa pola dibagi rata.
Contoh rata: 1–8 Nov dengan target Nov Rp 3 M → target rentang Rp 3 M × 8/30.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

_MONTHS = {
    "jan": 1, "januari": 1, "january": 1,
    "feb": 2, "februari": 2, "february": 2, "peb": 2,
    "mar": 3, "maret": 3, "march": 3,
    "apr": 4, "april": 4,
    "mei": 5, "may": 5,
    "jun": 6, "juni": 6, "june": 6,
    "jul": 7, "juli": 7, "july": 7,
    "agu": 8, "agt": 8, "agustus": 8, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "okt": 10, "oktober": 10, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "nop": 11, "nopember": 11,
    "des": 12, "desember": 12, "dec": 12, "december": 12,
}
_MONTH_COLUMNS = ("bulan", "periode", "month", "period", "tanggal")
_TARGET_COLUMNS = ("target", "target sales", "target penjualan", "target sales bersih", "target (rp)", "nilai")
ID_SHORT = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")


def month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def month_label(key: str) -> str:
    year, month = key.split("-")
    return f"{ID_SHORT[int(month) - 1]} {year}"


def parse_month(value) -> str | None:
    """'2026-11', '11/2026', 'Nov 2026', 'November 2026', tanggal Excel → '2026-11'."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (pd.Timestamp, date)):
        return f"{value.year:04d}-{value.month:02d}"
    text = str(value).strip().lower()
    if not text:
        return None
    hit = re.fullmatch(r"(\d{4})[-/.](\d{1,2})(?:[-/.]\d{1,2})?(?:\s.*)?", text)
    if hit:
        year, month = int(hit.group(1)), int(hit.group(2))
        return f"{year:04d}-{month:02d}" if 1 <= month <= 12 else None
    hit = re.fullmatch(r"(?:\d{1,2}[-/.])?(\d{1,2})[-/.](\d{4})", text)
    if hit:
        month, year = int(hit.group(1)), int(hit.group(2))
        return f"{year:04d}-{month:02d}" if 1 <= month <= 12 else None
    hit = re.fullmatch(r"([a-z]+)[\s\-/.']*(\d{2}|\d{4})", text)
    if hit and hit.group(1) in _MONTHS:
        year = int(hit.group(2))
        year = year + 2000 if year < 100 else year
        return f"{year:04d}-{_MONTHS[hit.group(1)]:02d}"
    return None


def parse_amount(value) -> float | None:
    """'Rp 5.500.000.000', '5,5 M', 5500000000 → 5500000000.0."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower().replace("rp", "").replace(" ", "")
    if not text:
        return None
    scale = 1.0
    for suffix, factor in (("miliar", 1e9), ("milyar", 1e9), ("m", 1e9), ("jt", 1e6), ("juta", 1e6)):
        if text.endswith(suffix):
            text, scale = text[: -len(suffix)], factor
            break
    if scale > 1:
        text = text.replace(".", "").replace(",", ".") if "," in text else text
    else:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text) * scale
    except ValueError:
        return None


def parse_target_file(frame: pd.DataFrame) -> pd.DataFrame:
    """File target bulanan → kolom periode ("YYYY-MM") dan target (Rp). Bulan ganda: baris terakhir dipakai."""
    if frame is None or frame.empty:
        raise ValueError("File kosong.")
    columns = {str(c).strip().lower(): c for c in frame.columns}
    month_col = next((columns[c] for c in _MONTH_COLUMNS if c in columns), None)
    target_col = next((columns[c] for c in _TARGET_COLUMNS if c in columns), None)
    if target_col is None:
        target_col = next((columns[c] for c in columns if c.startswith("target")), None)
    if month_col is None or target_col is None:
        raise ValueError("Kolom wajib: Bulan dan Target (Rp). Pakai template yang disediakan.")
    rows = []
    bad = []
    for index, (raw_month, raw_target) in enumerate(zip(frame[month_col], frame[target_col]), start=2):
        if raw_target is None or str(raw_target).strip() in ("", "nan", "None"):
            continue
        key, amount = parse_month(raw_month), parse_amount(raw_target)
        if key is None or amount is None or amount < 0:
            bad.append(str(index))
            continue
        rows.append({"periode": key, "target": float(amount)})
    if bad:
        raise ValueError(f"Baris {', '.join(bad[:10])} tidak terbaca: isi Bulan seperti 2026-11 atau Nov 2026, dan Target berupa angka rupiah.")
    if not rows:
        raise ValueError("Tidak ada baris target yang terbaca.")
    out = pd.DataFrame(rows).drop_duplicates("periode", keep="last").sort_values("periode").reset_index(drop=True)
    return out


def template_frame(today: date, saved: dict[str, float] | None = None) -> pd.DataFrame:
    """Januari tahun berjalan s.d. Desember tahun depan (plus bulan lama yang sudah bertarget).

    Target tersimpan sudah terisi; bulan tanpa target dibiarkan kosong dan dilewati saat diunggah.
    """
    saved = saved or {}
    first = pd.Period(f"{today.year}-01", freq="M")
    keys = [str(first + i) for i in range(24)]
    keys = sorted(set(keys) | set(saved))
    return pd.DataFrame({"Bulan": keys, "Target (Rp)": [saved.get(key) for key in keys]})


@dataclass(frozen=True)
class Achievement:
    actual: float
    target: float  # target rentang (prorata)
    pct: float
    month_target: float  # target bulan penuh bila rentang dalam satu bulan, selain itu = target
    month_pct: float
    single_month: str | None  # "YYYY-MM" bila rentang dalam satu bulan
    full_months: bool  # rentang menutup bulan penuh
    days: int
    month_days: int


def range_target(targets: dict[str, float], start: date, end: date,
                 weight: Callable[[date], float] | None = None) -> tuple[float | None, list[str]]:
    """Target prorata untuk [start, end]. Mengembalikan (target, bulan tanpa target)."""
    if start is None or end is None or end < start:
        return None, []
    total = 0.0
    missing: list[str] = []
    for period in pd.period_range(start, end, freq="M"):
        key = str(period)
        days_in = calendar.monthrange(period.year, period.month)[1]
        first = period.start_time.date()
        lo = max(start, first)
        hi = min(end, period.end_time.date())
        value = float(targets.get(key, 0) or 0)
        if value <= 0:
            missing.append(key)
            continue
        share = ((hi - lo).days + 1) / days_in
        if weight is not None:
            w = [max(float(weight(first + timedelta(days=i))), 0.0) for i in range(days_in)]
            if sum(w) > 0:
                share = sum(w[(lo - first).days:(hi - first).days + 1]) / sum(w)
        total += value * share
    if missing:
        return None, missing
    return total, []


def achievement(actual: float, start: date, end: date, targets: dict[str, float],
                weight: Callable[[date], float] | None = None) -> tuple[Achievement | None, list[str]]:
    target, missing = range_target(targets, start, end, weight)
    if target is None or target <= 0:
        return None, missing
    single = month_key(start) if (start.year, start.month) == (end.year, end.month) else None
    month_days = calendar.monthrange(start.year, start.month)[1] if single else 0
    full = start.day == 1 and end.day == calendar.monthrange(end.year, end.month)[1]
    month_target = float(targets.get(single, 0)) if single else target
    return Achievement(
        actual=float(actual), target=float(target), pct=float(actual) / target * 100,
        month_target=month_target, month_pct=float(actual) / month_target * 100 if month_target > 0 else float("nan"),
        single_month=single, full_months=full, days=(end - start).days + 1, month_days=month_days,
    ), []
