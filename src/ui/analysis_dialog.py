"""R7: Analisa prediksi per SKU dalam 5 blok tetap + Pendorong naik / Penahan-risiko."""

from __future__ import annotations

import html
from datetime import date

import numpy as np
import pandas as pd

from src.core.decision_table import lama_kosong_text, period_groups
from src.core.expert_system import action_steps, drivers_and_risks, evaluate_rules, root_cause, sku_facts
from src.core.performance import clean_performance, perf_number
from src.core.periods import MONTHS_SHORT, short_date
from src.ui.common import ID_MONTHS, STATUS_COLOR, fmt_date, fmt_idr, fmt_num, fmt_pct, fmt_qty, status_key


def store_performance(performance: pd.DataFrame | None, today: date) -> dict[str, float] | None:
    """Ringkasan 28 hari terakhir vs 28 hari sebelumnya dari data performa toko (hanya baris harian)."""
    if performance is None or performance.empty or "date" not in performance.columns:
        return None
    work = clean_performance(performance)
    if work.empty:
        return None
    end = min(pd.Timestamp(today).normalize(), work["date"].max() + pd.Timedelta(days=1))
    recent = work.loc[work["date"].ge(end - pd.Timedelta(days=28)) & work["date"].lt(end)]
    prior = work.loc[work["date"].ge(end - pd.Timedelta(days=56)) & work["date"].lt(end - pd.Timedelta(days=28))]

    def total(frame: pd.DataFrame, column: str) -> float:
        if column not in frame.columns:
            return float("nan")
        return float(perf_number(frame[column]).sum())

    def mean(frame: pd.DataFrame, column: str) -> float:
        if column not in frame.columns:
            return float("nan")
        return float(perf_number(frame[column]).mean())

    return {
        "start": (end - pd.Timedelta(days=28)).date(),
        "end": (end - pd.Timedelta(days=1)).date(),
        "prev_start": (end - pd.Timedelta(days=56)).date(),
        "prev_end": (end - pd.Timedelta(days=29)).date(),
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


def _take_text(value) -> str:
    if value is None or pd.isna(value):
        return "–"
    return f"{fmt_qty(float(value))} unit"


def _outstanding_block(row: pd.Series) -> str:
    """Outstanding PO/TR/TO menuju Site 10037 (Replenishment Calculation by Date): rincian, umur, dan kekurangan setelah outstanding."""
    from src.core.insight_live import STALE_DAYS, outstanding_plan, outstanding_verdict

    plan = outstanding_plan(row)
    if plan is None:
        return ("<p class='insight-copy'><b>Outstanding PO/TR/TO</b>: belum ada data. Unggah Replenishment Calculation by Date Site 10037 "
                "(Setting › Kapasitas gudang) agar barang yang sudah dalam proses ikut dihitung.</p>")
    when = f" per {short_date(plan['tanggal'])}" if plan.get("tanggal") else ""
    head = f"<p class='insight-copy'><b>Outstanding PO/TR/TO menuju Site 10037</b> (Replenishment Calculation by Date{when})</p>"
    rows = ""
    if plan["total"] > 0:
        names = {"PO": "PO ke supplier", "TR": "TR (transfer dari DC)", "TO": "TO (transfer order)", "TR toko lain": "TR dari toko lain"}
        rows = "".join(f"<tr><td>{names[label]}</td><td>{fmt_qty(v)} unit</td></tr>" for label, v in plan["parts"].items() if v > 0)
        rows += f"<tr><td><b>Total dalam proses</b></td><td><b>{fmt_qty(plan['total'])} unit</b></td></tr>"
        if plan["since"] is not None:
            mark = "≥ " if plan["minimal"] else ""
            age = f"sejak {'≤ ' if plan['minimal'] else ''}{short_date(plan['since'])} · {mark}{plan['days']} hari"
            if plan["stale"]:
                age += f" (lebih dari {STALE_DAYS} hari)"
            rows += f"<tr><td>Umur outstanding</td><td>{html.escape(age)}</td></tr>"
    if plan["known"]:
        rows += (f"<tr><td>Kekurangan Site 10037 (kebutuhan {fmt_qty(plan['need'])} − stok {fmt_qty(plan['stok'])})</td>"
                 f"<td>{fmt_qty(plan['shortfall'])} unit</td></tr>")
        if plan["shortfall"] > 0:
            rows += f"<tr><td>Sisa setelah outstanding</td><td>{fmt_qty(plan['rest'])} unit</td></tr>"
            for code, units in plan["take"].items():
                rows += f"<tr><td>→ ambil dari Site {code}</td><td>{fmt_qty(units)} unit</td></tr>"
            if plan["po"] > 0:
                rows += f"<tr><td>→ PO baru ke supplier</td><td>{fmt_qty(plan['po'])} unit</td></tr>"
    table = f"<table class='insight-table'><tr><th>Rincian</th><th>Jumlah</th></tr>{rows}</table>" if rows else ""
    return head + table + f"<p class='insight-copy'>{outstanding_verdict(plan)}</p>"


def _dc_block(row: pd.Series) -> str:
    """Keberadaan stok di Site 10062 (DC Cikupa) dan 10036 (DC Cipeucang) serta rencana pemenuhan Site 10037."""
    sites = (("10062", "DC Cikupa"), ("10036", "DC Cipeucang"))
    values = {}
    for code, _name in sites:
        value = row.get(f"stok_{code}")
        values[code] = None if value is None or pd.isna(value) else float(value)
    if all(value is None for value in values.values()):
        return _outstanding_block(row) + "<p class='insight-copy'>Stok DC belum diunggah. Unggah menu Stok DC Cikupa (Site 10062) dan Stok DC Cipeucang (Site 10036) agar rencana transfer terhitung.</p>"
    body = "".join(
        f"<tr><td>Site {code} · {name}</td><td>{'belum ada data' if values[code] is None else fmt_qty(values[code]) + ' unit'}</td>"
        f"<td>{_take_text(row.get(f'ambil_{code}'))}</td></tr>"
        for code, name in sites
    )
    table = f"<table class='insight-table'><tr><th>Lokasi</th><th>Stok tersedia</th><th>Diambil untuk Site 10037</th></tr>{body}</table>"
    has_store = bool(row.get("ada_data_stok", False))
    need = float(row.get("m_butuh", 0) or 0)
    store = float(row.get("stok", 0) or 0) if has_store else 0.0
    shortfall = max(0.0, need - store) if has_store else 0.0
    rest = row.get("kurang_setelah_dc")
    rest = 0.0 if rest is None or pd.isna(rest) else float(rest)
    dc_total = sum(value or 0.0 for value in values.values())
    if not has_store:
        verdict = "Stok Site 10037 belum ada, jadi kebutuhan transfer belum bisa dihitung."
    elif shortfall <= 0:
        verdict = (
            f"Site 10037 cukup untuk kebutuhan bulan ({fmt_qty(store)} ≥ {fmt_qty(need)} unit); stok DC {fmt_qty(dc_total)} unit menjadi cadangan."
        )
    elif rest <= 0:
        verdict = (
            f"Site 10037 kurang {fmt_qty(shortfall)} unit dari kebutuhan {fmt_qty(need)} unit. "
            f"Seluruh kekurangan bisa dipenuhi dari DC, jadi tidak perlu PO: lakukan transfer sekarang agar tidak kosong."
        )
    elif rest < shortfall:
        verdict = (
            f"Site 10037 kurang {fmt_qty(shortfall)} unit. DC hanya bisa menutup {fmt_qty(shortfall - rest)} unit; "
            f"sisa {fmt_qty(rest)} unit perlu PO ke supplier. Transfer dulu bagian dari DC, lalu buat PO untuk sisanya."
        )
    else:
        verdict = (
            f"Site 10037 kurang {fmt_qty(shortfall)} unit dan kedua DC kosong, jadi seluruhnya perlu PO ke supplier."
        )
    if shortfall > 0 and float(row.get("os_total", 0) or 0) > 0:
        verdict += " Hitungan ini belum mengurangi outstanding; kebutuhan transfer/PO bersihnya ada di bagian Outstanding di atas."
    plan = str(row.get("sumber_restock") or "").strip()
    try:
        from src.ui.gudang_view import location_text

        where = location_text(str(row.get("sku", "")))
    except Exception:
        where = ""
    where_html = f"<p class='insight-copy'><b>Gudang Site 10037</b>: {html.escape(where)}</p>" if where else ""
    return where_html + _outstanding_block(row) + (
        "<p class='insight-copy'><b>Stok DC</b> (urutan ambil: Site 10062 dulu karena satu kawasan dengan Site 10037, lalu Site 10036)</p>"
        + table
        + f"<p class='insight-copy'>{html.escape(verdict)}" + (f" Rencana: <b>{html.escape(plan)}</b>." if plan else "") + "</p>"
    )


BASIS_TEXT = {"bersih": "terjual bersih", "masuk": "masuk (semua pesanan)"}


def span_text(lo: date | None, hi: date | None) -> str:
    """Rentang tanggal ringkas: "12 Nov 2026", "1–12 Nov 2026", "13 Okt – 12 Nov 2026"."""
    if lo is None or hi is None:
        return "-"
    if lo == hi:
        return short_date(lo)
    if (lo.year, lo.month) == (hi.year, hi.month):
        return f"{lo.day}–{hi.day} {MONTHS_SHORT[hi.month - 1]} {hi.year}"
    if lo.year == hi.year:
        return f"{lo.day} {MONTHS_SHORT[lo.month - 1]} – {short_date(hi)}"
    return f"{short_date(lo)} – {short_date(hi)}"


def _days(lo: date, hi: date) -> int:
    return max((hi - lo).days + 1, 0)


def _cell(qty: float, sales: float) -> str:
    return f"{fmt_qty(round(float(qty)))} unit<br><span style='color:#64748b'>{fmt_idr(sales)}</span>"


def _pct_word(value: float, base_word: str) -> str:
    if value is None or not np.isfinite(value):
        return f"belum bisa dibandingkan dengan {base_word} (data pembanding 0 atau belum ada)"
    if abs(value) < 0.5:
        return f"setara {base_word}"
    return f"{'naik' if value > 0 else 'turun'} {fmt_pct(abs(value), 1)} dibanding {base_word}"


def _month_block(ctx: dict, row: pd.Series) -> str:
    month = ctx.get("month")
    if not month:
        return "<p class='insight-copy'>Data transaksi bulan berjalan belum tersedia.</p>"
    basis = month["basis"]
    act, same, full = month["actual"], month["last_same"], month["last_full"]
    first, cutoff, end = month["first"], month["cutoff"], month["end"]
    has_actual = cutoff >= first
    actual_span = span_text(first, cutoff) if has_actual else "belum ada hari penuh"
    mark = " style='background:#eef2ff;font-weight:700'"
    rows = [
        ("Aktual masuk (semua pesanan)", f"{actual_span}" + (f" · {_days(first, cutoff)} hari penuh" if has_actual else ""), act["qty_masuk"], act["sales_masuk"], basis == "masuk"),
        ("Aktual terjual bersih", actual_span, act["qty_bersih"], act["sales_bersih"], basis == "bersih"),
        ("Prediksi sisa bulan", f"{span_text(month['rest_start'], end)} · {month['rest_days']} hari, laju harian × pola hari", month["rest_qty"], month["rest_sales"], False),
        (f"Proyeksi akhir {ID_MONTHS[first.month - 1]} (aktual {BASIS_TEXT[basis]} + prediksi sisa)", span_text(first, end), month["proj_qty"], month["proj_sales"], True),
    ]
    if same is not None:
        rows.append((f"Pembanding: periode sama bulan lalu ({BASIS_TEXT[basis]})", span_text(same["start"], same["end"]), same[f"qty_{basis}"], same[f"sales_{basis}"], False))
    rows.append((f"Pembanding: {ID_MONTHS[full['start'].month - 1]} penuh ({BASIS_TEXT[basis]})", span_text(full["start"], full["end"]), full[f"qty_{basis}"], full[f"sales_{basis}"], False))
    body = "".join(
        f"<tr{mark if strong else ''}><td>{html.escape(name)}</td><td>{html.escape(when)}</td><td>{_cell(qty, sales)}</td></tr>"
        for name, when, qty, sales, strong in rows
    )
    table = f"<table class='insight-table'><tr><th>Komponen</th><th>Periode (tanggal)</th><th>QTY · sales produk</th></tr>{body}</table>"
    lines = []
    month_name = ID_MONTHS[first.month - 1]
    full_name = f"{ID_MONTHS[full['start'].month - 1]} penuh ({span_text(full['start'], full['end'])})"
    if has_actual and same is not None:
        same_name = f"periode sama bulan lalu ({span_text(same['start'], same['end'])})"
        lines.append(
            f"Sampai {short_date(cutoff)}, {BASIS_TEXT[basis]} {fmt_qty(act['qty_' + basis])} unit, "
            f"{_pct_word(month['vs_last_same_pct'], same_name)}."
        )
    lines.append(
        f"Proyeksi {month_name} {fmt_qty(round(month['proj_qty']))} unit ({fmt_idr(month['proj_sales'])}), "
        f"{_pct_word(month['vs_last_full_pct'], full_name)}."
    )
    if has_actual and act["qty_masuk"] > 0:
        lost = act["qty_masuk"] - act["qty_bersih"]
        lines.append(
            f"Dari {fmt_qty(act['qty_masuk'])} unit masuk {actual_span}, {fmt_qty(lost)} unit ({fmt_pct(lost / act['qty_masuk'] * 100, 1)}) tidak menjadi penjualan: "
            f"batal {fmt_qty(act['qty_batal'])}, Belum Bayar {fmt_qty(act['qty_belum_bayar'])}, retur {fmt_qty(act['qty_retur'])} unit."
        )
    pot = ctx.get("potential")
    if pot and np.isfinite(pot.get("short_qty", np.nan)):
        stock_day = ctx.get("stock_date")
        stock_note = f"data stok {short_date(stock_day)}" if stock_day else "data stok terakhir"
        if pot["short_qty"] > 0:
            lines.append(
                f"Sisa bulan ({span_text(month['rest_start'], end)}) butuh sekitar {fmt_qty(round(pot['need']))} unit; stok Site 10037 {fmt_qty(row.get('stok'))} unit ({stock_note}) "
                f"hanya menutup {fmt_qty(round(pot['covered']))} unit. Tanpa transfer DC atau PO, potensi tidak terlayani {fmt_qty(round(pot['short_qty']))} unit ≈ {fmt_idr(pot['short_sales'])} (sales produk)."
            )
        else:
            lines.append(f"Stok Site 10037 {fmt_qty(row.get('stok'))} unit ({stock_note}) cukup untuk perkiraan sisa bulan {fmt_qty(round(pot['need']))} unit ({span_text(month['rest_start'], end)}).")
    lost = ctx.get("empty_loss")
    if lost and lost.get("hari"):
        since = ctx.get("empty_since")
        lines.append(
            f"Stok kosong sejak {short_date(since)} ({lost['hari']} hari s.d. {short_date(ctx.get('empty_until') or since)}, hari penuh terakhir data latih): potensi sales hilang {fmt_qty(round(lost['qty']))} unit ≈ {fmt_idr(lost['sales'])}; "
            f"bagian {ID_MONTHS[first.month - 1]} {fmt_idr(lost['sales_bulan'])}. Ini bisa menjelaskan kenapa target bulan ini sulit tercapai."
        )
    return table + "".join(f"<p class='insight-copy'>{html.escape(text)}</p>" for text in lines)


def _transaction_block(ctx: dict, brief: dict | None) -> str:
    month = ctx.get("month")
    if not month:
        return "<p class='insight-copy'>Data transaksi belum tersedia.</p>"
    profiles = []
    if month["cutoff"] >= month["first"]:
        profiles.append(("Bulan berjalan", month["actual"]))
    if month["last_same"] is not None:
        profiles.append(("Periode sama bulan lalu", month["last_same"]))
    profiles.append(("Bulan lalu penuh", month["last_full"]))
    head = (
        "<tr><th>Periode (tanggal)</th><th>Masuk</th><th>Batal</th><th>Belum Bayar</th><th>Retur</th><th>Terjual bersih</th>"
        "<th>Hilang dari masuk</th><th>Pesanan · pembeli</th></tr>"
    )
    body = []
    reasons: dict[str, int] = {}
    for name, p in profiles:
        lost = p["qty_masuk"] - p["qty_bersih"]
        share = fmt_pct(lost / p["qty_masuk"] * 100, 1) if p["qty_masuk"] > 0 else "-"
        body.append(
            f"<tr><td><b>{name}</b><br>{span_text(p['start'], p['end'])}</td><td>{_cell(p['qty_masuk'], p['sales_masuk'])}</td>"
            f"<td>{_cell(p['qty_batal'], p['sales_batal'])}</td><td>{_cell(p['qty_belum_bayar'], p['sales_belum_bayar'])}</td>"
            f"<td>{_cell(p['qty_retur'], p['sales_retur'])}</td><td>{_cell(p['qty_bersih'], p['sales_bersih'])}</td>"
            f"<td>{share}</td><td>{fmt_num(p['pesanan'])} · {fmt_num(p['pembeli'])}</td></tr>"
        )
        if name != "Periode sama bulan lalu":
            for text, n in p["alasan_batal"]:
                reasons[text] = reasons.get(text, 0) + n
    out = f"<table class='insight-table'>{head}{''.join(body)}</table>"
    if reasons:
        lo = month["last_full"]["start"]
        hi = month["cutoff"] if month["cutoff"] >= month["first"] else month["last_full"]["end"]
        top = sorted(reasons.items(), key=lambda kv: -kv[1])[:3]
        out += f"<p class='insight-copy'>Alasan batal teratas {span_text(lo, hi)}: " + "; ".join(f"{html.escape(t)} ({fmt_num(n)}×)" for t, n in top) + ".</p>"
    promo = (brief or {}).get("promo") or {}
    window = (brief or {}).get("promo_span")
    if promo and window:
        bits = []
        if promo.get("net_price"):
            bits.append(f"harga bersih rata-rata {fmt_idr(promo['net_price'])}/unit")
        if float(promo.get("discount_depth", 0) or 0) >= 0.005:
            bits.append(f"diskon penjual {fmt_pct(promo['discount_depth'] * 100, 1)} dari harga awal {fmt_idr(promo.get('list_price'))}")
        for name, label in (("shopee_voucher_share", "memakai voucher Shopee"), ("seller_voucher_share", "memakai voucher toko"),
                            ("paylater_share", "dibayar PayLater/cicilan"), ("cod_share", "COD"), ("cargo_share", "dikirim kargo"),
                            ("buyer_shipping_share", "ongkir dibayar pembeli")):
            share = float(promo.get(name, 0) or 0)
            if share >= 0.05:
                bits.append(f"{fmt_pct(share * 100, 0)} unit {label}")
        if bits:
            basis = BASIS_TEXT.get(ctx.get("basis", "bersih"), "terjual bersih")
            out += (
                f"<p class='insight-copy'>Harga & cara beli {span_text(*window)} (28 hari, dasar {basis}): " + html.escape("; ".join(bits)) + ".</p>"
            )
    return out


def _competitor_block(ctx: dict) -> str:
    comp = ctx.get("competitor")
    if not comp or not comp.get("ada_data"):
        return "<p class='insight-copy'>Data kompetitor belum diunggah (menu Data produk kompetitor).</p>"
    when = f"unggahan {short_date(comp['tanggal'])}" if comp.get("tanggal") else "unggahan terakhir"
    if not comp.get("pembanding"):
        return f"<p class='insight-copy'>Tidak ada produk mirip di daftar peringkat Shopee ({when}); posisi pasar SKU ini belum bisa dibandingkan.</p>"
    pos = comp.get("posisi")
    change = comp.get("perubahan")
    if pos is not None and np.isfinite(float(pos)):
        where = f"Produk kita di posisi <b>#{fmt_num(pos)}</b>" + (f" (Change of Rank {fmt_num(change)})" if change is not None and np.isfinite(float(change)) else "")
    else:
        where = "Produk kita <b>belum masuk</b> daftar ini; pembanding diambil dari judul yang paling mirip"
    rows = "".join(
        f"<tr><td>#{fmt_num(c['posisi'])}</td><td>{html.escape(c['nama'])}</td><td>{html.escape(c['toko'])}</td>"
        f"<td>{fmt_num(c['perubahan']) if c['perubahan'] is not None and np.isfinite(float(c['perubahan'])) else '-'}</td></tr>"
        for c in comp["pembanding"]
    )
    out = (
        f"<p class='insight-copy'>Daftar peringkat Shopee {html.escape(str(comp['daftar']))} ({when}). {where}.</p>"
        f"<table class='insight-table'><tr><th>Posisi</th><th>Produk pembanding</th><th>Toko</th><th>Change of Rank</th></tr>{rows}</table>"
    )
    if comp.get("kata_kunci"):
        out += f"<p class='insight-copy'>Kata kunci di judul pembanding yang belum ada di nama kita: <b>{html.escape(', '.join(comp['kata_kunci']))}</b>.</p>"
    out += "<p class='insight-note'>File kompetitor berisi peringkat dan judul, tanpa harga dan terjual, jadi perbandingan harga belum bisa dihitung.</p>"
    return out


def _description_block(ctx: dict) -> str:
    desc = ctx.get("description")
    if not desc:
        return "<p class='insight-copy'>Data deskripsi produk belum diunggah.</p>"
    if not desc["ada"]:
        return "<p class='insight-copy'>Deskripsi SKU ini tidak ditemukan di data Deskripsi produk (cocokkan Kode Produk / nama).</p>"
    out = f"<p class='insight-copy'>Panjang {fmt_num(desc['panjang'])} karakter. Sudah memuat: {html.escape(', '.join(desc['lengkap']) or '-')}.</p>"
    if desc["kurang"]:
        out += f"<p class='insight-copy'>Belum memuat: <b>{html.escape(', '.join(desc['kurang']))}</b>. Lengkapi lewat halaman Rekomendasi agar pembeli tidak ragu (mengurangi batal dan menaikkan konversi).</p>"
    return out


def _context_points(ctx: dict, up: list[str], down: list[str]) -> None:
    month = ctx.get("month")
    if month:
        full = month["last_full"]
        vs = month["vs_last_full_pct"]
        name = f"Proyeksi {ID_MONTHS[month['first'].month - 1]} {fmt_pct(abs(vs), 0) if np.isfinite(vs) else ''} {'di atas' if np.isfinite(vs) and vs > 0 else 'di bawah'} {ID_MONTHS[full['start'].month - 1]} penuh"
        if np.isfinite(vs) and vs >= 5:
            up.append(name)
        elif np.isfinite(vs) and vs <= -5:
            down.append(name)
        act = month["actual"]
        if act["qty_masuk"] > 0 and month["cutoff"] >= month["first"]:
            lost = (act["qty_masuk"] - act["qty_bersih"]) / act["qty_masuk"] * 100
            if lost >= 15:
                down.append(f"{fmt_pct(lost, 0)} unit masuk {span_text(month['first'], month['cutoff'])} hilang (batal/Belum Bayar/retur)")
    pot = ctx.get("potential")
    if pot and np.isfinite(pot.get("short_qty", np.nan)) and pot["short_qty"] > 0:
        down.append(f"Stok tidak menutup sisa bulan: potensi {fmt_idr(pot['short_sales'])} tidak terlayani")
    comp = ctx.get("competitor") or {}
    if comp.get("pembanding"):
        pos = comp.get("posisi")
        if pos is not None and np.isfinite(float(pos)):
            up.append(f"Masuk daftar peringkat Shopee (#{fmt_num(pos)})")
        else:
            down.append("Belum masuk daftar peringkat Shopee kategori ini")
    desc = ctx.get("description") or {}
    if desc.get("ada") and len(desc.get("kurang", [])) >= 4:
        down.append(f"Deskripsi belum memuat {len(desc['kurang'])} dari 9 aspek")
    elif desc and not desc.get("ada"):
        down.append("Deskripsi produk belum terdata")


def _dated(text: str, ctx: dict) -> str:
    """Tempel periode pada kalimat sistem pakar yang belum menyebut tanggal."""
    trend = ctx.get("trend_span")
    if trend and text.startswith("Penjualan 28 hari terakhir"):
        return text.replace("28 hari terakhir", f"28 hari terakhir ({span_text(*trend[0])})", 1).replace(
            "28 hari sebelumnya", f"28 hari sebelumnya ({span_text(*trend[1])})", 1
        )
    report = ctx.get("report_span")
    if report and "atal" in text and "%" in text:
        return text.replace("%", f"% (seluruh laporan {span_text(*report)})", 1)
    return text


def analysis_markup(
    row: pd.Series,
    *,
    period: str,
    today: date,
    performance: dict[str, float] | None,
    brief: dict | None = None,
    context: dict | None = None,
) -> str:
    ctx = context or {}
    basis = ctx.get("basis", "bersih")
    name = html.escape(str(row.get("product_name", "")))
    sku = html.escape(str(row.get("sku", "")))
    variance = html.escape(str(row.get("variasi_tampil", "")))
    labels = html.escape(str(row.get("label_text", "") or ""))
    head = (
        "<div class='insight-head flat'>"
        f"<div class='insight-kicker'>Analisa prediksi · peringkat {fmt_num(row.get('peringkat'))}</div>"
        f"<div class='insight-title'>{name}</div>"
        f"<div class='insight-meta'>SKU {sku} · Varian: {variance} {('· ' + labels) if labels else ''}</div>"
        "</div>"
    )
    other = "masuk" if basis == "bersih" else "terjual bersih"
    guide = (
        "<p class='insight-note'><b>Cara baca angka.</b> <b>Masuk</b> = semua pesanan, termasuk yang batal, Belum Bayar, dan retur (minat beli yang sebenarnya masuk). "
        "<b>Terjual bersih</b> = masuk dikurangi batal, Belum Bayar, dan retur (yang benar-benar menjadi penjualan). "
        "<b>Sales produk</b> = Harga Setelah Diskon × QTY, sebelum voucher; bukan sales bersih Total Pembayaran (dasar target), karena Total Pembayaran per pesanan tidak bisa dibagi tepat per SKU. "
        f"Analisa ini memakai dasar <b>{BASIS_TEXT[basis]}</b>, sama dengan dasar prediksi (setelan Kecualikan batal & retur {'aktif' if basis == 'bersih' else 'mati'}); "
        f"angka {other} tetap ditampilkan sebagai pembanding. Setiap angka disertai tanggalnya.</p>"
    )
    # Prediksi per periode vs stok
    header = "<tr><th>Periode (tanggal)</th><th>Prediksi QTY</th><th>Prediksi sales produk</th><th>SS</th><th>Butuh (prediksi + SS)</th><th>Stok vs kebutuhan</th></tr>"
    lines = []
    for group in period_groups(period, today):
        p = group.prefix
        label = group.label if any(ch.isdigit() for ch in group.label) else f"{group.label} ({short_date(today)})"
        status = status_key(row.get(f"{p}_status"))
        if bool(row.get("ada_data_stok", False)):
            gap = float(row[f"{p}_selisih"])
            below = " · di bawah SS" if "di bawah SS" in str(row.get(f"{p}_status", "")) else ""
            stock_text = f"<span style='color:{STATUS_COLOR.get(status, '#334155')};font-weight:700'>{fmt_qty(row['stok'])} · {'+' if gap >= 0 else '−'}{fmt_qty(abs(gap))} ({fmt_pct(float(row[f'{p}_pct']) * 100, 0, signed=True)}) · {status}{below}</span>"
        else:
            stock_text = "belum ada data stok"
        style = " style='background:#eff6ff'" if group.extra else ""
        lines.append(
            f"<tr{style}><td>{html.escape(label)}</td><td>{fmt_qty(row[f'{p}_qty'])}</td><td>{fmt_idr(row[f'{p}_sales'])}</td>"
            f"<td>{fmt_qty(row[f'{p}_ss'])}</td><td>{fmt_qty(row[f'{p}_butuh'])}</td><td>{stock_text}</td></tr>"
        )
    block_pred = f"<table class='insight-table'>{header}{''.join(lines)}</table>"
    stock_day = ctx.get("stock_date")
    block_pred += (
        f"<p class='insight-copy'>Prediksi dasar {BASIS_TEXT[basis]}; sales = prediksi QTY × harga bersih 4 minggu terakhir. "
        f"Prediksi 30 hari = hari ini s.d. 30 hari ke depan (bukan bulan kalender; untuk bulan kalender lihat blok Bulan berjalan). "
        f"Stok = Site 10037 {('data ' + short_date(stock_day)) if stock_day else 'data stok terakhir'}.</p>"
    )
    # Kesehatan stok
    cover = row.get("hari_cukup")
    cover_text = "-" if cover is None or pd.isna(cover) else ("tidak habis pada laju sekarang" if not np.isfinite(float(cover)) else f"{fmt_num(cover, 0)} hari sejak {short_date(today)}")
    block_stock = (
        "<p class='insight-copy'>"
        f"Hari cukup: <b>{cover_text}</b> · Perkiraan habis: <b>{fmt_date(row.get('tanggal_habis')) if row.get('tanggal_habis') else '-'}</b> · "
        f"Riwayat kosong: <b>{html.escape(lama_kosong_text(row))}</b> · ROP (titik pesan ulang): <b>{fmt_qty(row.get('rop'))}</b> unit"
        "</p>"
    )
    if not bool(row.get("ada_data_stok", False)):
        block_stock = "<p class='insight-copy'>Data stok belum diunggah. Unggah menu Data stok Site 10037 agar hari cukup dan lama kosong terhitung.</p>"
    block_stock += _dc_block(row)
    # Performa toko
    if performance:
        dates = (
            f"{span_text(performance['start'], performance['end'])} dibanding {span_text(performance['prev_start'], performance['prev_end'])}"
            if performance.get("start") else "28 hari terakhir"
        )
        block_perf = (
            f"<p class='insight-copy'>Seluruh toko (bukan hanya SKU ini), {dates}: "
            f"pengunjung <b>{fmt_num(performance['pengunjung'])}</b>{_delta(performance['pengunjung'], performance['pengunjung_prev'])}, "
            f"pesanan <b>{fmt_num(performance['pesanan'])}</b>{_delta(performance['pesanan'], performance['pesanan_prev'])}, "
            f"konversi <b>{fmt_pct(performance['konversi'], 2)}</b>{_delta(performance['konversi'], performance['konversi_prev'])}, "
            f"pesanan batal <b>{fmt_num(performance['batal'])}</b>, pembeli baru <b>{fmt_num(performance['pembeli_baru'])}</b>.</p>"
        )
    else:
        block_perf = "<p class='insight-copy'>Data performa toko belum diunggah.</p>"
    # Iklan
    cost = float(row.get("biaya_iklan", 0) or 0)
    ad_sales = float(row.get("omzet_iklan", 0) or 0)
    # Pembagi = sales SKU pada periode laporan iklan yang sama, bukan saringan Periode penjualan.
    sales_in_ad_period = float(row.get("sales_sku", 0) or 0)
    ad_lo, ad_hi = row.get("iklan_mulai"), row.get("iklan_sampai")
    ad_span = span_text(pd.Timestamp(ad_lo).date(), pd.Timestamp(ad_hi).date()) if pd.notna(ad_lo) and pd.notna(ad_hi) else "periode laporan iklan"
    if cost > 0 or ad_sales > 0:
        roas = ad_sales / cost if cost > 0 else float("nan")
        acos = cost / ad_sales * 100 if ad_sales > 0 else float("nan")
        share = ad_sales / sales_in_ad_period * 100 if sales_in_ad_period > 0 else float("nan")
        block_ads = (
            f"<p class='insight-copy'>Laporan iklan {ad_span}: biaya <b>{fmt_idr(cost)}</b> · omzet iklan <b>{fmt_idr(ad_sales)}</b> · "
            f"ROAS (omzet iklan ÷ biaya) <b>{fmt_num(roas, 1)}</b> · ACoS (biaya ÷ omzet iklan) <b>{fmt_pct(acos)}</b> · "
            f"porsi sales dari iklan <b>{fmt_pct(share) if np.isfinite(share) else '-'}</b>"
            + (f" dari sales produk SKU {fmt_idr(sales_in_ad_period)} pada {ad_span}" if sales_in_ad_period > 0 else "")
            + ".</p>"
        )
        if np.isfinite(share) and share > 100:
            block_ads += (
                "<p class='insight-note'>Porsi di atas 100% berarti omzet yang dicatat laporan iklan (dihitung Shopee dengan aturannya sendiri) "
                "lebih besar dari sales produk SKU ini pada tanggal yang sama; baca ROAS sebagai batas atas.</p>"
            )
    else:
        block_ads = "<p class='insight-copy'>SKU ini tidak tercatat di laporan iklan (atau Kode produk belum terpetakan ke SKU).</p>"
    # Dua sisi + langkah kerja
    facts = sku_facts(row, today=today)
    advices = evaluate_rules(facts)
    steps = action_steps(advices, facts)
    cause, cause_text = root_cause(facts)
    up, down = drivers_and_risks(facts, row)
    if brief:
        for factor in brief.get("factors", [])[:4]:
            label = str(factor.get("label", ""))
            # Tren penjualan sudah dari fakta tren_pct (pesanan s.d. kemarin); versi data latih tidak ditampilkan dobel.
            if label.startswith("Laku 4 minggu") and np.isfinite(facts.get("tren_pct", np.nan)):
                continue
            if factor.get("tone") == "up" and label not in up:
                up.append(label)
            elif factor.get("tone") == "down" and label not in down:
                down.append(label)
    _context_points(ctx, up, down)
    up = [_dated(x, ctx) for x in up]
    down = [_dated(x, ctx) for x in down]
    steps = [_dated(s, ctx) for s in steps]
    steps_html = "".join(f"<li class='insight-step'><span class='insight-step-no'>{i}</span><div>{html.escape(s)}</div></li>" for i, s in enumerate(steps, 1))
    two_sides = (
        "<table class='insight-table'><tr><th>Pendorong naik</th><th>Penahan / risiko</th></tr><tr>"
        f"<td>{'<br>'.join('▲ ' + html.escape(x) for x in up[:7])}</td>"
        f"<td>{'<br>'.join('▼ ' + html.escape(x) for x in down[:7])}</td></tr></table>"
    )
    block_steps = f"<p class='insight-copy'><b>Akar masalah: {html.escape(cause)}.</b> {html.escape(cause_text)}</p><ol class='insight-steps'>{steps_html}</ol>"
    month = ctx.get("month")
    month_title = f"1. Bulan berjalan · {ID_MONTHS[today.month - 1]} {today.year}"
    return (
        head
        + guide
        + _block(month_title, _month_block(ctx, row) if month else "<p class='insight-copy'>Data transaksi bulan berjalan belum tersedia.</p>")
        + _block("2. Prediksi per periode vs stok", block_pred)
        + _block("3. Transaksi SKU: masuk, batal, Belum Bayar, retur, bersih", _transaction_block(ctx, brief))
        + _block("4. Kesehatan stok dan stok DC", block_stock)
        + _block("5. Kompetitor (daftar peringkat Shopee)", _competitor_block(ctx))
        + _block("6. Deskripsi produk", _description_block(ctx))
        + _block("7. Performa toko", block_perf)
        + _block("8. Iklan", block_ads)
        + _block("Analisa dua sisi", two_sides)
        + _block("9. Langkah kerja (maks. 3)", block_steps)
    )
