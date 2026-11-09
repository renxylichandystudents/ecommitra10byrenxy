"""Prediksi › Pantauan harian bulan berjalan: prediksi H-1 vs aktual per tanggal, target omzet, hari promo, Top 5 tindakan."""

from __future__ import annotations

import calendar
import html
from datetime import date, timedelta

import numpy as np
import pandas as pd
import streamlit as st

from src.core import month_track as M
from src.ui.common import card, download_excel, explain, fmt_idr, fmt_pct
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
    net, product, last_stamp = _daily_series(orders_all)
    if last_stamp is None:
        st.info("Belum ada data pesanan.")
        return
    data_last = last_stamp.date()
    complete = last_stamp.hour >= 23
    cutoff = data_last if complete else data_last - timedelta(days=1)
    months = []
    probe = (cutoff + timedelta(days=1)).replace(day=1)
    for _ in range(3):
        months.append(probe)
        probe = (probe - timedelta(days=1)).replace(day=1)
    labels = [f"{ID_MONTHS[m.month - 1]} {m.year}" for m in months]
    picked = st.selectbox("Bulan", labels, index=0, key="mt-month", label_visibility="collapsed")
    first = months[labels.index(picked)]
    month_days = calendar.monthrange(first.year, first.month)[1]
    last_day = first + timedelta(days=month_days - 1)
    current = first == months[0]
    month_cutoff = min(cutoff, last_day) if current else last_day
    running = None
    if current and data_last > cutoff and data_last <= last_day:
        running = float(net.get(pd.Timestamp(data_last), 0.0))
    if current and cutoff < today - timedelta(days=1):
        st.warning(f"Data pesanan baru sampai {last_stamp:%d/%m/%Y %H:%M}. Hari sesudahnya dihitung dari prediksi; "
                   "unggah data pesanan terbaru agar pencapaian kemarin terbaca.", icon=":material/schedule:")

    done_lo = pd.Timestamp(first)
    done_hi = pd.Timestamp(month_cutoff)
    net_month = float(net.loc[done_lo:done_hi].sum()) if month_cutoff >= first else 0.0
    prod_month = float(product.loc[done_lo:done_hi].sum()) if month_cutoff >= first else 0.0
    if prod_month <= 0:
        lo = pd.Timestamp(cutoff - timedelta(days=29))
        net_month, prod_month = float(net.loc[lo:pd.Timestamp(cutoff)].sum()), float(product.loc[lo:pd.Timestamp(cutoff)].sum())
    factor = float(min(max(net_month / prod_month, 0.5), 1.2)) if prod_month > 0 and net_month > 0 else 1.0
    history = net.loc[pd.Timestamp(cutoff - timedelta(days=364)):pd.Timestamp(cutoff)]
    profile = M.seasonal_profile(history)

    from src.ui.targets_view import monthly_targets

    target = monthly_targets(features).get(f"{first.year:04d}-{first.month:02d}")
    runs = _prediction_runs(features, first, last_day)
    days = [first + timedelta(days=i) for i in range(month_days)]
    preds = M.as_of_predictions(runs, days)
    month = M.month_table(
        month_first=first, cutoff=month_cutoff, actual=net.loc[done_lo:done_hi] if month_cutoff >= first else pd.Series(dtype=float),
        predictions=preds, factor=factor, profile=profile, target_month=target, running_actual=running,
    )
    summary = M.month_summary(month, month_cutoff, target, today=today)

    _cards(summary, month_cutoff, today, running, data_last, target, current)
    _target_alert(summary, target, current)
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
            excluded=getattr(data, "excluded", set()) if data is not None else set(),
            default_roas=float(cfg.get("roas_default", 6)), unpaid=unpaid, unpaid_orders=unpaid_orders,
            recent=_recent_sku(orders_all, cutoff - timedelta(days=6), cutoff),
        )
        _top_actions(top, summary, behind, _missing_inputs(table))

    _charts(month, target, month_cutoff)
    with st.expander(f"Rincian per tanggal · {picked}", expanded=False):
        view = _detail_view(month)
        show_table(view, kinds={"Pola hari": "dec", "Target": "money", "Prediksi": "money", "Aktual": "money", "Selisih": "money",
                                "% capaian": "pct", "Kumulatif aktual": "money", "Kumulatif target": "money", "Kumulatif proyeksi": "money"},
                   max_height=1200)
        download_excel(view, f"pantauan_harian_{first:%Y_%m}.xlsx", key="mt-xl")
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
                if pd.notna(pred) else "Belum ada analisa sebelum tanggal ini")
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


def _target_alert(summary: dict, target: float | None, current: bool) -> None:
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
            f"Aktual s.d. kemarin {fmt_idr(mtd)} = {fmt_pct(pace, 0)} dari target berjalan {fmt_idr(tmtd)}. "
            f"Sisa {summary['sisa_hari']} hari perlu rata-rata **{fmt_idr(need)}/hari**, prediksi hanya {fmt_idr(fc)}/hari "
            f"(kurang {fmt_idr(need - fc)}/hari). Jalankan Top 5 tindakan di bawah hari ini.",
            icon=":material/warning:",
        )
    else:
        st.success(f"Proyeksi akhir bulan {fmt_idr(summary['proyeksi'])} sudah di atas target {fmt_idr(target)} "
                   f"(aktual s.d. kemarin {fmt_pct(pace, 0)} dari target berjalan). Jaga stok SKU utama menjelang hari promo.")


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


def _charts(month: pd.DataFrame, target: float | None, cutoff: date) -> None:
    import plotly.graph_objects as go

    mode = st.segmented_control("Grafik", ["Harian", "Kumulatif"], default="Harian", key="mt-chart") or "Harian"
    x = pd.to_datetime(month["tanggal"])
    fig = go.Figure()
    if mode == "Harian":
        fig.add_bar(x=x, y=month["aktual"], name="Aktual", marker_color="#1b3da6",
                    hovertemplate="%{x|%d/%m}<br>Aktual Rp %{y:,.0f}<extra></extra>")
        fig.add_scatter(x=x, y=month["prediksi"], name="Prediksi", mode="lines+markers", line=dict(color="#ee4d2d", dash="dot"),
                        hovertemplate="%{x|%d/%m}<br>Prediksi Rp %{y:,.0f}<extra></extra>")
        if target:
            fig.add_scatter(x=x, y=month["target"], name="Target harian", mode="lines", line=dict(color="#64748b", shape="hv"),
                            hovertemplate="%{x|%d/%m}<br>Target Rp %{y:,.0f}<extra></extra>")
    else:
        fig.add_scatter(x=x, y=month["kum_aktual"], name="Aktual kumulatif", mode="lines+markers", line=dict(color="#1b3da6", width=3))
        fig.add_scatter(x=x, y=month["kum_proyeksi"].where(month["status_hari"].ne("Selesai") | month["tanggal"].eq(cutoff)),
                        name="Proyeksi (aktual + prediksi)", mode="lines", line=dict(color="#ee4d2d", dash="dot"))
        if target:
            fig.add_scatter(x=x, y=month["kum_target"], name="Target kumulatif", mode="lines", line=dict(color="#64748b"))
    for day, kind in zip(month["tanggal"], month["jenis_hari"]):
        if kind != "Normal":
            fig.add_vrect(x0=pd.Timestamp(day) - pd.Timedelta(hours=12), x1=pd.Timestamp(day) + pd.Timedelta(hours=12),
                          fillcolor="#fde68a" if kind == "Gajian" else "#fca5a5", opacity=0.25, line_width=0, layer="below")
    fig.add_vline(x=pd.Timestamp(cutoff) + pd.Timedelta(hours=12), line_dash="dash", line_color="#94a3b8")
    fig.update_layout(height=340, margin=dict(l=30, r=20, t=10, b=30), legend=dict(orientation="h", y=1.08),
                      xaxis=dict(type="date", tickformat="%d/%m", dtick=86_400_000 * 2), yaxis=dict(tickformat=",.0f"), hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True, key=f"mt-fig-{mode}")
    st.caption("Kolom kuning = gajian (25–3), merah muda = tanggal kembar. Garis putus tegak = batas data aktual penuh.")


def _detail_view(month: pd.DataFrame) -> pd.DataFrame:
    view = month.assign(
        Tanggal=pd.to_datetime(month["tanggal"]).dt.strftime("%d/%m/%Y"),
        Analisa=pd.to_datetime(month["analisa"]).dt.strftime("%d/%m %H:%M").fillna("–"),
    )
    view = view.rename(columns={
        "hari": "Hari", "keterangan": "Hari promo", "pola": "Pola hari", "target": "Target", "prediksi": "Prediksi", "aktual": "Aktual",
        "selisih": "Selisih", "capaian_pct": "% capaian", "status": "Status", "status_hari": "Data", "kum_aktual": "Kumulatif aktual",
        "kum_target": "Kumulatif target", "kum_proyeksi": "Kumulatif proyeksi",
    })
    cols = ["Tanggal", "Hari", "Hari promo", "Pola hari", "Target", "Prediksi", "Aktual", "Selisih", "% capaian", "Status", "Data", "Analisa",
            "Kumulatif aktual", "Kumulatif target", "Kumulatif proyeksi"]
    return view[cols]
