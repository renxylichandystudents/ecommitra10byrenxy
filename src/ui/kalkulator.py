"""Setting › Kalkulator biaya: margin bersih per unit untuk Shopee Mall + analisa agar tetap profit."""

from __future__ import annotations

import html
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from src.core import margin as margin_core
from src.core import shopee_fee as fee
from src.core.promo import product_label
from src.ui.common import card, download_excel, fmt_idr, fmt_num, fmt_pct
from src.utils.format import input_rupiah, show_table

KEY_PROGRAMS = "shopee_mall_program"
KEY_CATEGORY = "shopee_mall_category_fee"
KEY_AFFILIATE = "shopee_affiliate_commission"
KEY_SKU_CAT = "shopee_sku_category"
TONE = {"ok": ("#ecfdf5", "#047857", "✅"), "warn": ("#fffbeb", "#b45309", "⚠️"), "bad": ("#fef2f2", "#b91c1c", "⛔"), "info": ("#f8fafc", "#334155", "•")}


def _programs(features) -> tuple[dict, float]:
    saved = features.get_json(KEY_PROGRAMS, None) if features is not None else None
    programs = {k: dict(v) for k, v in fee.DEFAULT_PROGRAMS.items()}
    order_fee = fee.DEFAULT_ORDER_FEE
    if isinstance(saved, dict):
        for key, value in (saved.get("programs") or {}).items():
            if key in programs:
                programs[key].update({k: value[k] for k in ("pct", "cap", "on") if k in value})
        order_fee = float(saved.get("order_fee", order_fee))
    return programs, order_fee


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
            programs, order_fee = _programs(features)
            st.markdown(
                "<div class='field-hint'>Tarif dalam % dari harga jual akhir (setelah diskon & voucher penjual). Maks = batas Rp per kuantitas (0 = tanpa batas). "
                "Kolom <b>Ikut</b> = bawaan saat kalkulator dibuka; tim tetap bisa menyalakan/mematikan per simulasi.</div>",
                unsafe_allow_html=True,
            )
            frame = pd.DataFrame([
                {"Kode": k, "Biaya": v["label"], "Tarif (%)": float(v["pct"]), "Maks per kuantitas (Rp)": float(v.get("cap") or 0), "Ikut": bool(v.get("on")), "Wajib": bool(v.get("wajib"))}
                for k, v in programs.items()
            ])
            edited = st.data_editor(
                frame, hide_index=True, use_container_width=True, disabled=["Kode", "Biaya", "Wajib"] if may_edit else True,
                column_config={"Kode": None, "Tarif (%)": st.column_config.NumberColumn(format="%.2f", min_value=0.0, max_value=50.0, step=0.05),
                               "Maks per kuantitas (Rp)": st.column_config.NumberColumn(format="%d", min_value=0, step=1000)},
                key="fee-programs-editor",
            )
            order = st.number_input("Biaya Proses Pesanan (Rp per pesanan selesai)", 0.0, 50_000.0, float(order_fee), 50.0, key="fee-order", disabled=not may_edit)
            if float(programs["gratis_ongkir"]["pct"]) <= 0:
                st.warning("Tarif **Gratis Ongkir XTRA** masih 0%. Isi sesuai kategori produk Anda agar margin tidak terlihat lebih besar.", icon=":material/warning:")
            if may_edit and st.button("Simpan parameter", type="primary", key="fee-programs-save"):
                require("setting_kalkulator_biaya", "edit")
                payload = {"programs": {r["Kode"]: {"pct": float(r["Tarif (%)"]), "cap": float(r["Maks per kuantitas (Rp)"]), "on": bool(r["Ikut"])} for r in edited.to_dict("records")},
                           "order_fee": float(order)}
                features.set_json(KEY_PROGRAMS, payload, username=username)
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


def show_calculator(features, table: pd.DataFrame, data, *, username: str, today: date, user_root: Path | None, may_edit: bool, require) -> None:
    from src.core.config import load_params
    from src.ui.feature_data import product_frame

    st.markdown("**Kalkulator margin Shopee Mall** · simulasi per SKU, tidak mengubah data")
    st.caption(
        "Margin bersih = harga jual akhir − biaya administrasi kategori − biaya program Shopee Mall − biaya proses pesanan − komisi affiliate − iklan per unit − HPP − packing − ongkir penjual."
    )
    _parameter_panel(features, may_edit=may_edit, username=username, require=require)
    products = product_frame(table)
    if products.empty:
        st.info("Daftar SKU belum tersedia. Unggah data stok atau jalankan analisa sekali.")
        return
    products = products.drop_duplicates("sku")
    labels = {s: product_label(s, n, v) for s, n, v in zip(products["sku"], products["product_name"], products["variation"])}
    fees = _category_fees(features)
    programs, order_fee = _programs(features)
    aff = _affiliate(features)
    aff_by_code = dict(zip(aff.get("product_code", []), aff.get("komisi_pct", []))) if not aff.empty else {}
    codes = st.session_state.get("_sku_product_code") or {}
    sku_cat = features.get_json(KEY_SKU_CAT, {}) or {}

    st.markdown("<div class='section-title'>1 · Pilih produk & kategori Shopee</div>", unsafe_allow_html=True)
    c1, c2 = st.columns([1.3, 1.7])
    sku = c1.selectbox("SKU", list(labels), format_func=lambda s: labels[s], key="calc-sku", placeholder="Ketik SKU atau nama produk…")
    row = products.loc[products["sku"] == sku].iloc[0]
    saved_cat = sku_cat.get(sku)
    options = list(range(len(fees)))
    default_index = None
    if saved_cat is not None:
        match = fees.index[(fees["kategori"] == saved_cat.get("kategori")) & (fees["jenis_produk"] == saved_cat.get("jenis_produk"))]
        default_index = int(match[0]) if len(match) else None
    suggested = default_index is None
    if default_index is None:
        default_index = fee.suggest_category(row["product_name"], fees)
    pick = c2.selectbox(
        "Kategori Shopee (biaya administrasi)", options, index=default_index, key=f"calc-cat-{sku}",
        format_func=lambda i: f"{fees.loc[i, 'label']} · {fmt_num(fees.loc[i, 'biaya_admin_pct'], 2)}%" if pd.notna(fees.loc[i, "biaya_admin_pct"]) else fees.loc[i, "label"],
        placeholder="Pilih kategori (bila tidak ada, pakai 11,70%)",
    )
    admin_pct = float(fees.loc[pick, "biaya_admin_pct"]) if pick is not None and pd.notna(fees.loc[pick, "biaya_admin_pct"]) else fee.DEFAULT_ADMIN_PCT
    note = []
    if pick is not None:
        note.append("usulan otomatis dari nama produk — periksa & simpan" if suggested else "kategori tersimpan untuk SKU ini")
        if fees.loc[pick, "catatan"]:
            note.append("tarif perlu dicek: " + fees.loc[pick, "catatan"])
    else:
        note.append(f"kategori belum dipilih, memakai {fmt_num(fee.DEFAULT_ADMIN_PCT, 2)}%")
    c2.markdown(f"<div class='field-hint'>{html.escape(' · '.join(note))}</div>", unsafe_allow_html=True)
    if may_edit and pick is not None and c2.button("Simpan kategori untuk SKU ini", key=f"calc-cat-save-{sku}"):
        require("setting_kalkulator_biaya", "edit")
        sku_cat[sku] = {"kategori": fees.loc[pick, "kategori"], "sub_kategori": fees.loc[pick, "sub_kategori"], "jenis_produk": fees.loc[pick, "jenis_produk"]}
        features.set_json(KEY_SKU_CAT, sku_cat, username=username)
        st.toast("Kategori SKU tersimpan.")

    comp = margin_core.effective_components(data.components, sku, on=today) or margin_core.Components()
    ad_default = float(data.ad_per_unit.get(sku, 0.0) or 0.0)
    roas = None
    if isinstance(table, pd.DataFrame) and {"biaya_iklan", "omzet_iklan"} <= set(table.columns):
        part = table.loc[table["sku"].astype(str) == sku]
        cost, omzet = float(pd.to_numeric(part["biaya_iklan"], errors="coerce").sum()), float(pd.to_numeric(part["omzet_iklan"], errors="coerce").sum())
        roas = omzet / cost if cost > 0 else None
    aff_pct = float(aff_by_code.get(codes.get(sku, ""), 0.0) or 0.0)

    st.markdown("<div class='section-title'>2 · Harga & biaya per unit</div>", unsafe_allow_html=True)
    r = st.columns(4)
    with r[0]:
        harga = float(input_rupiah("Harga jual", int(round(float(row["price"]))), key=f"calc-price-{sku}", help="Bawaan = harga di data produk terakhir"))
    with r[1]:
        diskon = float(input_rupiah("Diskon penjual per unit", 0, key=f"calc-disc-{sku}"))
    with r[2]:
        voucher = float(input_rupiah("Voucher penjual per unit", int(comp.voucher), key=f"calc-vou-{sku}"))
    qty_order = float(r[3].number_input("Unit per pesanan", 1, 100, 1, key=f"calc-qty-{sku}", help="Biaya Proses Pesanan dibagi ke jumlah unit ini"))
    r = st.columns(4)
    with r[0]:
        hpp = float(input_rupiah("HPP", int(comp.hpp), key=f"calc-hpp-{sku}"))
    with r[1]:
        packing = float(input_rupiah("Packing", int(comp.packing), key=f"calc-pack-{sku}"))
    with r[2]:
        ongkir = float(input_rupiah("Ongkir ditanggung penjual", int(comp.ongkir_penjual), key=f"calc-ong-{sku}"))
    with r[3]:
        iklan = float(input_rupiah(
            "Biaya iklan per unit", int(round(ad_default)), key=f"calc-ad-{sku}",
            help="Bawaan = biaya iklan SKU dari data iklan yang diunggah ÷ QTY terjual periode yang sama",
        ))
    hints = [f"Iklan: {fmt_idr(ad_default)}/unit dari data iklan" + (f" · ROAS {fmt_num(roas, 1)}" if roas else "") if ad_default else "Iklan: belum ada data iklan untuk SKU ini"]
    hints.append(f"Komisi affiliate dari file: {fmt_num(aff_pct, 1)}%" if aff_pct else "Komisi affiliate: SKU ini tidak ada di file komisi")
    if comp.hpp <= 0:
        hints.append("HPP belum ada di komponen biaya (unggah di bagian bawah)")
    st.markdown(f"<div class='field-hint'>{' · '.join(html.escape(h) for h in hints)}</div>", unsafe_allow_html=True)

    st.markdown("<div class='section-title'>3 · Program Shopee yang diikuti</div>", unsafe_allow_html=True)
    sim_programs = {k: dict(v) for k, v in programs.items()}
    optional = [k for k, v in programs.items() if not v.get("wajib")]
    cols = st.columns(len(optional) + 2)
    for col, key in zip(cols, optional):
        prog = programs[key]
        sim_programs[key]["on"] = col.checkbox(
            f"{prog['label']} ({fmt_num(prog['pct'], 2)}%)", value=bool(prog.get("on")), key=f"calc-prog-{key}-{sku}",
        )
    aff_on = cols[len(optional)].checkbox(f"Terjual via affiliate ({fmt_num(aff_pct, 1)}%)", value=aff_pct > 0, key=f"calc-aff-{sku}")
    params = load_params(user_root) if user_root else {}
    target = float(cols[-1].number_input("Target margin (%)", 0.0, 60.0, float(params.get("margin", {}).get("margin_min_pct", 8) or 8), 0.5, key="calc-target"))

    inp = fee.Inputs(
        harga=harga, diskon=diskon, voucher=voucher, qty_per_order=qty_order, admin_pct=admin_pct, programs=sim_programs,
        order_fee=order_fee, affiliate_pct=aff_pct, affiliate_on=aff_on, iklan=iklan, hpp=hpp, packing=packing, ongkir=ongkir,
    )
    value, pct = fee.margin(inp)
    potong = fee.shopee_fees(inp)
    base = inp.harga_akhir

    st.markdown("<div class='section-title'>4 · Hasil</div>", unsafe_allow_html=True)
    k = st.columns(4)
    card(k[0], "Harga jual akhir", fmt_idr(base), hint="setelah diskon & voucher penjual")
    card(k[1], "Potongan Shopee", fmt_idr(potong), hint=f"{fmt_pct(potong / base * 100 if base else 0, 1)} dari harga akhir")
    tone = "untung" if value >= 0 else "rugi"
    card(k[2], "Margin bersih per unit", fmt_idr(value) if hpp > 0 else "HPP belum diisi", hint=f"{fmt_pct(pct, 1)} · {tone}" if hpp > 0 else "isi HPP untuk margin yang benar")
    need = fee.min_price(inp, target) if hpp > 0 else float("nan")
    card(k[3], f"Harga minimal margin {fmt_num(target, 1)}%", fmt_idr(need) if np.isfinite(need) else "–", hint="harga jual sebelum diskon & voucher")

    left, right = st.columns([1.25, 1])
    with left:
        detail = fee.breakdown(inp)
        show_table(detail, kinds={"Rp per unit": "money", "% harga akhir": "pct"}, bold_label="Harga jual akhir", max_height=10_000)
    with right:
        notes = fee.analysis(inp, target_pct=target, pred_qty_30=_prediction_30(table, features, sku), roas=roas)
        items = "".join(
            f"<div style='background:{TONE[t][0]};color:{TONE[t][1]};border-radius:10px;padding:.45rem .7rem;margin-bottom:.35rem;font-size:.88rem'>"
            f"{TONE[t][2]} {html.escape(text)}</div>"
            for t, text in notes
        )
        st.markdown(f"<div style='font-weight:700;margin-bottom:.35rem'>Analisa agar tetap profit</div>{items}", unsafe_allow_html=True)

    # Skenario: dampak tiap keputusan pada margin.
    scen = []
    from dataclasses import replace

    def add(name: str, trial: fee.Inputs) -> None:
        v, p = fee.margin(trial)
        scen.append({"Skenario": name, "Margin per unit": v, "Margin %": p, "Selisih vs sekarang": v - value})

    add("Sekarang", inp)
    add("Tanpa iklan", replace(inp, iklan=0.0))
    add("Tanpa komisi affiliate" if aff_on else f"Dengan komisi affiliate {fmt_num(aff_pct, 1)}%", replace(inp, affiliate_on=not aff_on))
    add("Tanpa program opsional (Gratis Ongkir/Promo/Live/Asuransi)", replace(inp, programs={k: {**v, "on": v.get("on") and v.get("wajib")} for k, v in sim_programs.items()}))
    add("Tanpa diskon & voucher penjual", replace(inp, diskon=0.0, voucher=0.0))
    st.markdown("**Skenario cepat**")
    show_table(pd.DataFrame(scen), kinds={"Margin per unit": "money", "Selisih vs sekarang": "money", "Margin %": "pct"}, bold_label="Sekarang", max_height=10_000)
