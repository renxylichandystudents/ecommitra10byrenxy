"""Ringkasan › Prioritas hari ini (Revisi Final 4A), di atas konten Ringkasan lama."""

from __future__ import annotations

import html
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src.core.access import ROLE_LABELS, setting_tabs
from src.core.decision_table import stock_shortage
from src.core.fmt import fmt_date, fmt_rp
from src.core.periods import prediction_window, short_date
from src.core.promo import promo_eligible
from src.core.restock import restock_priority
from src.ui.common import badge, batched_view, card, download_excel, explain, fmt_num, sku_cards, status_key
from src.ui.feature_data import FeatureData
from src.utils.format import show_table

STEP = 10
RESTOCK_STEP = 5


def status_badges(frame: pd.DataFrame, column: str = "Status") -> pd.DataFrame:
    """Status sebagai label berikon agar terbaca seperti badge di st.dataframe."""
    icons = {"Kosong": "🔴", "Kurang": "🟡", "Aman": "🟢", "Tanpa data stok": "⚪"}
    out = frame.copy()
    if column in out.columns:
        def _badge(value) -> str:
            text = str(value)
            key = status_key(text)
            if key not in icons:
                return text
            rest = text.split(" · ", 1)[1] if " · " in text else ""
            return f"{icons[key]} {key}" + (f" · {rest}" if rest else "")

        out[column] = out[column].map(_badge)
    return out


def capacity_summary(features, table: pd.DataFrame) -> tuple[str, str]:
    """(nilai kartu, keterangan) Kapasitas gudang Site 10037: lokasi terpakai dari denah + replenishment harian."""
    if features is None:
        return "–", "Data replenishment belum diunggah"
    try:
        from src.core import gudang
        from src.ui.gudang_view import cached_view

        view = cached_view(features, table)
    except Exception:
        return "–", "Data replenishment belum diunggah"
    if not view or not view.get("has_repl"):
        return "–", "Unggah replenishment Site 10037 (Setting › Kapasitas gudang)"
    return gudang.capacity_card(view)


def last_actual(orders: pd.DataFrame | None, keys: list[str], today: date) -> tuple[float, date | None]:
    """QTY Top 50 pada hari penuh terakhir sebelum `today`; hari ini dan hari data yang belum sampai 23:00 tidak dipakai."""
    if orders is None or orders.empty:
        return 0.0, None
    from src.ui.month_track_view import full_day_cutoff

    stamps = pd.to_datetime(orders["order_time"], errors="coerce")
    days = stamps.dt.date
    limit = min(full_day_cutoff(stamps.max()), today - timedelta(days=1)) if stamps.notna().any() else today - timedelta(days=1)
    full = days[days <= limit]
    if full.empty:
        return 0.0, None
    last = full.max()
    part = orders.loc[(days == last) & orders["item_key"].astype(str).isin(set(keys))]
    return float(part["qty"].sum()), last


def actual_hint(predicted: float, actual: float, day: date | None, today: date) -> str:
    if day is None:
        return "Belum ada transaksi hari penuh"
    when = "kemarin" if day == today - timedelta(days=1) else "hari penuh terakhir"
    text = f"Aktual {when} ({short_date(day)}): {fmt_num(actual)}"
    if actual > 0:
        gap = (predicted - actual) / actual * 100
        text += f" · selisih {'+' if gap >= 0 else '−'}{fmt_num(abs(gap), 1)}%"
    return text


MONTHS_SHORT = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")


def running_month_parts(table: pd.DataFrame, orders: pd.DataFrame | None, orders_all: pd.DataFrame | None, today: date,
                        *, all_items: bool = False) -> dict:
    """Bulan berjalan: aktual tgl 1 s.d. hari penuh terakhir + laju prediksi harian × jumlah pola hari sisa bulan.

    Sales = sales produk (dasar prediksi). all_items=True: aktual seluruh pesanan, bukan hanya SKU di `table`."""
    import calendar

    from src.ui.month_track_view import month_remaining_weight

    month_first = today.replace(day=1)
    month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    cutoff, weight = month_remaining_weight(orders_all if orders_all is not None else orders, today)
    actual_qty = actual_sales = 0.0
    if orders is not None and not orders.empty and cutoff >= month_first:
        days = pd.to_datetime(orders["order_time"], errors="coerce").dt.date
        mask = (days >= month_first) & (days <= cutoff)
        if not all_items:
            mask &= orders["item_key"].astype(str).isin(set(table["item_key"].astype(str)))
        actual_qty = float(orders.loc[mask, "qty"].sum())
        actual_sales = float(orders.loc[mask, "sales"].sum()) if "sales" in orders.columns else 0.0
    rate_qty = float(table["pred_harian"].sum()) if "pred_harian" in table.columns else 0.0
    rate_sales = float((table["pred_harian"] * table["harga_bersih"]).sum()) if {"pred_harian", "harga_bersih"} <= set(table.columns) else 0.0
    return {
        "month_first": month_first, "month_end": month_end, "cutoff": cutoff, "weight": weight,
        "rest_start": max(month_first, cutoff + timedelta(days=1)),
        "actual_qty": actual_qty, "actual_sales": actual_sales,
        "rest_qty": rate_qty * weight, "rest_sales": rate_sales * weight,
    }


def running_month_hint(parts: dict, actual: float, rest: float, fmt) -> str:
    month = MONTHS_SHORT[parts["month_first"].month - 1]

    def span(lo: date, hi: date) -> str:
        return f"{lo.day} {month}" if lo == hi else f"{lo.day}–{hi.day} {month}"

    out = []
    if parts["cutoff"] >= parts["month_first"]:
        out.append(f"aktual {span(parts['month_first'], parts['cutoff'])}: {fmt(actual)}")
    if parts["rest_start"] <= parts["month_end"]:
        out.append(f"prediksi {span(parts['rest_start'], parts['month_end'])}: {fmt(rest)}")
    return " + ".join(out)


def running_month(table: pd.DataFrame, orders: pd.DataFrame | None, orders_all: pd.DataFrame | None, today: date) -> tuple[float, str]:
    """(prediksi QTY bulan berjalan Top 50, keterangan)."""
    parts = running_month_parts(table, orders, orders_all, today)
    return parts["actual_qty"] + parts["rest_qty"], running_month_hint(parts, parts["actual_qty"], parts["rest_qty"], fmt_num)


def show_priority_dashboard(
    table: pd.DataFrame,
    *,
    today: date,
    orders: pd.DataFrame | None,
    orders_all: pd.DataFrame | None = None,
    features,
    data: FeatureData,
    role: str,
    window_label: str,
    window_start: date,
    fresh_period: bool,
    metric: str = "qty",
) -> None:
    st.markdown("<div class='section-title'>Prioritas hari ini</div>", unsafe_allow_html=True)
    if table is None or table.empty:
        st.write("Belum ada SKU untuk ditampilkan.")
        return
    top = table.head(50)
    keys = top["item_key"].astype(str).tolist()
    actual_qty, actual_day = last_actual(orders, keys, today)
    predicted_today = float(top["d_qty_exp"].sum()) if "d_qty_exp" in top.columns else float(top["d_qty"].sum())
    shortage = stock_shortage(top)
    cols = st.columns(5)
    card(
        cols[0],
        "Prediksi QTY hari ini · Top 50",
        fmt_num(predicted_today),
        hint=actual_hint(predicted_today, actual_qty, actual_day, today),
    )
    month_qty, month_hint = running_month(top, orders, orders_all, today)
    month_name = MONTHS_SHORT[today.month - 1]
    card(cols[1], f"Prediksi QTY bulan berjalan ({month_name} {today.year}) · Top 50", fmt_num(month_qty), hint=month_hint)
    fresh = " " + badge("periode baru", "info") if fresh_period else ""
    lo, hi = prediction_window("bulan", window_start)
    card(
        cols[2],
        f"Kebutuhan stok {window_label} · Top 50",
        fmt_num(top["m_butuh"].sum()) + fresh,
        hint=f"Prediksi (unit utuh) + safety stock · {short_date(lo)} – {short_date(hi)}",
    )
    gaps = [f"{fmt_num(shortage['kosong'])} kosong (stok 0)", f"{fmt_num(shortage['di_bawah_ss'])} di bawah SS"]
    if shortage["tanpa_data"]:
        gaps.append(f"{fmt_num(shortage['tanpa_data'])} tanpa data stok")
    card(cols[3], "SKU Top 50 stok kurang", fmt_num(shortage["kurang"]), hint="Stok di bawah prediksi + SS · " + " · ".join(gaps))
    cap_value, cap_note = capacity_summary(features, table)
    card(cols[4], "Kapasitas gudang 10037", cap_value if cap_value not in ("–", "-", "") else "Belum ada data", hint=cap_note)

    priority = restock_priority(top, today, po=data.po)
    basis = "Sales value" if metric == "sales" else "QTY terjual"
    # Insight di atas, tabel restock selebar penuh agar kolom Produk/Varian tidak terpotong.
    _insight_cards(table, priority, data, role)
    with st.container():
        st.markdown(f"**Kebutuhan restock prioritas · Top 50 {basis}**")
        explain(
            [
                ("SKU", f"Top 50 menurut {basis} (kolom Rank)"),
                ("Restock", "prediksi + SS − stok Site 10037 (minimal 0)"),
                ("Ambil dari DC", "dipenuhi dulu dari Site 10062 (DC Cikupa), lalu Site 10036 (DC Cipeucang); sisanya PO ke supplier"),
                ("Stok habis", "hari ini + stok ÷ prediksi harian; SKU Kosong: tanggal stok mulai 0 menurut riwayat unggahan Data stok Site 10037"),
                ("Kosong · N hari", "lama stok 0 sejak unggahan pertama yang mencatat stok 0; \"≥\" bila semua unggahan tersimpan sudah 0 (umur sebenarnya bisa lebih lama)"),
                ("Potensi hilang", "prediksi periode − stok Site 10037; dalam unit (QTY) dan rupiah (sales value)"),
                ("Urutan", "🔴 Kosong & ada stok di Site 10062/10036 → 🔴 Kosong tanpa stok DC → 🟡 Kurang & ada stok DC → 🟡 Kurang tanpa stok DC → 🟢 Aman"),
                ("Dalam tiap kelompok", "dampak omzet terbesar lebih dulu (gabungan potensi loss sales value dan QTY), lalu stok habis paling cepat"),
            ]
        )
        if priority.empty:
            st.info("Data stok Top 50 belum diunggah, jadi kebutuhan restock belum bisa dihitung.")
        else:
            view = restock_view(priority)
            # Kolom yang kosong untuk semua SKU disembunyikan (dinilai dari seluruh daftar, bukan per kelompok).
            hide = [c for c in ("Stok Site 10062", "Stok Site 10036") if view[c].isna().all()]
            if not view["Inbound"].astype(str).str.strip().any():
                hide.append("Inbound")
            if not view["Ambil dari DC"].astype(str).str.strip().any():
                hide.append("Ambil dari DC")

            def _render(lo: int, hi: int) -> None:
                part = view.iloc[lo:hi]
                display = status_badges(part).drop(columns=hide)
                with st.container(key=f"desktop-dash-restock-{lo}"):
                    show_table(display, kinds={"Rank": "count", "Stok Site 10037": "count", "Stok Site 10062": "count", "Stok Site 10036": "count", "Prediksi": "count", "SS": "count", "Restock": "count", "Potensi QTY hilang": "count", "Potensi sales hilang": "money"}, column_config={"Status": st.column_config.TextColumn(width="small"), "Ambil dari DC": st.column_config.TextColumn(width="large")})
                sku_cards(
                    [
                        {
                            "sku": r.get("SKU"),
                            "produk": r.get("Produk"),
                            "varian": r.get("Varian"),
                            "status": r.get("Status"),
                            "nums": [("Rank", fmt_num(r.get("Rank"))), ("Stok Site 10037", fmt_num(r.get("Stok Site 10037"))), ("Prediksi", fmt_num(r.get("Prediksi"))), ("SS", fmt_num(r.get("SS"))), ("Restock", fmt_num(r.get("Restock"))), ("Potensi sales hilang", fmt_rp(r.get("Potensi sales hilang"))), ("Stok habis", r.get("Stok habis", "–"))] + ([("Ambil dari DC", r.get("Ambil dari DC"))] if r.get("Ambil dari DC") else []),
                        }
                        for r in part.to_dict("records")
                    ],
                    key=f"dash-restock-{lo}",
                )

            batched_view(
                len(view),
                key="dash-restock",
                render=_render,
                noun="SKU",
                download=lambda: download_excel(view, "restock_prioritas.xlsx", key="xl-dash-restock"),
            )


def empty_age(days, since, from_first: bool) -> str:
    """'12 hari (sejak 1 Nov)'; bila semua unggahan stok tersimpan sudah 0, umur minimal: '≥ 12 hari'."""
    if days is None or pd.isna(days):
        return ""
    days = int(days)
    if days <= 0 and not from_first:
        return "mulai hari ini"
    prefix = "≥ " if from_first else ""
    return f"{prefix}{days} hari" + (f" (sejak {short_date(since)})" if since and not from_first else "")


def restock_view(priority: pd.DataFrame) -> pd.DataFrame:
    out = priority.rename(columns={"sku": "SKU"}).copy()
    since = out["_kosong_sejak"] if "_kosong_sejak" in out.columns else pd.Series(None, index=out.index)
    age = out["_lama_kosong"] if "_lama_kosong" in out.columns else pd.Series(None, index=out.index)
    first = out["_kosong_sejak_awal"] if "_kosong_sejak_awal" in out.columns else pd.Series(False, index=out.index)
    out["Status"] = [
        f"{status} · {text}" if status == "Kosong" and (text := empty_age(a, s, bool(f))) else status
        for status, a, s, f in zip(out["Status"], age, since, first)
    ]

    def habis_text(day, rate, status, start, from_first) -> str:
        if status_key(status) == "Kosong":
            if start:
                return f"Habis {'≤ ' if from_first else ''}{short_date(start)}"
            return "Sudah kosong"
        if day:
            return short_date(day)
        return "Tidak habis · prediksi 0" if rate <= 0 else "Tidak habis > 10 tahun"

    out["Stok habis"] = [
        habis_text(day, rate, status, start, bool(f))
        for day, rate, status, start, f in zip(out["Stok habis"], out["_pred_harian"], out["Status"], since, first)
    ]
    return out[["Rank", "SKU", "Produk", "Varian", "Status", "Stok Site 10037", "Stok Site 10062", "Stok Site 10036", "Potensi sales hilang", "Potensi QTY hilang", "Prediksi", "SS", "Restock", "Ambil dari DC", "Stok habis", "Inbound"]]


def _insight_cards(table: pd.DataFrame, priority: pd.DataFrame, data: FeatureData, role: str) -> None:
    lines = []
    if not priority.empty:
        empty = int((priority["Status"] == "Kosong").sum())
        total = float(priority["Restock"].sum())
        lines.append(f"<b>{fmt_num(empty)}</b> SKU Top 50 kosong · total restock Top 50 <b>{fmt_num(total)}</b> unit.")
        source = priority.loc[priority["Restock"] > 0, "Ambil dari DC"].astype(str)
        if source.str.strip().any():
            covered = int((source.str.startswith("Ambil") & ~source.str.contains("PO")).sum())
            partly = int((source.str.startswith("Ambil") & source.str.contains("PO")).sum())
            po_only = int(source.str.startswith("Stok Site").sum())
            lines.append(
                f"Dari {fmt_num(len(source))} SKU yang perlu restock: <b>{fmt_num(covered)}</b> cukup diambil dari Site 10062/10036, "
                f"{fmt_num(partly)} sebagian dari DC + PO, {fmt_num(po_only)} harus PO karena kedua DC kosong."
            )
        first = priority.iloc[0]
        po = data.po.get(str(first["sku"]))
        if po:
            eta = fmt_date(po["eta"]) if po.get("eta") else "ETA belum ada"
            lines.append(f"SKU teratas {html.escape(str(first['sku']))} punya PO impor {html.escape(po['no_po'])} ({fmt_num(po['qty'])} unit, {eta}).")
        elif data.po:
            lines.append(f"{fmt_num(len(data.po))} SKU punya PO impor terbuka (lihat kolom Inbound).")
    held = 0
    if "biaya_iklan" in table.columns:
        spending = table.loc[table["biaya_iklan"].fillna(0) > 0]
        for _, row in spending.iterrows():
            ok, _reasons, _decision = promo_eligible(row, excluded=data.excluded, margin_pct=data.margin_pct.get(str(row["sku"])), cancel_pct=row.get("batal_pct"))
            held += 0 if ok else 1
    if held:
        lines.append(f"<b>{fmt_num(held)}</b> SKU yang sedang beriklan sebaiknya ditahan (stok kurang, margin, atau batal tinggi).")
    body = "".join(f"<div style='margin:.25rem 0;font-size:var(--fs-sm)'>{line}</div>" for line in lines) or "<div class='field-hint'>Belum ada insight.</div>"
    st.markdown(f"<div class='stat-card'><div class='readable-metric-label'>Insight</div>{body}</div>", unsafe_allow_html=True)
    if role in ("team_dc", "team_icmd"):
        tabs = [label for _slug, label, _menu in setting_tabs(role)]
        st.markdown(
            "<div class='stat-card' style='margin-top:.6rem'><div class='readable-metric-label'>Akses role Anda</div>"
            f"<div style='font-size:var(--fs-sm)'>{html.escape(ROLE_LABELS.get(role, role))}: Ringkasan & Prediksi (lihat), "
            f"Setting › {html.escape(', '.join(tabs))}.</div></div>",
            unsafe_allow_html=True,
        )

