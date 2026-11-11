"""Pantauan bulan berjalan: prediksi vs aktual per tanggal, target omzet, pola hari ramai/promo, dan prioritas tindakan.

Basis angka = sales bersih (sama dengan target dan tab Data & Laporan): Total Pembayaran − batal − Belum Bayar − retur.
Prediksi tersimpan (prediction_snapshot) memakai harga setelah diskon × QTY, jadi dikalikan `faktor`
(sales bersih ÷ sales produk bersih bulan itu), sama dengan `targets_view.month_outlook`.

Prediksi per tanggal = prediksi analisa terakhir yang dibuat SEBELUM tanggal itu (analisa harian → prediksi H-1).
Snapshot menyimpan laju harian datar; untuk tampilan per tanggal laju itu dibagi menurut pola hari (Senin–Minggu)
dan hari promo (gajian, tanggal kembar) dari riwayat aktual. Pola dinormalkan (rata-rata 1 dalam sebulan),
jadi total prediksi sebulan tidak berubah — rumus model tidak diubah, hanya sebarannya per tanggal.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

DAY_NAMES = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
TYPES = ("Tanggal kembar", "Gajian", "Normal")
MIN_HISTORY_DAYS = 28


# --------------------------------------------------------------------------- aktual harian


def _money_by_day(lines: pd.DataFrame, day: pd.Series) -> pd.Series:
    """Total Pembayaran sekali per No. Pesanan per hari (bila kosong/0: jumlah nilai baris)."""
    if lines.empty:
        return pd.Series(dtype=float)
    once = lines.assign(_d=day.loc[lines.index]).groupby(["_d", "order_key"], sort=False).agg(
        amount=("order_amount", "first"), line=("line_value", "sum"))
    chosen = once["amount"].where(once["amount"].fillna(0) > 0, once["line"]).fillna(0.0)
    return chosen.groupby(level=0).sum()


def daily_net_sales(lines: pd.DataFrame, start: date, end: date) -> pd.Series:
    """Sales bersih per tanggal [start, end] dari baris `metrics.normalize_lines` (semua status). Sama dengan
    `order_metrics(...)["sales_bersih"]` bila dihitung per hari."""
    index = pd.date_range(start, end, freq="D")
    if lines is None or lines.empty:
        return pd.Series(0.0, index=index)
    day = pd.to_datetime(lines["order_time"], errors="coerce").dt.normalize()
    part = lines.loc[day.ge(pd.Timestamp(start)) & day.le(pd.Timestamp(end))]
    day = day.loc[part.index]
    active = part.loc[~part["is_cancel"] & ~part["is_open"]]
    returned = active.loc[active["returned_qty"] > 0]
    total = (
        _money_by_day(part, day).reindex(index, fill_value=0.0)
        - _money_by_day(part.loc[part["is_cancel"]], day).reindex(index, fill_value=0.0)
        - _money_by_day(part.loc[part["is_open"]], day).reindex(index, fill_value=0.0)
        - returned.groupby(day.loc[returned.index])["return_value"].sum().reindex(index, fill_value=0.0)
    )
    return total.astype(float)


def daily_product_sales(lines: pd.DataFrame, start: date, end: date) -> pd.Series:
    """Sales produk bersih per tanggal (harga setelah diskon × QTY bersih), basis yang sama dengan prediksi model."""
    from src.core.metrics import net_sku_sales

    index = pd.date_range(start, end, freq="D")
    rows = net_sku_sales(lines, start, end, normalized=True)
    if rows.empty:
        return pd.Series(0.0, index=index)
    return rows.groupby(pd.to_datetime(rows["order_time"]).dt.normalize())["sales"].sum().reindex(index, fill_value=0.0).astype(float)


# --------------------------------------------------------------------------- pola hari & promo


def day_type(day: date) -> str:
    """Jenis hari promo Shopee (sama dengan `preprocessing.promo_flag`): tanggal kembar (9.9, 10.10, 11.11, 12.12 …) dan gajian (25 s.d. 3)."""
    if day.day == day.month:
        return "Tanggal kembar"
    if day.day >= 25 or day.day <= 3:
        return "Gajian"
    return "Normal"


def day_label(day: date) -> str:
    kind = day_type(day)
    if kind == "Tanggal kembar":
        return f"Tanggal kembar {day.day}.{day.month}" + (" · Harbolnas" if (day.month, day.day) == (12, 12) else "")
    return "Gajian" if kind == "Gajian" else ""


@dataclass
class Profile:
    weekday: np.ndarray = field(default_factory=lambda: np.ones(7))
    uplift: dict = field(default_factory=lambda: {t: 1.0 for t in TYPES})
    samples: dict = field(default_factory=lambda: {t: 0 for t in TYPES})
    days: int = 0

    def factor(self, day: date) -> float:
        return float(self.weekday[day.weekday()] * self.uplift.get(day_type(day), 1.0))


def seasonal_profile(daily: pd.Series) -> Profile:
    """Pola dari sales bersih harian historis: indeks hari (Senin–Minggu) pada hari normal, dan kenaikan hari promo
    terhadap garis dasar (median bergulir 15 hari hari normal). Kenaikan disusutkan ke 1 bila contoh sedikit."""
    series = daily.astype(float).sort_index()
    series = series.loc[series.index.notna()]
    if len(series) < MIN_HISTORY_DAYS or float(series.sum()) <= 0:
        return Profile(days=len(series))
    dates = [d.date() for d in series.index]
    kinds = pd.Series([day_type(d) for d in dates], index=series.index)
    normal = series.where(kinds.eq("Normal"))
    base = normal.rolling(15, center=True, min_periods=5).median().interpolate(limit_direction="both")
    base = base.where(base > 0)
    ratio = (series / base).replace([np.inf, -np.inf], np.nan)
    dows = series.index.dayofweek
    weekday = np.ones(7)
    by_dow = ratio.where(kinds.eq("Normal")).groupby(dows).median()
    for dow, value in by_dow.items():
        if np.isfinite(value) and value > 0:
            weekday[int(dow)] = float(value)
    weekday = np.clip(weekday / weekday.mean(), 0.5, 2.0)
    uplift, samples = {"Normal": 1.0}, {"Normal": int(kinds.eq("Normal").sum())}
    adjusted = ratio / pd.Series(weekday[dows], index=series.index)
    for kind in ("Tanggal kembar", "Gajian"):
        values = adjusted.loc[kinds.eq(kind)].dropna()
        n = int(len(values))
        raw = float(values.median()) if n else 1.0
        shrink = n / (n + 2.0)
        uplift[kind] = float(np.clip(1.0 + (raw - 1.0) * shrink, 0.6, 3.0))
        samples[kind] = n
    return Profile(weekday=weekday, uplift=uplift, samples=samples, days=len(series))


# --------------------------------------------------------------------------- tabel bulan berjalan


def as_of_predictions(runs: pd.DataFrame, days: list[date]) -> pd.DataFrame:
    """Per tanggal: laju prediksi (Rp/hari, basis produk) dari analisa terakhir yang dibuat sebelum tanggal itu.

    runs: kolom run_id, run_at (waktu analisa), target_date, pred (Σ pred_sales SKU untuk tanggal itu).
    Tanggal sesudah analisa terakhir memakai analisa terakhir; tanggal di luar jendela analisa memakai rata-rata
    harian analisa itu."""
    out = []
    if runs is None or runs.empty:
        return pd.DataFrame({"tanggal": days, "pred_datar": np.nan, "run_id": np.nan, "run_at": pd.NaT})
    work = runs.copy()
    work["run_at"] = pd.to_datetime(work["run_at"])
    work["target_date"] = pd.to_datetime(work["target_date"]).dt.date
    per_run = work.groupby("run_id").agg(run_at=("run_at", "min"), mean=("pred", "mean"))
    by_key = work.set_index(["run_id", "target_date"])["pred"].to_dict()
    for day in days:
        before = per_run.loc[per_run["run_at"].dt.date < day]
        if before.empty:
            out.append({"tanggal": day, "pred_datar": np.nan, "run_id": np.nan, "run_at": pd.NaT})
            continue
        run_id = int(before["run_at"].idxmax())
        value = by_key.get((run_id, day), per_run.at[run_id, "mean"])
        out.append({"tanggal": day, "pred_datar": float(value), "run_id": run_id, "run_at": per_run.at[run_id, "run_at"]})
    return pd.DataFrame(out)


def month_shape(profile: Profile, month_first: date) -> dict[date, float]:
    """Pola harian bulan itu dinormalkan ke rata-rata 1: laju datar × pola, total sebulan tetap = laju × jumlah hari."""
    month_days = calendar.monthrange(month_first.year, month_first.month)[1]
    days = [month_first.replace(day=1) + timedelta(days=i) for i in range(month_days)]
    shape = np.array([profile.factor(d) for d in days])
    shape = shape / shape.mean() if shape.mean() > 0 else np.ones(month_days)
    return dict(zip(days, shape.tolist()))


def month_table(
    *,
    month_first: date,
    cutoff: date,
    actual: pd.Series,
    predictions: pd.DataFrame,
    factor: float,
    profile: Profile,
    target_month: float | None,
    running_actual: float | None = None,
) -> pd.DataFrame:
    """Satu baris per tanggal bulan itu. cutoff = hari penuh terakhir (aktual lengkap). running_actual = aktual
    sementara hari sesudah cutoff (hari ini, bila datanya sudah ada)."""
    month_days = calendar.monthrange(month_first.year, month_first.month)[1]
    days = [month_first + timedelta(days=i) for i in range(month_days)]
    shape = np.array(list(month_shape(profile, month_first).values()))
    pred = predictions.set_index("tanggal").reindex(days)
    actual_map = {pd.Timestamp(k).date(): float(v) for k, v in actual.items()}
    rows = []
    for i, day in enumerate(days):
        flat = pred.at[day, "pred_datar"] if day in pred.index else np.nan
        value = float(flat) * factor * shape[i] if pd.notna(flat) else np.nan
        done = day <= cutoff
        got = actual_map.get(day, 0.0) if done else np.nan
        rows.append({
            "tanggal": day,
            "hari": DAY_NAMES[day.weekday()],
            "jenis_hari": day_type(day),
            "keterangan": day_label(day),
            "pola": float(shape[i]),
            "target": float(target_month) * shape[i] / shape.sum() if target_month else np.nan,
            "prediksi": value,
            "aktual": got,
            "aktual_berjalan": float(running_actual) if (running_actual is not None and day == cutoff + timedelta(days=1)) else np.nan,
            "analisa": pred.at[day, "run_at"] if day in pred.index else pd.NaT,
            "status_hari": "Selesai" if done else ("Berjalan" if day == cutoff + timedelta(days=1) else "Akan datang"),
        })
    table = pd.DataFrame(rows)
    table["selisih"] = table["aktual"] - table["prediksi"]
    table["capaian_pct"] = np.where(table["prediksi"] > 0, table["aktual"] / table["prediksi"] * 100, np.nan)
    table["status"] = [achievement_status(a, p) if np.isfinite(a) and np.isfinite(p) and p > 0 else "" for a, p in zip(table["aktual"], table["prediksi"])]
    done = table["status_hari"].eq("Selesai")
    table["kum_aktual"] = table["aktual"].where(done).cumsum()
    table["kum_target"] = table["target"].cumsum() if target_month else np.nan
    projected = table["aktual"].where(done, table["prediksi"]).fillna(0.0)
    table["kum_proyeksi"] = projected.cumsum()
    return table


def achievement_status(actual: float, pred: float) -> str:
    from src.core.pred_actual import achievement_status as base

    return base(actual, pred)


def month_summary(table: pd.DataFrame, cutoff: date, target_month: float | None, today: date | None = None) -> dict:
    """Angka kartu: hari penuh terakhir (prediksi vs aktual), hari ini & besok (prediksi), MTD, proyeksi akhir bulan, kekurangan."""
    today = today or cutoff + timedelta(days=1)
    by_day = table.set_index("tanggal")
    done = table["status_hari"].eq("Selesai")
    rest = table.loc[~done]

    def row(day: date) -> dict:
        return {"tanggal": day, **by_day.loc[day].to_dict()} if day in by_day.index else {}

    mtd = float(table.loc[done, "aktual"].sum())
    mtd_pred_rows = table.loc[done & table["prediksi"].notna()]
    projection = mtd + float(rest["prediksi"].fillna(0.0).sum())
    target_mtd = float(table.loc[done, "target"].sum()) if target_month else np.nan
    gap = float(target_month) - projection if target_month else np.nan
    rest_days = int(len(rest))
    need_daily = (float(target_month) - mtd) / rest_days if target_month and rest_days else np.nan
    pred_daily_rest = float(rest["prediksi"].mean()) if rest_days and rest["prediksi"].notna().any() else np.nan
    return {
        "kemarin": row(cutoff),
        "hari_ini": row(today),
        "besok": row(today + timedelta(days=1)),
        "mtd": mtd,
        "mtd_prediksi": float(mtd_pred_rows["prediksi"].sum()),
        "mtd_aktual_terprediksi": float(mtd_pred_rows["aktual"].sum()),
        "target_mtd": target_mtd,
        "target": float(target_month) if target_month else np.nan,
        "proyeksi": projection,
        "kurang": gap,
        "sisa_hari": rest_days,
        "perlu_harian": need_daily,
        "prediksi_harian_sisa": pred_daily_rest,
        "hari_promo_sisa": [(d, lbl) for d, lbl in zip(rest["tanggal"], rest["keterangan"]) if lbl],
    }


# --------------------------------------------------------------------------- prioritas tindakan


def _num(value, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if np.isfinite(out) else default


def _units(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", ".")


def _rp(value: float) -> str:
    return "Rp " + f"{int(round(value)):,}".replace(",", ".")


def priority_actions(
    table: pd.DataFrame,
    *,
    today: date,
    rest_days: int,
    factor: float = 1.0,
    margin_pct: dict | None = None,
    excluded: set | None = None,
    default_roas: float = 6.0,
    unpaid: float = 0.0,
    unpaid_orders: int = 0,
    recent: pd.DataFrame | None = None,
    recent_days: int = 7,
    prior_days: int = 28,
    limit: int = 5,
) -> pd.DataFrame:
    """Kandidat tindakan dengan estimasi omzet bersih yang diselamatkan/ditambah sampai akhir bulan, diurutkan Rp terbesar.

    - Stok: kebutuhan sisa bulan (prediksi harian × sisa hari) yang tidak tertutup stok Site 10037 = omzet hilang;
      ambil dari Site 10062/10036 dulu, sisanya PO.
    - Iklan: SKU dengan riwayat iklan, stok cukup, ROAS marginal masih di atas titik impas (100 ÷ margin);
      tambahan budget sampai titik impas, maks. 5× budget sekarang (aturan sama dengan Rekomendasi › Iklan).
    - Harga & listing: SKU yang dalam `recent_days` hari penuh terakhir terjual < 60% prediksi DAN < 60% lajunya sendiri
      `prior_days` hari sebelumnya, padahal stok tidak habis (recent: kolom sku, qty, qty_sebelum). Potensi = kembali
      ke laju yang biasa (min. prediksi, laju sebelumnya) sampai akhir bulan; prediksi yang terlalu tinggi tidak dihitung.
    - Kejar bayar: pesanan Belum Bayar yang masih terbuka."""
    from src.core.ads import roas_estimate
    from src.core.ads_plan import default_curve, unit_cap_to_cost
    from src.core.dc_stock import DC_SITES, transfer_plan, transfer_text
    from src.core.restock import stock_out_date

    columns = ["Prioritas", "Jenis", "SKU", "Produk", "Tindakan", "Tenggat", "Potensi omzet", "Alasan"]
    margin_pct = margin_pct or {}
    excluded = excluded or set()
    rest_days = max(int(rest_days), 1)
    rows = []
    codes = [code for code, _n, _s in DC_SITES]
    sold, before = {}, {}
    if recent is not None and not recent.empty:
        recent = recent.assign(sku=recent["sku"].astype(str))
        sold = recent.groupby("sku")["qty"].sum().to_dict()
        if "qty_sebelum" in recent.columns:
            before = recent.groupby("sku")["qty_sebelum"].sum().to_dict()
    for _, r in (table if table is not None else pd.DataFrame()).iterrows():
        sku = str(r.get("sku", ""))
        if not sku or sku in excluded:
            continue
        daily = _num(r.get("pred_harian"))
        price = _num(r.get("harga_bersih"))
        if daily <= 0 or price <= 0:
            continue
        name = str(r.get("product_name", "") or "")
        variant = str(r.get("variasi_tampil", "") or "")
        label = name + (f" · {variant}" if variant and variant.lower() not in ("-", "nan", "tanpa variasi") else "")
        known = bool(r.get("ada_data_stok", False))
        stok = max(_num(r.get("stok")), 0.0)
        need = daily * rest_days
        ss = _num(r.get("ss"))
        lost = max(need - stok, 0.0)
        if known and lost > 0:
            # Jumlah restock = kebutuhan + SS − stok (aturan Kurang di Ringkasan); potensi omzet = permintaan yang tidak tertutup stok.
            short = float(math.ceil(need + ss - stok))
            available = {code: (None if pd.isna(r.get(f"stok_{code}")) else _num(r.get(f"stok_{code}"))) for code in codes}
            if any(v is not None for v in available.values()):
                take, remaining = transfer_plan(short, available)
                action = "Restock: " + transfer_text(short, take, remaining, True)
            else:
                action = f"Restock {_units(short)} unit (stok Site 10062/10036 belum diunggah: cek DC, lalu PO)"
            out_day = stock_out_date(stok, daily, today)
            rows.append({
                "Jenis": "Stok", "SKU": sku, "Produk": label, "Tindakan": action,
                "Tenggat": "Sudah kosong" if stok <= 0 else (f"Habis ±{out_day:%d/%m}" if out_day else ""),
                "Potensi omzet": lost * price * factor,
                "Alasan": f"Prediksi {_units(daily)} unit/hari × {rest_days} hari = {_units(need)} unit + SS {_units(ss)}, stok {_units(stok)}",
            })
            continue
        expected = daily * recent_days
        got = float(sold.get(sku, 0.0))
        usual = float(before.get(sku, 0.0)) / prior_days if before else daily
        reachable = min(daily, usual)
        if sold and expected >= 3 and got < 0.6 * expected and got < 0.6 * reachable * recent_days and not (known and stok <= 0):
            gain = (reachable - got / recent_days) * price * rest_days * factor
            rows.append({
                "Jenis": "Harga & listing", "SKU": sku, "Produk": label,
                "Tindakan": "Cek harga vs pesaing, foto & judul listing, dan status iklan; pasang voucher toko bila harga kalah",
                "Tenggat": "Hari ini",
                "Potensi omzet": gain,
                "Alasan": f"Terjual {_units(got)} unit dalam {recent_days} hari; biasanya ±{_units(usual * recent_days)} unit "
                          f"({prior_days} hari sebelumnya), prediksi {_units(expected)} unit"
                          + ("" if known else "; stok belum diunggah"),
            })
            continue
        if not known:
            continue
        roas, basis = roas_estimate(r, default_roas)
        cost = _num(r.get("biaya_harian"))
        if basis == "default" or cost <= 0 or roas <= 0:
            continue
        margin = margin_pct.get(sku)
        if margin is not None and np.isfinite(margin) and margin <= 0:
            continue
        break_even = 100.0 / margin if margin and np.isfinite(margin) and margin > 0 else max(default_roas, 1.0)
        curve = default_curve(cost, roas)
        best_cost = curve.a / break_even - curve.b
        extra = min(max(best_cost - cost, 0.0), max(5.0 * cost, 5_000_000.0 / 30))
        spare_units = (stok - need - ss) / rest_days * 30
        extra = min(extra, unit_cap_to_cost(curve, cost, spare_units, price))
        if extra < 10_000:
            continue
        # Tambahan dari iklan dibatasi permintaan: paling banyak sebesar penjualan harian SKU itu sendiri (naik ≤ 100%).
        gain = min(curve.sales(cost + extra) - curve.sales(cost), daily * price) * rest_days * factor
        if gain <= 0:
            continue
        rows.append({
            "Jenis": "Iklan", "SKU": sku, "Produk": label,
            "Tindakan": f"Naikkan budget iklan harian {_rp(cost)} → {_rp(cost + extra)}",
            "Tenggat": "Hari ini",
            "Potensi omzet": gain,
            "Alasan": f"ROAS {basis} {roas:.1f}".replace(".", ",") + f", titik impas {break_even:.1f}".replace(".", ",")
                      + f"; stok cukup {_units(stok)} unit (> kebutuhan {_units(need)})",
        })
    if unpaid > 0:
        rows.append({
            "Jenis": "Kejar bayar", "SKU": "–", "Produk": f"{_units(unpaid_orders)} pesanan Belum Bayar",
            "Tindakan": "Chat pembeli yang belum bayar (pengingat + voucher ongkir bila perlu)",
            "Tenggat": "Hari ini", "Potensi omzet": unpaid * 0.3,
            "Alasan": f"Nominal menunggu bayar {_rp(unpaid)}; estimasi 30% berhasil dibayar",
        })
    frame = pd.DataFrame(rows, columns=[c for c in columns if c != "Prioritas"])
    if frame.empty:
        return pd.DataFrame(columns=columns)
    frame = frame.sort_values("Potensi omzet", ascending=False).head(limit).reset_index(drop=True)
    frame.insert(0, "Prioritas", range(1, len(frame) + 1))
    return frame
