"""Tabel keputusan (Top 50 & Prediksi semua produk), Analisa safety stock, matriks Top 50, grafik per SKU."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from plotly.subplots import make_subplots

from src.core.decision_table import lama_kosong_text, period_groups, safety_stock_summary
from src.core.labels import LABEL_ICONS, LABEL_LEGEND
from src.forecast import forecast_calendar
from src.ui.common import (
    DOWN_COLOR,
    STATUS_CLASS,
    UP_COLOR,
    card,
    download_excel,
    fmt_date,
    fmt_idr,
    fmt_idr_short,
    fmt_num,
    fmt_pct,
    fmt_qty,
    status_key,
)

ROOT = Path(__file__).resolve().parents[2]
_TABLE = components.declare_component("decision_table", path=str(ROOT / "components" / "top50_table"))
SS_DEFINITION_TOP = "Safety stock adalah stok yang harus dimiliki agar tidak terjadi kekosongan produk."


def _clean(value: object, fallback: str) -> str:
    text = " ".join(str(value or "").split())
    return text if text and text.lower() not in {"nan", "none"} else fallback


def _stock_cell(row: pd.Series, prefix: str) -> dict:
    if not bool(row.get("ada_data_stok", False)):
        return {"v": None, "t": "-", "s": "belum ada data stok"}
    stok = float(row["stok"])
    gap = float(row[f"{prefix}_selisih"])
    pct = float(row[f"{prefix}_pct"]) * 100
    status = status_key(row[f"{prefix}_status"])
    sign = "+" if gap > 0 else ("−" if gap < 0 else "")
    sub = f"{sign}{fmt_qty(abs(gap))} ({fmt_pct(pct, 0, signed=True)}) · {status}"
    if "di bawah SS" in str(row[f"{prefix}_status"]):
        sub += " · di bawah SS"
    return {"v": stok, "t": fmt_qty(stok), "s": sub, "c": STATUS_CLASS.get(status, "")}


def table_parts(
    view: pd.DataFrame,
    *,
    period: str,
    today: date,
    metric: str,
    resume_label: str,
    window_label: str,
) -> tuple[list[dict], list[dict], dict, pd.DataFrame]:
    """Kolom, baris, baris Total, dan salinan Excel. Kolom per kelompok: Prediksi, SS, Butuh, Stok."""
    groups = period_groups(period, today)
    month_name = f"{fmt_date(today).split(' ', 1)[1]}"
    titles = {"d": f"Hari ini · {fmt_date(today, short=True)}", "m": f"Bulan ini · {month_name}", "p": window_label}
    main_label = "QTY" if metric == "qty" else "Sales"
    columns: list[dict] = [
        {"id": "pick", "label": "Grafik", "pin": True, "width": 64},
        {"id": "rank", "label": "Peringkat", "pin": True, "width": 86, "kind": "num", "sort": True},
        {"id": "sku", "label": "SKU", "kicker": "Produk", "pin": True, "width": 116, "sort": True},
        {"id": "name", "label": "Product Name", "kicker": "Produk", "pin": True, "width": 290, "kind": "name", "sort": True},
        {"id": "variance", "label": "Product variance", "width": 160, "kind": "name", "sort": True},
        {"id": "sold", "label": main_label, "group": f"Terjual · {resume_label}", "kind": "num", "sort": True},
    ]
    for group in groups:
        tone = "extra" if group.extra else None
        title = titles[group.prefix]
        columns += [
            {"id": f"{group.prefix}_pred", "label": main_label, "group": title, "kind": "num", "sort": True, "tone": tone},
            {"id": f"{group.prefix}_ss", "label": "SS", "group": title, "kind": "num", "sort": True, "tone": tone},
            {"id": f"{group.prefix}_butuh", "label": "Butuh", "group": title, "kind": "num", "sort": True, "tone": tone},
            {"id": f"{group.prefix}_stok", "label": "Stok", "group": title, "kind": "num", "sort": True, "tone": "stock"},
        ]
    columns += [
        {"id": "cover", "label": "Hari cukup", "group": "Kesehatan stok", "kind": "num", "sort": True, "tone": "stock"},
        {"id": "empty", "label": "Lama kosong", "group": "Kesehatan stok", "kind": "num", "sort": True, "tone": "stock"},
    ]
    rows: list[dict] = []
    totals: dict[str, float] = {}
    export_rows: list[dict] = []
    for _, row in view.iterrows():
        labels = [f"{LABEL_ICONS[name]} {name}" for name in (row.get("label") or [])]
        sold_value = float(row["qty_total"] if metric == "qty" else row["sales_total"])
        cells: dict[str, dict] = {
            "rank": {"v": int(row["peringkat"]), "t": fmt_num(int(row["peringkat"]))},
            "sku": {"v": _clean(row["sku"], "Tanpa SKU"), "t": _clean(row["sku"], "Tanpa SKU")},
            "name": {"v": _clean(row["product_name"], "Tanpa nama"), "t": _clean(row["product_name"], "Tanpa nama"), "l": labels},
            "variance": {"v": _clean(row.get("variasi_tampil"), "Tanpa variasi"), "t": _clean(row.get("variasi_tampil"), "Tanpa variasi")},
            "sold": {
                "v": sold_value,
                "t": fmt_qty(sold_value) if metric == "qty" else fmt_idr(sold_value),
                "s": fmt_idr(row["sales_total"]) if metric == "qty" else f"{fmt_qty(row['qty_total'])} unit",
            },
        }
        totals["sold"] = totals.get("sold", 0.0) + sold_value
        export = {
            "Peringkat": int(row["peringkat"]),
            "SKU": cells["sku"]["t"],
            "Product Name": cells["name"]["t"],
            "Product variance": cells["variance"]["t"],
            "Label": ", ".join(row.get("label") or []),
            "QTY terjual": float(row["qty_total"]),
            "Sales terjual": float(row["sales_total"]),
        }
        for group in groups:
            p = group.prefix
            qty = float(row[f"{p}_qty"])
            sales = float(row[f"{p}_sales"])
            main = qty if metric == "qty" else sales
            cells[f"{p}_pred"] = {
                "v": main,
                "t": fmt_qty(qty) if metric == "qty" else fmt_idr(sales),
                "s": fmt_idr(sales) if metric == "qty" else f"{fmt_qty(qty)} unit",
            }
            cells[f"{p}_ss"] = {"v": float(row[f"{p}_ss"]), "t": fmt_qty(row[f"{p}_ss"])}
            cells[f"{p}_butuh"] = {"v": float(row[f"{p}_butuh"]), "t": fmt_qty(row[f"{p}_butuh"])}
            cells[f"{p}_stok"] = _stock_cell(row, p)
            for name, value in ((f"{p}_pred", main), (f"{p}_ss", row[f"{p}_ss"]), (f"{p}_butuh", row[f"{p}_butuh"])):
                totals[name] = totals.get(name, 0.0) + float(value)
            if bool(row.get("ada_data_stok", False)):
                totals[f"{p}_stok"] = totals.get(f"{p}_stok", 0.0) + float(row["stok"])
            label = group.label
            export[f"{label} - Prediksi QTY"] = qty
            export[f"{label} - Prediksi sales"] = sales
            export[f"{label} - SS"] = float(row[f"{p}_ss"])
            export[f"{label} - Butuh"] = float(row[f"{p}_butuh"])
            export[f"{label} - Stok DC Cikupa"] = float(row["stok"]) if bool(row.get("ada_data_stok", False)) else None
            export[f"{label} - Selisih"] = float(row[f"{p}_selisih"]) if bool(row.get("ada_data_stok", False)) else None
            export[f"{label} - Status"] = status_key(row[f"{p}_status"])
        cover = row.get("hari_cukup")
        cover_ok = cover is not None and pd.notna(cover) and np.isfinite(float(cover))
        cells["cover"] = {
            "v": float(cover) if cover_ok else None,
            "t": fmt_num(cover, 0) if cover_ok else ("∞" if pd.notna(cover) else "-"),
            "s": f"habis {fmt_date(row.get('tanggal_habis'), short=True)}" if cover_ok and row.get("tanggal_habis") else "",
        }
        empty_text = lama_kosong_text(row)
        cells["empty"] = {"v": float(row["lama_kosong_hari"]) if pd.notna(row.get("lama_kosong_hari")) else None, "t": empty_text}
        export["Hari cukup"] = float(cover) if cover_ok else None
        export["Lama kosong"] = empty_text
        rows.append({"key": str(row["item_key"]), "cells": cells})
        export_rows.append(export)
    total: dict[str, dict] = {"name": {"t": "Total", "s": f"{len(rows)} item"}}
    for column in columns[5:]:
        name = column["id"]
        if name not in totals:
            continue
        value = totals[name]
        money = metric == "sales" and (name.endswith("_pred") or name == "sold")
        total[name] = {"t": fmt_idr(value) if money else fmt_qty(value)}
    return columns, rows, total, pd.DataFrame(export_rows)


def show_decision_table(
    view: pd.DataFrame,
    *,
    period: str,
    today: date,
    metric: str,
    resume_label: str,
    window_label: str,
    key: str,
    filename: str,
    height: int = 680,
) -> str:
    """Tabel bersama R8 dan Prediksi semua produk. Mengembalikan item_key yang dicentang di kolom Grafik."""
    columns, rows, total, export = table_parts(view, period=period, today=today, metric=metric, resume_label=resume_label, window_label=window_label)
    keys = {row["key"] for row in rows}
    previous = str(st.session_state.get(f"{key}-value") or "")
    picked = _TABLE(
        columns=columns,
        rows=rows,
        total=total,
        selected=previous if previous in keys else "",
        height=height,
        sort="rank",
        key=key,
        default=previous if previous in keys else "",
    )
    picked = str(picked or "")
    st.session_state[f"{key}-value"] = picked
    download_excel(export, filename, key=f"xl-{key}")
    return picked if picked in keys else ""


def label_legend() -> None:
    st.markdown(f"<div class='field-hint'>{LABEL_LEGEND}</div>", unsafe_allow_html=True)


def safety_stock_box(table: pd.DataFrame, *, period: str, today: date, definition: str, used_default: bool) -> None:
    groups = period_groups(period, today)
    with st.container(border=True):
        st.markdown("**Analisa safety stock**")
        st.caption(definition)
        cols = st.columns(len(groups))
        for column, group in zip(cols, groups):
            summary = safety_stock_summary(table, group.prefix)
            body = (
                f"Total SS <b>{fmt_qty(summary['total_ss'])}</b> unit<br>"
                f"SKU stok &lt; prediksi + SS: <b>{fmt_num(summary['sku_kurang_butuh'])}</b><br>"
                f"SKU stok &lt; SS: <b>{fmt_num(summary['sku_di_bawah_ss'])}</b>"
            )
            if summary["sku_tanpa_stok_data"]:
                body += f"<br><span style='color:#64748b'>{fmt_num(summary['sku_tanpa_stok_data'])} SKU belum ada data stok</span>"
            card(column, group.label, f"<div style='font-size:.95rem;font-weight:600;line-height:1.6'>{body}</div>", tone="extra" if group.extra else None)
        if used_default:
            st.caption("Lead time memakai asumsi default dari Pengaturan bisnis.")


def top50_matrix(view: pd.DataFrame, actuals: dict[str, dict[str, float]], *, period: str, today: date, resume_label: str) -> None:
    """R5: baris Hari ini/Bulan ini/+periode, kolom actual, prediksi, kontribusi sales Top 50."""
    groups = period_groups(period, today)
    rows = []
    for group in groups:
        p = group.prefix
        act = actuals.get(p, {})
        qty_act = float(act.get("qty", 0.0))
        sales_act = float(act.get("sales", 0.0))
        share_base = float(act.get("store_sales", 0.0))
        share = sales_act / share_base * 100 if share_base > 0 else np.nan
        rows.append(
            {
                "Periode": group.label,
                "QTY actual": fmt_qty(qty_act),
                "Sales volume actual": fmt_idr(sales_act),
                "Prediksi QTY": fmt_qty(view[f"{p}_qty"].sum()),
                "Prediksi sales volume": fmt_idr(view[f"{p}_sales"].sum()),
                "Kontribusi sales Top 50": f"{fmt_pct(share)} dari {fmt_idr(share_base)}" if share_base > 0 else "-",
            }
        )
    frame = pd.DataFrame(rows)
    header = "".join(f"<th>{c}</th>" for c in frame.columns)
    body = ""
    for _, r in frame.iterrows():
        extra = r["Periode"] not in {"Hari ini", "Bulan ini"}
        style = " style='background:#eff6ff'" if extra else ""
        body += f"<tr{style}>" + "".join(f"<td>{r[c]}</td>" for c in frame.columns) + "</tr>"
    st.markdown(
        "<div class='sheet-scroll'><table style='width:100%'><thead><tr>" + header + "</tr></thead><tbody>" + body + "</tbody></table></div>",
        unsafe_allow_html=True,
    )
    extra = next((g.label for g in groups if g.extra), None)
    extra_text = f"; {extra} = {extra.lower()} terakhir s.d. kemarin" if extra else ""
    st.caption(f"Actual Hari ini = data hari terakhir yang tercatat; Bulan ini = tanggal 1 s.d. kemarin{extra_text}. Kontribusi = sales Top 50 ÷ sales seluruh toko pada rentang yang sama.")


def _daily_path(row: pd.Series, item_orders: pd.DataFrame, weekday: np.ndarray, start: date, end: date, total: float) -> pd.DataFrame:
    dates = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
    if len(dates) == 0:
        return pd.DataFrame(columns=["date", "qty", "sales"])
    if item_orders is None or item_orders.empty:
        qty = np.full(len(dates), total / len(dates))
    else:
        by_day = item_orders.groupby(pd.to_datetime(item_orders["order_time"]).dt.normalize())["qty"].sum().sort_index()
        index = pd.date_range(by_day.index.min(), by_day.index.max(), freq="D")
        series = by_day.reindex(index, fill_value=0.0).to_numpy(dtype=float)
        qty = forecast_calendar(series, index[0], dates, weekday, total)
    price = float(row.get("harga_bersih", 0) or 0)
    return pd.DataFrame({"date": dates, "qty": qty, "sales": qty * price})


def _two_panel(x_labels, sold, pred, stock_line, ss_value: float, out_label: str | None, *, money: bool, title: str, unit: str) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.62, 0.38], subplot_titles=(title, "Proyeksi sisa stok"))
    fmt = fmt_idr_short if money else fmt_qty
    fig.add_bar(
        x=x_labels, y=sold, name="Terjual", marker_color="#1b3da6",
        text=[fmt(v) if v else "" for v in sold], textposition="outside",
        hovertemplate="%{x}<br>Terjual: %{customdata}<extra></extra>", customdata=[fmt(v) for v in sold], row=1, col=1,
    )
    fig.add_bar(
        x=x_labels, y=pred, name="Prediksi", marker_color="#ee4d2d",
        text=[fmt(v) if v else "" for v in pred], textposition="outside",
        hovertemplate="%{x}<br>Prediksi: %{customdata}<extra></extra>", customdata=[fmt(v) for v in pred], row=1, col=1,
    )
    if stock_line is not None:
        fig.add_scatter(
            x=x_labels, y=stock_line, mode="lines+markers", name="Sisa stok (stok − kumulatif prediksi)", line=dict(color="#ea580c", width=2),
            hovertemplate="%{x}<br>Sisa stok: %{customdata}<extra></extra>", customdata=[fmt(v) for v in stock_line], row=2, col=1,
        )
        fig.add_scatter(
            x=x_labels, y=[ss_value] * len(x_labels), mode="lines", name="Safety stock", line=dict(color="#a16207", dash="dash"),
            hovertemplate=f"Safety stock: {fmt(ss_value)}<extra></extra>", row=2, col=1,
        )
        if out_label is not None:
            idx = list(x_labels).index(out_label)
            fig.add_scatter(
                x=[out_label], y=[stock_line[idx]], mode="markers+text", name="Perkiraan stok habis", marker=dict(color=DOWN_COLOR, size=12, symbol="x"),
                text=["habis"], textposition="top center", hovertemplate="%{x}<br>Perkiraan stok habis<extra></extra>", row=2, col=1,
            )
    fig.update_layout(barmode="group", height=560, margin=dict(l=40, r=20, t=60, b=40), legend=dict(orientation="h", y=-0.12), font=dict(family="Plus Jakarta Sans"))
    fig.update_yaxes(title_text=unit, row=1, col=1)
    fig.update_yaxes(title_text=unit, row=2, col=1)
    return fig


def _bucket(frame: pd.DataFrame, grain: str) -> pd.DataFrame:
    work = frame.copy()
    stamps = pd.to_datetime(work["date"])
    if grain == "bulan":
        work["bucket"] = stamps.dt.to_period("M").astype(str)
        work["label"] = stamps.map(lambda s: f"{fmt_date(s, short=True).split(' ')[1]} {s.year}")
    else:
        origin = stamps.min().normalize()
        work["bucket"] = ((stamps.dt.normalize() - origin).dt.days // 7).astype(int)
        work["label"] = work.groupby("bucket")["date"].transform(lambda s: f"{fmt_date(s.min(), short=True)}–{fmt_date(s.max(), short=True)}")
    agg = {c: "sum" for c in work.columns if c not in {"date", "bucket", "label"}}
    grouped = work.groupby(["bucket", "label"], as_index=False, sort=True).agg(agg)
    return grouped


def sku_charts(
    row: pd.Series,
    item_orders: pd.DataFrame,
    *,
    period: str,
    today: date,
    window_end: date,
    weekday: np.ndarray,
    key: str,
) -> None:
    """R9: Grafik QTY dan Grafik Sales, dua panel sumbu X bersama."""
    month_start = date(today.year, today.month, 1)
    month_end = (pd.Timestamp(today) + pd.offsets.MonthEnd(0)).date()
    days = pd.date_range(month_start, month_end, freq="D")
    sold = pd.Series(0.0, index=days)
    sold_sales = pd.Series(0.0, index=days)
    if item_orders is not None and not item_orders.empty:
        stamps = pd.to_datetime(item_orders["order_time"]).dt.normalize()
        part = item_orders.loc[stamps.between(pd.Timestamp(month_start), pd.Timestamp(today) - pd.Timedelta(days=1))]
        if not part.empty:
            grouped = part.groupby(pd.to_datetime(part["order_time"]).dt.normalize()).agg(qty=("qty", "sum"), sales=("sales", "sum"))
            sold = sold.add(grouped["qty"].reindex(days, fill_value=0.0), fill_value=0.0)
            sold_sales = sold_sales.add(grouped["sales"].reindex(days, fill_value=0.0), fill_value=0.0)
    remain_total = float(row["pred_harian"]) * max((month_end - today).days + 1, 0)
    path = _daily_path(row, item_orders, weekday, today, month_end, remain_total)
    pred = pd.Series(0.0, index=days)
    pred_sales = pd.Series(0.0, index=days)
    if not path.empty:
        pred.loc[pd.DatetimeIndex(path["date"])] = path["qty"].to_numpy()
        pred_sales.loc[pd.DatetimeIndex(path["date"])] = path["sales"].to_numpy()
    has_stock = bool(row.get("ada_data_stok", False))
    stok = float(row["stok"]) if has_stock else 0.0
    ss = float(row["ss"])
    price = float(row.get("harga_bersih", 0) or 0)
    labels = [fmt_date(d, short=True) for d in days]

    def stock_projection(pred_series: np.ndarray, base: float) -> tuple[np.ndarray, str | None]:
        mask = np.array([d >= pd.Timestamp(today) for d in days]) if len(pred_series) == len(days) else np.ones(len(pred_series), bool)
        cumulative = np.cumsum(np.where(mask, pred_series, 0.0))
        line = base - cumulative
        out = next((i for i, v in enumerate(line) if mask[i] and v <= 0), None)
        return line, out

    qty_line, qty_out = stock_projection(pred.to_numpy(), stok) if has_stock else (None, None)
    sales_line = qty_line * price if qty_line is not None else None
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(
            _two_panel(labels, sold.to_numpy(), pred.to_numpy(), qty_line, ss, labels[qty_out] if qty_out is not None else None, money=False, title="Grafik QTY · Bulan ini", unit="Unit"),
            use_container_width=True, key=f"{key}-qty",
        )
    with c2:
        st.plotly_chart(
            _two_panel(labels, sold_sales.to_numpy(), pred_sales.to_numpy(), sales_line, ss * price, labels[qty_out] if qty_out is not None else None, money=True, title="Grafik Sales · Bulan ini", unit="Rupiah"),
            use_container_width=True, key=f"{key}-sales",
        )
    chips = st.columns(4)
    card(chips[0], "Terjual bulan ini", f"{fmt_qty(sold.sum())} unit", hint=fmt_idr(sold_sales.sum()))
    card(chips[1], "Prediksi bulan ini", f"{fmt_qty(row['m_qty'])} unit", hint=fmt_idr(row["m_sales"]))
    card(chips[2], "Safety stock", f"{fmt_qty(ss)} unit", hint=fmt_idr(ss * price))
    if has_stock:
        gap = float(row["m_selisih"])
        card(chips[3], "Stok DC Cikupa", f"{fmt_qty(stok)} unit", hint=(f"kurang {fmt_qty(-gap)} unit" if gap < 0 else f"lebih {fmt_qty(gap)} unit") + " dari kebutuhan", tone="stock")
    else:
        card(chips[3], "Stok DC Cikupa", "-", hint="Unggah Data stok untuk proyeksi sisa stok", tone="stock")

    if period == "bulan":
        return
    grain_label = st.radio("Agregasi periode prediksi", ["Per minggu", "Per bulan"], horizontal=True, key=f"{key}-grain")
    grain = "minggu" if grain_label == "Per minggu" else "bulan"
    full = _daily_path(row, item_orders, weekday, today, window_end, float(row["p_qty"]))
    if full.empty:
        return
    full["sold"] = 0.0
    full["sold_sales"] = 0.0
    if has_stock:
        full["stock_q"] = stok - full["qty"].cumsum()
    grouped = _bucket(full, grain)
    if has_stock:
        cum = grouped["qty"].cumsum().to_numpy()
        line = stok - cum
    else:
        line = None
    labels_p = grouped["label"].tolist()
    out_idx = next((i for i, v in enumerate(line) if v <= 0), None) if line is not None else None
    title_name = {"kuartal": "Quartal", "semester": "Semester", "tahun": "Tahun"}[period]
    c3, c4 = st.columns(2)
    with c3:
        st.plotly_chart(
            _two_panel(labels_p, grouped["sold"].to_numpy(), grouped["qty"].to_numpy(), line, ss, labels_p[out_idx] if out_idx is not None else None, money=False, title=f"Grafik QTY · {title_name}", unit="Unit"),
            use_container_width=True, key=f"{key}-pqty",
        )
    with c4:
        st.plotly_chart(
            _two_panel(labels_p, grouped["sold_sales"].to_numpy(), grouped["sales"].to_numpy(), line * price if line is not None else None, ss * price, labels_p[out_idx] if out_idx is not None else None, money=True, title=f"Grafik Sales · {title_name}", unit="Rupiah"),
            use_container_width=True, key=f"{key}-psales",
        )
    chips = st.columns(3)
    card(chips[0], f"Prediksi {title_name}", f"{fmt_qty(row['p_qty'])} unit", hint=fmt_idr(row["p_sales"]), tone="extra")
    card(chips[1], "Butuh (prediksi + SS)", f"{fmt_qty(row['p_butuh'])} unit", tone="extra")
    if has_stock:
        gap = float(row["p_selisih"])
        card(chips[2], "Stok vs kebutuhan", (f"kurang {fmt_qty(-gap)}" if gap < 0 else f"lebih {fmt_qty(gap)}") + " unit", tone="stock")


def direction_html(value: float) -> str:
    if value > 0:
        return f"<span style='color:{UP_COLOR};font-weight:700'>▲</span>"
    if value < 0:
        return f"<span style='color:{DOWN_COLOR};font-weight:700'>▼</span>"
    return ""
