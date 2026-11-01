"""R7: Analisa prediksi per SKU dalam 5 blok tetap + Pendorong naik / Penahan-risiko."""

from __future__ import annotations

import html
from datetime import date

import numpy as np
import pandas as pd

from src.core.decision_table import lama_kosong_text, period_groups
from src.core.expert_system import action_steps, drivers_and_risks, evaluate_rules, root_cause, sku_facts
from src.ui.common import STATUS_COLOR, fmt_date, fmt_idr, fmt_num, fmt_pct, fmt_qty, status_key


def store_performance(performance: pd.DataFrame | None, today: date) -> dict[str, float] | None:
    """Ringkasan 28 hari terakhir vs 28 hari sebelumnya dari Data performance."""
    if performance is None or performance.empty or "date" not in performance.columns:
        return None
    work = performance.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce", dayfirst=True).dt.normalize()
    work = work.dropna(subset=["date"])
    if work.empty:
        return None
    end = min(pd.Timestamp(today).normalize(), work["date"].max() + pd.Timedelta(days=1))
    recent = work.loc[work["date"].ge(end - pd.Timedelta(days=28)) & work["date"].lt(end)]
    prior = work.loc[work["date"].ge(end - pd.Timedelta(days=56)) & work["date"].lt(end - pd.Timedelta(days=28))]

    def total(frame: pd.DataFrame, column: str) -> float:
        if column not in frame.columns:
            return float("nan")
        values = pd.to_numeric(frame[column].astype(str).str.replace(".", "", regex=False).str.replace(",", ".", regex=False).str.replace("%", "", regex=False), errors="coerce")
        return float(values.sum())

    def mean(frame: pd.DataFrame, column: str) -> float:
        if column not in frame.columns:
            return float("nan")
        values = pd.to_numeric(frame[column].astype(str).str.replace(",", ".", regex=False).str.replace("%", "", regex=False), errors="coerce")
        return float(values.mean())

    return {
        "pengunjung": total(recent, "visitors"),
        "pengunjung_prev": total(prior, "visitors"),
        "pesanan": total(recent, "orders"),
        "pesanan_prev": total(prior, "orders"),
        "konversi": mean(recent, "conversion_rate"),
        "konversi_prev": mean(prior, "conversion_rate"),
        "batal": total(recent, "cancelled_orders"),
        "pembeli_baru": total(recent, "new_buyers"),
        "repeat": mean(recent, "repeat_rate"),
    }


def _delta(now: float, then: float) -> str:
    if not np.isfinite(now) or not np.isfinite(then) or then == 0:
        return ""
    pct = (now - then) / then * 100
    color = "#1d4ed8" if pct > 0 else "#dc2626"
    arrow = "▲" if pct > 0 else "▼"
    return f" <span style='color:{color};font-weight:700'>{arrow} {fmt_pct(abs(pct), 1)}</span>"


def _block(title: str, body: str) -> str:
    return f"<div class='insight-section'>{html.escape(title)}</div>{body}"


def analysis_markup(
    row: pd.Series,
    *,
    period: str,
    today: date,
    performance: dict[str, float] | None,
    brief: dict | None = None,
) -> str:
    name = html.escape(str(row.get("product_name", "")))
    sku = html.escape(str(row.get("sku", "")))
    variance = html.escape(str(row.get("variasi_tampil", "")))
    labels = html.escape(str(row.get("label_text", "") or ""))
    head = (
        "<div class='insight-head flat'>"
        f"<div class='insight-kicker'>Analisa prediksi · peringkat {fmt_num(row.get('peringkat'))}</div>"
        f"<div class='insight-title'>{name}</div>"
        f"<div class='insight-meta'>SKU {sku} · Variance: {variance} {('· ' + labels) if labels else ''}</div>"
        "</div>"
    )
    # 1. Prediksi per periode vs stok
    header = "<tr><th>Periode</th><th>Prediksi QTY</th><th>Prediksi sales</th><th>SS</th><th>Butuh</th><th>Stok vs kebutuhan</th></tr>"
    lines = []
    for group in period_groups(period, today):
        p = group.prefix
        status = status_key(row.get(f"{p}_status"))
        if bool(row.get("ada_data_stok", False)):
            gap = float(row[f"{p}_selisih"])
            stock_text = f"<span style='color:{STATUS_COLOR.get(status, '#334155')};font-weight:700'>{fmt_qty(row['stok'])} · {'+' if gap >= 0 else '−'}{fmt_qty(abs(gap))} ({fmt_pct(float(row[f'{p}_pct']) * 100, 0, signed=True)}) · {status}</span>"
        else:
            stock_text = "belum ada data stok"
        style = " style='background:#eff6ff'" if group.extra else ""
        lines.append(
            f"<tr{style}><td>{group.label}</td><td>{fmt_qty(row[f'{p}_qty'])}</td><td>{fmt_idr(row[f'{p}_sales'])}</td>"
            f"<td>{fmt_qty(row[f'{p}_ss'])}</td><td>{fmt_qty(row[f'{p}_butuh'])}</td><td>{stock_text}</td></tr>"
        )
    block1 = f"<table class='insight-table'>{header}{''.join(lines)}</table>"
    if row.get("m_qty", 0) and row.get("actual_mtd_qty", 0):
        block1 += f"<p class='insight-copy'>Bulan ini = terjual tanggal 1 s.d. kemarin {fmt_qty(row['actual_mtd_qty'])} unit + prediksi sisa bulan.</p>"
    # 2. Kesehatan stok
    cover = row.get("hari_cukup")
    cover_text = "-" if cover is None or pd.isna(cover) else ("tidak habis pada laju sekarang" if not np.isfinite(float(cover)) else f"{fmt_num(cover, 0)} hari")
    block2 = (
        "<p class='insight-copy'>"
        f"Hari cukup: <b>{cover_text}</b> · Perkiraan habis: <b>{fmt_date(row.get('tanggal_habis')) if row.get('tanggal_habis') else '-'}</b> · "
        f"Riwayat kosong: <b>{html.escape(lama_kosong_text(row))}</b> · ROP: <b>{fmt_qty(row.get('rop'))}</b> unit"
        "</p>"
    )
    if not bool(row.get("ada_data_stok", False)):
        block2 = "<p class='insight-copy'>Data stok belum diunggah. Unggah menu Data stok agar hari cukup dan lama kosong terhitung.</p>"
    # 3. Performa toko
    if performance:
        block3 = (
            "<p class='insight-copy'>28 hari terakhir: "
            f"pengunjung <b>{fmt_num(performance['pengunjung'])}</b>{_delta(performance['pengunjung'], performance['pengunjung_prev'])}, "
            f"pesanan <b>{fmt_num(performance['pesanan'])}</b>{_delta(performance['pesanan'], performance['pesanan_prev'])}, "
            f"konversi <b>{fmt_pct(performance['konversi'], 2)}</b>{_delta(performance['konversi'], performance['konversi_prev'])}, "
            f"pesanan batal <b>{fmt_num(performance['batal'])}</b>, pembeli baru <b>{fmt_num(performance['pembeli_baru'])}</b>.</p>"
        )
    else:
        block3 = "<p class='insight-copy'>Data performance belum diunggah.</p>"
    # 4. Iklan
    cost = float(row.get("biaya_iklan", 0) or 0)
    ad_sales = float(row.get("omzet_iklan", 0) or 0)
    sales_total = float(row.get("sales_total", 0) or 0)
    if cost > 0 or ad_sales > 0:
        roas = ad_sales / cost if cost > 0 else float("nan")
        acos = cost / ad_sales * 100 if ad_sales > 0 else float("nan")
        share = ad_sales / sales_total * 100 if sales_total > 0 else float("nan")
        block4 = (
            f"<p class='insight-copy'>Biaya <b>{fmt_idr(cost)}</b> · Omzet iklan <b>{fmt_idr(ad_sales)}</b> · "
            f"ROAS <b>{fmt_num(roas, 1)}</b> · Biaya/penjualan <b>{fmt_pct(acos)}</b> · Porsi penjualan dari iklan <b>{fmt_pct(min(share, 100) if np.isfinite(share) else share)}</b></p>"
        )
    else:
        block4 = "<p class='insight-copy'>SKU ini tidak tercatat di laporan iklan (atau Kode produk belum terpetakan ke SKU).</p>"
    # 5. Langkah kerja + dua sisi
    facts = sku_facts(row, today=today)
    advices = evaluate_rules(facts)
    steps = action_steps(advices, facts)
    cause, cause_text = root_cause(facts)
    up, down = drivers_and_risks(facts, row)
    if brief:
        for factor in brief.get("factors", [])[:4]:
            label = str(factor.get("label", ""))
            if factor.get("tone") == "up" and label not in up:
                up.append(label)
            elif factor.get("tone") == "down" and label not in down:
                down.append(label)
    steps_html = "".join(f"<li class='insight-step'><span class='insight-step-no'>{i}</span><div>{html.escape(s)}</div></li>" for i, s in enumerate(steps, 1))
    two_sides = (
        "<table class='insight-table'><tr><th>Pendorong naik</th><th>Penahan / risiko</th></tr><tr>"
        f"<td>{'<br>'.join('▲ ' + html.escape(x) for x in up[:5])}</td>"
        f"<td>{'<br>'.join('▼ ' + html.escape(x) for x in down[:5])}</td></tr></table>"
    )
    block5 = f"<p class='insight-copy'><b>Akar masalah: {html.escape(cause)}.</b> {html.escape(cause_text)}</p><ol class='insight-steps'>{steps_html}</ol>"
    return (
        head
        + _block("1. Prediksi per periode vs stok", block1)
        + _block("2. Kesehatan stok", block2)
        + _block("3. Performa toko", block3)
        + _block("4. Iklan", block4)
        + _block("Analisa dua sisi", two_sides)
        + _block("5. Langkah kerja (maks. 3)", block5)
    )
