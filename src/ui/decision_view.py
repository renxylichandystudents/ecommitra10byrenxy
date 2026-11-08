"""Tabel keputusan (Top 50 & Prediksi semua produk), Analisa safety stock, matriks Top 50, grafik per SKU."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import hashlib

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from plotly.subplots import make_subplots

from src.core.periods import prediction_window
from src.core.decision_table import lama_kosong_text, period_groups
from src.core.labels import LABEL_ICONS
from src.forecast import forecast_calendar
from src.ui.common import (
    explain,
    DOWN_COLOR,
    STATUS_CLASS,
    UP_COLOR,
    card,
    excel_payload,
    fmt_date,
    fmt_idr,
    fmt_idr_short,
    fmt_num,
    fmt_pct,
    fmt_qty,
    status_key,
)

ROOT = Path(__file__).resolve().parents[2]
# Nama komponen memuat sidik isi index.html: browser tidak memakai versi lama dari cache setelah komponen diubah.
_COMPONENT_DIR = ROOT / "components" / "top50_table"
COMPONENT_VERSION = hashlib.md5((_COMPONENT_DIR / "index.html").read_bytes()).hexdigest()[:8]
_TABLE = components.declare_component(f"decision_table_{COMPONENT_VERSION}", path=str(_COMPONENT_DIR))
SS_DEFINITION_TOP = (
    "Safety stock (SS) = stok cadangan agar produk tidak kosong. "
    "SS = Z × σ permintaan harian × √lead time lokal, dibulatkan ke atas."
)


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
    month_group = next(g for g in groups if g.prefix == "m")
    month_end = prediction_window("bulan", today)[1]
    titles = {
        "d": f"Hari ini · {fmt_date(today, short=True)}",
        "m": f"{month_group.label} · {fmt_date(today, short=True)} – {fmt_date(month_end, short=True)}",
        "p": window_label,
    }
    main_label = "QTY" if metric == "qty" else "Sales"
    columns: list[dict] = [
        {"id": "pick", "label": "Grafik", "pin": True, "width": 64},
        {"id": "rank", "label": "Rank", "pin": True, "width": 86, "kind": "num", "sort": True},
        {"id": "sku", "label": "SKU", "pin": True, "width": 116, "sort": True},
        {"id": "name", "label": "Produk", "pin": True, "width": 290, "kind": "name", "sort": True},
        {"id": "variance", "label": "Varian", "width": 160, "kind": "name", "sort": True},
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
    dc_known = any(f"stok_{code}" in view.columns and view[f"stok_{code}"].notna().any() for code in ("10062", "10036"))
    if dc_known:
        columns += [
            {"id": "dc_10062", "label": "Site 10062 · Cikupa", "group": "Stok DC", "kind": "num", "sort": True, "tone": "stock"},
            {"id": "dc_10036", "label": "Site 10036 · Cipeucang", "group": "Stok DC", "kind": "num", "sort": True, "tone": "stock"},
            {"id": "dc_take", "label": "Ambil dari DC", "group": "Stok DC", "width": 230, "kind": "name", "sort": True, "tone": "stock"},
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
            "Rank": int(row["peringkat"]),
            "SKU": cells["sku"]["t"],
            "Produk": cells["name"]["t"],
            "Varian": cells["variance"]["t"],
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
            export[f"{label} - Stok Site 10037"] = float(row["stok"]) if bool(row.get("ada_data_stok", False)) else None
            export[f"{label} - Selisih"] = float(row[f"{p}_selisih"]) if bool(row.get("ada_data_stok", False)) else None
            export[f"{label} - Status"] = status_key(row[f"{p}_status"])
        if dc_known:
            for code in ("10062", "10036"):
                value = row.get(f"stok_{code}")
                known = value is not None and pd.notna(value)
                take = row.get(f"ambil_{code}")
                take = float(take) if take is not None and pd.notna(take) else 0.0
                cells[f"dc_{code}"] = {
                    "v": float(value) if known else None,
                    "t": fmt_qty(value) if known else "-",
                    "s": f"ambil {fmt_qty(take)}" if take > 0 else "",
                    "c": "st-ok" if known and float(value) > 0 else "",
                }
                if known:
                    totals[f"dc_{code}"] = totals.get(f"dc_{code}", 0.0) + float(value)
                export[f"Stok Site {code}"] = float(value) if known else None
            plan = str(row.get("sumber_restock") or "").strip()
            cells["dc_take"] = {"v": plan, "t": plan or "Tidak perlu"}
            export["Ambil dari DC"] = plan
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
    filename: str | None,
    height: int = 680,
    step: int | None = None,
    sort: str = "rank",
) -> str:
    """Tabel bersama R8 dan Prediksi semua produk. Mengembalikan item_key yang dicentang di kolom Grafik.

    filename=None: tombol unduh tidak dibuat di dalam tabel (pemanggil menaruhnya di bilah navigasi halaman).
    step: tampilkan `step` baris teratas (setelah diurutkan) lalu tombol Muat lagi menambah `step` baris.
    """
    columns, rows, total, export = table_parts(view, period=period, today=today, metric=metric, resume_label=resume_label, window_label=window_label)
    keys = {row["key"] for row in rows}
    previous = str(st.session_state.get(f"{key}-value") or "")
    # Satu tabel, urut atas semua baris; tampil per kelompok (5 lalu +10) yang bisa dibuka/ditutup di dalam tabel.
    batch = {"first": int(step), "step": 10, "noun": "SKU"} if step else None
    picked = _TABLE(
        columns=columns,
        rows=rows,
        total=total,
        selected=previous if previous in keys else "",
        height=height,
        limit=0,
        batch=batch,
        download=excel_payload(export, filename) if filename else None,
        sort=sort,
        key=key,
        default=previous if previous in keys else "",
    )
    picked = str(picked or "")
    st.session_state[f"{key}-value"] = picked
    return picked if picked in keys else ""


def label_legend() -> None:
    """Keterangan label ringkas: satu baris kartu kecil + catatan sumber data (semua tetap terlihat)."""
    items = [
        ("🏆", "Terlaris", "10 besar QTY & sales sekaligus"),
        ("👁", "Populer", "10% teratas dilihat"),
        ("👆", "Paling diminati", "10% teratas klik/CTR"),
        ("⚠", "Perlu perhatian", "batal > 15% atau > 2× median toko, min. 5 baris pesanan"),
    ]
    cards = "".join(
        f"<div class='lg-item'><span class='lg-ico'>{icon}</span><div><b>{name}</b><br><span>{text}</span></div></div>"
        for icon, name, text in items
    )
    st.markdown(
        "<style>.lg-wrap{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:.4rem;margin:.1rem 0 .3rem}"
        ".lg-item{display:flex;gap:.5rem;align-items:flex-start;background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:.4rem .6rem;font-size:var(--fs-sm);line-height:1.25}"
        ".lg-item span{color:#6b7280}.lg-ico{font-size:var(--fs-base);line-height:1.2}"
        ".lg-note{font-size:var(--fs-xs);color:#6b7280;margin-bottom:.4rem}</style>"
        f"<div class='lg-wrap'>{cards}</div>"
        "<div class='lg-note'>Dilihat/klik berasal dari laporan iklan; produk tanpa iklan tidak mendapat label Populer/Paling diminati.</div>",
        unsafe_allow_html=True,
    )


def safety_stock_box(
    table: pd.DataFrame,
    *,
    period: str,
    today: date,
    definition: str,
    used_default: bool,
    scope: str = "Top 50",
    service: int | None = None,
    lead_days: float | None = None,
    import_mode: bool = False,
) -> None:
    """Analisa safety stock: parameter + angka yang tidak tergantung periode sekali saja, lalu satu tabel per periode."""
    del definition
    groups = period_groups(period, today)
    known = table["ada_data_stok"].astype(bool) if "ada_data_stok" in table.columns else pd.Series(False, index=table.index)
    stok = pd.to_numeric(table.get("stok", 0), errors="coerce").fillna(0.0)
    ss = pd.to_numeric(table.get("ss", 0), errors="coerce").fillna(0.0)
    below_ss = known & (stok < ss)
    empty = known & (stok <= 0)
    with st.container(border=True):
        st.markdown(f"**Analisa safety stock · {scope} ({fmt_num(len(table))} SKU)**")
        z = None
        if service:
            from src.core.inventory import service_level_to_z

            z = service_level_to_z(float(service))
        if import_mode:
            formula = f"(lead time maks − rata-rata) × permintaan harian; lead time rata-rata {fmt_num(lead_days or 0)} hari"
        else:
            formula = (
                f"Z × σ permintaan harian × √lead time = {fmt_num(z, 2) if z is not None else 'Z'} × σ × √{fmt_num(lead_days or 0)} hari, dibulatkan ke atas per SKU"
            )
        cols = st.columns(4)
        card(cols[0], "Service level", f"{fmt_num(service or 0)}%", hint=f"Z = {fmt_num(z, 2)}" if z is not None else "")
        card(cols[1], "Lead time", f"{fmt_num(lead_days or 0)} hari", hint="lead time impor dari Setting › Kedatangan impor" if import_mode else ("asumsi lead time lokal (bawaan)" if used_default else "lead time lokal tersimpan"))
        card(cols[2], "Total SS", f"{fmt_qty(ss.sum())} unit", hint=f"rata-rata {fmt_qty(ss.mean() if len(ss) else 0)} unit per SKU · sama di setiap periode")
        card(
            cols[3],
            "SKU stok di bawah SS",
            fmt_num(int(below_ss.sum())),
            hint=f"termasuk {fmt_num(int(empty.sum()))} kosong · berisiko habis sebelum barang baru datang"
            + (f" · {fmt_num(int((~known).sum()))} tanpa data stok" if int((~known).sum()) else ""),
            tone=None,
        )
        rows = []
        for group in groups:
            p = group.prefix
            if f"{p}_butuh" not in table.columns:
                continue
            qty = pd.to_numeric(table[f"{p}_qty"], errors="coerce").fillna(0.0)
            need = pd.to_numeric(table[f"{p}_butuh"], errors="coerce").fillna(0.0)
            short = known & (stok < need)
            gap = (need - stok).clip(lower=0).where(known, 0.0)
            dc_text = "–"
            if p == "m" and "kurang_setelah_dc" in table.columns:
                rest = pd.to_numeric(table["kurang_setelah_dc"], errors="coerce").fillna(0.0).where(known, 0.0)
                from_dc = (gap - rest).clip(lower=0)
                dc_text = f"{fmt_qty(from_dc.sum())} dari DC · {fmt_qty(rest.sum())} PO"
            style = " style='background:#eff6ff'" if group.extra else ""
            rows.append(
                f"<tr{style}><td>{group.label}</td><td>{fmt_qty(qty.sum())}</td><td>{fmt_qty(ss.sum())}</td>"
                f"<td><b>{fmt_qty(need.sum())}</b></td><td>{fmt_qty(stok.where(known, 0).sum())}</td>"
                f"<td><b>{fmt_num(int(short.sum()))}</b> SKU</td><td>{fmt_qty(gap.sum())} unit</td><td>{dc_text}</td></tr>"
            )
        header = (
            "<tr><th>Periode</th><th>Prediksi QTY (unit utuh)</th><th>+ SS</th><th>= Kebutuhan</th><th>Stok Site 10037</th>"
            "<th>SKU stok &lt; kebutuhan</th><th>Total kekurangan</th><th>Dipenuhi dari</th></tr>"
        )
        st.markdown(
            "<div class='sheet-scroll'><table class='insight-table' style='width:100%'>" + header + "".join(rows) + "</table></div>",
            unsafe_allow_html=True,
        )
        explain(
            [
                ("Safety stock (SS)", "stok cadangan agar tidak kosong saat permintaan atau pengiriman meleset dari perkiraan"),
                ("Rumus", formula),
                ("σ permintaan harian", "simpangan penjualan harian terhadap tren model; SKU yang penjualannya naik-turun tajam mendapat SS lebih besar"),
                ("Sama di setiap periode", "SS hanya menutup risiko selama lead time, jadi tidak bertambah walau periodenya lebih panjang"),
                ("Kebutuhan", "prediksi QTY periode + SS; SKU disebut kurang bila stok Site 10037 di bawah angka ini"),
                ("Stok di bawah SS", "lebih mendesak dari sekadar kurang: stok bahkan tidak cukup untuk cadangan, prioritaskan transfer dari DC / PO"),
                ("Dipenuhi dari", "kekurangan bulan dipenuhi dulu dari Site 10062, lalu Site 10036; sisanya PO ke supplier"),
            ]
        )


def top50_matrix(
    view: pd.DataFrame,
    actuals: dict[str, dict[str, float]],
    *,
    period: str,
    today: date,
    resume_label: str,
    all_sku: pd.DataFrame | None = None,
) -> None:
    """R5: baris Hari ini/Prediksi bulan/+periode, kolom actual, prediksi, kontribusi sales Top 50."""
    groups = period_groups(period, today)
    rows = []
    for group in groups:
        p = group.prefix
        act = actuals.get(p, {})
        end = pd.Timestamp(today) + pd.Timedelta(days=group.days - 1)
        span = fmt_date(today, short=True) if group.days == 1 else f"{fmt_date(today, short=True)} – {fmt_date(end.date(), short=True)}"
        qty_act = float(act.get("qty", 0.0))
        sales_act = float(act.get("sales", 0.0))
        share_base = float(act.get("store_sales", 0.0))
        share = sales_act / share_base * 100 if share_base > 0 else np.nan
        pred_sales = float(view[f"{p}_sales_exp"].sum() if f"{p}_sales_exp" in view.columns else view[f"{p}_sales"].sum())
        pred_base = 0.0
        if isinstance(all_sku, pd.DataFrame) and not all_sku.empty:
            col = f"{p}_sales_exp" if f"{p}_sales_exp" in all_sku.columns else f"{p}_sales"
            if col in all_sku.columns:
                pred_base = float(pd.to_numeric(all_sku[col], errors="coerce").fillna(0).sum())
        pred_share = pred_sales / pred_base * 100 if pred_base > 0 else np.nan
        rows.append(
            {
                "Periode": f"{group.label} · {span}",
                "Aktual pembanding": act.get("label", "-"),
                "QTY aktual": fmt_qty(qty_act),
                "Sales value aktual": fmt_idr(sales_act),
                "Prediksi QTY": fmt_qty(round(view[f"{p}_qty_exp"].sum() if f"{p}_qty_exp" in view.columns else view[f"{p}_qty"].sum())),
                "Prediksi sales value": fmt_idr(pred_sales),
                "Kontribusi aktual Top 50": f"{fmt_pct(share)} dari {fmt_idr(share_base)} (aktual seluruh toko)" if share_base > 0 else "-",
                "Kontribusi prediksi Top 50": f"{fmt_pct(pred_share)} dari {fmt_idr(pred_base)} (prediksi All SKU)" if pred_base > 0 else "-",
            }
        )
    frame = pd.DataFrame(rows)
    header = "".join(f"<th>{c}</th>" for c in frame.columns)
    body = ""
    for group, (_, r) in zip(groups, frame.iterrows()):
        style = " style='background:#eff6ff'" if group.extra else ""
        body += f"<tr{style}>" + "".join(f"<td>{r[c]}</td>" for c in frame.columns) + "</tr>"
    st.markdown(
        "<div class='sheet-scroll'><table style='width:100%'><thead><tr>" + header + "</tr></thead><tbody>" + body + "</tbody></table></div>",
        unsafe_allow_html=True,
    )
    extra = next((g.label for g in groups if g.extra), None)
    extra_text = f"; {extra} = {extra.lower()} terakhir s.d. kemarin" if extra else ""
    explain(
        [
            ("Aktual hari", "hari penuh terakhir sebelum hari ini (hari ini masih berjalan)"),
            ("Aktual bulan", "bulan penuh terakhir" + (f"; {extra_text.lstrip('; ')}" if extra_text else "")),
            ("Sales", "Harga setelah diskon × QTY, sesuai setelan Kecualikan batal & retur analisa ini"),
            ("Kontribusi aktual", "sales aktual Top 50 ÷ sales aktual seluruh toko pada tanggal aktual pembanding yang sama"),
            ("Kontribusi prediksi", "prediksi sales Top 50 ÷ prediksi sales All SKU (angka yang sama dengan kartu Prediksi sales · All SKU)"),
            ("Kenapa dasarnya berbeda", "aktual = transaksi yang sudah terjadi (kemarin / bulan lalu); prediksi = perkiraan periode berjalan. Bandingkan aktual dengan aktual, prediksi dengan prediksi"),
            ("Prediksi hari ini", "laju harian rata-rata periode prediksi (prediksi bulan ÷ jumlah hari), termasuk hari promo seperti 11.11, jadi bisa lebih tinggi dari aktual satu hari biasa"),
            ("Beda dengan kartu Sales bersih", "kartu itu memakai Total Pembayaran per pesanan (setelah voucher, termasuk ongkir)"),
        ]
    )


def past_predictions(features, sku: str, varian: str, start: date, end: date) -> pd.DataFrame:
    """Prediksi yang dulu dibuat untuk tanggal [start, end] (snapshot analisa): per tanggal D dipakai analisa
    terakhir yang dibuat paling lambat pada hari D (datanya s.d. D−1), sehingga bisa dibandingkan dengan aktual."""
    empty = pd.DataFrame(columns=["date", "pred_qty", "pred_sales"])
    if features is None or start > end:
        return empty
    try:
        from sqlalchemy import and_, select

        from src.core.feature_store import prediction_snapshot as snap

        query = select(snap.c.run_id, snap.c.created_at, snap.c.target_date, snap.c.varian, snap.c.pred_qty, snap.c.pred_sales).where(
            and_(snap.c.sku == str(sku), snap.c.target_date >= start, snap.c.target_date <= end)
        )
        with features.engine.connect() as conn:
            frame = pd.DataFrame(conn.execute(query).all(), columns=["run_id", "created_at", "date", "varian", "pred_qty", "pred_sales"])
    except Exception:
        return empty
    if frame.empty:
        return empty
    wanted = str(varian or "")
    if wanted and frame["varian"].astype(str).eq(wanted).any():
        frame = frame.loc[frame["varian"].astype(str).eq(wanted)]
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["created_at"] = pd.to_datetime(frame["created_at"])
    frame = frame.loc[frame["created_at"].dt.normalize() <= frame["date"]]
    if frame.empty:
        return empty
    latest = frame.groupby("date")["created_at"].transform("max")
    frame = frame.loc[frame["created_at"] == latest]
    return frame.groupby("date", as_index=False)[["pred_qty", "pred_sales"]].sum()


def backtest_days(item_orders: pd.DataFrame, days: list, weekday: np.ndarray, price: float) -> pd.DataFrame:
    """Uji mundur: prediksi 1 hari ke depan untuk tiap tanggal D yang sudah lewat, memakai model harian yang sama
    (level, tren, pola hari) dan hanya data s.d. D−1. Dipakai bila belum ada analisa tersimpan untuk tanggal itu."""
    from src.forecast import _robust_forecast

    out = []
    if item_orders is None or item_orders.empty or not days:
        return pd.DataFrame(columns=["date", "pred_qty", "pred_sales"])
    by_day = item_orders.groupby(pd.to_datetime(item_orders["order_time"]).dt.normalize())["qty"].sum().sort_index()
    start = by_day.index.min()
    for day in days:
        stamp = pd.Timestamp(day).normalize()
        if stamp <= start:
            continue
        index = pd.date_range(start, stamp - pd.Timedelta(days=1), freq="D")
        series = by_day.reindex(index, fill_value=0.0).to_numpy(dtype=float)
        qty = float(_robust_forecast(series, start, 1, weekday, forecast_start=stamp)) if series.sum() > 0 else 0.0
        out.append({"date": stamp, "pred_qty": qty, "pred_sales": qty * price})
    return pd.DataFrame(out, columns=["date", "pred_qty", "pred_sales"])


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


def _two_panel(x_labels, sold, pred, stock_line, ss_value: float, out_label: str | None, *, money: bool, title: str, unit: str, past=None, past_source=None) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.62, 0.38], subplot_titles=(title, "Proyeksi sisa stok"))
    fmt = fmt_idr_short if money else fmt_qty
    fig.add_bar(
        x=x_labels, y=sold, name="Terjual", marker_color="#1b3da6",
        text=[fmt(v) if v else "" for v in sold], textposition="outside",
        hovertemplate="%{x}<br>Terjual: %{customdata}<extra></extra>", customdata=[fmt(v) for v in sold], row=1, col=1,
    )
    if past is not None and np.nansum(np.asarray(past, dtype=float)) > 0:
        # Prediksi yang dulu dibuat untuk hari yang sudah lewat: dibandingkan langsung dengan batang Terjual.
        sources = list(past_source) if past_source is not None else [""] * len(past)
        hit = [
            ("" if not p else f"{fmt(p)} ({src or 'tersimpan'}) · aktual {fmt(a)} ({fmt_num(a / p * 100, 0)}%)")
            for a, p, src in zip(sold, past, sources)
        ]
        fig.add_bar(
            x=x_labels, y=past, name="Prediksi sebelumnya (hari lewat)", marker_color="rgba(238,77,45,0.30)",
            marker_line=dict(color="#ee4d2d", width=1.2), marker_pattern_shape="/",
            text=[fmt(v) if v else "" for v in past], textposition="outside",
            hovertemplate="%{x}<br>Prediksi sebelumnya: %{customdata}<extra></extra>", customdata=hit, row=1, col=1,
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
    past: pd.DataFrame | None = None,
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
    past_qty = pd.Series(0.0, index=days)
    past_sales = pd.Series(0.0, index=days)
    past_source = pd.Series("", index=days, dtype=object)
    lapsed = [d for d in days if d < pd.Timestamp(today)]
    saved_days: set = set()
    if isinstance(past, pd.DataFrame) and not past.empty:
        part = past.loc[(past["date"] >= pd.Timestamp(month_start)) & (past["date"] < pd.Timestamp(today))].set_index("date")
        past_qty.loc[part.index] = part["pred_qty"].to_numpy()
        past_sales.loc[part.index] = part["pred_sales"].to_numpy()
        past_source.loc[part.index] = "tersimpan"
        saved_days = set(part.index)
    # Hari yang belum punya analisa tersimpan diisi uji mundur, sehingga perbandingan tampil mulai tanggal 1.
    missing = [d for d in lapsed if d not in saved_days]
    if missing:
        back = backtest_days(item_orders, missing, weekday, float(row.get("harga_bersih", 0) or 0))
        if not back.empty:
            back = back.set_index("date")
            past_qty.loc[back.index] = back["pred_qty"].to_numpy()
            past_sales.loc[back.index] = back["pred_sales"].to_numpy()
            past_source.loc[back.index] = "uji mundur"
    has_stock = bool(row.get("ada_data_stok", False))
    stok = float(row["stok"]) if has_stock else 0.0
    ss = float(row["ss"])
    price = float(row.get("harga_bersih", 0) or 0)
    labels = [fmt_date(d, short=True) for d in days]

    def stock_projection(pred_series: np.ndarray, base: float) -> tuple[np.ndarray, str | None]:
        mask = np.array([d >= pd.Timestamp(today) for d in days]) if len(pred_series) == len(days) else np.ones(len(pred_series), bool)
        cumulative = np.cumsum(np.where(mask, pred_series, 0.0))
        # Stok snapshot berlaku mulai hari ini: hari sebelumnya tidak digambar (bukan stok historis).
        line = np.where(mask, base - cumulative, np.nan)
        out = next((i for i, v in enumerate(line) if mask[i] and v <= 0), None)
        return line, out

    qty_line, qty_out = stock_projection(pred.to_numpy(), stok) if has_stock else (None, None)
    sales_line = qty_line * price if qty_line is not None else None
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(
            _two_panel(labels, sold.to_numpy(), pred.to_numpy(), qty_line, ss, labels[qty_out] if qty_out is not None else None, money=False, title="Grafik QTY · Bulan ini", unit="Unit", past=past_qty.to_numpy(), past_source=past_source.to_numpy()),
            use_container_width=True, key=f"{key}-qty",
        )
    with c2:
        st.plotly_chart(
            _two_panel(labels, sold_sales.to_numpy(), pred_sales.to_numpy(), sales_line, ss * price, labels[qty_out] if qty_out is not None else None, money=True, title="Grafik Sales · Bulan ini", unit="Rupiah", past=past_sales.to_numpy(), past_source=past_source.to_numpy()),
            use_container_width=True, key=f"{key}-sales",
        )
    _sku_summary(
        row, today=today, month_end=month_end, sold=sold, sold_sales=sold_sales, pred=pred, pred_sales=pred_sales,
        qty_line=qty_line, days=days, past_qty=past_qty, past_sales=past_sales,
    )

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
    title_name = {"kuartal": "Kuartal", "semester": "Semester", "tahun": "Tahun"}[period]
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


def _sku_summary(
    row: pd.Series,
    *,
    today: date,
    month_end: date,
    sold: pd.Series,
    sold_sales: pd.Series,
    pred: pd.Series,
    pred_sales: pd.Series,
    qty_line: np.ndarray | None,
    days: pd.DatetimeIndex,
    past_qty: pd.Series | None = None,
    past_sales: pd.Series | None = None,
) -> None:
    """Kartu di bawah grafik SKU: penjualan, prediksi, stok Site 10037/10062/10036, rencana, dan catatan analisa."""
    month_start = date(today.year, today.month, 1)
    yesterday = (pd.Timestamp(today) - pd.Timedelta(days=1)).date()
    sold_days = max((today - month_start).days, 0)
    window_lo, window_hi = prediction_window("bulan", today)
    price = float(row.get("harga_bersih", 0) or 0)
    ss = float(row.get("ss", 0) or 0)
    daily_pred = float(row.get("pred_harian", 0) or 0)
    sold_qty, sold_val = float(sold.sum()), float(sold_sales.sum())
    rest_qty, rest_val = float(pred.sum()), float(pred_sales.sum())
    month_name = fmt_date(month_start, short=True).split(" ")[1]

    # Baris 1: penjualan dan prediksi
    cols = st.columns(4)
    sold_span = f"1–{fmt_date(yesterday, short=True)}" if sold_days else "belum ada hari penuh"
    card(
        cols[0],
        f"Terjual {sold_span}",
        f"{fmt_qty(sold_qty)} unit",
        hint=f"{fmt_idr(sold_val)} · rata-rata {fmt_num(sold_qty / sold_days, 1) if sold_days else '0'} unit/hari",
    )
    card(
        cols[1],
        f"Prediksi sisa {month_name} ({fmt_date(today, short=True)}–{fmt_date(month_end, short=True)})",
        f"{fmt_num(rest_qty, 1)} unit",
        hint=f"{fmt_idr(rest_val)} · perkiraan total {month_name}: {fmt_num(sold_qty + rest_qty, 1)} unit ({fmt_idr(sold_val + rest_val)})",
    )
    card(
        cols[2],
        f"Prediksi {fmt_date(window_lo, short=True)} – {fmt_date(window_hi, short=True)}",
        f"{fmt_qty(row['m_qty'])} unit",
        hint=f"{fmt_idr(row['m_sales'])} · {fmt_num(daily_pred, 2)} unit/hari · dasar kebutuhan stok",
    )
    card(
        cols[3],
        "Safety stock",
        f"{fmt_qty(ss)} unit",
        hint=f"nilai {fmt_idr(ss * price)} · harga bersih {fmt_idr(price)}/unit",
    )

    # Baris 2: stok per lokasi dan rencana
    has_stock = bool(row.get("ada_data_stok", False))
    stok = float(row["stok"]) if has_stock else 0.0
    need = float(row.get("m_butuh", 0) or 0)
    cols = st.columns(4)
    if has_stock:
        gap = stok - need
        card(
            cols[0],
            "Stok Site 10037 (toko)",
            f"{fmt_qty(stok)} unit",
            hint=f"kebutuhan {fmt_qty(need)} (prediksi {fmt_qty(row['m_qty'])} + SS {fmt_qty(ss)}) · "
            + (f"kurang {fmt_qty(-gap)} unit" if gap < 0 else f"lebih {fmt_qty(gap)} unit"),
            tone="stock",
        )
    else:
        card(cols[0], "Stok Site 10037 (toko)", "-", hint="Unggah Data stok Site 10037 untuk proyeksi sisa stok", tone="stock")
    for column, code, name in ((cols[1], "10062", "DC Cikupa"), (cols[2], "10036", "DC Cipeucang")):
        value = row.get(f"stok_{code}")
        if value is None or pd.isna(value):
            card(column, f"Stok Site {code} ({name})", "-", hint=f"Unggah Stok {name}", tone="stock")
            continue
        take = row.get(f"ambil_{code}")
        take = 0.0 if take is None or pd.isna(take) else float(take)
        cover = float(value) / daily_pred if daily_pred > 0 else float("inf")
        cover_text = "cukup lama (prediksi 0)" if not np.isfinite(cover) else f"cukup ±{fmt_num(cover, 0)} hari penjualan"
        card(
            column,
            f"Stok Site {code} ({name})",
            f"{fmt_qty(float(value))} unit",
            hint=(f"diambil {fmt_qty(take)} unit untuk Site 10037 · " if take > 0 else "") + cover_text,
            tone="stock",
        )
    plan = str(row.get("sumber_restock") or "").strip()
    rest = row.get("kurang_setelah_dc")
    rest = 0.0 if rest is None or pd.isna(rest) else float(rest)
    if not has_stock:
        plan_value, plan_hint = "-", "butuh data stok Site 10037"
    elif not plan:
        plan_value, plan_hint = "Tidak perlu", "stok Site 10037 menutup kebutuhan 30 hari"
    elif rest <= 0:
        plan_value, plan_hint = "Transfer DC", plan
    elif plan.startswith("Ambil"):
        plan_value, plan_hint = "Transfer + PO", plan
    else:
        plan_value, plan_hint = "PO supplier", plan
    card(cols[3], "Rencana restock", plan_value, hint=plan_hint, tone="stock")

    # Catatan analisa
    notes = []
    if has_stock:
        cover_days = stok / daily_pred if daily_pred > 0 else float("inf")
        if np.isfinite(cover_days):
            out_day = pd.Timestamp(today) + pd.Timedelta(days=int(cover_days))
            notes.append(("Stok Site 10037 cukup", f"±{fmt_num(cover_days, 0)} hari, perkiraan habis {fmt_date(out_day.date())}"))
        else:
            notes.append(("Stok Site 10037 cukup", "tidak habis pada laju prediksi sekarang (prediksi 0)"))
        below = None
        if qty_line is not None:
            below = next((days[i] for i, v in enumerate(qty_line) if np.isfinite(v) and v < ss), None)
        if stok < ss:
            notes.append(("Di bawah SS", "sudah sekarang: segera transfer / PO"))
        elif below is not None:
            notes.append(("Turun di bawah SS", f"sekitar {fmt_date(below.date())}; transfer sebaiknya tiba sebelum tanggal ini"))
        rop = row.get("rop")
        if rop is not None and pd.notna(rop):
            notes.append(("Titik pesan ulang (ROP)", f"{fmt_qty(rop)} unit = prediksi harian × lead time + SS; " + ("stok sudah di bawah ROP, pesan sekarang" if stok <= float(rop) else "pesan saat stok menyentuh angka ini")))
    if sold_days and daily_pred > 0:
        actual_rate = sold_qty / sold_days
        diff = (daily_pred - actual_rate) / actual_rate * 100 if actual_rate > 0 else None
        notes.append(
            (
                "Laju prediksi vs aktual",
                f"{fmt_num(daily_pred, 2)} vs {fmt_num(actual_rate, 2)} unit/hari bulan ini"
                + (f" ({'+' if diff >= 0 else '−'}{fmt_num(abs(diff), 0)}%)" if diff is not None else ""),
            )
        )
    if past_qty is not None and float(past_qty.sum()) > 0:
        covered = past_qty > 0
        p_qty, a_qty = float(past_qty[covered].sum()), float(sold[covered].sum())
        p_val, a_val = float(past_sales[covered].sum()), float(sold_sales[covered].sum())
        first_day = past_qty.index[covered][0]
        rate = a_qty / p_qty * 100 if p_qty > 0 else 0.0
        verdict = "sesuai" if 85 <= rate <= 115 else ("di atas prediksi" if rate > 115 else "di bawah prediksi (meleset)")
        notes.append(
            (
                f"Aktual vs prediksi sebelumnya ({fmt_date(first_day.date(), short=True)}–{fmt_date(yesterday, short=True)})",
                f"terjual {fmt_qty(a_qty)} vs prediksi {fmt_num(p_qty, 1)} unit ({fmt_num(rate, 0)}%, {verdict}); "
                f"sales {fmt_idr(a_val)} vs {fmt_idr(p_val)}",
            )
        )
    else:
        notes.append(("Prediksi sebelumnya", "belum ada riwayat penjualan yang cukup untuk menghitung prediksi hari-hari yang sudah lewat"))
    notes.append(("Prediksi sebelumnya", "dari analisa tersimpan bila ada; tanggal tanpa analisa tersimpan memakai uji mundur (model yang sama, hanya data s.d. sehari sebelumnya)"))
    notes.append(("Grafik", "batang biru = terjual s.d. kemarin; batang arsir = prediksi untuk hari itu (bandingkan dengan biru); merah = prediksi mulai hari ini; garis oranye = stok Site 10037 dikurangi prediksi kumulatif, garis putus = SS"))
    explain(notes, title="Catatan analisa")


def direction_html(value: float) -> str:
    if value > 0:
        return f"<span style='color:{UP_COLOR};font-weight:700'>▲</span>"
    if value < 0:
        return f"<span style='color:{DOWN_COLOR};font-weight:700'>▼</span>"
    return ""
