"""Prediksi › tabel ceklist, kartu penjelasan per SKU, Prediksi vs aktual harian (Revisi Final 4B)."""

from __future__ import annotations

import html
from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.core.dc_stock import dc_take_label
from src.core.decision_table import stock_need
from src.core.fmt import fmt_date, fmt_date_short
from src.core.metrics import sold_lines
from src.core.pred_actual import (
    cause_group,
    complete_through,
    daily_comparison,
    diagnose,
    lost_sales_from_stock,
    store_support,
    unpaid_by_day,
)
from src.core.periods import format_period_label, last_full_month, same_day_last_month
from src.core.restock import stock_out_date
from src.ui.common import batched_view, card, page_navigator, download_excel, explain, fmt_idr, fmt_num, fmt_pct, reset_batches, sku_cards, status_key
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
            "Ambil dari DC": [dc_take_label(r) for _i, r in page.iterrows()] if "sumber_restock" in page.columns else "",
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
            if str(row.get("outstanding_10037") or "").strip() and str(row.get("outstanding_10037")) != "nan":
                parts.append(f"Outstanding Site 10037: {row['outstanding_10037']}")
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


def _day_shape(frame: pd.DataFrame, cutoff: date):
    """Pola harian (Senin–Minggu, gajian, tanggal kembar) yang sama dengan Pantauan harian; hasil: tanggal → pengali."""
    from src.core import month_track as M
    from src.ui.month_track_view import _daily_series

    net, _product, _stamp = _daily_series(frame)
    history = net.loc[pd.Timestamp(cutoff - timedelta(days=364)):pd.Timestamp(cutoff)] if len(net) else net
    profile = M.seasonal_profile(history)
    months: dict[date, dict[date, float]] = {}

    def factor(day: date) -> float:
        first = day.replace(day=1)
        if first not in months:
            months[first] = M.month_shape(profile, first)
        return float(months[first].get(day, 1.0))

    return factor


def _comparison_for(features, runs: pd.DataFrame, lines: pd.DataFrame, day: date, stock: dict[str, float], table: pd.DataFrame | None = None, shape=None,
                    sold: pd.DataFrame | None = None) -> pd.DataFrame:
    """Prediksi vs aktual untuk tanggal D. Pakai snapshot analisa yang dibuat sebelum D; bila belum ada,
    pakai uji mundur (model harian yang sama, hanya data s.d. D−1). Kolom 'sumber' menandai asalnya.
    Snapshot berisi laju datar; `shape(D)` menyebarnya menurut pola hari seperti di Pantauan harian."""
    eligible = runs.loc[pd.to_datetime(runs["run_at"]) < pd.Timestamp(day)] if runs is not None and not runs.empty else pd.DataFrame()
    if not eligible.empty:
        run_id = int(eligible.loc[pd.to_datetime(eligible["run_at"]).idxmax(), "id"])
        snap = features.read("prediction_snapshot", {"run_id": run_id, "target_date": day}).rename(columns={"target_date": "tanggal"})
        if not snap.empty:
            if shape is not None:
                scale = shape(day)
                snap = snap.assign(pred_qty=pd.to_numeric(snap["pred_qty"], errors="coerce") * scale,
                                   pred_sales=pd.to_numeric(snap["pred_sales"], errors="coerce") * scale)
            return daily_comparison(snap, lines, day, stock_by_sku=stock, sold=sold).assign(sumber="tersimpan")
    snap = _backtest_cached(lines, table, day)
    if snap.empty:
        return pd.DataFrame()
    return daily_comparison(snap, lines, day, stock_by_sku=stock, sold=sold).assign(sumber="uji mundur")


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
    every = orders_all if orders_all is not None else orders
    # Hari penuh terakhir dari seluruh pesanan, sama dengan Pantauan harian: hari ini dan data < 23:00 belum dinilai.
    last_stamp = pd.to_datetime(every["order_time"], errors="coerce").max()
    last = complete_through(last_stamp, date.today())
    partial_note = ""
    if last < last_stamp.date():
        partial_note = (f" Data {fmt_date(last_stamp.date())} sampai pukul {last_stamp:%H:%M}; "
                        + ("hari ini masih berjalan" if last_stamp.date() >= date.today() else "belum satu hari penuh")
                        + f", jadi yang dinilai s.d. {fmt_date(last)}.")
    unpaid = unpaid_by_day(every)
    shape = _day_shape(every, last)
    sold = sold_lines(every)
    sold = sold.assign(sku=sold["sku"].astype(str))
    stock = {str(s): float(v) for s, v, k in zip(table["sku"], table["stok"], table["ada_data_stok"]) if k} if table is not None and not table.empty else {}
    with st.spinner("Menyiapkan prediksi vs aktual..."):
        rows = _comparison_for(features, runs, lines, last, stock, table, shape=shape, sold=sold)
    if rows.empty:
        st.info(f"Belum cukup riwayat penjualan untuk membandingkan prediksi dengan aktual {fmt_date(last)}.")
        return
    if str(rows["sumber"].iloc[0]) == "uji mundur":
        st.caption(
            f"Belum ada analisa tersimpan yang dibuat sebelum {fmt_date(last)}, jadi prediksi hari itu dihitung ulang (uji mundur): "
            "model harian yang sama, hanya memakai data s.d. sehari sebelumnya."
        )
    with st.spinner("Menyiapkan breakdown per tanggal bulan ini..."):
        month = _month_breakdown(features, runs, lines, last, last_stamp, table, unpaid, shape, sold=sold)
    month, target = _with_target(features, month, every, last)
    pred_sales, actual_sales = float(rows["pred_sales"].sum()), float(rows["aktual_sales"].sum())
    hit = int(rows["status"].isin(["Melebihi", "Tercapai"]).sum())
    cols = st.columns(4)
    card(cols[0], f"Prediksi sales produk {fmt_date(last)}", fmt_idr(pred_sales), hint="SKU berprediksi · Harga Setelah Diskon × QTY")
    # Seluruh toko = sales bersih toko hari itu dan target harian berpola, sama dengan baris tanggal itu di tabel breakdown.
    from src.ui.month_track_view import _daily_series

    net_day, _product, _stamp = _daily_series(every)
    day_total = float(net_day.get(pd.Timestamp(last), 0.0))
    reach = ""
    if target:
        goal = month.loc[month["tanggal"] == last, "target"]
        if len(goal) and float(goal.iloc[0]) > 0:
            pct = day_total / float(goal.iloc[0]) * 100
            reach = (f"Target harian {fmt_idr(float(goal.iloc[0]))} → "
                     f"<b style='color:{'#1d4ed8' if pct >= 100 else '#dc2626'}'>{fmt_pct(pct, 1)}</b>")
    card(cols[1], "Aktual sales produk", fmt_idr(actual_sales),
         hint=("SKU berprediksi · tanpa batal & Belum Bayar, setelah retur"
               f"<br>Sales bersih seluruh toko (dasar target, setelah voucher) {fmt_idr(day_total)}") + (f"<br>{reach}" if reach else ""))
    pending = float(unpaid.loc[(unpaid["tanggal"] == last) & unpaid["sku"].isin(set(rows["sku"].astype(str))), "belum_bayar"].sum())
    pct_hint = (
        f"Masih Belum Bayar {fmt_idr(pending)}; bila dibayar semua → {fmt_pct((actual_sales + pending) / pred_sales * 100, 1)}"
        if pending > 0 and pred_sales > 0 else "")
    card(cols[2], "% pencapaian prediksi", fmt_pct(actual_sales / pred_sales * 100 if pred_sales > 0 else float("nan"), 1), hint=pct_hint)
    card(cols[3], "SKU tercapai + melebihi", f"{fmt_num(hit)} / {fmt_num(len(rows))}", hint="SKU yang punya prediksi pada hari itu")
    if partial_note:
        st.caption(partial_note.strip())
    _month_chart(month, last, target)
    _month_table(month, last, target)
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
    view = view.rename(columns={"sku": "SKU", "varian": "Varian", "pred_qty": "Prediksi QTY (laju harian)", "aktual_qty": "Aktual QTY", "pred_sales": "Prediksi sales produk", "aktual_sales": "Aktual sales produk", "pct": "% capaian", "status": "Status", "penyebab": "Penyebab", "aksi": "Saran aksi"})
    columns = ["SKU", "Produk", "Varian", "Prediksi QTY (laju harian)", "Aktual QTY", "Prediksi sales produk", "Aktual sales produk", "Selisih omzet", "% capaian", "Status", "Penyebab", "Saran aksi"]

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
    for c in ("Prediksi QTY (laju harian)", "Aktual QTY", "Prediksi sales produk", "Aktual sales produk", "Selisih omzet"):
        total[c] = float(pd.to_numeric(view[c], errors="coerce").fillna(0).sum())
    total["% capaian"] = total["Aktual sales produk"] / total["Prediksi sales produk"] * 100 if total["Prediksi sales produk"] else None
    total_row = pd.DataFrame([total], columns=columns)

    sig = (tuple(status_pick), tuple(cause_pick), page_size)
    if st.session_state.get("pva-sig") != sig:
        st.session_state["pva-sig"] = sig
        st.session_state["pva-page-n"] = 1
    pages = max((len(view) - 1) // page_size + 1, 1)
    page = min(max(int(st.session_state.get("pva-page-n", 1)), 1), pages)
    page = page_navigator(
        page, pages, key="pva-page", total=len(view), page_size=page_size, noun="SKU",
        download=lambda: download_excel(pd.concat([total_row, view], ignore_index=True), f"prediksi_vs_aktual_{last:%Y%m%d}.xlsx", key="xl-pva"),
    )
    st.markdown(
        "<div class='field-hint'>Urutan: selisih omzet aktual vs prediksi terbesar (paling berdampak) lebih dulu. Baris Total (sesuai filter) di atas.</div>",
        unsafe_allow_html=True,
    )
    show_table(
        pd.concat([total_row, view.iloc[(page - 1) * page_size : page * page_size]], ignore_index=True),
        bold_label="Total",
        kinds={"Prediksi sales produk": "money", "Aktual sales produk": "money", "Selisih omzet": "money", "% capaian": "pct"},
        max_height=10_000,
    )


HARI = ("Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min")
ID_MONTHS = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember")


def _future_predictions(features, runs: pd.DataFrame) -> pd.Series:
    """Prediksi omzet per tanggal dari analisa terbaru (untuk tanggal yang belum terjadi)."""
    if runs is None or runs.empty:
        return pd.Series(dtype=float)
    run_id = int(runs.loc[pd.to_datetime(runs["run_at"]).idxmax(), "id"])
    snap = features.read("prediction_snapshot", {"run_id": run_id})
    if snap.empty:
        return pd.Series(dtype=float)
    days = pd.to_datetime(snap["target_date"], errors="coerce").dt.date
    return pd.to_numeric(snap["pred_sales"], errors="coerce").fillna(0.0).groupby(days).sum()


def _month_breakdown(features, runs, lines, last: date, last_stamp, table, unpaid: pd.DataFrame, shape, sold: pd.DataFrame | None = None) -> pd.DataFrame:
    """Satu baris per tanggal dari tgl 1 s.d. akhir bulan (bulan hari penuh terakhir), basis SKU berprediksi.

    Selesai: prediksi H-1 (snapshot sebelum tanggal itu / uji mundur) vs aktual bersih + Belum Bayar.
    Berjalan: hari yang datanya belum penuh. Akan datang: prediksi analisa terbaru."""
    start = last.replace(day=1)
    end = (pd.Timestamp(start) + pd.offsets.MonthEnd(0)).date()
    data_day = pd.Timestamp(last_stamp).date()
    future = _future_predictions(features, runs)
    flat = float(future.mean()) if len(future) else np.nan
    out = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        row = {"tanggal": day, "prediksi": np.nan, "aktual": np.nan, "belum_bayar": np.nan, "status": "Akan datang",
               "sumber": "analisa terbaru", "pola": shape(day)}
        if day <= data_day:
            part = _comparison_for(features, runs, lines, day, {}, table, shape=shape, sold=sold)
            row["status"] = "Selesai" if day <= last else "Berjalan"
            if not part.empty:
                skus = set(part["sku"].astype(str))
                row.update(
                    prediksi=float(part["pred_sales"].sum()),
                    aktual=float(part["aktual_sales"].sum()),
                    belum_bayar=float(unpaid.loc[(unpaid["tanggal"] == day) & unpaid["sku"].isin(skus), "belum_bayar"].sum()),
                    sumber="analisa H-1" if str(part["sumber"].iloc[0]) == "tersimpan" else "uji mundur",
                )
        else:
            row["prediksi"] = float(future.get(day, flat)) * shape(day)
        out.append(row)
    frame = pd.DataFrame(out)
    frame["pct"] = np.where(frame["prediksi"] > 0, frame["aktual"] / frame["prediksi"] * 100, np.nan)
    frame["pct_bayar"] = np.where(frame["prediksi"] > 0, (frame["aktual"] + frame["belum_bayar"].fillna(0)) / frame["prediksi"] * 100, np.nan)
    return frame


def _with_target(features, month: pd.DataFrame, frame_all: pd.DataFrame, last: date) -> tuple[pd.DataFrame, dict | None]:
    """Target harian = target bulan (sales bersih seluruh toko) dibagi per tanggal dengan pola hari (sama dengan
    Pantauan harian), totalnya tetap target bulan. Dibandingkan dengan sales bersih toko (basis yang sama), bukan
    dengan batang SKU. ratio = aktual SKU ÷ sales bersih toko s.d. kemarin, untuk mengubah prediksi sisa ke sales bersih."""
    from src.ui.month_track_view import _daily_series
    from src.ui.targets_view import monthly_targets

    month = month.assign(target=np.nan, bersih=np.nan)
    if month.empty or features is None:
        return month, None
    first = month["tanggal"].iloc[0]
    target = monthly_targets(features).get(f"{first.year:04d}-{first.month:02d}")
    if not target:
        return month, None
    done = month["status"].eq("Selesai")
    net, product, _stamp = _daily_series(frame_all)
    by_day = {pd.Timestamp(k).date(): float(v) for k, v in net.items()}
    month.loc[done, "bersih"] = [by_day.get(d, 0.0) for d in month.loc[done, "tanggal"]]
    net_done = float(month.loc[done, "bersih"].sum())
    chart_done = float(month.loc[done, "aktual"].fillna(0).sum())
    ratio = chart_done / net_done if net_done > 0 and chart_done > 0 else 1.0
    from src.ui.month_track_view import net_factor

    factor = net_factor(net, product, first, last, last)
    pola = month["pola"].astype(float)
    month["target"] = target * pola / pola.sum()
    projection = None
    try:
        from src.ui.month_track_view import month_state

        state = month_state(features, frame_all, first)
        if state and state.get("cutoff") == last:
            projection = float(state["summary"]["proyeksi"])
    except Exception:
        projection = None
    return month, {"target": float(target), "ratio": ratio, "factor": factor, "proyeksi": projection}


def _month_chart(month: pd.DataFrame, last: date, target: dict | None = None) -> None:
    if month.empty or month["prediksi"].isna().all():
        return
    x = pd.to_datetime(month["tanggal"])
    done = month["status"].eq("Selesai")
    fig = go.Figure()
    fig.add_bar(x=x, y=month["prediksi"], name="Prediksi", offsetgroup="p", marker_color=np.where(done, "#a5b4fc", "#e0e7ff").tolist(),
                hovertemplate="%{x|%d/%m} · Prediksi Rp %{y:,.0f}<extra></extra>")
    fig.add_bar(x=x, y=month["aktual"], name="Aktual sales produk", offsetgroup="a", marker_color="#1b3da6",
                text=[f"{v:.0f}%" if np.isfinite(v) and s == "Selesai" else "" for v, s in zip(month["pct"], month["status"])],
                textposition="outside", cliponaxis=False, hovertemplate="%{x|%d/%m} · Aktual Rp %{y:,.0f}<extra></extra>")
    if month["belum_bayar"].fillna(0).sum() > 0:
        fig.add_bar(x=x, y=month["belum_bayar"], base=month["aktual"].fillna(0), name="Belum Bayar", offsetgroup="a", marker_color="#fbbf24",
                    hovertemplate="%{x|%d/%m} · Belum Bayar Rp %{y:,.0f}<extra></extra>")
    if target:
        fig.add_scatter(x=x, y=month["target"], name="Target harian", mode="lines+markers", line=dict(color="#dc2626", dash="dash", width=2),
                        marker=dict(size=5), hovertemplate="%{x|%d/%m} · Target Rp %{y:,.0f}<extra></extra>")
    fig.add_vline(x=pd.Timestamp(last) + pd.Timedelta(hours=12), line_dash="dot", line_color="#94a3b8")
    fig.update_layout(
        height=340, barmode="group", bargap=0.25, bargroupgap=0.05,
        margin=dict(l=30, r=20, t=30, b=30),
        legend=dict(orientation="h", y=1.12, x=0),
        yaxis=dict(title="Omzet (Rp)", tickformat=",.0f"),
        xaxis=dict(type="date", tickformat="%d", dtick=86_400_000),
        separators=",.",
    )
    st.plotly_chart(fig, use_container_width=True, key="pva-month")
    target_text = " Target bulan ini belum diisi (menu Target sales)."
    if target:
        gap = (target["ratio"] - 1) * 100
        target_text = (
            f" Garis merah = target harian: target bulan ini {fmt_idr(target['target'])} dibagi per tanggal dengan pola hari. "
            f"Target memakai sales bersih seluruh toko; batang memakai sales produk SKU berprediksi, yang bulan ini "
            f"{abs(gap):.0f}% {'di atas' if gap >= 0 else 'di bawah'} sales bersih. Pencapaian target dihitung di tabel dengan sales bersih toko.")
    st.caption(
        f"Tanggal 1 s.d. akhir bulan, basis SKU yang diprediksi. Angka % di atas batang = aktual ÷ prediksi (hanya hari penuh). "
        f"Garis putus-putus = hari penuh terakhir ({fmt_date(last)}); sesudahnya prediksi dari analisa terbaru. "
        "Laju harian analisa disebar dengan pola hari yang sama dengan Pantauan harian (Senin–Minggu, gajian, tanggal kembar), "
        "total sebulan tetap. Pantauan harian memakai sales bersih seluruh toko, jadi angkanya berbeda sebesar faktor sales bersih ÷ sales produk. "
        "Kuning = pesanan masih Belum Bayar (belum dihitung terjual; sebagian dibayar 1–3 hari kemudian, sisanya batal)."
        + target_text)


def accuracy(actual, predicted) -> float:
    """Akurasi prediksi harian: 100% − |aktual − prediksi| ÷ aktual (min. 0%). Aktual 0 → 100% bila prediksi juga 0, selain itu 0%."""
    a = pd.to_numeric(pd.Series([actual]), errors="coerce").iat[0]
    p = pd.to_numeric(pd.Series([predicted]), errors="coerce").iat[0]
    if pd.isna(a) or pd.isna(p):
        return np.nan
    if a <= 0:
        return 100.0 if p <= 0 else 0.0
    return max(0.0, 100 - abs(a - p) / a * 100)


def _month_table(month: pd.DataFrame, last: date, target: dict | None = None) -> None:
    if month.empty:
        return
    done_days = month["status"].eq("Selesai")
    from src.core.month_track import day_label

    view = pd.DataFrame({
        "Tanggal": [f"{HARI[d.weekday()]} {fmt_date(d)}" for d in month["tanggal"]],
        "Jenis hari": [day_label(d) for d in month["tanggal"]],
        "Pola hari": [f"×{p:.2f}".replace(".", ",") if s != "uji mundur" else "pola model" for p, s in zip(month["pola"], month["sumber"])],
        "Status": month["status"],
        "Target harian": month["target"],
        "Prediksi sales produk": month["prediksi"],
        "Aktual sales produk": month["aktual"],
        "Sales bersih toko": month["bersih"],
        "% target": np.where(done_days & (month["target"] > 0), month["bersih"] / month["target"] * 100, np.nan),
        # Padanan kartu Pantauan harian (basis sales bersih toko): prediksi sales produk × faktor sales bersih ÷ sales produk.
        "Prediksi sales bersih": month["prediksi"] * (float(target["factor"]) if target else np.nan),
        "Achievement bersih": np.where(done_days & (month["prediksi"] > 0) & bool(target),
                                       month["bersih"] / (month["prediksi"] * (float(target["factor"]) if target else 1.0)) * 100, np.nan),
        "Belum Bayar": month["belum_bayar"],
        "Selisih": month["aktual"] - month["prediksi"],
        "% capaian": month["pct"],
        "Akurasi prediksi": [accuracy(a, p) if s == "Selesai" else np.nan for a, p, s in zip(month["aktual"], month["prediksi"], month["status"])],
        "% bila Belum Bayar dibayar": month["pct_bayar"],
        "Sumber prediksi": month["sumber"],
    })
    # Sel kosong (tanggal mendatang / belum ada data) sebagai NaN agar tampil "-" bukan "None".
    for column in view.columns.drop(["Tanggal", "Jenis hari", "Pola hari", "Status", "Sumber prediksi"]):
        view[column] = pd.to_numeric(view[column], errors="coerce")
    if not target:
        view = view.drop(columns=["Target harian", "Sales bersih toko", "% target", "Prediksi sales bersih", "Achievement bersih"])
    done = month["status"].eq("Selesai")
    pred, act, pend = (float(month.loc[done, c].fillna(0).sum()) for c in ("prediksi", "aktual", "belum_bayar"))
    label = f"Total s.d. {fmt_date(last)}"
    total = {
        "Tanggal": label, "Jenis hari": "", "Pola hari": "", "Status": f"{int(done.sum())} hari penuh", "Prediksi sales produk": pred, "Aktual sales produk": act, "Belum Bayar": pend,
        "Selisih": act - pred, "% capaian": act / pred * 100 if pred else np.nan,
        "Akurasi prediksi": max(0.0, 100 - float((month.loc[done, "aktual"].fillna(0) - month.loc[done, "prediksi"].fillna(0)).abs().sum()) / act * 100) if act else np.nan,
        "% bila Belum Bayar dibayar": (act + pend) / pred * 100 if pred else np.nan, "Sumber prediksi": "",
    }
    goal_done = float(month.loc[done, "target"].fillna(0).sum())
    net_done = float(month.loc[done, "bersih"].fillna(0).sum())
    total.update({"Target harian": goal_done, "Sales bersih toko": net_done, "% target": net_done / goal_done * 100 if goal_done else np.nan})
    if target:
        pred_net = pred * float(target["factor"])
        total.update({"Prediksi sales bersih": pred_net, "Achievement bersih": net_done / pred_net * 100 if pred_net else np.nan})
    first = month["tanggal"].iloc[0]
    month_label = f"Total {ID_MONTHS[first.month - 1]} {first.year} ({len(month)} hari)"
    pred_month = float(month["prediksi"].fillna(0).sum())
    projection = act + float(month.loc[~done, "prediksi"].fillna(0).sum())
    full = {
        "Tanggal": month_label, "Jenis hari": "", "Pola hari": "",
        "Status": f"Proyeksi {fmt_idr(projection)}",
        "Prediksi sales produk": pred_month, "Aktual sales produk": act, "Belum Bayar": pend,
        "Selisih": projection - pred_month, "% capaian": act / pred_month * 100 if pred_month else np.nan,
        "Akurasi prediksi": np.nan,
        "% bila Belum Bayar dibayar": (act + pend) / pred_month * 100 if pred_month else np.nan,
        "Sumber prediksi": "aktual + prediksi sisa",
    }
    goal_month = float(month["target"].fillna(0).sum())
    factor = float(target["factor"]) if target else 1.0
    net_projection = net_done + float(month.loc[~done, "prediksi"].fillna(0).sum()) * factor
    if target and target.get("proyeksi") is not None:
        net_projection = float(target["proyeksi"])
    full.update({"Target harian": goal_month, "Sales bersih toko": net_done,
                 "% target": net_projection / goal_month * 100 if goal_month else np.nan})
    if target:
        full.update({"Prediksi sales bersih": pred_month * factor, "Achievement bersih": net_done / (pred_month * factor) * 100 if pred_month else np.nan})
    if target:
        full["Status"] = f"Proyeksi bersih {fmt_idr(net_projection)}"
    rows = pd.DataFrame([full, total])[[c for c in view.columns]]
    with st.expander("Breakdown per tanggal (tgl 1 s.d. akhir bulan)", expanded=True):
        status_full = full["Status"]
        full["Status"] = "Sebulan"
        rows = pd.DataFrame([full, total])[[c for c in view.columns]]
        table = _month_display(pd.concat([rows, view], ignore_index=True), bool(target), net_projection=net_projection if target else None)
        _accuracy_cards(table, last)
        factor_text = str(round(float(target["factor"]), 2)).replace(".", ",") if target else ""
        st.markdown(
            f"<div class='field-hint'><b>{html.escape(month_label)}</b>: {html.escape(status_full)} "
            f"(aktual s.d. {fmt_date(last)} + prediksi hari tersisa).</div>",
            unsafe_allow_html=True,
        )
        explain(
            [
                ("Kelompok kolom", "Produk = sales produk (Harga Setelah Diskon × QTY), dasar model prediksi. "
                 + ("Bersih = sales bersih toko (Total Pembayaran − batal − Belum Bayar − retur), dasar target dan kartu Pantauan harian. "
                    f"Prediksi bersih = prediksi produk × faktor {factor_text} (sales bersih ÷ sales produk bulan ini)." if target else "")),
                ("Achievement", "aktual ÷ prediksi. 100% = sesuai prediksi, di atas 100% = melebihi. Hanya hari yang sudah penuh (Selesai); "
                 "baris Sebulan = progres aktual terhadap prediksi sebulan"),
                ("Akurasi", "100% − |aktual − prediksi| ÷ aktual, hanya hari penuh. Meleset ke atas maupun ke bawah sama-sama mengurangi akurasi. "
                 "Baris Total s.d. = 100% − Σ|selisih harian| ÷ Σ aktual"),
                ("Achievement + BB", "achievement bila pesanan yang masih Belum Bayar ikut dibayar"),
                *([("Target · % target", f"target bulan ({fmt_idr(target['target'])}) dibagi per tanggal mengikuti pola hari; % target = aktual bersih ÷ target. "
                    "Baris Sebulan: % target = proyeksi bersih akhir bulan ÷ target bulan")] if target else []),
                ("Hari", "jenis hari (gajian, tanggal kembar) dan pola pengali prediksi hari itu; \"pola model\" = tanggal uji mundur memakai pola Senin–Minggu model"),
                ("Tanggal hari ini (Berjalan)", "aktual belum sehari penuh, jadi selisih, achievement, dan akurasi belum dihitung"),
            ]
        )
        show_table(
            table,
            bold_label=(month_label, label),
            kinds={**{c: "money" for c in MONTH_MONEY if c in table.columns}, **{c: "pct" for c in MONTH_PCT if c in table.columns}},
            # Tinggi dibatasi agar tabel bergulir di dalam: judul kolom (header) tetap terlihat; kolom Tanggal disematkan di kiri.
            max_height=640,
            column_config=_month_widths(table),
        )


MONTH_MONEY = ("Produk · Prediksi", "Produk · Aktual", "Produk · Selisih", "Bersih · Prediksi", "Bersih · Aktual", "Bersih · Selisih",
               "Bersih · Target", "Belum Bayar")
MONTH_PCT = ("Produk · Achievement", "Produk · Akurasi", "Bersih · Achievement", "Bersih · Akurasi", "Bersih · % target", "Achievement + BB")
MONTH_TEXT = ("Tanggal", "Status", "Hari", "Sumber prediksi")


def _month_display(frame: pd.DataFrame, has_target: bool, net_projection: float | None = None) -> pd.DataFrame:
    """Urutan & nama kolom Breakdown per tanggal. Kelompok Produk dan Bersih memakai deret yang sama:
    Prediksi · Aktual · Selisih · Achievement · Akurasi, lalu Target & % target, Belum Bayar, sumber."""
    out = frame.copy()
    out["Hari"] = [" · ".join(p for p in (str(k), str(v)) if p and p != "nan") for k, v in zip(out["Jenis hari"].fillna(""), out["Pola hari"].fillna(""))]
    status = out["Status"].astype(str)
    day_done = status.eq("Selesai")
    upto = status.str.endswith("hari penuh")
    month_row = status.eq("Sebulan")
    open_day = ~(day_done | upto | month_row)
    if has_target:
        pred_net = pd.to_numeric(out["Prediksi sales bersih"], errors="coerce")
        act_net = pd.to_numeric(out["Sales bersih toko"], errors="coerce")
        out["Selisih bersih"] = np.where(day_done | upto, act_net - pred_net, np.nan)
        if net_projection is not None:
            out.loc[month_row, "Selisih bersih"] = net_projection - pred_net[month_row]
        out["Akurasi bersih"] = [accuracy(a, p) if d else np.nan for a, p, d in zip(act_net, pred_net, day_done)]
        err = float((act_net[day_done] - pred_net[day_done]).abs().sum())
        total_act = float(act_net[day_done].sum())
        out.loc[upto, "Akurasi bersih"] = max(0.0, 100 - err / total_act * 100) if total_act else np.nan
    # Hari berjalan/mendatang: aktual belum penuh → selisih & persentase dikosongkan agar tidak terbaca anjlok.
    for column in ("Selisih", "% capaian", "Akurasi prediksi", "% bila Belum Bayar dibayar", "Achievement bersih", "% target", "Selisih bersih", "Akurasi bersih"):
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
            out.loc[open_day, column] = np.nan
    names = {
        "Prediksi sales produk": "Produk · Prediksi", "Aktual sales produk": "Produk · Aktual", "Selisih": "Produk · Selisih",
        "% capaian": "Produk · Achievement", "Akurasi prediksi": "Produk · Akurasi",
        "Prediksi sales bersih": "Bersih · Prediksi", "Sales bersih toko": "Bersih · Aktual", "Selisih bersih": "Bersih · Selisih",
        "Achievement bersih": "Bersih · Achievement", "Akurasi bersih": "Bersih · Akurasi",
        "Target harian": "Bersih · Target", "% target": "Bersih · % target", "% bila Belum Bayar dibayar": "Achievement + BB",
    }
    out = out.rename(columns=names)
    order = ["Tanggal", "Status", "Hari",
             "Produk · Prediksi", "Produk · Aktual", "Produk · Selisih", "Produk · Achievement", "Produk · Akurasi"]
    if has_target:
        order += ["Bersih · Prediksi", "Bersih · Aktual", "Bersih · Selisih", "Bersih · Achievement", "Bersih · Akurasi",
                  "Bersih · Target", "Bersih · % target"]
    order += ["Belum Bayar", "Achievement + BB", "Sumber prediksi"]
    out = out[[c for c in order if c in out.columns]]
    for column in out.columns:
        if column not in MONTH_TEXT:
            out[column] = pd.to_numeric(out[column], errors="coerce").astype(float)
    return out


def _accuracy_cards(table: pd.DataFrame, last: date) -> None:
    """Ringkasan akurasi prediksi untuk hari yang sudah penuh (s.d. hari penuh terakhir)."""
    import streamlit as st

    days = table.loc[table["Status"].eq("Selesai")]
    if days.empty:
        return
    upto = table.loc[table["Status"].astype(str).str.endswith("hari penuh")]
    first = upto.iloc[0] if not upto.empty else None
    ach = pd.to_numeric(days["Produk · Achievement"], errors="coerce")
    within = int(((ach - 100).abs() <= 10).sum())
    cols = st.columns(4)
    if first is not None:
        card(cols[0], f"Akurasi prediksi · produk", fmt_pct(first.get("Produk · Akurasi"), 1),
             hint=f"{len(days)} hari penuh s.d. {fmt_date(last)} · 100% − Σ|selisih| ÷ Σ aktual")
        if "Bersih · Akurasi" in table.columns:
            card(cols[1], "Akurasi prediksi · bersih", fmt_pct(first.get("Bersih · Akurasi"), 1),
                 hint="basis sales bersih toko (kartu Pantauan harian)")
        card(cols[2], "Achievement s.d. kemarin", fmt_pct(first.get("Produk · Achievement"), 1),
             hint="aktual ÷ prediksi sales produk; 100% = sesuai prediksi")
    card(cols[3], "Hari tepat (±10%)", f"{within} dari {len(days)} hari",
         hint=f"achievement 90–110%; terendah {fmt_pct(ach.min(), 0)}, tertinggi {fmt_pct(ach.max(), 0)}")


def _month_widths(table: pd.DataFrame) -> dict:
    """Hanya kolom teks diberi lebar pasti (agar tidak terpotong); kolom angka memakai lebar otomatis seperti tabel lain."""
    import streamlit as st

    from src.utils.format import CELL_PAD_PX, CHAR_PX

    config = {}
    for column in MONTH_TEXT:
        if column not in table.columns:
            continue
        longest = max([len(str(column))] + [len(str(v)) for v in table[column].fillna("").tolist()])
        config[column] = st.column_config.TextColumn(str(column), width=int(longest * CHAR_PX + CELL_PAD_PX + 6), pinned=column == "Tanggal")
    return config


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
