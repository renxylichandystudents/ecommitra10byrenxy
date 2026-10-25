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
from src.ingest import (
    available_statuses,
    default_statuses,
    filter_by_statuses,
    load_shopee_report,
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
        fig.update_layout(yaxis2={**spec, "overlaying": "y", "side": "right", "title": "Sales volume (Rp)"})
    else:
        fig.update_yaxes(**spec)


@st.cache_data(show_spinner=False)
def parse_upload(file_bytes: bytes, filename: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    return load_shopee_report(file_bytes, filename=filename)


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


def _impact_from(shown: pd.DataFrame, stock: pd.DataFrame) -> dict[str, int | float]:
    indexed = stock.set_index("item_key")
    raw = indexed.reindex(shown["item_key"])["safety_stock"].fillna(0).astype(float)
    pred_qty = int(shown["pred_qty"].sum())
    buffer = int(shown["safety_stock"].sum())
    stok = int(shown["stok_disarankan"].sum())
    return {
        "items": int(len(shown)),
        "demand_qty": pred_qty,
        "buffer": buffer,
        "buffer_raw": float(raw.sum()),
        "pred_qty": pred_qty,
        "pred_sales": int(shown["pred_sales"].sum()),
        "stok": stok,
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
    plot = view.sort_values(["qty_histori", "pred_qty"], ascending=[True, True])
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
    actual = plot["qty_histori"].astype(float)
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
    }
    for column, width in widths.items():
        if column in frame.columns:
            config[column] = st.column_config.TextColumn(column, width=width)
    return config


st.title("Prediksi Stok & Item Terlaris Shopee")
st.caption(
    "Unggah laporan transaksi Shopee, pilih dasar peringkat (QTY terjual atau sales volume), periode, "
    "dan status pesanan. Aplikasi menampilkan 50 item terlaris beserta stok yang harus disiapkan."
)

with st.sidebar:
    st.header("Input")
    uploaded = st.file_uploader(
        "Laporan Shopee",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
    )
    st.markdown(
        "<div class='upload-note'>Unggah satu atau beberapa file CSV, XLSX, atau XLS. "
        "Maksimal 50 lampiran, total 1 GB.</div>",
        unsafe_allow_html=True,
    )
    metric = st.radio(
        "Dasar peringkat",
        options=list(METRIC_LABELS.keys()),
        format_func=lambda key: METRIC_LABELS[key],
        index=0,
        help="Mengurutkan Top 50 dari seluruh laporan. QTY terjual atau sales volume tertinggi di atas. Peringkat selalu unik.",
    )
    period = st.selectbox(
        "Periode prediksi",
        options=list(PERIOD_OPTIONS),
        format_func=lambda key: PERIOD_SPECS[key].label,
        index=0,
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
    status_options = available_statuses(orders_raw)
    st.markdown("**Status pesanan**")
    if not status_options and not load_error:
        st.caption("Status pesanan muncul setelah laporan berhasil dibaca.")
    kept_by_default = set(default_statuses(status_options))
    selected_statuses = []
    for status in status_options:
        checked = st.checkbox(
            status,
            value=status in kept_by_default,
            key=f"status-{source_key}-{status}",
        )
        if checked:
            selected_statuses.append(status)
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
            and set(stored_analysis.get("statuses") or []) == set(selected_statuses)
    )
    safety_impact = None
    if safety_synced:
        refreshed_stock, safety_impact = safety_view(stored_analysis, service, metric)
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
    )
    st.markdown(
        f"<div class='{safety_class}'><b>Suggest safety stock adalah {suggested_service}%.</b><br>{safety_text}</div>",
        unsafe_allow_html=True,
    )
    run = st.button("Jalankan analisis", type="primary", use_container_width=True)

today = date.today()
window_start, window_end, period_text = forecast_window(period, today)
date_col, period_col = st.columns([1, 2.2])
show_metric(date_col, "Tanggal hari ini", format_id_date(today))
period_col.markdown(
    "<div class='readable-metric-label'>Periode prediksi</div>"
    f"<div class='period-name'>{PERIOD_SPECS[period].label}</div>"
    f"<div class='period-dates'>{format_id_date(window_start)} – {format_id_date(window_end)}</div>",
    unsafe_allow_html=True,
)

if not run and "analysis" not in st.session_state:
    st.info("Unggah laporan Shopee (maksimal 50 file, total 1 GB), lalu klik **Jalankan analisis**.")
    st.markdown(
        """
**Yang bisa dipilih:**
- Dasar peringkat: QTY terjual atau sales volume
- Periode: bulan, kuartal, semester, atau tahun
- Status pesanan yang dicentang

**Hasil:** 50 item terlaris, lengkap dengan prediksi QTY, sales volume, dan stok yang harus disiapkan. Perhitungan bulan, kuartal, semester, dan tahun dimulai dari tanggal hari ini.

**Kolom yang didukung (otomatis dikenali):**
- Waktu Pesanan Dibuat / Tanggal
- Nama Produk (kolom O), Nomor Referensi SKU (kolom P), Nama Variasi (kolom Q)
- Jumlah
- Total Harga atau Harga Setelah Diskon
- Status Pesanan

Produk tanpa variasi diidentifikasi dari Nomor Referensi SKU. Produk dengan varian punya nama yang sama; yang membedakan adalah Nama Variasi, dan tiap varian punya referensi SKU sendiri.
"""
    )
    st.stop()

filters_changed = (
    "analysis" in st.session_state
    and not run
    and (
        st.session_state["analysis"]["period"] != period
        or st.session_state["analysis"].get("source_key") != source_key
        or set(st.session_state["analysis"]["statuses"]) != set(selected_statuses)
    )
)

if run or "analysis" not in st.session_state:
    if load_error:
        st.error(load_error)
        st.stop()
    if orders_raw.empty:
        st.warning("Tidak ada data. Unggah laporan Shopee terlebih dahulu.")
        st.stop()
    if not selected_statuses:
        st.warning("Pilih minimal satu status pesanan.")
        st.stop()

    orders = filter_by_statuses(orders_raw, selected_statuses)
    history = aggregate_item_periods(orders, period)

    if history.empty:
        st.warning("Tidak ada transaksi untuk status pesanan yang dipilih.")
        st.stop()

    base_period = "hari"
    horizon_steps = horizon_day_count(period, today)
    base_history = aggregate_item_periods(orders, base_period)
    last_bucket = period_start(orders["order_time"], period).max()
    next_label = period_label(next_period_start(last_bucket, period), period)

    with st.spinner("Membaca pola belanja harian untuk prediksi QTY..."):
        bar = st.progress(0.0, text="Prediksi dari tren robust")

        def on_qty(pct: float) -> None:
            bar.progress(min(pct * 0.9, 0.9), text="Prediksi dari tren robust")

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
        "statuses": list(selected_statuses),
        "source_key": source_key,
        "service": service,
        "horizon_steps": horizon_steps,
        "base_period": base_period,
        "base_history": base_history,
        "period_text": period_text,
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
    horizon_steps = int(stored.get("horizon_steps", 1))
    base_period = stored.get("base_period", period)
    period_text = stored.get("period_text") or forecast_window(period)[2]

if filters_changed:
    st.warning(
        "Periode, status pesanan, atau file laporan berubah. "
        "Klik **Jalankan analisis** untuk memperbarui hasil. "
        "Perubahan safety stock saja langsung menghitung ulang cadangan dan stok disarankan."
    )

last_period = history["period_start"].max()
catalog = top_bestsellers(orders, combined, stock, history, metric, last_period, period, top_n=None)
shown = catalog.head(TOP_N).reset_index(drop=True)
sort_name = "QTY terjual tertinggi" if metric == "qty" else "sales volume tertinggi"
grain_note = (
    "Pada riwayat di bawah 28 hari, laju harian periode panjang mengikuti level yang sama. "
    "Bulan yang terpotong di ujung kalender lebih kecil karena harinya lebih sedikit."
)

k1, k2, k3, k4 = st.columns(4)
show_metric(
    k1,
    "Jumlah pesanan",
    format_number(count_orders(orders), 0),
    hint="Sekali tiap No. Pesanan",
)
show_metric(
    k2,
    "Produk / varian",
    f"{orders['item_key'].nunique():,}".replace(",", "."),
    hint="Nomor Referensi SKU",
)
show_metric(
    k3,
    "Sales volume",
    format_idr(order_revenue(orders)),
    hint="Total Pembayaran, sekali tiap No. Pesanan",
)
show_metric(
    k4,
    "QTY terjual",
    format_qty(float(orders["qty"].sum()) if "qty" in orders.columns else 0),
    hint="Jumlah unit pada Nomor Referensi SKU",
)

tab_overview, tab_pred, tab_model, tab_data = st.tabs(
    ["Ringkasan", "Prediksi & stok", "Evaluasi model", "Data"]
)

with tab_overview:
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
            f"Peringkat dihitung dari {sort_name} seluruh laporan dan selalu unik. "
            f"Prediksi QTY untuk {period_text} adalah permintaan, tanpa safety stock. "
            "Prediksi sales volume = prediksi QTY kali harga jual. "
            "Stok disarankan = prediksi QTY + safety stock. "
            f"{grain_note} "
            "Centang satu baris untuk menampilkan grafik SKU itu."
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
                key=f"summary-top50-{summary_gen}-{metric}-{period}-{show_n}",
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
        last_qty = float(view["qty_histori"].sum()) if not view.empty else 0.0
        last_sales = float(view["sales_histori"].sum()) if not view.empty else 0.0
        pred_qty_value = float(view["pred_qty"].sum()) if not view.empty else 0.0
        pred_sales_value = float(view["pred_sales"].sum()) if not view.empty else 0.0

        st.subheader("Ringkasan total Top 50")
        m1, m2, m3, m4, m5 = st.columns([1.05, 1.2, 1.05, 1.35, 1.15])
        show_metric(m1, "QTY actual", format_qty(last_qty))
        show_metric(m2, "Sales volume actual", format_idr(last_sales))
        show_metric(m3, "Prediksi QTY", format_qty(pred_qty_value))
        show_metric(m4, "Prediksi sales volume", format_idr(pred_sales_value))
        top_sales = float(view["sales_total"].sum()) if not view.empty else 0.0
        total_sales = float(orders["sales"].sum()) if "sales" in orders.columns else 0.0
        share = top_sales / total_sales * 100 if total_sales > 0 else 0.0
        show_metric(
            m5,
            "Kontribusi sales Top 50",
            f"{format_number(share, 1)}%",
            hint=f"{format_idr(top_sales)} dari {format_idr(total_sales)}, status yang dicentang",
        )
        if last_qty > 0 and last_sales > 0 and (pred_qty_value - last_qty) * (pred_sales_value - last_sales) < 0:
            st.caption(
                "Total QTY dan total sales volume berbeda arah karena campurannya berubah: "
                "produk murah dan produk mahal tidak naik atau turun bersamaan. "
                "Pada tiap produk, sales volume tetap prediksi QTY kali harga jual produk itu."
            )

        if not view.empty:
            st.caption(
                "Biru adalah QTY actual, oranye adalah prediksi. "
                "Label diawali peringkat dan Nomor Referensi SKU, lalu nama produk."
            )
            st.plotly_chart(item_qty_chart(view, "total Top 50"), use_container_width=True)

        if selected_key is None:
            st.info("Centang satu SKU pada tabel Top 50 untuk menampilkan empat grafik di bawah.")
        else:
            chosen = view[view["item_key"] == selected_key].iloc[0]
            scope_label = selected_label or "SKU"
            st.subheader(scope_label)
            scope_orders = orders[orders["item_key"] == selected_key]
            st.caption(
                "Actual per tanggal memakai data yang ada pada laporan. "
                "Jika riwayat lebih pendek dari periode prediksi, yang tampil adalah tanggal yang tersedia."
            )
            actual_qty_total = float(scope_orders["qty"].sum()) if not scope_orders.empty else 0.0
            actual_sales_total = float(scope_orders["sales"].sum()) if not scope_orders.empty else 0.0
            st.plotly_chart(daily_actual_chart(scope_orders, scope_label, "qty"), use_container_width=True)
            show_metric(st, "Total QTY actual", format_qty(actual_qty_total))
            st.plotly_chart(daily_actual_chart(scope_orders, scope_label, "sales"), use_container_width=True)
            show_metric(st, "Total sales volume actual", format_idr(actual_sales_total))
            grain = "hari"
            interval_options = prediction_interval_options(period)
            if period == "bulan":
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
                    f"Prediksi {interval_name} untuk {PERIOD_SPECS[period].label}, "
                    f"{format_id_date(window_start)} – {format_id_date(window_end)}. "
                    f"Rentang ini {horizon_day_count(period, today)} hari kalender sejak tanggal hari ini. "
                    "Pilihan di atas menyesuaikan lebar grafik. "
                    "Grafik ini menampilkan permintaan saja. Stok final = prediksi QTY + safety stock, pada tabel."
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

with tab_pred:
    applied_service = int(st.session_state["analysis"].get("service", service))
    st.subheader(
        f"Seluruh SKU menurut {METRIC_LABELS[metric]} — {period_text}"
    )
    st.caption(
        f"Menampilkan seluruh {format_number(len(catalog))} SKU pada file, diurutkan {sort_name}. "
        "Peringkat unik dihitung dari seluruh laporan. "
        f"Prediksi QTY untuk {period_text} adalah permintaan, belum termasuk safety stock {format_number(applied_service)}%. "
        "Stok disarankan = prediksi QTY + safety stock. Itulah stok final. "
        "Mengubah persentase di samping mengubah safety stock dan stok disarankan. Prediksi QTY tidak berubah. "
        "Nama lengkap ada di kolom Produk."
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

with tab_model:
    applied_service = int(st.session_state["analysis"].get("service", service))
    applied_suggestion = SUGGESTED_SERVICE.get(period, applied_service)
    period_name = PERIOD_SPECS[period].label
    period_days = horizon_day_count(period)
    z_now = service_z(applied_service)
    z_value = format_number(z_now, 2)
    factor_now = z_now * float(np.sqrt(period_days))
    if shown.empty:
        board_n = 0
        board_demand = 0
        board_buffer = 0
        board_qty = 0
        board_sales = 0
        board_stock = 0
    else:
        board_n = int(len(shown))
        board_qty = int(shown["pred_qty"].sum())
        board_sales = int(shown["pred_sales"].sum())
        board_buffer = int(shown["safety_stock"].sum())
        board_stock = int(shown["stok_disarankan"].sum())
        board_demand = board_qty
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
    st.subheader("Cara aplikasi membaca data")
    st.markdown(
        f"""
Bagian ini menjelaskan logika program dari file yang diunggah sampai angka prediksi. Perhitungan di bawah memakai hasil analisis yang sedang tampil: periode **{period_name}**, {period_days} hari, {period_text}, safety stock **{applied_service}%**.

Langkah pengambilan data:

1. File CSV atau Excel dibaca menjadi tabel. Sheet **Data** menyimpan tabel itu apa adanya, termasuk baris yang nanti tidak masuk prediksi.
2. Nama kolom dikenali dari judul laporan Shopee. **No. Pesanan** menjadi identitas pesanan. **Nomor Referensi SKU** dan **Nama Variasi** menjadi identitas produk. Variasi kosong tetap satu produk. Variasi terisi dipisah dengan kunci `SKU||nama variasi`, sehingga varian tidak digabung.
3. **Jumlah** menjadi QTY. Nilai jual satu baris adalah **Harga Setelah Diskon × Jumlah**. Sales volume pesanan mengambil **Total Pembayaran** satu kali tiap No. Pesanan. Kalau pembayaran kosong atau nol, sales volume pesanan dijumlah dari nilai baris pesanan itu.
4. Hanya **Status Pesanan** yang dicentang yang masuk agregasi dan prediksi.
5. Waktu pesanan dipotong per hari. Program menyusun kalender dari hari pertama sampai hari terakhir, lalu mengisi hari tanpa order dengan nol. Nol itu sengaja disimpan supaya rata-rata tidak hanya dihitung pada hari yang ada penjualan.
6. Prediksi periode berjalan di atas deret harian itu. Panjang periode dihitung dari tanggal hari ini sampai satu bulan, tiga bulan, enam bulan, atau dua belas bulan kalender, lalu dikurangi satu hari.
"""
    )
    st.subheader("Algoritma yang dipakai: Tren robust")
    st.markdown(
        f"""
**Konsep.** Tren robust memperkirakan permintaan harian dari level penjualan, pola hari dalam seminggu, dan kemiringan yang hanya dipakai bila buktinya cukup. Level menjawab “berapa unit yang biasa terjual sehari”. Pola hari menaikkan atau menurunkan hari yang memang ramai. Kemiringan menjawab “apakah penjualan benar-benar naik atau turun”, dan pada riwayat di bawah 28 hari kemiringannya nol.

**Alasan dipilih.** Laporan yang pendek, hari promo, dan hari terakhir yang terpotong mudah membuat periode panjang terlihat turun bulan demi bulan. Tren harian membaca selisih paruh awal dan paruh akhir, lalu mengalikannya dengan redaman yang membesar seiring hari ke depan. Pada lampiran sekitar tiga minggu, paruh akhir sering lebih sepi daripada hari promo di paruh awal, sehingga bulan kedua dan ketiga pada kuartal ikut jatuh. Tren robust menahan itu. Lonjakan dipotong di kuantil 90% hari yang ada penjualan. Hari terakhir yang jauh di bawah median, pada deret yang hampir setiap hari ada transaksi, tidak masuk garis. Kemiringan Theil-Sen baru hidup setelah 28 hari, dan pada hari terjauh pergeserannya ditahan di 15% level.

**Atribut yang dipakai.** Tanggal pesanan, hari dalam seminggu, Nomor Referensi SKU, Nama Variasi, Jumlah bersih setelah Returned quantity, Harga Setelah Diskon untuk sales volume, dan Status Pesanan yang dicentang. Kota, pembayaran, pengiriman, voucher, dan identitas pembeli tidak menggeser prediksi.

**Cara hitung**, untuk satu SKU:

1. Kalender diisi dari hari pertama sampai hari terakhir. Hari tanpa order bernilai nol.
2. Bila deretnya padat dan hari terakhir di bawah 30% median hari sebelumnya, hari itu dikeluarkan. Ini menutup ekspor yang terputus, bukan hari nol pada SKU yang jarang laku.
3. Nilai di atas kuantil 90% dari hari yang ada penjualan dipotong, lalu `level = rata-rata hari yang sudah dipotong`.
4. Bila hari yang dipakai kurang dari 28, kemiringan = 0. Bila cukup, kemiringan = median kemiringan semua pasangan hari (Theil-Sen), dikecilkan bila riwayat masih di bawah 8 minggu.
5. Perkiraan hari ke-t, dengan redaman φ = 0,985: `max(0, (level + kemiringan × (1 − φ^t) / (1 − φ)) × profil hari)`. Sebelum dipakai, kemiringan diturunkan supaya hari terjauh tidak bergeser lebih dari 15% level.
6. Jumlah harian itu dijumlahkan sepanjang {period_days} hari sejak tanggal hari ini, lalu dijepit pada 0,6 kali sampai 1,6 kali `level × jumlah hari`.
7. Prediksi sales volume = prediksi QTY × harga rata-rata yang terbeli. Harga tidak diramal terpisah.

Pada lampiran yang lebih pendek dari 28 hari, prediksi kuartal, semester, dan tahun mengikuti level harian yang sama. Total bulan berbeda hanya karena jumlah hari dan pola Senin–Minggu, bukan karena garisnya terus menurun.
"""
    )
    st.subheader("Safety stock dan stok final")
    st.markdown(
        f"""
**Konsep.** Prediksi QTY adalah permintaan. Safety stock adalah cadangan. Stok disarankan = prediksi QTY + safety stock, dan angka itulah stok final. Tiga kolom itu tidak disamakan. Persentase yang diisi mengubah safety stock dan stok disarankan. Prediksi QTY tetap.

**Alasan rumus ini.** Sigma diukur dari residual, yaitu penjualan harian dikurangi garis tren robust pada hari yang sama. Lonjakan tetap tinggal di residual, sehingga ketidakpastiannya masuk ke cadangan, bukan ke permintaan. Akar jumlah hari membesarkan cadangan pada periode yang lebih panjang, tanpa menggandakan permintaan per hari.

**Cara hitung.**

1. Garis in-sample pada hari i: `max(0, (level + kemiringan × (i − titik tengah)) × profil hari)`.
2. `sigma = simpangan baku (QTY harian − garis)`, dengan pembagi n − 1. Hari terakhir yang terpotong tidak masuk sigma.
3. Faktor z dari persentase. Untuk 1–99%, z = invers distribusi normal `Φ⁻¹(persen / 100)`. Untuk 0%, z = 0. Untuk 100% ke atas, z = `Φ⁻¹(0,999) × persen / 100`.
4. `cadangan = z × sigma × √hari`.
5. Safety stock = pembulatan cadangan. Prediksi QTY = pembulatan permintaan. Prediksi sales volume = prediksi QTY × harga yang terbeli. Stok disarankan = prediksi QTY + safety stock.

**Saran per periode.** Persen saran diturunkan pada periode panjang karena √hari sudah membesarkan cadangan. Pengali di bawah adalah z × √hari pada saran masing-masing:

{suggestion_text}

**Hasil pada analisis ini.** Safety stock yang dipakai {applied_service}% (saran {period_name} {applied_suggestion}%). z = {z_value}. Pengali = {format_number(factor_now, 2)} × sigma. Pada {board_n} item terlaris: prediksi QTY {format_number(board_qty)} unit, safety stock {format_number(board_buffer)} unit, stok disarankan {format_number(board_stock)} unit, prediksi sales volume {format_idr(board_sales)}.

Mengubah angka safety stock menghitung ulang cadangan dan stok disarankan. Tren robust tidak dilatih ulang.
"""
    )
    st.subheader("Algoritma pembanding")
    st.markdown(
        """
Pembanding diuji pada **satu deret**: jumlah QTY seluruh toko per hari, hari kosong diisi nol. Beberapa hari terakhir disembunyikan sebagai ujian. Model dilatih hanya pada hari sebelum ujian. Profil hari pada ujian juga dihitung dari hari latih saja.

Panjang ujian: 7 hari bila kalender minimal 21 hari. Kalau lebih pendek, ujian = max(2, panjang ÷ 5), dan tabel baru muncul bila kalender minimal 8 hari.

**Selisih (%)** = |perkiraan jumlah QTY pada hari ujian − actual jumlah QTY pada hari ujian| / actual × 100. Skor ini mengukur jumlah periode, sesuai keputusan stok. Hari bernilai nol tidak mendominasi skor.

Tiap pembanding:

- **Tren harian.** Konsep: level rata-rata seluruh hari, kemiringan paruh akhir terhadap paruh awal, dan redaman φ = 0,985 yang membesar bersama nomor hari. Dipakai sebagai pembanding karena rumusnya mengikuti arah jangka pendek. Pada laporan pendek yang paruh akhirnya lebih sepi, redaman itu menurunkan bulan-bulan belakang pada kuartal, semester, dan tahun. Hasilnya dijepit 0,25–4 kali laju harian.
- **Naive.** Konsep: hari depan sama dengan hari terakhir. Cara hitung pada ujian: QTY hari terakhir data latih × jumlah hari ujian. Dipakai sebagai pembanding karena rumusnya transparan. Pada laporan Shopee, satu hari ramai yang kebetulan berada di ujung data akan terbawa ke seluruh periode.
- **Moving Average.** Konsep: hari depan sama dengan rata-rata jendela terakhir. Cara hitung pada ujian: rata-rata sampai 7 hari terakhir data latih × jumlah hari ujian. Jendela ini meredam satu hari ekstrem, dan kemiringan naik atau turun di luar jendela tidak ikut.
- **Holt Linear / Holt-Winters** (statsmodels `ExponentialSmoothing`). Konsep: pemulusan eksponensial dengan level dan tren. Bila data latih cukup untuk dua musim 7 hari, versi musiman aditif dan multiplikatif ikut dilatih, lalu yang lebih rapat pada ujian internal yang disimpan. Pada file pendek hasilnya Holt Linear, yaitu tren aditif tanpa musim. Perkiraan ujian adalah jumlah ramalan harian sepanjang jendela ujian. Model ini kuat pada deret panjang dan rapat. Pada banyak SKU yang jarang laku, parameternya mudah tidak stabil. Holt diuji pada total toko. Prediksi tiap Nomor Referensi SKU memakai Tren robust.
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

Selisih paling kecil pada total toko: **{closest['Algoritma']}** ({format_number(float(closest['Selisih (%)']), 1)}%). Prediksi per produk memakai **Tren robust**, bukan otomatis pemenang selisih pada total toko. Total toko lebih halus daripada satu SKU. Tren robust menjaga level harian saat riwayat belum cukup untuk kemiringan jangka panjang. Safety stock menambah cadangan di kolom terpisah, dan stok disarankan adalah jumlah keduanya.
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

with tab_data:
    st.caption(
        f"Isi file yang diunggah, {format_number(len(source_raw), 0)} baris. "
        "Kolom dan nilainya mengikuti lampiran, tidak diubah menjadi tabel prediksi."
    )
    if source_raw.empty:
        st.write("Belum ada file yang terbaca.")
    else:
        st.dataframe(source_raw, height=680, hide_index=True)
