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
    cancel_return_insight,
    focus_summary,
    ledger_from_raw,
    pareto_share,
    period_options,
    scope_ledger,
    slice_period,
    top_reason_table,
    unit_price_trend,
    unpaid_buyer_table,
    unpaid_concentration,
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
    FORECAST_CANDIDATE_LIMIT,
    MODEL_NAME,
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

APP_FONTS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Manrope:wght@400;500;600;700&display=swap" rel="stylesheet">
"""

APP_CSS = """
<style>
:root {
  --ink: #0b1f1c;
  --body: #243532;
  --muted: #5b736e;
  --soft: #eef5f3;
  --panel: #ffffff;
  --line: #d5e3df;
  --accent: #0f766e;
  --accent-deep: #0a5c56;
  --accent-soft: #e6f5f2;
  --target: #c2410c;
  --target-soft: #fff4eb;
  --ok: #166534;
  --ok-soft: #ecfdf3;
  --watch: #1d4ed8;
  --watch-soft: #eff6ff;
  --warn: #9a3412;
  --warn-soft: #fff7ed;
  --font-display: "Fraunces", "Palatino Linotype", Georgia, serif;
  --font-body: "Manrope", "Segoe UI", sans-serif;
}
html, body, .stApp {
  font-family: var(--font-body);
  color: var(--body);
}
.stMarkdown, .stText, .stCaption, label, p, h1, h2, h3, h4, h5, h6,
[data-testid="stWidgetLabel"], [data-testid="stMarkdownContainer"] {
  font-family: var(--font-body) !important;
}
/* Jangan override font ikon Material / BaseWeb */
[data-testid="stIconMaterial"],
span[data-testid="stIconMaterial"],
.material-icons, .material-symbols-rounded, .material-symbols-outlined {
  font-family: "Material Symbols Rounded", "Material Symbols Outlined", "Material Icons" !important;
  font-style: normal !important; font-weight: normal !important;
  letter-spacing: normal !important; text-transform: none !important;
}
.stApp {
  background:
    radial-gradient(1200px 520px at 8% -10%, rgba(15, 118, 110, 0.10), transparent 55%),
    radial-gradient(900px 480px at 100% 0%, rgba(194, 65, 12, 0.05), transparent 50%),
    linear-gradient(180deg, #f7faf9 0%, #eef4f2 48%, #f5f8f7 100%);
}
.block-container {
  padding-top: 2.35rem !important; padding-bottom: 2rem !important; max-width: 1180px;
}
[data-testid="stMetricValue"], [data-testid="stMetricValue"] > div {
  font-size: 1.2rem !important; line-height: 1.3 !important;
  white-space: normal !important; word-break: break-word !important;
}
.brand-mark {
  display: inline-flex; align-items: center; gap: 0.55rem; margin: 0.35rem 0 0.35rem;
}
.brand-mark .mark {
  width: 2rem; height: 2rem; border-radius: 0.6rem; flex: 0 0 auto;
  background: linear-gradient(145deg, var(--accent) 0%, var(--accent-deep) 100%);
  color: #fff; font-family: var(--font-display) !important; font-weight: 700; font-size: 1rem;
  display: inline-flex; align-items: center; justify-content: center;
  box-shadow: 0 6px 14px rgba(15, 118, 110, 0.18);
}
.brand-mark .brand-name {
  font-family: var(--font-display) !important; font-size: 1.45rem; font-weight: 700;
  color: var(--ink); letter-spacing: -0.02em; line-height: 1.15;
}
.target-rail {
  display: flex; flex-wrap: wrap; gap: 0.35rem; margin: 0 0 0.75rem;
}
.target-chip {
  font-size: 0.7rem; font-weight: 600; letter-spacing: 0.01em;
  color: var(--accent-deep); background: var(--accent-soft);
  border: 1px solid #b7ddd6; border-radius: 999px; padding: 0.2rem 0.58rem;
}
.target-chip.focus {
  color: var(--target); background: var(--target-soft); border-color: #fdba74;
}
.readable-metric-label {
  font-size: 0.7rem; font-weight: 600; color: var(--muted);
  margin-bottom: 0.12rem; letter-spacing: 0.03em; text-transform: uppercase;
}
.readable-metric-value {
  font-family: var(--font-display) !important; font-size: 1.15rem; font-weight: 700;
  line-height: 1.2; color: var(--ink); word-break: break-word;
}
.readable-metric-value.compact { font-size: 1rem; }
.metric-hint { font-size: 0.68rem; color: var(--muted); margin-top: 0.12rem; line-height: 1.3; }
.metric-card {
  background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
  padding: 0.65rem 0.75rem; min-height: 3.8rem;
  box-shadow: 0 1px 0 rgba(15, 40, 36, 0.03);
  border-left: 3px solid var(--accent);
}
.metric-card.target { border-left-color: var(--target); }
.period-name { font-family: var(--font-display) !important; font-size: 1.1rem; font-weight: 700; color: var(--ink); }
.period-dates { font-size: 0.84rem; color: #3f5b56; margin-top: 0.08rem; }
.page-kicker {
  font-size: 0.68rem; letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--accent-deep); font-weight: 700; margin: 0 0 0.12rem;
}
.page-title {
  font-family: var(--font-display) !important; font-size: 1.35rem; font-weight: 700;
  color: var(--ink); margin: 0 0 0.15rem; line-height: 1.2; letter-spacing: -0.02em;
}
.page-sub { font-size: 0.86rem; color: var(--muted); margin: 0 0 0.55rem; line-height: 1.35; max-width: 40rem; }
.nav-shell {
  background: rgba(255,255,255,0.78); border: 1px solid var(--line); border-radius: 12px;
  padding: 0.45rem 0.75rem 0.25rem; margin: 0 0 0.65rem;
  backdrop-filter: blur(6px);
}
.report-kicker { font-size: 0.75rem; letter-spacing: 0.06em; text-transform: uppercase; color: var(--accent-deep); font-weight: 700; margin: 0; }
.report-title {
  font-family: var(--font-display) !important; font-size: 1.45rem; font-weight: 700;
  color: var(--ink); margin: 0.15rem 0 0.45rem; line-height: 1.22;
}
.report-body { font-size: 0.98rem; line-height: 1.55; color: var(--body); }
.slide-deck {
  background: var(--panel); border: 1px solid var(--line); border-radius: 16px;
  padding: 1rem 1.1rem 0.85rem; margin: 0.35rem 0 0.85rem;
  box-shadow: 0 10px 28px rgba(11, 31, 28, 0.04);
}
.slide-note, .bone-result, .swot-card {
  background: var(--soft); border: 1px solid var(--line); border-radius: 12px;
  padding: 0.85rem 0.95rem; line-height: 1.45;
}
.slide-note.action { background: var(--accent-soft); border-color: #9fd4cb; }
.slide-note-label {
  font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.05em; color: var(--accent-deep); margin-bottom: 0.3rem;
}
.swot-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.65rem; margin: 0.4rem 0 0.8rem; }
.swot-s { background: var(--ok-soft); } .swot-w { background: #fef2f2; }
.swot-o { background: var(--watch-soft); } .swot-t { background: var(--warn-soft); }
.side-section {
  font-size: 0.68rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--accent-deep); margin: 0.7rem 0 0.25rem;
}
.side-note, .upload-note { font-size: 0.75rem; color: #4b6661; line-height: 1.3; margin: 0.05rem 0 0.35rem; }
.side-warn, .side-low, .side-best {
  font-size: 0.75rem; line-height: 1.35; border-radius: 8px; padding: 0.4rem 0.55rem; margin: 0.1rem 0 0.45rem;
}
.side-warn { color: var(--warn); background: var(--warn-soft); border: 1px solid #fdba74; }
.side-low { color: #1e3a8a; background: var(--watch-soft); border: 1px solid #bfdbfe; }
.side-best { color: var(--ok); background: var(--ok-soft); border: 1px solid #bbf7d0; }
.priority-badge {
  display: inline-flex; align-items: center; gap: 0.28rem;
  font-size: 0.72rem; font-weight: 700; letter-spacing: 0.02em;
  border-radius: 999px; padding: 0.18rem 0.55rem; border: 1px solid transparent;
}
.priority-tinggi { color: #9a3412; background: #fff7ed; border-color: #fdba74; }
.priority-sedang { color: #1d4ed8; background: #eff6ff; border-color: #bfdbfe; }
.priority-pantau { color: #166534; background: #ecfdf3; border-color: #bbf7d0; }
.cta-panel {
  background: linear-gradient(135deg, rgba(15,118,110,0.08), rgba(255,255,255,0.9));
  border: 1px solid #b7ddd6; border-radius: 12px; padding: 0.7rem 0.85rem; margin: 0.35rem 0 0.65rem;
}
.cta-panel .cta-title {
  font-family: var(--font-display) !important; font-size: 1.02rem; font-weight: 700;
  color: var(--ink); margin: 0 0 0.15rem;
}
.cta-panel .cta-body { font-size: 0.84rem; color: var(--muted); margin: 0; line-height: 1.35; }
.chart-heading {
  font-family: var(--font-display) !important; font-size: 1rem; font-weight: 700;
  color: var(--ink); margin: 0.65rem 0 0.3rem;
}
.section-gap { height: 0.35rem; }
.sheet-scroll { overflow: auto; border: 1px solid var(--line); border-radius: 10px; background: #fff; }
.sheet-scroll table { border-collapse: collapse; width: max-content; min-width: 100%; font-size: 0.88rem; }
.sheet-scroll th, .sheet-scroll td { padding: 0.42rem 0.7rem; border-bottom: 1px solid var(--line); white-space: nowrap; }
.sheet-scroll th { position: sticky; top: 0; background: #edf5f3; }
.sheet-scroll td.num, .sheet-scroll th.num { text-align: right; }
div[data-testid="stExpander"] {
  border: 1px solid var(--line); border-radius: 12px; background: rgba(255,255,255,0.92);
}
section[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #f8fbfa 0%, #eef5f3 100%);
  border-right: 1px solid var(--line);
}
section[data-testid="stSidebar"] .block-container { padding-top: 1rem; }
div[data-testid="stAlert"] { border-radius: 12px; }
/* Soften Streamlit alert red into amber guidance, keep meaning clear */
div[data-testid="stAlert"][kind="error"],
div[data-baseweb="notification"] {
  border-radius: 12px;
}
.stButton > button[kind="primary"],
.stButton > button[data-testid="baseButton-primary"] {
  background: linear-gradient(180deg, #149388 0%, #0c6b64 100%) !important;
  border: 1px solid #08534e !important;
  color: #ffffff !important;
  font-weight: 700 !important; border-radius: 10px !important;
  box-shadow: 0 8px 16px rgba(15, 118, 110, 0.22);
}
.stButton > button[kind="primary"] p,
.stButton > button[kind="primary"] span,
.stButton > button[data-testid="baseButton-primary"] p,
.stButton > button[data-testid="baseButton-primary"] span {
  color: #ffffff !important; font-weight: 700 !important;
}
.stButton > button[kind="secondary"],
.stButton > button[data-testid="baseButton-secondary"] {
  border-radius: 10px !important; border-color: var(--line) !important;
}
@media (max-width: 768px) {
  .swot-grid { grid-template-columns: 1fr; }
  .readable-metric-value { font-size: 1.05rem; }
  .page-title, .brand-mark .brand-name { font-size: 1.28rem; }
  .block-container { padding-left: 1rem !important; padding-right: 1rem !important; }
  .target-rail { gap: 0.35rem; }
}
</style>
"""


def configure_page() -> None:
    st.set_page_config(
        page_title="Prediksi Stok Shopee",
        page_icon="S",
        layout="wide",
    )
    st.markdown(APP_FONTS + APP_CSS, unsafe_allow_html=True)

TOP_N = 50
TABLE_HEIGHT = 260
DETAIL_TABLE_HEIGHT = 200
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
def cached_source(keys: tuple[str, ...], stamp: tuple[float, ...]) -> pd.DataFrame:
    """Satu load bulan tersimpan; clean/ledger memakai ulang sumber ini."""
    del stamp
    source, _stored = load_months(list(keys))
    if source is None or source.empty:
        return pd.DataFrame()
    return source


@st.cache_data(show_spinner=False)
def cached_library_frames(
    keys: tuple[str, ...], stamp: tuple[float, ...]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Baca bulan tersimpan sekali. Stempel file membuat cache batal saat impor baru."""
    source = cached_source(keys, stamp)
    if source.empty:
        return pd.DataFrame(), pd.DataFrame()
    return source, clean_order_frame(source)


@st.cache_data(show_spinner=False)
def cached_ledger(keys: tuple[str, ...], stamp: tuple[float, ...]) -> pd.DataFrame:
    return ledger_from_raw(cached_source(keys, stamp))


@st.cache_data(show_spinner=False)
def cached_merged(keys: tuple[str, ...], stamp: tuple[float, ...]) -> tuple[pd.DataFrame, pd.Series]:
    source = cached_source(keys, stamp)
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


SHEET_TARGETS = {
    "Ringkasan": "Top 50 & arah permintaan",
    "Prediksi & stok": "Stok siap + reorder",
    "Evaluasi model": "Cek akurasi dulu",
    "Data": "Batal & retur",
    "Folder data": "Data latih siap",
    "Laporan": "Keputusan manajer",
}


def show_brand_header() -> None:
    """Judul produk + chip target — tanpa essay filosofi."""
    st.markdown(
        "<div class='brand-mark'>"
        "<span class='mark'>S</span>"
        "<span class='brand-name'>Prediksi Stok Shopee</span>"
        "</div>"
        "<div class='target-rail'>"
        "<span class='target-chip focus'>Mencapai target</span>"
        "<span class='target-chip'>Stok siap</span>"
        "<span class='target-chip'>Top 50</span>"
        "<span class='target-chip'>Service level</span>"
        "<span class='target-chip'>Reorder</span>"
        "</div>",
        unsafe_allow_html=True,
    )


def show_app_menu() -> str:
    """Navigasi fitur lewat selectbox — ringan di mobile, tanpa 6 tombol penuh."""
    current = st.session_state.get("active-sheet", "Ringkasan")
    if current not in APP_SHEETS:
        current = "Ringkasan"
    st.markdown("<div class='nav-shell'>", unsafe_allow_html=True)
    nav_label, nav_pick = st.columns([1.0, 3.6], vertical_alignment="center")
    nav_label.markdown(
        "<div style='font-size:0.9rem;font-weight:700;color:var(--ink)'>Halaman</div>",
        unsafe_allow_html=True,
    )
    with nav_pick:
        chosen = st.selectbox(
            "Halaman",
            options=list(APP_SHEETS),
            index=list(APP_SHEETS).index(current),
            key="app-menu-select",
            help="Ganti halaman tidak menghitung ulang prediksi.",
            label_visibility="collapsed",
        )
    st.markdown("</div>", unsafe_allow_html=True)
    st.session_state["active-sheet"] = chosen
    return str(chosen)


def sheet_header(title: str, subtitle: str = "", *, kicker: str = "Halaman", target: str = "") -> None:
    """Judul singkat; target chip opsional (satu baris, tanpa essay)."""
    parts = [
        f"<div class='page-kicker'>{html.escape(kicker)}</div>",
        f"<div class='page-title'>{html.escape(title)}</div>",
    ]
    if subtitle:
        parts.append(f"<div class='page-sub'>{html.escape(subtitle)}</div>")
    elif target:
        parts.append(
            f"<div class='target-rail' style='margin:0.1rem 0 0.45rem'>"
            f"<span class='target-chip focus'>{html.escape(target)}</span></div>"
        )
    st.markdown("".join(parts), unsafe_allow_html=True)


def format_priority_label(value) -> str:
    """Label prioritas singkat untuk tabel."""
    text = str(value or "pantau").strip().lower()
    return {"tinggi": "Tinggi", "sedang": "Sedang", "pantau": "Pantau"}.get(text, "Pantau")


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
    try:
        pred = float(predicted)
        act = float(actual)
    except (TypeError, ValueError):
        return f"Belum ada {basis} pada laporan sebagai pembanding."
    if not np.isfinite(pred) or not np.isfinite(act) or act <= 0:
        return f"Belum ada {basis} pada laporan sebagai pembanding."
    percent = (pred - act) / act * 100
    if not np.isfinite(percent):
        return f"Belum ada {basis} pada laporan sebagai pembanding."
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
    sheet_header(
        "Data gabungan",
        f"{format_number(file_count)} file · {format_number(len(ledger))} baris",
        kicker="Data toko",
    )
    if ledger.empty:
        st.info("Laporan belum bisa diringkas. Pastikan file berisi waktu pesanan, produk, dan jumlah.")
        return
    period_view, range_text = filter_resume_orders(
        ledger,
        show_controls=True,
        prefix="data",
        caption="",
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
    show_section_title(range_text or "tidak ada tanggal yang dipilih")
    qty_shown = float(filtered["qty"].sum()) if not filtered.empty and "qty" in filtered.columns else 0.0
    row_one = st.columns(4)
    show_metric(row_one[0], "No. Pesanan", format_number(summary["orders"]))
    show_metric(row_one[1], "SKU terjual", format_number(summary["sku_sold"]))
    show_metric(row_one[2], "Sales volume", format_idr(summary["sales_volume"]))
    show_metric(row_one[3], "QTY terjual", format_qty(qty_shown))
    row_two = st.columns(4)
    show_metric(row_two[0], "Invoice batal", format_number(summary["invoice_cancel"]))
    show_metric(row_two[1], "Nominal batal", format_idr(summary["nominal_cancel"]))
    show_metric(row_two[2], "QTY retur", format_qty(summary["sales_return"]))
    show_metric(row_two[3], "Nominal retur", format_idr(summary["nominal_return"]))
    with st.expander("Status pesanan", expanded=True):
        status_view = append_total_row(status_table, "Status pesanan", ["No. Pesanan", "Kontribusi"])
        if "Kontribusi" in status_view.columns:
            status_view["Kontribusi"] = status_view["Kontribusi"].map(
                lambda value: f"{format_number(float(value), 1)}%" if str(value).strip() not in {"", "nan"} else ""
            )
        st.dataframe(
            status_view,
            height=min(44 * (len(status_view) + 1) + 36, DETAIL_TABLE_HEIGHT + 80),
            hide_index=True,
            column_config=table_column_config(status_view),
        )
    with st.expander("Kontribusi invoice batal", expanded=False):
        if not include_cancel:
            st.write("Nominal batal tidak dihitung karena status batal tidak dicentang.")
        elif contribution_table.empty:
            st.write("Tidak ada pesanan batal pada rentang ini.")
        else:
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
                height=min(44 * (len(contribution_view) + 1) + 36, DETAIL_TABLE_HEIGHT + 120),
                hide_index=True,
                column_config=table_column_config(contribution_view, roomy=True),
            )
    with st.expander("Pembeli batal karena belum bayar", expanded=False):
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
                height=min(44 * (len(unpaid) + 1) + 36, DETAIL_TABLE_HEIGHT + 120),
                hide_index=True,
                column_config=table_column_config(unpaid, roomy=True),
            )
            st.download_button(
                "Unduh pembeli belum bayar (CSV)",
                unpaid.to_csv(index=False).encode("utf-8-sig"),
                file_name="pembeli_belum_bayar.csv",
                mime="text/csv",
            )
    show_section_title("SKU dengan retur dan batal")
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
    st.caption(f"{format_number(sheet_count)} baris · {sheet_title}")
    if shown_sheet.empty:
        st.write("Tidak ada SKU dengan retur atau batal pada filter ini.")
    else:
        st.dataframe(
            shown_sheet,
            height=TABLE_HEIGHT,
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
    with st.expander("Tabel gabungan dari semua file", expanded=False):
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
        st.caption(f"{format_number(len(merged))} baris · {scope_text}")
        st.dataframe(merged, height=TABLE_HEIGHT, hide_index=True)


def _slide_head(kicker: str, title: str) -> None:
    st.markdown(
        "<div class='slide-deck'>"
        f"<p class='report-kicker'>{html.escape(kicker)}</p>"
        f"<div class='report-title'>{html.escape(title)}</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def _slide_advice(analysis: str, action: str) -> None:
    """Dua kotak di bawah data: analisa, lalu tindakan yang bisa dijalankan."""
    note, recommendation = st.columns(2, vertical_alignment="top")
    note.markdown(
        "<div class='slide-note'>"
        "<div class='slide-note-label'>Analisa</div>"
        f"{html.escape(analysis)}</div>",
        unsafe_allow_html=True,
    )
    recommendation.markdown(
        "<div class='slide-note action'>"
        "<div class='slide-note-label'>Rekomendasi</div>"
        f"{html.escape(action)}</div>",
        unsafe_allow_html=True,
    )


def _slide_strategy(
    *,
    scope_label: str,
    net_sales: float,
    net_orders: int,
    net_qty: float,
    cancel_share: float,
    cancel_nominal: float,
    return_qty: float,
    return_nominal: float,
    top_share: float,
    stock_sum: float,
    pred_qty_sum: float,
    safety_sum: float,
    top_cancel_reason: str,
    top_cancel_invoices: float,
    top_cancel_nominal: float,
    has_items: bool,
) -> None:
    """SWOT, akar masalah, dan rencana kerja yang memakai angka periode ini."""
    leak_is_cancel = cancel_nominal > return_nominal * 3 if return_nominal else cancel_nominal > 0
    reason_bit = (
        f"Alasan terbesar: {top_cancel_reason}, {format_number(top_cancel_invoices)} invoice, {format_idr(top_cancel_nominal)}."
        if top_cancel_reason
        else "Belum ada satu alasan batal yang menonjol pada tanggal ini."
    )
    strength = (
        f"Penjualan bersih {format_idr(net_sales)} dari {format_number(net_orders)} pesanan dan {format_qty(net_qty)} unit. "
        f"Top 50 menopang {format_number(top_share, 1)}% sales bersih, jadi iklan tidak perlu disebar ke seluruh katalog."
    )
    weakness = (
        f"Batal {format_number(cancel_share, 1)}% pesanan, senilai {format_idr(cancel_nominal)}. "
        f"Retur {format_qty(return_qty)} unit senilai {format_idr(return_nominal)}. {reason_bit}"
    )
    opportunity = (
        "Iklan Pencarian Shopee dengan kata kunci exact pada SKU yang bersih, "
        "chat kejar bayar sebelum pembatalan otomatis, dan voucher ongkir kecil hanya untuk order yang masih menunggu bayar."
    )
    threat = (
        "GMV iklan yang masih berisi batal membuat ROAS terlihat sehat padahal uangnya tidak masuk. "
        "Jendela bayar Shopee singkat, dan alasan ubah alamat atau ubah pesanan muncul karena listing belum jelas sebelum checkout."
    )
    if leak_is_cancel:
        root = (
            "Akar masalahnya ada di sebelum bayar, bukan di mutu barang. "
            f"Nominal batal {format_idr(cancel_nominal)} jauh di atas nominal retur {format_idr(return_nominal)}. "
            "Iklan yang menambah klik tanpa memastikan pembayaran hanya memperbesar tulang batal."
        )
    else:
        root = (
            "Retur cukup besar dibanding batal, jadi akarnya ada di janji produk: foto, varian, atau kualitas yang tidak sesuai yang diterima pembeli."
        )
    bones = [
        ("Pembeli", reason_bit),
        (
            "Iklan",
            "Budget yang mengejar klik atau GMV kotor menarik order yang tidak dibayar. Ukur iklan dari sales bersih.",
        ),
        (
            "Listing",
            "Ubah alamat dan ubah pesanan berarti ongkir, varian, atau ukuran baru ketahuan setelah checkout.",
        ),
        (
            "Operasi",
            "Belum ada shift yang mengingatkan bayar sebelum Shopee membatalkan otomatis.",
        ),
        (
            "Produk",
            "SKU dengan retur berulang jangan diisi ulang penuh dan jangan masuk Iklan Produk Serupa.",
        ),
    ]
    if has_items:
        plan = [
            f"Gudang: buat PO Top 50 sebesar {format_qty(stock_sum)} unit, yaitu prediksi QTY {format_qty(pred_qty_sum)} ditambah safety stock {format_qty(safety_sum)}. Jangan memesan dari QTY batal.",
            "Iklan: 70% budget Iklan Pencarian, kata kunci exact nama produk Top 50 yang batal dan retur-nya rendah. 20% Iklan Produk Serupa hanya untuk SKU itu. 10% uji satu kampanye. Matikan maximize clicks.",
            "Kejar bayar: dua jam sebelum batas batal otomatis, chat cara bayar. Voucher ongkir kecil hanya untuk order menunggu bayar, bukan voucher toko yang terbuka untuk semua.",
            "Listing: untuk alasan ubah alamat dan ubah pesanan, taruh ongkir, varian, dan ukuran di gambar pertama. Ukur ulang seminggu kemudian apakah invoice alasan itu turun.",
            "Rapat 20 menit tiap minggu pada slide ini: jika kontribusi alasan terbesar tidak turun, budget iklan minggu itu tidak dinaikkan.",
        ]
    else:
        plan = [
            "Perlebar tanggal sampai ada penjualan sebelum mengatur iklan dan pembelian.",
            "Selama rentang kosong, jangan menaikkan budget Iklan Pencarian.",
        ]
    cards = (
        ("swot-s", "Strength", strength),
        ("swot-w", "Weakness", weakness),
        ("swot-o", "Opportunity", opportunity),
        ("swot-t", "Threat", threat),
    )
    swot_html = "".join(
        f"<div class='swot-card {css}'><b>{html.escape(title)}</b>{html.escape(body)}</div>"
        for css, title, body in cards
    )
    bone_html = "".join(
        f"<div><b>{html.escape(name)}.</b> {html.escape(text)}</div>" for name, text in bones
    )
    plan_html = "".join(f"<div>{index}. {html.escape(step)}</div>" for index, step in enumerate(plan, start=1))
    st.markdown(
        f"<div class='report-kicker'>{html.escape(scope_label)}</div>"
        "<div class='report-title'>Strategi dan rencana minggu ini</div>"
        "<div class='swot-grid'>"
        f"{swot_html}"
        "</div>"
        "<div class='bone-result'>"
        "<div class='slide-note-label'>Akar masalah</div>"
        f"<div>{html.escape(root)}</div>"
        f"{bone_html}"
        "</div>"
        "<div class='slide-note action'>"
        "<div class='slide-note-label'>Rencana untuk tim</div>"
        f"{plan_html}"
        "</div>",
        unsafe_allow_html=True,
    )


def _display_report_numbers(frame: pd.DataFrame) -> pd.DataFrame:
    """Pisah ribuan dengan titik. Kolom SKU tetap utuh."""
    if frame is None or frame.empty:
        return frame
    shown = frame.copy()
    for column in shown.columns:
        key = str(column).strip().casefold()
        if "sku" in key or key in {"no", "tanggal pembelian"}:
            continue
        numeric = pd.to_numeric(shown[column], errors="coerce")
        if numeric.notna().mean() < 0.6:
            continue
        money = any(token in key for token in ("nominal", "sales", "omzet"))
        labels = []
        for value in numeric:
            if pd.isna(value):
                labels.append("")
            elif money:
                labels.append(format_idr(value))
            else:
                labels.append(format_number(value, 0))
        shown[column] = labels
    return shown


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
        "Rekomendasi",
    ]
    sheet_header(
        "Laporan presentasi",
        kicker="Presentasi",
        target=SHEET_TARGETS["Laporan"],
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
        caption="",
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
    previous, picker, following = st.columns([1.05, 2.5, 1.05], vertical_alignment="bottom")
    with previous:
        if st.button("← Sebelumnya", disabled=position == 0, use_container_width=True, key="laporan-prev"):
            st.session_state["laporan-slide-name"] = titles[position - 1]
            st.rerun()
    with following:
        if st.button("Berikutnya →", disabled=position >= len(titles) - 1, use_container_width=True, key="laporan-next"):
            st.session_state["laporan-slide-name"] = titles[position + 1]
            st.rerun()
    with picker:
        st.selectbox(
            f"Slide {position + 1} / {len(titles)}",
            titles,
            key="laporan-slide-name",
        )
    slide = str(st.session_state["laporan-slide-name"])

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
    cancel_share = float(summary.get("invoice_cancel", 0)) / gross_orders * 100 if gross_orders else 0.0
    sales_gap = gross_sales - net_sales
    top_sales = float(view["sales_total"].sum()) if not view.empty else 0.0
    top_share = top_sales / net_sales * 100 if net_sales > 0 else 0.0
    below_forecast = int((view["pred_sales"] + 0.5 < view["sales_total"]).sum()) if not view.empty else 0
    pred_qty_sum = float(view["pred_qty"].sum()) if not view.empty else 0.0
    pred_sales_sum = float(view["pred_sales"].sum()) if not view.empty else 0.0
    safety_sum = float(view["safety_stock"].sum()) if not view.empty else 0.0
    stock_sum = float(view["stok_disarankan"].sum()) if not view.empty else 0.0
    average_order = net_sales / net_orders if net_orders else 0.0
    metric_name = METRIC_LABELS.get(metric, metric)
    _contribution, contribution_table = cancel_contribution(period_view)
    top_cancel_reason = ""
    top_cancel_invoices = 0.0
    top_cancel_nominal = 0.0
    if not contribution_table.empty:
        top_row = contribution_table.iloc[0]
        top_cancel_reason = str(top_row.get("Alasan pembatalan", "")).strip()
        top_cancel_invoices = float(top_row.get("Invoice", 0) or 0)
        top_cancel_nominal = float(top_row.get("Nominal", 0) or 0)

    if slide == "Sampul":
        _slide_head("Tinjauan manajer", "Laporan analisa toko")
        st.markdown(
            "<div class='report-body'>"
            f"Data: <b>{html.escape(scope_label)}</b> · peringkat <b>{html.escape(METRIC_LABELS.get(metric, metric))}</b>. "
            f"Prediksi {html.escape(period_text)} "
            f"({html.escape(format_id_date(window_start))} – {html.escape(format_id_date(window_end))}), "
            f"service level {html.escape(format_number(service))}%. "
            f"Exclude return/batal: {'aktif' if exclude_return_cancel else 'nonaktif'} pada prediksi."
            "</div>",
            unsafe_allow_html=True,
        )
        cards = st.columns(4)
        show_metric(cards[0], "Pesanan pada periode", format_number(gross_orders))
        show_metric(cards[1], "Sales seluruh status", format_idr(gross_sales))
        show_metric(cards[2], "Sales bersih", format_idr(net_sales), hint="Tanpa batal dan tanpa baris yang habis diretur")
        show_metric(cards[3], "QTY bersih", format_qty(net_qty))
        _slide_advice(
            (
                f"Dari {format_number(gross_orders)} pesanan, yang menjadi penjualan bersih "
                f"{format_number(net_orders)} pesanan senilai {format_idr(net_sales)}. "
                f"Selisih {format_idr(sales_gap)} adalah batal dan baris yang habis diretur, "
                "jadi bukan permintaan yang harus disiapkan stoknya."
            ),
            (
                "Nilai omzet dan pembelian dari sales bersih. "
                "Jika selisih terhadap sales seluruh status besar, selesaikan dulu batal dan belum bayar sebelum menambah iklan."
            ),
        )
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
            _slide_advice(
                "Tidak ada penjualan bersih pada tanggal ini.",
                "Perlebar bulan atau tanggal. Jangan mengambil keputusan stok dari rentang yang kosong.",
            )
        else:
            st.plotly_chart(daily_actual_chart(net, scope_label, "sales"), use_container_width=True)
            peak_text = ""
            by_day = net.groupby(pd.to_datetime(net["order_time"]).dt.floor("D"))["sales"].sum()
            if not by_day.empty and float(by_day.sum()) > 0:
                peak_day = pd.Timestamp(by_day.idxmax())
                peak_share = float(by_day.max()) / float(by_day.sum()) * 100
                peak_text = (
                    f" Puncak grafik jatuh pada {format_id_date(peak_day.date())}, "
                    f"{format_number(peak_share, 1)}% dari nilai harian di grafik ini."
                )
            _slide_advice(
                f"Rata-rata pembayaran pesanan bersih {format_idr(average_order)} dari {format_qty(net_qty)} unit.{peak_text}",
                "Siapkan orang dan iklan pada hari puncak. Iklan Pencarian Shopee bid-nya dinaikkan hanya di tanggal itu, lalu diturunkan di hari sepi. Target iklan adalah sales bersih, bukan GMV yang masih berisi batal.",
            )
    elif slide == "Item terlaris":
        _slide_head(scope_label, f"50 item terlaris menurut {METRIC_LABELS.get(metric, metric)}")
        if view.empty:
            st.write("Tidak ada item pada tanggal ini.")
        elif metric == "sales":
            st.plotly_chart(item_sales_chart(view, "laporan"), use_container_width=True)
        else:
            st.plotly_chart(item_qty_chart(view, "laporan"), use_container_width=True)
        _slide_advice(
            (
                f"Top 50 menyumbang {format_number(top_share, 1)}% sales bersih. "
                f"{format_number(below_forecast)} SKU prediksi sales-nya di bawah sales periode ini, "
                "karena prediksi mengikuti 28 hari terakhir, bukan lonjakan satu periode."
                if not view.empty
                else "Tidak ada item pada tanggal ini, jadi belum ada konsentrasi penjualan yang bisa diurutkan."
            ),
            (
                "Beli lebih dulu SKU di Top 50, sebesar stok prediksi. "
                "Iklan: 70% budget Iklan Pencarian memakai kata kunci exact nama produk yang batal dan retur-nya rendah. "
                "SKU yang sering diretur dikeluarkan dari Iklan Produk Serupa."
                if not view.empty
                else "Perlebar tanggal sampai ada penjualan, lalu ulang slide ini."
            ),
        )
    elif slide == "Prediksi dan stok":
        _slide_head(period_text, "Prediksi permintaan dan stok yang disiapkan")
        if view.empty:
            st.write("Prediksi belum punya item pada tanggal ini.")
            _slide_advice(
                "Belum ada SKU pada tanggal ini, jadi stok prediksi belum bisa diurutkan.",
                "Perlebar tanggal penjualan, lalu jalankan analisis bila data inputnya berubah.",
            )
        else:
            pred_qty = float(view["pred_qty"].sum())
            pred_sales = float(view["pred_sales"].sum())
            safety_units = float(view["safety_stock"].sum())
            stock_units = float(view["stok_disarankan"].sum())
            cards = st.columns(4)
            show_metric(cards[0], "Prediksi QTY Top 50", format_qty(pred_qty))
            show_metric(cards[1], "Prediksi sales Top 50", format_idr(pred_sales))
            show_metric(cards[2], "Cadangan", format_qty(safety_units))
            show_metric(cards[3], "Stok prediksi", format_qty(stock_units))
            display = leaderboard_frame(view.head(10), period)
            st.dataframe(
                _display_report_numbers(display),
                hide_index=True,
                height=44 * (len(display) + 1) + 36,
                column_config=table_column_config(display, roomy=True),
            )
            _slide_advice(
                (
                    f"Prediksi QTY Top 50 {format_qty(pred_qty_sum)} unit, safety stock {format_qty(safety_sum)} unit, "
                    f"stok yang disiapkan {format_qty(stock_sum)} unit, senilai prediksi sales {format_idr(pred_sales_sum)}. "
                    f"Parameter {metric_name} hanya mengubah urutan 50 SKU. "
                    "Prediksi satu SKU tetap dari QTY 28 hari terakhir, lalu sales-nya QTY itu kali harga jual. "
                    "Total Top 50 berubah saat parameter diganti karena daftar SKU-nya berbeda. Angka SKU yang sama tidak berubah."
                ),
                "Purchase order memakai stok prediksi dalam unit. Sebelum flash sale, cocokkan kuota iklan dengan stok itu. SKU yang stok prediksinya tipis dihentikan dari GMV Max supaya iklan tidak menjual barang yang tidak ada.",
            )
    elif slide == "Status transaksi":
        _slide_head(scope_label, "Status pesanan")
        if status_table.empty:
            st.write("Tidak ada status pada tanggal ini.")
            _slide_advice(
                "Tidak ada pesanan pada tanggal ini.",
                "Perlebar filter sebelum menilai apakah operasi pengiriman atau pembatalan yang perlu ditangani.",
            )
        else:
            status_view = append_total_row(status_table, "Status pesanan", ["No. Pesanan", "Kontribusi"])
            if "Kontribusi" in status_view.columns:
                status_view = status_view.copy()
                status_view["Kontribusi"] = status_view["Kontribusi"].map(
                    lambda value: f"{format_number(float(value), 1)}%" if str(value).strip() not in {"", "nan"} else ""
                )
            st.dataframe(
                _display_report_numbers(status_view),
                hide_index=True,
                height=min(44 * (len(status_view) + 1) + 36, 520),
            )
            busiest = status_table.sort_values("No. Pesanan", ascending=False).iloc[0]
            st.markdown(
                "<div class='report-body'>"
                f"Status dengan pesanan terbanyak: <b>{html.escape(str(busiest['Status pesanan']))}</b>, "
                f"{html.escape(format_number(float(busiest['No. Pesanan'])))} pesanan."
                "</div>",
                unsafe_allow_html=True,
            )
            status_share = float(busiest["Kontribusi"]) if "Kontribusi" in busiest.index else 0.0
            _slide_advice(
                (
                    f"{busiest['Status pesanan']} memegang {format_number(float(busiest['No. Pesanan']))} pesanan"
                    f" ({format_number(status_share, 1)}%). "
                    f"Batal mencakup {format_number(cancel_share, 1)}% seluruh pesanan pada tanggal ini."
                ),
                (
                    "Jika batal masuk kelompok besar, tahan kenaikan budget Iklan Toko dan Iklan Pencarian sampai alasan terbesar turun. "
                    "Status berhasil yang dominan artinya pesanan sampai. Anggaran iklan berikutnya diarahkan ke SKU yang menopang status itu."
                ),
            )
    elif slide == "Retur dan batal":
        _slide_head(scope_label, "Retur dan pembatalan")
        cards = st.columns(4)
        show_metric(cards[0], "Invoice batal", format_number(summary.get("invoice_cancel", 0)))
        show_metric(cards[1], "Nominal batal", format_idr(summary.get("nominal_cancel", 0)))
        show_metric(cards[2], "QTY retur", format_qty(summary.get("sales_return", 0)))
        show_metric(cards[3], "Nominal retur", format_idr(summary.get("nominal_return", 0)))
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
            st.dataframe(
                _display_report_numbers(preview),
                hide_index=True,
                height=min(44 * (len(preview) + 1) + 36, 420),
            )
        if sku_sheet.empty:
            st.write("Tidak ada SKU retur atau batal pada tanggal ini.")
        else:
            issue = sku_sheet.head(8)
            st.caption("Delapan SKU dengan retur atau batal terbesar. Daftar lengkap ada di menu Data.")
            st.dataframe(
                _display_report_numbers(issue),
                hide_index=True,
                height=min(44 * (len(issue) + 1) + 36, 420),
            )
        reason_text = ""
        if not contribution_table.empty and "Alasan pembatalan" in contribution_table.columns:
            top_reason = contribution_table.iloc[0]
            reason_text = (
                f" Alasan dengan invoice terbanyak: {top_reason['Alasan pembatalan']} "
                f"({format_number(float(top_reason['Invoice']))} invoice)."
            )
        _slide_advice(
            (
                f"Batal {format_number(summary.get('invoice_cancel', 0))} invoice senilai {format_idr(summary.get('nominal_cancel', 0))}, "
                f"{format_number(cancel_share, 1)}% dari jumlah pesanan. "
                f"Retur {format_qty(summary.get('sales_return', 0))} unit senilai {format_idr(summary.get('nominal_return', 0))}."
                f"{reason_text}"
            ),
            "Tim iklan menghentikan perluasan kata kunci untuk SKU di tabel retur. Tim listing menaruh ongkir, varian, dan ukuran di gambar pertama untuk alasan ubah alamat dan ubah pesanan. Tim gudang mengisi ulang SKU retur hanya setelah alasannya dicek.",
        )
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
            _slide_advice(
                "Pada tanggal ini tidak ada akun yang batal hanya karena belum bayar.",
                "Pembatalan yang tersisa datang dari alasan lain. Gunakan slide retur dan batal untuk alasan yang masih menghasilkan invoice.",
            )
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
            _slide_advice(
                (
                    f"{format_number(buyer_count)} akun membatalkan karena belum bayar, "
                    f"{format_number(order_count)} pesanan, {format_qty(qty_missed)} unit, senilai {format_idr(sales_missed)}. "
                    f"Porsi ini {format_number(share_cancel, 1)}% dari nominal batal, dan bukan permintaan yang sudah dibayar."
                ),
                "Dua jam sebelum Shopee membatalkan otomatis, chat cara bayar. Voucher ongkir kecil hanya untuk order yang masih menunggu, bukan voucher terbuka. Matikan maximize clicks pada produk yang banyak menghasilkan order belum bayar. QTY ini tidak masuk pembelian stok.",
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
            _slide_advice(
                "Filter ini tidak memotong bulan yang tersimpan.",
                "Centang bulan yang sudah diunggah sebelum membandingkan tren.",
            )
        else:
            st.dataframe(
                _display_report_numbers(month_table),
                hide_index=True,
                height=min(44 * (len(month_table) + 1) + 36, 480),
            )
            strongest = month_table.loc[month_table["Sales bersih"].idxmax()]
            weakest = month_table.loc[month_table["Sales bersih"].idxmin()]
            _slide_advice(
                (
                    f"Sales bersih tertinggi {strongest['Bulan']} sebesar {format_idr(float(strongest['Sales bersih']))}. "
                    f"Terendah {weakest['Bulan']} sebesar {format_idr(float(weakest['Sales bersih']))}. "
                    "Angka ini sama dengan Folder data: tanpa batal dan tanpa baris yang habis diretur."
                ),
                "Latih prediksi dari bulan yang lengkap. Bulan yang baru separuh jangan dijadikan satu-satunya patokan di luar level 28 hari terakhir.",
            )
    else:
        _slide_strategy(
            scope_label=scope_label,
            net_sales=net_sales,
            net_orders=net_orders,
            net_qty=net_qty,
            cancel_share=cancel_share,
            cancel_nominal=float(summary.get("nominal_cancel", 0)),
            return_qty=float(summary.get("sales_return", 0)),
            return_nominal=float(summary.get("nominal_return", 0)),
            top_share=top_share,
            stock_sum=stock_sum,
            pred_qty_sum=pred_qty_sum,
            safety_sum=safety_sum,
            top_cancel_reason=top_cancel_reason,
            top_cancel_invoices=top_cancel_invoices,
            top_cancel_nominal=top_cancel_nominal,
            has_items=not view.empty and gross_orders > 0,
        )


def show_folder_menu() -> None:
    """Daftar data tersimpan menurut bulan dan tahun, plus riwayat impor."""
    saved = list_months()
    sheet_header(
        "Folder data",
        kicker="Arsip data",
        target=SHEET_TARGETS["Folder data"],
    )
    if not saved:
        st.info("Belum ada data tersimpan.")
    else:
        folder = cached_folder(bundle_stamp([item["key"] for item in saved]))
        st.dataframe(
            folder,
            height=min(44 * (len(folder) + 1) + 36, TABLE_HEIGHT + 80),
            hide_index=True,
            column_config=table_column_config(folder),
        )
    with st.expander("Riwayat perubahan data", expanded=False):
        changes = history_frame()
        if changes.empty:
            st.write("Belum ada perubahan impor.")
        else:
            st.dataframe(changes, height=min(44 * (len(changes) + 1) + 36, DETAIL_TABLE_HEIGHT + 80), hide_index=True)


def show_metric(
    column,
    label: str,
    value: str,
    *,
    compact: bool = False,
    hint: str | None = None,
    emphasize: bool = False,
) -> None:
    value_class = "readable-metric-value compact" if compact else "readable-metric-value"
    card_class = "metric-card target" if emphasize else "metric-card"
    hint_html = f"<div class='metric-hint'>{html.escape(str(hint))}</div>" if hint else ""
    column.markdown(
        f"<div class='{card_class}'>"
        f"<div class='readable-metric-label'>{html.escape(str(label))}</div>"
        f"<div class='{value_class}'>{value}</div>"
        f"{hint_html}"
        "</div>",
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
    """Satu baris status service level — detail di expander sidebar."""
    suggested = SUGGESTED_SERVICE[period]
    level = int(percent)
    if level == suggested:
        css = "side-best"
        headline = f"Sesuai saran {suggested}%."
    elif level < suggested:
        css = "side-low"
        headline = f"Di bawah saran {suggested}% — cadangan lebih tipis."
    else:
        css = "side-warn"
        headline = f"Di atas saran {suggested}% — stok bisa mengendap."
    if impact is None or not synced:
        if not synced and has_result:
            return css, f"{headline} Jalankan analisis ulang."
        if not has_result:
            return css, f"{headline} Jalankan analisis untuk angka."
        return css, headline
    if metric == "sales":
        figures = (
            f"Top {impact['items']}: prediksi {format_idr(impact['pred_sales'])} · "
            f"stok {format_idr(impact['stok_sales'])}."
        )
    else:
        figures = (
            f"Top {impact['items']}: prediksi {format_number(impact['pred_qty'])} · "
            f"cadangan {format_number(impact['buffer'])} · stok {format_number(impact['stok'])}."
        )
    return css, f"{headline} {figures}"


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
    wanted = [
        "item_key",
        "pred_qty",
        "pred_sales",
        "model_qty",
        "model_sales",
        "mape_qty",
        "mape_sales",
        "mae_qty",
        "rmse_qty",
        "next_period",
    ]
    if isinstance(combined, pd.DataFrame) and not combined.empty:
        forecast_cols = [c for c in wanted if c in combined.columns]
        if "item_key" in forecast_cols:
            view = view.merge(combined[forecast_cols], on="item_key", how="left")
    stock_cols = ["item_key"]
    if isinstance(stock, pd.DataFrame) and not stock.empty:
        for optional in ("safety_stock", "stok_disarankan", "stok_aktual", "reorder", "prioritas"):
            if optional in stock.columns:
                stock_cols.append(optional)
        if len(stock_cols) > 1:
            view = view.merge(stock[stock_cols], on="item_key", how="left")
    if (
        isinstance(history, pd.DataFrame)
        and not history.empty
        and "period_start" in history.columns
        and last_period is not None
    ):
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
        ("prioritas", "pantau"),
    ):
        if column not in view.columns:
            view[column] = default
        else:
            view[column] = view[column].fillna(default)
    view["pred_qty"] = np.rint(pd.to_numeric(view["pred_qty"], errors="coerce").fillna(0)).astype(int).clip(lower=0)
    view["pred_sales"] = np.rint(pd.to_numeric(view["pred_sales"], errors="coerce").fillna(0)).astype(int).clip(lower=0)
    view["safety_stock"] = np.rint(pd.to_numeric(view["safety_stock"], errors="coerce").fillna(0)).astype(int).clip(lower=0)
    view["stok_disarankan"] = (view["pred_qty"].astype(int) + view["safety_stock"].astype(int)).clip(lower=0)
    if "stok_aktual" in view.columns:
        actual = view["stok_aktual"]
        filled = actual.notna()
        view.loc[filled, "reorder"] = (
            view.loc[filled, "stok_disarankan"].astype(int) - actual.loc[filled].fillna(0).astype(int)
        ).clip(lower=0)
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
    if view is None or view.empty:
        return pd.DataFrame()
    period_name = PERIOD_SPECS[period].label.lower()
    frame = {
        "Peringkat": view["peringkat"].astype(int),
        "Produk": [
            ranked_name(rank, name) for rank, name in zip(view["peringkat"], view["product_name"])
        ],
        "Variasi": view["variasi_tampil"] if "variasi_tampil" in view.columns else "",
        "Referensi SKU": view["sku"] if "sku" in view.columns else "",
        "QTY terjual": view["qty_total"].astype(int),
        "Sales volume": view["sales_total"].round().astype(int),
        f"Prediksi QTY ({period_name})": view["pred_qty"].astype(int),
        f"Prediksi sales volume ({period_name})": view["pred_sales"].round().astype(int),
        f"Cadangan ({period_name})": view["safety_stock"].astype(int),
        f"Stok disarankan ({period_name})": view["stok_disarankan"].astype(int),
    }
    has_actual = "stok_aktual" in view.columns and view["stok_aktual"].notna().any()
    if has_actual:
        frame["Stok aktual"] = view["stok_aktual"].fillna(0).astype(int)
        if "reorder" in view.columns:
            frame["Reorder"] = view["reorder"].fillna(0).astype(int)
        if "prioritas" in view.columns:
            frame["Prioritas"] = view["prioritas"].fillna("pantau").map(format_priority_label)
    if "mape_qty" in view.columns:
        frame["MAPE holdout (%)"] = pd.to_numeric(view["mape_qty"], errors="coerce").fillna(0).round(1)
    return pd.DataFrame(frame)


def service_z(percent: int) -> float:
    """Ubah tingkat layanan (%) menjadi z-score Normal.

    Sampai 100% memakai Φ⁻¹. Di atas 100% cadangan terus naik dari batas 99,9%.
    """
    try:
        level = int(percent)
    except (TypeError, ValueError):
        return 0.0
    if level <= 0:
        return 0.0
    z_cap = float(NormalDist().inv_cdf(0.999))
    if level >= 100:
        return z_cap * (level / 100.0)
    # Clamp away from 0/1 endpoints for inv_cdf stability.
    p = min(max(level / 100.0, 1e-6), 1.0 - 1e-6)
    return float(NormalDist().inv_cdf(p))


def _actual_stock_map() -> dict[str, float]:
    try:
        raw = st.session_state.get("actual_stock") or {}
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        try:
            if value is None or (isinstance(value, float) and not np.isfinite(value)):
                continue
            parsed = float(value)
            if not np.isfinite(parsed):
                continue
            out[str(key)] = parsed
        except (TypeError, ValueError):
            continue
    return out


def _stock_for(analysis: dict, percent: int) -> pd.DataFrame:
    """Hitung ulang cadangan dari tren yang sudah tersimpan. Persentase hanya mengubah z."""
    return recommend_stock(
        analysis.get("base_history", pd.DataFrame()),
        analysis["combined"],
        analysis.get("base_period", "hari"),
        service_level_z=service_z(percent),
        horizon_steps=int(analysis.get("horizon_steps", HORIZON_DAYS[analysis["period"]])),
        actual_stock=_actual_stock_map(),
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
    if view is None or view.empty:
        fig = go.Figure()
        fig.update_layout(title=f"QTY actual vs prediksi ({scope_label})")
        return polish_chart(fig, height=320, margin_left=40, margin_bottom=40)
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
    if view is None or view.empty:
        fig = go.Figure()
        fig.update_layout(title=f"Sales actual vs prediksi ({scope_label})")
        return polish_chart(fig, height=320, margin_left=40, margin_bottom=40)
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


def _place_combo_labels(
    fig: go.Figure,
    labels,
    sales,
    sales_texts,
    qty,
    qty_texts,
) -> None:
    """Sales naik dari dasar batang. QTY berada di atas garis, supaya dua angka tidak bertumpuk."""
    count = len(list(labels))
    wide = count <= 8
    sales_peak = float(max(sales) or 1)
    show_qty = 0 < count <= 16
    for label, amount, sales_text, qty_value, qty_text in zip(labels, sales, sales_texts, qty, qty_texts):
        if sales_text and float(amount) > 0:
            fig.add_annotation(
                x=label,
                y=0,
                yref="y",
                text=sales_text,
                textangle=0 if wide else -90,
                showarrow=False,
                xanchor="center",
                yanchor="bottom",
                yshift=12 if wide else 8,
                font=dict(size=13 if wide else 11, color="#1f2937"),
                bgcolor="rgba(255,255,255,0.92)",
                borderpad=2,
            )
        if show_qty and qty_text:
            short_bar = float(amount) < sales_peak * 0.28
            fig.add_annotation(
                x=label,
                y=float(qty_value),
                yref="y2",
                text=qty_text,
                textangle=0,
                showarrow=False,
                xanchor="center",
                yanchor="bottom",
                yshift=22 if short_bar else 14,
                font=dict(size=13, color="#1e3a8a"),
                bgcolor="rgba(255,255,255,0.94)",
                borderpad=2,
            )


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
    fig.add_trace(
        go.Scatter(
            name="QTY",
            x=list(labels),
            y=qty_series,
            mode="lines+markers",
            yaxis="y2",
            marker=dict(size=11, color="#4C78A8", line=dict(width=1, color="#ffffff")),
            line=dict(color="#4C78A8", width=3),
            customdata=qty_hover,
            hovertemplate="%{x}<br>QTY: %{customdata}<extra></extra>",
        )
    )
    if any(_sales_text) or any(qty_hover):
        _place_combo_labels(fig, labels, sales_series, _sales_text, qty_series, qty_hover)
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
    qty_upper = max(qty_peak * 1.48, (qty_ticks[-1] * 1.2) if qty_ticks else qty_peak)
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
    apply_integer_axis(fig, "y", sales_peak, pad=1.28)
    return polish_chart(fig, height=540, margin_top=118, margin_bottom=78, margin_right=72)


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
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if pd.isna(start_ts) or pd.isna(end_ts) or end_ts < start_ts:
        return pd.DataFrame(columns=["date", "qty", "sales"])
    dates = pd.date_range(start_ts, end_ts, freq="D")
    if len(dates) == 0:
        return pd.DataFrame(columns=["date", "qty", "sales"])
    daily, series_start = sku_daily_qty(item_orders)
    try:
        target_qty = float(chosen.get("pred_qty", 0.0) or 0.0)
    except (TypeError, ValueError):
        target_qty = 0.0
    try:
        target_sales = float(chosen.get("pred_sales", 0.0) or 0.0)
    except (TypeError, ValueError):
        target_sales = 0.0
    if not np.isfinite(target_qty):
        target_qty = 0.0
    if not np.isfinite(target_sales):
        target_sales = 0.0
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
        if caption:
            st.caption(caption)
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


def main() -> None:
    configure_page()
    show_brand_header()

    with st.sidebar:
        st.markdown(
            "<div class='page-title' style='font-size:1.15rem;margin:0 0 0.35rem'>Siapkan analisis</div>",
            unsafe_allow_html=True,
        )
        st.markdown("<div class='side-section'>Laporan</div>", unsafe_allow_html=True)
        uploaded = st.file_uploader(
            "CSV / Excel Shopee",
            type=["csv", "xlsx", "xls"],
            accept_multiple_files=True,
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

        st.markdown("<div class='side-section'>Periode & layanan</div>", unsafe_allow_html=True)
        period = st.selectbox(
            "Periode prediksi",
            options=list(PERIOD_OPTIONS),
            format_func=lambda key: PERIOD_SPECS[key].label,
            index=0,
        )
        sidebar_metric = st.radio(
            "Peringkat Top 50",
            options=["qty", "sales"],
            format_func=lambda key: "QTY" if key == "qty" else "Sales",
            horizontal=True,
            key="rank-metric",
        )
        suggested_service = SUGGESTED_SERVICE[period]
        service = int(
            st.number_input(
                "Service level (%)",
                min_value=0,
                max_value=500,
                value=suggested_service,
                step=1,
                key=f"safety-stock-{period}",
                help="Diubah ke z-score Normal; cadangan = z × sigma × √hari. Saran mengikuti periode.",
            )
        )

        # Library dulu (bisa mengubah source_key), lalu status singkat + CTA di atas fold.
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
            with st.expander("Data tersimpan", expanded=False):
                library_year = st.selectbox("Tahun", years, key="library-year")
                month_keys = [item["key"] for item in saved_months if year_of(item["key"]) == library_year]
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
            # Hormati pilihan bulan meski expander tertutup (widget tetap di session).
            if "active-library-keys" in st.session_state and st.session_state["active-library-keys"]:
                active = tuple(st.session_state["active-library-keys"])
                loaded_source, loaded_orders = cached_library_frames(active, bundle_stamp(list(active)))
                if not loaded_source.empty and not files:
                    source_raw = loaded_source
                    orders_raw = loaded_orders
                    source_key = "library:" + ",".join(active)
        if (
            isinstance(source_raw, pd.DataFrame)
            and not source_raw.empty
            and (not isinstance(orders_raw, pd.DataFrame) or orders_raw.empty)
        ):
            rebuilt = clean_order_frame(source_raw)
            if not rebuilt.empty:
                orders_raw = rebuilt

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
            f"<div class='{safety_class}'>Saran {suggested_service}% · {safety_text}</div>",
            unsafe_allow_html=True,
        )
        run = st.button("Jalankan analisis → capai target", type="primary", use_container_width=True)

    today = date.today()
    window_start, window_end, period_text = forecast_window(period, today)

    if not run and "analysis" not in st.session_state:
        sheet_header(
            "Siap mencapai target",
            kicker="Mulai di sini",
            target="Jalankan analisis → capai target",
        )
        date_col, period_col = st.columns([1, 2.2])
        show_metric(date_col, "Tanggal hari ini", format_id_date(today))
        period_col.markdown(
            "<div class='metric-card target'>"
            "<div class='readable-metric-label'>Horizon</div>"
            f"<div class='period-name'>{PERIOD_SPECS[period].label}</div>"
            f"<div class='period-dates'>{format_id_date(window_start)} – {format_id_date(window_end)}</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<div class='cta-panel'>"
            "<div class='cta-title'>Langkah berikutnya</div>"
            "<p class='cta-body'>Klik tombol di sidebar untuk Top 50, stok, dan reorder.</p>"
            "</div>",
            unsafe_allow_html=True,
        )
        with st.expander("Kolom laporan yang dikenali", expanded=False):
            st.markdown(
                "- Waktu Pesanan Dibuat\n"
                "- Nama Produk, Nomor Referensi SKU, Nama Variasi\n"
                "- Jumlah, Harga Setelah Diskon / Total Harga\n"
                "- Status Pesanan"
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
                "<div class='metric-card'>"
                "<div class='readable-metric-label'>Periode prediksi</div>"
                f"<div class='period-name'>{PERIOD_SPECS[period].label}</div>"
                f"<div class='period-dates'>{format_id_date(window_start)} – {format_id_date(window_end)}</div>"
                "</div>",
                unsafe_allow_html=True,
            )
            if sheet != "Data":
                if "exclude-return-batal" not in st.session_state:
                    st.session_state["exclude-return-batal"] = exclude_return_cancel
                exclude_return_cancel = bool(
                    st.checkbox(
                        "Exclude return dan batal",
                        key="exclude-return-batal",
                        help="Kurangi batal & retur pada header, Top 50, dan Prediksi & stok.",
                    )
                )
                st.session_state["exclude_applied"] = exclude_return_cancel

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

    analysis_cache_key = (
        str(source_key),
        str(period),
        str(sidebar_metric),
        bool(exclude_return_cancel),
        int(horizon_day_count(period, today)),
    )

    # Hasil analisis di session_state: pindah menu / ubah service level tidak hitung ulang forecast.
    # Jalankan analisis atau ubah exclude memaksa hot path baru.
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

        with st.spinner(f"Prediksi {FORECAST_CANDIDATE_LIMIT} SKU teratas (Level terkini)..."):
            bar = st.progress(0.0, text="Level 28 hari terakhir — kandidat teratas")

            def on_qty(pct: float) -> None:
                bar.progress(min(pct * 0.9, 0.9), text="Level 28 hari terakhir — kandidat teratas")

            qty_fc = forecast_items(
                base_history,
                base_period,
                "qty",
                progress_callback=on_qty,
                steps=horizon_steps,
                next_label=period_text,
                forecast_start=pd.Timestamp(window_start),
                max_items=FORECAST_CANDIDATE_LIMIT,
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
            actual_stock=_actual_stock_map(),
        )
        # Bandingkan algoritma klasik hanya on-demand di tab Evaluasi (bukan hot path).
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
            "cache_key": analysis_cache_key,
            "candidate_limit": FORECAST_CANDIDATE_LIMIT,
            "model_name": MODEL_NAME,
        }
        st.rerun()
    else:
        stored = st.session_state["analysis"]
        orders = stored["orders"]
        history = stored["history"]
        combined = stored["combined"]
        stock = stored["stock"]
        board = stored.get("board", pd.DataFrame())
        comparison = stored.get("comparison", pd.DataFrame())
        period = stored["period"]
        metric = stored.get("metric", "qty")
        horizon_steps = int(stored.get("horizon_steps", 1))
        base_period = stored.get("base_period", period)
        period_text = stored.get("period_text") or forecast_window(period)[2]

    if filters_changed:
        st.warning("Input berubah. Klik **Jalankan analisis** untuk menghitung ulang prediksi.")

    show_resume = sheet in {"Ringkasan", "Prediksi & stok"}
    sales_orders, resume_label = filter_resume_orders(orders, show_controls=show_resume)
    if not resume_label:
        resume_label = "seluruh data input"

    last_period = history["period_start"].max()
    catalog = top_bestsellers(sales_orders, combined, stock, history, metric, last_period, period, top_n=None)
    shown = catalog.head(TOP_N).reset_index(drop=True)
    if sheet in SUMMARY_SHEETS and sheet != "Data":
        k1, k2, k3, k4 = st.columns(4)
        show_metric(k1, "Jumlah pesanan", format_number(count_orders(sales_orders), 0))
        show_metric(
            k2,
            "Produk / varian",
            f"{sales_orders['item_key'].nunique():,}".replace(",", ".") if not sales_orders.empty else "0",
        )
        show_metric(k3, "Sales volume", format_idr(order_revenue(sales_orders)))
        show_metric(
            k4,
            "QTY terjual",
            format_qty(float(sales_orders["qty"].sum()) if "qty" in sales_orders.columns and not sales_orders.empty else 0),
        )

    if sheet == "Ringkasan":
        summary_gen = st.session_state.setdefault("summary_gen", 0)
        selected_key = None
        selected_label = None
        view = shown.sort_values(["peringkat", "item_key"], kind="mergesort").reset_index(drop=True)

        last_qty = float(view["qty_total"].sum()) if not view.empty else 0.0
        last_sales = float(view["sales_total"].sum()) if not view.empty else 0.0
        pred_qty_value = float(view["pred_qty"].sum()) if not view.empty else 0.0
        pred_sales_value = float(view["pred_sales"].sum()) if not view.empty else 0.0
        pareto_sales = pareto_share(sales_orders, "sales", TOP_N)

        sheet_header(
            "Ringkasan Top 50",
            f"{resume_label} → {period_text}",
            kicker="Gambaran toko",
        )
        m1, m2, m3, m4, m5 = st.columns([1.05, 1.2, 1.05, 1.35, 1.15])
        show_metric(m1, "QTY actual", format_qty(last_qty))
        show_metric(m2, "Sales actual", format_idr(last_sales))
        show_metric(m3, "Prediksi QTY", format_qty(pred_qty_value), emphasize=True)
        show_metric(m4, "Prediksi sales", format_idr(pred_sales_value), emphasize=True)
        show_metric(
            m5,
            "Pareto Top 50",
            f"{format_number(pareto_sales['share_pct'], 1)}%",
            emphasize=True,
        )

        with st.expander("Insight: batal, retur, unpaid, harga", expanded=False):
            active_keys = tuple(st.session_state.get("active-library-keys") or ())
            if active_keys:
                insight_ledger = cached_ledger(active_keys, bundle_stamp(list(active_keys)))
            elif isinstance(source_raw, pd.DataFrame) and not source_raw.empty:
                insight_ledger = ledger_from_raw(source_raw)
            else:
                insight_ledger = pd.DataFrame()
            loss = cancel_return_insight(insight_ledger)
            unpaid = unpaid_concentration(source_raw if isinstance(source_raw, pd.DataFrame) else pd.DataFrame())
            c1, c2, c3 = st.columns(3)
            show_metric(c1, "Kontribusi batal", f"{format_number(loss['cancel_share_pct'], 1)}%", hint=format_idr(loss["cancel_sales"]))
            show_metric(c2, "Kontribusi retur", f"{format_number(loss['return_share_pct'], 1)}%", hint=f"{format_qty(loss['return_qty'])} unit")
            show_metric(c3, "Pembeli unpaid", format_number(unpaid["buyers"], 0), hint=format_idr(unpaid["sales"]))
            reason_cols = st.columns(2)
            with reason_cols[0]:
                st.caption("Alasan batal teratas")
                st.dataframe(top_reason_table(insight_ledger, "cancel", 5), height=220, hide_index=True)
            with reason_cols[1]:
                st.caption("Alasan retur teratas")
                st.dataframe(top_reason_table(insight_ledger, "return", 5), height=220, hide_index=True)
            if isinstance(unpaid.get("top"), pd.DataFrame) and not unpaid["top"].empty:
                st.caption("Konsentrasi unpaid buyer")
                st.dataframe(unpaid["top"], height=220, hide_index=True)
            price_trend = unit_price_trend(sales_orders, 8)
            if not price_trend.empty:
                st.caption("Tren harga unit (SKU terlaris)")
                st.dataframe(price_trend, height=240, hide_index=True)

        if view.empty:
            st.info("Tidak ada item pada periode penjualan ini. Perlebar filter tahun/bulan/tanggal.")
        elif metric == "sales":
            show_section_title("Grafik sales Top 50")
            st.plotly_chart(item_sales_chart(view.head(TOP_N), "total Top 50"), use_container_width=True)
        else:
            show_section_title("Grafik QTY Top 50")
            st.plotly_chart(item_qty_chart(view.head(TOP_N), "total Top 50"), use_container_width=True)

        with st.expander("Tabel Top 50", expanded=False):
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
                row_height = 38
                picked = st.dataframe(
                    summary_source,
                    height=min(row_height * (len(table_view) + 1) + 36, TABLE_HEIGHT + 80),
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

        with st.expander("Grafik detail SKU terpilih", expanded=bool(selected_key)):
            if selected_key is None:
                st.info("Buka tabel Top 50 dan pilih satu baris untuk grafik detail.")
            else:
                chosen = view[view["item_key"] == selected_key].iloc[0]
                scope_label = selected_label or "SKU"
                st.subheader(scope_label)
                scope_orders = sales_orders[sales_orders["item_key"] == selected_key]
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
                    show_metric(actual_cols[1], "Total QTY actual", format_qty(actual_qty_total))
                else:
                    st.plotly_chart(daily_actual_chart(scope_orders, scope_label, "qty"), use_container_width=True)
                    show_metric(st, "Total QTY actual", format_qty(actual_qty_total))
                    st.plotly_chart(daily_actual_chart(scope_orders, scope_label, "sales"), use_container_width=True)
                    show_metric(st, "Total sales volume actual", format_idr(actual_sales_total))
                grain = "hari"
                interval_options = prediction_interval_options(period)
                if period == "bulan":
                    show_section_title(
                        f"Prediksi {format_id_date(window_start)} – {format_id_date(window_end)}"
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
                        f"Prediksi {interval_name} · {PERIOD_SPECS[period].label}"
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
        sheet_header(
            "Prediksi & stok",
            f"Top {TOP_N} · SL {format_number(applied_service)}% · {period_text}",
            kicker=resume_label,
        )
        st.markdown(
            "<div class='target-rail'>"
            "<span class='priority-badge priority-tinggi'>Tinggi</span>"
            "<span class='priority-badge priority-sedang'>Sedang</span>"
            "<span class='priority-badge priority-pantau'>Pantau</span>"
            "</div>",
            unsafe_allow_html=True,
        )
        preview = sort_leaderboard(catalog.head(TOP_N), "qty_desc" if metric == "qty" else "sales_desc")
        if preview.empty:
            st.info("Tidak ada item untuk ditampilkan pada filter penjualan ini.")
        else:
            with st.expander("Stok aktual → reorder", expanded=False):
                editor_src = preview[["item_key", "sku", "product_name", "stok_disarankan"]].copy()
                editor_src["stok_aktual"] = editor_src["item_key"].map(
                    lambda key: _actual_stock_map().get(str(key), 0)
                ).astype(int)
                edited = st.data_editor(
                    editor_src.rename(
                        columns={
                            "sku": "Referensi SKU",
                            "product_name": "Produk",
                            "stok_disarankan": "Stok disarankan",
                            "stok_aktual": "Stok aktual",
                        }
                    )[["Referensi SKU", "Produk", "Stok disarankan", "Stok aktual"]],
                    height=min(38 * (len(editor_src) + 1) + 36, TABLE_HEIGHT),
                    hide_index=True,
                    disabled=["Referensi SKU", "Produk", "Stok disarankan"],
                    key="actual-stock-editor",
                )
                if st.button("Terapkan stok aktual", type="secondary"):
                    mapping = dict(st.session_state.get("actual_stock") or {})
                    for item_key, actual in zip(editor_src["item_key"], edited["Stok aktual"]):
                        try:
                            mapping[str(item_key)] = max(int(actual), 0)
                        except (TypeError, ValueError):
                            mapping[str(item_key)] = 0
                    st.session_state["actual_stock"] = mapping
                    refreshed, _impact = safety_view(st.session_state["analysis"], applied_service, metric)
                    if refreshed is not None:
                        st.session_state["analysis"]["stock"] = refreshed
                        stock = refreshed
                        catalog = top_bestsellers(
                            sales_orders, combined, stock, history, metric, last_period, period, top_n=None
                        )
                        preview = sort_leaderboard(
                            catalog.head(TOP_N), "qty_desc" if metric == "qty" else "sales_desc"
                        )
                    st.rerun()

            display = leaderboard_frame(preview, period)
            st.dataframe(
                display,
                height=TABLE_HEIGHT,
                row_height=38,
                hide_index=True,
                column_config=table_column_config(display, roomy=True),
            )
            with st.expander("Holdout MAPE / RMSE", expanded=False):
                metric_cols = {
                    "peringkat": "Peringkat",
                    "sku": "Referensi SKU",
                    "product_name": "Produk",
                    "model_qty": "Model",
                    "mape_qty": "MAPE (%)",
                    "rmse_qty": "RMSE",
                }
                available = [c for c in metric_cols if c in preview.columns]
                if available:
                    st.dataframe(
                        preview[available].rename(columns=metric_cols),
                        height=DETAIL_TABLE_HEIGHT,
                        hide_index=True,
                    )
            csv = display.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "Unduh Top 50 (CSV)",
                csv,
                file_name="rekomendasi_stok.csv",
                mime="text/csv",
            )

    elif sheet == "Evaluasi model":
        period_name = PERIOD_SPECS[period].label
        period_days = horizon_day_count(period)
        sheet_header(
            "Evaluasi model",
            f"{MODEL_NAME} · {period_name} ({period_days} hari)",
            kicker="Kualitas model",
        )
        metric_wanted = ["item_key", "item_label", "model_qty", "mape_qty", "rmse_qty", "mae_qty", "pred_qty"]
        metric_have = [c for c in metric_wanted if isinstance(combined, pd.DataFrame) and c in combined.columns]
        if "item_key" in metric_have and "mape_qty" in metric_have:
            qty_metrics = combined[metric_have].copy()
            qty_metrics = qty_metrics.sort_values("mape_qty", ascending=False)
        else:
            qty_metrics = pd.DataFrame(columns=metric_wanted)
        avg_mape = float(pd.to_numeric(qty_metrics.get("mape_qty"), errors="coerce").mean()) if not qty_metrics.empty else 0.0
        avg_rmse = float(pd.to_numeric(qty_metrics.get("rmse_qty"), errors="coerce").mean()) if not qty_metrics.empty else 0.0
        if not np.isfinite(avg_mape):
            avg_mape = 0.0
        if not np.isfinite(avg_rmse):
            avg_rmse = 0.0
        e1, e2, e3 = st.columns(3)
        show_metric(e1, "SKU diforecast", format_number(len(qty_metrics), 0))
        show_metric(e2, "MAPE holdout rata-rata", f"{format_number(avg_mape, 1)}%")
        show_metric(e3, "RMSE holdout rata-rata", format_number(avg_rmse, 2))
        if qty_metrics.empty:
            st.info("Belum ada metrik holdout. Klik **Jalankan analisis** di sidebar.")
        else:
            show_section_title("Holdout per SKU (Top 50 terburuk MAPE)")
            st.dataframe(
                qty_metrics.head(TOP_N).rename(
                    columns={
                        "item_label": "Produk",
                        "model_qty": "Model",
                        "mape_qty": "MAPE (%)",
                        "rmse_qty": "RMSE",
                        "mae_qty": "MAE",
                        "pred_qty": "Prediksi QTY",
                    }
                ).drop(columns=["item_key"], errors="ignore"),
                height=TABLE_HEIGHT,
                hide_index=True,
            )
        if isinstance(board, pd.DataFrame) and not board.empty:
            with st.expander("Leaderboard model (qty)", expanded=False):
                st.dataframe(board, height=DETAIL_TABLE_HEIGHT, hide_index=True)

        with st.expander("Cara kerja Level terkini & cadangan", expanded=False):
            st.markdown(
                f"""
1. Kalender harian per SKU; hari kosong = 0.  
2. Level = rata-rata 28 hari terakhir (lonjakan dipotong kuantil 90%).  
3. Kemiringan hanya jika riwayat ≥ 28 hari; ujung horizon ±15% level.  
4. Jumlahkan {period_days} hari sejak hari ini; jepit 0,6–1,6× run-rate.  
5. Cadangan = z(service level) × sigma residual × √hari.
"""
            )

        show_section_title("Benchmark klasik")
        base_history = st.session_state["analysis"].get("base_history", pd.DataFrame())
        if st.button("Jalankan pembanding algoritma (lazy)", type="secondary"):
            with st.spinner("Menguji pembanding pada total toko..."):
                try:
                    comparison = compare_daily_algorithms(base_history)
                except Exception:
                    comparison = pd.DataFrame()
                st.session_state["analysis"]["comparison"] = comparison
                st.rerun()
        comparison = st.session_state["analysis"].get("comparison", pd.DataFrame())
        if comparison is None or (isinstance(comparison, pd.DataFrame) and comparison.empty):
            st.info("Belum ada hasil pembanding. Klik tombol di atas bila kalender harian ≥ 8 hari.")
        else:
            present = set(comparison["Algoritma"].astype(str))
            if not (present & {"ARIMA", "SARIMA", "XGBoost"}):
                gate_note = "ARIMA/XGBoost tidak masuk (data latih di luar 12–90 hari). Holt tetap dihitung."
            else:
                gate_note = "ARIMA/XGBoost masuk (data latih 12–90 hari)."
            closest = comparison.sort_values(["Selisih (%)", "Algoritma"]).iloc[0]
            st.caption(
                f"Terdekat: {closest['Algoritma']} ({format_number(float(closest['Selisih (%)']), 1)}%). "
                f"Produksi tetap {MODEL_NAME}."
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
                height=TABLE_HEIGHT,
                hide_index=True,
            )

    elif sheet == "Data":
        if source_raw.empty:
            sheet_header(
                "Data",
                "Belum ada file aktif.",
                kicker="Data toko",
                target=SHEET_TARGETS["Data"],
            )
            st.info("Pilih bulan di Folder data atau unggah laporan, lalu **Jalankan analisis**.")
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


if __name__ == "__main__":
    main()
