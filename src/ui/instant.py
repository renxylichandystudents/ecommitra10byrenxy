"""Tab Data › Performa penjualan instan (Instant, Instant Prioritas, Same Day)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.core import instant as I
from src.ui.common import card, download_excel, explain, fmt_idr, fmt_idr_short, fmt_num, fmt_pct, range_label
from src.utils.format import show_table

UP, DOWN = "#1d4ed8", "#dc2626"
COLORS = {"Instant": "#ee4d2d", "Instant Prioritas": "#1b3da6", "Same Day": "#f59e0b"}


def _orders(source_raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    key = (id(source_raw), len(source_raw), tuple(source_raw.columns[:5]))
    cached = st.session_state.get("_instant-cache")
    if isinstance(cached, tuple) and cached[0] == key:
        return cached[1], cached[2]
    lines = I.instant_lines(source_raw)
    orders = I.order_frame(lines)
    st.session_state["_instant-cache"] = (key, lines, orders)
    return lines, orders


def _vs(now: float, other: float, *, lower_better: bool = False, unit: str = "%") -> str:
    if not (np.isfinite(now) and np.isfinite(other)):
        return ""
    better = now <= other if lower_better else now >= other
    gap = f"{abs(now - other):.1f}".replace(".", ",") + (" poin" if unit == "%" else f" {unit}")
    text = f"{'lebih rendah' if now < other else 'lebih tinggi'} {gap}"
    return f"<b style='color:{UP if better else DOWN}'>{text}</b>"


def _plot(fig: go.Figure, key: str, height: int = 360) -> None:
    fig.update_layout(height=height, separators=",.", margin=dict(l=40, r=20, t=50, b=40), template="plotly_white",
                      legend=dict(orientation="h", y=-0.2), font=dict(family="Plus Jakarta Sans"))
    st.plotly_chart(fig, use_container_width=True, key=key)


def show_instant_analysis(source_raw: pd.DataFrame, start: date | None, end: date | None) -> None:
    st.subheader("Performa penjualan instan")
    if source_raw is None or source_raw.empty:
        st.write("Belum ada data transaksi.")
        return
    lines, orders = _orders(source_raw)
    if orders.empty:
        st.info("Laporan pesanan belum memuat kolom Opsi Pengiriman, jadi pesanan instan belum bisa dipisahkan.", icon=":material/info:")
        return
    lo, hi = orders["day"].min().date(), orders["day"].max().date()
    start = max(pd.Timestamp(start).date(), lo) if start is not None else lo
    end = min(pd.Timestamp(end).date(), hi) if end is not None else hi
    in_range = orders["day"].between(pd.Timestamp(start), pd.Timestamp(end))
    orders = orders.loc[in_range]
    lines = lines.loc[lines["order_id"].isin(set(orders["order_id"]))]
    period = range_label(start, end)
    st.caption(f"{period} · pesanan dengan opsi pengiriman Instant, Instant Prioritas, dan Same Day (SPX, GoSend, GrabExpress), "
               "dibanding semua opsi pengiriman lain. Ikut periode data di atas.")
    stats = I.compare(orders)
    inst, other, every = stats.get("instan"), stats.get("lain"), stats.get("semua")
    if not inst or inst["invoice"] == 0:
        st.write("Tidak ada pesanan instan pada periode ini.")
        return

    share_inv = inst["invoice"] / every["invoice"] * 100 if every["invoice"] else float("nan")
    share_sales = inst["sales_bersih"] / every["sales_bersih"] * 100 if every["sales_bersih"] else float("nan")
    row = st.columns(4)
    card(row[0], "Invoice instan", fmt_num(inst["invoice"]), hint=f"{fmt_pct(share_inv, 1)} dari {fmt_num(every['invoice'])} invoice · {fmt_num(inst['pembeli'])} pembeli")
    card(row[1], "Sales bersih instan", fmt_idr(inst["sales_bersih"]), hint=f"{fmt_pct(share_sales, 2)} dari sales bersih toko · {fmt_num(inst['qty_bersih'])} unit")
    card(row[2], "Tingkat batal instan", fmt_pct(inst["tingkat_batal"], 1),
         hint=f"lainnya {fmt_pct(other['tingkat_batal'], 1)} · {_vs(inst['tingkat_batal'], other['tingkat_batal'], lower_better=True)}<br>"
              f"{fmt_num(inst['batal'])} batal, {fmt_num(inst['belum_bayar'])} di antaranya belum dibayar")
    card(row[3], "AOV instan", fmt_idr(inst["aov"]), hint=f"lainnya {fmt_idr(other['aov'])} · sales bersih ÷ invoice bersih")
    row = st.columns(4)
    card(row[0], "Median waktu proses", f"{fmt_num(inst['proses_median'], 1)} jam",
         hint=f"bayar → pengiriman diatur · lainnya {fmt_num(other['proses_median'], 1)} jam")
    card(row[1], f"Diproses > {fmt_num(I.SLOW_HOURS)} jam", fmt_num(inst["proses_lambat"]),
         hint=f"dari {fmt_num(inst['invoice'] - inst['batal'])} pesanan instan tidak batal · risiko dibatalkan sistem")
    card(row[2], "Median sampai selesai", f"{fmt_num(inst['selesai_median'] / 24, 1)} hari", hint=f"pesanan dibuat → selesai · lainnya {fmt_num(other['selesai_median'] / 24, 1)} hari")
    card(row[3], "Invoice retur instan", fmt_num(inst["retur"]), hint=f"lainnya {fmt_num(other['retur'])}")

    daily = I.daily_table(orders, start, end)
    fig = go.Figure()
    for name in I.INSTANT_GROUPS:
        fig.add_bar(x=daily["Tanggal"], y=daily[name], name=name, marker_color=COLORS[name])
    fig.add_scatter(x=daily["Tanggal"], y=daily["Porsi instan (%)"], name="Porsi instan dari semua invoice (%)", yaxis="y2", line=dict(color="#0f172a", width=2))
    fig.update_layout(barmode="stack", title=f"Invoice instan harian · {period}", yaxis_title="Invoice", yaxis2=dict(title="%", overlaying="y", side="right", rangemode="tozero"))
    _plot(fig, "instant-daily", 380)

    c1, c2 = st.columns(2)
    with c1:
        hourly = I.hourly_table(orders)
        fig = go.Figure()
        fig.add_bar(x=hourly["Jam"], y=hourly["Invoice instan"], name="Invoice instan", marker_color="#ee4d2d")
        fig.add_scatter(x=hourly["Jam"], y=hourly["% batal instan"], name="% batal instan", yaxis="y2", mode="lines+markers", line=dict(color=DOWN))
        fig.update_layout(title="Jam pesanan instan dibuat", xaxis=dict(title="Jam", dtick=2), yaxis_title="Invoice",
                          yaxis2=dict(title="% batal", overlaying="y", side="right", rangemode="tozero"))
        _plot(fig, "instant-hour", 340)
    with c2:
        active = orders.loc[orders["instan"] & ~orders["cancelled"] & orders["proses_jam"].notna()]
        fig = go.Figure()
        for name in I.INSTANT_GROUPS:
            part = active.loc[active["layanan"] == name, "proses_jam"].clip(upper=48)
            if not part.empty:
                fig.add_box(y=part, name=name, marker_color=COLORS[name], boxmean=True)
        fig.add_hline(y=I.SLOW_HOURS, line_dash="dash", line_color=DOWN, annotation_text=f"{fmt_num(I.SLOW_HOURS)} jam")
        fig.update_layout(title="Waktu proses (bayar → pengiriman diatur)", yaxis_title="Jam (maks. 48 jam)", showlegend=False)
        _plot(fig, "instant-proc", 340)

    st.markdown("**Per layanan & kurir** · semua opsi pengiriman sebagai pembanding")
    services = I.service_table(orders)
    services["AOV"] = services["AOV"].fillna(0.0)
    total = pd.DataFrame([{"Layanan": "Total", "Kurir": "", "Invoice": services["Invoice"].sum(), "Invoice batal": services["Invoice batal"].sum(),
                           "% batal": every["tingkat_batal"], "Invoice retur": services["Invoice retur"].sum(), "QTY bersih": services["QTY bersih"].sum(),
                           "Sales bersih": services["Sales bersih"].sum(), "AOV": every["aov"], "Kontribusi sales (%)": 100.0, "Median proses (jam)": every["proses_median"]}])
    show_table(pd.concat([total, services], ignore_index=True), bold_label="Total",
               kinds={"Invoice": "count", "Invoice batal": "count", "% batal": "pct", "Invoice retur": "count", "QTY bersih": "count", "Sales bersih": "money",
                      "AOV": "money", "Kontribusi sales (%)": "pct", "Median proses (jam)": "dec"})
    st.caption("Kurir \"Belum ditentukan\" = pesanan dibatalkan sebelum kurir ditugaskan.")

    c1, c2 = st.columns(2)
    reasons = I.cancel_reasons(orders)
    cities = I.top_cities(orders)
    with c1:
        st.markdown("**Alasan batal pesanan instan**")
        if reasons.empty:
            st.write("Tidak ada pesanan instan yang batal.")
        else:
            part = reasons.head(8).iloc[::-1]
            fig = go.Figure(go.Bar(x=part["Invoice"], y=part["Alasan batal"].str.slice(0, 48), orientation="h", marker_color=DOWN, text=part["Invoice"], textposition="outside"))
            fig.update_layout(title_text="", xaxis=dict(dtick=1, title="Pesanan"))
            _plot(fig, "instant-reason", 300)
    with c2:
        st.markdown("**Kota tujuan pesanan instan**")
        if not cities.empty:
            total = I.cities_total(orders)
            shown_note = f"{len(cities)} kota teratas dari {orders.loc[orders['instan'], 'city'].nunique()} kota; baris Total = semua kota"
            st.caption(shown_note)
            show_table(pd.concat([total, cities], ignore_index=True), bold_label="Total",
                       kinds={"Invoice instan": "count", "% batal": "pct", "Sales bersih": "money"})

    st.markdown("**Produk yang paling banyak dibeli dengan pengiriman instan** · kandidat stok siap kirim di toko terdekat")
    products = I.top_products(lines)
    if products.empty:
        st.write("Belum ada produk instan yang terjual (tidak batal).")
    else:
        from src.ui.common import pager

        st.caption("Sales produk instan = Harga Setelah Diskon × (QTY − retur) pesanan instan selain batal & Belum Bayar, sebelum voucher "
                   "(sama dengan sales produk di tab Prediksi). Berbeda dari Sales bersih di kartu & tabel kota (Total Pembayaran, sudah dipotong voucher).")
        total_row = I.products_total(lines, products)
        lo, hi = pager(len(products), key="instant-products", noun="produk", default_size=5,
                       download=lambda: download_excel(pd.concat([total_row, products], ignore_index=True), "produk_pengiriman_instan.xlsx",
                                                       key="xl-instant-products"))
        # Satu baris per produk (tinggi tetap): nama panjang dipotong "…", lihat utuh dengan mengarahkan/klik sel atau di Excel.
        show_table(pd.concat([total_row, products.iloc[lo:hi]], ignore_index=True), bold_label="Total", row_height=35,
                   kinds={"Invoice instan": "count", "QTY instan": "count", "Sales produk instan": "money", "Porsi instan dari sales produk SKU (%)": "pct"},
                   column_config={"Rank": st.column_config.Column("Rank", width=60, pinned=True),
                                  "SKU": st.column_config.TextColumn("SKU", width=110, pinned=True),
                                  "Produk": st.column_config.TextColumn("Produk", width=460, pinned=True),
                                  "Varian": st.column_config.TextColumn("Varian", width=150, pinned=True)})

    seller_fault = int(reasons.loc[reasons["Alasan batal"].str.contains("tidak mengatur pengiriman|Penjual", case=False, regex=True), "Invoice"].sum()) if not reasons.empty else 0
    notes = [f"Pesanan instan {fmt_pct(share_inv, 1)} dari invoice tetapi {fmt_pct(share_sales, 2)} dari sales bersih: kebanyakan barang kecil "
             f"(AOV {fmt_idr_short(inst['aov'])} vs {fmt_idr_short(other['aov'])})."]
    if inst["proses_lambat"]:
        notes.append(f"{fmt_num(inst['proses_lambat'])} pesanan instan baru diatur pengirimannya lebih dari {fmt_num(I.SLOW_HOURS)} jam setelah bayar; "
                     "percepat proses di jam ramai agar tidak dibatalkan sistem.")
    if seller_fault:
        notes.append(f"{fmt_num(seller_fault)} pesanan instan batal karena sisi penjual (mis. pengiriman tidak diatur tepat waktu) — ini bisa dicegah.")
    if not cities.empty:
        top = cities.iloc[0]
        notes.append(f"Tujuan instan terbanyak {top['Kota/Kabupaten']} ({fmt_num(top['Invoice instan'])} invoice): fokus stok produk instan di toko pengirim area ini.")
    st.markdown("\n".join(f"- {n}" for n in notes))
    explain([
        ("Instan", "Opsi Pengiriman berisi Instant, Instant Prioritas, atau Same Day"),
        ("Sales bersih", "Total Pembayaran pesanan tidak batal − Harga Setelah Diskon × jumlah retur (sama dengan tab Data)"),
        ("Waktu proses", "Waktu Pengiriman Diatur − Waktu Pembayaran Dilakukan, hanya pesanan tidak batal"),
        ("Sampai selesai", "Waktu Pesanan Selesai − Waktu Pesanan Dibuat"),
    ])
    download_excel({"Ringkasan layanan": services, "Harian": daily, "Per jam": I.hourly_table(orders), "Produk instan": products, "Kota instan": cities,
                    "Alasan batal instan": reasons}, "performa_penjualan_instan.xlsx", key="xl-instant", label="Unduh analisa instan (Excel)")
