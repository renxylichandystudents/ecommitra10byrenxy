"""Prediksi vs aktual harian per SKU (Revisi Final 4B).

  pct = aktual_qty / pred_qty
  Melebihi > 105%, Tercapai 95–105%, Hampir 80–95%, Tidak < 80%  (pred 0 & aktual > 0 → Melebihi)
  Penyebab: stok D = 0 → "Stok kosong"; stok < pred → "Stok tinggal N"; biaya iklan D < 50% rata-rata 7 hari
            → "Iklan turun"; harga D > rata-rata 7 hari + 5% → "Harga naik"; selain itu "—"
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

STATUS_ORDER = ("Melebihi", "Tercapai", "Hampir", "Tidak")


def achievement_status(actual: float, pred: float) -> str:
    if pred <= 0:
        return "Melebihi" if actual > 0 else "Tercapai"
    pct = actual / pred
    if pct > 1.05:
        return "Melebihi"
    if pct >= 0.95:
        return "Tercapai"
    if pct >= 0.80:
        return "Hampir"
    return "Tidak"


def cause(*, stock: float | None, pred: float, ad_cost_day: float | None, ad_cost_avg7: float | None, price_day: float | None, price_avg7: float | None) -> str:
    if stock is not None and np.isfinite(stock):
        if stock <= 0:
            return "Stok kosong"
        if stock < pred:
            return f"Stok tinggal {int(stock)}"
    if ad_cost_day is not None and ad_cost_avg7 and ad_cost_avg7 > 0 and ad_cost_day < 0.5 * ad_cost_avg7:
        return "Iklan turun"
    if price_day is not None and price_avg7 and price_avg7 > 0 and price_day > price_avg7 * 1.05:
        return "Harga naik"
    return "—"


def pick_snapshot(runs: pd.DataFrame, actual_day: date) -> int | None:
    """Run terakhir yang dibuat SEBELUM tanggal aktual D (created_at < D)."""
    if runs is None or runs.empty:
        return None
    stamps = pd.to_datetime(runs["run_at"], errors="coerce")
    eligible = runs.loc[stamps < pd.Timestamp(actual_day)]
    if eligible.empty:
        return None
    return int(eligible.loc[pd.to_datetime(eligible["run_at"]).idxmax(), "id"])


def daily_comparison(
    snapshot: pd.DataFrame,
    lines: pd.DataFrame,
    day: date,
    *,
    stock_by_sku: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Baris per SKU untuk tanggal D: prediksi (snapshot) vs aktual bersih (QTY & omzet)."""
    columns = ["sku", "varian", "pred_qty", "pred_sales", "aktual_qty", "aktual_sales", "pct", "status", "penyebab"]
    if snapshot is None or snapshot.empty:
        return pd.DataFrame(columns=columns)
    snap = snapshot.copy()
    snap["tanggal"] = pd.to_datetime(snap["tanggal"], errors="coerce").dt.date
    snap = snap.loc[snap["tanggal"] == day]
    if snap.empty:
        return pd.DataFrame(columns=columns)
    actual = pd.DataFrame(columns=["sku", "aktual_qty", "aktual_sales", "harga"])
    price7 = {}
    if lines is not None and not lines.empty:
        times = pd.to_datetime(lines["order_time"], errors="coerce").dt.date
        today_lines = lines.loc[times == day]
        actual = today_lines.groupby(today_lines["sku"].astype(str)).agg(aktual_qty=("qty", "sum"), aktual_sales=("sales", "sum")).reset_index()
        actual["harga"] = actual["aktual_sales"] / actual["aktual_qty"].replace(0, np.nan)
        week = lines.loc[(times < day) & (times >= day - timedelta(days=7))]
        if not week.empty:
            grouped = week.groupby(week["sku"].astype(str)).agg(q=("qty", "sum"), s=("sales", "sum"))
            price7 = (grouped["s"] / grouped["q"].replace(0, np.nan)).to_dict()
    merged = snap.groupby(snap["sku"].astype(str)).agg(varian=("varian", "first"), pred_qty=("pred_qty", "sum"), pred_sales=("pred_sales", "sum")).reset_index()
    merged = merged.merge(actual, on="sku", how="left")
    merged[["aktual_qty", "aktual_sales"]] = merged[["aktual_qty", "aktual_sales"]].fillna(0.0)
    stock_by_sku = stock_by_sku or {}
    merged["pct"] = np.where(merged["pred_qty"] > 0, merged["aktual_qty"] / merged["pred_qty"].replace(0, np.nan) * 100, np.nan)
    merged["status"] = [achievement_status(a, p) for a, p in zip(merged["aktual_qty"], merged["pred_qty"])]
    merged["penyebab"] = [
        cause(
            stock=stock_by_sku.get(sku),
            pred=p,
            ad_cost_day=None,
            ad_cost_avg7=None,
            price_day=h if pd.notna(h) else None,
            price_avg7=price7.get(sku),
        )
        if status in {"Hampir", "Tidak"}
        else "—"
        for sku, p, h, status in zip(merged["sku"], merged["pred_qty"], merged.get("harga", pd.Series(np.nan, index=merged.index)), merged["status"])
    ]
    return merged[columns]


def lost_sales_from_stock(rows: pd.DataFrame) -> float:
    """Potensi omzet hilang = Σ max(0, pred_sales − aktual_sales) untuk SKU stok kosong."""
    if rows is None or rows.empty:
        return 0.0
    mask = rows["penyebab"].astype(str).str.startswith("Stok")
    gap = (rows.loc[mask, "pred_sales"] - rows.loc[mask, "aktual_sales"]).clip(lower=0)
    return float(gap.sum())


# ---------------------------------------------------------------------------
# Diagnosa penyebab yang bisa ditindaklanjuti (per SKU, untuk satu tanggal D)
# ---------------------------------------------------------------------------

def _rp(value: float) -> str:
    return "Rp" + f"{value:,.0f}".replace(",", ".")


def _num(value: float, decimals: int = 1) -> str:
    text = f"{value:,.{decimals}f}".replace(",", "#").replace(".", ",").replace("#", ".")
    return text[:-2] if decimals == 1 and text.endswith(",0") else text


def _tgl(day) -> str:
    months = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
    return f"{day.day} {months[day.month - 1]}"


def price_change(daily: pd.DataFrame, day: date, *, lookback: int = 45, tolerance: float = 0.03) -> dict | None:
    """Perubahan harga jual terakhir s.d. D. `daily`: index tanggal, kolom q (qty), s (omzet), lp (harga coret), disc (diskon toko).

    Harga efektif harian = omzet / qty. Dari hari terjual terakhir mundur ke belakang selama harganya
    masih ±3% dari harga sekarang; hari pertama yang berbeda = harga lama. Laju jual sebelum (maks 14 hari)
    dan sesudah perubahan dihitung per hari kalender (hari tanpa penjualan ikut dihitung 0).
    """
    rate_col = "qc" if "qc" in daily.columns else "q"
    sold = daily.loc[(daily["q"] > 0) & (daily.index <= day) & (daily.index >= day - timedelta(days=lookback))]
    if len(sold) < 2:
        return None
    price = sold["s"] / sold["q"]
    current = float(price.iloc[-1])
    if current <= 0:
        return None
    since = sold.index[-1]
    old_idx = None
    for idx in range(len(sold) - 2, -1, -1):
        if abs(float(price.iloc[idx]) / current - 1) > tolerance:
            old_idx = idx
            break
        since = sold.index[idx]
    if old_idx is None:
        return None
    old_day = sold.index[old_idx]
    old = float(price.iloc[old_idx])
    # Harga berubah sesudah penjualan terakhir dengan harga lama: hitung "sejak" dari hari berikutnya,
    # supaya hari tanpa penjualan setelah perubahan ikut masuk ke laju sesudah (bukan sebelum).
    since = min(since, old_day + timedelta(days=1))
    before = daily.loc[(daily.index < since) & (daily.index >= since - timedelta(days=14))]
    before_days = max((since - max(before.index.min(), since - timedelta(days=14))).days, 1) if not before.empty else 0
    after_days = (day - since).days + 1
    lp_old = float(sold["lp"].iloc[old_idx]) if "lp" in sold else np.nan
    lp_now = float(sold["lp"].iloc[-1]) if "lp" in sold else np.nan
    return {
        "since": since,
        "old_day": old_day,
        "old": old,
        "new": current,
        "change": current / old - 1,
        # Laju memakai qty yang dibatasi per pesanan (qc) agar 1 pesanan borongan tidak menggelembungkan laju.
        "rate_before": float(before[rate_col].sum()) / before_days if before_days else np.nan,
        "rate_after": float(daily.loc[(daily.index >= since) & (daily.index <= day), rate_col].sum()) / after_days,
        "before_start": since - timedelta(days=before_days) if before_days else since,
        "after_days": after_days,
        # None = harga coret tidak diketahui; True = harga coret ikut berubah; False = hanya diskon yang berubah.
        "list_changed": (abs(lp_now / lp_old - 1) > tolerance) if np.isfinite(lp_old) and np.isfinite(lp_now) and lp_old > 0 else None,
    }


def diagnose(
    rows: pd.DataFrame,
    lines: pd.DataFrame,
    day: date,
    *,
    lines_all: pd.DataFrame | None = None,
    stock_by_sku: dict[str, float] | None = None,
    dc_by_sku: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Tambahkan kolom `penyebab` (dengan angka) dan `aksi` untuk tiap SKU pada tanggal D.

    Urutan pemeriksaan (yang pertama cocok dipakai, faktor lain yang juga cocok ditambahkan ringkas):
      Kurang dari prediksi : stok habis → harga naik / diskon berakhir → pesanan batal hari itu →
                             laku tidak setiap hari (wajar) → permintaan turun → toko sepi → fluktuasi biasa.
      Melebihi prediksi    : harga turun / diskon → pesanan borongan → permintaan naik → toko ramai → lonjakan harian.
    """
    out = rows.copy()
    if out.empty:
        out["aksi"] = []
        out["harga_sejak"] = []
        return out
    stock_by_sku = stock_by_sku or {}
    dc_by_sku = dc_by_sku or {}
    work = lines.assign(
        sku=lines["sku"].astype(str),
        d=pd.to_datetime(lines["order_time"], errors="coerce").dt.date,
        q=pd.to_numeric(lines["qty"], errors="coerce").fillna(0.0),
        s=pd.to_numeric(lines["sales"], errors="coerce").fillna(0.0),
    )
    work = work.loc[work["d"].notna() & (work["d"] <= day) & (work["d"] >= day - timedelta(days=60))]
    lp = pd.to_numeric(work["list_price"], errors="coerce") if "list_price" in work.columns else pd.Series(np.nan, index=work.index)
    work = work.assign(lp=lp * work["q"])
    # Qty per pesanan dibatasi (maks. 3 atau 2× median pesanan SKU tsb) untuk menghitung laju jual "normal".
    oid = work["order_id"].astype(str) if "order_id" in work.columns else pd.Series(work.index.astype(str), index=work.index)
    per_order = work.assign(o=oid).groupby(["sku", "d", "o"])["q"].sum().reset_index()
    cap = per_order.groupby("sku")["q"].median().mul(2).clip(lower=3)
    per_order["qc"] = per_order["q"].clip(upper=per_order["sku"].map(cap))
    capped = per_order.groupby(["sku", "d"])["qc"].sum()
    store_orders = per_order.groupby("d")["o"].nunique()
    daily_all = work.groupby(["sku", "d"]).agg(q=("q", "sum"), s=("s", "sum"), lp=("lp", "sum"))
    daily_all["qc"] = capped.reindex(daily_all.index).fillna(0.0)
    daily_all["lp"] = daily_all["lp"] / daily_all["q"].replace(0, np.nan)
    store = work.groupby("d")["q"].sum()
    store_today = float(store.get(day, 0.0))
    store_prev = store.loc[(store.index < day) & (store.index >= day - timedelta(days=14))]
    store_ratio = store_today / float(store_prev.mean()) if len(store_prev) and store_prev.mean() > 0 else np.nan
    today_lines = work.loc[work["d"] == day]
    max_order = today_lines.groupby(["sku", today_lines.get("order_id", today_lines.index).astype(str)])["q"].sum().groupby(level=0).max() if not today_lines.empty else pd.Series(dtype=float)
    cancel = {}
    if lines_all is not None and not lines_all.empty and "status" in lines_all.columns:
        from src.ingest import cancelled_status_mask

        stamp = pd.to_datetime(lines_all["order_time"], errors="coerce").dt.date
        part = lines_all.loc[(stamp == day) & cancelled_status_mask(lines_all["status"])]
        if not part.empty:
            gq = pd.to_numeric(part.get("gross_qty", part["qty"]), errors="coerce").fillna(0.0)
            reasons = part.get("cancel_reason", pd.Series("", index=part.index)).fillna("").astype(str).str.replace(r"^.*Alasan:\s*", "", regex=True)
            frame = pd.DataFrame({"sku": part["sku"].astype(str), "q": gq, "r": reasons})
            for sku, grp in frame.groupby("sku"):
                top = grp.loc[grp["r"].ne(""), "r"].value_counts()
                cancel[sku] = (float(grp["q"].sum()), str(top.index[0]) if len(top) else "")

    penyebab, aksi = [], []
    price_since: list = []
    for row in out.itertuples(index=False):
        sku = str(row.sku)
        pred, act, status = float(row.pred_qty or 0), float(row.aktual_qty or 0), str(row.status)
        try:
            daily = daily_all.loc[sku]
        except KeyError:
            daily = pd.DataFrame(columns=["q", "s", "lp", "qc"])
        full = daily["q"].reindex(pd.date_range(day - timedelta(days=29), day).date, fill_value=0.0)
        last30 = full.iloc[:-1]
        avg30 = float(last30.mean()) if len(last30) else 0.0
        avg7 = float(last30.iloc[-7:].mean()) if len(last30) else 0.0
        sold_days = int((last30 > 0).sum())
        change = price_change(daily, day) if not daily.empty else None
        recent_change = change is not None and (day - change["since"]).days <= 30
        notes: list[str] = []
        todo = ""
        if status in {"Hampir", "Tidak"}:
            stock = stock_by_sku.get(sku)
            dc = float(dc_by_sku.get(sku) or 0)
            if stock is not None and np.isfinite(stock) and stock < max(pred, 1):
                notes.append("Stok kosong" if stock <= 0 else f"Stok tinggal {int(stock)} (prediksi {_num(pred)})")
                todo = f"Isi stok dari DC ({int(dc)} unit tersedia)" if dc > 0 else "Ajukan pengadaan / restock segera"
            # Harga naik dianggap penyebab hanya bila laju jual memang turun setelah kenaikan (≥15%).
            # Harga naik dianggap penyebab bila laju jual SKU turun ≥15% setelah kenaikan DAN turunnya lebih dalam
            # daripada tren toko di periode yang sama (jadi bukan karena toko secara umum sedang sepi).
            store_trend = np.nan
            if change is not None:
                sb = store_orders.loc[(store_orders.index >= change["before_start"]) & (store_orders.index < change["since"])]
                sa = store_orders.loc[(store_orders.index >= change["since"]) & (store_orders.index <= day)]
                if len(sb) and len(sa) and sb.mean() > 0:
                    store_trend = float(sa.mean() / sb.mean())
            sku_trend = change["rate_after"] / change["rate_before"] if change is not None and change["rate_before"] else np.nan
            price_hurt = (
                recent_change and change["change"] > 0.03
                and np.isfinite(sku_trend) and sku_trend < 0.85
                and (not np.isfinite(store_trend) or sku_trend < 0.85 * store_trend)
            )
            if price_hurt:
                kind = "Diskon toko berakhir, harga naik" if change["list_changed"] is False else "Harga naik"
                toko = f", toko {'+' if store_trend >= 1 else ''}{_num((store_trend - 1) * 100, 0)}%" if np.isfinite(store_trend) else ""
                drop = f"; laku {_num(change['rate_before'])} → {_num(change['rate_after'])}/hari ({_num((sku_trend - 1) * 100, 0)}%{toko})"
                price_since.append((sku, change["since"]))
                notes.append(f"{kind} {_num(change['change'] * 100)}% sejak {_tgl(change['since'])} ({_rp(change['old'])} → {_rp(change['new'])}){drop}")
                todo = todo or (
                    f"Tinjau harga: kembali ke ±{_rp(change['old'])} atau beri voucher/diskon toko; bandingkan harga kompetitor"
                )
            got = cancel.get(sku)
            if got and got[0] > 0:
                reason = f", alasan utama: {got[1]}" if got[1] else ""
                notes.append(f"Batal {int(got[0])} pcs hari itu{reason}")
                if act + got[0] >= 0.8 * pred:
                    todo = todo or "Pesanan sebenarnya ada; tindak lanjuti pembeli yang batal (chat/voucher) dan cek alasan batal"
            if not notes:
                if avg30 >= 0.3 and avg7 == 0:
                    notes.append(f"Tidak terjual sama sekali 7 hari terakhir (sebelumnya {_num(avg30)}/hari)")
                    todo = "Cek stok di Shopee, status listing (nonaktif/diturunkan), dan harga — kemungkinan produk tidak tampil"
                elif sold_days <= 18 and pred < 2:
                    notes.append(f"Laku tidak setiap hari: terjual {sold_days} dari 30 hari terakhir, rata-rata {_num(avg30)}/hari — hari sepi wajar")
                    todo = "Belum perlu tindakan; pantau total 7 hari"
                elif avg30 > 0 and avg7 < 0.7 * avg30:
                    notes.append(f"Permintaan turun: rata-rata 7 hari {_num(avg7)}/hari vs 30 hari {_num(avg30)}/hari")
                    todo = "Cek iklan, ulasan/rating terbaru, dan harga kompetitor; pertimbangkan promosi"
                elif np.isfinite(store_ratio) and store_ratio < 0.85:
                    notes.append(f"Seluruh toko sepi: penjualan toko {_num(store_ratio * 100, 0)}% dari rata-rata 14 hari")
                    todo = "Bukan masalah SKU; pantau besok"
                else:
                    notes.append(f"Fluktuasi harian biasa (rata-rata 7 hari {_num(avg7)}/hari)")
                    todo = "Pantau; tindakan bila 3 hari berturut-turut di bawah prediksi"
        elif status == "Melebihi":
            biggest = float(max_order.get(sku, 0.0)) if len(max_order) else 0.0
            if change is not None and (day - change["since"]).days <= 7 and change["change"] < -0.03:
                kind = "Diskon toko" if change["list_changed"] is False else "Harga turun"
                notes.append(f"{kind} {_num(abs(change['change']) * 100)}% sejak {_tgl(change['since'])} ({_rp(change['old'])} → {_rp(change['new'])})")
                todo = "Pastikan stok cukup untuk laju baru; cek margin masih aman"
            if biggest >= 3 and act > 0 and biggest >= 0.3 * act:
                notes.append(f"Ada pesanan borongan {int(biggest)} pcs dalam 1 pesanan")
                todo = todo or "Lonjakan dari 1 pembeli, bukan tren; jangan naikkan stok berlebihan"
            if not notes:
                if avg30 > 0 and avg7 > 1.3 * avg30:
                    notes.append(f"Permintaan naik: rata-rata 7 hari {_num(avg7)}/hari vs 30 hari {_num(avg30)}/hari")
                    todo = "Tambah stok/safety stock; pertahankan iklan yang berjalan"
                elif np.isfinite(store_ratio) and store_ratio > 1.15:
                    notes.append(f"Seluruh toko ramai: penjualan toko {_num(store_ratio * 100, 0)}% dari rata-rata 14 hari")
                    todo = "Pantau stok SKU laris"
                else:
                    notes.append(f"Lonjakan harian (rata-rata 7 hari {_num(avg7)}/hari)")
                    todo = "Pantau; pastikan stok cukup"
        else:
            notes.append("Sesuai prediksi")
            todo = "—"
        penyebab.append("; ".join(notes))
        aksi.append(todo or "—")
    out["penyebab"] = penyebab
    out["aksi"] = aksi
    since_map = dict(price_since)
    out["harga_sejak"] = out["sku"].astype(str).map(since_map)
    return out


def cause_group(text: str) -> str:
    """Kelompok penyebab untuk ringkasan."""
    text = str(text)
    for key in ("Stok", "Harga naik", "Diskon toko berakhir", "Batal", "Laku tidak setiap hari", "Tidak terjual", "Permintaan turun", "Seluruh toko sepi",
                "Fluktuasi", "Harga turun", "Diskon toko", "Ada pesanan borongan", "Permintaan naik", "Seluruh toko ramai", "Lonjakan", "Sesuai"):
        if text.startswith(key):
            return {"Diskon toko berakhir": "Harga naik", "Ada pesanan borongan": "Pesanan borongan"}.get(key, key)
    return "Lainnya"
