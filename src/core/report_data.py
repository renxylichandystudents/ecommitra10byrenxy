"""Laporan: snapshot angka & tabel untuk satu rentang tanggal, serialisasi JSON, dan penyimpanan laporan.

Snapshot berisi semua yang dibutuhkan untuk menampilkan laporan (angka, tabel, data grafik), sehingga laporan yang
sudah disimpan bisa dibuka lagi tanpa menjalankan analisa atau menghitung ulang. Disimpan di kv_setting:
`laporan:index` (daftar) dan `laporan:<id>` (isi).
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd

from src.core.metrics import normalize_lines, slice_dates

INDEX_KEY = "laporan:index"
KEEP = 60
FRAME_TAG = "__frame__"


# ---------------------------------------------------------------- serialisasi

def _plain(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()[:10] if not isinstance(value, datetime) or (value.hour, value.minute) == (0, 0) else value.isoformat(sep=" ")[:16]
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def to_json(obj):
    """Snapshot → struktur JSON (DataFrame jadi {"__frame__": {"columns", "data"}})."""
    if isinstance(obj, pd.DataFrame):
        frame = obj.reset_index(drop=True)
        return {FRAME_TAG: {"columns": [str(c) for c in frame.columns],
                            "data": [[_plain(v) for v in row] for row in frame.astype(object).itertuples(index=False, name=None)]}}
    if isinstance(obj, dict):
        return {str(k): to_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_json(v) for v in obj]
    return _plain(obj)


def from_json(obj):
    if isinstance(obj, dict):
        if FRAME_TAG in obj and len(obj) == 1:
            spec = obj[FRAME_TAG]
            return pd.DataFrame(spec.get("data") or [], columns=spec.get("columns") or [])
        return {k: from_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [from_json(v) for v in obj]
    return obj


class ReportStore:
    """Laporan tersimpan per pengguna aplikasi (dipakai bersama)."""

    def __init__(self, features) -> None:
        self.features = features

    def all(self) -> list[dict]:
        items = self.features.get_json(INDEX_KEY) if self.features is not None else None
        return sorted(items or [], key=lambda r: r.get("dibuat", ""), reverse=True)

    def get(self, report_id: int) -> dict | None:
        raw = self.features.get_json(f"laporan:{int(report_id)}") if self.features is not None else None
        return from_json(raw) if raw else None

    def save(self, snapshot: dict, *, name: str, username: str, now: datetime | None = None) -> int:
        items = self.all()
        report_id = max((int(r["id"]) for r in items), default=0) + 1
        stamp = (now or datetime.now()).replace(microsecond=0).isoformat(sep=" ")
        meta = snapshot.get("meta") or {}
        entry = {"id": report_id, "nama": name, "mulai": meta.get("mulai"), "selesai": meta.get("selesai"), "dibuat": stamp, "dibuat_oleh": username,
                 "run": meta.get("run_id"), "data_sd": meta.get("data_sd")}
        snapshot = {**snapshot, "meta": {**meta, "nama": name, "dibuat": stamp, "dibuat_oleh": username, "id": report_id}}
        self.features.set_json(f"laporan:{report_id}", to_json(snapshot), username=username)
        items.insert(0, entry)
        for old in items[KEEP:]:
            self.features.set_json(f"laporan:{int(old['id'])}", None, username=username)
        self.features.set_json(INDEX_KEY, items[:KEEP], username=username)
        return report_id

    def delete(self, report_id: int, *, username: str) -> None:
        items = [r for r in self.all() if int(r["id"]) != int(report_id)]
        self.features.set_json(f"laporan:{int(report_id)}", None, username=username)
        self.features.set_json(INDEX_KEY, items, username=username)


# ---------------------------------------------------------------- angka per rentang

def daily_orders(frame: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Per hari: pesanan, pesanan batal, sales bersih (Total Pembayaran − batal − retur), sales & QTY produk bersih."""
    cols = ["Tanggal", "Pesanan", "Pesanan batal", "Tingkat batal (%)", "Sales bersih", "Sales produk bersih", "QTY bersih"]
    lines = slice_dates(normalize_lines(frame), start, end)
    days = pd.date_range(start, end, freq="D")
    if lines is None or lines.empty:
        return pd.DataFrame({"Tanggal": days}).reindex(columns=cols).fillna({c: 0 for c in cols[1:]})
    lines = lines.assign(day=pd.to_datetime(lines["order_time"]).dt.normalize())
    once = lines.groupby("order_key", sort=False).agg(day=("day", "first"), amount=("order_amount", "first"), line=("line_value", "sum"), cancel=("is_cancel", "any"))
    once["money"] = once["amount"].where(once["amount"].fillna(0) > 0, once["line"]).fillna(0)
    once = once.assign(gone=once.index.map(lines.groupby("order_key")["is_open"].any()) | once["cancel"])
    active = lines.loc[~lines["is_cancel"] & ~lines["is_open"]]
    per_day = pd.DataFrame({
        "Pesanan": once.groupby("day").size(),
        "Pesanan batal": once.loc[once["cancel"]].groupby("day").size(),
        "bruto": once.groupby("day")["money"].sum(),
        "batal": once.loc[once["gone"]].groupby("day")["money"].sum(),
        "retur": active.groupby("day")["return_value"].sum(),
        "Sales produk bersih": (active["line_value"] - active["return_value"]).groupby(active["day"]).sum(),
        "QTY bersih": (active["gross_qty"] - np.minimum(active["returned_qty"], active["gross_qty"])).groupby(active["day"]).sum(),
    }).reindex(days).fillna(0)
    per_day["Sales bersih"] = per_day["bruto"] - per_day["batal"] - per_day["retur"]
    per_day["Tingkat batal (%)"] = np.where(per_day["Pesanan"] > 0, per_day["Pesanan batal"] / per_day["Pesanan"].replace(0, 1) * 100, 0.0)
    return per_day.rename_axis("Tanggal").reset_index()[cols]


def top_products(orders: pd.DataFrame, start: date, end: date, prev: tuple[date, date], limit: int = 30) -> pd.DataFrame:
    """Produk terlaris di rentang + perubahan vs rentang pembanding.

    `orders` berisi semua status (orders_all). Angka bersih, sama dengan kartu Ringkasan: QTY bersih & Sales produk bersih
    = baris yang tidak batal / Belum Bayar, dikurangi unit & nilai retur (metrics.sold_lines). Porsi dihitung terhadap Sales
    produk bersih seluruh produk, bukan hanya produk yang ditampilkan."""
    from src.core.metrics import sold_lines

    cols = ["Rank", "SKU", "Produk", "QTY bersih", "Sales produk bersih", "Porsi (%)", "Sales produk bersih periode lalu", "Perubahan (%)"]
    lines = sold_lines(orders) if orders is not None and not orders.empty else None
    if lines is None or lines.empty:
        return pd.DataFrame(columns=cols)
    day = pd.to_datetime(lines["order_time"], errors="coerce").dt.normalize()
    names = lines.assign(sku=lines["sku"].astype(str)).drop_duplicates("sku", keep="last").set_index("sku")["product_name"]

    def grab(a, b):
        part = lines.loc[day.between(pd.Timestamp(a), pd.Timestamp(b))]
        return part.assign(sku=part["sku"].astype(str)).groupby("sku").agg(QTY=("qty", "sum"), Sales=("sales", "sum"))

    now = grab(start, end)
    now = now.loc[(now["QTY"] > 0) | (now["Sales"] != 0)]
    if now.empty:
        return pd.DataFrame(columns=cols)
    before = grab(*prev)["Sales"]
    now = now.sort_values(["Sales", "QTY"], ascending=False).reset_index()
    total = float(now["Sales"].sum()) or 1.0
    out = pd.DataFrame({
        "Rank": np.arange(1, len(now) + 1), "SKU": now["sku"], "Produk": now["sku"].map(names).fillna(""), "QTY bersih": now["QTY"],
        "Sales produk bersih": now["Sales"], "Porsi (%)": now["Sales"] / total * 100,
        "Sales produk bersih periode lalu": now["sku"].map(before).fillna(0.0)})
    out["Perubahan (%)"] = np.where(out["Sales produk bersih periode lalu"] > 0,
                                    (out["Sales produk bersih"] - out["Sales produk bersih periode lalu"]) / out["Sales produk bersih periode lalu"] * 100, np.nan)
    return out[cols].head(limit)


def performance_range(performance: pd.DataFrame | None, start: date, end: date) -> tuple[dict, pd.DataFrame]:
    """Performa toko pada rentang: total pengunjung, pesanan, rata-rata konversi + seri harian."""
    from src.core.performance import clean_performance, perf_number

    if performance is None or performance.empty:
        return {}, pd.DataFrame()
    work = clean_performance(performance)
    if work.empty:
        return {}, pd.DataFrame()
    part = work.loc[work["date"].between(pd.Timestamp(start), pd.Timestamp(end))]
    prev_start, prev_end = previous_range(start, end)
    prior = work.loc[work["date"].between(pd.Timestamp(prev_start), pd.Timestamp(prev_end))]

    def total(frame, col):
        return float(perf_number(frame[col]).sum()) if col in frame.columns and not frame.empty else float("nan")

    def mean(frame, col):
        if col not in frame.columns or frame.empty:
            return float("nan")
        values = perf_number(frame[col])
        weights = perf_number(frame["visitors"]) if "visitors" in frame.columns else None
        if weights is not None and float(weights.where(values.notna()).sum()) > 0:
            return float((values * weights).sum() / weights.where(values.notna()).sum())
        return float(values.mean())

    summary = {
        "hari": int(part["date"].nunique()), "pengunjung": total(part, "visitors"), "pengunjung_prev": total(prior, "visitors"),
        "pesanan": total(part, "orders"), "pesanan_prev": total(prior, "orders"), "konversi": mean(part, "conversion_rate"),
        "konversi_prev": mean(prior, "conversion_rate"), "pembeli_baru": total(part, "new_buyers"),
    }
    keep = [c for c in ("date", "visitors", "orders", "conversion_rate") if c in part.columns]
    daily = part[keep].copy()
    for col in keep[1:]:
        daily[col] = perf_number(daily[col])
    daily = daily.rename(columns={"date": "Tanggal", "visitors": "Pengunjung", "orders": "Pesanan", "conversion_rate": "Konversi (%)"})
    return summary, daily.reset_index(drop=True)


def previous_range(start: date, end: date) -> tuple[date, date]:
    """Pembanding: bulan kalender sebelumnya bila rentang = bulan penuh (Okt → Sep), selain itu rentang sama panjang tepat sebelumnya."""
    first, last = pd.Timestamp(start), pd.Timestamp(end)
    if first.day == 1 and last == last + pd.offsets.MonthEnd(0):
        months = (last.year - first.year) * 12 + last.month - first.month + 1
        prev_start = (first - pd.DateOffset(months=months)).date()
        return prev_start, (first - pd.Timedelta(days=1)).date()
    span = (end - start).days + 1
    return start - pd.Timedelta(days=span).to_pytimedelta(), start - pd.Timedelta(days=1).to_pytimedelta()


def campaigns_in_range(features, start: date, end: date) -> pd.DataFrame:
    """Campaign iklan / flash sale / exposure tersimpan yang periodenya beririsan dengan rentang laporan."""
    from src.core import campaigns as C

    rows = []
    names = {"iklan": "Iklan", "flash": "Flash sale", "exposure": "Exposure media sosial"}
    if features is None:
        return pd.DataFrame(columns=["Jenis", "Campaign", "Mulai", "Selesai", "Status", "Ringkasan"])
    for kind in C.KINDS:
        try:
            items = C.Store(features, kind).all()
        except Exception:
            items = []
        for item in items:
            try:
                a, b = C.as_date(item.get("mulai")), C.as_date(item.get("selesai"))
            except (TypeError, ValueError):
                continue
            if b < start or a > end:
                continue
            s = item.get("setelan") or {}
            if kind == "iklan":
                text = f"target ROAS {s.get('roas', '–')} · budget Rp {float(s.get('budget') or 0):,.0f} · proyeksi {float(s.get('capaian') or 0):.1f}% target".replace(",", ".")
            elif kind == "flash":
                text = f"{len(item.get('jadwal') or [])} slot terjadwal · {len(item.get('tidak_dijadwalkan') or [])} SKU tidak terjadwal"
            else:
                text = f"{len(item.get('jadwal') or [])} SKU terjadwal · {len(item.get('ditunda') or [])} ditunda"
            rows.append({"Jenis": names.get(kind, kind), "Campaign": f"#{item.get('id')} {item.get('nama', '')}", "Mulai": a, "Selesai": b,
                         "Status": C.status_of(item, date.today()), "Ringkasan": text})
    return pd.DataFrame(rows, columns=["Jenis", "Campaign", "Mulai", "Selesai", "Status", "Ringkasan"])
