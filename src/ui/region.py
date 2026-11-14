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
        f"Periode {period_text}: pesanan **batal** ({fmt_num(totals['Invoice batal'])} invoice) dan **retur** "
        f"({fmt_num(totals['Invoice retur'])} invoice), serta pesanan **Belum Bayar** ({fmt_num(totals['Invoice Belum Bayar'])} invoice), "
        "**dikeluarkan** dari Invoice bersih, QTY bersih, dan Sales produk bersih. Jumlahnya tetap terlihat di kolomnya masing-masing.",
        icon=":material/info:",
    )
    cols = st.columns(4)
    card(
        cols[0],
        "Invoice bersih",
        fmt_num(totals["Invoice bersih"]),
        hint=f"dari {fmt_num(totals['Invoice total'])} invoice · tanpa {fmt_num(totals['Invoice batal'])} batal, {fmt_num(totals['Invoice retur'])} retur "
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
            xaxis_title="Invoice bersih (tanpa batal & retur)", yaxis_title=None, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True, key="region-chart")
    explain(
        [
            ("Invoice bersih", "No. Pesanan unik yang tidak batal dan tidak retur"),
            ("Invoice batal / retur / Belum Bayar", "pesanan yang dikeluarkan dari angka bersih; % batal dan % retur dihitung terhadap Invoice total"),
            ("Invoice total", "semua No. Pesanan dari wilayah itu = bersih + batal + retur + Belum Bayar"),
            ("QTY bersih & Sales produk bersih", "unit yang tidak batal / Belum Bayar dikurangi unit retur; sales produk = Harga Setelah Diskon × QTY "
             "(sama dengan tabel Prediksi). Pesanan retur sebagian tetap menyumbang unit yang tidak diretur"),
            ("Kontribusi invoice bersih", "invoice bersih wilayah ÷ seluruh invoice bersih pada periode yang dipilih (jumlah pesanan)"),
            ("Kontribusi sales bersih", "sales produk bersih wilayah ÷ seluruh sales produk bersih (nilai rupiah); bisa berbeda dari kontribusi invoice "
             "bila nilai pesanan per wilayah berbeda"),
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
                "Rank": "count", "Invoice bersih": "count", "Invoice batal": "count", "Invoice retur": "count", "Invoice Belum Bayar": "count", "Invoice total": "count",
                "% batal": "pct", "% retur": "pct", "QTY bersih": "count", "Sales produk bersih": "money", "Kontribusi invoice bersih": "pct", "Kontribusi sales bersih": "pct",
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
