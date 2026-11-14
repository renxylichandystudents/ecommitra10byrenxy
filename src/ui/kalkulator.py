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
    total_sales, total_qty, n_before = float(grouped["omzet"].sum()), float(grouped["qty"].sum()), len(grouped)
    active, _at = st.session_state.get("_active_skus") or (set(), "")
    if active:
        # SKU nonaktif (tidak ada di unggahan stok terakhir) tidak bisa diperbaiki; dampaknya ada di Laporan margin › SKU nonaktif.
        from src.core.margin_file import sku_key

        grouped = grouped.loc[[sku_key(s) in active for s in grouped.index]]
    recon = {"sales_semua": total_sales, "qty_semua": total_qty, "sku_nonaktif": int(n_before - len(grouped)),
             "sales_nonaktif": total_sales - float(grouped["omzet"].sum()), "qty_nonaktif": total_qty - float(grouped["qty"].sum())}
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
    out = pd.DataFrame(rows)
    out.attrs["rekonsiliasi"] = recon
    return out


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
              + f" · Total Pembayaran, sama dengan tab Data · Sales produk bersih {fmt_idr(outlook.get('mtd_produk', 0))} (dasar margin)"
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

    Harga nett = harga setelah promo − voucher − PPN − potongan Shopee − iklan per unit (uang yang diterima per unit);
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


PRIORITY_GROUPS = {
    "Produk": ("Prioritas", "Status", "SKU", "Nama"),
    "Tindakan": ("Yang perlu dikerjakan",),
    "Aktual periode terpilih (bersih)": ("Sales produk bersih", "QTY bersih", "Harga akhir", "Margin kotor", "Potongan Shopee", "Iklan", "Komisi affiliate",
                                         "ROAS", "Margin bersih", "Margin bersih/unit", "Margin bersih periode", "Rugi / kurang periode"),
    "Usulan harga untuk MD": SUGGEST_COLUMNS,
    "Keterangan": ("Sumber margin", "Kategori Shopee"),
}


def _bridge_html(bridge: dict, table_sales: float, recon: dict | None, period_label: str) -> str:
    """Jembatan angka: Sales produk bersih (tabel) → Sales bersih / Total Pembayaran (kartu & tab Data)."""
    def line(sign: str, label: str, note: str, value: float, *, strong: bool = False) -> str:
        weight = "800" if strong else "500"
        top = "border-top:1px solid #cbd5e1;padding-top:.3rem;margin-top:.2rem;" if strong and sign == "=" else ""
        return (f"<div style='display:grid;grid-template-columns:1.4rem 1fr auto;gap:.5rem;align-items:baseline;{top}'>"
                f"<span style='color:#64748b;font-weight:700'>{sign}</span>"
                f"<span style='font-weight:{weight}'>{html.escape(label)}<span style='color:#64748b;font-weight:400;font-size:var(--fs-xs)'> · {html.escape(note)}</span></span>"
                f"<span style='font-weight:{weight};white-space:nowrap'>{fmt_idr(value)}</span></div>")

    rows = [line("", "Sales produk bersih", "harga setelah diskon × QTY bersih; dasar margin di tabel ini", bridge["sales_produk"], strong=True),
            line("−", "Voucher penjual", "biaya Mitra10, sudah dihitung di Harga akhir & margin", bridge["seller_voucher"]),
            line("−", "Voucher Shopee, koin & diskon kartu", "ditanggung Shopee, bukan biaya Mitra10", bridge["shopee_side"]),
            line("+", "Ongkir dibayar pembeli", "ikut tercatat di Total Pembayaran", bridge["buyer_shipping"])]
    if abs(bridge["lain"]) >= 1:
        rows.append(line("±", "Lain-lain", "biaya layanan, retur sebagian, pembulatan", bridge["lain"]))
    rows.append(line("=", "Sales bersih (Total Pembayaran)", "angka kartu Sales bersih aktual & tab Data", bridge["sales_bersih"], strong=True))
    hidden = ""
    if recon and recon.get("sku_nonaktif", 0) > 0:
        hidden = (f"<div style='color:#64748b;font-size:var(--fs-xs);margin-top:.35rem'>Baris Total tabel {fmt_idr(table_sales)} = Sales produk bersih "
                  f"tanpa {fmt_num(recon['sku_nonaktif'])} SKU nonaktif ({fmt_idr(recon.get('sales_nonaktif', 0))}; tidak ada di stok terakhir, tidak bisa diperbaiki harganya).</div>")
    return ("<div style='border:1px solid #e2e8f0;border-left:5px solid #2563eb;border-radius:12px;background:#fff;padding:.7rem 1rem;margin:.3rem 0 .7rem;"
            "font-size:var(--fs-sm);line-height:1.7;max-width:900px'>"
            f"<div style='font-weight:800;margin-bottom:.25rem'>Dari Sales produk bersih ke Sales bersih · {html.escape(period_label)}</div>"
            "<div style='color:#64748b;font-size:var(--fs-xs);margin-bottom:.35rem'>Pesanan yang sama (tanpa batal & Belum Bayar, dikurangi retur). "
            "Margin dihitung dari Sales produk bersih karena voucher Shopee & koin tidak mengurangi pendapatan Mitra10.</div>"
            + "".join(rows) + hidden + "</div>")


def _priority_table(port: pd.DataFrame, period_label: str = "30 hari terakhir", *, prices: pd.DataFrame | None = None,
                    recon: dict | None = None, bridge: dict | None = None) -> None:
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
            "**Promo disarankan** (selalu ada, min. 5% maks. 30%: kebiasaan promo transaksi SKU itu bila ≥ 20% transaksi berpromo, selain itu ruang margin sehat) → "
            "**Harga jual disarankan** (harga normal; dinaikkan bila perlu agar tanpa promo tidak rugi dan setelah promo margin tetap ≥ batas margin rendah) → "
            "**Harga setelah promo** → **Harga nett** (uang diterima per unit setelah voucher, PPN, potongan Shopee, dan iklan) → "
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
    frame = pd.concat([frame, suggest], axis=1)
    frame = frame[[c for cols in PRIORITY_GROUPS.values() for c in cols]]
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
    if bridge and bridge.get("sales_produk") and not status_pick and not query:
        st.markdown(_bridge_html(bridge, omzet, recon, period_label), unsafe_allow_html=True)
    from src.ui import grouped_table

    total_row = {c: v for c, v in total.items() if not (isinstance(v, float) and np.isnan(v))}
    total_row.update({"Nama": "Total", "Status": ""})
    grouped_table.show(
        frame, key="calc-port-tbl", filename="prioritas_perbaikan_margin.xlsx", export=full, noun="SKU", first=5,
        groups=PRIORITY_GROUPS, kinds=kinds, total=total_row, rank="Prioritas",
        pin=("Prioritas", "Status", "SKU", "Nama"), wrap=("Nama", "Yang perlu dikerjakan", "Catatan harga"),
        widths={"Prioritas": 84, "Status": 104, "SKU": 104, "Nama": 240, "Yang perlu dikerjakan": 380, "Catatan harga": 380,
                "Sumber margin": 170, "Kategori Shopee": 240},
        signed=("Margin kotor", "Margin bersih", "Margin bersih/unit", "Margin bersih periode", "Perubahan harga bayar vs aktual",
                "Profit/unit setelah promo", "Margin setelah promo"),
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
            "Ukuran khusus": "Ya" if inp.ukuran_khusus else "Tidak",
            **_calc_detail(inp, plan, sumber=sumber, admin_pct=float(r.admin_pct)),
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

    # Satu sumber transaksi untuk semua angka halaman ini (kartu, tabel, jembatan): semua transaksi tersimpan bila ada,
    # sama dengan kartu Sales bersih aktual dan tab Data.
    every = (st.session_state.get("analysis") or {}).get("orders_all")
    if isinstance(every, pd.DataFrame) and not every.empty:
        orders = every
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
        from src.core.metrics import sales_bridge

        bridge = sales_bridge(orders, start, end) if orders is not None and not orders.empty else None
        _priority_table(port, period_label, prices=all_prices, recon=rows.attrs.get("rekonsiliasi") if not rows.empty else None, bridge=bridge)
    with tab_param:
        _parameter_panel(features, may_edit=may_edit, username=username, require=require)
    with tab_sim:
        if not all_prices.empty:
            d1, d2 = st.columns([3, 1], vertical_alignment="center")
            d1.markdown(f"<div class='field-hint'>Rincian <b>semua {fmt_num(len(all_prices))} SKU</b> (periode {html.escape(period_label)}): semua komponen kalkulator "
                        "sekarang & rekomendasi (harga, promo, voucher, PPN, admin, tiap program Shopee, proses pesanan, iklan, nett diterima, harga beli, profit, margin), "
                        "harga impas & sehat, histori promo, dan catatan.</div>",
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


def _tone(pct: float, target: float, known: bool) -> tuple[str, str, str]:
    if not known or not np.isfinite(pct):
        return "#f8fafc", "#334155", "Tanpa data margin"
    if pct < 0:
        return "#fef2f2", "#b91c1c", "Rugi"
    if pct < target:
        return "#fffbeb", "#b45309", "Margin rendah"
    return "#ecfdf5", "#047857", "Margin sehat"


def _result_card(title: str, inp, value: float, pct: float, target: float, known: bool, *, iklan: float, aff_rp: float) -> str:
    bg, color, word = _tone(pct, target, known)
    base = inp.harga_akhir
    tax_rp = base * inp.pajak_share
    bar = _bar([("Harga beli", inp.hpp, "#64748b"), ("PPN", tax_rp, "#94a3b8"), ("Potongan Shopee", fee.shopee_fees(inp), "#f97316"),
                ("Iklan", iklan, "#ef4444"), ("Affiliate", aff_rp, "#a855f7"), ("Profit", max(value, 0), "#1d4ed8")], base)
    return (f"<div style='background:{bg};border-radius:14px;padding:.8rem 1rem;margin-bottom:.6rem'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center'>"
            f"<div><div style='font-size:var(--fs-xs);color:#475569;font-weight:700;letter-spacing:.03em'>{html.escape(title)}</div>"
            f"<div style='font-size:var(--fs-2xl);font-weight:800;color:{color}'>{fmt_idr(value) if known else '–'}</div>"
            f"<div style='font-size:var(--fs-xs);color:#64748b'>dibayar pembeli {fmt_idr(base)} · harga beli {fmt_idr(inp.hpp) if known else '–'}</div></div>"
            f"<div style='text-align:right'><span style='background:{color};color:#fff;border-radius:999px;padding:.2rem .7rem;font-size:var(--fs-sm);font-weight:700'>{word}</span>"
            f"<div style='font-size:var(--fs-lg);font-weight:700;color:{color};margin-top:.3rem'>{fmt_pct(pct, 1) if known and np.isfinite(pct) else '–'}</div>"
            f"<div style='font-size:var(--fs-xs);color:#64748b'>batas margin rendah {fmt_pct(target, 1)}</div></div></div>"
            + bar + "</div>")


def _recommend_card(rec, pl: dict, value: float, pct: float, target: float) -> str:
    """Kartu rekomendasi: harga beli, harga jual, promo, harga setelah promo, nett diterima, profit, margin."""
    bg, color, word = _tone(pct, target, True)
    base = rec.harga_akhir
    nett = rec.hpp + value
    tiles = [("Harga beli", fmt_idr(rec.hpp), ""), ("Harga jual disarankan", fmt_idr(pl["harga_disarankan"]), f"sekarang {fmt_idr(pl['harga_normal'])}"),
             ("Promo", f"{fmt_pct(pl['promo_pct'], 0)}", f"−{fmt_idr(rec.diskon)}"), ("Harga setelah promo", fmt_idr(pl["harga_promo"]),
             f"dibayar pembeli {fmt_idr(base)}" if rec.voucher else "dibayar pembeli"),
             ("Nett diterima", fmt_idr(nett), "setelah PPN, potongan Shopee, iklan"), ("Profit / unit", fmt_idr(value), "nett − harga beli"),
             ("Margin", fmt_pct(pct, 1), f"batas {fmt_pct(target, 1)}")]
    cells = "".join(
        f"<div style='background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:.45rem .6rem'>"
        f"<div style='font-size:var(--fs-xs);color:#64748b;font-weight:600'>{html.escape(t)}</div>"
        f"<div style='font-size:var(--fs-lg);font-weight:800;color:{color if t in ('Profit / unit', 'Margin', 'Nett diterima') else '#0f172a'}'>{v}</div>"
        f"<div style='font-size:var(--fs-xs);color:#94a3b8'>{html.escape(n)}</div></div>" for t, v, n in tiles)
    return (f"<div style='background:{bg};border-radius:14px;padding:.8rem 1rem;margin-bottom:.6rem'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:.45rem'>"
            f"<div style='font-size:var(--fs-xs);color:#475569;font-weight:700;letter-spacing:.03em'>REKOMENDASI HARGA & PROMO</div>"
            f"<span style='background:{color};color:#fff;border-radius:999px;padding:.2rem .7rem;font-size:var(--fs-sm);font-weight:700'>{word}</span></div>"
            f"<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(125px,1fr));gap:.45rem'>{cells}</div></div>")


def _calc_rows(inp, *, sumber: str, admin_pct: float) -> list[tuple[str, str, str, float]]:
    """Baris kalkulator: (jenis, komponen, keterangan, Rp per unit). jenis: price/minus/sub/total."""
    from src.core.shopee_fee import _capped, _rate

    base = inp.harga_akhir
    rows = [("price", "Harga jual normal", "harga sebelum promo", float(inp.harga))]
    rows.append(("minus", "Diskon / promo", "", -float(inp.diskon)))
    rows.append(("minus", "Voucher penjual", "biaya Mitra10", -float(inp.voucher)))
    rows.append(("sub", "Harga dibayar pembeli", "dasar potongan Shopee & margin", base))
    rows.append(("minus", "PPN dalam harga", f"{fmt_num(inp.pajak_share * 100, 2)}% dari harga dibayar", -base * float(inp.pajak_share)))
    rows.append(("minus", "Biaya administrasi kategori", f"{fmt_num(admin_pct, 2)}%", -_capped(base, inp.admin_pct, 0)))
    for key, prog in inp.programs.items():
        if prog.get("on"):
            pct, cap, label = _rate(inp, key, prog)
            rows.append(("minus", label, f"{fmt_num(pct, 2)}%" + (f" (maks {fmt_idr(cap)})" if cap else ""), -_capped(base, pct, cap)))
    rows.append(("minus", "Biaya proses pesanan", f"{fmt_idr(inp.order_fee)}/pesanan ÷ {inp.qty_per_order:g} unit", -float(inp.order_fee) / max(float(inp.qty_per_order or 1), 1.0)))
    if inp.affiliate_on and inp.affiliate_pct:
        rows.append(("minus", "Komisi affiliate", f"{fmt_num(inp.affiliate_pct, 2)}%", -_capped(base, inp.affiliate_pct, 0)))
    rows.append(("minus", "Iklan", "biaya iklan per unit", -float(inp.iklan)))
    value, pct = fee.margin(inp)
    rows.append(("sub", "Nett diterima", "dibayar pembeli − PPN − potongan Shopee − iklan", inp.hpp + value))
    rows.append(("minus", "Harga beli / modal", sumber or "", -float(inp.hpp)))
    rows.append(("total", "Profit / unit", "nett diterima − harga beli", value))
    rows.append(("pct", "Margin bersih", "profit ÷ harga dibayar pembeli", pct))
    return rows


def _calc_detail(inp, plan: dict, *, sumber: str, admin_pct: float) -> dict:
    """Semua komponen kalkulator (sekarang & rekomendasi) sebagai kolom unduhan, sama dengan tabel Kalkulator lengkap."""
    from dataclasses import replace

    out: dict = {}
    pairs = [("Sekarang", inp)]
    if np.isfinite(plan.get("harga_disarankan", np.nan)) and np.isfinite(plan.get("harga_promo", np.nan)):
        pairs.append(("Rekomendasi", replace(inp, harga=plan["harga_disarankan"], diskon=plan["harga_disarankan"] - plan["harga_promo"])))
    for tag, obj in pairs:
        for kind, label, _note, value in _calc_rows(obj, sumber=sumber, admin_pct=admin_pct):
            name = label.replace(" (ukuran khusus)", "")
            out[f"{tag} · {name}" + (" (%)" if kind == "pct" else "")] = value
    return out


def _calc_table(inp, rec, *, sumber: str, roas, admin_pct: float, known: bool) -> str:
    now = _calc_rows(inp, sumber=sumber, admin_pct=admin_pct)
    after = {r[1]: r[3] for r in _calc_rows(rec, sumber=sumber, admin_pct=admin_pct)} if rec is not None else {}

    def cell(kind: str, value) -> str:
        if value is None or (isinstance(value, float) and not np.isfinite(value)):
            return "–"
        if kind == "pct":
            text = fmt_pct(value, 1)
        else:
            text = ("−" + fmt_idr(abs(value))) if value < 0 else fmt_idr(value)
        color = "#b91c1c" if (kind in ("total", "pct") and value < 0) else ("#047857" if kind in ("total", "pct") else ("#64748b" if kind == "minus" else "#0f172a"))
        return f"<span style='color:{color}'>{text}</span>"

    body = []
    for kind, label, note, value in now:
        if kind == "minus" and abs(value) < 0.5 and abs(after.get(label, 0) or 0) < 0.5 and label not in ("Iklan", "Harga beli / modal"):
            continue
        style = {"sub": "background:#f8fafc;font-weight:700", "total": "background:#eff6ff;font-weight:800", "pct": "font-weight:800",
                 "price": "font-weight:600"}.get(kind, "")
        prefix = "− " if kind == "minus" else ("= " if kind in ("sub", "total") else "")
        if label == "Harga beli / modal" and not known:
            note = "belum diketahui"
        if label == "Iklan" and roas:
            note = f"biaya iklan per unit · ROAS {fmt_num(roas, 1)}"
        body.append(f"<tr style='{style}'><td style='padding:.35rem .6rem;border-bottom:1px solid #eef2f7'>{prefix}{html.escape(label)}"
                    f"<div style='font-size:var(--fs-xs);color:#94a3b8;font-weight:400'>{html.escape(note)}</div></td>"
                    f"<td style='padding:.35rem .6rem;border-bottom:1px solid #eef2f7;text-align:right;white-space:nowrap'>{cell(kind, value)}</td>"
                    f"<td style='padding:.35rem .6rem;border-bottom:1px solid #eef2f7;text-align:right;white-space:nowrap;background:#f0fdf4'>{cell(kind, after.get(label)) if rec is not None else '–'}</td></tr>")
    head = ("<tr style='background:#f1f5f9'><th style='text-align:left;padding:.45rem .6rem'>Komponen per unit</th>"
            "<th style='text-align:right;padding:.45rem .6rem;color:#1e3a8a'>Sekarang</th>"
            "<th style='text-align:right;padding:.45rem .6rem;color:#14532d;background:#dcfce7'>Rekomendasi</th></tr>")
    return ("<div style='border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;background:#fff'>"
            f"<table style='width:100%;border-collapse:collapse;font-size:var(--fs-base)'><thead>{head}</thead><tbody>{''.join(body)}</tbody></table></div>")


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
    # Harga, voucher, dan iklan diambil dari data (sama dengan Ringkasan); yang bisa diatur hanya program Shopee & pengaturan biaya.
    harga, iklan, diskon, voucher = harga0, iklan0, 0.0, voucher0
    with left:
        with st.container(border=True):
            chip = ("<div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:.4rem .6rem'>"
                    "<div style='font-size:var(--fs-xs);color:#64748b;font-weight:600'>{0}</div><div style='font-weight:800'>{1}</div>"
                    "<div style='font-size:var(--fs-xs);color:#94a3b8'>{2}</div></div>")
            st.markdown(
                "<div style='font-weight:800;margin-bottom:.4rem'>Data SKU</div>"
                "<div style='display:grid;grid-template-columns:repeat(3,1fr);gap:.4rem;margin-bottom:.2rem'>"
                + chip.format("Harga transaksi", fmt_idr(harga0), "rata-rata periode, setelah diskon" if base_row is not None else "harga data produk")
                + chip.format("Voucher penjual", fmt_idr(voucher0), "rata-rata per unit")
                + chip.format("Iklan per unit", fmt_idr(iklan0), f"ROAS {fmt_num(roas, 1)}" if roas else "data iklan ÷ QTY bersih")
                + "</div>", unsafe_allow_html=True)
            sim_programs = {k: dict(v) for k, v in programs.items()}
            fixed = [k for k, v in programs.items() if v.get("wajib")]
            optional = [k for k, v in programs.items() if not v.get("wajib")]
            st.markdown("<div style='font-weight:800;margin:.6rem 0 .3rem'>Program Shopee</div>", unsafe_allow_html=True)
            if fixed:
                st.markdown(
                    "<div style='display:flex;flex-wrap:wrap;gap:.3rem;margin-bottom:.4rem'>"
                    + "".join(f"<span style='background:#f1f5f9;border:1px solid #e2e8f0;border-radius:999px;padding:.15rem .6rem;font-size:var(--fs-xs)'>"
                              f"🔒 {html.escape(programs[k]['label'].replace(' (ukuran biasa)', ''))} {fmt_num(programs[k]['pct'], 2)}%</span>" for k in fixed)
                    + "</div>", unsafe_allow_html=True)
            cols = st.columns(2)
            for i, key in enumerate(optional):
                prog = programs[key]
                cap = f" · maks {fmt_idr(prog['cap'])}" if prog.get("cap") else ""
                with cols[i % 2]:
                    sim_programs[key]["on"] = st.toggle(prog["label"].replace(" (ukuran biasa)", ""), value=bool(prog.get("on")), key=f"calc-prog-{key}-{sku}",
                                                        help=f"Tarif {fmt_num(prog['pct'], 2)}%{cap}")
            st.markdown("<div style='font-weight:800;margin:.6rem 0 .3rem'>Pengaturan lain</div>", unsafe_allow_html=True)
            o1, o2 = st.columns(2)
            big = o1.toggle("Barang ukuran khusus", value=_is_big(product["product_name"]), key=f"calc-big-{sku}",
                            help="Tarif Gratis Ongkir ukuran khusus. Otomatis aktif untuk produk bertanda PACKING KAYU")
            aff_on = o2.toggle(f"Via affiliate ({fmt_num(aff_pct, 1)}%)", value=False, key=f"calc-aff-{sku}")
            o3, o4 = st.columns([1, 2])
            qty_order = float(o3.number_input("Unit per pesanan", 1, 100, 1, key=f"calc-qty-{sku}", help="Biaya Proses Pesanan dibagi ke jumlah unit ini"))
            pick = o4.selectbox(
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
            st.markdown("<div class='field-hint'>Program yang diubah di sini hanya untuk simulasi; bawaan semua SKU diatur di ⚙️ Parameter biaya.</div>", unsafe_allow_html=True)
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
    aff_rp = base * aff_pct / 100 if aff_on else 0.0

    from src.core import pricing

    pl, rec = None, None
    if known:
        h = (hist or {}).get(str(sku)) or {}
        normal = float(h.get("harga_awal") or 0) or harga
        pl = pricing.plan(inp, normal=normal, target_pct=target, hist_disc=float(h.get("diskon_median", np.nan) or np.nan),
                          hist_share=float(h.get("porsi_promo", 0) or 0))
        if np.isfinite(pl["harga_disarankan"]) and np.isfinite(pl["harga_promo"]):
            rec = replace(inp, harga=pl["harga_disarankan"], diskon=pl["harga_disarankan"] - pl["harga_promo"])

    with right:
        st.markdown(_result_card("MARGIN BERSIH PER UNIT · SEKARANG", inp, value, pct, target, known, iklan=iklan, aff_rp=aff_rp), unsafe_allow_html=True)
        if rec is not None:
            r_value, r_pct = fee.margin(rec)
            st.markdown(_recommend_card(rec, pl, r_value, r_pct, target), unsafe_allow_html=True)
        elif not known:
            st.info("Modal SKU ini belum diketahui (tidak ada di file harga beli maupun file margin), jadi rekomendasi harga belum bisa dihitung.")

    st.markdown("<div style='font-weight:800;font-size:var(--fs-lg);margin:.9rem 0 .35rem'>Kalkulator lengkap · sekarang vs rekomendasi</div>",
                unsafe_allow_html=True)
    st.markdown(_calc_table(inp, rec, sumber=sumber, roas=roas, admin_pct=admin_pct, known=known), unsafe_allow_html=True)
    notes = []
    if pl is not None:
        h = (hist or {}).get(str(sku)) or {}
        notes.append(f"Histori 90 hari: {fmt_pct(h.get('porsi_promo', 0), 0)} dari {fmt_num(h.get('transaksi', 0))} transaksi memakai promo, "
                     f"diskon median {fmt_pct(h.get('diskon_median', 0), 0)}, maks. {fmt_pct(h.get('diskon_maks', 0), 0)}" if h else "Belum ada histori harga awal di transaksi")
        notes.append(f"Harga minimal tidak rugi {fmt_idr(pl['harga_impas'])} · harga sehat (margin ≥ {fmt_pct(target, 1)}) {fmt_idr(pl['harga_sehat'])}")
        if pl["catatan"]:
            notes.append(pl["catatan"][0].upper() + pl["catatan"][1:])
    todo = fee.fixes(inp, 0.0 if pct < 0 else target) if known else []
    if todo:
        notes.append("Tanpa ubah harga: " + "; ".join(t[0].lower() + t[1:] for t in todo[:3]))
    if notes:
        st.markdown("<ul style='margin:.5rem 0 0 1.1rem;padding:0;color:#475569;font-size:var(--fs-sm);line-height:1.65'>"
                    + "".join(f"<li>{html.escape(n)}</li>" for n in notes) + "</ul>", unsafe_allow_html=True)
