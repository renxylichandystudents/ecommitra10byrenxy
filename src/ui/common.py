"""Komponen bersama: format angka Indonesia, kartu, badge, filter periode, toggle exclude."""

from __future__ import annotations

import html
from datetime import date

import numpy as np
import pandas as pd
import streamlit as st

from src.utils.format import angka, desimal, persen, rupiah
from src.utils.format import excel_bytes as numeric_excel_bytes

ID_MONTHS = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember")
ID_MONTHS_SHORT = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
STATUS_CLASS = {"Aman": "st-ok", "Kurang": "st-short", "Kosong": "st-empty", "di bawah SS": "st-thin"}
STATUS_COLOR = {"Aman": "#15803d", "Kurang": "#b91c1c", "Kosong": "#b91c1c", "di bawah SS": "#a16207", "Tanpa data stok": "#64748b"}
UP_COLOR = "#1d4ed8"
DOWN_COLOR = "#dc2626"
EXTRA_BG = "#eff6ff"
STOCK_BG = "#fff7ed"
DEFAULT_NOTE = "memakai asumsi default"


def fmt_num(value: object, decimals: int = 0) -> str:
    return angka(value) if decimals == 0 else desimal(value, decimals)


def fmt_qty(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return angka(None)
    if not np.isfinite(number):
        return angka(None)
    return fmt_num(number, 0 if abs(number - round(number)) < 0.05 else 1)


def fmt_idr(value: object) -> str:
    return rupiah(value)


def fmt_idr_short(value: object) -> str:
    """Label grafik ringkas: Rp 81,5 jt / Rp 1,40 M. Kartu dan tabel memakai fmt_idr (angka lengkap)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return angka(None)
    if not np.isfinite(number):
        return angka(None)
    sign = "−" if number < 0 else ""
    number = abs(number)
    if number >= 1e9:
        return f"{sign}Rp {fmt_num(number / 1e9, 2)} M"
    if number >= 1e6:
        return f"{sign}Rp {fmt_num(number / 1e6, 1)} jt"
    if number >= 1e3:
        return f"{sign}Rp {fmt_num(number / 1e3, 1)} rb"
    return f"{sign}Rp {fmt_num(number, 0)}"


def fmt_pct(value: object, decimals: int = 1, signed: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return angka(None)
    if not np.isfinite(number):
        return angka(None)
    text = persen(abs(number) if signed else number, decimals)
    if signed:
        return ("+" if number > 0 else "−" if number < 0 else "") + text
    return text


def fmt_date(value: date | None, short: bool = False) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "-"
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        return "-"
    months = ID_MONTHS_SHORT if short else ID_MONTHS
    return f"{stamp.day} {months[stamp.month - 1]}" + ("" if short else f" {stamp.year}")


def signed_delta(now: float, then: float | None, *, money: bool) -> tuple[str, str]:
    if then is None or not np.isfinite(float(then)):
        return "", "flat"
    delta = float(now) - float(then)
    if abs(delta) < 0.5:
        return "– tetap", "flat"
    amount = fmt_idr(abs(delta)) if money else fmt_qty(abs(delta))
    pct = f" ({fmt_pct(delta / then * 100, 1, signed=True)})" if then else ""
    return (f"▲ +{amount}{pct}", "up") if delta > 0 else (f"▼ −{amount}{pct}", "down")


def status_key(status: object) -> str:
    key = str(status or "").split(" · ")[0]
    # Run lama masih menyimpan "Tipis" (stok < prediksi + SS), kini termasuk Kurang.
    return "Kurang" if key == "Tipis" else key


def badge(text: str, tone: str = "neutral") -> str:
    colors = {
        "neutral": ("#f1f5f9", "#334155"),
        "on": ("#dcfce7", "#166534"),
        "off": ("#f1f5f9", "#475569"),
        "info": ("#dbeafe", "#1e40af"),
        "warn": ("#fef9c3", "#854d0e"),
        "bad": ("#fee2e2", "#991b1b"),
    }
    bg, fg = colors.get(tone, colors["neutral"])
    return (
        f"<span style='display:inline-block;padding:2px 10px;border-radius:999px;background:{bg};color:{fg};"
        f"font-size:var(--fs-xs);font-weight:700;letter-spacing:.02em'>{html.escape(text)}</span>"
    )


def card(column, label: str, value: str, *, hint: str | None = None, tone: str | None = None) -> None:
    style = ""
    if tone == "extra":
        style = f"background:{EXTRA_BG};"
    elif tone == "stock":
        style = f"background:{STOCK_BG};"
    hint_html = f"<div class='metric-hint'>{hint}</div>" if hint else ""
    column.markdown(
        f"<div class='stat-card' style='{style}'><div class='readable-metric-label'>{html.escape(label)}</div>"
        f"<div class='readable-metric-value'>{value}</div>{hint_html}</div>",
        unsafe_allow_html=True,
    )


def metric_card(column, key: str, value: str, *, hint: str | None = None, tone: str | None = None, label: str | None = None) -> None:
    """Kartu KPI dengan nama metrik baku dan tooltip ⓘ dari METRIC_DEFINITIONS."""
    from src.core.metrics import METRIC_DEFINITIONS, METRIC_LABELS

    name = html.escape(label or METRIC_LABELS.get(key, key))
    definition = METRIC_DEFINITIONS.get(key, "")
    info = (
        f" <span title='{html.escape(definition, quote=True)}' style='cursor:help;color:#94a3b8;font-weight:600'>ⓘ</span>"
        if definition
        else ""
    )
    style = f"background:{EXTRA_BG};" if tone == "extra" else (f"background:{STOCK_BG};" if tone == "stock" else "")
    hint_html = f"<div class='metric-hint'>{hint}</div>" if hint else ""
    column.markdown(
        f"<div class='stat-card' style='{style}'><div class='readable-metric-label'>{name}{info}</div>"
        f"<div class='readable-metric-value'>{value}</div>{hint_html}</div>",
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False, max_entries=64)
def cached_order_metrics(frame: pd.DataFrame, start=None, end=None, exclude_flag: bool = False) -> dict:
    """order_metrics dengan cache (hash data, start, end, exclude_flag)."""
    from src.core.metrics import order_metrics

    del exclude_flag
    return order_metrics(frame, start, end)


@st.cache_data(show_spinner=False, max_entries=64)
def cached_sku_coverage(frame: pd.DataFrame, start=None, end=None) -> dict:
    from src.core.metrics import sku_coverage

    return sku_coverage(frame, start, end)


def section(title: str, kicker: str | None = None) -> None:
    kicker_html = f"<div style='font-size:var(--fs-xs);font-weight:700;color:#64748b;letter-spacing:.08em;text-transform:uppercase'>{html.escape(kicker)}</div>" if kicker else ""
    st.markdown(f"{kicker_html}<div class='section-title'>{html.escape(title)}</div>", unsafe_allow_html=True)


def excel_bytes(frames: dict[str, pd.DataFrame] | pd.DataFrame) -> bytes:
    return numeric_excel_bytes(frames)


def download_excel(frames: dict[str, pd.DataFrame] | pd.DataFrame, filename: str, *, key: str | None = None, label: str = "Unduh Excel") -> None:
    name = filename if filename.endswith(".xlsx") else f"{filename}.xlsx"
    st.download_button(
        label,
        data=excel_bytes(frames),
        file_name=name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key or f"xl-{name}",
    )


def month_label(key: str) -> str:
    year, month = key.split("-", 1)
    return f"{ID_MONTHS[int(month) - 1]} {year}"


def period_filter(orders: pd.DataFrame, *, prefix: str, compact: bool = False) -> tuple[pd.DataFrame, str, list[str]]:
    """Filter periode penjualan bersama: checkbox tahun, grid bulan 4 kolom, tanggal mulai/selesai terkunci.

    Hanya memotong angka aktual; prediksi tetap dari input awal.
    """
    if orders is None or orders.empty or "order_time" not in orders.columns:
        return orders, "", []
    times = pd.to_datetime(orders["order_time"], errors="coerce")
    work = orders.loc[times.notna()].copy()
    work["_month"] = times.loc[times.notna()].dt.to_period("M").astype(str)
    months = sorted(work["_month"].unique())
    years = sorted({key[:4] for key in months})
    if not months:
        return work.iloc[0:0], "", []
    year_cols = st.columns(max(len(years), 1) + (0 if compact else 2))
    checked_years = []
    for index, year in enumerate(years):
        widget = f"{prefix}-y-{year}"
        if widget not in st.session_state:
            st.session_state[widget] = year == years[-1]
        if year_cols[index].checkbox(year, key=widget):
            checked_years.append(year)
    year_months = [key for key in months if key[:4] in checked_years]
    selected: list[str] = []
    grid = st.columns(4 if not compact else 6)
    for index, key in enumerate(year_months):
        widget = f"{prefix}-m-{key}"
        if widget not in st.session_state:
            st.session_state[widget] = key == year_months[-1]
        if grid[index % len(grid)].checkbox(month_label(key), key=widget):
            selected.append(key)
    if not selected:
        st.warning("Centang minimal satu tahun dan satu bulan penjualan.")
        return work.iloc[0:0].drop(columns="_month"), "tidak ada bulan dipilih", []
    span = work.loc[work["_month"].isin(selected), "order_time"]
    lo = pd.Timestamp(span.min()).date()
    hi = pd.Timestamp(span.max()).date()
    start_key, end_key = f"{prefix}-start", f"{prefix}-end"
    stamp_key = f"{prefix}-span"
    if st.session_state.get(stamp_key) != (lo, hi):
        st.session_state[start_key] = lo
        st.session_state[end_key] = hi
        st.session_state[stamp_key] = (lo, hi)
    c1, c2 = st.columns(2)
    start = c1.date_input("Tanggal mulai", min_value=lo, max_value=hi, key=start_key, format="DD/MM/YYYY")
    end = c2.date_input("Tanggal selesai", min_value=lo, max_value=hi, key=end_key, format="DD/MM/YYYY")
    if start > end:
        start, end = end, start
    days = pd.to_datetime(work["order_time"]).dt.normalize()
    mask = work["_month"].isin(selected) & days.between(pd.Timestamp(start), pd.Timestamp(end))
    filtered = work.loc[mask].drop(columns="_month").reset_index(drop=True)
    names = [month_label(key) for key in selected]
    if start == lo and end == hi:
        label = names[0] if len(names) == 1 else ", ".join(names)
    else:
        label = fmt_date(start) if start == end else f"{fmt_date(start)} – {fmt_date(end)}"
    return filtered, label, selected


def apply_saved_period(orders: pd.DataFrame, *, prefix: str) -> tuple[pd.DataFrame, str]:
    """Pakai pilihan `period_filter` terakhir tanpa menampilkan widget (default: bulan terakhir)."""
    if orders is None or orders.empty or "order_time" not in orders.columns:
        return orders, ""
    times = pd.to_datetime(orders["order_time"], errors="coerce")
    work = orders.loc[times.notna()].copy()
    work["_month"] = times.loc[times.notna()].dt.to_period("M").astype(str)
    months = sorted(work["_month"].unique())
    if not months:
        return work.iloc[0:0].drop(columns="_month"), ""
    selected = [key for key in months if st.session_state.get(f"{prefix}-m-{key}") and st.session_state.get(f"{prefix}-y-{key[:4]}")]
    if not selected:
        selected = [months[-1]]
    part = work.loc[work["_month"].isin(selected)]
    lo = pd.Timestamp(part["order_time"].min()).date()
    hi = pd.Timestamp(part["order_time"].max()).date()
    start = st.session_state.get(f"{prefix}-start", lo)
    end = st.session_state.get(f"{prefix}-end", hi)
    start = min(max(start, lo), hi)
    end = min(max(end, lo), hi)
    days = pd.to_datetime(part["order_time"]).dt.normalize()
    filtered = part.loc[days.between(pd.Timestamp(start), pd.Timestamp(end))].drop(columns="_month").reset_index(drop=True)
    names = [month_label(key) for key in selected]
    label = (", ".join(names)) if (start == lo and end == hi) else (fmt_date(start) if start == end else f"{fmt_date(start)} – {fmt_date(end)}")
    return filtered, label


def exclude_toggle_card(*, key: str, removed_orders: int, removed_units: float) -> bool:
    """Kartu toggle "Kecualikan batal & retur" dengan badge status dan jumlah yang dikeluarkan."""
    with st.container(border=True):
        left, right = st.columns([3, 2], vertical_alignment="center")
        with left:
            value = st.toggle("Kecualikan batal & retur", key=key)
            st.caption("Mengurangi pesanan batal & unit retur")
        with right:
            if value:
                st.markdown(badge("AKTIF · nilai bersih", "on"), unsafe_allow_html=True)
                st.caption(f"Seluruh data latih: {fmt_num(removed_orders)} pesanan batal dan {fmt_qty(removed_units)} unit retur dikeluarkan dari prediksi")
            else:
                st.markdown(badge("NONAKTIF · termasuk batal & retur", "off"), unsafe_allow_html=True)
                st.caption(f"Seluruh data latih: {fmt_num(removed_orders)} pesanan batal dan {fmt_qty(removed_units)} unit retur ikut dihitung di prediksi")
    return bool(value)


def default_note(used_default: bool) -> str:
    return f"<span style='font-size:var(--fs-xs);color:#94a3b8'>· {DEFAULT_NOTE}</span>" if used_default else ""


def lttb(x: np.ndarray, y: np.ndarray, threshold: int = 400) -> tuple[np.ndarray, np.ndarray]:
    """Largest-Triangle-Three-Buckets downsampling untuk grafik dengan banyak titik."""
    n = len(x)
    if threshold >= n or threshold < 3:
        return x, y
    xs = np.arange(n, dtype=float)
    ys = np.asarray(y, dtype=float)
    keep = [0]
    bucket = (n - 2) / (threshold - 2)
    a = 0
    for i in range(threshold - 2):
        start = int(np.floor((i + 1) * bucket)) + 1
        end = min(int(np.floor((i + 2) * bucket)) + 1, n)
        avg_x = xs[start:end].mean() if end > start else xs[min(start, n - 1)]
        avg_y = ys[start:end].mean() if end > start else ys[min(start, n - 1)]
        lo = int(np.floor(i * bucket)) + 1
        hi = int(np.floor((i + 1) * bucket)) + 1
        area = np.abs((xs[a] - avg_x) * (ys[lo:hi] - ys[a]) - (xs[a] - xs[lo:hi]) * (avg_y - ys[a]))
        a = lo + int(np.argmax(area)) if len(area) else lo
        keep.append(a)
    keep.append(n - 1)
    idx = np.array(keep)
    return np.asarray(x)[idx], ys[idx]


def button_tabs(options: list[tuple[str, str]], current: str, *, key: str) -> str | None:
    """Baris tombol sub-menu (gaya sama dengan menu utama); di HP berupa selectbox. Mengembalikan slug yang diklik, atau None."""
    clicked = None
    slugs = [slug for slug, _ in options]
    names = dict(options)
    with st.container(key=f"mobile-{key}"):
        pick = st.selectbox("Bagian", slugs, index=slugs.index(current) if current in slugs else 0, format_func=lambda s: names.get(s, s), key=f"m-{key}-{current}", label_visibility="collapsed")
        if pick != current and current in slugs:
            clicked = pick
    with st.container(key=f"desktop-{key}"):
        cols = st.columns(len(options))
        for column, (slug, label) in zip(cols, options):
            if column.button(label, key=f"{key}-{slug}", type="primary" if slug == current else "secondary", use_container_width=True):
                clicked = slug
    return clicked


def sku_cards(rows: list[dict], *, key: str) -> None:
    """Kartu per SKU untuk layar HP. Tiap baris: sku, produk, varian, status (opsional), nums [(label, teks)]."""
    parts = []
    for row in rows:
        title = html.escape(str(row.get("produk") or "-"))
        meta = " · ".join(html.escape(str(v)) for v in (row.get("sku"), row.get("varian")) if v and str(v).lower() != "nan")
        status = str(row.get("status") or "")
        tone = {"Aman": "on", "Kurang": "bad", "Kosong": "bad"}.get(status_key(status), "neutral")
        tag = f" {badge(status_key(status), tone)}" if status else ""
        nums = "".join(f"<div>{html.escape(str(label))}: <b>{html.escape(str(value))}</b></div>" for label, value in row.get("nums", []))
        parts.append(f"<div class='sku-card'><div class='sku-title'>{title}</div><div class='sku-meta'>{meta}{tag}</div><div class='sku-nums'>{nums}</div></div>")
    with st.container(key=f"mobile-cards-{key}"):
        st.markdown("".join(parts) or "<div class='field-hint'>Belum ada SKU.</div>", unsafe_allow_html=True)
