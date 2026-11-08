"""Setting › Kalkulator biaya: margin bersih per unit untuk Shopee Mall + analisa agar tetap profit."""

from __future__ import annotations

import html
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from src.core import shopee_fee as fee
from src.core.promo import product_label
from src.ui.common import card, download_excel, fmt_idr, fmt_num, fmt_pct
from src.utils.format import input_rupiah, show_table

KEY_PROGRAMS = "shopee_mall_program"
KEY_CATEGORY = "shopee_mall_category_fee"
KEY_AFFILIATE = "shopee_affiliate_commission"
KEY_SKU_CAT = "shopee_sku_category"
TONE = {"ok": ("#ecfdf5", "#047857", "✅"), "warn": ("#fffbeb", "#b45309", "⚠️"), "bad": ("#fef2f2", "#b91c1c", "⛔"), "info": ("#f8fafc", "#334155", "•")}


def _programs(features) -> tuple[dict, float, float]:
    """(program, biaya proses pesanan, batas total potongan %) dari pengaturan tersimpan."""
    saved = features.get_json(KEY_PROGRAMS, None) if features is not None else None
    programs = {k: dict(v) for k, v in fee.DEFAULT_PROGRAMS.items()}
    order_fee, limit = fee.DEFAULT_ORDER_FEE, fee.DEFAULT_COST_LIMIT
    if isinstance(saved, dict):
        for key, value in (saved.get("programs") or {}).items():
            if key in programs:
                programs[key].update({k: value[k] for k in ("pct", "cap", "on", "pct_khusus", "cap_khusus") if k in value})
        order_fee = float(saved.get("order_fee", order_fee))
        limit = float(saved.get("limit", limit))
    return programs, order_fee, limit


def _category_fees(features) -> pd.DataFrame:
    saved = features.get_json(KEY_CATEGORY, None) if features is not None else None
    return fee.load_category_fees(pd.DataFrame(saved) if saved else None)


def _affiliate(features) -> pd.DataFrame:
    saved = features.get_json(KEY_AFFILIATE, None) if features is not None else None
    return pd.DataFrame(saved) if saved else pd.DataFrame(columns=["product_code", "nama", "komisi_pct"])


def _read_any(upload) -> pd.DataFrame:
    name = str(getattr(upload, "name", "")).lower()
    if name.endswith(".csv"):
        return pd.read_csv(upload, header=None, dtype=object)
    return pd.read_excel(upload, header=None, dtype=object)


def _parameter_panel(features, *, may_edit: bool, username: str, require) -> None:
    with st.expander("⚙️ Parameter biaya Shopee Mall, biaya kategori, dan komisi affiliate", expanded=False):
        t1, t2, t3 = st.tabs(["Biaya program Shopee Mall", "Biaya administrasi kategori", "Komisi affiliate"])
        with t1:
            programs, order_fee, limit = _programs(features)
            st.markdown(
                "<div class='field-hint'>Program yang terdaftar di Seller Centre › Program Saya. Tarif dalam % dari harga jual akhir; "
                "Maks = batas Rp per kuantitas (0 = tanpa batas). <b>Ikut</b> = dihitung secara bawaan. Program dengan rentang tarif memakai "
                "batas atas agar perhitungan aman; ubah bila tarif kategori Anda lebih rendah.</div>",
                unsafe_allow_html=True,
            )
            rows = []
            for k, v in programs.items():
                rows.append({"Kode": k, "Biaya": v["label"], "Tarif (%)": float(v["pct"]), "Maks per kuantitas (Rp)": float(v.get("cap") or 0),
                             "Ikut": bool(v.get("on")), "Keterangan": v.get("rentang", "wajib" if v.get("wajib") else "")})
                if k == "gratis_ongkir":
                    rows.append({"Kode": "gratis_ongkir_khusus", "Biaya": "Gratis Ongkir XTRA (ukuran khusus)", "Tarif (%)": float(v.get("pct_khusus", 9.5)),
                                 "Maks per kuantitas (Rp)": float(v.get("cap_khusus", 60_000)), "Ikut": bool(v.get("on")), "Keterangan": "dipakai untuk barang besar"})
            edited = st.data_editor(
                pd.DataFrame(rows), hide_index=True, use_container_width=True, disabled=["Kode", "Biaya", "Keterangan"] if may_edit else True,
                column_config={"Kode": None, "Tarif (%)": st.column_config.NumberColumn(format="%.2f", min_value=0.0, max_value=50.0, step=0.05),
                               "Maks per kuantitas (Rp)": st.column_config.NumberColumn(format="%d", min_value=0, step=1000),
                               "Keterangan": st.column_config.TextColumn(width="large")},
                key="fee-programs-editor",
            )
            p1, p2 = st.columns(2)
            order = p1.number_input("Biaya Proses Pesanan (Rp per pesanan selesai)", 0.0, 50_000.0, float(order_fee), 50.0, key="fee-order", disabled=not may_edit)
            new_limit = p2.number_input(
                "Batas total potongan (%)", 5.0, 80.0, float(limit), 1.0, key="fee-limit", disabled=not may_edit,
                help="Total potongan Shopee + iklan (+ affiliate) di atas batas ini dianggap menggerus margin. Sesuaikan dengan margin kotor rata-rata produk.",
            )
            if may_edit and st.button("Simpan parameter", type="primary", key="fee-programs-save"):
                require("setting_kalkulator_biaya", "edit")
                payload_programs = {}
                for r in edited.to_dict("records"):
                    if r["Kode"] == "gratis_ongkir_khusus":
                        payload_programs.setdefault("gratis_ongkir", {}).update({"pct_khusus": float(r["Tarif (%)"]), "cap_khusus": float(r["Maks per kuantitas (Rp)"])})
                    else:
                        payload_programs.setdefault(r["Kode"], {}).update({"pct": float(r["Tarif (%)"]), "cap": float(r["Maks per kuantitas (Rp)"]), "on": bool(r["Ikut"])})
                features.set_json(KEY_PROGRAMS, {"programs": payload_programs, "order_fee": float(order), "limit": float(new_limit)}, username=username)
                st.session_state.pop("_calc-portfolio", None)
                st.toast("Parameter biaya tersimpan.")
                st.rerun()
        with t2:
            fees = _category_fees(features)
            st.markdown(
                f"<div class='field-hint'>{fmt_num(len(fees))} baris tarif biaya administrasi Shopee Mall per kategori. Baris dengan catatan perlu dicek ulang di Seller Centre. "
                "Untuk memperbarui, unduh tabel ini, ubah di Excel, lalu unggah kembali.</div>",
                unsafe_allow_html=True,
            )
            show_table(fees[["kategori", "sub_kategori", "jenis_produk", "biaya_admin_pct", "catatan"]].rename(columns={
                "kategori": "Kategori", "sub_kategori": "Sub kategori", "jenis_produk": "Jenis produk", "biaya_admin_pct": "Biaya admin (%)", "catatan": "Catatan"}),
                max_height=320, kinds={"Biaya admin (%)": "dec"})
            download_excel(fees[["kategori", "sub_kategori", "jenis_produk", "biaya_admin_pct", "catatan"]], "biaya_kategori_shopee_mall.xlsx", key="xl-fee-cat", label="Unduh tabel kategori")
            if may_edit:
                upload = st.file_uploader("Unggah tabel kategori (Excel/CSV: kategori, sub_kategori, jenis_produk, biaya_admin_pct)", type=["xlsx", "csv"], key="fee-cat-upload")
                if upload is not None:
                    try:
                        raw = pd.read_csv(upload, dtype=str) if upload.name.lower().endswith(".csv") else pd.read_excel(upload, dtype=str)
                        parsed = fee.parse_category_upload(raw)
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"File tidak bisa dibaca: {exc}")
                    else:
                        st.markdown(f"Terbaca **{fmt_num(len(parsed))} baris**.")
                        if st.button("Simpan tabel kategori", type="primary", key="fee-cat-save"):
                            require("setting_kalkulator_biaya", "edit")
                            features.set_json(KEY_CATEGORY, parsed[["kategori", "sub_kategori", "jenis_produk", "biaya_admin_pct", "catatan"]].to_dict("records"), username=username)
                            st.toast("Tabel kategori tersimpan.")
                            st.rerun()
        with t3:
            aff = _affiliate(features)
            codes = st.session_state.get("_sku_product_code") or {}
            mapped = sum(1 for c in aff.get("product_code", []) if c in set(codes.values())) if not aff.empty else 0
            st.markdown(
                f"<div class='field-hint'>File komisi affiliate dari Shopee (Produk ID, Nama Produk, Persentase Komisi). "
                f"Tersimpan: <b>{fmt_num(len(aff))} produk</b> · {fmt_num(mapped)} cocok dengan SKU di data stok.</div>",
                unsafe_allow_html=True,
            )
            if not aff.empty:
                show_table(aff.rename(columns={"product_code": "Produk ID", "nama": "Nama produk", "komisi_pct": "Komisi (%)"}), max_height=260, kinds={"Komisi (%)": "dec"})
            if may_edit:
                upload = st.file_uploader("Unggah file komisi affiliate (xlsx)", type=["xlsx", "csv"], key="fee-aff-upload")
                if upload is not None:
                    try:
                        parsed = fee.parse_affiliate(_read_any(upload))
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"File tidak bisa dibaca: {exc}")
                    else:
                        st.markdown(f"Terbaca **{fmt_num(len(parsed))} produk** (komisi {fmt_num(parsed['komisi_pct'].min(), 1)}–{fmt_num(parsed['komisi_pct'].max(), 1)}%).")
                        if st.button("Simpan komisi affiliate", type="primary", key="fee-aff-save"):
                            require("setting_kalkulator_biaya", "edit")
                            features.set_json(KEY_AFFILIATE, parsed.to_dict("records"), username=username)
                            st.toast("Komisi affiliate tersimpan.")
                            st.rerun()


def _prediction_30(table: pd.DataFrame, features, sku: str) -> float | None:
    if isinstance(table, pd.DataFrame) and "pred_harian" in table.columns and not table.empty:
        part = table.loc[table["sku"].astype(str) == sku, "pred_harian"]
        if not part.empty:
            return float(pd.to_numeric(part, errors="coerce").fillna(0).sum()) * 30
    try:
        from src.core.gudang import norm_sku
        from src.ui.gudang_view import latest_prediction

        qty, _sales, _at = latest_prediction(features)
        return float(qty.get(norm_sku(sku), 0.0)) * 30 if qty else None
    except Exception:
        return None


def _is_big(name: str) -> bool:
    return "packing kayu" in str(name).lower()


def _portfolio_rows(features, table: pd.DataFrame, data, orders: pd.DataFrame | None, fees: pd.DataFrame) -> pd.DataFrame:
    """Satu baris per SKU yang laku 30 hari terakhir: harga akhir rata-rata transaksi, voucher penjual, kategori, iklan, affiliate."""
    from src.core.gudang import norm_sku
    from src.ui.feature_data import product_frame

    products = product_frame(table).drop_duplicates("sku")
    if orders is None or orders.empty or products.empty:
        return pd.DataFrame()
    work = orders
    if "status" in work.columns:
        from src.ingest import cancelled_status_mask

        work = work.loc[~cancelled_status_mask(work["status"])]
    stamp = pd.to_datetime(work["order_time"], errors="coerce")
    work = work.loc[stamp >= stamp.max().normalize() - pd.Timedelta(days=29)]
    grouped = work.assign(sku=work["sku"].astype(str)).groupby("sku").agg(
        qty=("qty", "sum"), omzet=("sales", "sum"),
        voucher=("seller_voucher", "sum") if "seller_voucher" in work.columns else ("qty", lambda s: 0.0),
    )
    grouped = grouped.loc[grouped["qty"] > 0]
    names = dict(zip(products["sku"], products["product_name"]))
    prices = dict(zip(products["sku"], products["price"]))
    sku_cat = features.get_json(KEY_SKU_CAT, {}) or {}
    aff = _affiliate(features)
    aff_by_code = dict(zip(aff.get("product_code", []), aff.get("komisi_pct", []))) if not aff.empty else {}
    codes = st.session_state.get("_sku_product_code") or {}
    roas_map = {}
    if isinstance(table, pd.DataFrame) and {"biaya_iklan", "omzet_iklan"} <= set(table.columns):
        ads = table.assign(sku=table["sku"].astype(str)).groupby("sku")[["biaya_iklan", "omzet_iklan"]].sum()
        roas_map = {k: (r.omzet_iklan / r.biaya_iklan if r.biaya_iklan > 0 else np.nan) for k, r in ads.iterrows()}
    cache = st.session_state.setdefault("_calc-suggest", {})
    rows = []
    for sku, r in grouped.iterrows():
        name = names.get(sku) or names.get(norm_sku(sku), sku)
        saved = sku_cat.get(sku)
        idx = None
        if saved:
            hit = fees.index[(fees["kategori"] == saved.get("kategori")) & (fees["jenis_produk"] == saved.get("jenis_produk"))]
            idx = int(hit[0]) if len(hit) else None
        if idx is None:
            if sku not in cache:
                cache[sku] = fee.suggest_category(name, fees)
            idx = cache[sku]
        admin = float(fees.loc[idx, "biaya_admin_pct"]) if idx is not None and pd.notna(fees.loc[idx, "biaya_admin_pct"]) else fee.DEFAULT_ADMIN_PCT
        harga = float(r["omzet"]) / float(r["qty"]) if r["qty"] else float(prices.get(sku, 0))
        rows.append({
            "sku": sku, "nama": name, "kategori": (fees.loc[idx, "sub_kategori"] if idx is not None else "Lainnya") + f" ({fmt_num(admin, 2)}%)",
            "harga": harga, "diskon_unit": 0.0, "voucher_unit": float(r["voucher"]) / float(r["qty"]) if r["qty"] else 0.0,
            "admin_pct": admin, "affiliate_pct": float(aff_by_code.get(codes.get(sku, ""), 0.0) or 0.0),
            "iklan_unit": float(data.ad_per_unit.get(sku, 0.0) or 0.0), "roas": roas_map.get(sku, np.nan),
            "qty_30": float(r["qty"]), "omzet_30": float(r["omzet"]), "ukuran_khusus": _is_big(name),
        })
    return pd.DataFrame(rows)


def _priority_table(port: pd.DataFrame, limit: float) -> None:
    from src.ui.common import batched_view, explain

    st.markdown("<div class='section-title'>Prioritas perbaikan margin · 30 hari terakhir</div>", unsafe_allow_html=True)
    if port.empty:
        st.info("Belum ada SKU terjual 30 hari terakhir (data transaksi belum termuat).")
        return
    counts = port["status"].value_counts()
    leak = float(port["bocor_30"].sum())
    k = st.columns(4)
    card(k[0], "SKU melebihi batas", fmt_num(int(counts.get("Melebihi batas", 0))), hint=f"total potongan > {fmt_num(limit, 0)}% harga akhir")
    card(k[1], "Omzet terdampak", fmt_idr(float(port.loc[port["status"] == "Melebihi batas", "omzet_30"].sum())), hint="omzet 30 hari SKU yang melebihi batas")
    card(k[2], "Kebocoran di atas batas", fmt_idr(leak), hint="omzet × kelebihan potongan; yang bisa diselamatkan bila diperbaiki")
    card(k[3], "Penerimaan bersih 30 hari", fmt_idr(float(port["bersih_30"].sum())), hint="harga akhir − potongan Shopee − iklan, sebelum HPP")
    explain([
        ("Urutan prioritas", "🔴 Melebihi batas dulu, diurutkan dari kebocoran Rp terbesar (omzet × kelebihan potongan), lalu 🟠 Mendekati batas dan 🟢 Aman menurut omzet"),
        ("Total potongan", "biaya administrasi kategori + program Shopee Mall + biaya proses pesanan + iklan per unit, dalam % harga akhir (harga transaksi rata-rata setelah diskon & voucher penjual)"),
        ("Yang perlu dibenerin", "langkah dari tuas terbesar yang bisa dikendalikan: iklan (ROAS minimal), komisi affiliate, program opsional, diskon/voucher"),
        ("Tanpa HPP", "angka adalah penerimaan bersih sebelum HPP; batas potongan menggantikan target margin"),
    ])
    f1, f2 = st.columns([1.2, 1.8])
    status_pick = f1.multiselect("Status", ["Melebihi batas", "Mendekati batas", "Aman"], key="calc-port-status", placeholder="Semua status")
    query = f2.selectbox("Cari SKU", [f"{s} · {n}" for s, n in zip(port["sku"], port["nama"])], index=None, key="calc-port-q", placeholder="Ketik SKU atau nama produk…")
    view = port
    if status_pick:
        view = view.loc[view["status"].isin(status_pick)]
    if query:
        view = view.loc[view["sku"] == str(query).split(" · ")[0]]
    icon = {"Melebihi batas": "🔴 Melebihi batas", "Mendekati batas": "🟠 Mendekati batas", "Aman": "🟢 Aman"}
    frame = pd.DataFrame({
        "Prioritas": range(1, len(view) + 1), "Status": view["status"].map(icon), "SKU": view["sku"], "Nama": view["nama"],
        "Yang perlu dibenerin": view["perbaikan"], "Omzet 30 hari": view["omzet_30"], "Terjual 30 hari": view["qty_30"],
        "Total potongan": view["total_pct"], "Kebocoran 30 hari": view["bocor_30"], "Penerimaan bersih/unit": view["bersih_unit"],
        "Harga akhir": view["harga_akhir"], "Potongan Shopee": view["shopee_pct"], "Iklan/unit": view["iklan_unit"],
        "ROAS": view["roas"], "Komisi affiliate": view["affiliate_pct"], "Kategori Shopee": view["kategori"],
    }).reset_index(drop=True)
    total = {c: np.nan for c in frame.columns}
    total.update({"Prioritas": np.nan, "Status": "Total", "SKU": f"{fmt_num(len(frame))} SKU", "Nama": "", "Yang perlu dibenerin": "",
                  "Kategori Shopee": "", "Omzet 30 hari": frame["Omzet 30 hari"].sum(), "Terjual 30 hari": frame["Terjual 30 hari"].sum(),
                  "Kebocoran 30 hari": frame["Kebocoran 30 hari"].sum()})
    full = pd.concat([pd.DataFrame([total]), frame], ignore_index=True)
    kinds = {"Omzet 30 hari": "money", "Kebocoran 30 hari": "money", "Penerimaan bersih/unit": "money", "Harga akhir": "money", "Iklan/unit": "money",
             "Total potongan": "pct", "Potongan Shopee": "pct", "Komisi affiliate": "pct", "ROAS": "dec", "Terjual 30 hari": "count", "Prioritas": "count"}
    batched_view(
        len(frame), key="calc-port", noun="SKU",
        render=lambda lo, hi: show_table(
            pd.concat([full.iloc[:1], full.iloc[1:].iloc[lo:hi]], ignore_index=True), bold_label="Total", kinds=kinds, max_height=10_000,
            column_config={"Yang perlu dibenerin": st.column_config.TextColumn(width="large")},
        ),
        download=lambda: download_excel(full, "prioritas_perbaikan_margin.xlsx", key="xl-calc-port"),
    )


def show_calculator(features, table: pd.DataFrame, data, *, username: str, today: date, user_root: Path | None, may_edit: bool, require,
                    orders: pd.DataFrame | None = None) -> None:
    from dataclasses import replace

    from src.ui.feature_data import product_frame

    st.markdown("**Kalkulator margin Shopee Mall** · membaca data yang ada, tidak mengubah data")
    st.caption(
        "Penerimaan bersih = harga jual akhir − biaya administrasi kategori − biaya program Shopee Mall − biaya proses pesanan − iklan per unit (− komisi affiliate bila via affiliate). "
        "HPP tidak dipakai; tingkat aman dinilai dari batas total potongan."
    )
    _parameter_panel(features, may_edit=may_edit, username=username, require=require)
    fees = _category_fees(features)
    programs, order_fee, limit = _programs(features)
    rows = _portfolio_rows(features, table, data, orders, fees)
    port = fee.portfolio(rows, programs=programs, order_fee=order_fee, limit_pct=limit) if not rows.empty else pd.DataFrame()
    _priority_table(port, limit)

    # ------------------------------------------------------------------ simulasi satu SKU
    st.markdown("<div class='section-title'>Simulasi per SKU</div>", unsafe_allow_html=True)
    products = product_frame(table).drop_duplicates("sku")
    if products.empty:
        st.info("Daftar SKU belum tersedia. Unggah data stok atau jalankan analisa sekali.")
        return
    labels = {s: product_label(s, n, v) for s, n, v in zip(products["sku"], products["product_name"], products["variation"])}
    ordered = list(port["sku"]) + [s for s in labels if s not in set(port["sku"])] if not port.empty else list(labels)
    ordered = [s for s in ordered if s in labels]
    sku = st.selectbox("SKU (urut prioritas perbaikan)", ordered, format_func=lambda s: labels[s], key="calc-sku", placeholder="Ketik SKU atau nama produk…")
    base_row = rows.loc[rows["sku"] == sku].iloc[0] if not rows.empty and (rows["sku"] == sku).any() else None
    product = products.loc[products["sku"] == sku].iloc[0]
    sku_cat = features.get_json(KEY_SKU_CAT, {}) or {}
    saved_cat = sku_cat.get(sku)
    default_index = None
    if saved_cat is not None:
        match = fees.index[(fees["kategori"] == saved_cat.get("kategori")) & (fees["jenis_produk"] == saved_cat.get("jenis_produk"))]
        default_index = int(match[0]) if len(match) else None
    suggested = default_index is None
    if default_index is None:
        default_index = fee.suggest_category(product["product_name"], fees)
    c1, c2 = st.columns([1.7, 1])
    pick = c1.selectbox(
        "Kategori Shopee (biaya administrasi)", list(range(len(fees))), index=default_index, key=f"calc-cat-{sku}",
        format_func=lambda i: f"{fees.loc[i, 'label']} · {fmt_num(fees.loc[i, 'biaya_admin_pct'], 2)}%" if pd.notna(fees.loc[i, "biaya_admin_pct"]) else fees.loc[i, "label"],
        placeholder="Pilih kategori (bila tidak ada, pakai 11,70%)",
    )
    admin_pct = float(fees.loc[pick, "biaya_admin_pct"]) if pick is not None and pd.notna(fees.loc[pick, "biaya_admin_pct"]) else fee.DEFAULT_ADMIN_PCT
    note = ("usulan otomatis dari nama produk" if suggested else "kategori tersimpan") if pick is not None else f"memakai {fmt_num(fee.DEFAULT_ADMIN_PCT, 2)}%"
    if pick is not None and fees.loc[pick, "catatan"]:
        note += " · tarif perlu dicek"
    c1.markdown(f"<div class='field-hint'>{html.escape(note)}</div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        if may_edit and pick is not None and st.button("Simpan kategori SKU", key=f"calc-cat-save-{sku}", use_container_width=True):
            require("setting_kalkulator_biaya", "edit")
            sku_cat[sku] = {"kategori": fees.loc[pick, "kategori"], "sub_kategori": fees.loc[pick, "sub_kategori"], "jenis_produk": fees.loc[pick, "jenis_produk"]}
            features.set_json(KEY_SKU_CAT, sku_cat, username=username)
            st.toast("Kategori SKU tersimpan.")
            st.rerun()

    harga0 = float(base_row["harga"]) if base_row is not None else float(product["price"])
    voucher0 = float(base_row["voucher_unit"]) if base_row is not None else 0.0
    iklan0 = float(data.ad_per_unit.get(sku, 0.0) or 0.0)
    aff_pct = float(base_row["affiliate_pct"]) if base_row is not None else 0.0
    roas = float(base_row["roas"]) if base_row is not None and base_row["roas"] == base_row["roas"] else None
    r = st.columns(5)
    with r[0]:
        harga = float(input_rupiah("Harga jual", int(round(harga0)), key=f"calc-price-{sku}", help="Bawaan = harga transaksi rata-rata 30 hari (sudah setelah diskon), atau harga data produk"))
    with r[1]:
        diskon = float(input_rupiah("Diskon tambahan per unit", 0, key=f"calc-disc-{sku}"))
    with r[2]:
        voucher = float(input_rupiah("Voucher penjual per unit", int(round(voucher0)), key=f"calc-vou-{sku}", help="Bawaan = rata-rata voucher penjual per unit di transaksi"))
    with r[3]:
        iklan = float(input_rupiah("Biaya iklan per unit", int(round(iklan0)), key=f"calc-ad-{sku}", help="Bawaan = biaya iklan SKU dari data iklan ÷ QTY terjual"))
    qty_order = float(r[4].number_input("Unit per pesanan", 1, 100, 1, key=f"calc-qty-{sku}", help="Biaya Proses Pesanan dibagi ke jumlah unit ini"))
    sim_programs = {k: dict(v) for k, v in programs.items()}
    optional = [k for k, v in programs.items() if not v.get("wajib")]
    cols = st.columns(4)
    for i, key in enumerate(optional):
        prog = programs[key]
        sim_programs[key]["on"] = cols[i % 4].checkbox(f"{prog['label']} ({fmt_num(prog['pct'], 2)}%)", value=bool(prog.get("on")), key=f"calc-prog-{key}-{sku}")
    big = cols[len(optional) % 4].checkbox("Barang ukuran khusus (Gratis Ongkir)", value=_is_big(product["product_name"]), key=f"calc-big-{sku}",
                                          help="Otomatis tercentang untuk produk bertanda PACKING KAYU")
    aff_on = cols[(len(optional) + 1) % 4].checkbox(f"Terjual via affiliate ({fmt_num(aff_pct, 1)}%)", value=False, key=f"calc-aff-{sku}")

    inp = fee.Inputs(harga=harga, diskon=diskon, voucher=voucher, qty_per_order=qty_order, admin_pct=admin_pct, programs=sim_programs,
                     order_fee=order_fee, affiliate_pct=aff_pct, affiliate_on=aff_on, iklan=iklan, ukuran_khusus=big)
    value, pct = fee.margin(inp)
    base = inp.harga_akhir
    potong = fee.shopee_fees(inp)
    total = 100 - pct if np.isfinite(pct) else float("nan")
    k = st.columns(4)
    card(k[0], "Harga jual akhir", fmt_idr(base), hint="setelah diskon & voucher penjual")
    card(k[1], "Potongan Shopee", fmt_idr(potong), hint=f"{fmt_pct(potong / base * 100 if base else 0, 1)} dari harga akhir")
    card(k[2], "Total potongan", fmt_pct(total, 1), hint=f"batas {fmt_num(limit, 0)}% · {'melebihi' if total > limit else 'aman'}")
    card(k[3], "Penerimaan bersih per unit", fmt_idr(value), hint="sebelum HPP")
    left, right = st.columns([1.25, 1])
    with left:
        show_table(fee.breakdown(inp), kinds={"Rp per unit": "money", "% harga akhir": "pct"}, bold_label="Harga jual akhir", max_height=10_000)
    with right:
        notes = fee.analysis(inp, limit_pct=limit, qty_30=float(base_row["qty_30"]) if base_row is not None else None,
                             pred_qty_30=_prediction_30(table, features, sku), roas=roas)
        items = "".join(
            f"<div style='background:{TONE[t][0]};color:{TONE[t][1]};border-radius:10px;padding:.45rem .7rem;margin-bottom:.35rem;font-size:.88rem'>"
            f"{TONE[t][2]} {html.escape(text)}</div>"
            for t, text in notes
        )
        st.markdown(f"<div style='font-weight:700;margin-bottom:.35rem'>Analisa agar tetap profit</div>{items}", unsafe_allow_html=True)
    scen = []

    def add(name: str, trial: fee.Inputs) -> None:
        v, p = fee.margin(trial)
        scen.append({"Skenario": name, "Penerimaan bersih/unit": v, "Total potongan": 100 - p, "Selisih vs sekarang": v - value})

    add("Sekarang", inp)
    add("Tanpa iklan", replace(inp, iklan=0.0))
    add("Tanpa komisi affiliate" if aff_on else f"Bila via affiliate {fmt_num(aff_pct, 1)}%", replace(inp, affiliate_on=not aff_on))
    add("Tanpa Live & Video XTRA", replace(inp, programs={k: {**v, "on": v.get("on") and k not in ("live_xtra", "video_xtra")} for k, v in sim_programs.items()}))
    add("Tanpa diskon & voucher penjual", replace(inp, diskon=0.0, voucher=0.0))
    st.markdown("**Skenario cepat**")
    show_table(pd.DataFrame(scen), kinds={"Penerimaan bersih/unit": "money", "Selisih vs sekarang": "money", "Total potongan": "pct"}, bold_label="Sekarang", max_height=10_000)
