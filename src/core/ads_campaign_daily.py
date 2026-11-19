"""Laporan all iklan satu tanggal untuk evaluasi campaign.

Data latih tetap MTD di ads_overall. Campaign memakai file yang periodenya
tepat satu hari: Biaya dan Omzet Penjualan hari itu menggantikan selisih MTD.
Modal Harian tidak dibaca. Sales produk dan sales bersih tetap dari transaksi
atau performa.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from src.core.ads import _number
from src.core.ads_month import _unit_key
from src.core.schemas import SOURCE_SPECS, find_columns, normalize_header
from src.core.storage import read_upload_file

_STORE_COLS = ["Tanggal", "Biaya", "Omzet", "Sumber"]
_UNIT_COLS = ["Tanggal", "key", "Biaya", "Omzet"]


def _span(text: str) -> tuple[date, date] | None:
    parts = str(text or "").split(" - ")
    if len(parts) != 2:
        return None
    start = pd.to_datetime(parts[0].strip(), dayfirst=True, errors="coerce")
    end = pd.to_datetime(parts[1].strip(), dayfirst=True, errors="coerce")
    if pd.isna(start) or pd.isna(end):
        return None
    return start.date(), end.date()


def _period_text(frame: pd.DataFrame) -> str:
    for column in frame.columns:
        if normalize_header(column) == "periode laporan (teks)":
            values = frame[column].dropna().astype(str).str.strip()
            values = values[values.ne("")]
            if not values.empty:
                return str(values.iloc[0])
    return ""


def parse_daily_ad_file(data: bytes, filename: str) -> dict:
    """Satu file Semua Laporan Iklan yang awal dan akhir periodenya hari yang sama."""
    name = filename or "laporan"
    frame = read_upload_file(data, name, SOURCE_SPECS["ads_overall"])
    if frame is None or frame.empty:
        raise ValueError(f"{name}: tidak ada baris iklan.")
    text = _period_text(frame)
    span = _span(text)
    if span is None:
        raise ValueError(
            f"{name}: periode laporan tidak terbaca. "
            "Pakai ekspor Semua Laporan Iklan dari Seller Center."
        )
    start, end = span
    if start != end:
        raise ValueError(
            f"{name}: periode {text} adalah laporan MTD, bukan satu hari. "
            "Unduh Semua Laporan Iklan dengan tanggal awal dan akhir yang sama. "
            "File MTD tetap diunggah di data latih, bukan di sini."
        )
    cols = find_columns(frame.columns, SOURCE_SPECS["ads_overall"])
    if "cost" not in cols or "ad_sales" not in cols:
        raise ValueError(f"{name}: kolom Biaya atau Omzet Penjualan tidak ada.")
    biaya = _number(frame[cols["cost"]])
    omzet = _number(frame[cols["ad_sales"]])
    codes = frame[cols["product_code"]] if "product_code" in cols else pd.Series([""] * len(frame))
    names = frame[cols["product_name"]] if "product_name" in cols else pd.Series([""] * len(frame))
    ads: dict[str, dict] = {}
    for code, nama, cost, sales in zip(codes, names, biaya, omzet):
        key = _unit_key(code, nama)
        if not key:
            continue
        slot = ads.setdefault(key, {"key": key, "nama": "", "biaya": 0.0, "omzet": 0.0})
        slot["biaya"] += float(cost or 0)
        slot["omzet"] += float(sales or 0)
        label = str(nama or "").strip()
        if not slot["nama"] and label and label.lower() not in {"nan", "none", "-"}:
            slot["nama"] = label
    if not ads and float(biaya.sum() or 0) <= 0:
        raise ValueError(f"{name}: tidak ada baris iklan yang bisa dibaca.")
    return {
        "tanggal": start.isoformat(),
        "biaya": float(biaya.sum() or 0),
        "omzet": float(omzet.sum() or 0),
        "iklan": [ads[key] for key in sorted(ads)],
    }


def merge_daily_reports(campaign: dict, days: list[dict]) -> dict:
    """Tanggal yang sama diganti. Campaign lain tidak diubah."""
    by: dict[str, dict] = {}
    for item in (campaign or {}).get("laporan_harian") or []:
        if isinstance(item, dict) and item.get("tanggal"):
            by[str(item["tanggal"])[:10]] = item
    for item in days:
        if isinstance(item, dict) and item.get("tanggal"):
            by[str(item["tanggal"])[:10]] = item
    out = dict(campaign or {})
    out["laporan_harian"] = [by[key] for key in sorted(by)]
    return out


def _day(value) -> date | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def apply_campaign_daily(
    campaign: dict | None,
    store_daily: pd.DataFrame | None,
    unit_daily: pd.DataFrame | None,
    *,
    start: date | None = None,
    end: date | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Ganti biaya/omzet tanggal yang punya laporan satu hari. Hari lain tetap."""
    reports = [r for r in (campaign or {}).get("laporan_harian") or [] if isinstance(r, dict)]
    store = store_daily.copy() if isinstance(store_daily, pd.DataFrame) else pd.DataFrame(columns=_STORE_COLS)
    units = unit_daily.copy() if isinstance(unit_daily, pd.DataFrame) else None
    if not reports:
        return store, units
    for column in _STORE_COLS:
        if column not in store.columns:
            store[column] = pd.Series(dtype=object)
    for report in reports:
        day = str(report.get("tanggal") or "")[:10]
        when = _day(day)
        if when is None or (start is not None and when < start) or (end is not None and when > end):
            continue
        if not store.empty:
            store = store.loc[store["Tanggal"].astype(str).str[:10] != day]
        store = pd.concat(
            [
                store,
                pd.DataFrame([{
                    "Tanggal": day,
                    "Biaya": float(report.get("biaya") or 0),
                    "Omzet": float(report.get("omzet") or 0),
                    "Sumber": "laporan 1 hari",
                }]),
            ],
            ignore_index=True,
        )
        if units is None:
            units = pd.DataFrame(columns=_UNIT_COLS)
        if not units.empty and "Tanggal" in units.columns:
            units = units.loc[units["Tanggal"].astype(str).str[:10] != day]
        rows = []
        for item in report.get("iklan") or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "")
            if not key:
                continue
            rows.append({
                "Tanggal": day,
                "key": key,
                "Biaya": float(item.get("biaya") or 0),
                "Omzet": float(item.get("omzet") or 0),
            })
        if rows:
            units = pd.concat([units, pd.DataFrame(rows)], ignore_index=True)
    if not store.empty:
        store = store.sort_values("Tanggal").reset_index(drop=True)
    if units is not None and not units.empty:
        units = units.sort_values(["Tanggal", "key"]).reset_index(drop=True)
    return store, units
