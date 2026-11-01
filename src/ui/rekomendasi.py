"""Tab Rekomendasi: Nama & deskripsi, Iklan, Flash sale toko, Exposure media sosial.

Semua sub-tab membaca tabel keputusan yang sama dengan Ringkasan/Prediksi.
"""

from __future__ import annotations

import html
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from src.core.nlp_competitor import build_name_recommendations, clean_text
from src.core.recommendations import ads_plan, exposure_plan, flash_sale_plan, flash_sale_template
from src.core.segmentation import association_rules
from src.ui.common import card, download_excel, fmt_date, fmt_idr, fmt_num, fmt_pct

STATUS_TONES = {"Poor": "#fee2e2", "Standard": "#fef9c3", "Excellence": "#dcfce7"}
DESC_PREVIEW = 400


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
    page = view.head(shown_n)
    columns = ["SKU", "Nama produk saat ini", "Status skor", "Rekomendasi nama baru", "Kata kunci utama", "Rekomendasi deskripsi"]
    display = page[columns].copy()
    display["Rekomendasi deskripsi"] = display["Rekomendasi deskripsi"].map(lambda t: t if len(t) <= DESC_PREVIEW else t[:DESC_PREVIEW].rstrip() + " …")
    event = st.dataframe(
        display,
        hide_index=True,
        use_container_width=True,
        height=420,
        on_select="rerun",
        selection_mode="single-row",
        key="name-table",
        column_config={"Rekomendasi deskripsi": st.column_config.TextColumn(width="large")},
    )
    left, right = st.columns(2)
    if len(view) > shown_n and left.button("Load more", key="name-load-more"):
        st.session_state["name-more"] = shown_n + size
        st.rerun()
    with right:
        download_excel(
            view[["SKU", "Nama produk saat ini", "Rekomendasi nama baru", "Kata kunci utama", "Kata kunci pendukung", "Rekomendasi deskripsi"]],
            "rekomendasi_nama_deskripsi.xlsx",
            key="xl-names",
        )
    rows = getattr(getattr(event, "selection", None), "rows", []) or []
    if rows:
        item = page.iloc[rows[0]]
        with st.container(border=True):
            st.markdown(f"**Analisa · {html.escape(item['Nama produk saat ini'])}**")
            st.markdown(f"Skor nama lama: **{item['Status skor']}** ({item['Poin skor']}/8). {item['Alasan skor']}.")
            checks = item["Kriteria"] if isinstance(item["Kriteria"], dict) else {}
            if checks:
                st.markdown(" · ".join(f"{'✅' if ok else '❌'} {name}" for name, ok in checks.items()))
            st.markdown(f"Kata kunci utama: **{item['Kata kunci utama'] or '-'}** · pendukung: {item['Kata kunci pendukung'] or '-'}")
            strengths = item["Kekuatan deskripsi lama"] if isinstance(item["Kekuatan deskripsi lama"], dict) else {}
            if strengths and item["Ada deskripsi lama"]:
                st.markdown("Kekuatan deskripsi lama:")
                st.markdown("\n".join(f"- {'✅' if ok else '➖'} {aspect}" for aspect, ok in strengths.items()))
            else:
                st.caption("Deskripsi lama belum diunggah (menu Deskripsi produk); deskripsi baru disusun dari nama, variasi, dan kata kunci.")
            st.text_area("Deskripsi siap tempel ke Shopee", item["Rekomendasi deskripsi"], height=320, key=f"desc-{item['SKU']}")
    return recs


def _ads_tab(table: pd.DataFrame, orders: pd.DataFrame, params: dict, today: date) -> dict:
    cfg = params.get("iklan", {})
    c1, c2, c3 = st.columns([1.6, 1, 1.2])
    span = c1.date_input("Periode beriklan", value=(today, today + timedelta(days=29)), key="ads-span", format="DD/MM/YYYY")
    start, end = (span if isinstance(span, (list, tuple)) and len(span) == 2 else (today, today + timedelta(days=29)))
    target = float(c2.number_input("Target ROAS", min_value=1.0, max_value=100.0, value=float(cfg.get("target_roas", 8)), step=0.5, key="ads-roas"))
    budget = float(c3.number_input("Total budget maksimal (Rp)", min_value=0, value=int(cfg.get("budget_maks_rp", 5_000_000)), step=100_000, key="ads-budget"))
    try:
        rules = association_rules(orders)
    except Exception:
        rules = pd.DataFrame()
    if rules is None or rules.empty:
        rules = _similar_name_rules(table)
    plan = ads_plan(table, orders=orders, start=start, end=end, target_roas=target, budget_max=budget, params=params, rules=rules)
    summary = plan["ringkasan"]
    if summary:
        cols = st.columns(4)
        card(cols[0], "Estimasi sales dari iklan", fmt_idr(summary["estimasi_sales"]), hint=f"budget {fmt_idr(summary['budget'])}")
        card(cols[1], "Estimasi ROAS", fmt_num(summary["estimasi_roas"], 1), hint=f"target {fmt_num(target, 1)}")
        card(cols[2], "Item diiklankan", fmt_num(summary["item_diiklankan"]))
        card(cols[3], "Tidak perlu diiklankan", fmt_num(summary["item_tidak"]))
        if summary.get("tanggal"):
            st.caption("Tanggal permintaan tinggi: " + ", ".join(fmt_date(d, short=True) for d in summary["tanggal"]))
    if not table.get("biaya_iklan", pd.Series(dtype=float)).fillna(0).gt(0).any():
        st.caption("Laporan iklan belum diunggah atau belum terpetakan ke SKU: ROAS memakai nilai default dari Pengaturan bisnis.")
    money = {"Budget": st.column_config.NumberColumn(format="Rp %d"), "Estimasi sales iklan": st.column_config.NumberColumn(format="Rp %d"), "Estimasi ROAS": st.column_config.NumberColumn(format="%.1f")}
    t1, t2, t3 = st.tabs(["Iklan produk", "Iklan grup", "Tidak perlu diiklankan"])
    with t1:
        st.dataframe(plan["produk"], hide_index=True, use_container_width=True, column_config=money)
    with t2:
        st.caption("Kelompok dari produk yang sering dibeli bersamaan (association rules) atau nama sejenis.")
        st.dataframe(plan["grup"], hide_index=True, use_container_width=True, column_config=money)
    with t3:
        st.dataframe(plan["tidak"], hide_index=True, use_container_width=True)
    download_excel({"Iklan produk": plan["produk"], "Iklan grup": plan["grup"], "Tidak perlu diiklankan": plan["tidak"]}, "rekomendasi_iklan.xlsx", key="xl-ads")
    return plan


def _flash_tab(table: pd.DataFrame, params: dict, today: date, user_root: Path) -> pd.DataFrame:
    start = st.date_input("Mulai rencana flash sale (1 bulan)", value=today + timedelta(days=1), key="flash-start", format="DD/MM/YYYY")
    plan = flash_sale_plan(table, start=start, params=params)
    if plan.empty:
        st.info("Belum ada SKU dengan stok lebih setelah kebutuhan + safety stock, atau Data stok belum diunggah. Flash sale tidak disarankan agar kebutuhan prediksi tetap tertutup.")
        return plan
    days = sorted(plan["Tanggal"].unique())
    st.caption(f"{fmt_num(len(plan))} slot pada {len(days)} hari · {plan['SKU'].nunique()} SKU berbeda. Kuota tidak mengganggu kebutuhan prediksi + SS.")
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
    st.dataframe(
        plan,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Harga saat ini": st.column_config.NumberColumn(format="Rp %d"),
            "Harga flash sale": st.column_config.NumberColumn(format="Rp %d"),
            "Diskon (%)": st.column_config.NumberColumn(format="%.0f%%"),
        },
    )
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


def _exposure_tab(table: pd.DataFrame, names: pd.DataFrame, today: date, ads: dict, flash: pd.DataFrame) -> None:
    start = st.date_input("Mulai kalender exposure (1 bulan)", value=today, key="expo-start", format="DD/MM/YYYY")
    ad_days = [d for d in (ads.get("ringkasan", {}) or {}).get("tanggal", []) if d >= start] if ads else []
    plan = exposure_plan(table, names=names, cancel_reasons=_cancel_reason_map(table), start=start, ad_days=ad_days, flash=flash)
    if plan.empty:
        st.write("Belum ada SKU yang layak di-exposure (stok aman dan ada prediksi).")
        return
    st.caption("Tanggal tayang diselaraskan: sehari sebelum flash sale SKU itu, atau tanggal permintaan tinggi rencana iklan.")
    for _, row in plan.iterrows():
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
