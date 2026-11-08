"""Prediksi › tabel ceklist, kartu penjelasan per SKU, Prediksi vs aktual harian (Revisi Final 4B)."""

from __future__ import annotations

import html
from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.core.decision_table import stock_need
from src.core.fmt import fmt_date, fmt_date_short
from src.core.pred_actual import STATUS_ORDER, daily_comparison, lost_sales_from_stock
from src.core.periods import format_period_label, last_full_month, same_day_last_month
from src.core.restock import stock_out_date
from src.ui.common import batched_view, card, download_excel, fmt_idr, fmt_num, fmt_pct, reset_batches, sku_cards, status_key
from src.ui.dashboard import status_badges
from src.ui.feature_data import FeatureData
from src.utils.format import show_table, table_height, wrap_layout

STEP = 20


def _actual_month(orders: pd.DataFrame | None, data_until: date) -> tuple[dict[str, float], date]:
    lo, hi = last_full_month(data_until)
    if orders is None or orders.empty:
        return {}, lo
    days = pd.to_datetime(orders["order_time"], errors="coerce").dt.date
    part = orders.loc[(days >= lo) & (days <= hi)]
    return part.groupby(part["item_key"].astype(str))["qty"].sum().to_dict(), lo


def _qty_on(orders: pd.DataFrame | None, day: date | None) -> dict[str, float]:
    if orders is None or orders.empty or day is None:
        return {}
    days = pd.to_datetime(orders["order_time"], errors="coerce").dt.date
    part = orders.loc[days == day]
    return part.groupby(part["item_key"].astype(str))["qty"].sum().to_dict()


def show_prediction_checklist(
    table: pd.DataFrame,
    *,
    orders: pd.DataFrame | None,
    today: date,
    window_start: date,
    data: FeatureData,
    label_options: list[str],
) -> None:
    st.markdown("<div class='section-title'>Pilih SKU</div>", unsafe_allow_html=True)
    if table is None or table.empty:
        st.write("Belum ada SKU untuk ditampilkan.")
        return
    data_until = pd.to_datetime(orders["order_time"]).max().date() if orders is not None and not orders.empty else today
    month_qty, month_lo = _actual_month(orders, data_until)
    pred_label = format_period_label("prediksi", window_start)
    actual_label = format_period_label("aktual_bulan", month_lo)
    f1, f2, f3 = st.columns([2.2, 1.4, 1.4])
    query = f1.text_input("Cari SKU atau nama produk", placeholder="Cari SKU atau nama produk..", key="chk-search")
    labels = f2.multiselect("Label", options=label_options, key="chk-labels", placeholder="Pilih")
    statuses = f3.multiselect("Status stok", options=["Aman", "Kurang", "Kosong", "Tanpa data stok"], key="chk-status", placeholder="Pilih")
    work = table
    needle = " ".join(str(query or "").lower().split())
    if needle:
        blob = (work["sku"].astype(str) + " " + work["product_name"].astype(str) + " " + work["variasi_tampil"].astype(str)).str.lower()
        work = work.loc[blob.str.contains(needle, regex=False)]
    if labels:
        work = work.loc[work["label"].map(lambda names: any(name in (names or []) for name in labels))]
    if statuses:
        work = work.loc[work["m_status"].map(status_key).isin(statuses)]
    page = work
    picked_before = set(st.session_state.get("chk-picked", []))
    frame = pd.DataFrame(
        {
            "Pilih": page["item_key"].astype(str).isin(picked_before).to_numpy(),
            "SKU": page["sku"].astype(str).to_numpy(),
            "Produk": page["product_name"].astype(str).to_numpy(),
            "Varian": page["variasi_tampil"].fillna("").astype(str).to_numpy(),
            pred_label: page["m_qty"].to_numpy(),
            actual_label: page["item_key"].astype(str).map(month_qty).fillna(0).to_numpy(),
            "Stok Site 10037": page["stok"].where(page["ada_data_stok"].astype(bool)).to_numpy(),
            "Stok Site 10062": page["stok_10062"].to_numpy() if "stok_10062" in page.columns else np.nan,
            "Stok Site 10036": page["stok_10036"].to_numpy() if "stok_10036" in page.columns else np.nan,
            "Ambil dari DC": page["sumber_restock"].fillna("").astype(str).to_numpy() if "sumber_restock" in page.columns else "",
            "SS": page["ss"].to_numpy(),
            "Status stok": page["m_status"].map(status_key).to_numpy(),
            "Label": page.get("label_text", pd.Series("", index=page.index)).fillna("").astype(str).to_numpy(),
            "_key": page["item_key"].astype(str).to_numpy(),
        }
    )
    for column in ("Stok Site 10062", "Stok Site 10036"):
        if frame[column].isna().all():
            frame = frame.drop(columns=column)
    if not frame["Ambil dari DC"].astype(str).str.strip().any():
        frame = frame.drop(columns="Ambil dari DC")
    shown_all = status_badges(frame, "Status stok")
    editor_cfg = {
        "Pilih": st.column_config.CheckboxColumn("Pilih", width="small"),
        pred_label: st.column_config.NumberColumn(format="localized"),
        actual_label: st.column_config.NumberColumn(format="localized"),
        "Stok Site 10037": st.column_config.NumberColumn(format="localized"),
        "Stok Site 10062": st.column_config.NumberColumn(format="localized"),
        "Stok Site 10036": st.column_config.NumberColumn(format="localized"),
        "Ambil dari DC": st.column_config.TextColumn(width="large"),
        "SS": st.column_config.NumberColumn(format="localized"),
        "Status stok": st.column_config.TextColumn(width="small"),
    }
    picked = set(picked_before)
    filter_sig = f"{needle}-{'|'.join(labels)}-{'|'.join(statuses)}"
    if st.session_state.get("chk-filter-sig") != filter_sig:
        st.session_state["chk-filter-sig"] = filter_sig
        reset_batches("chk")

    def _render(lo: int, hi: int) -> None:
        nonlocal picked
        part = shown_all.iloc[lo:hi]
        keys_part = frame["_key"].iloc[lo:hi]
        row_px, cfg = wrap_layout(part.drop(columns="_key"), dict(editor_cfg))
        edited = st.container(key=f"desktop-chk-editor-{lo}").data_editor(
            part.drop(columns="_key"),
            row_height=row_px,
            hide_index=True,
            use_container_width=True,
            disabled=[c for c in part.columns if c not in ("Pilih", "_key")],
            column_config=cfg,
            key=f"chk-editor-{hi}-{filter_sig}",
            height=table_height(len(part), 720, row_px),
        )
        # Centang per kelompok digabung; kelompok yang ditutup tetap menyimpan pilihannya.
        picked = (picked - set(keys_part)) | set(keys_part[edited["Pilih"].to_numpy()])
        sku_cards(
            [
                {
                    "sku": r["SKU"],
                    "produk": r["Produk"],
                    "varian": r["Varian"],
                    "status": r["Status stok"],
                    "nums": [(pred_label, fmt_num(r[pred_label])), (actual_label, fmt_num(r[actual_label])), ("Stok Site 10037", fmt_num(r["Stok Site 10037"])), ("SS", fmt_num(r["SS"]))] + ([("Ambil dari DC", r["Ambil dari DC"])] if r.get("Ambil dari DC") else []),
                }
                for r in frame.iloc[lo:hi].to_dict("records")
            ],
            key=f"chk-{lo}",
        )

    batched_view(len(frame), key="chk", render=_render, noun="SKU")
    keys_on_page = set(frame["_key"])
    names = dict(zip(frame["_key"], frame["SKU"] + " · " + frame["Produk"]))
    default = sorted(picked_before & keys_on_page)
    with st.container(key="mobile-chk-pick"):
        mobile_pick = st.multiselect("Pilih SKU untuk penjelasan", list(names), default=default, format_func=lambda k: names.get(k, k), placeholder="Pilih", key=f"chk-mpick-{hash(tuple(default))}")
    if sorted(mobile_pick) != default:
        picked = (picked_before - keys_on_page) | set(mobile_pick)
    st.session_state["chk-picked"] = sorted(picked)
    c2, c3 = st.columns([1, 3])
    with c2:
        download_excel(frame.drop(columns=["Pilih", "_key"]), "prediksi_pilih_sku.xlsx", key="xl-chk")
    c3.markdown(f"<div class='field-hint' style='text-align:right'>{fmt_num(len(work))} SKU sesuai saringan</div>", unsafe_allow_html=True)
    chosen = table.loc[table["item_key"].astype(str).isin(picked)]
    if chosen.empty:
        st.caption("Centang kolom Pilih untuk menampilkan penjelasan prediksi per SKU.")
        return
    last_day = data_until
    day_qty = _qty_on(orders, last_day)
    ago = same_day_last_month(last_day)
    ago_qty = _qty_on(orders, ago)
    for _, row in chosen.iterrows():
        _explain_card(row, pred_label=pred_label, actual_label=actual_label, month_qty=month_qty, last_day=last_day, day_qty=day_qty, ago=ago, ago_qty=ago_qty, today=today, data=data)


def _explain_card(row, *, pred_label, actual_label, month_qty, last_day, day_qty, ago, ago_qty, today, data: FeatureData) -> None:
    key = str(row["item_key"])
    variant = str(row.get("variasi_tampil") or "")
    title = " · ".join(p for p in (str(row["sku"]), str(row["product_name"]), variant) if p and p.lower() != "nan")
    known = bool(row.get("ada_data_stok", False))
    stok = float(row["stok"]) if known else None
    need = stock_need(row)
    restock = max(0.0, need - stok) if known else None
    habis = stock_out_date(stok, float(row["pred_harian"]), today) if known else None
    po = data.po.get(str(row["sku"]))
    with st.container(border=True):
        st.markdown(f"**{html.escape(title)}**")
        cols = st.columns(4)
        card(cols[0], pred_label, fmt_num(row["m_qty"]), hint=fmt_idr(row["m_sales"]))
        card(cols[1], actual_label, fmt_num(month_qty.get(key, 0)))
        card(cols[2], format_period_label("aktual_hari", last_day), fmt_num(day_qty.get(key, 0)), hint=f"prediksi {fmt_num(row['pred_harian'], 1)}/hari")
        card(cols[3], format_period_label("bulan_lalu", ago), fmt_num(ago_qty.get(key, 0)))
        parts = [
            f"Stok Site 10037 {fmt_num(stok) if known else 'belum ada data'}",
            f"kebutuhan {fmt_num(need)} (prediksi + SS)",
        ]
        if known:
            parts.append(f"restock {fmt_num(restock)}" + (f", tenggat {fmt_date_short(habis)}" if habis and restock else ""))
            for code in ("10062", "10036"):
                value = row.get(f"stok_{code}")
                if value is not None and pd.notna(value):
                    parts.append(f"Stok Site {code} {fmt_num(value)}")
            if restock and str(row.get("sumber_restock") or ""):
                parts.append(str(row["sumber_restock"]))
        parts.append(f"PO impor {po['no_po']} · {fmt_num(po['qty'])} unit · ETA {fmt_date(po['eta'])}" if po else "tidak ada PO impor terbuka")
        st.markdown(f"<div class='field-hint'>{html.escape(' · '.join(parts))}</div>", unsafe_allow_html=True)


def save_run_snapshot(features, run_id: int, table: pd.DataFrame, window_start: date, window_end: date, username: str) -> int:
    """prediction_snapshot: satu baris per SKU × tanggal di jendela prediksi (laju harian ensemble)."""
    if features is None or table is None or table.empty:
        return 0
    base = table.loc[table["pred_harian"] > 0, ["sku", "variasi_tampil", "pred_harian", "harga_bersih"]]
    if base.empty:
        return 0
    days = pd.date_range(window_start, window_end, freq="D").date
    frame = base.loc[base.index.repeat(len(days))].copy()
    frame["target_date"] = list(days) * len(base)
    frame = frame.rename(columns={"variasi_tampil": "varian", "pred_harian": "pred_qty"})
    frame["pred_sales"] = frame["pred_qty"] * frame["harga_bersih"]
    return features.save_prediction_snapshot(int(run_id), frame[["target_date", "sku", "varian", "pred_qty", "pred_sales"]], username=username)


def _snapshot_runs(features) -> pd.DataFrame:
    from sqlalchemy import func, select

    from src.core.feature_store import prediction_snapshot

    with features.engine.connect() as conn:
        rows = conn.execute(select(prediction_snapshot.c.run_id, func.min(prediction_snapshot.c.created_at)).group_by(prediction_snapshot.c.run_id)).all()
    return pd.DataFrame(rows, columns=["id", "run_at"])


def _comparison_for(features, runs: pd.DataFrame, lines: pd.DataFrame, day: date, stock: dict[str, float]) -> pd.DataFrame:
    eligible = runs.loc[pd.to_datetime(runs["run_at"]) < pd.Timestamp(day)]
    if eligible.empty:
        return pd.DataFrame()
    run_id = int(eligible.loc[pd.to_datetime(eligible["run_at"]).idxmax(), "id"])
    snap = features.read("prediction_snapshot", {"run_id": run_id, "target_date": day}).rename(columns={"target_date": "tanggal"})
    return daily_comparison(snap, lines, day, stock_by_sku=stock)


def show_pred_vs_actual(features, *, orders: pd.DataFrame | None, table: pd.DataFrame) -> None:
    st.markdown("<div class='section-title'>Prediksi vs aktual harian</div>", unsafe_allow_html=True)
    if features is None or orders is None or orders.empty:
        st.write("Belum ada data.")
        return
    try:
        runs = _snapshot_runs(features)
    except Exception as exc:
        st.info(f"Snapshot prediksi belum bisa dibaca: {exc}")
        return
    lines = orders.assign(sku=orders["sku"].astype(str))
    last = pd.to_datetime(lines["order_time"]).max().date()
    # Hari ini masih berjalan: bandingkan hari penuh terakhir agar % pencapaian tidak terlihat anjlok.
    partial_note = ""
    if last >= date.today():
        partial_note = f" Data {fmt_date(last)} belum satu hari penuh, jadi yang dibandingkan {fmt_date(last - timedelta(days=1))}."
        last = last - timedelta(days=1)
    stock = {str(s): float(v) for s, v, k in zip(table["sku"], table["stok"], table["ada_data_stok"]) if k} if table is not None and not table.empty else {}
    rows = _comparison_for(features, runs, lines, last, stock) if not runs.empty else pd.DataFrame()
    if rows.empty:
        st.info(
            f"Belum ada snapshot prediksi yang dibuat sebelum {fmt_date(last)}. Setiap analisa kini menyimpan prediksi harian; "
            "setelah transaksi hari berikutnya diunggah, perbandingan muncul di sini."
        )
        return
    pred_sales, actual_sales = float(rows["pred_sales"].sum()), float(rows["aktual_sales"].sum())
    hit = int(rows["status"].isin(["Melebihi", "Tercapai"]).sum())
    cols = st.columns(4)
    card(cols[0], f"Prediksi omzet {fmt_date(last)}", fmt_idr(pred_sales))
    card(cols[1], "Aktual omzet bersih", fmt_idr(actual_sales))
    card(cols[2], "% pencapaian", fmt_pct(actual_sales / pred_sales * 100 if pred_sales > 0 else float("nan"), 1))
    card(cols[3], "SKU tercapai + melebihi", f"{fmt_num(hit)} / {fmt_num(len(rows))}", hint="SKU yang punya prediksi pada hari itu")
    if partial_note:
        st.caption(partial_note.strip())
    trend = []
    for back in range(13, -1, -1):
        day = last - timedelta(days=back)
        part = _comparison_for(features, runs, lines, day, {})
        if not part.empty and part["pred_sales"].sum() > 0:
            trend.append((day, part["aktual_sales"].sum() / part["pred_sales"].sum() * 100))
    if trend:
        fig = go.Figure(go.Scatter(x=[d for d, _ in trend], y=[v for _, v in trend], mode="lines+markers+text", text=[f"{v:.0f}%" for _, v in trend], textposition="top center", line=dict(color="#1b3da6")))
        fig.add_hline(y=100, line_dash="dot", line_color="#94a3b8")
        fig.update_layout(
            height=280,
            margin=dict(l=30, r=20, t=20, b=30),
            yaxis_title="% pencapaian omzet",
            xaxis=dict(type="date", tickformat="%d/%m", dtick=86_400_000),  # satu label per hari
        )
        st.plotly_chart(fig, use_container_width=True, key="pva-trend")
    stock_miss = rows.loc[rows["status"].isin(["Hampir", "Tidak"]) & rows["penyebab"].astype(str).str.startswith("Stok")]
    st.markdown(
        f"<div class='field-hint'>{fmt_num(len(stock_miss))} SKU tidak tercapai karena stok; potensi omzet hilang "
        f"{fmt_idr(lost_sales_from_stock(rows))}.</div>",
        unsafe_allow_html=True,
    )
    names = table.drop_duplicates("sku").set_index(table["sku"].astype(str).drop_duplicates())["product_name"].to_dict() if table is not None and not table.empty else {}
    view = rows.assign(Produk=rows["sku"].map(names).fillna(""))
    view["_order"] = view["status"].map({s: i for i, s in enumerate(reversed(STATUS_ORDER))})
    view = view.sort_values(["_order", "pred_sales"], ascending=[True, False]).drop(columns="_order")
    view["pred_qty"] = pd.to_numeric(view["pred_qty"], errors="coerce").round(1)
    view = view.rename(columns={"sku": "SKU", "varian": "Varian", "pred_qty": "Prediksi QTY (laju harian)", "aktual_qty": "Aktual QTY", "pred_sales": "Prediksi omzet", "aktual_sales": "Aktual omzet", "pct": "% capaian", "status": "Status", "penyebab": "Penyebab"})
    show_table(view[["SKU", "Produk", "Varian", "Prediksi QTY (laju harian)", "Aktual QTY", "Prediksi omzet", "Aktual omzet", "% capaian", "Status", "Penyebab"]], max_height=420)
