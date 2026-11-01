"""Tabel keputusan per SKU untuk semua tab.

Satu fungsi membentuk angka Hari ini, Bulan ini, dan periode tambahan
(Quartal/Semester/Tahun), supaya Ringkasan, Prediksi, Rekomendasi, dan Laporan
membaca angka yang sama.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from src.core.inventory import days_cover, inventory_status

PERIOD_MONTHS = {"bulan": 1, "kuartal": 3, "semester": 6, "tahun": 12}
PERIOD_LABELS = {"bulan": "Bulan", "kuartal": "Quartal", "semester": "Semester", "tahun": "Tahun"}


@dataclass(frozen=True)
class PeriodGroup:
    prefix: str
    label: str
    days: int
    extra: bool


def period_groups(period: str, today: date) -> list[PeriodGroup]:
    """Hari ini dan Bulan ini selalu ada. Periode tambahan hanya untuk Quartal/Semester/Tahun."""
    ref = pd.Timestamp(today).normalize()
    month_end = ref + pd.offsets.MonthEnd(0)
    groups = [
        PeriodGroup("d", "Hari ini", 1, False),
        PeriodGroup("m", "Bulan ini", int((month_end - ref).days) + 1, False),
    ]
    if period != "bulan":
        end = ref + pd.DateOffset(months=PERIOD_MONTHS[period]) - pd.Timedelta(days=1)
        groups.append(PeriodGroup("p", PERIOD_LABELS[period], int((end - ref).days) + 1, True))
    return groups


def month_to_yesterday(orders: pd.DataFrame, today: date, *, sku_col: str = "item_key") -> pd.DataFrame:
    columns = [sku_col, "actual_mtd_qty", "actual_mtd_sales"]
    if orders is None or orders.empty or not {sku_col, "order_time", "qty"} <= set(orders.columns):
        return pd.DataFrame(columns=columns)
    ref = pd.Timestamp(today).normalize()
    start = ref.replace(day=1)
    times = pd.to_datetime(orders["order_time"], errors="coerce").dt.normalize()
    part = orders.loc[times.ge(start) & times.lt(ref)]
    if part.empty:
        return pd.DataFrame(columns=columns)
    sales = part["sales"] if "sales" in part.columns else pd.Series(0.0, index=part.index)
    grouped = part.assign(_sales=sales).groupby(sku_col, as_index=False).agg(
        actual_mtd_qty=("qty", "sum"),
        actual_mtd_sales=("_sales", "sum"),
    )
    return grouped


def latest_stock_by_sku(stock_frame: pd.DataFrame | None) -> pd.DataFrame:
    columns = ["sku", "stok", "harga_stok", "stock_snapshot_at"]
    if stock_frame is None or stock_frame.empty or not {"sku", "stock_dc_cikupa"} <= set(stock_frame.columns):
        return pd.DataFrame(columns=columns)
    work = stock_frame.copy()
    work["sku"] = work["sku"].fillna("").astype(str).str.strip().str.replace(r"^(\d+)\.0+$", r"\1", regex=True)
    work = work.loc[work["sku"].ne("")]
    if "_submitted_at" in work.columns:
        latest = work["_submitted_at"].astype(str).max()
        work = work.loc[work["_submitted_at"].astype(str).eq(latest)]
        stamp = latest
    else:
        stamp = ""
    work["stok"] = pd.to_numeric(work["stock_dc_cikupa"], errors="coerce").fillna(0.0).clip(lower=0)
    price = pd.to_numeric(work["price"], errors="coerce") if "price" in work.columns else pd.Series(np.nan, index=work.index)
    work["harga_stok"] = price
    grouped = work.groupby("sku", as_index=False).agg(stok=("stok", "sum"), harga_stok=("harga_stok", "max"))
    grouped["stock_snapshot_at"] = stamp
    return grouped


def build_decision_table(
    view: pd.DataFrame,
    *,
    period: str,
    today: date,
    horizon_days: int,
    orders: pd.DataFrame | None = None,
    stock_frame: pd.DataFrame | None = None,
    zero_duration: pd.DataFrame | None = None,
    lead_time_days: float = 7.0,
) -> pd.DataFrame:
    """Tambah kolom keputusan per periode pada tabel produk.

    Input `view` minimal punya item_key, sku, pred_qty (horizon bergulir), pred_sales,
    safety_stock. Output per prefix (d, m, p): {p}_qty, {p}_sales, {p}_ss, {p}_butuh,
    {p}_stok, {p}_selisih, {p}_pct, {p}_status.

    - Hari ini = laju harian prediksi.
    - Bulan ini = realisasi tanggal 1 s.d. kemarin + prediksi sisa bulan; tidak pernah
      lebih kecil dari realisasi.
    - Butuh = prediksi permintaan yang belum terjadi pada periode itu + SS, karena stok
      hari ini hanya menutup permintaan yang akan datang.
    """
    if view is None or view.empty:
        return view
    out = view.copy()
    horizon = max(int(horizon_days), 1)
    pred_qty = pd.to_numeric(out.get("pred_qty", 0), errors="coerce").fillna(0.0).clip(lower=0)
    pred_sales = pd.to_numeric(out.get("pred_sales", 0), errors="coerce").fillna(0.0).clip(lower=0)
    out["pred_harian"] = pred_qty / horizon
    price = np.where(pred_qty > 0, pred_sales / pred_qty.replace(0, np.nan), np.nan)
    out["harga_bersih"] = pd.Series(price, index=out.index)
    if out["harga_bersih"].isna().any() and {"sales_total", "qty_total"} <= set(out.columns):
        fallback = out["sales_total"].astype(float) / out["qty_total"].astype(float).replace(0, np.nan)
        out["harga_bersih"] = out["harga_bersih"].fillna(fallback)
    out["harga_bersih"] = out["harga_bersih"].fillna(0.0)
    ss = pd.to_numeric(out.get("safety_stock", 0), errors="coerce").fillna(0.0).clip(lower=0)
    out["ss"] = np.ceil(ss)

    mtd = month_to_yesterday(orders, today) if orders is not None else pd.DataFrame()
    if not mtd.empty:
        out = out.merge(mtd, on="item_key", how="left")
    for column in ("actual_mtd_qty", "actual_mtd_sales"):
        if column not in out.columns:
            out[column] = 0.0
        out[column] = out[column].fillna(0.0)

    stock = latest_stock_by_sku(stock_frame)
    has_stock = not stock.empty
    if has_stock and "sku" in out.columns:
        key = out["sku"].fillna("").astype(str).str.strip()
        out = out.assign(_sku=key).merge(stock.rename(columns={"sku": "_sku"}), on="_sku", how="left").drop(columns="_sku")
    if "stok" not in out.columns:
        out["stok"] = np.nan
        out["harga_stok"] = np.nan
        out["stock_snapshot_at"] = ""
    out["ada_data_stok"] = out["stok"].notna()

    if zero_duration is not None and not zero_duration.empty and "sku" in out.columns:
        zero = zero_duration.rename(columns={"sku": "_sku"})[["_sku", "zero_since", "lama_kosong_hari"]]
        key = out["sku"].fillna("").astype(str).str.strip()
        out = out.assign(_sku=key).merge(zero, on="_sku", how="left").drop(columns="_sku")
    if "lama_kosong_hari" not in out.columns:
        out["zero_since"] = None
        out["lama_kosong_hari"] = np.nan

    for group in period_groups(period, today):
        p = group.prefix
        if p == "m":
            remaining = out["pred_harian"] * group.days
            qty = out["actual_mtd_qty"] + remaining
            qty = np.maximum(qty, out["actual_mtd_qty"])
            sales = out["actual_mtd_sales"] + remaining * out["harga_bersih"]
            future_need = remaining
        elif p == "p":
            qty = pred_qty.astype(float)
            sales = pred_sales.astype(float)
            future_need = qty
        else:
            qty = out["pred_harian"].astype(float)
            sales = qty * out["harga_bersih"]
            future_need = qty
        out[f"{p}_qty"] = np.rint(qty)
        out[f"{p}_sales"] = np.rint(sales)
        out[f"{p}_ss"] = out["ss"]
        out[f"{p}_butuh"] = np.ceil(future_need + out["ss"])
        stok = out["stok"]
        out[f"{p}_stok"] = stok
        out[f"{p}_selisih"] = stok - out[f"{p}_butuh"]
        out[f"{p}_pct"] = np.where(out[f"{p}_butuh"] > 0, out[f"{p}_selisih"] / out[f"{p}_butuh"], 0.0)
        statuses = []
        for value, need, guard, known in zip(stok, out[f"{p}_butuh"], out["ss"], out["ada_data_stok"]):
            if not known:
                statuses.append("Tanpa data stok")
            else:
                statuses.append(inventory_status(float(value), float(need), float(guard))[0])
        out[f"{p}_status"] = statuses

    out["hari_cukup"] = [
        days_cover(float(value), float(rate)) if known else np.nan
        for value, rate, known in zip(out["stok"], out["pred_harian"], out["ada_data_stok"])
    ]
    ref = pd.Timestamp(today).normalize()
    out["tanggal_habis"] = [
        (ref + pd.Timedelta(days=int(days))).date() if pd.notna(days) and np.isfinite(days) else None
        for days in out["hari_cukup"]
    ]
    out["di_bawah_ss"] = out["ada_data_stok"] & (out["stok"].fillna(0) < out["ss"])
    out["rop"] = np.ceil(out["pred_harian"] * float(lead_time_days) + out["ss"])
    return out


def period_actuals(orders: pd.DataFrame, keys: list[str], *, period: str, today: date) -> dict[str, dict[str, float]]:
    """Actual Top 50 dan seluruh toko per kelompok periode (untuk matriks Ringkasan total Top 50).

    Hari ini = tanggal terakhir yang ada transaksi (≤ hari ini); Bulan ini = tanggal 1 s.d. kemarin;
    periode tambahan = 3/6/12 bulan terakhir s.d. kemarin.
    """
    out: dict[str, dict[str, float]] = {}
    if orders is None or orders.empty:
        return out
    ref = pd.Timestamp(today).normalize()
    days = pd.to_datetime(orders["order_time"], errors="coerce").dt.normalize()
    last_day = min(days.max(), ref)
    in_top = orders["item_key"].astype(str).isin(set(keys))
    spans = {"d": (last_day, last_day + pd.Timedelta(days=1)), "m": (ref.replace(day=1), ref)}
    if period != "bulan":
        spans["p"] = (ref - pd.DateOffset(months=PERIOD_MONTHS[period]), ref)
    for prefix, (lo, hi) in spans.items():
        mask = days.ge(lo) & days.lt(hi)
        part = orders.loc[mask & in_top]
        out[prefix] = {
            "qty": float(part["qty"].sum()),
            "sales": float(part["sales"].sum()) if "sales" in part.columns else 0.0,
            "store_sales": float(orders.loc[mask, "sales"].sum()) if "sales" in orders.columns else 0.0,
        }
    return out


def lama_kosong_text(row: pd.Series) -> str:
    days = row.get("lama_kosong_hari")
    since = row.get("zero_since")
    if days is None or pd.isna(days):
        return "-"
    since_text = ""
    if since is not None and not (isinstance(since, float) and pd.isna(since)):
        stamp = pd.Timestamp(since)
        months = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
        since_text = f", sejak {stamp.day} {months[stamp.month - 1]}"
    return f"{int(days)} hari{since_text}"


def safety_stock_summary(table: pd.DataFrame, prefix: str = "m") -> dict[str, float]:
    """Total SS, jumlah SKU stok < prediksi + SS, dan jumlah SKU stok < SS."""
    if table is None or table.empty or f"{prefix}_butuh" not in table.columns:
        return {"total_ss": 0, "sku_kurang_butuh": 0, "sku_di_bawah_ss": 0, "sku_tanpa_stok_data": 0}
    known = table["ada_data_stok"] if "ada_data_stok" in table.columns else pd.Series(False, index=table.index)
    stok = table["stok"].fillna(0)
    return {
        "total_ss": float(table["ss"].sum()),
        "sku_kurang_butuh": int((known & (stok < table[f"{prefix}_butuh"])).sum()),
        "sku_di_bawah_ss": int((known & (stok < table["ss"])).sum()),
        "sku_tanpa_stok_data": int((~known).sum()),
    }
