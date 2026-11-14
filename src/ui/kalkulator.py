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
from src.ui.common import batched_view, card, download_excel, fmt_idr, fmt_num, fmt_pct
from src.utils.format import angka, desimal, input_rupiah, parse_angka, show_table

KEY_PROGRAMS = "shopee_mall_program"
KEY_CATEGORY = "shopee_mall_category_fee"
KEY_AFFILIATE = "shopee_affiliate_commission"
KEY_SKU_CAT = "shopee_sku_category"
TONE = {"ok": ("#ecfdf5", "#047857", "✅"), "warn": ("#fffbeb", "#b45309", "⚠️"), "bad": ("#fef2f2", "#b91c1c", "⛔"), "info": ("#f8fafc", "#334155", "•")}


def _pct_text(value) -> float:
    """"4,5" / "4.5" / 4.5 → 4.5 (tarif persen)."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().replace("%", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


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
    with st.container():
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
                rows.append({"Kode": k, "Biaya": v["label"], "Tarif (%)": desimal(v["pct"], 2), "Maks per kuantitas (Rp)": angka(v.get("cap") or 0),
                             "Ikut": bool(v.get("on")), "Keterangan": v.get("rentang", "wajib" if v.get("wajib") else "")})
                if k == "gratis_ongkir":
                    rows.append({"Kode": "gratis_ongkir_khusus", "Biaya": "Gratis Ongkir XTRA (ukuran khusus)", "Tarif (%)": desimal(v.get("pct_khusus", 9.5), 2),
                                 "Maks per kuantitas (Rp)": angka(v.get("cap_khusus", 60_000)), "Ikut": bool(v.get("on")), "Keterangan": "dipakai untuk barang besar"})
            edited = st.data_editor(
                pd.DataFrame(rows), hide_index=True, use_container_width=True, disabled=["Kode", "Biaya", "Keterangan"] if may_edit else True,
                column_config={"Kode": None, "Tarif (%)": st.column_config.TextColumn(help="Pakai koma untuk desimal, mis. 4,5"),
                               "Maks per kuantitas (Rp)": st.column_config.TextColumn(help="Ketik angka; titik ribuan otomatis dibaca (0 = tanpa batas)"),
                               "Keterangan": st.column_config.TextColumn(width="large")},
                key="fee-programs-editor",
            )
            order = float(input_rupiah("Biaya Proses Pesanan (Rp per pesanan selesai)", int(order_fee), key="fee-order"))
            st.caption("Modal/margin kotor per SKU tidak diisi di sini: dari Harga beli (file merchandising) atau File margin di Upload data › Target & margin.")
            if may_edit and st.button("Simpan parameter", type="primary", key="fee-programs-save"):
                require("setting_kalkulator_biaya", "edit")
                payload_programs = {}
                for r in edited.to_dict("records"):
                    if r["Kode"] == "gratis_ongkir_khusus":
                        payload_programs.setdefault("gratis_ongkir", {}).update({"pct_khusus": _pct_text(r["Tarif (%)"]), "cap_khusus": parse_angka(r["Maks per kuantitas (Rp)"])})
                    else:
                        payload_programs.setdefault(r["Kode"], {}).update({"pct": _pct_text(r["Tarif (%)"]), "cap": parse_angka(r["Maks per kuantitas (Rp)"]), "on": bool(r["Ikut"])})
                features.set_json(KEY_PROGRAMS, {"programs": payload_programs, "order_fee": float(order)}, username=username)
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
            cat_view = fees[["kategori", "sub_kategori", "jenis_produk", "biaya_admin_pct", "catatan"]].sort_values(["kategori", "sub_kategori"]).rename(columns={
                "kategori": "Kategori", "sub_kategori": "Sub kategori", "jenis_produk": "Jenis produk", "biaya_admin_pct": "Biaya admin (%)", "catatan": "Catatan"}).reset_index(drop=True)
            batched_view(
                len(cat_view), key="fee-cat", noun="baris",
                render=lambda lo, hi: show_table(cat_view.iloc[lo:hi], kinds={"Biaya admin (%)": "dec"}, max_height=10_000,
                                                 column_config={"Jenis produk": st.column_config.TextColumn(width="large")}),
                download=lambda: download_excel(fees[["kategori", "sub_kategori", "jenis_produk", "biaya_admin_pct", "catatan"]], "biaya_kategori_shopee_mall.xlsx", key="xl-fee-cat", label="Unduh tabel kategori"),
            )
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
                aff_view = aff.rename(columns={"product_code": "Produk ID", "nama": "Nama produk", "komisi_pct": "Komisi (%)"})
                aff_view = aff_view.sort_values("Komisi (%)", ascending=False, kind="mergesort").reset_index(drop=True)
                st.markdown("<div class='field-hint'>Urutan: komisi tertinggi di atas (paling memotong margin bila terjual lewat affiliate).</div>", unsafe_allow_html=True)
                batched_view(
                    len(aff_view), key="fee-aff", noun="produk",
                    render=lambda lo, hi: show_table(aff_view.iloc[lo:hi], kinds={"Komisi (%)": "dec"}, max_height=10_000),
                    download=lambda: download_excel(aff_view, "komisi_affiliate.xlsx", key="xl-fee-aff"),
                )
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


def _portfolio_rows(features, table: pd.DataFrame, data, orders: pd.DataFrame | None, fees: pd.DataFrame, md=None, start=None, end=None) -> pd.DataFrame:
    """Satu baris per SKU yang laku pada periode [start, end] (bawaan bulan berjalan s.d. hari penuh terakhir): harga akhir rata-rata transaksi, voucher penjual, kategori, iklan, affiliate."""
    from src.core.gudang import norm_sku
    from src.ui.feature_data import product_frame

    products = product_frame(table).drop_duplicates("sku")
    if orders is None or orders.empty or products.empty:
        return pd.DataFrame()
    # Semua angka bersih, sama dengan istilah tabel lain: QTY bersih & Sales produk bersih = baris yang tidak batal / Belum Bayar,
    # dikurangi unit & nilai retur (metrics.sold_lines = net_sku_sales). Voucher penjual ikut dikurangi sebanding unit retur.
    from src.core.metrics import sold_lines

    gross_qty = pd.to_numeric(orders["qty"], errors="coerce")
    work = sold_lines(orders.assign(_gross_qty=gross_qty))
    if work is None or work.empty:
        return pd.DataFrame()
    if "seller_voucher" in work.columns:
        share = (pd.to_numeric(work["qty"], errors="coerce") / work["_gross_qty"].where(work["_gross_qty"] > 0)).clip(0, 1).fillna(1.0)
        work = work.assign(seller_voucher=pd.to_numeric(work["seller_voucher"], errors="coerce").fillna(0.0) * share)
    stamp = pd.to_datetime(work["order_time"], errors="coerce")
    if start is not None and end is not None:
        work = work.loc[stamp.dt.normalize().between(pd.Timestamp(start), pd.Timestamp(end))]
    else:
        work = work.loc[stamp >= stamp.max().normalize() - pd.Timedelta(days=29)]
    grouped = work.assign(sku=work["sku"].astype(str)).groupby("sku").agg(
        qty=("qty", "sum"), omzet=("sales", "sum"),
        voucher=("seller_voucher", "sum") if "seller_voucher" in work.columns else ("qty", lambda s: 0.0),
    )
    grouped = grouped.loc[grouped["qty"] > 0]
    active, _at = st.session_state.get("_active_skus") or (set(), "")
    if active:
        # SKU nonaktif (tidak ada di unggahan stok terakhir) tidak bisa diperbaiki; dampaknya ada di Laporan margin › SKU nonaktif.
        from src.core.margin_file import sku_key

        grouped = grouped.loc[[sku_key(s) in active for s in grouped.index]]
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
    rows = []
    for sku, r in grouped.iterrows():
        name = names.get(sku) or names.get(norm_sku(sku), sku)
        idx, admin = fee.admin_for(sku, name, fees, sku_cat)
        harga = float(r["omzet"]) / float(r["qty"]) if r["qty"] else float(prices.get(sku, 0))
        rows.append({
            "sku": sku, "nama": name, "kategori": (fees.loc[idx, "sub_kategori"] if idx is not None else "Lainnya") + f" ({fmt_num(admin, 2)}%)",
            "harga": harga, "diskon_unit": 0.0, "voucher_unit": float(r["voucher"]) / float(r["qty"]) if r["qty"] else 0.0,
            "admin_pct": admin, "affiliate_pct": float(aff_by_code.get(codes.get(sku, ""), 0.0) or 0.0),
            "iklan_unit": float(data.ad_per_unit.get(sku, 0.0) or 0.0), "roas": roas_map.get(sku, np.nan),
            "qty_30": float(r["qty"]), "omzet_30": float(r["omzet"]), "ukuran_khusus": _is_big(name),
            **_margin_cols(md, sku, harga - (float(r["voucher"]) / float(r["qty"]) if r["qty"] else 0.0)),
        })
    return pd.DataFrame(rows)


def _margin_cols(md, sku: str, price: float | None = None) -> dict:
    """Margin kotor % SKU pada harga `price`: dari harga beli (file merchandising) bila ada, selain itu dari File margin."""
    hit = md.row_at(sku, price) if md is not None and md.ready else None
    if not hit or not np.isfinite(hit.get("margin_kotor_pct", np.nan)):
        return {"margin_kotor_pct": np.nan, "pajak_share": np.nan, "sumber": "", "harga_beli": np.nan}
    return {"margin_kotor_pct": float(hit["margin_kotor_pct"]), "pajak_share": float(hit["porsi_pajak"]), "sumber": hit["sumber"],
            "harga_beli": float(hit.get("harga_beli", np.nan))}


def _month_of(orders: pd.DataFrame | None) -> date:
    if orders is not None and not orders.empty:
        stamp = pd.to_datetime(orders["order_time"], errors="coerce").max()
        if pd.notna(stamp):
            return stamp.date()
    return date.today()


def _goals(features, user_root, orders, ref: date | None = None):
    """Target bulan acuan (bulan dari periode yang dipilih; bawaan bulan data terakhir)."""
    from src.core.business import business_targets
    from src.core.config import load_params
    from src.ui.feature_data import target_for

    last = ref or _month_of(orders)
    params = load_params(user_root) if user_root else {}
    saved = target_for(features, f"{last.year:04d}-{last.month:02d}")
    return business_targets(params, saved)


def _summary(goals, port: pd.DataFrame, orders: pd.DataFrame | None, features, md, ref: date | None = None, *,
             month_port: pd.DataFrame | None = None, period_label: str = "periode terpilih") -> None:
    """Kondisi margin toko + target penjualan + langkah yang disarankan (berurutan).

    Bulan acuan = bulan tanggal akhir periode terpilih. Bulan berjalan (bulan data terakhir) → proyeksi
    (realisasi s.d. hari ini + prediksi sisa hari); bulan yang sudah lewat → penjualan aktual sebulan penuh."""
    from src.ui.margin_data import status_line
    from src.ui.targets_view import month_outlook

    every = (st.session_state.get("analysis") or {}).get("orders_all")
    outlook = month_outlook(every if isinstance(every, pd.DataFrame) and not every.empty else orders, features, ref)
    running, last, mtd, rest = outlook["running"], outlook["last"], outlook["mtd"], outlook["rest"]
    pred_daily, projection, factor = outlook["pred_daily"], outlook["projection"], float(outlook.get("faktor") or 1.0)
    month_label = f"{['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des'][last.month - 1]} {last.year}"
    has_target = goals.target_sales > 0
    gap = goals.target_sales - projection if has_target else 0.0
    acuan = port.attrs.get("acuan_pct", float("nan")) if not port.empty else float("nan")
    overall = port.attrs.get("overall_pct", float("nan")) if not port.empty else float("nan")
    known = port.loc[port["bersih_30"].notna()] if not port.empty else port
    omzet = float(known["omzet_30"].sum()) if len(known) else 0.0
    kotor = float((known["omzet_30"] * known["kotor_pct"]).sum() / omzet) if omzet else float("nan")
    rugi = port.loc[port["status"] == "Rugi"] if not port.empty else port
    low = port.loc[port["status"] == "Rendah"] if not port.empty else port

    if not md.ready:
        st.warning("File margin dan harga beli belum diunggah: margin per SKU belum bisa dihitung. Unggah di **Upload data › Target & margin**.", icon=":material/upload_file:")
    # Margin toko mengacu ke penjualan aktual bulan acuan (tgl 1 s.d. data terakhir); bila belum ada, pakai periode terpilih.
    mp = month_port if month_port is not None and not month_port.empty else port
    m_known = mp.loc[mp["bersih_30"].notna()] if not mp.empty else mp
    m_omzet = float(m_known["omzet_30"].sum()) if len(m_known) else 0.0
    m_overall = mp.attrs.get("overall_pct", float("nan")) if not mp.empty else float("nan")
    m_kotor = float((m_known["omzet_30"] * m_known["kotor_pct"]).sum() / m_omzet) if m_omzet else float("nan")
    m_bersih = float(m_known["bersih_30"].sum()) if len(m_known) else 0.0
    actual_span = f"1–{last.day} {month_label}"
    from src.ui.targets_view import achievement_line

    reach = achievement_line(mtd, last.replace(day=1), last, features,
                             orders=every if isinstance(every, pd.DataFrame) and not every.empty else orders)
    k = st.columns(4)
    card(k[0], f"Sales bersih aktual {month_label}", fmt_idr(mtd),
         hint=(f"realisasi {actual_span}" if running else "bulan sudah lewat · angka aktual")
              + f" · sama dengan tab Data · sales produk {fmt_idr(outlook.get('mtd_produk', 0))}"
              + (f"<br>{reach}" if reach else ""))
    card(k[1], f"Margin bersih aktual {month_label}", fmt_pct(m_overall, 1) if np.isfinite(m_overall) else "–",
         hint=(f"{actual_span} · margin kotor {fmt_pct(m_kotor, 1)} − potongan Shopee & iklan = {fmt_idr(m_bersih)}") if np.isfinite(m_overall) else "butuh file margin")
    if running:
        rest_text = f"aktual + prediksi {rest} hari sisa" if rest else "bulan sudah penuh"
        card(k[2], f"Prediksi sales bersih {month_label}", fmt_idr(projection),
             hint=(f"{rest_text} · target {fmt_idr(goals.target_sales)} · prediksi pencapaian "
                   f"<b style='color:{'#1d4ed8' if gap <= 0 else '#dc2626'}'>{fmt_pct(projection / goals.target_sales * 100, 1)}</b>"
                   + (f" · kurang {fmt_idr(gap)}" if gap > 0 else " · target tercapai")) if has_target else f"{rest_text} · target {month_label} belum diunggah")
        proj_margin = projection / factor * m_overall / 100 if np.isfinite(m_overall) else float("nan")
        card(k[3], f"Prediksi margin bersih {month_label}", fmt_idr(proj_margin) if np.isfinite(proj_margin) else "–",
             hint=(f"prediksi sales produk {fmt_idr(projection / factor)} × margin aktual {fmt_pct(m_overall, 1)} · sisa {rest} hari {fmt_idr(proj_margin - m_bersih)}")
             if np.isfinite(proj_margin) else "butuh file margin")
        k = st.columns(4)
    card(k[2] if not running else k[0], "SKU rugi", fmt_num(len(rugi)),
         hint=f"{html.escape(period_label)} · rugi ±{fmt_idr(float(rugi['rugi_30'].sum()) if len(rugi) else 0)} · sales produk bersih {fmt_idr(float(rugi['omzet_30'].sum()) if len(rugi) else 0)}")
    card(k[3] if not running else k[1], "SKU margin rendah", fmt_num(len(low)),
         hint=f"{html.escape(period_label)} · untung di bawah {fmt_pct(acuan, 1)} · potensi +{fmt_idr(float(low['selisih_30'].sum()) if len(low) else 0)}")
    if running and np.isfinite(overall):
        card(k[2], "Margin bersih periode terpilih", fmt_pct(overall, 1),
             hint=f"{html.escape(period_label)} · sales produk bersih {fmt_idr(omzet)} · margin kotor {fmt_pct(kotor, 1)} · {fmt_idr(float(known['bersih_30'].sum()))}")
    chips = [status_line(md), f"Batas margin rendah <b>{fmt_pct(acuan, 1)}</b> (rata-rata SKU yang untung)", (f"Prediksi sisa {rest} hari: <b>{fmt_idr(projection - mtd)}</b> (±{fmt_idr(pred_daily)}/hari)" if running else f"Bulan {month_label} sudah lewat: angka aktual, bukan proyeksi")]
    if len(known):
        chips.insert(1, f"Potongan Shopee rata-rata <b>{fmt_pct(float((known['omzet_30'] * known['shopee_pct']).sum() / omzet), 1)}</b> · iklan <b>{fmt_pct(float((known['omzet_30'] * known['iklan_pct']).sum() / omzet), 1)}</b>")
    st.markdown(
        "<div style='display:flex;flex-wrap:wrap;gap:.4rem;margin:.2rem 0 .6rem'>"
        + "".join(f"<span style='background:#f1f5f9;border:1px solid #e2e8f0;border-radius:999px;padding:.2rem .7rem;font-size:var(--fs-sm);color:#334155'>{t}</span>" for t in chips)
        + "</div>",
        unsafe_allow_html=True,
    )
    steps: list[str] = []
    if not md.ready:
        steps.append("<b>Unggah file harga beli / file margin</b> di Upload data › Target & margin agar margin per SKU terbaca.")
    if len(rugi):
        steps.append(f"<b>Hentikan kerugian di {fmt_num(len(rugi))} SKU rugi</b>, mulai 5 teratas (±{fmt_idr(float(rugi.head(5)['rugi_30'].sum()))} per periode): "
                     "kurangi iklan/program opsional atau naikkan harga sesuai kolom <i>Yang perlu dikerjakan</i>.")
    if len(low):
        steps.append(f"<b>Naikkan {fmt_num(len(low))} SKU margin rendah</b> ke batas {fmt_pct(acuan, 1)} — 5 teratas menambah ±{fmt_idr(float(low.head(5)['selisih_30'].sum()))} per periode.")
    if has_target and gap > 0 and not running:
        steps.append(f"<b>{month_label} ditutup kurang {fmt_idr(gap)}</b> dari target — evaluasi SKU margin tinggi yang penjualannya turun untuk bulan berjalan.")
    if has_target and gap > 0 and running and not port.empty:
        safe = port.loc[port["status"] == "Tinggi"].sort_values("omzet_30", ascending=False).head(3)
        if not safe.empty:
            names = ", ".join(html.escape(str(n)[:38]) for n in safe["nama"])
            steps.append(f"<b>Tutup kekurangan {fmt_idr(gap)}</b> dengan mendorong SKU margin tinggi bersales bersih besar: {names}.")
    if len(rugi):
        steps.append("<b>Jangan menambah iklan</b> pada SKU rugi: sales naik tetapi kerugian ikut naik.")
    if has_target and gap <= 0:
        steps.append("<b>Proyeksi sudah mencapai target</b> — fokus menjaga margin." if running else f"<b>Target {month_label} tercapai</b>.")
    if steps:
        st.markdown(
            "<div style='border:1px solid #e2e8f0;border-left:4px solid #ee4d2d;border-radius:12px;background:#fff;padding:.7rem 1rem;margin-bottom:.8rem'>"
            "<div style='font-weight:700;margin-bottom:.3rem'>Langkah yang disarankan</div>"
            "<ol style='margin:0 0 0 1.1rem;padding:0;line-height:1.6;font-size:var(--fs-base)'>" + "".join(f"<li>{t}</li>" for t in steps) + "</ol></div>",
            unsafe_allow_html=True,
        )


STATUS_ICON = {"Rugi": "🔴 Rugi", "Rendah": "🟠 Rendah", "Tinggi": "🟢 Tinggi", "Tanpa data": "⚪ Tanpa data"}


SUGGEST_COLUMNS = ("Harga beli / modal", "Harga jual disarankan", "Promo disarankan", "Harga setelah promo", "Perubahan harga bayar vs aktual",
                   "Harga nett (setelah semua biaya)", "Profit/unit setelah promo", "Margin setelah promo", "Catatan harga")


def _suggestions(prices: pd.DataFrame | None, skus: pd.Series, actual: pd.Series) -> pd.DataFrame:
    """Kolom usulan harga per SKU (dari perhitungan Simulasi › semua SKU) untuk dibandingkan dengan aktual.

    Harga nett = harga setelah promo − voucher − potongan Shopee − iklan per unit (uang yang diterima per unit);
    profit/unit = harga nett − harga beli/modal."""
    empty = pd.DataFrame({c: [np.nan] * len(skus) for c in SUGGEST_COLUMNS})
    if prices is None or prices.empty:
        return empty
    p = prices.drop_duplicates("SKU").set_index("SKU")
    key = skus.astype(str).to_numpy()

    def col(name):
        return p[name].reindex(key).to_numpy(dtype=float) if name in p.columns else np.full(len(key), np.nan)

    modal, saran, after, profit = col("Modal/harga beli per unit"), col("Harga jual disarankan"), col("Harga setelah promo"), col("Margin setelah promo/unit")
    notes = p["Catatan"].reindex(key).fillna("").to_numpy() if "Catatan" in p.columns else [""] * len(key)
    voucher = np.nan_to_num(col("Voucher penjual/unit"))
    actual = pd.to_numeric(actual, errors="coerce").to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        change = np.where(actual > 0, ((after - voucher) / actual - 1) * 100, np.nan)
    return pd.DataFrame({
        "Harga beli / modal": modal, "Harga jual disarankan": saran, "Promo disarankan": col("Promo disarankan (%)"),
        "Harga setelah promo": after, "Perubahan harga bayar vs aktual": change,
        "Harga nett (setelah semua biaya)": modal + profit, "Profit/unit setelah promo": profit,
        "Margin setelah promo": col("Margin setelah promo (%)"), "Catatan harga": notes,
    })


def _priority_table(port: pd.DataFrame, period_label: str = "30 hari terakhir", *, prices: pd.DataFrame | None = None) -> None:
    st.markdown(f"<div class='section-title'>Daftar prioritas perbaikan margin · {html.escape(period_label)}</div>", unsafe_allow_html=True)
    if port.empty:
        st.info("Belum ada SKU terjual pada periode ini.")
        return
    acuan = port.attrs.get("acuan_pct", float("nan"))
    with st.expander("Cara membaca daftar ini"):
        st.markdown(
            "- **Margin bersih** = margin kotor (dari harga beli bila ada — PPN dari harga jual — selain itu file margin) − potongan Shopee (administrasi kategori + program + proses pesanan) − iklan per unit, "
            "dalam % harga akhir (harga transaksi rata-rata periode terpilih setelah diskon & voucher penjual).\n"
            f"- **Status**: 🔴 Rugi = margin bersih di bawah 0 · 🟠 Rendah = untung tetapi di bawah {fmt_pct(acuan, 1)} (rata-rata margin bersih SKU yang untung) · 🟢 Tinggi = sama/di atas batas itu · "
            "⚪ Tanpa data = tidak ada di file margin.\n"
            "- **Urutan**: Rugi dari kerugian Rp terbesar → Rendah dari selisih Rp terbesar ke batas (sales produk bersih × selisih %) → Tinggi dari sales produk bersih terbesar.\n"
            "- **Sales produk bersih & QTY bersih**: transaksi periode terpilih selain batal & Belum Bayar, dikurangi retur (istilah sama dengan tabel Data/Prediksi). "
            "Semua margin dihitung dari angka bersih ini.\n"
            "- **Yang perlu dikerjakan**: tuas yang bisa dikendalikan tim — iklan (ROAS minimal), komisi affiliate, program opsional, diskon/voucher, lalu harga.\n"
            "- **Usulan harga untuk MD** (setelah kolom Harga akhir = aktual): **Harga beli / modal** (file MD, belum PPN; selain itu file margin) → "
            "**Harga jual disarankan** (harga normal minimal impas setelah semua biaya & iklan) → **Promo disarankan** (sesuai kebiasaan promo transaksi SKU itu, "
            "dibatasi agar tidak rugi) → **Harga setelah promo** → **Harga nett** (uang diterima per unit setelah voucher, potongan Shopee, dan iklan) → "
            "**Profit/unit** = harga nett − harga beli. Bandingkan dengan Margin bersih/unit aktual; baris Total menunjukkan profit periode bila usulan dipakai dengan qty yang sama."
        )
    f1, f2 = st.columns([1.2, 1.8])
    status_pick = f1.multiselect("Status", list(STATUS_ICON), key="calc-port-status", placeholder="Semua status")
    query = f2.selectbox("Cari SKU", [f"{s} · {n}" for s, n in zip(port["sku"], port["nama"])], index=None, key="calc-port-q", placeholder="Ketik SKU atau nama produk…")
    view = port
    if status_pick:
        view = view.loc[view["status"].isin(status_pick)]
    if query:
        view = view.loc[view["sku"] == str(query).split(" · ")[0]]
    frame = pd.DataFrame({
        "Prioritas": range(1, len(view) + 1), "Status": view["status"].map(STATUS_ICON), "SKU": view["sku"], "Nama": view["nama"],
        "Yang perlu dikerjakan": view["perbaikan"], "Sales produk bersih": view["omzet_30"], "QTY bersih": view["qty_30"],
        "Margin kotor": view["kotor_pct"], "Potongan Shopee": view["shopee_pct"], "Iklan": view["iklan_pct"], "Margin bersih": view["bersih_pct"],
        "Margin bersih/unit": view["bersih_unit"], "Margin bersih periode": view["bersih_30"],
        "Rugi / kurang periode": np.where(view["status"] == "Rugi", view["rugi_30"], view["selisih_30"]),
        "Harga akhir": view["harga_akhir"], "ROAS": view["roas"], "Komisi affiliate": view["affiliate_pct"],
        "Sumber margin": view["sumber"], "Kategori Shopee": view["kategori"],
    }).reset_index(drop=True)
    # Usulan untuk MD: dibandingkan langsung dengan aktual (harga akhir & margin bersih) di baris yang sama.
    suggest = _suggestions(prices, frame["SKU"], frame["Harga akhir"])
    at = frame.columns.get_loc("Harga akhir") + 1
    frame = pd.concat([frame.iloc[:, :at], suggest, frame.iloc[:, at:]], axis=1)
    total = {c: np.nan for c in frame.columns}
    omzet = frame["Sales produk bersih"].sum()
    bersih = frame["Margin bersih periode"].sum(min_count=1)
    unit_after = pd.to_numeric(frame["Profit/unit setelah promo"], errors="coerce")
    after_qty = (unit_after * frame["QTY bersih"]).sum(min_count=1)
    same = frame.loc[unit_after.notna(), "Margin bersih periode"].sum()
    total.update({"Status": "Total", "SKU": f"{fmt_num(len(frame))} SKU", "Nama": "", "Yang perlu dikerjakan": "", "Sumber margin": "", "Kategori Shopee": "",
                  "Catatan harga": (f"{fmt_num(int(unit_after.notna().sum()))} SKU berusulan: bila harga & promo usulan dipakai dengan qty periode ini, "
                                    f"profit {fmt_idr(after_qty)} (aktual SKU yang sama {fmt_idr(same)})") if pd.notna(after_qty) else "",
                  "Sales produk bersih": omzet, "QTY bersih": frame["QTY bersih"].sum(), "Margin bersih periode": bersih,
                  "Margin bersih": (bersih / frame.loc[frame["Margin bersih periode"].notna(), "Sales produk bersih"].sum() * 100) if pd.notna(bersih) else np.nan,
                  "Rugi / kurang periode": frame["Rugi / kurang periode"].sum()})
    full = pd.concat([pd.DataFrame([total]), frame], ignore_index=True)
    kinds = {"Sales produk bersih": "money", "Margin bersih/unit": "money", "Margin bersih periode": "money", "Rugi / kurang periode": "money", "Harga akhir": "money",
             "Margin kotor": "pct", "Potongan Shopee": "pct", "Iklan": "pct", "Margin bersih": "pct", "Komisi affiliate": "pct", "ROAS": "dec",
             "QTY bersih": "count", "Prioritas": "count",
             "Harga beli / modal": "money", "Harga jual disarankan": "money", "Harga setelah promo": "money", "Harga nett (setelah semua biaya)": "money",
             "Profit/unit setelah promo": "money", "Perubahan harga bayar vs aktual": "pct", "Promo disarankan": "pct", "Margin setelah promo": "pct"}
    batched_view(
        len(frame), key="calc-port", noun="SKU",
        render=lambda lo, hi: show_table(
            pd.concat([full.iloc[:1], full.iloc[1:].iloc[lo:hi]], ignore_index=True), bold_label="Total", kinds=kinds, max_height=10_000, dash_missing=True,
            column_config={"Yang perlu dikerjakan": st.column_config.TextColumn(width="large"), "Catatan harga": st.column_config.TextColumn(width="large"),
                           "Harga akhir": st.column_config.Column(help="Aktual: harga transaksi rata-rata periode terpilih setelah diskon & voucher"),
                           "Harga beli / modal": st.column_config.Column(help="Harga beli file MD (belum PPN); bila tidak ada, modal dari file margin"),
                           "Harga jual disarankan": st.column_config.Column(help="Harga normal yang disarankan agar untung: ≥ harga impas (semua biaya + iklan) dan, bila bisa, margin ≥ batas margin rendah"),
                           "Perubahan harga bayar vs aktual": st.column_config.Column(help="Harga yang dibayar pembeli bila usulan dipakai (harga setelah promo − voucher penjual) dibanding Harga akhir aktual"),
                           "Promo disarankan": st.column_config.Column(help="Kedalaman promo sesuai kebiasaan transaksi SKU ini (median diskon bila ≥ 20% transaksi berpromo), dibatasi agar tidak di bawah impas"),
                           "Harga setelah promo": st.column_config.Column(help="Harga jual disarankan setelah promo disarankan = harga yang dibayar pembeli"),
                           "Harga nett (setelah semua biaya)": st.column_config.Column(help="Uang diterima per unit: harga setelah promo − voucher − potongan Shopee − iklan"),
                           "Profit/unit setelah promo": st.column_config.Column(help="Harga nett − harga beli/modal (bandingkan dengan Margin bersih/unit aktual)")},
        ),
        download=lambda: download_excel(full, "prioritas_perbaikan_margin.xlsx", key="xl-calc-port"),
    )


def _history(orders: pd.DataFrame | None) -> dict:
    """Histori harga per SKU (harga awal & diskon 90 hari terakhir), disimpan per sesi."""
    from src.core import pricing

    if orders is None or orders.empty:
        return {}
    key = (len(orders), str(pd.to_datetime(orders["order_time"], errors="coerce").max()))
    cache = st.session_state.get("_calc-history")
    if isinstance(cache, tuple) and cache[0] == key:
        return cache[1]
    hist = pricing.price_history(orders)
    out = {str(r["sku"]): r for r in hist.to_dict("records")}
    st.session_state["_calc-history"] = (key, out)
    return out


def _all_rows(features, table: pd.DataFrame, data, rows: pd.DataFrame, fees: pd.DataFrame, md) -> pd.DataFrame:
    """Baris portofolio (SKU laku di periode) + SKU aktif lain yang belum laku (harga dari data produk)."""
    from src.core.margin_file import sku_key
    from src.ui.feature_data import product_frame

    products = product_frame(table).drop_duplicates("sku")
    have = set(rows["sku"].astype(str)) if not rows.empty else set()
    active, _at = st.session_state.get("_active_skus") or (set(), "")
    sku_cat = features.get_json(KEY_SKU_CAT, {}) or {} if features is not None else {}
    aff = _affiliate(features)
    aff_by_code = dict(zip(aff.get("product_code", []), aff.get("komisi_pct", []))) if not aff.empty else {}
    codes = st.session_state.get("_sku_product_code") or {}
    extra = []
    for p in products.itertuples(index=False):
        sku = str(p.sku)
        if sku in have or not p.price or p.price <= 0 or (active and sku_key(sku) not in active):
            continue
        idx, admin = fee.admin_for(sku, p.product_name, fees, sku_cat)
        extra.append({
            "sku": sku, "nama": p.product_name, "kategori": (fees.loc[idx, "sub_kategori"] if idx is not None else "Lainnya") + f" ({fmt_num(admin, 2)}%)",
            "harga": float(p.price), "diskon_unit": 0.0, "voucher_unit": 0.0, "admin_pct": admin,
            "affiliate_pct": float(aff_by_code.get(codes.get(sku, ""), 0.0) or 0.0), "iklan_unit": float(data.ad_per_unit.get(sku, 0.0) or 0.0),
            "roas": np.nan, "qty_30": 0.0, "omzet_30": 0.0, "ukuran_khusus": _is_big(p.product_name), **_margin_cols(md, sku, float(p.price)),
        })
    if not extra:
        return rows
    return pd.concat([rows, pd.DataFrame(extra)], ignore_index=True) if not rows.empty else pd.DataFrame(extra)


def _price_table(all_rows: pd.DataFrame, *, programs: dict, order_fee: float, md, acuan: float, hist: dict) -> pd.DataFrame:
    """Perhitungan semua SKU: biaya, margin sekarang, harga impas/sehat/disarankan, promo disarankan, harga & margin setelah promo."""
    from src.core import pricing
    from src.core.margin_file import classify

    out = []
    target = acuan if np.isfinite(acuan) else 0.0
    for r in all_rows.itertuples(index=False):
        inp, kotor, sumber, known = fee.row_inputs(r, programs=programs, order_fee=order_fee, fallback_kotor_pct=md.store_kotor_pct)
        value, pct = fee.margin(inp) if known else (np.nan, np.nan)
        h = hist.get(str(r.sku)) or {}
        normal = float(h.get("harga_awal") or 0) or float(r.harga)
        plan = pricing.plan(inp, normal=normal, target_pct=target, hist_disc=float(h.get("diskon_median", np.nan) or np.nan),
                            hist_share=float(h.get("porsi_promo", 0) or 0), known=known)
        out.append({
            "SKU": str(r.sku), "Produk": r.nama, "Kategori (admin)": r.kategori, "Sumber modal": sumber or "–",
            "Modal/harga beli per unit": inp.hpp if known else np.nan, "Harga transaksi rata-rata": float(r.harga),
            "Harga normal (harga awal)": normal, "Voucher penjual/unit": float(r.voucher_unit), "Potongan Shopee/unit": fee.shopee_fees(inp),
            "Iklan/unit": float(r.iklan_unit or 0), "Margin bersih/unit": value, "Margin bersih (%)": pct, "Status": classify(pct, acuan),
            "QTY bersih (periode)": float(r.qty_30 or 0), "Harga minimal (impas)": plan["harga_impas"],
            "Harga sehat (margin ≥ batas)": plan["harga_sehat"], "Harga jual disarankan": plan["harga_disarankan"],
            "Transaksi berpromo (%)": h.get("porsi_promo", np.nan), "Promo historis median (%)": h.get("diskon_median", np.nan),
            "Promo historis maks. (%)": h.get("diskon_maks", np.nan),
            "Promo disarankan (%)": plan["promo_pct"], "Harga setelah promo": plan["harga_promo"],
            "Margin setelah promo/unit": plan["margin_promo"], "Margin setelah promo (%)": plan["margin_promo_pct"], "Catatan": plan["catatan"],
        })
    frame = pd.DataFrame(out)
    if frame.empty:
        return frame
    order = {"Rugi": 0, "Rendah": 1, "Tinggi": 2, "Tanpa data": 3}
    return frame.assign(_o=frame["Status"].map(order)).sort_values(["_o", "QTY bersih (periode)"], ascending=[True, False]).drop(columns="_o").reset_index(drop=True)


PRICE_KINDS = {c: "money" for c in ("Modal/harga beli per unit", "Harga transaksi rata-rata", "Harga normal (harga awal)", "Voucher penjual/unit",
                                     "Potongan Shopee/unit", "Iklan/unit", "Margin bersih/unit", "Harga minimal (impas)", "Harga sehat (margin ≥ batas)",
                                     "Harga jual disarankan", "Harga setelah promo", "Margin setelah promo/unit")}
PRICE_KINDS.update({c: "pct" for c in ("Margin bersih (%)", "Transaksi berpromo (%)", "Promo historis median (%)", "Promo historis maks. (%)", "Promo disarankan (%)",
                                        "Margin setelah promo (%)")})
PRICE_KINDS["QTY bersih (periode)"] = "count"


def show_calculator(features, table: pd.DataFrame, data, *, username: str, today: date, user_root: Path | None, may_edit: bool, require,
                    orders: pd.DataFrame | None = None) -> None:
    st.markdown(
        "<div style='margin-bottom:.2rem'><span style='font-size:var(--fs-lg);font-weight:800'>Kalkulator margin Shopee Mall</span>"
        "<span style='color:#64748b;font-size:var(--fs-base)'> · seberapa besar potongan Shopee & iklan memakan margin, dan apa yang harus diperbaiki dulu</span></div>",
        unsafe_allow_html=True,
    )
    from src.ui.margin_data import load_margin

    fees = _category_fees(features)
    programs, order_fee, _old_limit = _programs(features)
    md = load_margin(features)
    tab_sum, tab_sim, tab_param = st.tabs(["📊 Ringkasan & prioritas", "🧮 Simulasi per SKU", "⚙️ Parameter biaya"])
    start = end = None
    period_label = "bulan berjalan"
    with tab_sum:
        if orders is not None and not orders.empty:
            from src.ui.common import date_range_picker, range_label

            stamps = pd.to_datetime(orders["order_time"], errors="coerce").dropna()
            from src.ui.month_track_view import full_day_cutoff

            lo, hi = stamps.min().date(), stamps.max().date()
            # Bawaan = periode kartu "aktual" bulan berjalan: tanggal 1 s.d. hari penuh terakhir data (hari data terakhir yang
            # belum lengkap tidak ikut), sehingga kartu periode terpilih dan kartu bulan berjalan memakai rentang yang sama.
            cutoff = min(max(full_day_cutoff(stamps.max()), lo), hi)
            default = (max(lo, cutoff.replace(day=1)), cutoff)
            start, end = date_range_picker(key="calc-cal", lo=lo, hi=hi, default=default, label="Periode analisa")
            period_label = range_label(start, end)
    goals = _goals(features, user_root, orders, end)
    rows = _portfolio_rows(features, table, data, orders, fees, md, start, end)
    port = fee.portfolio(rows, programs=programs, order_fee=order_fee, fallback_kotor_pct=md.store_kotor_pct) if not rows.empty else pd.DataFrame()
    acuan = port.attrs.get("acuan_pct", float("nan")) if not port.empty else float("nan")
    month_port = pd.DataFrame()
    if orders is not None and not orders.empty:
        data_last = _month_of(orders)
        ref = end or data_last
        running = (ref.year, ref.month) == (data_last.year, data_last.month)
        m_end = data_last if running else (pd.Timestamp(ref) + pd.offsets.MonthEnd(0)).date()
        m_start = m_end.replace(day=1)
        if (start, end) == (m_start, m_end):
            month_port = port
        else:
            m_rows = _portfolio_rows(features, table, data, orders, fees, md, m_start, m_end)
            if not m_rows.empty:
                month_port = fee.portfolio(m_rows, programs=programs, order_fee=order_fee, fallback_kotor_pct=md.store_kotor_pct)
    hist = _history(orders)
    cache_key = ("calc-all", st.session_state.get("_feature-version", 0), st.session_state.get("_harga-beli-version", 0),
                 st.session_state.get("_margin-version", 0), str(start), str(end), len(rows), round(acuan, 3) if np.isfinite(acuan) else None)
    cached = st.session_state.get("_calc-all")
    if isinstance(cached, tuple) and cached[0] == cache_key:
        all_prices = cached[1]
    else:
        with tab_sum, st.spinner("Menghitung harga & promo semua SKU..."):
            all_prices = _price_table(_all_rows(features, table, data, rows, fees, md), programs=programs, order_fee=order_fee, md=md,
                                      acuan=acuan, hist=hist)
        st.session_state["_calc-all"] = (cache_key, all_prices)
    with tab_sum:
        _summary(goals, port, orders, features, md, end, month_port=month_port, period_label=period_label)
        _priority_table(port, period_label, prices=all_prices)
    with tab_param:
        _parameter_panel(features, may_edit=may_edit, username=username, require=require)
    with tab_sim:
        if not all_prices.empty:
            d1, d2 = st.columns([3, 1], vertical_alignment="center")
            d1.markdown(f"<div class='field-hint'>Perhitungan <b>semua {fmt_num(len(all_prices))} SKU</b> (periode {html.escape(period_label)}): modal/harga beli, "
                        "potongan Shopee, iklan, margin sekarang, harga impas, harga jual disarankan, promo disarankan, harga & margin setelah promo.</div>",
                        unsafe_allow_html=True)
            with d2:
                download_excel({"Semua SKU": all_prices}, f"kalkulator_harga_promo_semua_sku_{(end or date.today()).isoformat()}.xlsx",
                               key="xl-calc-all", label="Unduh semua SKU")
        _simulation(features, table, data, rows, port, fees, programs, order_fee, acuan, md, may_edit=may_edit, username=username, require=require,
                    hist=hist)


def _bar(parts: list[tuple[str, float, str]], base: float) -> str:
    """Batang komposisi harga jual akhir (HTML)."""
    if base <= 0:
        return ""
    segs = "".join(
        f"<div title='{html.escape(label)} {fmt_idr(value)}' style='width:{max(value, 0) / base * 100:.2f}%;background:{color}'></div>"
        for label, value, color in parts if value > 0
    )
    legend = "".join(
        f"<span style='margin-right:.8rem;white-space:nowrap'><span style='display:inline-block;width:.6rem;height:.6rem;border-radius:2px;background:{color};margin-right:.25rem'></span>"
        f"{html.escape(label)} {fmt_pct(value / base * 100, 1)}</span>"
        for label, value, color in parts if value > 0
    )
    return (f"<div style='display:flex;height:14px;border-radius:7px;overflow:hidden;background:#f1f5f9;margin:.35rem 0 .3rem'>{segs}</div>"
            f"<div style='font-size:var(--fs-xs);color:#475569;line-height:1.7'>{legend}</div>")


def _line(label: str, value: float, base: float, *, bold: bool = False, sub: str = "") -> str:
    weight = "700" if bold else "400"
    color = "#b91c1c" if value < 0 and bold else "#0f172a"
    pct = f"<span style='color:#64748b;font-size:var(--fs-sm);margin-left:.4rem'>{fmt_pct(value / base * 100, 1)}</span>" if base > 0 else ""
    note = f"<div style='color:#64748b;font-size:var(--fs-xs)'>{html.escape(sub)}</div>" if sub else ""
    border = "border-top:1px solid #e2e8f0;padding-top:.35rem;margin-top:.15rem;" if bold else ""
    return (f"<div style='display:flex;justify-content:space-between;align-items:flex-start;{border}padding-bottom:.25rem'>"
            f"<div style='font-weight:{weight}'>{html.escape(label)}{note}</div>"
            f"<div style='font-weight:{weight};color:{color};white-space:nowrap'>{fmt_idr(value)}{pct}</div></div>")


def _simulation(features, table, data, rows, port, fees, programs, order_fee, acuan, md, *, may_edit: bool, username: str, require,
                hist: dict | None = None) -> None:
    from dataclasses import replace

    from src.core.margin_file import DEFAULT_TAX_SHARE
    from src.ui.feature_data import product_frame

    products = product_frame(table).drop_duplicates("sku")
    if products.empty:
        st.info("Daftar SKU belum tersedia. Unggah data stok atau jalankan analisa sekali.")
        return
    labels = {s: product_label(s, n, v) for s, n, v in zip(products["sku"], products["product_name"], products["variation"])}
    ordered = list(port["sku"]) + [s for s in labels if s not in set(port["sku"])] if not port.empty else list(labels)
    ordered = [s for s in ordered if s in labels]
    sku = st.selectbox("Pilih SKU · urut prioritas perbaikan", ordered, format_func=lambda s: labels[s], key="calc-sku", placeholder="Ketik SKU atau nama produk…")
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
        default_index = fee.admin_for(sku, product["product_name"], fees, sku_cat)[0]

    harga0 = float(base_row["harga"]) if base_row is not None else float(product["price"])
    voucher0 = float(base_row["voucher_unit"]) if base_row is not None else 0.0
    iklan0 = float(data.ad_per_unit.get(sku, 0.0) or 0.0)
    aff_pct = float(base_row["affiliate_pct"]) if base_row is not None else 0.0
    roas = float(base_row["roas"]) if base_row is not None and base_row["roas"] == base_row["roas"] else None

    left, right = st.columns([1, 1.25], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("<div style='font-weight:700;margin-bottom:.2rem'>Atur simulasi</div>", unsafe_allow_html=True)
            r1 = st.columns(2)
            with r1[0]:
                harga = float(input_rupiah("Harga jual", int(round(harga0)), key=f"calc-price-{sku}", help="Bawaan = harga transaksi rata-rata periode terpilih di Ringkasan (sudah setelah diskon), atau harga data produk"))
            with r1[1]:
                iklan = float(input_rupiah("Biaya iklan per unit", int(round(iklan0)), key=f"calc-ad-{sku}", help="Bawaan = biaya iklan SKU dari data iklan ÷ QTY bersih"))
            r2 = st.columns(2)
            with r2[0]:
                diskon = float(input_rupiah("Diskon tambahan per unit", 0, key=f"calc-disc-{sku}"))
            with r2[1]:
                voucher = float(input_rupiah("Voucher penjual per unit", int(round(voucher0)), key=f"calc-vou-{sku}", help="Bawaan = rata-rata voucher penjual per unit di transaksi"))
            sim_programs = {k: dict(v) for k, v in programs.items()}
            optional = [k for k, v in programs.items() if not v.get("wajib")]
            on_count = sum(bool(programs[k].get("on")) for k in optional)
            with st.expander(f"Program Shopee & pengaturan lain · {on_count} program aktif"):
                cols = st.columns(2)
                for i, key in enumerate(optional):
                    prog = programs[key]
                    label = prog["label"].replace(" (ukuran biasa)", "")
                    sim_programs[key]["on"] = cols[i % 2].checkbox(f"{label} ({fmt_num(prog['pct'], 1)}%)", value=bool(prog.get("on")), key=f"calc-prog-{key}-{sku}")
                big = st.checkbox("Barang ukuran khusus (tarif Gratis Ongkir khusus)", value=_is_big(product["product_name"]), key=f"calc-big-{sku}",
                                  help="Otomatis tercentang untuk produk bertanda PACKING KAYU")
                aff_on = st.checkbox(f"Terjual via affiliate (komisi {fmt_num(aff_pct, 1)}%)", value=False, key=f"calc-aff-{sku}")
                qty_order = float(st.number_input("Unit per pesanan", 1, 100, 1, key=f"calc-qty-{sku}", help="Biaya Proses Pesanan dibagi ke jumlah unit ini"))
                pick = st.selectbox(
                    "Kategori Shopee (biaya administrasi)", list(range(len(fees))), index=default_index, key=f"calc-cat-{sku}",
                    format_func=lambda i: f"{fees.loc[i, 'sub_kategori']} › {fees.loc[i, 'jenis_produk'][:40]} · {fmt_num(fees.loc[i, 'biaya_admin_pct'], 2)}%"
                    if pd.notna(fees.loc[i, "biaya_admin_pct"]) else fees.loc[i, "label"],
                    placeholder="Pilih kategori (bila tidak ada, pakai 11,70%)",
                )
                note = ("usulan otomatis dari nama produk" if suggested else "kategori tersimpan") if pick is not None else f"memakai {fmt_num(fee.DEFAULT_ADMIN_PCT, 2)}%"
                if pick is not None and fees.loc[pick, "catatan"]:
                    note += " · tarif perlu dicek"
                st.markdown(f"<div class='field-hint'>{html.escape(note)}</div>", unsafe_allow_html=True)
                if may_edit and pick is not None and st.button("Simpan kategori SKU", key=f"calc-cat-save-{sku}"):
                    require("setting_kalkulator_biaya", "edit")
                    sku_cat[sku] = {"kategori": fees.loc[pick, "kategori"], "sub_kategori": fees.loc[pick, "sub_kategori"], "jenis_produk": fees.loc[pick, "jenis_produk"]}
                    features.set_json(KEY_SKU_CAT, sku_cat, username=username)
                    st.toast("Kategori SKU tersimpan.")
                    st.rerun()
            st.markdown("<div class='field-hint'>Simulasi tidak mengubah data apa pun.</div>", unsafe_allow_html=True)
    admin_pct = float(fees.loc[pick, "biaya_admin_pct"]) if pick is not None and pd.notna(fees.loc[pick, "biaya_admin_pct"]) else fee.DEFAULT_ADMIN_PCT

    hit = _margin_cols(md, sku, (harga0 - voucher0) if base_row is not None else float(product["price"]))
    kotor0, sumber = hit["margin_kotor_pct"], hit["sumber"]
    if not np.isfinite(kotor0) and np.isfinite(md.store_kotor_pct):
        kotor0, sumber = md.store_kotor_pct, "rata-rata toko"
    tax = hit["pajak_share"] if np.isfinite(hit["pajak_share"]) else DEFAULT_TAX_SHARE
    # Modal tetap dalam Rupiah: dihitung dari harga transaksi rata-rata (bukan harga simulasi) × (1 − pajak − margin kotor file).
    ref = harga0 - voucher0 if base_row is not None else float(product["price"])
    known = np.isfinite(kotor0)
    modal = max(ref * (1 - tax - kotor0 / 100.0), 0.0) if known else 0.0
    inp = fee.Inputs(harga=harga, diskon=diskon, voucher=voucher, qty_per_order=qty_order, admin_pct=admin_pct, programs=sim_programs,
                     order_fee=order_fee, affiliate_pct=aff_pct, affiliate_on=aff_on, iklan=iklan, ukuran_khusus=big,
                     hpp=modal, pajak_share=tax if known else 0.0)
    value, pct = fee.margin(inp)
    base = inp.harga_akhir
    target = acuan if np.isfinite(acuan) else 0.0
    shopee_rp = fee.shopee_fees(inp)
    aff_rp = base * aff_pct / 100 if aff_on else 0.0
    tax_rp = base * inp.pajak_share
    kotor_rp = base - tax_rp - modal

    with right:
        if pct < 0:
            tone, word = ("#fef2f2", "#b91c1c"), "Rugi"
        elif pct < target:
            tone, word = ("#fffbeb", "#b45309"), "Margin rendah"
        else:
            tone, word = ("#ecfdf5", "#047857"), "Margin tinggi"
        if not known:
            tone, word = ("#f8fafc", "#334155"), "Tanpa data margin"
        st.markdown(
            f"<div style='background:{tone[0]};border-radius:14px;padding:.8rem 1rem;margin-bottom:.6rem'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center'>"
            f"<div><div style='font-size:var(--fs-xs);color:#475569;font-weight:600;letter-spacing:.02em'>MARGIN BERSIH PER UNIT</div>"
            f"<div style='font-size:var(--fs-2xl);font-weight:800;color:{tone[1]}'>{fmt_idr(value)}</div></div>"
            f"<div style='text-align:right'><span style='background:{tone[1]};color:#fff;border-radius:999px;padding:.2rem .7rem;font-size:var(--fs-sm);font-weight:700'>{word}</span>"
            f"<div style='font-size:var(--fs-lg);font-weight:700;color:{tone[1]};margin-top:.3rem'>{fmt_pct(pct, 1) if np.isfinite(pct) else '–'}</div>"
            f"<div style='font-size:var(--fs-xs);color:#64748b'>batas margin rendah {fmt_pct(target, 1)}</div></div></div>"
            + _bar([("Modal + pajak", modal + tax_rp, "#94a3b8"), ("Potongan Shopee", shopee_rp, "#f97316"), ("Iklan", iklan, "#ef4444"),
                    ("Affiliate", aff_rp, "#a855f7"), ("Margin bersih", max(value, 0), "#1d4ed8")], base)
            + "</div>",
            unsafe_allow_html=True,
        )
        lines = [_line("Harga jual akhir", base, 0, sub="setelah diskon & voucher penjual")]
        if known:
            lines.append(_line("Margin kotor", kotor_rp, base, sub=(f"harga beli {fmt_idr(modal)}/unit · {sumber}" if "Harga beli" in str(sumber) else f"file margin · {sumber}")))
        lines.append(_line("− Potongan Shopee", -shopee_rp, base, sub=f"admin kategori {fmt_num(admin_pct, 2)}% + program + proses pesanan"))
        if iklan:
            lines.append(_line("− Iklan", -iklan, base, sub=f"ROAS {fmt_num(roas, 1)}" if roas else ""))
        if aff_rp:
            lines.append(_line("− Komisi affiliate", -aff_rp, base))
        lines.append(_line("Margin bersih", value, base, bold=True))
        st.markdown(f"<div style='border:1px solid #e2e8f0;border-radius:12px;padding:.6rem .9rem;font-size:var(--fs-base)'>{''.join(lines)}</div>", unsafe_allow_html=True)

        todo = fee.fixes(inp, 0.0 if pct < 0 else target) if known else []
        floor = fee.min_price(replace(inp, iklan=0.0), 0.0) if known else float("nan")
        st.markdown("<div style='font-weight:700;margin:.7rem 0 .3rem'>Yang perlu dilakukan</div>", unsafe_allow_html=True)
        if todo:
            st.markdown("<ol style='margin:0 0 0 1.1rem;padding:0;line-height:1.6;font-size:var(--fs-base)'>" + "".join(f"<li>{html.escape(t)}</li>" for t in todo[:4]) + "</ol>",
                        unsafe_allow_html=True)
        elif known:
            st.markdown(f"<div style='font-size:var(--fs-base)'>Margin sudah sehat. Iklan maksimal agar tetap di atas batas: <b>{fmt_idr(max(fee.max_iklan(inp, target), 0))}</b>/unit.</div>",
                        unsafe_allow_html=True)
        else:
            st.markdown("<div style='font-size:var(--fs-base)'>SKU belum ada di file margin. Unggah file margin terbaru di tab ⚙️ Parameter biaya.</div>", unsafe_allow_html=True)
        if np.isfinite(floor):
            st.caption(f"Harga impas tanpa iklan: {fmt_idr(floor)}")
        if known:
            from src.core import pricing

            h = (hist or {}).get(str(sku)) or {}
            normal = float(h.get("harga_awal") or 0) or harga
            pl = pricing.plan(inp, normal=normal, target_pct=target, hist_disc=float(h.get("diskon_median", np.nan) or np.nan),
                              hist_share=float(h.get("porsi_promo", 0) or 0))
            hist_txt = (f"histori 90 hari: {fmt_pct(h.get('porsi_promo', 0), 0)} dari {fmt_num(h.get('transaksi', 0))} transaksi memakai promo, "
                        f"diskon median {fmt_pct(h['diskon_median'], 0)}, maks. {fmt_pct(h['diskon_maks'], 0)}" if h else "belum ada histori harga awal di transaksi")
            ok = pl["margin_promo"] >= 0 if np.isfinite(pl["margin_promo"]) else False
            st.markdown(
                "<div style='font-weight:700;margin:.7rem 0 .3rem'>Rekomendasi harga & promo</div>"
                "<div style='border:1px solid #e2e8f0;border-radius:12px;padding:.6rem .9rem;font-size:var(--fs-base);line-height:1.7'>"
                f"Harga normal sekarang <b>{fmt_idr(pl['harga_normal'])}</b> · harga minimal tidak rugi (modal + potongan Shopee + iklan) <b>{fmt_idr(pl['harga_impas'])}</b> · "
                f"harga sehat (margin ≥ {fmt_pct(target, 1)}) <b>{fmt_idr(pl['harga_sehat'])}</b><br>"
                f"Harga jual disarankan <b>{fmt_idr(pl['harga_disarankan'])}</b> · promo disarankan <b>{fmt_pct(pl['promo_pct'], 0)}</b> → "
                f"harga setelah promo <b>{fmt_idr(pl['harga_promo'])}</b> · margin setelah promo "
                f"<b style='color:{'#047857' if ok else '#b91c1c'}'>{fmt_idr(pl['margin_promo'])} ({fmt_pct(pl['margin_promo_pct'], 1)})</b><br>"
                f"<span style='color:#64748b;font-size:var(--fs-sm)'>{html.escape(hist_txt)} · {html.escape(pl['catatan'])}</span></div>",
                unsafe_allow_html=True,
            )

    scen = []

    def add(name: str, trial: fee.Inputs) -> None:
        v, p = fee.margin(trial)
        scen.append({"Skenario": name, "Margin bersih/unit": v, "Margin bersih": p, "Selisih vs sekarang": v - value})

    add("Sekarang", inp)
    add("Tanpa iklan", replace(inp, iklan=0.0))
    add("Tanpa komisi affiliate" if aff_on else f"Bila via affiliate {fmt_num(aff_pct, 1)}%", replace(inp, affiliate_on=not aff_on))
    add("Tanpa Live & Video XTRA", replace(inp, programs={k: {**v, "on": v.get("on") and k not in ("live_xtra", "video_xtra")} for k, v in sim_programs.items()}))
    add("Tanpa diskon & voucher penjual", replace(inp, diskon=0.0, voucher=0.0))
    if np.isfinite(floor):
        add(f"Harga impas tanpa iklan ({fmt_idr(floor)})", replace(inp, harga=floor, iklan=0.0))
    # Tiga tombol dalam satu baris (ringkas); hanya satu detail terbuka, tampil selebar halaman di bawahnya.
    detail = st.segmented_control(
        "Detail", ["Skenario cepat", "Rincian biaya lengkap", "Analisa lengkap"], default=None, key=f"calc-detail-{sku}",
        label_visibility="collapsed", width="stretch",
    )
    if detail == "Skenario cepat":
        show_table(pd.DataFrame(scen), kinds={"Margin bersih/unit": "money", "Selisih vs sekarang": "money", "Margin bersih": "pct"}, bold_label="Sekarang", max_height=10_000)
    elif detail == "Rincian biaya lengkap":
        frame = fee.breakdown(inp)
        show_table(frame, kinds={"Rp per unit": "money", "% harga akhir": "pct"}, bold_label=str(frame["Komponen"].iloc[-1]), max_height=10_000,
                   column_config={"Komponen": st.column_config.TextColumn(width="medium"), "Dasar": st.column_config.TextColumn(width="medium"),
                                  "Tarif": st.column_config.TextColumn(width="medium")})
    elif detail == "Analisa lengkap":
        notes = fee.analysis(inp, target_pct=target, qty_30=float(base_row["qty_30"]) if base_row is not None else None,
                             pred_qty_30=_prediction_30(table, features, sku), roas=roas, sumber=sumber)
        st.markdown("".join(
            f"<div style='background:{TONE[t][0]};color:{TONE[t][1]};border-radius:10px;padding:.45rem .7rem;margin-bottom:.35rem;font-size:var(--fs-sm)'>"
            f"{TONE[t][2]} {html.escape(text)}</div>" for t, text in notes), unsafe_allow_html=True)
