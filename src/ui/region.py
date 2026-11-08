"""Analisa asal pesanan per provinsi dan kota/kabupaten (tab Data)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.ui.common import batched_view, card, download_excel, explain, fmt_num, fmt_pct, month_label
from src.utils.format import show_table


@st.fragment
def show_region_analysis(source_raw: pd.DataFrame) -> None:
    """Asal pesanan per provinsi dan kota/kabupaten, dengan filter bulan sendiri (satu, beberapa, atau semua bulan)."""
    from src.activity import region_lines, region_summary

    st.subheader("Asal pesanan per provinsi & kota/kabupaten")
    lines = region_lines(source_raw)
    if lines.empty:
        st.info("Data transaksi belum memuat kolom Provinsi dan Kota/Kabupaten. Unggah laporan pesanan Shopee lengkap agar analisa wilayah tampil.")
        return
    months = sorted(lines["month"].unique())
    labels = {m: month_label(m) for m in months}
    f1, f2, f3 = st.columns([2.6, 1.1, 1.3], vertical_alignment="bottom")
    all_months = f2.toggle("Semua bulan", value=False, key="region-all")
    chosen = f1.multiselect(
        "Periode (pilih satu atau beberapa bulan)",
        options=months,
        default=[months[-1]],
        format_func=labels.get,
        key="region-months",
        disabled=all_months,
        placeholder="Pilih bulan",
    )
    level = f3.segmented_control("Tampilkan per", ["Provinsi", "Kota/Kabupaten"], default="Provinsi", key="region-level") or "Provinsi"
    picked = months if all_months else (chosen or [months[-1]])
    view = lines.loc[lines["month"].isin(picked)]
    period_text = "semua bulan" if all_months else ", ".join(labels[m] for m in sorted(picked))
    prov = region_summary(view, "province")
    city = region_summary(view, "city")
    invoices = int(view["order_id"].nunique())
    cols = st.columns(4)
    card(cols[0], "Invoice", fmt_num(invoices), hint=period_text)
    card(cols[1], "Jumlah provinsi", fmt_num(len(prov)), hint=f"{fmt_num(len(city))} kota/kabupaten")
    if not prov.empty:
        top = prov.iloc[0]
        card(cols[2], "Provinsi terbanyak", str(top["Provinsi"]), hint=f"{fmt_num(top['Invoice'])} invoice · {fmt_pct(top['Kontribusi invoice'])}")
    if not city.empty:
        top_city = city.iloc[0]
        card(cols[3], "Kota/kabupaten terbanyak", str(top_city["Kota/Kabupaten"]), hint=f"{top_city['Provinsi']} · {fmt_num(top_city['Invoice'])} invoice")
    table = prov if level == "Provinsi" else city
    name_col = "Provinsi" if level == "Provinsi" else "Kota/Kabupaten"
    if not table.empty:
        top10 = table.head(10).iloc[::-1]
        fig = go.Figure(
            go.Bar(
                x=top10["Invoice"],
                y=top10[name_col],
                orientation="h",
                marker_color="#ee4d2d",
                text=[f"{fmt_num(v)} · {fmt_pct(p)}" for v, p in zip(top10["Invoice"], top10["Kontribusi invoice"])],
                textposition="outside",
                hovertemplate="%{y}<br>%{x} invoice<extra></extra>",
            )
        )
        fig.update_layout(
            title=f"10 {name_col.lower()} dengan invoice terbanyak · {period_text}",
            height=360, margin=dict(l=10, r=40, t=50, b=10), font=dict(family="Plus Jakarta Sans"),
            xaxis_title="Invoice", yaxis_title=None, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True, key="region-chart")
    explain(
        [
            ("Invoice", "No. Pesanan unik dari wilayah itu pada periode yang dipilih, termasuk yang batal"),
            ("QTY terjual & Sales value", "hanya pesanan yang tidak batal; sales value = harga setelah diskon × QTY"),
            ("% batal", "invoice batal ÷ invoice wilayah itu"),
            ("Kontribusi invoice", "invoice wilayah ÷ seluruh invoice pada periode yang dipilih"),
            ("Periode", "pilih satu bulan, beberapa bulan sekaligus, atau nyalakan Semua bulan"),
        ]
    )
    shown = table.copy()
    batched_view(
        len(shown),
        key=f"region-{level}",
        render=lambda lo, hi: show_table(
            shown.iloc[lo:hi],
            kinds={"Rank": "count", "Invoice": "count", "Invoice batal": "count", "% batal": "pct", "QTY terjual": "count", "Sales value": "money", "Kontribusi invoice": "pct"},
        ),
        noun=name_col.lower(),
        fragment=False,
        rerun_scope="fragment",
        download=lambda: download_excel(
            {"Per provinsi": prov, "Per kota-kabupaten": city},
            f"asal_pesanan_{'semua_bulan' if all_months else '_'.join(sorted(picked))}.xlsx",
            key="xl-region",
            label="Unduh Excel (provinsi & kota)",
        ),
    )
