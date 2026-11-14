"""Tab Data › Pembayaran, berat & ketepatan kirim."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.core import order_ops as O
from src.ui.common import card, download_excel, explain, fmt_num, fmt_pct, range_label
from src.ui.instant import _orders, _plot
from src.utils.format import show_table

UP, DOWN, MUTED = "#1d4ed8", "#dc2626", "#94a3b8"
KINDS = {"Invoice": "count", "Porsi invoice (%)": "pct", "Lewat kargo (%)": "pct", "% batal": "pct", "% batal belum bayar": "pct", "Sales bersih": "money", "AOV": "money"}


def _rate_bars(frame: pd.DataFrame, label: str, overall: float, key: str, title: str) -> None:
    colors = [DOWN if v > overall else UP for v in frame["% batal"]]
    fig = go.Figure(go.Bar(x=frame[label], y=frame["% batal"], marker_color=colors, text=[fmt_pct(v, 1) for v in frame["% batal"]], textposition="outside",
                           customdata=frame["Invoice"], hovertemplate="%{x}<br>Batal %{y:.1f}%<br>%{customdata} invoice<extra></extra>"))
    fig.add_hline(y=overall, line_dash="dash", line_color=MUTED, annotation_text=f"rata-rata {fmt_pct(overall, 1)}")
    fig.update_layout(title=title, yaxis=dict(title="% invoice batal", range=[0, max(float(frame["% batal"].max()), overall) * 1.2]), showlegend=False)
    _plot(fig, key, 320)


def show_ops_analysis(source_raw: pd.DataFrame, start: date | None, end: date | None) -> None:
    st.subheader("Pembayaran, berat & ketepatan kirim")
    if source_raw is None or source_raw.empty:
        st.write("Belum ada data transaksi.")
        return
    _lines, orders = _orders(source_raw)
    if orders.empty:
        st.info("Laporan pesanan belum memuat kolom yang dibutuhkan (Opsi Pengiriman, Metode Pembayaran, Total Berat).", icon=":material/info:")
        return
    lo, hi = orders["day"].min().date(), orders["day"].max().date()
    start = max(pd.Timestamp(start).date(), lo) if start is not None else lo
    end = min(pd.Timestamp(end).date(), hi) if end is not None else hi
    orders = orders.loc[orders["day"].between(pd.Timestamp(start), pd.Timestamp(end))]
    if orders.empty:
        st.write("Tidak ada pesanan pada periode ini.")
        return
    st.caption(f"{range_label(start, end)} · dari kolom Metode Pembayaran, Total Berat, dan Pesanan Harus Dikirimkan Sebelum pada laporan pesanan. "
               "Ikut periode data di atas.")
    overall = float(orders["cancelled"].mean() * 100)
    pay = O.payment_table(orders)
    weight = O.weight_table(orders)
    pay["AOV"], weight["AOV"] = pay["AOV"].fillna(0.0), weight["AOV"].fillna(0.0)
    ship = O.shipping_summary(orders)
    per_service = O.late_by(orders, "layanan")
    per_day = O.late_by(orders, "hari")

    main_pay = pay.loc[pay["Porsi invoice (%)"] >= 2]
    worst_pay = main_pay.sort_values("% batal", ascending=False).iloc[0] if not main_pay.empty else None
    best_pay = main_pay.sort_values("% batal").iloc[0] if not main_pay.empty else None
    heavy = weight.loc[weight["Berat paket"].isin(O.WEIGHT_LABELS[2:])]
    heavy_rate = float((heavy["% batal"] * heavy["Invoice"]).sum() / heavy["Invoice"].sum()) if not heavy.empty and heavy["Invoice"].sum() else np.nan
    light = weight.loc[weight["Berat paket"] == O.WEIGHT_LABELS[0]]
    light_rate = float(light["% batal"].iloc[0]) if not light.empty else np.nan

    row = st.columns(4)
    if worst_pay is not None:
        card(row[0], "Batal tertinggi per metode bayar", fmt_pct(worst_pay["% batal"], 1),
             hint=f"{worst_pay['Metode pembayaran']} · {fmt_num(worst_pay['Invoice'])} invoice<br>terendah {best_pay['Metode pembayaran']} {fmt_pct(best_pay['% batal'], 1)}")
    card(row[1], "Batal paket ≥ 20 kg", fmt_pct(heavy_rate, 1),
         hint=f"paket < 5 kg {fmt_pct(light_rate, 1)} · <b style='color:{DOWN if heavy_rate > light_rate else UP}'>"
              f"{'lebih tinggi' if heavy_rate > light_rate else 'lebih rendah'} {fmt_num(abs(heavy_rate - light_rate), 1)} poin</b>")
    card(row[2], "Dikirim lewat batas Shopee", fmt_pct(ship["porsi"], 1),
         hint=f"{fmt_num(ship['terlambat'])} dari {fmt_num(ship['dinilai'])} pesanan tidak batal · median telat {fmt_num(ship['median_jam'], 1)} jam")
    worst_service = per_service.loc[per_service["Pesanan dinilai"] >= 20].sort_values("% terlambat", ascending=False)
    if not worst_service.empty:
        w = worst_service.iloc[0]
        card(row[3], "Layanan paling sering telat", fmt_pct(w["% terlambat"], 1), hint=f"{w['Layanan']} · {fmt_num(w['Terlambat'])} dari {fmt_num(w['Pesanan dinilai'])} pesanan")

    c1, c2 = st.columns(2)
    with c1:
        _rate_bars(main_pay if not main_pay.empty else pay, "Metode pembayaran", overall, "ops-pay", "Batal per metode bayar")
    with c2:
        _rate_bars(weight, "Berat paket", overall, "ops-weight", "Batal per berat paket")

    st.caption("Grafik metode bayar hanya menampilkan metode dengan porsi ≥ 2% invoice; biru = di bawah rata-rata batal toko, merah = di atasnya.")
    st.markdown("**Per metode pembayaran**")
    pay_total = O.total_row(orders, "Metode pembayaran")
    show_table(pd.concat([pay_total, pay], ignore_index=True).fillna({"AOV": 0.0}), kinds=KINDS, bold_label="Total")
    st.markdown("**Per berat paket**")
    weight_total = O.total_row(orders, "Berat paket", weight=True)
    unknown = int(orders["weight_kg"].isna().sum())
    if unknown:
        st.caption(f"{fmt_num(unknown)} invoice tanpa Total Berat tidak masuk tabel ini.")
    show_table(pd.concat([weight_total, weight], ignore_index=True).fillna({"AOV": 0.0}), kinds=KINDS, bold_label="Total")

    st.markdown("**Ketepatan kirim** · pesanan tidak batal, Waktu Pengiriman Diatur dibanding Pesanan Harus Dikirimkan Sebelum")
    c1, c2 = st.columns(2)
    with c1:
        show_table(per_service, kinds={"Pesanan dinilai": "count", "Terlambat": "count", "% terlambat": "pct"})
    with c2:
        if not per_day.empty:
            fig = go.Figure(go.Bar(x=per_day["Hari pesanan"], y=per_day["% terlambat"], marker_color=[DOWN if v > ship["porsi"] else UP for v in per_day["% terlambat"]],
                                   text=[fmt_pct(v, 1) for v in per_day["% terlambat"]], textposition="outside"))
            fig.add_hline(y=ship["porsi"], line_dash="dash", line_color=MUTED, annotation_text=f"rata-rata {fmt_pct(ship['porsi'], 1)}")
            fig.update_layout(title="% telat kirim per hari pesanan", yaxis=dict(title="% terlambat", range=[0, float(per_day["% terlambat"].max()) * 1.25 or 1]),
                              showlegend=False)
            _plot(fig, "ops-late-day", 300)

    notes = []
    if worst_pay is not None and best_pay is not None and worst_pay["% batal"] > best_pay["% batal"]:
        notes.append(f"Pembeli dengan {worst_pay['Metode pembayaran']} batal {fmt_pct(worst_pay['% batal'], 1)} "
                     f"(belum bayar {fmt_pct(worst_pay['% batal belum bayar'], 1)}), {best_pay['Metode pembayaran']} hanya {fmt_pct(best_pay['% batal'], 1)}: "
                     f"prioritaskan chat kejar bayar untuk pesanan {worst_pay['Metode pembayaran']} di hari pertama.")
    if np.isfinite(heavy_rate) and np.isfinite(light_rate) and heavy_rate > light_rate:
        notes.append(f"Paket ≥ 20 kg batal {fmt_pct(heavy_rate, 1)} vs {fmt_pct(light_rate, 1)} untuk paket < 5 kg: tampilkan estimasi ongkir & opsi kargo "
                     "jelas di listing produk bulky, dan konfirmasi ongkir lewat chat sebelum pembeli membatalkan.")
    if ship["terlambat"]:
        top_days = per_day.sort_values("% terlambat", ascending=False).head(2)["Hari pesanan"].tolist()
        notes.append(f"{fmt_num(ship['terlambat'])} pesanan ({fmt_pct(ship['porsi'], 1)}) diatur pengirimannya setelah batas Shopee — berisiko penalti performa toko. "
                     f"Paling sering untuk pesanan hari {' & '.join(top_days)}: tambah kapasitas packing di hari itu.")
    if notes:
        st.markdown("\n".join(f"- {n}" for n in notes))
    explain([
        ("% batal belum bayar", "invoice batal dengan alasan belum dibayar ÷ semua invoice metode itu"),
        ("Berat paket", "Total Berat pesanan pada laporan (semua produk dalam satu pesanan)"),
        ("Lewat kargo", "porsi invoice dengan opsi Hemat Kargo / Trucking"),
        ("Terlambat kirim", "Waktu Pengiriman Diatur lewat dari Pesanan Harus Dikirimkan Sebelum; pesanan batal tidak dinilai"),
        ("AOV", "sales bersih ÷ invoice bersih (tidak batal & tidak habis diretur)"),
    ])
    download_excel({"Metode pembayaran": pay, "Berat paket": weight, "Terlambat per layanan": per_service, "Terlambat per hari": per_day},
                   "pembayaran_berat_kirim.xlsx", key="xl-ops", label="Unduh analisa (Excel)")
