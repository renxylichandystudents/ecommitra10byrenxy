"""Tab Laporan: 11 bagian untuk direktur & CEO, daftar isi di kiri, chip parameter di bawah judul."""

from __future__ import annotations

import html
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.core.decision_table import PERIOD_LABELS, stock_shortage
from src.core.expert_system import FISHBONE_CATEGORIES, evaluate_rules, fishbone, sku_facts, swot, work_guide
from src.core.optimization import monte_carlo_stock_scenarios
from src.core.preprocessing import promo_flag
from src.ui.analysis_dialog import store_performance
from src.core.ads import ad_validation
from src.core.cancel_reasons import CATEGORIES, categorize_series, short_reason
from src.core.metrics import ads_metrics
from src.core.periods import format_period_label, last_full_month
from src.core.restock import recommendation_records, records_display
from src.utils.format import show_table
from src.ui.common import ID_MONTHS, cached_order_metrics, card, download_excel, fmt_date, fmt_idr, fmt_idr_short, fmt_num, fmt_pct, fmt_qty, metric_card, status_key

ALL_SECTIONS = "Semua bagian (untuk dibaca berurutan / dicetak)"
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
        f"background:#f1f5f9;color:#334155;font-size:var(--fs-xs);font-weight:600'>{html.escape(text)}</span>"
    )


def _cancel_mask(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty or "status" not in frame.columns:
        return pd.Series(False, index=frame.index if frame is not None else [])
    from src.ingest import cancelled_status_mask

    return cancelled_status_mask(frame["status"])


def _top_advices(table: pd.DataFrame, today: date, limit: int = 8) -> pd.DataFrame:
    rows = []
    for _, row in table.head(50).iterrows():
        facts = sku_facts(row, today=today)
        advices = evaluate_rules(facts)
        short = facts.get("status_stok") in {"Kosong", "Kurang"}
        for advice in advices:
            if short and advice.action == "iklan" and advice.rule_id != "iklan_boros":
                continue
            rows.append({"Prioritas": advice.priority, "SKU": row["sku"], "Produk": row["product_name"], "Aksi": advice.action, "Rekomendasi": advice.text})
            break
    frame = pd.DataFrame(rows, columns=["Prioritas", "SKU", "Produk", "Aksi", "Rekomendasi"])
    return frame.sort_values(["Prioritas", "SKU"]).head(limit).reset_index(drop=True)


def _cancel_reasons(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty or "cancel_reason" not in frame.columns:
        return pd.DataFrame(columns=["reason", "orders", "kategori"])
    part = frame.loc[_cancel_mask(frame)]
    if part.empty:
        return pd.DataFrame(columns=["reason", "orders", "kategori"])
    reason = part["cancel_reason"].fillna("").astype(str).str.strip().replace("", "Tanpa alasan")
    key = part["order_id"] if "order_id" in part.columns else part.index.to_series()
    out = pd.DataFrame({"reason": reason, "key": key}).drop_duplicates().groupby("reason").size().rename("orders").reset_index()
    out["kategori"] = categorize_series(out["reason"])
    # Kategori dari teks asli; tampilan memakai label pendek (alasan sama beda tulisan/bahasa digabung).
    out["reason"] = out["reason"].map(short_reason)
    out = out.groupby(["reason", "kategori"], as_index=False)["orders"].sum()
    return out.sort_values("orders", ascending=False).reset_index(drop=True)


def _records(table: pd.DataFrame, today: date, data) -> pd.DataFrame:
    """Rekomendasi ber-SKU (Top 50): satu sumber untuk Laporan dan unduhan."""
    if table is None or table.empty:
        return pd.DataFrame()
    advice = {}
    adv = _top_advices(table, today, limit=50)
    for sku, text in zip(adv["SKU"].astype(str), adv["Rekomendasi"]):
        advice.setdefault(sku, str(text))
    return recommendation_records(
        table.head(50),
        today,
        po=getattr(data, "po", None),
        margin_pct=getattr(data, "margin_pct", None),
        advice=advice,
    )


def _report_month(orders: pd.DataFrame, features, run_id: int, username: str, can_edit: bool) -> tuple[pd.DataFrame, str]:
    """Periode laporan = bulan penuh terakhir sebelum data s.d. (disimpan per run); pilihan user ikut disimpan per run."""
    if orders is None or orders.empty:
        return orders, ""
    stamps = pd.to_datetime(orders["order_time"], errors="coerce")
    months = sorted(stamps.dt.to_period("M").dropna().astype(str).unique())
    lo, _hi = last_full_month(stamps.max().date())
    default = f"{lo.year:04d}-{lo.month:02d}"
    saved = None
    if features is not None and run_id:
        try:
            saved = features.report_period(run_id)
        except Exception:
            saved = None
    chosen = saved if saved in months else (default if default in months else months[-1])
    names = {key: f"{ID_MONTHS[int(key[5:]) - 1]} {key[:4]}" for key in months}
    options = months[::-1]
    pick = st.selectbox("Periode laporan", options, index=options.index(chosen), format_func=names.get, key=f"report-month-{run_id}", disabled=not can_edit)
    if pick != chosen and features is not None and run_id and can_edit:
        features.set_report_period(run_id, pick, username=username)
    part = orders.loc[stamps.dt.to_period("M").astype(str) == pick].reset_index(drop=True)
    return part, names[pick]



def _month_label(stamp: pd.Timestamp) -> str:
    return f"{ID_MONTHS[stamp.month - 1][:3]} {stamp.year}"


def _show_trend(orders: pd.DataFrame, orders_all: pd.DataFrame, *, today: date, month_pred: float, pred_label: str, exclude: bool) -> None:
    """Tren bulanan dengan dua dasar yang jelas dan bulan berjalan ditandai (tidak ikut moving average)."""
    times = pd.to_datetime(orders["order_time"])
    monthly = orders.assign(m=times.dt.to_period("M").dt.to_timestamp()).groupby("m")["sales"].sum()
    if monthly.empty:
        st.write("Belum ada transaksi.")
        return
    data_end = times.max().normalize()
    month_end = (data_end + pd.offsets.MonthEnd(0)).normalize()
    partial = data_end < month_end  # bulan terakhir belum penuh
    full = monthly.iloc[:-1] if partial else monthly
    ma = full.rolling(3, min_periods=1).mean()
    bersih = {}
    if isinstance(orders_all, pd.DataFrame) and not orders_all.empty:
        for stamp in monthly.index:
            end = min((stamp + pd.offsets.MonthEnd(0)).normalize(), data_end)
            bersih[stamp] = float(cached_order_metrics(orders_all, stamp.date(), end.date(), exclude)["sales_bersih"])
    labels = [_month_label(m) for m in monthly.index]
    if partial:
        labels[-1] = f"{labels[-1]} (s.d. {data_end.day} {ID_MONTHS[data_end.month - 1][:3]})"
    colors = ["#1b3da6"] * len(monthly)
    patterns = [""] * len(monthly)
    if partial:
        colors[-1], patterns[-1] = "#93a5d8", "/"
    basis = "Sales produk (dasar prediksi)"
    fig = go.Figure()
    fig.add_bar(
        x=labels, y=monthly.values / 1e9, name=basis, marker=dict(color=colors, pattern=dict(shape=patterns)),
        text=[fmt_idr_short(v) for v in monthly.values], textposition="outside", hovertext=[fmt_idr_short(v) for v in monthly.values], hoverinfo="x+text",
    )
    fig.add_scatter(x=labels[: len(ma)], y=ma.values / 1e9, name="Moving average 3 bulan (bulan penuh)", mode="lines+markers", line=dict(color="#0f766e"))
    if bersih:
        fig.add_scatter(x=labels, y=[bersih[m] / 1e9 for m in monthly.index], name="Sales bersih (kartu Ringkasan)", mode="lines+markers", line=dict(color="#64748b", dash="dot"))
    if month_pred > 0:
        fig.add_scatter(x=[labels[-1]], y=[month_pred / 1e9], name=pred_label, mode="markers+text", marker=dict(color="#ee4d2d", size=14, symbol="diamond"), text=[fmt_idr_short(month_pred)], textposition="top center")
    fig.update_layout(height=440, separators=",.", legend=dict(orientation="h", y=-0.22), yaxis_title="Miliar rupiah", margin=dict(l=40, r=20, t=30, b=40))
    st.plotly_chart(fig, use_container_width=True, key="report-trend")
    st.caption(
        f"{basis} = Harga setelah diskon × QTY{' (tanpa batal & retur)' if exclude else ' (termasuk pesanan batal, karena saklar Kecualikan batal & retur nonaktif)'}; "
        "dasar ini sama dengan prediksi. Sales bersih = Total Pembayaran per pesanan dikurangi batal & retur, sama dengan kartu Ringkasan eksekutif."
    )
    if len(full) >= 2:
        last, before = float(full.iloc[-1]), float(full.iloc[-2])
        change = (last - before) / before * 100 if before > 0 else float("nan")
        st.caption(
            f"Bulan penuh terakhir ({_month_label(full.index[-1])}) {fmt_idr(last)} vs {_month_label(full.index[-2])} {fmt_idr(before)}"
            + (f" ({fmt_pct(change, 1, signed=True)})." if np.isfinite(change) else ".")
            + (f" {labels[-1]} belum penuh, tidak dibandingkan." if partial else "")
        )



def _print_button() -> None:
    """Tombol cetak: membuka dialog cetak browser (pilih "Simpan sebagai PDF")."""
    import streamlit.components.v1 as components

    components.html(
        "<button onclick='window.parent.print()' style='width:100%;padding:.5rem .75rem;border-radius:10px;"
        "border:1px solid #ee4d2d;background:#fff;color:#ee4d2d;font:600 14px sans-serif;cursor:pointer'>"
        "Cetak / Simpan PDF</button>",
        height=48,
    )
    st.caption("Di dialog cetak, pilih \"Simpan sebagai PDF\".")


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
    features=None,
    data=None,
    run_id: int = 0,
    username: str = "",
    can_edit: bool = False,
) -> None:
    st.subheader("Laporan penjualan e-commerce Mitra10 × Shopee")
    st.markdown(
        _chip(f"Periode prediksi: {PERIOD_LABELS[period]}")
        + _chip(f"Prediksi: {fmt_date(window_start, short=True)} – {fmt_date(window_end)}")
        + _chip(f"Parameter: {'QTY terjual' if metric == 'qty' else 'Sales value'}")
        + _chip(f"Safety stock: {service}%")
        + _chip("Kecualikan batal & retur: aktif" if exclude else "Kecualikan batal & retur: nonaktif"),
        unsafe_allow_html=True,
    )
    report_orders, report_label = _report_month(orders, features, run_id, username, can_edit)
    if report_orders is None or report_orders.empty:
        st.write("Tidak ada transaksi pada periode laporan.")
        return
    report_all = orders_all
    if isinstance(orders_all, pd.DataFrame) and not orders_all.empty:
        stamps = pd.to_datetime(orders_all["order_time"]).dt.normalize()
        lo = pd.to_datetime(report_orders["order_time"]).min().normalize()
        hi = pd.to_datetime(report_orders["order_time"]).max().normalize()
        report_all = orders_all.loc[stamps.between(lo, hi)]

    saved_target = getattr(data, "target", None) or {}
    target = float(saved_target.get("target_sales_bersih", 0) or 0)
    month_pred = float(table["m_sales"].sum()) if table is not None and not table.empty and "m_sales" in table.columns else 0.0
    pred_label = format_period_label("prediksi", window_start)
    records = _records(table, today, data)

    top = table.head(50) if table is not None else pd.DataFrame()
    report_lo = pd.to_datetime(report_orders["order_time"]).min().normalize()
    report_hi = pd.to_datetime(report_orders["order_time"]).max().normalize()
    facts = cached_order_metrics(orders_all, report_lo.date(), report_hi.date(), exclude)
    span = report_hi - report_lo + pd.Timedelta(days=1)
    prev_facts = cached_order_metrics(orders_all, (report_lo - span).date(), (report_lo - pd.Timedelta(days=1)).date(), exclude)
    sales_now = float(facts["sales_bersih"])
    sales_prev = float(prev_facts["sales_bersih"]) if prev_facts["pesanan_semua"] > 0 else np.nan
    growth = (sales_now - sales_prev) / sales_prev * 100 if sales_prev and np.isfinite(sales_prev) and sales_prev > 0 else np.nan
    ads = ads_metrics(frames.ads, frames.stock, orders_all, report_lo, report_hi)
    ad_result = ads["result"]
    ad_cost, ad_sales, roas = ads["biaya_iklan"], ads["omzet_iklan"], ads["roas"]
    shortage = stock_shortage(top)
    short_top = shortage["kurang"]
    cancel_rate = float(facts["tingkat_batal"] * 100)
    reasons = _cancel_reasons(report_all)
    unpaid = int(facts["belum_bayar"])

    nav, body = st.columns([1, 4])
    with nav:
        st.markdown("**Daftar isi**")
        options = (ALL_SECTIONS,) + SECTIONS
        current = st.session_state.get("report-section")
        section = st.radio(
            "Daftar isi", options, index=options.index(current) if current in options else 1, key="report-section", label_visibility="collapsed"
        )
        if section == ALL_SECTIONS:
            _print_button()
    chosen = SECTIONS if section == ALL_SECTIONS else (section,)
    with body:
        for section in chosen:
            st.markdown(f"### {section}")
            st.caption(f"Periode laporan: {report_label}")
            try:
                if section == SECTIONS[0]:
                    cols = st.columns(4)
                    metric_card(cols[0], "sales_bersih", fmt_idr(sales_now), hint=(f"{fmt_pct(growth, 1, signed=True)} vs periode sebelumnya" if np.isfinite(growth) else "periode sebelumnya belum ada"))
                    window_text = f"{fmt_date(window_start, short=True)} – {fmt_date(window_end, short=True)}"
                    card(cols[1], f"{pred_label} · sales", fmt_idr(month_pred), hint=f"{window_text} · target {fmt_idr(target)}" if target > 0 else window_text)
                    metric_card(cols[2], "roas", fmt_num(roas, 1), hint=f"target {params.get('iklan', {}).get('target_roas', 8)}")
                    short_hint = f"stok di bawah {pred_label} + SS · {fmt_num(shortage['kosong'])} kosong (stok 0)"
                    if shortage["tanpa_data"]:
                        short_hint += f" · {fmt_num(shortage['tanpa_data'])} tanpa data stok"
                    card(cols[3], "Top 50 stok kurang", fmt_num(short_top), hint=short_hint)
                    gap = month_pred - target
                    target_line = f"- {pred_label} {fmt_idr(month_pred)} {'di atas' if gap >= 0 else 'di bawah'} target sebesar {fmt_idr(abs(gap))}.\n" if target > 0 else ""
                    st.markdown(
                        target_line
                        + f"- {short_top} SKU Top 50 stoknya di bawah {pred_label} + safety stock ({shortage['kosong']} di antaranya stok 0): prioritas restock sebelum menambah iklan.\n"
                        f"- Tingkat batal {fmt_pct(cancel_rate)}; {unpaid} pesanan batal karena belum bayar bisa dikejar lewat chat."
                    )
                    if not records.empty:
                        st.markdown("**Rekomendasi utama**")
                        show_table(records_display(records.head(5)), kinds={"Stok Site 10037": "count", "Kebutuhan": "count", "Restock": "count"})
                elif section == SECTIONS[1]:
                    _show_trend(orders, orders_all, today=today, month_pred=month_pred, pred_label=pred_label, exclude=exclude)
                elif section == SECTIONS[2]:
                    cols = ["peringkat", "sku", "product_name", "qty_total", "sales_total", "m_qty", "m_sales", "label_text"]
                    view = top[[c for c in cols if c in top.columns]].head(20).rename(
                        columns={"peringkat": "Peringkat", "sku": "SKU", "product_name": "Produk", "qty_total": "QTY terjual", "sales_total": "Sales", "m_qty": f"{pred_label} · QTY", "m_sales": f"{pred_label} · sales", "label_text": "Label"}
                    )
                    show_table(view)
                    download_excel(view, "laporan_terlaris.xlsx", key="xl-report-top")
                elif section == SECTIONS[3]:
                    if top.empty or "m_status" not in top.columns:
                        st.write("Data stok belum tersedia.")
                    else:
                        counts = top["m_status"].map(status_key).value_counts()
                        cols = st.columns(4)
                        for column, name in zip(cols, ("Aman", "Kurang", "Kosong", "Tanpa data stok")):
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
                    product_sales = float(ads["sales_produk_bersih"])
                    share = float(ads["porsi_sales_iklan_pct"])
                    warnings, notes = ad_validation(ad_result, product_sales)
                    for message in warnings:
                        st.warning(message)
                    cols = st.columns(4)
                    metric_card(cols[0], "biaya_iklan", fmt_idr(ad_cost))
                    metric_card(cols[1], "omzet_iklan", fmt_idr(ad_sales))
                    metric_card(cols[2], "roas", fmt_num(roas, 1))
                    card(cols[3], "Porsi sales dari iklan", fmt_pct(share), hint=f"dari sales produk bersih {fmt_idr(product_sales)}")
                    for message in notes:
                        st.caption(message)
                    st.caption(
                        "Porsi sales dari iklan = omzet iklan ÷ sales produk bersih (Harga Setelah Diskon × QTY, tanpa pesanan batal, "
                        "dikurangi retur). Dasar ini sama dengan batas omzet iklan per SKU. Sales bersih di kartu Ringkasan memakai "
                        "Total Pembayaran per pesanan (setelah voucher/koin, ditambah ongkir), jadi nilainya bisa berbeda."
                    )
                    if ad_cost <= 0:
                        st.caption("Laporan iklan belum diunggah, belum terpetakan ke SKU, atau tidak ada pada periode laporan.")
                    else:
                        ads = ad_result.per_sku.loc[ad_result.per_sku["biaya_iklan"] > 0].merge(table[["sku", "product_name", "m_status"]].drop_duplicates("sku"), on="sku", how="left")
                        ads = ads[["sku", "product_name", "biaya_iklan", "omzet_iklan", "m_status"]].copy()
                        ads["ROAS"] = ads["omzet_iklan"] / ads["biaya_iklan"]
                        ads = ads.sort_values("biaya_iklan", ascending=False).head(20)
                        show_table(ads.rename(columns={"sku": "SKU", "product_name": "Produk", "biaya_iklan": "Biaya", "omzet_iklan": "Omzet iklan", "m_status": "Status stok"}))
                elif section == SECTIONS[5]:
                    # Ikut periode laporan: 28 hari yang berakhir di hari terakhir periode laporan.
                    perf_end = (report_hi + pd.Timedelta(days=1)).date()
                    perf = store_performance(frames.performance, perf_end)
                    if not perf:
                        st.write("Data performa toko belum diunggah.")
                    else:
                        span_text = f"28 hari s.d. {fmt_date(report_hi.date(), short=True)}"
                        st.caption(f"Performa toko {span_text}, dibanding 28 hari sebelumnya.")
                        cols = st.columns(4)
                        card(cols[0], "Pengunjung", fmt_num(perf["pengunjung"]), hint=f"sebelumnya {fmt_num(perf['pengunjung_prev'])}")
                        card(cols[1], "Pesanan", fmt_num(perf["pesanan"]), hint=f"sebelumnya {fmt_num(perf['pesanan_prev'])}")
                        card(cols[2], "Konversi", fmt_pct(perf["konversi"], 2), hint=f"sebelumnya {fmt_pct(perf['konversi_prev'], 2)}")
                        card(cols[3], "Pembeli baru", fmt_num(perf["pembeli_baru"]))
                elif section == SECTIONS[6]:
                    cols = st.columns(4)
                    metric_card(cols[0], "pesanan_semua", fmt_num(facts["pesanan_semua"]), hint=f"bersih {fmt_num(facts['pesanan_bersih'])}")
                    metric_card(cols[1], "pesanan_batal", fmt_num(facts["pesanan_batal"]), hint=fmt_pct(cancel_rate))
                    metric_card(cols[2], "retur_unit", fmt_qty(facts["retur_unit"]), hint=f"{fmt_num(facts['pesanan_retur_penuh'])} pesanan diretur penuh")
                    metric_card(cols[3], "belum_bayar", fmt_num(unpaid), hint=f"{fmt_num(facts['belum_bayar_akun'])} akun")
                    if not reasons.empty:
                        per_cat = reasons.groupby("kategori")["orders"].sum().reindex(list(CATEGORIES), fill_value=0)
                        st.markdown("**Alasan batal per kategori**")
                        show_table(pd.DataFrame({"Kategori": per_cat.index, "Pesanan": per_cat.values.astype(int)}))
                        show_table(reasons.rename(columns={"reason": "Alasan batal", "orders": "Pesanan", "kategori": "Kategori"})[["Kategori", "Alasan batal", "Pesanan"]].head(10))
                elif section == SECTIONS[7]:
                    promo_days = int(promo_flag(pd.Series(pd.date_range(window_start, window_end))).sum())
                    context = {
                        "sales_growth_pct": growth,
                        "top50_share_pct": (
                            float(top["sales_total"].sum() / table["sales_total"].sum() * 100)
                            if not top.empty and table is not None and float(table["sales_total"].sum()) > 0
                            else None
                        ),
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
                    if records.empty:
                        st.write("Belum ada rekomendasi.")
                    else:
                        st.caption("Restock = max(0, prediksi + SS − stok DC). Tenggat = hari ini + stok ÷ prediksi harian (Segera bila sudah habis). PIC: restock lokal → Team DC; ada PO impor → Team IC/MD; harga/iklan → E-commerce.")
                        display = records_display(records.head(30))
                        show_table(display, kinds={"Stok Site 10037": "count", "Kebutuhan": "count", "Restock": "count"}, column_config={"Alasan": st.column_config.TextColumn(width="large")})
                        download_excel(records_display(records), "laporan_rekomendasi.xlsx", key="xl-report-adv")
                elif section == SECTIONS[10]:
                    days_in_month = pd.Timestamp(today).days_in_month
                    basis = target if target > 0 else month_pred
                    guide = work_guide(
                        {
                            "target_sales": basis,
                            "target_text": fmt_idr(basis),
                            "daily_target_text": fmt_idr(basis / days_in_month),
                            "target_roas": params.get("iklan", {}).get("target_roas", 8),
                        }
                    )
                    if target <= 0:
                        st.caption(f"Acuan panduan = {pred_label} (target belum diisi di Rekomendasi › Iklan).")
                    for name, tasks in guide.items():
                        st.markdown(f"**{name}**")
                        show_table(pd.DataFrame(tasks, columns=["Tugas", "Ukuran berhasil"]))
            except Exception as exc:  # satu bagian gagal tidak menghentikan laporan
                st.warning(f"Bagian ini belum bisa ditampilkan: {exc}")
