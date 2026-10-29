from __future__ import annotations

import base64
import html
import io
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.intelligence.dashboard import show_intelligence_dashboard
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
    _robust_state,
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
from src.movement import compare_runs, frame_from_stock, list_runs, load_run, record_run, setup_notes
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
    page_title="Mitra10 × Shopee",
    page_icon="📦",
    layout="wide",
)
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
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
    .stat-card {
        background: #ffffff;
        border: 1px solid #e6e9f2;
        border-radius: 16px;
        padding: 0.75rem 0.9rem 0.7rem;
        box-shadow: 0 8px 22px rgba(15, 23, 42, 0.04);
        border-top: 3px solid #ee4d2d;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .stat-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 16px 34px rgba(15, 23, 42, 0.08);
    }
    .stat-card.calm { border-top-color: #1b3da6; }
    .readable-metric-label {
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        line-height: 1.35;
        color: #64748b;
        margin: 0 0 0.45rem 0;
    }
    .readable-metric-value {
        font-size: 1.32rem;
        font-weight: 800;
        letter-spacing: -0.03em;
        line-height: 1.25;
        color: #0f172a;
        white-space: normal;
        word-break: break-word;
    }
    .readable-metric-value.compact {
        font-size: 1.12rem;
        line-height: 1.35;
        letter-spacing: -0.02em;
    }
    .metric-hint {
        font-size: 0.8rem;
        font-weight: 500;
        line-height: 1.4;
        color: #64748b;
        margin: 0.4rem 0 0 0;
        padding-top: 0.35rem;
        border-top: 1px solid #eef1f6;
    }
    .period-name {
        font-size: 1.32rem;
        font-weight: 800;
        letter-spacing: -0.03em;
        line-height: 1.25;
        color: #0f172a;
    }
    .period-dates {
        font-size: 0.95rem;
        line-height: 1.5;
        color: #334155;
        margin-top: 0.4rem;
    }
    .report-stage-head {
        margin: 0.95rem 0 0.2rem;
    }
    .report-kicker {
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #ee4d2d;
        margin: 0 0 0.3rem;
    }
    .report-title {
        display: block;
        width: 100%;
        box-sizing: border-box;
        font-size: 1.55rem;
        font-weight: 800;
        letter-spacing: -0.03em;
        line-height: 1.4;
        color: #0f172a;
        margin: 0 0 0.7rem;
        padding-bottom: 0.4rem;
        border-bottom: 3px solid #0f172a;
        overflow: visible;
        white-space: normal;
    }
    .report-body {
        font-size: 1rem;
        line-height: 1.55;
        color: #1e293b;
        margin: 0.15rem 0 0.7rem;
        max-width: 68rem;
    }
    .slide-note {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 0.8rem 0.95rem 0.85rem;
        min-height: 0;
        line-height: 1.5;
        color: #1e293b;
        margin-top: 0.15rem;
    }
    .slide-note.action {
        background: #f0fdf4;
        border-color: #bbf7d0;
    }
    .slide-note-label {
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: #1d4ed8;
        margin-bottom: 0.35rem;
    }
    .slide-note.action .slide-note-label {
        color: #047857;
    }
    .swot-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 0.7rem;
        margin: 0.4rem 0 0.8rem;
    }
    .swot-card {
        border-radius: 12px;
        padding: 0.75rem 0.9rem;
        line-height: 1.45;
        color: #1e293b;
        min-height: 6.2rem;
    }
    .swot-card b { display: block; margin-bottom: 0.25rem; }
    .swot-s { background: #ecfdf5; }
    .swot-w { background: #fef2f2; }
    .swot-o { background: #eff6ff; }
    .swot-t { background: #fff7ed; }
    .bone-result {
        background: #f8fafc;
        border-left: 4px solid #0f172a;
        border-radius: 10px;
        padding: 0.85rem 1rem;
        line-height: 1.5;
        margin-bottom: 0.8rem;
    }
    div[data-testid="stElementContainer"]:has(.slide-nav) + div [data-testid="stHorizontalBlock"] {
        align-items: center;
    }
    div[data-testid="stElementContainer"]:has(.slide-nav) + div [data-testid="stHorizontalBlock"] button {
        height: 2.55rem;
        margin: 0;
    }
    .app-menu-label {
        height: 0;
        margin: 0;
        overflow: hidden;
    }
    .section-title {
        display: block;
        width: 100%;
        box-sizing: border-box;
        font-size: 1.02rem;
        font-weight: 800;
        letter-spacing: -0.02em;
        line-height: 1.4;
        color: #0f172a;
        margin: 0.35rem 0 0.45rem;
        padding-bottom: 0.35rem;
        border-bottom: 2px solid #0f172a;
        overflow: visible;
        white-space: normal;
    }
    .section-title.tight { margin-top: 0.35rem; }
    .section-body,
    .field-hint {
        font-size: 0.86rem;
        line-height: 1.45;
        color: #64748b;
        max-width: 62rem;
        margin: 0 0 0.35rem;
    }
    div[data-testid="stElementContainer"]:has(.app-menu-label) {
        height: 0;
        min-height: 0;
        margin: 0;
        padding: 0;
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
        font-weight: 800;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: #0f172a;
        margin: 0.15rem 0 0.45rem 0;
        padding-bottom: 0.28rem;
        border-bottom: 2px solid #0f172a;
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
        display: block;
        width: 100%;
        box-sizing: border-box;
        font-size: 1.12rem;
        font-weight: 800;
        letter-spacing: -0.02em;
        line-height: 1.4;
        color: #0f172a;
        margin: 0.55rem 0 0.45rem;
        padding-bottom: 0.35rem;
        border-bottom: 2px solid #0f172a;
        overflow: visible;
        white-space: normal;
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
    .sheet-scroll th.stock-final,
    .sheet-scroll td.stock-final {
        text-align: right;
        white-space: normal;
        min-width: 11.5rem;
        vertical-align: top;
    }
    .stock-main {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 0.35rem;
        font-weight: 700;
        line-height: 1.2;
    }
    .stock-arrow {
        font-size: 0.82rem;
        line-height: 1;
    }
    .stock-delta {
        margin-top: 0.12rem;
        font-size: 0.72rem;
        line-height: 1.15;
        font-weight: 650;
        text-align: right;
    }
    .stock-arrow.up,
    .stock-delta.up {
        color: #1d4ed8;
    }
    .stock-arrow.down,
    .stock-delta.down {
        color: #dc2626;
    }
    .stock-delta.flat {
        color: #64748b;
        font-weight: 500;
    }
    .metric-move,
    .cell-move {
        font-size: 0.78rem;
        font-weight: 650;
        line-height: 1.25;
        margin-top: 0.12rem;
    }
    .metric-move.up,
    .cell-move.up { color: #1d4ed8; }
    .metric-move.down,
    .cell-move.down { color: #dc2626; }
    .metric-move.flat,
    .cell-move.flat {
        color: #64748b;
        font-weight: 500;
    }
    .qty-safety {
        margin-top: 0.12rem;
        font-size: 0.72rem;
        line-height: 1.15;
        font-weight: 500;
        color: #64748b;
    }
    .sheet-scroll thead tr:nth-child(2) th {
        top: 2.45rem;
    }
    .sheet-scroll th.group-head {
        text-align: center;
        background: #e2e8f0;
        border-left: 1px solid #cbd5e1;
    }
    .sheet-scroll td.wrap-name {
        white-space: normal;
        min-width: 14rem;
        max-width: 22rem;
    }
    .sheet-scroll.movement-sheet thead th { z-index: 4; }
    .sheet-scroll.movement-sheet thead tr:nth-child(2) th { top: 2.25rem; }
    .sheet-scroll.movement-sheet thead tr.sheet-total th {
        top: 4.5rem;
        background: #f8fafc;
        z-index: 4;
    }
    .sheet-scroll.movement-sheet .pin {
        position: sticky;
        box-sizing: border-box;
        background: #ffffff;
    }
    .sheet-scroll.movement-sheet thead .pin { z-index: 6; background: #f1f5f9; }
    .sheet-scroll.movement-sheet thead tr.sheet-total .pin { background: #f8fafc; z-index: 7; }
    .sheet-scroll.movement-sheet tbody .pin { z-index: 2; }
    .sheet-scroll.movement-sheet .pin-no { left: 0; width: 4.2rem; min-width: 4.2rem; max-width: 4.2rem; }
    .sheet-scroll.movement-sheet .pin-sku { left: 4.2rem; width: 9rem; min-width: 9rem; max-width: 9rem; }
    .sheet-scroll.movement-sheet .pin-name {
        left: 13.2rem;
        width: 16.5rem;
        min-width: 16.5rem;
        max-width: 16.5rem;
        white-space: normal;
        box-shadow: 1px 0 0 #e2e8f0, 6px 0 10px rgba(15, 23, 42, 0.05);
    }
    .sheet-scroll.movement-sheet .pin-group { left: 4.2rem; }
    .sheet-scroll.movement-sheet thead th.group-head.pin { background: #e2e8f0; }
    .pin-kicker {
        display: block;
        margin-bottom: 0.12rem;
        font-size: 0.68rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: #64748b;
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
    html, body, [class*="css"] {
        font-family: "Plus Jakarta Sans", ui-sans-serif, system-ui, sans-serif;
    }
    .stApp {
        background:
            radial-gradient(980px 420px at 110% -12%, rgba(238, 77, 45, 0.10), transparent 52%),
            radial-gradient(820px 380px at -12% -8%, rgba(27, 61, 166, 0.09), transparent 48%),
            #f4f6fb;
    }
    header[data-testid="stHeader"] {
        height: 0 !important;
        min-height: 0 !important;
        background: #f4f6fb !important;
        pointer-events: none;
        overflow: hidden;
    }
    [data-testid="stToolbar"], [data-testid="stDecoration"] { display: none; }
    .block-container {
        padding-top: 1.35rem;
        padding-bottom: 3.2rem;
        max-width: 1240px;
    }
    [data-testid="stVerticalBlock"] { gap: 0.45rem; }
    [data-testid="stHorizontalBlock"] { gap: 0.65rem !important; align-items: stretch; }
    [data-testid="stCaptionContainer"] { margin: 0 0 0.1rem 0; }
    [data-testid="stCaptionContainer"] p {
        font-size: 0.86rem !important;
        line-height: 1.45 !important;
        color: #64748b !important;
        max-width: 62rem;
        margin-bottom: 0;
    }
    [data-testid="stMarkdownContainer"] {
        margin-bottom: 0 !important;
        overflow: visible !important;
        height: auto !important;
    }
    [data-testid="stHeading"] {
        display: block !important;
        height: auto !important;
        overflow: visible !important;
        margin: 0.65rem 0 0.45rem !important;
        padding: 0 0 0.4rem !important;
        border-bottom: 2px solid #0f172a;
    }
    [data-testid="stHeading"] h1,
    [data-testid="stHeading"] h2,
    [data-testid="stHeading"] h3,
    [data-testid="stHeading"] h4,
    [data-testid="stHeading"] h5,
    [data-testid="stHeading"] h6 {
        display: block !important;
        width: 100% !important;
        height: auto !important;
        max-height: none !important;
        overflow: visible !important;
        white-space: normal !important;
        text-overflow: unset !important;
        letter-spacing: -0.03em;
        font-weight: 800;
        color: #0f172a;
        line-height: 1.4 !important;
        margin: 0 !important;
        padding: 0 !important;
        border: none !important;
    }
    [data-testid="stCaptionContainer"],
    [data-testid="stWidgetLabel"] {
        overflow: visible !important;
        height: auto !important;
    }
    [data-testid="stMarkdownContainer"] p {
        line-height: 1.5;
        margin-bottom: 0.2rem;
    }
    [data-testid="stCheckbox"] { padding: 0.02rem 0.05rem 0.08rem; }
    [data-testid="stCheckbox"] label p {
        font-size: 0.96rem;
        line-height: 1.4;
        color: #1e293b;
    }
    [data-testid="stWidgetLabel"] p,
    [data-testid="stWidgetLabel"] label {
        font-size: 0.92rem !important;
        font-weight: 650 !important;
        color: #334155 !important;
        line-height: 1.45 !important;
    }
    [data-testid="stAlert"] {
        border-radius: 14px;
        line-height: 1.6;
    }
    div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e6e9f2;
        border-radius: 16px;
        padding: 0.95rem 1rem 0.85rem;
        border-top: 3px solid #1b3da6;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.045);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    div[data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 16px 34px rgba(15, 23, 42, 0.08);
    }
    .stButton > button {
        border-radius: 12px;
        font-weight: 700;
        min-height: 2.75rem;
        transition: transform 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
    }
    .stButton > button[kind="primary"],
    .stButton > button[data-testid="stBaseButton-primary"] {
        background: linear-gradient(135deg, #ff7348 0%, #ee4d2d 100%);
        border: none;
        color: #ffffff;
    }
    .stButton > button[kind="primary"]:hover,
    .stButton > button[data-testid="stBaseButton-primary"]:hover {
        background: linear-gradient(135deg, #ff8158 0%, #e24122 100%);
        color: #ffffff;
    }
    .stat-card { width: 100%; box-sizing: border-box; }
    .qty-board-head { margin: 0.2rem 0 0.8rem; }
    .qty-board-title {
        font-size: 1.35rem;
        font-weight: 800;
        letter-spacing: -0.03em;
        color: #0f172a;
        margin: 0 0 0.25rem;
    }
    .qty-board-copy { color: #64748b; font-size: 0.92rem; line-height: 1.45; margin: 0; }
    .qty-legend {
        display: flex;
        justify-content: center;
        gap: 1.4rem;
        color: #334155;
        font-weight: 700;
        font-size: 0.92rem;
        margin: 0.85rem 0 0.2rem;
    }
    .qty-legend i {
        display: inline-block;
        width: 0.85rem;
        height: 0.85rem;
        border-radius: 3px;
        margin-right: 0.4rem;
        vertical-align: -1px;
    }
    .qty-legend .up { background: #16a34a; }
    .qty-legend .down { background: #dc2626; }
    .qty-legend .flat { background: #64748b; }
    .qty-card { padding: 0.95rem 0.15rem 1.05rem; }
    .qty-id { text-align: right; margin-bottom: 0.45rem; }
    .qty-rank { font-weight: 800; color: #0f172a; font-size: 0.98rem; }
    .qty-name { color: #1e293b; font-weight: 650; line-height: 1.4; margin-top: 0.12rem; }
    .qty-var { color: #94a3b8; font-size: 0.84rem; margin-top: 0.08rem; }
    .qty-line { display: flex; align-items: center; gap: 0.7rem; margin-top: 0.42rem; }
    .qty-metric {
        width: 7.6rem;
        flex: 0 0 7.6rem;
        color: #0f172a;
        font-size: 0.8rem;
        font-weight: 800;
        line-height: 1.2;
    }
    .qty-metric small,
    .qty-base small {
        display: block;
        color: #94a3b8;
        font-size: 0.7rem;
        font-weight: 600;
        margin-top: 0.08rem;
    }
    .qty-head-row { margin-top: 0.1rem; }
    .qty-head-row .qty-metric,
    .qty-head-row .qty-base,
    .qty-head-row .qty-head-mid {
        color: #94a3b8;
        font-size: 0.68rem;
        font-weight: 800;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    .qty-head-row .qty-head-mid { flex: 1; text-align: center; }
    .qty-track {
        flex: 1;
        height: 1.85rem;
        background: #f1f5f9;
        border-radius: 8px;
        overflow: hidden;
    }
    .qty-fill {
        height: 100%;
        min-width: 14.5rem;
        max-width: 100%;
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: flex-end;
        padding: 0 0.7rem;
        color: #ffffff;
        font-weight: 800;
        font-size: 0.82rem;
        white-space: nowrap;
        box-sizing: border-box;
    }
    .qty-fill.naik { background: #16a34a; }
    .qty-fill.turun { background: #dc2626; }
    .qty-fill.tetap { background: #64748b; }
    .qty-base {
        width: 6.2rem;
        flex: 0 0 6.2rem;
        text-align: right;
        color: #0f172a;
        font-weight: 800;
        font-size: 0.9rem;
        line-height: 1.2;
    }
    div[data-testid="stElementContainer"]:has(.qty-board-anchor) + div [data-testid="stButton"] button {
        border-radius: 999px;
        min-height: 2.45rem;
    }
    div[data-testid="stElementContainer"]:has(.qty-row-anchor) + div [data-testid="stButton"] button {
        border-radius: 999px;
        min-height: 2.35rem;
        background: #0f172a;
        color: #ffffff;
        border: none;
        font-size: 0.84rem;
    }
    .insight-head { border-radius: 16px; padding: 1.05rem 1.15rem 0.95rem; color: #ffffff; margin-bottom: 0.9rem; }
    .insight-head.up { background: #1d4ed8; }
    .insight-head.down { background: #dc2626; }
    .insight-head.flat { background: #334155; }
    .insight-kicker { font-size: 0.72rem; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; opacity: 0.85; }
    .insight-title { font-size: 1.25rem; font-weight: 800; line-height: 1.35; margin-top: 0.3rem; }
    .insight-meta { margin-top: 0.25rem; font-size: 0.88rem; opacity: 0.9; }
    .insight-stat {
        border: 1px solid #bfdbfe;
        background: #eff6ff;
        border-radius: 14px;
        padding: 0.85rem 1rem;
        margin-bottom: 0.9rem;
    }
    .insight-head.down + .insight-stat { border-color: #fecaca; background: #fef2f2; }
    .insight-head.flat + .insight-stat { border-color: #e2e8f0; background: #f8fafc; }
    .insight-stat-label { color: #64748b; font-size: 0.78rem; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; }
    .insight-stat-value { font-size: 1.55rem; font-weight: 800; color: #1d4ed8; margin-top: 0.15rem; }
    .insight-head.down + .insight-stat .insight-stat-value { color: #dc2626; }
    .insight-head.flat + .insight-stat .insight-stat-value { color: #334155; }
    .insight-stat-value span { font-size: 1rem; font-weight: 700; }
    .insight-stat-note { color: #475569; font-size: 0.88rem; line-height: 1.45; margin-top: 0.2rem; }
    .insight-section {
        font-size: 0.78rem;
        font-weight: 800;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        color: #64748b;
        margin: 0.85rem 0 0.45rem;
    }
    .insight-chips { display: flex; flex-wrap: wrap; gap: 0.45rem; }
    .insight-chip {
        border-radius: 999px;
        padding: 0.38rem 0.75rem;
        font-size: 0.88rem;
        font-weight: 700;
        background: #ffffff;
    }
    .insight-chip.up { color: #1d4ed8; border: 1px solid #93c5fd; }
    .insight-chip.down { color: #dc2626; border: 1px solid #fca5a5; }
    .insight-chip.flat { color: #334155; border: 1px solid #cbd5e1; }
    .insight-copy {
        background: #f8fafc;
        border-radius: 14px;
        padding: 0.8rem 1rem;
        color: #334155;
        line-height: 1.55;
        margin: 0 0 0.45rem;
    }
    .insight-note { color: #94a3b8; font-size: 0.8rem; line-height: 1.45; margin: 0.15rem 0 0; }
    .insight-reco {
        margin: 0;
        color: #0f172a;
        font-size: 1.02rem;
        font-weight: 750;
        line-height: 1.5;
    }
    .insight-steps { list-style: none; margin: 0; padding: 0; }
    .insight-step {
        display: flex;
        gap: 0.75rem;
        align-items: flex-start;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 0.75rem 0.9rem;
        margin-bottom: 0.45rem;
        color: #1e293b;
        line-height: 1.45;
    }
    .insight-step-no {
        width: 1.65rem;
        height: 1.65rem;
        border-radius: 999px;
        background: #0f172a;
        color: #ffffff;
        font-size: 0.82rem;
        font-weight: 800;
        display: flex;
        align-items: center;
        justify-content: center;
        flex: none;
    }
    .insight-step strong { display: block; margin-bottom: 0.12rem; }
    div[data-testid="stDialog"] [data-testid="stBaseButton-primary"] {
        background: #059669;
        border-radius: 999px;
    }
    footer, #MainMenu { visibility: hidden; height: 0; }
    section[data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"] {
        display: none !important;
    }
    [data-testid="stDataFrame"] {
        border: 1px solid #e7e9f2;
        border-radius: 12px;
        overflow: hidden;
        background: #ffffff;
    }
    .home-hero {
        background: linear-gradient(135deg, #ffffff 0%, #fff7f4 48%, #f4f7ff 100%);
        border: 1px solid #e7e9f2;
        border-radius: 28px;
        padding: 2.2rem 2.3rem 2rem;
        box-shadow: 0 24px 60px rgba(15, 23, 42, 0.06);
        margin-bottom: 1.2rem;
    }
    .brand-row {
        display: flex;
        align-items: center;
        gap: 0.85rem;
        margin-bottom: 1.5rem;
    }
    .brand-card {
        background: #ffffff;
        border: 1px solid #eceef5;
        border-radius: 16px;
        padding: 0.55rem 0.9rem;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
        display: flex;
        align-items: center;
        min-height: 74px;
    }
    .brand-card img { height: 52px; width: auto; display: block; }
    .brand-card.shopee img { height: 34px; }
    .brand-x {
        font-size: 1.35rem;
        font-weight: 700;
        color: #94a3b8;
    }
    .home-kicker {
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: #ee4d2d;
        margin-bottom: 0.45rem;
    }
    .home-title {
        font-size: 2.55rem;
        font-weight: 800;
        letter-spacing: -0.035em;
        line-height: 1.12;
        color: #0f172a;
        margin: 0 0 0.7rem;
    }
    .home-lead {
        max-width: 42rem;
        font-size: 1.08rem;
        line-height: 1.7;
        color: #334155;
    }
    .home-section {
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #64748b;
        margin: 0.2rem 0 0.55rem;
    }
    .feature-badge {
        display: inline-block;
        background: #fff1ec;
        color: #c2410c;
        border-radius: 999px;
        padding: 0.22rem 0.65rem;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.03em;
        margin-bottom: 0.55rem;
    }
    .feature-title {
        display: block;
        width: 100%;
        box-sizing: border-box;
        font-size: 1.45rem;
        font-weight: 800;
        letter-spacing: -0.03em;
        line-height: 1.35;
        color: #0f172a;
        margin-bottom: 0.55rem;
        padding-bottom: 0.35rem;
        border-bottom: 2px solid #0f172a;
        overflow: visible;
        white-space: normal;
    }
    .feature-copy {
        color: #334155;
        font-size: 1.02rem;
        line-height: 1.7;
        max-width: 46rem;
        margin: 0 0 1rem 0;
    }
    .feature-bar {
        display: flex;
        align-items: center;
        gap: 0.85rem;
        background: #ffffff;
        border: 1px solid #e7e9f2;
        border-radius: 18px;
        padding: 0.65rem 0.9rem;
        box-shadow: 0 10px 30px rgba(15, 23, 42, 0.04);
    }
    .feature-bar img { height: 36px; width: auto; display: block; }
    .feature-bar img.shopee-mark { height: 24px; }
    .feature-kicker {
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #64748b;
    }
    .feature-name {
        font-size: 1.15rem;
        font-weight: 800;
        letter-spacing: -0.02em;
        color: #0f172a;
        line-height: 1.2;
    }
    .block-container:has(.feature-bar) { padding-top: 6.4rem !important; }
    .block-container:has(.app-menu-label) { padding-top: 10.5rem !important; }
    .block-container:has(.period-name) { padding-top: 17.2rem !important; }
    div[data-testid="stHorizontalBlock"]:has(.feature-bar) {
        align-items: center !important;
        gap: 0.7rem !important;
        background: #ffffff;
        border: 1px solid #e7e9f2;
        border-radius: 20px;
        padding: 0.45rem 0.55rem 0.45rem 0.85rem;
        box-shadow: 0 12px 32px rgba(15, 23, 42, 0.06);
    }
    div[data-testid="stHorizontalBlock"]:has(.feature-bar) .feature-bar {
        background: transparent;
        border: none;
        box-shadow: none;
        padding: 0.15rem 0;
    }
    div[data-testid="stHorizontalBlock"]:has(.feature-bar) [data-testid="stColumn"]:last-child button {
        background: #0f172a !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 999px !important;
        min-height: 2.65rem;
        font-weight: 700;
        letter-spacing: 0.01em;
        box-shadow: 0 8px 18px rgba(15, 23, 42, 0.16);
    }
    div[data-testid="stHorizontalBlock"]:has(.feature-bar) [data-testid="stColumn"]:last-child button:hover {
        background: #1e293b !important;
        color: #ffffff !important;
        transform: translateY(-1px);
    }
    div[data-testid="stHorizontalBlock"]:has(.feature-bar) [data-testid="stColumn"]:not(:first-child):not(:last-child) button {
        background: #fff7f4 !important;
        color: #c2410c !important;
        border: 1px solid #fdba74 !important;
        border-radius: 999px !important;
        min-height: 2.65rem;
        font-weight: 700;
        box-shadow: none;
    }
    div[data-testid="stHorizontalBlock"]:has(.feature-bar) [data-testid="stColumn"]:not(:first-child):not(:last-child) button:hover {
        background: #ffedd5 !important;
        color: #9a3412 !important;
        transform: translateY(-1px);
    }
    div[data-testid="stHorizontalBlock"]:has(.period-name) {
        align-items: stretch !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.period-name) .stat-card,
    div[data-testid="stHorizontalBlock"]:has(.period-name) .stat-card:hover {
        transform: none;
        box-shadow: 0 8px 22px rgba(15, 23, 42, 0.04);
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 20px !important;
        border-color: #e7e9f2 !important;
        background: #ffffff;
        box-shadow: 0 16px 40px rgba(15, 23, 42, 0.05);
        padding: 0.35rem 0.4rem 0.2rem;
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


def days_in_calendar_month(day: date) -> int:
    """Jumlah hari bulan kalender, selalu dihitung dari tanggal 1."""
    first = date(day.year, day.month, 1)
    if day.month == 12:
        nxt = date(day.year + 1, 1, 1)
    else:
        nxt = date(day.year, day.month + 1, 1)
    return max((nxt - first).days, 1)


def slice_forecast(pred_qty: float, pred_sales: float, safety: float, horizon_days: int, days: int) -> tuple[int, int, int]:
    """Bagian prediksi untuk sejumlah hari. QTY dan sales lurus. Safety mengikuti akar hari."""
    horizon = max(int(horizon_days), 1)
    span = max(int(days), 0)
    share = span / horizon
    qty = int(np.rint(float(pred_qty) * share))
    sales = int(np.rint(float(pred_sales) * share))
    guard = int(np.rint(max(float(safety), 0.0) * np.sqrt(share))) if span else 0
    return qty, sales, max(qty + guard, 0)


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


FEATURE_ID = "prediksi-item-terlaris"
LOGO_DIR = ROOT / "assets"


def _logo_uri(name: str) -> str:
    path = LOGO_DIR / name
    mime = "image/svg+xml" if path.suffix == ".svg" else "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def show_homepage() -> None:
    """Pintu masuk. Satu kartu fitur, sebelum data input dibuka."""
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"] { display: none !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    mitra, shopee = _logo_uri("mitra10.png"), _logo_uri("shopee.svg")
    st.markdown(
        f"""
        <div class="home-hero">
            <div class="brand-row">
                <div class="brand-card"><img src="{mitra}" alt="Mitra10"></div>
                <div class="brand-x">×</div>
                <div class="brand-card shopee"><img src="{shopee}" alt="Shopee"></div>
            </div>
            <div class="home-kicker">E-commerce intelligence</div>
            <div class="home-title">Keputusan e-commerce,<br>dalam satu ruang kerja.</div>
            <div class="home-lead">
                Ruang kerja manajer e-commerce dan digital marketing, sekaligus artefak tesis
                Magister Teknik Informatika Renxy Lichandy for Mitra10 - 2026.
            </div>
        </div>
        <div class="home-section">Fitur</div>
        """,
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.markdown(
            """
            <div class="feature-badge">Fitur 01 · sedang dikembangkan</div>
            <div class="feature-title">Prediksi item terlaris</div>
            <div class="feature-copy">
                Isi data dan parameter lebih dulu, lalu jalankan analisis. Hasilnya bisa dibaca
                setelah itu. Data, unggahan, dan parameter bisa diubah lagi agar prediksi belajar ulang.
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Buka Prediksi item terlaris", type="primary"):
            st.session_state["active-feature"] = FEATURE_ID
            st.rerun()


def pin_app_header() -> None:
    """Kunci bar atas, menu, dan kartu tanggal ke layar. Sticky tidak menempel di Streamlit."""
    components.html(
        """
        <script>
        const parent = window.parent;
        const pin = () => {
          const doc = parent.document;
          const root = doc.querySelector('[data-testid="stMainBlockContainer"]');
          const bar = doc.querySelector('.feature-bar');
          const main = doc.querySelector('[data-testid="stMain"]');
          const existing = doc.getElementById('mitra-header-shield');
          if (!root || !bar || !main) {
            if (existing) existing.remove();
            return;
          }
          const rowOf = (node) => {
            if (!node) return null;
            const block = node.closest('[data-testid="stHorizontalBlock"]');
            if (!block) return node.closest('[data-testid="stElementContainer"]');
            return block.closest('[data-testid="stLayoutWrapper"]') || block;
          };
          const menuLabel = doc.querySelector('.app-menu-label');
          const menuHost = menuLabel ? menuLabel.closest('[data-testid="stElementContainer"]') : null;
          const menu = menuHost ? menuHost.nextElementSibling : null;
          const pieces = [rowOf(bar), menu, rowOf(doc.querySelector('.period-name'))].filter((el, index, list) => el && el.isConnected && list.indexOf(el) === index);
          if (!pieces.length || !pieces[0].parentElement) return;
          const page = pieces[0].parentElement;
          const box = root.getBoundingClientRect();
          const style = parent.getComputedStyle(root);
          const padLeft = parseFloat(style.paddingLeft) || 0;
          const padRight = parseFloat(style.paddingRight) || 0;
          const left = box.left + padLeft;
          const width = Math.max(box.width - padLeft - padRight, 0);
          let top = 12;
          pieces.forEach((el) => {
            el.style.setProperty('position', 'fixed', 'important');
            el.style.setProperty('top', top + 'px', 'important');
            el.style.setProperty('left', left + 'px', 'important');
            el.style.setProperty('width', width + 'px', 'important');
            el.style.setProperty('z-index', '40', 'important');
            el.style.setProperty('background', 'transparent', 'important');
            el.style.setProperty('box-sizing', 'border-box', 'important');
            el.style.setProperty('margin', '0', 'important');
            top += el.getBoundingClientRect().height + 10;
          });
          const pinned = new Set(pieces);
          Array.from(page.children).forEach((child) => {
            if (child.id === 'mitra-header-shield') return;
            const holdsHeader = child.querySelector && child.querySelector('.feature-bar, .app-menu-label, .period-name');
            if (pinned.has(child) || holdsHeader) {
              child.style.setProperty('z-index', '40', 'important');
              return;
            }
            child.style.setProperty('position', 'relative', 'important');
            child.style.setProperty('z-index', '1', 'important');
          });
          const shield = existing || doc.createElement('div');
          shield.id = 'mitra-header-shield';
          if (shield.parentElement !== page) page.appendChild(shield);
          shield.style.setProperty('position', 'fixed', 'important');
          shield.style.setProperty('top', '0px', 'important');
          shield.style.setProperty('left', '0px', 'important');
          shield.style.setProperty('width', parent.innerWidth + 'px', 'important');
          shield.style.setProperty('height', top + 'px', 'important');
          shield.style.setProperty('background', '#f4f6fb', 'important');
          shield.style.setProperty('z-index', '10', 'important');
          shield.style.setProperty('pointer-events', 'auto', 'important');
          shield.style.setProperty('border-bottom', '1px solid #e2e8f0', 'important');
          shield.style.setProperty('box-sizing', 'border-box', 'important');
          const restingPad = top - box.top - main.scrollTop + 8;
          root.style.setProperty('padding-top', Math.max(restingPad, 0) + 'px', 'important');
        };
        parent.__mitraHeaderPin = pin;
        if (!parent.__mitraHeaderPinBound) {
          parent.__mitraHeaderPinBound = true;
          parent.addEventListener('resize', () => parent.__mitraHeaderPin());
          const watch = () => {
            const main = parent.document.querySelector('[data-testid="stMain"]');
            if (!main || main.__mitraWatch) return;
            main.__mitraWatch = true;
            let queued = false;
            const schedule = () => {
              if (queued) return;
              queued = true;
              parent.requestAnimationFrame(() => {
                queued = false;
                parent.__mitraHeaderPin();
              });
            };
            new MutationObserver(schedule).observe(main, {childList: true, subtree: true});
          };
          watch();
          parent.setInterval(() => parent.__mitraHeaderPin(), 1000);
        }
        pin();
        </script>
        """,
        height=0,
        width=0,
    )


def show_feature_header(*, show_analysis_button: bool, show_training_button: bool) -> None:
    """Bar atas. Analisa Prediksi membuka hasil. Ubah data latih kembali ke periode latih."""
    pin_app_header()
    mitra, shopee = _logo_uri("mitra10.png"), _logo_uri("shopee.svg")
    slots = int(show_analysis_button) + int(show_training_button)
    if slots == 2:
        widths = [4.8, 1.85, 2.15, 1.35]
    elif slots == 1:
        widths = [5.5, 2.2, 1.4]
    else:
        widths = [6.4, 1.4]
    columns = st.columns(widths, vertical_alignment="center")
    columns[0].markdown(
        f"""
        <div class="feature-bar">
            <img src="{mitra}" alt="Mitra10">
            <img class="shopee-mark" src="{shopee}" alt="Shopee">
            <div>
                <div class="feature-kicker">Mitra10 × Shopee</div>
                <div class="feature-name">Prediksi item terlaris</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cursor = 1
    if show_analysis_button:
        if columns[cursor].button("Analisa Prediksi", use_container_width=True):
            st.session_state["editing-input"] = False
            st.rerun()
        cursor += 1
    if show_training_button:
        if columns[cursor].button("Ubah data latih", use_container_width=True):
            st.session_state["editing-input"] = True
            st.rerun()
    if columns[-1].button("Beranda", use_container_width=True):
        st.session_state["active-feature"] = ""
        st.rerun()


def _checked_library_keys() -> list[str]:
    keys = []
    for item in list_months():
        key = item["key"]
        if not st.session_state.get(f"library-year-on-{year_of(key)}", False):
            continue
        if st.session_state.get(f"library-month-{key}", False):
            keys.append(key)
    return keys


def _orders_from_library(keys: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    if not keys:
        return pd.DataFrame(), pd.DataFrame(), "empty"
    source, orders = cached_library_frames(tuple(keys), bundle_stamp(keys))
    if source is None or source.empty:
        return pd.DataFrame(), pd.DataFrame(), "library:" + ",".join(keys)
    if not isinstance(orders, pd.DataFrame) or orders.empty:
        rebuilt = clean_order_frame(source)
        if not rebuilt.empty:
            orders = rebuilt
    return orders, source, "library:" + ",".join(keys)


def show_prediction_inputs() -> None:
    """Halaman landasan prediksi. Terpisah dari hasil analisa."""
    st.markdown(
        """
        <div class="home-section">Data latih</div>
        <div class="feature-title">Periode untuk analisis</div>
        <div class="feature-copy">
            Laporan yang diunggah tersimpan di sini dan bertambah bila ada data baru.
            Centang tahun dan bulan yang dipakai sebagai data latih analisis ini.
        </div>
        """,
        unsafe_allow_html=True,
    )
    notice = st.session_state.pop("input-error", None)
    if notice:
        st.error(notice)
    if "analysis" in st.session_state:
        st.caption("Hasil analisis sebelumnya tetap ada sampai analisis dijalankan lagi.")

    with st.container(border=True):
        st.markdown("<div class='side-section'>Laporan</div>", unsafe_allow_html=True)
        uploaded = st.file_uploader(
            "Laporan Shopee",
            type=["csv", "xlsx", "xls"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        st.markdown(
            "<div class='upload-note'>CSV, XLSX, atau XLS. Beberapa file digabung. "
            "Maksimal 50 lampiran, total 1 GB. Unggahan baru menambah data latih, tidak menghapus bulan lama.</div>",
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
    if load_error:
        st.error(load_error)
    imported_keys: list[str] = []
    source_key = "empty"
    if files:
        source_key = "|".join(f"{item.name}:{getattr(item, 'size', 0)}" for item in files)
    if (
        files
        and not load_error
        and isinstance(source_raw, pd.DataFrame)
        and not source_raw.empty
        and source_key != st.session_state.get("saved_source_key")
    ):
        imported_keys, _import_notes = store_upload(
            source_raw,
            orders_raw,
            [getattr(item, "name", "Lampiran") for item in files],
        )
        st.session_state["saved_source_key"] = source_key
    saved_months = list_months()
    with st.container(border=True):
        st.markdown("<div class='side-section'>Filter data latih</div>", unsafe_allow_html=True)
        if saved_months:
            years = []
            for item in saved_months:
                year_name = year_of(item["key"])
                if year_name not in years:
                    years.append(year_name)
            years = sorted(years)
            year_options = ["Semua tahun", *years]
            if st.session_state.get("library-year-pick") not in year_options:
                st.session_state["library-year-pick"] = "Semua tahun"
            picked_year = st.selectbox("Tahun", year_options, key="library-year-pick")
            if st.session_state.get("_year_pick_applied") != picked_year:
                for year in years:
                    st.session_state[f"library-year-on-{year}"] = picked_year in {"Semua tahun", year}
                st.session_state["_year_pick_applied"] = picked_year
            if imported_keys:
                for key in imported_keys:
                    st.session_state[f"library-year-on-{year_of(key)}"] = True
                    st.session_state[f"library-month-{key}"] = True
            st.markdown(
                "<div class='field-hint'>Daftar memilih satu tahun atau semua. Centang untuk memilih lebih dari satu tahun.</div>",
                unsafe_allow_html=True,
            )
            year_columns = st.columns(max(len(years), 1))
            checked_years = []
            for index, year in enumerate(years):
                year_widget = f"library-year-on-{year}"
                if year_widget not in st.session_state:
                    st.session_state[year_widget] = True
                with year_columns[index]:
                    if st.checkbox(str(year), key=year_widget):
                        checked_years.append(year)
            month_keys = [item["key"] for item in saved_months if year_of(item["key"]) in checked_years]
            st.markdown(
                "<div class='field-hint'>Bulan dari tahun yang dicentang. Hanya bulan ini yang menjadi data latih analisis.</div>",
                unsafe_allow_html=True,
            )
            selected_library = []
            if month_keys:
                month_columns = st.columns(4)
                for index, key in enumerate(sorted(month_keys)):
                    month_widget = f"library-month-{key}"
                    if month_widget not in st.session_state:
                        st.session_state[month_widget] = True
                    with month_columns[index % 4]:
                        if st.checkbox(month_label(key), key=month_widget):
                            selected_library.append(key)
            if selected_library:
                orders_raw, source_raw, source_key = _orders_from_library(selected_library)
                st.session_state["active-library-keys"] = tuple(selected_library)
            else:
                orders_raw = pd.DataFrame()
                source_raw = pd.DataFrame()
                source_key = "library:none"
                st.session_state["active-library-keys"] = tuple()
                st.warning("Centang minimal satu tahun dan satu bulan.")
        else:
            st.caption("Belum ada data tersimpan. Unggah laporan di atas.")
    if (
        isinstance(source_raw, pd.DataFrame)
        and not source_raw.empty
        and (not isinstance(orders_raw, pd.DataFrame) or orders_raw.empty)
    ):
        rebuilt = clean_order_frame(source_raw)
        if not rebuilt.empty:
            orders_raw = rebuilt

    with st.container(border=True):
        st.markdown("<div class='side-section'>Parameter</div>", unsafe_allow_html=True)
        period = st.selectbox(
            "Periode prediksi",
            options=list(PERIOD_OPTIONS),
            format_func=lambda key: PERIOD_SPECS[key].label,
            key="forecast-period",
        )
        sidebar_metric = st.radio(
            "Parameter peringkat",
            options=["qty", "sales"],
            format_func=lambda key: "Quantity terjual" if key == "qty" else "Sales volume",
            horizontal=True,
            key="rank-metric",
        )
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
        if st.button("Jalankan analisis", type="primary"):
            if not isinstance(orders_raw, pd.DataFrame) or orders_raw.empty:
                st.session_state["input-error"] = "Pilih tahun dan bulan, atau unggah laporan, sebelum menjalankan analisis."
                st.rerun()
            st.session_state["saved-period"] = period
            st.session_state["saved-metric"] = sidebar_metric
            st.session_state["saved-service"] = int(service)
            st.session_state["saved-source-key"] = source_key
            st.session_state["pending-run"] = True
            st.session_state["editing-input"] = False
            st.rerun()
    st.stop()


def restore_prediction_context() -> tuple[pd.DataFrame, pd.DataFrame, str, str, str, int]:
    """Baca landasan yang terakhir dijalankan, tanpa menampilkan formulir."""
    period = str(st.session_state.get("saved-period", "bulan"))
    metric = str(st.session_state.get("saved-metric", "qty"))
    service = int(st.session_state.get("saved-service", SUGGESTED_SERVICE.get(period, 95)))
    keys = [str(key) for key in st.session_state.get("active-library-keys", tuple())]
    if not keys:
        keys = _checked_library_keys()
    orders, source, source_key = _orders_from_library(keys)
    if orders.empty:
        source_key = str(st.session_state.get("saved-source-key", source_key))
    return orders, source, source_key, period, metric, service


APP_SHEETS = (
    "Ringkasan",
    "Prediksi & stok",
    "Data",
    "Folder data",
    "Laporan",
    "Evaluasi model",
)
SUMMARY_SHEETS = {"Ringkasan", "Prediksi & stok", "Data"}


def show_app_menu() -> str:
    """Menu fitur. Tombol yang sedang terbuka memakai warna utama."""
    current = st.session_state.get("active-sheet", "Ringkasan")
    st.markdown("<div class='app-menu-label'></div>", unsafe_allow_html=True)
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


def _clean_product_piece(value: object, fallback: str) -> str:
    text = " ".join(str(value).split())
    if text.lower() in {"", "nan", "none", "-", "none"}:
        return fallback
    return text


def chart_axis_label(
    rank,
    sku,
    name: str,
    variation: str = "",
    *,
    width: int = 48,
    max_lines: int = 6,
) -> str:
    """Kiri SKU, tengah Product Name, kanan Product variance."""
    sku_text = _clean_product_piece(sku, "Tanpa SKU")
    name_text = _clean_product_piece(name, "Tanpa nama")
    variance_text = _clean_product_piece(variation, "Tanpa variasi")
    try:
        number = int(rank)
        head = f"{number}. SKU {sku_text}"
    except (TypeError, ValueError):
        head = f"SKU {sku_text}"
    return "<br>".join(
        [
            wrap_label(head, width=width, max_lines=2),
            wrap_label(f"Product Name {name_text}", width=width, max_lines=max_lines),
            wrap_label(f"Product variance {variance_text}", width=width, max_lines=2),
        ]
    )


def product_identity(rank, sku, name: str, variation: str = "") -> str:
    """Nama lengkap satu baris: SKU, Product Name, lalu Product variance."""
    return chart_axis_label(rank, sku, name, variation).replace("<br>", " ")


def _product_axis(plot: pd.DataFrame, *, width: int = 52, max_lines: int = 6) -> tuple[list[str], list[str]]:
    full_labels: list[str] = []
    labels: list[str] = []
    for rank, sku, name, variation in zip(
        plot["peringkat"],
        plot["sku"],
        plot["product_name"],
        plot["variasi_tampil"],
    ):
        labels.append(chart_axis_label(rank, sku, name, variation, width=width, max_lines=max_lines))
        full_labels.append(product_identity(rank, sku, name, variation))
    return full_labels, labels


def _prediction_marks(texts: list[str], plot: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Satu tanda pada angka prediksi. Biru naik, merah turun, tanda - bila tetap."""
    if "delta_qty_nilai" not in plot.columns:
        return list(texts), ["#1f2937"] * len(texts)
    marked: list[str] = []
    colors: list[str] = []
    for text, delta in zip(texts, plot["delta_qty_nilai"]):
        try:
            number = int(delta)
        except (TypeError, ValueError):
            marked.append(text)
            colors.append("#1f2937")
            continue
        if number > 0:
            marked.append(f"▲ {text}")
            colors.append("#1d4ed8")
        elif number < 0:
            marked.append(f"▼ {text}")
            colors.append("#dc2626")
        else:
            marked.append(f"- {text}")
            colors.append("#64748b")
    return marked, colors


def growth_hint(predicted: float, actual: float, basis: str) -> str:
    """Persentase prediksi terhadap penjualan yang sudah ada pada laporan."""
    if actual <= 0:
        return f"Belum ada {basis} pada laporan sebagai pembanding."
    percent = (float(predicted) - float(actual)) / float(actual) * 100
    text = format_number(percent, 1)
    if percent > 0:
        text = f"+{text}"
    return f"Kenaikan {text}% dibanding {basis} pada laporan."


_WEEKDAY_ID = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")


def _dismiss_qty_insight() -> None:
    st.session_state.pop("qty-insight-key", None)


def _qty_direction(predicted: int, actual: int) -> str:
    if predicted > actual:
        return "naik"
    if predicted < actual:
        return "turun"
    return "tetap"


def _qty_pill(predicted: int, actual: int) -> tuple[str, str, int, float | None]:
    gap = int(predicted) - int(actual)
    direction = _qty_direction(predicted, actual)
    percent = None if actual <= 0 else gap / actual * 100
    qty_text = format_qty(predicted)
    if direction == "naik":
        mark = "▲"
        signed = f"+{format_number(abs(percent), 2)}%" if percent is not None else ""
    elif direction == "turun":
        mark = "▼"
        signed = f"−{format_number(abs(percent), 2)}%" if percent is not None else ""
    else:
        mark = "–"
        signed = "0%"
    detail = f" ({signed})" if signed else ""
    return direction, f"{mark} {qty_text}{detail}", gap, percent


def _daily_qty_sales(history: pd.DataFrame | None, item_key: str) -> tuple[np.ndarray, np.ndarray]:
    """Kalender harian yang sama dengan Level terkini: hari kosong diisi nol."""
    empty = np.zeros(0, dtype=float)
    if not isinstance(history, pd.DataFrame) or history.empty or "item_key" not in history.columns:
        return empty, empty
    stamps = pd.to_datetime(history["period_start"], errors="coerce").dt.normalize()
    if stamps.notna().sum() == 0:
        return empty, empty
    calendar = pd.date_range(stamps.min(), stamps.max(), freq="D")
    part = history.loc[history["item_key"].astype(str) == str(item_key)].copy()
    if part.empty:
        return np.zeros(len(calendar), dtype=float), np.zeros(len(calendar), dtype=float)
    part["_day"] = pd.to_datetime(part["period_start"], errors="coerce").dt.normalize()
    grouped = part.dropna(subset=["_day"]).groupby("_day")[["qty", "sales"]].sum()
    qty = grouped["qty"].reindex(calendar, fill_value=0.0).to_numpy(dtype=float)
    sales = grouped["sales"].reindex(calendar, fill_value=0.0).to_numpy(dtype=float)
    return qty, sales


def _order_friction(orders: pd.DataFrame | None, item_key: str) -> dict[str, float]:
    blank = {"gross": 0.0, "cancel": 0.0, "returned": 0.0}
    if not isinstance(orders, pd.DataFrame) or orders.empty or "item_key" not in orders.columns:
        return blank
    part = orders.loc[orders["item_key"].astype(str) == str(item_key)]
    if part.empty:
        return blank
    qty_col = "gross_qty" if "gross_qty" in part.columns else "qty"
    gross = float(part[qty_col].sum()) if qty_col in part.columns else 0.0
    returned = float(part["returned_qty"].sum()) if "returned_qty" in part.columns else 0.0
    cancel = 0.0
    if "status" in part.columns and qty_col in part.columns:
        mask = part["status"].map(_is_cancelled_status)
        cancel = float(part.loc[mask, qty_col].sum())
    return {"gross": gross, "cancel": cancel, "returned": returned}


def _same_day_last_month(day: date) -> date:
    """Tanggal kalender yang sama, satu bulan sebelumnya. Akhir bulan menempel di hari terakhir."""
    return (pd.Timestamp(day) - pd.DateOffset(months=1)).date()


def _short_id_date(value: date) -> str:
    return f"{value.day} {ID_MONTHS[value.month - 1][:3]}"


def _day_sold_map(orders: pd.DataFrame | None, day: date) -> dict[str, int] | None:
    """QTY terjual per SKU pada satu tanggal laporan. None bila tanggal itu di luar laporan."""
    if not isinstance(orders, pd.DataFrame) or orders.empty or "order_time" not in orders.columns:
        return None
    stamps = pd.to_datetime(orders["order_time"], errors="coerce").dt.normalize()
    if stamps.notna().sum() == 0:
        return None
    target = pd.Timestamp(day)
    if target < stamps.min() or target > stamps.max():
        return None
    part = orders.loc[stamps == target]
    if part.empty or "item_key" not in part.columns:
        return {}
    sold = part.groupby(part["item_key"].astype(str))["qty"].sum()
    return {key: int(round(float(value))) for key, value in sold.items()}


def _signed_pct(value: float, decimals: int = 1) -> str:
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{format_number(abs(value), decimals)}%"


def _share_text(value: float) -> str:
    return f"{format_number(value * 100, 0)}%"


def _order_window(part: pd.DataFrame, end: pd.Timestamp, back: int, length: int) -> pd.DataFrame:
    if part.empty or "order_time" not in part.columns:
        return part.iloc[0:0]
    stamps = pd.to_datetime(part["order_time"], errors="coerce").dt.normalize()
    high = end - pd.Timedelta(days=back)
    low = high - pd.Timedelta(days=length - 1)
    return part.loc[(stamps >= low) & (stamps <= high)]


def _promo_profile(part: pd.DataFrame | None) -> dict | None:
    """Harga, diskon, voucher, koin, ongkir, opsi kirim, dan metode bayar dari baris laporan."""
    if not isinstance(part, pd.DataFrame) or part.empty:
        return None
    unit_col = "gross_qty" if "gross_qty" in part.columns else "qty"
    units = pd.to_numeric(part[unit_col], errors="coerce").fillna(0)
    total = float(units.sum())
    if total <= 0:
        return None

    def _column(name: str) -> pd.Series | None:
        if name not in part.columns:
            return None
        series = pd.to_numeric(part[name], errors="coerce")
        return None if series.isna().all() else series.fillna(0)

    def _unit_share(mask: pd.Series) -> float:
        return float(units[mask].sum()) / total

    profile: dict = {"units": total}
    net = _column("net_price")
    listed = _column("list_price")
    value = 0.0
    if net is not None and float(net.sum()) > 0:
        base_list = listed.where(listed > 0, net) if listed is not None else net
        value = float((net * units).sum())
        list_value = float((base_list * units).sum())
        profile["net_price"] = value / total
        profile["list_price"] = list_value / total
        profile["discount_depth"] = 1 - value / list_value if list_value > 0 else 0.0
    for name in (
        "shopee_voucher",
        "seller_voucher",
        "coin_deduction",
        "coin_cashback",
        "card_discount",
        "buyer_shipping",
        "shipping_rebate",
    ):
        series = _column(name)
        if series is None:
            continue
        profile[f"{name}_share"] = _unit_share(series > 0)
        profile[f"{name}_amount"] = float(series.sum())
    if value > 0:
        profile["shopee_voucher_rate"] = profile.get("shopee_voucher_amount", 0.0) / value
        profile["seller_voucher_rate"] = profile.get("seller_voucher_amount", 0.0) / value
    if "shipping_rebate_amount" in profile:
        profile["rebate_per_unit"] = profile["shipping_rebate_amount"] / total
    for name, key in (("shipping_option", "ship"), ("payment_method", "pay")):
        if name not in part.columns:
            continue
        text = part[name].fillna("").astype(str).str.strip()
        by_units = units.groupby(text).sum()
        by_units = by_units[by_units.index != ""]
        if len(by_units) and float(by_units.sum()) > 0:
            profile[f"{key}_top"] = str(by_units.idxmax())
            profile[f"{key}_top_share"] = float(by_units.max()) / total
    if "shipping_option" in part.columns:
        lower = part["shipping_option"].fillna("").astype(str).str.lower()
        profile["cargo_share"] = _unit_share(lower.str.contains("kargo|trucking|jtr|cargo", regex=True))
    if "payment_method" in part.columns:
        lower = part["payment_method"].fillna("").astype(str).str.lower()
        profile["paylater_share"] = _unit_share(lower.str.contains("paylater|cicilan", regex=True))
        profile["cod_share"] = _unit_share(lower.str.contains(r"\bcod\b|bayar di tempat", regex=True))
    return profile


def _bar_spec(
    label: str,
    sub: str,
    predicted: int | None,
    sold: int | None,
    sold_sub: str,
) -> dict:
    """Satu batang. Kiri parameter, tengah prediksi dengan arah dan persen, kanan QTY terjual."""
    if predicted is None:
        return {
            "label": label,
            "sub": sub,
            "direction": "tetap",
            "text": "Prediksi belum bisa dihitung",
            "width": 100.0,
            "sold": "–" if sold is None else format_qty(sold),
            "sold_sub": "belum ada di laporan" if sold is None else sold_sub,
        }
    predicted = int(predicted)
    if sold is None:
        return {
            "label": label,
            "sub": sub,
            "direction": "tetap",
            "text": format_qty(predicted),
            "width": 100.0,
            "sold": "–",
            "sold_sub": "belum ada di laporan",
        }
    sold = int(sold)
    direction, text, _gap, _percent = _qty_pill(predicted, sold)
    peak = max(predicted, sold, 1)
    return {
        "label": label,
        "sub": sub,
        "direction": direction,
        "text": text,
        "width": predicted / peak * 100,
        "sold": format_qty(sold),
        "sold_sub": sold_sub,
    }


def _one_day_prediction_map(frame: pd.DataFrame | None, period: str, as_of: date) -> dict[str, int]:
    """Prediksi 1 hari untuk tanggal itu: Level terkini dihitung dari data latih sebelum tanggal itu, lalu dipotong 1 hari."""
    if frame is None or frame.empty or "item_key" not in frame.columns or "pred_qty" not in frame.columns:
        return {}
    horizon = max(horizon_day_count(period, as_of), 1)
    mapped: dict[str, int] = {}
    for record in frame.itertuples(index=False):
        qty, _sales, _stock = slice_forecast(
            float(getattr(record, "pred_qty", 0) or 0),
            float(getattr(record, "pred_sales", 0) or 0),
            float(getattr(record, "safety_stock", 0) or 0),
            horizon,
            1,
        )
        mapped[str(record.item_key)] = int(qty)
    return mapped


def _forecast_read(predicted: int | None, sold: int | None) -> str | None:
    """'lebih' bila terjual jauh di atas prediksi, 'kurang' bila jauh di bawah, 'pas' bila dekat."""
    if predicted is None or sold is None:
        return None
    predicted = int(predicted)
    sold = int(sold)
    if sold - predicted >= max(2, 0.2 * max(predicted, 1)):
        return "lebih"
    if predicted - sold >= max(2, 0.2 * max(predicted, 1)):
        return "kurang"
    return "pas"


def _accuracy_line(name: str, predicted: int | None, sold: int | None) -> str:
    """Satu kalimat: prediksi untuk tanggal itu dan QTY yang benar-benar terjual."""
    if predicted is None:
        return f"Prediksi untuk {name} belum bisa dihitung: data latih sebelum tanggal itu belum cukup."
    if sold is None:
        return f"Prediksi untuk {name}: {format_qty(predicted)} unit. Penjualannya belum ada di laporan."
    text = f"Prediksi untuk {name}: {format_qty(predicted)} unit, terjual {format_qty(sold)} unit."
    if sold <= 0:
        return text + " Tidak ada yang terjual pada tanggal itu."
    gap = int(predicted) - int(sold)
    if gap == 0:
        return text + " Tepat."
    way = "di atas" if gap > 0 else "di bawah"
    return text + f" Prediksi {_signed_pct(gap / sold * 100)} {way} realisasi."


def explain_qty_gap(
    row: pd.Series,
    history: pd.DataFrame | None,
    orders: pd.DataFrame | None,
    *,
    resume_label: str,
    period_text: str,
    horizon_days: int,
    exclude_cancel: bool,
    today: date | None = None,
    today_qty: int | None = None,
    yesterday_sold: int | None = None,
    month_ago_sold: int | None = None,
    yesterday_pred: int | None = None,
    month_ago_pred: int | None = None,
    data_end: pd.Timestamp | None = None,
) -> dict:
    """Analisa satu SKU. Bagian terjual dari laporan, bagian prediksi dari Level terkini. Prediksi tidak dihitung ulang."""
    today = today or date.today()
    yesterday = today - timedelta(days=1)
    month_ago = _same_day_last_month(today)
    y_name = f"kemarin ({_short_id_date(yesterday)})"
    m_name = _short_id_date(month_ago)
    month_label = f"{ID_MONTHS[today.month - 1]} {today.year}"
    key = str(row["item_key"])
    actual = int(round(float(row["qty_total"])))
    sold_value = float(row["sales_total"]) if "sales_total" in row.index and pd.notna(row["sales_total"]) else 0.0
    predicted = int(round(float(row["pred_qty"])))
    month_pred = (
        int(round(float(row["pred_qty_bulan"])))
        if "pred_qty_bulan" in row.index and pd.notna(row["pred_qty_bulan"])
        else predicted
    )
    month_sales = (
        float(row["pred_sales_bulan"]) if "pred_sales_bulan" in row.index and pd.notna(row["pred_sales_bulan"]) else 0.0
    )
    horizon = max(int(horizon_days), 1)
    if today_qty is None:
        today_qty = (
            int(round(float(row["pred_qty_hari"])))
            if "pred_qty_hari" in row.index and pd.notna(row["pred_qty_hari"])
            else int(slice_forecast(predicted, 0, 0, horizon, 1)[0])
        )
    today_qty = int(today_qty)
    direction, pill, gap, percent = _qty_pill(month_pred, actual)
    day_read = _forecast_read(yesterday_pred, yesterday_sold)
    ago_read = _forecast_read(month_ago_pred, month_ago_sold)
    safety = int(round(float(row["safety_stock"]))) if "safety_stock" in row and pd.notna(row["safety_stock"]) else 0
    stock_qty = int(round(float(row["stok_disarankan"]))) if "stok_disarankan" in row and pd.notna(row["stok_disarankan"]) else predicted + safety

    qty, sales = _daily_qty_sales(history, key)
    level, slope = _robust_state(qty, horizon) if len(qty) else (0.0, 0.0)
    recent = qty[-28:] if len(qty) else qty
    prior = qty[-56:-28] if len(qty) >= 56 else np.zeros(0, dtype=float)
    recent_units = int(round(float(recent.sum()))) if len(recent) else 0
    prior_units = int(round(float(prior.sum()))) if len(prior) else None
    run_rate = int(round(level * horizon))
    active_days = int((qty > 0).sum()) if len(qty) else 0
    uneven = len(qty) >= 14 and active_days / max(len(qty), 1) < 0.35

    part = orders
    if isinstance(orders, pd.DataFrame) and "item_key" in orders.columns:
        part = orders.loc[orders["item_key"].astype(str) == key]
    if data_end is None and isinstance(orders, pd.DataFrame) and "order_time" in orders.columns and not orders.empty:
        data_end = pd.to_datetime(orders["order_time"], errors="coerce").max()
    now_promo = then_promo = None
    if isinstance(part, pd.DataFrame) and not part.empty and data_end is not None and pd.notna(data_end):
        end = pd.Timestamp(data_end).normalize()
        now_promo = _promo_profile(_order_window(part, end, 0, 28))
        then_promo = _promo_profile(_order_window(part, end, 28, 28))
    promo = now_promo or {}
    before = then_promo or {}

    friction = _order_friction(orders, key)
    cancel_share = friction["cancel"] / friction["gross"] if friction["gross"] > 0 else 0.0
    return_share = friction["returned"] / friction["gross"] if friction["gross"] > 0 else 0.0
    high_cancel = (not exclude_cancel) and cancel_share >= 0.12
    high_return = (not exclude_cancel) and return_share >= 0.08

    busy_name = ""
    busy_share = 0.0
    if (
        len(qty) >= 14
        and float(qty.sum()) > 0
        and isinstance(history, pd.DataFrame)
        and not history.empty
        and "period_start" in history.columns
    ):
        real_start = pd.to_datetime(history["period_start"], errors="coerce").dt.normalize().min()
        if pd.notna(real_start):
            stamps = pd.date_range(real_start, periods=len(qty), freq="D")
            totals = pd.Series(qty, index=stamps).groupby(lambda stamp: int(stamp.dayofweek)).sum()
            if float(totals.sum()) > 0:
                busy_share = float(totals.max()) / float(totals.sum())
                busy_name = _WEEKDAY_ID[int(totals.idxmax())]

    voucher_share = float(promo.get("shopee_voucher_share", 0.0))
    voucher_before = before.get("shopee_voucher_share")
    voucher_rate = float(promo.get("shopee_voucher_rate", 0.0))
    depth = float(promo.get("discount_depth", 0.0))
    depth_before = before.get("discount_depth")
    net_price = promo.get("net_price")
    net_before = before.get("net_price")
    paylater = float(promo.get("paylater_share", 0.0))
    cod = float(promo.get("cod_share", 0.0))
    cargo = float(promo.get("cargo_share", 0.0))
    buyer_ship = float(promo.get("buyer_shipping_share", 0.0))
    rebate = float(promo.get("rebate_per_unit", 0.0))
    seller_voucher = float(promo.get("seller_voucher_share", 0.0))
    coin = max(float(promo.get("coin_deduction_share", 0.0)), float(promo.get("coin_cashback_share", 0.0)))
    card = float(promo.get("card_discount_share", 0.0))
    voucher_led = voucher_share >= 0.4
    price_change = (net_price / net_before - 1) if net_price and net_before else 0.0

    factors: list[dict[str, str]] = []

    def _factor(label: str, tone: str) -> None:
        if len(factors) < 7:
            factors.append({"label": label, "tone": tone})

    if prior_units is not None and prior_units > 0:
        pace = recent_units / prior_units - 1
        if pace >= 0.08:
            _factor(f"Laku 4 minggu naik {format_number(pace * 100, 0)}%", "up")
        elif pace <= -0.08:
            _factor(f"Laku 4 minggu turun {format_number(abs(pace) * 100, 0)}%", "down")
        else:
            _factor("Laku 4 minggu stabil", "flat")
    elif len(qty) < 28:
        _factor("Riwayat masih pendek", "flat")
    if voucher_led:
        _factor(f"Voucher Shopee {_share_text(voucher_share)} unit", "flat")
    if depth >= 0.03:
        _factor(f"Diskon penjual {format_number(depth * 100, 1)}%", "flat")
    if paylater >= 0.3:
        _factor(f"PayLater/cicilan {_share_text(paylater)}", "flat")
    if cargo >= 0.5:
        _factor(f"Kargo {_share_text(cargo)}", "flat")
    if high_cancel:
        _factor(f"Batal {format_number(cancel_share * 100, 1)}%", "down")
    if high_return:
        _factor(f"Retur {format_number(return_share * 100, 1)}%", "down")
    if busy_name and busy_share >= 0.28:
        _factor(f"Puncak hari {busy_name}", "flat")

    # Bagian 1: yang sudah terjual. Fakta laporan saja, tanpa angka prediksi.
    sold_lines: list[str] = []
    month_line = f"{resume_label}: terjual {format_qty(actual)} unit"
    if sold_value > 0:
        month_line += f", senilai {format_idr(sold_value)}"
    month_line += "."
    if net_price:
        month_line += f" Harga bersih rata-rata 4 minggu terakhir {format_idr(net_price)} per unit"
        if depth >= 0.02:
            month_line += f", {format_number(depth * 100, 1)}% di bawah harga awal {format_idr(promo.get('list_price', net_price))}"
        month_line += "."
    sold_lines.append(month_line)
    day_bits = []
    day_bits.append(
        f"Kemarin ({_short_id_date(yesterday)}) belum ada di laporan."
        if yesterday_sold is None
        else f"Kemarin ({_short_id_date(yesterday)}) terjual {format_qty(yesterday_sold)} unit."
    )
    day_bits.append(
        f"Tanggal {m_name} belum ada di laporan."
        if month_ago_sold is None
        else f"Tanggal {m_name} terjual {format_qty(month_ago_sold)} unit."
    )
    if yesterday_sold is not None and month_ago_sold:
        swing = (yesterday_sold - month_ago_sold) / month_ago_sold * 100
        if abs(swing) >= 1:
            day_bits.append(f"Kemarin {'lebih ramai' if swing > 0 else 'lebih sepi'} {format_number(abs(swing), 0)}% dibanding tanggal yang sama bulan lalu.")
    sold_lines.append(" ".join(day_bits))
    if prior_units is not None and prior_units > 0:
        pace = recent_units / prior_units - 1
        if pace >= 0.08:
            sold_lines.append(
                f"Empat minggu terakhir laku {format_qty(recent_units)} unit, naik {format_number(pace * 100, 0)}% "
                f"dari {format_qty(prior_units)} unit empat minggu sebelumnya."
            )
        elif pace <= -0.08:
            sold_lines.append(
                f"Empat minggu terakhir laku {format_qty(recent_units)} unit, turun {format_number(abs(pace) * 100, 0)}% "
                f"dari {format_qty(prior_units)} unit empat minggu sebelumnya."
            )
        else:
            sold_lines.append(
                f"Empat minggu terakhir laku {format_qty(recent_units)} unit, setara empat minggu sebelumnya ({format_qty(prior_units)} unit)."
            )
    elif len(qty):
        sold_lines.append(f"Empat minggu terakhir laku {format_qty(recent_units)} unit. Riwayat sebelumnya belum cukup untuk dibandingkan.")

    driver_bits: list[str] = []
    if voucher_share >= 0.2:
        text = (
            f"{_share_text(voucher_share)} unit terjual memakai voucher Shopee, rata-rata {format_number(voucher_rate * 100, 1)}% dari harga"
        )
        if voucher_before is not None and abs(voucher_share - float(voucher_before)) >= 0.15:
            text += f" (sebelumnya {_share_text(float(voucher_before))})"
        driver_bits.append(text + ".")
    if depth_before is not None and abs(depth - float(depth_before)) >= 0.03:
        driver_bits.append(
            f"Diskon penjual {'diperdalam' if depth > float(depth_before) else 'dikurangi'} dari "
            f"{format_number(float(depth_before) * 100, 1)}% menjadi {format_number(depth * 100, 1)}%."
        )
    elif abs(price_change) >= 0.05:
        driver_bits.append(f"Harga bersih {'naik' if price_change > 0 else 'turun'} {format_number(abs(price_change) * 100, 1)}% dibanding empat minggu sebelumnya.")
    if seller_voucher >= 0.1:
        driver_bits.append(f"{_share_text(seller_voucher)} unit memakai voucher toko.")
    if coin >= 0.15:
        driver_bits.append(f"{_share_text(coin)} unit memakai koin Shopee.")
    if card >= 0.15:
        driver_bits.append(f"{_share_text(card)} unit memakai diskon kartu kredit.")
    if paylater >= 0.2:
        driver_bits.append(f"{_share_text(paylater)} unit dibayar dengan PayLater atau cicilan.")
    elif promo.get("pay_top") and float(promo.get("pay_top_share", 0)) >= 0.35:
        driver_bits.append(f"Cara bayar terbanyak {promo['pay_top']} ({_share_text(float(promo['pay_top_share']))}).")
    if cod >= 0.15:
        driver_bits.append(f"COD {_share_text(cod)} unit, rawan batal saat barang tiba.")
    if cargo >= 0.5:
        ship_text = f"{_share_text(cargo)} unit dikirim lewat kargo"
        if promo.get("ship_top"):
            ship_text += f", terbanyak {promo['ship_top']}"
        if rebate > 0:
            ship_text += f". Estimasi potongan ongkir {format_idr(rebate)} per unit"
        driver_bits.append(ship_text + ".")
    elif promo.get("ship_top") and float(promo.get("ship_top_share", 0)) >= 0.35:
        driver_bits.append(f"Pengiriman terbanyak {promo['ship_top']} ({_share_text(float(promo['ship_top_share']))}).")
    if buyer_ship >= 0.2:
        driver_bits.append(f"{_share_text(buyer_ship)} unit pembelinya masih membayar ongkir sendiri.")
    if driver_bits:
        sold_lines.append(" ".join(driver_bits))

    leak_bits: list[str] = []
    if exclude_cancel:
        leak_bits.append("Pesanan batal dan unit retur sudah dikeluarkan sesuai pengaturan.")
    elif high_cancel:
        leak_bits.append(
            f"Batal {format_qty(friction['cancel'])} unit, {format_number(cancel_share * 100, 1)}% dari qty kotor. Order masuk, uang belum."
        )
    elif friction["cancel"] > 0:
        leak_bits.append(f"Batal {format_qty(friction['cancel'])} unit ({format_number(cancel_share * 100, 1)}%), masih terkendali.")
    if high_return:
        leak_bits.append(f"Retur {format_qty(friction['returned'])} unit ({format_number(return_share * 100, 1)}%).")
    if uneven:
        leak_bits.append("Penjualan datang dari beberapa hari ramai, bukan arus harian yang rata.")
    if busy_name and busy_share >= 0.28:
        leak_bits.append(f"Hari paling ramai {busy_name}, {format_number(busy_share * 100, 0)}% dari qty.")
    if leak_bits:
        sold_lines.append(" ".join(leak_bits))

    # Bagian 2: yang diprediksi. Angka Level terkini yang sudah dikunci.
    pred_lines: list[str] = []
    month_pred_line = f"Prediksi {month_label}: {format_qty(month_pred)} unit"
    if month_sales > 0:
        month_pred_line += f", sales {format_idr(month_sales)}"
    month_pred_line += "."
    if actual > 0 and gap != 0:
        month_pred_line += (
            f" Itu {format_qty(abs(gap))} unit {'di atas' if gap > 0 else 'di bawah'} yang sudah terjual pada {resume_label} "
            f"({_signed_pct(percent or 0, 2)})."
        )
    elif actual > 0:
        month_pred_line += f" Sama dengan yang sudah terjual pada {resume_label}."
    pred_lines.append(month_pred_line)
    pred_lines.append(_accuracy_line(f"kemarin ({_short_id_date(yesterday)})", yesterday_pred, yesterday_sold))
    pred_lines.append(_accuracy_line(m_name, month_ago_pred, month_ago_sold))
    pred_lines.append(f"Prediksi hari ini ({_short_id_date(today)}): {format_qty(today_qty)} unit.")
    trend = "naik" if slope > 1e-4 else "turun" if slope < -1e-4 else "datar"
    if len(qty):
        pred_lines.append(
            f"Model membaca rata-rata {format_number(level, 1)} unit per hari dari 28 hari terakhir dengan tren {trend}."
        )
    pred_lines.append(
        f"Stok yang dikunci untuk {period_text}: {format_qty(stock_qty)} unit, yaitu prediksi {format_qty(predicted)} ditambah cadangan {format_qty(safety)}."
    )
    risk_bits: list[str] = []
    if voucher_led:
        risk_bits.append(
            f"Prediksi menganggap voucher Shopee tetap berjalan seperti 4 minggu terakhir ({_share_text(voucher_share)} unit). "
            "Kalau voucher berhenti, realisasi bisa di bawah angka ini."
        )
    if depth >= 0.08:
        risk_bits.append(f"Prediksi juga menganggap diskon penjual {format_number(depth * 100, 1)}% tetap dipasang.")
    if high_cancel:
        risk_bits.append("Qty batal ikut terbaca sebagai permintaan, jadi prediksi bisa terlalu tinggi.")
    if risk_bits:
        pred_lines.append("Risiko: " + " ".join(risk_bits))

    # Keputusan
    if high_cancel:
        recommendation = (
            "Tagih dulu pembayaran yang menggantung. Pesanan batal bukan permintaan, jadi stok dan iklan baru ditambah setelah batal di bawah 12%."
        )
    elif direction == "naik" and voucher_led:
        recommendation = (
            f"Permintaan naik, tetapi {_share_text(voucher_share)} unit ditopang voucher Shopee. "
            f"Kunci stok {format_qty(stock_qty)} unit dan pastikan SKU ikut kampanye voucher berikutnya sebelum menaikkan iklan."
        )
    elif direction == "naik" and depth >= 0.08:
        recommendation = (
            f"Permintaan naik dengan diskon {format_number(depth * 100, 1)}%. Kunci stok {format_qty(stock_qty)} unit, "
            "lalu uji tipiskan diskon untuk menjaga margin selama permintaan masih kuat."
        )
    elif direction == "naik":
        recommendation = (
            f"Permintaan naik secara organik. Kunci stok {format_qty(stock_qty)} unit sekarang dan tambah iklan pencarian pada nama produk ini."
        )
    elif direction == "turun" and depth < 0.03 and not voucher_led:
        recommendation = (
            "Permintaan melambat dan harga belum didorong promo. Uji diskon penjual atau voucher toko kecil selama 7 hari sebelum memotong stok."
        )
    elif direction == "turun":
        recommendation = (
            "Permintaan melambat meski promo sudah jalan. Jangan menambah diskon. Kunci stok ke prediksi yang lebih rendah dan alihkan iklan ke SKU yang naik."
        )
    else:
        recommendation = "Permintaan stabil. Pertahankan stok dan budget, jaga harga dan rating listing."
    if day_read == "lebih":
        recommendation += (
            f" Kemarin laku {format_qty(yesterday_sold)} dari prediksi {format_qty(yesterday_pred)}. "
            "Permintaan lebih kuat dari perkiraan model, jadi stok harus tampil sejak pagi."
        )
    elif day_read == "kurang":
        recommendation += (
            f" Kemarin hanya laku {format_qty(yesterday_sold)} dari prediksi {format_qty(yesterday_pred)}. "
            "Cari penyebabnya sebelum menambah budget."
        )

    steps: list[dict[str, str]] = []

    def _step(title: str, body: str) -> None:
        if len(steps) < 5:
            steps.append({"title": title, "body": body})

    if high_cancel:
        _step(
            "Kejar bayar",
            f"Chat pembeli yang belum bayar hari ini. {format_qty(friction['cancel'])} unit batal tidak boleh dihitung sebagai permintaan.",
        )
    if high_return:
        _step(
            "Rapikan listing",
            f"Cek varian, packing, dan bobot. Retur {format_qty(friction['returned'])} unit. Tahan PO tambahan sampai komplain ditutup.",
        )
    _step(
        "Kunci stok",
        f"Siapkan {format_qty(stock_qty)} unit untuk {period_text}: prediksi {format_qty(predicted)} + cadangan {format_qty(safety)}. "
        "Jangan memesan sebesar qty laporan atau qty batal.",
    )
    if day_read == "lebih":
        _step(
            "Kejar momentum hari ini",
            f"Kemarin laku {format_qty(yesterday_sold)}, prediksi {format_qty(yesterday_pred)}. Prediksi hari ini {format_qty(today_qty)}. "
            "Cek apakah dorongannya voucher, flash sale, atau pembeli proyek, lalu pastikan stok tampil dan iklan nama produk aktif sejak pagi.",
        )
    elif day_read == "kurang":
        _step(
            "Bedah kemarin",
            f"Kemarin laku {format_qty(yesterday_sold)} dari prediksi {format_qty(yesterday_pred)}. "
            "Cek stok kosong, harga berubah, voucher berhenti, atau iklan mati sebelum hari ini berjalan.",
        )
    if ago_read == "kurang":
        _step(
            f"Bandingkan dengan {m_name}",
            f"Tanggal itu laku {format_qty(month_ago_sold)} dari prediksi {format_qty(month_ago_pred)}. "
            "Kalau hari ini memakai harga dan voucher yang sama, target harian berisiko meleset dengan pola yang sama.",
        )
    if voucher_led:
        _step(
            "Amankan voucher",
            f"{_share_text(voucher_share)} unit memakai voucher Shopee. Daftarkan SKU ke kampanye berikutnya dan siapkan voucher toko "
            f"cadangan sekitar {format_number(voucher_rate * 100, 0)}% kalau voucher Shopee berhenti.",
        )
    if direction == "naik" and depth >= 0.08 and not voucher_led:
        _step(
            "Tipiskan diskon",
            f"Diskon penjual {format_number(depth * 100, 1)}%. Permintaan sedang naik, jadi kurangi diskon bertahap dan pantau 7 hari.",
        )
    if direction == "turun" and depth < 0.03 and not voucher_led:
        _step(
            "Uji promo harga",
            "Harga hampir tanpa diskon. Uji diskon penjual atau voucher toko selama 7 hari, lalu bandingkan dengan prediksi.",
        )
    if paylater >= 0.3:
        _step(
            "Tonjolkan cicilan",
            f"{_share_text(paylater)} unit dibayar dengan PayLater atau cicilan. Tampilkan cicilan di foto utama dan nama promo.",
        )
    if cargo >= 0.5:
        _step(
            "Jual ongkirnya",
            f"{_share_text(cargo)} unit lewat kargo. Tulis berat dan opsi kargo di foto supaya pembeli tidak kaget ongkir saat checkout.",
        )
    if buyer_ship >= 0.2:
        _step(
            "Ikut gratis ongkir",
            f"{_share_text(buyer_ship)} unit pembelinya bayar ongkir sendiri. Ikutkan SKU ke program gratis ongkir.",
        )
    if direction == "naik" and not high_cancel and not voucher_led and day_read != "kurang":
        body = "Kata kunci exact pada nama produk. Jangan nyalakan maximize clicks."
        if busy_name and busy_share >= 0.28:
            body += f" Naikkan bid pada hari {busy_name}, turunkan di hari sepi."
        _step("Naikkan iklan pencarian", body)
    elif direction == "turun":
        _step("Pindahkan budget iklan", "Tahan iklan SKU ini dan geser budget ke SKU yang prediksinya naik.")
    if not high_cancel and cancel_share > 0 and not exclude_cancel:
        _step(
            "Pantau batal",
            f"Batal {format_number(cancel_share * 100, 1)}%. Kalau menembus 12%, hentikan penambahan iklan.",
        )

    footnote = "Bagian terjual dibaca dari laporan transaksi. Bagian prediksi memakai Level terkini yang sudah dikunci, tidak dihitung ulang."
    titles = {
        "naik": "Prediksi bulan di atas terjual",
        "turun": "Prediksi bulan di bawah terjual",
        "tetap": "Prediksi bulan sama dengan terjual",
    }
    resume_short = resume_label if len(resume_label) <= 18 else "Periode laporan"
    bars = [
        _bar_spec("Bulan ini", resume_short, month_pred, actual, "terjual"),
        _bar_spec("Kemarin", _short_id_date(yesterday), yesterday_pred, yesterday_sold, "terjual"),
        _bar_spec("Bulan lalu", m_name, month_ago_pred, month_ago_sold, "terjual"),
    ]
    return {
        "direction": direction,
        "bars": bars,
        "month_pred": month_pred,
        "month_label": month_label,
        "today_qty": today_qty,
        "yesterday_sold": yesterday_sold,
        "month_ago_sold": month_ago_sold,
        "yesterday_pred": yesterday_pred,
        "month_ago_pred": month_ago_pred,
        "pill": pill,
        "gap": gap,
        "percent": percent,
        "predicted": month_pred,
        "actual": actual,
        "kicker": titles[direction],
        "factors": factors,
        "sold_lines": sold_lines,
        "pred_lines": pred_lines,
        "recommendation": recommendation,
        "steps": steps,
        "footnote": footnote,
        "resume_label": resume_label,
        "period_text": period_text,
        "safety": safety,
        "stock_qty": stock_qty,
        "busy_name": busy_name,
        "busy_share": busy_share,
        "run_rate": run_rate,
    }


def _insight_markup(row: pd.Series, brief: dict) -> str:
    name = html.escape(_clean_product_piece(row["product_name"], "Tanpa nama"))
    sku = html.escape(_clean_product_piece(row["sku"], "Tanpa SKU"))
    variance = html.escape(_clean_product_piece(row["variasi_tampil"], "Tanpa variasi"))
    direction = brief["direction"]
    head_tone = {"naik": "up", "turun": "down", "tetap": "flat"}.get(direction, "flat")
    gap = int(brief["gap"])
    percent = brief["percent"]
    if percent is None:
        value = format_qty(brief["month_pred"])
    else:
        unit = f"{'+' if gap > 0 else '−' if gap < 0 else ''}{format_qty(abs(gap))} unit"
        value = f"{_signed_pct(percent, 2)} <span>({unit})</span>"
    chips = "".join(
        f"<span class='insight-chip {html.escape(item['tone'])}'>{html.escape(item['label'])}</span>"
        for item in brief["factors"]
    )
    sold = "".join(f"<p class='insight-copy'>{html.escape(text)}</p>" for text in brief["sold_lines"])
    pred = "".join(f"<p class='insight-copy'>{html.escape(text)}</p>" for text in brief["pred_lines"])
    steps = "".join(
        "<li class='insight-step'>"
        f"<span class='insight-step-no'>{index}</span>"
        f"<div><strong>{html.escape(step['title'])}</strong>{html.escape(step['body'])}</div>"
        "</li>"
        for index, step in enumerate(brief["steps"], start=1)
    )
    return (
        f"<div class='insight-head {head_tone}'>"
        f"<div class='insight-kicker'>{html.escape(brief['kicker'])}</div>"
        f"<div class='insight-title'>{name}</div>"
        f"<div class='insight-meta'>SKU {sku} · Variance: {variance}</div>"
        "</div>"
        "<div class='insight-stat'>"
        f"<div class='insight-stat-label'>Prediksi {html.escape(brief['month_label'])} dibanding terjual</div>"
        f"<div class='insight-stat-value'>{value}</div>"
        f"<div class='insight-stat-note'>Prediksi {html.escape(format_qty(brief['month_pred']))} unit. "
        f"Terjual {html.escape(format_qty(brief['actual']))} unit pada {html.escape(brief['resume_label'])}.</div>"
        "</div>"
        f"<div class='insight-chips'>{chips}</div>"
        "<div class='insight-section'>Yang sudah terjual (laporan)</div>"
        f"{sold}"
        "<div class='insight-section'>Yang diprediksi (Level terkini)</div>"
        f"{pred}"
        f"<p class='insight-note'>{html.escape(brief['footnote'])}</p>"
        "<div class='insight-section'>Keputusan</div>"
        f"<p class='insight-reco'>{html.escape(brief['recommendation'])}</p>"
        "<div class='insight-section'>Langkah kerja, urutan prioritas</div>"
        f"<ol class='insight-steps'>{steps}</ol>"
    )


@st.dialog("Analisa prediksi", width="large", on_dismiss=_dismiss_qty_insight)
def _qty_insight_dialog(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)
    if st.button("Paham & Tutup", type="primary", key="qty-insight-close"):
        _dismiss_qty_insight()
        st.rerun()


def _qty_card_html(row: pd.Series, brief: dict) -> str:
    rank = int(row["peringkat"]) if pd.notna(row["peringkat"]) else 0
    sku = html.escape(_clean_product_piece(row["sku"], "Tanpa SKU"))
    name = html.escape(_clean_product_piece(row["product_name"], "Tanpa nama"))
    variance = html.escape(_clean_product_piece(row["variasi_tampil"], "Tanpa variasi"))
    lines = []
    for bar in brief["bars"]:
        lines.append(
            "<div class='qty-line'>"
            f"<div class='qty-metric'>{html.escape(bar['label'])}<small>{html.escape(bar['sub'])}</small></div>"
            "<div class='qty-track'>"
            f"<div class='qty-fill {html.escape(bar['direction'])}' style='width:{float(bar['width']):.1f}%'>"
            f"<span>{html.escape(bar['text'])}</span></div></div>"
            f"<div class='qty-base'>{html.escape(bar['sold'])}<small>{html.escape(bar['sold_sub'])}</small></div>"
            "</div>"
        )
    return (
        "<div class='qty-card'>"
        "<div class='qty-id'>"
        f"<div class='qty-rank'>{rank}. SKU {sku}</div>"
        f"<div class='qty-name'>{name}</div>"
        f"<div class='qty-var'>Product variance {variance}</div>"
        "</div>"
        "<div class='qty-line qty-head-row'>"
        "<div class='qty-metric'>Periode</div><div class='qty-head-mid'>Prediksi</div><div class='qty-base'>Terjual</div>"
        "</div>"
        f"{''.join(lines)}"
        "</div>"
    )


def show_qty_forecast_board(
    view: pd.DataFrame,
    *,
    resume_label: str,
    period_text: str,
    horizon_days: int,
    history: pd.DataFrame | None,
    orders: pd.DataFrame | None,
    exclude_cancel: bool,
    as_of: date | None = None,
    stock: pd.DataFrame | None = None,
    period: str = "bulan",
    service: int = 0,
    source_key: str = "",
) -> None:
    """Grafik Top 50. Satu pola untuk setiap SKU: bulan ini, kemarin, dan tanggal yang sama bulan lalu."""
    if view.empty:
        st.write("Tidak ada item untuk grafik ini.")
        return
    as_of = as_of or date.today()
    yesterday = as_of - timedelta(days=1)
    month_ago = _same_day_last_month(as_of)
    yesterday_map = _day_sold_map(orders, yesterday)
    month_ago_map = _day_sold_map(orders, month_ago)
    yesterday_pred_map: dict[str, int] | None = None
    month_ago_pred_map: dict[str, int] | None = None
    if isinstance(history, pd.DataFrame) and not history.empty:
        frame_args = dict(
            live_stock=stock,
            live_day=as_of,
            history=history,
            period=period,
            service=int(service),
            source_key=source_key,
        )
        yesterday_pred_map = _one_day_prediction_map(_movement_frame(yesterday, **frame_args), period, yesterday) or None
        month_ago_pred_map = _one_day_prediction_map(_movement_frame(month_ago, **frame_args), period, month_ago) or None
    data_end = None
    groups: dict[str, pd.DataFrame] = {}
    if isinstance(orders, pd.DataFrame) and not orders.empty and "item_key" in orders.columns:
        data_end = pd.to_datetime(orders["order_time"], errors="coerce").max()
        keys = set(view["item_key"].astype(str))
        scoped = orders.loc[orders["item_key"].astype(str).isin(keys)]
        groups = {str(key): part for key, part in scoped.groupby(scoped["item_key"].astype(str))}
    st.markdown(
        "<div class='qty-board-head'>"
        "<div class='qty-board-title'>QTY terjual dan prediksi</div>"
        "<p class='qty-board-copy'>Kiri adalah periode. Tengah adalah prediksi dengan arah dan persentase terhadap QTY terjual. "
        "Kanan adalah QTY terjual pada periode itu. Hijau berarti prediksi di atas terjual, merah berarti di bawah. "
        "Prediksi kemarin dan bulan lalu dihitung Level terkini dari data latih sebelum tanggal itu, dengan periode dan safety stock yang sama.</p>"
        "</div>",
        unsafe_allow_html=True,
    )
    work = view.sort_values(["peringkat", "item_key"], kind="mergesort").reset_index(drop=True)
    briefs = {}
    for _, row in work.iterrows():
        key = str(row["item_key"])
        today_qty = (
            int(round(float(row["pred_qty_hari"])))
            if "pred_qty_hari" in row.index and pd.notna(row["pred_qty_hari"])
            else None
        )
        briefs[key] = explain_qty_gap(
            row,
            history,
            groups.get(key, orders.iloc[0:0] if isinstance(orders, pd.DataFrame) else None),
            resume_label=resume_label,
            period_text=period_text,
            horizon_days=horizon_days,
            exclude_cancel=exclude_cancel,
            today=as_of,
            today_qty=today_qty,
            yesterday_sold=None if yesterday_map is None else yesterday_map.get(key, 0),
            month_ago_sold=None if month_ago_map is None else month_ago_map.get(key, 0),
            yesterday_pred=None if yesterday_pred_map is None else yesterday_pred_map.get(key, 0),
            month_ago_pred=None if month_ago_pred_map is None else month_ago_pred_map.get(key, 0),
            data_end=data_end,
        )
    counts = {"naik": 0, "turun": 0, "tetap": 0}
    for brief in briefs.values():
        counts[brief["direction"]] += 1
    if "qty-board-direction" not in st.session_state:
        st.session_state["qty-board-direction"] = "Semua"
    st.markdown("<div class='qty-board-anchor'></div>", unsafe_allow_html=True)
    search_col, all_col, up_col, down_col, flat_col = st.columns([2.3, 0.7, 0.85, 0.9, 0.75])
    query = search_col.text_input(
        "Cari SKU atau nama produk",
        placeholder="Cari SKU atau Nama Produk..",
        label_visibility="collapsed",
        key="qty-board-search",
    )
    current = st.session_state["qty-board-direction"]
    filters = (
        (all_col, "Semua", "Semua"),
        (up_col, "Naik", "▲ Naik"),
        (down_col, "Turun", "▼ Turun"),
        (flat_col, "Tetap", "– Tetap"),
    )
    for column, name, label in filters:
        if column.button(label, key=f"qty-board-filter-{name}", type="primary" if current == name else "secondary", use_container_width=True):
            st.session_state["qty-board-direction"] = name
            st.rerun()
    month_name = f"{ID_MONTHS[as_of.month - 1]} {as_of.year}"
    st.markdown(
        "<div class='qty-legend'><span><i class='up'></i>Naik</span><span><i class='down'></i>Turun</span><span><i class='flat'></i>Tetap</span></div>"
        f"<p class='qty-board-copy'>{counts['naik']} naik, {counts['turun']} turun, {counts['tetap']} tetap pada baris Bulan ini "
        f"(prediksi {html.escape(month_name)} dibanding terjual {html.escape(resume_label)}). "
        f"Baris Kemarin adalah prediksi untuk {html.escape(_short_id_date(yesterday))} dibanding terjual {html.escape(_short_id_date(yesterday))}. "
        f"Baris Bulan lalu adalah prediksi untuk {html.escape(_short_id_date(month_ago))} dibanding terjual {html.escape(_short_id_date(month_ago))}. "
        f"Stok tetap dikunci untuk {html.escape(period_text)}.</p>",
        unsafe_allow_html=True,
    )
    needle = " ".join(str(query or "").lower().split())
    shown_rows = []
    for _, row in work.iterrows():
        brief = briefs[str(row["item_key"])]
        if current != "Semua" and brief["direction"] != current.lower():
            continue
        if needle:
            blob = " ".join(
                [
                    str(row["sku"]),
                    str(row["product_name"]),
                    str(row["variasi_tampil"]),
                ]
            ).lower()
            if needle not in blob:
                continue
        shown_rows.append(row)
    if not shown_rows:
        st.info("Tidak ada SKU pada saringan ini.")
    for row in shown_rows:
        key = str(row["item_key"])
        brief = briefs[key]
        st.markdown("<div class='qty-row-anchor'></div>", unsafe_allow_html=True)
        card_col, action_col = st.columns([7.4, 1.15], vertical_alignment="center")
        card_col.markdown(_qty_card_html(row, brief), unsafe_allow_html=True)
        if action_col.button("Analisa", key=f"qty-insight-open-{key}", use_container_width=True):
            st.session_state["qty-insight-key"] = key
            st.rerun()
    selected = str(st.session_state.get("qty-insight-key") or "")
    if selected and selected in briefs:
        match = work.loc[work["item_key"].astype(str) == selected]
        if not match.empty:
            _qty_insight_dialog(_insight_markup(match.iloc[0], briefs[selected]))


def show_section_title(text: str) -> None:
    st.markdown(f"<div class='chart-heading'>{text}</div>", unsafe_allow_html=True)


def show_data_menu(source_raw: pd.DataFrame) -> None:
    """Gabungan semua file, dengan ringkasan periode dan satu daftar SKU retur serta batal."""
    active_keys = tuple(st.session_state.get("active-library-keys") or ())
    if active_keys:
        ledger = cached_ledger(active_keys, bundle_stamp(list(active_keys)))
    else:
        ledger = ledger_from_raw(source_raw)
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
    st.markdown("<div class='section-title'>Status pesanan</div>", unsafe_allow_html=True)
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
    offer_excel(status_view, "status_pesanan.xlsx")
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
        offer_excel(contribution_view, "kontribusi_invoice_batal.xlsx")
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
        offer_excel(unpaid, "pembeli_belum_bayar.xlsx")
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
    st.markdown("<div class='section-title'>Alasan</div>", unsafe_allow_html=True)
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
            "SKU",
            "Product Name",
            "Product variance",
            "Qty retur",
            "Nominal retur",
            "Alasan retur",
        ]
        sheet_title = "Hanya kolom retur. Diurutkan dari qty retur terbesar."
    elif issue_kind == "Batal":
        keep_columns = [
            "Peringkat",
            "SKU",
            "Product Name",
            "Product variance",
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
        shown_sheet = append_total_row(shown_sheet, "SKU", sum_columns)
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
        offer_excel(shown_sheet, "sku_retur_batal.xlsx")
    st.subheader("Tabel gabungan dari semua file")
    active_keys = tuple(st.session_state.get("active-library-keys") or ())
    if active_keys:
        merged_base, month_keys = cached_merged(active_keys, bundle_stamp(list(active_keys)))
    else:
        merged_base = source_raw.drop(columns=["Nama file"], errors="ignore").drop_duplicates().reset_index(drop=True)
        month_keys = order_month_keys(merged_base)
    month_values = sorted({key for key in month_keys.tolist() if key and key != "tanpa-bulan"})
    years = sorted({key[:4] for key in month_values})
    st.markdown("<div class='section-title'>Filter tabel</div>", unsafe_allow_html=True)
    selected_months: list[str] = []
    if not years:
        st.caption("Tidak ada bulan pada lampiran.")
    else:
        checked_years = _select_years(
            years,
            pick_key="merged-year-pick",
            applied_key="merged-year-applied",
            box_prefix="merged-year-on-",
        )
        previous_years = [year for year in (st.session_state.get("merged_years") or []) if year in years]
        if not previous_years:
            previous_years = [years[-1]]
        year_months = [key for key in month_values if key[:4] in set(checked_years)]
        known_months = st.session_state.get("merged_months")
        saved_months = [key for key in known_months if key in year_months] if isinstance(known_months, list) else []
        if not saved_months and not isinstance(known_months, list) and year_months:
            saved_months = [year_months[-1]]
        newly = {year for year in checked_years if year not in previous_years}
        st.markdown("<div class='section-title tight'>Bulan</div>", unsafe_allow_html=True)
        for start in range(0, len(year_months), 4):
            box_columns = st.columns(4)
            for offset, key in enumerate(year_months[start : start + 4]):
                widget = f"merged-month-{key}"
                if widget not in st.session_state:
                    st.session_state[widget] = True if key[:4] in newly else key in saved_months
                with box_columns[offset]:
                    if st.checkbox(month_label(key), key=widget):
                        selected_months.append(key)
        st.session_state["merged_years"] = checked_years
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
        merged_view = present_product_columns(merged)
        st.dataframe(merged_view, height=680, hide_index=True)
        offer_excel(merged_view, "tabel_gabungan.xlsx")


def present_product_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """SKU di kiri nama produk, Product variance di kanannya, pada tabel yang masih memakai nama lampiran."""
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return frame
    mapping: dict[str, str] = {}
    for column in frame.columns:
        label = str(column).strip().lower()
        if label in {"sku", "referensi sku"} or "referensi sku" in label:
            mapping.setdefault("SKU", str(column))
        elif label in {"product name", "nama produk", "produk"}:
            mapping.setdefault("Product Name", str(column))
        elif label in {"product variance", "variasi", "nama variasi", "varian"}:
            mapping.setdefault("Product variance", str(column))
    if "Product Name" not in mapping:
        return frame
    sources = set(mapping.values())
    original = [str(column) for column in frame.columns]
    first = min(index for index, column in enumerate(original) if column in sources)
    before = sum(1 for column in original[:first] if column not in sources)
    rename = {source: target for target, source in mapping.items() if source != target}
    work = frame.rename(columns=rename)
    ordered = [column for column in ("SKU", "Product Name", "Product variance") if column in work.columns]
    rest = [rename.get(column, column) for column in original if column not in sources]
    return work.loc[:, rest[:before] + ordered + rest[before:]]


def _slide_head(kicker: str, title: str) -> None:
    st.markdown(
        "<div class='report-stage-head'>"
        f"<div class='report-kicker'>{html.escape(kicker)}</div>"
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
        f"<div class='report-stage-head'><div class='report-kicker'>{html.escape(scope_label)}</div>"
        "<div class='report-title'>Strategi dan rencana minggu ini</div></div>"
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
    st.markdown(
        f"<div class='field-hint'>Slide {position + 1} dari {len(titles)}</div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div class='slide-nav'></div>", unsafe_allow_html=True)
    previous, picker, following = st.columns([1, 2.6, 1], vertical_alignment="center")
    if previous.button("Sebelumnya", disabled=position == 0, use_container_width=True):
        st.session_state["laporan-slide-name"] = titles[position - 1]
        st.rerun()
    if following.button("Berikutnya", disabled=position >= len(titles) - 1, use_container_width=True):
        st.session_state["laporan-slide-name"] = titles[position + 1]
        st.rerun()
    picker.selectbox(
        "Slide presentasi",
        titles,
        key="laporan-slide-name",
        label_visibility="collapsed",
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
            "Laporan kerja e-commerce dan digital marketing Mitra10, supermarket bahan bangunan. "
            "Angka yang sama dipakai untuk rapat toko dan untuk bab hasil tesis Magister Teknik Informatika. "
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
            st.caption("Batang adalah sales bersih per tanggal. Angka mengikuti Total Pembayaran sekali tiap No. Pesanan.")
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
            st.caption(
                "Biru dan oranye adalah sales. Hijau adalah stok prediksi dalam unit. "
                "Tiap produk punya skala sendiri."
            )
            st.plotly_chart(item_sales_chart(view, "laporan"), use_container_width=True)
        else:
            st.caption("Biru adalah QTY pada periode laporan. Oranye adalah prediksi.")
            st.plotly_chart(item_qty_chart(view, "laporan"), use_container_width=True)
        if not view.empty:
            st.caption(
                f"Sales Top 50 pada periode ini {format_idr(top_sales)}, "
                f"{format_number(top_share, 1)}% dari sales bersih."
            )
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
            show_metric(cards[2], "Safety stock", format_qty(safety_units), hint="Cadangan, dalam unit")
            show_metric(cards[3], "Stok disarankan periode", format_qty(stock_units), hint="Prediksi QTY periode ditambah safety stock periode. Bukan angka hari ini.")
            display = leaderboard_frame(view.head(10), period)
            st.caption("Sepuluh peringkat teratas. Daftar lengkap ada di menu Prediksi & stok.")
            scroll_table(display, max_height=520)
            offer_excel(display, "laporan_prediksi_stok.xlsx")
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
        st.caption("Seluruh status pada tanggal yang dipilih, termasuk batal dan retur.")
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
            offer_excel(status_view, "laporan_status_pesanan.xlsx")
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
            offer_excel(contribution_table, "laporan_kontribusi_batal.xlsx")
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
            offer_excel(sku_sheet, "laporan_sku_retur_batal.xlsx")
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
            offer_excel(month_table, "laporan_data_tersimpan.xlsx")
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
        offer_excel(folder, "folder_data.xlsx")
    st.subheader("Riwayat perubahan data")
    changes = history_frame()
    if changes.empty:
        st.write("Belum ada perubahan impor.")
    else:
        st.dataframe(changes, height=min(44 * (len(changes) + 1) + 36, 480), hide_index=True)
        offer_excel(changes, "riwayat_perubahan_data.xlsx")


def show_metric(column, label: str, value: str, *, compact: bool = False, hint: str | None = None) -> None:
    value_class = "readable-metric-value compact" if compact else "readable-metric-value"
    hint_html = f"<div class='metric-hint'>{hint}</div>" if hint else ""
    column.markdown(
        "<div class='stat-card'>"
        f"<div class='readable-metric-label'>{label}</div>"
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


def apply_horizon_slices(
    view: pd.DataFrame,
    period: str,
    day: date,
    horizon_days: int | None = None,
) -> pd.DataFrame:
    """Pecah prediksi periode menjadi 1 hari dan satu bulan kalender dari tanggal 1."""
    if view is None or view.empty:
        return view
    if not {"pred_qty", "pred_sales", "safety_stock"} <= set(view.columns):
        return view
    horizon = max(int(horizon_days) if horizon_days else horizon_day_count(period, day), 1)
    month_days = days_in_calendar_month(day)
    out = view.copy()
    sales_day: list[int] = []
    sales_month: list[int] = []
    qty_day: list[int] = []
    qty_month: list[int] = []
    stock_day: list[int] = []
    stock_month: list[int] = []
    safety_day: list[int] = []
    safety_month: list[int] = []
    for qty, sales, safety in zip(out["pred_qty"], out["pred_sales"], out["safety_stock"]):
        qty_one, sales_one, stock_one = slice_forecast(qty, sales, safety, horizon, 1)
        qty_rest, sales_rest, stock_rest = slice_forecast(qty, sales, safety, horizon, month_days)
        sales_day.append(sales_one)
        sales_month.append(sales_rest)
        qty_day.append(qty_one)
        qty_month.append(qty_rest)
        stock_day.append(stock_one)
        stock_month.append(stock_rest)
        safety_day.append(max(stock_one - qty_one, 0))
        safety_month.append(max(stock_rest - qty_rest, 0))
    out["pred_sales_hari"] = sales_day
    out["pred_sales_bulan"] = sales_month
    out["pred_qty_hari"] = qty_day
    out["pred_qty_bulan"] = qty_month
    out["stok_hari"] = stock_day
    out["stok_bulan"] = stock_month
    out["safety_hari"] = safety_day
    out["safety_bulan"] = safety_month
    out["slice_horizon_days"] = horizon
    out["slice_month_days"] = month_days
    return out


def leaderboard_frame(view: pd.DataFrame, period: str) -> pd.DataFrame:
    if view is not None and not view.empty and "stok_hari" not in view.columns:
        view = apply_horizon_slices(view, period, date.today())
    period_name = PERIOD_SPECS[period].label.lower()
    month_days = int(view["slice_month_days"].iloc[0]) if "slice_month_days" in view.columns and not view.empty else 1
    frame = pd.DataFrame(
        {
            "Stok disarankan hari ini": view["stok_hari"].astype(int) if "stok_hari" in view.columns else view["stok_disarankan"].astype(int),
            "SKU": view["sku"].map(lambda value: _clean_product_piece(value, "Tanpa SKU")),
            "Product Name": view["product_name"].map(lambda value: _clean_product_piece(value, "Tanpa nama")),
            "Product variance": view["variasi_tampil"].map(lambda value: _clean_product_piece(value, "Tanpa variasi")),
            "Peringkat": view["peringkat"].astype(int),
            "QTY terjual": view["qty_total"].astype(int),
            "Sales volume": view["sales_total"].round().astype(int),
            "Prediksi sales hari ini": view["pred_sales_hari"].astype(int) if "pred_sales_hari" in view.columns else 0,
            f"Prediksi sales bulan ini ({month_days} hari)": view["pred_sales_bulan"].astype(int) if "pred_sales_bulan" in view.columns else 0,
            "Stok disarankan bulan ini": view["stok_bulan"].astype(int) if "stok_bulan" in view.columns else view["stok_disarankan"].astype(int),
            f"Prediksi QTY ({period_name})": view["pred_qty"].astype(int),
            f"Prediksi sales volume ({period_name})": view["pred_sales"].round().astype(int),
            f"Safety stock ({period_name})": view["safety_stock"].astype(int),
            f"Stok disarankan ({period_name})": view["stok_disarankan"].astype(int),
        }
    )
    if "delta_stok_hari" in view.columns:
        frame["Perubahan stok"] = pd.to_numeric(view["delta_stok_hari"], errors="coerce")
    return frame


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
    full_labels, labels = _product_axis(plot, width=52, max_lines=6)
    actual = plot["qty_total"].astype(float)
    predicted = plot["pred_qty"].astype(float)
    placement = _label_placement(len(plot), money=False, orientation="h")
    actual_text, _actual_hover = _bar_texts(actual, money=False)
    pred_text, _pred_hover = _bar_texts(predicted, money=False)
    pred_text, pred_colors = _prediction_marks(pred_text, plot)
    pred_placement = dict(placement)
    pred_placement["textfont"] = dict(size=placement["textfont"]["size"], color=pred_colors)
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
            **pred_placement,
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
    full_labels, labels = _product_axis(plot, width=52, max_lines=6)
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
    pred_text, pred_colors = _prediction_marks(pred_text, plot)
    stock_text = [f"{format_number(value, 0)} unit" for value in stock_qty]
    size = _bar_text_size(len(plot))
    placement = dict(
        textposition="outside",
        textfont=dict(size=size, color="#1f2937"),
        textangle=0,
        cliponaxis=False,
        constraintext="none",
    )
    pred_placement = dict(placement)
    pred_placement["textfont"] = dict(size=size, color=pred_colors)
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
            **pred_placement,
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
    many = len(plot) > 40
    full_labels, labels = _product_axis(plot, width=40 if many else 52, max_lines=2 if many else 6)
    values = plot[value_col].astype(float)
    peak = float(values.max() or 1)
    money = value_col == "pred_sales"
    display, hover = _bar_texts(values, money=money)
    placement = _label_placement(len(plot), money=money, orientation="h")
    if str(value_col).startswith("pred"):
        display, pred_colors = _prediction_marks(display, plot)
        placement = dict(placement)
        placement["textfont"] = dict(size=placement["textfont"]["size"], color=pred_colors)
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            text=display,
            marker_color="#F58518",
            customdata=list(zip(full_labels, hover)),
            hovertemplate="%{customdata[0]}<br>%{customdata[1]}<extra></extra>",
            **placement,
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
        if column in {"Produk", "Variasi", "Referensi SKU", "Item", "SKU", "Product Name", "Product variance"}:
            continue
        if not pd.api.types.is_numeric_dtype(frame[column]):
            continue
        config[column] = st.column_config.NumberColumn(column, format="localized", step=1)
    return config


def _stock_cell(amount: object, delta: object) -> str:
    """Angka stok final, panah di kirinya, dan selisih lebih kecil di bawahnya."""
    try:
        number = int(round(float(amount)))
        amount_text = format_number(number, 0)
    except (TypeError, ValueError):
        amount_text = "-"
    arrow = ""
    delta_html = ""
    if delta is not None and not (isinstance(delta, float) and pd.isna(delta)) and not pd.isna(delta):
        try:
            change = int(delta)
        except (TypeError, ValueError):
            change = None
        if change is None:
            delta_html = ""
        elif change > 0:
            arrow = "<span class='stock-arrow up'>▲</span>"
            delta_html = f"<div class='stock-delta up'>+{format_number(change)}</div>"
        elif change < 0:
            arrow = "<span class='stock-arrow down'>▼</span>"
            delta_html = f"<div class='stock-delta down'>−{format_number(abs(change))}</div>"
        else:
            delta_html = "<div class='stock-delta flat'>-</div>"
    return (
        "<td class='stock-final'>"
        f"<div class='stock-main'>{arrow}<span>{amount_text}</span></div>"
        f"{delta_html}</td>"
    )


def scroll_table(frame: pd.DataFrame, *, max_height: int | None = 680, format_numbers: bool = True) -> None:
    """Tabel dengan batang geser yang tetap terlihat, ke kanan, kiri, atas, dan bawah."""
    if frame.empty:
        st.write("Tidak ada data.")
        return
    stock_column = "Stok disarankan hari ini"
    hidden = {"Perubahan stok"}
    columns = [column for column in frame.columns if column not in hidden]
    numeric = {
        column
        for column in columns
        if column != stock_column and format_numbers and pd.api.types.is_numeric_dtype(frame[column])
    }
    header = "".join(
        f"<th class='{'stock-final' if column == stock_column else 'num' if column in numeric else ''}'>"
        f"{html.escape(str(column))}</th>"
        for column in columns
    )
    body: list[str] = []
    for _, row in frame.iterrows():
        cells: list[str] = []
        for column in columns:
            value = row[column]
            if column == stock_column:
                delta = row["Perubahan stok"] if "Perubahan stok" in frame.columns else None
                cells.append(_stock_cell(value, delta))
                continue
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


_TOP50_TABLE = components.declare_component("top50_table", path=str(ROOT / "components" / "top50_table"))


def _move_cell(now: float | None, then: float | None, *, money: bool) -> tuple[str, str]:
    """Selisih kecil di bawah angka prediksi. Biru naik, merah turun."""
    if now is None or then is None or pd.isna(now) or pd.isna(then):
        return "", "flat"
    delta = int(round(float(now))) - int(round(float(then)))
    if delta == 0:
        return "– tetap", "flat"
    amount = format_idr(abs(delta)) if money else format_qty(abs(delta))
    if delta > 0:
        return f"▲ +{amount}", "up"
    return f"▼ −{amount}", "down"


def top50_table_parts(
    view: pd.DataFrame,
    *,
    period: str,
    today: date,
    then_day: date | None,
    resume_label: str,
) -> tuple[list[dict], list[dict], dict, pd.DataFrame]:
    """Kolom, baris, baris Total, dan salinan Excel untuk tabel Top 50 berkelompok."""
    horizon = max(horizon_day_count(period, today), 1)
    month_days = days_in_calendar_month(today)
    then_horizon = max(horizon_day_count(period, then_day), 1) if then_day else horizon
    then_month = days_in_calendar_month(then_day) if then_day else month_days
    _start, _end, period_window = forecast_window(period, today)
    month_name = f"{ID_MONTHS[today.month - 1]} {today.year}"
    pred_groups = (
        ("d", f"Prediksi hari ini · {_short_id_date(today)}"),
        ("m", f"Prediksi bulan ini · {month_name} ({month_days} hari)"),
        ("p", f"Prediksi {period_window}"),
    )
    columns: list[dict] = [
        {"id": "pick", "label": "Grafik", "pin": True, "width": 64},
        {"id": "rank", "label": "Peringkat", "pin": True, "width": 92, "kind": "num", "sort": True},
        {"id": "sku", "label": "SKU", "kicker": "Produk", "pin": True, "width": 116, "sort": True},
        {"id": "name", "label": "Product Name", "kicker": "Produk", "pin": True, "width": 280, "kind": "name", "sort": True},
        {"id": "variance", "label": "Product variance", "width": 170, "kind": "name", "sort": True},
        {"id": "sold_qty", "label": "QTY", "group": f"Penjualan · {resume_label}", "kind": "num", "sort": True},
        {"id": "sold_sales", "label": "Sales", "group": f"Penjualan · {resume_label}", "kind": "num", "sort": True},
    ]
    for prefix, group in pred_groups:
        columns += [
            {"id": f"{prefix}_qty", "label": "QTY prediksi", "group": group, "kind": "num", "sort": True},
            {"id": f"{prefix}_sales", "label": "Sales prediksi", "group": group, "kind": "num", "sort": True},
            {"id": f"{prefix}_safety", "label": "Safety stock", "group": group, "kind": "num", "sort": True},
            {"id": f"{prefix}_stock", "label": "Stok disarankan", "group": group, "kind": "num", "sort": True},
        ]

    def _number(row: pd.Series, name: str) -> float | None:
        if name not in row.index or pd.isna(row[name]):
            return None
        return float(row[name])

    rows: list[dict] = []
    totals: dict[str, float] = {}
    then_totals: dict[str, float] = {}
    has_then = False
    export_rows: list[dict] = []
    for _, row in view.iterrows():
        qty_now = float(row["pred_qty"])
        sales_now = float(row["pred_sales"])
        safety_now = max(float(row["safety_stock"]), 0.0)
        values = {
            "sold_qty": float(row["qty_total"]),
            "sold_sales": float(row["sales_total"]),
            "p_qty": qty_now,
            "p_sales": sales_now,
            "p_safety": safety_now,
            "p_stock": float(row["stok_disarankan"]),
        }
        for prefix, days in (("d", 1), ("m", month_days)):
            qty, sales, stock = slice_forecast(qty_now, sales_now, safety_now, horizon, days)
            values[f"{prefix}_qty"] = qty
            values[f"{prefix}_sales"] = sales
            values[f"{prefix}_safety"] = max(stock - qty, 0)
            values[f"{prefix}_stock"] = stock
        then_values: dict[str, float] = {}
        mv_qty_then = _number(row, "mv_pred_qty_then")
        mv_qty_now = _number(row, "mv_pred_qty_now")
        if mv_qty_then is not None and mv_qty_now is not None:
            has_then = True
            sales_then = _number(row, "mv_pred_sales_then") or 0.0
            stok_then = _number(row, "mv_stok_then") or 0.0
            safety_then = max(stok_then - mv_qty_then, 0.0)
            sales_mv_now = _number(row, "mv_pred_sales_now") or 0.0
            stok_mv_now = _number(row, "mv_stok_now") or 0.0
            safety_mv_now = max(stok_mv_now - mv_qty_now, 0.0)
            now_pairs = {"p_qty": mv_qty_now, "p_sales": sales_mv_now, "p_safety": safety_mv_now, "p_stock": stok_mv_now}
            then_values = {"p_qty": mv_qty_then, "p_sales": sales_then, "p_safety": safety_then, "p_stock": stok_then}
            for prefix, days, then_days in (("d", 1, 1), ("m", month_days, then_month)):
                qty, sales, stock = slice_forecast(mv_qty_now, sales_mv_now, safety_mv_now, horizon, days)
                now_pairs.update({f"{prefix}_qty": qty, f"{prefix}_sales": sales, f"{prefix}_safety": max(stock - qty, 0), f"{prefix}_stock": stock})
                qty, sales, stock = slice_forecast(mv_qty_then, sales_then, safety_then, then_horizon, then_days)
                then_values.update({f"{prefix}_qty": qty, f"{prefix}_sales": sales, f"{prefix}_safety": max(stock - qty, 0), f"{prefix}_stock": stock})
            # Selisih dihitung pada rentang tanggal pergerakan, lalu ditempel ke angka yang sedang dikunci.
            then_values = {name: values[name] - (now_pairs[name] - then_values[name]) for name in then_values}
        cells: dict[str, dict] = {
            "rank": {"v": int(row["peringkat"]), "t": format_number(int(row["peringkat"]))},
            "sku": {"v": _clean_product_piece(row["sku"], "Tanpa SKU"), "t": _clean_product_piece(row["sku"], "Tanpa SKU")},
            "name": {"v": _clean_product_piece(row["product_name"], "Tanpa nama"), "t": _clean_product_piece(row["product_name"], "Tanpa nama")},
            "variance": {
                "v": _clean_product_piece(row["variasi_tampil"], "Tanpa variasi"),
                "t": _clean_product_piece(row["variasi_tampil"], "Tanpa variasi"),
            },
        }
        export = {
            "Peringkat": int(row["peringkat"]),
            "SKU": cells["sku"]["t"],
            "Product Name": cells["name"]["t"],
            "Product variance": cells["variance"]["t"],
        }
        for column in columns[5:]:
            name = column["id"]
            value = float(values[name])
            money = name.endswith("sales")
            cell = {"v": value, "t": format_idr(value) if money else format_qty(value)}
            if name in then_values:
                cell["d"], cell["dc"] = _move_cell(value, then_values[name], money=money)
                then_totals[name] = then_totals.get(name, 0.0) + float(then_values[name])
            cells[name] = cell
            totals[name] = totals.get(name, 0.0) + value
            label = f"{column['group']} - {column['label']}"
            export[label] = int(round(value))
            if name in then_values:
                export[f"{label} (perubahan)"] = int(round(value - then_values[name]))
        rows.append({"key": str(row["item_key"]), "cells": cells})
        export_rows.append(export)

    total: dict[str, dict] = {
        "name": {"t": "Total", "s": f"{len(rows)} item"},
    }
    total_export = {"Peringkat": "", "SKU": "", "Product Name": "Total", "Product variance": ""}
    for column in columns[5:]:
        name = column["id"]
        money = name.endswith("sales")
        value = totals.get(name, 0.0)
        cell = {"t": format_idr(value) if money else format_qty(value)}
        if has_then and name in then_totals:
            cell["d"], cell["dc"] = _move_cell(value, then_totals[name], money=money)
        total[name] = cell
        label = f"{column['group']} - {column['label']}"
        total_export[label] = int(round(value))
        if has_then and name in then_totals:
            total_export[f"{label} (perubahan)"] = int(round(value - then_totals[name]))
    export_frame = pd.DataFrame([total_export, *export_rows])
    return columns, rows, total, export_frame


def show_top50_table(
    view: pd.DataFrame,
    *,
    period: str,
    today: date,
    then_day: date | None,
    resume_label: str,
    key: str,
) -> str:
    """Tabel Top 50 berkelompok. Centang satu baris mengembalikan item_key untuk grafik."""
    columns, rows, total, export_frame = top50_table_parts(
        view, period=period, today=today, then_day=then_day, resume_label=resume_label
    )
    keys = {row["key"] for row in rows}
    previous = str(st.session_state.get(f"{key}-value") or "")
    picked = _TOP50_TABLE(
        columns=columns,
        rows=rows,
        total=total,
        selected=previous if previous in keys else "",
        height=680,
        sort="rank",
        key=key,
        default=previous if previous in keys else "",
    )
    picked = str(picked or "")
    st.session_state[f"{key}-value"] = picked
    offer_excel(export_frame, "top50_item_terlaris.xlsx")
    return picked if picked in keys else ""


def excel_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


def offer_excel(frame: pd.DataFrame, filename: str) -> None:
    """Unduh tabel yang sedang ditampilkan sebagai file Excel."""
    if not isinstance(frame, pd.DataFrame):
        return
    safe = filename if str(filename).endswith(".xlsx") else f"{filename}.xlsx"
    st.download_button(
        "Unduh Excel",
        data=excel_bytes(frame),
        file_name=safe,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"excel-{safe}",
    )


def table_column_config(frame: pd.DataFrame, *, roomy: bool = False) -> dict:
    """Kolom nama cukup lebar supaya nama produk dan SKU tidak terpotong."""
    config = {}
    for column in frame.columns:
        if column in {"Produk", "Variasi", "Referensi SKU", "Item", "SKU", "Product Name", "Product variance"}:
            continue
        if not pd.api.types.is_numeric_dtype(frame[column]):
            continue
        if roomy:
            width = 120 if column == "Peringkat" else 200
            config[column] = st.column_config.NumberColumn(column, format="localized", step=1, width=width)
        else:
            config[column] = st.column_config.NumberColumn(column, format="localized", step=1)
    widths = {
        "SKU": 220,
        "Product Name": 780 if roomy else 640,
        "Product variance": 280,
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


def _select_years(years: list[str], *, pick_key: str, applied_key: str, box_prefix: str) -> list[str]:
    """Daftar tahun plus centang. Centang boleh lebih dari satu tahun."""
    options = ["Semua tahun", *years]
    if st.session_state.get(pick_key) not in options:
        st.session_state[pick_key] = years[-1] if years else "Semua tahun"
    picked = st.selectbox("Tahun", options, key=pick_key)
    if st.session_state.get(applied_key) != picked:
        for year in years:
            st.session_state[f"{box_prefix}{year}"] = picked in {"Semua tahun", year}
        st.session_state[applied_key] = picked
    checked: list[str] = []
    columns = st.columns(max(len(years), 1))
    for index, year in enumerate(years):
        widget = f"{box_prefix}{year}"
        if widget not in st.session_state:
            st.session_state[widget] = year == (years[-1] if years else year)
        with columns[index]:
            if st.checkbox(str(year), key=widget):
                checked.append(year)
    st.markdown(
        "<div class='field-hint'>Daftar memilih satu tahun atau semua. Centang untuk memilih lebih dari satu tahun.</div>",
        unsafe_allow_html=True,
    )
    return checked


def filter_resume_orders(
    orders: pd.DataFrame,
    *,
    show_controls: bool,
    prefix: str = "resume",
    caption: str | None = None,
    show_exclude: bool = False,
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
    years_state = f"{prefix}_years"
    months_state = f"{prefix}_months"
    start_state = f"{prefix}_start"
    end_state = f"{prefix}_end"
    start_widget = f"{prefix}-start"
    end_widget = f"{prefix}-end"
    previous_years = [year for year in (st.session_state.get(years_state) or []) if year in years]
    if not previous_years and years:
        previous_years = [years[-1]]

    if show_controls:
        period_copy = caption or (
            "Tahun, bulan, dan tanggal ini hanya memotong angka yang ditampilkan. "
            "Prediksi tetap dari data latih dan periode prediksi."
        )
        st.markdown(
            "<div class='section-title'>Periode penjualan</div>"
            f"<div class='field-hint'>{html.escape(period_copy)}</div>",
            unsafe_allow_html=True,
        )
        checked_years = _select_years(
            years,
            pick_key=f"{prefix}-year-pick",
            applied_key=f"{prefix}-year-applied",
            box_prefix=f"{prefix}-year-on-",
        )
        year_months = [key for key in months if key[:4] in set(checked_years)]
        known_months = st.session_state.get(months_state)
        saved_months = [key for key in known_months if key in year_months] if isinstance(known_months, list) else []
        if not saved_months and not isinstance(known_months, list) and year_months:
            saved_months = [year_months[-1]]
        newly = {year for year in checked_years if year not in previous_years}
        st.markdown("<div class='section-title tight'>Bulan penjualan</div>", unsafe_allow_html=True)
        selected: list[str] = []
        for start in range(0, len(year_months), 4):
            box_columns = st.columns(4)
            for offset, key in enumerate(year_months[start : start + 4]):
                widget = f"{prefix}-month-{key}"
                if widget not in st.session_state:
                    st.session_state[widget] = True if key[:4] in newly else key in saved_months
                with box_columns[offset]:
                    if st.checkbox(month_label(key), key=widget):
                        selected.append(key)
        if not checked_years or not selected:
            st.warning("Centang minimal satu tahun dan satu bulan penjualan.")
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
        if show_exclude:
            if "exclude-return-batal" not in st.session_state:
                st.session_state["exclude-return-batal"] = bool(st.session_state.get("exclude_applied", False))
            st.checkbox("Exclude return dan batal", key="exclude-return-batal")
            st.markdown(
                "<div class='field-hint'>Mengurangi pesanan batal dan unit retur pada angka penjualan, Top 50, dan Prediksi & stok.</div>",
                unsafe_allow_html=True,
            )
        st.session_state[years_state] = checked_years
        st.session_state[months_state] = selected
        st.session_state[start_state] = start
        st.session_state[end_state] = end
    else:
        selected = [key for key in (st.session_state.get(months_state) or []) if key[:4] in set(previous_years)]
        if not selected:
            fallback_months = [key for key in months if key[:4] in set(previous_years)]
            selected = [fallback_months[-1]] if fallback_months else []
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


def _analysis_meta(
    *,
    period: str,
    period_text: str,
    metric: str,
    service: int,
    exclude: bool,
    window_start: date,
    window_end: date,
) -> dict:
    months = [str(key) for key in st.session_state.get("active-library-keys", tuple())]
    return {
        "period": period,
        "period_text": period_text,
        "metric": metric,
        "service": int(service),
        "exclude_return_cancel": bool(exclude),
        "months": months,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
    }


def _remember_run(stock: pd.DataFrame, meta: dict) -> tuple[str, str]:
    try:
        run_id, previous_id = record_run(stock, meta)
    except OSError:
        return "", ""
    return run_id, previous_id or ""


def _signed_piece(value: int) -> str:
    number = int(value)
    if number > 0:
        return f"+{format_number(number)}"
    if number < 0:
        return f"−{format_number(abs(number))}"
    return "tetap"


def _stock_on_span(pred_qty: float, stok: float, horizon_days: int, days: int) -> int:
    safety = max(float(stok) - float(pred_qty), 0.0)
    _qty, _sales, stock = slice_forecast(pred_qty, 0.0, safety, horizon_days, days)
    return stock


def _attach_movement(view: pd.DataFrame, detail: pd.DataFrame, horizon_days: int) -> pd.DataFrame:
    if view is None or view.empty or detail is None or detail.empty or "item_key" not in view.columns:
        return view
    lookup = detail.drop_duplicates("item_key").set_index("item_key")
    qty_delta: list[int | None] = []
    stock_delta: list[int | None] = []
    for key in view["item_key"].astype(str):
        if key not in lookup.index:
            qty_delta.append(None)
            stock_delta.append(None)
            continue
        row = lookup.loc[key]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        qty_delta.append(int(row["delta_qty"]))
        now = _stock_on_span(row["pred_qty_now"], row["stok_now"], horizon_days, 1)
        then = _stock_on_span(row["pred_qty_then"], row["stok_then"], horizon_days, 1)
        stock_delta.append(now - then)
    out = view.copy()
    out["delta_qty_nilai"] = qty_delta
    out["delta_stok_hari"] = stock_delta
    keys = view["item_key"].astype(str)
    for name in ("pred_qty_now", "pred_qty_then", "pred_sales_now", "pred_sales_then", "stok_now", "stok_then"):
        out[f"mv_{name}"] = keys.map(lookup[name]) if name in lookup.columns else np.nan
    return out


def _saved_day(meta: dict | None) -> date | None:
    if not meta:
        return None
    try:
        return datetime.fromisoformat(str(meta.get("saved_at", ""))).date()
    except ValueError:
        return None


def _run_clock(meta: dict | None) -> str:
    if not meta:
        return "waktu belum tercatat"
    saved = str(meta.get("saved_at", ""))
    try:
        stamp = datetime.fromisoformat(saved)
    except ValueError:
        return saved or "waktu belum tercatat"
    return f"{format_id_date(stamp.date())}, {stamp.strftime('%H.%M')}"


def _movement_identity(key: str, label: str, catalog_names: dict[str, tuple[str, str, str]]) -> tuple[str, str, str]:
    if key in catalog_names:
        return catalog_names[key]
    sku = key.split("||", 1)[0] if key else "Tanpa SKU"
    if " — " in label:
        name, variance = label.split(" — ", 1)
    else:
        name, variance = label or "Tanpa nama", "Tanpa variasi"
    return (
        _clean_product_piece(sku, "Tanpa SKU"),
        _clean_product_piece(name, "Tanpa nama"),
        _clean_product_piece(variance, "Tanpa variasi"),
    )


def _window_days(meta: dict | None) -> int:
    if not meta:
        return 1
    try:
        start = date.fromisoformat(str(meta.get("window_start")))
        end = date.fromisoformat(str(meta.get("window_end")))
    except ValueError:
        return 1
    return max((end - start).days + 1, 1)


def _focus_slice(detail: pd.DataFrame, side: str, horizon_days: int, span_days: int) -> tuple[int, int]:
    if detail is None or detail.empty:
        return 0, 0
    sales_total = 0
    stock_total = 0
    qty_column = f"pred_qty_{side}"
    sales_column = f"pred_sales_{side}"
    stock_column = f"stok_{side}"
    for qty, sales, stock in zip(detail[qty_column], detail[sales_column], detail[stock_column]):
        safety = max(float(stock) - float(qty), 0.0)
        _piece_qty, sales_part, stock_part = slice_forecast(qty, sales, safety, horizon_days, span_days)
        sales_total += sales_part
        stock_total += stock_part
    return sales_total, stock_total


def _prediction_totals(frame: pd.DataFrame | None) -> tuple[int, int, int, int]:
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return 0, 0, 0, 0
    needed = {"pred_sales_hari", "stok_hari", "pred_sales_bulan", "stok_bulan"}
    if not needed <= set(frame.columns):
        return 0, 0, 0, 0
    return (
        int(frame["pred_sales_hari"].sum()),
        int(frame["stok_hari"].sum()),
        int(frame["pred_sales_bulan"].sum()),
        int(frame["stok_bulan"].sum()),
    )


def _history_before(history: pd.DataFrame | None, as_of: date) -> pd.DataFrame:
    """Data latih yang sudah terjadi sebelum tanggal ramalan."""
    if history is None or not isinstance(history, pd.DataFrame) or history.empty or "period_start" not in history.columns:
        return pd.DataFrame()
    stamps = pd.to_datetime(history["period_start"], errors="coerce")
    if getattr(stamps.dt, "tz", None) is not None:
        stamps = stamps.dt.tz_localize(None)
    last_train = pd.Timestamp(as_of) - pd.Timedelta(days=1)
    return history.loc[stamps.dt.normalize() <= last_train].copy()


def _forecast_stock_as_of(history: pd.DataFrame | None, as_of: date, period: str, service: int) -> pd.DataFrame:
    """Prediksi Level terkini pada satu tanggal, dari data latih sebelum tanggal itu. Rumus tidak diubah."""
    trimmed = _history_before(history, as_of)
    if trimmed.empty:
        return frame_from_stock(None)
    horizon = horizon_day_count(period, as_of)
    _start, _end, text = forecast_window(period, as_of)
    qty_fc = forecast_items(
        trimmed,
        "hari",
        "qty",
        steps=horizon,
        next_label=text,
        forecast_start=pd.Timestamp(as_of),
    )
    if qty_fc is None or qty_fc.empty:
        return frame_from_stock(None)
    sales_fc = forecast_revenue(trimmed, qty_fc, "hari", steps=horizon, next_label=text)
    combined = combine_forecasts(qty_fc, sales_fc)
    priced = recommend_stock(
        trimmed,
        combined,
        "hari",
        service_level_z=service_z(service),
        horizon_steps=horizon,
    )
    return frame_from_stock(priced)


def _movement_frame(
    as_of: date,
    *,
    live_stock: pd.DataFrame | None,
    live_day: date,
    history: pd.DataFrame | None,
    period: str,
    service: int,
    source_key: str,
) -> pd.DataFrame:
    """Hasil Jalankan analisis untuk hari ini. Tanggal lain dihitung ulang dari data latih."""
    if as_of == live_day and isinstance(live_stock, pd.DataFrame) and not live_stock.empty:
        return frame_from_stock(live_stock)
    stamp = ""
    rows = 0
    if isinstance(history, pd.DataFrame) and not history.empty and "period_start" in history.columns:
        stamp = str(pd.to_datetime(history["period_start"], errors="coerce").max())
        rows = len(history)
    key = f"{source_key}|{period}|{int(service)}|{as_of.isoformat()}|{stamp}|{rows}"
    cache = st.session_state.setdefault("movement-asof", {})
    cached = cache.get(key)
    if isinstance(cached, pd.DataFrame):
        return cached.copy()
    with st.spinner(f"Menghitung prediksi {format_id_date(as_of)} dari data latih. Rumus Level terkini tidak diubah."):
        frame = _forecast_stock_as_of(history, as_of, period, service)
    cache[key] = frame.copy()
    while len(cache) > 8:
        cache.pop(next(iter(cache)))
    return frame.copy()


def _aligned_totals(
    frame: pd.DataFrame | None,
    catalog: pd.DataFrame | None,
    period: str,
    day: date,
) -> tuple[int, int, int, int] | None:
    if frame is None or frame.empty or "item_key" not in frame.columns:
        return None
    work = frame
    if isinstance(catalog, pd.DataFrame) and "item_key" in catalog.columns and not catalog.empty:
        keys = set(catalog["item_key"].astype(str))
        work = frame.loc[frame["item_key"].astype(str).isin(keys)]
    if work.empty:
        return None
    return _prediction_totals(
        apply_horizon_slices(work, period, day, horizon_days=horizon_day_count(period, day))
    )


def _delta_text(now: int, then: int, *, money: bool) -> str:
    delta = int(now) - int(then)
    amount = format_idr(abs(delta)) if money else format_qty(abs(delta))
    if delta == 0:
        return "0 (0%)"
    sign = "+" if delta > 0 else "−"
    if then == 0:
        return f"{sign}{amount}"
    percent = delta / then * 100
    percent_sign = "+" if percent > 0 else "−"
    return f"{sign}{amount} ({percent_sign}{format_number(abs(percent), 1)}%)"


def _move_line(now: int, then: int | None, *, money: bool) -> str:
    if then is None:
        return "<div class='metric-move flat'>Data latih sebelum hari ini belum cukup untuk dihitung.</div>"
    tone = "up" if int(now) > int(then) else "down" if int(now) < int(then) else "flat"
    return f"<div class='metric-move {tone}'>{html.escape(_delta_text(now, then, money=money))} dibanding prediksi kemarin</div>"


def _prediction_card(column, label: str, value: str, move_html: str) -> None:
    column.markdown(
        "<div class='stat-card'>"
        f"<div class='readable-metric-label'>{html.escape(label)}</div>"
        f"<div class='readable-metric-value'>{html.escape(value)}</div>"
        "<div class='metric-hint'>Hasil prediksi</div>"
        f"{move_html}"
        "</div>",
        unsafe_allow_html=True,
    )


def _move_html(now: int, then: int, *, money: bool) -> str:
    delta = int(now) - int(then)
    if delta > 0:
        tone = "up"
    elif delta < 0:
        tone = "down"
    else:
        tone = "flat"
    return f"<div class='cell-move {tone}'>{html.escape(_delta_text(now, then, money=money))}</div>"


def _qty_cell(
    amount: int,
    safety: int | None,
    move_now: int | None = None,
    move_then: int | None = None,
    *,
    tag: str = "td",
) -> str:
    safety_html = ""
    if safety is not None:
        safety_html = f"<div class='qty-safety'>Safety stock {html.escape(format_qty(safety))}</div>"
    move_html = ""
    if move_now is not None and move_then is not None:
        move_html = _move_html(move_now, move_then, money=False)
    return f"<{tag} class='num'><div>{html.escape(format_qty(amount))}</div>{safety_html}{move_html}</{tag}>"


def _sales_cell(
    amount: int,
    move_now: int | None = None,
    move_then: int | None = None,
    *,
    tag: str = "td",
) -> str:
    move_html = ""
    if move_now is not None and move_then is not None:
        move_html = _move_html(move_now, move_then, money=True)
    return f"<{tag} class='num'><div>{html.escape(format_idr(amount))}</div>{move_html}</{tag}>"


def _prediction_moved(item: dict) -> bool:
    """Selisih prediksi pada rentang tanggal. Nol di hari ini dan bulan ini berarti tidak bergerak."""
    pairs = (
        ("qty_day_now", "qty_day_then"),
        ("sales_day_now", "sales_day_then"),
        ("qty_month_now", "qty_month_then"),
        ("sales_month_now", "sales_month_then"),
    )
    return any(int(item[now]) != int(item[then]) for now, then in pairs)


def _indexed_stock(frame: pd.DataFrame | None) -> pd.DataFrame:
    stock_frame = frame_from_stock(frame if isinstance(frame, pd.DataFrame) else None)
    if stock_frame.empty:
        return stock_frame
    return stock_frame.drop_duplicates("item_key").set_index("item_key")


def _row_slices(row: pd.Series | None, horizon_days: int, month_days: int) -> tuple[int, int, int, int, int, int]:
    if row is None:
        return 0, 0, 0, 0, 0, 0
    safety = max(float(row["safety_stock"]), 0.0)
    qty_day, sales_day, stock_day = slice_forecast(row["pred_qty"], row["pred_sales"], safety, horizon_days, 1)
    qty_month, sales_month, stock_month = slice_forecast(
        row["pred_qty"], row["pred_sales"], safety, horizon_days, month_days
    )
    return qty_day, sales_day, max(stock_day - qty_day, 0), qty_month, sales_month, max(stock_month - qty_month, 0)


def _render_movement_board(
    catalog: pd.DataFrame,
    focus_keys: list[str],
    locked: pd.DataFrame | None,
    start_frame: pd.DataFrame | None,
    end_frame: pd.DataFrame | None,
    *,
    period: str,
    start_day: date,
    end_day: date,
    today: date,
) -> pd.DataFrame:
    names: dict[str, tuple] = {}
    if isinstance(catalog, pd.DataFrame) and {
        "item_key",
        "sku",
        "product_name",
        "variasi_tampil",
        "peringkat",
        "qty_total",
        "sales_total",
    } <= set(catalog.columns):
        for record in catalog.itertuples(index=False):
            names[str(record.item_key)] = record
    locked_map = _indexed_stock(locked)
    start_map = _indexed_stock(start_frame)
    end_map = _indexed_stock(end_frame)
    locked_horizon = horizon_day_count(period, today)
    locked_month = days_in_calendar_month(today)
    start_horizon = horizon_day_count(period, start_day)
    end_horizon = horizon_day_count(period, end_day)
    start_month = days_in_calendar_month(start_day)
    end_month = days_in_calendar_month(end_day)
    records = []
    seen: set[str] = set()
    for key in [str(item) for item in focus_keys]:
        if key in seen or key not in names:
            continue
        seen.add(key)
        info = names[key]
        locked_row = locked_map.loc[key] if key in locked_map.index else None
        start_row = start_map.loc[key] if key in start_map.index else None
        end_row = end_map.loc[key] if key in end_map.index else None
        if isinstance(locked_row, pd.DataFrame):
            locked_row = locked_row.iloc[0]
        if isinstance(start_row, pd.DataFrame):
            start_row = start_row.iloc[0]
        if isinstance(end_row, pd.DataFrame):
            end_row = end_row.iloc[0]
        qty_day, sales_day, safety_day, qty_month, sales_month, safety_month = _row_slices(
            locked_row, locked_horizon, locked_month
        )
        qty_from, sales_from, _safety_from, qty_month_from, sales_month_from, _safety_month_from = _row_slices(
            start_row, start_horizon, start_month
        )
        qty_to, sales_to, _safety_to, qty_month_to, sales_month_to, _safety_month_to = _row_slices(
            end_row, end_horizon, end_month
        )
        records.append(
            {
                "rank": int(info.peringkat),
                "sku": _clean_product_piece(info.sku, "Tanpa SKU"),
                "product": _clean_product_piece(info.product_name, "Tanpa nama"),
                "variance": _clean_product_piece(info.variasi_tampil, "Tanpa variasi"),
                "sold_sales": int(round(float(info.sales_total))),
                "sold_qty": int(round(float(info.qty_total))),
                "sales_day": sales_day,
                "sales_day_then": sales_from,
                "sales_day_now": sales_to,
                "qty_day": qty_day,
                "qty_day_then": qty_from,
                "qty_day_now": qty_to,
                "safety_day": safety_day,
                "sales_month": sales_month,
                "sales_month_then": sales_month_from,
                "sales_month_now": sales_month_to,
                "qty_month": qty_month,
                "qty_month_then": qty_month_from,
                "qty_month_now": qty_month_to,
                "safety_month": safety_month,
                "move_qty": qty_to - qty_from,
            }
        )
    records = [item for item in records if _prediction_moved(item)]
    records.sort(key=lambda item: (-abs(item["move_qty"]), item["rank"], item["sku"]))
    if not records:
        return pd.DataFrame()
    body = []
    export_rows = []
    for number, item in enumerate(records, start=1):
        body.append(
            "<tr>"
            f"<td class='num pin pin-no'>{number}</td>"
            f"<td class='pin pin-sku'>{html.escape(item['sku'])}</td>"
            f"<td class='wrap-name pin pin-name'>{html.escape(item['product'])}</td>"
            f"<td>{html.escape(item['variance'])}</td>"
            f"<td class='num'>{item['rank']}</td>"
            f"{_sales_cell(item['sold_sales'])}"
            f"{_qty_cell(item['sold_qty'], None)}"
            f"{_sales_cell(item['sales_day'], item['sales_day_now'], item['sales_day_then'])}"
            f"{_qty_cell(item['qty_day'], item['safety_day'], item['qty_day_now'], item['qty_day_then'])}"
            f"{_sales_cell(item['sales_month'], item['sales_month_now'], item['sales_month_then'])}"
            f"{_qty_cell(item['qty_month'], item['safety_month'], item['qty_month_now'], item['qty_month_then'])}"
            "</tr>"
        )
        export_rows.append(
            {
                "No": number,
                "SKU": item["sku"],
                "Product Name": item["product"],
                "Product variance": item["variance"],
                "Peringkat": item["rank"],
                "Penjualan sales": item["sold_sales"],
                "Penjualan qty": item["sold_qty"],
                "Prediksi sales hari ini": item["sales_day"],
                "Prediksi qty hari ini": item["qty_day"],
                "Safety stock hari ini": item["safety_day"],
                "Perubahan sales hari ini": item["sales_day_now"] - item["sales_day_then"],
                "Perubahan qty hari ini": item["qty_day_now"] - item["qty_day_then"],
                "Prediksi sales bulan ini": item["sales_month"],
                "Prediksi qty bulan ini": item["qty_month"],
                "Safety stock bulan ini": item["safety_month"],
                "Perubahan sales bulan ini": item["sales_month_now"] - item["sales_month_then"],
                "Perubahan qty bulan ini": item["qty_month_now"] - item["qty_month_then"],
            }
        )
    def _total(key: str) -> int:
        return sum(int(item[key]) for item in records)

    total_row = (
        "<tr class='sheet-total'>"
        "<th class='pin pin-no'></th>"
        "<th class='pin pin-sku'></th>"
        "<th class='pin pin-name'>Total"
        f"<div class='qty-safety'>{len(records)} item bergerak</div></th>"
        "<th></th><th></th>"
        f"{_sales_cell(_total('sold_sales'), tag='th')}"
        f"{_qty_cell(_total('sold_qty'), None, tag='th')}"
        f"{_sales_cell(_total('sales_day'), _total('sales_day_now'), _total('sales_day_then'), tag='th')}"
        f"{_qty_cell(_total('qty_day'), _total('safety_day'), _total('qty_day_now'), _total('qty_day_then'), tag='th')}"
        f"{_sales_cell(_total('sales_month'), _total('sales_month_now'), _total('sales_month_then'), tag='th')}"
        f"{_qty_cell(_total('qty_month'), _total('safety_month'), _total('qty_month_now'), _total('qty_month_then'), tag='th')}"
        "</tr>"
    )
    header = (
        "<tr>"
        "<th class='pin pin-no' rowspan='2'>No</th>"
        "<th class='pin pin-sku' rowspan='2'><div class='pin-kicker'>Produk</div>SKU</th>"
        "<th class='pin pin-name' rowspan='2'><div class='pin-kicker'>Produk</div>Product Name</th>"
        "<th rowspan='2'>Product variance</th>"
        "<th rowspan='2'>Peringkat</th>"
        "<th class='group-head' colspan='2'>Penjualan</th>"
        "<th class='group-head' colspan='2'>Prediksi hari ini</th>"
        "<th class='group-head' colspan='2'>Prediksi bulan ini</th>"
        "</tr>"
        "<tr>"
        "<th class='num'>Sales</th><th class='num'>QTY</th>"
        "<th class='num'>Sales</th><th class='num'>QTY</th>"
        "<th class='num'>Sales</th><th class='num'>QTY</th>"
        "</tr>"
        f"{total_row}"
    )
    export_rows.append(
        {
            "No": "",
            "SKU": "",
            "Product Name": "Total",
            "Product variance": "",
            "Peringkat": "",
            "Penjualan sales": _total("sold_sales"),
            "Penjualan qty": _total("sold_qty"),
            "Prediksi sales hari ini": _total("sales_day"),
            "Prediksi qty hari ini": _total("qty_day"),
            "Safety stock hari ini": _total("safety_day"),
            "Perubahan sales hari ini": _total("sales_day_now") - _total("sales_day_then"),
            "Perubahan qty hari ini": _total("qty_day_now") - _total("qty_day_then"),
            "Prediksi sales bulan ini": _total("sales_month"),
            "Prediksi qty bulan ini": _total("qty_month"),
            "Safety stock bulan ini": _total("safety_month"),
            "Perubahan sales bulan ini": _total("sales_month_now") - _total("sales_month_then"),
            "Perubahan qty bulan ini": _total("qty_month_now") - _total("qty_month_then"),
        }
    )
    st.markdown(
        "<div class='sheet-scroll movement-sheet' style='max-height:640px;width:100%;max-width:100%;overflow:scroll;display:block;'>"
        f"<table><thead>{header}</thead><tbody>{''.join(body)}</tbody></table></div>",
        unsafe_allow_html=True,
    )
    return pd.DataFrame(export_rows)


def show_analysis_movement(
    stock: pd.DataFrame,
    current_id: str,
    _previous_id: str,
    current_meta: dict,
    metric: str,
    focus_keys: list[str],
    catalog: pd.DataFrame,
    history: pd.DataFrame | None = None,
    service: int = 0,
    source_key: str = "",
) -> pd.DataFrame | None:
    """Panel pergerakan untuk Ringkasan dan Prediksi & stok. Rumus prediksi tidak diubah."""
    st.markdown("<div class='section-title'>Pergerakan dari analisis sebelumnya</div>", unsafe_allow_html=True)
    today = date.today()
    yesterday = today - timedelta(days=1)
    period_key = str(current_meta.get("period") or "bulan")
    ready = apply_horizon_slices(catalog, period_key, today) if isinstance(catalog, pd.DataFrame) else catalog
    sales_day, stock_day, sales_month, stock_month = _prediction_totals(ready)
    prior_frame = _movement_frame(
        yesterday,
        live_stock=stock,
        live_day=today,
        history=history,
        period=period_key,
        service=int(current_meta.get("service", service) or 0),
        source_key=source_key,
    )
    prior = _aligned_totals(prior_frame, catalog if isinstance(catalog, pd.DataFrame) else None, period_key, yesterday)
    month_days = days_in_calendar_month(today)
    st.markdown(
        "<div class='field-hint'>Angka di bawah dibaca dari laporan transaksi yang sedang dianalisis. "
        f"Prediksi sales hari ini adalah 1 hari. Prediksi sales bulan ini dihitung dari tanggal 1 sampai akhir bulan "
        f"({format_number(month_days)} hari, {html.escape(ID_MONTHS[today.month - 1])} {today.year}). "
        "Tulisan di bawahnya (biru naik, merah turun) membandingkan prediksi ini dengan prediksi Level terkini seandainya dihitung kemarin dari data latih yang sama.</div>",
        unsafe_allow_html=True,
    )
    cards = st.columns(4)
    _prediction_card(cards[0], "Prediksi sales hari ini", format_idr(sales_day), _move_line(sales_day, None if prior is None else prior[0], money=True))
    _prediction_card(cards[1], "Prediksi stok hari ini", format_qty(stock_day), _move_line(stock_day, None if prior is None else prior[1], money=False))
    _prediction_card(cards[2], "Prediksi sales bulan ini", format_idr(sales_month), _move_line(sales_month, None if prior is None else prior[2], money=True))
    _prediction_card(cards[3], "Prediksi stok bulan ini", format_qty(stock_month), _move_line(stock_month, None if prior is None else prior[3], money=False))
    st.markdown("<div class='section-title'>Pergerakan Top 50</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='field-hint'>Angka prediksi hari ini dan bulan ini adalah target terkunci dari Jalankan analisis. "
        "Tabel hanya memuat item Top 50 yang prediksinya berubah pada rentang tanggal. Item yang selisihnya nol tidak ditampilkan. "
        "Biru berarti naik, merah berarti turun: prediksi pada sampai tanggal dikurangi prediksi pada dari tanggal. "
        "Baris Total di bawah header menjumlahkan item yang ditampilkan. Nama produk tetap terlihat saat tabel digeser ke kanan. "
        "Safety stock ditulis di bawah QTY prediksi.</div>",
        unsafe_allow_html=True,
    )
    if "movement-date-from" not in st.session_state:
        st.session_state["movement-date-from"] = today - timedelta(days=1)
    if "movement-date-to" not in st.session_state:
        st.session_state["movement-date-to"] = today
    pick_start, pick_end = st.columns(2)
    earliest = date(2020, 1, 1)
    start_day = _as_date(
        pick_start.date_input(
            "Dari tanggal",
            min_value=earliest,
            max_value=today,
            format="DD/MM/YYYY",
            key="movement-date-from",
        )
    ) or (today - timedelta(days=1))
    end_day = _as_date(
        pick_end.date_input(
            "Sampai tanggal",
            min_value=earliest,
            max_value=today,
            format="DD/MM/YYYY",
            key="movement-date-to",
        )
    ) or today
    frame_args = dict(
        live_stock=stock,
        live_day=today,
        history=history,
        period=period_key,
        service=int(current_meta.get("service", service) or 0),
        source_key=source_key,
    )
    locked = frame_from_stock(stock)
    start_frame = _movement_frame(start_day, **frame_args)
    end_frame = locked if end_day == today else _movement_frame(end_day, **frame_args)
    detail = compare_runs(end_frame, start_frame, metric)
    st.markdown(
        f"<div class='field-hint'>Pergerakan {html.escape(format_id_date(start_day))} "
        f"sampai {html.escape(format_id_date(end_day))}. "
        "Hanya item yang prediksi hari ini atau prediksi bulan ini-nya berubah. "
        "Target prediksi hari ini tidak diganti. Urutan baris mengikuti selisih QTY prediksi pada rentang ini.</div>",
        unsafe_allow_html=True,
    )
    export = _render_movement_board(
        catalog if isinstance(catalog, pd.DataFrame) else pd.DataFrame(),
        [str(key) for key in focus_keys],
        locked,
        start_frame,
        end_frame,
        period=period_key,
        start_day=start_day,
        end_day=end_day,
        today=today,
    )
    if export.empty:
        st.markdown(
            "<div class='field-hint'>Pada rentang ini tidak ada item Top 50 yang prediksinya berubah.</div>",
            unsafe_allow_html=True,
        )
        return detail
    offer_excel(export, "pergerakan_top50.xlsx")
    return detail


def priority_top10(view: pd.DataFrame) -> pd.DataFrame:
    """Sepuluh SKU yang QTY terjual dan sales volume-nya sama-sama besar."""
    if view is None or view.empty:
        return view.iloc[0:0].copy() if isinstance(view, pd.DataFrame) else pd.DataFrame()
    work = view.loc[(view["qty_total"] > 0) & (view["sales_total"] > 0)].copy()
    if work.empty:
        return work
    qty_peak = float(work["qty_total"].max() or 1)
    sales_peak = float(work["sales_total"].max() or 1)
    work["_score"] = 0.5 * work["qty_total"].astype(float) / qty_peak + 0.5 * work["sales_total"].astype(float) / sales_peak
    work = work.sort_values(
        ["_score", "sales_total", "qty_total", "item_key"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).head(10)
    work = work.drop(columns="_score").reset_index(drop=True)
    work["peringkat"] = range(1, len(work) + 1)
    return work


def show_priority_stock(catalog: pd.DataFrame, period: str, day: date) -> None:
    """Empat angka terpisah: sales dan stok untuk hari ini, serta untuk bulan kalender dari tanggal 1."""
    ready = apply_horizon_slices(catalog, period, day) if catalog is not None and not catalog.empty else catalog
    horizon = max(horizon_day_count(period, day), 1)
    month_days = days_in_calendar_month(day)
    month_end = date(day.year, day.month, month_days)
    st.markdown("<div class='section-title'>Prediksi hari ini dan bulan ini</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='field-hint'>"
        f"Prediksi {html.escape(PERIOD_SPECS[period].label)} adalah {format_number(horizon)} hari dari {html.escape(format_id_date(day))}, rumus Level terkini tidak diubah. "
        f"Prediksi sales hari ini = prediksi sales periode itu dibagi {format_number(horizon)}. "
        f"Prediksi sales bulan ini = bagian {format_number(month_days)} hari, {html.escape(format_id_date(day))} sampai {html.escape(format_id_date(month_end))}. "
        "Stok disarankan hari ini = prediksi QTY 1 hari + safety stock 1 hari. "
        f"Stok disarankan bulan ini memakai {format_number(month_days)} hari. Safety mengikuti akar jumlah hari, bukan dibagi rata. "
        "Di bawah stok hari ini, selisih terhadap analisis tanggal pembanding: biru naik, merah turun, tanda - bila sama.</div>",
        unsafe_allow_html=True,
    )
    if ready is None or ready.empty:
        st.write("Belum ada SKU pada periode penjualan ini.")
        return
    cards = st.columns(4)
    show_metric(cards[0], "Prediksi sales hari ini", format_idr(float(ready["pred_sales_hari"].sum())), hint=f"1 hari dari prediksi {PERIOD_SPECS[period].label}.")
    show_metric(
        cards[1],
        "Prediksi sales bulan ini",
        format_idr(float(ready["pred_sales_bulan"].sum())),
        hint=f"{format_number(month_days)} hari, sampai {format_id_date(month_end)}.",
    )
    show_metric(cards[2], "Stok disarankan hari ini", format_qty(float(ready["stok_hari"].sum())), hint="Prediksi QTY 1 hari + safety 1 hari.")
    show_metric(
        cards[3],
        "Stok disarankan bulan ini",
        format_qty(float(ready["stok_bulan"].sum())),
        hint=f"Prediksi QTY {format_number(month_days)} hari + safety {format_number(month_days)} hari.",
    )
    top = priority_top10(ready)
    if top.empty:
        st.write("Belum ada SKU yang punya QTY terjual dan sales volume sekaligus.")
        return
    display = leaderboard_frame(top, period)
    scroll_table(display, max_height=520)
    offer_excel(display, "top10_prioritas_stok.xlsx")


if st.session_state.get("active-feature") != FEATURE_ID:
    show_homepage()
    st.stop()

if "editing-input" not in st.session_state:
    st.session_state["editing-input"] = "analysis" not in st.session_state
editing_input = bool(st.session_state["editing-input"])
if (
    not editing_input
    and "analysis" not in st.session_state
    and not st.session_state.get("pending-run")
):
    editing_input = True
    st.session_state["editing-input"] = True

show_feature_header(
    show_analysis_button=editing_input and "analysis" in st.session_state,
    show_training_button=not editing_input,
)

if editing_input:
    show_prediction_inputs()

orders_raw, source_raw, source_key, period, sidebar_metric, service = restore_prediction_context()
run = bool(st.session_state.pop("pending-run", False))
load_error = None

today = date.today()
window_start, window_end, period_text = forecast_window(period, today)

if run and (not isinstance(orders_raw, pd.DataFrame) or orders_raw.empty):
    st.session_state["editing-input"] = True
    st.session_state["input-error"] = "Data latih tidak terbaca. Pilih bulan atau unggah laporan, lalu jalankan analisis lagi."
    st.rerun()

sheet = str(st.session_state.get("active-sheet", "Ringkasan"))
if "exclude-return-batal" not in st.session_state:
    st.session_state["exclude-return-batal"] = bool(st.session_state.get("exclude_applied", False))
exclude_return_cancel = bool(st.session_state.get("exclude-return-batal", False))
st.session_state["exclude_applied"] = exclude_return_cancel
if "analysis" in st.session_state and not run:
    sheet = show_app_menu()
    if sheet in SUMMARY_SHEETS:
        date_col, period_col = st.columns([1, 2.2])
        show_metric(date_col, "Tanggal hari ini", format_id_date(today))
        period_col.markdown(
            "<div class='stat-card calm'>"
            "<div class='readable-metric-label'>Periode prediksi</div>"
            f"<div class='period-name'>{PERIOD_SPECS[period].label}</div>"
            f"<div class='period-dates'>{format_id_date(window_start)} – {format_id_date(window_end)}</div>"
            "</div>",
            unsafe_allow_html=True,
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
    run_meta = _analysis_meta(
        period=period,
        period_text=period_text,
        metric=sidebar_metric,
        service=service,
        exclude=exclude_return_cancel,
        window_start=window_start,
        window_end=window_end,
    )
    run_id, previous_run_id = _remember_run(stock, run_meta)
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
        "run_id": run_id,
        "previous_run_id": previous_run_id,
    }
    st.rerun()
else:
    stored = st.session_state["analysis"]
    if not stored.get("run_id"):
        baseline_meta = _analysis_meta(
            period=str(stored.get("period", period)),
            period_text=str(stored.get("period_text") or period_text),
            metric=str(stored.get("metric", sidebar_metric)),
            service=int(stored.get("service", service)),
            exclude=bool(stored.get("exclude_return_cancel", exclude_return_cancel)),
            window_start=window_start,
            window_end=window_end,
        )
        run_id, previous_run_id = _remember_run(stored.get("stock", pd.DataFrame()), baseline_meta)
        stored["run_id"] = run_id
        stored["previous_run_id"] = previous_run_id
        st.session_state["analysis"] = stored
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
sales_orders, resume_label = filter_resume_orders(
    orders,
    show_controls=show_resume,
    show_exclude=show_resume,
)
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

if sheet in {"Ringkasan", "Prediksi & stok"} and isinstance(stock, pd.DataFrame):
    movement_detail = show_analysis_movement(
        stock,
        str(st.session_state.get("analysis", {}).get("run_id") or ""),
        str(st.session_state.get("analysis", {}).get("previous_run_id") or ""),
        _analysis_meta(
            period=period,
            period_text=period_text,
            metric=metric,
            service=int(st.session_state.get("analysis", {}).get("service", service)),
            exclude=exclude_return_cancel,
            window_start=window_start,
            window_end=window_end,
        ),
        metric,
        shown["item_key"].astype(str).tolist() if "item_key" in shown.columns else [],
        catalog,
        history=st.session_state.get("analysis", {}).get("base_history"),
        service=int(st.session_state.get("analysis", {}).get("service", service)),
        source_key=str(st.session_state.get("analysis", {}).get("source_key") or ""),
    )
    if movement_detail is not None and not movement_detail.empty:
        shown = _attach_movement(shown, movement_detail, horizon_day_count(period, today))
        catalog = _attach_movement(catalog, movement_detail, horizon_day_count(period, today))
    shown = apply_horizon_slices(shown, period, today)
    catalog = apply_horizon_slices(catalog, period, today)

if sheet == "Ringkasan":
    chart_slot = st.container()
    table_slot = st.container()
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
            "Stok disarankan hari ini adalah 1 hari dari prediksi. Stok disarankan bulan ini dihitung dari tanggal 1 sampai akhir bulan. Stok disarankan periode tetap prediksi QTY + safety stock untuk seluruh periode yang dipilih. "
            f"{grain_note} "
            "Centang SKU di tabel untuk menampilkan grafiknya. "
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
            then_day = _as_date(st.session_state.get("movement-date-from"))
            to_day = _as_date(st.session_state.get("movement-date-to"))
            if "mv_pred_qty_then" in table_view.columns and then_day and to_day:
                st.caption(
                    f"Angka kecil di bawah setiap prediksi adalah perubahan dibanding prediksi {format_id_date(then_day)} "
                    f"(rentang tabel pergerakan {format_id_date(then_day)} – {format_id_date(to_day)}). "
                    "▲ biru berarti naik, ▼ merah berarti turun. "
                    "Urutan hitung per kelompok: QTY prediksi, lalu sales = QTY × harga jual, "
                    "safety stock = z × sigma × akar hari, dan stok disarankan = QTY prediksi + safety stock. "
                    "Klik judul kolom untuk mengurutkan. Centang satu baris untuk menampilkan grafiknya."
                )
            else:
                then_day = None
                st.caption(
                    "Urutan hitung per kelompok: QTY prediksi, lalu sales = QTY × harga jual, "
                    "safety stock = z × sigma × akar hari, dan stok disarankan = QTY prediksi + safety stock. "
                    "Perubahan naik atau turun muncul setelah ada dua analisis tersimpan di tabel pergerakan. "
                    "Klik judul kolom untuk mengurutkan. Centang satu baris untuk menampilkan grafiknya."
                )
            selected_choice = show_top50_table(
                table_view,
                period=period,
                today=today,
                then_day=then_day,
                resume_label=resume_label,
                key=f"top50-table-{metric}-{period}",
            )
            if selected_choice:
                selected_key = selected_choice
                chosen_row = table_view.loc[table_view["item_key"].astype(str) == selected_choice].iloc[0]
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
                show_qty_forecast_board(
                    view,
                    resume_label=resume_label,
                    period_text=period_text,
                    horizon_days=horizon_day_count(period, today),
                    history=st.session_state.get("analysis", {}).get("base_history"),
                    orders=orders,
                    exclude_cancel=bool(st.session_state.get("analysis", {}).get("exclude_return_cancel", False)),
                    as_of=today,
                    stock=stock if isinstance(stock, pd.DataFrame) else None,
                    period=period,
                    service=int(st.session_state.get("analysis", {}).get("service", service)),
                    source_key=str(st.session_state.get("analysis", {}).get("source_key") or ""),
                )

        if selected_key is None:
            if metric == "sales":
                st.info("Pilih satu SKU pada tabel Top 50 untuk menampilkan grafik sales dan garis QTY.")
            else:
                st.info("Pilih satu SKU pada tabel Top 50 untuk menampilkan empat grafik di bawah.")
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
        "Stok disarankan hari ini = prediksi QTY 1 hari + safety 1 hari. Stok disarankan bulan ini dihitung dari tanggal 1 sampai akhir bulan. "
        "Stok disarankan periode = prediksi QTY periode + safety stock periode. Mengubah persentase hanya mengubah safety dan stok, bukan prediksi QTY. "
        "Kolom kiri adalah stok disarankan hari ini. Di bawah angkanya tertulis selisih stok hari ini. Lalu SKU, Product Name, dan Product variance. "
        "Isi tabel mengikuti centang Exclude return dan batal di header."
    )
    if catalog.empty:
        st.write("Tidak ada item untuk ditampilkan.")
    else:
        display = leaderboard_frame(
            sort_leaderboard(catalog, "qty_desc" if metric == "qty" else "sales_desc"),
            period,
        )
        scroll_table(display, max_height=680)
        offer_excel(display, "rekomendasi_stok.xlsx")

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
        offer_excel(comparison, "evaluasi_model.xlsx")
    daily_history = st.session_state.get("analysis", {}).get("base_history", pd.DataFrame())
    if not isinstance(daily_history, pd.DataFrame):
        daily_history = pd.DataFrame()
    show_intelligence_dashboard(orders, daily_history)

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
