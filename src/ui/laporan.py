"""Tab Laporan: laporan per rentang tanggal (kalender), bisa disimpan lalu dibuka lagi tanpa menganalisa ulang.

Alur: pilih rentang → laporan dihitung dari data transaksi, iklan, performa toko, campaign tersimpan, dan hasil analisa
aktif → (opsional) simpan dengan nama. Laporan tersimpan berisi snapshot angka/tabel/grafik (src/core/report_data.py).
"""

from __future__ import annotations

import html
from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.core import report_data as R
from src.core import targets as T
from src.core.ads import ad_validation
from src.core.cancel_reasons import CATEGORIES, categorize_series, short_reason
from src.core.decision_table import PERIOD_LABELS, stock_shortage
from src.core.expert_system import FISHBONE_CATEGORIES, evaluate_rules, fishbone, sku_facts, swot, work_guide
from src.core.metrics import ads_metrics
from src.core.optimization import monte_carlo_stock_scenarios
from src.core.periods import format_period_label, last_full_month
from src.core.preprocessing import promo_flag
from src.core.restock import recommendation_records, records_display
from src.ui.common import (cached_order_metrics, card, date_range_picker, download_excel, explain, fmt_date, fmt_idr, fmt_idr_short, fmt_num,
                           fmt_pct, fmt_qty, metric_card, range_label, status_key)
from src.ui.targets_view import monthly_targets, target_roas_for
from src.utils.format import show_table

UP, DOWN = "#1d4ed8", "#dc2626"
ALL_SECTIONS = "Semua bagian (dibaca berurutan / dicetak)"
SECTIONS = (
    "1. Ringkasan eksekutif",
    "2. Target & tren penjualan",
    "3. Produk terlaris",
    "4. Prediksi & stok",
    "5. Iklan",
    "6. Campaign & kegiatan",
    "7. Performa toko",
    "8. Transaksi, batal & retur",
    "9. Analisa SWOT",
    "10. Analisa fishbone",
    "11. Rekomendasi",
    "12. Panduan kerja",
)
LIVE, SAVED = "Buat laporan", "Laporan tersimpan"


def _chip(text: str) -> str:
    return ("<span style='display:inline-block;margin:2px 6px 2px 0;padding:3px 10px;border-radius:999px;"
            f"background:#f1f5f9;color:#334155;font-size:var(--fs-xs);font-weight:600'>{html.escape(text)}</span>")


def _signed_pct(value) -> str:
    if value is None or not np.isfinite(value):
        return "–"
    return f"<b style='color:{UP if value >= 0 else DOWN}'>{fmt_pct(value, 1, signed=True)}</b>"


def _plot(fig: go.Figure, key: str, height: int = 380) -> None:
    fig.update_layout(height=height, separators=",.", margin=dict(l=40, r=20, t=40, b=40), template="plotly_white", legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, use_container_width=True, key=key)


def _cancel_mask(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty or "status" not in frame.columns:
        return pd.Series(False, index=frame.index if frame is not None else [])
    from src.ingest import cancelled_status_mask

    return cancelled_status_mask(frame["status"])


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
    out["reason"] = out["reason"].map(short_reason)
    out = out.groupby(["reason", "kategori"], as_index=False)["orders"].sum()
    return out.sort_values("orders", ascending=False).reset_index(drop=True)


def _top_advices(table: pd.DataFrame, today: date, limit: int = 8) -> pd.DataFrame:
    rows = []
    for _, row in table.head(50).iterrows():
        facts = sku_facts(row, today=today)
        short = facts.get("status_stok") in {"Kosong", "Kurang"}
        for advice in evaluate_rules(facts):
            if short and advice.action == "iklan" and advice.rule_id != "iklan_boros":
                continue
            rows.append({"Prioritas": advice.priority, "SKU": row["sku"], "Produk": row["product_name"], "Aksi": advice.action, "Rekomendasi": advice.text})
            break
    frame = pd.DataFrame(rows, columns=["Prioritas", "SKU", "Produk", "Aksi", "Rekomendasi"])
    return frame.sort_values(["Prioritas", "SKU"]).head(limit).reset_index(drop=True)


def _records(table: pd.DataFrame, today: date, data) -> pd.DataFrame:
    if table is None or table.empty:
        return pd.DataFrame()
    advice = {}
    adv = _top_advices(table, today, limit=50)
    for sku, text in zip(adv["SKU"].astype(str), adv["Rekomendasi"]):
        advice.setdefault(sku, str(text))
    return recommendation_records(table.head(50), today, po=getattr(data, "po", None), margin_pct=getattr(data, "margin_pct", None), advice=advice)


def _print_button() -> None:
    import streamlit.components.v1 as components

    components.html(
        "<button onclick='window.parent.print()' style='width:100%;padding:.5rem .75rem;border-radius:10px;"
        "border:1px solid #ee4d2d;background:#fff;color:#ee4d2d;font:600 14px sans-serif;cursor:pointer'>Cetak / Simpan PDF</button>",
        height=48,
    )
    st.caption("Di dialog cetak, pilih \"Simpan sebagai PDF\".")


# ---------------------------------------------------------------- menyusun snapshot

def build_snapshot(table, *, orders, orders_all, frames, params, today, period, metric, service, exclude, window_start, window_end, stock,
                   features, data, run_id: int, start: date, end: date) -> dict:
    """Semua angka/tabel laporan untuk rentang [start, end]."""
    span = (end - start).days + 1
    prev = R.previous_range(start, end)
    data_until = pd.to_datetime(orders_all["order_time"]).max().date() if isinstance(orders_all, pd.DataFrame) and not orders_all.empty else None
    month_targets = monthly_targets(features)
    facts = cached_order_metrics(orders_all, start, end, exclude)
    prev_facts = cached_order_metrics(orders_all, prev[0], prev[1], exclude)
    sales_now = float(facts["sales_bersih"])
    sales_prev = float(prev_facts["sales_bersih"]) if prev_facts["pesanan_semua"] > 0 else float("nan")
    growth = (sales_now - sales_prev) / sales_prev * 100 if np.isfinite(sales_prev) and sales_prev > 0 else float("nan")
    reach, _missing = T.achievement(sales_now, start, end, month_targets)
    roas_goal = (target_roas_for(features, f"{end.year:04d}-{end.month:02d}") if features is not None else None) or params.get("iklan", {}).get("target_roas", 8)

    daily = R.daily_orders(orders_all, start, end)
    month_lo = (pd.Timestamp(end) - pd.DateOffset(months=5)).replace(day=1).date()
    months = []
    for stamp in pd.period_range(month_lo, end, freq="M"):
        a, b = max(stamp.start_time.date(), month_lo), min(stamp.end_time.date(), end)
        if data_until is not None and a > data_until:
            continue
        m = cached_order_metrics(orders_all, a, min(b, data_until or b), exclude)
        key = str(stamp)
        months.append({"Bulan": T.month_label(key), "Kunci": key, "Sales bersih": float(m["sales_bersih"]), "Target": float(month_targets.get(key, 0) or 0),
                       "Sebagian": bool(data_until is not None and data_until < stamp.end_time.date())})
    monthly = pd.DataFrame(months)
    if not monthly.empty:
        monthly["Pencapaian (%)"] = np.where(monthly["Target"] > 0, monthly["Sales bersih"] / monthly["Target"].replace(0, 1) * 100, np.nan)

    top = R.top_products(orders, start, end, prev)

    ads = ads_metrics(frames.ads, frames.stock, orders_all, pd.Timestamp(start), pd.Timestamp(end))
    ad_result = ads["result"]
    warnings, notes = ad_validation(ad_result, float(ads["sales_produk_bersih"]))
    per_sku = pd.DataFrame()
    if ads["biaya_iklan"] > 0 and getattr(ad_result, "per_sku", None) is not None and not ad_result.per_sku.empty:
        names = orders.drop_duplicates("sku").set_index("sku")["product_name"] if orders is not None and not orders.empty else pd.Series(dtype=str)
        per_sku = ad_result.per_sku.loc[ad_result.per_sku["biaya_iklan"] > 0, ["sku", "biaya_iklan", "omzet_iklan"]].copy()
        per_sku["Produk"] = per_sku["sku"].map(names).fillna("")
        per_sku["ROAS"] = per_sku["omzet_iklan"] / per_sku["biaya_iklan"]
        per_sku = per_sku.sort_values("biaya_iklan", ascending=False).head(20).rename(columns={"sku": "SKU", "biaya_iklan": "Biaya", "omzet_iklan": "Omzet iklan"})
        per_sku = per_sku[["SKU", "Produk", "Biaya", "Omzet iklan", "ROAS"]]

    perf, perf_daily = R.performance_range(getattr(frames, "performance", None), start, end)
    report_all = orders_all
    if isinstance(orders_all, pd.DataFrame) and not orders_all.empty:
        stamps = pd.to_datetime(orders_all["order_time"]).dt.normalize()
        report_all = orders_all.loc[stamps.between(pd.Timestamp(start), pd.Timestamp(end))]
    reasons = _cancel_reasons(report_all)
    per_cat = reasons.groupby("kategori")["orders"].sum().reindex(list(CATEGORIES), fill_value=0) if not reasons.empty else pd.Series(dtype=float)
    campaigns = R.campaigns_in_range(features, start, end)

    month_col = "m_sales_exp" if table is not None and "m_sales_exp" in table.columns else "m_sales"
    month_pred = float(table[month_col].sum()) if table is not None and not table.empty and month_col in table.columns else 0.0
    pred_label = format_period_label("prediksi", window_start)
    top50 = table.head(50) if table is not None else pd.DataFrame()
    shortage = stock_shortage(top50) if not top50.empty else {"kurang": 0, "kosong": 0, "tanpa_data": 0}
    status_counts = top50["m_status"].map(status_key).value_counts().to_dict() if not top50.empty and "m_status" in top50.columns else {}
    mc_rows = []
    if not top50.empty and "m_status" in top50.columns:
        sigma_map = stock.set_index("item_key")["sigma_qty"].to_dict() if isinstance(stock, pd.DataFrame) and "sigma_qty" in stock.columns else {}
        lead = params.get("lead_time", {})
        for _, row in top50.head(10).iterrows():
            mc = monte_carlo_stock_scenarios(
                demand_mean=float(row["pred_harian"]), demand_sigma=float(sigma_map.get(row["item_key"], row["pred_harian"] * 0.5)),
                lead_time_mean=float(lead.get("lokal_hari", 7)), lead_time_sigma=float(lead.get("lokal_sigma_hari", 0) or 0),
                current_stock=float(row["stok"]) if bool(row.get("ada_data_stok", False)) else 0.0, safety_stock=float(row["ss"]),
            ).set_index("Skenario")
            mc_rows.append({"SKU": row["sku"], "Produk": row["product_name"], "Stok": row["stok"] if bool(row.get("ada_data_stok", False)) else None,
                            "SS": row["ss"], "ROP": row["rop"], "Restock moderat": round(mc.loc["Moderat", "Restock disarankan"]),
                            "Restock pesimistis": round(mc.loc["Pesimistis", "Restock disarankan"]), "Risiko stockout (%)": round(mc.loc["Moderat", "Risiko stockout"], 1)})
    pred_cols = ["peringkat", "sku", "product_name", "qty_total", "sales_total", "m_qty", "m_sales", "label_text"]
    pred_top = top50[[c for c in pred_cols if c in top50.columns]].head(20).rename(columns={
        "peringkat": "Rank", "sku": "SKU", "product_name": "Produk", "qty_total": "QTY terjual (analisa)", "sales_total": "Sales (analisa)",
        "m_qty": f"{pred_label} · QTY", "m_sales": f"{pred_label} · sales", "label_text": "Label"}) if not top50.empty else pd.DataFrame()
    records = _records(table, today, data)
    recs = records_display(records) if not records.empty else pd.DataFrame()

    cancel_rate = float(facts["tingkat_batal"] * 100)
    promo_days = int(promo_flag(pd.Series(pd.date_range(start, end))).sum())
    context = {
        "sales_growth_pct": growth,
        "top50_share_pct": float(top["Sales"].head(50).sum() / max(float(top["Sales"].sum()), 1) * 100) if not top.empty else None,
        "roas": ads["roas"], "target_roas": roas_goal, "cancel_pct": cancel_rate, "top50_short": shortage["kurang"], "unpaid_orders": int(facts["belum_bayar"]),
        "promo_days": promo_days,
        "poor_names": int((st.session_state.get("_name-recs", (None, pd.DataFrame()))[1].get("Status skor", pd.Series(dtype=str)) == "Poor").sum()) if st.session_state.get("_name-recs") else None,
        "dead_stock": int(table.get("productivity_label", pd.Series(dtype=str)).astype(str).str.contains("Dead|Slow", regex=True).sum()) if table is not None else None,
        "zero_stock": int(table["m_status"].map(status_key).eq("Kosong").sum()) if table is not None and "m_status" in table.columns else None,
    }
    saved_target = getattr(data, "target", None) or {}
    from src.core.business import business_targets

    target_month = business_targets(params, saved_target).target_sales
    basis = target_month if target_month > 0 else month_pred
    guide = work_guide({"target_sales": basis, "target_text": fmt_idr(basis), "daily_target_text": fmt_idr(basis / pd.Timestamp(today).days_in_month), "target_roas": roas_goal})

    return {
        "meta": {"mulai": start, "selesai": end, "label": range_label(start, end), "hari": span, "data_sd": data_until, "run_id": run_id,
                 "periode_lalu": f"{fmt_date(prev[0], short=True)} – {fmt_date(prev[1], short=True)}",
                 "chips": [f"Periode prediksi: {PERIOD_LABELS.get(period, period)}", f"Prediksi: {fmt_date(window_start, short=True)} – {fmt_date(window_end)}",
                           f"Parameter: {'QTY terjual' if metric == 'qty' else 'Sales value'}", f"Safety stock: {service}%",
                           "Kecualikan batal & retur: " + ("aktif" if exclude else "nonaktif")]},
        "kpi": {"sales_bersih": sales_now, "sales_prev": sales_prev, "growth": growth, "pesanan": facts["pesanan_semua"], "pesanan_bersih": facts["pesanan_bersih"],
                "pesanan_prev": prev_facts["pesanan_semua"], "batal": facts["pesanan_batal"], "tingkat_batal": cancel_rate, "retur_unit": facts["retur_unit"],
                "retur_penuh": facts["pesanan_retur_penuh"], "belum_bayar": facts["belum_bayar"], "belum_bayar_akun": facts["belum_bayar_akun"],
                "nominal_batal": facts["nominal_batal"], "nominal_retur": facts["nominal_retur"], "qty_bersih": facts["qty_bersih"],
                "aov": sales_now / facts["pesanan_bersih"] if facts["pesanan_bersih"] else 0.0,
                "target": reach.target if reach else None, "target_pct": reach.pct if reach else None,
                "target_bulan": reach.month_target if reach else None, "target_bulan_pct": reach.month_pct if reach else None},
        "daily": daily, "monthly": monthly, "top": top,
        "ads": {"biaya": ads["biaya_iklan"], "omzet": ads["omzet_iklan"], "roas": ads["roas"], "target_roas": roas_goal, "porsi": float(ads["porsi_sales_iklan_pct"]),
                "sales_produk": float(ads["sales_produk_bersih"]), "hari_iklan": int(ads.get("hari_iklan", 0) or 0), "peringatan": list(warnings), "catatan": list(notes),
                "per_sku": per_sku},
        "perf": perf, "perf_daily": perf_daily,
        "tx": {"reasons": reasons.rename(columns={"reason": "Alasan batal", "orders": "Pesanan", "kategori": "Kategori"}),
               "per_cat": pd.DataFrame({"Kategori": list(per_cat.index), "Pesanan": [int(v) for v in per_cat.values]})},
        "campaigns": campaigns,
        "swot": swot(context), "fishbone": fishbone(reasons),
        "pred": {"month_pred": month_pred, "label": pred_label, "target": target_month, "kurang": int(shortage["kurang"]), "kosong": int(shortage["kosong"]),
                 "tanpa_data": int(shortage["tanpa_data"]), "status": {k: int(v) for k, v in status_counts.items()}, "mc": pd.DataFrame(mc_rows), "top": pred_top,
                 "window": f"{fmt_date(window_start, short=True)} – {fmt_date(window_end, short=True)}"},
        "recs": recs,
        "guide": {name: pd.DataFrame(tasks, columns=["Tugas", "Ukuran berhasil"]) for name, tasks in guide.items()},
    }


# ---------------------------------------------------------------- menampilkan snapshot

def _s_summary(s: dict) -> None:
    k, ads, pred = s["kpi"], s["ads"], s["pred"]
    cols = st.columns(4)
    reach = f"<br>target {fmt_idr(k['target'])} · {_signed_pct(k['target_pct'] - 100)} dari target" if k.get("target") else ""
    metric_card(cols[0], "sales_bersih", fmt_idr(k["sales_bersih"]), hint=f"{_signed_pct(k['growth'])} vs {s['meta']['periode_lalu']}{reach}")
    card(cols[1], "Pesanan bersih", fmt_num(k["pesanan_bersih"]), hint=f"AOV {fmt_idr(k['aov'])} · batal {fmt_pct(k['tingkat_batal'], 1)}")
    metric_card(cols[2], "roas", fmt_num(ads["roas"], 1), hint=f"target {fmt_num(ads['target_roas'], 1)} · biaya iklan {fmt_idr_short(ads['biaya'])}")
    card(cols[3], "Top 50 stok kurang", fmt_num(pred["kurang"]), hint=f"{fmt_num(pred['kosong'])} stok 0 · dari analisa aktif")
    daily = s["daily"]
    if not daily.empty:
        fig = go.Figure(go.Scatter(x=pd.to_datetime(daily["Tanggal"]), y=daily["Sales bersih"], fill="tozeroy", line=dict(color="#1b3da6"), name="Sales bersih"))
        fig.update_layout(title="Sales bersih harian", yaxis_title="Rp", showlegend=False)
        _plot(fig, f"rp-sum-{id(s)}", 260)
    lines = []
    if k.get("target"):
        lines.append(f"Sales bersih {fmt_idr(k['sales_bersih'])} = {fmt_pct(k['target_pct'], 1)} dari target periode {fmt_idr(k['target'])}.")
    if np.isfinite(k.get("growth") or np.nan):
        lines.append(f"{'Naik' if k['growth'] >= 0 else 'Turun'} {fmt_pct(abs(k['growth']), 1)} dibanding periode sebelumnya ({s['meta']['periode_lalu']}).")
    lines.append(f"ROAS iklan {fmt_num(ads['roas'], 1)} vs target {fmt_num(ads['target_roas'], 1)}; omzet atribusi iklan setara {fmt_pct(ads['porsi'], 1)} sales produk bersih (atribusi Shopee ikut menghitung belanja produk lain setelah klik iklan, jadi bisa di atas 100%).")
    lines.append(f"Tingkat batal {fmt_pct(k['tingkat_batal'], 1)}; {fmt_num(k['belum_bayar'])} pesanan batal karena belum bayar bisa dikejar lewat chat.")
    lines.append(f"{fmt_num(pred['kurang'])} SKU Top 50 stoknya di bawah {pred['label']} + safety stock: prioritas restock sebelum menambah iklan.")
    st.markdown("\n".join(f"- {t}" for t in lines))
    if not s["recs"].empty:
        st.markdown("**Rekomendasi utama**")
        show_table(s["recs"].head(5), kinds={"Stok Site 10037": "count", "Kebutuhan": "count", "Restock": "count"})


def _s_trend(s: dict) -> None:
    k, daily, monthly = s["kpi"], s["daily"], s["monthly"]
    if k.get("target"):
        pct = float(k["target_pct"])
        st.markdown(
            f"<div style='margin:.3rem 0 .8rem'><div style='display:flex;justify-content:space-between;font-size:.85rem'><b>Pencapaian target periode</b>"
            f"<span>{fmt_idr(k['sales_bersih'])} / {fmt_idr(k['target'])} · <b style='color:{UP if pct >= 100 else DOWN}'>{fmt_pct(pct, 1)}</b></span></div>"
            f"<div style='height:14px;background:#e2e8f0;border-radius:999px;overflow:hidden'><div style='width:{min(pct, 100):.1f}%;height:100%;"
            f"background:{UP if pct >= 100 else '#ee4d2d'}'></div></div></div>", unsafe_allow_html=True)
    if not daily.empty:
        x = pd.to_datetime(daily["Tanggal"])
        fig = go.Figure()
        fig.add_bar(x=x, y=daily["Sales bersih"], name="Sales bersih", marker_color="#93c5fd")
        fig.add_scatter(x=x, y=daily["Sales bersih"].rolling(7, min_periods=1).mean(), name="Rata-rata 7 hari", line=dict(color="#1b3da6", width=3))
        if k.get("target"):
            fig.add_scatter(x=x, y=[k["target"] / len(daily)] * len(daily), name="Target harian", line=dict(color="#f59e0b", dash="dash"))
        fig.update_layout(title="Sales bersih harian", yaxis_title="Rp")
        _plot(fig, f"rp-trend-d-{id(s)}")
        if k.get("target"):
            cum = daily["Sales bersih"].cumsum()
            fig = go.Figure()
            fig.add_scatter(x=x, y=cum, name="Aktual kumulatif", fill="tozeroy", line=dict(color="#1b3da6"))
            fig.add_scatter(x=x, y=np.linspace(k["target"] / len(daily), k["target"], len(daily)), name="Laju target", line=dict(color="#f59e0b", dash="dash"))
            fig.update_layout(title="Kumulatif vs laju target", yaxis_title="Rp")
            _plot(fig, f"rp-trend-c-{id(s)}", 320)
    if not monthly.empty:
        fig = go.Figure()
        colors = ["#93a5d8" if p else "#1b3da6" for p in monthly["Sebagian"]]
        fig.add_bar(x=monthly["Bulan"], y=monthly["Sales bersih"], marker_color=colors, name="Sales bersih", text=[fmt_idr_short(v) for v in monthly["Sales bersih"]], textposition="outside")
        if (monthly["Target"] > 0).any():
            fig.add_scatter(x=monthly["Bulan"], y=monthly["Target"].where(monthly["Target"] > 0), name="Target bulanan", mode="lines+markers", line=dict(color="#f59e0b", dash="dash"))
        fig.update_layout(title="Sales bersih 6 bulan terakhir (batang muda = bulan belum penuh)", yaxis_title="Rp")
        _plot(fig, f"rp-trend-m-{id(s)}")
        view = monthly.assign(Status=np.where(monthly["Target"] <= 0, "", np.where(monthly["Sales bersih"] >= monthly["Target"], "✅ Tercapai",
                                                                                 np.where(monthly["Sebagian"], "⏳ Berjalan", "🔴 Tidak tercapai"))))
        show_table(view[["Bulan", "Sales bersih", "Target", "Pencapaian (%)", "Status"]], kinds={"Sales bersih": "money", "Target": "money", "Pencapaian (%)": "pct"})
    explain([("Sales bersih", "Total Pembayaran per pesanan − batal − retur (sama dengan kartu Ringkasan)"),
             ("Target", "dari Upload data › Target sales bulanan, diprorata bila rentang tidak sebulan penuh")])


def _s_products(s: dict) -> None:
    top = s["top"]
    if top.empty:
        st.write("Belum ada penjualan pada rentang ini.")
        return
    part = top.head(15).iloc[::-1]
    fig = go.Figure(go.Bar(x=part["Sales"], y=part["Produk"].str.slice(0, 45), orientation="h", marker_color="#1b3da6", text=[fmt_idr_short(v) for v in part["Sales"]], textposition="outside"))
    fig.update_layout(title="15 produk terlaris (sales produk bersih)", xaxis_title="Rp")
    _plot(fig, f"rp-top-{id(s)}", 480)
    fig = go.Figure(go.Treemap(labels=top["Produk"].str.slice(0, 30), parents=[""] * len(top), values=top["Sales"], textinfo="label+percent root"))
    fig.update_layout(title="Porsi sales 30 produk teratas")
    _plot(fig, f"rp-tree-{id(s)}", 380)
    show_table(top, kinds={"Sales": "money", "Sales periode lalu": "money", "Porsi (%)": "pct", "Perubahan (%)": "pct", "QTY": "count"},
               column_config={"Produk": st.column_config.TextColumn(width="large")})
    st.caption(f"Perubahan dibanding periode sebelumnya yang sama panjang ({s['meta']['periode_lalu']}).")


def _s_stock(s: dict) -> None:
    pred = s["pred"]
    st.caption(f"Bagian ini dari hasil analisa aktif (prediksi {pred['window']}), bukan dari rentang laporan.")
    cols = st.columns(4)
    card(cols[0], pred["label"], fmt_idr(pred["month_pred"]), hint=f"target bulan {fmt_idr(pred['target'])}" if pred["target"] else "")
    for column, name in zip(cols[1:], ("Aman", "Kurang", "Kosong")):
        card(column, f"Top 50 · {name}", fmt_num(pred["status"].get(name, 0)), hint="status stok bulan ini")
    if pred["status"]:
        fig = go.Figure(go.Pie(labels=list(pred["status"]), values=list(pred["status"].values()), hole=.5,
                               marker_colors=[{"Aman": UP, "Kurang": "#f59e0b", "Kosong": DOWN}.get(n, "#94a3b8") for n in pred["status"]]))
        fig.update_layout(title="Status stok Top 50")
        _plot(fig, f"rp-stock-{id(s)}", 300)
    if not pred["top"].empty:
        st.markdown("**20 produk teratas & prediksinya**")
        show_table(pred["top"])
    if not pred["mc"].empty:
        st.markdown("**Skenario Monte Carlo (1.000 simulasi permintaan × lead time) 10 SKU teratas**")
        show_table(pred["mc"], kinds={"SS": "count", "ROP": "count"})
        st.caption("ROP = permintaan harian × lead time + SS; restock pesimistis = kebutuhan kuantil 90%.")


def _s_ads(s: dict) -> None:
    ads = s["ads"]
    for message in ads["peringatan"]:
        st.warning(message)
    cols = st.columns(4)
    metric_card(cols[0], "biaya_iklan", fmt_idr(ads["biaya"]))
    metric_card(cols[1], "omzet_iklan", fmt_idr(ads["omzet"]))
    metric_card(cols[2], "roas", fmt_num(ads["roas"], 1), hint=f"target {fmt_num(ads['target_roas'], 1)}")
    card(cols[3], "Omzet iklan ÷ sales produk", fmt_pct(ads["porsi"]), hint=f"sales produk bersih {fmt_idr(ads['sales_produk'])} · bisa > 100% karena atribusi Shopee")
    for message in ads["catatan"]:
        st.caption(message)
    if 0 < ads["hari_iklan"] < s["meta"]["hari"]:
        st.caption(f"Laporan iklan hanya mencakup {ads['hari_iklan']} dari {s['meta']['hari']} hari rentang ini.")
    per_sku = ads["per_sku"]
    if isinstance(per_sku, pd.DataFrame) and not per_sku.empty:
        part = per_sku.head(15)
        fig = go.Figure()
        fig.add_bar(x=part["Produk"].str.slice(0, 25), y=part["Biaya"], name="Biaya", marker_color="#ee4d2d")
        fig.add_bar(x=part["Produk"].str.slice(0, 25), y=part["Omzet iklan"], name="Omzet iklan", marker_color="#1b3da6")
        fig.add_scatter(x=part["Produk"].str.slice(0, 25), y=part["ROAS"], name="ROAS", mode="markers+lines", yaxis="y2", line=dict(color="#f59e0b"))
        fig.update_layout(barmode="group", title="Biaya vs omzet iklan per produk", yaxis_title="Rp", yaxis2=dict(title="ROAS", overlaying="y", side="right"))
        _plot(fig, f"rp-ads-{id(s)}", 420)
        show_table(per_sku, kinds={"Biaya": "money", "Omzet iklan": "money", "ROAS": "dec"})
    elif ads["biaya"] <= 0:
        st.caption("Laporan iklan belum diunggah atau tidak ada pada rentang ini.")


def _s_campaigns(s: dict) -> None:
    camp = s["campaigns"]
    if camp is None or camp.empty:
        st.write("Tidak ada campaign tersimpan (iklan, flash sale, exposure) pada rentang ini.")
        return
    fig = go.Figure()
    colors = {"Iklan": "#ee4d2d", "Flash sale": "#1b3da6", "Exposure media sosial": "#0891b2"}
    for _, row in camp.iterrows():
        a, b = pd.Timestamp(row["Mulai"]), pd.Timestamp(row["Selesai"])
        fig.add_bar(y=[row["Campaign"]], x=[(b - a).days + 1], base=[a], orientation="h", marker_color=colors.get(row["Jenis"], "#94a3b8"), name=row["Jenis"],
                    hovertemplate=f"{row['Jenis']}: {row['Ringkasan']}<extra></extra>", showlegend=False)
    fig.add_vrect(x0=pd.Timestamp(s["meta"]["mulai"]), x1=pd.Timestamp(s["meta"]["selesai"]) + pd.Timedelta(days=1), fillcolor="#fde68a", opacity=.25, line_width=0)
    fig.update_layout(xaxis_type="date", title="Jadwal campaign (area kuning = rentang laporan)", yaxis=dict(autorange="reversed"))
    _plot(fig, f"rp-camp-{id(s)}", 120 + 40 * len(camp))
    show_table(camp, column_config={"Ringkasan": st.column_config.TextColumn(width="large")})


def _s_perf(s: dict) -> None:
    perf, daily = s["perf"], s["perf_daily"]
    if not perf:
        st.write("Data performa toko belum diunggah.")
        return

    def delta(now, then):
        return _signed_pct((now - then) / then * 100) if then and np.isfinite(then) and then > 0 and np.isfinite(now) else "–"

    cols = st.columns(4)
    card(cols[0], "Pengunjung", fmt_num(perf["pengunjung"]), hint=f"{delta(perf['pengunjung'], perf['pengunjung_prev'])} vs periode lalu")
    card(cols[1], "Pesanan (performa toko)", fmt_num(perf["pesanan"]), hint=f"{delta(perf['pesanan'], perf['pesanan_prev'])} vs periode lalu")
    card(cols[2], "Konversi (tertimbang)", fmt_pct(perf["konversi"], 2), hint=f"periode lalu {fmt_pct(perf['konversi_prev'], 2)}")
    card(cols[3], "Pembeli baru", fmt_num(perf["pembeli_baru"]), hint=f"{perf['hari']} hari data performa")
    if isinstance(daily, pd.DataFrame) and not daily.empty:
        x = pd.to_datetime(daily["Tanggal"])
        fig = go.Figure()
        if "Pengunjung" in daily:
            fig.add_bar(x=x, y=daily["Pengunjung"], name="Pengunjung", marker_color="#cbd5e1")
        if "Konversi (%)" in daily:
            fig.add_scatter(x=x, y=daily["Konversi (%)"], name="Konversi (%)", yaxis="y2", line=dict(color="#ee4d2d", width=3))
        fig.update_layout(title="Pengunjung & konversi harian", yaxis_title="Pengunjung", yaxis2=dict(title="Konversi (%)", overlaying="y", side="right"))
        _plot(fig, f"rp-perf-{id(s)}")


def _s_tx(s: dict) -> None:
    k, tx, daily = s["kpi"], s["tx"], s["daily"]
    cols = st.columns(4)
    metric_card(cols[0], "pesanan_semua", fmt_num(k["pesanan"]), hint=f"bersih {fmt_num(k['pesanan_bersih'])} · lalu {fmt_num(k['pesanan_prev'])}")
    metric_card(cols[1], "pesanan_batal", fmt_num(k["batal"]), hint=f"{fmt_pct(k['tingkat_batal'], 1)} · {fmt_idr_short(k['nominal_batal'])}")
    metric_card(cols[2], "retur_unit", fmt_qty(k["retur_unit"]), hint=f"{fmt_num(k['retur_penuh'])} pesanan diretur penuh · {fmt_idr_short(k['nominal_retur'])}")
    metric_card(cols[3], "belum_bayar", fmt_num(k["belum_bayar"]), hint=f"{fmt_num(k['belum_bayar_akun'])} akun")
    c1, c2 = st.columns(2)
    with c1:
        if not daily.empty:
            x = pd.to_datetime(daily["Tanggal"])
            fig = go.Figure()
            fig.add_bar(x=x, y=daily["Pesanan"], name="Pesanan", marker_color="#cbd5e1")
            fig.add_bar(x=x, y=daily["Pesanan batal"], name="Batal", marker_color=DOWN)
            fig.add_scatter(x=x, y=daily["Tingkat batal (%)"], name="Tingkat batal (%)", yaxis="y2", line=dict(color="#0f172a"))
            fig.update_layout(barmode="overlay", title="Pesanan & batal harian", yaxis2=dict(title="%", overlaying="y", side="right"))
            _plot(fig, f"rp-tx-{id(s)}")
    with c2:
        per_cat = tx["per_cat"]
        if not per_cat.empty and per_cat["Pesanan"].sum() > 0:
            fig = go.Figure(go.Pie(labels=per_cat["Kategori"], values=per_cat["Pesanan"], hole=.5))
            fig.update_layout(title="Alasan batal per kategori")
            _plot(fig, f"rp-txpie-{id(s)}")
    if not tx["reasons"].empty:
        show_table(tx["reasons"][["Kategori", "Alasan batal", "Pesanan"]].head(15))


def _s_swot(s: dict) -> None:
    colors = {"Strength": UP, "Weakness": DOWN, "Opportunity": "#0891b2", "Threat": "#b45309"}
    cols = st.columns(2)
    for index, (name, items) in enumerate((s["swot"] or {}).items()):
        color = colors.get(name, "#475569")
        cols[index % 2].markdown(
            f"<div style='border:1px solid #e2e8f0;border-top:5px solid {color};border-radius:12px;padding:.7rem 1rem;margin-bottom:.8rem;background:#fff'>"
            f"<b style='color:{color}'>{html.escape(str(name))}</b><ul style='margin:.3rem 0 0 1rem;padding:0'>"
            + "".join(f"<li>{html.escape(str(i))}</li>" for i in items) + "</ul></div>", unsafe_allow_html=True)


def _s_fishbone(s: dict) -> None:
    st.caption("Masalah utama: pembatalan pesanan. Angka = jumlah pesanan batal per alasan pada rentang laporan.")
    per_cat = s["tx"]["per_cat"]
    if not per_cat.empty and per_cat["Pesanan"].sum() > 0:
        part = per_cat.sort_values("Pesanan")
        fig = go.Figure(go.Bar(x=part["Pesanan"], y=part["Kategori"], orientation="h", marker_color="#ee4d2d", text=part["Pesanan"], textposition="outside"))
        fig.update_layout(title="Penyebab batal per kategori (tulang ikan)")
        _plot(fig, f"rp-fish-{id(s)}", 320)
    bones = s["fishbone"] or {}
    cols = st.columns(3)
    for index, category in enumerate(FISHBONE_CATEGORIES):
        with cols[index % 3].container(border=True):
            st.markdown(f"**{category}**")
            items = bones.get(category) or ["Tidak ada alasan pada kategori ini"]
            st.markdown("\n".join(f"- {item}" for item in items[:6]))


def _s_recs(s: dict) -> None:
    if s["recs"].empty:
        st.write("Belum ada rekomendasi (jalankan analisa).")
        return
    st.caption("Dari analisa aktif. Restock = max(0, prediksi + SS − stok DC). PIC: restock lokal → Team DC; PO impor → Team IC/MD; harga/iklan → E-commerce.")
    show_table(s["recs"].head(30), kinds={"Stok Site 10037": "count", "Kebutuhan": "count", "Restock": "count"}, column_config={"Alasan": st.column_config.TextColumn(width="large")})


def _s_guide(s: dict) -> None:
    for name, frame in (s["guide"] or {}).items():
        st.markdown(f"**{name}**")
        show_table(frame)


RENDER = dict(zip(SECTIONS, (_s_summary, _s_trend, _s_products, _s_stock, _s_ads, _s_campaigns, _s_perf, _s_tx, _s_swot, _s_fishbone, _s_recs, _s_guide)))


def render(s: dict, *, key: str) -> None:
    meta = s["meta"]
    st.markdown("".join(_chip(c) for c in meta.get("chips") or [])
                + _chip(f"Data transaksi s.d. {fmt_date(pd.Timestamp(meta['data_sd']).date(), short=True)}" if meta.get("data_sd") else "")
                + (_chip(f"Analisa #{meta['run_id']}") if meta.get("run_id") else ""), unsafe_allow_html=True)
    nav, body = st.columns([1, 4])
    with nav:
        st.markdown("**Daftar isi**")
        options = (ALL_SECTIONS,) + SECTIONS
        section = st.radio("Daftar isi", options, index=1, key=f"{key}-section", label_visibility="collapsed")
        if section == ALL_SECTIONS:
            _print_button()
        sheets = {"Harian": s["daily"], "Bulanan": s["monthly"], "Produk terlaris": s["top"], "Iklan per produk": s["ads"]["per_sku"],
                  "Campaign": s["campaigns"], "Performa harian": s["perf_daily"], "Alasan batal": s["tx"]["reasons"], "Prediksi Top 20": s["pred"]["top"],
                  "Monte Carlo": s["pred"]["mc"], "Rekomendasi": s["recs"]}
        download_excel({k: v for k, v in sheets.items() if isinstance(v, pd.DataFrame) and not v.empty}, f"laporan_{meta['mulai']}_{meta['selesai']}.xlsx",
                       key=f"xl-{key}", label="Unduh semua tabel (Excel)")
    with body:
        for name in (SECTIONS if section == ALL_SECTIONS else (section,)):
            st.markdown(f"<div class='section-title'>{html.escape(name)}</div>", unsafe_allow_html=True)
            st.caption(f"Periode laporan: {meta['label']} ({meta['hari']} hari)")
            try:
                RENDER[name](s)
            except Exception as exc:
                st.warning(f"Bagian ini belum bisa ditampilkan: {exc}")


# ---------------------------------------------------------------- halaman

def show_report(table: pd.DataFrame, *, orders: pd.DataFrame, orders_all: pd.DataFrame, frames, params: dict, today: date, period: str, metric: str,
                service: int, exclude: bool, window_start: date, window_end: date, stock: pd.DataFrame | None = None, features=None, data=None,
                run_id: int = 0, username: str = "", can_edit: bool = False) -> None:
    st.subheader("Laporan penjualan e-commerce Mitra10 × Shopee")
    store = R.ReportStore(features) if features is not None else None
    saved = store.all() if store is not None else []
    flash = st.session_state.pop("report-flash", None)
    if flash:
        st.success(flash)
    modes = [LIVE, f"{SAVED} ({len(saved)})"]
    pending = st.session_state.pop("report-mode-pending", None)
    if pending:
        st.session_state["report-mode"] = modes[1] if pending == SAVED else modes[0]
    if st.session_state.get("report-mode") not in modes:
        st.session_state["report-mode"] = modes[0]
    mode = st.segmented_control("Mode laporan", modes, key="report-mode", label_visibility="collapsed") if hasattr(st, "segmented_control") else st.radio("Mode", modes, horizontal=True)
    if mode == modes[1]:
        _saved_view(store, saved, username=username, can_edit=can_edit)
        return

    if orders_all is None or orders_all.empty:
        st.write("Belum ada transaksi untuk dilaporkan.")
        return
    stamps = pd.to_datetime(orders_all["order_time"], errors="coerce").dropna()
    lo, hi = stamps.min().date(), stamps.max().date()
    full_lo, full_hi = last_full_month(hi)
    default = (max(full_lo, lo), min(full_hi, hi)) if full_lo >= lo else (max(lo, hi.replace(day=1)), hi)
    with st.container(border=True):
        c1, c2 = st.columns([1.3, 2])
        with c1:
            start, end = date_range_picker(key="report-cal", lo=lo, hi=hi, default=default, label="Periode laporan")
        c2.markdown(f"<div class='field-hint' style='margin-top:1.9rem'>Semua angka, grafik & tabel mengikuti rentang ini. Bagian prediksi, stok & rekomendasi "
                    f"memakai analisa aktif{f' #{run_id}' if run_id else ''}. Data transaksi tersedia {fmt_date(lo, short=True)} – {fmt_date(hi, short=True)}.</div>",
                    unsafe_allow_html=True)
    cache_key = (run_id, start, end, bool(exclude), len(orders_all), str(hi))
    cached = st.session_state.get("report-live")
    if not (isinstance(cached, tuple) and cached[0] == cache_key):
        with st.spinner(f"Menyusun laporan {range_label(start, end)}..."):
            snapshot = build_snapshot(table, orders=orders, orders_all=orders_all, frames=frames, params=params, today=today, period=period, metric=metric,
                                      service=service, exclude=exclude, window_start=window_start, window_end=window_end, stock=stock, features=features,
                                      data=data, run_id=run_id, start=start, end=end)
        st.session_state["report-live"] = (cache_key, snapshot)
    else:
        snapshot = cached[1]
    with st.container(border=True):
        s1, s2 = st.columns([3, 1])
        name = s1.text_input("Nama laporan", value=f"Laporan {range_label(start, end)}", key=f"report-name-{start}-{end}", max_chars=80)
        s2.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        if s2.button("Simpan laporan", key="report-save", type="primary", disabled=not (can_edit and store is not None), use_container_width=True):
            report_id = store.save(snapshot, name=name.strip() or f"Laporan {range_label(start, end)}", username=username, now=datetime.now())
            st.session_state["report-flash"] = f"Laporan #{report_id} disimpan. Buka kapan saja dari \"{SAVED}\" tanpa menganalisa ulang."
            st.session_state["report-open"] = report_id
            st.session_state["report-mode-pending"] = SAVED
            st.rerun()
        st.caption("Laporan tersimpan menyimpan semua angka, tabel & grafik saat ini; dibuka lagi persis sama walau data atau analisa sudah berubah.")
    render(snapshot, key="report-live")


def _saved_view(store, saved: list[dict], *, username: str, can_edit: bool) -> None:
    if not saved:
        st.info("Belum ada laporan tersimpan. Buat laporan, pilih periodenya, lalu tekan Simpan laporan.")
        return
    labels = {int(r["id"]): f"#{r['id']} · {r.get('nama', '')} · dibuat {str(r.get('dibuat', ''))[:16]} oleh {r.get('dibuat_oleh', '')}" for r in saved}
    ids = list(labels)
    wanted = st.session_state.pop("report-open", None)
    if wanted in ids:
        st.session_state["report-pick"] = wanted
    if st.session_state.get("report-pick") not in ids:
        st.session_state["report-pick"] = ids[0]
    c1, c2 = st.columns([4, 1])
    pick = c1.selectbox("Laporan tersimpan", ids, format_func=labels.get, key="report-pick")
    with c2:
        st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        with st.popover("Hapus", use_container_width=True, disabled=not can_edit):
            st.write(f"Hapus laporan #{pick}?")
            if st.button("Ya, hapus", key=f"report-del-{pick}", type="primary"):
                store.delete(pick, username=username)
                st.session_state["report-flash"] = f"Laporan #{pick} dihapus."
                st.session_state["report-mode-pending"] = SAVED
                st.rerun()
    with st.expander("Daftar semua laporan tersimpan"):
        show_table(pd.DataFrame(saved).rename(columns={"id": "No", "nama": "Nama", "mulai": "Mulai", "selesai": "Selesai", "dibuat": "Dibuat", "dibuat_oleh": "Oleh",
                                                       "run": "Analisa", "data_sd": "Data s.d."}))
    cache = st.session_state.setdefault("report-saved-cache", {})
    if pick not in cache:
        cache.clear()
        cache[pick] = store.get(pick)
    snapshot = cache[pick]
    if not snapshot:
        st.warning("Isi laporan ini tidak ditemukan.")
        return
    meta = snapshot.get("meta") or {}
    st.markdown(f"<div class='field-hint'>Laporan tersimpan: <b>{html.escape(str(meta.get('nama', '')))}</b> · periode {html.escape(str(meta.get('label', '')))} · "
                f"dibuat {html.escape(str(meta.get('dibuat', ''))[:16])} oleh {html.escape(str(meta.get('dibuat_oleh', '')))}. Angka tidak dihitung ulang.</div>",
                unsafe_allow_html=True)
    render(snapshot, key=f"report-saved-{pick}")
