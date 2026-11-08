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
from src.core.pred_actual import cause_group, daily_comparison, diagnose, lost_sales_from_stock, store_support
from src.core.periods import format_period_label, last_full_month, same_day_last_month
from src.core.restock import stock_out_date
from src.ui.common import batched_view, card, centered_download, page_navigator, download_excel, fmt_idr, fmt_num, fmt_pct, reset_batches, sku_cards, status_key
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

    batched_view(
        len(frame),
        key="chk",
        render=_render,
        noun="SKU",
        fragment=False,  # centang Pilih harus memperbarui penjelasan di bawah tabel (rerun penuh)
        download=lambda: download_excel(frame.drop(columns=["Pilih", "_key"]), "prediksi_pilih_sku.xlsx", key="xl-chk"),
    )
    keys_on_page = set(frame["_key"])
    names = dict(zip(frame["_key"], frame["SKU"] + " · " + frame["Produk"]))
    default = sorted(picked_before & keys_on_page)
    with st.container(key="mobile-chk-pick"):
        mobile_pick = st.multiselect("Pilih SKU untuk penjelasan", list(names), default=default, format_func=lambda k: names.get(k, k), placeholder="Pilih", key=f"chk-mpick-{hash(tuple(default))}")
    if sorted(mobile_pick) != default:
        picked = (picked_before - keys_on_page) | set(mobile_pick)
    st.session_state["chk-picked"] = sorted(picked)
    st.markdown(f"<div class='field-hint' style='text-align:right'>{fmt_num(len(work))} SKU sesuai saringan</div>", unsafe_allow_html=True)
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


def _comparison_for(features, runs: pd.DataFrame, lines: pd.DataFrame, day: date, stock: dict[str, float], table: pd.DataFrame | None = None) -> pd.DataFrame:
    """Prediksi vs aktual untuk tanggal D. Pakai snapshot analisa yang dibuat sebelum D; bila belum ada,
    pakai uji mundur (model harian yang sama, hanya data s.d. D−1). Kolom 'sumber' menandai asalnya."""
    eligible = runs.loc[pd.to_datetime(runs["run_at"]) < pd.Timestamp(day)] if runs is not None and not runs.empty else pd.DataFrame()
    if not eligible.empty:
        run_id = int(eligible.loc[pd.to_datetime(eligible["run_at"]).idxmax(), "id"])
        snap = features.read("prediction_snapshot", {"run_id": run_id, "target_date": day}).rename(columns={"target_date": "tanggal"})
        if not snap.empty:
            return daily_comparison(snap, lines, day, stock_by_sku=stock).assign(sumber="tersimpan")
    snap = _backtest_cached(lines, table, day)
    if snap.empty:
        return pd.DataFrame()
    return daily_comparison(snap, lines, day, stock_by_sku=stock).assign(sumber="uji mundur")


def _daily_matrix(lines: pd.DataFrame) -> pd.DataFrame:
    """Matriks QTY harian per SKU (baris = tanggal, kolom = SKU) dari transaksi bersih."""
    stamp = pd.to_datetime(lines["order_time"], errors="coerce").dt.normalize()
    work = pd.DataFrame({"day": stamp, "sku": lines["sku"].astype(str), "qty": pd.to_numeric(lines["qty"], errors="coerce").fillna(0.0)})
    work = work.dropna(subset=["day"])
    matrix = work.pivot_table(index="day", columns="sku", values="qty", aggfunc="sum", fill_value=0.0)
    return matrix.reindex(pd.date_range(matrix.index.min(), matrix.index.max(), freq="D"), fill_value=0.0)


def _backtest_cached(lines: pd.DataFrame, table: pd.DataFrame | None, day: date) -> pd.DataFrame:
    """Uji mundur disimpan per sesi (kunci: ukuran & jumlah data) agar tidak dihitung ulang tiap rerun."""
    if lines is None or lines.empty or table is None or table.empty:
        return pd.DataFrame(columns=["tanggal", "sku", "varian", "pred_qty", "pred_sales"])
    sig = (len(lines), float(pd.to_numeric(lines["qty"], errors="coerce").sum()), str(pd.to_datetime(lines["order_time"]).max()), len(table))
    store = st.session_state.setdefault("_backtest_cache", {})
    if store.get("sig") != sig:
        store.clear()
        store["sig"] = sig
        store["matrix"] = _daily_matrix(lines)
    key = str(day)
    if key not in store:
        store[key] = _backtest_snapshot(store["matrix"], table, day)
    return store[key]


def _backtest_snapshot(matrix: pd.DataFrame, table: pd.DataFrame | None, day: date) -> pd.DataFrame:
    """Prediksi 1 hari ke depan untuk tanggal D per SKU (uji mundur) dengan data s.d. D−1."""
    from src.forecast import _robust_forecast

    columns = ["tanggal", "sku", "varian", "pred_qty", "pred_sales"]
    if matrix is None or matrix.empty or table is None or table.empty:
        return pd.DataFrame(columns=columns)
    stamp = pd.Timestamp(day)
    history = matrix.loc[matrix.index < stamp]
    if len(history) < 7:
        return pd.DataFrame(columns=columns)
    total = history.sum(axis=1)
    profile = np.ones(7)
    means = total.groupby(total.index.dayofweek).mean()
    if means.mean() > 0:
        for dow, value in means.items():
            profile[int(dow)] = float(value) / float(means.mean())
    info = table.drop_duplicates("sku").set_index(table.drop_duplicates("sku")["sku"].astype(str))
    rows = []
    # Hanya SKU yang terjual dalam 90 hari terakhir sebelum D (SKU tidur diprediksi ~0 dan memperlambat).
    recent = history.iloc[-90:].sum(axis=0)
    active = set(recent.index[recent > 0])
    for sku in info.index:
        if sku not in history.columns or sku not in active:
            continue
        series = history[sku].to_numpy(dtype=float)
        nonzero = np.flatnonzero(series)
        if len(nonzero) == 0:
            continue
        series = series[nonzero[0]:]
        start = history.index[nonzero[0]]
        qty = float(_robust_forecast(series, start, 1, profile, forecast_start=stamp))
        if qty <= 0:
            continue
        price = float(info.at[sku, "harga_bersih"] or 0) if "harga_bersih" in info.columns else 0.0
        rows.append({"tanggal": day, "sku": sku, "varian": str(info.at[sku, "variasi_tampil"] or ""), "pred_qty": qty, "pred_sales": qty * price})
    return pd.DataFrame(rows, columns=columns)


def show_pred_vs_actual(features, *, orders: pd.DataFrame | None, table: pd.DataFrame, orders_all: pd.DataFrame | None = None) -> None:
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
    with st.spinner("Menyiapkan prediksi vs aktual..."):
        rows = _comparison_for(features, runs, lines, last, stock, table)
    if rows.empty:
        st.info(f"Belum cukup riwayat penjualan untuk membandingkan prediksi dengan aktual {fmt_date(last)}.")
        return
    if str(rows["sumber"].iloc[0]) == "uji mundur":
        st.caption(
            f"Belum ada analisa tersimpan yang dibuat sebelum {fmt_date(last)}, jadi prediksi hari itu dihitung ulang (uji mundur): "
            "model harian yang sama, hanya memakai data s.d. sehari sebelumnya."
        )
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
    with st.spinner("Menghitung tren pencapaian 7 hari..."):
        for back in range(6, -1, -1):
            day = last - timedelta(days=back)
            part = _comparison_for(features, runs, lines, day, {}, table)
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
    # Diagnosa penyebab per SKU (harga, stok, batal, pola jual, kondisi toko) + saran aksi.
    dc = {}
    if table is not None and not table.empty:
        for code in ("10062", "10036"):
            if f"stok_{code}" in table.columns:
                for sku, value in zip(table["sku"].astype(str), pd.to_numeric(table[f"stok_{code}"], errors="coerce").fillna(0.0)):
                    dc[sku] = dc.get(sku, 0.0) + float(value)
    rows = diagnose(rows, lines, last, lines_all=orders_all, stock_by_sku=stock, dc_by_sku=dc)
    rows["kelompok"] = rows["penyebab"].map(cause_group)
    rows["selisih"] = rows["aktual_sales"] - rows["pred_sales"]
    _cause_summary(rows, last, support=store_support(lines, last))

    names = table.drop_duplicates("sku").set_index(table["sku"].astype(str).drop_duplicates())["product_name"].to_dict() if table is not None and not table.empty else {}
    view = rows.assign(Produk=rows["sku"].map(names).fillna(""))
    # Prioritas dampak: selisih omzet aktual vs prediksi terbesar (meleset atau melebihi) lebih dulu.
    view["Selisih omzet"] = view["selisih"]
    view = view.sort_values("Selisih omzet", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
    view["pred_qty"] = pd.to_numeric(view["pred_qty"], errors="coerce").round(1)
    view = view.rename(columns={"sku": "SKU", "varian": "Varian", "pred_qty": "Prediksi QTY (laju harian)", "aktual_qty": "Aktual QTY", "pred_sales": "Prediksi omzet", "aktual_sales": "Aktual omzet", "pct": "% capaian", "status": "Status", "penyebab": "Penyebab", "aksi": "Saran aksi"})
    columns = ["SKU", "Produk", "Varian", "Prediksi QTY (laju harian)", "Aktual QTY", "Prediksi omzet", "Aktual omzet", "Selisih omzet", "% capaian", "Status", "Penyebab", "Saran aksi"]

    f1, f2, f3 = st.columns([1.3, 1.6, 0.8])
    status_pick = f1.multiselect("Status", options=["Tidak", "Hampir", "Tercapai", "Melebihi"], key="pva-status", placeholder="Semua")
    group_options = [g for g in view["kelompok"].value_counts().index.tolist()]
    cause_pick = f2.multiselect("Penyebab", options=group_options, key="pva-cause", placeholder="Semua")
    page_size = int(f3.selectbox("Baris/halaman", options=[5, 10, 20, 50, 100], index=0, key="pva-size"))
    if status_pick:
        view = view.loc[view["Status"].isin(status_pick)]
    if cause_pick:
        view = view.loc[view["kelompok"].isin(cause_pick)]
    view = view[columns].reset_index(drop=True)
    total = {c: "" for c in columns}
    total["SKU"] = "Total"
    total["Produk"] = f"{fmt_num(len(view))} SKU"
    for c in ("Prediksi QTY (laju harian)", "Aktual QTY", "Prediksi omzet", "Aktual omzet", "Selisih omzet"):
        total[c] = float(pd.to_numeric(view[c], errors="coerce").fillna(0).sum())
    total["% capaian"] = total["Aktual omzet"] / total["Prediksi omzet"] * 100 if total["Prediksi omzet"] else None
    total_row = pd.DataFrame([total], columns=columns)

    sig = (tuple(status_pick), tuple(cause_pick), page_size)
    if st.session_state.get("pva-sig") != sig:
        st.session_state["pva-sig"] = sig
        st.session_state["pva-page-n"] = 1
    pages = max((len(view) - 1) // page_size + 1, 1)
    page = min(max(int(st.session_state.get("pva-page-n", 1)), 1), pages)
    page = page_navigator(page, pages, key="pva-page", total=len(view), page_size=page_size, noun="SKU")
    st.markdown(
        "<div class='field-hint'>Urutan: selisih omzet aktual vs prediksi terbesar (paling berdampak) lebih dulu. Baris Total (sesuai filter) di atas.</div>",
        unsafe_allow_html=True,
    )
    show_table(
        pd.concat([total_row, view.iloc[(page - 1) * page_size : page * page_size]], ignore_index=True),
        bold_label="Total",
        kinds={"Prediksi omzet": "money", "Aktual omzet": "money", "Selisih omzet": "money", "% capaian": "pct"},
        max_height=10_000,
    )
    centered_download(
        "pva-dl",
        lambda: download_excel(pd.concat([total_row, view], ignore_index=True), f"prediksi_vs_aktual_{last:%Y%m%d}.xlsx", key="xl-pva"),
    )


def _cause_summary(rows: pd.DataFrame, day: date, support: tuple[float, float] = (np.nan, np.nan)) -> None:
    """Ringkasan penyebab: berapa SKU, dampak omzet, dan aksi utama — dari yang paling merugikan."""
    under = rows.loc[rows["status"].isin(["Hampir", "Tidak"])]
    over = rows.loc[rows["status"].eq("Melebihi")]
    actions = {
        "Stok": "isi stok dari DC 10062/10036 atau ajukan restock",
        "Harga naik": "tinjau harga — kembalikan/beri voucher toko, cek harga kompetitor",
        "Batal": "tindak lanjuti pembeli yang batal, cek alasan batal",
        "Dukungan Shopee berkurang": "voucher/diskon dari Shopee berkurang atau hilang — daftarkan SKU ke program Shopee atau ganti dengan voucher toko",
        "Tidak terjual": "cek stok di Shopee & status listing (nonaktif/diturunkan) — produk kemungkinan tidak tampil",
        "Permintaan turun": "cek iklan, ulasan, dan harga kompetitor; pertimbangkan promosi",
        "Laku tidak setiap hari": "wajar untuk SKU jarang laku; nilai per 7 hari, bukan per hari",
        "Seluruh toko sepi": "bukan masalah SKU; pantau besok",
        "Fluktuasi": "pantau; bertindak bila 3 hari berturut-turut di bawah prediksi",
    }
    items = []
    if not under.empty:
        grouped = under.groupby("kelompok").agg(n=("sku", "size"), gap=("selisih", "sum")).sort_values("gap")
        for name, row in grouped.iterrows():
            extra = ""
            if name == "Harga naik" and "harga_sejak" in under.columns:
                # Tanggal kenaikan harga yang paling banyak — membantu mengecek promo/campaign apa yang berakhir.
                dates = pd.to_datetime(under.loc[under["kelompok"].eq(name), "harga_sejak"].dropna()).dt.date.value_counts()
                dates = dates.loc[dates >= 2].sort_index(ascending=False).head(4)
                if len(dates):
                    extra = "<br><span class='field-hint'>Tanggal harga naik terbanyak: " + ", ".join(
                        f"{fmt_date(d)} ({fmt_num(int(n))} SKU)" for d, n in dates.items()
                    ) + " — cek promo/diskon apa yang berakhir pada tanggal itu.</span>"
            items.append(
                f"<li><b>{html.escape(name)}</b> — {fmt_num(int(row['n']))} SKU, omzet kurang {fmt_idr(abs(row['gap']))}"
                f" → <i>{html.escape(actions.get(name, 'pantau'))}</i>{extra}</li>"
            )
    up = ""
    if not over.empty:
        grouped = over.groupby("kelompok").agg(n=("sku", "size"), gap=("selisih", "sum")).sort_values("gap", ascending=False)
        parts = [f"{html.escape(name)} {fmt_num(int(r['n']))} SKU (+{fmt_idr(r['gap'])})" for name, r in grouped.iterrows()]
        up = f"<div class='field-hint' style='margin-top:.35rem'><b>Di atas prediksi:</b> {' · '.join(parts)}.</div>"
    sup_text = ""
    before, after = support
    if np.isfinite(before) and np.isfinite(after):
        move = after - before
        tone = "turun" if move < -1 else ("naik" if move > 1 else "stabil")
        sup_text = (
            f"<div class='field-hint' style='margin-top:.35rem'><b>Dukungan Shopee seluruh toko</b> (voucher + diskon dari Shopee): "
            f"{fmt_pct(before, 1)} dari omzet (14 hari sebelumnya) → {fmt_pct(after, 1)} (7 hari terakhir), <b>{tone}</b>.</div>"
        )
    lost = lost_sales_from_stock(rows)
    lost_text = f" Potensi omzet hilang karena stok: <b>{fmt_idr(lost)}</b>." if lost > 0 else ""
    st.markdown(
        f"<div class='tip-box' style='background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:.7rem .9rem;margin:.4rem 0 .6rem'>"
        f"<div style='font-weight:700;margin-bottom:.25rem'>Kenapa meleset pada {fmt_date(day)} &amp; apa yang dilakukan</div>"
        f"<div class='field-hint'>SKU di bawah prediksi, dikelompokkan menurut penyebab (paling merugikan di atas).{lost_text}</div>"
        f"<ul style='margin:.3rem 0 0 1.1rem;padding:0'>{''.join(items) or '<li>Tidak ada SKU di bawah prediksi.</li>'}</ul>{up}{sup_text}"
        "<div class='field-hint' style='margin-top:.35rem'><b>Cara baca:</b><br>"
        "• <b>Harga naik</b>: harga jual sekarang vs sebelum perubahan terakhir (30 hari). Disebut penyebab hanya bila laju jual SKU "
        "(maks. 14 hari sebelum vs sesudah perubahan) turun ≥15% <i>dan</i> lebih dalam dari tren pesanan toko di periode yang sama. "
        "Pesanan borongan dibatasi agar tidak menggelembungkan laju.<br>"
        "• <b>Dukungan Shopee</b>: voucher ditanggung Shopee + diskon dari Shopee per unit, sebelum vs sesudah (sekitar perubahan harga, "
        "atau 14 hari vs 7 hari terakhir); disebut penyebab bila berkurang ≥30% (≥3% harga) dan laju jual ikut turun lebih dalam dari toko. "
        "Harga bayar pembeli = harga jual − voucher Shopee − voucher toko.<br>"
        "• <b>Batal</b>: pesanan hari itu yang dibatalkan. <b>Pola jual</b>: 30 hari terakhir. <b>Toko</b>: total penjualan hari itu vs rata-rata 14 hari.</div>"
        "</div>",
        unsafe_allow_html=True,
    )
