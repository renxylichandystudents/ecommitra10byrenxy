"""Halaman Setting (Revisi Final 4F–4H): SKU dikecualikan, Kalkulator biaya, Laporan margin,
Kapasitas gudang, Kedatangan impor, Kelola user. Ubah data latih TIDAK ada di sini."""

from __future__ import annotations

import html
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src.core import margin as margin_core
from src.core import warehouse
from src.core.access import allowed, setting_tabs
from src.core.feature_store import IMPORT_STATUSES
from src.core.fmt import fmt_date_short
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
        _excluded_tab(features, table, username, orders)
    elif picked == "kalkulator-biaya":
        _calculator_tab(features, table, data, username, today, user_root=user_root)
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


def _sku_catalog(table: pd.DataFrame, orders: pd.DataFrame | None) -> dict[str, str]:
    """SKU → nama produk dari hasil analisa + transaksi (termasuk SKU jasa yang tidak masuk rank)."""
    names: dict[str, str] = {}
    for frame in (orders, table):
        if isinstance(frame, pd.DataFrame) and not frame.empty and {"sku", "product_name"} <= set(frame.columns):
            part = frame[["sku", "product_name"]].dropna()
            part = part.assign(sku=part["sku"].astype(str).str.strip().str.replace(r"\.0+$", "", regex=True))
            for sku, name in zip(part["sku"], part["product_name"].astype(str)):
                if sku and sku.lower() not in {"nan", "none"}:
                    names[sku] = name
    return names


def _exc_row(cols, sku: str, name: str, note: str, *, bold: bool = False) -> None:
    sku_text = html.escape(sku) if sku else "<span style='color:#94a3b8'>tanpa SKU</span>"
    cols[0].markdown(f"<div style='font-weight:{700 if bold else 500}'>{sku_text}</div>", unsafe_allow_html=True)
    cols[1].markdown(f"<div style='line-height:1.35'>{html.escape(name or '-')}</div>", unsafe_allow_html=True)
    cols[2].markdown(f"<div class='field-hint'>{html.escape(note)}</div>", unsafe_allow_html=True)


def _exc_header(labels: list[str], widths: list[float]) -> None:
    cols = st.columns(widths, vertical_alignment="center")
    for col, text in zip(cols, labels):
        col.markdown(f"<div style='font-size:.8rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.02em'>{text}</div>", unsafe_allow_html=True)


def _add_excluded(features, username: str, rows: list[dict]) -> None:
    _require("setting_sku_dikecualikan", "edit")
    stamp = datetime.now()
    payload = [{"sku": r["sku"], "nama": r["nama"], "jenis": r["jenis"], "added_by": username, "added_at": stamp} for r in rows]
    features.replace("excluded_sku", payload, keys=["sku"], username=username, action="tambah:sku_dikecualikan")
    bump(st.session_state)


def _excluded_tab(features, table: pd.DataFrame, username: str, orders: pd.DataFrame | None = None) -> None:
    widths = [1.1, 3.4, 1.6, 0.9]
    st.markdown("**SKU dikecualikan**")
    st.caption("SKU di sini keluar dari rank, safety stock, iklan, flash sale, dan exposure (filter di awal pipeline). Di tabel alokasi iklan tampil sebagai \"SKU jasa\".")
    frame = features.read("excluded_sku")
    catalog = _sku_catalog(table, orders)
    excluded = set(frame["sku"].astype(str)) if not frame.empty else set()

    # 1) Tambah: cari SKU — saat diketik muncul "SKU · nama produk" agar jelas SKU mana yang dipilih.
    with st.container(border=True):
        st.markdown("**Tambah SKU**")
        options = [f"{sku} · {name}" for sku, name in sorted(catalog.items()) if sku not in excluded]
        lookup = {label: label.split(" · ", 1)[0] for label in options}
        a1, a2, a3 = st.columns([3, 2, 0.9], vertical_alignment="bottom")
        picked = a1.selectbox(
            "Cari SKU atau nama produk",
            options=options,
            index=None,
            placeholder="Ketik SKU atau nama produk…",
            accept_new_options=True,
            key="exc-search",
        )
        reason = a2.text_input("Alasan (opsional)", key="exc-reason", placeholder="mis. SKU jasa / biaya tambahan")
        sku = ""
        if picked:
            sku = lookup.get(picked, str(picked).split(" · ", 1)[0].strip())
        name = catalog.get(sku, "")
        if a3.button("Tambah", type="primary", use_container_width=True, disabled=not sku, key="exc-add"):
            if sku in excluded:
                st.warning(f"SKU {sku} sudah ada di daftar.")
            else:
                _add_excluded(features, username, [{"sku": sku, "nama": (reason.strip() or name), "jenis": "Manual"}])
                for k in ("exc-search", "exc-reason"):
                    st.session_state.pop(k, None)
                st.rerun()
        if picked:
            if name:
                st.markdown(f"<div class='field-hint'>Akan dikecualikan: <b>{html.escape(sku)}</b> — {html.escape(name)}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div class='field-hint' style='color:#b45309'>SKU <b>{html.escape(sku)}</b> tidak ditemukan di data penjualan. Periksa kembali sebelum menambah.</div>", unsafe_allow_html=True)

    # 2) Daftar SKU yang sudah dikecualikan.
    st.markdown(f"**Daftar SKU dikecualikan** · {fmt_num(len(frame))} SKU")
    if frame.empty:
        st.info("Belum ada SKU yang dikecualikan.")
    else:
        with st.container(border=True):
            _exc_header(["SKU", "Nama produk", "Jenis · oleh", ""], widths)
            for _, row in frame.sort_values("sku").iterrows():
                sku_row = str(row["sku"])
                display = catalog.get(sku_row) or str(row["nama"] or "-")
                added = row.get("added_at")
                when = f" · {fmt_date_short(pd.Timestamp(added).date())}" if pd.notna(added) else ""
                cols = st.columns(widths, vertical_alignment="center")
                _exc_row(cols, sku_row, display, f"{row['jenis'] or '-'} · {row['added_by']}{when}", bold=True)
                if cols[3].button("Hapus", key=f"exc-del-{sku_row}", use_container_width=True):

                    def _delete(sku: str = sku_row) -> None:
                        _require("setting_sku_dikecualikan", "edit")
                        features.remove("excluded_sku", {"sku": sku}, username=username, action="hapus:sku_dikecualikan")
                        bump(st.session_state)

                    confirm_action("Hapus dari SKU dikecualikan?", f"SKU {html.escape(sku_row)} akan kembali masuk rank dan rekomendasi.", _delete, confirm_label="Ya, hapus")

    # 3) Usulan sistem (hanya yang punya SKU; produk tanpa SKU tidak bisa dikecualikan).
    products = pd.DataFrame({"sku": list(catalog), "product_name": list(catalog.values())})
    suggestions = exclusion_suggestions(products, excluded)
    suggestions = suggestions.loc[suggestions["sku"].astype(str).str.strip().ne("")].drop_duplicates("sku")
    if not suggestions.empty:
        head, bulk = st.columns([3, 1], vertical_alignment="center")
        head.markdown(f"**Usulan sistem** · {fmt_num(len(suggestions))} SKU")
        head.markdown("<div class='field-hint'>Nama berisi packing, bubble wrap, biaya, atau ongkir. Tekan Kecualikan untuk mengonfirmasi.</div>", unsafe_allow_html=True)
        if bulk.button(f"Kecualikan semua ({len(suggestions)})", key="exc-sug-all", use_container_width=True):
            _add_excluded(features, username, [{"sku": str(r["sku"]), "nama": str(r["nama"]), "jenis": "SKU jasa"} for _, r in suggestions.iterrows()])
            st.rerun()
        with st.container(border=True):
            _exc_header(["SKU", "Nama produk", "Alasan", ""], widths)
            for _, row in suggestions.iterrows():
                cols = st.columns(widths, vertical_alignment="center")
                _exc_row(cols, str(row["sku"]), str(row["nama"]), str(row["alasan"]))
                if cols[3].button("Kecualikan", key=f"exc-sug-{row['sku']}", use_container_width=True):
                    _add_excluded(features, username, [{"sku": str(row["sku"]), "nama": str(row["nama"]), "jenis": "SKU jasa"}])
                    st.rerun()


# ---------------------------------------------------------------- Kalkulator biaya


def _calculator_tab(features, table: pd.DataFrame, data: FeatureData, username: str, today: date, *, user_root: Path | None = None) -> None:
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
    from src.core.config import load_params

    margin_min = float(load_params(user_root).get("margin", {}).get("margin_min_pct", 8) or 8)
    cols = st.columns(3)
    if hpp <= 0:
        # Tanpa HPP, "margin" hanya harga dikurangi biaya platform: menyesatkan bila ditampilkan sebagai margin.
        card(cols[0], "Margin per unit", "HPP belum diisi", hint="Isi HPP untuk menghitung margin")
        card(cols[1], f"Harga minimal margin {fmt_num(margin_min, 0)}%", "–", hint="Butuh HPP")
        card(cols[2], "Harga minimal margin 0%", "–", hint="Butuh HPP")
    else:
        card(cols[0], "Margin per unit", fmt_idr(value), hint=fmt_pct(pct, 1))
        card(cols[1], f"Harga minimal margin {fmt_num(margin_min, 0)}%", fmt_idr(margin_core.harga_minimal(sim, iklan, margin_min)), hint="Margin minimum dari Pengaturan bisnis")
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
        st.info(
            "Komponen biaya belum diunggah. Langkah: buka Setting › Kalkulator biaya → Unduh template → isi HPP, komisi, "
            "biaya layanan, packing, dan ongkir per SKU → unggah. Laporan margin muncul otomatis setelahnya."
        )
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
    """Gudang Site 10037: denah bawaan + replenishment harian + stok 10037 (lihat src/ui/gudang_view.py)."""
    from src.ui.gudang_view import show_capacity

    show_capacity(features, table, may_upload=allowed(role, "setting_kapasitas_gudang", "upload"), username=username, require=_require)


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
