from __future__ import annotations

import base64
import hashlib
import html
import os
import sys
import time
from datetime import date, datetime, timedelta

# Server Streamlit Cloud berjalan di UTC; tanggal "hari ini" harus WIB seperti waktu pesanan Shopee.
# Selalu WIB, juga bila platform sudah mengisi TZ=UTC: tanggal "hari ini" menentukan jendela prediksi.
os.environ["TZ"] = "Asia/Jakarta"
if hasattr(time, "tzset"):
    time.tzset()
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


def _reloadable(name: str) -> bool:
    # auth.ui ikut dimuat ulang (cache FeatureStore); auth.repository tidak, agar objek User di sesi tetap dikenali.
    return name == "src" or name.startswith("src.") or name == "auth.ui"


class _ImportClock:
    """Mencatat waktu impor modul src/auth.ui (sekali per proses) untuk dibandingkan dengan waktu ubah file."""

    def __init__(self, loaded: dict) -> None:
        self.loaded = loaded

    def find_spec(self, name, path=None, target=None):
        if _reloadable(name):
            self.loaded[name] = time.time()
        return None


def _drop_stale_src_modules() -> None:
    """Push ke main memperbarui file tanpa me-restart proses Cloud. Bila ada modul src/auth.ui yang filenya
    lebih baru dari saat diimpor (atau diimpor sebelum pencatat ada), semua modul itu dibuang agar diimpor
    ulang dari file terbaru — tanpa ImportError, tanpa FeatureStore lama, tanpa Reboot."""
    loaded = sys.__dict__.setdefault("_mitra10_loaded_at", {})
    if not any(isinstance(finder, _ImportClock) or type(finder).__name__ == "_ImportClock" for finder in sys.meta_path):
        sys.meta_path.insert(0, _ImportClock(loaded))
    files = [*(ROOT / "src").rglob("*.py"), ROOT / "auth" / "ui.py"]
    os.environ["MITRA10_SRC_STAMP"] = str(max((p.stat().st_mtime for p in files if p.exists()), default=0.0))
    stale = False
    for name, module in list(sys.modules.items()):
        path = getattr(module, "__file__", None) if _reloadable(name) else None
        if not path:
            continue
        try:
            stale = os.path.getmtime(path) >= loaded.get(name, 0.0)
        except OSError:
            stale = True
        if stale:
            break
    if not stale:
        return
    for name in [m for m in sys.modules if _reloadable(m)]:
        del sys.modules[name]
        loaded.pop(name, None)


_drop_stale_src_modules()

from src.activity import (
    activity_report,
    append_total_row,
    cancel_contribution,
    focus_summary,
    ledger_from_raw,
    scope_ledger,
    unpaid_buyer_table,
)
from src.aggregate import (
    PERIOD_OPTIONS,
    PERIOD_SPECS,
    aggregate_item_periods,
    next_period_start,
    period_label,
    period_start,
)
from src.core.config import changed_from_default, load_params, save_params
from src.core.consolidation import consolidation_summary
from src.core.decision_table import PERIOD_LABELS, build_decision_table, lama_kosong_text, period_actuals, period_groups, whole_units
from src.core.enrich import StoreFrames, enrich_catalog, load_store_frames, zero_since_map
from src.core.performance import clean_performance, perf_number
from src.core.pipeline import (
    apply_ensemble,
    apply_recent_price,
    outcome_with_weights,
    run_demand_models,
)
from src.core.service_level import recommended_service_level, safety_impact
from src.ui.analysis_dialog import analysis_markup, store_performance
from src.core.labels import LABEL_ICONS
from src.ui.common import DEFAULT_NOTE, apply_saved_period, install_plotly_locale, batched_view, page_navigator, date_range_picker, excel_payload, reset_batches, cached_order_metrics, cached_sku_coverage, card, download_excel, exclude_status_card, explain, metric_card, period_filter, table_toolbar
from src.ui.common import fmt_pct as format_pct_id
from src.core.metrics import EMPTY_ORDER_METRICS, ads_metrics, period_bounds
from src.core.periods import format_period_label, month_year, prediction_window, same_target, window_days
from src.ui.confirm import confirm_action
from src.ui.evaluasi import show_evaluation
from src.ui.laporan import show_report
from src.ui.rekomendasi import show_recommendations
from src.ui.decision_view import (
    SS_DEFINITION_TOP,
    label_legend,
    past_predictions,
    safety_stock_box,
    show_decision_table,
    sku_charts,
    top50_matrix,
)
from src.ui.region import show_region_analysis
from src.ui.instant import show_instant_analysis
from src.ui.order_ops import show_ops_analysis
from src.ui.targets_view import achievement_line, monthly_targets, show_target_uploader
from src.core.schemas import SOURCE_SPECS, canonicalize_frame, find_columns, source_menu, validation_report
from src.utils.format import angka as fmt_angka
from src.utils.format import desimal as fmt_desimal
from src.utils.format import excel_bytes as numeric_excel_bytes
from src.utils.format import TOTAL_ROW_CSS, drop_blank_rows, show_table, style_frame, table_height, wrap_layout
from src.utils.format import rupiah as fmt_rupiah
from src.core.storage import LocalDataStore, read_upload_file
from src.core.filevault import FileVault, vault_enabled
from src.core.storage_guard import database_size_mb, enforce as enforce_storage, settings as storage_settings
from src.core.userspace import deploy_mode, team_root
from auth.permissions import SHEET_PERMISSIONS, allowed_sheets, can, role_label
from auth.ui import PAGE_KEY as AUTH_PAGE_KEY, audit, get_engine, get_features, login_gate, require, require_role, show_auth_page, account_menu
from auth.ui import logout as auth_logout
from src.ui.routing import FEATURE_ID, PAGE_HOME, PAGE_INPUT, PAGE_PASSWORD, PAGE_RESULT, PAGE_SETTING, PAGE_USERS, apply_route, route_from_state, sync_route
from src.core.promo import drop_excluded
from src.core.periods import last_full_month
from src.core.warehouse import lead_time_stats
from src.ui.dashboard import show_priority_dashboard
from src.ui.feature_data import cached_feature_data, excluded_skus
from src.ui.prediksi_top import save_run_snapshot, show_pred_vs_actual
from src.ui.setting_page import show_setting
from src.core.access import allowed as allowed_access, setting_tabs
from src.core.fmt import fmt_date_short
from src.core.runs import RunRepository, data_hash as training_data_hash
from src.core import journey
import src.library as library_store
from src.library import configure_root as configure_library_root
from src.movement import configure_root as configure_movement_root
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
from src.movement import compare_runs, frame_from_stock, record_run
from src.ingest import (
    _is_cancelled_status,
    cancelled_status_mask,
    clean_order_frame,
    load_shopee_report,
    order_month_keys,
)
from src.ranking import combine_forecasts, rank_for_period, rank_from_orders
from src.stock import recommend_stock

st.set_page_config(
    page_title="Mitra10 × Shopee",
    page_icon="📦",
    layout="wide",
)
install_plotly_locale()


def _app_page() -> None:
    """Isi halaman dirender langsung oleh skrip ini."""


# Tanpa st.navigation, Streamlit tidak rerun saat tombol back browser mengubah ?page=.
st.navigation([st.Page(_app_page, title="Mitra10 × Shopee", default=True)], position="hidden").run()

USER_ROOT = team_root()
if deploy_mode() == "server":
    configure_library_root(USER_ROOT)
    configure_movement_root(USER_ROOT)
DATA_STORE = LocalDataStore(USER_ROOT)


def _vault_areas() -> dict[str, Path]:
    import src.movement as movement_store
    from src.core.runs import DEFAULT_RUNS_ROOT

    areas = {"team": USER_ROOT, "runs": DEFAULT_RUNS_ROOT}
    for name, folder in (("library", library_store.LIBRARY_DIR), ("history", movement_store.RUNS_DIR)):
        if USER_ROOT not in Path(folder).resolve().parents:
            areas[name] = Path(folder)
    return areas


@st.cache_resource(show_spinner="Memulihkan data latih dan hasil analisa tersimpan…")
def file_vault() -> FileVault | None:
    """Sekali per proses server: pulihkan file dari database ke disk yang baru (kosong)."""
    engine = get_engine()
    if not vault_enabled(engine):
        return None
    vault = FileVault(engine, _vault_areas())
    vault.restore()
    return vault


def sync_file_vault() -> None:
    """Salin file data/hasil yang baru berubah ke database. Gagal sinkron tidak menghentikan halaman."""
    try:
        vault = file_vault()
        if vault is not None:
            vault.push()
    except Exception as exc:  # noqa: BLE001
        st.session_state["_vault-error"] = str(exc)


def show_vault_status() -> None:
    """Keterangan apakah data latih aman dari restart/redeploy server."""
    error = st.session_state.pop("_vault-error", None)
    if error:
        st.warning(f"Data latih belum tersalin ke database permanen: {error}. Data tetap terbaca selama server belum restart.")
        return
    try:
        vault = file_vault()
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Database permanen untuk data latih belum bisa dihubungi: {exc}")
        return
    if vault is None:
        if deploy_mode() == "server":
            st.warning(
                "Data latih tersimpan di disk server sementara dan akan hilang saat server tidur, restart, atau redeploy. "
                "Isi `DATABASE_URL` (Postgres Supabase) di Secrets agar data latih dan hasil analisa tetap ada."
            )
        return
    files, size, stored = vault.summary()
    cfg = storage_settings(current_params())
    used = database_size_mb(get_engine())
    usage = f" Database terpakai {format_number(used, 0)} dari {format_number(cfg['kuota_mb'])} MB." if used is not None else ""
    st.caption(
        f"Data latih dan hasil analisa tersimpan permanen di database: {format_number(files)} file · "
        f"{format_number(size / 1024 / 1024, 1)} MB, dikompres menjadi {format_number(stored / 1024 / 1024, 1)} MB.{usage} "
        f"Disimpan {cfg['maks_riwayat_analisa']} riwayat analisa terbaru; yang lebih lama dihapus otomatis agar kuota gratis tidak penuh."
    )
    if used is not None and used > cfg["batas_darurat_mb"]:
        st.warning(f"Database hampir penuh ({format_number(used, 0)} MB). Analisa tertua dihapus otomatis; "
                   "kurangi `penyimpanan.maks_riwayat_analisa` bila peringatan ini sering muncul.")
    report = st.session_state.pop("_storage-report", None)
    if report is not None and report.runs_deleted:
        st.caption(f"Pembersihan otomatis: riwayat analisa #{', #'.join(str(i) for i in sorted(report.runs_deleted))} dihapus.")


def current_params() -> dict:
    """Parameter bisnis (config/business_params.yaml); lead time impor diganti lead time aktual dari Setting › Kedatangan impor bila sudah ada."""
    params = load_params(USER_ROOT)
    stats = import_lead_time()
    if stats:
        lead = dict(params.get("lead_time", {}))
        lead["impor_rata_hari"], lead["impor_maks_hari"] = int(round(stats[0])), int(round(stats[1]))
        lead["impor_sumber"] = "Kedatangan impor"
        params = {**params, "lead_time": lead}
    # Margin kotor toko dari File margin (Setting › Laporan margin) bila sudah diunggah.
    try:
        from src.ui.margin_data import load_margin

        md = load_margin(get_features())
        kotor = md.store_kotor_pct if md.ready else float("nan")
        if kotor == kotor:
            margin = {**(params.get("margin") or {}), "hpp_pct_harga": round(100.0 - kotor, 1), "margin_min_pct": 0, "sumber": f"File margin {md.periode}"}
            params = {**params, "margin": margin}
    except Exception:
        pass
    room = warehouse_capacity()
    if room:
        gudang_cfg = {**(params.get("gudang") or {}), "kapasitas_unit": int(round(room["unit"])), "kapasitas_sumber": room["sumber"]}
        params = {**params, "gudang": gudang_cfg}
    return params


def warehouse_capacity() -> dict | None:
    """Kapasitas restock dari replenishment Site 10037 terbaru (Setting › Kapasitas gudang)."""
    version = st.session_state.get("_feature-version", 0)
    cached = st.session_state.get("_wh-capacity")
    if isinstance(cached, tuple) and cached[0] == version:
        return cached[1]
    try:
        from src.core.gudang import restock_capacity
        from src.ui.gudang_view import load_replenishment

        repl, snapshot, _dates = load_replenishment(get_features())
        room = restock_capacity(repl)
        if room:
            room["sumber"] = f"Replenishment Site 10037 {snapshot}"
    except Exception:
        room = None
    st.session_state["_wh-capacity"] = (version, room)
    return room


def import_lead_time() -> tuple[float, float] | None:
    version = st.session_state.get("_feature-version", 0)
    cached = st.session_state.get("_import-lead")
    if isinstance(cached, tuple) and cached[0] == version:
        return cached[1]
    try:
        stats = lead_time_stats(get_features().read("import_note"))
    except Exception:
        stats = None
    st.session_state["_import-lead"] = (version, stats)
    return stats


def store_frames() -> StoreFrames:
    """Data stok, iklan, performa, deskripsi, kompetitor dari 9 menu upload; dibaca ulang bila ada upload baru."""
    path = DATA_STORE.registry_path
    stamp = (str(DATA_STORE.root), path.stat().st_mtime if path.exists() else 0.0)
    cached = st.session_state.get("_store-frames")
    if isinstance(cached, tuple) and cached[0] == stamp:
        return cached[1]
    frames = load_store_frames(DATA_STORE)
    st.session_state["_store-frames"] = (stamp, frames)
    return frames


_APP_CSS = """
    <style>
    /* Satu skala ukuran huruf untuk seluruh aplikasi; jangan menulis font-size angka langsung. */
    :root {
        --fs-xs: 0.75rem;
        --fs-sm: 0.85rem;
        --fs-base: 0.95rem;
        --fs-lg: 1.1rem;
        --fs-xl: 1.35rem;
        --fs-2xl: 1.6rem;
        --fs-display: 2.4rem;
    }
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stAlertContainer"] p,
    [data-testid="stExpander"] summary p,
    [data-testid="stTab"] p,
    [data-testid="stButton"] button p,
    [data-testid="stDownloadButton"] button p,
    [data-testid="stPopover"] button p,
    [data-testid="stCheckbox"] label p,
    [data-testid="stRadio"] label p { font-size: var(--fs-base); }
    [data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] p,
    [data-testid="stWidgetLabel"] p,
    [data-testid="stMetricLabel"] p { font-size: var(--fs-sm); }
    [data-testid="stHeading"] h1 { font-size: var(--fs-2xl); }
    [data-testid="stHeading"] h2 { font-size: var(--fs-xl); }
    [data-testid="stHeading"] h3,
    [data-testid="stHeading"] h4 { font-size: var(--fs-lg); }
    [data-testid="stMetricValue"],
    [data-testid="stMetricValue"] > div {
        font-size: var(--fs-xl) !important;
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
        font-size: var(--fs-xs);
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        line-height: 1.35;
        color: #64748b;
        margin: 0 0 0.45rem 0;
    }
    .readable-metric-value {
        font-size: var(--fs-xl);
        font-weight: 800;
        letter-spacing: -0.03em;
        line-height: 1.25;
        color: #0f172a;
        white-space: normal;
        word-break: keep-all;
        overflow-wrap: normal;
        font-size: clamp(1.05rem, 1.9vw, var(--fs-xl));
    }
    .readable-metric-value.compact {
        font-size: var(--fs-lg);
        line-height: 1.35;
        letter-spacing: -0.02em;
    }
    .metric-hint {
        font-size: var(--fs-sm);
        font-weight: 500;
        line-height: 1.4;
        color: #64748b;
        margin: 0.4rem 0 0 0;
        padding-top: 0.35rem;
        border-top: 1px solid #eef1f6;
    }
    .period-name {
        font-size: var(--fs-xl);
        font-weight: 800;
        letter-spacing: -0.03em;
        line-height: 1.25;
        color: #0f172a;
    }
    .period-dates {
        font-size: var(--fs-base);
        line-height: 1.5;
        color: #334155;
        margin-top: 0.4rem;
    }
    .report-stage-head {
        margin: 0.95rem 0 0.2rem;
    }
    .report-kicker {
        font-size: var(--fs-xs);
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
        font-size: var(--fs-2xl);
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
        font-size: var(--fs-base);
        line-height: 1.55;
        color: #1e293b;
        margin: 0.15rem 0 0.7rem;
        max-width: none;
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
        font-size: var(--fs-xs);
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
        font-size: var(--fs-base);
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
        font-size: var(--fs-sm);
        line-height: 1.45;
        color: #64748b;
        max-width: none;
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
    /* Sama dengan judul kartu lain (.home-section): huruf kapital kecil abu-abu, tanpa garis hitam. */
    .side-section {
        font-size: var(--fs-xs);
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #64748b;
        margin: 0.35rem 0 0.45rem 0;
        padding-bottom: 0.28rem;
        border-bottom: 1px solid #e2e8f0;
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
        font-size: var(--fs-base);
    }
    .side-note {
        font-size: var(--fs-sm);
        line-height: 1.35;
        color: #475569;
        margin: 0.1rem 0 0.55rem 0;
    }
    .side-warn {
        font-size: var(--fs-sm);
        line-height: 1.35;
        color: #9a3412;
        background: #fff7ed;
        border-radius: 8px;
        padding: 0.45rem 0.6rem;
        margin: 0.1rem 0 0.7rem 0;
    }
    .side-low {
        font-size: var(--fs-sm);
        line-height: 1.35;
        color: #1e3a8a;
        background: #eff6ff;
        border-radius: 8px;
        padding: 0.45rem 0.6rem;
        margin: 0.1rem 0 0.7rem 0;
    }
    .side-best {
        font-size: var(--fs-sm);
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
    /* Teks kotak unggah bawaan Streamlit berbahasa Inggris: diganti lewat CSS. */
    [data-testid="stFileUploaderDropzoneInstructions"] div span:first-child {
        white-space: normal !important;
        overflow: visible !important;
        text-overflow: unset !important;
        font-size: 0 !important;
    }
    [data-testid="stFileUploaderDropzoneInstructions"] div span:first-child::after {
        content: "Tarik & lepas file ke sini";
        font-size: var(--fs-base);
    }
    [data-testid="stFileUploaderDropzone"] [data-testid="stBaseButton-secondary"] { font-size: 0 !important; }
    [data-testid="stFileUploaderDropzone"] [data-testid="stBaseButton-secondary"]::after {
        content: "Pilih file";
        font-size: var(--fs-sm);
    }
    .upload-note {
        font-size: var(--fs-sm);
        line-height: 1.4;
        white-space: normal;
        overflow: visible;
        margin: 0.15rem 0 0.8rem 0;
    }
    .chart-heading {
        display: block;
        width: 100%;
        box-sizing: border-box;
        font-size: var(--fs-lg);
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
        font-size: var(--fs-base);
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
        font-size: var(--fs-sm);
        line-height: 1;
    }
    .stock-delta {
        margin-top: 0.12rem;
        font-size: var(--fs-xs);
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
        font-size: var(--fs-xs);
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
        font-size: var(--fs-xs);
        line-height: 1.15;
        font-weight: 500;
        color: #64748b;
    }
    .sheet-scroll thead tr:nth-child(-n+2) th {
        height: 2.5rem;
        line-height: 1.4rem;
        box-sizing: border-box;
    }
    .sheet-scroll thead tr:nth-child(2) th {
        top: 2.5rem;
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
    .sheet-scroll.movement-sheet thead tr:nth-child(2) th { top: 2.5rem; }
    .sheet-scroll.movement-sheet thead tr.sheet-total th {
        top: 5rem;
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
        font-size: var(--fs-xs);
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
        font-size: var(--fs-sm) !important;
        line-height: 1.45 !important;
        color: #64748b !important;
        max-width: none;
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
        font-size: var(--fs-base);
        line-height: 1.4;
        color: #1e293b;
    }
    [data-testid="stWidgetLabel"] p,
    [data-testid="stWidgetLabel"] label {
        font-size: var(--fs-base) !important;
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
    .stButton > button[data-testid="stBaseButton-primary"],
    [data-testid="stFormSubmitButton"] > button[kind="primaryFormSubmit"],
    button[data-testid="stBaseButton-primaryFormSubmit"] {
        background: linear-gradient(135deg, #ff7348 0%, #ee4d2d 100%);
        border: none;
        color: #ffffff;
    }
    .stButton > button[kind="primary"]:hover,
    .stButton > button[data-testid="stBaseButton-primary"]:hover,
    button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
        background: linear-gradient(135deg, #ff8158 0%, #e24122 100%);
        color: #ffffff;
    }
    .stat-card { width: 100%; box-sizing: border-box; }
    .qty-board-head { margin: 0.2rem 0 0.8rem; }
    .qty-board-title {
        font-size: var(--fs-xl);
        font-weight: 800;
        letter-spacing: -0.03em;
        color: #0f172a;
        margin: 0 0 0.25rem;
    }
    .qty-board-copy { color: #64748b; font-size: var(--fs-base); line-height: 1.45; margin: 0; }
    .qty-line.extra { background: #eff6ff; border-radius: 8px; }
    .qty-track.stock-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; background: #fff7ed; border-radius: 8px; padding: 5px 6px; height: auto; min-height: 1.85rem; overflow: visible; }
    .qty-track.stock-row.dc { background: #f0f9ff; }
    .stock-chip.info { background: #dbeafe; color: #1e3a8a; }
    /* Tombol unduh Excel: hijau lembut, ikon unduh, sudut membulat (sama di semua halaman). */
    div[class*="-nav"][class*="st-key-"] button {
        min-height: 34px !important;
        height: 34px;
        padding: 0 .35rem !important;
        border-radius: 9px !important;
        font-size: .9rem;
    }
    div[class*="-nav"][class*="st-key-"] [data-testid="stHorizontalBlock"] {
        gap: .35rem !important;
        flex-wrap: nowrap !important;
    }
    [data-testid="stDownloadButton"] button {
        background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%) !important;
        color: #065f46 !important;
        border: 1px solid #6ee7b7 !important;
        border-radius: 10px !important;
        font-weight: 700 !important;
        padding: 0.45rem 1.05rem !important;
        box-shadow: 0 1px 2px rgba(6, 95, 70, 0.10);
        transition: background .15s ease, transform .15s ease, box-shadow .15s ease;
    }
    [data-testid="stDownloadButton"] button:hover {
        background: linear-gradient(135deg, #d1fae5 0%, #a7f3d0 100%) !important;
        border-color: #34d399 !important;
        color: #064e3b !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 10px rgba(6, 95, 70, 0.15);
    }
    [data-testid="stDownloadButton"] button p { font-weight: 700 !important; }
    /* Bilah tombol tabel (Muat lebih banyak · Tutup · Unduh Excel): sama tinggi, teks satu baris, lebar penuh kolom. */
    div[class*="st-key-"][class*="-actions"] button {
        min-height: 42px !important; width: 100% !important; border-radius: 10px !important;
        white-space: nowrap !important; padding-left: .8rem !important; padding-right: .8rem !important;
    }
    div[class*="st-key-"][class*="-actions"] button p { white-space: nowrap !important; overflow: hidden; text-overflow: ellipsis; }
    div[class*="st-key-dlbar-"] [data-testid="stDownloadButton"], div[class*="st-key-dlbar-"] [data-testid="stDownloadButton"] button { width: 100% !important; }
    div[class*="st-key-dlbar-"] button { min-height: 38px !important; border-radius: 10px !important; white-space: nowrap !important; padding: 0 .6rem !important; }
    div[class*="st-key-"][class*="-actions"] [data-testid="stDownloadButton"],
    div[class*="st-key-"][class*="-actions"] [data-testid="stButton"] { width: 100% !important; }
    /* Tulisan "Press Enter to submit form/apply" di kolom isian mengganggu saat mengetik: disembunyikan. */
    [data-testid="InputInstructions"] { display: none !important; }
    .stock-chip { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: var(--fs-xs); font-weight: 700; }
    .stock-chip.ok { background: #dcfce7; color: #166534; }
    .stock-chip.bad { background: #fee2e2; color: #991b1b; }
    .stock-chip.warn { background: #fef9c3; color: #854d0e; }
    .stock-chip.none { background: #f1f5f9; color: #475569; }
    .insight-table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); margin: 4px 0 8px; }
    .insight-table th, .insight-table td { border-bottom: 1px solid #e2e8f0; padding: 5px 8px; text-align: left; vertical-align: top; }
    .insight-table th { background: #f8fafc; font-weight: 700; color: #334155; }
    .movement-sheet .stock-col { background: #fff7ed; }
    .qty-legend {
        display: flex;
        justify-content: center;
        gap: 1.4rem;
        color: #334155;
        font-weight: 700;
        font-size: var(--fs-base);
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
    .qty-legend .up { background: #1d4ed8; }
    .qty-legend .down { background: #dc2626; }
    .qty-legend .flat { background: #64748b; }
    .qty-card { padding: 0.95rem 0.15rem 1.05rem; }
    .qty-id { text-align: left; margin-bottom: 0.45rem; }
    .qty-rank { font-weight: 800; color: #0f172a; font-size: var(--fs-base); }
    .qty-name { color: #1e293b; font-weight: 650; line-height: 1.4; margin-top: 0.12rem; overflow-wrap: anywhere; }
    .qty-var { color: #94a3b8; font-size: var(--fs-sm); margin-top: 0.08rem; }
    .qty-line { display: flex; align-items: center; gap: 0.7rem; margin-top: 0.42rem; }
    .qty-metric {
        width: 7.6rem;
        flex: 0 0 7.6rem;
        color: #0f172a;
        font-size: var(--fs-sm);
        font-weight: 800;
        line-height: 1.2;
    }
    .qty-metric small,
    .qty-base small {
        display: block;
        color: #94a3b8;
        font-size: var(--fs-xs);
        font-weight: 600;
        margin-top: 0.08rem;
    }
    .qty-head-row { margin-top: 0.1rem; }
    .qty-head-row .qty-metric,
    .qty-head-row .qty-base,
    .qty-head-row .qty-head-mid {
        color: #94a3b8;
        font-size: var(--fs-xs);
        font-weight: 800;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    .qty-head-row .qty-head-mid { flex: 1; text-align: center; }
    .qty-track {
        flex: 1;
        min-width: 0;
        min-height: 1.85rem;
        display: flex;
        background: #f1f5f9;
        border-radius: 8px;
        overflow: hidden;
    }
    .qty-fill {
        min-height: 1.85rem;
        min-width: 14.5rem;
        max-width: 100%;
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: flex-end;
        padding: 0.25rem 0.7rem;
        color: #ffffff;
        font-weight: 800;
        font-size: var(--fs-sm);
        line-height: 1.25;
        text-align: right;
        white-space: normal;
        overflow-wrap: anywhere;
        box-sizing: border-box;
    }
    .qty-fill.naik { background: #1d4ed8; }
    .qty-fill.turun { background: #dc2626; }
    .qty-fill.tetap { background: #64748b; }
    .qty-base {
        width: 6.2rem;
        flex: 0 0 6.2rem;
        text-align: right;
        color: #0f172a;
        font-weight: 800;
        font-size: var(--fs-base);
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
        font-size: var(--fs-sm);
    }
    .insight-head { border-radius: 16px; padding: 1.05rem 1.15rem 0.95rem; color: #ffffff; margin-bottom: 0.9rem; }
    .insight-head.up { background: #1d4ed8; }
    .insight-head.down { background: #dc2626; }
    .insight-head.flat { background: #334155; }
    .insight-kicker { font-size: var(--fs-xs); font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; opacity: 0.85; }
    .insight-title { font-size: var(--fs-xl); font-weight: 800; line-height: 1.35; margin-top: 0.3rem; }
    .insight-meta { margin-top: 0.25rem; font-size: var(--fs-sm); opacity: 0.9; }
    .insight-stat {
        border: 1px solid #bfdbfe;
        background: #eff6ff;
        border-radius: 14px;
        padding: 0.85rem 1rem;
        margin-bottom: 0.9rem;
    }
    .insight-head.down + .insight-stat { border-color: #fecaca; background: #fef2f2; }
    .insight-head.flat + .insight-stat { border-color: #e2e8f0; background: #f8fafc; }
    .insight-stat-label { color: #64748b; font-size: var(--fs-xs); font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; }
    .insight-stat-value { font-size: var(--fs-2xl); font-weight: 800; color: #1d4ed8; margin-top: 0.15rem; }
    .insight-head.down + .insight-stat .insight-stat-value { color: #dc2626; }
    .insight-head.flat + .insight-stat .insight-stat-value { color: #334155; }
    .insight-stat-value span { font-size: var(--fs-base); font-weight: 700; }
    .insight-stat-note { color: #475569; font-size: var(--fs-sm); line-height: 1.45; margin-top: 0.2rem; }
    .insight-section {
        font-size: var(--fs-xs);
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
        font-size: var(--fs-sm);
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
    .insight-note { color: #94a3b8; font-size: var(--fs-sm); line-height: 1.45; margin: 0.15rem 0 0; }
    .insight-reco {
        margin: 0;
        color: #0f172a;
        font-size: var(--fs-base);
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
        font-size: var(--fs-sm);
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
    /* Indikator memuat: muncul otomatis saat skrip berjalan > 0,6 detik (pindah menu, buka riwayat). */
    @keyframes mitra-load-in { from { opacity: 0; } to { opacity: 1; } }
    @keyframes mitra-load-bar { 0% { background-position: 0% 0; } 100% { background-position: 200% 0; } }
    .stApp[data-test-script-state="running"]::before {
        content: "";
        position: fixed; top: 0; left: 0; right: 0; height: 3px; z-index: 2000;
        background: linear-gradient(90deg, #ee4d2d, #f6a58f, #1b3da6, #ee4d2d);
        background-size: 200% 100%;
        opacity: 0;
        animation: mitra-load-in .2s ease .6s forwards, mitra-load-bar 1.2s linear infinite;
    }
    .stApp[data-test-script-state="running"]::after {
        content: "Memuat data…";
        position: fixed; bottom: 1.25rem; left: 50%; transform: translateX(-50%); z-index: 2000;
        background: #0f172a; color: #ffffff; padding: .45rem 1rem; border-radius: 999px;
        font-size: var(--fs-sm); box-shadow: 0 6px 18px rgba(15, 23, 42, .25);
        opacity: 0;
        animation: mitra-load-in .2s ease .6s forwards;
        pointer-events: none;
    }
    /* Cetak laporan (Laporan › Semua bagian › Cetak / Simpan PDF): tanpa header yang dipaku dan tombol. */
    @media print {
        #mitra-header-shield, [data-testid="stHeader"], [data-testid="stToolbar"], iframe { display: none !important; }
        [style*="position: fixed"] { position: static !important; }
        [data-testid="stMainBlockContainer"] { padding-top: 0 !important; }
        .stApp::before, .stApp::after { display: none !important; }
    }
    /* Judul kolom Riwayat analisa tetap terlihat saat daftar di-scroll. */
    /* Wadah ber-border punya padding atas ±1rem; tanpa offset negatif, baris yang di-scroll terlihat di celah
       di atas judul kolom. Judul ditarik ke tepi atas wadah dan diberi latar penuh agar menutupi baris di bawahnya. */
    .st-key-run-history > :first-child {
        position: sticky; top: -1.05rem; z-index: 5;
        margin-top: -1.05rem; padding-top: 1.05rem; padding-bottom: .45rem;
        background: #ffffff; border-bottom: 1px solid #e2e8f0;
        box-shadow: 0 6px 8px -8px rgba(15, 23, 42, .25);
    }
    /* Pop-up (menu akun, pilihan dropdown) selalu di atas header yang dipaku (z-index 40) dan pelindungnya. */
    div[data-baseweb="popover"],
    div[data-testid="stPopoverBody"] { z-index: 1000 !important; }
    /* Elemen <style> pertama di wadah halaman: tidak menambah jarak. */
    .st-key-page-root > [data-testid="stElementContainer"]:first-child { display: none !important; }
    [data-stale="true"],
    [data-stale="true"] * {
        opacity: 1 !important;
        transition: none !important;
        filter: none !important;
    }
    [data-testid="stDataFrame"] {
        border: 1px solid #e2e8f0;
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
        font-size: var(--fs-xl);
        font-weight: 700;
        color: #94a3b8;
    }
    .home-kicker {
        font-size: var(--fs-xs);
        font-weight: 700;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: #ee4d2d;
        margin-bottom: 0.45rem;
    }
    .home-title {
        font-size: var(--fs-display);
        font-weight: 800;
        letter-spacing: -0.035em;
        line-height: 1.12;
        color: #0f172a;
        margin: 0 0 0.7rem;
    }
    .explain { font-size: var(--fs-sm); color: #64748b; line-height: 1.5; margin: 0.15rem 0 0.6rem; }
    .explain .explain-title { font-weight: 700; color: #475569; margin-bottom: 0.15rem; }
    .explain ul { margin: 0; padding-left: 1.1rem; }
    .explain li { margin: 0.1rem 0; }
    .explain b { color: #334155; font-weight: 650; }
    .home-lead {
        max-width: none;
        font-size: var(--fs-lg);
        line-height: 1.7;
        color: #334155;
    }
    .home-section {
        font-size: var(--fs-xs);
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #64748b;
        margin: 0.2rem 0 0.55rem;
    }
    .journey-step {
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 10px 12px;
        background: #ffffff;
        min-height: 128px;
    }
    .journey-title { font-weight: 700; color: #0f172a; margin-bottom: 4px; }
    .journey-num {
        display: inline-block; width: 22px; height: 22px; line-height: 22px; text-align: center;
        border-radius: 999px; background: #0f172a; color: #ffffff; font-size: var(--fs-xs); margin-right: 2px;
    }
    .journey-line { font-size: var(--fs-sm); color: #475569; line-height: 1.5; }
    .feature-badge {
        display: inline-block;
        background: #fff1ec;
        color: #c2410c;
        border-radius: 999px;
        padding: 0.22rem 0.65rem;
        font-size: var(--fs-xs);
        font-weight: 700;
        letter-spacing: 0.03em;
        margin-bottom: 0.55rem;
    }
    .feature-title {
        display: block;
        width: 100%;
        box-sizing: border-box;
        font-size: var(--fs-xl);
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
        font-size: var(--fs-base);
        line-height: 1.6;
        max-width: none;
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
        font-size: var(--fs-xs);
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #64748b;
    }
    .feature-name {
        font-size: var(--fs-lg);
        font-weight: 800;
        letter-spacing: -0.02em;
        color: #0f172a;
        line-height: 1.2;
    }
    .block-container:has(.feature-bar) { padding-top: 4.8rem !important; }
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
    .st-key-hdr-beranda button {
        background: #0f172a !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 999px !important;
        min-height: 2.65rem;
        font-weight: 700;
        letter-spacing: 0.01em;
        box-shadow: 0 8px 18px rgba(15, 23, 42, 0.16);
    }
    .st-key-hdr-beranda button:hover {
        background: #1e293b !important;
        color: #ffffff !important;
        transform: translateY(-1px);
    }
    .st-key-hdr-account button {
        background: #ffffff !important;
        color: #0f172a !important;
        border: 1px solid #e2e8f0 !important;
        border-radius: 999px !important;
        min-height: 2.65rem;
        font-weight: 600;
        box-shadow: none;
    }
    .st-key-hdr-account button:hover { background: #f8fafc !important; border-color: #cbd5e1 !important; }
    .st-key-hdr-analisa button, .st-key-hdr-latih button, .st-key-hdr-setting button {
        background: #fff7f4 !important;
        color: #c2410c !important;
        border: 1px solid #fdba74 !important;
        border-radius: 999px !important;
        min-height: 2.65rem;
        font-weight: 700;
        box-shadow: none;
    }
    .st-key-hdr-analisa button:hover, .st-key-hdr-latih button:hover, .st-key-hdr-setting button:hover {
        background: #ffedd5 !important;
        color: #9a3412 !important;
        transform: translateY(-1px);
    }
    div[class*="st-key-hdr-"] button { padding-left: 0.55rem !important; padding-right: 0.55rem !important; }
    div[class*="st-key-hdr-"] button p { white-space: nowrap; }
    div[class*="st-key-menu-"] button, div[class*="st-key-rek-sub-btn-"] button, div[class*="st-key-setting-tab-"] button {
        padding-left: 0.4rem !important; padding-right: 0.4rem !important;
    }
    div[class*="st-key-menu-"] button p, div[class*="st-key-rek-sub-btn-"] button p, div[class*="st-key-setting-tab-"] button p {
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: var(--fs-sm);
    }
    div[data-testid="stHorizontalBlock"]:has(.period-name) {
        align-items: stretch !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.period-name) .stat-card,
    div[data-testid="stHorizontalBlock"]:has(.period-name) .stat-card:hover {
        transform: none;
        box-shadow: 0 8px 22px rgba(15, 23, 42, 0.04);
    }
    button:focus-visible, input:focus, textarea:focus,
    [data-baseweb="select"] > div:focus-within, [data-baseweb="input"]:focus-within {
        outline: 2px solid #3B6FE0 !important;
        outline-offset: 1px;
        border-color: #3B6FE0 !important;
        box-shadow: 0 0 0 3px rgba(59, 111, 224, 0.18) !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 20px !important;
        border-color: #e7e9f2 !important;
        background: #ffffff;
        box-shadow: 0 16px 40px rgba(15, 23, 42, 0.05);
        padding: 0.35rem 0.4rem 0.2rem;
    }
    [class*="st-key-mobile-"] { display: none !important; }
    .sku-card { border: 1px solid #e2e8f0; border-radius: 10px; background: #fff; padding: .6rem .75rem; margin-bottom: .5rem; }
    .sku-card .sku-title { font-weight: 650; color: #0f172a; line-height: 1.3; }
    .sku-card .sku-meta { font-size: var(--fs-sm); color: #64748b; margin: .15rem 0 .35rem; }
    .sku-card .sku-nums { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .25rem .75rem; font-size: var(--fs-sm); }
    .sku-card .sku-nums b { color: #0f172a; }
    @media (max-width: 767px) {
        [class*="st-key-mobile-"] { display: block !important; }
        [class*="st-key-desktop-"] { display: none !important; }
        [data-testid="stHorizontalBlock"]:has(.user-bar),
        [data-testid="stHorizontalBlock"]:has(.feature-bar),
        [data-testid="stElementContainer"]:has(.app-menu-label) + div { display: none !important; }
        .st-key-mobile-header { position: static !important; }
        .st-key-mobile-header [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; align-items: center; min-height: 56px; max-height: 56px; }
        .st-key-mobile-header [data-testid="stColumn"] { min-width: 0 !important; width: auto !important; flex: 1 1 auto !important; }
        .st-key-mobile-header img { height: 30px; }
        /* HP: tanpa ruang kosong besar di atas header (padding bawaan Streamlit 6rem). */
        [data-testid="stMainBlockContainer"] { padding-top: 0.75rem !important; }
        /* Riwayat analisa di HP: baris tetap mendatar dan bisa digeser, bukan ditumpuk per kolom. */
        .st-key-run-history { overflow-x: auto !important; }
        .st-key-run-history [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; min-width: 980px; }
        .st-key-run-history [data-testid="stColumn"] { min-width: 0 !important; }
    }
    </style>
"""


# Pengukur waktu per tahap (hanya super user, buka dengan ?debug=waktu) untuk mencari bagian yang lambat.
_T0 = time.perf_counter()
TIMINGS: list[tuple[str, float]] = []


def _tick(label: str) -> None:
    TIMINGS.append((label, time.perf_counter()))


def show_timings() -> None:
    # ?debug=waktu sekali saja: tanda disimpan di sesi karena URL ditulis ulang saat pindah halaman.
    if str(st.query_params.get("debug", "")) == "waktu":
        st.session_state["_debug-waktu"] = True
    if os.getenv("MITRA_TIMING") == "1":
        prev = _T0
        parts = []
        for label, stamp in TIMINGS:
            parts.append(f"{label}={stamp - prev:.2f}")
            prev = stamp
        print("TIMING " + " | ".join(parts) + f" | TOTAL={time.perf_counter() - _T0:.2f}", flush=True)
    if not st.session_state.get("_debug-waktu") or getattr(AUTH_USER, "role", "") != "super_user":
        return
    rows, last = [], _T0
    for label, stamp in TIMINGS:
        rows.append({"Tahap": label, "Detik": round(stamp - last, 2)})
        last = stamp
    rows.append({"Tahap": "TOTAL", "Detik": round(time.perf_counter() - _T0, 2)})
    with st.expander("Waktu proses (debug)", expanded=True):
        st.dataframe(pd.DataFrame(rows), hide_index=True)

AUTH_USER = login_gate()
if str(st.query_params.get("debug", "")) == "waktu":
    st.session_state["_debug-waktu"] = True
_tick("login")
# CSS dan sinkron file baru dikirim setelah login, supaya putaran "memeriksa sesi" tidak mengulang kerja ini.
st.markdown(_APP_CSS, unsafe_allow_html=True)
sync_file_vault()
get_features()

TOP_N = 50
METRIC_LABELS = {
    "qty": "QTY terjual",
    "sales": "Sales value",
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
    from src.core.periods import calendar_period, prediction_window

    start = today or date.today()
    start, end = prediction_window(period, start)
    name = PERIOD_SPECS[period].label if period == "bulan" else f"Sisa {calendar_period(period, start)[2]}"
    text = f"{name} · {format_id_date(start)} – {format_id_date(end)}"
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


TODAY_FACTOR = [1.0]  # pola hari ini (Pantauan harian), diisi sekali per jalan halaman analisa


def slice_forecast(pred_qty: float, pred_sales: float, safety: float, horizon_days: int, days: int, day_factor: float = 1.0) -> tuple[int, int, int]:
    """Bagian prediksi untuk sejumlah hari. QTY dibulatkan ke bawah ke unit utuh, sales = QTY × harga bersih;
    SS berbasis lead time, sama di semua periode. day_factor = pola hari untuk potongan 1 hari (hari ini)."""
    horizon = max(int(horizon_days), 1)
    span = max(int(days), 0)
    qty = int(whole_units(float(pred_qty) * span / horizon * (float(day_factor) if span == 1 else 1.0)))
    price = float(pred_sales) / float(pred_qty) if float(pred_qty) > 0 else 0.0
    sales = int(np.rint(qty * price))
    guard = int(np.ceil(max(float(safety), 0.0) - 1e-9)) if span else 0
    return qty, sales, max(qty + guard, 0)


def format_number(value: float, decimals: int = 0) -> str:
    return fmt_angka(value) if decimals == 0 else fmt_desimal(value, decimals)


def format_idr(value: float) -> str:
    return fmt_rupiah(value)


def format_qty(value: float) -> str:
    if value is None or pd.isna(value):
        return fmt_angka(None)
    number = float(value)
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


def _content_key(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _suffix(filename: str) -> str:
    return Path(str(filename)).suffix.lower()


@st.cache_data(show_spinner=False, max_entries=60, ttl=3600)
def _parse_transactions_cached(digest: str, suffix: str, _data: bytes) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Kunci cache = hash isi file (+ ekstensi untuk deteksi format), bukan nama file."""
    return load_shopee_report(_data, filename=f"upload{suffix}")


@st.cache_data(show_spinner=False, max_entries=60, ttl=3600)
def _parse_generic_cached(digest: str, suffix: str, source_key: str, _data: bytes) -> pd.DataFrame:
    return read_upload_file(_data, f"upload{suffix}", SOURCE_SPECS[source_key])


def parse_upload(file_bytes: bytes, filename: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    return _parse_transactions_cached(_content_key(file_bytes), _suffix(filename), file_bytes)


def parse_generic_upload(file_bytes: bytes, filename: str, source_key: str) -> pd.DataFrame:
    return _parse_generic_cached(_content_key(file_bytes), _suffix(filename), source_key, file_bytes)


@st.cache_data(show_spinner=False, max_entries=4)
def cached_consolidation(root: str, stamp: float) -> tuple[pd.DataFrame, dict]:
    """Ringkasan konsolidasi dihitung ulang hanya bila ada submit baru (registry berubah)."""
    del stamp
    return consolidation_summary(LocalDataStore(root))


@st.cache_resource(show_spinner=False, max_entries=2)
def cached_library_frames(
    keys: tuple[str, ...], stamp: tuple[float, ...]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Baca bulan tersimpan sekali. Stempel file membuat cache batal saat impor baru.

    Dibagi antar-sesi tanpa disalin (frame besar, dibaca setiap rerun): pemanggil tidak boleh mengubahnya di tempat.
    """
    del stamp
    source, _stored = load_months(list(keys))
    if source is None or source.empty:
        return pd.DataFrame(), pd.DataFrame()
    return source, clean_order_frame(source)


@st.cache_data(show_spinner=False, max_entries=4)  # Data & Ringkasan memakai kombinasi bulan berbeda
def cached_ledger(keys: tuple[str, ...], stamp: tuple[float, ...]) -> pd.DataFrame:
    del stamp
    source, _orders = load_months(list(keys))
    return ledger_from_raw(source)


@st.cache_data(show_spinner=False, max_entries=2)
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


def _size_text(size: int) -> str:
    return f"{int(size or 0) / 1024:,.1f} KB".replace(",", "X").replace(".", ",").replace("X", ".")


def parse_uploaded_files(files, spec, on_file=None) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    """Baca file satu per satu (cache per isi file). Hasil: pesanan bersih, data mentah gabungan, baris per file."""
    orders_parts: list[pd.DataFrame] = []
    frames: list[pd.DataFrame] = []
    rows: list[dict] = []
    several = len(files) > 1
    for index, item in enumerate(files, start=1):
        if on_file is not None:
            on_file(index, len(files), item.name)
        data = item.getvalue()
        if spec.key == "transactions":
            orders, frame = parse_upload(data, item.name)
            orders_parts.append(orders)
        else:
            frame = parse_generic_upload(data, item.name, spec.key)
        rows.append(
            {
                "Nama file": item.name,
                "Ukuran": _size_text(getattr(item, "size", 0) or len(data)),
                "Baris": int(len(frame)),
                "Periode": _file_period_text(frame, spec.key),
                "Status": validation_report(frame, spec)["status"],
            }
        )
        if several:
            frame = frame.copy()
            frame.insert(0, "Nama file", item.name)
        frames.append(frame)
    parsed = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    orders = pd.concat(orders_parts, ignore_index=True).drop_duplicates().reset_index(drop=True) if orders_parts else pd.DataFrame()
    return orders, parsed, rows


def _uploaded_size(files) -> int:
    return sum(int(getattr(item, "size", 0) or 0) for item in list(files or []))


def _source_status_map(store: LocalDataStore) -> dict[str, str]:
    summary = store.source_summaries()
    if summary.empty:
        return {spec.key: "Kosong" for spec in source_menu()}
    by_label = summary.set_index("Menu")["Status"].to_dict()
    return {spec.key: str(by_label.get(spec.label, "Kosong")) for spec in source_menu()}


TARGET_UPLOAD = "sales_target"
MARGIN_UPLOAD = "margin_item"
SPECIAL_UPLOADS = (TARGET_UPLOAD, MARGIN_UPLOAD)
STOCK_GROUP = ("Stok", ("stock", "stock_10062", "stock_10036"))
UPLOAD_GROUPS = (
    ("Penjualan", ("transactions", "performance")),
    ("Iklan", ("ads_overall", "ads_auto", "ads_group", "ads_search")),
    STOCK_GROUP,
    ("Produk", ("product_descriptions", "competitors")),
    ("Target & margin", (TARGET_UPLOAD, MARGIN_UPLOAD)),
)


def _source_updated_map(store: LocalDataStore) -> dict[str, str]:
    """Tanggal unggahan terakhir per menu (dd/mm/yyyy)."""
    summary = store.source_summaries()
    if summary.empty or "Diperbarui" not in summary.columns:
        return {}
    by_label = summary.set_index("Menu")["Diperbarui"].astype(str).str.slice(0, 10).to_dict()
    return {spec.key: by_label.get(spec.label, "") for spec in source_menu() if by_label.get(spec.label, "") not in ("", "-")}


def _file_period_text(frame: pd.DataFrame, source_key: str) -> str:
    spec = SOURCE_SPECS[source_key]
    mapping = find_columns(frame.columns, spec)
    for field in spec.date_fields:
        column = field if field in frame.columns else mapping.get(field)
        if column is None:
            continue
        dates = pd.to_datetime(frame[column], errors="coerce", dayfirst=True)
        if dates.notna().any():
            return f"{dates.min().date()} - {dates.max().date()}"
    return "-"


def _submit_upload(store, spec, files, parsed: pd.DataFrame, orders: pd.DataFrame):
    names = [getattr(item, "name", "Lampiran") for item in files]
    imported_keys: list[str] = []
    result = store.submit_source(spec.key, parsed, filenames=names)
    if spec.key == "transactions":
        imported_keys, _notes = store_upload(parsed, orders, names)
    return result, imported_keys


def _process_upload(store, spec, files) -> dict:
    """Dijalankan hanya saat tombol Simpan ditekan: baca per file dengan progress, validasi, lalu simpan (parquet + library)."""
    total = len(files)
    outcome: dict = {"level": "error", "message": "", "warning": "", "rows": [], "keys": []}
    with st.status(f"Memproses {total} file...", expanded=True) as status:
        bar = st.progress(0.0, text=f"Memproses 1 dari {total} file")

        def on_file(index: int, count: int, name: str) -> None:
            bar.progress((index - 1) / count, text=f"Memproses {index} dari {count} file · {name}")

        try:
            orders, parsed, rows = parse_uploaded_files(files, spec, on_file)
        except Exception as exc:  # noqa: BLE001 - file rusak ditampilkan, app tidak berhenti
            status.update(label="Gagal membaca file", state="error")
            outcome["message"] = f"File tidak bisa dibaca: {exc}"
            return outcome
        outcome["rows"] = rows
        report = validation_report(parsed, spec)
        if report["missing_required"]:
            outcome["warning"] = "Kolom wajib belum cocok: " + ", ".join(report["missing_required"])
        if report["status"] == "Cek kolom":
            status.update(label="File belum disimpan", state="error")
            outcome["message"] = "File belum disimpan karena kolom wajib belum cocok dengan menu ini."
            return outcome
        if spec.site_code:
            from src.core.dc_stock import site_codes_in

            codes = site_codes_in(canonicalize_frame(parsed, spec)[0])
            wrong = [code for code in codes if code != spec.site_code]
            if wrong:
                status.update(label="File belum disimpan", state="error")
                outcome["message"] = (
                    f"File ini berisi stok Site {', '.join(wrong)}, bukan Site {spec.site_code}. "
                    "Pilih menu upload yang sesuai dengan kode site pada file."
                )
                return outcome
            qty_column = find_columns(parsed.columns, spec).get("qty")
            if qty_column is not None and not pd.to_numeric(parsed[qty_column], errors="coerce").fillna(0).abs().gt(0).any():
                status.update(label="File belum disimpan", state="error")
                outcome["message"] = (
                    f"Semua stok di kolom '{qty_column}' bernilai 0, jadi file tidak disimpan agar stok DC tidak terbaca kosong. "
                    "Pakai laporan stok (kolom Quantity) atau Replenishment Calculation by Date (kolom Stock On Hand)."
                )
                return outcome
        bar.progress(1.0, text=f"{total} dari {total} file terbaca · menyimpan data latih...")
        try:
            result, keys = _submit_upload(store, spec, files, parsed, orders)
        except Exception as exc:  # noqa: BLE001 - malformed files should be surfaced
            status.update(label="Gagal menyimpan", state="error")
            outcome["message"] = str(exc)
            return outcome
        bar.progress(1.0, text="Menyalin data latih ke database permanen...")
        sync_file_vault()
        status.update(label=f"Selesai: {total} file diproses dan disimpan", state="complete", expanded=False)
    outcome.update(level="success", message=result.message, keys=list(keys))
    return outcome


def show_training_uploads(groups=UPLOAD_GROUPS) -> tuple[list[str], str | None]:
    """Upload menu data latih. Data transaksi juga disalin ke library lama agar analisis lama tetap jalan."""
    store = DATA_STORE
    imported_keys: list[str] = []
    load_error: str | None = None
    st.markdown(
        """
        <div class="home-section">LANGKAH 1 · UPLOAD DATA</div>
        <div class="feature-copy">
        <b>Transaksi</b> diunggah setiap hari dan boleh diunggah ulang kapan saja: pesanan yang sama diganti, bukan digandakan.
        <b>Data lain</b> (stok, iklan, produk, target) cukup diunggah bila berubah; data yang sudah tersimpan tetap dipakai.
        Pilih menu, unggah file, lalu tekan Simpan.
        </div>
        """,
        unsafe_allow_html=True,
    )
    show_vault_status()
    statuses = _source_status_map(store)
    updated = _source_updated_map(store)
    done = set(st.session_state.get("upload-done", set()))
    group_keys = {key for _group, keys in groups for key in keys}
    specs = [spec for spec in source_menu() if spec.key in group_keys]
    by_key = {spec.key: spec for spec in specs}

    def menu_label(spec) -> str:
        if spec == TARGET_UPLOAD:
            months = len(monthly_targets(get_features()))
            if not months:
                return "Target sales bulanan · Kosong"
            mark = "✓ Siap (baru disimpan)" if TARGET_UPLOAD in done else "tersimpan"
            return f"Target sales bulanan · {mark} · {months} bulan"
        if spec == MARGIN_UPLOAD:
            from src.ui.margin_data import load_margin

            md = load_margin(get_features())
            if not md.ready:
                return "File margin · Kosong"
            if MARGIN_UPLOAD in done:
                return f"File margin · ✓ Siap (baru disimpan) · periode {md.periode}"
            when = f" {md.uploaded_at:%d/%m/%Y}" if md.uploaded_at is not None and pd.notna(md.uploaded_at) else ""
            return f"File margin · tersimpan{when} · periode {md.periode}"
        status = statuses.get(spec.key, "Kosong")
        if status == "Siap" and spec.key in done:
            return f"{spec.label} · ✓ Siap (baru disimpan)"
        if status == "Siap":
            when = updated.get(spec.key)
            due = " · ⚠️ belum hari ini" if journey.upload_due(spec.key, _parse_day(when or ""), date.today()) else ""
            return (f"{spec.label} · tersimpan {when}" if when else f"{spec.label} · tersimpan") + due
        return f"{spec.label} · {status}"

    selected_key = st.session_state.get("upload-source", specs[0].key)
    if selected_key not in by_key and selected_key not in (set(SPECIAL_UPLOADS) & group_keys):
        selected_key = specs[0].key

    def pick(group: str) -> None:
        choice = st.session_state.get(f"upload-group-{group}")
        if choice:
            st.session_state["upload-source"] = choice
            for other, _keys in groups:
                if other != group:
                    st.session_state[f"upload-group-{other}"] = None

    left, right = st.columns([1.35, 3.1], gap="large")
    with left:
        st.markdown("<div class='side-section'>Menu upload</div>", unsafe_allow_html=True)
        for group, keys in groups:
            keys = [key for key in keys if key in by_key or key in SPECIAL_UPLOADS]
            if not keys:
                continue
            widget = f"upload-group-{group}"
            if widget not in st.session_state:
                st.session_state[widget] = selected_key if selected_key in keys else None
            st.radio(group, options=keys, format_func=lambda key: menu_label(by_key.get(key, key)), key=widget, on_change=pick, args=(group,))
        picked_key = st.session_state.get("upload-source", selected_key)
        if picked_key not in by_key and picked_key not in group_keys:
            picked_key = selected_key
        filled = sum(1 for status in statuses.values() if status == "Siap")
        st.caption(
            f"{filled} dari {len(specs)} menu berisi data. ✓ Siap = baru disimpan di sesi ini; "
            "tersimpan = tanggal unggahan terakhir; ⚠️ = transaksi belum diunggah hari ini."
        )
    with right:
        if picked_key == TARGET_UPLOAD:
            st.markdown("<div class='side-section'>Target sales bulanan</div>", unsafe_allow_html=True)
            show_target_uploader(get_features(), username=AUTH_USER.username, today=date.today(), title=False)
            return imported_keys, load_error
        if picked_key == MARGIN_UPLOAD:
            from src.ui.margin_data import upload_card

            st.markdown("<div class='side-section'>File margin</div>", unsafe_allow_html=True)
            upload_card(get_features(), username=AUTH_USER.username, may_edit=can(AUTH_USER.role, "ubah_data_latih"), require=require, key="upload-margin")
            return imported_keys, load_error
        selected_spec = by_key[picked_key]
        st.markdown(f"<div class='side-section'>{html.escape(selected_spec.label)}</div>", unsafe_allow_html=True)
        result_key = f"upload-result-{selected_spec.key}"
        with st.form(f"upload-form-{selected_spec.key}", clear_on_submit=True, border=False):
            uploaded = st.file_uploader(
                selected_spec.label,
                type=["csv", "xlsx", "xls"],
                accept_multiple_files=True,
                key=f"uploader-{selected_spec.key}",
                label_visibility="collapsed",
            )
            st.markdown(
                "<div class='upload-note'>Tipe file CSV, XLSX, atau XLS. Maksimal 50 lampiran, total 1 GB. "
                "File dibaca setelah tombol Simpan ditekan. Unggahan baru menambah data latih, tidak menghapus file lama.</div>",
                unsafe_allow_html=True,
            )
            submitted = st.form_submit_button("Simpan", type="primary")
        if submitted:
            files = list(uploaded or [])
            if not files:
                st.info("Tombol Simpan ditekan tanpa file baru. Data tersimpan yang sudah ada tetap dipakai.")
            elif len(files) > MAX_FILES:
                load_error = f"Maksimal {MAX_FILES} file. Yang dipilih {len(files)} file."
            elif _uploaded_size(files) > MAX_UPLOAD_BYTES:
                load_error = "Total ukuran file melebihi 1 GB."
            else:
                # Selama file diproses, sembunyikan sisa tampilan dari run sebelumnya agar halaman tidak tampil dobel.
                st.markdown("<style>[data-stale='true']{display:none !important;}</style>", unsafe_allow_html=True)
                outcome = _process_upload(store, selected_spec, files)
                st.session_state[result_key] = outcome
                if outcome["level"] == "success":
                    st.session_state["upload-imported-keys"] = outcome["keys"]
                    st.session_state["upload-done"] = set(st.session_state.get("upload-done", set())) | {selected_spec.key}
                    st.rerun()
                load_error = outcome["message"]
            if load_error and result_key not in st.session_state:
                st.error(load_error)
        imported_keys = list(st.session_state.pop("upload-imported-keys", []) or [])
        saved = st.session_state.get(result_key)
        if isinstance(saved, dict):
            if saved.get("level") == "success":
                st.success(saved.get("message", ""))
                if can(AUTH_USER.role, "jalankan_analisa"):
                    st.info("Data tersimpan. Lanjut ke **Langkah 3 · Jalankan analisa** di bawah agar hasil memakai data ini.")
            elif saved.get("message"):
                st.error(saved["message"])
            if saved.get("warning"):
                st.warning(saved["warning"])
            if saved.get("rows"):
                st.caption("File terakhir yang disimpan")
                show_table(pd.DataFrame(saved["rows"]))
        else:
            st.caption("Pilih file lalu klik Simpan. File dibaca dan disimpan setelah tombol Simpan ditekan.")
    return imported_keys, load_error


def show_training_summary() -> None:
    """Ringkasan data latih tersimpan dan hasil konsolidasi antar-sumber."""
    store = DATA_STORE
    stored_summary = store.source_summaries()
    with st.expander("Ringkasan data tersimpan", expanded=False):
        toggle_table(stored_summary, key="stored-summary")
    try:
        stamp = store.registry_path.stat().st_mtime if store.registry_path.exists() else 0.0
        with st.spinner("Menyusun ringkasan konsolidasi..."):
            consolidated, metrics = cached_consolidation(str(store.root), stamp)
        with st.expander("Ringkasan data terkonsolidasi", expanded=False):
            c1, c2, c3 = st.columns(3)
            show_metric(c1, "SKU transaksi cocok stok", f"{format_number(metrics['sku_transaksi_cocok_stok_pct'], 1)}%")
            show_metric(c2, "Produk iklan terpetakan", f"{format_number(metrics['produk_iklan_terpetakan_sku_pct'], 1)}%")
            show_metric(c3, "Snapshot stok", format_number(metrics["snapshot_stok"], 0))
        with st.expander("Rincian: kenapa angka kecocokan tidak 100%?", expanded=False):
            show_match_diagnostics(store, stamp)
    except Exception as exc:  # noqa: BLE001 - summary is informative, not blocking
        st.caption(f"Ringkasan konsolidasi belum tersedia: {exc}")


PAGE_STEP = 5


def toggle_table(frame: pd.DataFrame, *, key: str, step: int = PAGE_STEP) -> None:
    """Tabel 5 baris teratas; satu tombol untuk membuka semua baris dan menutupnya kembali."""
    if not isinstance(frame, pd.DataFrame):
        return
    batched_view(len(frame), key=key, render=lambda a, b: show_table(frame.iloc[a:b]))


def paged_table(frame: pd.DataFrame, *, key: str, filename: str, kinds: dict | None = None, step: int = PAGE_STEP) -> None:
    """Tabel bernomor urut, tampil bertahap (Muat lagi) + unduh Excel lengkap."""
    full = frame.reset_index(drop=True)
    full.insert(0, "No", range(1, len(full) + 1))
    batched_view(
        len(full),
        key=key,
        render=lambda a, b: show_table(full.iloc[a:b], kinds=kinds, max_height=10_000),
        download=lambda: download_excel(full, filename.replace("/", "-").replace(" ", "_"), key=f"{key}-xl"),
    )


@st.cache_data(show_spinner=False, max_entries=2)
def cached_match_diagnostics(root: str, stamp: float) -> dict:
    from src.core.consolidation import match_diagnostics

    return match_diagnostics(LocalDataStore(root), today=date.today())


def show_match_diagnostics(store, stamp: float) -> None:
    """Penjelasan tiga kartu konsolidasi dengan angka dari data tersimpan."""
    with st.spinner("Menghitung rincian kecocokan..."):
        diag = cached_match_diagnostics(str(store.root), stamp)
    tx = diag.get("tx")
    st.markdown("**1. SKU transaksi cocok stok**")
    if tx:
        miss = tx["sku_total"] - tx["sku_cocok"]
        explain(
            [
                ("Arti", "persentase SKU yang pernah terjual dan juga ada di Data stok Site 10037 (daftar produk Shopee)"),
                ("Hasil", f"{format_number(tx['sku_cocok'], 0)} dari {format_number(tx['sku_total'], 0)} SKU cocok; {format_number(miss, 0)} tidak"),
                ("Bobot penjualan", f"SKU yang cocok mewakili {format_number(tx['qty_cocok_pct'], 1)}% QTY dan {format_number(tx['sales_cocok_pct'], 1)}% Sales value"),
                ("Terakhir terjual (yang tidak cocok)", f"{format_number(tx['miss_30'], 0)} SKU ≤ 30 hari · {format_number(tx['miss_90'], 0)} SKU 31–90 hari · {format_number(tx['miss_lama'], 0)} SKU > 90 hari"),
                ("Masih ada di DC", f"{format_number(tx['miss_di_dc'], 0)} SKU ada di Site 10062/10036 → barang ada, listing Shopee hilang/diarsipkan/ganti SKU"),
                (f"{format_number(tx['baris_tanpa_sku'], 0)} baris transaksi tanpa SKU", "tidak dihitung") if tx["baris_tanpa_sku"] else None,
                ("Sebaliknya", f"{format_number(tx['stok_tanpa_transaksi'], 0)} dari {format_number(tx['sku_stok'], 0)} SKU di Data stok belum pernah terjual"),
            ]
        )
        lo, hi = diag.get("tx_period", (None, None))
        period_text = f"{fmt_date_short(lo)} – {fmt_date_short(hi)}" if lo is not None and pd.notna(lo) else "-"
        if not diag["tx_miss"].empty:
            st.markdown(f"**SKU transaksi yang tidak ada di Data stok** · QTY terjual & Sales value periode data transaksi {period_text}")
            miss_tx = diag["tx_miss"]
            t1, t2, t3, t4 = st.columns(4)
            card(t1, "SKU tidak ada di Data stok", format_number(len(miss_tx), 0))
            card(t2, "QTY terjual", format_number(miss_tx["QTY terjual"].sum(), 0), hint=period_text)
            card(t3, "Potensi sales hilang", format_idr(miss_tx["Sales value"].sum()), hint="Sales value SKU yang tidak lagi terdaftar di toko")
            dc_cols = [c for c in miss_tx.columns if c.startswith("Stok Site")]
            dc_ready = int((miss_tx[dc_cols].sum(axis=1) > 0).sum()) if dc_cols else 0
            card(t4, "Masih ada stok di DC", f"{format_number(dc_ready, 0)} SKU", hint="Site 10062 / 10036 · bisa didaftarkan ulang")
            paged_table(diag["tx_miss"], key="diag-tx", filename=f"sku_tidak_cocok_stok_{period_text}", kinds={"QTY terjual": "count", "Sales value": "money", "Stok Site 10062": "count", "Stok Site 10036": "count"})
    else:
        st.caption("Data transaksi atau Data stok Site 10037 belum ada.")
    ads = diag.get("ads")
    st.markdown("**2. Produk iklan terpetakan**")
    if ads:
        miss = ads["kode_total"] - ads["kode_cocok"]
        explain(
            [
                ("Arti", "persentase Kode Produk di laporan iklan yang bisa diterjemahkan ke SKU lewat Data stok Site 10037"),
                ("Hasil", f"{format_number(ads['kode_cocok'], 0)} dari {format_number(ads['kode_total'], 0)} kode ditemukan; {format_number(miss, 0)} tidak"),
                ("Bobot biaya", f"kode yang terpetakan mewakili {format_number(ads['biaya_cocok_pct'], 1)}% biaya iklan; yang tidak {format_idr(ads['biaya_miss'])}"),
                ("Penyebab umum", "produk yang diiklankan sudah dihapus/diarsipkan dari toko atau listing-nya diganti"),
                ("Baris tanpa Kode Produk", f"{format_number(ads['baris_tanpa_kode'], 0)} baris ringkasan pengaturan iklan (Otomatis, kepala grup) — rinciannya ada di laporan otomatis & grup") if ads["baris_tanpa_kode"] else None,
                ("Dampak", "biaya & omzet kode yang tidak terpetakan tidak masuk ROAS per SKU"),
            ]
        )
        lo, hi = diag.get("ads_period", (None, None))
        period_text = f"{fmt_date_short(lo)} – {fmt_date_short(hi)}" if lo is not None and pd.notna(lo) else "-"
        if not diag["ads_miss"].empty:
            st.markdown(f"**Kode produk iklan yang belum terpetakan** · biaya & omzet iklan periode laporan iklan {period_text} · urut omzet terbesar")
            miss_ads = diag["ads_miss"]
            a1, a2, a3, a4 = st.columns(4)
            card(a1, "Kode produk", format_number(len(miss_ads), 0))
            card(a2, "Biaya iklan", format_idr(miss_ads["Biaya iklan"].sum()), hint=period_text)
            card(a3, "Potensi omzet hilang", format_idr(miss_ads["Omzet iklan"].sum()), hint="Omzet iklan yang tidak masuk ROAS per SKU")
            spend = float(miss_ads["Biaya iklan"].sum())
            card(a4, "ROAS kode ini", format_number(miss_ads["Omzet iklan"].sum() / spend, 1) if spend > 0 else "–")
            paged_table(diag["ads_miss"], key="diag-ads", filename=f"iklan_belum_terpetakan_{period_text}", kinds={"Biaya iklan": "money", "Omzet iklan": "money"})
            st.caption("SKU (varian) dicari dari nama produk yang sama di Data transaksi; \"tidak ditemukan\" = produk belum pernah terjual dengan nama itu.")
    else:
        st.caption("Laporan iklan atau Data stok Site 10037 belum ada.")
    st.markdown("**3. Snapshot stok**")
    snaps = diag.get("snapshots")
    if snaps is not None and not snaps.empty:
        explain(
            [
                ("Snapshot", "satu kali Simpan Data stok Site 10037; stok tidak ditimpa, tiap unggahan jadi potret stok jam itu"),
                ("Nilai saat ini", f"{format_number(len(snaps), 0)} kali unggahan (dua kali di hari yang sama tetap dihitung dua)"),
                ("Dipakai untuk", "stok saat ini (snapshot terbaru) dan lama kosong (sejak kapan stok 0)"),
                ("Saran", "unggah rutin (harian/mingguan) agar lama kosong akurat"),
                "Stok Site 10062/10036 tidak dihitung di kartu ini.",
            ]
        )
        show_table(snaps, kinds={"Jumlah SKU": "count", "SKU stok 0": "count"})


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
            work = work.loc[~cancelled_status_mask(work["status"])].copy()
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
            <div class="home-title">Keputusan e&#8209;commerce,<br>dalam satu ruang kerja.</div>
            <div class="home-lead">
                Ruang kerja manajer e-commerce dan digital marketing, sekaligus artefak tesis
                Magister Teknik Informatika · Renxy Lichandy untuk Mitra10 · 2026.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    notice = st.session_state.pop("run-error", None)
    if notice:
        st.error(notice)
    status = analysis_status()
    st.markdown("<div class='home-section'>Pekerjaan hari ini</div>", unsafe_allow_html=True)
    show_daily_journey(status, where="home")
    st.markdown("<div class='home-section'>Status data</div>", unsafe_allow_html=True)
    show_data_status(status)
    with st.expander("Riwayat analisa (30 terakhir) — buka hasil lama untuk perbandingan", expanded=False):
        show_run_history()


SETTING_LABELS = {"qty": "QTY terjual", "sales": "Sales value"}
STATE_TONE = {
    journey.STATE_EMPTY: ("#475569", "#f1f5f9"),
    journey.STATE_NEW_DATA: ("#1d4ed8", "#dbeafe"),
    journey.STATE_CURRENT: ("#166534", "#dcfce7"),
    journey.STATE_WAITING: ("#92400e", "#fef3c7"),
}


def _run_keys_map() -> dict:
    return st.session_state.setdefault("_run-keys", {})


def daily_run_keys(latest=None) -> tuple[str, ...]:
    """Bulan untuk Jalankan analisa harian: rentang analisa terakhir diperpanjang sampai bulan tersimpan terbaru."""
    saved = [item["key"] for item in list_months()]
    previous = _run_keys_map().get(latest.id, ()) if latest is not None else ()
    if latest is not None and not previous:
        previous = tuple(st.session_state.get("active-library-keys") or ())
    return journey.next_run_keys(previous, saved)


def newest_order_day() -> date | None:
    """Tanggal pesanan terakhir di data transaksi tersimpan. Diingat per file bulan, jadi beranda tidak membaca ulang tiap klik."""
    dated = sorted(item["key"] for item in list_months() if str(item["key"])[:4].isdigit())
    if not dated:
        return None
    key = dated[-1]
    path = library_store.LIBRARY_DIR / f"{key}.pkl"
    file_stamp = path.stat().st_mtime if path.exists() else 0.0
    cached = st.session_state.get("_newest-order-day")
    if isinstance(cached, tuple) and cached[0] == (key, file_stamp):
        return cached[1]
    orders = _orders_from_library([key])[0]
    if orders.empty or "order_time" not in orders.columns:
        found = None
    else:
        stamp = pd.to_datetime(orders["order_time"], errors="coerce").max()
        found = None if pd.isna(stamp) else stamp.date()
    st.session_state["_newest-order-day"] = ((key, file_stamp), found)
    return found


def run_data_until(run_id: int | None) -> date | None:
    if run_id is None:
        return None
    try:
        info = get_features().read("run_info")
        match = info.loc[info["run_id"].astype(int) == int(run_id), "data_until"]
    except Exception:
        return None
    if match.empty or pd.isna(match.iloc[0]):
        return None
    return pd.Timestamp(match.iloc[0]).date()


def _opened_run_id() -> int | None:
    active = st.session_state.get("active-run")
    if "analysis" not in st.session_state or not isinstance(active, tuple) or not active:
        return None
    return int(active[0])


def analysis_status() -> dict:
    """Satu sumber status untuk Beranda, Upload data, dan halaman hasil."""
    today = date.today()
    latest = _latest_ready_run()
    keys = daily_run_keys(latest)
    changed = latest is not None and (not keys or current_data_hash(keys) != str(latest.data_hash or ""))
    run_day = None
    if latest is not None:
        try:
            run_day = datetime.fromisoformat(str(latest.run_at)).date()
        except ValueError:
            run_day = None
    return {
        "today": today,
        "latest": latest,
        "keys": keys,
        "state": journey.analysis_state(has_run=latest is not None, run_day=run_day, today=today, data_changed=changed),
        "data_until": newest_order_day(),
        "run_until": run_data_until(latest.id if latest is not None else None),
        "opened": _opened_run_id(),
        "updated": _source_updated_map(DATA_STORE),
    }


def _state_copy(status: dict) -> tuple[str, str]:
    latest = status["latest"]
    stamp = run_stamp_text(latest.run_at) if latest is not None else ""
    until = f" (transaksi s.d. {format_id_date(status['run_until'])})" if status.get("run_until") else ""
    state = status["state"]
    if state == journey.STATE_EMPTY:
        return "Belum ada analisa", "Upload data transaksi, lalu jalankan analisa pertama."
    if state == journey.STATE_NEW_DATA:
        return (
            "Ada data baru sejak analisa terakhir",
            f"Analisa {stamp}{until} belum memakai unggahan terbaru. Jalankan analisa agar prediksi, stok, dan iklan memakai data ini.",
        )
    if state == journey.STATE_CURRENT:
        return "Hasil analisa sudah terbaru", f"Analisa {stamp}{until} sudah memakai semua data yang tersimpan. Langsung lihat hasil."
    return (
        "Transaksi hari ini belum diunggah",
        f"Analisa terakhir {stamp}{until}. Upload transaksi terbaru lalu jalankan analisa. Selama belum ada data baru, hasil terakhir tetap dipakai.",
    )


def _step_html(number: int, title: str, lines: list[str], done: bool) -> str:
    mark = "<span style='color:#166534'>✓</span>" if done else f"<span class='journey-num'>{number}</span>"
    body = "".join(f"<div class='journey-line'>{line}</div>" for line in lines)
    return f"<div class='journey-step'><div class='journey-title'>{mark} {html.escape(title)}</div>{body}</div>"


def run_daily_analysis(status: dict) -> None:
    request_analysis_run(**{**last_run_settings(), "keys": status["keys"]})


def view_latest_result(status: dict) -> None:
    latest = status["latest"]
    if latest is not None and status["opened"] != latest.id:
        with st.spinner("Membuka hasil analisa terbaru…"):
            if not open_saved_run(latest.id):
                st.rerun()
    _go(PAGE_RESULT)


def show_daily_journey(status: dict, *, where: str) -> None:
    """Tiga langkah harian dengan satu tombol utama sesuai status data."""
    role = AUTH_USER.role
    may_upload = can(role, "ubah_data_latih")
    may_run = can(role, "jalankan_analisa")
    latest = status["latest"]
    action = journey.STATE_ACTION[status["state"]]
    if action == journey.ACTION_UPLOAD and not may_upload:
        action = journey.ACTION_RUN if may_run else journey.ACTION_VIEW
    if action == journey.ACTION_RUN and not may_run:
        action = journey.ACTION_VIEW
    with st.container(border=True):
        show_status_banner(status)
        today = status["today"]
        tx_updated = status["updated"].get("transactions", "")
        tx_today = not journey.upload_due("transactions", _parse_day(tx_updated), today)
        settings = last_run_settings()
        cols = st.columns(3, gap="medium")
        upload_lines = [
            f"Transaksi s.d. <b>{format_id_date(status['data_until'])}</b>" if status["data_until"] else "Belum ada transaksi tersimpan",
            f"Terakhir diunggah {tx_updated}" if tx_updated else "Belum pernah diunggah",
            "Stok, iklan, produk, target: unggah hanya bila berubah.",
        ]
        cols[0].markdown(_step_html(1, "Upload data", upload_lines, tx_today), unsafe_allow_html=True)
        months = len(status["keys"])
        run_lines = [
            f"{PERIOD_LABELS.get(settings['period'], settings['period'])} · {SETTING_LABELS.get(settings['metric'], settings['metric'])} · safety stock {settings['service']}%",
            f"{months} bulan data · batal & retur {'dikecualikan' if settings['exclude'] else 'ikut dihitung'}",
            "Setelan sama dengan analisa terakhir; ubah di Upload data › Setelan analisa.",
        ]
        cols[1].markdown(_step_html(2, "Jalankan analisa", run_lines, status["state"] == journey.STATE_CURRENT), unsafe_allow_html=True)
        if latest is not None:
            view_lines = [f"Analisa {run_stamp_text(latest.run_at)} oleh {html.escape(latest.run_by)}"]
            if status["run_until"]:
                view_lines.append(f"Memakai transaksi s.d. {format_id_date(status['run_until'])}")
            view_lines.append("Prediksi, stok, rekomendasi, laporan, evaluasi model.")
        else:
            view_lines = ["Belum ada hasil."]
        cols[2].markdown(_step_html(3, "Lihat hasil", view_lines, False), unsafe_allow_html=True)
        b1, b2, b3 = st.columns(3, gap="medium")
        if may_upload and where != "input" and b1.button("Upload data", key=f"jr-upload-{where}", type="primary" if action == journey.ACTION_UPLOAD else "secondary", use_container_width=True):
            _go(PAGE_INPUT)
        if may_run and b2.button("Jalankan analisa", key=f"jr-run-{where}", type="primary" if action == journey.ACTION_RUN else "secondary", use_container_width=True, disabled=not status["keys"]):
            run_daily_analysis(status)
            st.rerun()
        if latest is not None and b3.button("Lihat hasil analisa", key=f"jr-view-{where}", type="primary" if action == journey.ACTION_VIEW else "secondary", use_container_width=True):
            view_latest_result(status)
        show_duplicate_offer(where)


def _parse_day(text: str) -> date | None:
    try:
        return datetime.strptime(str(text)[:10], "%d/%m/%Y").date()
    except ValueError:
        return None


def show_data_status(status: dict) -> None:
    """Kapan tiap data terakhir diunggah dan apakah perlu diunggah lagi."""
    statuses = _source_status_map(DATA_STORE)
    updated = status["updated"]
    today = status["today"]
    labels = {spec.key: spec.label for spec in source_menu()}
    targets = monthly_targets(get_features())
    rows = []
    for group, keys in UPLOAD_GROUPS:
        for key in keys:
            if key == TARGET_UPLOAD:
                has_month = f"{today:%Y-%m}" in targets
                rows.append({"Kelompok": group, "Data": "Target sales bulanan", "Terakhir diunggah": f"{len(targets)} bulan tersimpan" if targets else "–", "Jadwal unggah": "Awal bulan", "Keterangan": "Target bulan ini ada" if has_month else "⚠️ Target bulan ini belum ada"})
                continue
            if key not in labels:
                continue
            when = updated.get(key, "")
            filled = statuses.get(key) == "Siap"
            due = journey.upload_due(key, _parse_day(when), today)
            note = "⚠️ Belum diunggah hari ini" if due else ("✓ Tersimpan" if filled else "Kosong")
            if key == "transactions" and status["data_until"]:
                note += f" · pesanan s.d. {fmt_date_short(status['data_until'])}"
            rows.append({"Kelompok": group, "Data": labels[key], "Terakhir diunggah": when or "–", "Jadwal unggah": journey.upload_rhythm(key), "Keterangan": note})
    show_table(pd.DataFrame(rows))
    st.caption("Transaksi bisa diunggah kapan saja dan setiap hari. Data lain tetap dipakai sampai diunggah ulang; unggah ulang hanya bila ada perubahan.")


@st.cache_resource(show_spinner=False)
def run_repository() -> RunRepository:
    repo = RunRepository(get_engine())
    repo.cleanup()
    guard_storage(repo)
    return repo


def guard_storage(repo: RunRepository) -> None:
    """Batas kapasitas database (config `penyimpanan`); gagal tidak menghentikan halaman."""
    try:
        report = enforce_storage(get_engine(), repo, current_params())
        st.session_state["_storage-report"] = report
    except Exception as exc:  # noqa: BLE001
        st.session_state["_storage-error"] = str(exc)


def current_data_hash(keys) -> str:
    """Sidik isi data latih (bulan terpilih) + data stok, di-cache per waktu ubah file."""
    keys = tuple(sorted(str(key) for key in keys))
    paths = [library_store.LIBRARY_DIR / f"{key}.pkl" for key in keys] + [DATA_STORE.registry_path]
    stamp = tuple(path.stat().st_mtime if path.exists() else 0.0 for path in paths)
    cached = st.session_state.get("_data-hash")
    if isinstance(cached, tuple) and cached[0] == (keys, stamp):
        return cached[1]
    value = training_data_hash(paths, extra="|".join(keys))
    st.session_state["_data-hash"] = ((keys, stamp), value)
    return value


def training_exclude() -> bool:
    """Setelan data latih "Kecualikan batal & retur" untuk analisa BARU: tersimpan di parameter pengguna,
    tidak ikut berubah saat membuka analisa lama atau menggeser saklar tampilan di halaman hasil."""
    saved = (current_params().get("analisa") or {}).get("kecualikan_batal_retur")
    if saved is not None:
        return bool(saved)
    latest = _latest_ready_run()
    return bool(latest.exclude_batal_retur) if latest is not None else False


def save_training_exclude(value: bool) -> None:
    params = load_params(USER_ROOT)
    section = dict(params.get("analisa") or {})
    if section.get("kecualikan_batal_retur") == bool(value):
        return
    section["kecualikan_batal_retur"] = bool(value)
    save_params({**params, "analisa": section}, USER_ROOT)


def last_run_settings() -> dict:
    """Setelan analisa sukses terakhir (bukan analisa lama yang sedang dibuka); bila belum ada, nilai bawaan."""
    latest = _latest_ready_run()
    if latest is None:
        period = "bulan"
        return {
            "period": period,
            "metric": "qty",
            "service": recommended_service_level(period, current_params()).pct,
            "keys": daily_run_keys(None),
            "exclude": training_exclude(),
        }
    return {
        "period": str(latest.periode),
        "metric": str(latest.parameter),
        "service": int(latest.safety_stock),
        "keys": daily_run_keys(latest),
        "exclude": bool(latest.exclude_batal_retur),
    }


def request_analysis_run(*, period: str, metric: str, service: int, keys, exclude: bool, training_months: int | None = None, service_recommended: int | None = None) -> None:
    """Tombol Jalankan analisa: tawarkan hasil tersimpan bila data & parameter sama sudah sukses hari ini."""
    require("data_latih", "edit")
    keys = tuple(keys)
    if not keys:
        st.session_state["active-feature"] = FEATURE_ID
        st.session_state["editing-input"] = True
        st.session_state["input-error"] = "Belum ada data latih. Unggah laporan atau pilih bulan lebih dulu."
        return
    st.session_state["saved-period"] = period
    st.session_state["saved-metric"] = metric
    st.session_state["saved-service"] = int(service)
    st.session_state["saved-source-key"] = "library:" + ",".join(keys)
    st.session_state["active-library-keys"] = keys
    # Analisa memakai setelan data latih yang diminta, bukan posisi saklar tampilan dari analisa yang terakhir dibuka.
    st.session_state["run-exclude"] = bool(exclude)
    st.session_state["analysis-config"] = {
        "training_months": len(keys) if training_months is None else training_months,
        "period": period,
        "service": int(service),
        "service_recommended": int(service if service_recommended is None else service_recommended),
        "metric": metric,
    }
    hashed = current_data_hash(keys)
    st.session_state["run-data-hash"] = hashed
    try:
        duplicate = run_repository().find_duplicate(
            data_hash=hashed, periode=period, parameter=metric, safety_stock=int(service), exclude=bool(exclude)
        )
    except Exception:
        duplicate = None
    if duplicate is not None:
        st.session_state["dup-run"] = {"id": duplicate.id, "run_at": duplicate.run_at, "run_by": duplicate.run_by}
        return
    start_analysis_run()


def start_analysis_run() -> None:
    st.session_state.pop("dup-run", None)
    st.session_state["active-feature"] = FEATURE_ID
    st.session_state["pending-run"] = True
    st.session_state["editing-input"] = False


def show_duplicate_offer(key: str) -> None:
    offer = st.session_state.get("dup-run")
    if not isinstance(offer, dict):
        return
    st.info(
        f"Data latih dan parameter yang sama sudah dianalisa hari ini ({run_stamp_text(offer['run_at'])} oleh "
        f"{offer['run_by']}). Buka hasil tersimpan agar tidak menunggu, atau analisa ulang."
    )
    open_col, again_col, cancel_col, _gap = st.columns([1.3, 1.1, 0.8, 2.8])
    if open_col.button("Buka hasil tersimpan", type="primary", key=f"dup-open-{key}", use_container_width=True):
        st.session_state.pop("dup-run", None)
        open_saved_run(int(offer["id"]))
        st.rerun()
    if again_col.button("Analisa ulang", key=f"dup-again-{key}", use_container_width=True):
        start_analysis_run()
        st.rerun()
    if cancel_col.button("Batal", key=f"dup-cancel-{key}", use_container_width=True):
        st.session_state.pop("dup-run", None)
        st.rerun()


def run_stamp_text(run_at: str) -> str:
    try:
        stamp = datetime.fromisoformat(str(run_at))
    except ValueError:
        return str(run_at)
    return f"{format_id_date(stamp.date())} {stamp:%H:%M}"


def open_saved_run(run_id: int, *, navigate: bool = True) -> bool:
    """Muat hasil analisa tersimpan ke session_state tanpa menghitung ulang."""
    try:
        record, result = run_repository().load(run_id)
    except Exception as exc:
        st.session_state["run-error"] = f"Hasil analisa #{run_id} tidak bisa dibuka: {exc}"
        return False
    result.pop("katalog", None)
    movement_cache = result.pop("movement_asof", None)
    st.session_state["movement-asof"] = dict(movement_cache) if isinstance(movement_cache, dict) else {}
    st.session_state["active-run"] = (record.id, tuple(st.session_state["movement-asof"]))
    keys = tuple(result.get("library_keys") or ())
    _run_keys_map()[record.id] = keys
    result["exclude_return_cancel"] = bool(result.get("exclude_return_cancel", record.exclude_batal_retur))
    st.session_state["analysis"] = result
    st.session_state["saved-period"] = str(result.get("period", record.periode))
    st.session_state["saved-metric"] = str(result.get("metric", record.parameter))
    st.session_state["saved-service"] = int(result.get("service", record.safety_stock))
    st.session_state["saved-source-key"] = str(result.get("source_key") or "library:" + ",".join(keys))
    st.session_state["active-library-keys"] = keys
    st.session_state["editing-input"] = False
    st.session_state["run-origin"] = {"id": record.id, "run_at": record.run_at, "run_by": record.run_by}
    if navigate:
        st.session_state["active-feature"] = FEATURE_ID
    return True


def save_analysis_run(analysis: dict, *, duration: float, window_start: date, window_end: date) -> None:
    keys = tuple(analysis.get("library_keys") or ())
    try:
        hashed = st.session_state.pop("run-data-hash", None) or current_data_hash(keys)
        repo = run_repository()
        record = repo.save(
            analysis,
            run_by=AUTH_USER.username,
            periode=str(analysis.get("period")),
            tgl_mulai=window_start,
            tgl_akhir=window_end,
            parameter=str(analysis.get("metric", "qty")),
            safety_stock=int(analysis.get("service", 0)),
            exclude=bool(analysis.get("exclude_return_cancel", False)),
            data_hash=hashed,
            duration=duration,
        )
        repo.cleanup()
        guard_storage(repo)
    except Exception as exc:
        st.session_state["run-error"] = f"Analisa selesai, tetapi belum tersimpan ke riwayat: {exc}"
        return
    sync_file_vault()
    _run_keys_map()[record.id] = keys
    st.session_state["_run-save-katalog"] = record.id
    st.session_state["active-run"] = (record.id, tuple())
    st.session_state.pop("run-origin", None)


def persist_run_caches() -> None:
    """Simpan hasil hitung pergerakan stok ke run aktif, supaya Buka berikutnya tidak menghitung ulang."""
    active = st.session_state.get("active-run")
    cache = st.session_state.get("movement-asof")
    if not isinstance(active, tuple) or not isinstance(cache, dict) or not cache:
        return
    run_id, saved_keys = active
    if tuple(cache) == tuple(saved_keys):
        return
    try:
        run_repository().save_blob(int(run_id), "movement_asof", dict(cache))
    except Exception:
        return
    st.session_state["active-run"] = (run_id, tuple(cache))


def _latest_ready_run():
    """Riwayat terbaru yang file hasilnya masih ada (untuk tombol Buka analisa terakhir)."""
    try:
        repo = run_repository()
        for record in repo.list_runs(limit=10):
            if repo.available(record):
                return record
    except Exception:
        return None
    return None


def run_daily_totals() -> dict[int, float]:
    """Total prediksi QTY per hari per analisa, dari prediction_snapshot (rata-rata per tanggal target)."""
    try:
        from sqlalchemy import func, select

        from src.core.feature_store import prediction_snapshot

        with get_features().engine.connect() as conn:
            rows = conn.execute(
                select(prediction_snapshot.c.run_id, func.sum(prediction_snapshot.c.pred_qty), func.count(func.distinct(prediction_snapshot.c.target_date))).group_by(prediction_snapshot.c.run_id)
            ).all()
        return {int(run): float(total) / max(int(days), 1) for run, total, days in rows if total is not None}
    except Exception:
        return {}


def show_run_history() -> None:
    try:
        runs = run_repository().list_runs(limit=30)
    except Exception as exc:
        st.warning(f"Riwayat analisa belum bisa dibaca: {exc}")
        return
    if not runs:
        st.caption("Belum ada riwayat. Klik Jalankan analisa untuk membuat yang pertama.")
        return
    can_delete = can(AUTH_USER.role, "hapus_riwayat")
    opened = (st.session_state.get("run-origin") or {}).get("id")
    repo = run_repository()
    try:
        info = get_features().read("run_info")
        data_until = {int(r): d for r, d in zip(info["run_id"], info["data_until"])}
    except Exception:
        data_until = {}
    totals = run_daily_totals()
    # Analisa dengan data, periode, parameter, SS, dan tanggal yang sama harus menghasilkan prediksi yang sama.
    groups: dict[tuple, set[int]] = {}
    for record in runs:
        if record.id in totals:
            key = (record.data_hash, record.periode, record.parameter, record.safety_stock, record.exclude_batal_retur, str(record.run_at)[:10])
            groups.setdefault(key, set()).add(float(totals[record.id]))
    widths = [1.5, 0.9, 0.8, 0.95, 0.5, 0.9, 0.75, 1.0, 0.75, 0.75] + ([0.75] if can_delete else [])
    headers = ["Tanggal & jam", "Oleh", "Periode", "Parameter", "SS", "Data s.d.", "Sidik data", "Prediksi/hari", "Status", ""] + ([""] if can_delete else [])
    with st.container(border=True, height=min(80 + 46 * len(runs), 520), key="run-history"):
        for column, title in zip(st.columns(widths), headers):
            column.markdown(f"<div class='field-hint'><b>{title}</b></div>", unsafe_allow_html=True)
        for record in runs:
            cells = st.columns(widths, vertical_alignment="center")
            mark = " · dibuka" if record.id == opened else ""
            cells[0].markdown(f"{run_stamp_text(record.run_at)}{mark}")
            cells[1].markdown(html.escape(record.run_by))
            cells[2].markdown(PERIOD_LABELS.get(record.periode, record.periode))
            cells[3].markdown(("QTY terjual" if record.parameter == "qty" else "Sales value") + (" · tanpa batal/retur" if record.exclude_batal_retur else ""))
            cells[4].markdown(f"{record.safety_stock}%")
            until = data_until.get(int(record.id))
            cells[5].markdown(fmt_date_short(until) if until else "<span style='color:#94a3b8'>tidak tercatat</span>", unsafe_allow_html=True)
            cells[6].markdown(f"<code>{html.escape(str(record.data_hash or '')[:6]) or '–'}</code>", unsafe_allow_html=True, help="6 karakter pertama sidik isi data latih. Sama = data latih identik.")
            total = totals.get(record.id)
            key = (record.data_hash, record.periode, record.parameter, record.safety_stock, record.exclude_batal_retur, str(record.run_at)[:10])
            values = groups.get(key, set())
            # Beda > 0,5% dianggap tidak konsisten (pembulatan kecil antar-versi diabaikan).
            differs = total is not None and len(values) > 1 and (max(values) - min(values)) > 0.005 * max(max(values), 1.0)
            cells[7].markdown(
                ("–" if total is None else f"{format_number(total, 0)} unit") + (" ⚠️" if differs else ""),
                help=("Total prediksi QTY per hari (semua SKU). " + ("Berbeda dengan analisa lain yang data, parameter, dan tanggalnya sama." if differs else "Analisa dengan sidik data, parameter, dan tanggal yang sama harus bernilai sama.")),
            )
            ready = repo.available(record)
            if ready:
                cells[8].markdown("✅ Sukses")
            elif record.status == "sukses":
                cells[8].markdown("⚠️ File hasil hilang", help="Server sempat restart/redeploy; file hasil di disk server terhapus.")
            else:
                cells[8].markdown(f"⚠️ {record.status.title()}")
            if cells[9].button("Buka", key=f"run-open-{record.id}", disabled=not ready, use_container_width=True):
                with st.spinner(f"Membuka hasil analisa {run_stamp_text(record.run_at)}…"):
                    opened_ok = open_saved_run(record.id)
                if opened_ok:
                    st.rerun()
            if can_delete and cells[10].button("Hapus", key=f"run-del-{record.id}", use_container_width=True):

                def _delete(run_id: int = record.id, stamp: str = run_stamp_text(record.run_at)) -> None:
                    require("riwayat_analisa", "edit")
                    repo.delete(run_id)
                    audit("hapus_riwayat", f"#{run_id} · {stamp}")
                    if run_id == opened:
                        st.session_state.pop("run-origin", None)

                confirm_action(
                    "Hapus riwayat analisa?",
                    f"Hasil analisa {run_stamp_text(record.run_at)} oleh {html.escape(record.run_by)} akan dihapus permanen.",
                    _delete,
                    confirm_label="Ya, hapus",
                )
    explain(
        [
            ("Buka", "memuat hasil tersimpan tanpa menghitung ulang"),
            ("Sidik data", "berubah setiap ada unggahan baru (transaksi, stok, iklan, DC)"),
            ("Prediksi/hari", "total prediksi QTY per hari semua SKU; analisa dengan sidik data, setelan, dan tanggal sama harus bernilai sama"),
            ("⚠️", "muncul bila analisa yang seharusnya sama berbeda lebih dari 0,5%"),
            f"Disimpan {storage_settings(current_params())['maks_riwayat_analisa']} analisa terbaru (maks. 90 hari); yang lebih lama dihapus otomatis agar database gratis tidak penuh.",
        ]
    )


def pin_app_header() -> None:
    """Kunci bar atas, menu, dan kartu tanggal ke layar. Sticky tidak menempel di Streamlit."""
    components.html(
        """
        <script>
        const parent = window.parent;
        const pin = () => {
          const doc = parent.document;
          const root = doc.querySelector('[data-testid="stMainBlockContainer"]');
          const bar = root ? root.querySelector('.feature-bar') : null;
          const main = doc.querySelector('[data-testid="stMain"]');
          const existing = doc.getElementById('mitra-header-shield');
          const unpin = (el) => {
            ['position', 'top', 'left', 'width', 'z-index', 'background', 'box-sizing', 'margin'].forEach((p) => el.style.removeProperty(p));
          };
          const previous = parent.__mitraPinned || [];
          if (!root || !bar || !main || parent.innerWidth < 768) {
            if (existing) existing.remove();
            previous.forEach(unpin);
            parent.__mitraPinned = [];
            if (root) root.style.removeProperty('padding-top');
            return;
          }
          const rowOf = (node) => {
            if (!node) return null;
            const block = node.closest('[data-testid="stHorizontalBlock"]');
            if (!block) return node.closest('[data-testid="stElementContainer"]');
            return block.closest('[data-testid="stLayoutWrapper"]') || block;
          };
          const menuLabel = root.querySelector('.app-menu-label');
          const menuHost = menuLabel ? menuLabel.closest('[data-testid="stElementContainer"]') : null;
          const menu = menuHost ? menuHost.nextElementSibling : null;
          // Hanya header + menu yang dipaku; kartu tanggal/periode ikut tergulung agar ruang baca lebih lega.
          // Cari di area halaman saja: isi pop-up akun (juga berkelas .user-bar) tidak boleh ikut dipaku.
          const pieces = [rowOf(root.querySelector('.user-bar')), rowOf(bar), menu].filter((el, index, list) => el && el.isConnected && list.indexOf(el) === index);
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
          previous.filter((el) => !pinned.has(el)).forEach(unpin);
          parent.__mitraPinned = pieces;
          Array.from(page.children).forEach((child) => {
            if (child.id === 'mitra-header-shield') return;
            if (pinned.has(child)) {
              child.style.setProperty('z-index', '40', 'important');
              return;
            }
            const holdsHeader = child.querySelector && child.querySelector('.user-bar, .feature-bar, .app-menu-label, .period-name');
            if (holdsHeader) {
              // Wadah isi halaman yang memuat menu tetap: tanpa z-index agar isinya tidak menimpa header.
              child.style.removeProperty('position');
              child.style.removeProperty('z-index');
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
            parent.__mitraHeaderPin();
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
          // Hanya memasang ulang observer bila Streamlit mengganti elemen stMain; tidak menghitung layout tiap detik.
          parent.setInterval(watch, 1500);
        }
        pin();
        </script>
        """,
        height=0,
        width=0,
    )


def _go(page: str) -> None:
    apply_route(st.session_state, (page, ""), allowed_sheets(AUTH_USER.role, APP_SHEETS))
    st.rerun()


def _mobile_header(logo: str, title: str, analysis: bool, training: bool, setting: bool) -> None:
    """Header HP (< 768 px): logo + popover "☰ Akun". Disembunyikan CSS di desktop."""
    with st.container(key="mobile-header"):
        left, right = st.columns([3, 1.4], vertical_alignment="center")
        left.markdown(
            f"<div style='display:flex;align-items:center;gap:.5rem'><img src='{logo}' alt='Mitra10' style='height:30px'>"
            f"<b style='font-size:var(--fs-base);color:#0f172a'>{html.escape(title)}</b></div>",
            unsafe_allow_html=True,
        )
        with right.popover("☰ Akun", use_container_width=True):
            st.markdown(f"👤 **{html.escape(AUTH_USER.username)}** · {role_label(AUTH_USER.role)}")
            if st.button("Beranda", key="m-beranda", use_container_width=True):
                _go(PAGE_HOME)
            if analysis and st.button("Hasil analisa", key="m-analisa", use_container_width=True):
                _go(PAGE_RESULT)
            if training and st.button("Upload data", key="m-latih", use_container_width=True):
                _go(PAGE_INPUT)
            if setting and st.button("Setting", key="m-setting", use_container_width=True):
                _go(PAGE_SETTING)
            if st.button("Ubah password", key="m-pwd", use_container_width=True):
                st.session_state[AUTH_PAGE_KEY] = "password"
                st.rerun()
            if can(AUTH_USER.role, "kelola_user") and st.button("Kelola user", key="m-users", use_container_width=True):
                st.session_state[AUTH_PAGE_KEY] = "users"
                st.rerun()
            if st.button("Keluar", key="m-logout", use_container_width=True):
                auth_logout()


def _has_saved_run() -> bool:
    """Ada analisa tersimpan (untuk tombol Hasil analisa di Beranda sebelum file hasilnya dibuka). Dicek ulang tiap 60 detik."""
    cached = st.session_state.get("_has-saved-run")
    if isinstance(cached, tuple) and time.time() - cached[0] < 60:
        return cached[1]
    found = _latest_ready_run() is not None
    st.session_state["_has-saved-run"] = (time.time(), found)
    return found


def render_header() -> None:
    """Header semua halaman setelah login (termasuk Kelola user & Ubah password): bar user, logo, judul, Beranda.

    Tata letak kolom selalu sama agar elemen header tidak bergeser antarhalaman.
    """
    pin_app_header()
    page = route_from_state(st.session_state, allowed_sheets(AUTH_USER.role, APP_SHEETS))[0]
    on_setting = page == PAGE_SETTING
    show_analysis_button = page != PAGE_RESULT and ("analysis" in st.session_state or _has_saved_run())
    show_training_button = page not in (PAGE_INPUT, PAGE_HOME) and not on_setting and (
        can(AUTH_USER.role, "ubah_data_latih") or can(AUTH_USER.role, "unggah_stok")
    )
    show_setting_button = not on_setting and bool(setting_tabs(AUTH_USER.role))
    mitra, shopee = _logo_uri("mitra10.png"), _logo_uri("shopee.svg")
    title = "Setting" if on_setting else {PAGE_HOME: "Beranda", PAGE_INPUT: "Upload data & setelan analisa", PAGE_USERS: "Kelola user", PAGE_PASSWORD: "Ubah password"}.get(page, "Hasil analisa")
    _mobile_header(mitra, title, show_analysis_button, show_training_button, show_setting_button)
    columns = st.columns([3.6, 1.7, 1.8, 1.35, 1.4, 1.45], vertical_alignment="center")
    columns[0].markdown(
        f"""
        <div class="feature-bar">
            <img src="{mitra}" alt="Mitra10">
            <img class="shopee-mark" src="{shopee}" alt="Shopee">
            <div>
                <div class="feature-kicker">Mitra10 × Shopee</div>
                <div class="feature-name">{title}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if show_analysis_button and columns[1].button("Hasil analisa", key="hdr-analisa", use_container_width=True):
        _go(PAGE_RESULT)
    if show_training_button and columns[2].button("Upload data", key="hdr-latih", use_container_width=True):
        _go(PAGE_INPUT)
    if show_setting_button and columns[3].button("Setting", key="hdr-setting", use_container_width=True):
        _go(PAGE_SETTING)
    if columns[4].button("Beranda", key="hdr-beranda", type="primary" if page == PAGE_HOME else "secondary", use_container_width=True):
        _go(PAGE_HOME)
    with columns[5].container(key="hdr-account"):
        account_menu(AUTH_USER)


def _checked_library_keys() -> list[str]:
    """Bulan tersimpan yang tersentuh rentang tanggal "Rentang data latih" (bulan tanpa tanggal selalu ikut)."""
    keys = sorted(item["key"] for item in list_months())
    saved = st.session_state.get("_keep::library-cal-range")
    if not (isinstance(saved, tuple) and len(saved) == 2):
        return keys
    touched = set(pd.period_range(saved[0], saved[1], freq="M").astype(str))
    return [k for k in keys if not k[:4].isdigit() or k in touched]


def _setting_fallback_table() -> pd.DataFrame:
    """SKU, nama produk, dan stok Site 10037 dari upload Data stok terakhir (untuk halaman Setting tanpa analisa)."""
    from src.core.decision_table import latest_stock_by_sku

    try:
        frame = store_frames().stock
    except Exception:
        return pd.DataFrame()
    if frame is None or frame.empty:
        return pd.DataFrame()
    stock = latest_stock_by_sku(frame)
    if stock.empty:
        return pd.DataFrame()
    names = frame.assign(sku=frame["sku"].fillna("").astype(str).str.strip().str.replace(r"^(\d+)\.0+$", r"\1", regex=True))
    names = names.drop_duplicates("sku", keep="last").set_index("sku")["product_name"] if "product_name" in names.columns else pd.Series(dtype=str)
    return stock.assign(product_name=stock["sku"].map(names).fillna(""), ada_data_stok=True)


def _sku_product_codes() -> dict[str, str]:
    """SKU → Kode Produk Shopee dari data stok terakhir (untuk mencocokkan file komisi affiliate)."""
    try:
        frame = store_frames().stock
    except Exception:
        return {}
    if frame is None or frame.empty or not {"sku", "product_code"} <= set(frame.columns):
        return {}
    sku = frame["sku"].fillna("").astype(str).str.strip().str.replace(r"^(\d+)\.0+$", r"\1", regex=True)
    code = frame["product_code"].fillna("").astype(str).str.strip()
    return {s: c for s, c in zip(sku, code) if s and c}


def _active_skus() -> tuple[set[str], str]:
    """SKU aktif = SKU pada unggahan data stok terakhir (daftar produk yang masih tayang di Shopee), memakai kunci tanpa nol depan."""
    try:
        frame = store_frames().stock
    except Exception:
        return set(), ""
    if frame is None or frame.empty or "sku" not in frame.columns:
        return set(), ""
    from src.core.margin_file import sku_key

    work = frame
    stamp = ""
    if "_submitted_at" in work.columns:
        stamp = str(work["_submitted_at"].astype(str).max())
        work = work.loc[work["_submitted_at"].astype(str).eq(stamp)]
    skus = {sku_key(s) for s in work["sku"].fillna("").astype(str) if str(s).strip()}
    return skus, stamp[:10]


def _with_ads(table: pd.DataFrame, orders: pd.DataFrame | None) -> pd.DataFrame:
    """Tambahkan biaya iklan, omzet iklan, dan QTY 30 hari terakhir per SKU dari data iklan yang diunggah."""
    try:
        from src.core.ads import attribute_ads

        frames = store_frames()
        if not frames.has_ads or orders is None or orders.empty:
            return table
        end = pd.to_datetime(orders["order_time"], errors="coerce").max().normalize()
        start = end - pd.Timedelta(days=29)
        per_sku = attribute_ads(frames.ads, frames.stock, orders=orders, start=start, end=end).per_sku
        stamp = pd.to_datetime(orders["order_time"], errors="coerce")
        recent = orders.loc[stamp >= start]
        if "status" in recent.columns:
            recent = recent.loc[~cancelled_status_mask(recent["status"])]
        qty = recent.assign(sku=recent["sku"].astype(str)).groupby("sku")["qty"].sum()
    except Exception:
        return table
    out = table.copy()
    keys = out["sku"].astype(str)
    if not per_sku.empty:
        ads = per_sku.assign(sku=per_sku["sku"].astype(str)).groupby("sku")[["biaya_iklan", "omzet_iklan"]].sum()
        out["biaya_iklan"] = keys.map(ads["biaya_iklan"]).fillna(0.0).to_numpy()
        out["omzet_iklan"] = keys.map(ads["omzet_iklan"]).fillna(0.0).to_numpy()
    out["qty_total"] = keys.map(qty).fillna(0.0).to_numpy()
    out["qty_sku"] = out["qty_total"]
    return out


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


def show_stock_uploads() -> None:
    """Upload data khusus menu Stok untuk role yang hanya boleh mengunggah stok (Team DC)."""
    require("upload_stok", "upload")
    with st.container(border=True):
        show_training_uploads(groups=(STOCK_GROUP,))


def show_prediction_inputs() -> None:
    """Halaman landasan prediksi. Terpisah dari hasil analisa."""
    require("data_latih", "edit")
    # Pesan bersyarat diletakkan di satu wadah tetap, supaya posisi kotak upload tidak bergeser
    # antar-rerun (pergeseran posisi membuat kotak upload lama tertinggal dan tampil dobel).
    with st.container():
        notice = st.session_state.pop("input-error", None)
        if notice:
            st.error(notice)
        status = analysis_status()
        show_status_banner(status)
    last = last_run_settings()

    upload_box = st.container(border=True)
    period_box = st.container(border=True)
    with upload_box:
        imported_keys, load_error = show_training_uploads()
        st.markdown("<div class='side-section'>Cek kualitas data tersimpan</div>", unsafe_allow_html=True)
        show_training_summary()
    orders_raw = pd.DataFrame()
    source_raw = pd.DataFrame()
    source_key = "empty"
    saved_months = list_months()
    selected_library: list[str] = []
    with period_box:
        st.markdown(
            """
            <div class="home-section">LANGKAH 2 · SETELAN ANALISA</div>
            <div class="feature-copy">Sudah terisi sama dengan analisa terakhir, ditambah bulan data terbaru. Untuk pemakaian
            harian tidak perlu diubah; ubah hanya bila ingin membandingkan (mis. untuk tesis).</div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("<div class='side-section'>Rentang data latih</div>", unsafe_allow_html=True)
        if saved_months:
            years = []
            for item in saved_months:
                year_name = year_of(item["key"])
                if year_name not in years:
                    years.append(year_name)
            years = sorted(years)
            today_ts = pd.Timestamp(date.today())

            def _library_label(key: str) -> str:
                label = month_label(key)
                if key != "tanpa-bulan":
                    start = pd.Period(key, freq="M").to_timestamp()
                    if start.year == today_ts.year and start.month == today_ts.month:
                        label = f"{label} (s.d. {today_ts.day} {ID_MONTHS[today_ts.month - 1]})"
                return label

            library_keys = sorted(item["key"] for item in saved_months)
            dated_keys = [k for k in library_keys if k[:4].isdigit()]
            undated_keys = [k for k in library_keys if not k[:4].isdigit()]
            if dated_keys:
                lib_lo = pd.Period(dated_keys[0], freq="M").start_time.date()
                lib_hi = min(pd.Period(dated_keys[-1], freq="M").end_time.date(), max(date.today(), lib_lo))
                last_dated = [k for k in last["keys"] if k[:4].isdigit()]
                default_lo = max(pd.Period(last_dated[0], freq="M").start_time.date(), lib_lo) if last_dated else lib_lo
                if imported_keys:
                    # Data baru diunggah: rentang analisa terakhir diperpanjang sampai bulan terbaru.
                    st.session_state["_keep::library-cal-range"] = (default_lo, lib_hi)
                lib_start, lib_end = date_range_picker(key="library-cal", lo=lib_lo, hi=lib_hi, default=(default_lo, lib_hi), label="Rentang data latih")
                touched = set(pd.period_range(lib_start, lib_end, freq="M").astype(str))
                selected_library = [k for k in dated_keys if k in touched] + undated_keys
                st.caption("Bulan yang tersentuh rentang tanggal dipakai utuh sebagai data latih: " + ", ".join(_library_label(k) for k in selected_library) + ".")
            else:
                selected_library = list(undated_keys)
            current_key = f"{today_ts.year:04d}-{today_ts.month:02d}"
            if current_key in selected_library:
                st.caption(f"{_library_label(current_key)}: bulan berjalan, data s.d. hari ini.")
            if selected_library:
                orders_raw, source_raw, source_key = _orders_from_library(selected_library)
            else:
                source_key = "library:none"
                st.warning("Pilih rentang tanggal yang memuat data tersimpan.")
        else:
            st.caption("Belum ada data tersimpan. Unggah laporan di langkah 1.")
        if "train-exclude" not in st.session_state:
            st.session_state["train-exclude"] = bool(last["exclude"])
        st.checkbox(
            "Kecualikan pesanan batal & unit retur",
            key="train-exclude",
            help="Aktif: model belajar dari permintaan bersih (batal & retur tidak dihitung). Berlaku untuk analisa yang dijalankan dari sini dan analisa harian berikutnya.",
        )
    if (
        isinstance(source_raw, pd.DataFrame)
        and not source_raw.empty
        and (not isinstance(orders_raw, pd.DataFrame) or orders_raw.empty)
    ):
        rebuilt = clean_order_frame(source_raw)
        if not rebuilt.empty:
            orders_raw = rebuilt

    params = current_params()
    training_months = len(selected_library)
    with period_box:
        st.markdown("<div class='side-section'>Periode prediksi</div>", unsafe_allow_html=True)
        period_choices = list(PERIOD_OPTIONS)
        if "forecast-period" not in st.session_state or st.session_state["forecast-period"] not in period_choices:
            st.session_state["forecast-period"] = last["period"] if last["period"] in period_choices else "bulan"
        if st.session_state.get("rank-metric") not in ("qty", "sales"):
            st.session_state["rank-metric"] = last["metric"] if last["metric"] in ("qty", "sales") else "qty"
        if hasattr(st, "segmented_control"):
            picked_period = st.segmented_control(
                "Periode prediksi",
                options=period_choices,
                format_func=lambda key: PERIOD_LABELS[key],
                key="forecast-period",
                label_visibility="collapsed",
            )
            period = picked_period or "bulan"
        else:
            period = st.radio(
                "Periode prediksi",
                options=period_choices,
                format_func=lambda key: PERIOD_LABELS[key],
                horizontal=True,
                key="forecast-period",
                label_visibility="collapsed",
            )
        if period in {"semester", "tahun"} and training_months < 12:
            st.warning(
                f"Data latih baru {training_months} bulan. Prediksi {PERIOD_LABELS[period]} butuh minimal 12 bulan "
                "agar pola musiman (mis. musim renovasi) ikut terbaca."
            )

        st.markdown("<div class='side-section'>Parameter</div>", unsafe_allow_html=True)
        sidebar_metric = st.radio(
            "Parameter",
            options=["qty", "sales"],
            format_func=lambda key: "QTY terjual" if key == "qty" else "Sales value",
            captions=[
                "Rank dan prediksi dibaca dari jumlah unit terjual. Cocok untuk keputusan stok.",
                "Rank dan prediksi dibaca dari nilai rupiah. Cocok untuk target omzet dan iklan.",
            ],
            horizontal=True,
            key="rank-metric",
            label_visibility="collapsed",
        )

        st.markdown("<div class='side-section'>Safety stock</div>", unsafe_allow_html=True)
        rec = recommended_service_level(
            period,
            params,
            orders_raw if isinstance(orders_raw, pd.DataFrame) else None,
            used_default=not any(
                changed_from_default(params, path)
                for path in ("margin.hpp_pct_harga", "gudang.biaya_kehabisan_pct", "gudang.biaya_simpan_pct_tahun")
            ),
        )
        service = int(
            st.number_input(
                "Safety stock (%)",
                min_value=0,
                max_value=500,
                value=int(last["service"]) if period == last["period"] else rec.pct,
                step=1,
                key=f"safety-stock-{period}",
            )
        )
        stored_analysis = st.session_state.get("analysis")
        safety_synced = bool(
            isinstance(stored_analysis, dict)
            and stored_analysis.get("period") == period
            and stored_analysis.get("source_key") == source_key
        )
        impact = None
        if safety_synced:
            impact = safety_impact(
                stored_analysis.get("stock"),
                stored_pct=float(stored_analysis.get("service", rec.pct)),
                rec_pct=rec.pct,
                new_pct=service,
                hpp_pct=float(params["margin"]["hpp_pct_harga"]),
            )
        st.markdown(safety_recommendation_html(rec, service, impact, period), unsafe_allow_html=True)

    exclude = bool(st.session_state.get("train-exclude", last["exclude"]))
    chosen = (period, sidebar_metric, int(service), tuple(selected_library), exclude)
    same_as_last = chosen == (last["period"], last["metric"], int(last["service"]), tuple(last["keys"]), bool(last["exclude"]))
    with st.container(border=True):
        st.markdown("<div class='home-section'>LANGKAH 3 · JALANKAN ANALISA</div>", unsafe_allow_html=True)
        summary_col, run_col = st.columns([3, 1.1], vertical_alignment="center")
        summary_col.markdown(
            "<div class='field-hint'>"
            f"<b>Data latih</b> {training_months} bulan · <b>Periode</b> {PERIOD_LABELS[period]} · "
            f"<b>Parameter</b> {SETTING_LABELS.get(sidebar_metric, sidebar_metric)} · <b>Safety stock</b> {service}% · "
            f"<b>Batal & retur</b> {'dikecualikan' if exclude else 'ikut dihitung'}<br>"
            + ("Setelan sama dengan analisa harian." if same_as_last else "<b style='color:#1d4ed8'>Setelan berbeda dari analisa terakhir</b>; analisa harian berikutnya akan mengikuti setelan ini.")
            + " Selesai dianalisa, hasilnya langsung dibuka dan menjadi analisa terakhir.</div>",
            unsafe_allow_html=True,
        )
        if run_col.button("Jalankan analisa", type="primary", use_container_width=True):
            if not isinstance(orders_raw, pd.DataFrame) or orders_raw.empty:
                st.session_state["input-error"] = "Pilih rentang data latih, atau unggah laporan, sebelum menjalankan analisa."
                st.rerun()
            save_training_exclude(exclude)
            request_analysis_run(
                period=period,
                metric=sidebar_metric,
                service=int(service),
                keys=tuple(selected_library),
                exclude=exclude,
                training_months=training_months,
                service_recommended=rec.pct,
            )
            st.session_state["saved-source-key"] = source_key
            st.rerun()
        show_duplicate_offer("input")
    st.stop()


def show_result_status(status: dict) -> None:
    """Baris status di atas hasil: analisa mana yang dibuka dan apakah sudah memakai data terbaru."""
    latest = status["latest"]
    opened = status["opened"]
    record = None
    if opened is not None:
        try:
            record = latest if latest is not None and latest.id == opened else run_repository().get(opened)
        except Exception:
            record = None
    if record is None:
        return
    stamp = run_stamp_text(record.run_at)
    until = run_data_until(record.id)
    line = f"Hasil analisa <b>{stamp}</b> oleh {html.escape(record.run_by)}" + (f" · transaksi s.d. {format_id_date(until)}" if until else "")
    older = latest is not None and record.id != latest.id
    if older:
        text_col, btn_col = st.columns([4, 1.2], vertical_alignment="center")
        text_col.markdown(
            f"<div style='border-left:4px solid #92400e;background:#fef3c7;padding:8px 12px;border-radius:8px'>"
            f"<b style='color:#92400e'>Anda membuka analisa lama</b> · {line}. Analisa terakhir {run_stamp_text(latest.run_at)}.</div>",
            unsafe_allow_html=True,
        )
        if btn_col.button("Buka analisa terakhir", key="rs-latest", type="primary", use_container_width=True):
            view_latest_result(status)
        return
    if status["state"] == journey.STATE_NEW_DATA:
        text_col, btn_col = st.columns([4, 1.2], vertical_alignment="center")
        text_col.markdown(
            f"<div style='border-left:4px solid #1d4ed8;background:#dbeafe;padding:8px 12px;border-radius:8px'>"
            f"<b style='color:#1d4ed8'>Ada data baru sejak analisa ini</b> · {line}. Jalankan analisa agar angka di bawah memakai unggahan terbaru.</div>",
            unsafe_allow_html=True,
        )
        if can(AUTH_USER.role, "jalankan_analisa") and btn_col.button("Jalankan analisa", key="rs-run", type="primary", use_container_width=True):
            run_daily_analysis(status)
            st.rerun()
        show_duplicate_offer("result")
        return
    badge_text = "terbaru" if status["state"] == journey.STATE_CURRENT else "terakhir · belum ada transaksi baru"
    st.markdown(
        f"<div class='field-hint' style='margin:2px 0 8px'>{line} · <span style='color:#166534;font-weight:700'>{badge_text}</span></div>",
        unsafe_allow_html=True,
    )


def show_status_banner(status: dict, *, compact: bool = False) -> None:
    title, body = _state_copy(status)
    tone, bg = STATE_TONE[status["state"]]
    st.markdown(
        f"<div style='border-left:4px solid {tone};background:{bg};padding:{'8px 12px' if compact else '10px 14px'};border-radius:8px;margin:4px 0 10px'>"
        f"<b style='color:{tone}'>{html.escape(title)}</b><br><span style='color:#0f172a;font-size:var(--fs-sm)'>{html.escape(body)}</span></div>",
        unsafe_allow_html=True,
    )


def safety_recommendation_html(rec, service: int, impact: dict | None, period: str) -> str:
    """Kotak saran safety stock: hijau sama, biru di atas, merah di bawah saran."""
    if service == rec.pct:
        tone, bg, word = "#166534", "#dcfce7", "sama dengan saran"
    elif service > rec.pct:
        tone, bg, word = "#1e40af", "#dbeafe", f"{service - rec.pct} poin di atas saran"
    else:
        tone, bg, word = "#991b1b", "#fee2e2", f"{rec.pct - service} poin di bawah saran"
    default_txt = f" <span style='color:#64748b;font-size:var(--fs-xs)'>· {DEFAULT_NOTE}</span>" if rec.used_default else ""
    basis = (
        f"Critical ratio {format_number(rec.critical_ratio * 100, 1)}% dari margin + biaya kehabisan vs biaya simpan "
        f"{PERIOD_LABELS[period].lower()}, disesuaikan porsi sales kelas A {format_number(rec.share_a * 100, 0)}% "
        f"dan kelas C {format_number(rec.share_c * 100, 0)}%."
    )
    lines = [f"<b>Saran safety stock {PERIOD_LABELS[period]}: {rec.pct}%</b>{default_txt}", basis, f"Pilihan {service}%: {word}."]
    if impact:
        sign = "+" if impact["units_delta"] >= 0 else "−"
        lines.append(
            f"Dampak pada {format_number(impact['items'])} SKU: SS {sign}{format_qty(abs(impact['units_delta']))} unit "
            f"({sign}{format_number(abs(impact['pct_delta']), 1)}%), nilai {sign}{format_idr(abs(impact['rp_delta']))}, "
            f"modal tertahan {sign}{format_idr(abs(impact['modal_delta']))}. "
            f"Risiko kehabisan per siklus ±{format_number(impact['risk_new'], 0)}% (saran ±{format_number(impact['risk_rec'], 0)}%)."
        )
    else:
        lines.append(f"Risiko kehabisan per siklus ±{format_number(max(100 - service, 0), 0)}%. Jalankan analisa untuk melihat dampak unit dan rupiah.")
    return (
        f"<div style='border-left:4px solid {tone};background:{bg};padding:10px 14px;border-radius:8px;color:#0f172a;font-size:var(--fs-sm);line-height:1.55'>"
        + "<br>".join(lines)
        + "</div>"
    )


def restore_prediction_context() -> tuple[pd.DataFrame, pd.DataFrame, str, str, str, int]:
    """Baca landasan yang terakhir dijalankan, tanpa menampilkan formulir."""
    period = str(st.session_state.get("saved-period", "bulan"))
    metric = str(st.session_state.get("saved-metric", "qty"))
    service = int(st.session_state.get("saved-service", recommended_service_level(period, current_params()).pct))
    keys = [str(key) for key in st.session_state.get("active-library-keys", tuple())]
    if not keys:
        keys = _checked_library_keys()
    orders, source, source_key = _orders_from_library(keys)
    if orders.empty:
        source_key = str(st.session_state.get("saved-source-key", source_key))
    return orders, source, source_key, period, metric, service


APP_SHEETS = (
    "Ringkasan",
    "Prediksi",
    "Data",
    "Folder data",
    "Rekomendasi",
    "Laporan",
    "Evaluasi model",
)
SUMMARY_SHEETS = {"Ringkasan", "Prediksi"}


def show_app_menu() -> str:
    """Menu fitur. Tombol yang sedang terbuka memakai warna utama."""
    current = st.session_state.get("active-sheet", "Ringkasan")
    sheets = allowed_sheets(AUTH_USER.role, APP_SHEETS)
    with st.container(key="mobile-menu"):
        pick = st.selectbox("Halaman", sheets, index=sheets.index(current) if current in sheets else 0, key=f"m-sheet-{current}")
        if current in sheets and pick != current:
            st.session_state["active-sheet"] = pick
            st.session_state["_menu_rerun"] = True
    st.markdown("<div class='app-menu-label'></div>", unsafe_allow_html=True)
    columns = st.columns(len(sheets))
    for column, name in zip(columns, sheets):
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
    """Kiri SKU, tengah Produk, kanan Varian."""
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
            wrap_label(f"Produk {name_text}", width=width, max_lines=max_lines),
            wrap_label(f"Varian {variance_text}", width=width, max_lines=2),
        ]
    )


def product_identity(rank, sku, name: str, variation: str = "") -> str:
    """Nama lengkap satu baris: SKU, Produk, lalu Varian."""
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
        signed = _signed_pct(abs(percent)) if percent is not None else ""
    elif direction == "turun":
        mark = "▼"
        signed = _signed_pct(-abs(percent)) if percent is not None else ""
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


def _last_month_sold(orders: pd.DataFrame | None, as_of: date) -> tuple[str, dict[str, int], dict[str, float]] | None:
    """QTY dan sales per SKU pada bulan penuh terakhir (dasar sama dengan Ringkasan total Top 50)."""
    if not isinstance(orders, pd.DataFrame) or orders.empty or "order_time" not in orders.columns:
        return None
    stamps = pd.to_datetime(orders["order_time"], errors="coerce").dt.normalize()
    full = stamps[stamps < pd.Timestamp(as_of)]
    if full.notna().sum() == 0:
        return None
    lo, hi = last_full_month(full.max().date())
    if pd.Timestamp(lo) < stamps.min():
        return None
    part = orders.loc[stamps.ge(pd.Timestamp(lo)) & stamps.le(pd.Timestamp(hi))]
    keys = part["item_key"].astype(str)
    qty = part.groupby(keys)["qty"].sum()
    sales = part.groupby(keys)["sales"].sum() if "sales" in part.columns else pd.Series(dtype=float)
    return (
        format_period_label("aktual_bulan", lo),
        {key: int(round(float(value))) for key, value in qty.items()},
        {key: float(value) for key, value in sales.items()},
    )


PCT_DISPLAY_CAP = 999.0


def _signed_pct(value: float, decimals: int = 1) -> str:
    """Persen bertanda, 1 desimal; di atas ±999% ditulis "> +999%" (angka dasar terlalu kecil untuk dibaca sebagai %)."""
    sign = "+" if value > 0 else "−" if value < 0 else ""
    if abs(value) > PCT_DISPLAY_CAP:
        return f"> {sign}{format_number(PCT_DISPLAY_CAP, 0)}%"
    return f"{sign}{format_number(abs(value), min(decimals, 1))}%"


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
    *,
    money: bool = False,
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
            "text": f"Prediksi {format_idr(predicted) if money else format_qty(predicted)}",
            "width": 100.0,
            "sold": "–",
            "sold_sub": "belum ada di laporan",
        }
    sold = int(sold)
    direction, _text, _gap, percent = _qty_pill(predicted, sold)
    value = format_idr(predicted) if money else format_qty(predicted)
    # Teks dibaca: "▲ Prediksi 1.169 · 5,7% di atas terjual" (bukan angka + persen saja).
    if direction == "tetap":
        text = f"– Prediksi {value} · sama dengan terjual"
    elif percent is None:
        text = f"{'▲' if direction == 'naik' else '▼'} Prediksi {value} · terjual 0"
    else:
        where = "di atas" if direction == "naik" else "di bawah"
        text = f"{'▲' if direction == 'naik' else '▼'} Prediksi {value} · {format_number(abs(percent), 1)}% {where} terjual"
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


def active_forecast_model() -> str:
    """Nama model prediksi yang dipakai hasil analisa aktif (pilihan WAPE luar sampel); tanpa bobot = Level terkini."""
    analysis = st.session_state.get("analysis") or {}
    weights = analysis.get("ensemble_weights") if isinstance(analysis, dict) else None
    if not weights:
        return "Level terkini"
    from src.models.evaluate import SEGMENT_KEY

    members = [k for k, v in weights.items() if not str(k).startswith("_") and v]
    if len(members) == 1 and not weights.get("_koreksi_bias") and not weights.get(SEGMENT_KEY):
        return members[0]
    return "Ensemble per segmen" if weights.get(SEGMENT_KEY) else "Ensemble"


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
    month_actual: int | None = None,
    month_actual_label: str | None = None,
) -> dict:
    """Analisa satu SKU. Bagian terjual dari laporan, bagian prediksi dari hasil analisa yang dikunci. Prediksi tidak dihitung ulang."""
    today = today or date.today()
    yesterday = today - timedelta(days=1)
    month_ago = _same_day_last_month(today)
    m_name = _short_id_date(month_ago)
    month_label = month_year(today)
    key = str(row["item_key"])
    actual = int(round(float(row["qty_total"])))
    sold_value = float(row["sales_total"]) if "sales_total" in row.index and pd.notna(row["sales_total"]) else 0.0
    predicted = int(whole_units(float(row["pred_qty"])))
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
            else int(slice_forecast(predicted, 0, 0, horizon, 1, TODAY_FACTOR[0] if today == date.today() else 1.0)[0])
        )
    today_qty = int(today_qty)
    # Prediksi 30 hari dibandingkan bulan penuh terakhir, bukan dengan saringan periode laporan yang panjangnya bisa beda.
    compare = actual if month_actual is None else int(month_actual)
    compare_label = resume_label if month_actual is None else str(month_actual_label or "bulan penuh terakhir")
    direction, pill, gap, percent = _qty_pill(month_pred, compare)
    day_read = _forecast_read(yesterday_pred, yesterday_sold)
    ago_read = _forecast_read(month_ago_pred, month_ago_sold)
    safety = int(np.ceil(float(row["safety_stock"]) - 1e-9)) if "safety_stock" in row and pd.notna(row["safety_stock"]) else 0
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

    # Bagian 2: yang diprediksi. Angka hasil analisa (Ensemble atau Level terkini) yang sudah dikunci.
    pred_lines: list[str] = []
    month_pred_line = f"Prediksi {month_label}: {format_qty(month_pred)} unit"
    if month_sales > 0:
        month_pred_line += f", sales {format_idr(month_sales)}"
    month_pred_line += "."
    if compare > 0 and gap != 0:
        month_pred_line += (
            f" Itu {format_qty(abs(gap))} unit {'di atas' if gap > 0 else 'di bawah'} yang terjual pada {compare_label} "
            f"({_signed_pct(percent or 0, 2)})."
        )
    elif compare > 0:
        month_pred_line += f" Sama dengan yang terjual pada {compare_label}."
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

    model_label = active_forecast_model()
    footnote = f"Bagian terjual dibaca dari laporan transaksi. Bagian prediksi memakai {model_label} yang sudah dikunci, tidak dihitung ulang."
    titles = {
        "naik": "Prediksi bulan di atas terjual",
        "turun": "Prediksi bulan di bawah terjual",
        "tetap": "Prediksi bulan sama dengan terjual",
    }
    window_end = today + timedelta(days=window_days("bulan", today) - 1)
    bars = [
        _bar_spec(
            format_period_label("prediksi", today),
            f"{_short_id_date(today)} – {_short_id_date(window_end)}",
            month_pred,
            compare,
            compare_label if month_actual is not None else "terjual",
        ),
        _bar_spec(format_period_label("aktual_hari", yesterday), "prediksi vs terjual", yesterday_pred, yesterday_sold, "terjual"),
        _bar_spec("Tanggal sama bulan lalu", m_name, month_ago_pred, month_ago_sold, "terjual"),
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
        "actual": compare,
        "compare_label": compare_label,
        "kicker": titles[direction],
        "factors": factors,
        "sold_lines": sold_lines,
        "pred_lines": pred_lines,
        "recommendation": recommendation,
        "steps": steps,
        "footnote": footnote,
        "model_label": model_label,
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
        f"<div class='insight-meta'>SKU {sku} · Varian: {variance}</div>"
        "</div>"
        "<div class='insight-stat'>"
        f"<div class='insight-stat-label'>Prediksi {html.escape(brief['month_label'])} dibanding terjual</div>"
        f"<div class='insight-stat-value'>{value}</div>"
        f"<div class='insight-stat-note'>Prediksi {html.escape(format_qty(brief['month_pred']))} unit. "
        f"Terjual {html.escape(format_qty(brief['actual']))} unit pada {html.escape(brief.get('compare_label', brief['resume_label']))}.</div>"
        "</div>"
        f"<div class='insight-chips'>{chips}</div>"
        "<div class='insight-section'>Yang sudah terjual (laporan)</div>"
        f"{sold}"
        f"<div class='insight-section'>Yang diprediksi ({html.escape(brief.get('model_label', active_forecast_model()))})</div>"
        f"{pred}"
        f"<p class='insight-note'>{html.escape(brief['footnote'])}</p>"
        "<div class='insight-section'>Keputusan</div>"
        f"<p class='insight-reco'>{html.escape(brief['recommendation'])}</p>"
        "<div class='insight-section'>Langkah kerja, urutan prioritas</div>"
        f"<ol class='insight-steps'>{steps}</ol>"
    )


def _stock_chip_row(row: pd.Series | None, period: str, today: date) -> str:
    """Baris Stok Site 10037 paling bawah: chip per periode, hijau aman, merah kurang (jumlah & %)."""
    if row is None:
        return ""
    if not bool(row.get("ada_data_stok", False)):
        chips = "<span class='stock-chip none'>Belum ada data stok</span>"
        stock_text = "–"
    else:
        stock_text = format_qty(float(row["stok"]))
        parts = []
        for group in period_groups(period, today):
            p = group.prefix
            gap = float(row[f"{p}_selisih"])
            pct = float(row[f"{p}_pct"]) * 100
            status = str(row.get(f"{p}_status") or ("Aman" if gap >= 0 else "Kurang"))
            base, _, suffix = status.partition(" · ")
            tone = "ok" if gap >= 0 else ("bad" if base == "Kosong" else "warn")
            if gap >= 0:
                word = status
            elif base == "Kosong":
                word = f"Kosong · butuh {format_qty(float(row[f'{p}_butuh']))} unit"
            else:
                word = f"{base} {format_qty(-gap)} unit ({format_number(abs(pct), 0)}%)" + (f" · {suffix}" if suffix else "")
            parts.append(f"<span class='stock-chip {tone}'>{html.escape(group.label)}: {word}</span>")
        chips = "".join(parts)
    return (
        "<div class='qty-line'>"
        "<div class='qty-metric'>Stok Site 10037<small>data stok terakhir</small></div>"
        f"<div class='qty-track stock-row'>{chips}</div>"
        f"<div class='qty-base'>{stock_text}<small>unit</small></div>"
        "</div>"
        + _dc_chip_row(row)
    )


def _dc_chip_row(row: pd.Series | None) -> str:
    """Baris Stok DC: Site 10062 (DC Cikupa) dan Site 10036 (DC Cipeucang) + rencana ambil bila Site 10037 kurang."""
    if row is None:
        return ""
    chips, total, known = [], 0.0, False
    for code, name in (("10062", "DC Cikupa"), ("10036", "DC Cipeucang")):
        value = row.get(f"stok_{code}")
        if value is None or pd.isna(value):
            chips.append(f"<span class='stock-chip none'>Site {code} · {name}: belum ada data</span>")
            continue
        known = True
        value = float(value)
        total += value
        tone = "ok" if value > 0 else "none"
        chips.append(f"<span class='stock-chip {tone}'>Site {code} · {name}: {format_qty(value)} unit</span>")
    plan = str(row.get("sumber_restock") or "").strip()
    if plan:
        tone = "bad" if "PO" in plan and not plan.startswith("Ambil") else ("warn" if "PO" in plan else "info")
        chips.append(f"<span class='stock-chip {tone}'>Rencana: {html.escape(plan)}</span>")
    return (
        "<div class='qty-line'>"
        "<div class='qty-metric'>Stok DC<small>Site 10062 · 10036</small></div>"
        f"<div class='qty-track stock-row dc'>{''.join(chips)}</div>"
        f"<div class='qty-base'>{format_qty(total) if known else '–'}<small>unit di DC</small></div>"
        "</div>"
    )


def _sales_bars(brief: dict, row: pd.Series, item_orders: pd.DataFrame | None, today: date) -> list[dict]:
    """Versi Rupiah dari batang QTY untuk parameter Sales value (prediksi × harga bersih 4 minggu)."""
    price = float(row.get("harga_bersih", 0) or 0)
    yesterday = today - timedelta(days=1)
    month_ago = _same_day_last_month(today)
    sold_sales = [None, None, None]
    if isinstance(item_orders, pd.DataFrame) and not item_orders.empty:
        days = pd.to_datetime(item_orders["order_time"]).dt.date
        sold_sales = [
            float(brief.get("month_actual_sales", row.get("sales_total", 0)) or 0),
            float(item_orders.loc[days == yesterday, "sales"].sum()),
            float(item_orders.loc[days == month_ago, "sales"].sum()),
        ]
    out = []
    for bar, pred_qty, sold in zip(brief["bars"], (brief.get("month_pred"), brief.get("yesterday_pred"), brief.get("month_ago_pred")), sold_sales):
        pred = None if pred_qty is None else int(round(float(pred_qty) * price))
        spec = _bar_spec(bar["label"], bar["sub"], pred, None if sold is None else int(round(sold)), bar.get("sold_sub") or "terjual", money=True)
        spec["sold"] = "–" if sold is None else format_idr(sold)
        out.append(spec)
    return out


def _extra_period_bar(row: pd.Series | None, period: str, item_orders: pd.DataFrame | None, today: date, metric: str) -> dict | None:
    """Baris periode tambahan (Kuartal/Semester/Tahun) di bawah Bulan lalu."""
    if row is None or period == "bulan" or "p_qty" not in row.index:
        return None
    from src.core.periods import calendar_period, previous_calendar_period

    prev_lo, prev_hi, prev_label = previous_calendar_period(period, today)
    _lo, end, now_label = calendar_period(period, today)
    sold = None
    if isinstance(item_orders, pd.DataFrame) and not item_orders.empty:
        days = pd.to_datetime(item_orders["order_time"]).dt.normalize()
        part = item_orders.loc[days.ge(pd.Timestamp(prev_lo)) & days.le(pd.Timestamp(prev_hi))]
        sold = float(part["qty" if metric == "qty" else "sales"].sum())
    pred = float(row["p_qty"] if metric == "qty" else row["p_sales"])
    label = PERIOD_LABELS[period]
    spec = _bar_spec(label, f"sisa {now_label} s.d. {format_id_date(end)}", int(round(pred)), None if sold is None else int(round(sold)), f"aktual {prev_label}", money=metric == "sales")
    if metric == "sales":
        spec["sold"] = "–" if sold is None else format_idr(sold)
    spec["extra"] = True
    return spec


@st.dialog("Analisa prediksi", width="large", on_dismiss=_dismiss_qty_insight)
def _qty_insight_dialog(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)
    if st.button("Paham & Tutup", type="primary", key="qty-insight-close"):
        _dismiss_qty_insight()
        st.rerun()


def _qty_card_html(row: pd.Series, brief: dict, bars: list[dict] | None = None, stock_row: str = "") -> str:
    rank = int(row["peringkat"]) if pd.notna(row["peringkat"]) else 0
    sku = html.escape(_clean_product_piece(row["sku"], "Tanpa SKU"))
    name = html.escape(_clean_product_piece(row["product_name"], "Tanpa nama"))
    variance = html.escape(_clean_product_piece(row["variasi_tampil"], "Tanpa variasi"))
    lines = []
    for bar in bars if bars is not None else brief["bars"]:
        lines.append(
            f"<div class='qty-line{' extra' if bar.get('extra') else ''}'>"
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
        f"<div class='qty-name' title='{name}'>{name}</div>"
        f"<div class='qty-var'>Varian {variance}</div>"
        "</div>"
        "<div class='qty-line qty-head-row'>"
        "<div class='qty-metric'>Periode</div><div class='qty-head-mid'>Prediksi (batang) vs terjual</div><div class='qty-base'>Terjual</div>"
        "</div>"
        f"{''.join(lines)}"
        f"{stock_row}"
        "</div>"
    )


QTY_BOARD_STEP = 5


@st.fragment
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
    metric: str = "qty",
    decision: pd.DataFrame | None = None,
    performance: dict | None = None,
) -> None:
    """R6: per SKU baris Prediksi bulan, Aktual kemarin, Tanggal sama bulan lalu, + periode tambahan, dan Stok Site 10037 paling bawah."""
    if view.empty:
        st.write("Tidak ada item untuk grafik ini.")
        return
    as_of = as_of or date.today()
    yesterday = as_of - timedelta(days=1)
    month_ago = _same_day_last_month(as_of)
    yesterday_map = _day_sold_map(orders, yesterday)
    month_ago_map = _day_sold_map(orders, month_ago)
    last_month = _last_month_sold(orders, as_of)
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
    board_title = "Prediksi QTY terjual" if metric == "qty" else "Prediksi sales value"
    st.markdown(
        f"<div class='qty-board-head'><div class='qty-board-title'>{board_title}</div></div>",
        unsafe_allow_html=True,
    )
    decision_rows = (
        {str(k): r for k, r in decision.set_index("item_key", drop=False).iterrows()}
        if isinstance(decision, pd.DataFrame) and not decision.empty
        else {}
    )
    work = view.sort_values(["peringkat", "item_key"], kind="mergesort").reset_index(drop=True)
    brief_key = "|".join(
        str(part)
        for part in (
            int(pd.util.hash_pandas_object(work.astype(str), index=False).sum()),
            len(orders) if isinstance(orders, pd.DataFrame) else 0,
            len(history) if isinstance(history, pd.DataFrame) else 0,
            resume_label,
            period_text,
            horizon_days,
            exclude_cancel,
            as_of,
            yesterday_pred_map is None,
            month_ago_pred_map is None,
            None if last_month is None else last_month[0],
            active_forecast_model(),
        )
    )
    brief_cache = st.session_state.get("_qty-briefs")
    briefs = brief_cache[1] if isinstance(brief_cache, tuple) and brief_cache[0] == brief_key else {}
    for _, row in work.iterrows() if not briefs else ():
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
            month_actual=None if last_month is None else last_month[1].get(key, 0),
            month_actual_label=None if last_month is None else last_month[0],
        )
        if last_month is not None:
            briefs[key]["month_actual_sales"] = last_month[2].get(key, 0.0)
    st.session_state["_qty-briefs"] = (brief_key, briefs)
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
            reset_batches("qty-board")
            st.rerun(scope="fragment")
    unit_word = "unit" if metric == "qty" else "Rp"
    explain(
        [
            ("Cara baca satu kartu", "tiap baris membandingkan PREDIKSI (batang, tengah) dengan yang TERJUAL (angka kanan) pada periode di kiri"),
            (f"Baris {format_period_label('prediksi', as_of)}", "prediksi periode berjalan dibanding terjual bulan penuh terakhir; naik = permintaan diperkirakan lebih tinggi dari bulan lalu"),
            (f"Baris {format_period_label('aktual_hari', as_of - timedelta(days=1))}", "prediksi untuk kemarin dibanding yang benar-benar terjual kemarin (cek ketepatan model)"),
            ("Baris Tanggal sama bulan lalu", "sama, untuk tanggal yang sama bulan lalu"),
            ("Warna & panjang batang", f"🟢 prediksi di atas terjual · 🔴 di bawah terjual · ⚪ sama; batang penuh = prediksi ≥ terjual, batang pendek = prediksi lebih kecil ({unit_word})"),
            ("Stok Site 10037", "stok toko dibanding kebutuhan (prediksi + SS) per periode: hijau Aman, kuning Kurang, merah Kosong"),
            ("Stok DC", "stok Site 10062 (DC Cikupa) dan 10036 (DC Cipeucang); bila Site 10037 kurang, Rencana menunjukkan berapa yang bisa diambil dari DC sebelum PO"),
            ("Analisa", "klik untuk rincian per SKU: prediksi vs stok, stok DC & rencana transfer, iklan, dan langkah kerja"),
        ],
        title="Cara membaca",
    )
    st.markdown(
        "<div class='qty-legend'><span><i class='up'></i>Naik</span><span><i class='down'></i>Turun</span><span><i class='flat'></i>Tetap</span></div>"
        f"<p class='qty-board-copy'>{counts['naik']} naik · {counts['turun']} turun · {counts['tetap']} tetap pada baris {html.escape(format_period_label('prediksi', as_of))}.</p>",
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
    # Kartu ditampilkan bertahap (5 Rank teratas dulu) agar halaman Ringkasan tidak setinggi 23 layar.
    total_rows = len(shown_rows)

    def _render_cards(lo: int, hi: int) -> None:
        for row in shown_rows[lo:hi]:
            _qty_board_card(row)

    def _qty_board_card(row) -> None:
        key = str(row["item_key"])
        brief = briefs[key]
        st.markdown("<div class='qty-row-anchor'></div>", unsafe_allow_html=True)
        card_col, action_col = st.columns([7.4, 1.15], vertical_alignment="center")
        enriched = decision_rows.get(key)
        item_orders = groups.get(key)
        bars = _sales_bars(brief, enriched if enriched is not None else row, item_orders, as_of) if metric == "sales" else list(brief["bars"])
        extra_bar = _extra_period_bar(enriched, period, item_orders, as_of, metric)
        if extra_bar:
            bars.append(extra_bar)
        card_col.markdown(_qty_card_html(row, brief, bars, _stock_chip_row(enriched, period, as_of)), unsafe_allow_html=True)
        if action_col.button("Analisa", key=f"qty-insight-open-{key}", use_container_width=True):
            st.session_state["qty-insight-key"] = key

    batched_view(total_rows, key="qty-board", render=_render_cards, noun="SKU", rerun_scope="fragment")
    if total_rows > 5:
        st.caption("Gunakan pencarian untuk langsung ke satu SKU.")
    selected = str(st.session_state.get("qty-insight-key") or "")
    if selected and selected in briefs:
        enriched = decision_rows.get(selected)
        if enriched is not None:
            _qty_insight_dialog(analysis_markup(enriched, period=period, today=as_of, performance=performance, brief=briefs[selected]))
        else:
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
    st.markdown("<div class='section-title'>Periode data</div>", unsafe_allow_html=True)
    period_view, range_text, data_months = period_filter(ledger, prefix="data")
    st.session_state["data_months"] = list(data_months)
    _data_range = st.session_state.get("_keep::data-cal-range") or (None, None)
    st.session_state["data-start"], st.session_state["data-end"] = _data_range
    st.session_state["data_start"], st.session_state["data_end"] = _data_range
    selected_label = range_text or "kosong"
    show_store_overview(range_text, period_view)
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
        st.checkbox("Semua", key=all_key, on_change=toggle_all)
    picked = []
    for index, status in enumerate(choice_names):
        with status_boxes[(index + 1) % box_count]:
            if st.checkbox("Retur" if status == "Return" else status, key=status_widget_key(status), on_change=toggle_one):
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
        sku_hint = "SKU pada semua status, termasuk pesanan batal dan retur (beda dengan SKU terjual bersih di Ringkasan)"
    elif not picked:
        filtered = period_view.iloc[0:0]
        sales_hint = "Centang minimal satu status pesanan"
        order_hint = "Tidak ada status yang dicentang"
        sku_hint = "Tidak ada status yang dicentang"
    elif return_only:
        filtered = period_view.loc[period_view["returned_qty"] > 0].copy()
        sales_hint = "Nilai barang yang diretur: jumlah retur × Harga Setelah Diskon"
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
            sales_hint = "Total Pembayaran tanpa batal, sekali tiap No. Pesanan; pesanan yang habis diretur tidak dihitung. Sales bersih di bawah juga mengurangi nilai retur sebagian"
            order_hint = "Tanpa batal dan tanpa pesanan yang habis diretur"
            sku_hint = "SKU yang masih punya QTY setelah retur dikurangi"
        else:
            sales_hint = "Total Pembayaran untuk status yang dicentang, sekali tiap No. Pesanan"
            order_hint = "Unik, status yang dicentang"
            sku_hint = "SKU pada status yang dicentang"
    report_frame = filtered
    if return_only and not filtered.empty:
        report_frame = filtered.copy()
        report_frame["status"] = "Retur"
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
        sku_sheet["Status retur"] = ""
    if not include_return and not include_cancel:
        sku_sheet = sku_sheet.iloc[0:0]
    if include_cancel:
        _contribution, contribution_table = cancel_contribution(period_view)
    else:
        _contribution, contribution_table = cancel_contribution(period_view.iloc[0:0])
    st.markdown(f"**{range_text or 'tidak ada tanggal yang dipilih'}**")
    period_start_day, period_end_day = period_bounds(period_view)
    facts = cached_order_metrics(period_view, period_start_day, period_end_day)
    if select_all:
        summary = {
            **summary,
            "orders": facts["pesanan_semua"],
            "sales_volume": facts["sales_bruto"],
            "invoice_cancel": facts["pesanan_batal"],
            "nominal_cancel": facts["nominal_batal"],
            "sales_return": facts["retur_unit"],
            "nominal_return": facts["nominal_retur"],
        }
    qty_shown = float(filtered["qty"].sum()) if not filtered.empty and "qty" in filtered.columns else 0.0
    sku_shown = int(filtered["item_key"].nunique()) if not filtered.empty and "item_key" in filtered.columns else 0
    resume_row = st.columns(4)
    show_metric(resume_row[0], "Jumlah pesanan", format_number(summary["orders"]), hint=order_hint)
    show_metric(resume_row[1], "Produk / varian", format_number(sku_shown), hint=sku_hint)
    show_metric(resume_row[2], "Sales bruto" if select_all else "Sales value", format_idr(summary["sales_volume"]), hint=sales_hint)
    show_metric(resume_row[3], "QTY semua status" if select_all else "QTY", format_qty(qty_shown),
                hint=f"termasuk batal & retur · QTY bersih {format_qty(facts['qty_bersih'])}" if select_all else "QTY pada status yang dicentang")
    row_two = st.columns(4)
    waiting = int(facts.get("pesanan_menunggu_bayar", 0))
    metric_card(row_two[0], "pesanan_batal", format_number(summary["invoice_cancel"]),
                hint=(f"{format_number(waiting)} pesanan masih Belum Bayar ({format_idr(facts.get('nominal_menunggu_bayar', 0))}) tidak dihitung batal"
                      if waiting else None))
    metric_card(row_two[1], "nominal_batal", format_idr(summary["nominal_cancel"]))
    metric_card(row_two[2], "retur_unit", format_qty(summary["sales_return"]))
    metric_card(row_two[3], "nominal_retur", format_idr(summary["nominal_return"]))
    row_three = st.columns(4)
    net_hint = "Selalu tanpa pesanan batal, Belum Bayar & retur, apa pun centang status di atas"
    metric_card(row_three[0], "pesanan_bersih", format_number(facts["pesanan_bersih"]), hint=net_hint)
    reach = achievement_line(facts["sales_bersih"], period_start_day, period_end_day, get_features(), orders=ledger)
    metric_card(row_three[1], "sales_bersih", format_idr(facts["sales_bersih"]), hint=net_hint + (f"<br>{reach}" if reach else ""))
    metric_card(row_three[2], "belum_bayar", format_number(facts["belum_bayar"]), hint=f"{format_number(facts['belum_bayar_akun'])} akun")
    metric_card(row_three[3], "tingkat_batal", format_pct_id(facts["tingkat_batal"] * 100))
    st.subheader("Status pesanan")
    status_view = append_total_row(status_table, "Status pesanan", ["No. Pesanan", "Kontribusi"])
    if "Kontribusi" in status_view.columns:
        status_view["Kontribusi"] = pd.to_numeric(status_view["Kontribusi"], errors="coerce")
    excel_toolbar(status_view, "status_pesanan.xlsx")
    show_table(status_view, kinds={"Kontribusi": "pct"}, bold_label="Total", column_config=table_column_config(status_view))
    st.subheader("Kontribusi invoice batal")
    if not include_cancel:
        st.write("Nominal batal tidak dihitung karena status batal tidak dicentang.")
    elif contribution_table.empty:
        st.write("Tidak ada pesanan batal pada rentang ini.")
    else:
        total_invoice = int(contribution_table["Invoice"].sum())
        total_nominal = float(contribution_table["Nominal"].sum())
        contribution_view = append_total_row(
            contribution_table,
            "Alasan pembatalan",
            ["Invoice", "Nominal", "Kontribusi invoice", "Kontribusi nominal"],
        )
        for column in ("Invoice", "Nominal", "Kontribusi invoice", "Kontribusi nominal"):
            contribution_view[column] = pd.to_numeric(contribution_view[column], errors="coerce")
        peak = float(contribution_table["Kontribusi nominal"].max() or 1.0)
        excel_toolbar(contribution_view, "kontribusi_invoice_batal.xlsx",
                      caption=f"{html.escape(range_text)} · {format_number(total_invoice)} invoice batal · total {format_idr(total_nominal)}")
        show_table(
            contribution_view,
            kinds={"Invoice": "count", "Nominal": "money", "Kontribusi invoice": "pct"},
            bold_label="Total",
            column_config={
                "Kontribusi invoice": st.column_config.Column(help="Invoice batal ÷ seluruh invoice pada rentang"),
                "Kontribusi nominal": st.column_config.ProgressColumn(format="%.1f%%", min_value=0.0, max_value=max(peak, 100.0 if peak > 100 else peak), help="Nominal batal ÷ seluruh nominal pada rentang"),
            },
        )
    show_sku_issue_section(sku_sheet, selected_label)
    show_region_analysis(source_raw, *_data_range)
    show_instant_analysis(source_raw, *_data_range)
    show_ops_analysis(source_raw, *_data_range)
    st.subheader("Pembeli batal karena belum bayar")
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
        buyers = int((unpaid["No"].astype(str) != "").sum())
        st.caption(f"{format_number(buyers)} akun · {format_number(unpaid['No. Pesanan'].nunique())} pesanan belum dibayar. Pembeli yang punya pesanan terbayar untuk SKU yang sama pada periode ini tidak dimasukkan.")
        # Prioritas: akun dengan nilai pesanan belum dibayar terbesar (dampak ke sales) lebih dulu.
        work = unpaid.copy()
        for column in ("QTY", "Sales value"):
            work[column] = pd.to_numeric(work[column], errors="coerce")
        work["_grp"] = work["No"].astype(str).replace("", np.nan).ffill()
        impact = work.groupby("_grp")["Sales value"].sum().sort_values(ascending=False, kind="mergesort")
        order = {grp: rank for rank, grp in enumerate(impact.index)}
        work["_rank"] = work["_grp"].map(order)
        work = work.sort_values(["_rank"], kind="mergesort").reset_index(drop=True)
        work["No"] = np.where(work["No"].astype(str) != "", (work["_rank"] + 1).astype(str), "")
        total_row = append_total_row(work.drop(columns=["_grp", "_rank"]), "Nama akun pembeli", ["QTY", "Sales value"]).tail(1).copy()
        total_row["Nama akun pembeli"] = f"Total · {format_number(len(impact))} akun"
        total_row["No"] = ""
        if "No. Pesanan" in total_row.columns:
            total_row["No. Pesanan"] = f"{format_number(work['No. Pesanan'].nunique())} pesanan"
        explain(
            [
                ("Urutan", "akun dengan nilai pesanan belum dibayar (sales value) terbesar lebih dulu, jadi yang paling berdampak ke sales ada di atas"),
                ("Baris Total", "di paling atas, menjumlahkan semua akun pada periode ini"),
            ]
        )

        def _render_unpaid(lo: int, hi: int) -> None:
            part = work.loc[work["_rank"].between(lo, hi - 1)]
            view = pd.concat([total_row, part.drop(columns=["_grp", "_rank"])], ignore_index=True)
            shade = pd.concat([pd.Series([False]), (part["_rank"] % 2 == 1).reset_index(drop=True)], ignore_index=True)
            styled = style_frame(view, kinds={"QTY": "count", "Sales value": "money"}).apply(
                lambda row: [
                    TOTAL_ROW_CSS if str(row["Nama akun pembeli"]).startswith("Total") else ("background-color:#f8fafc" if shade.iloc[row.name] else "")
                ]
                * len(row),
                axis=1,
            )
            view_row, view_cfg = wrap_layout(view)
            st.dataframe(styled, height=table_height(len(view), 720, view_row), row_height=view_row, column_config=view_cfg or None, hide_index=True, use_container_width=True)

        export = pd.concat([total_row, work.drop(columns=["_grp", "_rank"])], ignore_index=True)
        batched_view(
            int(len(impact)),
            key="unpaid-buyers",
            render=_render_unpaid,
            noun="akun",
            download=lambda: download_excel(export, "pembeli_belum_bayar.xlsx", key="xl-unpaid"),
        )


ISSUE_COLUMNS = {
    "Retur": ["Rank", "SKU", "Produk", "Varian", "Qty retur", "Nominal retur", "Status retur"],
    "Batal": ["Rank", "SKU", "Produk", "Varian", "Qty batal", "Invoice batal", "Nominal batal", "Alasan batal"],
}
ISSUE_TITLES = {
    "Retur": "Hanya kolom retur. Diurutkan dari qty retur terbesar.",
    "Batal": "Hanya kolom batal. Diurutkan dari qty batal terbesar.",
    "All": "Kolom retur dan batal. Diurutkan dari retur terbanyak, lalu batal terbanyak.",
}
ISSUE_SUMS = ("Qty retur", "Nominal retur", "Qty batal", "Invoice batal", "Nominal batal")


def _issue_kind_sheet(sku_sheet: pd.DataFrame, issue_kind: str) -> pd.DataFrame:
    if sku_sheet.empty or issue_kind == "All":
        return sku_sheet
    column = "Qty retur" if issue_kind == "Retur" else "Qty batal"
    return sku_sheet.loc[pd.to_numeric(sku_sheet[column], errors="coerce").fillna(0) > 0]


@st.cache_data(show_spinner=False, max_entries=64)
def sku_issue_reasons(sku_sheet: pd.DataFrame, issue_kind: str) -> list[str]:
    kind_sheet = _issue_kind_sheet(sku_sheet, issue_kind)
    columns = {"Retur": ["Status retur"], "Batal": ["Alasan batal"]}.get(issue_kind, ["Status retur", "Alasan batal"])
    return sorted({str(v) for c in columns if c in kind_sheet.columns for v in kind_sheet[c].tolist() if str(v).strip()})


def _join_reasons(values: pd.Series, weights: pd.Series) -> str:
    """Alasan unik per SKU, terbanyak dulu: "Belum dibayar (3) · Ubah alamat (1)"."""
    totals: dict[str, float] = {}
    for reason, weight in zip(values.astype(str), pd.to_numeric(weights, errors="coerce").fillna(0)):
        if reason.strip():
            totals[reason] = totals.get(reason, 0.0) + float(weight)
    ordered = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    return " · ".join(f"{reason} ({format_number(weight)})" if weight > 0 else reason for reason, weight in ordered)


def _one_row_per_sku(shown: pd.DataFrame, issue_kind: str) -> pd.DataFrame:
    """Sumber dikelompokkan per SKU × alasan; tampilan digabung jadi satu baris per SKU + varian."""
    if shown.empty or not {"SKU", "Varian"} <= set(shown.columns):
        return shown
    sums = [c for c in ISSUE_SUMS if c in shown.columns]
    work = shown.copy()
    for column in sums:
        work[column] = pd.to_numeric(work[column], errors="coerce").fillna(0)
    keys = ["SKU", "Varian"]
    agg = {column: "sum" for column in sums}
    if "Produk" in work.columns:
        agg["Produk"] = "first"
    merged = work.groupby(keys, sort=False, as_index=False).agg(agg)
    for reason_col, weight_col in (("Status retur", "Qty retur"), ("Alasan batal", "Invoice batal")):
        if reason_col not in work.columns:
            continue
        weights = work[weight_col] if weight_col in work.columns else pd.Series(0, index=work.index)
        part = work.assign(_w=weights).loc[work[reason_col].astype(str).str.strip().ne("")]
        if part.empty:
            merged[reason_col] = ""
            continue
        per = part.groupby(keys + [reason_col], sort=False, as_index=False)["_w"].sum()
        per = per.sort_values(keys + ["_w", reason_col], ascending=[True, True, False, True], kind="mergesort")
        per["_txt"] = [f"{r} ({format_number(w)})" if w > 0 else str(r) for r, w in zip(per[reason_col], per["_w"])]
        joined = per.groupby(keys, sort=False)["_txt"].agg(" · ".join).rename(reason_col).reset_index()
        merged = merged.merge(joined, on=keys, how="left")
        merged[reason_col] = merged[reason_col].fillna("")
    order = {"Retur": ["Qty retur", "Nominal retur"], "Batal": ["Qty batal", "Nominal batal"]}.get(
        issue_kind, ["Qty retur", "Nominal retur", "Qty batal", "Nominal batal"]
    )
    order = [c for c in order if c in merged.columns]
    if order:
        merged = merged.sort_values(order + ["SKU"], ascending=[False] * len(order) + [True], kind="mergesort")
    merged.insert(0, "Rank", 0)
    columns = [c for c in shown.columns if c in merged.columns]
    return merged.loc[:, columns].reset_index(drop=True)

@st.cache_data(show_spinner=False, max_entries=64)
def sku_issue_view(sku_sheet: pd.DataFrame, issue_kind: str, reasons: tuple[str, ...], all_reasons: tuple[str, ...]) -> tuple[pd.DataFrame, int]:
    """Tabel SKU retur/batal sesuai filter jenis + alasan, dengan rank ulang dan baris Total."""
    kind_sheet = _issue_kind_sheet(sku_sheet, issue_kind)
    if kind_sheet.empty or not all_reasons:
        shown = kind_sheet
    elif not reasons:
        shown = kind_sheet.iloc[0:0]
    elif issue_kind in ISSUE_COLUMNS:
        shown = kind_sheet.loc[kind_sheet[f"Alasan {issue_kind.lower()}"].astype(str).isin(reasons)]
    else:
        shown = kind_sheet.loc[kind_sheet["Status retur"].astype(str).isin(reasons) | kind_sheet["Alasan batal"].astype(str).isin(reasons)]
    keep = ISSUE_COLUMNS.get(issue_kind, list(shown.columns))
    shown = shown.loc[:, [c for c in keep if c in shown.columns]].copy()
    shown = _one_row_per_sku(shown, issue_kind)
    count = len(shown)
    if shown.empty:
        return shown, 0
    sums = [c for c in ISSUE_SUMS if c in shown.columns]
    shown["Rank"] = [str(n) for n in range(1, len(shown) + 1)]
    shown = append_total_row(shown, "SKU", sums)
    for column in sums:
        shown[column] = pd.to_numeric(shown[column], errors="coerce")
    return shown, count


@st.fragment
def _reason_items(text) -> list[str]:
    """'Sistem Shopee · Belum dibayar (34) · Pembeli · Lainnya (15)' → ['Sistem Shopee · Belum dibayar (34)', ...]."""
    import re

    value = "" if text is None or (isinstance(text, float) and np.isnan(text)) else str(text).strip()
    if not value:
        return []
    items = [m.strip(" ·") for m in re.findall(r".+?\(\d+\)(?:\s·\s|$)", value)]
    return items or [value]


def _short_reasons(text, keep: int = 2) -> str:
    items = _reason_items(text)
    if len(items) <= keep:
        return "" if text is None or (isinstance(text, float) and np.isnan(text)) else str(text)
    return " · ".join(items[:keep]) + f" · +{len(items) - keep} lainnya"


ISSUE_MONEY = {"Nominal retur", "Nominal batal"}
ISSUE_RENAME = {"Qty retur": "Unit retur", "Qty batal": "Unit batal"}


def _issue_table_html(total_part: pd.DataFrame, part: pd.DataFrame, reason_cols: list[str], tips: dict | None = None) -> str:
    """Tabel SKU retur/batal sebagai HTML: alasan panjang diringkas, tombol "Lihat semua" membuka seluruh
    alasan di sel yang sama (tanpa tabel baru)."""
    columns = list(part.columns if not part.empty else total_part.columns)
    numeric = {c for c in columns if c not in {"Rank", "SKU", "Produk", "Varian", *reason_cols}}

    def cell(column: str, value, bold: bool = False) -> str:
        if column in reason_cols:
            items = _reason_items(value)
            if len(items) <= 2:
                text = html.escape(" · ".join(items))
            else:
                short = html.escape(" · ".join(items[:2]))
                full = "".join(f"<li>{html.escape(item)}</li>" for item in items)
                text = (
                    f"{short}<details class='reason-more'><summary>Lihat semua ({len(items)})</summary>"
                    f"<ul>{full}</ul></details>"
                )
            return f"<td class='reason'>{text}</td>"
        if column in numeric:
            number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
            text = "" if pd.isna(number) else (format_idr(number) if column in ISSUE_MONEY else format_number(number, 0))
            return f"<td class='num'>{'<b>' + text + '</b>' if bold else text}</td>"
        text = "" if value is None or (isinstance(value, float) and np.isnan(value)) else html.escape(str(value))
        return f"<td>{'<b>' + text + '</b>' if bold else text}</td>"

    tips = tips or {}
    head = "".join(
        f"<th class='{'num' if c in numeric else ''}' title='{html.escape(tips.get(c, ''))}'>{html.escape(ISSUE_RENAME.get(c, c))}</th>"
        for c in columns
    )
    rows = []
    for _, record in total_part.iterrows():
        rows.append("<tr class='total'>" + "".join(cell(c, record.get(c), bold=True) for c in columns) + "</tr>")
    for _, record in part.iterrows():
        rows.append("<tr>" + "".join(cell(c, record.get(c)) for c in columns) + "</tr>")
    style = (
        "<style>"
        ".issue-table{border-collapse:separate;border-spacing:0;width:max-content;min-width:100%;font-size:.875rem;color:#31333f}"
        ".issue-table th{position:sticky;top:0;background:#f1f5f9;color:#6b6d76;font-weight:500;text-align:left;padding:8px;border-bottom:1px solid #e2e8f0;white-space:nowrap}"
        ".issue-table td{padding:8px;border-bottom:1px solid #e2e8f0;vertical-align:top;background:#fff}"
        ".issue-table td.num,.issue-table th.num{text-align:right;white-space:nowrap}"
        ".issue-table tr.total td{background:#f8fafc}"
        ".issue-table td.reason{min-width:260px;max-width:420px;white-space:normal}"
        ".reason-more{margin-top:4px}"
        ".reason-more summary{display:inline-block;cursor:pointer;color:#1d4ed8;background:#eff6ff;border:1px solid #bfdbfe;"
        "border-radius:999px;padding:1px 10px;font-size:.78rem;font-weight:700;list-style:none}"
        ".reason-more summary::-webkit-details-marker{display:none}"
        ".reason-more[open] summary{color:#475569;background:#f1f5f9;border-color:#cbd5e1}"
        ".reason-more ul{margin:6px 0 0 16px;padding:0}"
        "</style>"
    )
    return style + f"<div class='sheet-scroll' style='max-height:640px'><table class='issue-table'><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def reason_picker(options: list[str], *, key: str) -> list[str]:
    """Filter alasan ringkas: satu tombol (popover) berisi Semua/Kosongkan dan checkbox per alasan,
    dikelompokkan menurut sumber (Pembeli, Sistem Shopee, Penjual, ...) dengan teks lengkap."""
    for option in options:
        widget = f"{key}::{option}"
        if widget not in st.session_state:
            st.session_state[widget] = True

    def _set(value: bool) -> None:
        for option in options:
            st.session_state[f"{key}::{option}"] = value

    chosen = [o for o in options if st.session_state.get(f"{key}::{o}")]
    if len(chosen) == len(options):
        summary = f"Semua alasan ({len(options)})"
    elif not chosen:
        summary = "Pilih alasan"
    elif len(chosen) == 1:
        summary = chosen[0] if len(chosen[0]) <= 40 else chosen[0][:38] + "…"
    else:
        summary = f"{len(chosen)} dari {len(options)} alasan"
    with st.popover(f"🏷️ Alasan · {summary}", use_container_width=True):
        q1, q2, _gap = st.columns([1, 1, 2])
        q1.button("Semua", key=f"{key}-all", on_click=_set, args=(True,), use_container_width=True)
        q2.button("Kosongkan", key=f"{key}-none", on_click=_set, args=(False,), use_container_width=True)
        groups: dict[str, list[str]] = {}
        for option in options:
            head = option.split(" · ", 1)[0] if " · " in option else "Lainnya"
            groups.setdefault(head, []).append(option)
        for head, items in groups.items():
            st.markdown(f"<div class='field-hint' style='margin-top:6px'><b>{html.escape(head)}</b></div>", unsafe_allow_html=True)
            cols = st.columns(2)
            for index, option in enumerate(items):
                text = option.split(" · ", 1)[1] if " · " in option else option
                cols[index % 2].checkbox(text, key=f"{key}::{option}")
    return [o for o in options if st.session_state.get(f"{key}::{o}")]


def show_sku_issue_section(sku_sheet: pd.DataFrame, selected_label: str) -> None:
    """Filter hanya menjalankan ulang bagian ini (bukan seluruh tab Data)."""
    st.subheader("SKU dengan retur dan batal")
    issue_labels = {"All": "Semua", "Retur": "Retur", "Batal": "Batal"}
    kind_col, reason_col = st.columns([1, 2], vertical_alignment="bottom")
    issue_kind = kind_col.segmented_control(
        "Tampilkan", options=["All", "Retur", "Batal"], default="All", format_func=issue_labels.get, key="data-issue-kind"
    ) or "All"
    reason_names = sku_issue_reasons(sku_sheet, issue_kind)
    selected_reasons: list[str] = []
    if not reason_names:
        reason_col.caption("Tidak ada alasan pada tampilan ini.")
    else:
        with reason_col:
            selected_reasons = reason_picker(reason_names, key=f"data-reasons-{issue_kind}-{selected_label}")
        if not selected_reasons:
            st.warning("Pilih minimal satu alasan.")
    shown_sheet, sheet_count = sku_issue_view(sku_sheet, issue_kind, tuple(selected_reasons), tuple(reason_names))
    st.caption(f"{format_number(sheet_count)} SKU. {ISSUE_TITLES[issue_kind]}")
    if shown_sheet.empty:
        st.write("Tidak ada SKU dengan retur atau batal pada filter ini.")
        return
    tips = {
        "Qty retur": "Jumlah retur (kolom Returned quantity di laporan Shopee)",
        "Nominal retur": "Jumlah retur × Harga Setelah Diskon",
        "Qty batal": "Jumlah pada baris berstatus batal",
        "Invoice batal": "No. Pesanan unik berstatus batal",
        "Nominal batal": "Harga Setelah Diskon × Jumlah pada baris batal",
        "Status retur": "Status pengajuan retur dari kolom Status Pembatalan/Pengembalian (laporan Shopee tidak memuat alasan retur)",
        "Alasan batal": "Dari kolom Alasan Pembatalan",
    }
    # Baris Total dipindah ke atas; data tampil 5 SKU lalu Muat lebih banyak (+10).
    is_total = shown_sheet["SKU"].astype(str).eq("Total")
    total_part, body = shown_sheet.loc[is_total], shown_sheet.loc[~is_total].reset_index(drop=True)
    export = pd.concat([total_part, body], ignore_index=True)
    reason_cols = [c for c in ("Status retur", "Alasan batal") if c in body.columns]

    def _render_issue(lo: int, hi: int) -> None:
        part = body.iloc[lo:hi].reset_index(drop=True)
        st.markdown(_issue_table_html(total_part, part, reason_cols, tips), unsafe_allow_html=True)

    batched_view(
        len(body),
        key=f"sku-issue-{issue_kind}",
        render=_render_issue,
        noun="SKU",
        fragment=False,
        rerun_scope="fragment",
        download=lambda: offer_excel(export, "sku_retur_batal.xlsx"),
    )


def show_store_overview(range_text: str, period_view: pd.DataFrame | None = None) -> None:
    """Kartu performa toko (data performa toko) dan ringkasan iklan per periode terpilih."""
    frames = store_frames()
    perf = frames.performance
    if isinstance(perf, pd.DataFrame) and not perf.empty and "date" in perf.columns:
        work = clean_performance(perf)
        start = st.session_state.get("data-start")
        end = st.session_state.get("data-end")
        if start and end:
            span = pd.Timestamp(end) - pd.Timestamp(start) + pd.Timedelta(days=1)
            now = work.loc[work["date"].between(pd.Timestamp(start), pd.Timestamp(end))]
            prev = work.loc[work["date"].between(pd.Timestamp(start) - span, pd.Timestamp(start) - pd.Timedelta(days=1))]
        else:
            now, prev = work, work.iloc[0:0]

        def total(frame: pd.DataFrame, column: str, mean: bool = False) -> float:
            if column not in frame.columns or frame.empty:
                return float("nan")
            values = perf_number(frame[column])
            if not mean:
                return float(values.sum())
            weight_col = "visitors" if column == "conversion_rate" else "orders"
            weights = perf_number(frame[weight_col]) if weight_col in frame.columns else None
            if weights is not None and float(weights.where(values.notna()).sum()) > 0:
                return float((values * weights).sum() / weights.where(values.notna()).sum())
            return float(values.mean())

        def delta(a: float, b: float) -> str | None:
            if not np.isfinite(a) or not np.isfinite(b) or b == 0:
                return None
            pct = (a - b) / b * 100
            color = "#1d4ed8" if pct >= 0 else "#dc2626"
            return f"<span style='color:{color};font-weight:700'>{'▲' if pct >= 0 else '▼'} {format_number(abs(pct), 1)}%</span> vs periode sebelumnya"

        st.markdown("<div class='section-title'>Performa toko</div>", unsafe_allow_html=True)
        cols = st.columns(4)
        for column, (label, key, is_mean, pct) in zip(
            cols,
            (("Pengunjung", "visitors", False, False), ("Konversi (tertimbang)", "conversion_rate", True, True), ("Pembeli baru", "new_buyers", False, False), ("Pembelian berulang", "repeat_rate", True, True)),
        ):
            value = total(now, key, is_mean)
            text = "-" if not np.isfinite(value) else (f"{format_number(value, 2)}%" if pct else format_number(value, 0))
            show_metric(column, label, text, hint=delta(value, total(prev, key, is_mean)))
    else:
        st.caption("Data performa toko belum diunggah: kartu pengunjung, konversi, dan pembeli berulang belum tersedia.")
    if not frames.has_ads or period_view is None or period_view.empty:
        return
    start, end = period_bounds(period_view)
    ads = ads_metrics(frames.ads, frames.stock, period_view, start, end)
    st.markdown("<div class='section-title'>Ringkasan iklan</div>", unsafe_allow_html=True)
    monthly = ads_by_month(frames.ads, start, end)
    if ads["biaya_iklan"] > 0:
        cols = st.columns(4)
        metric_card(cols[0], "biaya_iklan", format_idr(ads["biaya_iklan"]))
        metric_card(cols[1], "omzet_iklan", format_idr(ads["omzet_iklan"]))
        metric_card(cols[2], "roas", format_number(ads["roas"], 1))
        show_metric(cols[3], "Hari laporan iklan", f"{format_number(ads['hari_iklan'])} hari", hint=f"{format_id_date(pd.Timestamp(start).date())} – {format_id_date(pd.Timestamp(end).date())}")
    else:
        available = ads_report_span(frames.ads)
        st.info(
            "Belum ada laporan iklan untuk periode ini."
            + (f" Laporan iklan tersimpan mencakup {available}." if available else " Unggah laporan iklan di Upload data › Iklan."),
            icon=":material/info:",
        )
    if len(monthly) > 1:
        st.markdown("**Iklan per bulan** (acuan: Semua laporan iklan, diprorata per hari laporan)")
        show_table(monthly, kinds={"Biaya iklan": "money", "Omzet iklan": "money", "Hari laporan": "count"})


def ads_report_span(ads_frames) -> str:
    """Rentang tanggal seluruh laporan iklan tersimpan, untuk pesan bila periode terpilih tidak punya iklan."""
    from src.core.ads import _prepare

    try:
        ads = _prepare(list(ads_frames or []))
    except Exception:
        return ""
    if ads.empty or ads["_lo"].isna().all():
        return ""
    return f"{format_id_date(ads['_ulo'].min().date())} – {format_id_date(ads['_uhi'].max().date())}"


def ads_by_month(ads_frames, start, end) -> pd.DataFrame:
    """Biaya, omzet, ROAS all iklan per bulan kalender di dalam periode terpilih."""
    from src.core.ads import OVERALL, SUMMARY_CODES, ad_report_rows

    rows = []
    if start is None or end is None:
        return pd.DataFrame()
    for month in pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M"):
        lo = max(month.start_time.normalize(), pd.Timestamp(start).normalize())
        hi = min(month.end_time.normalize(), pd.Timestamp(end).normalize())
        try:
            part, _lo, _hi, days = ad_report_rows(list(ads_frames or []), start=lo, end=hi)
        except Exception:
            continue
        overall = part.loc[part["_src"].eq(OVERALL)] if not part.empty else part
        source = "All iklan"
        if overall.empty and not part.empty:
            # Tanpa laporan all iklan: jumlah baris per produk (tanpa baris ringkasan), sama dengan attribute_ads.
            overall = part.loc[~part["product_code"].astype(str).str.lower().isin(SUMMARY_CODES)]
            source = "Per produk (all iklan belum diunggah)"
        if overall.empty:
            continue
        cost = float(overall["biaya_iklan"].sum())
        sales = float(overall["omzet_iklan"].sum())
        rows.append(
            {
                "Bulan": f"{ID_MONTHS[month.month - 1]} {month.year}",
                "Biaya iklan": cost,
                "Omzet iklan": sales,
                "ROAS": round(sales / cost, 1) if cost > 0 else None,
                "Hari laporan": days,
                "Sumber": source,
            }
        )
    return pd.DataFrame(rows)


def show_folder_menu() -> None:
    """Daftar data tersimpan menurut bulan dan tahun, plus riwayat impor."""
    saved = list_months()
    st.subheader("Folder data")
    explain(
        [
            "Data yang sudah diimpor tersimpan di sini.",
            ("Data latih", "bulan yang dipakai dipilih di Upload data › Setelan analisa"),
            ("Unggah ulang transaksi", "file baru yang memuat bulan yang sama menggantikan isi bulan itu"),
        ]
    )
    if not saved:
        st.write("Belum ada data tersimpan.")
    else:
        folder = cached_folder(bundle_stamp([item["key"] for item in saved])).rename(
            columns={
                "No. Pesanan": "Jumlah pesanan",
                "Sales bersih": "Sales bersih (Rp)",
                "Sales retur": "Sales retur (Rp)",
                "Sales batal": "Sales batal (Rp)",
            }
        )
        st.caption(
            "Angka per bulan sama dengan Ringkasan, Data, dan Laporan untuk bulan yang sama. Arahkan kursor ke ikon ? untuk definisi kolom.",
            help=(
                "Sales bersih = sales bruto − nominal batal − nominal retur. "
                "QTY bersih = QTY selain batal − unit retur. Sales retur = unit retur × Harga Setelah Diskon. "
                "Pesanan retur dan Pesanan batal adalah jumlah No. Pesanan. "
                "Berhasil = Pesanan Diterima, Sedang Dikirim, Selesai, dan Telah Dikirim."
            ),
        )
        # Filter kalender (bulan yang tersentuh rentang); bawaan 12 bulan terakhir. Total di atas, tinggi baris tetap.
        keys = [item["key"] for item in saved]
        folder = folder.assign(_key=keys[: len(folder)])
        goals = monthly_targets(get_features())
        if "Sales bersih (Rp)" in folder.columns:
            goal_values = folder["_key"].map(lambda k: goals.get(str(k), 0.0))
            sales_values = pd.to_numeric(folder["Sales bersih (Rp)"], errors="coerce").fillna(0)
            at = folder.columns.get_loc("Sales bersih (Rp)") + 1
            folder.insert(at, "Target (Rp)", [format_number(g) if g > 0 else "–" for g in goal_values])
            month_goal = dict(zip(folder["Bulan"], goal_values))
            folder.insert(at + 1, "Pencapaian target", [
                f"{format_pct_id(s / g * 100)} {'✅' if s >= g else '🔴'}" if g > 0 else "belum diunggah"
                for s, g in zip(sales_values, goal_values)
            ])
        dated = sorted(k for k in keys if str(k)[:4].isdigit())
        if dated:
            lo = pd.Period(dated[0], freq="M").start_time.date()
            hi = pd.Period(dated[-1], freq="M").end_time.date()
            default_lo = max(lo, (pd.Period(dated[-1], freq="M") - 11).start_time.date())
            start, end = date_range_picker(key="folder-cal", lo=lo, hi=hi, default=(default_lo, hi), label="Periode folder data")
            touched = set(pd.period_range(start, end, freq="M").astype(str))
            folder = folder.loc[folder["_key"].isin(touched) | ~folder["_key"].astype(str).str[:4].str.isdigit()]
        folder = folder.drop(columns="_key").reset_index(drop=True)
        if "File terakhir" in folder.columns:
            folder_export = folder.copy()
            folder["File terakhir"] = folder["File terakhir"].map(lambda t: (lambda n: ", ".join(n[:1]) + (f" +{len(n) - 1} file" if len(n) > 1 else ""))([x.strip() for x in str(t or "").split(",") if x.strip()]))
        else:
            folder_export = folder.copy()
        sums = [c for c in folder.columns if c not in {"Bulan", "File terakhir", "Diperbarui"} and pd.api.types.is_numeric_dtype(folder[c])]

        def _with_total(frame: pd.DataFrame) -> pd.DataFrame:
            total = {c: (frame[c].sum() if c in sums else "") for c in frame.columns}
            total["Bulan"] = f"Total · {len(frame)} bulan"
            if "Pencapaian target" in frame.columns:
                goal_raw = frame["Bulan"].map(month_goal).fillna(0.0)
                has_goal = goal_raw > 0
                goal_sum = float(goal_raw[has_goal].sum())
                sales_sum = float(pd.to_numeric(frame.loc[has_goal, "Sales bersih (Rp)"], errors="coerce").sum())
                total["Target (Rp)"] = format_number(goal_sum) if goal_sum > 0 else "–"
                total["Pencapaian target"] = (
                    f"{format_pct_id(sales_sum / goal_sum * 100)} {'✅' if sales_sum >= goal_sum else '🔴'} · {int(has_goal.sum())} bulan bertarget"
                    if goal_sum > 0 else ""
                )
            return pd.concat([pd.DataFrame([total]), frame], ignore_index=True)

        shown, rest = folder.head(12), folder.iloc[12:]
        table_toolbar(lambda: offer_excel(_with_total(folder_export), "folder_data.xlsx"), key="folder-data",
                      caption=f"{format_number(len(folder))} bulan pada periode terpilih · baris Total di atas")
        show_table(_with_total(folder) if rest.empty else pd.concat([_with_total(folder).head(1), shown], ignore_index=True),
                   bold_label=f"Total · {len(folder)} bulan", column_config=table_column_config(folder), row_height=35, max_height=10_000)
        if not rest.empty:
            with st.expander(f"Lihat detail · {format_number(len(rest))} bulan lainnya"):
                show_table(rest, column_config=table_column_config(folder), row_height=35, max_height=10_000)
    st.subheader("Riwayat perubahan data")
    changes = history_frame()
    if changes.empty:
        st.write("Belum ada perubahan impor.")
    else:
        # Daftar file panjang diringkas di layar ("a.xlsx, b.xlsx +8 file"); unduhan Excel tetap lengkap.
        def _short_files(text: object) -> str:
            names = [n.strip() for n in str(text or "").split(",") if n.strip()]
            return ", ".join(names[:2]) + (f" +{len(names) - 2} file" if len(names) > 2 else "")

        shown_changes = changes.assign(File=changes["File"].map(_short_files)) if "File" in changes.columns else changes
        batched_view(
            len(shown_changes), key="folder-history", noun="perubahan",
            render=lambda lo, hi: show_table(shown_changes.iloc[lo:hi], column_config={"Perubahan": st.column_config.TextColumn(width="large")}, max_height=10_000),
            download=lambda: offer_excel(changes, "riwayat_perubahan_data.xlsx"),
        )


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
            pending = "Klik Jalankan analisa supaya angka mengikuti file dan periode yang baru."
        elif not has_result:
            pending = "Klik Jalankan analisa untuk menghitung angka ini."
        else:
            pending = "Angka item terlaris belum tersedia untuk persentase ini."
        return css, f"{headline}<br>{pending}"
    if metric == "sales":
        figures = (
            f"Pada {impact['items']} item terlaris menurut sales value: "
            f"prediksi sales value {format_idr(impact['pred_sales'])} "
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
        f"prediksi sales value {format_idr(impact['pred_sales'])}."
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
    period_orders: pd.DataFrame | None = None,
) -> pd.DataFrame:
    ranked = rank_from_orders(orders, metric) if period_orders is None else rank_for_period(orders, period_orders, metric)
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
    missed = view["pred_qty"].isna() & (view["qty_total"] > 0)
    for column, default in (
        ("qty_histori", 0.0),
        ("sales_histori", 0.0),
        ("pred_qty", 0.0),
        ("pred_sales", 0.0),
        ("safety_stock", 0.0),
        ("stok_disarankan", 0),
    ):
        view[column] = view[column].fillna(default)
    # Prediksi model disimpan apa adanya (pecahan); pembulatan ke bawah hanya di tabel keputusan, supaya laju harian
    # SKU lambat tidak jadi 0 lalu tertimpa rata-rata. Rata-rata riwayat hanya bila model tidak punya prediksi SKU itu.
    view["pred_qty"] = view["pred_qty"].astype(float).clip(lower=0)
    view["pred_sales"] = view["pred_sales"].astype(float).clip(lower=0)
    view["safety_stock"] = np.ceil(view["safety_stock"].astype(float) - 1e-9).astype(int).clip(lower=0)
    if missed.any():
        span_days = max(int((orders["order_time"].max() - orders["order_time"].min()).days) + 1, 1)
        horizon_days = horizon_day_count(period)
        view.loc[missed, "pred_qty"] = view.loc[missed, "qty_total"].astype(float) / span_days * horizon_days
        unit_price = view.loc[missed, "sales_total"] / view.loc[missed, "qty_total"].replace(0, np.nan)
        view.loc[missed, "pred_sales"] = view.loc[missed, "pred_qty"] * unit_price.fillna(0)
    view["stok_disarankan"] = (whole_units(view["pred_qty"].to_numpy()).astype(int) + view["safety_stock"].astype(int)).clip(lower=0)
    view["variasi_tampil"] = view["variation"].map(lambda value: value if str(value).strip() else "Tanpa variasi")
    return view


TABLE_SORTS = {
    "qty_desc": ("qty_total", False, "QTY terjual, terbesar dulu"),
    "qty_asc": ("qty_total", True, "QTY terjual, terkecil dulu"),
    "sales_desc": ("sales_total", False, "Sales value, terbesar dulu"),
    "sales_asc": ("sales_total", True, "Sales value, terkecil dulu"),
    "pred_qty_desc": ("pred_qty", False, "Prediksi QTY, terbesar dulu"),
    "pred_qty_asc": ("pred_qty", True, "Prediksi QTY, terkecil dulu"),
    "pred_sales_desc": ("pred_sales", False, "Prediksi sales value, terbesar dulu"),
    "pred_sales_asc": ("pred_sales", True, "Prediksi sales value, terkecil dulu"),
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
    month_days = horizon_day_count("bulan", day)
    factor = TODAY_FACTOR[0] if day == date.today() else 1.0
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
        qty_one, sales_one, stock_one = slice_forecast(qty, sales, safety, horizon, 1, factor)
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
    out["slice_day_factor"] = factor
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
            "Produk": view["product_name"].map(lambda value: _clean_product_piece(value, "Tanpa nama")),
            "Varian": view["variasi_tampil"].map(lambda value: _clean_product_piece(value, "Tanpa variasi")),
            "Rank": view["peringkat"].astype(int),
            "QTY terjual": view["qty_total"].astype(int),
            "Sales value": view["sales_total"].round().astype(int),
            "Prediksi sales hari ini": view["pred_sales_hari"].astype(int) if "pred_sales_hari" in view.columns else 0,
            f"Prediksi sales bulan ini ({month_days} hari)": view["pred_sales_bulan"].astype(int) if "pred_sales_bulan" in view.columns else 0,
            "Stok disarankan bulan ini": view["stok_bulan"].astype(int) if "stok_bulan" in view.columns else view["stok_disarankan"].astype(int),
            f"Prediksi QTY ({period_name})": view["pred_qty"].astype(int),
            f"Prediksi sales value ({period_name})": view["pred_sales"].round().astype(int),
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
    return stock_for_combined(
        analysis.get("base_history", pd.DataFrame()),
        analysis["combined"],
        period=analysis["period"],
        as_of=date.today(),
        service=percent,
        params=current_params(),
        weights=analysis.get("ensemble_weights"),
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
            name="Aktual",
            x=actual,
            y=labels,
            orientation="h",
            text=actual_text,
            marker_color="#4C78A8",
            customdata=full_labels,
            hovertemplate="%{customdata}<br>Aktual: %{text}<extra></extra>",
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
        title=dict(text=f"QTY aktual vs prediksi ({scope_label})", font=dict(size=16)),
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
            name="Sales aktual",
            x=actual_x,
            y=labels,
            orientation="h",
            text=actual_text,
            marker_color="#4C78A8",
            customdata=np.column_stack([full_labels, _actual_hover]),
            hovertemplate="%{customdata[0]}<br>Sales aktual: %{customdata[1]}<extra></extra>",
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
    """Batang sales value dan garis QTY pada sumbu kanan."""
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
            name="Sales value",
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
        yaxis_title="Sales value (Rp)",
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
        f"Prediksi sales {scope} lebih rendah {format_idr(gap)} ({format_number(percent, 1)}%) dari sales aktual.",
        "Sales prediksi = prediksi QTY × harga jual. Penurunan sales mengikuti qty dan harga, bukan model omzet terpisah.",
    ]
    if actual_qty > 0 and pred_qty + 0.5 < actual_qty:
        sentences.append(
            f"Prediksi QTY {format_qty(pred_qty)} berada di bawah QTY aktual {format_qty(actual_qty)}. "
            "Level 28 hari terakhir lebih sepi daripada periode yang ditampilkan."
        )
    elif actual_qty > 0:
        sentences.append(
            "Prediksi QTY tidak lebih rendah dari QTY aktual. Penurunan sales datang dari harga jual pada campuran qty itu."
        )
    sentences.append("Stok yang disiapkan tetap prediksi QTY ditambah safety stock, pada tabel.")
    return " ".join(sentences)


def daily_actual_chart(scope_orders: pd.DataFrame, scope_label: str, value: str) -> go.Figure:
    del scope_label
    money = value == "sales"
    title = "Sales value aktual per hari" if money else "QTY aktual per hari"
    axis = "Sales value (Rp)" if money else "QTY"
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
    """Dua batang Aktual dan Prediksi. Angka selalu di dalam batang."""
    series = pd.Series(values, dtype=float)
    peak = float(series.max() or 1)
    positions, colors = _bar_label_style(series, peak)
    texts = [format_idr(value) if money else format_number(value, 0) for value in values]
    fig = go.Figure(
        go.Bar(
            x=["Aktual", "Prediksi"],
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
        xaxis_title="Sales value (Rp)" if money else "QTY",
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
        if column in {"Produk", "Variasi", "Referensi SKU", "Item", "SKU", "Varian"}:
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
    frame = drop_blank_rows(frame)
    if frame.empty:
        st.info("Belum ada data")
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
    height_style = "max-height:70vh;" if max_height is None else f"max-height:min({int(max_height)}px, 70vh);"
    box = (
        "<div class='sheet-scroll' "
        f"style='{height_style}width:100%;max-width:100%;overflow:scroll;display:block;'>"
    )
    st.markdown(
        box + f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table></div>",
        unsafe_allow_html=True,
    )


MOVEMENT_STEP = 5


def _ss_params(params: dict, service: int) -> dict:
    """Parameter yang ditampilkan di kotak Analisa safety stock (sama dengan yang dipakai recommend_stock)."""
    from src.core.service_level import class_service_levels
    from src.models.evaluate import SS_CALIBRATION_KEY

    lead = params.get("lead_time", {}) if isinstance(params, dict) else {}
    impor = bool(lead.get("impor_aktif", False))
    days = float(lead.get("impor_rata_hari", 60) if impor else lead.get("lokal_hari", 7))
    analysis = st.session_state.get("analysis")
    weights = analysis.get("ensemble_weights") if isinstance(analysis, dict) else None
    return {"service": int(service), "lead_days": days, "import_mode": impor, "review_days": float(lead.get("review_hari", 7) or 0),
            "class_levels": class_service_levels(service, params),
            "calibration": float((weights or {}).get(SS_CALIBRATION_KEY, 1.0) or 1.0)}


from src.ui.decision_view import COMPONENT_VERSION as _TABLE_VERSION  # noqa: E402

# Nama memuat sidik index.html agar browser tidak memakai komponen lama dari cache.
_TOP50_TABLE = components.declare_component(f"top50_table_{_TABLE_VERSION}", path=str(ROOT / "components" / "top50_table"))


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
        {"id": "rank", "label": "Rank", "pin": True, "width": 92, "kind": "num", "sort": True},
        {"id": "sku", "label": "SKU", "kicker": "Produk", "pin": True, "width": 116, "sort": True},
        {"id": "name", "label": "Produk", "kicker": "Produk", "pin": True, "width": 280, "kind": "name", "sort": True},
        {"id": "variance", "label": "Varian", "width": 170, "kind": "name", "sort": True},
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
        expected = {}
        for prefix, days in (("d", 1), ("m", month_days)):
            mult = TODAY_FACTOR[0] if prefix == "d" else 1.0
            qty, sales, stock = slice_forecast(qty_now, sales_now, safety_now, horizon, days, mult)
            expected[f"{prefix}_qty"] = qty_now * days / horizon * mult
            expected[f"{prefix}_sales"] = sales_now * days / horizon * mult
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
                mult = TODAY_FACTOR[0] if prefix == "d" else 1.0
                qty, sales, stock = slice_forecast(mv_qty_now, sales_mv_now, safety_mv_now, horizon, days, mult)
                now_pairs.update({f"{prefix}_qty": qty, f"{prefix}_sales": sales, f"{prefix}_safety": max(stock - qty, 0), f"{prefix}_stock": stock})
                qty, sales, stock = slice_forecast(mv_qty_then, sales_then, safety_then, then_horizon, then_days, mult)
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
            "Rank": int(row["peringkat"]),
            "SKU": cells["sku"]["t"],
            "Produk": cells["name"]["t"],
            "Varian": cells["variance"]["t"],
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
            # Total memakai nilai harapan untuk QTY/sales harian & bulanan (pembulatan per SKU membuat SKU lambat laku = 0).
            totals[name] = totals.get(name, 0.0) + float(expected.get(name, value))
            label = f"{column['group']} - {column['label']}"
            export[label] = int(round(value))
            if name in then_values:
                export[f"{label} (perubahan)"] = int(round(value - then_values[name]))
        rows.append({"key": str(row["item_key"]), "cells": cells})
        export_rows.append(export)

    total: dict[str, dict] = {
        "name": {"t": "Total", "s": f"{len(rows)} item"},
    }
    total_export = {"Rank": "", "SKU": "", "Produk": "Total", "Varian": ""}
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
    excel_toolbar(export_frame, "top50_item_terlaris.xlsx")
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
    return picked if picked in keys else ""


def excel_bytes(frame: pd.DataFrame) -> bytes:
    return numeric_excel_bytes(frame)


def offer_excel(frame: pd.DataFrame, filename: str) -> None:
    """Unduh tabel yang sedang ditampilkan sebagai file Excel (ringkas bila berada di bilah navigasi tabel)."""
    if not isinstance(frame, pd.DataFrame):
        return
    safe = filename if str(filename).endswith(".xlsx") else f"{filename}.xlsx"
    download_excel(frame, safe, key=f"excel-{safe}")


def excel_toolbar(frame: pd.DataFrame, filename: str, *, caption: str = "") -> None:
    """Tombol Excel ringkas di atas tabel (kanan), sejajar keterangan tabel."""
    if isinstance(frame, pd.DataFrame):
        table_toolbar(lambda: offer_excel(frame, filename), key=f"tb-{filename}", caption=caption)


def table_column_config(frame: pd.DataFrame, *, roomy: bool = False) -> dict:
    """Kolom nama cukup lebar supaya nama produk dan SKU tidak terpotong."""
    config = {}
    for column in frame.columns:
        if column in {"Produk", "Variasi", "Referensi SKU", "Item", "SKU", "Varian"}:
            continue
        if not pd.api.types.is_numeric_dtype(frame[column]):
            continue
        if roomy:
            width = 120 if column == "Rank" else 200
            config[column] = st.column_config.NumberColumn(column, format="localized", step=1, width=width)
        else:
            config[column] = st.column_config.NumberColumn(column, format="localized", step=1)
    widths = {
        "SKU": 220,
        "Produk": 780 if roomy else 640,
        "Varian": 280,
        "Variasi": 320 if roomy else 260,
        "Referensi SKU": 260 if roomy else 220,
        "Item": 780 if roomy else 640,
        "Alasan batal": 460,
        "Status retur": 280,
        "Alasan pembatalan": 520,
        "Status batal": 180,
        "Status pesanan": 220,
        "Nama akun pembeli": 240,
        "Nama produk": 420,
        "No. Pesanan": 220,
        "Tanggal pembelian": 160,
        "Kontribusi": 140,
        "Target (Rp)": 150,
        "Pencapaian target": 250,
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
        start_kwargs = {"min_value": span_min, "max_value": span_max, "key": start_widget, "format": "DD/MM/YYYY"}
        end_kwargs = {"min_value": span_min, "max_value": span_max, "key": end_widget, "format": "DD/MM/YYYY"}
        if start_widget not in st.session_state:
            start_kwargs["value"] = span_min
        if end_widget not in st.session_state:
            end_kwargs["value"] = span_max
        start = _as_date(date_col.date_input("Tanggal mulai", **start_kwargs)) or span_min
        end = _as_date(date_col_end.date_input("Tanggal selesai", **end_kwargs)) or span_max
        if start > end:
            start, end = end, start
        if show_exclude:
            if "train-exclude" not in st.session_state:
                st.session_state["train-exclude"] = training_exclude()
            st.checkbox("Kecualikan batal & retur", key="train-exclude", on_change=lambda: save_training_exclude(bool(st.session_state.get("train-exclude"))))
            st.markdown(
                "<div class='field-hint'>Setelan tersimpan untuk setiap analisa baru.<br>• Aktif: pesanan batal & unit retur tidak ikut dilatih (permintaan bersih).<br>"
                "• Membuka analisa lama tidak mengubah setelan ini.</div>",
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
    # Sales = nilai harapan (prediksi sales × hari ÷ horizon) agar SKU yang laku < 1 unit/hari tidak hilang dari total.
    horizon = frame["slice_horizon_days"].clip(lower=1) if "slice_horizon_days" in frame.columns else None
    if horizon is not None and "pred_sales" in frame.columns:
        month = frame["slice_month_days"] if "slice_month_days" in frame.columns else 30
        factor = frame["slice_day_factor"] if "slice_day_factor" in frame.columns else 1.0
        sales_day = float((frame["pred_sales"] / horizon * factor).sum())
        sales_month = float((frame["pred_sales"] * month / horizon).sum())
    else:
        sales_day, sales_month = float(frame["pred_sales_hari"].sum()), float(frame["pred_sales_bulan"].sum())
    return (
        int(round(sales_day)),
        int(frame["stok_hari"].sum()),
        int(round(sales_month)),
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
    """Prediksi (Level terkini → ensemble dengan bobot tersimpan) pada satu tanggal, dari data latih sebelum tanggal itu. Rumus tidak diubah."""
    trimmed = _history_before(history, as_of)
    if trimmed.empty:
        return frame_from_stock(None)
    analysis = st.session_state.get("analysis", {})
    orders = analysis.get("orders")
    if isinstance(orders, pd.DataFrame) and not orders.empty:
        orders = orders.loc[pd.to_datetime(orders["order_time"]) < pd.Timestamp(as_of)]
    _combined, priced, _outcome = build_forecast(
        trimmed,
        orders,
        period=period,
        as_of=as_of,
        service=service,
        params=current_params(),
        weights=analysis.get("ensemble_weights"),
    )
    return frame_from_stock(priced)


def stock_for_combined(base_history: pd.DataFrame, combined: pd.DataFrame, *, period: str, as_of: date, service: int, params: dict,
                       weights: dict | None = None) -> pd.DataFrame:
    """Safety stock dari parameter bisnis: lead time lokal, variasi lead time, atau impor; σ dikali faktor kalibrasi walk-forward."""
    from src.core.inventory import lead_time_days
    from src.core.service_level import abc_by_qty, class_service_levels
    from src.models.evaluate import SS_CALIBRATION_KEY

    lead = params.get("lead_time", {})
    impor = bool(lead.get("impor_aktif", False))
    levels = class_service_levels(service, params)
    per_item = {key: levels[label] for key, label in abc_by_qty(base_history).items()}
    return recommend_stock(
        base_history,
        combined,
        "hari",
        service_level_z=service_z(service),
        horizon_steps=horizon_day_count(period, as_of),
        service_level_pct=service,
        lead_time_days=lead_time_days(params),
        lead_time_sigma=float(lead.get("lokal_sigma_hari", 0) or 0),
        source_type="import" if impor else "local",
        lead_time_max=float(lead.get("impor_maks_hari", 90)) if impor else None,
        review_days=float(lead.get("review_hari", 7) or 0),
        sigma_scale=float((weights or {}).get(SS_CALIBRATION_KEY, 1.0) or 1.0),
        item_service_pct=per_item,
    )


def build_forecast(
    base_history: pd.DataFrame,
    orders: pd.DataFrame | None,
    *,
    period: str,
    as_of: date,
    service: int,
    params: dict,
    weights: dict | None = None,
    evaluate: bool = False,
    zero_since: dict | None = None,
    progress=None,
):
    """Satu jalur prediksi: Level terkini → ensemble (bila ada bobot/evaluasi) → harga 4 minggu → safety stock."""
    horizon = horizon_day_count(period, as_of)
    _start, _end, text = forecast_window(period, as_of)
    qty_fc = forecast_items(
        base_history,
        "hari",
        "qty",
        steps=horizon,
        next_label=text,
        forecast_start=pd.Timestamp(as_of),
        progress_callback=(lambda pct: progress(pct * 0.3, "Level terkini per SKU")) if progress else None,
    )
    outcome = None
    if qty_fc is not None and not qty_fc.empty:
        try:
            if evaluate:
                outcome = run_demand_models(
                    base_history,
                    horizon=horizon,
                    zero_since=zero_since,
                    progress=(lambda pct, label: progress(0.3 + pct * 0.6, label)) if progress else None,
                )
            elif weights:
                outcome = outcome_with_weights(base_history, horizon=horizon, weights=weights, zero_since=zero_since)
            if outcome is not None:
                qty_fc = apply_ensemble(qty_fc, outcome)
        except Exception as exc:  # model tambahan gagal: tetap jalan dengan Level terkini
            st.session_state["ensemble-error"] = str(exc)
            outcome = None
    if qty_fc is None or qty_fc.empty:
        return pd.DataFrame(), frame_from_stock(None), None
    sales_fc = forecast_revenue(base_history, qty_fc, "hari", steps=horizon, next_label=text)
    combined = combine_forecasts(qty_fc, sales_fc)
    if isinstance(orders, pd.DataFrame) and not orders.empty:
        combined = apply_recent_price(combined, orders, today=as_of)
    stock = stock_for_combined(base_history, combined, period=period, as_of=as_of, service=service, params=params,
                               weights=outcome.weights if outcome is not None else weights)
    return combined, stock, outcome


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
    with st.spinner(f"Menghitung prediksi {format_id_date(as_of)} dari data latih. Rumus prediksi tidak diubah."):
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


def _delta_text(now: float, then: float, *, money: bool) -> str:
    delta = round(float(now)) - round(float(then))
    amount = format_idr(abs(delta)) if money else format_qty(abs(delta))
    if delta == 0:
        return "0 (0%)"
    sign = "+" if delta > 0 else "−"
    if then == 0:
        return f"{sign}{amount}"
    percent = delta / then * 100
    percent_sign = "+" if percent > 0 else "−"
    return f"{sign}{amount} ({percent_sign}{format_number(abs(percent), 1)}%)"


def _move_line(now: float, then: float | None, *, money: bool, fresh: bool = False) -> str:
    if fresh:
        return (
            "<div class='metric-move flat'><span style='display:inline-block;padding:1px 8px;border-radius:999px;"
            "background:#e0e7ff;color:#3730a3;font-weight:700'>periode baru</span> target periode berbeda dari prediksi kemarin</div>"
        )
    if then is None:
        return "<div class='metric-move flat'>Data latih sebelum hari ini belum cukup untuk dihitung.</div>"
    text = _delta_text(now, then, money=money)
    tone = "flat" if text.startswith("0 ") else ("up" if float(now) > float(then) else "down")
    before = format_idr(then) if money else f"{format_number(round(float(then)), 0)} unit"
    # Nilai pembanding ditulis langsung agar user tidak perlu menghitung dari persentase.
    return f"<div class='metric-move {tone}'>{html.escape(text)} dibanding prediksi kemarin <b>{html.escape(before)}</b></div>"


def _prediction_card(column, label: str, value: str, move_html: str, *, tip: str = "", extra_html: str = "") -> None:
    info = f" <span title='{html.escape(tip, quote=True)}' style='cursor:help;color:#64748b'>ⓘ</span>" if tip else ""
    column.markdown(
        "<div class='stat-card'>"
        f"<div class='readable-metric-label'>{html.escape(label)}{info}</div>"
        f"<div class='readable-metric-value'>{html.escape(value)}</div>"
        "<div class='metric-hint'>Hasil prediksi</div>"
        f"{extra_html}{move_html}"
        "</div>",
        unsafe_allow_html=True,
    )


def actual_on_day(orders: pd.DataFrame | None, keys: list[str], day: date) -> tuple[float, date | None]:
    """QTY aktual Top 50 pada `day` (WIB). Bila hari itu belum ada transaksi atau datanya belum sampai 23:00, pakai hari penuh terakhir sebelum `day`."""
    if orders is None or orders.empty or not keys:
        return 0.0, None
    from src.ui.month_track_view import full_day_cutoff

    stamp = pd.to_datetime(orders["order_time"], errors="coerce").max()
    if pd.notna(stamp):
        day = min(day, full_day_cutoff(stamp))
    work = orders.loc[orders["item_key"].astype(str).isin(set(keys))]
    if work.empty:
        return 0.0, None
    days = pd.to_datetime(work["order_time"], errors="coerce").dt.date
    eligible = days[days <= day]
    if eligible.empty:
        return 0.0, None
    pick = day if (eligible == day).any() else eligible.max()
    return float(pd.to_numeric(work.loc[days == pick, "qty"], errors="coerce").sum()), pick


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
    qty_day, sales_day, stock_day = slice_forecast(row["pred_qty"], row["pred_sales"], safety, horizon_days, 1, TODAY_FACTOR[0])
    qty_month, sales_month, stock_month = slice_forecast(
        row["pred_qty"], row["pred_sales"], safety, horizon_days, month_days
    )
    return qty_day, sales_day, max(stock_day - qty_day, 0), qty_month, sales_month, max(stock_month - qty_month, 0)


MONTHS_ID_SHORT_TEXT = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")


def _daily_rate(row: pd.Series | None, horizon_days: int) -> tuple[float, float]:
    """(laju QTY/hari, laju sales produk/hari) dari prediksi horizon analisa."""
    if row is None or horizon_days <= 0:
        return 0.0, 0.0
    return float(row.get("pred_qty", 0) or 0) / horizon_days, float(row.get("pred_sales", 0) or 0) / horizon_days


def _running_month_actuals(orders: pd.DataFrame | None, orders_all: pd.DataFrame | None, today: date) -> tuple[dict, float, date]:
    """({item_key: (QTY, sales produk) tgl 1 s.d. hari penuh terakhir}, jumlah pola hari sisa bulan, hari penuh terakhir).

    Aturan sama dengan kartu Prediksi bulan berjalan (`dashboard.running_month_parts`)."""
    from src.ui.month_track_view import month_remaining_weight

    cutoff, weight = month_remaining_weight(orders_all if orders_all is not None else orders, today)
    first = today.replace(day=1)
    actual: dict = {}
    if orders is not None and not orders.empty and cutoff >= first:
        days = pd.to_datetime(orders["order_time"], errors="coerce").dt.date
        part = orders.loc[(days >= first) & (days <= cutoff)]
        if not part.empty:
            sales = part["sales"] if "sales" in part.columns else pd.Series(0.0, index=part.index)
            grouped = pd.DataFrame({"k": part["item_key"].astype(str), "q": part["qty"].astype(float), "s": sales.astype(float)}).groupby("k")[["q", "s"]].sum()
            actual = {k: (float(r.q), float(r.s)) for k, r in grouped.iterrows()}
    return actual, weight, cutoff


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
    decision: dict | None = None,
    orders: pd.DataFrame | None = None,
    orders_all: pd.DataFrame | None = None,
) -> pd.DataFrame:
    decision = decision or {}
    run_actual, rest_weight, run_cutoff = _running_month_actuals(orders, orders_all, today)
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
        enriched = decision.get(key)
        if enriched is not None:
            qty_day, sales_day = int(enriched["d_qty"]), int(enriched["d_sales"])
            qty_month, sales_month = int(enriched["m_qty"]), int(enriched["m_sales"])
            safety_day = safety_month = int(enriched["ss"])
            rate_q = float(enriched.get("pred_harian", 0) or 0)
            rate_s = rate_q * float(enriched.get("harga_bersih", 0) or 0)
        else:
            rate_q, rate_s = _daily_rate(locked_row, locked_horizon)
        from_q, from_s = _daily_rate(start_row, start_horizon)
        to_q, to_s = _daily_rate(end_row, end_horizon)
        act_q, act_s = run_actual.get(key, (0.0, 0.0))
        records.append(
            {
                "key": key,
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
                "run_qty": act_q + rate_q * rest_weight,
                "run_sales": act_s + rate_s * rest_weight,
                "run_qty_act": act_q,
                "run_sales_act": act_s,
                "run_qty_then": act_q + from_q * rest_weight,
                "run_qty_now": act_q + to_q * rest_weight,
                "run_sales_then": act_s + from_s * rest_weight,
                "run_sales_now": act_s + to_s * rest_weight,
                "move_qty": qty_to - qty_from,
            }
        )
    records = [item for item in records if _prediction_moved(item)]
    if not records:
        return pd.DataFrame()
    # Prioritas omzet: besar perubahan prediksi bulan dalam sales value (Rp) dan QTY, keduanya diskalakan 0–1
    # terhadap perubahan terbesar lalu dirata-rata; seri dipecah oleh perubahan hari ini lalu Rank.
    def _scaled(values: list[float]) -> list[float]:
        top = max(values) if values else 0.0
        return [value / top if top > 0 else 0.0 for value in values]

    sales_moves = _scaled([abs(item["sales_month_now"] - item["sales_month_then"]) for item in records])
    qty_moves = _scaled([abs(item["qty_month_now"] - item["qty_month_then"]) for item in records])
    day_sales = _scaled([abs(item["sales_day_now"] - item["sales_day_then"]) for item in records])
    day_qty = _scaled([abs(item["qty_day_now"] - item["qty_day_then"]) for item in records])
    for item, a, b, c, d in zip(records, sales_moves, qty_moves, day_sales, day_qty):
        item["_impact"] = 0.5 * a + 0.5 * b
        item["_impact_day"] = 0.5 * c + 0.5 * d
    records.sort(key=lambda item: (-item["_impact"], -item["_impact_day"], item["rank"], item["sku"]))

    month_label = format_period_label("prediksi", today)
    g_day, g_month, g_sold = "Prediksi hari ini", month_label, "Penjualan"
    g_run = f"Prediksi bulan berjalan ({month_year(today)})"
    g_stock = "Stok"
    columns = [
        {"id": "rank", "label": "Rank", "pin": True, "width": 76, "kind": "num", "sort": True},
        {"id": "sku", "label": "SKU", "pin": True, "width": 112, "sort": True},
        {"id": "name", "label": "Produk", "pin": True, "width": 260, "kind": "name", "sort": True},
        {"id": "variance", "label": "Varian", "width": 150, "kind": "name", "sort": True},
        {"id": "d_sales", "label": "Sales produk", "group": g_day, "kind": "num", "sort": True},
        {"id": "d_qty", "label": "QTY · SS", "group": g_day, "kind": "num", "sort": True},
        {"id": "r_sales", "label": "Sales produk", "group": g_run, "kind": "num", "sort": True},
        {"id": "r_qty", "label": "QTY", "group": g_run, "kind": "num", "sort": True},
        {"id": "m_sales", "label": "Sales produk", "group": g_month, "kind": "num", "sort": True},
        {"id": "m_qty", "label": "QTY · SS", "group": g_month, "kind": "num", "sort": True},
        {"id": "stok_d", "label": "Site 10037 · hari ini", "group": g_stock, "kind": "num", "sort": True},
        {"id": "stok_m", "label": f"Site 10037 · {month_year(today)}", "group": g_stock, "kind": "num", "sort": True},
        {"id": "stok_10062", "label": "Site 10062", "group": g_stock, "kind": "num", "sort": True},
        {"id": "stok_10036", "label": "Site 10036", "group": g_stock, "kind": "num", "sort": True},
        {"id": "ambil_dc", "label": "Ambil dari DC", "group": g_stock, "width": 220, "kind": "name", "sort": True},
        {"id": "kosong", "label": "Lama kosong", "group": g_stock, "width": 120, "sort": True},
        {"id": "sold_sales", "label": "Sales produk", "group": g_sold, "kind": "num", "sort": True},
        {"id": "sold_qty", "label": "QTY", "group": g_sold, "kind": "num", "sort": True},
    ]
    month_short = MONTHS_ID_SHORT_TEXT[today.month - 1]
    act_span = f"aktual 1–{run_cutoff.day} {month_short}" if run_cutoff >= today.replace(day=1) else "belum ada aktual"

    def money_cell(value: float, now: float | None = None, then: float | None = None, note: str | None = None) -> dict:
        cell = {"v": float(value), "t": format_idr(value)}
        if now is not None and then is not None:
            cell["d"], cell["dc"] = _move_cell(now, then, money=True)
        if note:
            cell["s"] = note
        return cell

    def qty_cell(value: float, safety: float | None, now: float | None = None, then: float | None = None) -> dict:
        cell = {"v": float(value), "t": format_qty(value)}
        if safety is not None:
            cell["s"] = f"Safety stock {format_qty(safety)}"
        if now is not None and then is not None:
            cell["d"], cell["dc"] = _move_cell(now, then, money=False)
        return cell

    def run_qty_cell(value: float, actual: float, now: float, then: float) -> dict:
        cell = {"v": float(value), "t": format_number(round(value), 0), "s": f"{act_span}: {format_number(round(actual), 0)}"}
        cell["d"], cell["dc"] = _move_cell(now, then, money=False)
        return cell

    def stock_cell(row, prefix: str) -> dict:
        if row is None or not bool(row.get("ada_data_stok", False)):
            return {"v": -1, "t": "–", "s": "belum ada data stok"}
        gap = float(row[f"{prefix}_selisih"])
        status = str(row[f"{prefix}_status"]).split(" · ")[0]
        sign = "+" if gap > 0 else ("−" if gap < 0 else "")
        return {"v": float(row["stok"]), "t": format_qty(float(row["stok"])), "d": f"{sign}{format_qty(abs(gap))} · {status}", "dc": "up" if gap >= 0 else "down"}

    def dc_cell(row, code: str) -> dict:
        value = None if row is None else row.get(f"stok_{code}")
        if value is None or pd.isna(value):
            return {"v": -1, "t": "–"}
        return {"v": float(value), "t": format_qty(float(value))}

    rows, export_rows = [], []
    for item in records:
        row = decision.get(item["key"])
        has_stock = row is not None and bool(row.get("ada_data_stok", False))
        transfer = str(row.get("sumber_restock") or "") if row is not None else ""
        cells = {
            "rank": {"v": item["rank"], "t": format_number(item["rank"], 0)},
            "sku": {"v": item["sku"], "t": item["sku"]},
            "name": {"v": item["product"], "t": item["product"]},
            "variance": {"v": item["variance"], "t": item["variance"]},
            "d_sales": money_cell(item["sales_day"], item["sales_day_now"], item["sales_day_then"]),
            "d_qty": qty_cell(item["qty_day"], item["safety_day"], item["qty_day_now"], item["qty_day_then"]),
            "r_sales": money_cell(item["run_sales"], item["run_sales_now"], item["run_sales_then"], f"{act_span}: {format_idr(item['run_sales_act'])}"),
            "r_qty": run_qty_cell(item["run_qty"], item["run_qty_act"], item["run_qty_now"], item["run_qty_then"]),
            "m_sales": money_cell(item["sales_month"], item["sales_month_now"], item["sales_month_then"]),
            "m_qty": qty_cell(item["qty_month"], item["safety_month"], item["qty_month_now"], item["qty_month_then"]),
            "stok_d": stock_cell(row, "d"),
            "stok_m": stock_cell(row, "m"),
            "stok_10062": dc_cell(row, "10062"),
            "stok_10036": dc_cell(row, "10036"),
            "ambil_dc": {"v": transfer, "t": transfer or "–"},
            "kosong": {"v": lama_kosong_text(row) if row is not None else "-", "t": lama_kosong_text(row) if row is not None else "-"},
            "sold_sales": money_cell(item["sold_sales"]),
            "sold_qty": qty_cell(item["sold_qty"], None),
        }
        rows.append({"key": item["key"], "cells": cells})
        export_rows.append(
            {
                "Rank": item["rank"],
                "SKU": item["sku"],
                "Produk": item["product"],
                "Varian": item["variance"],
                "Penjualan sales": item["sold_sales"],
                "Penjualan qty": item["sold_qty"],
                "Prediksi sales hari ini": item["sales_day"],
                "Prediksi qty hari ini": item["qty_day"],
                "Safety stock hari ini": item["safety_day"],
                "Perubahan sales hari ini": item["sales_day_now"] - item["sales_day_then"],
                "Perubahan qty hari ini": item["qty_day_now"] - item["qty_day_then"],
                f"Prediksi sales produk bulan berjalan ({month_year(today)})": round(item["run_sales"]),
                f"Aktual sales produk ({act_span.removeprefix('aktual ')})": round(item["run_sales_act"]),
                f"Prediksi qty bulan berjalan ({month_year(today)})": round(item["run_qty"]),
                f"Aktual qty ({act_span.removeprefix('aktual ')})": round(item["run_qty_act"]),
                "Prediksi sales bulan ini": item["sales_month"],
                "Prediksi qty bulan ini": item["qty_month"],
                "Safety stock bulan ini": item["safety_month"],
                "Perubahan sales bulan ini": item["sales_month_now"] - item["sales_month_then"],
                "Perubahan qty bulan ini": item["qty_month_now"] - item["qty_month_then"],
                "Stok Site 10037": float(row["stok"]) if has_stock else None,
                "Selisih stok hari ini": float(row["d_selisih"]) if has_stock else None,
                "Selisih stok bulan ini": float(row["m_selisih"]) if has_stock else None,
                "Stok Site 10062": dc_cell(row, "10062")["v"] if dc_cell(row, "10062")["v"] >= 0 else None,
                "Stok Site 10036": dc_cell(row, "10036")["v"] if dc_cell(row, "10036")["v"] >= 0 else None,
                "Ambil dari DC": transfer,
                "Lama kosong": lama_kosong_text(row) if row is not None else "-",
            }
        )

    def total(key: str) -> int:
        return sum(int(item[key]) for item in records)

    def fsum(key: str) -> float:
        return float(sum(float(item[key]) for item in records))

    stock_total = sum(float(decision[item["key"]]["stok"]) for item in records if item["key"] in decision and bool(decision[item["key"]].get("ada_data_stok", False)))
    dc_totals = {
        code: sum(float(decision[item["key"]].get(f"stok_{code}") or 0) for item in records if item["key"] in decision and pd.notna(decision[item["key"]].get(f"stok_{code}")))
        for code in ("10062", "10036")
    }
    total_row = {
        "name": {"t": "Total", "s": f"{len(records)} item bergerak"},
        "d_sales": money_cell(total("sales_day"), total("sales_day_now"), total("sales_day_then")),
        "d_qty": qty_cell(total("qty_day"), total("safety_day"), total("qty_day_now"), total("qty_day_then")),
        "r_sales": money_cell(fsum("run_sales"), fsum("run_sales_now"), fsum("run_sales_then"), f"{act_span}: {format_idr(fsum('run_sales_act'))}"),
        "r_qty": run_qty_cell(fsum("run_qty"), fsum("run_qty_act"), fsum("run_qty_now"), fsum("run_qty_then")),
        "m_sales": money_cell(total("sales_month"), total("sales_month_now"), total("sales_month_then")),
        "m_qty": qty_cell(total("qty_month"), total("safety_month"), total("qty_month_now"), total("qty_month_then")),
        "stok_d": {"t": format_qty(stock_total)},
        "stok_m": {"t": format_qty(stock_total)},
        "stok_10062": {"t": format_qty(dc_totals["10062"])},
        "stok_10036": {"t": format_qty(dc_totals["10036"])},
        "sold_sales": money_cell(total("sold_sales")),
        "sold_qty": qty_cell(total("sold_qty"), None),
    }
    _TOP50_TABLE(
        columns=columns, rows=rows, total=total_row, selected="", height=620, sort="", key="movement-top50", default="",
        limit=0, batch={"first": MOVEMENT_STEP, "step": 10, "noun": "SKU"},
        download=excel_payload(pd.DataFrame(export_rows), "pergerakan_top50.xlsx") if export_rows else None,
    )
    return pd.DataFrame(export_rows)


def _period_totals(frame: pd.DataFrame | None, keys: list[str], *, period: str, day: date, orders: pd.DataFrame | None,
                   day_factor: float = 1.0) -> dict[str, tuple[float, float]] | None:
    """Total prediksi sales dan kebutuhan stok (prediksi + SS) per kelompok periode untuk SKU `keys`."""
    if frame is None or frame.empty or "item_key" not in frame.columns:
        return None
    work = frame.loc[frame["item_key"].astype(str).isin(set(keys))]
    if work.empty:
        return None
    table = build_decision_table(work, period=period, today=day, horizon_days=horizon_day_count(period, day), orders=orders, day_factor=day_factor)
    return _group_totals(table, period, day)


def _group_totals(table: pd.DataFrame, period: str, day: date) -> dict[str, tuple[float, float, float]]:
    """Total banyak SKU memakai nilai harapan (sebelum dibulatkan per SKU), lihat decision_table."""
    def col(name: str, prefix: str) -> pd.Series:
        exp = f"{prefix}_{name}_exp"
        return table[exp] if exp in table.columns else table[f"{prefix}_{name}"]

    return {
        g.prefix: (float(col("qty", g.prefix).sum()), float(col("sales", g.prefix).sum()), float(table[f"{g.prefix}_butuh"].sum()))
        for g in period_groups(period, day)
    }


SS_DEFINITION_MOVEMENT = "safety stock adalah nilai cadangan yang harus disiapkan agar tidak kehabisan stok"


def _today_factor(orders_all: pd.DataFrame | None, today: date, day: date | None = None) -> float:
    """Pola hari ini (rata-rata sebulan = 1), sama dengan Pantauan harian; 1 bila belum bisa dihitung."""
    try:
        from src.ui.month_track_view import day_multiplier

        return day_multiplier(orders_all, day or today, today)
    except Exception:
        return 1.0


def _today_pattern_hint(orders_all: pd.DataFrame | None, today: date, day_sales: float) -> str:
    """Asal angka hari ini: laju rata-rata × pola hari ini (sama dengan Pantauan harian & breakdown per tanggal)."""
    mult = _today_factor(orders_all, today)
    if day_sales <= 0 or abs(mult - 1.0) < 0.005:
        return ""
    from src.core.month_track import day_label

    label = day_label(today) or "pola hari"
    return (f"<br>laju rata-rata {html.escape(format_idr(day_sales / mult))}/hari × {html.escape(label)} ×{format_number(mult, 2)} · "
            "sales produk; Pantauan harian = angka ini × faktor sales bersih")


def _running_month_cards(decision: pd.DataFrame, all_sku: pd.DataFrame | None, orders, orders_all, today: date,
                         prior: dict | None, day_factor: float, metric: str) -> None:
    """Baris kartu bulan berjalan: aktual tgl 1 s.d. hari penuh terakhir + laju prediksi × pola sisa hari (sama dengan Ringkasan)."""
    from src.ui.dashboard import MONTHS_SHORT, running_month_hint, running_month_parts

    top = running_month_parts(decision, orders, orders_all, today)
    name = f"bulan berjalan ({MONTHS_SHORT[today.month - 1]} {today.year})"
    then_rate = None
    if prior and prior.get("d") and day_factor > 0:
        then_rate = (float(prior["d"][0]) / day_factor, float(prior["d"][1]) / day_factor)
    tip = ("Aktual tgl 1 s.d. hari penuh terakhir (data ≥ 23:00) + laju prediksi harian × pola hari sisa bulan "
           "(hari dalam minggu, gajian, tanggal kembar; sama dengan Pantauan harian). Pembanding: aktual yang sama + laju prediksi kemarin. "
           "Sales = sales produk (Harga Setelah Diskon × QTY terjual, dasar prediksi), bukan sales bersih (Total Pembayaran, dasar target) "
           "di kartu Sales bersih; sales bersih lebih kecil karena sudah dipotong voucher.")
    qty_now = top["actual_qty"] + top["rest_qty"]
    sales_now = top["actual_sales"] + top["rest_sales"]
    qty_then = None if then_rate is None else top["actual_qty"] + then_rate[0] * top["weight"]
    sales_then = None if then_rate is None else top["actual_sales"] + then_rate[1] * top["weight"]
    qty_hint = f"<div class='metric-move flat'>{html.escape(running_month_hint(top, top['actual_qty'], top['rest_qty'], lambda v: format_number(round(v), 0), 'aktual terjual'))}</div>"
    sales_hint = f"<div class='metric-move flat'>{html.escape(running_month_hint(top, top['actual_sales'], top['rest_sales'], format_idr, 'aktual sales produk'))}</div>"
    st.markdown(f"<div class='field-hint' style='margin-top:.4rem'><b>Prediksi {html.escape(name)}</b></div>", unsafe_allow_html=True)
    cards = st.columns(4)
    money_first = metric == "sales"
    order = [("sales", sales_now, sales_then, sales_hint), ("qty", qty_now, qty_then, qty_hint)]
    if not money_first:
        order.reverse()
    for column, (kind, now, then, hint) in zip(cards[:2], order):
        money = kind == "sales"
        _prediction_card(
            column,
            f"Prediksi {'sales' if money else 'QTY'} {name} · Top 50 SKU",
            format_idr(now) if money else f"{format_number(round(now), 0)} unit",
            _move_line(now, then, money=money),
            tip=tip,
            extra_html=hint,
        )
    if all_sku is not None and not all_sku.empty:
        whole = running_month_parts(all_sku, orders, orders_all, today, all_items=True)
        total = whole["actual_sales"] + whole["rest_sales"]
        cards[3].markdown(
            "<div class='stat-card'>"
            f"<div class='readable-metric-label'>Prediksi sales produk {html.escape(name)} · All SKU</div>"
            f"<div class='readable-metric-value'>{html.escape(format_idr(total))}</div>"
            f"<div class='metric-hint'>{html.escape(running_month_hint(whole, whole['actual_sales'], whole['rest_sales'], format_idr, 'aktual sales produk'))}"
            " · seluruh toko" + _net_month_hint(orders_all if orders_all is not None else orders) + "</div>"
            "</div>",
            unsafe_allow_html=True,
        )


def _net_month_hint(orders_all) -> str:
    """Padanan sales bersih (dasar target) untuk kartu sales produk bulan berjalan; sama dengan kartu Sales bersih & Pantauan harian."""
    try:
        from src.ui.dashboard import MONTHS_SHORT
        from src.ui.targets_view import month_outlook

        out = month_outlook(orders_all, get_features())
    except Exception:
        return ""
    if not out.get("running") or out.get("mtd", 0) <= 0:
        return ""
    last = out["last"]
    return ("<br><b>Dalam sales bersih (dasar target)</b>: "
            f"aktual 1–{last.day} {MONTHS_SHORT[last.month - 1]} {html.escape(format_idr(out['mtd']))} "
            f"(= Pencapaian di kartu Sales bersih) → proyeksi akhir bulan {html.escape(format_idr(out['projection']))} "
            f"(= Pantauan harian). Sales bersih ≈ {format_number(out['faktor'], 2)} × sales produk, "
            "terutama karena sudah dipotong voucher & koin.")


def show_analysis_movement(
    stock: pd.DataFrame,
    current_meta: dict,
    metric: str,
    focus_keys: list[str],
    catalog: pd.DataFrame,
    decision: pd.DataFrame | None,
    orders: pd.DataFrame | None,
    history: pd.DataFrame | None = None,
    service: int = 0,
    source_key: str = "",
    used_default_lead: bool = True,
    orders_all: pd.DataFrame | None = None,
) -> pd.DataFrame | None:
    """R3 (kartu pergerakan per periode) dan R4 (Pergerakan Top 50)."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    period_key = str(current_meta.get("period") or "bulan")
    groups = period_groups(period_key, today)
    keys = catalog["item_key"].astype(str).tolist() if isinstance(catalog, pd.DataFrame) and not catalog.empty else []
    frame_args = dict(
        live_stock=stock,
        live_day=today,
        history=history,
        period=period_key,
        service=int(current_meta.get("service", service) or 0),
        source_key=source_key,
    )
    now_totals = None
    if isinstance(decision, pd.DataFrame) and not decision.empty:
        now_totals = _group_totals(decision, period_key, today)
    prior_frame = _movement_frame(yesterday, **frame_args)
    # Pembanding harus SKU yang sama dengan kartu (Top 50), bukan seluruh katalog.
    day_factor = _today_factor(orders_all if orders_all is not None else orders, today)
    prior = _period_totals(prior_frame, list(focus_keys) or keys, period=period_key, day=today, orders=orders, day_factor=day_factor)
    st.markdown("<div class='section-title'>Pergerakan dari analisa sebelumnya</div>", unsafe_allow_html=True)
    explain(
        [
            ("Setelan", f"{'QTY terjual' if metric == 'qty' else 'Sales value'} · safety stock {int(current_meta.get('service', service) or 0)}%"),
            ("Pembanding", f"prediksi kemarin ({format_id_date(yesterday)}) untuk {format_number(len(focus_keys))} SKU Top 50 yang sama"),
            ("Cara hitung pembanding", "data latih s.d. sehari sebelumnya, parameter sama"),
            ("Total banyak SKU", "dijumlah dari nilai harapan sebelum dibulatkan per SKU"),
            ("Sales di bagian ini", "sales produk = Harga Setelah Diskon × QTY (dasar prediksi). Berbeda dengan kartu Sales bersih di atas "
             "(Total Pembayaran − batal − Belum Bayar − retur, sudah dipotong voucher; dasar target), jadi angkanya lebih besar"),
        ]
    )
    if now_totals:
        all_sku = catalog if isinstance(catalog, pd.DataFrame) and not catalog.empty else None
        actual_qty, actual_day = actual_on_day(orders, focus_keys, yesterday)
        for group in groups:
            qty_now, sales_now, need_now = now_totals[group.prefix]
            fresh = group.prefix != "d" and not same_target(yesterday, period_key, today, period_key)
            then = None if fresh else (prior.get(group.prefix) if prior else None)
            if group.extra:
                st.markdown(f"<div class='field-hint' style='margin-top:.4rem'><b>{html.escape(group.label)}</b></div>", unsafe_allow_html=True)
            cards = st.columns(4)
            name = "hari ini" if group.prefix == "d" else (group.label.removeprefix("Prediksi ") if group.prefix == "m" else group.label)
            is_day = group.prefix == "d"
            main_money = metric == "sales"
            main_now = sales_now if main_money else qty_now
            main_then = None if then is None else float(then[1] if main_money else then[0])
            qty_label = "QTY terjual" if is_day else "QTY"
            day_tip = (
                "Prediksi QTY hari ini = jumlah nilai harapan per SKU (prediksi QTY horizon ÷ jumlah hari horizon × pola hari ini) sebelum dibulatkan, "
                "sales = nilai harapan × harga bersih. Pola hari ini sama dengan Pantauan harian dan breakdown per tanggal (hari dalam minggu, gajian, "
                "tanggal kembar). Tabel per SKU dan Kebutuhan stok memakai unit utuh (dibulatkan ke bawah per SKU), jadi totalnya bisa lebih kecil. "
                "Tanggal mengikuti WIB (Asia/Jakarta). Hari ini masih berjalan, jadi pembanding yang adil adalah aktual hari penuh terakhir (kemarin)."
            ) if is_day else ""
            actual_html = ""
            if is_day:
                if actual_day is None:
                    actual_html = "<div class='metric-move flat'>Aktual terjual kemarin: belum ada transaksi</div>"
                else:
                    gap = (qty_now - actual_qty) / actual_qty * 100 if actual_qty > 0 else None
                    when = "kemarin" if actual_day == yesterday else format_id_date(actual_day) + " (hari penuh terakhir)"
                    gap_text = f" · selisih {'+' if gap >= 0 else '−'}{format_number(abs(gap), 1)}%" if gap is not None else ""
                    then_mult = _today_factor(orders_all if orders_all is not None else orders, today, actual_day) if actual_day else 1.0
                    if abs(then_mult - day_factor) >= 0.05:
                        gap_text += f" (pola {actual_day:%d/%m} ×{format_number(then_mult, 2)}, hari ini ×{format_number(day_factor, 2)})"
                    actual_html = f"<div class='metric-move flat'>Aktual terjual {html.escape(when)}: {format_qty(actual_qty)} unit{gap_text}</div>"
            _prediction_card(
                cards[0],
                f"Prediksi {'sales' if main_money else qty_label} {name} · Top 50 SKU",
                format_idr(main_now) if main_money else f"{format_number(round(float(main_now)), 0)} unit",
                _move_line(main_now, main_then, money=main_money, fresh=fresh),
                tip=day_tip if not main_money else "",
                extra_html=actual_html if not main_money else "",
            )
            _prediction_card(
                cards[1],
                f"Prediksi {qty_label if main_money else 'sales'} {name} · Top 50 SKU",
                f"{format_number(round(float(qty_now)), 0)} unit" if main_money else format_idr(sales_now),
                _move_line(qty_now if main_money else sales_now, None if then is None else (then[0] if main_money else then[1]), money=not main_money, fresh=fresh),
                tip=day_tip if main_money else "",
                extra_html=actual_html if main_money else "",
            )
            need_tip = (
                "Kebutuhan stok = prediksi QTY (unit utuh, dibulatkan ke bawah) + safety stock, dijumlah per SKU."
                + (f" Jendela prediksi bulan: {format_id_date(today)} – {format_id_date(prediction_window('bulan', today)[1])}." if group.prefix == "m" else "")
            )
            whole = float(decision[f"{group.prefix}_qty"].sum()) if f"{group.prefix}_qty" in decision.columns else float("nan")
            _prediction_card(
                cards[2],
                f"Kebutuhan stok {name} · Top 50 SKU",
                f"{format_number(round(float(need_now)), 0)} unit",
                _move_line(need_now, None if then is None else then[2], money=False, fresh=fresh),
                tip=need_tip,
                extra_html=(f"<div class='metric-move flat'>= {format_number(round(whole), 0)} unit utuh + SS {format_number(round(need_now - whole), 0)}</div>"
                            if whole == whole else ""),
            )
            if all_sku is not None and group.prefix in {"d", "m"} and f"{group.prefix}_sales" in all_sku.columns:
                exp_col = f"{group.prefix}_sales_exp"
                total_sales = float(all_sku[exp_col].sum() if exp_col in all_sku.columns else all_sku[f"{group.prefix}_sales"].sum())
                pattern_html = ""
                if is_day:
                    pattern_html = _today_pattern_hint(orders_all if orders_all is not None else orders, today, total_sales)
                cards[3].markdown(
                    "<div class='stat-card'>"
                    f"<div class='readable-metric-label'>Prediksi sales {html.escape(name)} · All SKU</div>"
                    f"<div class='readable-metric-value'>{html.escape(format_idr(total_sales))}</div>"
                    f"<div class='metric-hint'>{format_number(len(all_sku), 0)} SKU dianalisa"
                    + ("" if is_day else " · sales produk, mulai hari ini") + f"{pattern_html}</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )
        _running_month_cards(decision, all_sku, orders, orders_all, today, prior, day_factor, metric)

    st.markdown("<div class='section-title'>Pergerakan Top 50</div>", unsafe_allow_html=True)
    explain(
        [
            "SKU Top 50 yang prediksinya berubah pada rentang tanggal yang dipilih.",
            ("Urutan", "dampak ke omzet terbesar lebih dulu: gabungan besar perubahan prediksi bulan dalam sales value (Rp) dan QTY, naik maupun turun"),
            ("Tampilan", "5 SKU teratas; Muat lebih banyak menambah 10 SKU, Tutup kembali ke 5 SKU. Unduh Excel berisi semua SKU"),
            ("Angka kecil di sel", "besar perubahan: ▲ naik, ▼ turun"),
            ("Sales produk", "semua kolom Sales di tabel ini = Harga Setelah Diskon × QTY (dasar prediksi), bukan sales bersih (Total Pembayaran, dasar target); "
             "sales bersih lebih kecil karena sudah dipotong voucher"),
            ("Prediksi bulan berjalan", "aktual SKU itu tgl 1 s.d. hari penuh terakhir + laju prediksi harian × pola hari sisa bulan; aturan sama dengan kartu "
             "Prediksi bulan berjalan di atas. Baris Total hanya menjumlah SKU yang prediksinya bergerak, jadi bisa sedikit di bawah kartu (semua Top 50)"),
            ("Prediksi 30 hari", "30 hari mulai hari ini (melewati akhir bulan), bukan bulan kalender"),
            ("Stok Site 10062 / 10036 · Ambil dari DC", "bila stok Site 10037 kurang, cek apakah DC bisa memenuhi sebelum PO"),
            ("Kolom", "klik judul untuk mengurutkan, geser judul untuk memindah, tarik tepi judul untuk mengubah lebar"),
        ]
    )
    if "movement-date-from" not in st.session_state:
        st.session_state["movement-date-from"] = yesterday
    if "movement-date-to" not in st.session_state:
        st.session_state["movement-date-to"] = today
    pick_start, pick_end, _space = st.columns([1, 1, 2])
    earliest = date(2020, 1, 1)
    start_day = _as_date(
        pick_start.date_input("Dari", min_value=earliest, max_value=today, format="DD/MM/YYYY", key="movement-date-from")
    ) or yesterday
    end_day = _as_date(
        pick_end.date_input("Sampai", min_value=earliest, max_value=today, format="DD/MM/YYYY", key="movement-date-to")
    ) or today
    if st.session_state.get("movement-limit-for") != (start_day, end_day):
        st.session_state["movement-limit-for"] = (start_day, end_day)
        st.session_state["movement-limit"] = MOVEMENT_STEP
    locked = frame_from_stock(stock)
    start_frame = _movement_frame(start_day, **frame_args)
    end_frame = locked if end_day == today else _movement_frame(end_day, **frame_args)
    detail = compare_runs(end_frame, start_frame, metric)
    decision_map = (
        {str(k): r for k, r in decision.set_index("item_key", drop=False).iterrows()}
        if isinstance(decision, pd.DataFrame) and not decision.empty
        else {}
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
        decision=decision_map,
        orders=orders,
        orders_all=orders_all,
    )
    if export.empty:
        st.markdown(
            "<div class='field-hint'>Pada rentang ini tidak ada item Top 50 yang prediksinya berubah.</div>",
            unsafe_allow_html=True,
        )
    # Unduh Excel ada di bilah tombol tabel (di dalam komponen).
    return detail


def removed_counts(raw: pd.DataFrame | None) -> tuple[int, float]:
    """Jumlah pesanan batal dan unit retur pada data latih (untuk kartu toggle exclude)."""
    if raw is None or raw.empty:
        return 0, 0.0
    cancelled = cancelled_status_mask(raw["status"]) if "status" in raw.columns else pd.Series(False, index=raw.index)
    orders_count = int(raw.loc[cancelled, "order_id"].nunique()) if "order_id" in raw.columns else int(cancelled.sum())
    units = 0.0
    if {"gross_qty", "qty"} <= set(raw.columns):
        units = float((raw.loc[~cancelled, "gross_qty"] - raw.loc[~cancelled, "qty"]).clip(lower=0).sum())
    return orders_count, units


def enriched_catalog(
    catalog: pd.DataFrame,
    *,
    run_id: str,
    resume_label: str,
    period: str,
    today: date,
    horizon_days: int,
    orders: pd.DataFrame,
    orders_all: pd.DataFrame,
    frames: StoreFrames,
    params: dict,
) -> pd.DataFrame:
    """Katalog + tabel keputusan (SS, Butuh, Stok), iklan, label, segmen; disimpan selama input sama."""
    if catalog is None or catalog.empty:
        return catalog
    store_stamp = st.session_state.get("_store-frames", (None,))[0]
    day_factor = _today_factor(orders_all, today)
    stamp = (
        run_id,
        resume_label,
        len(catalog),
        float(catalog["qty_total"].sum()),
        store_stamp,
        repr(sorted((k, repr(v)) for k, v in params.items())),
        today.isoformat(),
        round(day_factor, 6),
    )
    cached = st.session_state.get("_enriched")
    if isinstance(cached, tuple) and cached[0] == stamp:
        return cached[1]
    # Beberapa menu memakai periode penjualan berbeda (stamp berbeda): simpan 8 hasil terakhir agar
    # bolak-balik menu tidak menghitung ulang katalog.
    recent = st.session_state.setdefault("_enriched-recent", {})
    if stamp in recent:
        st.session_state["_enriched"] = (stamp, recent[stamp])
        return recent[stamp]
    try:
        table = enrich_catalog(
            catalog,
            period=period,
            today=today,
            horizon_days=horizon_days,
            orders_used=orders,
            orders_all=orders_all,
            frames=frames,
            params=params,
            day_factor=day_factor,
        )
    except Exception as exc:  # data tambahan bermasalah: tetap tampilkan tabel keputusan dasar
        st.warning(
            "Data stok, iklan, dan label belum bisa digabung dengan prediksi, jadi kolom stok tampil sebagai \"tanpa data stok\". "
            f"Data yang diunggah tetap tersimpan. Detail teknis untuk perbaikan: {type(exc).__name__}: {exc}"
        )
        table = build_decision_table(catalog, period=period, today=today, horizon_days=horizon_days, orders=orders, day_factor=day_factor)
        table["label"] = [[] for _ in range(len(table))]
        table["label_text"] = ""
    st.session_state["_enriched"] = (stamp, table)
    recent[stamp] = table
    while len(recent) > 8:
        recent.pop(next(iter(recent)))
    return table


def priority_top10(view: pd.DataFrame) -> pd.DataFrame:
    """Sepuluh SKU yang QTY terjual dan sales value-nya sama-sama besar."""
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
    explain(
        [
            ("Prediksi " + PERIOD_SPECS[period].label, f"{format_number(horizon)} hari mulai {format_id_date(day)}"),
            ("Sales hari ini", f"prediksi sales periode ÷ {format_number(horizon)} × pola hari ini (sama dengan Pantauan harian)"),
            ("Sales bulan ini", f"bagian {format_number(month_days)} hari, {format_id_date(day)} – {format_id_date(month_end)}"),
            ("Stok disarankan", "prediksi QTY + safety stock pada jumlah hari yang sama"),
            ("Warna selisih", "biru naik, merah turun, tanda – bila sama dengan analisa pembanding"),
        ]
    )
    if ready is None or ready.empty:
        st.write("Belum ada SKU pada periode penjualan ini.")
        return
    cards = st.columns(4)
    day_sales = (float((ready["pred_sales"] / ready["slice_horizon_days"].clip(lower=1) * ready.get("slice_day_factor", 1.0)).sum())
                 if {"pred_sales", "slice_horizon_days"} <= set(ready.columns) else float(ready["pred_sales_hari"].sum()))
    show_metric(cards[0], "Prediksi sales hari ini", format_idr(day_sales),
                hint=f"1 hari dari prediksi {PERIOD_SPECS[period].label} × pola hari ini ×{format_number(TODAY_FACTOR[0], 2)}.")
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
        st.write("Belum ada SKU yang punya QTY terjual dan sales value sekaligus.")
        return
    display = leaderboard_frame(top, period)
    excel_toolbar(display, "top10_prioritas_stok.xlsx")
    scroll_table(display, max_height=520)


ROUTE_CHANGED = sync_route(st.session_state, st.query_params, allowed_sheets(AUTH_USER.role, APP_SHEETS))

# Beranda tidak membuka file hasil analisa. Halaman lain (hasil, Setting, Upload data) memuatnya seperti biasa,
# supaya angka di Setting tetap memakai transaksi analisa terakhir, bukan bergantung urutan klik.
if (
    route_from_state(st.session_state, allowed_sheets(AUTH_USER.role, APP_SHEETS))[0] not in (PAGE_HOME, PAGE_USERS, PAGE_PASSWORD)
    and not st.session_state.get("_autoload-done")
):
    # Tanda "selesai" baru dipasang setelah analisa terakhir termuat: bila rerun pertama terputus (klik / sambung ulang),
    # rerun berikutnya mencoba lagi, bukan terjebak di halaman Upload data tanpa hasil.
    if "analysis" not in st.session_state and not st.session_state.get("pending-run"):
        try:
            last_ok = run_repository().last_success()
        except Exception:
            last_ok = None
        if last_ok is not None and open_saved_run(last_ok.id, navigate=False):
            st.session_state.pop("editing-input", None)
    st.session_state["_autoload-done"] = True

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
    ROUTE_CHANGED = sync_route(st.session_state, st.query_params, allowed_sheets(AUTH_USER.role, APP_SHEETS)) or ROUTE_CHANGED

render_header()
_tick("header")

# Satu wadah isi halaman: saat pindah halaman/menu dikosongkan dulu, jadi blok lama tidak tampil dobel/pudar.
PAGE_ROOT = st.empty()
if ROUTE_CHANGED:
    PAGE_ROOT.empty()
with PAGE_ROOT.container(key="page-root"):
    # Elemen pertama selalu ada (jumlah elemen tetap). Saat halaman berganti, sisa halaman lama (data-stale)
    # disembunyikan selama halaman baru dihitung; tanpa ini baris Beranda tampil acak di kolom halaman baru.
    st.markdown(
        "<style>.st-key-page-root [data-stale='true']{display:none !important;}</style>" if ROUTE_CHANGED else "<style></style>",
        unsafe_allow_html=True,
    )
    if show_auth_page(AUTH_USER):
        st.stop()
    if st.session_state.get("setting-open"):
        setting_table = (st.session_state.get("_enriched") or (None, pd.DataFrame()))[1]
        setting_orders = (st.session_state.get("analysis") or {}).get("orders")
        # Setting dibuka langsung (analisa belum dimuat di sesi ini): pakai data stok Site 10037 dan transaksi tersimpan
        # agar pencarian SKU dan kapasitas gudang tetap punya daftar SKU, nama produk, dan stok.
        if not isinstance(setting_table, pd.DataFrame) or setting_table.empty:
            setting_table = _setting_fallback_table()
        if not isinstance(setting_orders, pd.DataFrame) or setting_orders.empty:
            try:
                setting_orders = _orders_from_library(_checked_library_keys())[0]
            except Exception:
                setting_orders = None
        if isinstance(setting_table, pd.DataFrame) and not setting_table.empty and "biaya_iklan" not in setting_table.columns:
            ads_key = (len(setting_table), 0 if setting_orders is None else len(setting_orders))
            cached_ads = st.session_state.get("_setting-ads")
            if isinstance(cached_ads, tuple) and cached_ads[0] == ads_key:
                setting_table = cached_ads[1]
            else:
                setting_table = _with_ads(setting_table, setting_orders)
                st.session_state["_setting-ads"] = (ads_key, setting_table)
        st.session_state["_sku_product_code"] = _sku_product_codes()
        st.session_state["_active_skus"] = _active_skus()
        setting_data = cached_feature_data(st.session_state, get_features(), setting_table, date.today(), periode="", stamp="setting")
        shown_tab = show_setting(
            str(st.session_state.get("setting-slug", "") or ""),
            role=AUTH_USER.role,
            username=AUTH_USER.username,
            features=get_features(),
            table=setting_table,
            data=setting_data,
            orders=setting_orders,
            today=date.today(),
            user_root=USER_ROOT,
        )
        if shown_tab != st.session_state.get("setting-slug"):
            st.session_state["setting-slug"] = shown_tab
            st.rerun()
        st.stop()
    if st.session_state.get("active-feature") != FEATURE_ID:
        show_homepage()
        st.stop()

    if editing_input and not can(AUTH_USER.role, "ubah_data_latih") and can(AUTH_USER.role, "unggah_stok"):
        show_stock_uploads()
        st.stop()
    if editing_input:
        show_prediction_inputs()

    run_notice = st.session_state.pop("run-error", None)
    if run_notice:
        st.warning(run_notice)
    if "analysis" in st.session_state and not st.session_state.get("pending-run"):
        show_result_status(analysis_status())

    orders_raw, source_raw, source_key, period, sidebar_metric, service = restore_prediction_context()
    _tick("konteks")
    run = bool(st.session_state.pop("pending-run", False))
    load_error = None

    today = date.today()
    window_start, window_end, period_text = forecast_window(period, today)

    if run and (not isinstance(orders_raw, pd.DataFrame) or orders_raw.empty):
        st.session_state["editing-input"] = True
        st.session_state["input-error"] = "Data latih tidak terbaca. Pilih bulan atau unggah laporan, lalu jalankan analisa lagi."
        st.rerun()

    sheet = str(st.session_state.get("active-sheet", "Ringkasan"))
    if sheet not in allowed_sheets(AUTH_USER.role, APP_SHEETS):
        sheet = "Ringkasan"
        st.session_state["active-sheet"] = sheet
    # Satu sumber: analisa yang sedang dibuka (atau setelan analisa yang baru diminta). Bukan kunci widget,
    # karena Streamlit menghapus nilai widget yang tidak tampil saat pindah halaman → angka berganti-ganti.
    if run:
        exclude_return_cancel = bool(st.session_state.get("run-exclude", training_exclude()))
    else:
        exclude_return_cancel = bool((st.session_state.get("analysis") or {}).get("exclude_return_cancel", training_exclude()))
    if "analysis" in st.session_state and not run:
        sheet = show_app_menu()
        if sheet not in allowed_sheets(AUTH_USER.role, APP_SHEETS):
            sheet = "Ringkasan"
            st.session_state["active-sheet"] = sheet
        if sheet in SUMMARY_SHEETS:
            stored_meta = st.session_state.get("analysis", {})
            shown_period = str(stored_meta.get("period", period))
            shown_start, shown_end, _shown_text = forecast_window(shown_period, today)
            shown_metric = "QTY terjual" if stored_meta.get("metric", sidebar_metric) == "qty" else "Sales value"
            date_col, period_col = st.columns([1, 2.2])
            show_metric(date_col, "Tanggal hari ini", format_id_date(today))
            period_col.markdown(
                "<div class='stat-card calm'>"
                "<div class='readable-metric-label'>Periode prediksi</div>"
                f"<div class='period-name'>{PERIOD_LABELS[shown_period]}</div>"
                f"<div class='period-dates'>{format_id_date(shown_start)} – {format_id_date(shown_end)} · "
                f"Parameter: {shown_metric} · Safety stock {int(stored_meta.get('service', service))}%</div>"
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
            st.warning("Tidak ada transaksi yang bisa dianalisa pada data ini.")
            st.stop()

        base_period = "hari"
        horizon_steps = horizon_day_count(period, today)
        base_history = aggregate_item_periods(orders, base_period)
        last_bucket = period_start(orders["order_time"], period).max()
        next_label = period_label(next_period_start(last_bucket, period), period)

        params_now = current_params()
        frames_now = store_frames()
        _zero_frame, zero_since = zero_since_map(frames_now.stock, today)
        st.session_state.pop("ensemble-error", None)
        run_started = time.perf_counter()
        with st.spinner("Membaca pola belanja harian, menguji model, dan menyusun ensemble..."):
            bar = st.progress(0.0, text="Level terkini per SKU")

            def on_progress(pct: float, label: str) -> None:
                bar.progress(min(max(pct, 0.0), 0.98), text=label)

            previous = st.session_state.get("analysis") if not run else None
            reuse = isinstance(previous, dict) and previous.get("ensemble_weights") and previous.get("period") == period
            combined, stock, outcome = build_forecast(
                base_history,
                orders,
                period=period,
                as_of=today,
                service=service,
                params=params_now,
                evaluate=not reuse,
                weights=previous.get("ensemble_weights") if reuse else None,
                zero_since=zero_since,
                progress=on_progress,
            )
            if reuse and outcome is not None:
                outcome.evaluations = previous["demand_outcome"].evaluations if previous.get("demand_outcome") else []
                outcome.evaluated_skus = previous["demand_outcome"].evaluated_skus if previous.get("demand_outcome") else 0
                outcome.history_days = previous["demand_outcome"].history_days if previous.get("demand_outcome") else 0
                outcome.eval_records = getattr(previous.get("demand_outcome"), "eval_records", {}) or {}
            bar.progress(1.0, text="Selesai")
        if combined.empty:
            st.warning("Tidak ada SKU yang bisa diprediksi dari data latih ini.")
            st.stop()
        try:
            comparison = compare_daily_algorithms(base_history)
        except Exception:
            comparison = pd.DataFrame()
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
        orders_all = orders if not exclude_return_cancel else prepare_analysis_orders(orders_raw, exclude_return_cancel=False)
        st.session_state["analysis"] = {
            "orders": orders,
            "orders_all": orders_all,
            "zero_since": zero_since,
            "history": history,
            "combined": combined,
            "stock": stock,
            "demand_outcome": outcome,
            "ensemble_weights": outcome.weights if outcome is not None else None,
            "eval": getattr(outcome, "eval_records", {}) if outcome is not None else {},
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
            "library_keys": [str(key) for key in st.session_state.get("active-library-keys", tuple())],
        }
        save_analysis_run(
            st.session_state["analysis"],
            duration=time.perf_counter() - run_started,
            window_start=window_start,
            window_end=window_end,
        )
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
        comparison = stored.get("comparison", pd.DataFrame())
        period = stored["period"]
        metric = stored.get("metric", "qty")
        horizon_steps = int(stored.get("horizon_steps", 1))
        base_period = stored.get("base_period", period)
        period_text = stored.get("period_text") or forecast_window(period)[2]

    if filters_changed:
        st.warning("Periode prediksi, parameter, atau data latih berubah. Klik **Jalankan analisa** untuk menghitung ulang.")

    stored = st.session_state["analysis"]
    orders_all = stored.get("orders_all", orders)
    TODAY_FACTOR[0] = _today_factor(orders_all, today)
    params = current_params()
    frames = store_frames()
    outcome = stored.get("demand_outcome")
    horizon_days = horizon_day_count(period, today)
    window_label = f"{PERIOD_LABELS[period]} · s.d. {format_id_date(window_end)}"
    applied_service = int(stored.get("service", service))
    lead_default = not changed_from_default(params, "lead_time.lokal_hari")

    dashboard_slot = st.container() if sheet == "Ringkasan" else None
    if sheet in SUMMARY_SHEETS:
        st.markdown(
            "<div class='section-title'>Periode penjualan "
            "<span style='display:inline-block;margin-left:8px;padding:2px 10px;border-radius:999px;background:#dbeafe;color:#1e40af;"
            "font-size:var(--fs-xs);font-weight:700;vertical-align:middle'>Data aktual · bukan prediksi</span></div>",
            unsafe_allow_html=True,
        )
        sales_orders, resume_label, _picked_months = period_filter(orders, prefix="resume")
    else:
        sales_orders, resume_label = apply_saved_period(orders, prefix="resume")
    if not resume_label:
        resume_label = "seluruh data input"

    last_period = history["period_start"].max()
    catalog = top_bestsellers(orders, combined, stock, history, metric, last_period, period, top_n=None, period_orders=sales_orders)
    _tick("peringkat")
    FEATURES = get_features()
    EXCLUDED = excluded_skus(FEATURES)
    if isinstance(catalog, pd.DataFrame) and not catalog.empty and EXCLUDED:
        catalog = drop_excluded(catalog, EXCLUDED).reset_index(drop=True)
        if "peringkat" in catalog.columns:
            catalog["peringkat"] = range(1, len(catalog) + 1)
    enriched = enriched_catalog(
        catalog,
        run_id=str(stored.get("run_id") or ""),
        resume_label=resume_label,
        period=period,
        today=today,
        horizon_days=horizon_days,
        orders=orders,
        orders_all=orders_all,
        frames=frames,
        params=params,
    )
    _tick("katalog diperkaya")
    shown = enriched.head(TOP_N).reset_index(drop=True) if isinstance(enriched, pd.DataFrame) else pd.DataFrame()
    katalog_run = st.session_state.pop("_run-save-katalog", None)
    if katalog_run and isinstance(enriched, pd.DataFrame) and not enriched.empty:
        try:
            run_repository().save_extra(int(katalog_run), "katalog", enriched)
        except Exception:
            pass
        try:
            data_until = pd.to_datetime(orders_all["order_time"]).max().date()
            month_lo, _month_hi = last_full_month(data_until)
            FEATURES.set_report_period(int(katalog_run), f"{month_lo.year:04d}-{month_lo.month:02d}", username=AUTH_USER.username)
            FEATURES.replace("run_info", [{"run_id": int(katalog_run), "data_until": data_until}], keys=["run_id"], username=AUTH_USER.username, action="simpan:data_sd")
            save_run_snapshot(FEATURES, int(katalog_run), enriched, window_start, window_end, AUTH_USER.username)
        except Exception as exc:
            st.session_state["run-error"] = f"Snapshot prediksi belum tersimpan: {exc}"
    FEATURE_DATA = cached_feature_data(
        st.session_state,
        FEATURES,
        enriched if isinstance(enriched, pd.DataFrame) else pd.DataFrame(),
        today,
        periode=f"{window_start.year:04d}-{window_start.month:02d}",
        stamp=str(stored.get("run_id") or ""),
    )
    _tick("data fitur")


    def show_performance_cards(start, end, label: str, *, tone: str | None = None) -> dict:
        if start is None:
            facts, coverage = dict(EMPTY_ORDER_METRICS), {"sku_terjual_bersih": 0}
        else:
            facts = cached_order_metrics(orders_all, start, end, exclude_return_cancel)
            coverage = cached_sku_coverage(orders_all, start, end)
        cols = st.columns(4)
        metric_card(cols[0], "pesanan_bersih", format_number(facts["pesanan_bersih"], 0), hint=f"{label} · dari {format_number(facts['pesanan_semua'], 0)} pesanan semua status", tone=tone)
        metric_card(cols[1], "sku_terjual_bersih", format_number(coverage["sku_terjual_bersih"], 0), hint=label, tone=tone)
        reach = achievement_line(facts["sales_bersih"], start, end, FEATURES, orders=orders_all)
        metric_card(cols[2], "sales_bersih", format_idr(facts["sales_bersih"]), hint=f"Bruto {format_idr(facts['sales_bruto'])}" + (f"<br>{reach}" if reach else ""), tone=tone)
        metric_card(cols[3], "qty_bersih", format_qty(facts["qty_bersih"]), hint=label, tone=tone)
        return facts


    def show_exclude_and_cards() -> None:
        removed_orders, removed_units = removed_counts(orders_raw)
        exclude_status_card(exclude_return_cancel, removed_orders=removed_orders, removed_units=removed_units)
        start, end = period_bounds(sales_orders)
        facts = show_performance_cards(start, end, resume_label)
        if period != "bulan":
            from src.core.periods import calendar_period

            lo, _hi, cal_label = calendar_period(period, today)
            stamp = pd.to_datetime(orders_all["order_time"], errors="coerce").max() if orders_all is not None and not orders_all.empty else pd.NaT
            upto = min(today, stamp.date()) if pd.notna(stamp) else today
            show_performance_cards(lo, upto, f"{cal_label} · {format_id_date(lo)} s.d. {format_id_date(upto)}", tone="extra")
        note = (
            f"{resume_label}: {format_number(facts['pesanan_batal'], 0)} pesanan batal "
            f"({format_pct_id(facts['tingkat_batal'] * 100)}) dan {format_qty(facts['retur_unit'])} unit retur "
            f"({format_number(facts['pesanan_retur_penuh'], 0)} pesanan diretur penuh)."
        )
        st.markdown(f"<div class='field-hint'>{html.escape(note)}</div>", unsafe_allow_html=True)


    def show_sku_detail(table: pd.DataFrame, picked: str, key: str) -> None:
        match = table.loc[table["item_key"].astype(str) == picked]
        if match.empty:
            return
        chosen = match.iloc[0]
        st.subheader(product_identity(chosen["peringkat"], chosen["sku"], chosen["product_name"], chosen["variasi_tampil"]))
        item_orders = orders.loc[orders["item_key"].astype(str) == picked]
        base_hist = stored.get("base_history")
        weekday = _weekday_profile(base_hist) if isinstance(base_hist, pd.DataFrame) and not base_hist.empty else np.ones(7)
        try:
            past = past_predictions(FEATURES, str(chosen["sku"]), str(chosen.get("variasi_tampil") or ""), date(today.year, today.month, 1), today - timedelta(days=1))
            sku_charts(chosen, item_orders, period=period, today=today, window_end=window_end, weekday=weekday, key=key, past=past)
        except Exception as exc:  # grafik tidak boleh menghentikan halaman
            st.info(f"Grafik SKU belum bisa digambar: {exc}")


    require_role(SHEET_PERMISSIONS.get(sheet, "ringkasan"))

    _tick("persiapan menu")
    if sheet == "Ringkasan":
        with dashboard_slot:
            show_priority_dashboard(
                enriched,
                today=today,
                orders=orders,
                orders_all=orders_all,
                features=FEATURES,
                data=FEATURE_DATA,
                role=AUTH_USER.role,
                window_label=format_period_label("prediksi", window_start),
                window_start=window_start,
                fresh_period=window_start.day == 1,
                metric=metric,
                )
        show_exclude_and_cards()
        if isinstance(stock, pd.DataFrame) and not shown.empty:
            movement_detail = show_analysis_movement(
                stock,
                _analysis_meta(
                    period=period,
                    period_text=period_text,
                    metric=metric,
                    service=applied_service,
                    exclude=exclude_return_cancel,
                    window_start=window_start,
                    window_end=window_end,
                ),
                metric,
                shown["item_key"].astype(str).tolist(),
                enriched,
                shown,
                orders,
                history=stored.get("base_history"),
                service=applied_service,
                source_key=str(stored.get("source_key") or ""),
                used_default_lead=lead_default,
                orders_all=orders_all,
            )

        st.subheader("Ringkasan total Top 50")
        if shown.empty:
            st.write("Tidak ada item untuk ditampilkan.")
        else:
            top50_matrix(
                shown,
                period_actuals(orders_all if orders_all is not None else orders, shown["item_key"].astype(str).tolist(), period=period, today=today),
                period=period,
                today=today,
                resume_label=resume_label,
                all_sku=enriched,
                exclude=exclude_return_cancel,
            )
            legacy_view = apply_horizon_slices(shown, period, today)
            show_qty_forecast_board(
                legacy_view,
                resume_label=resume_label,
                period_text=period_text,
                horizon_days=horizon_days,
                history=stored.get("base_history"),
                orders=orders,
                exclude_cancel=bool(stored.get("exclude_return_cancel", False)),
                as_of=today,
                stock=stock if isinstance(stock, pd.DataFrame) else None,
                period=period,
                service=applied_service,
                source_key=str(stored.get("source_key") or ""),
                metric=metric,
                decision=shown,
                performance=store_performance(frames.performance, today),
            )

            st.subheader("Top 50 item terlaris")
            label_legend()
            picked = show_decision_table(
                shown,
                period=period,
                today=today,
                metric=metric,
                resume_label=resume_label,
                window_label=window_label,
                key=f"top50-{metric}-{period}",
                filename="top50_item_terlaris.xlsx",
                step=5,
            )
            # Grafik SKU langsung di bawah tabel (dekat centang Grafik); analisa safety stock sesudahnya.
            if picked:
                show_sku_detail(shown, picked, key=f"top50-chart-{picked}")
            else:
                st.info("Centang kolom Grafik pada satu SKU untuk menampilkan Grafik QTY dan Grafik Sales.")
            safety_stock_box(shown, period=period, today=today, definition=SS_DEFINITION_TOP, used_default=lead_default, **_ss_params(params, applied_service))

    elif sheet == "Prediksi":
        # Ringkasan penjualan periode & status Kecualikan batal & retur langsung di atas (tidak dilipat).
        show_exclude_and_cards()
        show_pred_vs_actual(FEATURES, orders=orders, table=enriched, orders_all=orders_all)
        try:
            from src.ui.month_track_view import show_month_tracking

            show_month_tracking(FEATURES, orders_all=orders_all, table=enriched, today=today, data=FEATURE_DATA, params=params)
        except Exception as exc:  # noqa: BLE001 - pantauan tidak boleh menghentikan halaman Prediksi
            st.info(f"Pantauan harian belum bisa ditampilkan: {exc}")
        st.subheader("Prediksi semua produk")
        if enriched is None or enriched.empty:
            st.write("Tidak ada item untuk ditampilkan.")
        else:
            label_legend()
            f1, f2, f3, f4 = st.columns([2.4, 1.2, 1.2, 0.8])
            # Cari: saat diketik, daftar menampilkan SKU · nama produk · varian sehingga SKU yang tidak sesuai terlihat.
            labels_all = (
                enriched["sku"].astype(str) + " · " + enriched["product_name"].astype(str)
                + np.where(enriched["variasi_tampil"].fillna("").astype(str).str.len() > 0, " · " + enriched["variasi_tampil"].fillna("").astype(str), "")
            )
            choice_keys = dict(zip(labels_all, enriched["item_key"].astype(str)))
            choices = list(choice_keys)
            query = f1.selectbox(
                "Cari SKU atau nama produk",
                options=choices,
                index=None,
                placeholder="Ketik SKU atau nama produk…",
                accept_new_options=True,
                key="pred-search",
            )
            label_pick = f2.multiselect("Label", options=list(LABEL_ICONS), key="pred-labels", placeholder="Pilih")
            status_pick = f3.multiselect("Status stok (bulan ini)", options=["Aman", "Kurang", "Kosong", "Tanpa data stok"], key="pred-status", placeholder="Pilih")
            work = enriched
            if query:
                if query in choice_keys:
                    work = work.loc[work["item_key"].astype(str) == choice_keys[query]]
                else:
                    needle = " ".join(str(query).lower().split())
                    blob = (work["sku"].astype(str) + " " + work["product_name"].astype(str) + " " + work["variasi_tampil"].astype(str)).str.lower()
                    work = work.loc[blob.str.contains(needle, regex=False)]
            if label_pick:
                work = work.loc[work["label"].map(lambda names: any(name in (names or []) for name in label_pick))]
            if status_pick:
                work = work.loc[work["m_status"].map(lambda value: str(value).split(" · ")[0]).isin(status_pick)]
            # Urutan dampak: prediksi bulan (sales value bila parameter sales, QTY bila parameter QTY) terbesar dulu.
            impact_col = ("m_sales_exp" if "m_sales_exp" in work.columns else "m_sales") if metric == "sales" else ("m_qty_exp" if "m_qty_exp" in work.columns else "m_qty")
            work = work.sort_values(impact_col, ascending=False, kind="mergesort")
            total = len(work)
            filter_sig = (str(query), tuple(label_pick), tuple(status_pick))
            if st.session_state.get("pred-filter-sig") != filter_sig:
                st.session_state["pred-filter-sig"] = filter_sig
                st.session_state["pred-page-n"] = 1
            page_size = int(f4.selectbox("Baris/halaman", options=[5, 10, 20, 50, 100], index=0, key="pred-size"))
            pages = max((total - 1) // page_size + 1, 1)
            page = min(max(int(st.session_state.get("pred-page-n", 1)), 1), pages)
            def _allpred_excel() -> None:
                from src.ui.decision_view import table_parts

                export = table_parts(work, period=period, today=today, metric=metric, resume_label=resume_label, window_label=window_label)[3]
                download_excel(export, "prediksi_semua_produk.xlsx", key="xl-allpred")

            # Tombol Excel di bilah navigasi (sejajar nomor halaman), berisi semua SKU sesuai saringan, bukan hanya halaman ini.
            page = page_navigator(page, pages, key="pred-page", total=total, page_size=page_size, noun="SKU", download=_allpred_excel)
            page_view = work.iloc[(page - 1) * page_size : page * page_size].reset_index(drop=True)
            if page_view.empty:
                st.write("Tidak ada SKU yang cocok dengan filter.")
            else:
                picked = show_decision_table(
                    page_view,
                    period=period,
                    today=today,
                    metric=metric,
                    resume_label=resume_label,
                    window_label=window_label,
                    key=f"allpred-{metric}-{period}-{page}-{page_size}",
                    filename=None,
                    height=720,
                    sort="",
                )
                if picked:
                    show_sku_detail(page_view, picked, key=f"allpred-chart-{picked}")
                safety_stock_box(work, period=period, today=today, definition=SS_DEFINITION_TOP, used_default=lead_default, scope="Semua produk sesuai saringan", **_ss_params(params, applied_service))

    elif sheet == "Data":
        if source_raw.empty:
            st.write("Belum ada file yang terbaca. Pilih bulan pada Folder data bila data sudah pernah diimpor.")
        else:
            show_data_menu(source_raw)

    elif sheet == "Folder data":
        show_folder_menu()

    elif sheet == "Rekomendasi":
        show_recommendations(
            enriched,
            orders=orders,
            orders_all=orders_all,
            frames=frames,
            params=params,
            today=today,
            user_root=USER_ROOT,
            features=FEATURES,
            data=FEATURE_DATA,
            window_start=window_start,
            username=AUTH_USER.username,
            can_edit=allowed_access(AUTH_USER.role, "rekomendasi", "edit"),
        )

    elif sheet == "Laporan":
        show_report(
            enriched,
            orders=orders,
            orders_all=orders_all,
            frames=frames,
            params=params,
            today=today,
            period=period,
            metric=metric,
            service=applied_service,
            exclude=exclude_return_cancel,
            window_start=window_start,
            window_end=window_end,
            stock=stock if isinstance(stock, pd.DataFrame) else None,
            features=FEATURES,
            data=FEATURE_DATA,
            run_id=int((st.session_state.get("active-run") or (0,))[0] or 0),
            username=AUTH_USER.username,
            can_edit=allowed_access(AUTH_USER.role, "laporan", "edit"),
        )

    elif sheet == "Evaluasi model":
        show_evaluation(
            outcome,
            comparison=comparison,
            enriched=enriched,
            orders=orders,
            period=period,
            today=today,
            params=params,
            base_history=stored.get("base_history"),
            is_super=AUTH_USER.role == "super_user",
            repo=run_repository(),
            run_id=int((st.session_state.get("active-run") or (0,))[0] or 0),
            features=FEATURES,
        )

    _tick(f"menu {sheet}")
    persist_run_caches()
    show_timings()
