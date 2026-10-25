from __future__ import annotations

import html
import sys
from datetime import date
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.activity import (
    ACTIVITY_GRAINS,
    activity_period_label,
    activity_report,
    append_total_row,
    cancel_contribution,
    focus_summary,
    ledger_from_raw,
    period_options,
    scope_ledger,
    slice_period,
    unpaid_buyer_table,
)
from src.aggregate import (
    HORIZON_DAYS,
    PERIOD_OPTIONS,
    PERIOD_SPECS,
    aggregate_item_periods,
    next_period_start,
    period_label,
    period_start,
)
from src.forecast import (
    _weekday_profile,
    compare_daily_algorithms,
    forecast_calendar,
    forecast_items,
    forecast_revenue,
)
from src.library import (
    bundle_stamp,
    folder_frame,
    history_frame,
    list_months,
    load_months,
    month_label,
    store_upload,
    year_of,
)
from src.ingest import (
    _is_cancelled_status,
    clean_order_frame,
    clean_sku_columns,
    load_shopee_report,
    order_month_keys,
    order_revenue,
)
from src.ranking import combine_forecasts, model_leaderboard, rank_from_orders
from src.stock import recommend_stock

st.set_page_config(
    page_title="Prediksi Stok Shopee",
    page_icon="📦",
    layout="wide",
)
st.markdown(
    """
    <style>
    [data-testid="stMetricValue"],
    [data-testid="stMetricValue"] > div {
        font-size: 1.35rem !important;
        line-height: 1.25 !important;
        white-space: normal !important;
        overflow: visible !important;
        text-overflow: unset !important;
        word-break: break-word !important;
    }
    [data-testid="stMetricLabel"],
    [data-testid="stMetricLabel"] > div {
        white-space: normal !important;
        overflow: visible !important;
    }
    .readable-metric-label {
        font-size: 0.85rem;
        line-height: 1.3;
        margin-bottom: 0.15rem;
        opacity: 0.7;
    }
    .readable-metric-value {
        font-size: 1.28rem;
        font-weight: 600;
        line-height: 1.3;
        white-space: normal;
        word-break: break-word;
    }
    .readable-metric-value.compact {
        font-size: 1.05rem;
        line-height: 1.35;
    }
    .metric-hint {
        font-size: 0.75rem;
        line-height: 1.3;
        color: #64748b;
        margin-top: 0.12rem;
    }
    .period-name {
        font-size: 1.28rem;
        font-weight: 600;
        line-height: 1.25;
    }
    .period-dates {
        font-size: 0.95rem;
        line-height: 1.35;
        color: #334155;
        margin-top: 0.12rem;
    }
    .report-kicker {
        font-size: 0.82rem;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: #64748b;
        margin: 0;
    }
    .report-title {
        font-size: 1.7rem;
        font-weight: 700;
        line-height: 1.25;
        color: #0f172a;
        margin: 0.15rem 0 0.45rem 0;
    }
    .report-body {
        font-size: 1.05rem;
        line-height: 1.55;
        color: #1e293b;
    }
    .app-menu-label {
        font-size: 0.95rem;
        font-weight: 700;
        color: #0f172a;
        margin: 0.15rem 0 0.15rem 0;
    }
    .app-menu-hint {
        font-size: 0.82rem;
        line-height: 1.35;
        color: #64748b;
        margin: 0 0 0.45rem 0;
    }
    div[data-testid="stElementContainer"]:has(.app-menu-label) + div[data-testid="stElementContainer"] [data-testid="stHorizontalBlock"] {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 0.4rem;
        gap: 0.4rem;
    }
    div[data-testid="stElementContainer"]:has(.app-menu-label) + div[data-testid="stElementContainer"] button {
        border-radius: 10px;
        font-weight: 600;
        min-height: 2.6rem;
        white-space: normal;
    }
    .side-section {
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: #64748b;
        margin: 0.9rem 0 0.35rem 0;
    }
    section[data-testid="stSidebar"] [data-testid="stButton"] button {
        border-radius: 10px;
        font-weight: 650;
        min-height: 2.7rem;
    }
    section[data-testid="stSidebar"] [data-testid="stCheckbox"] {
        margin-bottom: -0.15rem;
    }
    section[data-testid="stSidebar"] [data-testid="stCheckbox"] label p {
        font-size: 0.92rem;
    }
    .side-note {
        font-size: 0.82rem;
        line-height: 1.35;
        color: #475569;
        margin: 0.1rem 0 0.55rem 0;
    }
    .side-warn {
        font-size: 0.82rem;
        line-height: 1.35;
        color: #9a3412;
        background: #fff7ed;
        border-radius: 8px;
        padding: 0.45rem 0.6rem;
        margin: 0.1rem 0 0.7rem 0;
    }
    .side-low {
        font-size: 0.82rem;
        line-height: 1.35;
        color: #1e3a8a;
        background: #eff6ff;
        border-radius: 8px;
        padding: 0.45rem 0.6rem;
        margin: 0.1rem 0 0.7rem 0;
    }
    .side-best {
        font-size: 0.82rem;
        line-height: 1.35;
        color: #14532d;
        background: #f0fdf4;
        border-radius: 8px;
        padding: 0.45rem 0.6rem;
        margin: 0.1rem 0 0.7rem 0;
    }
    [data-testid="stFileUploaderDropzoneInstructions"] div span:last-child {
        display: none !important;
    }
    [data-testid="stFileUploaderDropzoneInstructions"] div span:first-child {
        white-space: normal !important;
        overflow: visible !important;
        text-overflow: unset !important;
        font-size: 0.95rem !important;
    }
    .upload-note {
        font-size: 0.86rem;
        line-height: 1.4;
        white-space: normal;
        overflow: visible;
        margin: 0.15rem 0 0.8rem 0;
    }
    .chart-heading {
        font-size: 1.08rem;
        font-weight: 700;
        line-height: 1.45;
        color: #1f2937;
        margin: 1.35rem 0 0.9rem 0;
    }
    [data-testid="stElementContainer"]:has(.sheet-scroll),
    [data-testid="stMarkdown"]:has(.sheet-scroll),
    [data-testid="stMarkdownContainer"]:has(.sheet-scroll) {
        display: block;
        width: 100% !important;
        max-width: 100% !important;
        min-width: 0 !important;
    }
    .sheet-scroll {
        display: block;
        width: 100%;
        max-width: 100%;
        box-sizing: border-box;
        overflow: auto;
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        background: #ffffff;
        scrollbar-width: auto;
        scrollbar-color: #334155 #e2e8f0;
    }
    .sheet-scroll table {
        border-collapse: separate;
        border-spacing: 0;
        width: max-content;
        min-width: max(100%, 1100px);
        font-size: 0.92rem;
        color: #1f2937;
    }
    .sheet-scroll th,
    .sheet-scroll td {
        padding: 0.55rem 0.9rem;
        border-bottom: 1px solid #e2e8f0;
        white-space: nowrap;
        text-align: left;
        background: #ffffff;
    }
    .sheet-scroll th {
        position: sticky;
        top: 0;
        z-index: 1;
        background: #f1f5f9;
        font-weight: 650;
    }
    .sheet-scroll td.num,
    .sheet-scroll th.num {
        text-align: right;
    }
    .sheet-scroll::-webkit-scrollbar {
        width: 16px;
        height: 16px;
    }
    .sheet-scroll::-webkit-scrollbar-thumb {
        background: #334155;
        border-radius: 8px;
    }
    .sheet-scroll::-webkit-scrollbar-track {
        background: #e2e8f0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

TOP_N = 50
METRIC_LABELS = {
    "qty": "QTY terjual",
    "sales": "Sales volume",
}
ID_MONTHS = (
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)


def format_id_date(value: date) -> str:
    return f"{value.day} {ID_MONTHS[value.month - 1]} {value.year}"


def forecast_window(period: str, today: date | None = None) -> tuple[date, date, str]:
    """Periode prediksi dimulai hari ini dan mengikuti tanggal kalender."""
    start = today or date.today()
    months = {"bulan": 1, "kuartal": 3, "semester": 6, "tahun": 12}[period]
    end = (pd.Timestamp(start) + pd.DateOffset(months=months) - pd.Timedelta(days=1)).date()
    text = f"{PERIOD_SPECS[period].label} · {format_id_date(start)} – {format_id_date(end)}"
    return start, end, text


def horizon_day_count(period: str, today: date | None = None) -> int:
    start, end, _text = forecast_window(period, today)
    return (end - start).days + 1


def format_number(value: float, decimals: int = 0) -> str:
    if value is None or pd.isna(value):
        return "-"
    number = float(value)
    if pd.isna(number):
        return "-"
    text = f"{number:,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def format_idr(value: float) -> str:
    return f"Rp {format_number(value, 0)}"


def format_qty(value: float) -> str:
    if value is None or pd.isna(value):
        return "-"
    number = float(value)
    if pd.isna(number):
        return "-"
    decimals = 0 if abs(number - round(number)) < 0.05 else 1
    return format_number(number, decimals)


def format_columns(frame: pd.DataFrame, kinds: dict[str, str]) -> pd.DataFrame:
    formatted = frame.copy()
    for column, kind in kinds.items():
        if kind == "money":
            formatted[column] = formatted[column].map(format_idr)
        elif kind == "qty":
            formatted[column] = formatted[column].map(format_qty)
        elif kind == "int":
            formatted[column] = formatted[column].map(lambda value: format_number(value, 0))
        elif kind == "decimal":
            formatted[column] = formatted[column].map(lambda value: format_number(value, 2))
    return formatted


def polish_chart(
    fig: go.Figure,
    *,
    height: int | None = None,
    margin_top: int = 64,
    margin_bottom: int = 56,
    margin_left: int = 8,
    margin_right: int = 28,
) -> go.Figure:
    fig.update_layout(
        margin=dict(t=margin_top, r=margin_right, b=margin_bottom, l=margin_left, autoexpand=True),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=13)),
        font=dict(size=13, color="#1f2937"),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#f8fafc",
        uniformtext=dict(minsize=10, mode="show"),
    )
    if height is not None:
        fig.update_layout(height=height)
    return fig


def count_orders(orders: pd.DataFrame) -> int:
    """Satu No. Pesanan dihitung satu kali, meski berisi beberapa produk."""
    if orders.empty or "order_id" not in orders.columns:
        return 0
    ids = orders["order_id"].fillna("").astype(str).str.strip()
    ids = ids[~ids.str.lower().isin({"", "nan", "none", "-"})]
    return int(ids.nunique())


def _tick_step(peak: float, steps: int = 5) -> float:
    raw = max(float(peak), 1.0) / max(steps, 1)
    magnitude = 10 ** np.floor(np.log10(raw))
    for multiplier in (1, 2, 2.5, 5, 10):
        step = multiplier * magnitude
        if step >= raw * 0.8:
            return float(step)
    return float(10 * magnitude)


def integer_ticks(peak: float, steps: int = 5) -> tuple[list[float], list[str]]:
    """Sumbu bilangan bulat. Angka >= 1000 tetap utuh, misalnya 1.250, bukan 1."""
    peak = max(float(peak), 1.0)
    step = _tick_step(peak, steps)
    values: list[float] = []
    cursor = 0.0
    while len(values) < 8:
        values.append(cursor)
        if cursor >= peak:
            break
        cursor += step
    return values, [format_number(value, 0) for value in values]


def apply_integer_axis(fig: go.Figure, axis: str, peak: float, *, pad: float = 1.45) -> None:
    values, labels = integer_ticks(peak)
    upper = max(float(peak) * pad, values[-1] if values else float(peak))
    spec = dict(tickmode="array", tickvals=values, ticktext=labels, range=[0, upper], automargin=True)
    if axis == "x":
        fig.update_xaxes(**spec)
    elif axis == "y2":
        fig.update_layout(yaxis2={**spec, "overlaying": "y", "side": "right", "title": "QTY"})
    else:
        fig.update_layout(yaxis=spec)


@st.cache_data(show_spinner=False)
def parse_upload(file_bytes: bytes, filename: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    return load_shopee_report(file_bytes, filename=filename)


@st.cache_data(show_spinner=False)
def cached_library_frames(
    keys: tuple[str, ...], stamp: tuple[float, ...]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Baca bulan tersimpan sekali. Stempel file membuat cache batal saat impor baru."""
    del stamp
    source, _stored = load_months(list(keys))
    if source is None or source.empty:
        return pd.DataFrame(), pd.DataFrame()
    return source, clean_order_frame(source)


@st.cache_data(show_spinner=False)
def cached_ledger(keys: tuple[str, ...], stamp: tuple[float, ...]) -> pd.DataFrame:
    del stamp
    source, _orders = load_months(list(keys))
    return ledger_from_raw(source)


@st.cache_data(show_spinner=False)
def cached_merged(keys: tuple[str, ...], stamp: tuple[float, ...]) -> tuple[pd.DataFrame, pd.Series]:
    del stamp
    source, _orders = load_months(list(keys))
    base = source.drop(columns=["Nama file"], errors="ignore").drop_duplicates().reset_index(drop=True)
    return base, order_month_keys(base)


@st.cache_data(show_spinner=False)
def cached_folder(stamp: tuple[float, ...]) -> pd.DataFrame:
    del stamp
    return folder_frame()


MAX_FILES = 50
MAX_UPLOAD_BYTES = 1024 * 1024 * 1024


def load_orders(uploaded_files) -> tuple[pd.DataFrame, pd.DataFrame]:
    files = list(uploaded_files or [])
    if not files:
        return pd.DataFrame(), pd.DataFrame()
    frames = []
    sources = []
    several = len(files) > 1
    for item in files:
        frame, source = parse_upload(item.getvalue(), item.name)
        if several:
            source = source.copy()
            source.insert(0, "Nama file", item.name)
        frames.append(frame)
        sources.append(source)
    orders = pd.concat(frames, ignore_index=True).drop_duplicates().reset_index(drop=True)
    imported = pd.concat(sources, ignore_index=True)
    return orders, imported


def prepare_analysis_orders(
    orders_raw: pd.DataFrame,
    *,
    exclude_return_cancel: bool,
) -> pd.DataFrame:
    """Semua status masuk analisis. Centang exclude mengeluarkan batal dan unit retur."""
    if orders_raw is None or orders_raw.empty:
        return orders_raw
    work = orders_raw.copy()
    if exclude_return_cancel:
        if "status" in work.columns:
            work = work.loc[~work["status"].map(_is_cancelled_status)].copy()
        if "qty" in work.columns:
            work = work.loc[work["qty"] > 0].copy()
        return work.reset_index(drop=True)
    if "gross_qty" in work.columns:
        work["qty"] = work["gross_qty"]
    if "gross_sales" in work.columns:
        work["sales"] = work["gross_sales"]
    if "qty" in work.columns:
        work = work.loc[work["qty"] > 0]
    return work.reset_index(drop=True)


APP_SHEETS = (
    "Ringkasan",
    "Prediksi & stok",
    "Evaluasi model",
    "Data",
    "Folder data",
    "Laporan",
)
SUMMARY_SHEETS = {"Ringkasan", "Prediksi & stok", "Data"}


def show_app_menu() -> str:
    """Menu fitur. Tombol yang sedang terbuka memakai warna utama."""
    current = st.session_state.get("active-sheet", "Ringkasan")
    st.markdown(
        "<div class='app-menu-label'>Menu</div>"
        "<div class='app-menu-hint'>Pilih fitur yang ingin dibuka.</div>",
        unsafe_allow_html=True,
    )
    columns = st.columns(len(APP_SHEETS))
    for column, name in zip(columns, APP_SHEETS):
        if column.button(
            name,
            key=f"menu-{name}",
            type="primary" if current == name else "secondary",
            use_container_width=True,
        ):
            st.session_state["active-sheet"] = name
            st.session_state["_menu_rerun"] = True
    return str(st.session_state.get("active-sheet", "Ringkasan"))


def wrap_label(text: str, width: int = 42, max_lines: int = 8) -> str:
    """Pecah nama panjang supaya sumbu grafik menampilkan nama utuh."""
    remaining = " ".join(str(text).split())
    lines: list[str] = []
    while remaining:
        if len(remaining) <= width:
            lines.append(remaining)
            break
        cut = remaining.rfind(" ", 0, width + 1)
        if cut <= 0:
            cut = width
        lines.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max(width - 1, 1)].rstrip() + "…"
    return "<br>".join(lines)


def chart_axis_label(
    rank,
    sku,
    name: str,
    variation: str = "",
    *,
    width: int = 48,
    max_lines: int = 6,
) -> str:
    """Peringkat dan Nomor Referensi SKU di baris pertama, nama produk di bawahnya."""
    sku_text = " ".join(str(sku).split())
    if sku_text.lower() in {"", "nan", "none", "-"}:
        sku_text = "Tanpa SKU"
    try:
        number = int(rank)
        head = f"{number}. {sku_text}"
    except (TypeError, ValueError):
        head = sku_text
    title = " ".join(str(name).split())
    extra = " ".join(str(variation).split())
    if extra and extra.lower() not in {"", "tanpa variasi", "nan"} and extra.lower() not in title.lower():
        title = f"{title} — {extra}"
    head_label = wrap_label(head, width=width, max_lines=2)
    if not title:
        return head_label
    return head_label + "<br>" + wrap_label(title, width=width, max_lines=max_lines)


def product_identity(rank, sku, name: str, variation: str = "") -> str:
    """Nama lengkap satu baris: peringkat, SKU, lalu produk."""
    return chart_axis_label(rank, sku, name, variation).replace("<br>", " ")


def growth_hint(predicted: float, actual: float, basis: str) -> str:
    """Persentase prediksi terhadap penjualan yang sudah ada pada laporan."""
    if actual <= 0:
        return f"Belum ada {basis} pada laporan sebagai pembanding."
    percent = (float(predicted) - float(actual)) / float(actual) * 100
    text = format_number(percent, 1)
    if percent > 0:
        text = f"+{text}"
    return f"Kenaikan {text}% dibanding {basis} pada laporan."


def show_section_title(text: str) -> None:
    st.markdown(f"<div class='chart-heading'>{text}</div>", unsafe_allow_html=True)


def show_data_menu(source_raw: pd.DataFrame) -> None:
    """Gabungan semua file, dengan ringkasan periode dan satu daftar SKU retur serta batal."""
    file_count = 1
    if "Nama file" in source_raw.columns:
        file_count = int(source_raw["Nama file"].nunique())
    active_keys = tuple(st.session_state.get("active-library-keys") or ())
    if active_keys:
        ledger = cached_ledger(active_keys, bundle_stamp(list(active_keys)))
    else:
        ledger = ledger_from_raw(source_raw)
    st.subheader("Ringkasan data gabungan")
    st.caption(
        f"{format_number(file_count)} file digabung menjadi satu, {format_number(len(ledger))} baris produk. "
        "Baris yang sama pada lebih dari satu file dihitung sekali. "
        "Tahun, bulan, tanggal, dan status di bawah mengubah angka pada lembar Data."
    )
    if ledger.empty:
        st.write("Laporan belum bisa diringkas. Pastikan file berisi waktu pesanan, produk, dan jumlah.")
        return
    period_view, range_text = filter_resume_orders(
        ledger,
        show_controls=True,
        prefix="data",
        caption=(
            "Tahun, bulan, dan tanggal memotong seluruh angka pada lembar Data. "
            "Filter status di bawah tetap berlaku pada rentang ini."
        ),
    )
    selected_label = range_text or "kosong"
    status_names = sorted(
        {status for status in period_view["status"].tolist() if str(status).strip()},
        key=str.casefold,
    )
    choice_names = [*status_names, "Return"]
    st.markdown("**Status pesanan**")
    all_key = f"data-status-all-{selected_label}"

    def status_widget_key(status: str) -> str:
        return f"data-status-{selected_label}-{status}"

    if all_key not in st.session_state:
        st.session_state[all_key] = True
    for status in choice_names:
        key = status_widget_key(status)
        if key not in st.session_state:
            st.session_state[key] = True

    def toggle_all() -> None:
        chosen = bool(st.session_state[all_key])
        for status in choice_names:
            st.session_state[status_widget_key(status)] = chosen

    def toggle_one() -> None:
        st.session_state[all_key] = all(
            bool(st.session_state.get(status_widget_key(status), False)) for status in choice_names
        )

    box_count = min(4, max(len(choice_names) + 1, 1))
    status_boxes = st.columns(box_count)
    with status_boxes[0]:
        st.checkbox("All", key=all_key, on_change=toggle_all)
    picked = []
    for index, status in enumerate(choice_names):
        with status_boxes[(index + 1) % box_count]:
            if st.checkbox(status, key=status_widget_key(status), on_change=toggle_one):
                picked.append(status)
    select_all = bool(st.session_state.get(all_key, False)) or set(picked) == set(choice_names)
    status_picked = [name for name in picked if name != "Return"]
    include_return = select_all or "Return" in picked
    include_cancel = select_all or any(_is_cancelled_status(name) for name in status_picked)
    return_only = (not select_all) and picked == ["Return"]
    cancel_only = (
        not select_all
        and not include_return
        and bool(status_picked)
        and all(_is_cancelled_status(name) for name in status_picked)
    )
    if select_all:
        filtered = period_view
        sales_hint = (
            "Total Pembayaran seluruh transaksi pada rentang ini, termasuk retur dan batal, "
            "sekali tiap No. Pesanan"
        )
        order_hint = "Unik, semua status"
        sku_hint = "Selain pesanan batal"
    elif not picked:
        filtered = period_view.iloc[0:0]
        sales_hint = "Centang minimal satu status pesanan"
        order_hint = "Tidak ada status yang dicentang"
        sku_hint = "Tidak ada status yang dicentang"
    elif return_only:
        filtered = period_view.loc[period_view["returned_qty"] > 0].copy()
        sales_hint = "Nilai barang yang diretur: Returned quantity × Harga Setelah Diskon"
        order_hint = "No. Pesanan yang ada retur"
        sku_hint = "SKU yang ada unit retur"
    elif cancel_only:
        filtered = period_view.loc[period_view["status"].isin(status_picked)].copy()
        sales_hint = "Total Pembayaran pesanan batal, sekali tiap No. Pesanan"
        order_hint = "No. Pesanan berstatus batal"
        sku_hint = "SKU pada pesanan batal"
    else:
        mask = period_view["status"].isin(status_picked) if status_picked else pd.Series(False, index=period_view.index)
        if include_return:
            mask = mask | period_view["returned_qty"].gt(0)
        filtered = scope_ledger(
            period_view.loc[mask].copy(),
            include_cancel=include_cancel,
            include_return=include_return,
        )
        if not include_return and not include_cancel:
            sales_hint = "Sama dengan Ringkasan saat Exclude return dan batal. Total Pembayaran tanpa batal, sekali tiap No. Pesanan. Baris yang habis diretur tidak dihitung"
            order_hint = "Tanpa batal dan tanpa pesanan yang habis diretur"
            sku_hint = "SKU yang masih punya QTY setelah retur dikurangi"
        else:
            sales_hint = "Total Pembayaran untuk status yang dicentang, sekali tiap No. Pesanan"
            order_hint = "Unik, status yang dicentang"
            sku_hint = "SKU pada status yang dicentang"
    report_frame = filtered
    if return_only and not filtered.empty:
        report_frame = filtered.copy()
        report_frame["status"] = "Return"
    summary, status_table, sku_sheet = activity_report(report_frame)
    summary = focus_summary(
        summary,
        include_return=include_return,
        include_cancel=include_cancel,
        return_only=return_only,
        cancel_only=cancel_only,
    )
    if not sku_sheet.empty and not include_return:
        sku_sheet = sku_sheet.loc[pd.to_numeric(sku_sheet["Qty batal"], errors="coerce").fillna(0) > 0].copy()
    if not sku_sheet.empty and not include_cancel:
        sku_sheet = sku_sheet.loc[pd.to_numeric(sku_sheet["Qty retur"], errors="coerce").fillna(0) > 0].copy()
        if not sku_sheet.empty:
            sku_sheet["Qty batal"] = 0
            sku_sheet["Invoice batal"] = 0
            sku_sheet["Nominal batal"] = 0
            sku_sheet["Alasan batal"] = ""
    if not sku_sheet.empty and not include_return:
        sku_sheet["Qty retur"] = 0
        sku_sheet["Nominal retur"] = 0
        sku_sheet["Alasan retur"] = ""
    if not include_return and not include_cancel:
        sku_sheet = sku_sheet.iloc[0:0]
    if include_cancel:
        _contribution, contribution_table = cancel_contribution(period_view)
    else:
        _contribution, contribution_table = cancel_contribution(period_view.iloc[0:0])
    st.markdown(f"**{range_text or 'tidak ada tanggal yang dipilih'}**")
    qty_shown = float(filtered["qty"].sum()) if not filtered.empty and "qty" in filtered.columns else 0.0
    sku_shown = int(filtered["item_key"].nunique()) if not filtered.empty and "item_key" in filtered.columns else 0
    resume_row = st.columns(4)
    show_metric(resume_row[0], "Jumlah pesanan", format_number(summary["orders"]), hint=order_hint)
    show_metric(resume_row[1], "Produk / varian", format_number(sku_shown), hint=sku_hint)
    show_metric(resume_row[2], "Sales volume", format_idr(summary["sales_volume"]), hint=sales_hint)
    show_metric(
        resume_row[3],
        "QTY terjual",
        format_qty(qty_shown),
        hint="Tanpa centang Return, QTY = Jumlah − unit retur. Baris yang habis diretur tidak dihitung",
    )
    row_one = st.columns(4)
    show_metric(
        row_one[0],
        "No. Pesanan",
        format_number(summary["orders"]),
        hint=order_hint,
    )
    show_metric(row_one[1], "SKU terjual", format_number(summary["sku_sold"]), hint=sku_hint)
    show_metric(row_one[2], "SKU pada filter", format_number(summary["sku_all"]), hint="SKU pada baris yang sedang ditampilkan")
    show_metric(
        row_one[3],
        "Sales volume",
        format_idr(summary["sales_volume"]),
        hint=sales_hint,
    )
    row_two = st.columns(4)
    show_metric(
        row_two[0],
        "Invoice cancel",
        format_number(summary["invoice_cancel"]),
        hint="Hanya saat status batal atau All dicentang",
    )
    show_metric(
        row_two[1],
        "Nominal cancel",
        format_idr(summary["nominal_cancel"]),
        hint="Pembayaran pesanan batal. Nol pada status selain batal",
    )
    show_metric(
        row_two[2],
        "Sales return",
        format_qty(summary["sales_return"]),
        hint="Hanya saat Return atau All dicentang",
    )
    show_metric(
        row_two[3],
        "Nominal return",
        format_idr(summary["nominal_return"]),
        hint="Returned quantity × Harga Setelah Diskon. Nol pada status selain Return",
    )
    st.subheader("Status pesanan")
    st.caption("Jumlah No. Pesanan pada status yang dicentang. Baris Total menjumlahkan tabel ini.")
    status_view = append_total_row(status_table, "Status pesanan", ["No. Pesanan", "Kontribusi"])
    if "Kontribusi" in status_view.columns:
        status_view["Kontribusi"] = status_view["Kontribusi"].map(
            lambda value: f"{format_number(float(value), 1)}%" if str(value).strip() not in {"", "nan"} else ""
        )
    st.dataframe(
        status_view,
        height=min(44 * (len(status_view) + 1) + 36, 480),
        hide_index=True,
        column_config=table_column_config(status_view),
    )
    st.subheader("Kontribusi invoice batal")
    if not include_cancel:
        st.write("Nominal batal tidak dihitung karena status batal tidak dicentang.")
    elif contribution_table.empty:
        st.write("Tidak ada pesanan batal pada rentang ini.")
    else:
        st.caption(
            "Tiap baris adalah satu alasan pembatalan. "
            "Persentase dihitung terhadap seluruh invoice pada rentang, termasuk status yang tidak sedang dicentang. "
            "Baris Total menjumlahkan invoice, nominal, dan kontribusi pada tabel ini."
        )
        contribution_view = append_total_row(
            contribution_table,
            "Alasan pembatalan",
            ["Invoice", "Nominal", "Kontribusi invoice", "Kontribusi nominal"],
        )
        for column in ("Kontribusi invoice", "Kontribusi nominal"):
            contribution_view[column] = contribution_view[column].map(
                lambda value: f"{format_number(float(value), 1)}%" if str(value).strip() not in {"", "nan"} else ""
            )
        st.dataframe(
            contribution_view,
            height=min(44 * (len(contribution_view) + 1) + 36, 560),
            hide_index=True,
            column_config=table_column_config(contribution_view, roomy=True),
        )
    st.subheader("Pembeli batal karena belum bayar")
    st.caption(
        "Nama akun pembeli ditulis sekali. Tiap No. Pesanan tetap baris sendiri, dengan tanggal, SKU, nama produk, QTY, dan sales volume. "
        "Pembeli yang batal karena belum dibayar lalu punya pesanan lain untuk SKU yang sama tidak masuk tabel ini."
    )
    unpaid_months = list(st.session_state.get("data_months") or [])
    if not unpaid_months:
        unpaid = unpaid_buyer_table(source_raw.iloc[0:0])
    else:
        unpaid = unpaid_buyer_table(
            source_raw,
            months=unpaid_months,
            start=st.session_state.get("data_start"),
            end=st.session_state.get("data_end"),
        )
    if unpaid.empty:
        st.write("Tidak ada pembeli yang batal karena belum bayar pada periode ini.")
    else:
        st.dataframe(
            unpaid,
            height=min(44 * (len(unpaid) + 1) + 36, 560),
            hide_index=True,
            column_config=table_column_config(unpaid, roomy=True),
        )
        st.download_button(
            "Unduh pembeli belum bayar (CSV)",
            unpaid.to_csv(index=False).encode("utf-8-sig"),
            file_name="pembeli_belum_bayar.csv",
            mime="text/csv",
        )
    st.subheader("SKU dengan retur dan batal")
    issue_kind = st.selectbox(
        "Tampilkan",
        options=["All", "Retur", "Batal"],
        index=0,
        key="data-issue-kind",
    )
    if issue_kind == "Retur":
        kind_sheet = sku_sheet.loc[sku_sheet["Qty retur"] > 0] if not sku_sheet.empty else sku_sheet
        reason_column = "Alasan retur"
        reason_names = sorted({value for value in kind_sheet[reason_column].tolist() if str(value).strip()})
    elif issue_kind == "Batal":
        kind_sheet = sku_sheet.loc[sku_sheet["Qty batal"] > 0] if not sku_sheet.empty else sku_sheet
        reason_column = "Alasan batal"
        reason_names = sorted({value for value in kind_sheet[reason_column].tolist() if str(value).strip()})
    else:
        kind_sheet = sku_sheet
        reason_column = ""
        reason_names = sorted(
            {
                value
                for column in ("Alasan retur", "Alasan batal")
                for value in (sku_sheet[column].tolist() if column in sku_sheet.columns else [])
                if str(value).strip()
            }
        )
    st.markdown("**Alasan**")
    selected_reasons: list[str] = []
    if not reason_names:
        st.caption("Tidak ada alasan pada tampilan ini.")
    else:
        reason_all_key = f"data-reason-all-{issue_kind}"

        def reason_widget_key(reason: str) -> str:
            return f"data-reason-{issue_kind}-{reason}"

        if reason_all_key not in st.session_state:
            st.session_state[reason_all_key] = True
        for reason in reason_names:
            widget = reason_widget_key(reason)
            if widget not in st.session_state:
                st.session_state[widget] = True

        def toggle_reason_all() -> None:
            chosen = bool(st.session_state[reason_all_key])
            for reason in reason_names:
                st.session_state[reason_widget_key(reason)] = chosen

        def toggle_reason_one() -> None:
            st.session_state[reason_all_key] = all(
                bool(st.session_state.get(reason_widget_key(reason), False)) for reason in reason_names
            )

        st.checkbox("All", key=reason_all_key, on_change=toggle_reason_all)
        reason_boxes = st.columns(2)
        for index, reason in enumerate(reason_names):
            with reason_boxes[index % 2]:
                if st.checkbox(reason, key=reason_widget_key(reason), on_change=toggle_reason_one):
                    selected_reasons.append(reason)
        if not selected_reasons:
            st.warning("Centang minimal satu alasan.")
    if kind_sheet.empty or not reason_names:
        shown_sheet = kind_sheet
    elif not selected_reasons:
        shown_sheet = kind_sheet.iloc[0:0]
    elif reason_column:
        shown_sheet = kind_sheet.loc[kind_sheet[reason_column].isin(selected_reasons)]
    else:
        shown_sheet = kind_sheet.loc[
            kind_sheet["Alasan retur"].isin(selected_reasons) | kind_sheet["Alasan batal"].isin(selected_reasons)
        ]
    if issue_kind == "Retur":
        keep_columns = [
            "Peringkat",
            "Referensi SKU",
            "Variasi",
            "Produk",
            "Qty retur",
            "Nominal retur",
            "Alasan retur",
        ]
        sheet_title = "Hanya kolom retur. Diurutkan dari qty retur terbesar."
    elif issue_kind == "Batal":
        keep_columns = [
            "Peringkat",
            "Referensi SKU",
            "Variasi",
            "Produk",
            "Qty batal",
            "Invoice batal",
            "Nominal batal",
            "Alasan batal",
        ]
        sheet_title = "Hanya kolom batal. Diurutkan dari qty batal terbesar."
    else:
        keep_columns = list(shown_sheet.columns)
        sheet_title = "Kolom retur dan batal. Diurutkan dari retur terbanyak, lalu batal terbanyak."
    if not shown_sheet.empty:
        shown_sheet = shown_sheet.loc[:, [column for column in keep_columns if column in shown_sheet.columns]].copy()
    sheet_count = len(shown_sheet)
    sum_columns = [
        column
        for column in ("Qty retur", "Nominal retur", "Qty batal", "Invoice batal", "Nominal batal")
        if column in shown_sheet.columns
    ]
    if not shown_sheet.empty:
        shown_sheet = shown_sheet.copy()
        shown_sheet["Peringkat"] = [str(number) for number in range(1, len(shown_sheet) + 1)]
        shown_sheet = append_total_row(shown_sheet, "Referensi SKU", sum_columns)
    st.caption(
        f"{format_number(sheet_count)} baris. {sheet_title} "
        "Alasan retur dari Status Pembatalan/Pengembalian. "
        "Alasan batal dari Alasan Pembatalan. "
        "Nominal retur = Returned quantity × Harga Setelah Diskon. "
        "Nominal batal = Harga Setelah Diskon × Jumlah pada baris batal."
    )
    if shown_sheet.empty:
        st.write("Tidak ada SKU dengan retur atau batal pada filter ini.")
    else:
        st.dataframe(
            shown_sheet,
            height=680,
            row_height=44,
            hide_index=True,
            column_config=table_column_config(shown_sheet, roomy=True),
        )
        st.download_button(
            "Unduh lembar SKU retur dan batal (CSV)",
            shown_sheet.to_csv(index=False).encode("utf-8-sig"),
            file_name="sku_retur_batal.csv",
            mime="text/csv",
        )
    st.subheader("Tabel gabungan dari semua file")
    active_keys = tuple(st.session_state.get("active-library-keys") or ())
    if active_keys:
        merged_base, month_keys = cached_merged(active_keys, bundle_stamp(list(active_keys)))
    else:
        merged_base = source_raw.drop(columns=["Nama file"], errors="ignore").drop_duplicates().reset_index(drop=True)
        month_keys = order_month_keys(merged_base)
    month_values = sorted({key for key in month_keys.tolist() if key and key != "tanpa-bulan"})
    years = sorted({key[:4] for key in month_values})
    st.markdown("**Filter tabel**")
    selected_months: list[str] = []
    if not years:
        st.caption("Tidak ada bulan pada lampiran.")
    else:
        saved_year = str(st.session_state.get("merged_year") or years[-1])
        if saved_year not in years:
            saved_year = years[-1]
        if st.session_state.get("merged-year") not in years:
            st.session_state["merged-year"] = saved_year
        merged_year = st.selectbox("Tahun", years, index=years.index(saved_year), key="merged-year")
        year_months = [key for key in month_values if key.startswith(str(merged_year))]
        known_months = st.session_state.get("merged_months")
        saved_months = [key for key in known_months if key in year_months] if isinstance(known_months, list) else []
        fresh_year = year_months and all(f"merged-month-{key}" not in st.session_state for key in year_months)
        if not saved_months and fresh_year:
            saved_months = [year_months[-1]]
        st.markdown("**Bulan**")
        for start in range(0, len(year_months), 4):
            box_columns = st.columns(4)
            for offset, key in enumerate(year_months[start : start + 4]):
                widget = f"merged-month-{key}"
                if widget not in st.session_state:
                    st.session_state[widget] = key in saved_months
                with box_columns[offset]:
                    if st.checkbox(month_label(key), key=widget):
                        selected_months.append(key)
        st.session_state["merged_year"] = str(merged_year)
        st.session_state["merged_months"] = selected_months
        if not selected_months:
            st.warning("Centang minimal satu bulan.")
    if selected_months:
        merged = merged_base.loc[month_keys.isin(selected_months)].reset_index(drop=True)
    else:
        merged = merged_base.iloc[0:0].copy()
    merged = clean_sku_columns(merged)
    scope_text = ", ".join(month_label(key) for key in selected_months) or "tidak ada bulan"
    st.caption(f"{format_number(len(merged))} baris, {scope_text}. Kolom mengikuti lampiran.")
    show_merged = st.session_state.setdefault("show-merged-table", True)
    toggle_label = "Sembunyikan tabel" if show_merged else "Tampilkan tabel"
    if st.button(toggle_label, key="toggle-merged-table"):
        st.session_state["show-merged-table"] = not show_merged
        st.rerun()
    if st.session_state["show-merged-table"]:
        st.dataframe(merged, height=680, hide_index=True)


def _slide_head(kicker: str, title: str) -> None:
    st.markdown(
        f"<p class='report-kicker'>{html.escape(kicker)}</p>"
        f"<div class='report-title'>{html.escape(title)}</div>",
        unsafe_allow_html=True,
    )


def _month_rows(ledger: pd.DataFrame) -> pd.DataFrame:
    """Ringkas transaksi per bulan pada rentang laporan."""
    columns = ["Bulan", "No. Pesanan", "QTY bersih", "Sales bersih", "Sales batal", "Nominal retur"]
    if ledger is None or ledger.empty or "order_time" not in ledger.columns:
        return pd.DataFrame(columns=columns)
    work = ledger.copy()
    work["_bulan"] = pd.to_datetime(work["order_time"], errors="coerce").dt.to_period("M").astype(str)
    rows = []
    for key, group in work.groupby("_bulan", sort=True):
        net = scope_ledger(group, include_cancel=False, include_return=False)
        cancel = group.loc[group["is_cancel"]] if "is_cancel" in group.columns else group.iloc[0:0]
        rows.append(
            {
                "Bulan": month_label(str(key)),
                "No. Pesanan": count_orders(group),
                "QTY bersih": int(round(float(net["qty"].sum()))) if not net.empty and "qty" in net.columns else 0,
                "Sales bersih": int(round(order_revenue(net))),
                "Sales batal": int(round(order_revenue(cancel))),
                "Nominal retur": int(round(float(group["return_value"].sum()))) if "return_value" in group.columns else 0,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def show_report_menu(
    source_raw: pd.DataFrame,
    orders: pd.DataFrame,
    combined: pd.DataFrame,
    stock: pd.DataFrame,
    history: pd.DataFrame,
    metric: str,
    period: str,
    period_text: str,
    last_period,
    *,
    window_start,
    window_end,
    service: int,
    exclude_return_cancel: bool,
) -> None:
    """Slide presentasi dari Ringkasan, Prediksi & stok, Data, dan Folder data."""
    titles = [
        "Sampul",
        "Penjualan",
        "Item terlaris",
        "Prediksi dan stok",
        "Status transaksi",
        "Retur dan batal",
        "Belum bayar",
        "Data tersimpan",
        "Insight",
    ]
    st.subheader("Laporan")
    st.caption(
        "Slide ini merangkum analisa di aplikasi, kecuali Evaluasi model. "
        "Tahun, bulan, dan tanggal di bawah membaca data yang sudah diunggah. "
        "Prediksi tetap hasil analisis terakhir."
    )
    active_keys = tuple(st.session_state.get("active-library-keys") or ())
    if active_keys:
        ledger = cached_ledger(active_keys, bundle_stamp(list(active_keys)))
    elif source_raw is not None and not source_raw.empty:
        ledger = ledger_from_raw(source_raw)
    else:
        ledger = pd.DataFrame()
    period_view, range_text = filter_resume_orders(
        ledger,
        show_controls=True,
        prefix="laporan",
        caption="Tahun, bulan, dan tanggal ini memotong seluruh slide laporan.",
    )
    forecast_orders, _forecast_label = filter_resume_orders(
        orders,
        show_controls=False,
        prefix="laporan",
    )
    scope_label = range_text or "tidak ada tanggal yang dipilih"
    if "laporan-slide-name" not in st.session_state or st.session_state["laporan-slide-name"] not in titles:
        st.session_state["laporan-slide-name"] = titles[0]
    position = titles.index(st.session_state["laporan-slide-name"])
    previous, picker, following = st.columns([1, 2.6, 1])
    if previous.button("Sebelumnya", disabled=position == 0, use_container_width=True):
        st.session_state["laporan-slide-name"] = titles[position - 1]
        st.rerun()
    if following.button("Berikutnya", disabled=position >= len(titles) - 1, use_container_width=True):
        st.session_state["laporan-slide-name"] = titles[position + 1]
        st.rerun()
    picker.selectbox("Slide presentasi", titles, key="laporan-slide-name")
    slide = str(st.session_state["laporan-slide-name"])
    st.caption(f"Slide {titles.index(slide) + 1} dari {len(titles)}")

    summary, status_table, sku_sheet = activity_report(period_view if period_view is not None else pd.DataFrame())
    net = scope_ledger(period_view, include_cancel=False, include_return=False)
    net_orders = count_orders(net)
    net_qty = float(net["qty"].sum()) if not net.empty and "qty" in net.columns else 0.0
    net_sales = order_revenue(net)
    gross_orders = int(summary.get("orders", 0))
    gross_sales = float(summary.get("sales_volume", 0))
    catalog = top_bestsellers(
        forecast_orders if forecast_orders is not None else pd.DataFrame(),
        combined,
        stock,
        history,
        metric,
        last_period,
        period,
        top_n=None,
    )
    view = catalog.head(TOP_N).reset_index(drop=True) if not catalog.empty else catalog
    if not view.empty:
        view = view.sort_values(["peringkat", "item_key"], kind="mergesort").reset_index(drop=True)

    if slide == "Sampul":
        _slide_head("Tinjauan manajer", "Laporan analisa toko")
        st.markdown(
            "<div class='report-body'>"
            f"Periode data pada slide ini: <b>{html.escape(scope_label)}</b>. "
            f"Parameter peringkat: <b>{html.escape(METRIC_LABELS.get(metric, metric))}</b>. "
            f"Prediksi {html.escape(period_text)}, {html.escape(format_id_date(window_start))} – {html.escape(format_id_date(window_end))}. "
            f"Safety stock pada analisis terakhir {html.escape(format_number(service))}%. "
            f"Exclude return dan batal {'sedang menyala' if exclude_return_cancel else 'sedang mati'} "
            "pada angka prediksi, karena angka itu mengikuti hasil Jalankan analisis."
            "</div>",
            unsafe_allow_html=True,
        )
        cards = st.columns(4)
        show_metric(cards[0], "Pesanan pada periode", format_number(gross_orders))
        show_metric(cards[1], "Sales seluruh status", format_idr(gross_sales))
        show_metric(cards[2], "Sales bersih", format_idr(net_sales), hint="Tanpa batal dan tanpa baris yang habis diretur")
        show_metric(cards[3], "QTY bersih", format_qty(net_qty))
    elif slide == "Penjualan":
        _slide_head(scope_label, "Penjualan pada periode ini")
        cards = st.columns(4)
        show_metric(cards[0], "No. Pesanan bersih", format_number(net_orders))
        show_metric(cards[1], "Sales bersih", format_idr(net_sales))
        show_metric(cards[2], "QTY bersih", format_qty(net_qty))
        show_metric(
            cards[3],
            "Selisih sales kotor",
            format_idr(gross_sales - net_sales),
            hint="Sales seluruh status dikurangi sales bersih",
        )
        if net.empty:
            st.write("Tidak ada penjualan bersih pada tanggal ini.")
        else:
            st.plotly_chart(daily_actual_chart(net, scope_label, "sales"), use_container_width=True)
            st.caption("Batang adalah sales bersih per tanggal. Angka mengikuti Total Pembayaran sekali tiap No. Pesanan.")
    elif slide == "Item terlaris":
        _slide_head(scope_label, f"50 item terlaris menurut {METRIC_LABELS.get(metric, metric)}")
        if view.empty:
            st.write("Tidak ada item pada tanggal ini.")
        elif metric == "sales":
            st.caption(
                "Biru dan oranye adalah sales. Hijau adalah stok prediksi dalam unit. "
                "Tiap produk punya skala sendiri."
            )
            st.plotly_chart(item_sales_chart(view, "laporan"), use_container_width=True)
        else:
            st.caption("Biru adalah QTY pada periode laporan. Oranye adalah prediksi.")
            st.plotly_chart(item_qty_chart(view, "laporan"), use_container_width=True)
        if not view.empty:
            top_sales = float(view["sales_total"].sum())
            share = top_sales / net_sales * 100 if net_sales > 0 else 0.0
            st.caption(
                f"Sales Top 50 pada periode ini {format_idr(top_sales)}, "
                f"{format_number(share, 1)}% dari sales bersih."
            )
    elif slide == "Prediksi dan stok":
        _slide_head(period_text, "Prediksi permintaan dan stok yang disiapkan")
        if view.empty:
            st.write("Prediksi belum punya item pada tanggal ini.")
        else:
            pred_qty = float(view["pred_qty"].sum())
            pred_sales = float(view["pred_sales"].sum())
            safety_units = float(view["safety_stock"].sum())
            stock_units = float(view["stok_disarankan"].sum())
            cards = st.columns(4)
            show_metric(cards[0], "Prediksi QTY Top 50", format_qty(pred_qty))
            show_metric(cards[1], "Prediksi sales Top 50", format_idr(pred_sales))
            show_metric(cards[2], "Safety stock", format_qty(safety_units), hint="Cadangan, dalam unit")
            show_metric(cards[3], "Stok prediksi", format_qty(stock_units), hint="Prediksi QTY ditambah safety stock")
            display = leaderboard_frame(view.head(10), period)
            st.caption("Sepuluh peringkat teratas. Daftar lengkap ada di menu Prediksi & stok.")
            st.dataframe(display, hide_index=True, height=44 * (len(display) + 1) + 36, column_config=table_column_config(display, roomy=True))
    elif slide == "Status transaksi":
        _slide_head(scope_label, "Status pesanan")
        st.caption("Seluruh status pada tanggal yang dipilih, termasuk batal dan retur.")
        if status_table.empty:
            st.write("Tidak ada status pada tanggal ini.")
        else:
            status_view = append_total_row(status_table, "Status pesanan", ["No. Pesanan", "Kontribusi"])
            if "Kontribusi" in status_view.columns:
                status_view = status_view.copy()
                status_view["Kontribusi"] = status_view["Kontribusi"].map(
                    lambda value: f"{format_number(float(value), 1)}%" if str(value).strip() not in {"", "nan"} else ""
                )
            st.dataframe(status_view, hide_index=True, height=min(44 * (len(status_view) + 1) + 36, 520))
            busiest = status_table.sort_values("No. Pesanan", ascending=False).iloc[0]
            st.markdown(
                "<div class='report-body'>"
                f"Status dengan pesanan terbanyak: <b>{html.escape(str(busiest['Status pesanan']))}</b>, "
                f"{html.escape(format_number(float(busiest['No. Pesanan'])))} pesanan."
                "</div>",
                unsafe_allow_html=True,
            )
    elif slide == "Retur dan batal":
        _slide_head(scope_label, "Retur dan pembatalan")
        cards = st.columns(4)
        show_metric(cards[0], "Invoice batal", format_number(summary.get("invoice_cancel", 0)))
        show_metric(cards[1], "Nominal batal", format_idr(summary.get("nominal_cancel", 0)))
        show_metric(cards[2], "QTY retur", format_qty(summary.get("sales_return", 0)))
        show_metric(cards[3], "Nominal retur", format_idr(summary.get("nominal_return", 0)))
        _contribution, contribution_table = cancel_contribution(period_view)
        if contribution_table.empty:
            st.write("Tidak ada pesanan batal pada tanggal ini.")
        else:
            preview = contribution_table.head(8).copy()
            for column in ("Kontribusi invoice", "Kontribusi nominal"):
                if column in preview.columns:
                    preview[column] = preview[column].map(
                        lambda value: f"{format_number(float(value), 1)}%" if str(value).strip() not in {"", "nan"} else ""
                    )
            st.caption("Delapan alasan batal dengan invoice terbanyak.")
            st.dataframe(preview, hide_index=True, height=min(44 * (len(preview) + 1) + 36, 420))
        if sku_sheet.empty:
            st.write("Tidak ada SKU retur atau batal pada tanggal ini.")
        else:
            issue = sku_sheet.head(8)
            st.caption("Delapan SKU dengan retur atau batal terbesar. Daftar lengkap ada di menu Data.")
            st.dataframe(issue, hide_index=True, height=min(44 * (len(issue) + 1) + 36, 420))
    elif slide == "Belum bayar":
        _slide_head(scope_label, "Batal karena pembeli belum bayar")
        months = list(st.session_state.get("laporan_months") or [])
        if not months or source_raw is None or source_raw.empty:
            unpaid = pd.DataFrame()
        else:
            unpaid = unpaid_buyer_table(
                source_raw,
                months=months,
                start=st.session_state.get("laporan_start"),
                end=st.session_state.get("laporan_end"),
            )
        if unpaid.empty:
            st.write("Tidak ada pembeli yang batal karena belum bayar pada tanggal ini.")
        else:
            buyer_count = int(unpaid.loc[unpaid["No"].astype(str).str.strip().ne(""), "No"].nunique()) if "No" in unpaid.columns else 0
            order_count = int(unpaid["No. Pesanan"].replace("", pd.NA).nunique()) if "No. Pesanan" in unpaid.columns else 0
            qty_missed = float(pd.to_numeric(unpaid["QTY"], errors="coerce").fillna(0).sum()) if "QTY" in unpaid.columns else 0.0
            sales_missed = float(pd.to_numeric(unpaid["Sales volume"], errors="coerce").fillna(0).sum()) if "Sales volume" in unpaid.columns else 0.0
            cards = st.columns(4)
            show_metric(cards[0], "Akun pembeli", format_number(buyer_count))
            show_metric(cards[1], "No. Pesanan", format_number(order_count))
            show_metric(cards[2], "QTY", format_qty(qty_missed))
            show_metric(cards[3], "Sales yang tidak masuk", format_idr(sales_missed), hint="Harga setelah diskon kali jumlah")
            share_cancel = sales_missed / float(summary.get("nominal_cancel", 0) or 0) * 100 if float(summary.get("nominal_cancel", 0) or 0) > 0 else 0.0
            st.markdown(
                "<div class='report-body'>"
                "Ini pembeli yang batal karena belum bayar, dan tidak punya pesanan lain untuk SKU yang sama. "
                f"Nilainya {html.escape(format_number(share_cancel, 1))}% dari nominal batal pada periode ini. "
                "Nama akun dan nomor pesanan ada di menu Data."
                "</div>",
                unsafe_allow_html=True,
            )
    elif slide == "Data tersimpan":
        _slide_head(scope_label, "Data yang diunggah pada periode ini")
        month_table = _month_rows(period_view)
        saved = list_months()
        st.caption(
            f"{format_number(len(saved))} bulan tersimpan di Folder data. "
            "Tabel di bawah hanya bulan yang masuk filter laporan."
        )
        if month_table.empty:
            st.write("Tidak ada bulan pada tanggal ini.")
        else:
            st.dataframe(month_table, hide_index=True, height=min(44 * (len(month_table) + 1) + 36, 480))
            st.markdown(
                "<div class='report-body'>"
                "Sales bersih sama dengan Folder data: Total Pembayaran tanpa pesanan batal, sekali tiap No. Pesanan, "
                "dan tanpa baris yang habis diretur."
                "</div>",
                unsafe_allow_html=True,
            )
    else:
        _slide_head(scope_label, "Insight untuk ditinjau")
        lines = []
        if gross_orders <= 0:
            lines.append("Pada tanggal ini belum ada transaksi yang bisa ditinjau.")
        else:
            cancel_share = float(summary.get("invoice_cancel", 0)) / gross_orders * 100 if gross_orders else 0.0
            lines.append(
                f"Dari {format_number(gross_orders)} pesanan, {format_number(cancel_share, 1)}% berstatus batal. "
                f"Nominal batal {format_idr(summary.get('nominal_cancel', 0))}."
            )
            lines.append(
                f"Penjualan bersih {format_idr(net_sales)} dari {format_qty(net_qty)} unit, "
                f"{format_number(net_orders)} pesanan."
            )
            if float(summary.get("nominal_return", 0)) > 0:
                lines.append(
                    f"Retur pada periode ini {format_qty(summary.get('sales_return', 0))} unit, "
                    f"senilai {format_idr(summary.get('nominal_return', 0))}."
                )
            if not view.empty:
                gap = float(view["pred_sales"].sum() - view["sales_total"].sum())
                direction = "di atas" if gap >= 0 else "di bawah"
                lines.append(
                    f"Prediksi sales Top 50 berada {direction} sales periode ini sebesar {format_idr(abs(gap))}. "
                    f"Stok yang disiapkan untuk Top 50 adalah {format_qty(float(view['stok_disarankan'].sum()))} unit."
                )
            lines.append("Evaluasi model tidak masuk presentasi ini. Detail algoritma tetap di menu itu.")
        st.markdown(
            "<div class='report-body'>" + "<br><br>".join(html.escape(line) for line in lines) + "</div>",
            unsafe_allow_html=True,
        )


def show_folder_menu() -> None:
    """Daftar data tersimpan menurut bulan dan tahun, plus riwayat impor."""
    saved = list_months()
    st.subheader("Folder data")
    st.caption(
        "Data yang sudah diimpor tersimpan di sini. "
        "Pilih tahun dan bulan pada menu samping untuk memakai data itu tanpa mengunggah ulang. "
        "Mengunggah file baru mengganti bulan yang sama dengan isi file baru."
    )
    if not saved:
        st.write("Belum ada data tersimpan.")
    else:
        folder = cached_folder(bundle_stamp([item["key"] for item in saved]))
        st.caption(
            "QTY terjual dan Sales sama dengan Ringkasan saat Exclude return dan batal dicentang: "
            "Total Pembayaran tanpa pesanan batal, sekali tiap No. Pesanan, dan tanpa baris yang habis diretur. "
            "QTY return berdampingan dengan Sales return. QTY batal berdampingan dengan Sales batal. "
            "Return dan Batal adalah jumlah No. Pesanan. "
            "Berhasil menggabungkan Pesanan Diterima, Sedang Dikirim, Selesai, dan Telah Dikirim."
        )
        st.dataframe(
            folder,
            height=min(44 * (len(folder) + 1) + 36, 480),
            hide_index=True,
            column_config=table_column_config(folder),
        )
    st.subheader("Riwayat perubahan data")
    changes = history_frame()
    if changes.empty:
        st.write("Belum ada perubahan impor.")
    else:
        st.dataframe(changes, height=min(44 * (len(changes) + 1) + 36, 480), hide_index=True)


def show_metric(column, label: str, value: str, *, compact: bool = False, hint: str | None = None) -> None:
    value_class = "readable-metric-value compact" if compact else "readable-metric-value"
    hint_html = f"<div class='metric-hint'>{hint}</div>" if hint else ""
    column.markdown(
        f"<div class='readable-metric-label'>{label}</div>"
        f"<div class='{value_class}'>{value}</div>"
        f"{hint_html}",
        unsafe_allow_html=True,
    )


SUGGESTED_SERVICE = {
    "bulan": 95,
    "kuartal": 94,
    "semester": 91,
    "tahun": 85,
}


def _signed_units(value: int) -> str:
    number = int(value)
    if number > 0:
        return f"+{format_number(number)} unit"
    if number < 0:
        return f"−{format_number(abs(number))} unit"
    return "0 unit"


def _signed_money(value: int) -> str:
    number = int(value)
    if number > 0:
        return f"+{format_idr(number)}"
    if number < 0:
        return f"−{format_idr(abs(number))}"
    return format_idr(0)


def safety_analysis(
    percent: int,
    period: str,
    impact: dict | None,
    synced: bool,
    has_result: bool = False,
    metric: str = "qty",
) -> tuple[str, str]:
    """Analisa singkat safety stock untuk periode yang sedang dipilih."""
    suggested = SUGGESTED_SERVICE[period]
    period_phrase = f"periode yang dipilih ({PERIOD_SPECS[period].label})"
    level = int(percent)
    if level == suggested:
        css = "side-best"
        headline = f"Analisa terbaik. Safety stock {level}% sama dengan saran untuk {period_phrase}."
    elif level < suggested:
        css = "side-low"
        headline = (
            f"Analisa: Safety stock {level}% berada di bawah saran {suggested}% untuk {period_phrase}. "
            "Cadangan lebih tipis, jadi peluang kehabisan barang lebih besar."
        )
    else:
        css = "side-warn"
        headline = (
            f"Analisa: Safety stock {level}% berada di atas saran {suggested}% untuk {period_phrase}. "
            "Stok disarankan lebih tinggi, jadi barang bisa mengendap lebih lama."
        )
    if impact is None or not synced:
        if not synced and has_result:
            pending = "Klik Jalankan analisis supaya angka mengikuti file dan periode yang baru."
        elif not has_result:
            pending = "Klik Jalankan analisis untuk menghitung angka ini."
        else:
            pending = "Angka item terlaris belum tersedia untuk persentase ini."
        return css, f"{headline}<br>{pending}"
    if metric == "sales":
        figures = (
            f"Pada {impact['items']} item terlaris menurut sales volume: "
            f"prediksi sales volume {format_idr(impact['pred_sales'])} "
            f"({format_number(impact['pred_qty'])} unit), "
            f"stok prediksi {format_idr(impact['stok_sales'])} "
            f"({format_number(impact['stok'])} unit)."
        )
        if level != suggested:
            figures += (
                f" Selisih dari saran {suggested}%: "
                f"stok prediksi {_signed_money(impact['stok_sales'] - impact['base_stok_sales'])}."
            )
        return css, f"{headline}<br>{figures}"
    figures = (
        f"Pada {impact['items']} item terlaris: "
        f"prediksi QTY {format_number(impact['pred_qty'])} unit, "
        f"safety stock {format_number(impact['buffer'])} unit, "
        f"stok disarankan {format_number(impact['stok'])} unit, "
        f"prediksi sales volume {format_idr(impact['pred_sales'])}."
    )
    if level != suggested:
        figures += (
            f" Selisih dari saran {suggested}%: "
            f"safety stock {_signed_units(impact['buffer'] - impact['base_buffer'])}, "
            f"stok disarankan {_signed_units(impact['stok'] - impact['base_stok'])}."
        )
    return css, f"{headline}<br>{figures}"


def ranked_name(rank, name: str, variation: str = "") -> str:
    """Nama produk dengan nomor peringkat di depan."""
    body = " ".join(str(name).split())
    extra = " ".join(str(variation).split())
    if extra and extra.lower() not in {"", "tanpa variasi", "nan"} and extra.lower() not in body.lower():
        body = f"{body} — {extra}"
    try:
        number = int(rank)
    except (TypeError, ValueError):
        return body
    return f"{number}. {body}"


def top_bestsellers(
    orders: pd.DataFrame,
    combined: pd.DataFrame,
    stock: pd.DataFrame,
    history: pd.DataFrame,
    metric: str,
    last_period,
    period: str,
    top_n: int | None = TOP_N,
) -> pd.DataFrame:
    ranked = rank_from_orders(orders, metric)
    if ranked.empty:
        return ranked
    view = ranked.copy() if top_n is None else ranked.head(top_n).copy()
    forecast_cols = [
        "item_key",
        "pred_qty",
        "pred_sales",
        "model_qty",
        "model_sales",
        "mape_qty",
        "mape_sales",
        "next_period",
    ]
    view = view.merge(combined[forecast_cols], on="item_key", how="left")
    view = view.merge(
        stock[["item_key", "safety_stock", "stok_disarankan"]],
        on="item_key",
        how="left",
    )
    last = history.loc[
        history["period_start"] == last_period, ["item_key", "qty", "sales"]
    ].rename(columns={"qty": "qty_histori", "sales": "sales_histori"})
    view = view.merge(last, on="item_key", how="left")
    for column, default in (
        ("qty_histori", 0.0),
        ("sales_histori", 0.0),
        ("pred_qty", 0.0),
        ("pred_sales", 0.0),
        ("safety_stock", 0.0),
        ("stok_disarankan", 0),
    ):
        view[column] = view[column].fillna(default)
    view["pred_qty"] = np.rint(view["pred_qty"].astype(float)).astype(int).clip(lower=0)
    view["pred_sales"] = np.rint(view["pred_sales"].astype(float)).astype(int).clip(lower=0)
    view["safety_stock"] = np.rint(view["safety_stock"].astype(float)).astype(int).clip(lower=0)
    missed = (view["pred_qty"] <= 0) & (view["qty_total"] > 0)
    if missed.any():
        span_days = max(int((orders["order_time"].max() - orders["order_time"].min()).days) + 1, 1)
        horizon_days = horizon_day_count(period)
        view.loc[missed, "pred_qty"] = np.maximum(
            np.rint(view.loc[missed, "qty_total"] / span_days * horizon_days).astype(int),
            1,
        )
        unit_price = view.loc[missed, "sales_total"] / view.loc[missed, "qty_total"].replace(0, np.nan)
        view.loc[missed, "pred_sales"] = np.rint(view.loc[missed, "pred_qty"] * unit_price.fillna(0)).astype(int)
    view["stok_disarankan"] = (view["pred_qty"].astype(int) + view["safety_stock"].astype(int)).clip(lower=0)
    view["variasi_tampil"] = view["variation"].map(lambda value: value if str(value).strip() else "Tanpa variasi")
    return view


TABLE_SORTS = {
    "qty_desc": ("qty_total", False, "QTY terjual, terbesar dulu"),
    "qty_asc": ("qty_total", True, "QTY terjual, terkecil dulu"),
    "sales_desc": ("sales_total", False, "Sales volume, terbesar dulu"),
    "sales_asc": ("sales_total", True, "Sales volume, terkecil dulu"),
    "pred_qty_desc": ("pred_qty", False, "Prediksi QTY, terbesar dulu"),
    "pred_qty_asc": ("pred_qty", True, "Prediksi QTY, terkecil dulu"),
    "pred_sales_desc": ("pred_sales", False, "Prediksi sales volume, terbesar dulu"),
    "pred_sales_asc": ("pred_sales", True, "Prediksi sales volume, terkecil dulu"),
    "stok_desc": ("stok_disarankan", False, "Stok disarankan, terbesar dulu"),
    "stok_asc": ("stok_disarankan", True, "Stok disarankan, terkecil dulu"),
}


def sort_leaderboard(view: pd.DataFrame, sort_key: str) -> pd.DataFrame:
    column, ascending, _label = TABLE_SORTS[sort_key]
    ordered = view.sort_values(
        [column, "peringkat", "item_key"],
        ascending=[ascending, True, True],
        kind="mergesort",
    )
    return ordered.reset_index(drop=True)


def leaderboard_frame(view: pd.DataFrame, period: str) -> pd.DataFrame:
    period_name = PERIOD_SPECS[period].label.lower()
    return pd.DataFrame(
        {
            "Peringkat": view["peringkat"].astype(int),
            "Produk": [
                ranked_name(rank, name) for rank, name in zip(view["peringkat"], view["product_name"])
            ],
            "Variasi": view["variasi_tampil"],
            "Referensi SKU": view["sku"],
            "QTY terjual": view["qty_total"].astype(int),
            "Sales volume": view["sales_total"].round().astype(int),
            f"Prediksi QTY ({period_name})": view["pred_qty"].astype(int),
            f"Prediksi sales volume ({period_name})": view["pred_sales"].round().astype(int),
            f"Safety stock ({period_name})": view["safety_stock"].astype(int),
            f"Stok disarankan ({period_name})": view["stok_disarankan"].astype(int),
        }
    )


def service_z(percent: int) -> float:
    """Ubah persentase safety stock menjadi z-score.

    Sampai 100% memakai distribusi normal. Di atas 100% cadangan terus naik
    dari batas 99,9%, supaya input tidak berhenti di angka 100.
    """
    level = int(percent)
    if level <= 0:
        return 0.0
    z_cap = float(NormalDist().inv_cdf(0.999))
    if level >= 100:
        return z_cap * (level / 100.0)
    return float(NormalDist().inv_cdf(level / 100.0))


def _stock_for(analysis: dict, percent: int) -> pd.DataFrame:
    """Hitung ulang cadangan dari tren yang sudah tersimpan. Persentase hanya mengubah z."""
    return recommend_stock(
        analysis.get("base_history", pd.DataFrame()),
        analysis["combined"],
        analysis.get("base_period", "hari"),
        service_level_z=service_z(percent),
        horizon_steps=int(analysis.get("horizon_steps", HORIZON_DAYS[analysis["period"]])),
    )


def _money_from_units(shown: pd.DataFrame) -> tuple[int, int]:
    """Nilai cadangan dan stok disarankan dalam rupiah, dari harga yang membentuk prediksi sales."""
    pred_qty = shown["pred_qty"].astype(float)
    pred_sales = shown["pred_sales"].astype(float)
    price = pd.Series(0.0, index=shown.index)
    positive = pred_qty > 0
    price.loc[positive] = pred_sales.loc[positive] / pred_qty.loc[positive]
    if (~positive).any() and "sales_total" in shown.columns and "qty_total" in shown.columns:
        qty_total = shown["qty_total"].astype(float).replace(0, np.nan)
        price.loc[~positive] = (
            shown.loc[~positive, "sales_total"].astype(float) / qty_total.loc[~positive]
        ).fillna(0)
    buffer_sales = int(round(float((shown["safety_stock"].astype(float) * price.fillna(0)).sum())))
    stok_sales = int(round(float(pred_sales.sum()))) + buffer_sales
    return buffer_sales, stok_sales


def _impact_from(shown: pd.DataFrame, stock: pd.DataFrame) -> dict[str, int | float]:
    indexed = stock.set_index("item_key")
    raw = indexed.reindex(shown["item_key"])["safety_stock"].fillna(0).astype(float)
    pred_qty = int(shown["pred_qty"].sum())
    buffer = int(shown["safety_stock"].sum())
    stok = int(shown["stok_disarankan"].sum())
    buffer_sales, stok_sales = _money_from_units(shown)
    return {
        "items": int(len(shown)),
        "demand_qty": pred_qty,
        "buffer": buffer,
        "buffer_raw": float(raw.sum()),
        "pred_qty": pred_qty,
        "pred_sales": int(shown["pred_sales"].sum()),
        "stok": stok,
        "buffer_sales": buffer_sales,
        "stok_sales": stok_sales,
    }


def safety_view(analysis: dict, percent: int, metric: str) -> tuple[pd.DataFrame | None, dict | None]:
    """Prediksi 50 item terlaris pada satu persentase safety stock."""
    combined = analysis.get("combined")
    orders = analysis.get("orders")
    history = analysis.get("history")
    if (
        not isinstance(combined, pd.DataFrame)
        or not isinstance(orders, pd.DataFrame)
        or not isinstance(history, pd.DataFrame)
        or combined.empty
        or orders.empty
        or history.empty
    ):
        return None, None
    period = analysis["period"]
    last_period = history["period_start"].max()
    stock = _stock_for(analysis, percent)
    shown = top_bestsellers(orders, combined, stock, history, metric, last_period, period)
    if shown.empty:
        return stock, None
    current = _impact_from(shown, stock)
    suggested = SUGGESTED_SERVICE[period]
    if int(percent) == int(suggested):
        baseline = current
    else:
        base_stock = _stock_for(analysis, suggested)
        base_shown = top_bestsellers(orders, combined, base_stock, history, metric, last_period, period)
        baseline = _impact_from(base_shown, base_stock)
    current["base_buffer"] = baseline["buffer"]
    current["base_qty"] = baseline["pred_qty"]
    current["base_sales"] = baseline["pred_sales"]
    current["base_stok"] = baseline["stok"]
    current["base_buffer_sales"] = baseline["buffer_sales"]
    current["base_stok_sales"] = baseline["stok_sales"]
    return stock, current


def _bar_label_style(values: pd.Series, peak: float) -> tuple[list[str], list[str]]:
    """Angka di luar batang, satu warna gelap, supaya tidak ada teks putih dan hitam bercampur."""
    del peak
    count = len(values)
    positions = ["outside"] * count
    colors = ["#1f2937"] * count
    return positions, colors


def _bar_text_size(count: int) -> int:
    if count <= 2:
        return 14
    if count <= 12:
        return 13
    return 11


def _bar_texts(values: pd.Series, *, money: bool) -> tuple[list[str], list[str]]:
    """Setiap batang menampilkan angkanya, termasuk sales pada kolom yang pendek."""
    display: list[str] = []
    hover: list[str] = []
    for value in values:
        number = float(value)
        label = format_idr(number) if money else format_number(number, 0)
        hover.append(label)
        display.append("" if money and number < 0 else label)
    return display, hover


def _label_placement(count: int, *, money: bool, orientation: str = "v") -> dict:
    """Sales horizontal berada di dalam batang. QTY tetap di luar batang, satu warna gelap."""
    size = _bar_text_size(count)
    if money and orientation == "h":
        return dict(
            textposition="inside",
            textfont=dict(size=size, color="#1f2937"),
            textangle=0,
            insidetextanchor="end",
            constraintext="none",
            cliponaxis=False,
        )
    return dict(
        textposition="outside",
        textfont=dict(size=size, color="#1f2937"),
        textangle=0,
        insidetextanchor="end",
        constraintext="none",
        cliponaxis=False,
    )


def _place_sales_labels(fig: go.Figure, labels, amounts, texts) -> None:
    """Batang tinggi: angka turun dari ujung atas ke dalam kolom. Batang pendek: angka naik dari ujung batang."""
    series = pd.Series(list(amounts), dtype=float)
    peak = float(series.max() or 1)
    size = _bar_text_size(len(list(labels)))
    for label, amount, text in zip(labels, amounts, texts):
        if not text:
            continue
        value = float(amount)
        above = value < peak * 0.42
        fig.add_annotation(
            x=label,
            y=value,
            text=text,
            textangle=-90,
            showarrow=False,
            xanchor="center",
            yanchor="bottom" if above else "top",
            yshift=8 if above else -3,
            font=dict(size=size, color="#1f2937"),
        )


def day_tick_label(stamp) -> str:
    """Tanggal lurus: angka di atas, bulan di bawah, supaya tidak memotong label sebelah."""
    moment = pd.Timestamp(stamp)
    return f"{int(moment.day)}<br>{ID_MONTHS[int(moment.month) - 1][:3]}"


def apply_straight_dates(fig: go.Figure, labels: list[str]) -> None:
    """Sumbu tanggal selalu lurus dan sejajar dengan batang."""
    count = len(labels)
    step = 1 if count <= 40 else max(1, int(np.ceil(count / 31)))
    indexes = list(range(0, count, step))
    if indexes and indexes[-1] != count - 1:
        indexes.append(count - 1)
    chosen = [labels[index] for index in indexes] if indexes else []
    fig.update_xaxes(
        tickmode="array",
        tickvals=chosen,
        ticktext=chosen,
        tickangle=0,
        tickfont=dict(size=11 if count <= 20 else 10, color="#334155"),
        automargin=True,
    )


def _axis_label_margin(labels: list[str]) -> int:
    longest = 0
    for label in labels:
        for line in str(label).split("<br>"):
            longest = max(longest, len(line))
    return int(min(460, max(180, longest * 7.2 + 28)))


def item_qty_chart(view: pd.DataFrame, scope_label: str) -> go.Figure:
    plot = view.sort_values(["qty_total", "pred_qty"], ascending=[True, True])
    full_labels = [
        product_identity(rank, sku, name, variation)
        for rank, sku, name, variation in zip(
            plot["peringkat"], plot["sku"], plot["product_name"], plot["variasi_tampil"]
        )
    ]
    labels = [
        chart_axis_label(rank, sku, name, variation, width=52, max_lines=6)
        for rank, sku, name, variation in zip(
            plot["peringkat"], plot["sku"], plot["product_name"], plot["variasi_tampil"]
        )
    ]
    actual = plot["qty_total"].astype(float)
    predicted = plot["pred_qty"].astype(float)
    placement = _label_placement(len(plot), money=False, orientation="h")
    actual_text, _actual_hover = _bar_texts(actual, money=False)
    pred_text, _pred_hover = _bar_texts(predicted, money=False)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="Actual",
            x=actual,
            y=labels,
            orientation="h",
            text=actual_text,
            marker_color="#4C78A8",
            customdata=full_labels,
            hovertemplate="%{customdata}<br>Actual: %{text}<extra></extra>",
            **placement,
        )
    )
    fig.add_trace(
        go.Bar(
            name="Prediksi",
            x=predicted,
            y=labels,
            orientation="h",
            text=pred_text,
            marker_color="#F58518",
            customdata=full_labels,
            hovertemplate="%{customdata}<br>Prediksi: %{text}<extra></extra>",
            **placement,
        )
    )
    peak = float(max(actual.max() if len(actual) else 1, predicted.max() if len(predicted) else 1, 1))
    line_count = sum(label.count("<br>") + 1 for label in labels)
    fig.update_layout(
        barmode="group",
        bargap=0.28,
        bargroupgap=0.08,
        title=dict(text=f"QTY actual vs prediksi ({scope_label})", font=dict(size=16)),
        xaxis_title="QTY",
        yaxis_title="",
    )
    fig.update_yaxes(automargin=True, tickfont=dict(size=12, color="#1f2937"))
    fig.update_xaxes(tickfont=dict(size=12, color="#334155"), title_font=dict(size=13))
    apply_integer_axis(fig, "x", peak, pad=1.45)
    return polish_chart(
        fig,
        height=max(560, 26 * line_count + 28 * len(labels)),
        margin_left=_axis_label_margin(labels),
        margin_bottom=48,
    )


def item_sales_chart(view: pd.DataFrame, scope_label: str) -> go.Figure:
    """Sales dalam rupiah dan stok prediksi dalam unit. Tiap produk punya skala sendiri."""
    plot = view.sort_values(["sales_total", "pred_sales"], ascending=[True, True])
    full_labels = [
        product_identity(rank, sku, name, variation)
        for rank, sku, name, variation in zip(
            plot["peringkat"], plot["sku"], plot["product_name"], plot["variasi_tampil"]
        )
    ]
    labels = [
        chart_axis_label(rank, sku, name, variation, width=52, max_lines=6)
        for rank, sku, name, variation in zip(
            plot["peringkat"], plot["sku"], plot["product_name"], plot["variasi_tampil"]
        )
    ]
    actual = plot["sales_total"].astype(float)
    predicted = plot["pred_sales"].astype(float)
    stock_qty = plot["stok_disarankan"].astype(float)
    sales_peak = pd.concat([actual, predicted], axis=1).max(axis=1).replace(0, np.nan)
    qty_peak = pd.concat(
        [plot["qty_total"].astype(float), plot["pred_qty"].astype(float), stock_qty],
        axis=1,
    ).max(axis=1).replace(0, np.nan)
    actual_x = (actual / sales_peak).fillna(0.0)
    pred_x = (predicted / sales_peak).fillna(0.0)
    stock_x = (stock_qty / qty_peak).fillna(0.0)
    actual_text, _actual_hover = _bar_texts(actual, money=True)
    pred_text, _pred_hover = _bar_texts(predicted, money=True)
    stock_text = [f"{format_number(value, 0)} unit" for value in stock_qty]
    size = _bar_text_size(len(plot))
    placement = dict(
        textposition="outside",
        textfont=dict(size=size, color="#1f2937"),
        textangle=0,
        cliponaxis=False,
        constraintext="none",
    )
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="Sales actual",
            x=actual_x,
            y=labels,
            orientation="h",
            text=actual_text,
            marker_color="#4C78A8",
            customdata=np.column_stack([full_labels, _actual_hover]),
            hovertemplate="%{customdata[0]}<br>Sales actual: %{customdata[1]}<extra></extra>",
            **placement,
        )
    )
    fig.add_trace(
        go.Bar(
            name="Prediksi sales",
            x=pred_x,
            y=labels,
            orientation="h",
            text=pred_text,
            marker_color="#F58518",
            customdata=np.column_stack([full_labels, _pred_hover]),
            hovertemplate="%{customdata[0]}<br>Prediksi sales: %{customdata[1]}<extra></extra>",
            **placement,
        )
    )
    fig.add_trace(
        go.Bar(
            name="Stok prediksi (unit)",
            x=stock_x,
            y=labels,
            orientation="h",
            text=stock_text,
            marker_color="#059669",
            customdata=np.column_stack([full_labels, stock_text]),
            hovertemplate="%{customdata[0]}<br>Stok prediksi: %{customdata[1]}<extra></extra>",
            **placement,
        )
    )
    line_count = sum(label.count("<br>") + 1 for label in labels)
    fig.update_layout(
        barmode="group",
        bargap=0.22,
        bargroupgap=0.05,
        title=dict(
            text=f"Sales dan stok prediksi, skala per produk ({scope_label})",
            font=dict(size=16),
        ),
        xaxis_title="Skala per produk. Angka pada batang adalah nilai asli.",
        yaxis_title="",
    )
    fig.update_yaxes(automargin=True, tickfont=dict(size=12, color="#1f2937"))
    fig.update_xaxes(
        range=[0, 2.35],
        showticklabels=False,
        showgrid=False,
        title_font=dict(size=13, color="#334155"),
    )
    return polish_chart(
        fig,
        height=max(720, 38 * line_count + 46 * len(labels)),
        margin_left=_axis_label_margin(labels),
        margin_right=150,
        margin_bottom=48,
    )


def _stock_sales(view: pd.DataFrame) -> pd.Series:
    """Nilai stok disarankan dalam rupiah, dari harga yang membentuk prediksi sales."""
    pred_qty = view["pred_qty"].astype(float)
    pred_sales = view["pred_sales"].astype(float)
    price = pd.Series(0.0, index=view.index, dtype=float)
    positive = pred_qty > 0
    price.loc[positive] = pred_sales.loc[positive] / pred_qty.loc[positive]
    if bool((~positive).any()) and "sales_total" in view.columns and "qty_total" in view.columns:
        qty_total = view["qty_total"].astype(float).replace(0, np.nan)
        price.loc[~positive] = (
            view.loc[~positive, "sales_total"].astype(float) / qty_total.loc[~positive]
        ).fillna(0)
    return view["stok_disarankan"].astype(float) * price.fillna(0)


def sales_qty_chart(
    labels: list[str],
    sales: np.ndarray,
    qty: np.ndarray,
    title: str,
) -> go.Figure:
    """Batang sales volume dan garis QTY pada sumbu kanan."""
    sales_series = np.asarray(sales, dtype=float)
    qty_series = np.asarray(qty, dtype=float)
    fig = go.Figure()
    if len(labels) == 0:
        fig.update_layout(title=title)
        return polish_chart(fig, height=420)
    _sales_text, sales_hover = _bar_texts(pd.Series(sales_series), money=True)
    qty_hover = [format_number(value, 0) for value in qty_series]
    fig.add_trace(
        go.Bar(
            name="Sales volume",
            x=list(labels),
            y=sales_series,
            marker_color="#F58518",
            customdata=sales_hover,
            hovertemplate="%{x}<br>Sales: %{customdata}<extra></extra>",
        )
    )
    show_qty_text = 0 < len(labels) <= 16
    fig.add_trace(
        go.Scatter(
            name="QTY",
            x=list(labels),
            y=qty_series,
            mode="lines+markers+text" if show_qty_text else "lines+markers",
            yaxis="y2",
            text=qty_hover if show_qty_text else None,
            textposition="top center",
            textfont=dict(size=13, color="#1e3a8a"),
            marker=dict(size=11, color="#4C78A8", line=dict(width=1, color="#ffffff")),
            line=dict(color="#4C78A8", width=3),
            customdata=qty_hover,
            hovertemplate="%{x}<br>QTY: %{customdata}<extra></extra>",
            cliponaxis=False,
        )
    )
    if any(_sales_text):
        _place_sales_labels(fig, labels, sales_series, _sales_text)
    sales_peak = float(np.max(sales_series) if len(sales_series) else 1) or 1
    qty_peak = float(np.max(qty_series) if len(qty_series) else 1) or 1
    if qty_peak <= 12:
        qty_step = 1.0
    else:
        qty_step = _tick_step(qty_peak, 4)
    qty_ticks: list[float] = []
    cursor = 0.0
    while cursor <= qty_peak + 1e-6 and len(qty_ticks) < 7:
        qty_ticks.append(cursor)
        cursor += qty_step
    if not qty_ticks or qty_ticks[-1] < qty_peak:
        qty_ticks.append(float(np.ceil(qty_peak)))
    qty_upper = max(qty_peak * 1.35, qty_ticks[-1] if qty_ticks else qty_peak)
    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        yaxis_title="Sales volume (Rp)",
        yaxis2=dict(
            title=dict(text="QTY", font=dict(size=14, color="#1e3a8a")),
            overlaying="y",
            side="right",
            showgrid=False,
            range=[0, qty_upper],
            tickmode="array",
            tickvals=qty_ticks,
            ticktext=[format_number(value, 0) for value in qty_ticks],
            tickfont=dict(size=14, color="#1e3a8a"),
            automargin=True,
        ),
        xaxis_title="Tanggal",
        bargap=0.28,
        legend=dict(orientation="h", yanchor="bottom", y=1.08, x=0),
    )
    apply_straight_dates(fig, labels)
    apply_integer_axis(fig, "y", sales_peak, pad=1.22)
    return polish_chart(fig, height=520, margin_top=108, margin_bottom=78, margin_right=72)


def sales_drop_note(
    actual_sales: float,
    pred_sales: float,
    actual_qty: float,
    pred_qty: float,
    *,
    scope: str,
) -> str:
    """Analisa singkat bila prediksi sales berada di bawah sales yang sudah terjadi."""
    if actual_sales <= 0 or pred_sales + 0.5 >= actual_sales:
        return ""
    gap = actual_sales - pred_sales
    percent = gap / actual_sales * 100
    sentences = [
        f"Prediksi sales {scope} lebih rendah {format_idr(gap)} ({format_number(percent, 1)}%) dari sales actual.",
        "Sales prediksi = prediksi QTY × harga jual. Penurunan sales mengikuti qty dan harga, bukan model omzet terpisah.",
    ]
    if actual_qty > 0 and pred_qty + 0.5 < actual_qty:
        sentences.append(
            f"Prediksi QTY {format_qty(pred_qty)} berada di bawah QTY actual {format_qty(actual_qty)}. "
            "Level 28 hari terakhir lebih sepi daripada periode yang ditampilkan."
        )
    elif actual_qty > 0:
        sentences.append(
            "Prediksi QTY tidak lebih rendah dari QTY actual. Penurunan sales datang dari harga jual pada campuran qty itu."
        )
    sentences.append("Stok yang disiapkan tetap prediksi QTY ditambah safety stock, pada tabel.")
    return " ".join(sentences)


def daily_actual_chart(scope_orders: pd.DataFrame, scope_label: str, value: str) -> go.Figure:
    del scope_label
    money = value == "sales"
    title = "Sales volume actual per hari" if money else "QTY actual per hari"
    axis = "Sales volume (Rp)" if money else "QTY"
    fig = go.Figure()
    if scope_orders.empty:
        fig.update_layout(title=title)
        return polish_chart(fig, height=420)
    days = scope_orders["order_time"].dt.floor("D")
    grouped = scope_orders.groupby(days).agg(qty=("qty", "sum"), sales=("sales", "sum"))
    index = pd.date_range(grouped.index.min(), grouped.index.max(), freq="D")
    grouped = grouped.reindex(index, fill_value=0)
    labels = [day_tick_label(stamp) for stamp in grouped.index]
    amounts = grouped[value]
    display, hover = _bar_texts(amounts, money=money)
    fig.add_trace(
        go.Bar(
            x=labels,
            y=amounts,
            marker_color="#F58518" if money else "#4C78A8",
            text=None if money else display,
            customdata=hover,
            hovertemplate="%{x}<br>%{customdata}<extra></extra>",
            **(_label_placement(len(labels), money=False, orientation="v") if not money else {}),
        )
    )
    if money:
        _place_sales_labels(fig, labels, amounts, display)
    peak = float(amounts.max() or 1)
    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        yaxis_title=axis,
        xaxis_title="Tanggal",
        bargap=0.28,
    )
    apply_straight_dates(fig, labels)
    apply_integer_axis(fig, "y", peak, pad=1.28 if money else 1.35)
    return polish_chart(fig, height=480, margin_top=96 if money else 72, margin_bottom=78)


def comparison_chart(title: str, axis_title: str, values: list[float], *, money: bool = False) -> go.Figure:
    """Dua batang Actual dan Prediksi. Angka selalu di dalam batang."""
    series = pd.Series(values, dtype=float)
    peak = float(series.max() or 1)
    positions, colors = _bar_label_style(series, peak)
    texts = [format_idr(value) if money else format_number(value, 0) for value in values]
    fig = go.Figure(
        go.Bar(
            x=["Actual", "Prediksi"],
            y=values,
            text=texts,
            textposition=positions,
            insidetextanchor="end",
            constraintext="none",
            textfont=dict(size=12 if money else 14, color=colors),
            cliponaxis=False,
            marker_color=["#4C78A8", "#F58518"],
            hovertemplate="%{x}<br>%{text}<extra></extra>",
        )
    )
    fig.update_layout(title=dict(text=title, font=dict(size=16)), yaxis_title=axis_title)
    apply_integer_axis(fig, "y", peak, pad=1.4)
    return polish_chart(fig, height=360)


def timeline_chart(labels: list[str], values: np.ndarray, title: str, axis: str, *, money: bool = False) -> go.Figure:
    """Grafik batang per tanggal atau per bulan."""
    series = pd.Series(np.asarray(values, dtype=float))
    fig = go.Figure()
    if len(series) == 0:
        fig.update_layout(title=title)
        return polish_chart(fig, height=420)
    peak = float(series.max() or 1)
    display, hover = _bar_texts(series, money=money)
    fig.add_trace(
        go.Bar(
            x=list(labels),
            y=series,
            marker_color="#F58518",
            text=None if money else display,
            customdata=hover,
            hovertemplate="%{x}<br>%{customdata}<extra></extra>",
            **(_label_placement(len(labels), money=False, orientation="v") if not money else {}),
        )
    )
    if money:
        _place_sales_labels(fig, labels, series, display)
    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        yaxis_title=axis,
        xaxis_title="Tanggal",
        bargap=0.28,
    )
    apply_straight_dates(fig, labels)
    apply_integer_axis(fig, "y", peak, pad=1.28 if money else 1.35)
    return polish_chart(fig, height=480, margin_top=96 if money else 72, margin_bottom=78)


def sku_daily_qty(item_orders: pd.DataFrame) -> tuple[np.ndarray, pd.Timestamp]:
    if item_orders.empty or "order_time" not in item_orders.columns:
        return np.zeros(0, dtype=float), pd.Timestamp(date.today())
    days = pd.to_datetime(item_orders["order_time"]).dt.floor("D")
    grouped = item_orders.groupby(days)["qty"].sum().sort_index()
    index = pd.date_range(grouped.index.min(), grouped.index.max(), freq="D")
    series = grouped.reindex(index, fill_value=0.0).to_numpy(dtype=float)
    return series, pd.Timestamp(index[0])


def prediction_frame(
    chosen: pd.Series,
    item_orders: pd.DataFrame,
    weekday: np.ndarray,
    start: date,
    end: date,
) -> pd.DataFrame:
    """Prediksi QTY dan sales pada tiap tanggal kalender. Jumlahnya sama dengan prediksi SKU."""
    dates = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
    daily, series_start = sku_daily_qty(item_orders)
    target_qty = float(chosen["pred_qty"])
    target_sales = float(chosen["pred_sales"])
    qty = forecast_calendar(daily, series_start, dates, weekday, target_qty)
    if target_qty > 0:
        sales = qty * (target_sales / target_qty)
    else:
        sales = np.zeros(len(dates), dtype=float)
    return pd.DataFrame({"date": dates, "qty": qty, "sales": sales})


def prediction_interval_options(period: str) -> list[tuple[str, str]]:
    """Interval yang muat di grafik. Bulan tetap per tanggal kalender."""
    if period == "kuartal":
        return [
            ("minggu", "Per minggu (disarankan)"),
            ("2minggu", "Per 2 minggu"),
            ("bulan", "Per bulan"),
            ("hari", "Per tanggal"),
        ]
    if period == "semester":
        return [
            ("2minggu", "Per 2 minggu (disarankan)"),
            ("minggu", "Per minggu"),
            ("bulan", "Per bulan"),
            ("hari", "Per tanggal"),
        ]
    if period == "tahun":
        return [
            ("bulan", "Per bulan (disarankan)"),
            ("2minggu", "Per 2 minggu"),
            ("minggu", "Per minggu"),
            ("hari", "Per tanggal"),
        ]
    return [("hari", "Per tanggal")]


def _interval_span_label(start, end) -> str:
    opening = pd.Timestamp(start)
    closing = pd.Timestamp(end)
    if opening.normalize() == closing.normalize():
        return day_tick_label(opening)
    if opening.month == closing.month and opening.year == closing.year:
        return f"{int(opening.day)}–{int(closing.day)}<br>{ID_MONTHS[opening.month - 1][:3]}"
    return (
        f"{int(opening.day)} {ID_MONTHS[opening.month - 1][:3]}"
        f"<br>{int(closing.day)} {ID_MONTHS[closing.month - 1][:3]}"
    )


def bucket_prediction(frame: pd.DataFrame, grain: str) -> tuple[list[str], np.ndarray, np.ndarray]:
    if frame.empty:
        return [], np.zeros(0), np.zeros(0)
    if grain == "hari":
        labels = [day_tick_label(stamp) for stamp in frame["date"]]
        return labels, frame["qty"].to_numpy(dtype=float), frame["sales"].to_numpy(dtype=float)
    work = frame.copy()
    if grain == "bulan":
        work["bucket"] = pd.to_datetime(work["date"]).dt.to_period("M")
        grouped = work.groupby("bucket", as_index=False).agg(
            qty=("qty", "sum"),
            sales=("sales", "sum"),
            start=("date", "min"),
        )
        labels = [f"{ID_MONTHS[stamp.month - 1][:3]} {stamp.year}" for stamp in grouped["start"]]
        return labels, grouped["qty"].to_numpy(dtype=float), grouped["sales"].to_numpy(dtype=float)
    step = 14 if grain == "2minggu" else 7
    origin = pd.Timestamp(work["date"].iloc[0]).normalize()
    elapsed = (pd.to_datetime(work["date"]).dt.normalize() - origin).dt.days
    work["bucket"] = elapsed // step
    grouped = work.groupby("bucket", as_index=False).agg(
        qty=("qty", "sum"),
        sales=("sales", "sum"),
        start=("date", "min"),
        end=("date", "max"),
    )
    labels = [_interval_span_label(start, end) for start, end in zip(grouped["start"], grouped["end"])]
    return labels, grouped["qty"].to_numpy(dtype=float), grouped["sales"].to_numpy(dtype=float)


def ranked_horizontal_chart(view: pd.DataFrame, value_col: str, title: str) -> go.Figure:
    """Grafik horizontal dengan nomor peringkat pada nama produk dan angka di dalam batang."""
    plot = view.sort_values(value_col, ascending=True)
    full_labels = [
        product_identity(rank, sku, name, variation)
        for rank, sku, name, variation in zip(
            plot["peringkat"], plot["sku"], plot["product_name"], plot["variasi_tampil"]
        )
    ]
    many = len(plot) > 40
    labels = [
        chart_axis_label(
            rank,
            sku,
            name,
            variation,
            width=40 if many else 52,
            max_lines=2 if many else 6,
        )
        for rank, sku, name, variation in zip(
            plot["peringkat"], plot["sku"], plot["product_name"], plot["variasi_tampil"]
        )
    ]
    values = plot[value_col].astype(float)
    peak = float(values.max() or 1)
    money = value_col == "pred_sales"
    display, hover = _bar_texts(values, money=money)
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            text=display,
            marker_color="#F58518",
            customdata=list(zip(full_labels, hover)),
            hovertemplate="%{customdata[0]}<br>%{customdata[1]}<extra></extra>",
            **_label_placement(len(plot), money=money, orientation="h"),
        )
    )
    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        xaxis_title="Sales volume (Rp)" if money else "QTY",
        yaxis_title="",
    )
    fig.update_yaxes(automargin=True, tickfont=dict(size=12, color="#1f2937"))
    apply_integer_axis(fig, "x", peak, pad=1.08 if money else 1.45)
    line_count = sum(label.count("<br>") + 1 for label in labels)
    return polish_chart(
        fig,
        height=max(420, 24 * line_count + 22 * len(labels)),
        margin_left=_axis_label_margin(labels),
        margin_bottom=48,
    )


def numeric_column_config(frame: pd.DataFrame) -> dict:
    """Angka tetap numerik supaya klik header mengurutkan nilai, bukan teks."""
    config = {}
    for column in frame.columns:
        if column in {"Produk", "Variasi", "Referensi SKU", "Item"}:
            continue
        if not pd.api.types.is_numeric_dtype(frame[column]):
            continue
        config[column] = st.column_config.NumberColumn(column, format="localized", step=1)
    return config


def scroll_table(frame: pd.DataFrame, *, max_height: int | None = 680, format_numbers: bool = True) -> None:
    """Tabel dengan batang geser yang tetap terlihat, ke kanan, kiri, atas, dan bawah."""
    if frame.empty:
        st.write("Tidak ada data.")
        return
    numeric = {
        column
        for column in frame.columns
        if format_numbers and pd.api.types.is_numeric_dtype(frame[column])
    }
    header = "".join(
        f"<th class='{'num' if column in numeric else ''}'>{html.escape(str(column))}</th>"
        for column in frame.columns
    )
    body: list[str] = []
    for _, row in frame.iterrows():
        cells: list[str] = []
        for column in frame.columns:
            value = row[column]
            if column in numeric and pd.notna(value):
                number = float(value)
                decimals = 0 if abs(number - round(number)) < 0.05 else 1
                text = format_number(number, decimals)
                kind = "num"
            else:
                text = "" if pd.isna(value) else html.escape(str(value))
                kind = ""
            cells.append(f"<td class='{kind}'>{text}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    height_style = "" if max_height is None else f"max-height:{int(max_height)}px;"
    box = (
        "<div class='sheet-scroll' "
        f"style='{height_style}width:100%;max-width:100%;overflow:scroll;display:block;'>"
    )
    st.markdown(
        box + f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def table_column_config(frame: pd.DataFrame, *, roomy: bool = False) -> dict:
    """Kolom nama cukup lebar supaya nama produk dan SKU tidak terpotong."""
    config = {}
    for column in frame.columns:
        if column in {"Produk", "Variasi", "Referensi SKU", "Item"}:
            continue
        if not pd.api.types.is_numeric_dtype(frame[column]):
            continue
        if roomy:
            width = 120 if column == "Peringkat" else 200
            config[column] = st.column_config.NumberColumn(column, format="localized", step=1, width=width)
        else:
            config[column] = st.column_config.NumberColumn(column, format="localized", step=1)
    widths = {
        "Produk": 780 if roomy else 640,
        "Variasi": 320 if roomy else 260,
        "Referensi SKU": 260 if roomy else 220,
        "Item": 780 if roomy else 640,
        "Alasan batal": 460,
        "Alasan retur": 280,
        "Alasan pembatalan": 520,
        "Status batal": 180,
        "Status pesanan": 220,
        "Nama akun pembeli": 240,
        "Nama produk": 420,
        "No. Pesanan": 220,
        "SKU": 180,
        "Tanggal pembelian": 160,
        "Kontribusi": 140,
        "File terakhir": 360,
        "Perubahan": 520,
        "Tanggal perubahan": 180,
    }
    for column, width in widths.items():
        if column in frame.columns:
            config[column] = st.column_config.TextColumn(column, width=width)
    return config


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(stamp):
        return None
    return stamp.date()


def filter_resume_orders(
    orders: pd.DataFrame,
    *,
    show_controls: bool,
    prefix: str = "resume",
    caption: str | None = None,
) -> tuple[pd.DataFrame, str]:
    """Potong angka penjualan menurut tahun, bulan, dan tanggal."""
    if orders is None or orders.empty or "order_time" not in orders.columns:
        return orders, ""
    times = pd.to_datetime(orders["order_time"], errors="coerce")
    work = orders.loc[times.notna()].copy()
    if work.empty:
        return orders.iloc[0:0].copy(), ""
    work["_month"] = times.loc[times.notna()].dt.to_period("M").astype(str)
    months = sorted(work["_month"].unique())
    years = sorted({key[:4] for key in months})
    year_state = f"{prefix}_year"
    months_state = f"{prefix}_months"
    start_state = f"{prefix}_start"
    end_state = f"{prefix}_end"
    year_widget = f"{prefix}-year"
    start_widget = f"{prefix}-start"
    end_widget = f"{prefix}-end"
    saved_year = str(st.session_state.get(year_state) or "")
    if saved_year not in years:
        saved_year = years[-1]
    year_months = [key for key in months if key.startswith(saved_year)]
    saved_months = [key for key in (st.session_state.get(months_state) or []) if key in year_months]
    if not saved_months and year_months:
        saved_months = [year_months[-1]]

    if show_controls:
        st.markdown("**Periode penjualan**")
        st.caption(
            caption
            or (
                "Tahun, bulan, dan tanggal ini hanya memotong angka penjualan di ringkasan. "
                "Prediksi tetap dihitung dari bulan yang dicentang di input dan dari periode prediksi. "
                "Perubahan di input dihitung lagi lewat Jalankan analisis."
            )
        )
        if st.session_state.get(year_widget) not in years:
            st.session_state[year_widget] = saved_year
        year = st.selectbox(
            "Tahun penjualan",
            years,
            index=years.index(saved_year),
            key=year_widget,
        )
        year_months = [key for key in months if key.startswith(str(year))]
        saved_months = [key for key in (st.session_state.get(months_state) or saved_months) if key in year_months]
        if not saved_months and year_months:
            saved_months = [year_months[-1]]
        st.markdown("**Bulan penjualan**")
        selected: list[str] = []
        for start in range(0, len(year_months), 4):
            box_columns = st.columns(4)
            for offset, key in enumerate(year_months[start : start + 4]):
                widget = f"{prefix}-month-{key}"
                if widget not in st.session_state:
                    st.session_state[widget] = key in saved_months
                with box_columns[offset]:
                    if st.checkbox(month_label(key), key=widget):
                        selected.append(key)
        if not selected:
            st.warning("Centang minimal satu bulan penjualan.")
        span = work.loc[work["_month"].isin(selected), "order_time"] if selected else work.iloc[0:0]
        if span.empty:
            span_min = _as_date(work["order_time"].min()) or date.today()
            span_max = _as_date(work["order_time"].max()) or span_min
        else:
            span_min = _as_date(span.min()) or date.today()
            span_max = _as_date(span.max()) or span_min
        if span_max < span_min:
            span_min, span_max = span_max, span_min
        for widget, fallback in ((start_widget, span_min), (end_widget, span_max)):
            current = _as_date(st.session_state.get(widget))
            if current is None or current < span_min or current > span_max:
                if widget in st.session_state:
                    st.session_state[widget] = fallback
        date_col, date_col_end = st.columns(2)
        start_kwargs = {"min_value": span_min, "max_value": span_max, "key": start_widget}
        end_kwargs = {"min_value": span_min, "max_value": span_max, "key": end_widget}
        if start_widget not in st.session_state:
            start_kwargs["value"] = span_min
        if end_widget not in st.session_state:
            end_kwargs["value"] = span_max
        start = _as_date(date_col.date_input("Tanggal mulai", **start_kwargs)) or span_min
        end = _as_date(date_col_end.date_input("Tanggal selesai", **end_kwargs)) or span_max
        if start > end:
            start, end = end, start
        st.session_state[year_state] = str(year)
        st.session_state[months_state] = selected
        st.session_state[start_state] = start
        st.session_state[end_state] = end
    else:
        selected = saved_months
        span = work.loc[work["_month"].isin(selected), "order_time"] if selected else work.iloc[0:0]
        span_min = _as_date(span.min()) if not span.empty else None
        span_max = _as_date(span.max()) if not span.empty else None
        start = _as_date(st.session_state.get(start_state)) or span_min
        end = _as_date(st.session_state.get(end_state)) or span_max
        if start is None or end is None:
            start, end = span_min, span_max
        elif span_min and span_max:
            start = min(max(start, span_min), span_max)
            end = min(max(end, span_min), span_max)
        if start and end and start > end:
            start, end = end, start

    if not selected or start is None or end is None:
        label = "tidak ada tanggal yang dipilih"
        return work.iloc[0:0].drop(columns=["_month"]), label
    days = pd.to_datetime(work["order_time"]).dt.normalize()
    mask = work["_month"].isin(selected) & days.ge(pd.Timestamp(start)) & days.le(pd.Timestamp(end))
    filtered = work.loc[mask].drop(columns=["_month"]).reset_index(drop=True)
    names = [month_label(key) for key in selected]
    full_span = not span.empty and start == span_min and end == span_max
    if full_span and len(names) == 1:
        label = names[0]
    elif full_span:
        label = ", ".join(names)
    else:
        label = f"{format_id_date(start)} – {format_id_date(end)}"
    return filtered, label


st.title("Prediksi Stok & Item Terlaris Shopee")
st.caption(
    "Unggah laporan transaksi Shopee, pilih data input dan periode prediksi, lalu jalankan analisis. "
    "Angka penjualan di ringkasan mengikuti tahun, bulan, dan tanggal yang dipilih di sana. "
    "Retur dan batal diatur dari centang di header ringkasan."
)

with st.sidebar:
    st.header("Input")
    st.markdown("<div class='side-section'>Laporan</div>", unsafe_allow_html=True)
    uploaded = st.file_uploader(
        "Laporan Shopee",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
    st.markdown(
        "<div class='upload-note'>CSV, XLSX, atau XLS. Beberapa file digabung. "
        "Maksimal 50 lampiran, total 1 GB.</div>",
        unsafe_allow_html=True,
    )
    files = list(uploaded or [])
    load_error = None
    if len(files) > MAX_FILES:
        load_error = f"Maksimal {MAX_FILES} file. Yang dipilih {len(files)} file."
        files = []
    elif files and sum(int(getattr(item, "size", 0) or 0) for item in files) > MAX_UPLOAD_BYTES:
        load_error = "Total ukuran file melebihi 1 GB."
        files = []

    try:
        orders_raw, source_raw = load_orders(files)
    except ValueError as exc:
        orders_raw = pd.DataFrame()
        source_raw = pd.DataFrame()
        load_error = str(exc)

    if files:
        source_key = "|".join(f"{item.name}:{getattr(item, 'size', 0)}" for item in files)
    else:
        source_key = "empty"
    if load_error:
        st.error(load_error)
    imported_keys: list[str] = []
    if (
        files
        and not load_error
        and isinstance(source_raw, pd.DataFrame)
        and not source_raw.empty
        and source_key != st.session_state.get("saved_source_key")
    ):
        imported_keys, import_notes = store_upload(
            source_raw,
            orders_raw,
            [getattr(item, "name", "Lampiran") for item in files],
        )
        st.session_state["saved_source_key"] = source_key
        st.session_state["last_import_notes"] = import_notes
    saved_months = list_months()
    if saved_months:
        years = []
        for item in saved_months:
            year_name = year_of(item["key"])
            if year_name not in years:
                years.append(year_name)
        years = sorted(years)
        if imported_keys:
            st.session_state["library-year"] = year_of(imported_keys[0])
            for key in imported_keys:
                st.session_state[f"library-month-{key}"] = True
        if st.session_state.get("library-year") not in years:
            st.session_state["library-year"] = years[-1]
        st.markdown("<div class='side-section'>Data tersimpan</div>", unsafe_allow_html=True)
        library_year = st.selectbox("Tahun", years, key="library-year")
        month_keys = [item["key"] for item in saved_months if year_of(item["key"]) == library_year]
        st.markdown("**Bulan**")
        selected_library = []
        for key in sorted(month_keys):
            month_widget = f"library-month-{key}"
            if month_widget not in st.session_state:
                st.session_state[month_widget] = True
            if st.checkbox(month_label(key), key=month_widget):
                selected_library.append(key)
        if selected_library:
            loaded_source, loaded_orders = cached_library_frames(
                tuple(selected_library), bundle_stamp(selected_library)
            )
            st.session_state["active-library-keys"] = tuple(selected_library)
            if not loaded_source.empty:
                source_raw = loaded_source
                orders_raw = loaded_orders
                source_key = "library:" + ",".join(selected_library)
        else:
            st.session_state["active-library-keys"] = tuple()
            source_raw = pd.DataFrame()
            orders_raw = pd.DataFrame()
            source_key = f"library:{library_year}:none"
            st.warning("Centang minimal satu bulan.")
    if (
        isinstance(source_raw, pd.DataFrame)
        and not source_raw.empty
        and (not isinstance(orders_raw, pd.DataFrame) or orders_raw.empty)
    ):
        rebuilt = clean_order_frame(source_raw)
        if not rebuilt.empty:
            orders_raw = rebuilt
    st.markdown("<div class='side-section'>Prediksi</div>", unsafe_allow_html=True)
    st.caption("Bulan yang dicentang di atas adalah data latih. Periode di bawah adalah jangka ramalan.")
    period = st.selectbox(
        "Periode prediksi",
        options=list(PERIOD_OPTIONS),
        format_func=lambda key: PERIOD_SPECS[key].label,
        index=0,
    )
    sidebar_metric = st.radio(
        "Parameter",
        options=["qty", "sales"],
        format_func=lambda key: "Quantity terjual" if key == "qty" else "Sales volume",
        horizontal=True,
        key="rank-metric",
    )
    st.caption("Parameter ini menentukan peringkat pada periode penjualan di ringkasan. Ubah input, lalu klik Jalankan analisis.")
    suggested_service = SUGGESTED_SERVICE[period]
    service = int(
        st.number_input(
            "Safety stock (%)",
            min_value=0,
            max_value=500,
            value=suggested_service,
            step=1,
            key=f"safety-stock-{period}",
        )
    )
    stored_analysis = st.session_state.get("analysis")
    safety_synced = bool(
        isinstance(stored_analysis, dict)
            and stored_analysis.get("period") == period
            and stored_analysis.get("source_key") == source_key
            and stored_analysis.get("metric", "qty") == sidebar_metric
    )
    safety_impact = None
    if safety_synced:
        refreshed_stock, safety_impact = safety_view(stored_analysis, service, sidebar_metric)
        if refreshed_stock is not None:
            stored_analysis["stock"] = refreshed_stock
            stored_analysis["service"] = service
            st.session_state["analysis"] = stored_analysis
    safety_class, safety_text = safety_analysis(
        service,
        period,
        safety_impact,
        safety_synced,
        has_result=isinstance(stored_analysis, dict),
        metric=sidebar_metric,
    )
    st.markdown(
        f"<div class='{safety_class}'><b>Suggest safety stock adalah {suggested_service}%.</b><br>{safety_text}</div>",
        unsafe_allow_html=True,
    )
    run = st.button("Jalankan analisis", type="primary", use_container_width=True)

today = date.today()
window_start, window_end, period_text = forecast_window(period, today)

if not run and "analysis" not in st.session_state:
    date_col, period_col = st.columns([1, 2.2])
    show_metric(date_col, "Tanggal hari ini", format_id_date(today))
    period_col.markdown(
        "<div class='readable-metric-label'>Periode prediksi</div>"
        f"<div class='period-name'>{PERIOD_SPECS[period].label}</div>"
        f"<div class='period-dates'>{format_id_date(window_start)} – {format_id_date(window_end)}</div>",
        unsafe_allow_html=True,
    )
    st.info("Unggah laporan Shopee (maksimal 50 file, total 1 GB), lalu klik **Jalankan analisis**.")
    st.markdown(
        """
**Yang bisa dipilih:**
- Periode prediksi: bulan, kuartal, semester, atau tahun
- Parameter: Quantity terjual atau Sales volume
- Centang Exclude return dan batal pada header Ringkasan dan Prediksi & stok, setelah analisis berjalan
- Tahun dan bulan data input untuk prediksi
- Menu Laporan: slide presentasi dari Ringkasan, Prediksi & stok, Data, dan Folder data

**Hasil:** 50 item terlaris pada periode penjualan yang dipilih, lengkap dengan prediksi QTY, sales volume, dan stok yang harus disiapkan. Prediksi dihitung dari data input dan dimulai dari tanggal hari ini.

**Kolom yang didukung (otomatis dikenali):**
- Waktu Pesanan Dibuat / Tanggal
- Nama Produk (kolom O), Nomor Referensi SKU (kolom P), Nama Variasi (kolom Q)
- Jumlah
- Total Harga atau Harga Setelah Diskon
- Status Pesanan

Acuan produk adalah Nomor Referensi SKU. Bila nama produk berbeda, yang ditampilkan adalah nama pada pesanan terakhir.
"""
    )
    st.stop()

sheet = str(st.session_state.get("active-sheet", "Ringkasan"))
exclude_return_cancel = bool(st.session_state.get("exclude_applied", False))
if "analysis" in st.session_state and not run:
    sheet = show_app_menu()
    if sheet in SUMMARY_SHEETS:
        date_col, period_col = st.columns([1, 2.2])
        show_metric(date_col, "Tanggal hari ini", format_id_date(today))
        period_col.markdown(
            "<div class='readable-metric-label'>Periode prediksi</div>"
            f"<div class='period-name'>{PERIOD_SPECS[period].label}</div>"
            f"<div class='period-dates'>{format_id_date(window_start)} – {format_id_date(window_end)}</div>",
            unsafe_allow_html=True,
        )
        if sheet != "Data":
            if "exclude-return-batal" not in st.session_state:
                st.session_state["exclude-return-batal"] = exclude_return_cancel
            exclude_return_cancel = bool(st.checkbox("Exclude return dan batal", key="exclude-return-batal"))
            st.session_state["exclude_applied"] = exclude_return_cancel
            st.caption(
                "Centang ini mengurangi pesanan batal dan unit retur pada header, "
                "Top 50, serta lembar Prediksi & stok. "
                "Lembar Data memakai centang status sendiri."
            )
    if st.session_state.pop("_menu_rerun", False):
        st.rerun()

exclude_changed = (
    "analysis" in st.session_state
    and st.session_state["analysis"].get("exclude_return_cancel", None) != exclude_return_cancel
)
filters_changed = (
    "analysis" in st.session_state
    and not run
    and not exclude_changed
    and (
        st.session_state["analysis"]["period"] != period
        or st.session_state["analysis"].get("source_key") != source_key
        or st.session_state["analysis"].get("metric", "qty") != sidebar_metric
    )
)

if run or "analysis" not in st.session_state or exclude_changed:
    if load_error:
        st.error(load_error)
        st.stop()
    if orders_raw.empty:
        st.warning("Tidak ada data. Unggah laporan Shopee terlebih dahulu.")
        st.stop()

    orders = prepare_analysis_orders(
        orders_raw,
        exclude_return_cancel=exclude_return_cancel,
    )
    history = aggregate_item_periods(orders, period)

    if history.empty:
        st.warning("Tidak ada transaksi yang bisa dianalisis pada data ini.")
        st.stop()

    base_period = "hari"
    horizon_steps = horizon_day_count(period, today)
    base_history = aggregate_item_periods(orders, base_period)
    last_bucket = period_start(orders["order_time"], period).max()
    next_label = period_label(next_period_start(last_bucket, period), period)

    with st.spinner("Membaca pola belanja harian untuk prediksi QTY..."):
        bar = st.progress(0.0, text="Prediksi dari level 28 hari terakhir")

        def on_qty(pct: float) -> None:
            bar.progress(min(pct * 0.9, 0.9), text="Prediksi dari level 28 hari terakhir")

        qty_fc = forecast_items(
            base_history,
            base_period,
            "qty",
            progress_callback=on_qty,
            steps=horizon_steps,
            next_label=period_text,
            forecast_start=pd.Timestamp(window_start),
        )
        bar.progress(0.92, text="Prediksi sales volume dari QTY × harga")
        sales_fc = forecast_revenue(
            base_history,
            qty_fc,
            base_period,
            steps=horizon_steps,
            next_label=next_label,
        )
        bar.progress(1.0, text="Selesai")

    combined = combine_forecasts(qty_fc, sales_fc)
    stock = recommend_stock(
        base_history,
        combined,
        base_period,
        service_level_z=service_z(service),
        horizon_steps=horizon_steps,
    )
    try:
        comparison = compare_daily_algorithms(base_history)
    except Exception:
        comparison = pd.DataFrame()
    board = model_leaderboard(qty_fc, pd.DataFrame())
    st.session_state["analysis"] = {
        "orders": orders,
        "history": history,
        "combined": combined,
        "stock": stock,
        "board": board,
        "comparison": comparison,
        "period": period,
        "metric": sidebar_metric,
        "source_key": source_key,
        "service": service,
        "horizon_steps": horizon_steps,
        "base_period": base_period,
        "base_history": base_history,
        "period_text": period_text,
        "exclude_return_cancel": exclude_return_cancel,
    }
    st.rerun()
else:
    stored = st.session_state["analysis"]
    orders = stored["orders"]
    history = stored["history"]
    combined = stored["combined"]
    stock = stored["stock"]
    board = stored["board"]
    comparison = stored.get("comparison", pd.DataFrame())
    period = stored["period"]
    metric = stored.get("metric", "qty")
    horizon_steps = int(stored.get("horizon_steps", 1))
    base_period = stored.get("base_period", period)
    period_text = stored.get("period_text") or forecast_window(period)[2]

if filters_changed:
    st.warning(
        "Data input, periode prediksi, atau parameter berubah. "
        "Klik **Jalankan analisis** untuk menghitung ulang. "
        "Tahun, bulan, dan tanggal penjualan di ringkasan hanya mengubah angka yang ditampilkan. "
        "Perubahan safety stock langsung menghitung ulang cadangan dan stok disarankan."
    )

show_resume = sheet in {"Ringkasan", "Prediksi & stok"}
sales_orders, resume_label = filter_resume_orders(orders, show_controls=show_resume)
if not resume_label:
    resume_label = "seluruh data input"

last_period = history["period_start"].max()
catalog = top_bestsellers(sales_orders, combined, stock, history, metric, last_period, period, top_n=None)
shown = catalog.head(TOP_N).reset_index(drop=True)
sort_name = "Quantity terjual tertinggi" if metric == "qty" else "sales volume tertinggi"

grain_note = (
    "Pada riwayat di bawah 28 hari, laju harian periode panjang mengikuti level yang sama. "
    "Bulan yang terpotong di ujung kalender lebih kecil karena harinya lebih sedikit."
)

if sheet in SUMMARY_SHEETS and sheet != "Data":
    if exclude_return_cancel:
        header_order_hint = f"{resume_label}. Tanpa pesanan batal. Unit retur sudah dikurangi"
        header_sku_hint = f"{resume_label}. SKU tanpa pesanan batal dan tanpa baris yang hanya berisi retur"
        header_sales_hint = f"{resume_label}. Total Pembayaran tanpa pesanan batal, sekali tiap No. Pesanan"
        header_qty_hint = f"{resume_label}. Jumlah dikurangi Returned quantity, tanpa pesanan batal"
    else:
        header_order_hint = f"{resume_label}. Termasuk batal dan retur"
        header_sku_hint = f"{resume_label}. Termasuk SKU pada pesanan batal dan retur"
        header_sales_hint = f"{resume_label}. Total Pembayaran termasuk batal dan retur, sekali tiap No. Pesanan"
        header_qty_hint = f"{resume_label}. Jumlah termasuk unit retur dan pesanan batal"
    if sheet == "Data":
        st.caption(
            f"Angka header memakai periode penjualan {resume_label}. "
            "Tahun, bulan, dan tanggal penjualan diatur di menu Ringkasan."
        )
    k1, k2, k3, k4 = st.columns(4)
    show_metric(k1, "Jumlah pesanan", format_number(count_orders(sales_orders), 0), hint=header_order_hint)
    show_metric(
        k2,
        "Produk / varian",
        f"{sales_orders['item_key'].nunique():,}".replace(",", ".") if not sales_orders.empty else "0",
        hint=header_sku_hint,
    )
    show_metric(k3, "Sales volume", format_idr(order_revenue(sales_orders)), hint=header_sales_hint)
    show_metric(
        k4,
        "QTY terjual",
        format_qty(float(sales_orders["qty"].sum()) if "qty" in sales_orders.columns and not sales_orders.empty else 0),
        hint=header_qty_hint,
    )

if sheet == "Ringkasan":
    chart_slot = st.container()
    table_slot = st.container()
    summary_gen = st.session_state.setdefault("summary_gen", 0)
    selected_key = None
    selected_label = None
    view = shown.reset_index(drop=True)

    with table_slot:
        st.subheader("Top 50 item terlaris")
        view = view.sort_values(["peringkat", "item_key"], kind="mergesort").reset_index(drop=True)
        st.caption(
            f"Peringkat dihitung dari {sort_name} pada {resume_label}, dan selalu unik. "
            f"Prediksi QTY untuk {period_text} adalah permintaan dari data input, tanpa safety stock. "
            "Prediksi sales volume = prediksi QTY kali harga jual. "
            "Stok disarankan = prediksi QTY + safety stock. "
            f"{grain_note} "
            "Centang satu baris untuk menampilkan grafik SKU itu. "
            "Nilai penjualan mengikuti periode di atas dan centang Exclude return dan batal."
        )
        if view.empty:
            st.write("Tidak ada item untuk ditampilkan.")
        else:
            filter_col, _filter_space = st.columns([1.15, 3])
            with filter_col:
                show_n = st.selectbox(
                    "Tampilkan",
                    options=[10, 20, 30, 40, 50],
                    index=4,
                    format_func=lambda count: f"{count} item",
                    key=f"top50-show-{metric}-{period}",
                )
            table_view = view.head(int(show_n)).reset_index(drop=True)
            summary_source = leaderboard_frame(table_view, period)
            row_height = 44
            picked = st.dataframe(
                summary_source,
                height=row_height * (len(table_view) + 1) + 36,
                row_height=row_height,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                column_config=table_column_config(summary_source, roomy=True),
                key=f"summary-top50-{summary_gen}-{metric}-{period}-{show_n}-{resume_label}",
            )
            picked_rows = list(getattr(getattr(picked, "selection", None), "rows", []) or [])
            if picked_rows:
                selected_key = table_view.iloc[picked_rows[0]]["item_key"]
                chosen_row = table_view.iloc[picked_rows[0]]
                selected_label = product_identity(
                    chosen_row["peringkat"],
                    chosen_row["sku"],
                    chosen_row["product_name"],
                    chosen_row["variasi_tampil"],
                )

    with chart_slot:
        last_qty = float(view["qty_total"].sum()) if not view.empty else 0.0
        last_sales = float(view["sales_total"].sum()) if not view.empty else 0.0
        pred_qty_value = float(view["pred_qty"].sum()) if not view.empty else 0.0
        pred_sales_value = float(view["pred_sales"].sum()) if not view.empty else 0.0

        st.subheader("Ringkasan total Top 50")
        m1, m2, m3, m4, m5 = st.columns([1.05, 1.2, 1.05, 1.35, 1.15])
        show_metric(m1, "QTY actual", format_qty(last_qty))
        show_metric(m2, "Sales volume actual", format_idr(last_sales))
        show_metric(m3, "Prediksi QTY", format_qty(pred_qty_value))
        show_metric(m4, "Prediksi sales volume", format_idr(pred_sales_value))
        top_sales = float(view["sales_total"].sum()) if not view.empty else 0.0
        total_sales = float(sales_orders["sales"].sum()) if "sales" in sales_orders.columns and not sales_orders.empty else 0.0
        share = top_sales / total_sales * 100 if total_sales > 0 else 0.0
        show_metric(
            m5,
            "Kontribusi sales Top 50",
            f"{format_number(share, 1)}%",
            hint=f"{format_idr(top_sales)} dari {format_idr(total_sales)} pada {resume_label}",
        )
        if last_qty > 0 and last_sales > 0 and (pred_qty_value - last_qty) * (pred_sales_value - last_sales) < 0:
            st.caption(
                "Total QTY dan total sales volume berbeda arah karena campurannya berubah: "
                "produk murah dan produk mahal tidak naik atau turun bersamaan. "
                "Pada tiap produk, sales volume tetap prediksi QTY kali harga jual produk itu."
            )

        if not view.empty:
            if metric == "sales":
                st.caption(
                    f"Biru adalah sales actual pada {resume_label}. "
                    f"Oranye adalah prediksi sales {period_text}. "
                    "Hijau adalah stok prediksi dalam unit, di atas prediksi sales: prediksi QTY ditambah safety stock. "
                    "Tiap produk punya skala sendiri, jadi nominal kecil tetap terbaca. "
                    "Angka pada batang adalah nilai asli, bukan panjang yang disamakan dari peringkat 1 sampai 50."
                )
                st.plotly_chart(item_sales_chart(view, "total Top 50"), use_container_width=True)
                down = view.loc[view["pred_sales"] + 0.5 < view["sales_total"]]
                if not down.empty:
                    gap = float((down["sales_total"] - down["pred_sales"]).sum())
                    qty_down = int((down["pred_qty"] + 0.5 < down["qty_total"]).sum())
                    detail = (
                        f"{qty_down} di antaranya juga prediksi QTY-nya lebih rendah, "
                        "karena level 28 hari terakhir lebih sepi daripada periode ini. "
                        if qty_down
                        else "Prediksi QTY pada SKU itu tidak lebih rendah; penurunannya datang dari harga jual. "
                    )
                    st.info(
                        f"{len(down)} dari {len(view)} SKU prediksi sales-nya di bawah sales actual pada {resume_label}. "
                        f"Selisih pada SKU itu {format_idr(gap)}. "
                        "Prediksi sales mengikuti prediksi QTY kali harga jual. "
                        f"{detail}"
                        "Angka hijau pada batang stok prediksi adalah jumlah unit yang disiapkan."
                    )
            else:
                st.caption(
                    f"Biru adalah QTY pada {resume_label}. Oranye adalah prediksi {period_text}. "
                    "Label diawali peringkat dan Nomor Referensi SKU, lalu nama produk terakhir."
                )
                st.plotly_chart(item_qty_chart(view, "total Top 50"), use_container_width=True)

        if selected_key is None:
            if metric == "sales":
                st.info("Centang satu SKU pada tabel Top 50 untuk menampilkan grafik sales dan garis QTY.")
            else:
                st.info("Centang satu SKU pada tabel Top 50 untuk menampilkan empat grafik di bawah.")
        else:
            chosen = view[view["item_key"] == selected_key].iloc[0]
            scope_label = selected_label or "SKU"
            st.subheader(scope_label)
            scope_orders = sales_orders[sales_orders["item_key"] == selected_key]
            st.caption(
                f"Actual per tanggal memakai {resume_label}. "
                f"Prediksi di bawahnya tetap {period_text}, dihitung dari data input."
            )
            actual_qty_total = float(scope_orders["qty"].sum()) if not scope_orders.empty else 0.0
            actual_sales_total = float(scope_orders["sales"].sum()) if not scope_orders.empty else 0.0
            if metric == "sales":
                if scope_orders.empty:
                    actual_labels: list[str] = []
                    actual_sales_series = np.zeros(0)
                    actual_qty_series = np.zeros(0)
                else:
                    actual_days = scope_orders["order_time"].dt.floor("D")
                    actual_grouped = scope_orders.groupby(actual_days).agg(qty=("qty", "sum"), sales=("sales", "sum"))
                    actual_index = pd.date_range(actual_grouped.index.min(), actual_grouped.index.max(), freq="D")
                    actual_grouped = actual_grouped.reindex(actual_index, fill_value=0)
                    actual_labels = [day_tick_label(stamp) for stamp in actual_grouped.index]
                    actual_sales_series = actual_grouped["sales"].to_numpy(dtype=float)
                    actual_qty_series = actual_grouped["qty"].to_numpy(dtype=float)
                st.caption(
                    "Batang adalah sales volume pada skala rupiah. "
                    "Garis biru adalah QTY pada skala kanan, mengikuti jumlah unit supaya tetap terbaca."
                )
                st.plotly_chart(
                    sales_qty_chart(
                        actual_labels,
                        actual_sales_series,
                        actual_qty_series,
                        "Sales actual dan QTY actual",
                    ),
                    use_container_width=True,
                )
                actual_cols = st.columns(2)
                show_metric(actual_cols[0], "Total sales volume actual", format_idr(actual_sales_total))
                show_metric(
                    actual_cols[1],
                    "Total QTY actual",
                    format_qty(actual_qty_total),
                    hint="QTY pada garis grafik",
                )
            else:
                st.plotly_chart(daily_actual_chart(scope_orders, scope_label, "qty"), use_container_width=True)
                show_metric(st, "Total QTY actual", format_qty(actual_qty_total))
                st.plotly_chart(daily_actual_chart(scope_orders, scope_label, "sales"), use_container_width=True)
                show_metric(st, "Total sales volume actual", format_idr(actual_sales_total))
            grain = "hari"
            interval_options = prediction_interval_options(period)
            if period == "bulan":
                if metric == "sales":
                    show_section_title(
                        f"Prediksi sales {format_id_date(window_start)} – {format_id_date(window_end)}. "
                        "Batang adalah sales prediksi. Garis adalah prediksi QTY yang membentuk sales itu."
                    )
                else:
                    show_section_title(
                        f"Prediksi mengikuti tanggal kalender {format_id_date(window_start)} – {format_id_date(window_end)}, "
                        "sejak tanggal hari ini. Tiap batang adalah satu tanggal. "
                        "Grafik ini menampilkan permintaan saja. Stok final = prediksi QTY + safety stock, pada tabel."
                    )
            else:
                interval_labels = [label for _key, label in interval_options]
                grain_choice = st.selectbox(
                    "Tampilan prediksi",
                    interval_labels,
                    index=0,
                    key=f"pred-interval-{period}-{selected_key}",
                )
                grain = interval_options[interval_labels.index(grain_choice)][0]
                interval_name = {
                    "hari": "per tanggal",
                    "minggu": "per minggu",
                    "2minggu": "per 2 minggu",
                    "bulan": "per bulan",
                }[grain]
                show_section_title(
                    f"Prediksi sales {interval_name} untuk {PERIOD_SPECS[period].label}, "
                    f"{format_id_date(window_start)} – {format_id_date(window_end)}. "
                    "Batang adalah sales prediksi. Garis adalah prediksi QTY."
                    if metric == "sales"
                    else (
                        f"Prediksi {interval_name} untuk {PERIOD_SPECS[period].label}, "
                        f"{format_id_date(window_start)} – {format_id_date(window_end)}. "
                        f"Rentang ini {horizon_day_count(period, today)} hari kalender sejak tanggal hari ini. "
                        "Pilihan di atas menyesuaikan lebar grafik. "
                        "Grafik ini menampilkan permintaan saja. Stok final = prediksi QTY + safety stock, pada tabel."
                    )
                )
            stored_analysis = st.session_state.get("analysis", {})
            base_history = stored_analysis.get("base_history", pd.DataFrame())
            if isinstance(base_history, pd.DataFrame) and not base_history.empty:
                weekday = _weekday_profile(base_history)
            else:
                weekday = np.ones(7, dtype=float)
            projected = prediction_frame(chosen, scope_orders, weekday, window_start, window_end)
            labels, pred_qty_series, pred_sales_series = bucket_prediction(projected, grain)
            pred_qty_total = float(np.sum(pred_qty_series)) if len(pred_qty_series) else 0.0
            pred_sales_total = float(np.sum(pred_sales_series)) if len(pred_sales_series) else 0.0
            if metric == "sales":
                st.plotly_chart(
                    sales_qty_chart(
                        labels,
                        pred_sales_series,
                        pred_qty_series,
                        "Sales prediksi dan QTY prediksi",
                    ),
                    use_container_width=True,
                )
                pred_cols = st.columns(2)
                show_metric(
                    pred_cols[0],
                    "Total prediksi sales volume",
                    format_idr(pred_sales_total),
                    hint=growth_hint(pred_sales_total, actual_sales_total, "sales volume"),
                )
                show_metric(
                    pred_cols[1],
                    "Total prediksi QTY",
                    format_qty(pred_qty_total),
                    hint="QTY pada garis grafik, dikalikan harga jual menjadi sales prediksi",
                )
                chosen_stock = float(_stock_sales(pd.DataFrame([chosen])).sum())
                show_metric(
                    st,
                    "Stok prediksi",
                    format_idr(chosen_stock),
                    hint=f"{format_qty(float(chosen['stok_disarankan']))} unit. Prediksi sales ditambah safety stock",
                )
                drop_text = sales_drop_note(
                    actual_sales_total,
                    pred_sales_total,
                    actual_qty_total,
                    pred_qty_total,
                    scope="SKU ini",
                )
                if drop_text:
                    st.info(drop_text)
            else:
                st.plotly_chart(
                    timeline_chart(labels, pred_qty_series, "Prediksi QTY", "QTY"),
                    use_container_width=True,
                )
                show_metric(
                    st,
                    "Total prediksi QTY",
                    format_qty(pred_qty_total),
                    hint=growth_hint(pred_qty_total, actual_qty_total, "QTY terjual"),
                )
                st.plotly_chart(
                    timeline_chart(
                        labels,
                        pred_sales_series,
                        "Prediksi sales volume",
                        "Sales volume (Rp)",
                        money=True,
                    ),
                    use_container_width=True,
                )
                show_metric(
                    st,
                    "Total prediksi sales volume",
                    format_idr(pred_sales_total),
                    hint=growth_hint(pred_sales_total, actual_sales_total, "sales volume"),
                )

elif sheet == "Prediksi & stok":
    applied_service = int(st.session_state["analysis"].get("service", service))
    st.subheader(
        f"SKU pada {resume_label} menurut {METRIC_LABELS[metric]} — prediksi {period_text}"
    )
    st.caption(
        f"Menampilkan {format_number(len(catalog))} SKU yang ada penjualan pada {resume_label}, diurutkan {sort_name}. "
        "Peringkat unik dihitung pada rentang itu, bukan dari seluruh bulan input. "
        f"Prediksi QTY untuk {period_text} adalah permintaan dari data input, belum termasuk safety stock {format_number(applied_service)}%. "
        "Stok disarankan = prediksi QTY + safety stock. Itulah stok final. "
        "Mengubah persentase di samping mengubah safety stock dan stok disarankan. Prediksi QTY tidak berubah. "
        "Nama lengkap ada di kolom Produk. "
        "Isi tabel mengikuti centang Exclude return dan batal di header."
    )
    if catalog.empty:
        st.write("Tidak ada item untuk ditampilkan.")
    else:
        display = leaderboard_frame(
            sort_leaderboard(catalog, "qty_desc" if metric == "qty" else "sales_desc"),
            period,
        )
        st.dataframe(
            display,
            height=680,
            row_height=44,
            hide_index=True,
            column_config=table_column_config(display, roomy=True),
        )
        csv = display.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Unduh seluruh SKU (CSV)",
            csv,
            file_name="rekomendasi_stok.csv",
            mime="text/csv",
        )

elif sheet == "Evaluasi model":
    period_name = PERIOD_SPECS[period].label
    period_days = horizon_day_count(period)
    suggestion_lines = []
    for key in PERIOD_OPTIONS:
        pct = SUGGESTED_SERVICE[key]
        days = horizon_day_count(key)
        z_key = service_z(pct)
        suggestion_lines.append(
            f"- **{PERIOD_SPECS[key].label}:** saran {pct}%, z = {format_number(z_key, 2)}, "
            f"akar {days} hari = {format_number(np.sqrt(days), 2)}, "
            f"pengali cadangan = {format_number(z_key * np.sqrt(days), 2)} × sigma harian."
        )
    suggestion_text = "\n".join(suggestion_lines)
    st.subheader("Alur kerja sistem, dari unggah sampai stok")
    st.markdown(
        f"""
Halaman ini menjelaskan cara sistem mengambil data, menghitung, dan menguji algoritma. Periode yang sedang dipilih adalah **{period_name}** ({period_days} hari, {period_text}). Angka toko ada di menu Ringkasan dan Prediksi & stok.

**A. Mengunggah dan menyimpan**

1. File CSV, XLSX, atau XLS dibaca. Beberapa file digabung. Baris yang sama dihitung sekali.
2. Data disimpan per bulan. Mengunggah bulan yang sama mengganti isi bulan itu bila ada perubahan. Bila isinya sama, catatannya **Tidak ada perubahan data**.
3. Tahun dan bulan yang dicentang di input adalah data latih prediksi. Makin banyak bulan yang dicentang, riwayat yang dipelajari makin panjang. Periode prediksi di bawahnya adalah jangka ramalan. Keduanya baru dihitung setelah **Jalankan analisis**.
4. Setelah analisis jalan, Ringkasan punya filter tahun, bulan, dan tanggal penjualan. Filter itu hanya memotong angka penjualan yang ditampilkan. Prediksi tidak dihitung ulang.

**B. Kolom yang dipakai**

1. **No. Pesanan** adalah identitas pesanan. Sales volume mengambil **Total Pembayaran** satu kali tiap nomor. Bila pembayaran kosong atau nol, sistem menjumlah nilai baris pesanan itu.
2. **Nomor Referensi SKU** adalah acuan produk. Bila satu SKU punya beberapa nama, yang dipakai adalah nama pada pesanan terakhir. Nama Variasi ikut nama terakhir itu dan tetap ditampilkan, tetapi tidak memecah SKU.
3. **Jumlah** adalah QTY kotor. **Returned quantity** adalah unit retur. QTY bersih = Jumlah − Returned quantity, dan tidak boleh di bawah nol.
4. Nilai satu baris = **Harga Setelah Diskon × Jumlah**. Nominal retur = Returned quantity × Harga Setelah Diskon.
5. Kota, pembayaran, pengiriman, voucher, dan identitas pembeli tidak masuk prediksi.

**C. Exclude return dan batal**

1. Centang ini ada di header Ringkasan dan Prediksi & stok. Lembar Data memakai centang status sendiri. Semua status pesanan masuk analisis. Tidak ada filter status di input.
2. Centang kosong: pesanan batal ikut dihitung, dan QTY memakai Jumlah kotor, termasuk unit yang diretur.
3. Centang terisi: baris berstatus batal dikeluarkan, dan QTY memakai Jumlah bersih. Baris yang jumlah bersihnya nol ikut keluar.
4. Header, Top 50, dan Prediksi & stok memakai set data yang sama dengan centang itu.

**D. Menu Data**

1. Tahun, bulan, dan tanggal memotong laporan pada lembar Data, sama seperti periode penjualan di Ringkasan.
2. Centang status, termasuk Return dan Batal, hanya mengubah angka di menu Data.
3. Nominal retur muncul bila Return atau All dicentang. Nominal batal muncul bila status batal atau All dicentang.
4. Tabel status, kontribusi invoice batal, dan SKU punya baris Total.
5. Filter SKU Retur hanya menampilkan kolom retur. Filter Batal hanya menampilkan kolom batal. Alasan pada tabel itu berbentuk centang, dan baris mengikuti alasan yang dicentang.
6. Tabel gabungan memakai filter tahun dan bulan. Bulan berbentuk centang. Baris yang tampil mengikuti bulan yang dicentang.

**E. Peringkat**

1. Parameter dipilih di input: **Quantity terjual** atau **Sales volume**. Pilihan baru dipakai setelah **Jalankan analisis**.
2. Angka yang diperingkat adalah penjualan pada tahun, bulan, dan tanggal di Ringkasan. Bulan input yang lain tidak ikut dijumlah, supaya Top 50 tidak menumpuk.
3. Peringkat 1 adalah nilai terbesar pada rentang itu. Peringkat selalu unik.
4. Top 50 adalah 50 peringkat pertama. Prediksi pada baris itu tetap ramalan untuk periode prediksi, dihitung dari seluruh bulan input yang dicentang.
"""
    )
    st.subheader("F. Prediksi: Level terkini")
    st.markdown(
        f"""
**Konsep.** Prediksi QTY adalah permintaan, belum termasuk cadangan. Level memakai 28 hari terakhir, bukan rata-rata sejak bulan pertama. Karena itu prediksi mengikuti bulan yang sedang berjalan. Bulan yang lebih sepi di awal tahun tidak menarik angka ke bawah.

**Mengapa rumus ini.** Rata-rata sepanjang Januari–Oktober membuat hampir semua SKU diprediksi di bawah bulan ini, sebab bulan awal lebih sepi. Level 28 hari terakhir mengikuti laju yang baru terjadi. Lonjakan satu hari dipotong di kuantil 90%. Kemiringan hanya selisih 28 hari terakhir terhadap 28 hari sebelumnya, dan ujung horizon ditahan di 15% level supaya kuartal tidak jatuh atau melonjak.

**Cara hitung, untuk satu SKU**

1. Susun kalender harian dari hari pertama sampai hari terakhir. Hari tanpa pesanan diisi nol.
2. Bila hampir setiap hari ada penjualan dan hari terakhir di bawah 30% median hari sebelumnya, hari terakhir dikeluarkan.
3. Ambil 28 hari terakhir. Nilai di atas kuantil 90% hari yang ada penjualan dipotong. `level = rata-rata jendela itu`.
4. Bila riwayat kurang dari 28 hari, kemiringan = 0. Bila cukup, kemiringan = (level 28 hari terakhir − level 28 hari sebelumnya) / 28.
5. Perkiraan hari ke-t, φ = 0,985: `max(0, (level + kemiringan × (1 − φ^t) / (1 − φ)) × profil hari)`.
6. Jumlahkan {period_days} hari sejak tanggal hari ini. Hasil dijepit pada 0,6 sampai 1,6 kali `level × jumlah hari`.
7. Prediksi sales volume = prediksi QTY × harga rata-rata yang terbeli. Harga tidak diramal sendiri.

Periode yang lebih panjang mengulang laju 28 hari terakhir, dengan geseran kemiringan paling banyak 15% di hari terakhir.
"""
    )
    st.subheader("G. Safety stock dan stok final")
    st.markdown(
        f"""
**Konsep.** Prediksi QTY adalah permintaan. Safety stock adalah cadangan. Stok disarankan = prediksi QTY + safety stock. Itulah stok final. Mengubah persen safety stock mengubah cadangan dan stok disarankan. Prediksi QTY tidak dihitung ulang.

**Cara hitung**

1. Garis pada 28 hari terakhir: `level × profil hari`. Level adalah laju harian terkini, bukan rata-rata sejak bulan pertama.
2. `sigma = simpangan baku (QTY harian − garis)`, pembagi n − 1. Hari terakhir yang terputus tidak masuk sigma. Lonjakan tetap di residual, jadi ketidakpastian masuk ke cadangan.
3. Untuk 1–99%, z = `Φ⁻¹(persen / 100)`. Untuk 0%, z = 0. Untuk 100% ke atas, z = `Φ⁻¹(0,999) × persen / 100`.
4. `cadangan = z × sigma × √hari`.
5. Safety stock dan prediksi QTY dibulatkan. Stok disarankan adalah jumlah keduanya.

Persen saran diturunkan pada periode panjang karena √hari sudah membesarkan cadangan:

{suggestion_text}
"""
    )
    st.subheader("H. Hasil pengujian algoritma")
    st.markdown(
        """
Pembanding diuji pada **satu deret**: jumlah QTY seluruh toko per hari, hari kosong diisi nol. Beberapa hari terakhir disembunyikan sebagai ujian. Model dilatih hanya pada hari sebelum ujian. Profil hari pada ujian juga dihitung dari hari latih saja.

Panjang ujian: 7 hari bila kalender minimal 21 hari. Kalau lebih pendek, ujian = max(2, panjang ÷ 5), dan tabel baru muncul bila kalender minimal 8 hari.

**Selisih (%)** = |perkiraan jumlah QTY pada hari ujian − actual jumlah QTY pada hari ujian| / actual × 100. Skor ini mengukur jumlah periode, sesuai keputusan stok. Hari bernilai nol tidak mendominasi skor.

Tiap pembanding:

- **Tren harian.** Konsep: level rata-rata seluruh hari, kemiringan paruh akhir terhadap paruh awal, dan redaman φ = 0,985 yang membesar bersama nomor hari. Dipakai sebagai pembanding karena rumusnya mengikuti arah jangka pendek. Pada laporan pendek yang paruh akhirnya lebih sepi, redaman itu menurunkan bulan-bulan belakang pada kuartal, semester, dan tahun. Hasilnya dijepit 0,25–4 kali laju harian.
- **Naive.** Konsep: hari depan sama dengan hari terakhir. Cara hitung pada ujian: QTY hari terakhir data latih × jumlah hari ujian. Dipakai sebagai pembanding karena rumusnya transparan. Pada laporan Shopee, satu hari ramai yang kebetulan berada di ujung data akan terbawa ke seluruh periode.
- **Moving Average.** Konsep: hari depan sama dengan rata-rata jendela terakhir. Cara hitung pada ujian: rata-rata sampai 7 hari terakhir data latih × jumlah hari ujian. Jendela ini meredam satu hari ekstrem, dan kemiringan naik atau turun di luar jendela tidak ikut.
- **Holt Linear / Holt-Winters** (statsmodels `ExponentialSmoothing`). Konsep: pemulusan eksponensial dengan level dan tren. Bila data latih cukup untuk dua musim 7 hari, versi musiman aditif dan multiplikatif ikut dilatih, lalu yang lebih rapat pada ujian internal yang disimpan. Pada file pendek hasilnya Holt Linear, yaitu tren aditif tanpa musim. Perkiraan ujian adalah jumlah ramalan harian sepanjang jendela ujian. Model ini kuat pada deret panjang dan rapat. Pada banyak SKU yang jarang laku, parameternya mudah tidak stabil. Holt diuji pada total toko. Prediksi tiap Nomor Referensi SKU memakai Level terkini.
- **ARIMA / SARIMA** (statsmodels `SARIMAX`). Konsep: kombinasi autoregresi, selisih untuk membuat deret lebih stabil, dan rata-rata bergerak. Ordo yang dicoba (1,1,1), (0,1,1), dan (1,0,1). Musiman 7 hari ditambahkan bila data latih memuat minimal dua musim. Dipakai sebagai pembanding klasik peramalan. Dilatih hanya bila panjang data latih 12–90 hari: file belasan hari masih kebagian, file yang sangat panjang tidak menahan tombol analisis.
- **XGBoost** (`XGBRegressor`). Konsep: pohon gradient boosting yang belajar dari lag hari sebelumnya. Lag = min(6, max(3, panjang ÷ 4)), 120 pohon, kedalaman 3, learning rate 0,08, objective squared error. Ramalan periode disusun langkah demi langkah: prediksi satu hari dimasukkan kembali sebagai lag hari berikutnya, lalu dijumlahkan. Gerbang panjang datanya sama dengan ARIMA, 12–90 hari latih. Pada deret pendek, pohon mudah mengikuti noise satu per satu SKU, sehingga XGBoost diuji pada total toko.
"""
    )
    st.subheader("Hasil perbandingan")
    if comparison.empty:
        st.write(
            "Perbandingan belum tersedia. Kalender harian masih di bawah 8 hari, "
            "jadi ujian sembunyi belum bisa dibentuk."
        )
    else:
        present = set(comparison["Algoritma"].astype(str))
        if not (present & {"ARIMA", "SARIMA", "XGBoost"}):
            gate_note = (
                "ARIMA dan XGBoost tidak muncul pada file ini karena panjang data latih berada di luar 12–90 hari. "
                "Holt tetap dihitung."
            )
        else:
            gate_note = "ARIMA dan XGBoost masuk karena panjang data latih berada pada 12–90 hari."
        if "Holt-Winters" in present:
            gate_note += " Hasil Holt pada file ini memakai komponen musiman."
        elif "Holt Linear" in present:
            gate_note += " Hasil Holt pada file ini adalah Holt Linear, tanpa komponen musiman."
        result_lines = []
        for _, result_row in comparison.sort_values(["Selisih (%)", "Algoritma"]).iterrows():
            result_lines.append(
                f"- **{result_row['Algoritma']}** ({result_row['Peran']}): "
                f"perkiraan {format_number(float(result_row['Perkiraan ujian']), 1)} unit, "
                f"actual {format_number(float(result_row['Actual ujian']), 1)} unit, "
                f"selisih {format_number(float(result_row['Selisih (%)']), 1)}%."
            )
        closest = comparison.sort_values(["Selisih (%)", "Algoritma"]).iloc[0]
        st.markdown(
            f"""
{gate_note}

Hasil ujian total toko, diurutkan dari selisih paling kecil:

{chr(10).join(result_lines)}

Selisih paling kecil pada total toko: **{closest['Algoritma']}** ({format_number(float(closest['Selisih (%)']), 1)}%). Prediksi per produk memakai **Level terkini**, bukan otomatis pemenang selisih pada total toko. Total toko lebih halus daripada satu SKU. Level terkini mengikuti 28 hari terakhir supaya prediksi tidak tertarik ke bulan yang lebih sepi. Croston, SBA, dan TSB dirancang untuk SKU yang jarang laku; pada SKU terlaris metode itu justru lebih rendah dari penjualan bulan ujian daripada Level terkini, jadi tidak dipakai sebagai prediksi utama. Safety stock memakai `z × sigma × √hari`, sama dengan rumus cadangan saat lead time pemasok tidak ada di laporan. Stok disarankan adalah prediksi QTY ditambah cadangan itu.
"""
        )
        st.dataframe(
            format_columns(
                comparison,
                {
                    "Perkiraan ujian": "decimal",
                    "Actual ujian": "decimal",
                    "Selisih (%)": "decimal",
                },
            ),
            height=420,
            hide_index=True,
        )

elif sheet == "Data":
    if source_raw.empty:
        st.write("Belum ada file yang terbaca. Pilih bulan pada Folder data bila data sudah pernah diimpor.")
    else:
        show_data_menu(source_raw)

elif sheet == "Folder data":
    show_folder_menu()

elif sheet == "Laporan":
    show_report_menu(
        source_raw,
        orders,
        combined,
        stock,
        history,
        metric,
        period,
        period_text,
        last_period,
        window_start=window_start,
        window_end=window_end,
        service=int(st.session_state["analysis"].get("service", service)),
        exclude_return_cancel=exclude_return_cancel,
    )
