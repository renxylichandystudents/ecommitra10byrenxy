"""Tabel keputusan (Top 50 & Prediksi semua produk), Analisa safety stock, matriks Top 50, grafik per SKU."""

from __future__ import annotations

from datetime import date, timedelta
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
    "SS = Z × σ permintaan harian × √(lead time + periode tinjau), dibulatkan ke atas."
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


def span_text(lo, hi) -> str:
    from src.ui.analysis_dialog import span_text as _span

    return _span(lo, hi)


def empty_cell(row: pd.Series, cutoff: date) -> tuple[str, str, float | None]:
    """Lama kosong s.d. hari penuh terakhir data latih + sales hilang; aturan sama dengan Restock prioritas."""
    from src.core.periods import short_date

    known = bool(row.get("ada_data_stok", False))
    stock = row.get("stok")
    if not known:
        return "-", "belum ada data stok", None
    if stock is None or pd.isna(stock) or float(stock) > 0:
        return "-", "stok ada", None
    since = pd.to_datetime(row.get("zero_since"), errors="coerce")
    days = row.get("empty_days")
    if pd.isna(since) or days is None or pd.isna(days):
        return "Kosong", "tanggal mulai kosong belum tercatat", None
    first = bool(row.get("kosong_sejak_awal", False))
    mark = "≤ " if first else ""
    days = int(days)
    if days <= 0:
        text = f"kosong sejak {mark}{short_date(since.date())}"
        return text, f"belum ada hari penuh kosong s.d. {short_date(cutoff)}", 0.0
    text = f"{'≥ ' if first else ''}{days} hari"
    sub = f"sejak {mark}{short_date(since.date())} s.d. {short_date(cutoff)}"
    lost = row.get("empty_sales")
    if lost is not None and pd.notna(lost):
        sub += f" · hilang {fmt_idr(lost)}"
        month_lost = row.get("empty_month_sales")
        if month_lost is not None and pd.notna(month_lost) and float(month_lost) > 0 and float(month_lost) < float(lost) - 0.5:
            sub += f" (bulan ini {fmt_idr(month_lost)})"
    return text, sub, float(days)


def table_parts(
    view: pd.DataFrame,
    *,
    period: str,
    today: date,
    metric: str,
    resume_label: str,
    window_label: str,
    meta: dict | None = None,
) -> tuple[list[dict], list[dict], dict, pd.DataFrame]:
    """Kolom, baris, baris Total, dan salinan Excel. Kolom per kelompok: Prediksi, SS, Butuh, Stok.

    meta (dari `sku_insight.table_extras`): basis, sold_span, first, cutoff, month_end. Bila ada, kolom Terjual dipecah
    masuk vs terjual bersih, ditambah Prediksi bulan berjalan, dan Lama kosong dihitung s.d. hari penuh terakhir data latih."""
    meta = meta if meta and "run_qty" in view.columns else None
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
        {"id": "variance", "label": "Varian", "pin": True, "width": 160, "kind": "name", "sort": True},
    ]
    if meta:
        basis = meta["basis"]
        lo, hi = meta["sold_span"] if meta.get("sold_span") else (None, None)
        sold_group = f"Aktual · {span_text(lo, hi)}" if lo else f"Aktual · {resume_label}"
        columns += [
            {"id": "sold_bersih", "label": "Terjual bersih" + (" (dasar)" if basis == "bersih" else ""), "group": sold_group, "kind": "num", "sort": True},
            {"id": "sold_masuk", "label": "Masuk" + (" (dasar)" if basis == "masuk" else " (semua)"), "group": sold_group, "kind": "num", "sort": True},
            {"id": "run", "label": main_label, "group": f"Prediksi bulan berjalan · {span_text(meta['first'], meta['month_end'])}", "kind": "num", "sort": True},
        ]
    else:
        columns.append({"id": "sold", "label": main_label, "group": f"Terjual · {resume_label}", "kind": "num", "sort": True})
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
            {"id": "dc_take", "label": "Ambil dari DC", "group": "Stok DC", "width": 300, "kind": "name", "sort": True, "tone": "stock"},
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
        }
        if meta:
            for side in ("bersih", "masuk"):
                qty, sales = float(row[f"sold_qty_{side}"]), float(row[f"sold_sales_{side}"])
                main = qty if metric == "qty" else sales
                cells[f"sold_{side}"] = {"v": main, "t": fmt_qty(qty) if metric == "qty" else fmt_idr(sales),
                                         "s": fmt_idr(sales) if metric == "qty" else f"{fmt_qty(qty)} unit"}
                totals[f"sold_{side}"] = totals.get(f"sold_{side}", 0.0) + main
            run_qty, run_sales = float(row["run_qty"]), float(row["run_sales"])
            run_main = run_qty if metric == "qty" else run_sales
            act = float(row["run_act_qty"] if metric == "qty" else row["run_act_sales"])
            act_text = fmt_qty(act) if metric == "qty" else fmt_idr(act)
            cells["run"] = {
                "v": run_main,
                "t": fmt_qty(round(run_qty)) if metric == "qty" else fmt_idr(run_sales),
                "s": (f"{fmt_idr(run_sales)} · " if metric == "qty" else f"{fmt_qty(round(run_qty))} unit · ")
                + (f"aktual {'bersih' if meta['basis'] == 'bersih' else 'masuk'} {span_text(meta['first'], meta['cutoff'])}: {act_text}" if meta["cutoff"] >= meta["first"] else "belum ada hari penuh"),
            }
            totals["run"] = totals.get("run", 0.0) + run_main
        else:
            cells["sold"] = {
                "v": sold_value,
                "t": fmt_qty(sold_value) if metric == "qty" else fmt_idr(sold_value),
                "s": fmt_idr(row["sales_total"]) if metric == "qty" else f"{fmt_qty(row['qty_total'])} unit",
            }
            totals["sold"] = totals.get("sold", 0.0) + sold_value
        export = {
            "Rank": int(row["peringkat"]),
            "SKU": cells["sku"]["t"],
            "Produk": cells["name"]["t"],
            "Varian": cells["variance"]["t"],
            "Label": ", ".join(row.get("label") or []),
        }
        if meta:
            when = span_text(*meta["sold_span"]) if meta.get("sold_span") else resume_label
            export[f"QTY masuk ({when})"] = float(row["sold_qty_masuk"])
            export[f"Sales produk masuk ({when})"] = float(row["sold_sales_masuk"])
            export[f"QTY terjual bersih ({when})"] = float(row["sold_qty_bersih"])
            export[f"Sales produk bersih ({when})"] = float(row["sold_sales_bersih"])
            run_when = span_text(meta["first"], meta["month_end"])
            export[f"Prediksi bulan berjalan QTY ({run_when})"] = float(row["run_qty"])
            export[f"Prediksi bulan berjalan sales produk ({run_when})"] = float(row["run_sales"])
            export[f"Aktual {meta['basis']} bulan berjalan QTY (s.d. {span_text(meta['cutoff'], meta['cutoff'])})"] = float(row["run_act_qty"])
        else:
            export["QTY terjual"] = float(row["qty_total"])
            export["Sales terjual"] = float(row["sales_total"])
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
            # Total prediksi = jumlah nilai harapan sebelum dibulatkan per SKU, sama dengan kartu Ringkasan & matriks Top 50.
            expected = row.get(f"{p}_qty_exp" if metric == "qty" else f"{p}_sales_exp", main)
            expected = main if expected is None or pd.isna(expected) else expected
            for name, value in ((f"{p}_pred", expected), (f"{p}_ss", row[f"{p}_ss"]), (f"{p}_butuh", row[f"{p}_butuh"])):
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
            from src.core.dc_stock import dc_take_label

            plan = dc_take_label(row)
            cells["dc_take"] = {"v": plan, "t": plan or "Tidak perlu"}
            export["Ambil dari DC"] = plan
        cover = row.get("hari_cukup")
        cover_ok = cover is not None and pd.notna(cover) and np.isfinite(float(cover))
        cells["cover"] = {
            "v": float(cover) if cover_ok else None,
            "t": fmt_num(cover, 0) if cover_ok else ("∞" if pd.notna(cover) else "-"),
            "s": f"habis {fmt_date(row.get('tanggal_habis'), short=True)}" if cover_ok and row.get("tanggal_habis") else "",
        }
        if meta:
            empty_text, empty_sub, empty_days = empty_cell(row, meta["cutoff"])
            cells["empty"] = {"v": empty_days, "t": empty_text, "s": empty_sub}
            if empty_sub:
                export["Sales hilang sejak kosong"] = float(row["empty_sales"]) if pd.notna(row.get("empty_sales")) else None
        else:
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
        money = metric == "sales" and (name.endswith("_pred") or name.startswith("sold") or name == "run")
        total[name] = {"t": fmt_idr(value) if money else fmt_qty(round(value))}
        if name.endswith("_pred") or name == "run":
            total[name]["s"] = "sebelum dibulatkan per SKU"
    return columns, rows, total, pd.DataFrame(export_rows)


def decision_table_guide(meta: dict | None, metric: str) -> None:
    """Cara baca kolom aktual, prediksi bulan berjalan, dan lama kosong (dasar bersih/masuk tertulis)."""
    if not meta:
        return
    basis = meta["basis"]
    word = "terjual bersih" if basis == "bersih" else "masuk"
    sold = f"{span_text(*meta['sold_span'])}" if meta.get("sold_span") else "periode penjualan terpilih"
    cutoff = span_text(meta["cutoff"], meta["cutoff"])
    explain(
        [
            ("Dasar tabel ini", f"{word.upper()}, sama dengan dasar prediksi (centang Kecualikan batal & retur {'dicentang' if basis == 'bersih' else 'tidak dicentang'} saat analisa dijalankan). "
             "Kolom yang menjadi dasar ditandai (dasar)"),
            (f"Aktual · {sold}", "data nyata pada periode penjualan yang dipilih di atas, dihitung dari semua status pesanan. "
             "Terjual bersih = masuk dikurangi pesanan batal, pesanan Belum Bayar, dan barang retur. "
             "Masuk = semua pesanan yang masuk, termasuk yang kemudian batal, belum dibayar, atau diretur"),
            ("Sales", "sales produk = Harga Setelah Diskon × QTY, sebelum voucher; bukan sales bersih Total Pembayaran (dasar target), "
             "karena Total Pembayaran per pesanan tidak bisa dibagi tepat per SKU"),
            (f"Prediksi bulan berjalan · {span_text(meta['first'], meta['month_end'])}",
             f"aktual {word} tgl 1 s.d. {cutoff} (hari penuh terakhir data latih, data ≥ 23:00) + prediksi harian × pola hari untuk sisa bulan. "
             "Angka abu-abu menyebut bagian aktualnya. Sama dengan kolom Prediksi bulan berjalan di Pergerakan Top 50"),
            ("Prediksi 30 hari", "jendela hari ini s.d. 30 hari ke depan (bukan bulan kalender); dasar kebutuhan stok dan safety stock"),
            ("Lama kosong", f"hanya untuk SKU yang stok Site 10037 terakhirnya 0: dari unggahan Data stok pertama yang mencatat 0 (rangkaian kosong terakhir) "
             f"s.d. {cutoff}, hari penuh terakhir data latih; bertambah setiap data latih ditambah selama stok belum diisi. "
             "\"≥/≤\" bila semua unggahan tersimpan sudah 0 (angka minimal). Hilang = prediksi harian × pola hari tiap hari kosong − yang tetap terjual, "
             "sama dengan Restock prioritas"),
        ],
        title="Cara membaca tabel",
    )


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
    meta: dict | None = None,
) -> str:
    """Tabel bersama R8 dan Prediksi semua produk. Mengembalikan item_key yang dicentang di kolom Grafik.

    filename=None: tombol unduh tidak dibuat di dalam tabel (pemanggil menaruhnya di bilah navigasi halaman).
    step: tampilkan `step` baris teratas (setelah diurutkan) lalu tombol Muat lagi menambah `step` baris.
    """
    columns, rows, total, export = table_parts(view, period=period, today=today, metric=metric, resume_label=resume_label, window_label=window_label, meta=meta)
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
    review_days: float = 0.0,
    class_levels: dict | None = None,
    calibration: float = 1.0,
    run_meta: dict | None = None,
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
        exposure = (lead_days or 0) + (review_days or 0)
        from src.core.inventory import service_level_to_z

        levels = class_levels or {}
        z_text = " · ".join(f"{k} {fmt_num(service_level_to_z(v), 2)}" for k, v in levels.items()) if levels else (fmt_num(z, 2) if z is not None else "Z")
        r = float(calibration or 1.0)
        r_text = f" × r {fmt_num(r, 2)}" if abs(r - 1.0) > 1e-9 else ""
        if import_mode:
            formula = (f"Z(kelas ABC){r_text} × √((L + R) × σ² + permintaan² × σ_L²), σ_L = (lead time maks − rata-rata) ÷ 1,645; "
                       f"L = {fmt_num(lead_days or 0)} hari, R = {fmt_num(review_days or 0)} hari; Z per kelas {z_text}")
        else:
            formula = (
                f"Z(kelas ABC){r_text} × σ permintaan harian × √(lead time + periode tinjau) = Z{r_text} × σ × √({fmt_num(lead_days or 0)} + "
                f"{fmt_num(review_days or 0)}) = √{fmt_num(exposure)} hari, dibulatkan ke atas per SKU; Z per kelas {z_text}"
            )
        cols = st.columns(4)
        if levels:
            card(cols[0], "Service level per kelas", " · ".join(f"{k} {fmt_num(v)}%" for k, v in levels.items()),
                 hint=f"dasar {fmt_num(service or 0)}% · kelas ABC dari QTY 90 hari" + (f" · kalibrasi r {fmt_num(r, 2)}" if r_text else ""))
        else:
            card(cols[0], "Service level", f"{fmt_num(service or 0)}%", hint=f"Z = {fmt_num(z, 2)}" if z is not None else "")
        card(cols[1], "Lead time + tinjau", f"{fmt_num(lead_days or 0)} + {fmt_num(review_days or 0)} hari", hint="lead time impor dari Setting › Kedatangan impor" if import_mode else ("asumsi lead time lokal (bawaan)" if used_default else "lead time lokal tersimpan"))
        card(cols[2], "Total SS", f"{fmt_qty(ss.sum())} unit", hint=f"rata-rata {fmt_qty(ss.mean() if len(ss) else 0)} unit per SKU · sama di setiap periode")
        card(
            cols[3],
            "SKU stok di bawah SS",
            fmt_num(int(below_ss.sum())),
            hint=f"termasuk {fmt_num(int(empty.sum()))} kosong · berisiko habis sebelum barang baru datang"
            + (f" · {fmt_num(int((~known).sum()))} tanpa data stok" if int((~known).sum()) else ""),
            tone=None,
        )
        from src.core.dc_stock import DC_SITES, transfer_plan

        codes = [code for code, _n, _s in DC_SITES]

        def _dc_split(gap: pd.Series) -> str:
            if not any(f"stok_{code}" in table.columns for code in codes):
                return "belum ada data stok DC"
            from_dc = rest = 0.0
            for idx in gap.index[gap > 0]:
                available = {code: (None if f"stok_{code}" not in table.columns or pd.isna(table.at[idx, f"stok_{code}"]) else float(table.at[idx, f"stok_{code}"]))
                             for code in codes}
                take, remaining = transfer_plan(float(np.ceil(gap.at[idx])), available)
                from_dc += sum(take.values())
                rest += remaining
            return f"{fmt_qty(from_dc)} dari DC · {fmt_qty(rest)} PO"

        def _row(label: str, qty: pd.Series, *, need: pd.Series | None = None, extra: bool = False, note: str = "") -> str:
            need = qty + ss if need is None else need
            short = known & (stok < need)
            gap = (need - stok).clip(lower=0).where(known, 0.0)
            style = " style='background:#eff6ff'" if extra else ""
            sub = f"<br><span style='color:#64748b;font-size:.85em'>{note}</span>" if note else ""
            return (
                f"<tr{style}><td>{label}{sub}</td><td>{fmt_qty(qty.sum())}</td><td>{fmt_qty(ss.sum())}</td>"
                f"<td><b>{fmt_qty(need.sum())}</b></td><td>{fmt_qty(stok.where(known, 0).sum())}</td>"
                f"<td><b>{fmt_num(int(short.sum()))}</b> SKU</td><td>{fmt_qty(gap.sum())} unit</td><td>{_dc_split(gap)}</td></tr>"
            )

        rows = []
        for group in groups:
            p = group.prefix
            if f"{p}_butuh" not in table.columns:
                continue
            qty = pd.to_numeric(table[f"{p}_qty"], errors="coerce").fillna(0.0)
            label = group.label if any(ch.isdigit() for ch in group.label) else f"{group.label} ({fmt_date(today, short=True)})"
            rows.append(_row(label, qty, need=pd.to_numeric(table[f"{p}_butuh"], errors="coerce").fillna(0.0), extra=group.extra))
            if p == "d" and run_meta and "run_rest_qty" in table.columns:
                from src.ui.analysis_dialog import span_text

                rest_start = max(run_meta["first"], run_meta["cutoff"] + timedelta(days=1))
                rest_qty = np.floor(pd.to_numeric(table["run_rest_qty"], errors="coerce").fillna(0.0) + 1e-9)
                act = pd.to_numeric(table["run_act_qty"], errors="coerce").fillna(0.0).sum()
                word = "terjual bersih" if run_meta["basis"] == "bersih" else "masuk"
                proj = act + rest_qty.sum()
                note = (f"aktual {word} {span_text(run_meta['first'], run_meta['cutoff'])}: {fmt_qty(act)} unit (sudah terjual, tidak butuh stok) · "
                        f"proyeksi bulan {fmt_qty(proj)} unit" if run_meta["cutoff"] >= run_meta["first"] else "belum ada hari penuh bulan ini")
                if rest_start < today:
                    note += (f" · {span_text(rest_start, today - timedelta(days=1))} sudah lewat tetapi belum penuh di data latih "
                             f"(hari penuh terakhir {span_text(run_meta['cutoff'], run_meta['cutoff'])}), jadi masih dihitung sebagai prediksi; "
                             "unggah transaksi terbaru lalu jalankan analisa agar menjadi aktual")
                rows.append(_row(f"Bulan berjalan · sisa {span_text(rest_start, run_meta['month_end'])} "
                                 f"({(run_meta['month_end'] - rest_start).days + 1} hari)", rest_qty, note=note))
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
                ("Kelas ABC", "A = SKU penyumbang 80% QTY 90 hari, B = 15% berikutnya, C = sisanya; kelas A diberi tingkat layanan lebih tinggi"),
                ("Kalibrasi r", "galat prediksi nyata selama lead time + tinjau di uji walk-forward ÷ σ × √(L + R), diestimasi robust (median); "
                                "r = 1 bila analisa belum punya hasil uji ini"),
                ("Sama di setiap periode", "SS hanya menutup risiko selama lead time, jadi tidak bertambah walau periodenya lebih panjang"),
                ("Kebutuhan", "prediksi QTY periode + SS; SKU disebut kurang bila stok Site 10037 di bawah angka ini"),
                ("Stok di bawah SS", "lebih mendesak dari sekadar kurang: stok bahkan tidak cukup untuk cadangan, prioritaskan transfer dari DC / PO"),
                ("Prediksi QTY (unit utuh)", "prediksi per SKU dibulatkan ke bawah lalu dijumlah; karena itu sedikit lebih kecil dari total di Ringkasan "
                 "total Top 50 yang menjumlah nilai sebelum dibulatkan"),
                ("Bulan berjalan", "kebutuhan untuk sisa bulan kalender (hari ini s.d. akhir bulan) = prediksi harian × pola hari tiap sisa hari + SS. "
                 "Aktual tanggal 1 s.d. hari penuh terakhir sudah terjual, jadi tidak dihitung sebagai kebutuhan stok; proyeksi bulan = aktual + sisa"),
                ("SKU stok < kebutuhan vs SKU stok di bawah SS", "dua ukuran berbeda: kartu atas menghitung stok < SS saja (lebih mendesak), tabel menghitung stok < prediksi periode + SS"),
                ("Dipenuhi dari", "kekurangan tiap periode dipenuhi dulu dari Site 10062, lalu Site 10036 (stok DC saat ini); sisanya PO ke supplier"),
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
    exclude: bool | None = None,
) -> None:
    """R5: baris Hari ini/Prediksi bulan/+periode; aktual masuk vs bersih, prediksi, kontribusi sales Top 50."""
    groups = period_groups(period, today)
    rows = []
    for group in groups:
        p = group.prefix
        act = actuals.get(p, {})
        end = pd.Timestamp(today) + pd.Timedelta(days=group.days - 1)
        span = fmt_date(today, short=True) if group.days == 1 else f"{fmt_date(today, short=True)} – {fmt_date(end.date(), short=True)}"
        qty_act = float(act.get("qty", 0.0))
        sales_act = float(act.get("sales", 0.0))
        qty_in = float(act.get("qty_masuk", qty_act))
        sales_in = float(act.get("sales_masuk", sales_act))
        share_base = float(act.get("store_sales", 0.0))
        lo, hi = act.get("start"), act.get("end")
        if lo is None:
            when = act.get("label", "-")
        elif lo == hi:
            when = f"{fmt_date(lo)} (1 hari, hari penuh terakhir)"
        else:
            when = f"{act.get('label', '').removeprefix('Aktual ')} · {fmt_date(lo)} – {fmt_date(hi)} ({(hi - lo).days + 1} hari)"

        def _drop(net: float, gross: float) -> str:
            return f"<br><span style='color:#64748b;font-size:.85em'>{fmt_pct((gross - net) / gross * 100, 1)} lebih kecil dari masuk</span>" if gross > 0 else ""
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
                "Periode prediksi": f"{group.label} · {span}",
                "Aktual pembanding (tanggal)": when,
                "QTY masuk": fmt_qty(qty_in),
                "QTY terjual bersih": fmt_qty(qty_act) + _drop(qty_act, qty_in),
                "Sales produk masuk": fmt_idr(sales_in),
                "Sales produk bersih": fmt_idr(sales_act) + _drop(sales_act, sales_in),
                "Prediksi QTY": fmt_qty(round(view[f"{p}_qty_exp"].sum() if f"{p}_qty_exp" in view.columns else view[f"{p}_qty"].sum())),
                "Prediksi sales produk": fmt_idr(pred_sales),
                "Kontribusi aktual Top 50": f"{fmt_pct(share)} dari {fmt_idr(share_base)} (sales produk bersih seluruh toko)" if share_base > 0 else "-",
                "Kontribusi prediksi Top 50": f"{fmt_pct(pred_share)} dari {fmt_idr(pred_base)} (prediksi semua SKU)" if pred_base > 0 else "-",
                "Sales bersih seluruh toko (dasar target)": fmt_idr(float(act["store_net"])) if "store_net" in act else "-",
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
    basis = ("Prediksi dilatih tanpa batal, Belum Bayar & retur (Kecualikan batal & retur dicentang saat analisa dijalankan), jadi bandingkan prediksi dengan kolom bersih."
             if exclude else "Prediksi dilatih dengan semua pesanan (Kecualikan batal & retur tidak dicentang saat analisa dijalankan), jadi bandingkan prediksi dengan kolom masuk."
             if exclude is not None else "")
    explain(
        [
            ("Cara baca singkat", "tiap baris = satu periode prediksi (kiri) dan periode aktual yang sudah selesai sebagai pembanding (kolom tanggal). "
             "Aktual dibagi dua: masuk = semua pesanan yang benar-benar masuk ke toko, bersih = yang akhirnya benar-benar terjual. " + basis),
            ("Aktual pembanding (tanggal)", "baris hari: hari penuh terakhir (data sampai ≥ 23:00; hari ini masih berjalan). Baris bulan: bulan kalender penuh terakhir, "
             "tanggal 1 s.d. akhir bulan" + (f"; {extra_text.lstrip('; ')}" if extra_text else "") + ". Periode prediksi dan aktual sengaja beda: aktual sudah terjadi, prediksi belum"),
            ("QTY / Sales produk masuk", "semua pesanan Top 50 pada tanggal itu, termasuk yang kemudian batal, belum dibayar, atau diretur. Untuk melihat minat beli yang sebenarnya masuk"),
            ("QTY terjual / Sales produk bersih", "masuk dikurangi pesanan batal, pesanan Belum Bayar, dan barang yang diretur. Yang benar-benar menjadi penjualan. "
             "Teks abu-abu = berapa persen hilang dari masuk karena batal / belum bayar / retur"),
            ("Sales produk", "Harga Setelah Diskon × QTY per produk, belum dipotong voucher. Dasar prediksi, karena bisa dihitung per SKU"),
            ("Sales bersih seluruh toko (dasar target)", "Total Pembayaran semua pesanan toko − batal − Belum Bayar − retur, sudah dipotong voucher. "
             "Angka yang sama dengan kartu Sales bersih dan target; hanya bisa dihitung per toko, bukan per SKU"),
            ("Kontribusi aktual", "sales produk bersih Top 50 ÷ sales produk bersih seluruh toko pada tanggal pembanding yang sama"),
            ("Kontribusi prediksi", "prediksi sales Top 50 ÷ prediksi sales semua SKU (angka yang sama dengan kartu Prediksi sales · semua SKU)"),
            ("Prediksi hari ini", "prediksi bulan ÷ jumlah hari × pola hari ini (hari dalam minggu, gajian, tanggal kembar seperti 11.11), sama dengan Pantauan harian dan breakdown per tanggal"),
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


def _round_label(money: bool):
    """Label angka grafik dibulatkan tanpa desimal: QTY unit utuh, sales Rupiah utuh (5.169.500; label batang tegak)."""
    return lambda v: fmt_num(round(float(v)), 0) if v is not None and np.isfinite(float(v)) else "-"


LABEL_FONT = 10
CHART_HEIGHT = 760
TOP_PANEL_PX = (CHART_HEIGHT - 70 - 40) * (1 - 0.2) * 0.6  # tinggi area panel atas (px): margin, jarak antarpanel, porsi 60%


def label_headroom(labels: list[tuple[object, float, str]], panel_px: float = TOP_PANEL_PX, char_px: float = LABEL_FONT * 0.68) -> float:
    """Batas atas sumbu Y agar setiap label tegak (panjang teks × lebar huruf) masih muat di dalam panel, tidak menabrak judul.

    Label setinggi L px di atas batang h harus memenuhi h + L × (Y / panel_px) ≤ Y → Y ≥ h ÷ (1 − L ÷ panel_px)."""
    need = 0.0
    for _x, height, text in labels:
        if height <= 0:
            continue
        length = len(str(text)) * char_px + 12  # + jarak yshift & ruang napas
        share = min(length / panel_px, 0.85)
        need = max(need, height / (1 - share))
    return need if need > 0 else 1.0


def _two_panel(
    x_labels, sold, pred, stock_line, ss_value: float, out_label: str | None, *, money: bool, title: str, unit: str,
    past=None, past_source=None, sold_name: str = "Terjual", sold_hover=None, today_index: int | None = None, stock_past=None,
    stock_past_hover=None,
) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.2, row_heights=[0.6, 0.4], subplot_titles=(title, "Proyeksi sisa stok"))
    fmt = _round_label(money)
    lapsed = [today_index is None or i < today_index for i in range(len(x_labels))]
    # Batang tanpa teks: angka ditulis satu label per tanggal (lihat anotasi di bawah) agar tidak saling menimpa.
    label_style = {}
    fig.add_bar(
        x=x_labels, y=sold, name=sold_name, marker_color="#1b3da6",
        # Hari yang sudah lewat selalu diberi angka (termasuk 0) agar tanggal 1 s.d. kemarin terbaca lengkap.
        **label_style,
        hovertemplate="%{x}<br>%{customdata}<extra></extra>",
        customdata=list(sold_hover) if sold_hover is not None else [f"{sold_name}: {fmt(v)}" for v in sold], row=1, col=1,
    )
    if past is not None and (past_source is None or any(str(src) for src in past_source)):
        # Prediksi yang dulu dibuat untuk hari yang sudah lewat: dibandingkan langsung dengan batang Terjual.
        sources = list(past_source) if past_source is not None else [""] * len(past)
        hit = [
            ("" if not src else f"{fmt(p)} ({src}) · aktual {fmt(a)}" + (f" ({fmt_num(a / p * 100, 0)}% dari prediksi)" if p else " (prediksi 0)"))
            for a, p, src in zip(sold, past, sources)
        ]
        fig.add_bar(
            x=x_labels, y=past, name="Prediksi sebelumnya (hari lewat)", marker_color="rgba(238,77,45,0.30)",
            marker_line=dict(color="#ee4d2d", width=1.2), marker_pattern_shape="/",
            **label_style,
            hovertemplate="%{x}<br>Prediksi sebelumnya: %{customdata}<extra></extra>", customdata=hit, row=1, col=1,
        )
    fig.add_bar(
        x=x_labels, y=pred, name="Prediksi", marker_color="#ee4d2d",
        **label_style,
        hovertemplate="%{x}<br>Prediksi: %{customdata}<extra></extra>", customdata=[fmt(v) for v in pred], row=1, col=1,
    )
    if stock_past is not None and np.isfinite(np.asarray(stock_past, dtype=float)).any():
        # Tanggal 1 s.d. hari ini: stok dari riwayat unggahan Data stok Site 10037 ± terjual di antaranya.
        fig.add_scatter(
            x=x_labels, y=stock_past, mode="lines+markers", name="Stok tanggal lalu (unggahan ± terjual)", line=dict(color="#64748b", width=2),
            marker=dict(size=5), hovertemplate="%{x}<br>%{customdata}<extra></extra>",
            customdata=list(stock_past_hover) if stock_past_hover is not None else [fmt(v) for v in stock_past], row=2, col=1,
        )
    if stock_line is not None:
        fig.add_scatter(
            x=x_labels, y=stock_line, mode="lines+markers", name="Sisa stok (stok − kumulatif prediksi)", line=dict(color="#ea580c", width=2),
            hovertemplate="%{x}<br>Sisa stok: %{customdata}<extra></extra>", customdata=[fmt(v) if np.isfinite(v) else "-" for v in stock_line], row=2, col=1,
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
    if today_index is not None and 0 < today_index < len(x_labels):
        # Garis batas per panel (bukan seluruh kertas) agar tidak menembus judul "Proyeksi sisa stok".
        for axis in ("y", "y2"):
            fig.add_shape(type="line", xref="x", yref=f"{axis} domain", x0=today_index - 0.5, x1=today_index - 0.5, y0=0, y1=1,
                          line=dict(color="#64748b", width=1, dash="dot"))
    fig.update_layout(barmode="group", height=CHART_HEIGHT, margin=dict(l=40, r=20, t=70, b=40), legend=dict(orientation="h", y=-0.1), font=dict(family="Plus Jakarta Sans"))
    # Tanggal tegak lurus (sama di kedua panel), tidak miring.
    fig.update_xaxes(showticklabels=True, tickangle=-90, tickfont=dict(size=9))
    # Satu label tegak per tanggal di atas batang tertinggi: hari lewat "terjual / prediksi sebelumnya", hari mendatang "prediksi".
    sold_v = np.nan_to_num(np.asarray(sold, dtype=float))
    pred_v = np.nan_to_num(np.asarray(pred, dtype=float))
    past_v = np.nan_to_num(np.asarray(past, dtype=float)) if past is not None else np.zeros(len(x_labels))
    has_past = past is not None and (past_source is None or any(str(src) for src in past_source))
    labels = []
    for i, x in enumerate(x_labels):
        if lapsed[i]:
            text, height = (f"{fmt(sold_v[i])} / {fmt(past_v[i])}" if has_past else fmt(sold_v[i])), max(sold_v[i], past_v[i] if has_past else 0.0)
        else:
            text, height = fmt(pred_v[i]), pred_v[i]
        labels.append((x, float(height), text))
        fig.add_annotation(x=x, y=height, xref="x", yref="y", text=text, textangle=-90, yanchor="bottom", yshift=3, showarrow=False,
                           font=dict(size=LABEL_FONT, color="#334155"))
    fig.update_yaxes(title_text=unit, range=[0, label_headroom(labels)], row=1, col=1)
    fig.update_yaxes(title_text=unit, row=2, col=1)
    return fig


def past_stock_path(days, today: date, stock_now: float | None, sold: pd.Series, history: pd.DataFrame | None) -> tuple[np.ndarray, list[str]]:
    """Stok akhir hari untuk tanggal 1 s.d. kemarin + stok hari ini (titik awal proyeksi).

    Dasar: unggahan Data stok Site 10037 (`history`: _submitted_at, stok untuk SKU ini; unggahan terakhir per hari). Hari dengan
    unggahan = stok tercatat; hari sesudah unggahan = stok unggahan − terjual sejak itu; hari sebelum unggahan pertama yang ada =
    stok unggahan + terjual di antaranya (perkiraan mundur, tanpa tahu barang masuk). Tanpa riwayat: mundur dari stok sekarang."""
    days = pd.DatetimeIndex(days)
    ref = pd.Timestamp(today).normalize()
    values = np.full(len(days), np.nan)
    notes = [""] * len(days)
    sold = pd.to_numeric(sold.reindex(days), errors="coerce").fillna(0.0)
    snaps: dict[pd.Timestamp, float] = {}
    if isinstance(history, pd.DataFrame) and not history.empty and {"_submitted_at", "stok"} <= set(history.columns):
        from src.core.inventory import snapshot_time

        work = history.assign(_t=snapshot_time(history["_submitted_at"])).dropna(subset=["_t"]).sort_values("_t")
        work = work.loc[work["_t"].dt.normalize() <= ref]
        for stamp, part in work.groupby("_t"):
            snaps[pd.Timestamp(stamp).normalize()] = float(pd.to_numeric(part["stok"], errors="coerce").fillna(0.0).clip(lower=0).sum())
    if stock_now is not None and np.isfinite(stock_now):
        snaps[ref] = float(stock_now)  # titik hari ini = stok yang dipakai proyeksi
    if not snaps:
        return values, notes
    snap_days = sorted(snaps)
    for i, day in enumerate(days):
        if day > ref:
            break
        if day in snaps:
            values[i], notes[i] = snaps[day], "stok tercatat di unggahan"
            continue
        before = [s for s in snap_days if s < day]
        if before:
            base = before[-1]
            used = float(sold.loc[(sold.index > base) & (sold.index <= day)].sum())
            values[i] = max(snaps[base] - used, 0.0)
            notes[i] = f"stok unggahan {fmt_date(base, short=True)} − terjual sesudahnya"
        else:
            base = snap_days[0]
            added = float(sold.loc[(sold.index > day) & (sold.index <= base)].sum())
            values[i] = snaps[base] + added
            notes[i] = f"perkiraan mundur: stok {fmt_date(base, short=True)} + terjual di antaranya (barang masuk tidak diketahui)"
    return values, notes


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
    lines: pd.DataFrame | None = None,
    basis: str = "bersih",
    stock_history: pd.DataFrame | None = None,
) -> None:
    """R9: Grafik QTY dan Grafik Sales, dua panel sumbu X bersama.

    Batang Terjual memakai dasar `basis` yang sama dengan data latih dan tabel Top 50 (bersih atau masuk), dihitung
    dari `lines` (`normalize_lines` semua status) bila ada; hover menampilkan keduanya beserta batal/Belum Bayar/retur."""
    from src.core.sku_insight import daily_profile

    month_start = date(today.year, today.month, 1)
    month_end = (pd.Timestamp(today) + pd.offsets.MonthEnd(0)).date()
    days = pd.date_range(month_start, month_end, freq="D")
    yesterday = pd.Timestamp(today) - pd.Timedelta(days=1)
    sold = pd.Series(0.0, index=days)
    sold_sales = pd.Series(0.0, index=days)
    daily = None
    if lines is not None and today > month_start:
        daily = daily_profile(lines, str(row["item_key"]), month_start, yesterday.date())
        sold = sold.add(daily[f"qty_{basis}"], fill_value=0.0)
        sold_sales = sold_sales.add(daily[f"sales_{basis}"], fill_value=0.0)
    elif item_orders is not None and not item_orders.empty:
        stamps = pd.to_datetime(item_orders["order_time"]).dt.normalize()
        part = item_orders.loc[stamps.between(pd.Timestamp(month_start), yesterday)]
        if not part.empty:
            grouped = part.groupby(pd.to_datetime(part["order_time"]).dt.normalize()).agg(qty=("qty", "sum"), sales=("sales", "sum"))
            sold = sold.add(grouped["qty"].reindex(days, fill_value=0.0), fill_value=0.0)
            sold_sales = sold_sales.add(grouped["sales"].reindex(days, fill_value=0.0), fill_value=0.0)
    run_rest = pd.to_numeric(pd.Series([row.get("run_rest_qty")]), errors="coerce").iat[0]
    remain_total = float(run_rest) if pd.notna(run_rest) else float(row["pred_harian"]) * max((month_end - today).days + 1, 0)
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
    # Tanggal lewat yang tetap tanpa prediksi (SKU belum punya riwayat penjualan sebelum tanggal itu) = prediksi 0, bukan kosong.
    for d in lapsed:
        if not past_source.loc[d]:
            past_source.loc[d] = "belum ada riwayat penjualan"
    has_stock = bool(row.get("ada_data_stok", False))
    stok = float(row["stok"]) if has_stock else 0.0
    ss = float(row["ss"])
    price = float(row.get("harga_bersih", 0) or 0)
    labels = [fmt_date(d, short=True) for d in days]
    basis_word = "Terjual bersih" if basis == "bersih" else "Masuk (semua pesanan)"
    today_index = int((pd.Timestamp(today) - pd.Timestamp(month_start)).days)

    def sold_hover(money: bool) -> list[str]:
        fmt = fmt_idr_short if money else fmt_qty
        values = sold_sales if money else sold
        if daily is None:
            return [f"{basis_word}: {fmt(v)}" if d < pd.Timestamp(today) else "belum terjadi" for d, v in values.items()]
        out = []
        for d in days:
            if d >= pd.Timestamp(today):
                out.append("belum terjadi (lihat batang Prediksi)")
                continue
            r = daily.loc[d]
            head = (f"bersih {fmt(r['sales_bersih'])} · masuk {fmt(r['sales_masuk'])}" if money
                    else f"bersih {fmt_qty(r['qty_bersih'])} · masuk {fmt_qty(r['qty_masuk'])} unit")
            out.append(f"Dipakai: {basis_word.lower()}<br>{head}<br>batal {fmt_qty(r['qty_batal'])} · Belum Bayar {fmt_qty(r['qty_belum_bayar'])} · retur {fmt_qty(r['qty_retur'])} unit")
        return out

    def stock_projection(pred_series: np.ndarray, base: float) -> tuple[np.ndarray, str | None]:
        mask = np.array([d >= pd.Timestamp(today) for d in days]) if len(pred_series) == len(days) else np.ones(len(pred_series), bool)
        cumulative = np.cumsum(np.where(mask, pred_series, 0.0))
        # Stok snapshot berlaku mulai hari ini: hari sebelumnya tidak digambar (bukan stok historis).
        line = np.where(mask, base - cumulative, np.nan)
        out = next((i for i, v in enumerate(line) if mask[i] and v <= 0), None)
        return line, out

    qty_line, qty_out = stock_projection(pred.to_numpy(), stok) if has_stock else (None, None)
    sales_line = qty_line * price if qty_line is not None else None
    stock_past, stock_note = past_stock_path(days, today, stok if has_stock else None, sold, stock_history)
    fmt_hist = _round_label(False)
    past_hover_qty = [f"Stok {fmt_hist(v)} unit · {n}" if n else "" for v, n in zip(stock_past, stock_note)]
    past_hover_sales = [f"Nilai stok {fmt_idr(round(v * price))} · {n}" if n else "" for v, n in zip(stock_past, stock_note)]
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(
            _two_panel(labels, sold.to_numpy(), pred.to_numpy(), qty_line, ss, labels[qty_out] if qty_out is not None else None, money=False, title="Grafik QTY · Bulan ini", unit="Unit", past=past_qty.to_numpy(), past_source=past_source.to_numpy(),
                       sold_name=basis_word, sold_hover=sold_hover(False), today_index=today_index, stock_past=stock_past, stock_past_hover=past_hover_qty),
            use_container_width=True, key=f"{key}-qty",
        )
    with c2:
        st.plotly_chart(
            _two_panel(labels, sold_sales.to_numpy(), pred_sales.to_numpy(), sales_line, ss * price, labels[qty_out] if qty_out is not None else None, money=True, title="Grafik Sales · Bulan ini", unit="Rupiah", past=past_sales.to_numpy(), past_source=past_source.to_numpy(),
                       sold_name=basis_word, sold_hover=sold_hover(True), today_index=today_index, stock_past=stock_past * price, stock_past_hover=past_hover_sales),
            use_container_width=True, key=f"{key}-sales",
        )
    st.caption("Garis putus-putus = batas hari ini: kiri aktual, kanan prediksi. "
               f"Angka di atas batang: tanggal lewat = {basis_word.lower()} / prediksi sebelumnya; tanggal mendatang = prediksi. "
               "Semua angka dibulatkan (QTY unit utuh, sales Rupiah utuh).")
    _sku_summary(
        row, today=today, month_end=month_end, sold=sold, sold_sales=sold_sales, pred=pred, pred_sales=pred_sales,
        qty_line=qty_line, days=days, past_qty=past_qty, past_sales=past_sales, past_source=past_source, daily=daily, basis=basis,
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
    past_source: pd.Series | None = None,
    daily: pd.DataFrame | None = None,
    basis: str = "bersih",
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
    cols = st.columns(5)
    sold_span = f"1–{fmt_date(yesterday, short=True)}" if sold_days else "belum ada hari penuh"
    word = "bersih" if basis == "bersih" else "masuk"
    other = "masuk" if basis == "bersih" else "bersih"
    other_text = ""
    if daily is not None:
        other_text = (f"<br>{other} {fmt_qty(daily[f'qty_{other}'].sum())} unit ({fmt_idr(daily[f'sales_{other}'].sum())}) · "
                      f"batal {fmt_qty(daily['qty_batal'].sum())} · Belum Bayar {fmt_qty(daily['qty_belum_bayar'].sum())} · retur {fmt_qty(daily['qty_retur'].sum())}")
    card(
        cols[0],
        f"Terjual {word} {sold_span}",
        f"{fmt_qty(sold_qty)} unit",
        hint=f"{fmt_idr(sold_val)} · rata-rata {fmt_num(sold_qty / sold_days, 0) if sold_days else '0'} unit/hari" + other_text,
    )
    card(
        cols[1],
        f"Prediksi sisa {month_name} ({fmt_date(today, short=True)}–{fmt_date(month_end, short=True)})",
        f"{fmt_num(rest_qty, 0)} unit",
        hint=f"{fmt_idr(rest_val)} · {(month_end - today).days + 1} hari, laju harian × pola hari",
    )
    card(
        cols[2],
        f"Bulan berjalan {month_name} (1–{fmt_date(month_end, short=True)})",
        f"{fmt_num(sold_qty + rest_qty, 0)} unit",
        hint=f"{fmt_idr(sold_val + rest_val)} = terjual {word} {sold_span} + prediksi sisa",
        tone="extra",
    )
    card(
        cols[3],
        f"Prediksi {fmt_date(window_lo, short=True)} – {fmt_date(window_hi, short=True)}",
        f"{fmt_qty(row['m_qty'])} unit",
        hint=f"{fmt_idr(row['m_sales'])} · {fmt_num(daily_pred, 0)} unit/hari · dasar kebutuhan stok",
    )
    card(
        cols[4],
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

    _past_table(sold, sold_sales, past_qty, past_sales, past_source, daily, basis=basis, today=today)

    # Catatan analisa
    notes = []
    if has_stock:
        cover_days = stok / daily_pred if daily_pred > 0 else float("inf")
        if np.isfinite(cover_days) and cover_days > 3650:
            notes.append(("Stok Site 10037 cukup", "lebih dari 10 tahun pada laju prediksi sekarang"))
        elif np.isfinite(cover_days):
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
                f"{fmt_num(daily_pred, 0)} vs {fmt_num(actual_rate, 0)} unit/hari bulan ini"
                + (f" ({'+' if diff >= 0 else '−'}{fmt_num(abs(diff), 0)}%)" if diff is not None else ""),
            )
        )
    covered = (past_source.astype(str) != "") if past_source is not None else (past_qty > 0 if past_qty is not None else None)
    if covered is not None and bool(covered.any()):
        p_qty, a_qty = float(past_qty[covered].sum()), float(sold[covered].sum())
        p_val, a_val = float(past_sales[covered].sum()), float(sold_sales[covered].sum())
        first_day = past_qty.index[covered][0]
        rate = a_qty / p_qty * 100 if p_qty > 0 else 0.0
        verdict = "sesuai" if 85 <= rate <= 115 else ("di atas prediksi" if rate > 115 else "di bawah prediksi (meleset)")
        notes.append(
            (
                f"Aktual vs prediksi sebelumnya ({fmt_date(first_day.date(), short=True)}–{fmt_date(yesterday, short=True)})",
                f"terjual {word} {fmt_qty(a_qty)} vs prediksi {fmt_num(p_qty, 0)} unit ({fmt_num(rate, 0)}%, {verdict}); "
                f"sales {fmt_idr(a_val)} vs {fmt_idr(p_val)}",
            )
        )
    else:
        notes.append(("Prediksi sebelumnya", "belum ada riwayat penjualan yang cukup untuk menghitung prediksi hari-hari yang sudah lewat"))
    notes.append(("Prediksi sebelumnya", "dari analisa tersimpan bila ada; tanggal tanpa analisa tersimpan memakai uji mundur (model yang sama, hanya data s.d. sehari sebelumnya)"))
    notes.append(("Grafik", f"batang biru = terjual {word} s.d. {fmt_date(yesterday, short=True)} (arahkan kursor untuk melihat bersih dan masuk); batang arsir = prediksi untuk hari itu (bandingkan dengan biru); merah = prediksi mulai hari ini; garis oranye = stok Site 10037 dikurangi prediksi kumulatif, garis putus = SS"))
    explain(notes, title="Catatan analisa")


def _past_table(sold, sold_sales, past_qty, past_sales, past_source, daily, *, basis: str, today: date) -> None:
    """Tabel per tanggal tgl 1 s.d. kemarin: aktual (masuk & bersih) vs prediksi sebelumnya, agar terlihat hari yang meleset."""
    if past_qty is None or past_source is None:
        return
    lapsed = [d for d in past_qty.index if d < pd.Timestamp(today)]
    if not lapsed:
        return
    word = "bersih" if basis == "bersih" else "masuk"
    rows = []
    for d in lapsed:
        actual, predicted = float(sold.get(d, 0.0)), float(past_qty.get(d, 0.0))
        source = str(past_source.get(d, "") or "")
        rec = {"Tanggal": fmt_date(d.date(), short=True)}
        if daily is not None:
            rec["Masuk (semua) unit"] = fmt_qty(daily.at[d, "qty_masuk"])
            rec["Bersih unit"] = fmt_qty(daily.at[d, "qty_bersih"])
        else:
            rec[f"Terjual {word} unit"] = fmt_qty(actual)
        rec["Prediksi sebelumnya unit"] = fmt_num(predicted, 1) if source else "-"
        rec[f"Selisih ({word} − prediksi)"] = (("+" if actual - predicted >= 0 else "−") + fmt_num(abs(actual - predicted), 1)) if source else "-"
        rec[f"Sales {word}"] = fmt_idr(float(sold_sales.get(d, 0.0)))
        rec["Prediksi sales"] = fmt_idr(float(past_sales.get(d, 0.0))) if source else "-"
        rec["Sumber prediksi"] = source or "tidak ada"
        rows.append(rec)
    first, last = lapsed[0].date(), lapsed[-1].date()
    with st.expander(f"Aktual vs prediksi sebelumnya per tanggal · {fmt_date(first, short=True)}–{fmt_date(last)} (dasar {word})", expanded=True):
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption(
            "Masuk = semua pesanan (termasuk batal, Belum Bayar, retur); bersih = tanpa batal & Belum Bayar, setelah retur. "
            f"Selisih dihitung dengan dasar {word}, sama dengan data latih model. Prediksi 0 berarti model tidak memperkirakan penjualan hari itu."
        )


def direction_html(value: float) -> str:
    if value > 0:
        return f"<span style='color:{UP_COLOR};font-weight:700'>▲</span>"
    if value < 0:
        return f"<span style='color:{DOWN_COLOR};font-weight:700'>▼</span>"
    return ""
