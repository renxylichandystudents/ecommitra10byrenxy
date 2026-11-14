"""Analisa asal pesanan per provinsi dan kota/kabupaten (tab Data)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.ui.common import batched_view, card, download_excel, explain, fmt_num, fmt_pct, range_label
from src.utils.format import show_table


@st.fragment
def show_region_analysis(source_raw: pd.DataFrame, start=None, end=None) -> None:
    """Asal pesanan per provinsi dan kota/kabupaten, dengan filter bulan sendiri (satu, beberapa, atau semua bulan)."""
    from src.activity import region_lines, region_summary, region_total_row

    st.subheader("Asal pesanan per provinsi & kota/kabupaten")
    lines = region_lines(source_raw)
    if lines.empty:
        st.info("Data transaksi belum memuat kolom Provinsi dan Kota/Kabupaten. Unggah laporan pesanan Shopee lengkap agar analisa wilayah tampil.")
        return
    stamp = pd.to_datetime(lines["order_time"], errors="coerce")
    lo, hi = stamp.min().date(), stamp.max().date()
    start = max(pd.Timestamp(start).date(), lo) if start is not None else lo
    end = min(pd.Timestamp(end).date(), hi) if end is not None else hi
    st.caption(f"Ikut periode data di atas: {range_label(start, end)}.")
    level = st.segmented_control("Tampilkan per", ["Provinsi", "Kota/Kabupaten"], default="Provinsi", key="region-level") or "Provinsi"
    view = lines.loc[stamp.dt.normalize().between(pd.Timestamp(start), pd.Timestamp(end))]
    period_text = "semua data" if (start, end) == (lo, hi) else range_label(start, end)
    prov = region_summary(view, "province")
    city = region_summary(view, "city")
    totals = region_total_row(prov, "Provinsi").iloc[0]
    st.info(
        f"Periode {period_text}: pesanan **batal** ({fmt_num(totals['Invoice batal'])} invoice) dan **retur penuh** "
        f"({fmt_num(totals['Invoice retur penuh'])} invoice), serta pesanan **Belum Bayar** ({fmt_num(totals['Invoice Belum Bayar'])} invoice), "
        "**dikeluarkan** dari Invoice bersih; nilai batal, Belum Bayar, dan unit retur dikeluarkan dari QTY bersih dan Sales bersih. Jumlahnya tetap terlihat di kolomnya masing-masing.",
        icon=":material/info:",
    )
    cols = st.columns(4)
    card(
        cols[0],
        "Invoice bersih",
        fmt_num(totals["Invoice bersih"]),
        hint=f"dari {fmt_num(totals['Invoice total'])} invoice · tanpa {fmt_num(totals['Invoice batal'])} batal, {fmt_num(totals['Invoice retur penuh'])} retur penuh "
             f"& {fmt_num(totals['Invoice Belum Bayar'])} Belum Bayar",
    )
    card(cols[1], "Jumlah provinsi", fmt_num(len(prov)), hint=f"{fmt_num(len(city))} kota/kabupaten")
    if not prov.empty:
        top = prov.iloc[0]
        card(cols[2], "Provinsi terbanyak", str(top["Provinsi"]), hint=f"{fmt_num(top['Invoice bersih'])} invoice bersih · {fmt_pct(top['Kontribusi invoice bersih'])}")
    if not city.empty:
        top_city = city.iloc[0]
        card(cols[3], "Kota/kabupaten terbanyak", str(top_city["Kota/Kabupaten"]), hint=f"{top_city['Provinsi']} · {fmt_num(top_city['Invoice bersih'])} invoice bersih")
    table = prov if level == "Provinsi" else city
    name_col = "Provinsi" if level == "Provinsi" else "Kota/Kabupaten"
    if not table.empty:
        top10 = table.head(10).iloc[::-1]
        fig = go.Figure(
            go.Bar(
                x=top10["Invoice bersih"],
                y=top10[name_col],
                orientation="h",
                marker_color="#ee4d2d",
                text=[f"{fmt_num(v)} · {fmt_pct(p)}" for v, p in zip(top10["Invoice bersih"], top10["Kontribusi invoice bersih"])],
                textposition="outside",
                hovertemplate="%{y}<br>%{x} invoice bersih<extra></extra>",
            )
        )
        fig.update_layout(
            title=f"10 {name_col.lower()} dengan invoice bersih terbanyak · {period_text}",
            height=360, margin=dict(l=10, r=40, t=50, b=10), font=dict(family="Plus Jakarta Sans"),
            xaxis_title="Invoice bersih (tanpa batal, Belum Bayar & retur penuh)", yaxis_title=None, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True, key="region-chart")
    explain(
        [
            ("Invoice bersih", "No. Pesanan unik selain batal, Belum Bayar, dan retur penuh (sama dengan kartu Pesanan bersih)"),
            ("Definisi", "sama dengan kartu di atas (Pesanan bersih, Sales bersih), jadi baris Total = kartu untuk periode yang sama"),
            ("Invoice batal / retur penuh / Belum Bayar", "pesanan yang dikeluarkan dari Invoice bersih; % dihitung terhadap Invoice total. "
             "Pesanan yang hanya sebagian barangnya diretur tetap dihitung bersih"),
            ("Invoice total", "semua No. Pesanan dari wilayah itu = bersih + batal + retur penuh + Belum Bayar"),
            ("Sales bersih", "Total Pembayaran pesanan selain batal & Belum Bayar (sudah dipotong voucher, sekali per pesanan) − nilai unit retur; "
             "dasar yang sama dengan target. Berbeda dari sales produk di tab Prediksi (Harga Setelah Diskon × QTY, sebelum voucher)"),
            ("QTY bersih", "unit pesanan selain batal & Belum Bayar dikurangi unit retur"),
            ("Kontribusi invoice / sales bersih", "bagian wilayah dari seluruh invoice bersih (jumlah pesanan) / dari seluruh sales bersih (rupiah)"),
            ("Baris Total", "di paling atas tabel, menjumlahkan semua wilayah pada periode yang dipilih"),
        ]
    )
    shown = table.copy()
    total_row = region_total_row(table, name_col)
    batched_view(
        len(shown),
        key=f"region-{level}",
        render=lambda lo, hi: show_table(
            pd.concat([total_row, shown.iloc[lo:hi]], ignore_index=True),
            bold_label="Total",
            kinds={
                "Rank": "count", "Invoice bersih": "count", "Invoice batal": "count", "Invoice retur penuh": "count", "Invoice Belum Bayar": "count", "Invoice total": "count",
                "% batal": "pct", "% retur penuh": "pct", "QTY bersih": "count", "Sales bersih": "money", "Kontribusi invoice bersih": "pct", "Kontribusi sales bersih": "pct",
            },
        ),
        noun=name_col.lower(),
        fragment=False,
        rerun_scope="fragment",
        download=lambda: download_excel(
            {
                "Per provinsi": pd.concat([region_total_row(prov, "Provinsi"), prov], ignore_index=True),
                "Per kota-kabupaten": pd.concat([region_total_row(city, "Kota/Kabupaten"), city], ignore_index=True),
            },
            f"asal_pesanan_{start:%Y%m%d}_{end:%Y%m%d}.xlsx",
            key="xl-region",
            label="Unduh Excel (provinsi & kota)",
        ),
    )
