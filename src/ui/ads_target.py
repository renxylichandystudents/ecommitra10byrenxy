"""Rekomendasi › Iklan: strategi iklan untuk mengejar target sales bulan berjalan.

Pengguna menetapkan tiga angka: target sales bulan ini, target ROAS, dan budget iklan sisa bulan. Rencana dihitung
hanya untuk iklan produk tunggal dan iklan grup (plus usulan iklan produk tunggal baru). Tambahan omzet tiap iklan
dibatasi ruang stok produknya (barang yang tidak ada tidak bisa terjual); margin hanya tampil sebagai catatan per iklan.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import streamlit as st

from src.core import ads_fixed as F
from src.core import ads_strategy as A
from src.core import campaigns as C
from src.core.business import business_targets
from src.core.campaigns import as_date
from src.core.fmt import fmt_date
from src.ui import campaign_ui as cmp
from src.core.targets import month_label
from src.ui.common import batched_view, button_tabs, card, download_excel, explain, fmt_idr, fmt_num, fmt_pct
from src.ui.feature_data import bump, target_for
from src.ui.targets_view import month_outlook, target_roas_for
from functools import partial

from src.utils.format import angka, input_rupiah, parse_rupiah
from src.utils.format import show_table as _show_table

# Tabel iklan: sel kosong (mis. ROAS produk yang belum pernah diiklankan) tampil "–", bukan "None".
show_table = partial(_show_table, dash_missing=True)

UP = "#1d4ed8"
DOWN = "#dc2626"
MONTHS_FULL = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember")


def _tone(ok: bool) -> str:
    return UP if ok else DOWN


def _signed(value: float) -> str:
    return ("+" if value >= 0 else "−") + fmt_idr(abs(value))


def _push_action_style(action: str) -> str:
    colors = {
        A.PUSH_PRIORITIZE: ("#166534", "#dcfce7"),
        A.PUSH_SCALE: ("#075985", "#e0f2fe"),
        A.PUSH_HOLD: ("#334155", "#f1f5f9"),
        A.PUSH_PAUSE: ("#991b1b", "#fee2e2"),
    }
    fg, bg = colors.get(str(action), ("#334155", "#f1f5f9"))
    return f"color:{fg};background:{bg}"


def _show_push_top_n(selection: pd.DataFrame, *, top_n: int = 8) -> None:
    """Tabel Top N Push tunggal & Masuk/pertahankan grup — skor, aksi, chip alasan, % gap (derived)."""
    if selection is None or selection.empty or "Push skor" not in selection.columns:
        return
    single, group = A.push_top_tables(selection, top_n=top_n)
    degraded = int((selection.get("Peringatan degradasi", pd.Series(dtype=str)).astype(str) == A.BUDGET_DEGRADE_WARN).sum()) if "Peringatan degradasi" in selection.columns else 0
    if degraded:
        _box(
            "⚠️ Degradasi budget (eksplisit)",
            f"<b>{fmt_num(degraded)} produk</b> diubah dari <b>Buat iklan tunggal</b> menjadi <b>Tambahkan ke grup</b> "
            f"karena budget usulan 0 pada setelan ROAS/budget ini — bukan rekomendasi struktural diam-diam. "
            f"Chip: <code>{html.escape(A.BUDGET_DEGRADE_WARN)}</code>.",
            "#b45309",
        )
    st.caption("Push skor 0–100 (gap · ROAS vs BEP aman · margin · stok · bonus belum occupied · penalti CTR hanya jika kolom CTR ada). "
               "% gap tertutup = estimasi derived dari prediksi/stok vs kekurangan harian. Jalur eksekusi utama tetap unduhan Seller Center.")
    c1, c2 = st.columns(2)
    kinds = {"Push skor": "dec", "% gap tertutup": "pct", "ROAS 2 bulan": "dec", "Prediksi omzet/hari": "money", "Stok": "count"}
    col_cfg = {
        "Produk": st.column_config.TextColumn(width="medium"),
        "Alasan chip": st.column_config.TextColumn(width="large"),
        "Aksi push": st.column_config.TextColumn(width="small"),
        "% gap tertutup": st.column_config.Column(help="Estimasi derived: prediksi/stok vs gap harian — bukan jaminan GMV."),
    }
    with c1:
        st.markdown("**Top push tunggal**")
        if single.empty:
            st.caption("Belum ada kandidat rute tunggal pada skor ini.")
        else:
            show_table(single.drop(columns=["Peringatan degradasi"], errors="ignore"), kinds=kinds, row_height=35, max_height=420,
                       column_config=col_cfg)
    with c2:
        st.markdown("**Top masuk / pertahankan grup**")
        if group.empty:
            st.caption("Belum ada kandidat rute grup pada skor ini.")
        else:
            show_table(group.drop(columns=["Peringatan degradasi"], errors="ignore"), kinds=kinds, row_height=35, max_height=420,
                       column_config=col_cfg)
    # Chip ringkas aksi
    if "Aksi push" in selection.columns:
        chips = []
        for act in A.PUSH_ACTIONS:
            n = int((selection["Aksi push"] == act).sum())
            if not n:
                continue
            style = _push_action_style(act)
            chips.append(
                f"<span style='border:1px solid #e2e8f0;border-radius:999px;padding:.2rem .65rem;font-size:var(--fs-sm);"
                f"{style}'><b>{html.escape(act)}</b> {fmt_num(n)}</span>"
            )
        if chips:
            st.markdown("<div style='display:flex;flex-wrap:wrap;gap:.4rem;margin:.35rem 0 .5rem'>" + "".join(chips) + "</div>",
                        unsafe_allow_html=True)


def _set_value(key: str, value: float, *, money: bool = True) -> None:
    st.session_state[key] = angka(round(value)) if money else float(value)


def _progress_bar(actual: float, rest: float, extra: float, target: float) -> str:
    """Batang: aktual (gelap) + prediksi sisa bulan (muda) + tambahan dari rencana iklan (oranye), garis target."""
    rest = max(rest + min(extra, 0), 0)
    scale = max(target, actual + rest + max(extra, 0)) * 1.06 or 1.0
    seg = lambda value, color, label: (  # noqa: E731
        f"<div title='{html.escape(label)}' style='width:{max(value, 0) / scale * 100:.2f}%;background:{color};height:100%'></div>" if value > 0 else ""
    )
    marker = (
        f"<div style='position:absolute;left:{target / scale * 100:.2f}%;top:-6px;bottom:-6px;width:3px;background:#0f172a;border-radius:2px'></div>"
        f"<div style='position:absolute;left:{target / scale * 100:.2f}%;top:-1.45rem;transform:translateX(-50%);font-size:var(--fs-xs);font-weight:700;color:#0f172a;white-space:nowrap'>Target</div>"
        if target > 0 else ""
    )
    legend = (
        "<div style='display:flex;flex-wrap:wrap;gap:1rem;font-size:var(--fs-xs);color:#475569;margin-top:.45rem'>"
        f"<span><i style='display:inline-block;width:10px;height:10px;background:#1e3a8a;border-radius:2px;margin-right:4px'></i>Aktual {fmt_idr(actual)}</span>"
        f"<span><i style='display:inline-block;width:10px;height:10px;background:#93c5fd;border-radius:2px;margin-right:4px'></i>Prediksi sisa bulan {fmt_idr(rest)}</span>"
        f"<span><i style='display:inline-block;width:10px;height:10px;background:#ee4d2d;border-radius:2px;margin-right:4px'></i>Efek budget iklan {_signed(extra)}</span>"
        "</div>"
    )
    return (
        "<div style='position:relative;margin:1.6rem 0 .2rem'>"
        "<div style='display:flex;height:22px;border-radius:999px;overflow:hidden;background:#e2e8f0'>"
        + seg(actual, "#1e3a8a", "Aktual") + seg(rest, "#93c5fd", "Prediksi sisa bulan") + seg(extra, "#ee4d2d", "Tambahan iklan")
        + "</div>" + marker + "</div>" + legend
    )


def _box(title: str, body: str, color: str) -> None:
    st.markdown(
        f"<div style='border:1px solid #e2e8f0;border-left:5px solid {color};border-radius:12px;background:#fff;padding:.75rem 1rem;margin:.7rem 0'>"
        f"<div style='font-weight:800;color:{color};margin-bottom:.25rem'>{title}</div><div style='font-size:var(--fs-base);line-height:1.6;color:#1f2937'>{body}</div></div>",
        unsafe_allow_html=True,
    )


def _step(number: int, title: str, note: str = "") -> None:
    st.markdown(
        f"<div style='display:flex;align-items:baseline;gap:.55rem;margin:1.1rem 0 .4rem'>"
        f"<span style='background:#ee4d2d;color:#fff;border-radius:999px;min-width:1.6rem;height:1.6rem;display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-size:var(--fs-sm)'>{number}</span>"
        f"<span style='font-weight:800;font-size:var(--fs-lg)'>{html.escape(title)}</span>"
        f"<span style='color:#64748b;font-size:var(--fs-sm)'>{html.escape(note)}</span></div>",
        unsafe_allow_html=True,
    )


def _ads_os_hub(cur: dict | None, today: date) -> dict:
    """A0: status Ads OS (running / learning / siap end / antrian kosong)."""
    hub = C.hub_status(cur, today)
    color = {
        "empty": "#64748b",
        C.LEARNING_LOCKED: "#b45309",
        C.ENDING_PROPOSED: "#dc2626",
        C.STABLE: "#1d4ed8",
        C.SCALING: "#059669",
        C.HOLDING: "#475569",
        C.ENDED: "#64748b",
        C.EXPORTED: "#1d4ed8",
    }.get(hub.get("state") or "empty", "#1d4ed8")
    st.markdown(
        f"<div style='border:1px solid #e2e8f0;border-left:5px solid {color};border-radius:14px;background:#fff;"
        f"padding:.85rem 1.05rem;margin:.35rem 0 .75rem'>"
        f"<div style='font-size:var(--fs-xs);text-transform:uppercase;letter-spacing:.06em;color:#64748b;font-weight:700'>Ads OS</div>"
        f"<div style='font-weight:800;font-size:var(--fs-lg);color:{color};margin:.15rem 0'>{html.escape(hub['label'])}</div>"
        f"<div style='color:#334155;line-height:1.55'>{html.escape(hub['blurb'])}</div></div>",
        unsafe_allow_html=True,
    )
    return hub


def _overlap_will_pause(acts: pd.DataFrame, selection: pd.DataFrame) -> pd.DataFrame:
    """D0: daftar iklan/produk yang akan dijeda di SC saat apply rencana (overlap / jeda usulan)."""
    rows: list[dict] = []
    if isinstance(acts, pd.DataFrame) and not acts.empty and "Tindakan" in acts.columns:
        for _, r in acts.loc[acts["Tindakan"].astype(str).isin(["Jeda", "Turunkan budget"])].iterrows():
            if str(r.get("Tindakan")) == "Turunkan budget" and float(r.get("Budget harian usulan") or 0) > 0:
                continue
            rows.append({
                "Iklan": str(r.get("Iklan") or ""),
                "Jenis": str(r.get("Jenis") or ""),
                "Kode produk": str(r.get("Kode produk") or ""),
                "Alasan": "Jeda / budget 0 di rencana — pause di Seller Center",
            })
    if isinstance(selection, pd.DataFrame) and not selection.empty and "Saran" in selection.columns:
        pause_sel = selection.loc[selection["Saran"].astype(str).isin(["Jeda sampai restock", "Keluarkan dari grup"])]
        for _, r in pause_sel.iterrows():
            rows.append({
                "Iklan": str(r.get("Iklan") or r.get("Produk") or ""),
                "Jenis": str(r.get("Jenis") or ""),
                "Kode produk": str(r.get("Kode produk") or ""),
                "Alasan": str(r.get("Saran") or ""),
            })
    if not rows:
        return pd.DataFrame(columns=["Iklan", "Jenis", "Kode produk", "Alasan"])
    out = pd.DataFrame(rows).drop_duplicates(subset=["Iklan", "Kode produk", "Alasan"], keep="first")
    return out.reset_index(drop=True)


ACT_COLS = ["Tindakan", "Iklan", "Jenis", "Anggota", "Kode produk", "Budget harian sekarang", "Budget harian usulan", "Perubahan/hari",
            "Target ROAS Shopee", "ROAS bulan terakhir", "Prediksi omzet produk/hari", "Omzet iklan usulan/hari", "Tambahan omzet/hari", "Catatan"]
ACT_KINDS = {"Budget harian sekarang": "money", "Budget harian usulan": "money", "Perubahan/hari": "money", "Tambahan omzet/hari": "money",
             "Prediksi omzet produk/hari": "money", "Omzet iklan usulan/hari": "money",
             "Anggota": "count", "ROAS bulan terakhir": "dec", "Target ROAS Shopee": "dec"}
SEL_KINDS = {"Biaya iklan/hari": "money", "Omzet iklan/hari": "money", "ROAS 2 bulan": "dec", "Porsi omzet grup": "pct",
             "Prediksi omzet/hari": "money", "Prediksi qty/hari": "dec", "Stok": "count", "Budget usulan iklan/hari": "money"}


LIFTS = (0.5, 0.75, 1.0)
LIFT_LABELS = {0.5: "+50% · konservatif", 0.75: "+75% · sedang", 1.0: "+100% · agresif"}


def _apply(roas_key: str, roas: float, budget_key: str, budget: float, *, lift_key: str | None = None, lift: float | None = None) -> None:
    _set_value(roas_key, roas, money=False)
    _set_value(budget_key, budget)
    if lift_key is not None:
        st.session_state[lift_key] = lift


def _blocks(start: date, end: date, first_open: date, month_end: date) -> list[tuple[date, date]]:
    """Minggu campaign di sisa bulan target (setelah tanggal data terakhir); bila tidak ada, seluruh periode campaign."""
    a, b = max(start, first_open), min(end, month_end)
    return A.week_blocks(a, b) if a <= b else A.week_blocks(start, end)


def _recommendation(units, members, products, contribution, *, weeks: list[int], gap: float, lift: float, key: tuple) -> dict:
    """`A.recommend` disimpan per sesi: pencarian ROAS butuh beberapa detik dan tidak bergantung pada budget/ROAS yang diketik."""
    cache = st.session_state.setdefault("adt-rec-cache", {})
    full = (*key, tuple(weeks), round(gap), lift, len(units), round(sum(u.daily_cost for u in units)), round(sum(u.daily_sales for u in units)),
            len(products), round(sum(contribution.values()), 4) if isinstance(contribution, dict) else 0)
    if full not in cache:
        if len(cache) > 8:
            cache.clear()
        cache[full] = A.recommend(units, members, products, contribution, weeks=weeks, gap_total=gap, lift=lift, stock_cap=True)
    return cache[full]


DAY_NAMES = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")
FIXED_CSS = """<style>
.st-key-adt-fixed{border:2px solid #ee4d2d;border-radius:16px;background:linear-gradient(180deg,#fff4ed 0%,#ffffff 38%);
padding:1rem 1.1rem 1.1rem;margin:1rem 0 .6rem;box-shadow:0 6px 20px rgba(238,77,45,.12)}
</style>"""


def _day_shape_of(orders: pd.DataFrame | None, last: date):
    try:
        from src.ui.prediksi_top import _day_shape

        return _day_shape(orders, last) if orders is not None and not orders.empty else (lambda _d: 1.0)
    except Exception:
        return lambda _d: 1.0


def _fixed_plan(units, members, products, contribution, *, weeks, blocks, gap_ads: float, roas: float, budget_daily: float, lift: float, shape, key: tuple,
                select_roas: float | None = None, exclude: frozenset = frozenset(), min_marginal: float = A.MIN_MARGINAL,
                occupied: frozenset = frozenset(), base_selection=None) -> dict:
    """Rencana budget & ROAS tetap (dengan batas stok) + kalender budget harian; disimpan per sesi seperti rekomendasi."""
    cache = st.session_state.setdefault("adt-fixed-cache", {})
    full = (*key, tuple(weeks), round(gap_ads), round(roas, 2), round(budget_daily), lift, select_roas, len(units), round(sum(u.daily_cost for u in units)),
            round(sum(u.daily_sales for u in units)), len(products), tuple(sorted(exclude)), min_marginal, tuple(sorted(occupied)))
    if full not in cache:
        if len(cache) > 8:
            cache.clear()
        run_days = max(sum(weeks), 1)
        plan_units, plan, selection = A.build_plan(units, members, products, contribution, gap_daily=gap_ads / run_days, target_roas=roas,
                                                   budget_daily=budget_daily, lift=lift, stock_cap=True, select_roas=select_roas, exclude=exclude,
                                                   min_marginal=min_marginal, occupied=occupied, base_selection=base_selection)
        steps = A.ramp(plan_units, weeks=weeks, gap_total=gap_ads, target_roas=roas, budget_total=budget_daily * run_days, first=plan, min_marginal=min_marginal)
        calendar, timing = F.day_plan(plan_units, steps, blocks, shape)
        cache[full] = {"units": plan_units, "plan": plan, "selection": selection, "steps": steps, "eff": A.ramp_effect(plan_units, steps),
                       "kalender": calendar, "timing": timing}
    return cache[full]


def _calendar_view(calendar: pd.DataFrame) -> pd.DataFrame:
    from src.core.month_track import day_label

    def action(m: float) -> str:
        if m >= 1.01:
            return f"Naikkan budget iklan 'ikut kalender' ×{m:.2f}".replace(".", ",")
        if m <= 0.99:
            return f"Turunkan budget iklan 'ikut kalender' ×{m:.2f}".replace(".", ",")
        return "Budget minggu ini (×1)"

    return pd.DataFrame({
        "Tanggal": calendar["Tanggal"].map(fmt_date), "Hari": calendar["Tanggal"].map(lambda d: DAY_NAMES[d.weekday()]),
        "Jenis hari": calendar["Tanggal"].map(lambda d: day_label(d) or "Normal"), "Minggu": calendar["Minggu"], "Pola hari": calendar["Pola hari"],
        "Pengali budget": calendar["Pengali budget"], "Budget/hari": calendar["Budget/hari"], "Omzet iklan/hari": calendar["Omzet iklan/hari"],
        "ROAS hari": calendar["ROAS hari"], "Tindakan di Shopee": calendar["Pengali budget"].map(action),
    })


def _option_plan(units, members, products, contribution, *, weeks, gap_ads: float, roas: float, budget_daily: float | None, lift: float, key: tuple,
                 stock: bool = True, select_roas: float | None = None, exclude: frozenset = frozenset(), min_marginal: float = A.MIN_MARGINAL,
                 occupied: frozenset = frozenset(), base_selection=None) -> dict:
    """Hasil iklan untuk ROAS & budget harian tertentu (None = tanpa batas); stock=False: stok dianggap cukup. Disimpan per sesi.

    Selain angka `ramp_effect`, `kurang_stok` = daftar iklan yang tambahan penjualannya melebihi stok tersisa (nilai jual)."""
    cache = st.session_state.setdefault("adt-option-cache", {})
    full = (*key, tuple(weeks), round(gap_ads), round(roas, 2), -1 if budget_daily is None else round(budget_daily), lift, stock, select_roas, len(units),
            round(sum(u.daily_cost for u in units)), len(products), tuple(sorted(exclude)), min_marginal, tuple(sorted(occupied)))
    if full not in cache:
        if len(cache) > 300:
            cache.clear()
        run_days = max(sum(weeks), 1)
        plan_units, plan, _sel = A.build_plan(units, members, products, contribution, gap_daily=gap_ads / run_days, target_roas=roas,
                                              budget_daily=budget_daily, lift=lift, stock_cap=stock, select_roas=select_roas, exclude=exclude,
                                              min_marginal=min_marginal, occupied=occupied, base_selection=base_selection)
        steps = A.ramp(plan_units, weeks=weeks, gap_total=gap_ads, target_roas=roas,
                       budget_total=None if budget_daily is None else budget_daily * run_days, first=plan, min_marginal=min_marginal)
        result = dict(A.ramp_effect(plan_units, steps))
        short: dict[str, list] = {}
        if not stock:
            for days, step in steps:
                for u in plan_units:
                    if u.locked or not np.isfinite(u.stock_room):
                        continue
                    gap_u = A.ad_sales(u, step.cost.get(u.key, 0.0)) - A._now_sales(u) - max(u.stock_room, 0.0)
                    if gap_u > 1:
                        item = short.setdefault(u.key, [u.nama, 0.0, max(u.stock_room, 0.0)])
                        item[1] += gap_u * days
        result["kurang_stok"] = sorted(short.values(), key=lambda x: -x[1])
        cache[full] = result
    return cache[full]


def _fixed_strategy(res: dict, *, rec: dict | None, target: float, projection: float, factor: float, period_days: int, run_days: int,
                    budget: float, roas: float, auto: bool, key_budget: str, key_roas: str, key_mode: str, set_key_budget: str, set_key_roas: str,
                    mode_key: str, applied: bool, start: date, periode: str, lift: float, current_roas: float, option, gap_ads: float,
                    sales_now: float, demand_daily: float) -> None:
    units, plan, eff, calendar, timing = res["units"], res["plan"], res["eff"], res["kalender"], res["timing"]
    ads_net = eff["omzet_tambahan"] * factor
    timing_net = max(timing["tambahan"], 0.0) * factor
    final = projection + ads_net + timing_net
    budget_run = budget / period_days * run_days
    used = float(eff["biaya_total"])
    unused = max(budget_run - used, 0.0)
    short = max(target - final, 0.0)
    limited = [u for u in units if F.stock_limited(u) and plan.cost.get(u.key, 0) > 0]
    r_txt, cur_txt = fmt_num(roas, 1), fmt_num(current_roas, 1)

    st.markdown(
        "<div style='display:flex;align-items:center;gap:.6rem;flex-wrap:wrap'>"
        "<span style='background:#ee4d2d;color:#fff;border-radius:999px;padding:.15rem .7rem;font-size:var(--fs-xs);font-weight:800;letter-spacing:.03em'>FITUR KHUSUS</span>"
        "<span style='font-weight:800;font-size:var(--fs-lg);color:#0f172a'>🎯 Kejar target hanya dengan iklan · budget dikunci</span></div>"
        "<div style='color:#475569;font-size:var(--fs-sm);margin:.3rem 0 .6rem'>Isi budget iklan yang tersedia. Sistem menghitung ROAS yang dibutuhkan untuk menutup "
        "sisa target, lalu memilih Target ROAS dan membagi budget ke iklan supaya omzet iklan sebesar mungkin tanpa melewati budget. "
        "Hanya iklan produk tunggal & grup; flash sale, voucher, dan sumber lain tidak dihitung.</div>",
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns([1.25, 0.95, 0.7, 1.0])
    with c1:
        input_rupiah(f"Budget iklan yang tersedia ({period_days} hari)", int(budget), key=key_budget,
                     help="Plafon budget iklan produk tunggal + grup untuk periode campaign. Rencana tidak akan melewati angka ini.")
    c2.radio("ROAS", ["Diatur sistem", "Saya tentukan"], key=key_mode, horizontal=True,
             help="Diatur sistem: Target ROAS 1–30 dicoba semua dengan budget ini; yang diisi = ROAS rata-rata pembagian budget dengan omzet iklan terbesar. Saya tentukan: ROAS rata-rata tidak boleh di bawah angka Anda.")
    if auto:
        c3.markdown(f"<div style='font-size:var(--fs-sm);color:#64748b;margin-top:.2rem'>Target ROAS</div>"
                    f"<div style='font-weight:800;font-size:var(--fs-xl);color:#0f172a'>{r_txt}</div>", unsafe_allow_html=True)
    else:
        c3.number_input("ROAS minimal", min_value=1.0, max_value=A.MAX_SHOPEE_ROAS, step=0.5, key=key_roas)
    with c4:
        st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        st.button("✓ Dipakai di langkah 3–4" if applied else "Jadikan setelan campaign", key="adt-fix-apply", type="primary",
                  disabled=applied, use_container_width=True, on_click=_apply_fixed, args=(set_key_roas, roas, set_key_budget, budget, mode_key))

    if short <= 1:
        verdict, color = f"Target tercapai dengan iklan saja · proyeksi {fmt_pct(final / target * 100, 1)}", UP
    else:
        verdict, color = f"Dengan budget ini, iklan membawa proyeksi ke {fmt_pct(final / target * 100, 1)} target · kurang {fmt_idr(short)}", DOWN
    st.markdown(f"<div style='border-radius:12px;background:{color};color:#fff;padding:.65rem 1rem;margin:.5rem 0 .7rem;font-weight:700'>{html.escape(verdict)}</div>",
                unsafe_allow_html=True)
    k = st.columns(3)
    card(k[0], "Proyeksi akhir bulan", fmt_idr(final), hint=f"<b style='color:{_tone(final >= target)}'>{fmt_pct(final / target * 100, 1)}</b> dari target {fmt_idr(target)}"
                                                           f" · tanpa perubahan iklan {fmt_pct(projection / target * 100, 1)}"
                                                           + (f" · termasuk atur budget per tanggal {_signed(timing_net)}" if timing_net >= 1 else ""))
    card(k[1], "Omzet tambahan dari iklan", _signed(ads_net + timing_net), hint=f"ROAS rata-rata {fmt_num(eff['roas_rencana'], 1)} (Target ROAS {r_txt}) · ROAS iklan sekarang {cur_txt}")
    card(k[2], "Budget terpakai", fmt_idr(used), hint=f"dari {fmt_idr(budget_run)} tersedia"
                                                      + (f" · <b style='color:{DOWN}'>{fmt_idr(unused)} tidak terpakai</b>" if unused > max(0.01 * budget_run, 1.0) else " · terpakai penuh"))

    # Hitungan target: ROAS yang dibutuhkan vs kemampuan iklan dengan budget ini
    days_txt = f"{fmt_num(run_days)} hari"
    base_now = sum(A._now_sales(u) for u in units)
    need_sales = base_now * run_days + gap_ads
    need = F.needed_roas(sales_now_daily=base_now, gap=gap_ads, days=run_days, budget=budget_run)
    achieved = float(eff["roas_rencana"]) if eff["roas_rencana"] == eff["roas_rencana"] else 0.0
    with st.spinner("Menghitung hasil bila stok produk iklan cukup..."):
        free = max((option(r, budget / period_days, lift, False) for r in {1.0, roas}), key=lambda e: e["omzet_tambahan"])
    free_final = projection + free["omzet_tambahan"] * factor + timing_net
    free_roas = float(free["roas_rencana"]) if free["roas_rencana"] == free["roas_rencana"] else 0.0
    gap_daily_ads = gap_ads / max(run_days, 1)
    lines = [
        f"<b>Kekurangan ke target</b>: {fmt_idr(target - projection)} sales bersih = <b>{fmt_idr(gap_daily_ads)}/hari</b> nilai produk selama {days_txt}"
        + (f", setara <b>+{gap_daily_ads / demand_daily * 100:.0f}%</b> dari prediksi penjualan semua produk ({fmt_idr(demand_daily)}/hari)" if demand_daily > 0 else "") + ".",
        f"<b>Agar budget {fmt_idr(budget_run)} cukup</b>, omzet iklan selama {days_txt} harus {fmt_idr(need_sales)} "
        f"(omzet iklan sekarang di susunan baru {fmt_idr(base_now)}/hari × {days_txt} + kekurangan) → <b>ROAS dibutuhkan {fmt_num(need, 1)}</b>. "
        f"ROAS iklan sekarang {cur_txt}"
        + (f" (semua iklan berjalan, omzet {fmt_idr(sales_now)}/hari)" if abs(base_now - sales_now) > 1 else "") + ".",
        f"<b>Kemampuan iklan dengan budget ini</b> (kurva hasil tiap iklan): ROAS rata-rata <b>{fmt_num(achieved, 1)}</b> dengan stok sekarang → "
        f"{fmt_pct(final / target * 100, 1)} target; bila produk iklan direstock, ROAS {fmt_num(free_roas, 1)} → {fmt_pct(free_final / target * 100, 1)} target.",
    ]
    if short <= 1:
        lines.append("✅ <b>Target tercapai dengan budget ini.</b> Isi Target ROAS sesuai tabel <i>Budget per iklan</i> dan jalankan langkah di bawah.")
    else:
        lines.append(
            f"⚠️ <b>Budget {fmt_idr(budget_run)} belum cukup untuk target hanya dengan iklan</b>: butuh ROAS {fmt_num(need, 1)}, sedangkan yang realistis "
            f"{fmt_num(achieved, 1)}. Penyebabnya: tiap tambahan Rp 1 iklan menghasilkan makin sedikit (pembeli paling berminat sudah terjangkau), "
            f"tambahan penjualan per produk dibatasi +{lift * 100:.0f}% dari prediksinya"
            + (", dan sebagian produk iklan akan habis stok" if free_final - final > max(0.005 * target, 1.0) else "")
            + ". Strategi di bawah memberi omzet iklan terbesar dari budget ini.")
    if auto:
        lines.append(f"<b>Target ROAS {r_txt} diatur sistem</b>: semua Target ROAS 1–30 dicoba dengan budget ini; pembagian budget dengan omzet iklan terbesar "
                     f"memberi ROAS rata-rata ±{r_txt}, jadi angka itu yang diisi di Shopee. Target ROAS lebih rendah tidak dipakai: Shopee akan "
                     "menghabiskan budget di iklan yang hampir tidak menambah penjualan.")
    elif current_roas > 0 and roas > current_roas + 0.25 and ads_net < 0:
        lines.append(f"<b>ROAS minimal {r_txt} lebih tinggi dari ROAS iklan sekarang ({cur_txt})</b>: iklan lemah harus dikurangi dan omzet iklan turun "
                     f"{fmt_idr(-ads_net)}. Pilih <i>Diatur sistem</i> untuk hasil terbesar dengan budget ini.")
    if unused > max(0.01 * budget_run, 1.0):
        lines.append(f"<b>{fmt_idr(unused)} budget tidak terpakai</b>: iklan sudah mentok di batas permintaan produk dan stok"
                     + (" atau di ROAS minimal Anda" if not auto else "") + "; menambah budget tidak menambah omzet.")
    if limited:
        lines.append(f"<b>{fmt_num(len(limited))} iklan tertahan stok</b>: budgetnya tidak dinaikkan melewati stok tersisa.")
    _box("🧮 Hitungan target dengan budget ini", "<br>".join(f"• {w}" for w in lines), color)
    if short > 1 and free["kurang_stok"]:
        with st.expander(f"Produk iklan yang akan habis stok · {fmt_num(len(free['kurang_stok']))} iklan · restock ±{fmt_idr(sum(x[1] for x in free['kurang_stok']))} nilai jual"):
            st.caption("Kurang stok = tambahan penjualan dari iklan dengan budget ini yang melebihi stok tersisa (setelah penjualan biasa) sampai akhir periode, "
                       "dalam nilai jual. Restock sebesar ini membuat iklan bisa memakai budget untuk produk tersebut.")
            show_table(pd.DataFrame([{"Iklan": n, "Kurang stok (nilai jual)": v, "Ruang stok sekarang/hari": room} for n, v, room in free["kurang_stok"]]),
                       kinds={"Kurang stok (nilai jual)": "money", "Ruang stok sekarang/hari": "money"},
                       column_config={"Iklan": st.column_config.TextColumn(width="large")})

    # Yang dikerjakan
    acts = A.target_actions(units, plan, target_roas=roas)
    todo = []
    if not acts.empty:
        up = acts.loc[acts["Tindakan"].isin(["Naikkan budget", "Buat iklan baru", "Pisahkan jadi iklan tunggal"])]
        down = acts.loc[acts["Tindakan"].isin(["Turunkan budget", "Jeda"])]
        todo.append(f"<b>Mulai {fmt_date(start)}: ubah budget iklan di Shopee</b> — {fmt_num(len(up))} iklan dinaikkan/dibuat, {fmt_num(len(down))} diturunkan/dijeda, "
                    f"total {fmt_idr(float(acts['Budget harian usulan'].sum()))}/hari di minggu pertama; isi Target ROAS tiap iklan sesuai tabel <i>Budget per iklan</i>.")
    if len(res["steps"]) > 1:
        todo.append("<b>Tiap Senin naikkan budget bertahap</b> sesuai jadwal (maks. 2× per minggu agar perlindungan ROAS Shopee tetap aktif).")
    peaks = calendar.loc[calendar["Pengali budget"] >= 1.04].sort_values("Pola hari", ascending=False) if not calendar.empty else calendar
    if not peaks.empty and timing_net > 0:
        days = ", ".join(fmt_date(d) for d in peaks["Tanggal"].head(4))
        todo.append(f"<b>Tanggal ramai ({days}{'…' if len(peaks) > 4 else ''})</b>: naikkan sedikit budget iklan bertanda <i>Ikut kalender</i>, turunkan sedikit di hari sepi "
                    f"(total sama, omzet {_signed(timing_net)}). Angka per tanggal: <i>Kalender budget harian</i>.")
    if limited:
        names = ", ".join(html.escape(u.nama[:32]) for u in sorted(limited, key=lambda u: -plan.cost.get(u.key, 0))[:3])
        todo.append(f"<b>Ajukan PO/restock</b> untuk produk di {fmt_num(len(limited))} iklan yang tertahan stok ({names}{'…' if len(limited) > 3 else ''}); "
                    "setelah stok masuk, buka menu ini lagi agar budgetnya bisa naik.")
    todo.append(f"<b>Pantau ROAS harian</b>: bila 3 hari berturut-turut di bawah {fmt_num(max(eff['roas_rencana'], 1) * 0.9, 1)}, turunkan iklan dengan ROAS terendah. "
                "Tiap Senin unggah laporan iklan dan buka menu ini lagi.")
    _box("✅ Yang dikerjakan", "<ol style='margin:0 0 0 1.1rem;padding:0'>" + "".join(f"<li style='margin-bottom:.35rem'>{t}</li>" for t in todo) + "</ol>", "#ee4d2d")

    # Rincian (tertutup)
    rows_cmp = []
    if rec is not None:
        rec_final = projection + rec["tambahan"] * factor
        rows_cmp = [("ROAS", fmt_num(rec["roas"], 1), f"{r_txt} (hasil {fmt_num(eff['roas_rencana'], 1)})"),
                    (f"Budget ({period_days} hari)", fmt_idr(rec["budget"] / run_days * period_days), f"{fmt_idr(budget)} (terpakai {fmt_idr(used)})"),
                    ("Omzet tambahan dari iklan", _signed(rec["tambahan"] * factor), _signed(ads_net + timing_net)),
                    ("Proyeksi akhir bulan", fmt_idr(rec_final), fmt_idr(final)),
                    ("% target", fmt_pct(rec_final / target * 100, 1), fmt_pct(final / target * 100, 1))]
    with st.expander("Rincian angka & perbandingan dengan rekomendasi sistem"):
        show_table(pd.DataFrame([
            {"Langkah": "Tanpa perubahan iklan (aktual + prediksi)", "Tambahan sales bersih": 0.0, "Proyeksi": projection},
            {"Langkah": "Budget dibagi ulang ke iklan terbaik", "Tambahan sales bersih": ads_net, "Proyeksi": projection + ads_net},
            {"Langkah": "Budget digeser ke tanggal ramai", "Tambahan sales bersih": timing_net, "Proyeksi": final},
        ]).assign(**{"% target": lambda f: f["Proyeksi"] / target * 100}), kinds={"Tambahan sales bersih": "money", "Proyeksi": "money", "% target": "pct"})
        if rows_cmp:
            show_table(pd.DataFrame(rows_cmp, columns=["Ukuran", "Rekomendasi sistem", "Budget dikunci"]))
        st.caption(f"Tambahan omzet tiap iklan dibatasi daya dorong +{lift * 100:.0f}% dari prediksi produknya dan stok tersisa; sales bersih = nilai produk × "
                   f"{fmt_num(factor * 100, 1)}% (setelah voucher Shopee). Kalender harian memakai pola sales bersih 12 bulan.")

    cols = ["Tindakan", "Iklan", "Jenis", "Budget harian sekarang", "Budget harian usulan", "Perubahan/hari", "Target ROAS Shopee", "Omzet iklan usulan/hari",
            "Tambahan omzet/hari", "Catatan"]
    if not acts.empty:
        with st.expander(f"Budget per iklan · {fmt_num(int((acts['Budget harian usulan'] > 0).sum()))} iklan aktif"):
            view = acts[cols].copy()
            by_key = {u.key: u for u in units}
            view.insert(1, "Dibatasi stok", ["Ya" if k in by_key and F.stock_limited(by_key[k]) else "" for k in acts["key"]])
            view.insert(2, "Ikut kalender", ["Ya" if k in timing.get("ikut", set()) else "" for k in acts["key"]])
            show_table(view, kinds=ACT_KINDS, column_config={"Iklan": st.column_config.TextColumn(width="medium"), "Catatan": st.column_config.TextColumn(width="large")})
    cal_view = _calendar_view(calendar)
    if not cal_view.empty:
        with st.expander(f"Kalender budget harian · {fmt_date(calendar['Tanggal'].min())} – {fmt_date(calendar['Tanggal'].max())}"):
            st.caption(f"Pengali hanya untuk {fmt_num(len(timing.get('ikut', ())))} iklan bertanda 'Ikut kalender' (masih bisa tumbuh); iklan lain tetap di budget mingguannya. "
                       "Pengali 0,7–1,4 menjaga perubahan antarhari maks. 2× sehingga perlindungan ROAS Shopee tetap aktif.")
            show_table(cal_view, kinds={"Budget/hari": "money", "Omzet iklan/hari": "money", "ROAS hari": "dec", "Pola hari": "dec", "Pengali budget": "dec", "Minggu": "count"})
    setup = A.seller_center_setup(acts, None, campaign="Fitur khusus · budget dikunci", target_roas=roas, period=f"{period_days} hari")
    download_excel(setup, f"setelan_seller_center_budget_dikunci_{periode}.xlsx", key="xl-adt-fixed",
                   label="Unduh setelan Seller Center")


def _apply_fixed(set_key_roas: str, roas: float, set_key_budget: str, budget: float, mode_key: str) -> None:
    _apply(set_key_roas, roas, set_key_budget, budget)
    st.session_state[mode_key] = (float(roas), float(budget))


def _run_days(start: date, end: date, first_open: date, month_end: date) -> int:
    """Hari campaign yang jatuh di sisa bulan target (setelah tanggal data terakhir)."""
    a, b = max(start, first_open), min(end, month_end)
    return max((b - a).days + 1, 0)


def _describe(c: dict) -> str:
    s = c.get("setelan") or {}
    return (f"Target {fmt_idr(s.get('target', 0))} · target ROAS {fmt_num(s.get('roas', 0), 1)} · budget {fmt_idr(s.get('budget', 0))} "
            f"(≈ {fmt_idr(s.get('budget_harian', 0))}/hari, rencana {fmt_idr(s.get('budget_rencana_harian', 0))}/hari) · "
            f"proyeksi saat disimpan {fmt_idr(s.get('proyeksi', 0))} ({fmt_pct(s.get('capaian', 0), 1)} target) · {fmt_num(len(c.get('iklan') or []))} iklan")


def _not_advertised(products: pd.DataFrame, selection: pd.DataFrame, *, key: str, periode: str) -> None:
    """Produk (Kode produk) yang tidak masuk iklan mana pun di rencana, untuk diunduh."""
    if products is None or products.empty or "product_code" not in products.columns:
        return
    in_plan, status = set(), {}
    if selection is not None and not selection.empty and "Kode produk" in selection.columns:
        codes = selection["Kode produk"].astype(str)
        if "Iklan di rencana" in selection.columns:
            in_plan = set(codes[selection["Iklan di rencana"].astype(str) != "–"])
        status = dict(zip(codes, selection["Saran"].astype(str)))
    rest = products.loc[~products["product_code"].astype(str).isin(in_plan)]
    if rest.empty:
        return
    out = pd.DataFrame({
        "Kode produk": rest["product_code"].astype(str), "Produk": rest["nama"], "Prediksi omzet/hari": rest["omzet_harian"], "Stok": rest["stok"],
        "Status di rencana": rest["product_code"].astype(str).map(status).fillna("tidak terpilih: omzet/stok belum layak iklan sendiri"),
    }).sort_values("Prediksi omzet/hari", ascending=False).reset_index(drop=True)
    with st.expander(f"Produk tidak diiklankan di rencana · {fmt_num(len(out))} produk"):
        st.caption("Produk yang tidak berada di iklan tunggal maupun grup mana pun setelah rencana dijalankan (dikeluarkan, dijeda, atau tidak terpilih).")
        batched_view(
            len(out), key=f"{key}-view", noun="produk",
            render=lambda lo, hi: show_table(out.iloc[lo:hi], kinds={"Prediksi omzet/hari": "money", "Stok": "count"}, max_height=10_000,
                                             column_config={"Produk": st.column_config.TextColumn(width="large")}),
            download=lambda: download_excel(out, f"produk_tidak_diiklankan_{periode}.xlsx", key=f"xl-{key}", label="Unduh SKU tidak dijadwalkan"),
        )




def _store_curve(ads_overall, orders, *, before: date):
    """Kurva respons toko (biaya iklan bulanan vs sales bersih bulanan), disimpan per sesi."""
    from src.core import ads_month as M
    from src.core.metrics import normalize_lines, order_metrics

    if ads_overall is None or orders is None or orders.empty:
        return None
    key = (before, len(ads_overall), len(orders), str(pd.to_datetime(orders["order_time"], errors="coerce").max()))
    cache = st.session_state.get("adt-store-curve")
    if isinstance(cache, tuple) and cache[0] == key:
        return cache[1]
    lines = normalize_lines(orders)
    stamps = pd.to_datetime(lines["order_time"], errors="coerce") if "order_time" in lines.columns else pd.Series(dtype="datetime64[ns]")
    sales: dict[str, float] = {}
    if not stamps.empty and stamps.notna().any():
        for period in sorted(stamps.dt.to_period("M").dropna().unique()):
            lo, hi = period.start_time.date(), period.end_time.date()
            if hi >= before:
                continue
            sales[f"{lo.year:04d}-{lo.month:02d}"] = float(order_metrics(lines, lo, hi, normalized=True)["sales_bersih"])
    curve = M.fit_store_curve(M.monthly_history(ads_overall, sales, before=before))
    st.session_state["adt-store-curve"] = (key, curve)
    return curve


VIEW_CUSTOM, VIEW_REC, VIEW_TRACK = "fitur-khusus", "rekomendasi", "pantau"


def _round_m(value: float) -> float:
    return float(math.ceil(max(value, 0.0) / 1_000_000) * 1_000_000)


def _submitted_setting(features, periode: str) -> dict | None:
    """Setelan Fitur khusus yang sudah dikirim untuk bulan ini (kv `iklan-setelan:<periode>`), disimpan per sesi."""
    key = f"adt-submitted-{periode}"
    if key not in st.session_state:
        try:
            st.session_state[key] = features.get_json(f"iklan-setelan:{periode}", None) if features is not None else None
        except Exception:
            st.session_state[key] = None
    return st.session_state.get(key) or None


def _rec_options(*, target: float, projection: float, spent: float, cost_now: float, days_left: int, month_days: int, run_days: int, pace_total: float,
                 curve, spent_daily: float, best_roas, option, project, units, factor: float, month_name: str,
                 economics, ratio_budget, user_budget: float | None = None, user_note: str = "",
                 contrib_rate: float | None = None) -> tuple[list[dict], dict]:
    """Opsi rekomendasi sistem (biaya yang benar-benar bisa dibelanjakan efisien + sadar margin):

    - Budget Anda / laju sekarang / maksimal efisien / hemat / minimum Shopee / 100% target (hanya bila tidak menambah rugi).
    - Bila kontribusi toko di bawah titik impas iklan, opsi utama = yang estimasi kontribusi sesudah iklan paling baik
      (bukan sales tertinggi dengan biaya gila).
    Mengembalikan (opsi, info kebutuhan 100% target)."""
    from src.core import ads_month as M

    gap = target - projection
    out: list[dict] = []
    strict = 2 * A.MIN_MARGINAL
    res_share = max(days_left, 0) / max(month_days, 1)
    m_now = curve.marginal(cost_now * month_days) if curve is not None and cost_now > 0 else (
        curve.marginal(spent_daily * month_days) if curve is not None and spent_daily > 0 else float("nan"))
    underwater = M.ads_deepens_loss(contrib_rate, m_now) if m_now == m_now else (contrib_rate is not None and contrib_rate <= 0)
    profit_cap = M.profitable_monthly_cap(curve, contrib_rate)

    def make(name: str, budget: float, action: str, extra_lines: list[str] | None = None, *, mm: float = A.MIN_MARGINAL, origin: str = "") -> dict:
        daily = max(budget - spent, 0.0) / max(days_left, 1)
        roas = best_roas(daily, gap, mm)
        final, extra, by_curve, effective = project(target, budget, roas, mm)
        reach = final / target * 100 if target else 0.0
        saved_cost = max(budget - effective, 0.0)
        lines = [f"Budget iklan {month_name} <b>{fmt_idr(budget)}</b> (terpakai {fmt_idr(spent)} + sisa {fmt_idr(max(budget - spent, 0))} ≈ "
                 f"<b>{fmt_idr(daily)}/hari</b> selama {days_left} hari), Target ROAS Shopee <b>{fmt_num(roas, 1)}</b>; tiap tambahan Rp 1 biaya iklan "
                 f"minimal kembali Rp {fmt_num(mm, 0)} omzet iklan.",
                 (f"Biaya yang benar-benar dibelanjakan rencana ≈ <b>{fmt_idr(effective)}</b> sebulan; <b>hemat {fmt_idr(saved_cost)}</b> karena sisanya tidak bisa "
                  "dipakai efisien (produk distop/dikecualikan, batas naik 2×/minggu, atau tambahan Rp 1 tidak lagi kembali cukup)."
                  if saved_cost > 500_000 else f"Seluruh budget terserap efisien (≈ {fmt_idr(effective)} sebulan)."),
                 f"Hasil: proyeksi sales bersih akhir bulan <b>{fmt_idr(final)}</b> ({fmt_pct(reach, 1)} target), efek budget iklan {_signed(extra)} "
                 "dibanding iklan berjalan dengan laju rata-rata bulan ini" + (" (kurva respons toko)." if by_curve else " (rencana per iklan)."),
                 f"Yang dilakukan: {action}", *(extra_lines or [])]
        if curve is not None and by_curve:
            pace = max(effective - spent, 0.0) / max(res_share, 1e-9)
            lo_c, hi_c = min(p_[1] for p_ in curve.points), max(p_[1] for p_ in curve.points)
            if pace < lo_c * 0.8 or pace > hi_c * 1.3:
                lines.append(f"⚠️ Laju biaya ±{fmt_idr(pace)}/bulan di luar riwayat ({fmt_idr(lo_c)}–{fmt_idr(hi_c)}): proyeksi kurva kurang andal, "
                             "ubah bertahap dan pantau tiap Senin.")
        ratio, profit = economics(final, effective)
        econ = []
        if ratio == ratio:
            econ.append(f"biaya iklan ≈ <b>{fmt_pct(ratio, 1)}</b> sales bruto sebulan "
                        + ("(✓ memenuhi syarat minimum Shopee 3%)" if ratio >= M.SHOPEE_MIN_AD_PCT - 0.05 else "(⚠️ di bawah syarat minimum Shopee 3%)"))
        if profit is not None:
            econ.append(f"estimasi kontribusi sesudah iklan {_signed(profit)}")
        if econ:
            lines.insert(3, "Ekonomi: " + " · ".join(econ) + ".")
        return {"nama": name, "budget": budget, "harian": daily, "roas": roas, "proyeksi": final, "tambahan": extra, "aksi": action, "rincian": lines,
                "utama": False, "efektif": effective, "mm": mm, "rasio": ratio, "laba": profit, "asal": origin}

    if user_budget:
        out.append(make("Budget Anda", float(user_budget),
                        "jalankan budget yang Anda isi di Fitur khusus; sistem membagi sisanya ke iklan bermargin positif / ROAS tinggi dulu (lihat Pemilihan produk).",
                        origin=f"diisi di Fitur khusus{(' · ' + user_note) if user_note else ''}"))
    # Laju sekarang: jangan disajikan sebagai jalur wajar bila jauh di atas rata-rata bulan ini.
    pace_vs_avg = cost_now / spent_daily if spent_daily > 0 and cost_now > 0 else 1.0
    high_burn = pace_vs_avg >= 1.5
    if not user_budget or abs(pace_total - user_budget) > 0.02 * max(user_budget, 1):
        if high_burn:
            out.append(make(
                f"Laju tinggi sekarang ({fmt_idr(cost_now)}/hari · +{fmt_pct((pace_vs_avg - 1) * 100, 0)} vs rata-rata)",
                max(pace_total, spent),
                "turunkan dulu ke laju mendekati rata-rata bulan ini, lalu rapikan produk: iklan tunggal untuk andalan bermargin positif, "
                "grup untuk sisanya, jeda yang ROAS lemah.",
                [f"⚠️ Laju berjalan {fmt_idr(cost_now)}/hari vs rata-rata 1–hari-data {fmt_idr(spent_daily)}/hari. "
                 "Meneruskan laju ini tanpa seleksi produk biasanya boros dan (bila margin toko lemah) menambah rugi."],
                origin=f"terpakai {fmt_idr(spent)} + iklan berjalan {fmt_idr(cost_now)}/hari × {days_left} hari (bukan saran utama)",
            ))
        else:
            out.append(make(f"Laju iklan sekarang diteruskan ({fmt_idr(cost_now)}/hari)", max(pace_total, spent),
                            "budget harian iklan tetap seperti sekarang; rapikan pemilihan produk (tunggal vs grup) & Target ROAS sesuai tabel di bawah.",
                            origin=f"terpakai {fmt_idr(spent)} + iklan berjalan {fmt_idr(cost_now)}/hari × {days_left} hari"))
    res = M.month_plan(curve, target=target, projection=projection, spent=spent, cost_now_daily=spent_daily, days_left=days_left,
                       month_days=month_days, budget_total=None)
    need_total = _round_m(res["budget_dibutuhkan"]) if res.get("ada_kurva") else None
    # Plafon pencarian: jangan pakai cost_now×4 bila laju berjalan sudah absurd — pakai rata-rata / kebutuhan kurva.
    search_daily = max(
        (need_total - spent) / max(days_left, 1) if need_total else 0.0,
        spent_daily * 2 if spent_daily > 0 else 0.0,
        min(cost_now, spent_daily * 1.5) if spent_daily > 0 else cost_now,
        1.0,
    )
    big = max(search_daily, 1.0)
    absorbed = min(float(option(best_roas(big, gap), big, gap)["biaya_total"]) / max(run_days, 1), big)
    max_total = _round_m(spent + absorbed * days_left)
    # Batas titik impas toko: jangan usulkan "maksimal efisien" di atas laju di mana marginal sales × kontribusi < 1.
    if profit_cap is not None and days_left > 0:
        cap_total = _round_m(spent + max(profit_cap, 0.0) * (days_left / max(month_days, 1)))
        if underwater:
            max_total = min(max_total, max(cap_total, spent))
        elif cap_total > spent:
            max_total = min(max_total, cap_total)
    lean_daily = min(float(option(best_roas(big, gap, strict), big, gap, strict)["biaya_total"]) / max(run_days, 1), big)
    lean_total = _round_m(spent + lean_daily * days_left)
    # Acuan laju sehat ≈ rata-rata bulan ini (bukan spike berjalan).
    avg_pace_total = _round_m(spent + spent_daily * days_left) if spent_daily > 0 else pace_total
    if high_burn and abs(avg_pace_total - pace_total) > 0.02 * max(pace_total, 1):
        out.append(make(
            f"Kembalikan ke rata-rata bulan ini ({fmt_idr(spent_daily)}/hari)",
            max(avg_pace_total, spent),
            "turunkan budget iklan ke laju rata-rata 1–hari-data; pindahkan budget ke iklan tunggal produk bermargin positif yang ROAS-nya kuat, "
            "sisanya di grup hemat.",
            ["Jalur terukur dari data terbaru: biaya ikut histori bulan ini, bukan spike harian yang sedang jalan."],
            origin=f"terpakai {fmt_idr(spent)} + rata-rata {fmt_idr(spent_daily)}/hari × {days_left} hari",
        ))
    if out and max_total > max(o["efektif"] for o in out) * 1.02:
        eff_lines = [f"Ini batas biaya yang masih efisien menurut ROAS iklan: iklan yang ada + usulan iklan baru ±{fmt_idr(absorbed)}/hari. "
                     f"Di atas itu tambahan Rp 1 kembali kurang dari Rp {fmt_num(A.MIN_MARGINAL, 0)} omzet iklan."]
        if underwater:
            eff_lines.append("⚠️ Kontribusi toko di bawah titik impas: opsi ini menaikkan omzet tetapi estimasi kontribusi sesudah iklan bisa lebih buruk. "
                             "Utamakan opsi hemat / minimum Shopee bila prioritasnya tidak menambah rugi.")
        out.append(make("Maksimal yang bisa dibelanjakan efisien", max_total,
                        "naikkan hanya iklan tunggal bermargin positif yang masih efektif (maks. 2× tiap Senin); produk lemah tetap di grup atau dikeluarkan.",
                        eff_lines,
                        origin=f"batas biaya yang tiap tambahan Rp 1 masih kembali ≥ Rp {fmt_num(A.MIN_MARGINAL, 0)} omzet iklan"
                               + (" · dibatasi titik impas toko" if profit_cap is not None else "")))
    if out and lean_total < min(o["efektif"] for o in out) * 0.98:
        out.append(make(f"Hemat biaya (tiap Rp 1 kembali ≥ Rp {fmt_num(strict, 0)})", lean_total,
                        "pangkas/jeda iklan dan produk yang hasilnya rendah; pertahankan iklan tunggal andalan bermargin positif, sisanya di grup hemat.",
                        ["Opsi ini menekan biaya iklan sambil menjaga omzet dari produk yang benar-benar merespons."], mm=strict,
                        origin=f"hanya iklan yang tiap tambahan Rp 1 kembali ≥ Rp {fmt_num(strict, 0)} omzet iklan"))
    min_total = ratio_budget()
    if min_total is not None and out and min_total < min(o["efektif"] for o in out) * 0.98:
        out.append(make(f"Minimum {fmt_num(M.SHOPEE_MIN_AD_PCT, 0)}% sales bruto (syarat Shopee)", min_total,
                        "turunkan budget iklan ke batas minimum agar benefit Shopee tetap didapat; budget hanya untuk iklan tunggal ROAS tertinggi bermargin positif.",
                        ["Opsi paling hemat yang masih memenuhi syarat minimum biaya iklan Shopee."],
                        origin=f"{fmt_num(M.SHOPEE_MIN_AD_PCT, 0)}% × sales bruto proyeksi bulan ini (tidak kurang dari yang sudah terpakai)"))
    info = {
        "need": need_total,
        "max_efisien": max((max(o["efektif"] for o in out) if out else 0.0), spent + absorbed * days_left),
        "gap": gap,
        "absorbed": absorbed,
        "underwater": underwater,
        "profit_cap": profit_cap,
        "high_burn": high_burn,
    }
    # 100% target hanya ditawarkan bila tidak secara jelas menambah rugi.
    if need_total is not None and gap > 0 and need_total <= info["max_efisien"] * 1.02 and not underwater:
        lines = []
        room = sum(max(u.stock_room, 0.0) for u in units if np.isfinite(u.stock_room))
        need_extra_daily = gap / max(days_left, 1) / max(factor, 1e-9)
        if room and need_extra_daily > room:
            lines.append(f"⚠️ Ruang stok produk yang diiklankan ±{fmt_idr(room)}/hari, di bawah tambahan penjualan yang dibutuhkan ±{fmt_idr(need_extra_daily)}/hari: "
                         "ajukan restock/PO agar target tidak tertahan stok.")
        out.append(make("Budget untuk 100% target", need_total,
                        "naikkan budget iklan efektif bertahap tiap Senin pada produk bermargin positif, buat iklan tunggal untuk andalan, dan pastikan stok cukup.",
                        lines, origin="kurva respons toko: biaya sebulan agar proyeksi = target"))
    elif need_total is not None and gap > 0 and underwater:
        info["need_blocked"] = True

    if not out:
        return out, info

    if underwater:
        # Prioritas: estimasi kontribusi sesudah iklan terbaik (paling sedikit rugi), lalu biaya terkecil.
        with_laba = [o for o in out if o["laba"] is not None]
        pick = max(with_laba, key=lambda o: (o["laba"], -o["efektif"])) if with_laba else min(out, key=lambda o: o["efektif"])
    elif gap <= 0:
        ok = [o for o in out if o["proyeksi"] >= target - 1]
        pick = min(ok, key=lambda o: o["efektif"]) if ok else max(out, key=lambda o: o["proyeksi"])
    else:
        # Sales tertinggi, tapi bila opsi lain hanya kalah ≤ 0,5% target dengan biaya lebih kecil / laba lebih baik, pilih yang lebih sehat.
        best = max(o["proyeksi"] for o in out)
        near = [o for o in out if o["proyeksi"] >= best - max(0.005 * target, 1.0)]
        pick = min(near, key=lambda o: (o["efektif"], -(o["laba"] if o["laba"] is not None else -1e30)))
    # Jangan jadikan opsi "laju tinggi / spike" sebagai utama.
    if high_burn and pick["nama"].startswith("Laju tinggi"):
        alts = [o for o in out if not o["nama"].startswith("Laju tinggi")]
        if alts:
            if underwater and any(o["laba"] is not None for o in alts):
                pick = max([o for o in alts if o["laba"] is not None], key=lambda o: (o["laba"], -o["efektif"]))
            else:
                pick = min(alts, key=lambda o: o["efektif"]) if underwater else max(alts, key=lambda o: (o["proyeksi"], -o["efektif"]))
    pick["utama"] = True
    for i, o in enumerate(out):
        o["nama"] = f"{chr(65 + i)} · {o['nama']}"
    return out, info


def _track_banner(cur: dict, track: dict | None) -> None:
    s = cur.get("setelan") or {}
    src = html.escape(str(s.get("sumber") or "rencana"))
    if track is None:
        text, color = (f"📌 Rencana #{cur['id']} ({src}) disimpan tanpa titik awal pantauan (rencana lama) atau bulan sudah berganti: "
                       "buka <b>Pantau rencana tersimpan</b> untuk evaluasi per iklan."), "#64748b"
    elif track["status"] == "Menunggu data":
        text, color = (f"📌 Rencana #{cur['id']} ({src}) · menunggu data baru setelah {fmt_date(track['mulai'])} untuk dibandingkan dengan jalur rencana."), "#64748b"
    else:
        on = track["status"] == "On track"
        text = (f"📌 Rencana #{cur['id']} ({src}) · <b>{'✅ On track' if on else '⚠️ Tertinggal'}</b>: sales bersih s.d. hari ini {fmt_idr(track['sales'])} vs jalur rencana "
                f"{fmt_idr(track['jalur_sales'])} ({fmt_pct(track['pct_sales'], 1)}) · biaya iklan {track['biaya_status']} "
                f"({fmt_idr(track['biaya_baru'])} vs rencana {fmt_idr(track['jalur_biaya'] - track['terpakai_awal'])} sejak disimpan).")
        color = UP if on else DOWN
    st.markdown(f"<div style='border-left:5px solid {color};background:#fff;border:1px solid #e2e8f0;border-left-width:5px;border-radius:10px;"
                f"padding:.5rem .8rem;margin:.2rem 0 .6rem;font-size:var(--fs-sm);line-height:1.6'>{text}</div>", unsafe_allow_html=True)



EXCLUDE_KEY = "iklan-kecualikan"


def _exclusion_store(features) -> dict:
    cache = st.session_state.get("adt-exclude")
    if not isinstance(cache, dict):
        try:
            cache = (features.get_json(EXCLUDE_KEY, None) if features is not None else None) or {}
        except Exception:
            cache = {}
        cache = {"kode": [str(k) for k in cache.get("kode", [])], "kata": [str(k) for k in cache.get("kata", []) if str(k).strip()],
                 "oleh": cache.get("oleh", ""), "waktu": cache.get("waktu", "")}
        st.session_state["adt-exclude"] = cache
    return cache


def _product_names(products: pd.DataFrame, members: pd.DataFrame) -> dict[str, str]:
    names: dict[str, str] = {}
    if isinstance(members, pd.DataFrame) and not members.empty and {"product_code", "nama"} <= set(members.columns):
        names.update({str(k): str(v) for k, v in zip(members["product_code"], members["nama"]) if str(v)})
    if isinstance(products, pd.DataFrame) and not products.empty and {"product_code", "nama"} <= set(products.columns):
        names.update({str(k): str(v) for k, v in zip(products["product_code"], products["nama"]) if str(v)})
    return names


def _excluded_codes(features, products: pd.DataFrame, members: pd.DataFrame) -> frozenset:
    """Kode Produk yang dikecualikan pengguna: dipilih langsung + nama mengandung kata kunci (mis. merek)."""
    store = _exclusion_store(features)
    codes = set(store["kode"])
    words = [w.lower() for w in store["kata"]]
    if words:
        for code, name in _product_names(products, members).items():
            low = name.lower()
            if any(w in low for w in words):
                codes.add(code)
    return frozenset(codes)


def _match(query: str, text: str) -> bool:
    """Pencarian tepat: semua kata yang diketik harus ada di nama/kode produk (tanpa beda huruf besar-kecil)."""
    words = query.lower().split()
    low = text.lower()
    return all(w in low for w in words)


def _exclusion_editor(features, products: pd.DataFrame, members: pd.DataFrame, excluded: frozenset, *, can_edit: bool, username: str) -> None:
    store = _exclusion_store(features)
    names = _product_names(products, members)
    draft_key, ver_key = "adt-exclude-draft", "adt-exclude-ver"
    if not isinstance(st.session_state.get(draft_key), set):
        st.session_state[draft_key] = set(store["kode"])
    draft: set = st.session_state[draft_key]
    ver = int(st.session_state.get(ver_key, 0))
    with st.expander(f"🚫 Produk dikecualikan dari iklan · {fmt_num(len(excluded))} produk"):
        st.caption("Produk yang dicentang dikeluarkan dari semua iklan (grup & tunggal), tidak diusulkan iklan baru, dan budgetnya dibagi ulang ke "
                   "produk lain. Berlaku untuk Fitur khusus, Rekomendasi sistem, dan rencana berikutnya sampai centangnya dihapus.")
        c1, c2 = st.columns([2, 1])
        query = c1.text_input("Cari produk", key="adt-ex-q", placeholder="ketik nama / merek / kode, mis. lem dextone silicon",
                              help="Hanya produk yang memuat SEMUA kata yang diketik yang tampil.")
        words = c2.text_input("Kata kunci otomatis (opsional)", value=", ".join(store["kata"]), key=f"adt-ex-words-{ver}",
                              help="Produk yang namanya memuat kata ini ikut dikecualikan, termasuk produk baru nanti. Pisahkan dengan koma.")
        if query.strip():
            codes = [k for k in names if _match(query, f"{names[k]} {k}")]
            note = f"{fmt_num(len(codes))} produk cocok dengan “{html.escape(query.strip())}”"
        else:
            codes = [k for k in names if k in draft]
            note = "ketik di kotak Cari untuk menampilkan produk; tanpa pencarian hanya produk yang sudah dicentang yang tampil"
        codes = sorted(codes, key=lambda k: (k not in draft, names[k]))[:300]
        st.markdown(f"<div class='field-hint'>{note} · dicentang: <b>{fmt_num(len(draft))}</b> produk</div>", unsafe_allow_html=True)
        if codes:
            b1, b2, _sp = st.columns([1, 1, 3])
            if b1.button("Centang semua hasil", key="adt-ex-all", use_container_width=True):
                draft.update(codes)
                st.session_state[ver_key] = ver + 1
                st.rerun()
            if b2.button("Hapus centang hasil", key="adt-ex-none", use_container_width=True):
                draft.difference_update(codes)
                st.session_state[ver_key] = ver + 1
                st.rerun()
            frame = pd.DataFrame({"Kecualikan": [k in draft for k in codes], "Produk": [names[k] for k in codes], "Kode produk": codes})
            edited = st.data_editor(frame, key=f"adt-ex-ed-{ver}-{hashlib.md5(query.strip().lower().encode()).hexdigest()[:8]}", hide_index=True,
                                    disabled=["Produk", "Kode produk"], use_container_width=True, row_height=35,
                                    height=min(35 * (len(codes) + 1) + 3, 400),
                                    column_config={"Kecualikan": st.column_config.CheckboxColumn("Kecualikan", width=90),
                                                   "Produk": st.column_config.TextColumn(width=760), "Kode produk": st.column_config.TextColumn(width=130)})
            for code, on in zip(edited["Kode produk"], edited["Kecualikan"]):
                (draft.add if bool(on) else draft.discard)(str(code))
        new_words = [w.strip() for w in words.split(",") if w.strip()]
        changed = draft != set(store["kode"]) or new_words != store["kata"]
        if st.button("Simpan daftar pengecualian", key="adt-ex-save", type="primary", disabled=not (can_edit and changed)):
            new = {"kode": sorted(draft), "kata": new_words, "oleh": username, "waktu": pd.Timestamp.now().strftime("%d/%m/%Y %H:%M")}
            st.session_state["adt-exclude"] = new
            if features is not None:
                try:
                    features.set_json(EXCLUDE_KEY, new, username=username)
                except Exception:
                    pass
            st.rerun()
        if changed:
            st.caption("Ada perubahan yang belum disimpan: rencana di bawah masih memakai daftar tersimpan.")
        elif store.get("oleh"):
            st.caption(f"Terakhir disimpan {store['oleh']} {store.get('waktu', '')}.")
        if not can_edit:
            st.caption("Hanya pengguna dengan akses edit Rekomendasi yang bisa mengubah daftar ini.")


def show_target_strategy(table: pd.DataFrame, *, features, params: dict, username: str, can_edit: bool, frames=None,
                         orders: pd.DataFrame | None = None, inputs=None) -> None:
    st.markdown("<div class='section-title'>Ads OS · strategi iklan kejar target</div>", unsafe_allow_html=True)
    if table is None or table.empty:
        st.write("Jalankan analisa terlebih dahulu.")
        return
    outlook = month_outlook(orders, features)
    last, periode = outlook["last"], outlook["periode"]
    days_left = max(int(outlook["rest"]), 1)
    month_name = f"{MONTHS_FULL[last.month - 1]} {last.year}"
    saved = target_for(features, periode) or {}
    try:
        saved_plan = json.loads(saved.get("budget_json") or "{}") if saved else {}
    except (TypeError, ValueError):
        saved_plan = {}
    goals = business_targets(params, saved)
    today = date.today()
    month_end = (pd.Timestamp(last) + pd.offsets.MonthEnd(0)).date()
    first_open = last + timedelta(days=1)

    cmp.flash_message("iklan")
    _mode, cur = cmp.panel("iklan", features=features, today=today, can_edit=can_edit, username=username, describe=_describe, toggle=False)
    hub = _ads_os_hub(cur, today)
    if hub.get("next_cta") and cur is None:
        st.caption("Jalur default: **Rekomendasi sistem** → Pick SKU (Push skor) → konfirmasi → unduh Setelan SC.")

    has_ads = frames is not None and any(isinstance(f, pd.DataFrame) and not f.empty for f in (getattr(frames, "ads", []) or []))
    units, members, contribution, products, occupied = [], pd.DataFrame(), {}, pd.DataFrame(), frozenset()
    if has_ads and inputs is not None:
        with st.spinner("Membaca riwayat iklan produk tunggal & grup..."):
            packed = inputs(table, features, frames, days_left)
            if len(packed) == 5:
                units, members, contribution, products, occupied = packed
            else:
                units, members, contribution, products = packed
                occupied = frozenset(c for u in units if A._running(u) for c in u.members)
    running = [u for u in units if u.daily_cost > 0 and A._running(u)]
    cost_now = sum(u.daily_cost for u in running)
    sales_now = sum(u.daily_sales for u in running)
    projection, mtd = float(outlook["projection"]), float(outlook["mtd"])
    mtd_produk = float(outlook.get("mtd_produk") or 0.0)
    factor = float(outlook.get("faktor") or 1.0)

    # ---------------- Data bulan berjalan: biaya iklan terpakai (laporan iklan keseluruhan) & kurva respons toko
    from src.core import ads_month as M

    month_first = last.replace(day=1)
    month_days = (month_end - month_first).days + 1
    ads_overall = None
    if frames is not None:
        ads_list = list(getattr(frames, "ads", []) or [])
        ads_overall = ads_list[2] if len(ads_list) > 2 and isinstance(ads_list[2], pd.DataFrame) else None
    spend = M.ad_spend(ads_overall, month_first, last)
    spent, spent_days = float(spend["biaya"]), int(spend["hari"])
    spent_daily = spent / spent_days if spent_days else cost_now
    curve = _store_curve(ads_overall, orders, before=month_first)
    pace_total = float(math.ceil((spent + cost_now * days_left) / 1_000_000) * 1_000_000)
    current_roas = min(math.floor(sales_now / cost_now * 2) / 2, A.MAX_SHOPEE_ROAS) if cost_now > 0 else 0.0

    # ---------------- Pantauan jalur rencana (untuk banner & tab Pantau)
    track = (M.plan_track(cur.get("setelan") or {}, mtd=mtd, last=last, spent=spent, periode=periode, mtd_produk=mtd_produk,
                          factor=factor)
             if cur is not None else None)

    # ---------------- Pilihan tampilan: Rekomendasi sistem = happy path; Fitur khusus = override
    show_custom = bool(st.session_state.get("adt-show-custom")) or st.session_state.get("adt-view") == VIEW_CUSTOM
    nxt = st.session_state.pop("adt-view-next", None)
    if nxt == VIEW_CUSTOM:
        show_custom = True
        st.session_state["adt-show-custom"] = True
        st.session_state["adt-view"] = VIEW_CUSTOM
    elif nxt in (VIEW_REC, VIEW_TRACK):
        st.session_state["adt-view"] = nxt
    views = [(VIEW_REC, "💡 Rekomendasi sistem")]
    if cur is not None:
        views.append((VIEW_TRACK, "📌 Pantau rencana tersimpan"))
    if show_custom:
        views.append((VIEW_CUSTOM, "🎛️ Fitur khusus · override"))
    slugs = [v for v, _l in views]
    # Default: Pantau bila ada campaign; else Rekomendasi sistem (bukan Fitur khusus)
    if st.session_state.get("adt-view") not in slugs:
        st.session_state["adt-view"] = VIEW_TRACK if cur is not None else VIEW_REC
    view = st.session_state["adt-view"]
    clicked = button_tabs(views, view, key="adt-view-btn")
    if clicked and clicked != view:
        st.session_state["adt-view"] = clicked
        st.rerun()
    if view != VIEW_CUSTOM:
        with st.expander("Override · Fitur khusus (manual budget)", expanded=False):
            st.caption(
                "Jalur default = Rekomendasi sistem (pace picker → Pick SKU → unduh SC). "
                "Fitur khusus hanya bila Anda ingin mengunci budget sebulan sendiri — engine-nya hampir sama."
            )
            if st.button("Buka Fitur khusus", key="adt-open-custom"):
                st.session_state["adt-show-custom"] = True
                st.session_state["adt-view-next"] = VIEW_CUSTOM
                st.rerun()

    # ---------------- Periode campaign: hanya saat buat/ubah rencana (bukan di Pantau)
    hi = max(month_end, today + timedelta(days=6))
    default_start = max(today, first_open) if max(today, first_open) <= month_end else today
    if view != VIEW_TRACK:
        with st.container(border=True):
            start, end = cmp.period_picker(key=f"adt-period-{periode}", today=today, hi=hi,
                                           default=(default_start, month_end if month_end >= default_start else default_start + timedelta(days=6)))
    else:
        # Pantau memakai periode campaign tersimpan — jangan tampilkan period picker di atas cockpit.
        start = as_date(cur["mulai"]) if cur else default_start
        end = as_date(cur["selesai"]) if cur else (month_end if month_end >= default_start else default_start + timedelta(days=6))
    period_days = (end - start).days + 1
    week_text = f"{fmt_date(start)} – {fmt_date(end)}"

    # Ringkas di Fitur khusus / Rekomendasi; tab Pantau punya cockpit sendiri
    if cur is not None and view != VIEW_TRACK:
        _track_banner(cur, track)

    spent_text = (f"terpakai 1–{last.day} {month_label(periode)} <b>{fmt_idr(spent)}</b> ({fmt_idr(spent_daily)}/hari, laporan iklan keseluruhan"
                  + (f"; omzet diklaim iklan {fmt_idr(spend['omzet'])}, ROAS {fmt_num(spend['omzet'] / spent, 1)}" if spent > 0 else "") + ")"
                  if spent_days else "biaya iklan bulan ini belum terbaca (unggah laporan iklan keseluruhan bulan berjalan)")

    blocks = _blocks(start, end, first_open, month_end)
    weeks = [(b - a).days + 1 for a, b in blocks]
    run_days = max(sum(weeks), 1)
    base_units = units
    excluded = _excluded_codes(features, products, members)
    lift = A.FREE_LIFT
    select = F.selection_roas(base_units) if base_units else None
    # Kekurangan sales → omzet iklan harian yang perlu ditutup (sama dasar gap di build_plan / Fitur khusus).
    gap_ads_daily = max(float(goals.target_sales) - projection, 0.0) / max(factor, 1e-9) / max(days_left, 1)
    # Pemilihan produk: malas — baru dihitung saat Rekomendasi sistem / Fitur khusus (atau project_fn Pantau tanpa kurva).
    _sel_cache: dict = {"value": None, "ready": False}

    def _base_selection():
        if _sel_cache["ready"]:
            return _sel_cache["value"]
        if not base_units:
            _sel_cache["value"] = None
            _sel_cache["ready"] = True
            return None
        sel_key = (periode, select, round(gap_ads_daily), tuple(sorted(excluded)), tuple(sorted(occupied)), len(members), len(products),
                   round(sum(u.daily_cost for u in base_units)), round(sum(contribution.values()), 4) if contribution else 0,
                   "gap-catalog-v1", "push-score-v1")
        sel_box = st.session_state.setdefault("adt-sel-cache", {})
        if sel_key not in sel_box:
            if len(sel_box) > 4:
                sel_box.clear()
            with st.spinner("Memilih produk iklan (Push skor)…"):
                sel_box[sel_key] = A.product_selection(members, base_units, products, contribution, target_roas=select or 8.0,
                                                       exclude=excluded, occupied=occupied, gap_daily=gap_ads_daily)
        _sel_cache["value"] = sel_box[sel_key]
        _sel_cache["ready"] = True
        return _sel_cache["value"]

    def option(r: float, daily: float, gap_now: float, mm: float = A.MIN_MARGINAL) -> dict:
        return _option_plan(base_units, members, products, contribution, weeks=weeks, gap_ads=max(gap_now / factor, 0.0), roas=r, budget_daily=daily, lift=lift,
                            key=(periode, start, end), stock=True, select_roas=select, exclude=excluded, min_marginal=mm,
                            occupied=occupied, base_selection=_base_selection())

    def best_roas(daily: float, gap_now: float, mm: float = A.MIN_MARGINAL, *, fine: bool = False) -> float:
        """Pilih Target ROAS ≤ 30. `fine=False` (daftar opsi) memakai grid kasar agar halaman cepat terbuka."""
        if daily <= 0:
            return min(current_roas or 8.0, A.MAX_SHOPEE_ROAS)
        grid = A.ROAS_GRID if fine else A.OPTION_ROAS_GRID
        picked = F.pick_roas(lambda r: option(r, daily, gap_now, mm)["omzet_tambahan"], grid=grid)
        return min(F.shopee_roas(option(picked, daily, gap_now, mm)["roas_rencana"]), A.MAX_SHOPEE_ROAS)

    def spend_of(month_budget: float, roas: float, gap_now: float, mm: float = A.MIN_MARGINAL) -> float:
        """Biaya iklan harian yang benar-benar dibelanjakan rencana per iklan (setelah pemilihan produk, pengecualian,
        batas naik 2×/minggu, dan efisiensi minimum) untuk sisa budget ini; ≤ sisa budget per hari."""
        daily = max(month_budget - spent, 0.0) / days_left
        if daily <= 0 or not base_units:
            return 0.0
        return min(float(option(roas, daily, gap_now, mm)["biaya_total"]) / run_days, daily)

    def project(target: float, month_budget: float, roas: float, mm: float = A.MIN_MARGINAL) -> tuple[float, float, bool, float]:
        """(proyeksi akhir bulan, efek budget, pakai kurva toko?, biaya iklan sebulan efektif).

        Proyeksi memakai biaya yang benar-benar dibelanjakan rencana (bukan budget nominal): budget yang tidak terserap
        efisien tidak menambah sales, dan produk yang dikecualikan/distop ikut mengurangi biaya rencana."""
        used = spend_of(month_budget, roas, target - projection, mm)
        effective = spent + used * days_left
        res = M.month_plan(curve, target=target, projection=projection, spent=spent, cost_now_daily=spent_daily, days_left=days_left,
                           month_days=month_days, budget_total=effective)
        if res.get("ada_kurva"):
            return float(res["proyeksi"]), float(res["tambahan"]), True, effective
        daily = max(month_budget - spent, 0.0) / days_left
        extra = option(roas, daily, target - projection, mm)["omzet_tambahan"] * factor if base_units and daily > 0 else 0.0
        return projection + extra, extra, False, effective

    gross = float(outlook.get("mtd_bruto") or 0.0)
    gross_ratio = gross / mtd if mtd > 0 and gross > 0 else None
    weights = products.set_index("product_code")["omzet_harian"].to_dict() if isinstance(products, pd.DataFrame) and not products.empty else {}
    contrib_rate = M.store_contribution_rate(contribution or {}, weights)

    def economics(final: float, effective: float) -> tuple[float, float | None]:
        """(biaya iklan sebulan % sales bruto proyeksi, estimasi kontribusi sesudah iklan = sales bersih × kontribusi sebelum iklan − biaya iklan)."""
        ratio = effective / (final * gross_ratio) * 100 if gross_ratio and final > 0 else float("nan")
        profit = final * contrib_rate - effective if contrib_rate is not None else None
        return ratio, profit

    def ratio_budget() -> float | None:
        """Budget sebulan = 3% sales bruto proyeksi tanpa perubahan (syarat minimum Shopee), tidak kurang dari yang sudah terpakai."""
        if not gross_ratio or not base_units:
            return None
        return float(math.ceil(max(M.SHOPEE_MIN_AD_PCT / 100 * projection * gross_ratio, spent) / 1_000_000) * 1_000_000)

    if view == VIEW_TRACK and cur is not None:
        from src.ui.ads_monitor_view import render_monitor

        saved_s = cur.get("setelan") or {}
        project_fn = None
        if saved_s.get("budget_bulan") and saved_s.get("periode_target") == periode:
            project_fn = lambda goal_, roas_: project(goal_, float(saved_s["budget_bulan"]), roas_,  # noqa: E731
                                                      float(saved_s.get("efisiensi_min") or A.MIN_MARGINAL))[:2]
        perf_frame = getattr(frames, "performance", None) if frames is not None else None
        render_monitor(
            cur, units=units, members=members, products=products, contribution=contribution, projection=projection, mtd=mtd,
            target_now=float(goals.target_sales), today=today, factor=factor, first_open=first_open, month_end=month_end,
            periode=periode, has_ads=has_ads, track=track, project_fn=project_fn, ads_overall=ads_overall,
            spent_month=spent, mtd_produk=mtd_produk, features=features, username=username or "",
            orders=orders, performance=perf_frame,
        )
        return

    # Eager selection untuk tab rencana (scan opsi butuh base_selection siap).
    base_selection = _base_selection()

    if _run_days(start, end, first_open, month_end) == 0:
        st.warning(f"Periode campaign {week_text} tidak jatuh di sisa hari {month_name} setelah data terakhir ({fmt_date(last)}). "
                   "Rencana memakai seluruh periode campaign sebagai pendekatan; untuk target bulan berikutnya, unggah data & target bulan itu dulu.")

    def plan_section(n0: int, *, target: float, month_budget: float, roas: float, auto: bool, final: float, extra: float, source: str, key: str,
                     mm: float = A.MIN_MARGINAL) -> None:
        """Pemilihan produk + budget per iklan + simpan, untuk setelan apa pun (fitur khusus atau opsi rekomendasi)."""
        remaining = max(month_budget - spent, 0.0)
        budget_daily = remaining / days_left
        budget = budget_daily * period_days
        reach = final / target * 100 if target > 0 else 0.0
        roas = min(float(roas), A.MAX_SHOPEE_ROAS)
        gap_ads = max(target - projection, 0.0) / max(factor, 1e-9)
        plan_gap_daily = gap_ads / max(run_days, 1)
        # Satu logika pemilihan untuk Fitur khusus & Rekomendasi sistem. Bila target beda dari acuan cache, hitung ulang.
        sel_for_plan = base_selection
        if base_units and (base_selection is None or abs(float(target) - float(goals.target_sales or 0)) > 1.0):
            sel_for_plan = A.product_selection(members, base_units, products, contribution, target_roas=select or 8.0,
                                               exclude=excluded, occupied=occupied, gap_daily=plan_gap_daily)
        with st.spinner("Membagi budget ke iklan..."):
            fixed = _fixed_plan(base_units, members, products, contribution, weeks=weeks, blocks=blocks, gap_ads=gap_ads, roas=roas,
                                budget_daily=budget_daily, lift=lift, shape=_day_shape_of(orders, last), key=(periode, start, end), select_roas=select,
                                exclude=excluded, min_marginal=mm, occupied=occupied, base_selection=sel_for_plan)
        units, plan, selection, steps = fixed["units"], fixed["plan"], fixed["selection"], fixed["steps"]
        eff = fixed["eff"]
        week_table = A.weekly_table(units, steps, blocks)
        used_daily = sum(plan.cost.values())
        fixed_used = True
        acts = A.target_actions(units, plan, target_roas=roas)
        setup_sheets = A.seller_center_setup(acts, selection, campaign=source, target_roas=roas, period=week_text)

        # ---------------- B0/C0: Pick SKU (produk) dulu — bukan unduh SC
        _step(n0, "Pick SKU · pemilihan produk", "· Top N Push skor · tunggal vs grup · occupied/stok/BEP")
        learning_exit = start + timedelta(days=C.LEARNING_DAYS - 1)
        st.caption(
            f"Learning terkunci ~{C.LEARNING_DAYS} hari sejak {fmt_date(start)} (keluar learning {fmt_date(learning_exit)}). "
            f"Target ROAS rencana ≤ {fmt_num(A.MAX_SHOPEE_ROAS, 0)}; lantai budget "
            f"Rp {fmt_num(A.SHOPEE_MIN_SINGLE, 0)} tunggal / Rp {fmt_num(A.SHOPEE_MIN_GROUP, 0)} grup."
        )
        _exclusion_editor(features, products, members, excluded, can_edit=can_edit, username=username)
        if selection.empty:
            st.info("Belum ada data produk iklan (laporan iklan grup / keseluruhan) untuk dianalisa.")
        else:
            if "Push skor" not in selection.columns:
                selection = A.enrich_push_scores(
                    selection, products, contribution, gap_daily=plan_gap_daily, occupied=occupied,
                )
            _show_push_top_n(selection, top_n=8)
            sel_groups = [
                ("Buat iklan tunggal", "🆕", UP, "produk laris belum diiklankan"), ("Jadikan iklan tunggal", "⭐", UP, "andalan di grup"),
                ("Pertahankan iklan tunggal", "✅", "#64748b", ""), ("Tambahkan ke grup", "➕", UP, "belum diiklankan"),
                ("Pertahankan di grup", "✅", "#64748b", ""), ("Pindahkan ke grup", "↘️", DOWN, "iklan tunggal kurang efisien"),
                ("Keluarkan dari grup", "➖", DOWN, "menyedot budget"), (A.SMALL_SALES, "🔻", DOWN, "potensi sales & qty kecil"), (A.MANUAL_OUT, "🚫", DOWN, "daftar pengecualian"),
                ("Jeda sampai restock", "⏸️", DOWN, "stok 0"), ("Sudah di iklan lain", "🔁", "#64748b", "jangan buat dobel"),
            ]
            chips = []
            for name, icon, color, note in sel_groups:
                count = int((selection["Saran"] == name).sum())
                if count:
                    chips.append(f"<span style='border:1px solid #e2e8f0;border-radius:999px;padding:.25rem .75rem;font-size:var(--fs-sm);background:#fff'>{icon} "
                                 f"<b style='color:{color}'>{name}</b> {fmt_num(count)} produk" + (f" · {note}" if note else "") + "</span>")
            st.markdown("<div style='display:flex;flex-wrap:wrap;gap:.45rem;margin:.2rem 0 .6rem'>" + "".join(chips) + "</div>", unsafe_allow_html=True)
            with st.expander("Tabel pemilihan produk (rincian analisa — bukan file yang diisi di Shopee)", expanded=False):
                names = [g[0] for g in sel_groups if (selection["Saran"] == g[0]).any()]
                default_pick = [n for n in names if not n.startswith("Pertahankan") and n != "Sudah di iklan lain"]
                picked = st.multiselect("Tampilkan saran", names, default=default_pick, key="adt-sel-pick", placeholder="Semua saran")
                sel_drop = selection.drop(columns=["_unit"], errors="ignore")
                sel_view = sel_drop.loc[sel_drop["Saran"].isin(picked)] if picked else sel_drop
                sel_kinds = {"Biaya iklan/hari": "money", "Omzet iklan/hari": "money", "ROAS 2 bulan": "dec", "Porsi omzet grup": "pct",
                             "Prediksi omzet/hari": "money", "Prediksi qty/hari": "dec", "Stok": "count", "Budget usulan iklan/hari": "money",
                             "Push skor": "dec", "% gap tertutup": "pct"}
                batched_view(
                    len(sel_view), key="adt-sel", noun="produk",
                    render=lambda lo, hi: show_table(sel_view.iloc[lo:hi], kinds=sel_kinds, max_height=10_000, row_height=35,
                                                     column_config={"Produk": st.column_config.TextColumn(width="medium"), "Alasan": st.column_config.TextColumn(width="large")}),
                    download=lambda: download_excel(sel_drop, f"pemilihan_produk_iklan_{periode}.xlsx", key="xl-adt-sel",
                                                    label="Unduh rincian analisa produk"),
                )
            selection = selection.drop(columns=["_unit"], errors="ignore")
            floor_sales, floor_qty = A.potential_floors(products)
            dup_count = int((selection["Saran"] == "Sudah di iklan lain").sum())
            paused_count = int((selection["Saran"] == A.PAUSED_IDLE).sum()) if hasattr(A, "PAUSED_IDLE") else 0
            new_count = int((selection["Saran"] == "Buat iklan tunggal").sum())
            if dup_count:
                st.caption(f"{fmt_num(dup_count)} produk sudah di iklan AKTIF lain (otomatis/berjalan): tidak diusulkan iklan baru agar tidak dobel.")
            if paused_count:
                st.caption(f"{fmt_num(paused_count)} produk di iklan yang sudah dijeda/nonaktif: biarkan (bukan langkah setel ulang di Seller Center). "
                           "Bila masih perlu diiklankan dan belum di iklan aktif, bisa muncul sebagai buat iklan baru.")
            if new_count:
                st.caption(f"{fmt_num(new_count)} produk dari katalog prediksi diusulkan **buat iklan tunggal** (belum di iklan aktif) untuk membantu menutup target.")
            st.caption(f"Dasar: audit katalog (prediksi + hasil iklan 2 bulan + stok + margin) · target ROAS {fmt_num(roas, 1)} (maks. 30). "
                       f"Layak iklan ≥ {fmt_idr(floor_sales)}/hari atau ≥ {fmt_num(floor_qty, 1)} unit/hari"
                       + (" · kuota produk baru diperluas karena kekurangan target" if gap_ads_daily >= 1_000_000 else "") + ". "
                       "Rapikan iklan jalan bila berguna; produk laris belum diiklan aktif ikut diusulkan. "
                       "Hanya iklan yang sedang berjalan yang diubah/dijeda di Seller Center.")

        # ---------------- D0: Konfirmasi (overlap will-pause, ROAS≤30, lantai budget) lalu unduh SC
        _step(n0 + 1, "Konfirmasi sebelum unduh SC", "· overlap will-pause · ROAS ≤ 30 · lantai 25rb/100rb")
        will_pause = _overlap_will_pause(acts, selection if isinstance(selection, pd.DataFrame) else pd.DataFrame())
        if will_pause.empty:
            st.caption("Tidak ada iklan yang diusulkan jeda/pause overlap pada rencana ini.")
        else:
            _box(
                "⚠️ Overlap → will-pause di Seller Center",
                f"<b>{fmt_num(len(will_pause))} baris</b> akan dijeda atau dibersihkan di SC saat Anda apply unduhan. "
                "Shopee juga menjeda GMV Max lama bila Anda buat baru untuk SKU yang sama — konfirmasi di SC sebelum publish.",
                "#b45309",
            )
            show_table(will_pause, column_config={"Alasan": st.column_config.TextColumn(width="large"),
                                                   "Iklan": st.column_config.TextColumn(width="medium")})
        guard_bits = [
            f"Target ROAS rencana <b>{fmt_num(min(float(roas), A.MAX_SHOPEE_ROAS), 1)}</b> (cap Shopee ≤ {fmt_num(A.MAX_SHOPEE_ROAS, 0)})",
            f"Lantai budget: tunggal ≥ <b>Rp {fmt_num(A.SHOPEE_MIN_SINGLE, 0)}</b> · grup ≥ <b>Rp {fmt_num(A.SHOPEE_MIN_GROUP, 0)}</b>",
            f"Periode {fmt_date(start)} – {fmt_date(end)} · learning s.d. {fmt_date(learning_exit)}",
        ]
        _box("Guardrails ekspor", "<br>".join(guard_bits), UP)

        if acts.empty:
            st.info("Tidak ada perubahan iklan yang disarankan (iklan dijeda/nonaktif tidak diisi ulang).")
        else:
            groups = [
                ("Naikkan budget", "⬆️", UP), ("Pisahkan jadi iklan tunggal", "⭐", UP), ("Buat iklan baru", "🆕", UP),
                ("Turunkan budget", "⬇️", DOWN), ("Jeda", "⏸️", DOWN), ("Pertahankan", "➖", "#64748b"),
            ]
            chips = []
            for name, icon, color in groups:
                part = acts.loc[acts["Tindakan"] == name]
                if part.empty:
                    continue
                delta = float(part["Perubahan/hari"].sum())
                chips.append(
                    f"<span style='border:1px solid #e2e8f0;border-radius:999px;padding:.25rem .75rem;font-size:var(--fs-sm);background:#fff'>{icon} <b>{name}</b> "
                    f"{fmt_num(len(part))} iklan" + (f" · <b style='color:{color}'>{'+' if delta > 0 else '−'}{fmt_idr(abs(delta))}/hari</b>" if abs(delta) >= 1 else "") + "</span>"
                )
            st.markdown("<div style='display:flex;flex-wrap:wrap;gap:.45rem;margin:.2rem 0 .6rem'>" + "".join(chips) + "</div>", unsafe_allow_html=True)
            with st.expander("Tabel budget per iklan (rincian)", expanded=False):
                f1, f2 = st.columns([1, 2])
                kind_pick = f1.segmented_control("Jenis iklan", ["Semua", "Produk tunggal", "Grup"], default="Semua", key="adt-kind") if hasattr(st, "segmented_control") else "Semua"
                act_names = [g[0] for g in groups if (acts["Tindakan"] == g[0]).any()]
                act_pick = f2.multiselect("Tindakan", act_names, key="adt-act", placeholder="Semua tindakan")
                shown = acts
                if kind_pick and kind_pick != "Semua":
                    shown = shown.loc[shown["Jenis"] == kind_pick]
                if act_pick:
                    shown = shown.loc[shown["Tindakan"].isin(act_pick)]
                cols = [c for c in ACT_COLS if c in shown.columns]
                batched_view(
                    len(shown), key="adt-units", noun="iklan",
                    render=lambda lo, hi: show_table(shown.iloc[lo:hi][cols], kinds=ACT_KINDS, max_height=10_000, row_height=35,
                                                     column_config={"Iklan": st.column_config.TextColumn(width="medium"), "Catatan": st.column_config.TextColumn(width="large"),
                                                                    "Target ROAS Shopee": st.column_config.Column(help="Maks. 30 di Seller Center")}),
                )
        unit_weeks = A.unit_weekly_budget(units, steps)
        if len(week_table) > 1:
            with st.expander("Jadwal budget per minggu (opsional)", expanded=False):
                st.caption("Tabel di atas = budget minggu 1; tiap Senin naik maks. 2× dari minggu sebelumnya.")
                show_table(week_table, kinds={"Budget/hari": "money", "Omzet iklan/hari": "money", "ROAS": "dec", "Tambahan omzet": "money", "Hari": "count", "Iklan aktif": "count"})
        stock_flags = int(acts["Catatan"].str.contains("stok kurang").sum()) if not acts.empty else 0
        loss_flags = int(acts["Catatan"].str.contains("margin minus").sum()) if not acts.empty else 0
        if stock_flags or loss_flags:
            notes = []
            if stock_flags:
                notes.append(f"{fmt_num(stock_flags)} iklan akan menjual lebih dari stok tersisa: ajukan restock/PO sekarang supaya omzet tambahan tidak tertahan.")
            if loss_flags:
                notes.append(f"{fmt_num(loss_flags)} iklan menambah omzet pada produk bermargin minus (dampak margin rencana {_signed(eff['dampak_margin'])}). "
                             "Tetap dijalankan karena prioritas target sales; tinjau harga setelah target aman.")
            _box("Catatan stok & margin (tidak menghentikan rencana)", "<br>".join(notes), "#b45309")

        _step(n0 + 2, "Unduh setelan Seller Center", "· setelah konfirmasi overlap & guardrails")
        st.caption("File berisi 2 sheet: Ringkas + Setelan Seller Center. Bukan dump analisa. Budget sudah menyesuaikan minimum "
                   f"Rp {fmt_num(A.SHOPEE_MIN_SINGLE, 0)}/hari (tunggal) dan Rp {fmt_num(A.SHOPEE_MIN_GROUP, 0)}/hari (grup); Target ROAS ≤ 30. "
                   "Iklan yang sudah jalan: pertahankan / ubah budget / jeda — jangan buat iklan baru untuk produk yang sama.")
        download_excel(setup_sheets, f"setelan_seller_center_{periode}.xlsx", key=f"xl-adt-setup-{key}",
                       label="Unduh setelan Seller Center")
        if not acts.empty:
            preview_cols = ["Urutan", "Langkah di Seller Center", "Iklan", "Jenis", "Kode produk", "Budget harian isi (Rp)",
                            "Target ROAS isi", "Pertahankan / ubah iklan yang sudah jalan"]
            setup_view = setup_sheets["Setelan Seller Center"]
            show_table(setup_view[preview_cols].head(40) if len(setup_view) > 40 else setup_view[preview_cols],
                       kinds={"Budget harian isi (Rp)": "money", "Target ROAS isi": "dec", "Urutan": "count"},
                       row_height=35, max_height=520,
                       column_config={"Langkah di Seller Center": st.column_config.TextColumn(width="large"),
                                      "Iklan": st.column_config.TextColumn(width="medium")})
            if len(setup_view) > 40:
                st.caption(f"Menampilkan 40 dari {fmt_num(len(setup_view))} baris — unduh Excel untuk semua langkah.")

        todo = [
            f"<b>Pick SKU & konfirmasi</b> — cek Top N Push, overlap will-pause, ROAS ≤ 30, lantai budget.",
            f"<b>Unduh setelan Seller Center</b> — isi Modal Harian & Target ROAS (≤ 30) persis angka di file; hanya iklan yang SEDANG BERJALAN yang diubah/dijeda. "
            "Iklan dijeda/nonaktif tidak perlu diaktifkan atau diisi ulang.",
            f"<b>{fmt_date(start)}</b> — kerjakan langkah berurutan di SC. Learning ~{C.LEARNING_DAYS} hari s.d. {fmt_date(learning_exit)}: jangan ubah ROAS/budget.",
            f"Budget min. Rp {fmt_num(A.SHOPEE_MIN_SINGLE, 0)} (tunggal) / Rp {fmt_num(A.SHOPEE_MIN_GROUP, 0)} (grup); naik maks. 2× per evaluasi.",
            "<b>Tiap Senin setelah learning</b> — unggah laporan & buka Pantau; sistem bisa mengusulkan end (konfirmasi, bukan silent).",
            "<b>Akhir bulan</b> — evaluasi di Laporan › Iklan; unggah target bulan berikutnya di Upload data › Target.",
        ]
        _box("Tindak lanjut", "<ol style='margin:0 0 0 1.1rem;padding:0'>" + "".join(f"<li>{t}</li>" for t in todo) + "</ol>", "#ee4d2d")
        with st.expander("Cara rencana dihitung"):
            explain([
                ("Iklan yang dihitung", "iklan produk tunggal dan iklan grup dari laporan iklan bulanan, plus usulan iklan produk tunggal baru untuk produk laris yang belum diiklankan"),
                ("Kurva respons", "omzet iklan harian = a·ln(1 + biaya/b) dari riwayat biaya vs omzet tiap iklan: makin besar budget, tambahan omzetnya makin kecil"),
                ("Target ROAS", "ROAS rata-rata seluruh iklan di rencana (total omzet iklan ÷ total biaya), sama dengan arti Target ROAS di Shopee"),
                ("Urutan", "1) budget dipindah dari iklan dengan tambahan omzet per Rp terendah ke yang tertinggi selama omzet naik, "
                           "2) bila melebihi budget atau ROAS rata-rata di bawah target, iklan paling tidak efektif dipangkas, "
                           "3) sisa budget diberikan ke iklan paling efektif sampai kekurangan omzet tertutup atau ROAS rata-rata menyentuh target"),
                ("Efisiensi minimum", f"tiap tambahan Rp 1 biaya iklan harus kembali ≥ Rp {fmt_num(A.MIN_MARGINAL, 0)} omzet iklan; iklan yang Rp terakhirnya di bawah itu "
                                  "dipangkas (lalu dijeda bila rata-ratanya pun di bawah itu). Sisa budget yang tidak bisa dipakai efisien tidak dibelanjakan"),
            ("Pengecualian", "produk di daftar pengecualian (pilih produk atau kata kunci nama/merek) dikeluarkan dari semua iklan"),
            ("Target ROAS Shopee per iklan", "ROAS rata-rata iklan itu pada budget usulan, maks. 30; boleh berbeda antar iklan selama rata-ratanya ≥ target"),
                ("Batas per iklan", "budget harian naik maks. 2× atau turun ke ≥ ½ dari sekarang per minggu (selain dijeda), iklan baru maks. Rp 100 rb/hari: "
                                    "di luar batas itu perlindungan ROAS Shopee mati"),
                ("Siklus", "rencana dibagi per minggu: budget tiap iklan boleh naik maks. 2× dari minggu sebelumnya, jadi budget bisa naik bertahap sampai akhir bulan; "
                           "pelaksanaan dievaluasi tiap hari dari laporan iklan terbaru"),
                ("Pemilihan produk", "per produk: ROAS & porsi omzet di grup (2 bulan terakhir), prediksi omzet dari analisa, dan stok"),
                ("Satu alur", "pemilihan produk dihitung dulu, lalu susunan iklan diubah (anggota keluar/dijeda dilepas, andalan dipisah jadi iklan tunggal, "
                              "produk laris belum diiklankan dibuatkan iklan), baru budget dibagi. Usulan iklan tunggal yang tidak kebagian budget dikembalikan ke grup"),
                ("Budget sebulan", "budget yang diisi = total sebulan; biaya yang sudah keluar dibaca dari laporan iklan keseluruhan (diprorata ke tanggal 1 s.d. "
                                   "data terakhir), sisanya dibagi rata ke hari tersisa"),
                ("Proyeksi & rekomendasi", "kurva respons toko: sales bersih bulanan = s0 + a·ln(1 + biaya iklan bulanan / b) dari riwayat bulan penuh "
                                           "(biaya iklan keseluruhan vs sales bersih). Tambahan = selisih sales pada laju biaya baru vs laju biaya sekarang, "
                                           "dikali porsi hari tersisa. Biaya yang dipakai = biaya yang benar-benar dibelanjakan rencana per iklan (sesudah pemilihan produk, "
                                       "pengecualian, batas naik 2×/minggu, dan efisiensi minimum), bukan budget nominal; budget yang tidak terserap tidak "
                                       "menambah proyeksi. Opsi rekomendasi: laju sekarang, maksimal yang efisien, hemat biaya, dan 100% target bila masih efisien"),
                ("Rencana per iklan", "sisa budget dibagi ke iklan dengan kurva tiap iklan (omzet diklaim Shopee), dibatasi stok dan batas naik 2× per minggu; "
                                      "dipakai untuk Target ROAS Shopee dan budget per iklan, bukan untuk proyeksi target"),
                ("Stok", "tambahan omzet tiap iklan maks. ruang stok produknya sampai akhir bulan (stok − prediksi − SS); iklan yang tertahan stok ditandai untuk restock"),
                ("Margin", "ikut menentukan prioritas budget: tambahan omzet dinilai × bobot margin (margin positif 1,0–1,6; margin tidak diketahui 1,0; "
                       "margin minus 0,55 bila produk laku banyak, 0,35 bila tidak). Iklan margin minus tetap boleh untuk mengejar sales/qty, tetapi dipangkas "
                       "lebih dulu dan butuh hasil lebih tinggi (batas efisiensi Rp 5 ÷ bobot)"),
                ("Proyeksi tanpa perubahan", "sales bersih aktual s.d. hari penuh terakhir + prediksi per tanggal berpola untuk sisa bulan "
                                             "(sama dengan Pantauan harian dan Kalkulator biaya)"),
            ])
        _not_advertised(products, selection, key="adt-noads", periode=periode)
        if features is not None:
            def _to_target(campaign: dict) -> None:
                payload = {"target_roas": roas, "budget_sisa": budget, "hari": period_days, "strategi": "Kejar target", "minggu": start.isoformat(),
                           "total_harian": used_daily, "campaign": campaign["id"]}
                features.replace(
                    "sales_target",
                    [{"periode": periode, "target_sales_bersih": target, "margin_min_pct": float(saved.get("margin_min_pct", 0) or 0), "strategi": "Kejar target",
                      "budget_json": json.dumps(payload, default=float), "set_by": username}],
                    keys=["periode"], username=username, action="kirim:rencana_iklan",
                )
                bump(st.session_state)
                st.session_state["adt-view-next"] = VIEW_TRACK

            keep = selection.loc[selection["Saran"] != "Sudah di iklan lain"] if not selection.empty else selection
            cmp.save_controls(
                "iklan", features=features, today=today, start=start, end=end, cur=cur, can_edit=can_edit, username=username, after_save=_to_target,
                default_name=f"Iklan {month_name} · {source.split(' · ')[-1]} · ROAS {fmt_num(roas, 1)} · {fmt_date(start)} – {fmt_date(end)}",
                payload={"lifecycle": C.EXPORTED,
                         "learning_days": C.LEARNING_DAYS,
                         "learning_exit": learning_exit.isoformat(),
                         "setelan": {"periode_target": periode, "target": target, "roas": roas, "budget": budget, "budget_bulan": month_budget, "terpakai": spent, "budget_harian": budget_daily, "biaya_harian_rencana": eff["biaya_total"] / max(run_days, 1),
                                     "budget_rencana_harian": used_daily, "proyeksi": final, "capaian": reach, "hari_hitung": run_days, "daya_dorong": lift,
                                     "strategi_budget_tetap": fixed_used, "sumber": source, "mtd": mtd, "mtd_produk": mtd_produk,
                                     "data_sampai": last.isoformat(), "hari_sisa": days_left,
                                     "proyeksi_tanpa": projection, "roas_otomatis": auto, "efisiensi_min": mm},
                         "kalender_harian": cmp.records_of(fixed["kalender"]) if fixed_used else [],
                         "jadwal_minggu": cmp.records_of(week_table),
                         "iklan_minggu": cmp.records_of(unit_weeks),
                         "baseline": A.month_totals(base_units),
                         "iklan": cmp.records_of(acts.reindex(columns=[*ACT_COLS, "key"])) if not acts.empty else [],
                         "produk": cmp.records_of(keep)},
            )

    # ================= FITUR KHUSUS · setelan Anda (berdiri sendiri)
    if view == VIEW_CUSTOM:
        store_key, cache_key = f"iklan-setelan:{periode}", f"adt-submitted-{periode}"
        if cache_key not in st.session_state:
            try:
                st.session_state[cache_key] = features.get_json(store_key, None) if features is not None else None
            except Exception:
                st.session_state[cache_key] = None
        submitted = st.session_state.get(cache_key) or None
        kt, kb, km, kr = (f"adt-f-target-{periode}", f"adt-f-budget-{periode}", f"adt-f-mode-{periode}", f"adt-f-roas-{periode}")
        if st.session_state.pop(f"adt-f-reset-{periode}", False) or kt not in st.session_state:
            src = submitted or {}
            st.session_state[kt] = angka(round(float(src.get("target") or goals.target_sales)))
            st.session_state[kb] = angka(round(float(src.get("budget_bulan") or pace_total)))
            st.session_state[km] = "Saya tentukan" if src.get("roas_mode") == "manual" else "Diatur sistem"
            st.session_state[kr] = min(float(src.get("roas") or current_roas or 8.0), A.MAX_SHOPEE_ROAS) if (src.get("roas") or current_roas) else 8.0
        st.markdown(FIXED_CSS, unsafe_allow_html=True)
        with st.container(key="adt-fixed"):
            st.markdown(
                "<div style='display:flex;align-items:center;gap:.6rem;flex-wrap:wrap'>"
                "<span style='background:#ee4d2d;color:#fff;border-radius:999px;padding:.15rem .7rem;font-size:var(--fs-xs);font-weight:800;letter-spacing:.03em'>FITUR KHUSUS</span>"
                f"<span style='font-weight:800;font-size:var(--fs-lg);color:#0f172a'>🎛️ Setelan Anda · {html.escape(month_name)}</span></div>"
                "<div style='color:#475569;font-size:var(--fs-sm);margin:.3rem 0 .6rem'>Isi budget iklan <b>sebulan penuh</b> sesuai yang Anda sediakan, boleh lebih besar, "
                "lebih kecil, atau sama dengan laju sekarang, lalu klik <b>Hitung rencana</b>. Setelan yang dikirim menjadi acuan perhitungan. "
                "Biaya iklan yang sudah keluar dibaca otomatis dari laporan iklan; sistem membagi <b>sisa budget</b> ke hari tersisa, lalu menilai sendiri "
                "Target ROAS, produk yang diiklankan, budget per iklan, dan sales yang dihasilkan. Fitur ini berdiri sendiri: tidak memakai dan tidak mengubah Rekomendasi sistem.</div>",
                unsafe_allow_html=True,
            )
            st.markdown(f"<div class='field-hint'>Biaya iklan {month_name}: {spent_text} · iklan berjalan sekarang {fmt_num(len(running))} iklan "
                        f"{fmt_idr(cost_now)}/hari; bila laju ini diteruskan, budget sebulan ≈ <b>{fmt_idr(pace_total)}</b>.</div>", unsafe_allow_html=True)
            with st.form(f"adt-form-{periode}", border=False):
                c1, c2, c3 = st.columns([1.1, 1.1, 1.2])
                c1.text_input(f"Target sales {month_name} (Rp)", key=kt,
                              help="Bawaan dari Upload data › Target sales bulanan (sales bersih). Ubah untuk mencoba target lain.")
                c2.text_input(f"Budget iklan {month_name} · total sebulan (Rp)", key=kb,
                              help="Total budget iklan produk tunggal + grup untuk sebulan penuh, termasuk yang sudah terpakai. "
                                   "Sisa budget = isian ini − biaya iklan yang sudah keluar (laporan iklan keseluruhan).")
                with c3:
                    st.radio("Target ROAS", ["Diatur sistem", "Saya tentukan"], key=km, horizontal=True,
                             help="Diatur sistem = Target ROAS dipilih agar sisa budget menghasilkan omzet iklan terbesar. "
                                  "Saya tentukan = pakai angka di bawah (maks. 30, batas perlindungan ROAS Shopee).")
                    st.number_input("Target ROAS bila Saya tentukan", min_value=1.0, max_value=A.MAX_SHOPEE_ROAS, step=0.5, key=kr)
                go = st.form_submit_button("Hitung rencana", type="primary")
            if go:
                new = {"target": float(parse_rupiah(st.session_state.get(kt))), "budget_bulan": float(parse_rupiah(st.session_state.get(kb))),
                       "roas_mode": "manual" if st.session_state.get(km) == "Saya tentukan" else "auto", "roas": float(st.session_state.get(kr) or 8.0),
                       "dikirim": pd.Timestamp.now().strftime("%d/%m/%Y %H:%M"), "oleh": username}
                if new["target"] <= 0 or new["budget_bulan"] <= 0:
                    st.error("Target sales dan budget iklan sebulan harus lebih dari 0.")
                else:
                    st.session_state[cache_key] = new
                    if features is not None and can_edit:
                        try:
                            features.set_json(store_key, new, username=username)
                        except Exception:
                            pass
                    st.session_state[f"adt-f-reset-{periode}"] = True
                    st.rerun()
            if submitted is None:
                st.info("Belum ada setelan yang dikirim untuk bulan ini. Isi budget iklan sebulan lalu klik **Hitung rencana**.")
                return
            typed = (parse_rupiah(st.session_state.get(kt)), parse_rupiah(st.session_state.get(kb)))
            dirty = typed != (round(submitted["target"]), round(submitted["budget_bulan"]))
            st.markdown(f"<div class='field-hint'>Acuan perhitungan: setelan dikirim {html.escape(str(submitted.get('oleh') or '-'))} "
                        f"{html.escape(str(submitted.get('dikirim') or ''))} · target {fmt_idr(submitted['target'])} · budget sebulan {fmt_idr(submitted['budget_bulan'])} · "
                        f"Target ROAS {'diatur sistem' if submitted.get('roas_mode') != 'manual' else fmt_num(submitted.get('roas'), 1)}"
                        + (" · <b style='color:#b45309'>angka di kotak belum dikirim, klik Hitung rencana</b>" if dirty else "") + "</div>", unsafe_allow_html=True)
            result_slot = st.container()

        target, month_budget = float(submitted["target"]), float(submitted["budget_bulan"])
        auto = submitted.get("roas_mode") != "manual"
        if not has_ads or not units:
            st.info("Laporan iklan (grup / keseluruhan) belum diunggah atau tidak ada iklan produk tunggal & grup: rencana iklan butuh riwayat biaya & omzet per iklan.")
            return
        remaining = max(month_budget - spent, 0.0)
        budget_daily = remaining / days_left
        with st.spinner("Membagi sisa budget ke iklan dan memilih Target ROAS..."):
            roas = best_roas(budget_daily, target - projection, fine=True) if auto else min(float(submitted.get("roas") or 8.0), A.MAX_SHOPEE_ROAS)
        final, extra, by_curve, effective = project(target, month_budget, roas)
        used_daily_eff = max(effective - spent, 0.0) / days_left
        reach = final / target * 100
        with result_slot:
            k = st.columns(4)
            base_daily = spent_daily if by_curve else cost_now
            card(k[0], "Proyeksi sales bersih akhir bulan", fmt_idr(final),
                 hint=f"<b style='color:{_tone(final >= target)}'>{fmt_pct(reach, 1)}</b> dari target {fmt_idr(target)} · seluruh penjualan toko 1–{month_days} "
                      f"{month_label(periode)} (dari iklan & non-iklan, setelah batal/Belum Bayar/retur), dengan budget iklan setelan ini")
            card(k[1], "Efek budget iklan setelan", _signed(extra),
                 hint=(f"biaya dibelanjakan {fmt_idr(used_daily_eff)}/hari vs laju iklan rata-rata 1–{last.day} {month_label(periode)} {fmt_idr(base_daily)}/hari: "
                       + (f"<b style='color:{UP}'>budget lebih besar → sales naik</b>" if extra > 0 else f"<b style='color:{DOWN}'>budget lebih kecil → sales turun</b>" if extra < 0 else "sama")))
            card(k[2], "Sisa budget", fmt_idr(remaining), hint=f"budget {fmt_idr(month_budget)} − terpakai {fmt_idr(spent)} · ≈ {fmt_idr(budget_daily)}/hari × {days_left} hari · "
                 + (f"dibelanjakan efisien {fmt_idr(used_daily_eff)}/hari, <b style='color:{UP}'>hemat {fmt_idr(remaining - used_daily_eff * days_left)}</b>"
                    if remaining - used_daily_eff * days_left > 500_000 else "terserap penuh"))
            card(k[3], "Target ROAS Shopee", fmt_num(roas, 1),
                 hint=("dipilih sistem: omzet iklan terbesar dengan sisa budget" if auto else "ditentukan Anda") + f" · ROAS iklan sekarang {fmt_num(current_roas, 1)}")
            ok = final >= target - 1
            st.markdown(f"<div style='background:{UP if ok else DOWN};color:#fff;border-radius:10px;padding:.5rem .8rem;font-weight:700;margin-top:.4rem'>"
                        + (f"Dengan setelan ini target {month_name} tercapai ({fmt_pct(reach, 1)})." if ok else
                           f"Dengan setelan ini proyeksi {fmt_pct(reach, 1)} target · kurang {fmt_idr(target - final)}.") + "</div>", unsafe_allow_html=True)
            ratio, profit = economics(final, effective)
            econ = []
            if ratio == ratio:
                okr = ratio >= M.SHOPEE_MIN_AD_PCT - 0.05
                econ.append(f"Biaya iklan sebulan ≈ <b style='color:{UP if okr else DOWN}'>{fmt_pct(ratio, 1)}</b> sales bruto proyeksi "
                            + ("(✓ memenuhi syarat minimum Shopee 3%)" if okr else "(⚠️ di bawah syarat minimum Shopee 3%: benefit program bisa hilang)"))
            if profit is not None:
                econ.append(f"estimasi kontribusi sesudah iklan <b style='color:{_tone(profit >= 0)}'>{_signed(profit)}</b> "
                            f"(kontribusi sebelum iklan {fmt_pct(contrib_rate * 100, 1)} dari file margin)")
            if econ:
                st.markdown("<div class='field-hint' style='margin-top:.4rem'>" + " · ".join(econ) + "</div>", unsafe_allow_html=True)

        _step(1, "Evaluasi budget Anda", f"· budget sebulan vs biaya iklan yang sudah keluar 1–{last.day} {month_label(periode)}")
        k = st.columns(4)
        card(k[0], "Budget sebulan (setelan)", fmt_idr(month_budget), hint=f"dibanding laju sekarang {fmt_idr(pace_total)}: "
             + (f"<b style='color:{UP}'>lebih besar {fmt_idr(month_budget - pace_total)}</b>" if month_budget > pace_total * 1.01 else
                f"<b style='color:{DOWN}'>lebih kecil {fmt_idr(pace_total - month_budget)}</b>" if month_budget < pace_total * 0.99 else "sama"))
        card(k[1], "Sudah terpakai", fmt_idr(spent), hint=(f"{fmt_pct(spent / month_budget * 100 if month_budget else 0, 0)} budget pada {fmt_pct(last.day / month_days * 100, 0)} hari · "
                                                           f"omzet diklaim iklan {fmt_idr(spend['omzet'])} (ROAS {fmt_num(spend['omzet'] / spent if spent else 0, 1)})" if spent_days else "laporan iklan bulan ini belum ada"))
        card(k[2], "Sisa per hari", fmt_idr(budget_daily), hint=f"{days_left} hari tersisa · iklan berjalan sekarang {fmt_idr(cost_now)}/hari "
             + (f"(<b style='color:{UP}'>+{fmt_pct((budget_daily / cost_now - 1) * 100, 0)}</b>)" if cost_now and budget_daily > cost_now * 1.01 else
                f"(<b style='color:{DOWN}'>−{fmt_pct((1 - budget_daily / cost_now) * 100, 0)}</b>)" if cost_now and budget_daily < cost_now * 0.99 else ""))
        gross = float(outlook.get("mtd_bruto") or 0.0)
        card(k[3], "Biaya iklan % sales bersih · bruto",
             (fmt_pct(spent / mtd * 100, 1) if mtd > 0 else "–") + " · " + (fmt_pct(spent / gross * 100, 1) if gross > 0 else "–"),
             hint=f"s.d. {fmt_date(last)}: sales bersih {fmt_idr(mtd)} · sales bruto {fmt_idr(gross)}. Bruto = semua pesanan masuk (termasuk batal, Belum Bayar, retur) "
                    "yang sudah ikut menyerap biaya iklan; % bersih lebih tinggi karena sebagian pesanan itu tidak jadi uang.")
        if spent > month_budget:
            _box("Budget sebulan sudah terlampaui", f"Biaya iklan yang sudah keluar {fmt_idr(spent)} melebihi setelan {fmt_idr(month_budget)} "
                 f"({fmt_idr(spent - month_budget)}). Sisa budget dihitung 0: rencana di bawah menjeda iklan dan proyeksi turun. Naikkan budget sebulan bila iklan tetap ingin berjalan.", DOWN)

        _step(2, "Hasil setelan Anda", "· cara proyeksi sales bersih akhir bulan dihitung")
        st.markdown(_progress_bar(mtd, projection - mtd, extra, target), unsafe_allow_html=True)
        base_daily = spent_daily if by_curve else cost_now
        rest_from = fmt_date(last + timedelta(days=1))
        steps_tbl = pd.DataFrame([
            {"Komponen": f"Aktual sales bersih 1–{last.day} {month_label(periode)}", "Nilai": mtd,
             "Keterangan": "sudah terjadi (data pesanan)"},
            {"Komponen": f"Prediksi sales bersih {rest_from} – {fmt_date(month_end)}", "Nilai": projection - mtd,
             "Keterangan": f"{days_left} hari, iklan tetap {fmt_idr(base_daily)}/hari (rata-rata 1–{last.day}); model prediksi"},
            {"Komponen": "Efek budget iklan setelan", "Nilai": extra,
             "Keterangan": f"biaya dibelanjakan {fmt_idr(used_daily_eff)}/hari (dari sisa budget {fmt_idr(budget_daily)}/hari) vs {fmt_idr(base_daily)}/hari · "
                           + ("kurva respons toko" if by_curve else "rencana per iklan")},
            {"Komponen": "Proyeksi sales bersih akhir bulan", "Nilai": final, "Keterangan": f"{fmt_pct(reach, 1)} target"},
            {"Komponen": f"Target {month_label(periode)}", "Nilai": target, "Keterangan": "Upload data › Target sales bulanan" if target == goals.target_sales else "diisi di setelan"},
            {"Komponen": "Kurang dari target" if final < target else "Lebih dari target", "Nilai": abs(target - final), "Keterangan": ""},
        ])
        show_table(steps_tbl, kinds={"Nilai": "money"}, bold_label=("Proyeksi sales bersih akhir bulan",), row_height=35,
                   column_config={"Komponen": st.column_config.TextColumn(width=300), "Nilai": st.column_config.Column(width=160),
                                  "Keterangan": st.column_config.TextColumn(width=760)})
        st.caption("Cara membaca: proyeksi = aktual + prediksi sisa bulan + efek budget iklan. Prediksi sisa bulan sudah memuat iklan pada laju rata-rata bulan ini, "
                   "jadi efek budget hanya mengukur selisihnya: positif bila sisa budget per hari lebih besar dari laju itu (sales bertambah), "
                   "negatif bila lebih kecil (iklan dikurangi, sebagian sales yang biasa datang dari iklan hilang).")
        plan_section(3, target=target, month_budget=month_budget, roas=roas, auto=auto, final=final, extra=extra,
                     source="Fitur khusus · setelan Anda", key="custom")
        return

    # ================= REKOMENDASI SISTEM (berdiri sendiri, memakai target bulan dari Upload data)
    target = float(goals.target_sales)
    if target <= 0:
        _box("Target bulan ini belum ada", f"Unggah target {month_name} di Upload data › Target sales bulanan.", DOWN)
        return
    gap = target - projection
    _step(1, "Evaluasi kondisi saat ini", f"· aktual 1–{last.day} {month_label(periode)} + prediksi sisa bulan dengan laju iklan sekarang")
    st.markdown(_progress_bar(mtd, projection - mtd, 0.0, target), unsafe_allow_html=True)
    k = st.columns(4)
    card(k[0], f"Target {month_label(periode)}", fmt_idr(target), hint=f"sumber: {html.escape(goals.target_source)}")
    card(k[1], "Aktual sales bersih", fmt_idr(mtd), hint=f"<b style='color:{_tone(mtd / target >= last.day / month_days)}'>{fmt_pct(mtd / target * 100, 1)}</b> target "
                                                        f"pada {fmt_pct(last.day / month_days * 100, 0)} hari")
    card(k[2], "Proyeksi tanpa perubahan", fmt_idr(projection), hint=f"aktual + prediksi sisa bulan dengan laju iklan rata-rata {fmt_idr(spent_daily)}/hari · <b style='color:{_tone(gap <= 0)}'>{fmt_pct(projection / target * 100, 1)}</b> target · "
                                                                      + (f"kurang {fmt_idr(gap)}" if gap > 0 else f"lebih {fmt_idr(-gap)}"))
    gross = float(outlook.get("mtd_bruto") or 0.0)
    card(k[3], "Biaya iklan terpakai", fmt_idr(spent), hint=(f"{fmt_idr(spent_daily)}/hari · {fmt_pct(spent / mtd * 100 if mtd else 0, 1)} sales bersih · "
                                                             f"{fmt_pct(spent / gross * 100 if gross else 0, 1)} sales bruto · omzet diklaim iklan {fmt_idr(spend['omzet'])} "
                                                             f"(ROAS {fmt_num(spend['omzet'] / spent if spent else 0, 1)})" if spent_days else "laporan iklan bulan ini belum ada"))
    notes = [f"Iklan berjalan sekarang {fmt_num(len(running))} iklan, {fmt_idr(cost_now)}/hari, ROAS {fmt_num(sales_now / cost_now if cost_now else 0, 1)}; "
             f"bila diteruskan, biaya iklan sebulan ≈ {fmt_idr(pace_total)}."]
    _sub0 = _submitted_setting(features, periode)
    notes.append(f"Budget iklan sebulan yang Anda isi di Fitur khusus: <b>{fmt_idr(float(_sub0['budget_bulan']))}</b> (opsi A memakai angka ini)."
                 if _sub0 else f"Belum ada budget {month_name} yang dikirim di Fitur khusus: isi di sana agar opsi pertama memakai budget Anda.")
    if spent_days and cost_now:
        diff = cost_now / spent_daily - 1 if spent_daily else 0
        if abs(diff) > 0.1:
            notes.append(f"Laju iklan sekarang {'lebih tinggi' if diff > 0 else 'lebih rendah'} {fmt_pct(abs(diff) * 100, 0)} dari rata-rata biaya harian 1–{last.day} "
                         f"({fmt_idr(spent_daily)}/hari).")
    if curve is not None:
        notes.append(f"Kurva respons toko ({html.escape(curve.source)}): pada laju sekarang tiap tambahan Rp 1 iklan menambah ±{fmt_num(curve.marginal(cost_now * month_days), 1)} "
                     "sales bersih, makin kecil saat budget makin besar.")
    else:
        notes.append("Riwayat iklan bulanan belum cukup (minimal 3 bulan penuh) untuk kurva respons toko: proyeksi opsi memakai rencana per iklan.")
    notes.append(f"Kesimpulan: {'target sudah terkejar dengan laju sekarang — opsi di bawah mencari budget paling hemat' if gap <= 0 else f'perlu tambahan {fmt_idr(gap)} sales bersih dalam {days_left} hari ({fmt_idr(gap / days_left)}/hari)'}.")
    st.markdown("<div class='field-hint'>" + "<br>".join(notes) + "</div>", unsafe_allow_html=True)
    if curve is not None and contrib_rate is not None:
        m_now = curve.marginal(cost_now * month_days) if cost_now > 0 else curve.marginal(spent_daily * month_days)
        need_rate = M.break_even_contrib(m_now)
        if M.ads_deepens_loss(contrib_rate, m_now):
            _box("💰 Titik impas iklan · jangan kejar target dengan biaya gila",
                 f"Pada laju sekarang, tambahan Rp 1 iklan menambah ±Rp {fmt_num(m_now, 1)} sales bersih. Agar tambahan itu tidak menambah rugi, kontribusi "
                 f"produk (margin kotor − potongan Shopee, sebelum iklan) perlu ≥ <b>{fmt_pct(need_rate * 100, 0)}</b>; rata-rata produk yang diprediksi "
                 f"terjual sekarang <b>{fmt_pct(contrib_rate * 100, 1)}</b>. "
                 "<b>Opsi utama di bawah memilih jalur yang estimasi kontribusinya paling baik</b> (bukan sales tertinggi dengan spend besar). "
                 "Strategi biaya/omzet: jadikan iklan tunggal hanya andalan bermargin positif, sisanya di grup hemat, keluarkan yang margin minus / ROAS lemah. "
                 "Perbaiki harga produk rugi sebelum menaikkan budget.", DOWN)
    if not has_ads or not units:
        st.info("Laporan iklan (grup / keseluruhan) belum diunggah atau tidak ada iklan produk tunggal & grup: opsi iklan butuh riwayat biaya & omzet per iklan.")
        return

    step2_note = ("· pace picker: rata-rata / efisien / kejar — opsi utama sadar margin"
                  if contrib_rate is not None and curve is not None and M.ads_deepens_loss(
                      contrib_rate, curve.marginal(cost_now * month_days) if cost_now > 0 else curve.marginal(spent_daily * month_days))
                  else "· pilih pace dulu; rincian produk & unduh SC di bawah")
    _step(2, "Pilih pace budget", step2_note)
    with st.spinner("Menghitung opsi..."):
        _sub = _submitted_setting(features, periode)
        opts, need_info = _rec_options(target=target, projection=projection, spent=spent, cost_now=cost_now, days_left=days_left, month_days=month_days, run_days=run_days,
                            pace_total=pace_total, curve=curve, spent_daily=spent_daily, best_roas=best_roas, option=option, project=project, units=base_units,
                            factor=factor, month_name=month_name, economics=economics, ratio_budget=ratio_budget,
                            user_budget=float(_sub["budget_bulan"]) if _sub else None,
                            user_note=f"dikirim {_sub.get('oleh', '')} {_sub.get('dikirim', '')}".strip() if _sub else "",
                            contrib_rate=contrib_rate)
    if not opts:
        st.info("Belum ada opsi budget yang bisa dihitung dari data iklan saat ini.")
        return

    def _pace_of(opt: dict) -> str:
        name = str(opt.get("nama") or "").lower()
        if "rata-rata" in name or "kembalikan" in name:
            return "rata-rata"
        if "efisien" in name or "hemat" in name or "minimum shopee" in name:
            return "efisien"
        if "100%" in name or "kejar" in name or "target" in name:
            return "kejar"
        if opt.get("utama"):
            return "efisien" if (opt.get("laba") is not None and float(opt["laba"]) >= 0) else "rata-rata"
        if "budget anda" in name:
            return "kejar"
        if "laju" in name:
            return "kejar"
        return "efisien"

    for o in opts:
        o["pace"] = _pace_of(o)
    pace_order = ("rata-rata", "efisien", "kejar")
    pace_labels = {
        "rata-rata": ("Rata-rata bulan ini", "Kembalikan burn ke histori; aman saat spike."),
        "efisien": ("Efisien / sadar margin", "Maksimal yang masih efisien; utamakan kontribusi."),
        "kejar": ("Kejar target", "Budget Anda / laju sekarang / 100% target bila aman."),
    }
    by_pace: dict[str, list] = {p: [] for p in pace_order}
    for o in opts:
        by_pace.setdefault(o["pace"], []).append(o)
    # Default pace = yang memuat opsi utama, else efisien
    default_pace = next((o["pace"] for o in opts if o.get("utama")), "efisien")
    if default_pace not in pace_order:
        default_pace = "efisien"
    if st.session_state.get("adt-pace") not in pace_order:
        st.session_state["adt-pace"] = default_pace
    pace_pick = st.radio(
        "Pace budget",
        list(pace_order),
        format_func=lambda p: f"{pace_labels[p][0]} · {len(by_pace.get(p) or [])} opsi",
        key="adt-pace",
        horizontal=True,
        help="Tiga jalur: rata-rata · efisien · kejar. Detail angka di expander.",
    )
    st.caption(pace_labels[pace_pick][1])
    pace_opts = by_pace.get(pace_pick) or opts
    # Kartu ringkas per opsi dalam pace — bukan tabel multi-metrik di muka
    cols = st.columns(min(len(pace_opts), 3) or 1)
    for i, o in enumerate(pace_opts[:3]):
        with cols[i % len(cols)]:
            badge = " · saran utama" if o.get("utama") else ""
            st.markdown(
                f"<div style='border:1px solid #e2e8f0;border-radius:12px;padding:.7rem .85rem;background:#fff;margin:.2rem 0'>"
                f"<div style='font-weight:800'>{html.escape(o['nama'])}{badge}</div>"
                f"<div style='margin-top:.35rem;font-size:var(--fs-sm);line-height:1.45;color:#334155'>"
                f"Budget <b>{fmt_idr(o['budget'])}</b> · efektif {fmt_idr(o['efektif'])}<br>"
                f"Proyeksi <b>{fmt_pct(o['proyeksi'] / target * 100, 1)}</b> target"
                + (f" · kontribusi {_signed(o['laba'])}" if o.get("laba") is not None else "")
                + f"</div></div>",
                unsafe_allow_html=True,
            )
    with st.expander("Tabel lengkap semua opsi (metrik)", expanded=False):
        table_opts = pd.DataFrame([{
            "Pace": o["pace"], "Opsi": o["nama"], "Asal angka budget": o["asal"],
            "Budget sebulan": o["budget"], "Biaya efektif sebulan": o["efektif"],
            "Hemat": max(o["budget"] - o["efektif"], 0.0), "Sisa/hari": o["harian"], "Target ROAS": o["roas"],
            "Proyeksi sales bersih akhir bulan": o["proyeksi"], "% target": o["proyeksi"] / target * 100,
            "Efek budget iklan": o["tambahan"], "Biaya iklan % sales bruto": o["rasio"],
            "Estimasi kontribusi": o["laba"], "Yang dilakukan": o["aksi"],
        } for o in opts])
        show_table(
            table_opts,
            kinds={"Budget sebulan": "money", "Biaya efektif sebulan": "money", "Hemat": "money", "Sisa/hari": "money",
                   "Target ROAS": "dec", "Proyeksi sales bersih akhir bulan": "money", "% target": "pct",
                   "Efek budget iklan": "money", "Biaya iklan % sales bruto": "pct", "Estimasi kontribusi": "money"},
            column_config={"Opsi": st.column_config.TextColumn(width="medium"),
                           "Asal angka budget": st.column_config.TextColumn(width="large"),
                           "Yang dilakukan": st.column_config.TextColumn(width="large")},
            row_height=35,
        )
    top = max(opts, key=lambda o: o["proyeksi"])
    best_profit = max((o for o in opts if o["laba"] is not None), key=lambda o: o["laba"], default=None)
    if need_info.get("underwater") and need_info.get("need"):
        _box("🎯 Target omzet vs margin",
             f"Kurva respons toko memperkirakan 100% target butuh biaya iklan ±<b>{fmt_idr(need_info['need'])}</b> sebulan, "
             "tetapi kontribusi rata-rata toko di bawah titik impas: mengejar angka itu dengan iklan "
             f"<b>memperbesar rugi</b>. Proyeksi omzet tertinggi {fmt_idr(top['proyeksi'])} "
             f"({fmt_pct(top['proyeksi'] / target * 100, 1)} target)"
             + (f"; jalur kontribusi terbaik ≈ {_signed(best_profit['laba'])} dengan biaya efektif {fmt_idr(best_profit['efektif'])}."
                if best_profit is not None else ".")
             + " Tutup sisa gap dengan Flash sale, Exposure, restock produk laris bermargin positif, atau sesuaikan target/harga — "
             "bukan dengan menaikkan budget tanpa seleksi.", DOWN)
    elif need_info["gap"] > 0 and top["proyeksi"] < target - 1:
        lack = target - top["proyeksi"]
        need_txt = (f"Menurut kurva respons toko, 100% target butuh biaya iklan ±<b>{fmt_idr(need_info['need'])}</b> sebulan, tetapi iklan yang ada + usulan "
                    f"iklan baru hanya bisa membelanjakan efisien ±<b>{fmt_idr(need_info['max_efisien'])}</b>. " if need_info["need"] else "")
        _box("🎯 100% target tidak terkejar dengan iklan secara efisien",
             need_txt + f"Proyeksi terbaik {fmt_idr(top['proyeksi'])} ({fmt_pct(top['proyeksi'] / target * 100, 1)}): masih kurang <b>{fmt_idr(lack)}</b>. "
             "Menambah budget di atas batas efisien hanya membuang biaya (tiap tambahan Rp 1 kembali kurang dari "
             f"Rp {fmt_num(A.MIN_MARGINAL, 0)} omzet iklan). Tutup kekurangan dengan cara lain: Flash sale toko, Exposure media sosial, "
             "restock produk laris yang stoknya menahan penjualan, atau sesuaikan target.", "#b45309")
    names = [o["nama"] for o in pace_opts] or [o["nama"] for o in opts]
    best = next((o["nama"] for o in pace_opts if o.get("utama")), names[0])
    if st.session_state.get("adt-rec-pick") not in names:
        st.session_state["adt-rec-pick"] = best
    pick = st.radio("Opsi yang ingin dirinci", names, key="adt-rec-pick", horizontal=True)
    chosen = next(o for o in opts if o["nama"] == pick)
    chosen_color = UP if (chosen["laba"] is not None and chosen["laba"] >= 0) or chosen["proyeksi"] >= target - 1 else "#b45309"
    if chosen.get("utama"):
        badge = " · saran utama sistem"
    else:
        badge = ""
    _box(f"💡 {html.escape(chosen['nama'])}{badge} · proyeksi {fmt_pct(chosen['proyeksi'] / target * 100, 1)} target"
         + (f" · kontribusi {_signed(chosen['laba'])}" if chosen["laba"] is not None else ""),
         "<br>".join(chosen["rincian"]), chosen_color)
    if curve is not None:
        with st.expander("Bandingkan budget sebulan lain & riwayat kurva"):
            rows = []
            for mult in (0.75, 1.0, 1.25, 1.5, 2.0, 3.0):
                b_total = max(spent + (pace_total - spent) * mult, spent)
                f_, e_, _c, eff_ = project(target, b_total, current_roas or 8.0)
                rows.append({"Budget sebulan": b_total, "Biaya efektif": eff_, "Sisa/hari": max(b_total - spent, 0) / days_left, "Proyeksi": f_,
                             "% target": f_ / target * 100, "Efek budget iklan": e_})
            show_table(pd.DataFrame(rows).drop_duplicates("Budget sebulan"),
                       kinds={"Budget sebulan": "money", "Biaya efektif": "money", "Sisa/hari": "money", "Proyeksi": "money", "% target": "pct",
                              "Efek budget iklan": "money"})
            st.caption("Riwayat yang dipakai kurva respons toko:")
            show_table(pd.DataFrame(curve.points, columns=["Bulan", "Biaya iklan", "Sales bersih"]), kinds={"Biaya iklan": "money", "Sales bersih": "money"})
    plan_section(3, target=target, month_budget=chosen["budget"], roas=chosen["roas"], auto=True, final=chosen["proyeksi"], extra=chosen["tambahan"],
                 source=f"Rekomendasi sistem · {chosen['nama']}", key="rec", mm=chosen["mm"])
