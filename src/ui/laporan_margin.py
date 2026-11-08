"""Setting › Laporan margin: item margin rendah vs tinggi dan yang perlu segera ditindaklanjuti (dari File margin)."""

from __future__ import annotations

import html

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.core import margin_file as mf
from src.core import margin_report
from src.core import shopee_fee as fee
from src.ui.common import batched_view, card, download_excel, fmt_idr, fmt_num, fmt_pct
from src.utils.format import show_table

ICON = {"Rugi": "🔴 Rugi", "Rendah": "🟠 Rendah", "Tinggi": "🟢 Tinggi", "Data tidak wajar": "⚪ Data tidak wajar"}
COLOR = {"Rugi": "#dc2626", "Rendah": "#f59e0b", "Tinggi": "#16a34a", "Data tidak wajar": "#94a3b8"}
KINDS = {"Penjualan": "money", "Margin kotor": "money", "Margin bersih": "money", "Rugi": "money", "Kurang dari rata-rata": "money",
         "Margin kotor (%)": "pct", "Margin di file (%)": "pct", "Potongan Shopee (%)": "pct", "Iklan (%)": "pct", "Margin bersih (%)": "pct",
         "Margin nasional (%)": "pct", "Selisih vs nasional (poin)": "dec", "Margin kotor periode lalu (%)": "pct", "No": "count",
         "Jumlah item": "count", "Porsi penjualan (%)": "pct"}


def _inputs(features, table: pd.DataFrame, data, keys: list[str], file_names: dict[str, str]):
    """Harga, biaya admin kategori, nama, iklan per unit, barang besar per sku_key."""
    from src.ui.feature_data import product_frame
    from src.ui.kalkulator import KEY_SKU_CAT, _category_fees, _programs

    products = product_frame(table).drop_duplicates("sku") if isinstance(table, pd.DataFrame) and not table.empty else pd.DataFrame(columns=["sku", "product_name", "price"])
    products = products.assign(key=products["sku"].map(mf.sku_key)).drop_duplicates("key").set_index("key")
    fees = _category_fees(features)
    sku_cat = features.get_json(KEY_SKU_CAT, {}) or {}
    programs, order_fee, _ = _programs(features)
    price, admin, names, ads, big = {}, {}, {}, {}, set()
    ad_map = {mf.sku_key(k): v for k, v in (getattr(data, "ad_per_unit", {}) or {}).items()}
    for key in keys:
        name = str(products.loc[key, "product_name"]) if key in products.index else file_names.get(key, "")
        sku = str(products.loc[key, "sku"]) if key in products.index else key
        names[key] = name
        price[key] = float(products.loc[key, "price"]) if key in products.index else 0.0
        admin[key] = fee.admin_for(sku, name, fees, sku_cat)[1]
        ads[key] = float(ad_map.get(key, 0.0) or 0.0)
        if "packing kayu" in name.lower():
            big.add(key)
    return price, admin, names, ads, big, programs, order_fee


def _view(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    full = pd.DataFrame({
        "No": range(1, len(frame) + 1), "Status": frame["status"].map(ICON), "SKU": frame["sku"], "Nama": frame["nama"],
        "Tindak lanjut": frame["tindak_lanjut"], "Penjualan": frame["penjualan"], "Margin kotor": frame["kotor_rp"],
        "Margin kotor (%)": frame["kotor_pct"], "Potongan Shopee (%)": frame["shopee_pct"], "Iklan (%)": frame["iklan_pct"],
        "Margin bersih": frame["bersih_rp"], "Margin bersih (%)": frame["bersih_pct"], "Rugi": frame["rugi_rp"],
        "Kurang dari rata-rata": frame["kurang_rp"], "Margin nasional (%)": frame["nasional_pct"],
        "Selisih vs nasional (poin)": frame["selisih_nasional"], "Margin kotor periode lalu (%)": frame["kotor_lalu_pct"],
        "Margin di file (%)": frame["kotor_file_pct"], "Catatan": frame["catatan"],
    }).reset_index(drop=True)
    return full[columns]


def _with_total(view: pd.DataFrame) -> pd.DataFrame:
    total = {c: np.nan for c in view.columns}
    total.update({c: "" for c in view.columns if view[c].dtype == object})
    total["Status"] = "Total"
    if "SKU" in view.columns:
        total["SKU"] = f"{fmt_num(len(view))} item"
    for c in ("Penjualan", "Margin kotor", "Margin bersih", "Rugi", "Kurang dari rata-rata"):
        if c in view.columns:
            total[c] = view[c].sum()
    sales = view["Penjualan"].sum() if "Penjualan" in view.columns else 0
    if sales:
        if "Margin kotor (%)" in view.columns and "Margin kotor" in view.columns:
            total["Margin kotor (%)"] = view["Margin kotor"].sum() / sales * 100
        if "Margin bersih (%)" in view.columns and "Margin bersih" in view.columns:
            total["Margin bersih (%)"] = view["Margin bersih"].sum() / sales * 100
    total["No"] = np.nan
    return pd.concat([pd.DataFrame([total]), view], ignore_index=True)


def _paged(view: pd.DataFrame, key: str, filename: str, *, wide: str = "Tindak lanjut") -> None:
    if view.empty:
        st.info("Tidak ada item pada kelompok ini.")
        return
    full = _with_total(view)
    config = {wide: st.column_config.TextColumn(width="large")} if wide in view.columns else None
    batched_view(
        len(view), key=key, noun="item",
        render=lambda lo, hi: show_table(pd.concat([full.iloc[:1], full.iloc[1:].iloc[lo:hi]], ignore_index=True), bold_label="Total",
                                         kinds=KINDS, max_height=10_000, column_config=config),
        download=lambda: download_excel(full, filename, key=f"xl-{key}"),
    )


def _scatter(report: pd.DataFrame, acuan: float) -> None:
    fig = go.Figure()
    for status in ("Tinggi", "Rendah", "Rugi"):
        part = report.loc[report["status"] == status]
        if part.empty:
            continue
        fig.add_trace(go.Scatter(
            x=part["penjualan"], y=part["bersih_pct"], mode="markers", name=status,
            marker={"color": COLOR[status], "size": 8, "opacity": 0.75, "line": {"width": 0}},
            customdata=np.stack([part["sku"], part["nama"].str.slice(0, 50), part["bersih_rp"]], axis=-1),
            hovertemplate="<b>%{customdata[0]}</b> %{customdata[1]}<br>Penjualan Rp%{x:,.0f}<br>Margin bersih %{y:.1f}% (Rp%{customdata[2]:,.0f})<extra></extra>",
        ))
    if np.isfinite(acuan):
        fig.add_hline(y=acuan, line_dash="dot", line_color="#64748b", annotation_text=f"batas margin rendah {acuan:.1f}%".replace(".", ","), annotation_position="top left")
    fig.add_hline(y=0, line_color="#dc2626", line_width=1)
    fig.update_layout(
        height=330, margin={"l": 10, "r": 10, "t": 30, "b": 10}, legend={"orientation": "h", "y": 1.12, "x": 0},
        xaxis={"title": "Penjualan periode (Rp, skala log)", "type": "log", "separatethousands": True},
        yaxis={"title": "Margin bersih (%)", "range": [max(float(report["bersih_pct"].quantile(0.02)) - 5, -60), min(float(report["bersih_pct"].quantile(0.98)) + 5, 80)]},
        separators=",.", plot_bgcolor="#fff",
    )
    fig.update_xaxes(gridcolor="#f1f5f9")
    fig.update_yaxes(gridcolor="#f1f5f9", zeroline=False)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def show_margin_report(features, table: pd.DataFrame, data, *, username: str, may_edit: bool, require) -> None:
    from src.ui.margin_data import load_margin, periods, upload_card

    st.markdown(
        "<div style='margin-bottom:.2rem'><span style='font-size:1.15rem;font-weight:800'>Laporan margin Shopee</span>"
        "<span style='color:#64748b;font-size:.9rem'> · item margin rendah & tinggi, dan yang perlu segera ditindaklanjuti</span></div>",
        unsafe_allow_html=True,
    )
    upload_card(features, username=username, may_edit=may_edit, require=require, key="report-margin")
    options = periods(features)
    if not options:
        st.info("Unggah file margin (sheet Margin Shopee, dan Margin Nasional sebagai pembanding) untuk menampilkan laporan.")
        return
    c1, _c2 = st.columns([1, 2])
    chosen = c1.selectbox("Periode", options, key="report-margin-period", help="Periode tersimpan, terbaru di atas.")
    md = load_margin(features, chosen)
    if md.shopee.empty:
        st.warning(f"Periode {chosen} tidak memiliki sheet Margin Shopee; laporan butuh data penjualan Shopee.")
        return
    idx = options.index(chosen)
    previous = load_margin(features, options[idx + 1]).shopee if idx + 1 < len(options) else None
    keys = md.shopee["sku"].astype(str).tolist()
    price, admin, names, ads, big, programs, order_fee = _inputs(features, table, data, keys, dict(zip(md.shopee["sku"], md.shopee["nama"])))
    report = margin_report.build(md.shopee, md.nasional, previous, price=price, admin=admin, names=names, ad_unit=ads,
                                 programs=programs, order_fee=order_fee, big=big)
    if report.empty:
        st.info("Tidak ada item terjual di sheet Shopee periode ini.")
        return
    acuan, overall = report.attrs["acuan_pct"], report.attrs["overall_pct"]
    ok = report.loc[report["status"] != "Data tidak wajar"]
    sales, kotor, bersih = float(ok["penjualan"].sum()), float(ok["kotor_rp"].sum()), float(ok["bersih_rp"].sum())
    rugi = report.loc[report["status"] == "Rugi"]
    low = report.loc[report["status"] == "Rendah"]
    high = report.loc[report["status"] == "Tinggi"]
    odd = report.loc[report["status"] == "Data tidak wajar"]
    prev_pct = mf.store_average(previous) if previous is not None else float("nan")
    k = st.columns(4)
    card(k[0], f"Penjualan Shopee · {chosen}", fmt_idr(sales), hint=f"{fmt_num(len(ok))} item · termasuk pajak")
    card(k[1], "Margin kotor", fmt_idr(kotor), hint=f"{fmt_pct(kotor / sales * 100 if sales else 0, 1)} dari penjualan"
         + (f" · periode lalu {fmt_pct(prev_pct, 1)}" if np.isfinite(prev_pct) else ""))
    card(k[2], "Estimasi margin bersih", fmt_idr(bersih), hint=f"{fmt_pct(overall, 1)} setelah potongan Shopee & iklan")
    card(k[3], "Perlu segera ditindaklanjuti", fmt_num(len(rugi) + len(low)),
         hint=f"{fmt_num(len(rugi))} rugi ({fmt_idr(float(rugi['rugi_rp'].sum()))}) · {fmt_num(len(low))} untung di bawah {fmt_pct(acuan, 1)}")

    # Ringkasan per status + sebaran
    left, right = st.columns([1, 1.25])
    with left:
        st.markdown("<div class='section-title'>Ringkasan per status</div>", unsafe_allow_html=True)
        summary = []
        for status in ("Rugi", "Rendah", "Tinggi", "Data tidak wajar"):
            part = report.loc[report["status"] == status]
            if part.empty:
                continue
            summary.append({"Status": ICON[status], "Jumlah item": len(part), "Penjualan": part["penjualan"].sum(),
                            "Porsi penjualan (%)": part["penjualan"].sum() / report["penjualan"].sum() * 100,
                            "Margin kotor": part["kotor_rp"].sum(), "Margin bersih": part["bersih_rp"].sum()})
        frame = pd.DataFrame(summary)
        show_table(frame, kinds=KINDS, max_height=10_000)
        steps = []
        if len(rugi):
            steps.append(f"<b>Hentikan kerugian {fmt_num(len(rugi))} item rugi</b> — 5 teratas menyumbang {fmt_idr(float(rugi.head(5)['rugi_rp'].sum()))}.")
        if len(low):
            steps.append(f"<b>Naikkan {fmt_num(len(low))} item margin rendah</b> ke {fmt_pct(acuan, 1)} — potensi +{fmt_idr(float(low['kurang_rp'].sum()))} per periode.")
        below_nas = report.loc[report["selisih_nasional"] <= -margin_report.GAP_NASIONAL_PP]
        if len(below_nas):
            steps.append(f"<b>{fmt_num(len(below_nas))} item</b> margin kotor Shopee-nya ≥ {fmt_num(margin_report.GAP_NASIONAL_PP, 0)} poin di bawah nasional: tinjau harga & diskon Shopee.")
        if len(high):
            top = ", ".join(html.escape(str(n)[:30]) for n in high.head(3)["nama"])
            steps.append(f"<b>Dorong item margin tinggi</b> beromzet besar (iklan, flash sale, exposure): {top}.")
        if len(odd):
            steps.append(f"<b>Cek {fmt_num(len(odd))} item</b> dengan data margin tidak wajar ke tim finance.")
        if steps:
            st.markdown(
                "<div style='border:1px solid #e2e8f0;border-left:4px solid #ee4d2d;border-radius:12px;background:#fff;padding:.6rem .9rem;margin-top:.5rem'>"
                "<div style='font-weight:700;margin-bottom:.2rem'>Yang perlu dilakukan</div><ol style='margin:0 0 0 1.1rem;padding:0;line-height:1.55;font-size:.9rem'>"
                + "".join(f"<li>{s}</li>" for s in steps) + "</ol></div>",
                unsafe_allow_html=True,
            )
    with right:
        st.markdown("<div class='section-title'>Sebaran item: penjualan vs margin bersih</div>", unsafe_allow_html=True)
        _scatter(ok, acuan)

    with st.expander("Cara membaca laporan ini"):
        st.markdown(
            f"- **Sumber**: sheet Margin Shopee periode {html.escape(chosen)} (penjualan yang sudah terjadi). Margin di file = Gross Margin ÷ Sales Exclude Tax; "
            "di aplikasi margin dihitung dari **penjualan termasuk pajak** (harga yang dipotong Shopee), jadi angkanya sedikit lebih kecil.\n"
            "- **Margin bersih** = margin kotor − potongan Shopee (administrasi kategori + program Shopee Mall + proses pesanan, estimasi dari Kalkulator biaya) "
            "− iklan (data iklan terakhir). Ini estimasi, bukan laporan keuangan.\n"
            f"- **Status**: 🔴 Rugi = margin bersih di bawah 0 · 🟠 Rendah = untung tetapi di bawah {fmt_pct(acuan, 1)} (rata-rata margin bersih item yang untung) · 🟢 Tinggi = sama/di atas batas itu · "
            "⚪ Data tidak wajar = margin di file di luar −100%…95%.\n"
            "- **Urutan prioritas**: Rugi dari kerugian Rp terbesar → Rendah dari kekurangan Rp terbesar ke batas → Tinggi dari margin Rp terbesar.\n"
            "- **Margin nasional** = margin kotor item yang sama di semua kanal (sheet Margin Nasional), untuk melihat apakah harga di Shopee lebih rendah."
        )

    st.markdown("<div class='section-title'>Daftar item</div>", unsafe_allow_html=True)
    f1, f2 = st.columns([1.2, 1.8])
    group = f1.segmented_control("Kelompok", ["Perlu ditindaklanjuti", "Margin tinggi", "Shopee vs nasional", "Semua item"],
                                 default="Perlu ditindaklanjuti", key="report-margin-group", label_visibility="collapsed") or "Perlu ditindaklanjuti"
    query = f2.selectbox("Cari SKU", [f"{s} · {n}" for s, n in zip(report["sku"], report["nama"])], index=None, key="report-margin-q",
                         placeholder="Cari SKU atau nama produk…", label_visibility="collapsed")
    base = report.loc[report["sku"] == str(query).split(" · ")[0]] if query else report
    main = ["No", "Status", "SKU", "Nama", "Tindak lanjut", "Penjualan", "Margin kotor (%)", "Potongan Shopee (%)", "Iklan (%)", "Margin bersih (%)", "Margin bersih"]
    if group == "Perlu ditindaklanjuti":
        part = base.loc[base["status"].isin(["Rugi", "Rendah"])]
        st.caption(f"Rugi dulu (kerugian Rp terbesar), lalu margin rendah (kekurangan Rp terbesar ke batas {fmt_pct(acuan, 1)}).")
        _paged(_view(part, main + ["Rugi", "Kurang dari rata-rata", "Margin nasional (%)", "Margin kotor periode lalu (%)"]), "report-act", "margin_perlu_tindak_lanjut.xlsx")
    elif group == "Margin tinggi":
        part = base.loc[base["status"] == "Tinggi"].sort_values("bersih_rp", ascending=False)
        st.caption("Urut margin bersih Rp terbesar: kandidat utama untuk didorong penjualannya.")
        _paged(_view(part, main + ["Margin nasional (%)", "Margin kotor periode lalu (%)"]), "report-high", "margin_tinggi.xlsx")
    elif group == "Shopee vs nasional":
        part = base.loc[base["selisih_nasional"].notna()].sort_values("selisih_nasional")
        st.caption("Urut selisih terbesar: margin kotor Shopee jauh di bawah nasional berarti harga/diskon di Shopee perlu ditinjau.")
        _paged(_view(part, ["No", "Status", "SKU", "Nama", "Penjualan", "Margin kotor (%)", "Margin nasional (%)", "Selisih vs nasional (poin)", "Tindak lanjut"]),
               "report-nas", "margin_shopee_vs_nasional.xlsx")
    else:
        _paged(_view(base, main + ["Rugi", "Kurang dari rata-rata", "Margin nasional (%)", "Margin kotor periode lalu (%)", "Margin di file (%)", "Catatan"]),
               "report-all", "laporan_margin_semua_item.xlsx")
