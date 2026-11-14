"""Rekomendasi › Iklan: strategi iklan untuk mengejar target sales bulan berjalan.

Pengguna menetapkan tiga angka: target sales bulan ini, target ROAS, dan budget iklan sisa bulan. Rencana dihitung
hanya untuk iklan produk tunggal dan iklan grup (plus usulan iklan produk tunggal baru). Tambahan omzet tiap iklan
dibatasi ruang stok produknya (barang yang tidak ada tidak bisa terjual); margin hanya tampil sebagai catatan per iklan.
"""

from __future__ import annotations

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
from src.utils.format import angka, input_rupiah, parse_rupiah, show_table

UP = "#1d4ed8"
DOWN = "#dc2626"
MONTHS_FULL = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember")


def _tone(ok: bool) -> str:
    return UP if ok else DOWN


def _signed(value: float) -> str:
    return ("+" if value >= 0 else "−") + fmt_idr(abs(value))


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
        f"<span><i style='display:inline-block;width:10px;height:10px;background:#ee4d2d;border-radius:2px;margin-right:4px'></i>Perubahan dari rencana iklan {_signed(extra)}</span>"
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


ACT_COLS = ["Tindakan", "Iklan", "Jenis", "Anggota", "Budget harian sekarang", "Budget harian usulan", "Perubahan/hari", "Target ROAS Shopee",
            "ROAS bulan terakhir", "Prediksi omzet produk/hari", "Omzet iklan usulan/hari", "Tambahan omzet/hari", "Catatan"]
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
                select_roas: float | None = None) -> dict:
    """Rencana budget & ROAS tetap (dengan batas stok) + kalender budget harian; disimpan per sesi seperti rekomendasi."""
    cache = st.session_state.setdefault("adt-fixed-cache", {})
    full = (*key, tuple(weeks), round(gap_ads), round(roas, 2), round(budget_daily), lift, select_roas, len(units), round(sum(u.daily_cost for u in units)),
            round(sum(u.daily_sales for u in units)), len(products))
    if full not in cache:
        if len(cache) > 8:
            cache.clear()
        run_days = max(sum(weeks), 1)
        plan_units, plan, selection = A.build_plan(units, members, products, contribution, gap_daily=gap_ads / run_days, target_roas=roas,
                                                   budget_daily=budget_daily, lift=lift, stock_cap=True, select_roas=select_roas)
        steps = A.ramp(plan_units, weeks=weeks, gap_total=gap_ads, target_roas=roas, budget_total=budget_daily * run_days, first=plan)
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
                 stock: bool = True, select_roas: float | None = None) -> dict:
    """Hasil iklan untuk ROAS & budget harian tertentu (None = tanpa batas); stock=False: stok dianggap cukup. Disimpan per sesi.

    Selain angka `ramp_effect`, `kurang_stok` = daftar iklan yang tambahan penjualannya melebihi stok tersisa (nilai jual)."""
    cache = st.session_state.setdefault("adt-option-cache", {})
    full = (*key, tuple(weeks), round(gap_ads), round(roas, 2), -1 if budget_daily is None else round(budget_daily), lift, stock, select_roas, len(units),
            round(sum(u.daily_cost for u in units)), len(products))
    if full not in cache:
        if len(cache) > 300:
            cache.clear()
        run_days = max(sum(weeks), 1)
        plan_units, plan, _sel = A.build_plan(units, members, products, contribution, gap_daily=gap_ads / run_days, target_roas=roas,
                                              budget_daily=budget_daily, lift=lift, stock_cap=stock, select_roas=select_roas)
        steps = A.ramp(plan_units, weeks=weeks, gap_total=gap_ads, target_roas=roas,
                       budget_total=None if budget_daily is None else budget_daily * run_days, first=plan)
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
        up = acts.loc[acts["Tindakan"].isin(["Naikkan budget", "Buat iklan baru", "Pisahkan jadi iklan tunggal", "Aktifkan kembali"])]
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
    sheets = {"Perbandingan": pd.DataFrame(rows_cmp, columns=["Ukuran", "Rekomendasi sistem", "Budget dikunci"]),
              "Budget per iklan": acts[cols] if not acts.empty else pd.DataFrame(), "Kalender harian": cal_view}
    download_excel(sheets, f"strategi_iklan_budget_dikunci_{periode}.xlsx", key="xl-adt-fixed", label="Unduh strategi")


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


def _report_end(totals: dict[str, dict]) -> date | None:
    ends = [date.fromisoformat(str(v["periode"])[:10]) + timedelta(days=int(v["hari"]) - 1) for v in totals.values() if v.get("hari")]
    return max(ends) if ends else None


def _evaluation(cur: dict, units, *, start: date, roas: float) -> None:
    """Evaluasi harian: laporan iklan terbaru dibandingkan dengan laporan saat campaign disimpan (laporan bulanan kumulatif)."""
    st.markdown("**Evaluasi pelaksanaan** · dari laporan iklan terbaru")
    rec = cur.get("rekomendasi") or {}
    if rec:
        st.markdown(
            f"<div class='field-hint'>Rekomendasi saat disimpan: target ROAS {fmt_num(rec.get('roas', 0), 1)}, budget {fmt_idr(rec.get('budget', 0))} → "
            f"{fmt_pct(rec.get('capaian', 0), 1)} target · campaign ini <b>{'memakai' if rec.get('dipakai') else 'tidak memakai'}</b> rekomendasi "
            f"(setelan disimpan: ROAS {fmt_num((cur.get('setelan') or {}).get('roas', 0), 1)}, budget {fmt_idr((cur.get('setelan') or {}).get('budget', 0))}).</div>",
            unsafe_allow_html=True,
        )
    base = cur.get("baseline") or {}
    if not base:
        st.caption("Campaign ini disimpan sebelum ada evaluasi otomatis: simpan ulang sebagai campaign baru agar pelaksanaannya bisa dievaluasi.")
        return
    current = A.month_totals(units) if units else {}
    report_end = _report_end(current)
    if report_end is None or report_end < start:
        st.info(f"Laporan iklan terakhir s.d. {fmt_date(report_end) if report_end else '–'}, campaign mulai {fmt_date(start)}. "
                "Unggah laporan iklan esok hari (Upload data) agar pelaksanaan campaign bisa dievaluasi.")
        return
    weekly = cmp.frame_of(cur.get("iklan_minggu"))
    week_no = (report_end - start).days // 7 + 1
    planned: dict[str, float] = {}
    if not weekly.empty and "_key" in weekly.columns:
        cols = [c for c in weekly.columns if c.startswith("Minggu ")]
        col = f"Minggu {min(week_no, len(cols))}" if cols else None
        if col:
            planned = {str(k): float(v or 0) for k, v in zip(weekly["_key"], weekly[col])}
    if not planned:
        saved = cmp.frame_of(cur.get("iklan"))
        if "key" in saved.columns:
            planned = {str(k): float(v or 0) for k, v in zip(saved["key"], saved["Budget harian usulan"])}
    frame, summary = A.evaluate(base, current, planned, target_roas=roas)
    if not summary:
        st.info(f"Belum ada hari baru di laporan iklan sejak campaign disimpan (laporan s.d. {fmt_date(report_end)}). "
                "Unggah laporan iklan esok hari untuk melihat apakah budget usulan sudah dijalankan.")
        return
    names = {u.key: (u.nama, "Produk tunggal" if u.jenis.startswith("Produk tunggal") else u.jenis) for u in units}
    if not weekly.empty and {"_key", "Iklan", "Jenis"} <= set(weekly.columns):
        names.update({str(k): (str(n), "Produk tunggal" if str(j).startswith("Produk tunggal") else str(j))
                      for k, n, j in zip(weekly["_key"], weekly["Iklan"], weekly["Jenis"])})
    frame.insert(1, "Iklan", frame["_key"].map(lambda k: names.get(k, (k, ""))[0]))
    frame.insert(2, "Jenis", frame["_key"].map(lambda k: names.get(k, ("", ""))[1]))
    done, total = summary["dijalankan"], summary["iklan"]
    k = st.columns(4)
    card(k[0], "Rekomendasi dijalankan", f"{fmt_num(done)} / {fmt_num(total)} iklan",
         hint=f"laporan s.d. {fmt_date(report_end)} · {fmt_num(summary['hari'])} hari dievaluasi · minggu {week_no}")
    card(k[1], "Biaya iklan aktual", f"{fmt_idr(summary['biaya_harian'])}/hari", hint=f"usulan {fmt_idr(summary['budget_usulan_harian'])}/hari")
    card(k[2], "Omzet iklan aktual", f"{fmt_idr(summary['omzet_harian'])}/hari", hint="iklan produk tunggal & grup di campaign")
    ok_roas = summary["roas"] >= roas * 0.9
    card(k[3], "ROAS aktual", fmt_num(summary["roas"], 1), hint=f"target {fmt_num(roas, 1)} · <b style='color:{_tone(ok_roas)}'>"
                                                                f"{'sesuai' if ok_roas else 'di bawah target'}</b>")
    applied = done / total >= 0.7 if total else False
    if applied and ok_roas:
        _box("✅ Rekomendasi dijalankan dan berjalan sesuai rencana",
             f"{fmt_num(done)} dari {fmt_num(total)} iklan memakai budget usulan (±40%) dan ROAS aktual {fmt_num(summary['roas'], 1)} ≥ 90% target. Lanjutkan sampai Senin berikutnya.", UP)
    elif applied:
        _box("⚠️ Rekomendasi dijalankan, tetapi ROAS di bawah target",
             f"ROAS aktual {fmt_num(summary['roas'], 1)} vs target {fmt_num(roas, 1)}. Cek iklan dengan ROAS terendah di tabel; "
             "bila berlanjut sampai Senin, buat campaign baru dari saran (budget iklan lemah dipindah).", DOWN)
    else:
        _box("⚠️ Rekomendasi belum dijalankan penuh",
             f"Hanya {fmt_num(done)} dari {fmt_num(total)} iklan yang biayanya sesuai budget usulan (±40%). Ubah budget harian di Shopee sesuai tabel "
             "'Budget per iklan', lalu unggah laporan iklan esok hari.", DOWN)
    view = frame.drop(columns=["_key"]).sort_values(["Rekomendasi dijalankan", "Biaya aktual/hari"], ascending=[True, False])
    with st.expander(f"Evaluasi per iklan · {fmt_num(total - done)} belum sesuai usulan"):
        st.caption("Biaya & omzet harian = selisih laporan iklan terbaru dengan laporan saat campaign disimpan, dibagi jumlah hari baru. "
                   "Dijalankan = biaya aktual 60–140% budget usulan (iklan yang diusulkan dijeda: biaya ≈ 0). Iklan baru usulan belum punya baris sampai muncul di laporan.")
        show_table(view, kinds={"Hari dievaluasi": "count", "Budget usulan/hari": "money", "Biaya aktual/hari": "money",
                                "Omzet iklan aktual/hari": "money", "ROAS aktual": "dec"},
                   column_config={"Iklan": st.column_config.TextColumn(width="large")})
        download_excel(view, f"evaluasi_campaign_iklan_{cur['id']}.xlsx", key="xl-adt-eval", label="Unduh evaluasi")


def _locked_view(cur: dict, *, units, members, products, contribution, projection: float, mtd: float, target_now: float, today: date, factor: float,
                 first_open: date, month_end: date, periode: str, has_ads: bool) -> None:
    """Campaign iklan tersimpan: tetap jadi acuan, dicek dengan data terbaru, dan disarankan diganti bila tidak lagi sejalan."""
    s = cur.get("setelan") or {}
    start, end = as_date(cur["mulai"]), as_date(cur["selesai"])
    acts_saved = cmp.frame_of(cur.get("iklan"))
    sel_saved = cmp.frame_of(cur.get("produk"))
    target = float(s.get("target") or 0)
    goal = target_now if target_now > 0 else target
    roas = float(s.get("roas") or 8.0)
    budget_daily = float(s.get("budget_harian") or 0)
    reasons: list[str] = []
    if s.get("periode_target") and s["periode_target"] != periode:
        reasons.append(f"campaign dibuat untuk target {month_label(s['periode_target'])}, data sekarang sudah {month_label(periode)}")
    if target_now > 0 and abs(target_now - target) > max(1.0, 0.01 * target):
        reasons.append(f"target bulan ini berubah dari {fmt_idr(target)} menjadi {fmt_idr(target_now)}")
    lift = float(s.get("daya_dorong") or A.DEMAND_LIFT)
    blocks = _blocks(max(start, today), max(end, today), first_open, month_end)
    weeks = [(b - a).days + 1 for a, b in blocks]
    run_days = max(sum(weeks), 1)
    extra, final, diff = 0.0, projection, pd.DataFrame()
    if has_ads and units and goal > 0:
        with st.spinner("Mencocokkan campaign dengan data terbaru..."):
            fresh_units, fresh_plan, _sel = A.build_plan(units, members, products, contribution, gap_daily=(goal - projection) / factor / run_days,
                                                         target_roas=roas, budget_daily=budget_daily, lift=lift, stock_cap=True)
            steps = A.ramp(fresh_units, weeks=weeks, gap_total=(goal - projection) / factor, target_roas=roas, budget_total=budget_daily * run_days, first=fresh_plan)
            eff = A.ramp_effect(fresh_units, steps)
            fresh_acts = A.target_actions(fresh_units, fresh_plan, target_roas=roas)
        extra = eff["omzet_tambahan"] * factor
        final = projection + extra
        diff = C.compare_budgets(acts_saved, fresh_acts)
        changed = int(diff["Berubah"].sum()) if not diff.empty else 0
        if diff.shape[0] and changed / diff.shape[0] > 0.2:
            reasons.append(f"{fmt_num(changed)} dari {fmt_num(len(diff))} iklan: budget saran hari ini beda > 20% dari campaign")
        saved_reach = float(s.get("capaian") or 0)
        reach = final / goal * 100
        if reach < min(saved_reach, 100.0) - 5:
            reasons.append(f"proyeksi turun: saat disimpan {fmt_pct(saved_reach, 1)} target, dengan data {fmt_date(today)} {fmt_pct(reach, 1)}")
    if reasons:
        _box("⚠️ Campaign perlu ditinjau", "<br>".join(f"• {html.escape(r)}" for r in reasons)
             + "<br>Saran: susun rencana baru di Rekomendasi sistem atau Fitur khusus lalu simpan. Rencana ini baru dihentikan saat rencana baru disimpan.", DOWN)
        st.button("Buka Rekomendasi sistem untuk rencana baru", key="adt-renew", on_click=st.session_state.__setitem__, args=("adt-view-next", VIEW_REC), type="primary")
    else:
        _box("✅ Campaign masih sejalan dengan target",
             f"Dicek dengan data {fmt_date(today)}: target sama, budget saran per iklan tidak jauh berbeda, proyeksi {fmt_idr(final)}"
             + (f" ({fmt_pct(final / goal * 100, 1)} target)" if goal > 0 else "") + ". Jalankan budget per iklan di bawah sampai periode selesai.", UP)
    if goal > 0:
        st.markdown(_progress_bar(mtd, projection - mtd, extra, goal), unsafe_allow_html=True)
    k = st.columns(4)
    card(k[0], "Target", fmt_idr(goal), hint=f"aktual sales bersih {fmt_idr(mtd)} · <b style='color:{_tone(mtd >= goal)}'>{fmt_pct(mtd / goal * 100 if goal else 0, 1)}</b> tercapai")
    card(k[1], "Proyeksi dengan campaign", fmt_idr(final), hint=f"hitungan ulang data {fmt_date(today)} · <b style='color:{_tone(final >= goal)}'>"
                                                               f"{fmt_pct(final / goal * 100 if goal else 0, 1)}</b> target")
    card(k[2], "Budget campaign", fmt_idr(float(s.get("budget") or 0)), hint=f"≈ {fmt_idr(budget_daily)}/hari · target ROAS {fmt_num(roas, 1)}")
    card(k[3], "Periode", f"{(end - start).days + 1} hari", hint=f"{fmt_date(start)} – {fmt_date(end)} · sisa {max((end - max(today, start)).days + 1, 0)} hari")
    _evaluation(cur, units, start=start, roas=roas)
    st.markdown("**Budget per iklan (terkunci)**")
    if acts_saved.empty:
        st.info("Campaign ini tidak menyimpan perubahan per iklan.")
    else:
        cols = [c for c in ACT_COLS if c in acts_saved.columns]
        settings = pd.DataFrame([{"Setelan": k_, "Nilai": v} for k_, v in (
            ("Campaign", f"#{cur['id']} {cur.get('nama', '')}"), ("Periode", f"{fmt_date(start)} – {fmt_date(end)}"), ("Target sales", fmt_idr(target)),
            ("Target ROAS", fmt_num(roas, 1)), ("Budget campaign", fmt_idr(float(s.get('budget') or 0))), ("Disimpan", f"{cur.get('dibuat_oleh', '')} {cur.get('dibuat', '')}"))])
        batched_view(
            len(acts_saved), key="adt-lock-units", noun="iklan",
            render=lambda lo, hi: show_table(acts_saved.iloc[lo:hi][cols], kinds=ACT_KINDS, max_height=10_000,
                                             column_config={"Iklan": st.column_config.TextColumn(width="medium"), "Catatan": st.column_config.TextColumn(width="large")}),
            download=lambda: download_excel({"Setelan": settings, "Rencana per iklan": acts_saved[cols], "Pemilihan produk": sel_saved, "Beda dengan saran hari ini": diff},
                                            f"campaign_iklan_{cur['id']}.xlsx", key="xl-adt-lock"),
        )
    weekly_saved = cmp.frame_of(cur.get("jadwal_minggu"), ("Mulai", "Selesai"))
    if len(weekly_saved) > 1:
        with st.expander(f"Jadwal budget per minggu (terkunci) · {fmt_num(len(weekly_saved))} minggu"):
            show_table(weekly_saved, kinds={"Budget/hari": "money", "Omzet iklan/hari": "money", "ROAS": "dec", "Tambahan omzet": "money", "Hari": "count", "Iklan aktif": "count"})
            per_unit = cmp.frame_of(cur.get("iklan_minggu"))
            if not per_unit.empty:
                download_excel(per_unit.drop(columns=["_key"], errors="ignore"), f"budget_iklan_per_minggu_{cur['id']}.xlsx", key="xl-adt-lock-weeks",
                               label="Unduh budget per iklan per minggu")
    calendar_saved = cmp.frame_of(cur.get("kalender_harian"), ("Tanggal",))
    if not calendar_saved.empty:
        with st.expander(f"Kalender budget harian (terkunci) · strategi budget tetap · {fmt_num(len(calendar_saved))} hari"):
            show_table(_calendar_view(calendar_saved), kinds={"Budget/hari": "money", "Omzet iklan/hari": "money", "ROAS hari": "dec", "Pola hari": "dec",
                                                              "Pengali budget": "dec", "Minggu": "count"})
    if not diff.empty:
        with st.expander(f"Beda dengan saran hari ini · {fmt_num(int(diff['Berubah'].sum()))} iklan berubah"):
            st.caption("Budget harian usulan campaign vs hitungan ulang dengan setelan yang sama (target ROAS & budget) dan data terbaru.")
            show_table(diff, kinds={"Budget tersimpan/hari": "money", "Budget saran hari ini/hari": "money", "Selisih/hari": "money"},
                       column_config={"Iklan": st.column_config.TextColumn(width="large")})
    if not sel_saved.empty:
        with st.expander(f"Pemilihan produk (terkunci) · {fmt_num(len(sel_saved))} produk"):
            batched_view(
                len(sel_saved), key="adt-lock-sel", noun="produk",
                render=lambda lo, hi: show_table(sel_saved.iloc[lo:hi].drop(columns=["_unit"], errors="ignore"), kinds=SEL_KINDS, max_height=10_000,
                                                 column_config={"Produk": st.column_config.TextColumn(width="medium"), "Alasan": st.column_config.TextColumn(width="large")}),
            )
    _not_advertised(products, sel_saved, key="adt-lock-noads", periode=periode)


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


def _rec_options(*, target: float, projection: float, spent: float, cost_now: float, days_left: int, month_days: int, run_days: int, pace_total: float,
                 curve, spent_daily: float, best_roas, option, project, units, factor: float, month_name: str) -> list[dict]:
    """Opsi rekomendasi sistem: laju sekarang, maksimal yang bisa diserap iklan, dan budget minimum untuk 100% target."""
    from src.core import ads_month as M

    gap = target - projection
    out: list[dict] = []

    def make(name: str, budget: float, action: str, extra_lines: list[str], *, main: bool = False) -> dict:
        daily = max(budget - spent, 0.0) / max(days_left, 1)
        roas = best_roas(daily, gap)
        final, extra, by_curve = project(target, budget, roas)
        reach = final / target * 100 if target else 0.0
        lines = [f"Budget iklan {month_name} <b>{fmt_idr(budget)}</b> (terpakai {fmt_idr(spent)} + sisa {fmt_idr(max(budget - spent, 0))} ≈ "
                 f"<b>{fmt_idr(daily)}/hari</b> selama {days_left} hari), Target ROAS Shopee <b>{fmt_num(roas, 1)}</b>.",
                 f"Hasil: proyeksi akhir bulan <b>{fmt_idr(final)}</b> ({fmt_pct(reach, 1)} target), tambahan sales bersih {_signed(extra)} dibanding proyeksi tanpa perubahan"
                 + (" (kurva respons toko)." if by_curve else " (rencana per iklan)."),
                 f"Yang dilakukan: {action}", *extra_lines]
        return {"nama": name, "budget": budget, "harian": daily, "roas": roas, "proyeksi": final, "tambahan": extra, "aksi": action, "rincian": lines, "utama": main}

    out.append(make("A · Pertahankan laju sekarang", max(pace_total, spent),
                    "budget harian iklan tetap seperti sekarang; rapikan pemilihan produk & Target ROAS sesuai tabel di bawah.", []))
    res = M.month_plan(curve, target=target, projection=projection, spent=spent, cost_now_daily=spent_daily, days_left=days_left,
                       month_days=month_days, budget_total=None)
    need_total = _round_m(res["budget_dibutuhkan"]) if res.get("ada_kurva") else None
    big = max((need_total - spent) / max(days_left, 1) if need_total else 0.0, cost_now * 3, 1.0)
    r_big = best_roas(big, gap)
    absorbed = float(option(r_big, big, gap)["biaya_total"]) / max(run_days, 1)
    max_total = _round_m(spent + absorbed * days_left)
    hi_cost = max((c for _m, c, _s in curve.points), default=0.0) if curve is not None else 0.0
    if need_total is not None and need_total > max_total * 1.02 and max_total > pace_total * 1.02:
        out.append(make("B · Maksimal yang bisa diserap iklan", max_total,
                        "naikkan budget iklan yang ada bertahap (maks. 2× tiap Senin) dan buat iklan baru untuk produk laris yang belum diiklankan (lihat Pemilihan produk).",
                        [f"Ini batas yang bisa dibelanjakan iklan yang ada + usulan iklan baru tanpa melanggar batas naik 2× per minggu Shopee (±{fmt_idr(absorbed)}/hari)."]))
    if need_total is not None and abs(need_total - (out[-1]["budget"])) > 1_000_000 * 0.5:
        lines = []
        need_daily = max(need_total - spent, 0.0) / max(days_left, 1)
        if gap <= 0:
            action = "turunkan budget harian iklan ke angka di samping; target tetap tercapai dengan biaya lebih hemat."
        else:
            action = "naikkan budget iklan bertahap tiap Senin, buat iklan baru untuk produk laris, dan pastikan stok produk yang diiklankan cukup."
            if need_daily > absorbed * 1.05:
                lines.append(f"⚠️ Iklan yang ada + usulan iklan baru hanya bisa menyerap ±{fmt_idr(absorbed)}/hari: sisanya perlu iklan baru tambahan "
                             "atau kenaikan bertahap; bila tidak, hasil akan seperti opsi B.")
            pace_need = (need_total - spent) / max(res["porsi"], 1e-9)
            if hi_cost and pace_need > hi_cost * 1.3:
                lines.append(f"⚠️ Laju budget ini (±{fmt_idr(pace_need)}/bulan) di atas bulan termahal di riwayat ({fmt_idr(hi_cost)}): angka di luar riwayat, "
                             "naikkan bertahap dan pantau hasilnya tiap Senin.")
            room = sum(max(u.stock_room, 0.0) for u in units if np.isfinite(u.stock_room))
            need_extra_daily = gap / max(days_left, 1) / max(factor, 1e-9)
            if room and need_extra_daily > room:
                lines.append(f"⚠️ Ruang stok produk yang diiklankan ±{fmt_idr(room)}/hari, di bawah tambahan penjualan yang dibutuhkan ±{fmt_idr(need_extra_daily)}/hari: "
                             "ajukan restock/PO agar target tidak tertahan stok.")
        out.append(make("C · Budget untuk 100% target" if gap > 0 else "C · Budget paling hemat untuk 100% target", need_total, action, lines, main=True))
    elif need_total is None and gap > 0:
        out.append(make("B · Maksimal yang bisa diserap iklan", max(max_total, pace_total),
                        "naikkan budget iklan yang ada bertahap (maks. 2× tiap Senin) dan buat iklan baru untuk produk laris.",
                        ["Budget untuk 100% target belum bisa dihitung: riwayat iklan bulanan belum cukup (minimal 3 bulan penuh)."], main=True))
    if not any(o["utama"] for o in out):
        out[-1]["utama"] = True
    return out


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


def _track_detail(cur: dict, track: dict | None, *, today: date) -> None:
    s = cur.get("setelan") or {}
    _step(1, "Apakah rencana on track?", f"· {s.get('sumber') or 'rencana tersimpan'} · dibandingkan dengan data terbaru")
    if track is None:
        st.info("Rencana ini disimpan sebelum pantauan jalur tersedia, atau bulan target sudah berganti. Evaluasi per iklan tetap ada di bawah; "
                "simpan rencana baru agar jalur sales & biaya bisa dipantau.")
        return
    if track["status"] == "Menunggu data":
        st.info(f"Rencana disimpan dengan data s.d. {fmt_date(track['mulai'])}. Pantauan muncul setelah data penjualan & laporan iklan hari berikutnya diunggah.")
        return
    on = track["status"] == "On track"
    k = st.columns(4)
    card(k[0], "Status", "✅ On track" if on else "⚠️ Tertinggal", hint=f"{track['hari']} hari data baru sejak {fmt_date(track['mulai'])} dari {track['hari_sisa']} hari rencana")
    card(k[1], "Sales bersih vs jalur rencana", fmt_idr(track["sales"]),
         hint=f"jalur {fmt_idr(track['jalur_sales'])} · <b style='color:{_tone(on)}'>{fmt_pct(track['pct_sales'], 1)}</b> · "
              f"{_signed(track['selisih_sales'])} · tanpa rencana {fmt_idr(track['jalur_tanpa'])}")
    card(k[2], "Biaya iklan sejak disimpan", fmt_idr(track["biaya_baru"]),
         hint=f"rencana {fmt_idr(track['jalur_biaya'] - track['terpakai_awal'])} · <b>{track['biaya_status']}</b>"
              + (f" ({fmt_pct(track['pct_biaya'], 0)})" if track["pct_biaya"] == track["pct_biaya"] else ""))
    card(k[3], "Biaya iklan % sales bersih", fmt_pct(track["biaya_baru"] / track["sales_baru"] * 100, 1) if track["sales_baru"] > 0 else "–",
         hint=f"sejak disimpan: biaya iklan {fmt_idr(track['biaya_baru'])} ÷ sales bersih {fmt_idr(track['sales_baru'])} (TACoS; makin kecil makin hemat)")
    tips = []
    if not on:
        tips.append("Sales bersih di bawah jalur rencana. Buka <b>Rekomendasi sistem</b> untuk opsi baru atau ubah setelan di <b>Fitur khusus</b>, lalu simpan rencana baru "
                    "(rencana ini dihentikan otomatis).")
    if track["biaya_status"] == "kurang terserap":
        tips.append("Biaya iklan lebih rendah dari rencana: cek apakah budget per iklan sudah diubah di Shopee atau iklan tertahan Target ROAS yang terlalu tinggi.")
    elif track["biaya_status"] == "lebih boros":
        tips.append("Biaya iklan lebih tinggi dari rencana: cek iklan yang budgetnya dinaikkan melebihi usulan (tabel Evaluasi per iklan di bawah).")
    if tips:
        _box("Tindak lanjut", "<br>".join(tips), DOWN if not on else "#b45309")
    st.caption(f"Jalur rencana = sales bersih saat disimpan ({fmt_idr(track['mtd_awal'])}) menuju proyeksi rencana ({fmt_idr(track['proyeksi_rencana'])}) dibagi rata "
               f"ke {track['hari_sisa']} hari tersisa; biaya = terpakai saat disimpan + budget harian rencana × hari berjalan. On track = sales ≥ 97% jalur. "
               "Biaya iklan dari laporan iklan keseluruhan; unggah laporan terbaru agar pantauan akurat.")


def show_target_strategy(table: pd.DataFrame, *, features, params: dict, username: str, can_edit: bool, frames=None,
                         orders: pd.DataFrame | None = None, inputs=None) -> None:
    st.markdown("<div class='section-title'>Strategi iklan kejar target</div>", unsafe_allow_html=True)
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

    has_ads = frames is not None and any(isinstance(f, pd.DataFrame) and not f.empty for f in (getattr(frames, "ads", []) or []))
    units, members, contribution, products = [], pd.DataFrame(), {}, pd.DataFrame()
    if has_ads and inputs is not None:
        with st.spinner("Membaca riwayat iklan produk tunggal & grup..."):
            units, members, contribution, products = inputs(table, features, frames, days_left)
    running = [u for u in units if u.daily_cost > 0 and A._running(u)]
    cost_now = sum(u.daily_cost for u in running)
    sales_now = sum(u.daily_sales for u in running)
    projection, mtd = float(outlook["projection"]), float(outlook["mtd"])
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

    # ---------------- Pantauan rencana tersimpan (selalu tampil ringkas di atas)
    track = M.plan_track(cur.get("setelan") or {}, mtd=mtd, last=last, spent=spent, periode=periode) if cur is not None else None
    if cur is not None:
        _track_banner(cur, track)

    # ---------------- Periode campaign (dipakai rencana mana pun yang disimpan)
    hi = max(month_end, today + timedelta(days=6))
    default_start = max(today, first_open) if max(today, first_open) <= month_end else today
    with st.container(border=True):
        start, end = cmp.period_picker(key=f"adt-period-{periode}", today=today, hi=hi,
                                       default=(default_start, month_end if month_end >= default_start else default_start + timedelta(days=6)))
    period_days = (end - start).days + 1
    week_text = f"{fmt_date(start)} – {fmt_date(end)}"

    # ---------------- Pilihan tampilan: tiga fitur berdiri sendiri
    views = [(VIEW_CUSTOM, "🎛️ Fitur khusus · setelan Anda"), (VIEW_REC, "💡 Rekomendasi sistem")]
    if cur is not None:
        views.append((VIEW_TRACK, "📌 Pantau rencana tersimpan"))
    slugs = [v for v, _l in views]
    nxt = st.session_state.pop("adt-view-next", None)
    if nxt in slugs:
        st.session_state["adt-view"] = nxt
    if st.session_state.get("adt-view") not in slugs:
        st.session_state["adt-view"] = VIEW_TRACK if cur is not None else VIEW_CUSTOM
    view = st.session_state["adt-view"]
    clicked = button_tabs(views, view, key="adt-view-btn")
    if clicked and clicked != view:
        st.session_state["adt-view"] = clicked
        st.rerun()

    if view == VIEW_TRACK and cur is not None:
        _track_detail(cur, track, today=today)
        _locked_view(cur, units=units, members=members, products=products, contribution=contribution, projection=projection, mtd=mtd,
                     target_now=float(goals.target_sales), today=today, factor=factor, first_open=first_open, month_end=month_end, periode=periode, has_ads=has_ads)
        return

    spent_text = (f"terpakai 1–{last.day} {month_label(periode)} <b>{fmt_idr(spent)}</b> ({fmt_idr(spent_daily)}/hari, laporan iklan keseluruhan"
                  + (f"; omzet diklaim iklan {fmt_idr(spend['omzet'])}, ROAS {fmt_num(spend['omzet'] / spent, 1)}" if spent > 0 else "") + ")"
                  if spent_days else "biaya iklan bulan ini belum terbaca (unggah laporan iklan keseluruhan bulan berjalan)")

    blocks = _blocks(start, end, first_open, month_end)
    weeks = [(b - a).days + 1 for a, b in blocks]
    run_days = max(sum(weeks), 1)
    base_units = units
    lift = A.FREE_LIFT
    select = F.selection_roas(base_units) if base_units else None

    def option(r: float, daily: float, gap_now: float) -> dict:
        return _option_plan(base_units, members, products, contribution, weeks=weeks, gap_ads=max(gap_now / factor, 0.0), roas=r, budget_daily=daily, lift=lift,
                            key=(periode, start, end), stock=True, select_roas=select)

    def best_roas(daily: float, gap_now: float) -> float:
        if daily <= 0:
            return current_roas or 8.0
        return F.shopee_roas(option(F.pick_roas(lambda r: option(r, daily, gap_now)["omzet_tambahan"]), daily, gap_now)["roas_rencana"])

    def project(target: float, month_budget: float, roas: float) -> tuple[float, float, bool]:
        """(proyeksi akhir bulan, tambahan sales bersih, pakai kurva toko?) untuk budget sebulan tertentu."""
        res = M.month_plan(curve, target=target, projection=projection, spent=spent, cost_now_daily=spent_daily, days_left=days_left,
                           month_days=month_days, budget_total=month_budget)
        if res.get("ada_kurva"):
            return float(res["proyeksi"]), float(res["tambahan"]), True
        daily = max(month_budget - spent, 0.0) / days_left
        extra = option(roas, daily, target - projection)["omzet_tambahan"] * factor
        return projection + extra, extra, False

    if _run_days(start, end, first_open, month_end) == 0:
        st.warning(f"Periode campaign {week_text} tidak jatuh di sisa hari {month_name} setelah data terakhir ({fmt_date(last)}). "
                   "Rencana memakai seluruh periode campaign sebagai pendekatan; untuk target bulan berikutnya, unggah data & target bulan itu dulu.")

    def plan_section(n0: int, *, target: float, month_budget: float, roas: float, auto: bool, final: float, extra: float, source: str, key: str) -> None:
        """Pemilihan produk + budget per iklan + simpan, untuk setelan apa pun (fitur khusus atau opsi rekomendasi)."""
        remaining = max(month_budget - spent, 0.0)
        budget_daily = remaining / days_left
        budget = budget_daily * period_days
        reach = final / target * 100 if target > 0 else 0.0
        with st.spinner("Membagi budget ke iklan..."):
            fixed = _fixed_plan(base_units, members, products, contribution, weeks=weeks, blocks=blocks, gap_ads=max(target - projection, 0.0) / factor, roas=roas,
                                budget_daily=budget_daily, lift=lift, shape=_day_shape_of(orders, last), key=(periode, start, end), select_roas=select)
        units, plan, selection, steps = fixed["units"], fixed["plan"], fixed["selection"], fixed["steps"]
        eff = fixed["eff"]
        week_table = A.weekly_table(units, steps, blocks)
        used_daily = sum(plan.cost.values())
        fixed_used = True
        acts = A.target_actions(units, plan, target_roas=roas)

        # ---------------- 3. Pemilihan produk
        _step(n0, "Pemilihan produk iklan", "· siapa masuk iklan tunggal, siapa di grup, siapa dikeluarkan")
        if selection.empty:
            st.info("Belum ada data produk iklan (laporan iklan grup / keseluruhan) untuk dianalisa.")
        else:
            sel_groups = [
                ("Buat iklan tunggal", "🆕", UP, "produk laris belum diiklankan"), ("Jadikan iklan tunggal", "⭐", UP, "andalan di grup"),
                ("Pertahankan iklan tunggal", "✅", "#64748b", ""), ("Tambahkan ke grup", "➕", UP, "belum diiklankan"),
                ("Pertahankan di grup", "✅", "#64748b", ""), ("Pindahkan ke grup", "↘️", DOWN, "iklan tunggal kurang efisien"),
                ("Keluarkan dari grup", "➖", DOWN, "menyedot budget"), (A.SMALL_SALES, "🔻", DOWN, "potensi sales & qty kecil"),
                ("Jeda sampai restock", "⏸️", DOWN, "stok 0"),
            ]
            chips = []
            for name, icon, color, note in sel_groups:
                count = int((selection["Saran"] == name).sum())
                if count:
                    chips.append(f"<span style='border:1px solid #e2e8f0;border-radius:999px;padding:.25rem .75rem;font-size:var(--fs-sm);background:#fff'>{icon} "
                                 f"<b style='color:{color}'>{name}</b> {fmt_num(count)} produk" + (f" · {note}" if note else "") + "</span>")
            st.markdown("<div style='display:flex;flex-wrap:wrap;gap:.45rem;margin:.2rem 0 .6rem'>" + "".join(chips) + "</div>", unsafe_allow_html=True)
            names = [g[0] for g in sel_groups if (selection["Saran"] == g[0]).any()]
            default_pick = [n for n in names if not n.startswith("Pertahankan")]
            picked = st.multiselect("Tampilkan saran", names, default=default_pick, key="adt-sel-pick", placeholder="Semua saran")
            selection = selection.drop(columns=["_unit"], errors="ignore")
            sel_view = selection.loc[selection["Saran"].isin(picked)] if picked else selection
            sel_kinds = {"Biaya iklan/hari": "money", "Omzet iklan/hari": "money", "ROAS 2 bulan": "dec", "Porsi omzet grup": "pct",
                         "Prediksi omzet/hari": "money", "Prediksi qty/hari": "dec", "Stok": "count", "Budget usulan iklan/hari": "money"}
            batched_view(
                len(sel_view), key="adt-sel", noun="produk",
                render=lambda lo, hi: show_table(sel_view.iloc[lo:hi], kinds=sel_kinds, max_height=10_000,
                                                 column_config={"Produk": st.column_config.TextColumn(width="medium"), "Alasan": st.column_config.TextColumn(width="large"),
                                                                "Prediksi omzet/hari": st.column_config.Column(help="Prediksi omzet harian produk dari analisa (semua kanal penjualan)"),
                                                                "Iklan di rencana": st.column_config.Column(help="Iklan tempat produk ini berada sesudah perubahan; sama dengan baris di tabel Budget per iklan"),
                                                                "Budget usulan iklan/hari": st.column_config.Column(help="Budget harian usulan iklan tersebut di tabel Budget per iklan (untuk grup: budget seluruh grup)")}),
                download=lambda: download_excel(selection, f"pemilihan_produk_iklan_{periode}.xlsx", key="xl-adt-sel"),
            )
            floor_sales, floor_qty = A.potential_floors(products)
            dup_count = int((selection["Saran"] == "Sudah di iklan lain").sum())
            if dup_count:
                st.caption(f"{fmt_num(dup_count)} baris lain adalah produk di iklan yang sudah dijeda/berakhir yang juga ada di iklan aktif: "
                           "tidak perlu tindakan, omzetnya hanya dihitung di iklan aktifnya (ada di unduhan Excel).")
            st.caption(f"Dasar: hasil iklan 2 bulan terakhir per produk, prediksi omzet dari analisa, stok, dan target ROAS {fmt_num(roas, 1)}. "
                       f"Layak diiklankan = potensi sales ≥ {fmt_idr(floor_sales)}/hari (produk pembentuk 95% sales toko) atau laku ≥ {fmt_num(floor_qty, 1)} unit/hari; "
                       "di bawah itu iklan dihentikan (Stop iklan · sales kecil) dan produk belum diiklankan tidak diusulkan. "
                       "Jadikan tunggal = porsi omzet ≥ 30% di grup dan ROAS ≥ 80% target; keluarkan/pindahkan = ROAS < 50% target atau biaya tanpa omzet. "
                       "Satu produk hanya di satu iklan. Budget per iklan sudah dihitung dengan susunan ini: produk yang dikeluarkan/dijeda tidak lagi "
                       "dihitung omzetnya, iklan tunggal hasil pisah mengambil budget dari grup asalnya. Kerjakan bersamaan dengan perubahan budget hari Senin.")

        # ---------------- 4. Rencana per iklan
        _step(n0 + 1, "Budget per iklan", f"· ubah di Shopee mulai {fmt_date(start)}, berlaku s.d. {fmt_date(end)}")
        if acts.empty:
            st.info("Tidak ada perubahan iklan yang disarankan.")
        else:
            groups = [
                ("Naikkan budget", "⬆️", UP), ("Pisahkan jadi iklan tunggal", "⭐", UP), ("Buat iklan baru", "🆕", UP), ("Aktifkan kembali", "▶️", UP),
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
            f1, f2 = st.columns([1, 2])
            kind_pick = f1.segmented_control("Jenis iklan", ["Semua", "Produk tunggal", "Grup"], default="Semua", key="adt-kind") if hasattr(st, "segmented_control") else "Semua"
            act_names = [g[0] for g in groups if (acts["Tindakan"] == g[0]).any()]
            act_pick = f2.multiselect("Tindakan", act_names, key="adt-act", placeholder="Semua tindakan")
            shown = acts
            if kind_pick and kind_pick != "Semua":
                shown = shown.loc[shown["Jenis"] == kind_pick]
            if act_pick:
                shown = shown.loc[shown["Tindakan"].isin(act_pick)]
            cols = ["Tindakan", "Iklan", "Jenis", "Anggota", "Budget harian sekarang", "Budget harian usulan", "Perubahan/hari", "Target ROAS Shopee",
                    "ROAS bulan terakhir", "Prediksi omzet produk/hari", "Omzet iklan usulan/hari", "Tambahan omzet/hari", "Catatan"]
            kinds = {"Budget harian sekarang": "money", "Budget harian usulan": "money", "Perubahan/hari": "money", "Tambahan omzet/hari": "money",
                     "Prediksi omzet produk/hari": "money", "Omzet iklan usulan/hari": "money",
                     "Anggota": "count", "ROAS bulan terakhir": "dec", "Target ROAS Shopee": "dec"}
            settings = pd.DataFrame([
                {"Setelan": "Bulan", "Nilai": month_name}, {"Setelan": "Periode campaign", "Nilai": week_text}, {"Setelan": "Target sales", "Nilai": fmt_idr(target)},
                {"Setelan": "Target ROAS", "Nilai": fmt_num(roas, 1)}, {"Setelan": f"Budget campaign ({period_days} hari)", "Nilai": fmt_idr(budget)},
                {"Setelan": "Proyeksi dengan rencana", "Nilai": f"{fmt_idr(final)} ({fmt_pct(reach, 1)})"},
            ])
            batched_view(
                len(shown), key="adt-units", noun="iklan",
                render=lambda lo, hi: show_table(shown.iloc[lo:hi][cols], kinds=kinds, max_height=10_000,
                                                 column_config={"Iklan": st.column_config.TextColumn(width="medium"), "Catatan": st.column_config.TextColumn(width="large"),
                                                                "Target ROAS Shopee": st.column_config.Column(help="ROAS rata-rata iklan ini pada budget usulan (maks. 30); isi di pengaturan iklan GMV Max ROAS Shopee"),
                                                                "Prediksi omzet produk/hari": st.column_config.Column(help="Prediksi omzet harian (analisa, semua kanal) produk yang tinggal di iklan ini"),
                                                                "Omzet iklan usulan/hari": st.column_config.Column(help="Omzet yang tercatat di iklan Shopee pada budget usulan; tambahannya dibatasi daya dorong iklan × prediksi omzet produk")}),
                download=lambda: download_excel({"Setelan": settings, "Rencana per iklan": acts[cols], "Pemilihan produk": selection}, f"strategi_iklan_{periode}.xlsx", key="xl-adt"),
            )
        unit_weeks = A.unit_weekly_budget(units, steps)
        if len(week_table) > 1:
            st.markdown("**Jadwal budget per minggu** · tabel di atas = budget minggu 1; tiap Senin budget per iklan dinaikkan maks. 2× dari minggu sebelumnya")
            show_table(week_table, kinds={"Budget/hari": "money", "Omzet iklan/hari": "money", "ROAS": "dec", "Tambahan omzet": "money", "Hari": "count", "Iklan aktif": "count"})
            if not unit_weeks.empty:
                download_excel(unit_weeks.drop(columns=["_key"]), f"budget_iklan_per_minggu_{periode}.xlsx", key="xl-adt-weeks", label="Unduh budget per iklan per minggu")
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

        steps = [
            f"<b>{fmt_date(start)}</b> — ubah susunan produk (Pemilihan produk) serta budget harian & Target ROAS tiap iklan (Budget per iklan) di Shopee, lalu simpan sebagai campaign di bawah agar terkunci. "
            "Budget naik maks. 2× atau turun ke ≥ ½ agar perlindungan ROAS Shopee tetap aktif.",
            "<b>Selasa–Minggu</b> — jangan ubah budget; biarkan algoritma Shopee belajar. Pantau stok produk yang ditandai ⚠️.",
            "<b>Tiap Senin</b> — unggah laporan iklan minggu lalu dan buka menu ini: campaign tersimpan dicek dengan data terbaru. Bila statusnya perlu ditinjau, "
            "buat campaign baru dari saran (campaign lama dihentikan otomatis); budget naik maks. 2× per minggu.",
            "<b>Akhir bulan</b> — evaluasi di Laporan › Iklan; unggah target bulan berikutnya di Upload data › Target.",
        ]
        _box("Tindak lanjut", "<ol style='margin:0 0 0 1.1rem;padding:0'>" + "".join(f"<li>{t}</li>" for t in steps) + "</ol>", "#ee4d2d")
        with st.expander("Cara rencana dihitung"):
            explain([
                ("Iklan yang dihitung", "iklan produk tunggal dan iklan grup dari laporan iklan bulanan, plus usulan iklan produk tunggal baru untuk produk laris yang belum diiklankan"),
                ("Kurva respons", "omzet iklan harian = a·ln(1 + biaya/b) dari riwayat biaya vs omzet tiap iklan: makin besar budget, tambahan omzetnya makin kecil"),
                ("Target ROAS", "ROAS rata-rata seluruh iklan di rencana (total omzet iklan ÷ total biaya), sama dengan arti Target ROAS di Shopee"),
                ("Urutan", "1) budget dipindah dari iklan dengan tambahan omzet per Rp terendah ke yang tertinggi selama omzet naik, "
                           "2) bila melebihi budget atau ROAS rata-rata di bawah target, iklan paling tidak efektif dipangkas, "
                           "3) sisa budget diberikan ke iklan paling efektif sampai kekurangan omzet tertutup atau ROAS rata-rata menyentuh target"),
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
                                           "dikali porsi hari tersisa. Rekomendasi = budget sebulan terkecil yang menutup 100% target"),
                ("Rencana per iklan", "sisa budget dibagi ke iklan dengan kurva tiap iklan (omzet diklaim Shopee), dibatasi stok dan batas naik 2× per minggu; "
                                      "dipakai untuk Target ROAS Shopee dan budget per iklan, bukan untuk proyeksi target"),
                ("Stok", "tambahan omzet tiap iklan maks. ruang stok produknya sampai akhir bulan (stok − prediksi − SS); iklan yang tertahan stok ditandai untuk restock"),
                ("Margin", "tidak membatasi rencana; tampil sebagai catatan per iklan"),
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
                payload={"setelan": {"periode_target": periode, "target": target, "roas": roas, "budget": budget, "budget_bulan": month_budget, "terpakai": spent, "budget_harian": budget_daily,
                                     "budget_rencana_harian": used_daily, "proyeksi": final, "capaian": reach, "hari_hitung": run_days, "daya_dorong": lift,
                                     "strategi_budget_tetap": fixed_used, "sumber": source, "mtd": mtd, "data_sampai": last.isoformat(), "hari_sisa": days_left,
                                     "proyeksi_tanpa": projection, "roas_otomatis": auto},
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
            roas = best_roas(budget_daily, target - projection) if auto else min(float(submitted.get("roas") or 8.0), A.MAX_SHOPEE_ROAS)
        final, extra, by_curve = project(target, month_budget, roas)
        reach = final / target * 100
        with result_slot:
            k = st.columns(4)
            card(k[0], "Proyeksi akhir bulan", fmt_idr(final),
                 hint=f"<b style='color:{_tone(final >= target)}'>{fmt_pct(reach, 1)}</b> dari target {fmt_idr(target)} · tanpa perubahan {fmt_pct(projection / target * 100, 1)}")
            card(k[1], "Tambahan sales bersih dari iklan", _signed(extra),
                 hint=("dibanding proyeksi tanpa perubahan · kurva respons toko" if by_curve else "dari rencana per iklan (kurva toko belum ada)"))
            card(k[2], "Sisa budget", fmt_idr(remaining), hint=f"budget {fmt_idr(month_budget)} − terpakai {fmt_idr(spent)} · ≈ {fmt_idr(budget_daily)}/hari × {days_left} hari")
            card(k[3], "Target ROAS Shopee", fmt_num(roas, 1),
                 hint=("dipilih sistem: omzet iklan terbesar dengan sisa budget" if auto else "ditentukan Anda") + f" · ROAS iklan sekarang {fmt_num(current_roas, 1)}")
            ok = final >= target - 1
            st.markdown(f"<div style='background:{UP if ok else DOWN};color:#fff;border-radius:10px;padding:.5rem .8rem;font-weight:700;margin-top:.4rem'>"
                        + (f"Dengan setelan ini target {month_name} tercapai ({fmt_pct(reach, 1)})." if ok else
                           f"Dengan setelan ini proyeksi {fmt_pct(reach, 1)} target · kurang {fmt_idr(target - final)}.") + "</div>", unsafe_allow_html=True)

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
        card(k[3], "Biaya iklan % sales bersih", fmt_pct(spent / mtd * 100, 1) if mtd > 0 else "–",
             hint=f"biaya iklan terpakai ÷ sales bersih toko s.d. {fmt_date(last)} {fmt_idr(mtd)} (TACoS: termasuk penjualan non-iklan; makin kecil makin hemat)")
        if spent > month_budget:
            _box("Budget sebulan sudah terlampaui", f"Biaya iklan yang sudah keluar {fmt_idr(spent)} melebihi setelan {fmt_idr(month_budget)} "
                 f"({fmt_idr(spent - month_budget)}). Sisa budget dihitung 0: rencana di bawah menjeda iklan dan proyeksi turun. Naikkan budget sebulan bila iklan tetap ingin berjalan.", DOWN)

        _step(2, "Hasil setelan Anda", "· aktual + prediksi sisa bulan + perubahan dari setelan")
        st.markdown(_progress_bar(mtd, projection - mtd, extra, target), unsafe_allow_html=True)
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
    card(k[2], "Proyeksi tanpa perubahan", fmt_idr(projection), hint=f"<b style='color:{_tone(gap <= 0)}'>{fmt_pct(projection / target * 100, 1)}</b> target · "
                                                                      + (f"kurang {fmt_idr(gap)}" if gap > 0 else f"lebih {fmt_idr(-gap)}"))
    card(k[3], "Biaya iklan terpakai", fmt_idr(spent), hint=(f"{fmt_idr(spent_daily)}/hari · omzet diklaim iklan {fmt_idr(spend['omzet'])} "
                                                             f"(ROAS {fmt_num(spend['omzet'] / spent if spent else 0, 1)})" if spent_days else "laporan iklan bulan ini belum ada"))
    notes = [f"Iklan berjalan sekarang {fmt_num(len(running))} iklan, {fmt_idr(cost_now)}/hari, ROAS {fmt_num(sales_now / cost_now if cost_now else 0, 1)}; "
             f"bila diteruskan, biaya iklan sebulan ≈ {fmt_idr(pace_total)}."]
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
    if not has_ads or not units:
        st.info("Laporan iklan (grup / keseluruhan) belum diunggah atau tidak ada iklan produk tunggal & grup: opsi iklan butuh riwayat biaya & omzet per iklan.")
        return

    _step(2, "Opsi mencapai target", "· pilih satu opsi; rincian produk & budget per iklan serta tombol simpan ada di bawah")
    with st.spinner("Menghitung opsi..."):
        opts = _rec_options(target=target, projection=projection, spent=spent, cost_now=cost_now, days_left=days_left, month_days=month_days, run_days=run_days,
                            pace_total=pace_total, curve=curve, spent_daily=spent_daily, best_roas=best_roas, option=option, project=project, units=base_units,
                            factor=factor, month_name=month_name)
    table_opts = pd.DataFrame([{"Opsi": o["nama"], "Budget sebulan": o["budget"], "Sisa/hari": o["harian"], "Target ROAS": o["roas"],
                                "Proyeksi akhir bulan": o["proyeksi"], "% target": o["proyeksi"] / target * 100, "Tambahan sales bersih": o["tambahan"],
                                "Yang dilakukan": o["aksi"]} for o in opts])
    show_table(table_opts, kinds={"Budget sebulan": "money", "Sisa/hari": "money", "Target ROAS": "dec", "Proyeksi akhir bulan": "money", "% target": "pct",
                                  "Tambahan sales bersih": "money"},
               column_config={"Opsi": st.column_config.TextColumn(width="medium"), "Yang dilakukan": st.column_config.TextColumn(width="large")})
    names = [o["nama"] for o in opts]
    best = next((o["nama"] for o in opts if o.get("utama")), names[-1])
    if st.session_state.get("adt-rec-pick") not in names:
        st.session_state["adt-rec-pick"] = best
    pick = st.radio("Opsi yang ingin dirinci", names, key="adt-rec-pick", horizontal=True)
    chosen = next(o for o in opts if o["nama"] == pick)
    _box(f"💡 {html.escape(chosen['nama'])} · proyeksi {fmt_pct(chosen['proyeksi'] / target * 100, 1)} target",
         "<br>".join(chosen["rincian"]), UP if chosen["proyeksi"] >= target - 1 else "#b45309")
    if curve is not None:
        with st.expander("Bandingkan budget sebulan lain & riwayat kurva"):
            rows = []
            for mult in (0.75, 1.0, 1.25, 1.5, 2.0, 3.0):
                b_total = max(spent + (pace_total - spent) * mult, spent)
                f_, e_, _c = project(target, b_total, current_roas or 8.0)
                rows.append({"Budget sebulan": b_total, "Sisa/hari": max(b_total - spent, 0) / days_left, "Proyeksi": f_, "% target": f_ / target * 100, "Tambahan sales": e_})
            show_table(pd.DataFrame(rows).drop_duplicates("Budget sebulan"),
                       kinds={"Budget sebulan": "money", "Sisa/hari": "money", "Proyeksi": "money", "% target": "pct", "Tambahan sales": "money"})
            st.caption("Riwayat yang dipakai kurva respons toko:")
            show_table(pd.DataFrame(curve.points, columns=["Bulan", "Biaya iklan", "Sales bersih"]), kinds={"Biaya iklan": "money", "Sales bersih": "money"})
    plan_section(3, target=target, month_budget=chosen["budget"], roas=chosen["roas"], auto=True, final=chosen["proyeksi"], extra=chosen["tambahan"],
                 source=f"Rekomendasi sistem · {chosen['nama']}", key="rec")
