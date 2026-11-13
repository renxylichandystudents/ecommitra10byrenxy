"""Bahan dialog Analisa prediksi per SKU: transaksi (masuk vs bersih), bulan berjalan, potensi, kompetitor, deskripsi.

Semua angka membawa rentang tanggalnya sendiri agar tidak dibaca untuk periode yang salah.
masuk  = semua pesanan (termasuk batal, Belum Bayar, retur);
bersih = tanpa batal & Belum Bayar, setelah retur; sales = Harga Setelah Diskon × QTY (sales produk).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

import numpy as np
import pandas as pd


def transaction_profile(lines: pd.DataFrame, key: str, lo: date, hi: date) -> dict:
    """Ringkasan transaksi satu SKU pada tanggal lo s.d. hi (inklusif) dari `normalize_lines` semua status."""
    out = {"start": lo, "end": hi, "pesanan": 0, "pembeli": 0, "alasan_batal": []}
    for name in ("masuk", "batal", "belum_bayar", "retur", "bersih"):
        out[f"qty_{name}"] = 0.0
        out[f"sales_{name}"] = 0.0
    if lines is None or lines.empty or lo > hi:
        return out
    days = pd.to_datetime(lines["order_time"], errors="coerce").dt.normalize()
    part = lines.loc[lines["item_key"].astype(str).eq(str(key)) & days.ge(pd.Timestamp(lo)) & days.le(pd.Timestamp(hi))]
    if part.empty:
        return out
    cancel, open_ = part["is_cancel"], part["is_open"]
    sold = ~cancel & ~open_
    ret_qty = np.minimum(part["returned_qty"], part["gross_qty"]).where(sold, 0.0)
    out.update(
        qty_masuk=float(part["gross_qty"].sum()),
        sales_masuk=float(part["line_value"].sum()),
        qty_batal=float(part.loc[cancel, "gross_qty"].sum()),
        sales_batal=float(part.loc[cancel, "line_value"].sum()),
        qty_belum_bayar=float(part.loc[open_, "gross_qty"].sum()),
        sales_belum_bayar=float(part.loc[open_, "line_value"].sum()),
        qty_retur=float(ret_qty.sum()),
        sales_retur=float(part["return_value"].where(sold, 0.0).sum()),
        pesanan=int(part["order_key"].nunique()),
        pembeli=int(part.loc[part["buyer"].ne(""), "buyer"].nunique()),
    )
    out["qty_bersih"] = float((part["gross_qty"].where(sold, 0.0) - ret_qty).sum())
    out["sales_bersih"] = float((part["line_value"] - part["return_value"]).where(sold, 0.0).sum())
    reasons = part.loc[cancel & part["cancel_reason"].ne(""), "cancel_reason"]
    out["alasan_batal"] = [(text, int(n)) for text, n in reasons.value_counts().head(3).items()]
    return out


def month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def same_span_last_month(first: date, cutoff: date) -> tuple[date, date]:
    """Tanggal 1 s.d. tanggal yang sama bulan lalu (dipotong ke akhir bulan lalu), pembanding bulan berjalan yang adil."""
    prev_first = (first - timedelta(days=1)).replace(day=1)
    return prev_first, min(prev_first.replace(day=1) + timedelta(days=cutoff.day - 1), month_end(prev_first))


def running_month(
    lines: pd.DataFrame,
    key: str,
    today: date,
    cutoff: date,
    rest_weight: float,
    daily_qty: float,
    price: float,
    *,
    basis: str,
) -> dict:
    """Bulan berjalan satu SKU: aktual tgl 1 s.d. hari penuh terakhir (masuk & bersih), prediksi sisa bulan, proyeksi.

    Proyeksi = aktual dasar `basis` (bersih/masuk, sama dengan dasar prediksi) + laju prediksi harian × pola hari sisa bulan."""
    first = today.replace(day=1)
    end = month_end(today)
    actual = transaction_profile(lines, key, first, cutoff) if cutoff >= first else transaction_profile(lines, key, first, first - timedelta(days=1))
    prev_lo, prev_hi = same_span_last_month(first, max(cutoff, first))
    last_same = transaction_profile(lines, key, prev_lo, prev_hi) if cutoff >= first else None
    last_full = transaction_profile(lines, key, prev_lo, month_end(prev_lo))
    rest_start = max(first, cutoff + timedelta(days=1))
    rest_qty = max(float(daily_qty), 0.0) * float(rest_weight)
    rest_sales = rest_qty * max(float(price), 0.0)
    proj_qty = actual[f"qty_{basis}"] + rest_qty
    proj_sales = actual[f"sales_{basis}"] + rest_sales
    return {
        "first": first,
        "end": end,
        "cutoff": cutoff,
        "rest_start": rest_start,
        "rest_days": max((end - rest_start).days + 1, 0),
        "basis": basis,
        "actual": actual,
        "last_same": last_same,
        "last_full": last_full,
        "rest_qty": rest_qty,
        "rest_sales": rest_sales,
        "proj_qty": proj_qty,
        "proj_sales": proj_sales,
        "vs_last_full_pct": (proj_qty / last_full[f"qty_{basis}"] - 1) * 100 if last_full[f"qty_{basis}"] > 0 else np.nan,
        "vs_last_same_pct": (actual[f"qty_{basis}"] / last_same[f"qty_{basis}"] - 1) * 100 if last_same and last_same[f"qty_{basis}"] > 0 else np.nan,
    }


def stock_potential(stock: float | None, daily_qty: float, price: float, rest_weight: float, rest_days: int) -> dict:
    """Potensi sisa bulan yang tidak tertutup stok Site 10037 (tanpa transfer/PO): QTY dan sales produk."""
    need = max(float(daily_qty), 0.0) * float(rest_weight)
    if stock is None or not np.isfinite(stock):
        return {"need": need, "covered": np.nan, "short_qty": np.nan, "short_sales": np.nan}
    covered = min(max(float(stock), 0.0), need)
    short = max(need - covered, 0.0)
    return {"need": need, "covered": covered, "short_qty": short, "short_sales": short * max(float(price), 0.0), "days": rest_days}


def description_review(text: str) -> dict:
    """Aspek deskripsi yang sudah ada / belum ada (kamus yang sama dengan halaman Rekomendasi) + panjang teks."""
    from src.core.nlp_competitor import description_strengths

    text = str(text or "")
    if not text.strip():
        return {"ada": False, "panjang": 0, "lengkap": [], "kurang": []}
    aspects = description_strengths(text)
    return {
        "ada": True,
        "panjang": len(text),
        "lengkap": [name for name, ok in aspects.items() if ok],
        "kurang": [name for name, ok in aspects.items() if not ok],
    }


def find_description(descriptions: pd.DataFrame | None, *, product_code: str, sku: str, name: str) -> str:
    """Deskripsi produk: cocokkan Kode Produk, lalu SKU, lalu nama (urutan sama dengan halaman Rekomendasi)."""
    if descriptions is None or descriptions.empty or "description" not in descriptions.columns:
        return ""
    from src.core.nlp_competitor import clean_text

    for column, value in (("product_code", product_code), ("sku", sku)):
        value = str(value or "").strip()
        if value and value.lower() not in {"none", "nan"} and column in descriptions.columns:
            hit = descriptions.loc[descriptions[column].astype(str).str.strip().eq(value), "description"]
            if not hit.empty:
                return str(hit.iloc[0] or "")
    if "product_name" in descriptions.columns and name:
        target = clean_text(name)
        hit = descriptions.loc[descriptions["product_name"].map(clean_text).eq(target), "description"]
        if not hit.empty:
            return str(hit.iloc[0] or "")
    return ""


def competitor_view(competitors: pd.DataFrame | None, key: str, name: str) -> dict:
    """Posisi produk di daftar peringkat Shopee dan pembanding teratas (aturan sama dengan halaman Rekomendasi)."""
    from src.core.nlp_competitor import competitor_lists, keyword_set, strip_packing_words

    blank = {"ada_data": False, "daftar": "", "posisi": np.nan, "perubahan": np.nan, "sumber": "", "pembanding": [], "kata_kunci": [], "tanggal": None}
    if competitors is None or competitors.empty or "product_name" not in competitors.columns:
        return blank
    own = pd.DataFrame({"item_key": [str(key)], "product_name": [str(name)]})
    lists, comp = competitor_lists(own, competitors)
    info = lists.get(str(key), {})
    picked = info.get("pembanding", [])
    stamp = pd.to_datetime(competitors.get("_submitted_at"), errors="coerce").max() if "_submitted_at" in competitors.columns else pd.NaT
    out = dict(blank, ada_data=True, tanggal=None if pd.isna(stamp) else stamp.date())
    if not picked:
        return out
    rows = comp.iloc[picked]
    titles = [strip_packing_words(t) for t in rows["product_name"]]
    primary, _support = keyword_set(name, titles, [w * 10 for w in info.get("bobot", [])])
    out.update(
        daftar=info.get("daftar", ""),
        posisi=info.get("posisi", np.nan),
        perubahan=info.get("perubahan", np.nan),
        sumber=info.get("sumber", ""),
        pembanding=[
            {"nama": str(r["product_name"]), "toko": str(r.get("shop_name", "") or ""), "posisi": r.get("_rank"), "perubahan": r.get("_change")}
            for _, r in rows.head(3).iterrows()
        ],
        kata_kunci=[k for k in primary if k.lower() not in str(name).lower()][:5],
    )
    return out
