"""Tab Rekomendasi: Nama & deskripsi, Iklan, Flash sale toko, Exposure media sosial.

Semua sub-tab membaca tabel keputusan yang sama dengan Ringkasan/Prediksi.
"""

from __future__ import annotations

import html
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from src.core.nlp_competitor import build_name_recommendations, clean_text, description_summary
from src.core.recommendations import ads_plan, exposure_plan, flash_sale_plan, flash_sale_template
from src.core.segmentation import association_rules
from src.ui.common import card, download_excel, fmt_date, fmt_idr, fmt_num
from src.utils.format import input_rupiah, show_table

STATUS_TONES = {"Poor": "#fee2e2", "Standard": "#fef9c3", "Excellence": "#dcfce7"}


def _cancel_reason_map(table: pd.DataFrame) -> dict[str, list[str]]:
    if table is None or table.empty or "alasan_batal" not in table.columns:
        return {}
    return {str(k): list(v or []) for k, v in zip(table["item_key"], table["alasan_batal"])}


NAME_LIMIT = 300


def _name_recs(table: pd.DataFrame, frames, params: dict) -> tuple[pd.DataFrame, str]:
    table = table.head(NAME_LIMIT)
    stamp = (len(table), float(table["qty_total"].sum()), len(frames.descriptions), len(frames.competitors))
    cached = st.session_state.get("_name-recs")
    if isinstance(cached, tuple) and cached[0] == stamp:
        return cached[1], cached[2]
    with st.spinner("Membandingkan nama produk dengan kompetitor..."):
        recs, note = build_name_recommendations(table, frames.descriptions, frames.competitors, _cancel_reason_map(table), params)
    st.session_state["_name-recs"] = (stamp, recs, note)
    return recs, note


def _similar_name_rules(table: pd.DataFrame) -> pd.DataFrame:
    """Kelompok cadangan bila association rules kosong: dua kata pertama nama yang sama."""
    heads = table.assign(_head=table["product_name"].map(lambda n: " ".join(clean_text(n).split()[:2])))
    rows = []
    for _head, part in heads.groupby("_head"):
        keys = part["item_key"].astype(str).tolist()
        for a, c in zip(keys, keys[1:]):
            rows.append({"antecedent": a, "consequent": c})
    return pd.DataFrame(rows, columns=["antecedent", "consequent"])


def _names_tab(table: pd.DataFrame, frames, params: dict) -> pd.DataFrame:
    recs, note = _name_recs(table, frames, params)
    if recs.empty:
        st.write("Belum ada produk untuk dinilai.")
        return recs
    if frames.competitors.empty:
        st.caption("Data Produk kompetitor belum diunggah: kata kunci dibaca dari nama produk sendiri.")
    st.caption(f"{note} Dinilai {fmt_num(len(recs))} SKU teratas menurut peringkat (maks. {NAME_LIMIT}).")
    counts = recs["Status skor"].value_counts()
    current = st.session_state.get("name-filter", "Semua")
    cols = st.columns(4)
    for column, status in zip(cols, ("Semua", "Poor", "Standard", "Excellence")):
        total = len(recs) if status == "Semua" else int(counts.get(status, 0))
        if column.button(f"{status} · {fmt_num(total)}", key=f"name-filter-{status}", type="primary" if current == status else "secondary", use_container_width=True):
            st.session_state["name-filter"] = status
            st.rerun()
    view = recs if current == "Semua" else recs.loc[recs["Status skor"].eq(current)]
    size = int(st.selectbox("Tampilkan", [10, 50, 100, 200], index=0, key="name-size"))
    shown_n = int(st.session_state.get("name-more", size))
    shown_n = max(shown_n, size)
    page = view.head(shown_n).reset_index(drop=True)
    columns = ["SKU", "Nama produk saat ini", "Status skor", "Rekomendasi nama baru", "Kata kunci utama"]
    display = page[columns].copy()
    display["Ringkasan deskripsi"] = page["Rekomendasi deskripsi"].map(description_summary)
    table_col, detail_col = st.columns([3, 2], gap="medium")
    with table_col:
        event = show_table(
            display,
            on_select="rerun",
            selection_mode="single-row",
            key="name-table",
            column_config={"Ringkasan deskripsi": st.column_config.TextColumn(width="medium")},
        )
    rows = getattr(getattr(event, "selection", None), "rows", []) or []
    with detail_col:
        if rows:
            _name_detail(page.iloc[rows[0]])
        else:
            st.caption("Pilih satu baris untuk melihat nama rekomendasi, kata kunci, dan deskripsi lengkap.")
    left, right = st.columns(2)
    if len(view) > shown_n and left.button("Tampilkan lebih banyak", key="name-load-more"):
        st.session_state["name-more"] = shown_n + size
        st.rerun()
    with right:
        download_excel(
            view[["SKU", "Nama produk saat ini", "Rekomendasi nama baru", "Kata kunci utama", "Kata kunci pendukung", "Rekomendasi deskripsi"]],
            "rekomendasi_nama_deskripsi.xlsx",
            key="xl-names",
        )
    return recs


def _keyword_chips(text: str) -> str:
    words = [w.strip() for w in str(text or "").split(",") if w.strip()]
    return "".join(
        f"<span style='display:inline-block;margin:2px 4px 2px 0;padding:2px 10px;border-radius:999px;background:#eef2ff;color:#3730a3;font-size:.78rem'>{html.escape(w)}</span>"
        for w in words
    )


def _description_html(text: str) -> str:
    """Paragraf + poin: baris "- x" jadi bullet, baris huruf kapital jadi subjudul tebal."""
    parts: list[str] = []
    bullets: list[str] = []

    def flush() -> None:
        if bullets:
            parts.append("<ul style='margin:.2rem 0 .5rem 1.1rem;padding:0'>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    for raw in str(text or "").split("\n"):
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("- ") or re.match(r"^\d+\.\s", line):
            bullets.append(html.escape(re.sub(r"^(- |\d+\.\s)", "", line)))
            continue
        flush()
        if line.isupper() and len(line) < 60:
            parts.append(f"<div style='font-weight:700;margin-top:.5rem'>{html.escape(line.title())}</div>")
        else:
            parts.append(f"<p style='margin:.2rem 0'>{html.escape(line)}</p>")
    flush()
    return "<div style='font-size:.86rem;line-height:1.5'>" + "".join(parts) + "</div>"


def _name_detail(item: pd.Series) -> None:
    with st.container(border=True):
        st.markdown(f"<div style='font-size:.75rem;color:#64748b'>Nama saat ini · skor {html.escape(str(item['Status skor']))} ({item['Poin skor']}/8)</div>"
                    f"<div style='font-size:.85rem'>{html.escape(str(item['Nama produk saat ini']))}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:.75rem;color:#64748b;margin-top:.5rem'>Nama rekomendasi · skor {html.escape(str(item['Skor nama baru']))}</div>"
                    f"<div style='font-weight:700'>{html.escape(str(item['Rekomendasi nama baru']))}</div>", unsafe_allow_html=True)
        st.markdown(_keyword_chips(item["Kata kunci utama"]) + _keyword_chips(item["Kata kunci pendukung"]), unsafe_allow_html=True)
        checks = item["Kriteria"] if isinstance(item["Kriteria"], dict) else {}
        if checks:
            st.caption(" · ".join(f"{'✅' if ok else '❌'} {name}" for name, ok in checks.items()))
        if not item["Ada deskripsi lama"]:
            st.caption("Deskripsi lama belum diunggah; deskripsi baru disusun dari nama, variasi, dan kata kunci.")
        with st.container(height=360):
            st.markdown(_description_html(item["Rekomendasi deskripsi"]), unsafe_allow_html=True)
        st.caption("Salin deskripsi lengkap (ikon salin di pojok kanan kotak):")
        st.code(item["Rekomendasi deskripsi"], language=None, wrap_lines=True)


ADS_VIEWS = ("Iklan produk", "Iklan grup", "Tidak perlu diiklankan")


def _ads_cards(plan: dict, view: str, target: float) -> None:
    summary = plan.get("ringkasan") or {}
    part = plan.get({"Iklan produk": "produk", "Iklan grup": "grup"}.get(view, "tidak"), pd.DataFrame())
    cols = st.columns(4)
    if view == "Tidak perlu diiklankan":
        reasons = part["Alasan"].str.split(":").str[0].value_counts() if not part.empty else pd.Series(dtype=int)
        card(cols[0], "Tidak perlu diiklankan", fmt_num(len(part)))
        for column, (reason, count) in zip(cols[1:], reasons.head(3).items()):
            card(column, reason, fmt_num(count), hint="SKU")
        return
    budget = float(part["Budget"].sum()) if not part.empty else 0.0
    sales = float(part["Estimasi sales iklan"].sum()) if not part.empty else 0.0
    card(cols[0], f"Budget {view.lower()}", fmt_idr(budget), hint=f"dari total {fmt_idr(summary.get('budget_input', 0))} · sisa {fmt_idr(summary.get('sisa_budget', 0))}")
    card(cols[1], "Estimasi sales dari iklan", fmt_idr(sales))
    card(cols[2], "Estimasi ROAS", fmt_num(sales / budget, 2) if budget > 0 else "–", hint=f"target {fmt_num(target, 2)}")
    card(cols[3], "Item diiklankan", fmt_num(len(part)))


def _ads_tab(table: pd.DataFrame, orders: pd.DataFrame, params: dict, today: date) -> dict:
    cfg = params.get("iklan", {})
    c1, c2, c3 = st.columns([1.6, 1, 1.2])
    span = c1.date_input("Periode beriklan", value=(today, today + timedelta(days=29)), key="ads-span", format="DD/MM/YYYY")
    start, end = (span if isinstance(span, (list, tuple)) and len(span) == 2 else (today, today + timedelta(days=29)))
    target = float(c2.number_input("Target ROAS", min_value=1.0, max_value=100.0, value=float(cfg.get("target_roas", 8)), step=0.5, key="ads-roas"))
    with c3:
        budget = float(input_rupiah("Total budget maksimal", int(cfg.get("budget_maks_rp", 5_000_000)), key="ads-budget-rp"))
    try:
        rules = association_rules(orders)
    except Exception:
        rules = pd.DataFrame()
    if rules is None or rules.empty:
        rules = _similar_name_rules(table)
    plan = ads_plan(table, orders=orders, start=start, end=end, target_roas=target, budget_max=budget, params=params, rules=rules)
    summary = plan["ringkasan"]
    view = st.segmented_control("Jenis rekomendasi", ADS_VIEWS, default=ADS_VIEWS[0], key="ads-view", label_visibility="collapsed") or ADS_VIEWS[0]
    if summary:
        _ads_cards(plan, view, target)
        st.caption(
            f"Total dialokasikan {fmt_idr(summary['budget'])} dari {fmt_idr(summary['budget_input'])} "
            f"({fmt_num(summary['item_diiklankan'])} SKU). Sisa tidak dialokasikan bila permintaan atau stok di atas SS tidak cukup menyerap budget."
        )
        if summary.get("tanggal"):
            st.caption("Tanggal permintaan tinggi: " + ", ".join(fmt_date(d, short=True) for d in summary["tanggal"]))
    if not table.get("biaya_iklan", pd.Series(dtype=float)).fillna(0).gt(0).any():
        st.caption("Laporan iklan belum diunggah atau belum terpetakan ke SKU: ROAS memakai nilai default dari Pengaturan bisnis.")
    kinds = {"Budget": "money", "Estimasi sales iklan": "money", "Estimasi ROAS": "dec"}
    if view == "Iklan produk":
        show_table(plan["produk"], kinds=kinds)
    elif view == "Iklan grup":
        st.caption("Kelompok dari produk yang sering dibeli bersamaan (association rules) atau nama sejenis.")
        show_table(plan["grup"], kinds=kinds)
    else:
        show_table(plan["tidak"])
    download_excel({"Iklan produk": plan["produk"], "Iklan grup": plan["grup"], "Tidak perlu diiklankan": plan["tidak"]}, "rekomendasi_iklan.xlsx", key="xl-ads")
    return plan


def _stock_date_text(table: pd.DataFrame) -> str:
    if not {"stock_snapshot_at", "ada_data_stok"} <= set(table.columns):
        return ""
    known = table["ada_data_stok"].fillna(False).astype(bool)
    stamps = pd.to_datetime(table.loc[known, "stock_snapshot_at"], errors="coerce").dropna()
    return fmt_date(stamps.max()) if not stamps.empty else ""


def _flash_tab(table: pd.DataFrame, params: dict, today: date, user_root: Path) -> pd.DataFrame:
    start = st.date_input("Mulai rencana flash sale (1 bulan)", value=today + timedelta(days=1), key="flash-start", format="DD/MM/YYYY")
    has_stock = bool(table.get("ada_data_stok", pd.Series(dtype=bool)).fillna(False).any())
    if not has_stock:
        st.info("Data stok belum pernah diunggah (menu Data stok), jadi kuota flash sale belum bisa dihitung tanpa mengganggu kebutuhan prediksi + SS.")
        return pd.DataFrame()
    stamp = _stock_date_text(table)
    plan = flash_sale_plan(table, start=start, params=params)
    if plan.empty:
        st.info("Belum ada SKU yang laku dengan stok tersisa dan margin aman untuk flash sale.")
        return plan
    limited = plan["Alasan"].astype(str).str.startswith("Stok terbatas").all()
    days = sorted(plan["Tanggal"].unique())
    note = f"Stok per {stamp} (unggahan terakhir). " if stamp else ""
    if limited:
        st.warning(f"{note}Stok terbatas: tidak ada SKU dengan stok lebih setelah kebutuhan + SS. Daftar berisi SKU laku dengan sisa stok terbesar dan kuota kecil.")
    else:
        st.caption(f"{note}{fmt_num(len(plan))} slot pada {len(days)} hari · {plan['SKU'].nunique()} SKU berbeda. Kuota tidak mengganggu kebutuhan prediksi + SS.")
    weeks = [days[i : i + 7] for i in range(0, len(days), 7)]
    for week in weeks:
        cols = st.columns(7)
        for column, day in zip(cols, week):
            part = plan.loc[plan["Tanggal"] == day]
            items = "".join(f"<div style='font-size:.72rem;line-height:1.3;margin-top:3px'>• {html.escape(str(name)[:38])}</div>" for name in part["Produk"])
            column.markdown(
                f"<div style='border:1px solid #e2e8f0;border-radius:8px;padding:6px;min-height:120px'><b>{fmt_date(day, short=True)}</b>{items}</div>",
                unsafe_allow_html=True,
            )
    show_table(plan, kinds={"Harga saat ini": "money", "Harga flash sale": "money", "Diskon (%)": "pct", "Stok saat ini": "count", "Saran stok flash sale": "count"})
    left, right = st.columns(2)
    if left.button("Submit rencana flash sale", type="primary", key="flash-submit"):
        folder = Path(user_root) / "flash_sale"
        folder.mkdir(parents=True, exist_ok=True)
        plan.to_csv(folder / f"rencana_{start.isoformat()}.csv", index=False)
        st.session_state["flash-submitted"] = start.isoformat()
        st.success(f"Rencana flash sale mulai {fmt_date(start)} disimpan.")
    with right:
        download_excel(flash_sale_template(plan, params), f"template_flash_sale_{start.isoformat()}.xlsx", key="xl-flash", label="Unduh template Shopee")
    return plan


WEEKDAYS = ("Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min")


def month_grid(year: int, month: int) -> list[list[date | None]]:
    """Minggu kalender Senin–Minggu; sel di luar bulan = None."""
    import calendar

    return [[d if d.month == month else None for d in week] for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)]


def _exposure_calendar(plan: pd.DataFrame, month_start: date) -> None:
    by_day: dict[date, list[str]] = {}
    for _, row in plan.iterrows():
        by_day.setdefault(pd.Timestamp(row["Tanggal"]).date(), []).append(str(row["Produk"]))
    picked = st.session_state.get("expo-day")
    head = st.columns(7)
    for column, name in zip(head, WEEKDAYS):
        column.markdown(f"<div style='text-align:center;font-size:.75rem;color:#64748b;font-weight:700'>{name}</div>", unsafe_allow_html=True)
    for week in month_grid(month_start.year, month_start.month):
        cols = st.columns(7)
        for column, day in zip(cols, week):
            if day is None:
                column.markdown("<div style='min-height:96px'></div>", unsafe_allow_html=True)
                continue
            items = by_day.get(day, [])
            with column.container(border=True):
                label = f"{day.day}" + (f" · {len(items)}" if items else "")
                kind = "primary" if picked == day.isoformat() else "secondary"
                if st.button(label, key=f"expo-day-{day.isoformat()}", use_container_width=True, type=kind, disabled=not items):
                    st.session_state["expo-day"] = day.isoformat()
                    st.rerun()
                lines = "".join(f"<div style='font-size:.68rem;line-height:1.25'>• {html.escape(name[:26])}</div>" for name in items[:2])
                if len(items) > 2:
                    lines += f"<div style='font-size:.68rem;color:#64748b'>+{len(items) - 2} lainnya</div>"
                st.markdown(lines or "<div style='font-size:.68rem;color:#cbd5e1'>–</div>", unsafe_allow_html=True)


def _exposure_tab(table: pd.DataFrame, names: pd.DataFrame, today: date, ads: dict, flash: pd.DataFrame) -> None:
    start = st.date_input("Mulai kalender exposure (1 bulan)", value=today, key="expo-start", format="DD/MM/YYYY")
    ad_days = [d for d in (ads.get("ringkasan", {}) or {}).get("tanggal", []) if d >= start] if ads else []
    plan = exposure_plan(table, names=names, cancel_reasons=_cancel_reason_map(table), start=start, ad_days=ad_days, flash=flash)
    if plan.empty:
        st.write("Belum ada SKU yang layak di-exposure (stok aman dan ada prediksi).")
        return
    st.caption("Tanggal tayang diselaraskan: sehari sebelum flash sale SKU itu, atau tanggal permintaan tinggi rencana iklan. Klik tanggal untuk melihat detailnya.")
    months = sorted({pd.Timestamp(d).to_period("M") for d in plan["Tanggal"]})
    month_key = st.session_state.get("expo-month")
    labels = [m.strftime("%m/%Y") for m in months]
    if len(months) > 1:
        month_key = st.segmented_control("Bulan", labels, default=labels[0], key="expo-month", label_visibility="collapsed") or labels[0]
    current = months[labels.index(month_key)] if month_key in labels else months[0]
    _exposure_calendar(plan, current.to_timestamp().date())
    picked = st.session_state.get("expo-day")
    detail = plan
    if picked:
        detail = plan.loc[pd.to_datetime(plan["Tanggal"]).dt.date.astype(str) == picked]
        left, right = st.columns([3, 1])
        left.markdown(f"**Detail {fmt_date(date.fromisoformat(picked))}** · {fmt_num(len(detail))} SKU")
        if right.button("Tampilkan semua", key="expo-all", use_container_width=True):
            st.session_state.pop("expo-day", None)
            st.rerun()
    for _, row in detail.iterrows():
        with st.container(border=True):
            st.markdown(f"**{fmt_date(row['Tanggal'])} · {html.escape(row['Produk'])}** · SKU {html.escape(row['SKU'])} {('· ' + html.escape(row['Label'])) if row['Label'] else ''}")
            st.markdown(f"Kenapa layak: {html.escape(row['Kenapa layak'])}")
            st.markdown(f"Hook: _{html.escape(row['Hook masalah'])}_")
            st.markdown(row["Poin penting"])
    download_excel(plan, "kalender_exposure.xlsx", key="xl-expo")


def show_recommendations(table: pd.DataFrame, *, orders: pd.DataFrame, orders_all: pd.DataFrame, frames, params: dict, today: date, user_root: Path) -> None:
    st.subheader("Rekomendasi")
    if table is None or table.empty:
        st.write("Jalankan analisis terlebih dahulu.")
        return
    tabs = st.tabs(["Nama & deskripsi", "Iklan", "Flash sale toko", "Exposure media sosial"])
    names = pd.DataFrame()
    plan_ads: dict = {}
    flash = pd.DataFrame()
    with tabs[0]:
        try:
            names = _names_tab(table, frames, params)
        except Exception as exc:
            st.warning(f"Rekomendasi nama belum bisa dibuat: {exc}")
    with tabs[1]:
        try:
            plan_ads = _ads_tab(table, orders, params, today)
        except Exception as exc:
            st.warning(f"Rekomendasi iklan belum bisa dibuat: {exc}")
    with tabs[2]:
        try:
            flash = _flash_tab(table, params, today, user_root)
        except Exception as exc:
            st.warning(f"Rencana flash sale belum bisa dibuat: {exc}")
    with tabs[3]:
        try:
            _exposure_tab(table, names, today, plan_ads, flash)
        except Exception as exc:
            st.warning(f"Kalender exposure belum bisa dibuat: {exc}")
