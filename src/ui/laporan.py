"""Tab Laporan: 11 bagian untuk direktur & CEO, daftar isi di kiri, chip parameter di bawah judul."""

from __future__ import annotations

import html
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.core.decision_table import PERIOD_LABELS
from src.core.expert_system import FISHBONE_CATEGORIES, evaluate_rules, fishbone, sku_facts, swot, work_guide
from src.core.optimization import monte_carlo_stock_scenarios
from src.core.preprocessing import promo_flag
from src.ui.analysis_dialog import store_performance
from src.core.ads import ad_validation, attribute_ads
from src.utils.format import input_rupiah, show_table
from src.ui.common import card, download_excel, fmt_date, fmt_idr, fmt_idr_short, fmt_num, fmt_pct, fmt_qty, period_filter, status_key

SECTIONS = (
    "1. Ringkasan eksekutif",
    "2. Tren penjualan",
    "3. Item terlaris & prediksi",
    "4. Stok & safety stock",
    "5. Iklan",
    "6. Performa toko",
    "7. Transaksi, batal & retur",
    "8. Analisa SWOT",
    "9. Analisa fishbone",
    "10. Rekomendasi",
    "11. Panduan kerja",
)


def _chip(text: str) -> str:
    return (
        "<span style='display:inline-block;margin:2px 6px 2px 0;padding:3px 10px;border-radius:999px;"
        f"background:#f1f5f9;color:#334155;font-size:.76rem;font-weight:600'>{html.escape(text)}</span>"
    )


def _cancel_mask(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty or "status" not in frame.columns:
        return pd.Series(False, index=frame.index if frame is not None else [])
    from src.ingest import cancelled_status_mask

    return cancelled_status_mask(frame["status"])


def _orders_count(frame: pd.DataFrame) -> int:
    if frame is None or frame.empty:
        return 0
    return int(frame["order_id"].nunique()) if "order_id" in frame.columns else len(frame)


def _previous_span(frame: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    """Rentang sebelumnya dengan panjang hari yang sama (dipakai sebagai pembanding 'bulan lalu')."""
    if frame is None or frame.empty:
        return orders.iloc[0:0]
    lo = pd.to_datetime(frame["order_time"]).min().normalize()
    hi = pd.to_datetime(frame["order_time"]).max().normalize()
    span = hi - lo + pd.Timedelta(days=1)
    stamps = pd.to_datetime(orders["order_time"]).dt.normalize()
    return orders.loc[stamps.ge(lo - span) & stamps.lt(lo)]


def _top_advices(table: pd.DataFrame, today: date, limit: int = 8) -> pd.DataFrame:
    rows = []
    for _, row in table.head(50).iterrows():
        facts = sku_facts(row, today=today)
        advices = evaluate_rules(facts)
        short = facts.get("status_stok") in {"Kosong", "Kurang", "Tipis"}
        for advice in advices:
            if short and advice.action == "iklan" and advice.rule_id != "iklan_boros":
                continue
            rows.append({"Prioritas": advice.priority, "SKU": row["sku"], "Produk": row["product_name"], "Aksi": advice.action, "Rekomendasi": advice.text})
            break
    frame = pd.DataFrame(rows, columns=["Prioritas", "SKU", "Produk", "Aksi", "Rekomendasi"])
    return frame.sort_values(["Prioritas", "SKU"]).head(limit).reset_index(drop=True)


def _cancel_reasons(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty or "cancel_reason" not in frame.columns:
        return pd.DataFrame(columns=["reason", "orders"])
    part = frame.loc[_cancel_mask(frame)]
    if part.empty:
        return pd.DataFrame(columns=["reason", "orders"])
    reason = part["cancel_reason"].fillna("").astype(str).str.strip().replace("", "Tanpa alasan")
    key = part["order_id"] if "order_id" in part.columns else part.index.to_series()
    out = pd.DataFrame({"reason": reason, "key": key}).drop_duplicates().groupby("reason").size().rename("orders").reset_index()
    return out.sort_values("orders", ascending=False).reset_index(drop=True)


def show_report(
    table: pd.DataFrame,
    *,
    orders: pd.DataFrame,
    orders_all: pd.DataFrame,
    frames,
    params: dict,
    today: date,
    period: str,
    metric: str,
    service: int,
    exclude: bool,
    window_start: date,
    window_end: date,
    stock: pd.DataFrame | None = None,
) -> None:
    st.subheader("Laporan penjualan e-commerce Mitra10 × Shopee")
    st.markdown(
        _chip(f"Periode prediksi: {PERIOD_LABELS[period]}")
        + _chip(f"Prediksi: {fmt_date(window_start, short=True)} – {fmt_date(window_end)}")
        + _chip(f"Parameter: {'Quantity terjual' if metric == 'qty' else 'Sales volume'}")
        + _chip(f"Safety stock: {service}%")
        + _chip("Exclude batal & return: aktif" if exclude else "Exclude batal & return: nonaktif"),
        unsafe_allow_html=True,
    )
    with st.expander("Periode laporan", expanded=False):
        report_orders, report_label, _months = period_filter(orders, prefix="report", compact=True)
    if report_orders is None or report_orders.empty:
        st.write("Tidak ada transaksi pada periode laporan.")
        return
    report_all = orders_all
    if isinstance(orders_all, pd.DataFrame) and not orders_all.empty:
        stamps = pd.to_datetime(orders_all["order_time"]).dt.normalize()
        lo = pd.to_datetime(report_orders["order_time"]).min().normalize()
        hi = pd.to_datetime(report_orders["order_time"]).max().normalize()
        report_all = orders_all.loc[stamps.between(lo, hi)]

    target_default = float(params.get("target", {}).get("sales_bulanan_rp", 0) or 0)
    target = float(input_rupiah("Target sales bulanan", target_default, key="report-target-rp"))
    month_pred = float(table["m_sales"].sum()) if table is not None and not table.empty and "m_sales" in table.columns else 0.0
    target_note = ""
    if target <= 0:
        target = month_pred
        target_note = "Target belum diisi: memakai prediksi sales bulan ini sebagai target."

    top = table.head(50) if table is not None else pd.DataFrame()
    sales_now = float(report_orders["sales"].sum())
    prev = _previous_span(report_orders, orders)
    sales_prev = float(prev["sales"].sum()) if not prev.empty else np.nan
    growth = (sales_now - sales_prev) / sales_prev * 100 if sales_prev and np.isfinite(sales_prev) and sales_prev > 0 else np.nan
    report_lo = pd.to_datetime(report_orders["order_time"]).min().normalize()
    report_hi = pd.to_datetime(report_orders["order_time"]).max().normalize()
    ad_result = attribute_ads(frames.ads, frames.stock, orders=report_orders, start=report_lo, end=report_hi)
    ad_cost, ad_sales = ad_result.cost, ad_result.sales
    roas = ad_sales / ad_cost if ad_cost > 0 else np.nan
    short_top = int(top["m_status"].map(status_key).isin({"Kurang", "Kosong"}).sum()) if not top.empty and "m_status" in top.columns else 0
    cancel_rate = float(_cancel_mask(report_all).mean() * 100) if isinstance(report_all, pd.DataFrame) and not report_all.empty else 0.0
    reasons = _cancel_reasons(report_all)
    unpaid = int(reasons.loc[reasons["reason"].str.lower().str.contains("bayar"), "orders"].sum()) if not reasons.empty else 0

    nav, body = st.columns([1, 4])
    with nav:
        st.markdown("**Daftar isi**")
        section = st.radio("Daftar isi", SECTIONS, key="report-section", label_visibility="collapsed")
    with body:
        st.markdown(f"### {section}")
        st.caption(f"Periode laporan: {report_label}")
        try:
            if section == SECTIONS[0]:
                cols = st.columns(4)
                card(cols[0], "Sales bersih", fmt_idr(sales_now), hint=(f"{fmt_pct(growth, 1, signed=True)} vs periode sebelumnya" if np.isfinite(growth) else "periode sebelumnya belum ada"))
                card(cols[1], "Prediksi sales bulan ini", fmt_idr(month_pred), hint=f"target {fmt_idr(target)}")
                card(cols[2], "ROAS iklan", fmt_num(roas, 2), hint=f"target {params.get('iklan', {}).get('target_roas', 8)}")
                card(cols[3], "Top 50 stok kurang", fmt_num(short_top), hint="status Kurang/Kosong bulan ini")
                if target_note:
                    st.caption(target_note)
                gap = month_pred - target
                st.markdown(
                    f"- Prediksi bulan ini {fmt_idr(month_pred)} {'di atas' if gap >= 0 else 'di bawah'} target sebesar {fmt_idr(abs(gap))}.\n"
                    f"- {short_top} SKU Top 50 stoknya belum menutup kebutuhan (prediksi + safety stock): prioritas restock sebelum menambah iklan.\n"
                    f"- Tingkat batal {fmt_pct(cancel_rate)}; {unpaid} pesanan batal karena belum bayar bisa dikejar lewat chat."
                )
                adv = _top_advices(table, today, limit=3)
                if not adv.empty:
                    st.markdown("**Rekomendasi utama**")
                    st.markdown("\n".join(f"1. {r}" for r in adv["Rekomendasi"]))
            elif section == SECTIONS[1]:
                monthly = orders.assign(m=pd.to_datetime(orders["order_time"]).dt.to_period("M").dt.to_timestamp()).groupby("m")["sales"].sum()
                ma = monthly.rolling(3, min_periods=1).mean()
                fig = go.Figure()
                fig.add_bar(x=monthly.index, y=monthly.values, name="Sales aktual", marker_color="#1b3da6", text=[fmt_idr_short(v) for v in monthly.values], textposition="outside", hovertemplate="%{x|%b %Y}<br>%{text}<extra></extra>")
                fig.add_scatter(x=ma.index, y=ma.values, name="Moving average 3 bulan", mode="lines+markers", line=dict(color="#0f766e"))
                if month_pred > 0:
                    this_month = pd.Timestamp(today).to_period("M").to_timestamp()
                    fig.add_scatter(x=[this_month], y=[month_pred], name="Prediksi bulan ini", mode="markers+text", marker=dict(color="#ee4d2d", size=14, symbol="diamond"), text=[fmt_idr_short(month_pred)], textposition="top center")
                fig.update_layout(height=420, legend=dict(orientation="h", y=-0.2), yaxis_title="Rupiah", margin=dict(l=40, r=20, t=30, b=40))
                st.plotly_chart(fig, use_container_width=True, key="report-trend")
                if len(monthly) >= 2:
                    last, before = float(monthly.iloc[-1]), float(monthly.iloc[-2])
                    st.caption(f"Bulan terakhir {fmt_idr(last)} vs bulan sebelumnya {fmt_idr(before)}. Bulan berjalan masih terpotong sampai data terakhir.")
            elif section == SECTIONS[2]:
                cols = ["peringkat", "sku", "product_name", "qty_total", "sales_total", "m_qty", "m_sales", "label_text"]
                view = top[[c for c in cols if c in top.columns]].head(20).rename(
                    columns={"peringkat": "Peringkat", "sku": "SKU", "product_name": "Produk", "qty_total": "QTY terjual", "sales_total": "Sales", "m_qty": "Prediksi QTY bulan ini", "m_sales": "Prediksi sales bulan ini", "label_text": "Label"}
                )
                show_table(view)
                download_excel(view, "laporan_terlaris.xlsx", key="xl-report-top")
            elif section == SECTIONS[3]:
                if top.empty or "m_status" not in top.columns:
                    st.write("Data stok belum tersedia.")
                else:
                    counts = top["m_status"].map(status_key).value_counts()
                    cols = st.columns(5)
                    for column, name in zip(cols, ("Aman", "Tipis", "Kurang", "Kosong", "Tanpa data stok")):
                        card(column, name, fmt_num(int(counts.get(name, 0))), hint="SKU Top 50")
                    sigma_map = stock.set_index("item_key")["sigma_qty"].to_dict() if isinstance(stock, pd.DataFrame) and "sigma_qty" in stock.columns else {}
                    lead = params.get("lead_time", {})
                    rows = []
                    for _, row in top.head(10).iterrows():
                        mc = monte_carlo_stock_scenarios(
                            demand_mean=float(row["pred_harian"]),
                            demand_sigma=float(sigma_map.get(row["item_key"], row["pred_harian"] * 0.5)),
                            lead_time_mean=float(lead.get("lokal_hari", 7)),
                            lead_time_sigma=float(lead.get("lokal_sigma_hari", 0) or 0),
                            current_stock=float(row["stok"]) if bool(row.get("ada_data_stok", False)) else 0.0,
                            safety_stock=float(row["ss"]),
                        )
                        pick = mc.set_index("Skenario")
                        rows.append(
                            {
                                "SKU": row["sku"],
                                "Produk": row["product_name"],
                                "Stok": row["stok"] if bool(row.get("ada_data_stok", False)) else None,
                                "SS": row["ss"],
                                "ROP": row["rop"],
                                "Restock moderat": round(pick.loc["Moderat", "Restock disarankan"]),
                                "Restock pesimistis": round(pick.loc["Pesimistis", "Restock disarankan"]),
                                "Risiko stockout (%)": round(pick.loc["Moderat", "Risiko stockout"], 1),
                            }
                        )
                    frame = pd.DataFrame(rows)
                    st.markdown("**Skenario Monte Carlo (1.000 simulasi permintaan × lead time) untuk 10 SKU teratas**")
                    show_table(frame, kinds={"SS": "count", "ROP": "count"})
                    st.caption("ROP = permintaan harian × lead time + SS. Pesan ulang saat stok menyentuh ROP; restock pesimistis = kebutuhan kuantil 90%.")
                    download_excel(frame, "laporan_stok_monte_carlo.xlsx", key="xl-report-mc")
            elif section == SECTIONS[4]:
                share = ad_sales / sales_now * 100 if sales_now > 0 else np.nan
                warnings, notes = ad_validation(ad_result, sales_now)
                for message in warnings:
                    st.warning(message)
                cols = st.columns(4)
                card(cols[0], "Biaya iklan", fmt_idr(ad_cost))
                card(cols[1], "Omzet iklan", fmt_idr(ad_sales))
                card(cols[2], "ROAS", fmt_num(roas, 2))
                card(cols[3], "Porsi sales dari iklan", fmt_pct(share))
                for message in notes:
                    st.caption(message)
                if ad_cost <= 0:
                    st.caption("Laporan iklan belum diunggah, belum terpetakan ke SKU, atau tidak ada pada periode laporan.")
                else:
                    ads = ad_result.per_sku.loc[ad_result.per_sku["biaya_iklan"] > 0].merge(table[["sku", "product_name", "m_status"]].drop_duplicates("sku"), on="sku", how="left")
                    ads = ads[["sku", "product_name", "biaya_iklan", "omzet_iklan", "m_status"]].copy()
                    ads["ROAS"] = ads["omzet_iklan"] / ads["biaya_iklan"]
                    ads = ads.sort_values("biaya_iklan", ascending=False).head(20)
                    show_table(ads.rename(columns={"sku": "SKU", "product_name": "Produk", "biaya_iklan": "Biaya", "omzet_iklan": "Omzet iklan", "m_status": "Status stok"}))
            elif section == SECTIONS[5]:
                perf = store_performance(frames.performance, today)
                if not perf:
                    st.write("Data performance belum diunggah.")
                else:
                    cols = st.columns(4)
                    card(cols[0], "Pengunjung 28 hari", fmt_num(perf["pengunjung"]), hint=f"sebelumnya {fmt_num(perf['pengunjung_prev'])}")
                    card(cols[1], "Pesanan 28 hari", fmt_num(perf["pesanan"]), hint=f"sebelumnya {fmt_num(perf['pesanan_prev'])}")
                    card(cols[2], "Konversi", fmt_pct(perf["konversi"], 2), hint=f"sebelumnya {fmt_pct(perf['konversi_prev'], 2)}")
                    card(cols[3], "Pembeli baru", fmt_num(perf["pembeli_baru"]))
            elif section == SECTIONS[6]:
                total = _orders_count(report_all)
                cancelled = _orders_count(report_all.loc[_cancel_mask(report_all)]) if total else 0
                returned = float((report_all["gross_qty"] - report_all["qty"]).clip(lower=0).sum()) if {"gross_qty", "qty"} <= set(report_all.columns) else 0.0
                cols = st.columns(4)
                card(cols[0], "Pesanan", fmt_num(total))
                card(cols[1], "Batal", fmt_num(cancelled), hint=fmt_pct(cancel_rate))
                card(cols[2], "Unit retur", fmt_qty(returned))
                card(cols[3], "Batal belum bayar", fmt_num(unpaid))
                if not reasons.empty:
                    show_table(reasons.rename(columns={"reason": "Alasan batal", "orders": "Pesanan"}).head(10))
            elif section == SECTIONS[7]:
                promo_days = int(promo_flag(pd.Series(pd.date_range(window_start, window_end))).sum())
                context = {
                    "sales_growth_pct": growth,
                    "top50_share_pct": float(top["sales_total"].sum() / sales_now * 100) if sales_now > 0 and not top.empty else None,
                    "roas": roas,
                    "target_roas": params.get("iklan", {}).get("target_roas", 8),
                    "cancel_pct": cancel_rate,
                    "top50_short": short_top,
                    "unpaid_orders": unpaid,
                    "promo_days": promo_days,
                    "poor_names": int((st.session_state.get("_name-recs", (None, pd.DataFrame()))[1].get("Status skor", pd.Series(dtype=str)) == "Poor").sum()) if st.session_state.get("_name-recs") else None,
                    "dead_stock": int(table.get("productivity_label", pd.Series(dtype=str)).astype(str).str.contains("Dead|Slow", regex=True).sum()) if table is not None else None,
                    "zero_stock": int(table["m_status"].map(status_key).eq("Kosong").sum()) if table is not None and "m_status" in table.columns else None,
                }
                result = swot(context)
                cols = st.columns(2)
                for index, (name, items) in enumerate(result.items()):
                    with cols[index % 2].container(border=True):
                        st.markdown(f"**{name}**")
                        st.markdown("\n".join(f"- {item}" for item in items))
            elif section == SECTIONS[8]:
                bones = fishbone(reasons)
                st.caption("Masalah utama: pembatalan pesanan. Angka = jumlah pesanan batal per alasan pada periode laporan.")
                cols = st.columns(3)
                for index, category in enumerate(FISHBONE_CATEGORIES):
                    with cols[index % 3].container(border=True):
                        st.markdown(f"**{category}**")
                        items = bones.get(category) or ["Tidak ada alasan pada kategori ini"]
                        st.markdown("\n".join(f"- {item}" for item in items[:6]))
            elif section == SECTIONS[9]:
                adv = _top_advices(table, today, limit=12)
                if adv.empty:
                    st.write("Tidak ada aturan sistem pakar yang terpicu pada Top 50.")
                else:
                    show_table(adv)
                    download_excel(adv, "laporan_rekomendasi.xlsx", key="xl-report-adv")
            elif section == SECTIONS[10]:
                days_in_month = pd.Timestamp(today).days_in_month
                guide = work_guide(
                    {
                        "target_sales": target,
                        "target_text": fmt_idr(target),
                        "daily_target_text": fmt_idr(target / days_in_month),
                        "target_roas": params.get("iklan", {}).get("target_roas", 8),
                    }
                )
                if target_note:
                    st.caption(target_note)
                for name, tasks in guide.items():
                    st.markdown(f"**{name}**")
                    show_table(pd.DataFrame(tasks, columns=["Tugas", "Ukuran berhasil"]))
        except Exception as exc:  # satu bagian gagal tidak menghentikan laporan
            st.warning(f"Bagian ini belum bisa ditampilkan: {exc}")
