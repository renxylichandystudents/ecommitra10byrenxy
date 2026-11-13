"""Komponen bersama: format angka Indonesia, kartu, badge, filter periode, toggle exclude."""

from __future__ import annotations

import hashlib
import html
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.utils.format import angka, desimal, persen, rupiah
from src.utils.format import excel_bytes as numeric_excel_bytes

ID_MONTHS = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember")
ID_MONTHS_SHORT = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
STATUS_CLASS = {"Aman": "st-ok", "Kurang": "st-short", "Kosong": "st-empty", "di bawah SS": "st-thin"}
STATUS_COLOR = {"Aman": "#15803d", "Kurang": "#a16207", "Kosong": "#b91c1c", "di bawah SS": "#a16207", "Tanpa data stok": "#64748b"}
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


def set_upload_notice(key: str, ok: bool, text: str) -> None:
    """Simpan hasil unggah; tetap tampil sampai unggahan berikutnya (rerun otomatis tidak menghapusnya)."""
    from datetime import datetime

    st.session_state[f"_upload-notice-{key}"] = (bool(ok), str(text), datetime.now().strftime("%d/%m/%Y %H:%M"))


def mark_upload_done(menu_key: str) -> None:
    """Menu upload diberi tanda "✓ Siap (baru disimpan)" di daftar Menu upload."""
    st.session_state["upload-done"] = set(st.session_state.get("upload-done", set())) | {menu_key}


def show_upload_notice(key: str) -> None:
    notice = st.session_state.get(f"_upload-notice-{key}")
    if not notice:
        return
    ok, text, when = notice
    if ok:
        st.success(f"{text}  \nDiterima {when}.", icon=":material/check_circle:")
    else:
        st.error(f"{text}  \nPercobaan {when}. Perbaiki file lalu unggah lagi.", icon=":material/error:")


def file_check(ok: bool, text: str) -> None:
    """Hasil pemeriksaan file sebelum disimpan."""
    if ok:
        st.success(f"**File sesuai, belum disimpan.** {text} Tekan tombol Simpan untuk menerima data.", icon=":material/task_alt:")
    else:
        st.error(f"**File tidak sesuai, tidak disimpan.** {text}", icon=":material/error:")


def _keep_rp(value: str) -> str:
    """ "Rp" tidak terpisah baris dari angkanya di kartu sempit."""
    return str(value).replace("Rp ", "Rp&nbsp;")


def _neg_style(value: str) -> str:
    """Nilai kartu negatif (−Rp…, -12,3%) tampil merah."""
    text = str(value).strip()
    return " style='color:#dc2626'" if text[:1] in ("-", "−") and len(text) > 1 else ""


def card(column, label: str, value: str, *, hint: str | None = None, tone: str | None = None) -> None:
    style = ""
    if tone == "extra":
        style = f"background:{EXTRA_BG};"
    elif tone == "stock":
        style = f"background:{STOCK_BG};"
    hint_html = f"<div class='metric-hint'>{hint}</div>" if hint else ""
    column.markdown(
        f"<div class='stat-card' style='{style}'><div class='readable-metric-label'>{html.escape(label)}</div>"
        f"<div class='readable-metric-value'{_neg_style(value)}>{_keep_rp(value)}</div>{hint_html}</div>",
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
        f"<div class='readable-metric-value'{_neg_style(value)}>{_keep_rp(value)}</div>{hint_html}</div>",
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False, max_entries=64)
def cached_order_metrics(frame: pd.DataFrame, start=None, end=None, exclude_flag: bool = False) -> dict:
    """order_metrics dengan cache (hash data, start, end, exclude_flag)."""
    from src.core.metrics import order_metrics

    del exclude_flag
    return dict(order_metrics(frame, start, end))


@st.cache_data(show_spinner=False, max_entries=64)
def cached_sku_coverage(frame: pd.DataFrame, start=None, end=None) -> dict:
    from src.core.metrics import sku_coverage

    return sku_coverage(frame, start, end)


def section(title: str, kicker: str | None = None) -> None:
    kicker_html = f"<div style='font-size:var(--fs-xs);font-weight:700;color:#64748b;letter-spacing:.08em;text-transform:uppercase'>{html.escape(kicker)}</div>" if kicker else ""
    st.markdown(f"{kicker_html}<div class='section-title'>{html.escape(title)}</div>", unsafe_allow_html=True)


def excel_bytes(frames: dict[str, pd.DataFrame] | pd.DataFrame) -> bytes:
    return numeric_excel_bytes(frames)


_COMPACT_DOWNLOAD = {"on": False}


def download_excel(frames: dict[str, pd.DataFrame] | pd.DataFrame, filename: str, *, key: str | None = None, label: str = "Unduh Excel") -> None:
    name = filename if filename.endswith(".xlsx") else f"{filename}.xlsx"
    rows = len(frames) if isinstance(frames, pd.DataFrame) else sum(len(f) for f in frames.values() if isinstance(f, pd.DataFrame))
    text = label if "(" in label or not rows else f"{label} · {rows:,} baris".replace(",", ".")
    if _COMPACT_DOWNLOAD["on"]:
        # Di bilah navigasi tabel: label pendek (jumlah baris sudah tertulis di keterangan), lebar mengikuti kolom.
        text = "Excel"
    # Gaya tombol unduh (hijau, ikon) diatur global lewat CSS [data-testid="stDownloadButton"] di app.py.
    st.download_button(
        text,
        data=excel_bytes(frames),
        file_name=name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key or f"xl-{name}",
        icon=":material/download:",
        use_container_width=_COMPACT_DOWNLOAD["on"],
        help=f"Unduh Excel · {rows:,} baris".replace(",", ".") if _COMPACT_DOWNLOAD["on"] and rows else None,
    )


def table_toolbar(download, *, key: str, caption: str = "") -> None:
    """Bilah di atas tabel tanpa halaman: keterangan (opsional) di kiri, tombol Excel ringkas di kanan."""
    left, right = st.columns([1.6 + 1.05 + 0.42, 0.42], vertical_alignment="center")
    if caption:
        left.markdown(f"<div class='field-hint'>{caption}</div>", unsafe_allow_html=True)
    _compact_download(right, download, key)


def _compact_download(target, download, key: str) -> None:
    """Tombol unduh ringkas di bilah navigasi tabel (sejajar pilihan baris & nomor halaman)."""
    if not download:
        return
    with target.container(key=f"dlbar-{key}"):
        _COMPACT_DOWNLOAD["on"] = True
        try:
            download()
        finally:
            _COMPACT_DOWNLOAD["on"] = False


def month_label(key: str) -> str:
    year, month = key.split("-", 1)
    return f"{ID_MONTHS[int(month) - 1]} {year}"


def _kept(key: str, default=None):
    """Nilai widget yang tetap ada walau widget tidak dirender (Streamlit menghapus kunci widget saat pindah halaman)."""
    if key in st.session_state:
        return st.session_state[key]
    return st.session_state.get(f"_keep::{key}", default)


def _restore(key: str, default) -> None:
    if key not in st.session_state:
        st.session_state[key] = st.session_state.get(f"_keep::{key}", default)


def _keep(key: str, value) -> None:
    st.session_state[f"_keep::{key}"] = value


SHORT_MONTHS = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")


def month_picker(
    months: list[str],
    *,
    key: str,
    year_key,
    month_key,
    default,
    label_fn=None,
    persist: bool = False,
) -> list[str]:
    """Pemilih bulan ringkas: satu tombol (popover) berisi pilihan cepat dan checkbox tahun & bulan.

    months: kunci "YYYY-MM" (kunci lain, mis. "tanpa-bulan", masuk kelompok Lainnya). Tahun terbaru di atas;
    bila datanya lebih dari dua tahun, tahun lama dilipat. Mengembalikan bulan yang tercentang
    (bulan dihitung hanya bila tahunnya juga tercentang)."""
    def year_of(item: str) -> str:
        return item[:4] if item[:4].isdigit() else "Lainnya"

    years = sorted({year_of(m) for m in months}, key=lambda y: (y == "Lainnya", y))
    dated = [m for m in months if year_of(m) != "Lainnya"]
    for year in years:
        if year_key(year) not in st.session_state:
            st.session_state[year_key(year)] = (st.session_state.get(f"_keep::{year_key(year)}") if persist else None)
            if st.session_state[year_key(year)] is None:
                st.session_state[year_key(year)] = any(default(m) for m in months if year_of(m) == year)
    for item in months:
        if month_key(item) not in st.session_state:
            st.session_state[month_key(item)] = (st.session_state.get(f"_keep::{month_key(item)}") if persist else None)
            if st.session_state[month_key(item)] is None:
                st.session_state[month_key(item)] = bool(default(item))

    def _set(keys: list[str]) -> None:
        chosen = set(keys)
        for year in years:
            st.session_state[year_key(year)] = any(year_of(k) == year for k in chosen)
        for item in months:
            st.session_state[month_key(item)] = item in chosen

    def _label(item: str) -> str:
        return label_fn(item) if label_fn else month_label(item)

    current = [m for m in months if st.session_state.get(month_key(m)) and st.session_state.get(year_key(year_of(m)))]
    if not current:
        summary = "Pilih bulan"
    elif len(current) == len(months) and len(months) > 1:
        summary = f"Semua bulan ({len(months)})"
    elif len(current) <= 2:
        summary = ", ".join(_label(m) for m in current)
    else:
        first, last = current[0], current[-1]
        summary = f"{len(current)} bulan · {_label(first)} – {_label(last)}"
    with st.popover(f"📅 {summary}", use_container_width=True):
        st.markdown("<div class='field-hint'>Centang bulan yang ingin dipakai. Tahun yang tidak dicentang diabaikan.</div>", unsafe_allow_html=True)
        q = st.columns(4)
        q[0].button("Bulan terakhir", key=f"{key}-q1", on_click=_set, args=(dated[-1:] or months[-1:],), use_container_width=True)
        q[1].button("3 bulan", key=f"{key}-q3", on_click=_set, args=(dated[-3:] or months[-3:],), use_container_width=True)
        q[2].button("Semua", key=f"{key}-qa", on_click=_set, args=(list(months),), use_container_width=True)
        q[3].button("Kosongkan", key=f"{key}-q0", on_click=_set, args=([],), use_container_width=True)
        ordered = [y for y in reversed(years) if y != "Lainnya"] + [y for y in years if y == "Lainnya"]
        for position, year in enumerate(ordered):
            year_months = [m for m in months if year_of(m) == year]
            box = st.container() if position == 0 or len(ordered) <= 2 else st.expander(f"Tahun {year}", expanded=False)
            with box:
                on_year = st.checkbox(f"**{year}**", key=year_key(year))
                if persist:
                    _keep(year_key(year), bool(on_year))
                grid = st.columns(6)
                for index, item in enumerate(year_months):
                    text = SHORT_MONTHS[int(item[5:7]) - 1] if year != "Lainnya" and not label_fn else _label(item)
                    on = grid[index % 6].checkbox(text, key=month_key(item), disabled=not on_year)
                    if persist:
                        _keep(month_key(item), bool(on))
    return [m for m in months if st.session_state.get(month_key(m)) and st.session_state.get(year_key(year_of(m)))]


_DATE_DIR = Path(__file__).resolve().parents[2] / "components" / "date_range"
_DATE_VERSION = hashlib.md5((_DATE_DIR / "index.html").read_bytes()).hexdigest()[:8]
_DATE_RANGE = components.declare_component(f"date_range_{_DATE_VERSION}", path=str(_DATE_DIR))


def date_range_picker(*, key: str, lo: date, hi: date, default: tuple[date, date], label: str = "Periode",
                      presets: list[tuple[str, date, date]] | None = None) -> tuple[date, date]:
    """Filter tanggal gaya Shopee: satu kolom tanggal; diklik muncul pilihan cepat (Hari Ini, Kemarin, 1 Minggu,
    1 Bulan, 3 Bulan, Bulan Ini, Bulan Lalu, Semua Data) dan kalender dua bulan untuk memilih rentang.

    presets: pilihan cepat pengganti (mis. untuk rencana ke depan). Pilihan disimpan (tetap sama walau pindah halaman).
    Tanggal di luar [lo, hi] tidak bisa dipilih."""
    def _fit(pair) -> tuple[date, date]:
        a, b = pair
        a, b = (b, a) if a > b else (a, b)
        return min(max(a, lo), hi), min(max(b, lo), hi)

    saved = _kept(f"{key}-range")
    current = _fit(saved if isinstance(saved, tuple) and len(saved) == 2 else default)
    value = _DATE_RANGE(lo=lo.isoformat(), hi=hi.isoformat(), start=current[0].isoformat(), end=current[1].isoformat(), label=label, key=key, default=None,
                        presets=[[name, a.isoformat(), b.isoformat()] for name, a, b in presets or []])
    if isinstance(value, dict) and value.get("start") and value.get("end"):
        raw = (value["start"], value["end"])
        # Komponen terus mengirim nilai terakhir; pakai hanya bila berbeda dari klik sebelumnya.
        if st.session_state.get(f"{key}-raw") != raw:
            st.session_state[f"{key}-raw"] = raw
            current = _fit((date.fromisoformat(raw[0]), date.fromisoformat(raw[1])))
    _keep(f"{key}-range", current)
    return current


def range_label(start: date, end: date) -> str:
    """"Oktober 2026" bila tepat satu/lebih bulan penuh, selain itu "1 Nov 2026 – 7 Nov 2026"."""
    month_end = (pd.Timestamp(end) + pd.offsets.MonthEnd(0)).date()
    if start.day == 1 and end == month_end:
        months = pd.period_range(start, end, freq="M").astype(str).tolist()
        names = [month_label(m) for m in months]
        return names[0] if len(names) == 1 else f"{names[0]} – {names[-1]}"
    return fmt_date(start) if start == end else f"{fmt_date(start)} – {fmt_date(end)}"


def _default_range(lo: date, hi: date) -> tuple[date, date]:
    """Bawaan: bulan terakhir pada data (tanggal 1 s.d. tanggal data terakhir)."""
    return max(lo, hi.replace(day=1)), hi


def _period_slice(orders: pd.DataFrame, start: date, end: date) -> tuple[pd.DataFrame, list[str]]:
    days = pd.to_datetime(orders["order_time"], errors="coerce").dt.normalize()
    filtered = orders.loc[days.between(pd.Timestamp(start), pd.Timestamp(end))].reset_index(drop=True)
    months = pd.period_range(start, end, freq="M").astype(str).tolist()
    return filtered, months


def period_filter(orders: pd.DataFrame, *, prefix: str, compact: bool = False) -> tuple[pd.DataFrame, str, list[str]]:
    """Filter periode penjualan bersama: satu kolom tanggal dengan kalender (gaya Shopee).

    Hanya memotong angka aktual; prediksi tetap dari input awal. Mengembalikan (pesanan terfilter, label, bulan yang tercakup).
    """
    if orders is None or orders.empty or "order_time" not in orders.columns:
        return orders, "", []
    times = pd.to_datetime(orders["order_time"], errors="coerce").dropna()
    if times.empty:
        return orders.iloc[0:0], "", []
    lo, hi = times.min().date(), times.max().date()
    # Lebar penuh: kolom tanggal tetap ramping (maks. 380px), panel kalender dua bulan tampil berdampingan.
    with st.container():
        start, end = date_range_picker(key=f"{prefix}-cal", lo=lo, hi=hi, default=_default_range(lo, hi))
    filtered, months = _period_slice(orders, start, end)
    return filtered, range_label(start, end), months


def apply_saved_period(orders: pd.DataFrame, *, prefix: str) -> tuple[pd.DataFrame, str]:
    """Pakai pilihan `period_filter` terakhir tanpa menampilkan kalender (bawaan: bulan terakhir)."""
    if orders is None or orders.empty or "order_time" not in orders.columns:
        return orders, ""
    times = pd.to_datetime(orders["order_time"], errors="coerce").dropna()
    if times.empty:
        return orders.iloc[0:0], ""
    lo, hi = times.min().date(), times.max().date()
    saved = _kept(f"{prefix}-cal-range")
    start, end = saved if isinstance(saved, tuple) and len(saved) == 2 else _default_range(lo, hi)
    start, end = min(max(start, lo), hi), min(max(end, lo), hi)
    filtered, _months = _period_slice(orders, start, end)
    return filtered, range_label(start, end)


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


def exclude_status_card(active: bool, *, removed_orders: int, removed_units: float, span: str = "") -> None:
    """Keterangan (bukan saklar) setelan "Kecualikan batal & retur" analisa yang sedang dibuka."""
    with st.container(border=True):
        left, right = st.columns([3, 2], vertical_alignment="center")
        with left:
            st.markdown("**Kecualikan batal & retur**")
            st.caption("Setelan analisa ini. Ubah di Upload data › Setelan analisa, lalu jalankan analisa.")
        with right:
            if active:
                st.markdown(badge("AKTIF · nilai bersih", "on"), unsafe_allow_html=True)
                st.caption(f"{fmt_num(removed_orders)} pesanan batal dan {fmt_qty(removed_units)} unit retur {span}tidak ikut dilatih; prediksi = permintaan bersih")
            else:
                st.markdown(badge("NONAKTIF · termasuk batal & retur", "off"), unsafe_allow_html=True)
                st.caption(f"{fmt_num(removed_orders)} pesanan batal dan {fmt_qty(removed_units)} unit retur {span}ikut dilatih; prediksi = permintaan masuk")


def explain(items, *, title: str | None = None, target=None) -> None:
    """Penjelasan singkat per poin, bukan paragraf bersambung.

    items: list berisi "teks" atau (istilah, arti). Ditampilkan sebagai daftar kecil abu-abu."""
    rows = []
    for item in items:
        if not item:
            continue
        if isinstance(item, (tuple, list)):
            term, meaning = item
            rows.append(f"<li><b>{html.escape(str(term))}</b> — {html.escape(str(meaning))}</li>")
        else:
            rows.append(f"<li>{html.escape(str(item))}</li>")
    head = f"<div class='explain-title'>{html.escape(title)}</div>" if title else ""
    (target or st).markdown(f"<div class='explain'>{head}<ul>{''.join(rows)}</ul></div>", unsafe_allow_html=True)


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
        tone = {"Aman": "on", "Kurang": "warn", "Kosong": "bad"}.get(status_key(status), "neutral")
        tag = f" {badge(status_key(status), tone)}" if status else ""
        nums = "".join(f"<div>{html.escape(str(label))}: <b>{html.escape(str(value))}</b></div>" for label, value in row.get("nums", []))
        parts.append(f"<div class='sku-card'><div class='sku-title'>{title}</div><div class='sku-meta'>{meta}{tag}</div><div class='sku-nums'>{nums}</div></div>")
    with st.container(key=f"mobile-cards-{key}"):
        st.markdown("".join(parts) or "<div class='field-hint'>Belum ada SKU.</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Muat lebih banyak: 5 baris pertama, +10 per klik, Tutup kembali ke 5 baris
# ---------------------------------------------------------------------------
BATCH_FIRST = 5
BATCH_STEP = 10

BATCH_CSS = """
<style>
.batch-done { border:1px solid #a7f3d0; background:#ecfdf5; border-radius:10px; padding:6px 14px; text-align:center;
  color:#047857; font-size:.82rem; margin:4px auto 6px; max-width:420px; }
.batch-done b { margin-right:6px; }
</style>
"""


PAGE_SIZES = (5, 10, 20, 50, 100)


def reset_batches(key: str) -> None:
    """Kembali ke halaman 1 (dipanggil saat filter/data berubah)."""
    st.session_state.pop(f"{key}-page-n", None)


def batched_view(
    total: int,
    *,
    key: str,
    render,
    noun: str = "baris",
    first: int = BATCH_FIRST,
    step: int = BATCH_STEP,
    rerun_scope: str = "app",
    fragment: bool | None = None,
    download=None,
) -> None:
    """Satu tabel per halaman: di atas tabel satu bilah berisi keterangan baris, pilihan Baris/hal. (5/10/20/50/100),
    tombol Excel, dan tombol halaman bernomor ‹ 1 2 3 … N ›.

    render(start, end) menggambar baris [start, end). Bila fragment=True (bawaan untuk tabel tampilan), ganti
    halaman hanya menjalankan ulang tabel ini sehingga halaman lain tidak ikut dimuat ulang. `step` tidak dipakai lagi
    (dipertahankan agar pemanggil lama tetap jalan)."""
    if fragment is None:
        fragment = rerun_scope == "app"

    def _body() -> None:
        if total <= first:
            if download:
                info, _gap, dl = st.columns([1.05, 1.6, 0.42], vertical_alignment="center")
                info.markdown(_page_caption(1 if total else 0, total, total, noun, 1, 1), unsafe_allow_html=True)
                _compact_download(dl, download, key)
            render(0, total)
            return
        lo, hi = pager(total, key=key, noun=noun, default_size=first, download=download)
        render(lo, hi)

    if fragment:
        st.fragment(_body)()
    else:
        _body()


def _rerun(scope: str) -> None:
    if scope != "app":
        try:
            st.rerun(scope=scope)
        except st.errors.StreamlitAPIException:
            # Klik terjadi pada rerun penuh (bukan rerun fragment): ulangi seluruh halaman.
            st.rerun()
    st.rerun()


def excel_payload(frame: pd.DataFrame, filename: str) -> dict:
    """Isi file Excel untuk tombol Unduh di dalam komponen tabel (base64 + nama + label)."""
    import base64

    name = filename if filename.endswith(".xlsx") else f"{filename}.xlsx"
    label = f"Unduh Excel · {len(frame):,} baris".replace(",", ".")
    return {"b64": base64.b64encode(excel_bytes(frame)).decode("ascii"), "name": name, "label": label}


def centered_download(key: str, download) -> None:
    """Tombol Unduh Excel di tengah, gaya sama dengan bilah tombol tabel (dipakai bila tabel tanpa navigasi halaman)."""
    _action_bar(key, [], download)


def _action_bar(key: str, actions: list, download) -> int | None:
    """Bilah tombol rapi di tengah: Muat lebih banyak · Tutup · Unduh Excel, sama tinggi, teks tidak terlipat."""
    count = len(actions) + (1 if download else 0)
    if count == 0:
        return None
    clicked = None
    with st.container(key=f"{key}-actions"):
        side = {1: 1.6, 2: 1.0, 3: 0.45}[count]
        cols = st.columns([side] + [1.25] * count + [side], gap="small")
        slots = cols[1:-1]
        for slot, (name, label, icon, kind, target) in zip(slots, actions):
            if slot.button(label, key=f"{key}-{name}", icon=icon, type=kind, use_container_width=True):
                clicked = target
        if download:
            with slots[len(actions)]:
                download()
    return clicked


def _page_items(page: int, pages: int) -> list:
    """Nomor halaman: selalu 1 dan terakhir, plus 2 di kiri-kanan halaman aktif; celah ditulis "…"."""
    numbers = sorted({1, pages, *range(max(1, page - 2), min(pages, page + 2) + 1)})
    items: list = []
    for number in numbers:
        if items and isinstance(items[-1], int) and number - items[-1] > 1:
            items.append("…")
        items.append(number)
    return ["prev", *items, "next"]


def _nav_buttons(target, page: int, pages: int, *, key: str) -> None:
    state = f"{key}-n"

    def _go(value: int) -> None:
        st.session_state[state] = max(1, min(pages, value))

    with target.container(key=f"{key}-nav"):
        slots = _page_items(page, pages)
        cols = st.columns(len(slots), gap="small")
        for col, item in zip(cols, slots):
            if item == "prev":
                col.button("‹", key=f"{key}-prev", disabled=page <= 1, on_click=_go, args=(page - 1,), use_container_width=True, help="Halaman sebelumnya")
            elif item == "next":
                col.button("›", key=f"{key}-next", disabled=page >= pages, on_click=_go, args=(page + 1,), use_container_width=True, help="Halaman berikutnya")
            elif item == "…":
                col.markdown("<div style='text-align:center;color:#6b7280'>…</div>", unsafe_allow_html=True)
            else:
                col.button(
                    str(item), key=f"{key}-p{item}", type="primary" if item == page else "secondary",
                    on_click=_go, args=(item,), use_container_width=True,
                )


def _page_caption(lo_row: int, hi_row: int, total: int, noun: str, page: int, pages: int) -> str:
    return (
        f"<div class='field-hint' style='padding-top:.45rem'>Baris <b>{fmt_num(lo_row)}–{fmt_num(hi_row)}</b> "
        f"dari <b>{fmt_num(total)}</b> {noun} · hal. {page}/{pages}</div>"
    )


def pager(total: int, *, key: str, noun: str = "baris", default_size: int = 5, download=None) -> tuple[int, int]:
    """Satu baris: keterangan baris · pilihan Baris/hal. · ‹ 1 2 3 … N ›. Mengembalikan rentang baris [lo, hi)."""
    size_key, page_key = f"{key}-size", f"{key}-page"
    sizes = list(PAGE_SIZES) if default_size in PAGE_SIZES else sorted({*PAGE_SIZES, default_size})
    # Data berubah (jumlah baris lain) → kembali ke halaman 1.
    if st.session_state.get(f"{key}-total") != total:
        st.session_state[f"{key}-total"] = total
        st.session_state[f"{page_key}-n"] = 1
    if download:
        info, size_col, dl, nav = st.columns([1.0, 0.42, 0.36, 1.6], vertical_alignment="center")
        _compact_download(dl, download, key)
    else:
        info, size_col, nav = st.columns([1.05, 0.42, 1.6], vertical_alignment="center")
    size = int(
        size_col.selectbox(
            "Baris per halaman", options=sizes, index=sizes.index(default_size), key=size_key,
            format_func=lambda n: f"{n} / hal.", label_visibility="collapsed",
        )
    )
    if st.session_state.get(f"{key}-size-last") != size:
        st.session_state[f"{key}-size-last"] = size
        st.session_state[f"{page_key}-n"] = 1
    pages = max((total - 1) // size + 1, 1)
    page = min(max(int(st.session_state.get(f"{page_key}-n", 1)), 1), pages)
    lo, hi = (page - 1) * size, min(page * size, total)
    info.markdown(_page_caption(lo + 1 if total else 0, hi, total, noun, page, pages), unsafe_allow_html=True)
    if pages > 1:
        _nav_buttons(nav, page, pages, key=page_key)
    return lo, hi


def page_navigator(page: int, pages: int, *, key: str, total: int, page_size: int, noun: str, download=None) -> int:
    """Navigasi halaman bernomor: ‹ 1 2 3 … 80 › + keterangan baris yang tampil. Mengembalikan halaman aktif."""
    lo_row = (page - 1) * page_size + 1 if total else 0
    hi_row = min(page * page_size, total)
    if download:
        info, dl, nav = st.columns([1, 0.32, 1.25], vertical_alignment="center")
        _compact_download(dl, download, key)
    elif pages <= 1:
        st.markdown(_page_caption(lo_row, hi_row, total, noun, page, pages), unsafe_allow_html=True)
        return page
    else:
        info, nav = st.columns([1, 1.25], vertical_alignment="center")
    if pages <= 1:
        info.markdown(_page_caption(lo_row, hi_row, total, noun, page, pages), unsafe_allow_html=True)
        return page
    info.markdown(_page_caption(lo_row, hi_row, total, noun, page, pages), unsafe_allow_html=True)
    _nav_buttons(nav, page, pages, key=key)
    return min(max(int(st.session_state.get(f"{key}-n", page)), 1), pages)


def _axis_values(fig, axis_key: str) -> list:
    """Nilai data semua trace yang memakai sumbu itu (mis. "xaxis", "yaxis2")."""
    dim = axis_key[0]
    ref = dim + axis_key[5:]
    out = []
    for trace in fig.data:
        try:
            values = getattr(trace, dim, None)
            own = getattr(trace, f"{dim}axis", None) or dim
        except Exception:
            continue
        if values is None or own != ref:
            continue
        try:
            out.extend(list(values)[:500])
        except TypeError:
            continue
    return out


def _is_dateish(value) -> bool:
    import re
    from datetime import datetime

    if isinstance(value, (datetime, date, np.datetime64, pd.Timestamp)):
        return True
    return isinstance(value, str) and bool(re.match(r"^\d{4}-\d{2}-\d{2}", value))


def localize_figure(fig):
    """Grafik gaya Indonesia: pemisah 1.234,5; tanggal dd/mm (bukan "Oct 4"); judul kosong tidak tampil "undefined"."""
    try:
        fig.update_layout(separators=",.")
        if fig.layout.title.text is None:
            fig.update_layout(title_text="")
        layout = fig.layout.to_plotly_json()
        keys = {k for k in layout if k.startswith(("xaxis", "yaxis"))} | {"xaxis", "yaxis"}
        for key in keys:
            axis = getattr(fig.layout, key, None)
            if axis is None or axis.tickformat or axis.type in ("category", "multicategory", "log"):
                continue
            values = [v for v in _axis_values(fig, key) if v is not None]
            if not values:
                continue
            if axis.type == "date" or _is_dateish(values[0]):
                stamps = pd.to_datetime(pd.Series(values), errors="coerce").dropna()
                span = (stamps.max() - stamps.min()).days if not stamps.empty else 0
                axis.update(tickformat="%d/%m" if span <= 400 else "%m/%Y", hoverformat="%d/%m/%Y")
            elif all(isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool) for v in values[:50]):
                axis.update(tickformat=",~f")
    except Exception:
        pass
    return fig


def install_plotly_locale() -> None:
    """Semua st.plotly_chart di aplikasi memakai localize_figure."""
    if getattr(st.plotly_chart, "_localized", False):
        return
    original = st.plotly_chart

    def plotly_chart(figure_or_data, *args, **kwargs):
        return original(localize_figure(figure_or_data) if hasattr(figure_or_data, "update_layout") else figure_or_data, *args, **kwargs)

    plotly_chart._localized = True
    st.plotly_chart = plotly_chart
