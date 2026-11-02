"""Halaman Setting (Revisi Final 4F–4H): SKU dikecualikan, Kalkulator biaya, Laporan margin,
Kapasitas gudang, Kedatangan impor, Kelola user. Ubah data latih TIDAK ada di sini."""

from __future__ import annotations

import html
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.core import margin as margin_core
from src.core import warehouse
from src.core.access import allowed, setting_tabs
from src.core.feature_store import IMPORT_STATUSES
from src.core.fmt import fmt_date, fmt_date_short
from src.core.periods import last_full_month
from src.core.promo import exclusion_suggestions, product_label
from src.ui.common import ID_MONTHS, button_tabs, card, download_excel, fmt_idr, fmt_num, fmt_pct
from src.ui.confirm import confirm_action
from src.ui.feature_data import FeatureData, bump, product_frame
from src.utils.format import input_rupiah, show_table


def _read_upload(upload) -> pd.DataFrame:
    name = str(getattr(upload, "name", "")).lower()
    return pd.read_csv(upload, dtype=str) if name.endswith(".csv") else pd.read_excel(upload, dtype=str)


def _require(menu: str, need: str) -> None:
    from auth.ui import require

    require(menu, need)


def show_setting(tab_slug: str, *, role: str, username: str, features, table: pd.DataFrame | None, data: FeatureData, orders: pd.DataFrame | None, today: date, user_root: Path) -> str:
    """Render tab Setting yang dipilih; kembalikan slug tab aktif (untuk URL)."""
    tabs = setting_tabs(role)
    if not tabs:
        st.warning("Role Anda tidak punya akses ke Setting.")
        st.stop()
    slugs = [slug for slug, _label, _menu in tabs]
    if tab_slug not in slugs:
        tab_slug = slugs[0]
    clicked = button_tabs([(slug, label) for slug, label, _menu in tabs], tab_slug, key="setting-tab")
    if clicked and clicked != tab_slug:
        st.session_state["setting-slug"] = clicked
        st.rerun()
    picked = tab_slug
    menu = next(m for s, _l, m in tabs if s == picked)
    _require(menu, "view")
    table = table if isinstance(table, pd.DataFrame) else pd.DataFrame()
    if picked == "sku-dikecualikan":
        _excluded_tab(features, table, username)
    elif picked == "kalkulator-biaya":
        _calculator_tab(features, table, data, username, today)
    elif picked == "laporan-margin":
        _margin_report_tab(table, data, orders, today)
    elif picked == "kapasitas-gudang":
        _capacity_tab(features, table, data, role, username, today, user_root)
    elif picked == "kedatangan-impor":
        _import_tab(features, table, role, username, today)
    elif picked == "kelola-user":
        from auth.ui import current_user, get_repo, users_panel

        users_panel(get_repo(), current_user())
    return picked


# ---------------------------------------------------------------- SKU dikecualikan


def _excluded_tab(features, table: pd.DataFrame, username: str) -> None:
    st.markdown("**SKU dikecualikan**")
    st.caption("SKU di sini keluar dari peringkat, safety stock, iklan, flash sale, dan exposure (filter di awal pipeline). Di tabel alokasi iklan tampil sebagai \"SKU jasa\".")
    frame = features.read("excluded_sku")
    if frame.empty:
        st.info("Belum ada SKU yang dikecualikan.")
    else:
        for _, row in frame.sort_values("sku").iterrows():
            c1, c2, c3, c4 = st.columns([1.2, 3, 1.4, 0.8], vertical_alignment="center")
            c1.markdown(f"**{html.escape(str(row['sku']))}**")
            c2.markdown(html.escape(str(row["nama"] or "-")))
            c3.caption(f"{row['jenis'] or '-'} · {row['added_by']}")
            if c4.button("Hapus", key=f"exc-del-{row['sku']}", use_container_width=True):

                def _delete(sku: str = str(row["sku"])) -> None:
                    _require("setting_sku_dikecualikan", "edit")
                    features.remove("excluded_sku", {"sku": sku}, username=username, action="hapus:sku_dikecualikan")
                    bump(st.session_state)

                confirm_action("Hapus dari SKU dikecualikan?", f"SKU {html.escape(str(row['sku']))} akan kembali masuk peringkat dan rekomendasi.", _delete, confirm_label="Ya, hapus")
    with st.form("exc-add", clear_on_submit=True):
        a1, a2, a3 = st.columns([1.2, 3, 1])
        sku = a1.text_input("SKU")
        name = a2.text_input("Nama / alasan")
        a3.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        if a3.form_submit_button("Tambah", type="primary") and sku.strip():
            _require("setting_sku_dikecualikan", "edit")
            features.replace("excluded_sku", [{"sku": sku.strip(), "nama": name.strip(), "jenis": "Manual", "added_by": username, "added_at": datetime.now()}], keys=["sku"], username=username, action="tambah:sku_dikecualikan")
            bump(st.session_state)
            st.rerun()
    products = table[["sku", "product_name"]] if not table.empty else pd.DataFrame(columns=["sku", "product_name"])
    suggestions = exclusion_suggestions(products, set(frame["sku"].astype(str)) if not frame.empty else set())
    if not suggestions.empty:
        st.markdown("**Usulan** (nama berisi packing, bubble wrap, biaya, ongkir) — tekan Kecualikan untuk mengonfirmasi.")
        for _, row in suggestions.iterrows():
            c1, c2, c3, c4 = st.columns([1.2, 3, 1.4, 0.8], vertical_alignment="center")
            c1.markdown(html.escape(str(row["sku"])))
            c2.markdown(html.escape(str(row["nama"])))
            c3.caption(str(row["alasan"]))
            if c4.button("Kecualikan", key=f"exc-sug-{row['sku']}", use_container_width=True):
                _require("setting_sku_dikecualikan", "edit")
                features.replace("excluded_sku", [{"sku": str(row["sku"]), "nama": str(row["nama"]), "jenis": "SKU jasa", "added_by": username, "added_at": datetime.now()}], keys=["sku"], username=username, action="tambah:sku_dikecualikan")
                bump(st.session_state)
                st.rerun()


# ---------------------------------------------------------------- Kalkulator biaya


def _calculator_tab(features, table: pd.DataFrame, data: FeatureData, username: str, today: date) -> None:
    st.markdown("**Kalkulator biaya** · simulasi tidak menyimpan")
    st.caption("Harga jual = harga data produk terkini. Margin = harga × (1 − komisi − layanan − transaksi) − HPP − packing − iklan per unit − voucher − ongkir penjual.")
    products = product_frame(table)
    if products.empty:
        st.info("Jalankan analisa dulu agar daftar SKU dan harga data produk tersedia.")
        return
    labels = {sku: product_label(sku, name, var) for sku, name, var in zip(products["sku"], products["product_name"], products["variation"])}
    sku = st.selectbox("SKU", list(labels), format_func=lambda s: labels[s], key="calc-sku")
    price = float(products.loc[products["sku"] == sku, "price"].iloc[0])
    comp = margin_core.effective_components(data.components, sku, on=today)
    if comp is None:
        st.caption("Komponen biaya SKU ini belum diunggah; isi kolom di bawah untuk simulasi.")
        comp = margin_core.Components()
    ad_default = data.ad_per_unit.get(sku, 0.0)
    c = st.columns(4)
    c[0].markdown(f"<div class='stat-card'><div class='readable-metric-label'>Harga jual (data produk)</div><div class='readable-metric-value'>{fmt_idr(price)}</div></div>", unsafe_allow_html=True)
    with c[1]:
        hpp = float(input_rupiah("HPP", int(comp.hpp), key=f"calc-hpp-{sku}"))
    komisi = float(c[2].number_input("Komisi (%)", 0.0, 50.0, float(comp.komisi_pct), 0.1, key=f"calc-kom-{sku}"))
    layanan = float(c[3].number_input("Biaya layanan (%)", 0.0, 50.0, float(comp.layanan_pct), 0.1, key=f"calc-lay-{sku}"))
    c = st.columns(4)
    transaksi = float(c[0].number_input("Biaya transaksi (%)", 0.0, 20.0, float(comp.transaksi_pct), 0.1, key=f"calc-trx-{sku}"))
    with c[1]:
        packing = float(input_rupiah("Packing", int(comp.packing), key=f"calc-pack-{sku}"))
    with c[2]:
        iklan = float(input_rupiah("Iklan per unit", int(round(ad_default)), key=f"calc-ad-{sku}", help="Default = biaya iklan SKU periode ÷ QTY bersih SKU periode."))
    with c[3]:
        voucher = float(input_rupiah("Voucher", int(comp.voucher), key=f"calc-vou-{sku}"))
    ongkir = float(input_rupiah("Ongkir penjual", int(comp.ongkir_penjual), key=f"calc-ong-{sku}"))
    sim = margin_core.Components(hpp=hpp, komisi_pct=komisi, layanan_pct=layanan, transaksi_pct=transaksi, packing=packing, voucher=voucher, ongkir_penjual=ongkir)
    value, pct = margin_core.unit_margin(price, sim, iklan)
    cols = st.columns(3)
    card(cols[0], "Margin per unit", fmt_idr(value), hint=fmt_pct(pct, 1))
    card(cols[1], "Harga minimal margin 8%", fmt_idr(margin_core.harga_minimal(sim, iklan, 8.0)))
    card(cols[2], "Harga minimal margin 0%", fmt_idr(margin_core.harga_minimal(sim, iklan, 0.0)))
    show_table(margin_core.breakdown(price, sim, iklan), kinds={"Rp per unit": "money", "% harga": "pct"})

    st.markdown("**Unggah komponen biaya** (berperiode: baris baru menutup periode baris lama)")
    template = pd.DataFrame(columns=list(margin_core.TEMPLATE_COLUMNS))
    u1, u2 = st.columns([3, 1])
    upload = u1.file_uploader("File komponen biaya", type=["xlsx", "csv"], key="cost-upload")
    with u2:
        download_excel(template, "template_komponen_biaya.xlsx", key="xl-cost-tpl", label="Unduh template")
    if upload is not None and st.button("Simpan komponen biaya", key="cost-save", type="primary"):
        _require("setting_kalkulator_biaya", "edit")
        rows = margin_core.normalize_components(_read_upload(upload))
        bad = rows["berlaku_mulai"].isna()
        if bad.any():
            st.error(f"{int(bad.sum())} baris tanpa tanggal berlaku_mulai yang valid tidak disimpan.")
        rows = rows.loc[~bad]
        if not rows.empty:
            existing = features.read("cost_component")
            closed = margin_core.close_previous_periods(existing, rows)
            if not closed.empty:
                features.replace("cost_component", closed, keys=["id"], username=username, action="tutup:komponen_biaya")
            features.insert("cost_component", rows.assign(uploaded_by=username), username=username, action="unggah:komponen_biaya")
            bump(st.session_state)
            st.success(f"{fmt_num(len(rows))} baris komponen biaya disimpan; {fmt_num(len(closed))} periode lama ditutup.")
    margin = data.margin
    total = len(products)
    complete = int(margin["lengkap"].sum()) if not margin.empty else 0
    with_hpp = int(margin["ada_hpp"].sum()) if not margin.empty else 0
    st.caption(f"Kelengkapan: {fmt_num(complete)} dari {fmt_num(total)} SKU punya komponen lengkap · {fmt_num(total - with_hpp)} SKU tanpa HPP.")


# ---------------------------------------------------------------- Laporan margin


def _margin_report_tab(table: pd.DataFrame, data: FeatureData, orders: pd.DataFrame | None, today: date) -> None:
    st.markdown("**Laporan margin**")
    if data.components.empty:
        st.info("Komponen biaya belum diunggah (Setting › Kalkulator biaya).")
        return
    if orders is None or orders.empty:
        st.info("Belum ada transaksi.")
        return
    stamps = pd.to_datetime(orders["order_time"], errors="coerce")
    months = sorted(stamps.dt.to_period("M").dropna().astype(str).unique())
    default_lo, _hi = last_full_month(stamps.max().date())
    default = f"{default_lo.year:04d}-{default_lo.month:02d}"
    month = st.selectbox("Periode", months[::-1], index=months[::-1].index(default) if default in months else 0, format_func=lambda k: f"{ID_MONTHS[int(k[5:]) - 1]} {k[:4]}", key="margin-month")
    lines = orders.loc[stamps.dt.to_period("M").astype(str) == month].assign(sku=lambda f: f["sku"].astype(str))
    rows = margin_core.transaction_margins(lines, data.components, data.ad_per_unit)
    if rows.empty:
        st.info("Tidak ada transaksi bersih dengan komponen biaya yang berlaku pada periode ini.")
        return
    per_sku = rows.groupby("sku").agg(qty=("qty", "sum"), margin_total=("margin_total", "sum"), harga=("harga", "mean"), margin_unit=("margin_unit", "mean")).reset_index()
    per_sku["margin_pct"] = per_sku["margin_unit"] / per_sku["harga"] * 100
    minus = per_sku.loc[per_sku["margin_total"] < 0]
    thin = per_sku.loc[(per_sku["margin_pct"] >= 0) & (per_sku["margin_pct"] < margin_core.THIN_MARGIN_PCT)]
    cols = st.columns(4)
    card(cols[0], "Margin kotor", fmt_idr(rows["margin_total"].sum()), hint="Σ margin × QTY bersih")
    card(cols[1], "SKU margin minus", fmt_num(len(minus)))
    card(cols[2], "Kerugian", fmt_idr(minus["margin_total"].sum()), hint="Σ margin negatif")
    card(cols[3], "SKU margin tipis (< 5%)", fmt_num(len(thin)))
    cost_cols = ["Komisi & biaya Shopee", "HPP", "Packing", "Iklan", "Voucher", "Ongkir penjual"]
    names = table.drop_duplicates("sku").set_index(table["sku"].astype(str).drop_duplicates())["product_name"].to_dict() if not table.empty else {}
    if not minus.empty:
        avg = rows[cost_cols].div(rows["harga"], axis=0).mean()
        causes = []
        for sku in minus["sku"]:
            part = rows.loc[rows["sku"] == sku, cost_cols].div(rows.loc[rows["sku"] == sku, "harga"], axis=0).mean()
            excess = (part - avg).sort_values(ascending=False)
            causes.append(excess.index[0] if not excess.empty else "-")
        view = minus.assign(Produk=minus["sku"].map(names).fillna(""), Penyebab=causes)
        view = view.rename(columns={"sku": "SKU", "qty": "QTY bersih", "harga": "Harga rata-rata", "margin_unit": "Margin per unit", "margin_pct": "Margin (%)", "margin_total": "Total margin"})
        st.markdown("**Item margin minus** · penyebab = komponen biaya terbesar di atas rata-rata")
        show_table(view[["SKU", "Produk", "QTY bersih", "Harga rata-rata", "Margin per unit", "Margin (%)", "Total margin", "Penyebab"]].sort_values("Total margin"))
        st.caption("SKU margin minus otomatis \"Tahan · margin minus\" di Iklan, Flash sale, dan Exposure.")
    pick = st.selectbox("Rincian per unit SKU", per_sku["sku"].tolist(), format_func=lambda s: f"{s} · {names.get(s, '')}", key="margin-detail")
    comp = margin_core.effective_components(data.components, pick, on=today)
    if comp:
        price = float(per_sku.loc[per_sku["sku"] == pick, "harga"].iloc[0])
        show_table(margin_core.breakdown(price, comp, data.ad_per_unit.get(pick, 0.0)), kinds={"Rp per unit": "money", "% harga": "pct"})
        st.caption(f"Harga minimal margin 8%: {fmt_idr(margin_core.harga_minimal(comp, data.ad_per_unit.get(pick, 0.0), 8.0))}")


# ---------------------------------------------------------------- Kapasitas gudang


def _capacity_tab(features, table: pd.DataFrame, data: FeatureData, role: str, username: str, today: date, user_root: Path) -> None:
    st.markdown("**Kapasitas gudang**")
    may_upload = allowed(role, "setting_kapasitas_gudang", "upload")
    with st.expander("Unggah layout rak, dimensi karton, dan denah", expanded=False):
        if not may_upload:
            st.caption("Role Anda hanya melihat. Unggahan oleh Team DC atau Super user.")
        t1, t2 = st.columns(2)
        with t1:
            download_excel(pd.DataFrame(columns=list(warehouse.LAYOUT_COLUMNS)), "template_layout_rak.xlsx", key="xl-layout-tpl", label="Unduh template layout")
            layout_file = st.file_uploader("Layout rak (kode_rak, zona, panjang_cm, lebar_cm, tinggi_cm, faktor_isi)", type=["xlsx", "csv"], key="layout-upload", disabled=not may_upload)
            if layout_file is not None and may_upload and st.button("Simpan layout", key="layout-save", type="primary"):
                _require("setting_kapasitas_gudang", "upload")
                good, bad = warehouse.normalize_layout(_read_upload(layout_file))
                if not bad.empty:
                    show_table(bad)
                if not good.empty:
                    version = datetime.now().strftime("%Y%m%d%H%M%S")
                    features.insert("warehouse_rack", good.assign(layout_version=version), username=username, action="unggah:layout_gudang")
                    bump(st.session_state)
                    st.success(f"Layout {fmt_num(len(good))} rak disimpan (versi {version}).")
        with t2:
            download_excel(pd.DataFrame(columns=list(warehouse.CARTON_COLUMNS)), "template_dimensi_karton.xlsx", key="xl-carton-tpl", label="Unduh template karton")
            carton_file = st.file_uploader("Dimensi karton (sku, varian, panjang_cm, lebar_cm, tinggi_cm, isi_per_karton)", type=["xlsx", "csv"], key="carton-upload", disabled=not may_upload)
            if carton_file is not None and may_upload and st.button("Simpan dimensi karton", key="carton-save", type="primary"):
                _require("setting_kapasitas_gudang", "upload")
                raw = _read_upload(carton_file)
                raw.columns = [str(c).strip().lower() for c in raw.columns]
                missing = [c for c in warehouse.CARTON_COLUMNS if c not in raw.columns and c != "varian"]
                if missing:
                    st.error("Kolom hilang: " + ", ".join(missing))
                else:
                    raw["varian"] = raw.get("varian", "").fillna("") if "varian" in raw.columns else ""
                    raw["sku"] = raw["sku"].astype(str).str.strip().str.replace(r"\.0+$", "", regex=True)
                    for column in ("panjang_cm", "lebar_cm", "tinggi_cm", "isi_per_karton"):
                        raw[column] = pd.to_numeric(raw[column].astype(str).str.replace(",", "."), errors="coerce")
                    raw["isi_per_karton"] = raw["isi_per_karton"].fillna(1)
                    clean = raw.dropna(subset=["panjang_cm", "lebar_cm", "tinggi_cm"])
                    features.replace("carton_dimension", clean[list(warehouse.CARTON_COLUMNS)], keys=["sku", "varian"], username=username, action="unggah:dimensi_karton")
                    bump(st.session_state)
                    st.success(f"{fmt_num(len(clean))} dimensi karton disimpan; {fmt_num(len(raw) - len(clean))} baris tanpa dimensi dilewati.")
        plan_file = st.file_uploader("Lampiran denah (gambar/PDF, hanya ditampilkan)", type=["png", "jpg", "jpeg", "pdf"], key="plan-upload", disabled=not may_upload)
        if plan_file is not None and may_upload:
            folder = Path(user_root) / "denah"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / plan_file.name).write_bytes(plan_file.getvalue())
            st.success("Denah disimpan.")
    folder = Path(user_root) / "denah"
    plans = sorted(folder.glob("*")) if folder.exists() else []
    images = [p for p in plans if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
    if images:
        st.image(str(images[-1]), caption=f"Denah: {images[-1].name}", use_container_width=True)
    racks = features.read("warehouse_rack")
    if racks.empty:
        st.info("Layout gudang belum diunggah.")
        return
    latest = racks.loc[racks["layout_version"] == racks["layout_version"].max()]
    capacity = warehouse.zone_capacity(latest)
    zones = list(capacity.index)
    volumes = warehouse.unit_volume(features.read("carton_dimension"))
    used, missing = warehouse.zone_usage(table, volumes, zones)
    rows = []
    for zone, cap in capacity.items():
        pct = float(used.get(zone, 0.0)) / cap * 100 if cap > 0 else np.nan
        rows.append({"Zona": zone, "Kapasitas (m³)": cap, "Terpakai (m³)": float(used.get(zone, 0.0)), "Sisa (m³)": cap - float(used.get(zone, 0.0)), "Terpakai (%)": pct})
    zone_frame = pd.DataFrame(rows)
    cols = st.columns(min(len(zone_frame), 4) or 1)
    for index, row in zone_frame.iterrows():
        color = warehouse.capacity_color(row["Terpakai (%)"])
        cols[index % len(cols)].markdown(
            f"<div class='stat-card' style='border-left:6px solid {color}'><div class='readable-metric-label'>{html.escape(row['Zona'])}</div>"
            f"<div class='readable-metric-value' style='color:{color}'>{fmt_pct(row['Terpakai (%)'], 1)}</div>"
            f"<div class='metric-hint'>{fmt_num(row['Terpakai (m³)'], 1)} / {fmt_num(row['Kapasitas (m³)'], 1)} m³</div></div>",
            unsafe_allow_html=True,
        )
    st.caption("Hijau < 75%, oranye 75–90%, merah > 90%. Terpakai = Σ stok DC × volume unit (dimensi karton ÷ isi per karton).")
    projection = warehouse.weekly_projection(table, volumes, capacity, zones, data.import_po, today)
    if not projection.empty:
        fig = go.Figure()
        for zone, part in projection.groupby("zona"):
            fig.add_scatter(x=part["minggu"], y=part["pct"], mode="lines+markers", name=str(zone))
        fig.add_hline(y=100, line_dash="dot", line_color="#dc2626")
        fig.update_layout(height=320, yaxis_title="% kapasitas", margin=dict(l=30, r=20, t=20, b=30), legend=dict(orientation="h", y=-0.25), xaxis=dict(tickformat="%d/%m"))
        st.plotly_chart(fig, use_container_width=True, key="cap-projection")
        full = warehouse.first_full(projection)
        st.markdown(f"**Zona pertama penuh:** {html.escape(full[0])} pada {fmt_date(full[1])}" if full else "**Zona pertama penuh:** tidak ada dalam 12 minggu proyeksi.")
    if not data.import_po.empty and volumes:
        inbound = data.import_po.loc[data.import_po["status"].astype(str) != "Diterima DC"].copy()
        if not inbound.empty:
            names = table.drop_duplicates("sku").set_index(table["sku"].astype(str).drop_duplicates())["product_name"].to_dict() if not table.empty else {}
            inbound["m3"] = inbound["sku"].astype(str).map(volumes).fillna(0) * pd.to_numeric(inbound["qty"], errors="coerce").fillna(0)
            inbound["zona"] = [warehouse.zone_for(names.get(str(s), ""), zones) for s in inbound["sku"]]
            spare = zone_frame.set_index("Zona")["Sisa (m³)"]
            best = spare.idxmax() if not spare.empty else "-"
            inbound["Sisa zona"] = inbound["zona"].map(spare)
            inbound["Rekomendasi"] = np.where(inbound["m3"] > inbound["Sisa zona"].fillna(0), f"Pindah ke {best}", "Muat")
            st.markdown("**Rencana inbound vs ruang**")
            show_table(inbound[["no_po", "sku", "qty", "eta_terbaru", "zona", "m3", "Sisa zona", "Rekomendasi"]].rename(columns={"no_po": "No PO", "sku": "SKU", "qty": "QTY", "eta_terbaru": "ETA terbaru", "zona": "Zona", "m3": "Volume (m³)"}))
    if not missing.empty:
        with st.expander(f"Data belum lengkap · {fmt_num(len(missing))} SKU tanpa dimensi karton"):
            show_table(missing.rename(columns={"sku": "SKU"}))


# ---------------------------------------------------------------- Kedatangan impor


def _import_tab(features, table: pd.DataFrame, role: str, username: str, today: date) -> None:
    st.markdown("**Kedatangan impor**")
    may_write = allowed(role, "setting_kedatangan_impor", "write_note")
    known = set(table["sku"].astype(str)) if not table.empty else set()
    if may_write:
        with st.expander("+ Catatan baru", expanded=False):
            with st.form("imp-note", clear_on_submit=True):
                f1, f2, f3, f4 = st.columns(4)
                no_po = f1.text_input("No PO")
                tanggal = f2.date_input("Tanggal catatan", value=today, format="DD/MM/YYYY")
                sku = f3.text_input("SKU")
                qty = f4.number_input("QTY", min_value=0, step=1)
                g1, g2, g3, g4 = st.columns(4)
                eta_plan = g1.date_input("ETA rencana", value=None, format="DD/MM/YYYY")
                eta_new = g2.date_input("ETA terbaru", value=None, format="DD/MM/YYYY")
                status = g3.selectbox("Status", IMPORT_STATUSES)
                kondisi = g4.text_input("Kondisi barang")
                catatan = st.text_area("Catatan", height=70)
                if st.form_submit_button("Simpan catatan", type="primary"):
                    _require("setting_kedatangan_impor", "write_note")
                    frame = pd.DataFrame([{"no_po": no_po, "tanggal_catatan": tanggal.isoformat(), "sku": sku, "varian": "", "qty": qty, "eta_rencana": eta_plan.isoformat() if eta_plan else "", "eta_terbaru": eta_new.isoformat() if eta_new else "", "status": status, "kondisi_barang": kondisi, "catatan": catatan}])
                    _save_import(features, frame, known, username)
        u1, u2 = st.columns([3, 1])
        upload = u1.file_uploader("Unggah template catatan impor", type=["xlsx", "csv"], key="imp-upload")
        with u2:
            download_excel(pd.DataFrame(columns=list(warehouse.IMPORT_COLUMNS)), "template_kedatangan_impor.xlsx", key="xl-imp-tpl", label="Unduh template")
        if upload is not None and st.button("Simpan file catatan", key="imp-save", type="primary"):
            _require("setting_kedatangan_impor", "write_note")
            _save_import(features, _read_upload(upload), known, username)
        st.caption("Status baku: " + ", ".join(IMPORT_STATUSES) + ". Author diisi otomatis dari user login.")
    else:
        st.caption("Role Anda hanya melihat. Catatan ditulis oleh Team IC/MD atau Super user.")
    po = features.read("import_po")
    notes = features.read("import_note")
    if po.empty:
        st.info("Belum ada PO impor.")
        return
    names = table.drop_duplicates("sku").set_index(table["sku"].astype(str).drop_duplicates())["product_name"].to_dict() if not table.empty else {}
    view = po.assign(Produk=po["sku"].astype(str).map(names).fillna(""))
    for column in ("eta_rencana", "eta_terbaru"):
        view[column] = view[column].map(fmt_date_short)
    show_table(view[["no_po", "sku", "Produk", "varian", "qty", "eta_rencana", "eta_terbaru", "status"]].rename(columns={"no_po": "No PO", "sku": "SKU", "varian": "Varian", "qty": "QTY", "eta_rencana": "ETA rencana", "eta_terbaru": "ETA terbaru", "status": "Status"}))
    impact = warehouse.delay_impact(po, table, today) if not table.empty else pd.DataFrame()
    if not impact.empty:
        st.markdown("**Dampak keterlambatan** · hari kosong = max(0, ETA terbaru − tanggal stok habis); potensi sales hilang = hari kosong × prediksi sales harian")
        late = impact.loc[impact["hari_kosong"] > 0]
        cols = st.columns(2)
        card(cols[0], "PO berisiko kosong", fmt_num(len(late)))
        card(cols[1], "Potensi sales hilang", fmt_idr(late["potensi_sales_hilang"].sum()))
        view = impact.copy()
        view["eta_terbaru"] = view["eta_terbaru"].map(fmt_date_short)
        view["stok_habis"] = view["stok_habis"].map(fmt_date_short)
        show_table(view.rename(columns={"no_po": "No PO", "sku": "SKU", "eta_terbaru": "ETA terbaru", "stok_habis": "Stok habis", "hari_kosong": "Hari kosong", "potensi_sales_hilang": "Potensi sales hilang"}))
    stats = warehouse.lead_time_stats(notes)
    st.caption(
        f"Lead time impor aktual (Diterima DC − tanggal PO): rata-rata {fmt_num(stats[0], 1)} hari, maks. {fmt_num(stats[1])} hari. Dipakai SS impor = (L_maks − L_rata) × permintaan harian."
        if stats
        else "Lead time impor aktual belum tersedia (belum ada PO berstatus Diterima DC)."
    )
    if not notes.empty:
        with st.expander(f"Riwayat catatan · {fmt_num(len(notes))}"):
            hist = notes.sort_values("created_at", ascending=False).copy()
            hist["tanggal_catatan"] = hist["tanggal_catatan"].map(fmt_date_short)
            show_table(hist[["no_po", "tanggal_catatan", "status", "kondisi_barang", "catatan", "author"]].rename(columns={"no_po": "No PO", "tanggal_catatan": "Tanggal", "status": "Status", "kondisi_barang": "Kondisi", "catatan": "Catatan", "author": "Oleh"}))


def _save_import(features, frame: pd.DataFrame, known: set[str], username: str) -> None:
    good, bad = warehouse.validate_import_rows(frame, known, username)
    if not bad.empty:
        st.error(f"{fmt_num(len(bad))} baris gagal:")
        show_table(bad.rename(columns={"baris": "Baris", "no_po": "No PO", "alasan": "Alasan"}))
    if good.empty:
        return
    now = datetime.now()
    features.insert("import_note", good.assign(created_at=now), username=username, action="tulis:catatan_impor")
    features.replace("import_po", good[["no_po", "sku", "varian", "qty", "eta_rencana", "eta_terbaru", "status"]], keys=["no_po", "sku"], username=username, action="simpan:po_impor")
    bump(st.session_state)
    st.success(f"{fmt_num(len(good))} catatan impor disimpan.")
