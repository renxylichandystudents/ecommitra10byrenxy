"""Prediksi › Pantauan harian bulan berjalan: prediksi H-1 vs aktual per tanggal, target omzet, hari promo, Top 5 tindakan."""

from __future__ import annotations

import calendar
import html
from datetime import date, timedelta

import numpy as np
import pandas as pd
import streamlit as st

from src.core import month_track as M
from src.ui.common import card, explain, fmt_idr, fmt_pct
from src.utils.format import show_table

ID_MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
STATUS_TONE = {"Melebihi": "#15803d", "Tercapai": "#15803d", "Hampir": "#b45309", "Tidak": "#dc2626"}


@st.cache_data(show_spinner=False, max_entries=8)
def _daily_series(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series, object]:
    """(sales bersih per tanggal, sales produk bersih per tanggal, waktu pesanan terakhir) dari seluruh data pesanan."""
    from src.core.metrics import normalize_lines

    lines = normalize_lines(frame)
    stamps = pd.to_datetime(lines["order_time"], errors="coerce").dropna()
    if stamps.empty:
        empty = pd.Series(dtype=float)
        return empty, empty, None
    lo, hi = stamps.min().date(), stamps.max().date()
    return M.daily_net_sales(lines, lo, hi), M.daily_product_sales(lines, lo, hi), stamps.max()


def full_day_cutoff(last_stamp, today: date | None = None) -> date:
    """Hari penuh terakhir: hari data terakhir dihitung penuh bila sudah lewat (sebelum hari ini) dan datanya sampai ≥ 23:00.

    Satu aturan untuk semua halaman (Pantauan harian, breakdown Prediksi vs aktual, pencapaian target, Ringkasan)."""
    from src.core.pred_actual import complete_through

    return complete_through(last_stamp, today or date.today())


def target_pattern(orders_all: pd.DataFrame | None):
    """(pola hari untuk membagi target bulan, hari penuh terakhir data), sama dengan `month_state`; (None, None) bila tanpa data."""
    if orders_all is None or orders_all.empty:
        return None, None
    stamp = pd.to_datetime(orders_all["order_time"], errors="coerce").max()
    key = (len(orders_all), str(stamp), date.today())
    cache = st.session_state.get("_target-pattern")
    if isinstance(cache, tuple) and cache[0] == key:
        return cache[1]
    net, _product, last_stamp = _daily_series(orders_all)
    result = (None, None)
    if last_stamp is not None:
        cutoff = full_day_cutoff(last_stamp)
        profile = M.seasonal_profile(net.loc[pd.Timestamp(cutoff - timedelta(days=364)):pd.Timestamp(cutoff)])
        result = (profile.factor, cutoff)
    st.session_state["_target-pattern"] = (key, result)
    return result


def net_factor(net: pd.Series, product: pd.Series, first: date, month_cutoff: date, data_cutoff: date | None = None) -> float:
    """Faktor sales bersih ÷ sales produk tgl 1 s.d. hari penuh terakhir bulan itu (cadangan: 30 hari s.d. hari penuh
    terakhir data), dibatasi 0,5–1,2.

    Satu aturan untuk Pantauan harian, breakdown Prediksi vs aktual, Kalkulator biaya, dan Rekomendasi › Iklan."""
    lo, hi = pd.Timestamp(first), pd.Timestamp(month_cutoff)
    net_m = float(net.loc[lo:hi].sum()) if month_cutoff >= first else 0.0
    prod_m = float(product.loc[lo:hi].sum()) if month_cutoff >= first else 0.0
    if prod_m <= 0:
        end = data_cutoff or month_cutoff
        lo, hi = pd.Timestamp(end - timedelta(days=29)), pd.Timestamp(end)
        net_m, prod_m = float(net.loc[lo:hi].sum()), float(product.loc[lo:hi].sum())
    return float(min(max(net_m / prod_m, 0.5), 1.2)) if prod_m > 0 and net_m > 0 else 1.0


def month_state(features, orders_all: pd.DataFrame, first: date | None = None, *, today: date | None = None) -> dict:
    """Tabel per tanggal & ringkasan bulan (aktual s.d. hari penuh terakhir + prediksi H-1/terbaru berpola × faktor).

    Sumber tunggal "Proyeksi akhir bulan": Pantauan harian, Kalkulator biaya, dan Rekomendasi › Iklan."""
    net, product, last_stamp = _daily_series(orders_all)
    if last_stamp is None:
        return {}
    data_last = last_stamp.date()
    today = today or date.today()
    cutoff = full_day_cutoff(last_stamp, today)
    first = first or (cutoff + timedelta(days=1)).replace(day=1)
    month_days = calendar.monthrange(first.year, first.month)[1]
    last_day = first + timedelta(days=month_days - 1)
    current = first == (cutoff + timedelta(days=1)).replace(day=1)
    month_cutoff = min(cutoff, last_day) if current else last_day
    running = float(net.get(pd.Timestamp(data_last), 0.0)) if current and cutoff < data_last <= last_day else None
    factor = net_factor(net, product, first, month_cutoff, cutoff)
    profile = M.seasonal_profile(net.loc[pd.Timestamp(cutoff - timedelta(days=364)):pd.Timestamp(cutoff)])

    from src.ui.targets_view import monthly_targets

    target = monthly_targets(features).get(f"{first.year:04d}-{first.month:02d}")
    runs = _prediction_runs(features, first, last_day)
    preds = M.as_of_predictions(runs, [first + timedelta(days=i) for i in range(month_days)])
    done_lo, done_hi = pd.Timestamp(first), pd.Timestamp(month_cutoff)
    table = M.month_table(
        month_first=first, cutoff=month_cutoff, actual=net.loc[done_lo:done_hi] if month_cutoff >= first else pd.Series(dtype=float),
        predictions=preds, factor=factor, profile=profile, target_month=target, running_actual=running,
    )
    return {
        "table": table, "summary": M.month_summary(table, month_cutoff, target, today=today), "factor": factor, "profile": profile,
        "target": target, "cutoff": month_cutoff, "running": running, "data_last": data_last, "current": current,
        "net": net, "product": product,
    }


def _prediction_runs(features, first: date, last: date) -> pd.DataFrame:
    """Σ prediksi omzet per analisa per tanggal target di bulan itu (prediction_snapshot)."""
    try:
        from sqlalchemy import func, select

        from src.core.feature_store import prediction_snapshot as snap

        with features.engine.connect() as conn:
            rows = conn.execute(
                select(snap.c.run_id, snap.c.target_date, func.sum(snap.c.pred_sales), func.min(snap.c.created_at))
                .where(snap.c.target_date >= first, snap.c.target_date <= last)
                .group_by(snap.c.run_id, snap.c.target_date)
            ).all()
    except Exception:
        return pd.DataFrame(columns=["run_id", "target_date", "pred", "run_at"])
    frame = pd.DataFrame(rows, columns=["run_id", "target_date", "pred", "run_at"])
    if frame.empty:
        return frame
    frame["run_at"] = pd.to_datetime(frame["run_at"]).groupby(frame["run_id"]).transform("min")
    return frame


def _unpaid(orders_all: pd.DataFrame, start: date, end: date) -> tuple[float, int]:
    from src.ui.common import cached_order_metrics

    facts = cached_order_metrics(orders_all, start, end, False)
    return float(facts.get("nominal_menunggu_bayar", 0.0)), int(facts.get("pesanan_menunggu_bayar", 0))


def _dec(value: float) -> str:
    return f"{float(value):.2f}".replace(".", ",")


def _status_chip(status: str) -> str:
    if not status:
        return ""
    color = STATUS_TONE.get(status, "#475569")
    return f"<b style='color:{color}'>{html.escape(status)}</b>"


def show_month_tracking(features, *, orders_all: pd.DataFrame | None, table: pd.DataFrame | None, today: date, data=None, params: dict | None = None) -> None:
    st.markdown(
        "<div class='section-title'>Pantauan harian bulan berjalan "
        "<span style='display:inline-block;margin-left:8px;padding:2px 10px;border-radius:999px;background:#fef3c7;color:#92400e;"
        "font-size:var(--fs-xs);font-weight:700;vertical-align:middle'>Prediksi H-1 vs aktual · target omzet</span></div>",
        unsafe_allow_html=True,
    )
    if orders_all is None or orders_all.empty:
        st.info("Belum ada data pesanan.")
        return
    _net, _product, last_stamp = _daily_series(orders_all)
    if last_stamp is None:
        st.info("Belum ada data pesanan.")
        return
    cutoff = full_day_cutoff(last_stamp, today)
    months = []
    probe = (cutoff + timedelta(days=1)).replace(day=1)
    for _ in range(3):
        months.append(probe)
        probe = (probe - timedelta(days=1)).replace(day=1)
    labels = [f"{ID_MONTHS[m.month - 1]} {m.year}" for m in months]
    picked = st.selectbox("Bulan", labels, index=0, key="mt-month", label_visibility="collapsed")
    first = months[labels.index(picked)]
    current = first == months[0]
    if current and cutoff < today - timedelta(days=1):
        st.warning(f"Data pesanan baru sampai {last_stamp:%d/%m/%Y %H:%M}. Hari sesudahnya dihitung dari prediksi; "
                   "unggah data pesanan terbaru agar pencapaian kemarin terbaca.", icon=":material/schedule:")
    state = month_state(features, orders_all, first, today=today)
    summary, factor, profile, target = state["summary"], state["factor"], state["profile"], state["target"]
    month_cutoff, running, data_last = state["cutoff"], state["running"], state["data_last"]

    _cards(summary, month_cutoff, today, running, data_last, target, current)
    _target_alert(summary, target, current, month_cutoff, today)
    if current and summary["hari_promo_sisa"]:
        bits = [f"{d:%d/%m} {lbl} (pola ×{_dec(profile.factor(d))})" for d, lbl in summary["hari_promo_sisa"][:8]]
        st.markdown(f"<div class='field-hint'>Hari promo tersisa bulan ini: {html.escape(' · '.join(bits))}. "
                    "Pastikan stok SKU utama cukup sebelum tanggal ini dan budget iklan dinaikkan sehari sebelumnya.</div>", unsafe_allow_html=True)

    behind = bool(target) and np.isfinite(summary["kurang"]) and summary["kurang"] > 0
    yesterday = summary["kemarin"]
    missed = yesterday.get("status") in ("Tidak", "Hampir")
    if current and (behind or missed or not target):
        unpaid, unpaid_orders = _unpaid(orders_all, data_last - timedelta(days=2), data_last)
        cfg = (params or {}).get("iklan", {})
        top = M.priority_actions(
            table, today=today, rest_days=summary["sisa_hari"], factor=factor,
            margin_pct=getattr(data, "margin_pct", {}) if data is not None else {},
            ad_per_unit=getattr(data, "ad_per_unit", {}) if data is not None else {},
            excluded=getattr(data, "excluded", set()) if data is not None else set(),
            default_roas=float(cfg.get("roas_default", 6)), unpaid=unpaid, unpaid_orders=unpaid_orders,
            recent=_recent_sku(orders_all, cutoff - timedelta(days=6), cutoff),
        )
        _top_actions(top, summary, behind, _missing_inputs(table))

    explain([
        ("Prediksi per tanggal", "prediksi dari analisa terakhir yang dijalankan sebelum tanggal itu (analisa harian = prediksi H-1). "
         "Tanggal yang belum terjadi memakai analisa terbaru. Analisa yang sudah lewat tidak dihitung ulang, jadi akurasi kemarin tetap bisa diaudit walau data latih diperbarui."),
        ("Basis angka", "sales bersih (Total Pembayaran − batal − Belum Bayar − retur), sama dengan target. Prediksi model (harga setelah diskon × QTY) "
         f"dikali faktor {_dec(factor)} = sales bersih ÷ sales produk bulan ini."),
        ("Pola hari & promo", "laju harian model dibagi ke tanggal menurut pola hari (Senin–Minggu) dan kenaikan hari gajian (25–3) dan tanggal kembar dari "
         f"{profile.days} hari riwayat; dinormalkan sehingga total sebulan sama dengan prediksi model. "
         f"Kenaikan: tanggal kembar ×{_dec(profile.uplift.get('Tanggal kembar', 1))} ({profile.samples.get('Tanggal kembar', 0)} hari), "
         f"gajian ×{_dec(profile.uplift.get('Gajian', 1))} ({profile.samples.get('Gajian', 0)} hari)."),
        ("Target harian", "target bulan dibagi mengikuti pola yang sama, jadi hari promo punya target lebih tinggi; totalnya tetap target bulan."),
        ("Status", "Melebihi > 105%, Tercapai 95–105%, Hampir 80–95%, Tidak < 80% dari prediksi."),
        ("Top 5", "diurutkan menurut omzet bersih sampai akhir bulan yang diselamatkan (stok) atau ditambah (iklan, harga & listing, kejar bayar). "
         "Iklan memakai aturan titik impas yang sama dengan Rekomendasi › Iklan (ROAS marginal ≥ 100 ÷ margin, maks. 5× budget), "
         "tambahan dari iklan paling banyak sebesar penjualan harian SKU itu. Harga & listing = SKU yang 7 hari terakhir terjual < 60% prediksi; "
         "potensinya bila kembali ke laju prediksi. Kejar bayar = 30% dari nominal Belum Bayar 3 hari terakhir."),
    ], title="Cara membaca")


def _day_word(day: date, today: date) -> str:
    return {today - timedelta(days=1): "Kemarin", today: "Hari ini", today + timedelta(days=1): "Besok"}.get(day, "Tanggal")


def _cards(summary: dict, cutoff: date, today: date, running: float | None, data_last: date, target: float | None, current: bool) -> None:
    cols = st.columns(4)
    y = summary["kemarin"]
    word = _day_word(cutoff, today)
    label_y = (word if word == "Kemarin" else "Hari penuh terakhir") + f" · {cutoff:%d/%m}"
    if y:
        pred, act = y.get("prediksi"), y.get("aktual")
        hint = (f"Prediksi {fmt_idr(pred)} · capaian {fmt_pct(y.get('capaian_pct'), 0)} {_status_chip(y.get('status', ''))}"
                if pd.notna(pred) else "Belum ada analisa tersimpan sebelum tanggal ini (tabel Prediksi vs aktual memakai uji mundur)")
        if y.get("keterangan"):
            hint += f"<br>{html.escape(y['keterangan'])}"
        card(cols[0], label_y, fmt_idr(act), hint=hint)
    else:
        card(cols[0], label_y, "–", hint="Di luar bulan ini")
    if current:
        for col, key, word in ((cols[1], "hari_ini", "Hari ini"), (cols[2], "besok", "Besok")):
            row = summary[key]
            if not row:
                card(col, word, "–", hint="Sudah akhir bulan")
                continue
            day = row["tanggal"]
            bits = [f"Prediksi {day:%d/%m}" + (f" · {html.escape(row['keterangan'])}" if row.get("keterangan") else "")]
            if pd.notna(row.get("target")):
                bits.append(f"Target hari itu {fmt_idr(row['target'])}")
            if running is not None and day == data_last:
                bits.append(f"Aktual berjalan {fmt_idr(running)} (data belum sehari penuh)")
            card(col, f"{word} · {day:%d/%m}", fmt_idr(row.get("prediksi")) if pd.notna(row.get("prediksi")) else "–", hint="<br>".join(bits))
    else:
        card(cols[1], "Aktual sebulan", fmt_idr(summary["mtd"]), hint=f"Prediksi tersimpan {fmt_idr(summary['mtd_prediksi'])}")
        acc = summary["mtd_aktual_terprediksi"] / summary["mtd_prediksi"] * 100 if summary["mtd_prediksi"] else np.nan
        card(cols[2], "Capaian prediksi", fmt_pct(acc, 0), hint="aktual ÷ prediksi pada tanggal yang punya prediksi")
    if target:
        pct = summary["proyeksi"] / target * 100
        gap = summary["kurang"]
        hint = f"Target {fmt_idr(target)} · {fmt_pct(pct, 0)}"
        hint += f"<br><b style='color:#dc2626'>Kurang {fmt_idr(gap)}</b>" if gap > 0 else f"<br><b style='color:#15803d'>Lebih {fmt_idr(-gap)}</b>"
        card(cols[3], "Proyeksi akhir bulan" if current else "Aktual akhir bulan", fmt_idr(summary["proyeksi"]), hint=hint)
    else:
        card(cols[3], "Proyeksi akhir bulan" if current else "Aktual akhir bulan", fmt_idr(summary["proyeksi"]), hint="Target bulan ini belum diisi (menu Target penjualan)")


def _target_alert(summary: dict, target: float | None, current: bool, cutoff: date, today: date) -> None:
    upto = "kemarin" if cutoff == today - timedelta(days=1) else f"{cutoff:%d/%m} (hari penuh terakhir)"
    if not target:
        st.info("Target omzet bulan ini belum diisi, jadi kekurangan target belum bisa dihitung. Isi target di menu Target penjualan.")
        return
    mtd, tmtd = summary["mtd"], summary["target_mtd"]
    pace = mtd / tmtd * 100 if tmtd else np.nan
    if not current:
        (st.success if summary["kurang"] <= 0 else st.error)(
            f"Bulan ini selesai di {fmt_idr(summary['proyeksi'])} ({fmt_pct(summary['proyeksi'] / target * 100, 0)} dari target {fmt_idr(target)}).")
        return
    if summary["kurang"] > 0:
        need, fc = summary["perlu_harian"], summary["prediksi_harian_sisa"]
        st.error(
            f"⚠️ Proyeksi akhir bulan {fmt_idr(summary['proyeksi'])} masih **kurang {fmt_idr(summary['kurang'])}** dari target {fmt_idr(target)}. "
            f"Aktual s.d. {upto} {fmt_idr(mtd)} = {fmt_pct(pace, 0)} dari target berjalan {fmt_idr(tmtd)}. "
            f"Sisa {summary['sisa_hari']} hari perlu rata-rata **{fmt_idr(need)}/hari**, prediksi hanya {fmt_idr(fc)}/hari "
            f"(kurang {fmt_idr(need - fc)}/hari). Jalankan Top 5 tindakan di bawah hari ini.",
            icon=":material/warning:",
        )
    else:
        st.success(f"Proyeksi akhir bulan {fmt_idr(summary['proyeksi'])} sudah di atas target {fmt_idr(target)} "
                   f"(aktual s.d. {upto} {fmt_pct(pace, 0)} dari target berjalan). Jaga stok SKU utama menjelang hari promo.")


def _recent_sku(orders_all: pd.DataFrame, start: date, end: date, prior_days: int = 28) -> pd.DataFrame:
    """QTY bersih per SKU pada [start, end] (qty) dan `prior_days` hari sebelumnya (qty_sebelum)."""
    from src.core.gudang import norm_sku
    from src.core.metrics import net_sku_sales

    rows = net_sku_sales(orders_all, start - timedelta(days=prior_days), end)
    if rows.empty:
        return pd.DataFrame(columns=["sku", "qty", "qty_sebelum"])
    recent = pd.to_datetime(rows["order_time"]).dt.normalize() >= pd.Timestamp(start)
    frame = pd.DataFrame({"sku": rows["sku"].map(norm_sku), "qty": rows["qty"].where(recent, 0.0), "qty_sebelum": rows["qty"].where(~recent, 0.0)})
    return frame.groupby("sku", as_index=False)[["qty", "qty_sebelum"]].sum()


def _missing_inputs(table: pd.DataFrame | None) -> list[str]:
    if table is None or table.empty:
        return ["hasil analisa"]
    missing = []
    if "ada_data_stok" not in table.columns or not table["ada_data_stok"].fillna(False).astype(bool).any():
        missing.append("data stok Site 10037 (prioritas stok)")
    cost = pd.to_numeric(table.get("biaya_iklan", pd.Series(dtype=float)), errors="coerce").fillna(0)
    if not (cost > 0).any():
        missing.append("laporan iklan (prioritas iklan)")
    return missing


def _top_actions(top: pd.DataFrame, summary: dict, behind: bool, missing: list[str]) -> None:
    st.markdown("<div class='section-title'>Top 5 tindakan segera</div>", unsafe_allow_html=True)
    if missing:
        st.caption("Belum ada di analisa ini: " + ", ".join(missing) + ". Unggah lalu jalankan analisa agar Top 5 ikut menghitungnya.")
    if top.empty:
        st.caption("Tidak ada SKU dengan kekurangan stok atau ruang iklan yang menguntungkan. Periksa harga dan listing SKU yang capaiannya turun di tabel prediksi vs aktual di atas.")
        return
    total = float(top["Potensi omzet"].sum())
    gap = summary["kurang"]
    note = f"Total potensi {fmt_idr(total)} sampai akhir bulan"
    if behind and np.isfinite(gap) and gap > 0:
        cover = total / gap * 100
        note += f" · menutup {fmt_pct(min(cover, 999), 0)} kekurangan target"
        if cover < 100:
            note += f". Sisa {fmt_idr(gap - total)} perlu promo tambahan (flash sale/voucher toko) pada hari promo berikutnya."
    st.markdown(f"<div class='field-hint'>{html.escape(note)}</div>", unsafe_allow_html=True)
    show_table(top, kinds={"Prioritas": "count", "Potensi omzet": "money"}, column_config={
        "Tindakan": st.column_config.TextColumn(width="large"), "Alasan": st.column_config.TextColumn(width="large")})
