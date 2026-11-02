"""Flash sale toko dan kalender exposure media sosial (Revisi Final 4D)."""

from __future__ import annotations

import calendar
import math
from datetime import date, timedelta

import pandas as pd

CHANNELS = ("Instagram", "TikTok", "Shopee Live", "Shopee Video")
HARBOLNAS = ((12, 12),)
SLOT_HOURS = ("12.00–14.00", "20.00–22.00")


def special_days(year: int, month: int) -> list[tuple[date, str]]:
    """Tanggal kembar, tanggal 25 (gajian), dan Harbolnas (12.12)."""
    days = []
    last = calendar.monthrange(year, month)[1]
    days.append((date(year, month, month), f"Tanggal kembar {month}.{month}"))
    if 25 <= last:
        days.append((date(year, month, 25), "Gajian (25)"))
    for m, d in HARBOLNAS:
        if m == month:
            days.append((date(year, m, d), "Harbolnas"))
    seen = {}
    for day, label in sorted(days):
        seen.setdefault(day, label if day not in seen else seen[day])
    return sorted(seen.items())


def flash_price(price: float, discount: float, min_price_margin0: float | None) -> float:
    """harga_flash = max(harga × (1 − diskon), harga_minimal_margin_0)."""
    value = price * (1 - discount)
    if min_price_margin0 is not None and math.isfinite(min_price_margin0):
        value = max(value, min_price_margin0)
    return float(math.ceil(value / 100.0) * 100)


def flash_quota(stok: float, ss: float, daily: float, window_pred: float) -> int:
    """kuota = min(stok − SS − prediksi_harian × 7, round(0,1 × prediksi_window)); harus > 0."""
    return int(max(min(stok - ss - daily * 7, round(0.1 * window_pred)), 0))


def schedule_flash(
    candidates: pd.DataFrame,
    today: date,
    *,
    months: int = 2,
    per_slot: int = 2,
    gap_days: int = 7,
    po_eta: dict[str, date] | None = None,
) -> pd.DataFrame:
    """Slot 2 jam di tanggal spesial; maks. 2 SKU per slot; SKU sama tidak di dua slot dalam 7 hari.

    candidates: sku, label, kuota, kuota_setelah_po, harga, harga_flash, skor (urut skor turun).
    """
    po_eta = po_eta or {}
    slots = []
    cursor = date(today.year, today.month, 1)
    for _ in range(months):
        for day, label in special_days(cursor.year, cursor.month):
            if day >= today:
                slots.append((day, label))
        cursor = (pd.Timestamp(cursor) + pd.DateOffset(months=1)).date()
    used: dict[str, date] = {}
    rows = []
    pool = candidates.sort_values("skor", ascending=False).to_dict("records")
    for day, label in slots:
        taken = 0
        for item in pool:
            if taken >= per_slot:
                break
            sku = item["sku"]
            if sku in used and abs((day - used[sku]).days) < gap_days:
                continue
            status = "Siap"
            if item["kuota"] <= 0:
                eta = po_eta.get(sku)
                if eta and eta < day and item.get("kuota_setelah_po", 0) > 0:
                    status = "Tunggu stok"
                else:
                    continue
            used[sku] = day
            taken += 1
            rows.append(
                {
                    "Tanggal": day,
                    "Momen": label,
                    "Jam": SLOT_HOURS[(taken - 1) % len(SLOT_HOURS)],
                    "SKU · produk · varian": item["label"],
                    "Harga normal": item["harga"],
                    "Harga flash": item["harga_flash"],
                    "Kuota": item["kuota"] if status == "Siap" else item.get("kuota_setelah_po", 0),
                    "Status": status,
                }
            )
    return pd.DataFrame(rows)


def exposure_calendar(
    ranked: pd.DataFrame,
    year: int,
    month: int,
    *,
    slots: int = 20,
    per_day: int = 2,
    min_gap: int = 5,
) -> pd.DataFrame:
    """Tanggal round(k × jarak) mulai tanggal 3; maks. 2 SKU/hari; SKU sama minimal berjarak 5 hari;
    tanggal spesial diisi SKU prioritas tertinggi; kanal bergilir per kategori.

    ranked: sku, label, kategori, prioritas (urut turun).
    """
    if ranked is None or ranked.empty:
        return pd.DataFrame(columns=["tanggal", "sku", "label", "kanal", "kategori", "spesial"])
    days_in = calendar.monthrange(year, month)[1]
    step = days_in / max(slots, 1)
    dates = sorted({min(max(3, round(3 + k * step)), days_in) for k in range(slots)})
    specials = {day.day: label for day, label in special_days(year, month)}
    dates = sorted(set(dates) | set(specials))
    pool = ranked.sort_values("prioritas", ascending=False).to_dict("records")
    last_used: dict[str, int] = {}
    rotation: dict[str, int] = {}
    rows = []
    for day in dates:
        capacity = per_day if day in specials else 1
        for item in pool:
            if capacity <= 0:
                break
            sku = item["sku"]
            if sku in last_used and day - last_used[sku] < min_gap:
                continue
            category = str(item.get("kategori") or "Aksesoris")
            turn = rotation.get(category, 0)
            rotation[category] = turn + 1
            last_used[sku] = day
            capacity -= 1
            rows.append(
                {
                    "tanggal": date(year, month, day),
                    "sku": sku,
                    "label": item["label"],
                    "kanal": CHANNELS[turn % len(CHANNELS)],
                    "kategori": category,
                    "spesial": specials.get(day, ""),
                }
            )
    return pd.DataFrame(rows)


def month_grid(year: int, month: int) -> list[list[date | None]]:
    """Minggu Senin–Minggu untuk kalender bulanan."""
    cal = calendar.Calendar(firstweekday=0)
    weeks = []
    for week in cal.monthdatescalendar(year, month):
        weeks.append([day if day.month == month else None for day in week])
    return weeks


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    stamp = pd.Timestamp(year=year, month=month, day=1) + pd.DateOffset(months=delta)
    return stamp.year, stamp.month


def category_of(name: str) -> str:
    lower = f" {str(name or '').lower()} "
    for category, hints in (
        ("Sealant", ("sealant", "silicone", "silikon")),
        ("Lem", ("lem ", "perekat", "epoxy", "lem-")),
        ("Kloset", ("kloset", "closet", "toilet")),
        ("Wastafel", ("wastafel", "washtafel", "lavatory")),
        ("Glass block", ("glass block", "glassblock")),
    ):
        if any(hint in lower for hint in hints):
            return category
    return "Aksesoris"


def next_days(day: date, n: int) -> list[date]:
    return [day + timedelta(days=i) for i in range(n)]
