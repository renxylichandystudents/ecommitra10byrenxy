"""Rekomendasi › Iklan: strategi iklan untuk mengejar target sales bulan berjalan.

Pengguna menetapkan tiga angka: target sales bulan ini, target ROAS, dan budget iklan sisa bulan. Rencana dihitung
hanya untuk iklan produk tunggal dan iklan grup (plus usulan iklan produk tunggal baru). Margin dan stok tidak
membatasi rencana karena prioritasnya sales value; keduanya tampil sebagai catatan per iklan.
"""

from __future__ import annotations

import html
import json
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import streamlit as st

from src.core import ads_strategy as A
from src.core.business import business_targets
from src.core.targets import month_label
from src.ui.common import batched_view, card, download_excel, explain, fmt_idr, fmt_num, fmt_pct
from src.ui.feature_data import bump, target_for
from src.ui.targets_view import month_outlook, target_roas_for
from src.utils.format import angka, input_rupiah, show_table

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
        f"<div style='position:absolute;left:{target / scale * 100:.2f}%;top:-1.45rem;transform:translateX(-50%);font-size:.72rem;font-weight:700;color:#0f172a;white-space:nowrap'>Target</div>"
        if target > 0 else ""
    )
    legend = (
        "<div style='display:flex;flex-wrap:wrap;gap:1rem;font-size:.78rem;color:#475569;margin-top:.45rem'>"
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
        f"<div style='font-weight:800;color:{color};margin-bottom:.25rem'>{title}</div><div style='font-size:.92rem;line-height:1.6;color:#1f2937'>{body}</div></div>",
        unsafe_allow_html=True,
    )


def _step(number: int, title: str, note: str = "") -> None:
    st.markdown(
        f"<div style='display:flex;align-items:baseline;gap:.55rem;margin:1.1rem 0 .4rem'>"
        f"<span style='background:#ee4d2d;color:#fff;border-radius:999px;min-width:1.6rem;height:1.6rem;display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-size:.85rem'>{number}</span>"
        f"<span style='font-weight:800;font-size:1.05rem'>{html.escape(title)}</span>"
        f"<span style='color:#64748b;font-size:.85rem'>{html.escape(note)}</span></div>",
        unsafe_allow_html=True,
    )


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
    week_start = today if today.weekday() == 0 else today + timedelta(days=7 - today.weekday())
    week_end, next_monday = week_start + timedelta(days=6), week_start + timedelta(days=7)
    week_text = f"{week_start:%d/%m} – {week_end:%d/%m/%Y}"

    has_ads = frames is not None and any(isinstance(f, pd.DataFrame) and not f.empty for f in (getattr(frames, "ads", []) or []))
    units, members, contribution, products = [], pd.DataFrame(), {}, pd.DataFrame()
    if has_ads and inputs is not None:
        with st.spinner("Membaca riwayat iklan produk tunggal & grup..."):
            units, members, contribution, products = inputs(table, features, frames, days_left)
    running = [u for u in units if u.daily_cost > 0 and A._running(u)]
    cost_now = sum(u.daily_cost for u in running)
    sales_now = sum(u.daily_sales for u in running)

    # ---------------- 1. Setelan
    _step(1, "Setelan", f"· {month_name}, sisa {days_left} hari · rencana berlaku seminggu (Senin {week_text}), dievaluasi tiap Senin")
    running_week = today - timedelta(days=today.weekday())
    if saved_plan.get("minggu") in {week_start.isoformat(), running_week.isoformat()}:
        saved_start = date.fromisoformat(saved_plan["minggu"])
        _box("Rencana minggu ini sudah disimpan",
             f"Disimpan oleh {html.escape(str(saved.get('set_by') or '-'))} untuk minggu {saved_start:%d/%m} – {saved_start + timedelta(days=6):%d/%m}: "
             f"target ROAS {fmt_num(saved_plan.get('target_roas', 0), 1)}, budget {fmt_idr(saved_plan.get('total_harian', 0))}/hari. "
             f"Jalankan budget per iklan itu sampai evaluasi Senin {saved_start + timedelta(days=7):%d/%m}; "
             "angka di bawah adalah hitungan ulang dari data terbaru sebagai pembanding.", UP)
    key_target, key_roas, key_budget = f"adt-target-{periode}", f"adt-roas-{periode}", f"adt-budget-{periode}"
    current_roas = min(math.floor(sales_now / cost_now * 2) / 2, A.MAX_SHOPEE_ROAS) if cost_now > 0 else 0.0
    default_roas = min(float(saved_plan.get("target_roas") or target_roas_for(features, periode) or current_roas or 8.0), A.MAX_SHOPEE_ROAS)
    default_budget = float(saved_plan.get("budget_sisa") or cost_now * days_left)
    with st.container(border=True):
        c1, c2, c3 = st.columns([1.25, 0.8, 1.25])
        with c1:
            target = float(input_rupiah(f"Target sales {month_name}", int(goals.target_sales), key=key_target,
                                        help="Bawaan dari Ubah data latih › Menu upload › Target sales bulanan. Simpan di sini untuk mengganti target bulan ini."))
        if key_roas not in st.session_state or float(st.session_state[key_roas]) > A.MAX_SHOPEE_ROAS:
            st.session_state[key_roas] = default_roas
        roas = float(c2.number_input("Target ROAS", min_value=1.0, max_value=A.MAX_SHOPEE_ROAS, step=0.5, key=key_roas,
                                     help="ROAS rata-rata minimal seluruh iklan produk tunggal & grup di rencana (total omzet iklan ÷ total biaya iklan). "
                                          "Makin rendah, makin banyak budget yang bisa dipakai untuk mengejar omzet. Maks. 30 (batas Shopee; di atasnya ROAS protection mati). "
                                          "Hasil per iklan boleh berbeda-beda; yang dijaga rata-ratanya."))
        with c3:
            budget = float(input_rupiah(f"Budget iklan sisa {days_left} hari", int(default_budget), key=key_budget,
                                        help="Total budget iklan produk tunggal + grup untuk sisa bulan ini, dibagi rata per hari."))
        budget_daily = budget / days_left
        st.markdown(
            f"<div class='field-hint'>Budget ≈ <b>{fmt_idr(budget_daily)}/hari</b> · saat ini {fmt_num(len(running))} iklan produk tunggal & grup berjalan "
            f"{fmt_idr(cost_now)}/hari → omzet iklan {fmt_idr(sales_now)}/hari (ROAS {fmt_num(sales_now / cost_now if cost_now else 0, 1)}). "
            f"Sumber target: {html.escape(goals.target_source)}.</div>",
            unsafe_allow_html=True,
        )

    projection, mtd = float(outlook["projection"]), float(outlook["mtd"])
    rest_pred = projection - mtd
    gap = target - projection
    gap_daily = gap / days_left
    if target <= 0:
        _box("Target bulan ini belum ada", f"Isi target {month_name} di atas atau unggah di Ubah data latih › Menu upload › Target sales bulanan.", DOWN)
        return
    if not has_ads or not units:
        _step(2, "Posisi target")
        st.markdown(_progress_bar(mtd, rest_pred, 0, target), unsafe_allow_html=True)
        st.info("Laporan iklan (grup / keseluruhan) belum diunggah atau tidak ada iklan produk tunggal & grup: rencana iklan butuh riwayat biaya & omzet per iklan.")
        return

    plan = A.allocate_target(units, gap_daily=gap_daily, target_roas=roas, budget_daily=budget_daily)
    eff = A.plan_effect(units, plan, days=days_left)
    final = projection + eff["omzet_tambahan"]
    reach = final / target * 100
    used_daily = sum(plan.cost.values())

    # ---------------- 2. Posisi target
    _step(2, "Posisi target & kesimpulan", f"· aktual 1–{last.day} {month_label(periode)} + prediksi sisa bulan + rencana iklan")
    st.markdown(_progress_bar(mtd, rest_pred, eff["omzet_tambahan"], target), unsafe_allow_html=True)
    k = st.columns(4)
    card(k[0], f"Target {month_label(periode)}", fmt_idr(target),
         hint=f"aktual {fmt_idr(mtd)} · <b style='color:{_tone(False)}'>{fmt_pct(mtd / target * 100, 1)}</b> tercapai")
    card(k[1], "Proyeksi tanpa perubahan", fmt_idr(projection),
         hint=f"aktual + prediksi {days_left} hari · <b style='color:{_tone(projection >= target)}'>{fmt_pct(projection / target * 100, 1)}</b> target"
              + (f" · kurang {fmt_idr(gap)}" if gap > 0 else ""))
    card(k[2], "Proyeksi dengan rencana", fmt_idr(final),
         hint=f"{_signed(eff['omzet_tambahan'])} dari iklan · <b style='color:{_tone(final >= target)}'>{fmt_pct(reach, 1)}</b> target"
              f" · rentang {fmt_idr(projection + eff['rentang'][0])} – {fmt_idr(projection + eff['rentang'][1])}")
    card(k[3], "Budget iklan rencana", fmt_idr(eff["biaya_total"]),
         hint=f"{fmt_idr(used_daily)}/hari · seminggu {fmt_idr(used_daily * 7)} · ROAS rencana {fmt_num(eff['roas_rencana'], 1)}"
              + (f" · sisa budget {fmt_idr(budget - eff['biaya_total'])}" if budget - eff["biaya_total"] > used_daily else " · budget terpakai penuh"))

    # ---------------- 3. Kesimpulan & pilihan
    if gap <= 0:
        _box("✅ Target sudah terkejar tanpa tambahan iklan",
             f"Proyeksi {fmt_idr(projection)} sudah di atas target. Rencana di bawah menjaga ROAS rata-rata ≥ {fmt_num(roas, 1)} "
             "dan memindahkan budget dari iklan yang kurang efektif ke yang lebih efektif.", UP)
    elif final >= target - 1:
        _box("✅ Target tercapai dengan rencana ini",
             f"Budget {fmt_idr(used_daily)}/hari ({fmt_idr(eff['biaya_total'])} untuk {days_left} hari) dengan target ROAS {fmt_num(roas, 1)} mengubah omzet "
             f"{_signed(eff['omzet_tambahan'])}. Jalankan langkah 3 & 4 Senin {week_start:%d/%m}.", UP)
    else:
        short = target - final
        need_daily, max_extra = A.budget_needed(units, gap_daily=gap_daily, target_roas=roas)
        best_roas = A.roas_for_budget(units, gap_daily=gap_daily, budget_daily=budget_daily)
        _floor_need, max_extra_1 = A.budget_needed(units, gap_daily=gap_daily, target_roas=1.0)
        lines = [f"Dengan budget {fmt_idr(budget)} dan target ROAS {fmt_num(roas, 1)}, proyeksi {fmt_idr(final)} (<b>{fmt_pct(reach, 1)}</b>); masih kurang <b>{fmt_idr(short)}</b>."]
        options: list[tuple[str, str, float, bool]] = []
        if need_daily is not None:
            options.append((f"Naikkan budget menjadi {fmt_idr(need_daily * days_left)} (≈ {fmt_idr(need_daily)}/hari), target ROAS tetap {fmt_num(roas, 1)}.",
                            f"Pakai budget {fmt_idr(need_daily * days_left)}", need_daily * days_left, True))
        elif max_extra < 0:
            lines.append(f"Target ROAS {fmt_num(roas, 1)} di atas ROAS iklan sekarang ({fmt_num(sales_now / cost_now if cost_now else 0, 1)}): agar rata-ratanya naik ke "
                         f"{fmt_num(roas, 1)}, iklan yang kurang efektif harus dikurangi sehingga omzet iklan turun {fmt_idr(-max_extra * days_left)}. "
                         "Untuk mengejar target sales, target ROAS perlu diturunkan.")
        else:
            lines.append(f"Pada ROAS {fmt_num(roas, 1)}, iklan produk tunggal & grup paling banyak menambah {fmt_idr(max_extra * days_left)}: berapa pun budgetnya, target belum terkejar.")
        if best_roas is not None and best_roas < roas:
            options.append((f"Turunkan target ROAS ke {fmt_num(best_roas, 1)} dengan budget sekarang.", f"Pakai ROAS {fmt_num(best_roas, 1)}", best_roas, False))
        if projection + max_extra_1 * days_left < target:
            lines.append(f"Iklan saja tidak cukup: bahkan di ROAS 1 tambahan maksimal {_signed(max_extra_1 * days_left)}. "
                         f"Sisa minimal {fmt_idr(target - projection - max_extra_1 * days_left)} perlu dari flash sale, voucher, atau harga (Rekomendasi › Flash sale toko).")
        elif need_daily is None and best_roas is None:
            for r in sorted({max(round(x * 2) / 2, 1.0) for x in (roas * 0.75, roas * 0.5, roas * 0.35, 2.0, 1.0)}, reverse=True):
                need_r, _x = A.budget_needed(units, gap_daily=gap_daily, target_roas=r)
                if need_r is not None:
                    options.append((f"Turunkan target ROAS ke {fmt_num(r, 1)} dan naikkan budget menjadi {fmt_idr(need_r * days_left)}.",
                                    f"Pakai ROAS {fmt_num(r, 1)} + budget", (r, need_r * days_left), None))
                    break
        _box("⚠️ Target belum tercapai dengan setelan ini", "<br>".join(lines) + ("<br><b>Pilihan:</b>" if options else ""), DOWN)
        for index, (text, label, value, is_budget) in enumerate(options):
            left, right = st.columns([3, 1])
            left.markdown(f"<div style='padding:.45rem 0;font-size:.92rem'>{index + 1}. {text}</div>", unsafe_allow_html=True)
            if is_budget is True:
                right.button(label, key=f"adt-opt-{index}", on_click=_set_value, args=(key_budget, value), use_container_width=True)
            elif is_budget is False:
                right.button(label, key=f"adt-opt-{index}", on_click=_set_value, args=(key_roas, value), kwargs={"money": False}, use_container_width=True)
            else:
                def _both(pair=value) -> None:
                    _set_value(key_roas, pair[0], money=False)
                    _set_value(key_budget, pair[1])

                right.button(label, key=f"adt-opt-{index}", on_click=_both, use_container_width=True)

    # ---------------- Skenario ROAS
    with st.expander("Bandingkan target ROAS lain", expanded=gap > 0 and final < target - 1):
        grid = sorted({round(x * 2) / 2 for x in (roas, roas - 4, roas - 2, roas + 2, roas + 4, roas * 0.5, roas * 1.5) if x >= 1})
        rows = []
        for r in grid:
            p = A.allocate_target(units, gap_daily=gap_daily, target_roas=r, budget_daily=budget_daily)
            e = A.plan_effect(units, p, days=days_left)
            need, _x = A.budget_needed(units, gap_daily=gap_daily, target_roas=r)
            rows.append({
                "Target ROAS": f"{fmt_num(r, 1)}" + (" ← setelan" if abs(r - roas) < 0.01 else ""),
                "Budget terpakai": e["biaya_total"], "Omzet tambahan": e["omzet_tambahan"], "% target": (projection + e["omzet_tambahan"]) / target * 100,
                "Budget agar target tercapai": need * days_left if need is not None else np.nan,
                "Dampak margin (info)": e["dampak_margin"],
            })
        frame = pd.DataFrame(rows)
        show_table(frame, kinds={"Budget terpakai": "money", "Omzet tambahan": "money", "% target": "pct", "Budget agar target tercapai": "money", "Dampak margin (info)": "money"},
                   column_config={"Budget agar target tercapai": st.column_config.Column(help="Kosong = pada ROAS ini target tidak terkejar berapa pun budgetnya (tiap iklan maks. 2× budget sekarang per minggu)"),
                                  "Dampak margin (info)": st.column_config.Column(help="Tambahan omzet × kontribusi sebelum iklan − tambahan biaya iklan. Tidak membatasi rencana.")})
        st.caption(f"Semua angka untuk sisa {days_left} hari dengan budget {fmt_idr(budget)}. ROAS lebih rendah = budget lebih mudah terserap dan omzet naik, tetapi efisiensi iklan turun.")

    acts = A.target_actions(units, plan, target_roas=roas)
    selection = A.product_selection(members, units, products, contribution, target_roas=roas, plan=plan)

    # ---------------- 3. Pemilihan produk
    _step(3, "Pemilihan produk iklan", "· siapa masuk iklan tunggal, siapa di grup, siapa dikeluarkan")
    if selection.empty:
        st.info("Belum ada data produk iklan (laporan iklan grup / keseluruhan) untuk dianalisa.")
    else:
        sel_groups = [
            ("Buat iklan tunggal", "🆕", UP, "produk laris belum diiklankan"), ("Jadikan iklan tunggal", "⭐", UP, "andalan di grup"),
            ("Pertahankan iklan tunggal", "✅", "#64748b", ""), ("Tambahkan ke grup", "➕", UP, "belum diiklankan"),
            ("Pertahankan di grup", "✅", "#64748b", ""), ("Pindahkan ke grup", "↘️", DOWN, "iklan tunggal kurang efisien"),
            ("Keluarkan dari grup", "➖", DOWN, "menyedot budget"), ("Jeda sampai restock", "⏸️", DOWN, "stok 0"),
        ]
        chips = []
        for name, icon, color, note in sel_groups:
            count = int((selection["Saran"] == name).sum())
            if count:
                chips.append(f"<span style='border:1px solid #e2e8f0;border-radius:999px;padding:.25rem .75rem;font-size:.85rem;background:#fff'>{icon} "
                             f"<b style='color:{color}'>{name}</b> {fmt_num(count)} produk" + (f" · {note}" if note else "") + "</span>")
        st.markdown("<div style='display:flex;flex-wrap:wrap;gap:.45rem;margin:.2rem 0 .6rem'>" + "".join(chips) + "</div>", unsafe_allow_html=True)
        names = [g[0] for g in sel_groups if (selection["Saran"] == g[0]).any()]
        default_pick = [n for n in names if not n.startswith("Pertahankan")]
        picked = st.multiselect("Tampilkan saran", names, default=default_pick, key="adt-sel-pick", placeholder="Semua saran")
        sel_view = selection.loc[selection["Saran"].isin(picked)] if picked else selection
        sel_kinds = {"Biaya iklan/hari": "money", "Omzet iklan/hari": "money", "ROAS 2 bulan": "dec", "Porsi omzet grup": "pct",
                     "Prediksi omzet/hari": "money", "Stok": "count"}
        batched_view(
            len(sel_view), key="adt-sel", noun="produk",
            render=lambda lo, hi: show_table(sel_view.iloc[lo:hi], kinds=sel_kinds, max_height=10_000,
                                             column_config={"Produk": st.column_config.TextColumn(width="medium"), "Alasan": st.column_config.TextColumn(width="large"),
                                                            "Prediksi omzet/hari": st.column_config.Column(help="Prediksi omzet harian produk dari analisa (semua kanal penjualan)")}),
            download=lambda: download_excel(selection, f"pemilihan_produk_iklan_{periode}.xlsx", key="xl-adt-sel"),
        )
        st.caption(f"Dasar: hasil iklan 2 bulan terakhir per produk, prediksi omzet dari analisa, stok, dan target ROAS {fmt_num(roas, 1)}. "
                   "Jadikan tunggal = porsi omzet ≥ 30% di grup dan ROAS ≥ 80% target; keluarkan/pindahkan = ROAS < 50% target atau biaya tanpa omzet. "
                   "Kerjakan perubahan susunan produk bersamaan dengan perubahan budget hari Senin.")

    # ---------------- 4. Rencana per iklan
    _step(4, "Budget per iklan", f"· ubah di Shopee Senin {week_start:%d/%m}, berlaku s.d. Minggu {week_end:%d/%m}")
    if acts.empty:
        st.info("Tidak ada perubahan iklan yang disarankan.")
    else:
        groups = [
            ("Naikkan budget", "⬆️", UP), ("Buat iklan baru", "🆕", UP), ("Aktifkan kembali", "▶️", UP),
            ("Turunkan budget", "⬇️", DOWN), ("Jeda", "⏸️", DOWN), ("Pertahankan", "➖", "#64748b"),
        ]
        chips = []
        for name, icon, color in groups:
            part = acts.loc[acts["Tindakan"] == name]
            if part.empty:
                continue
            delta = float(part["Perubahan/hari"].sum())
            chips.append(
                f"<span style='border:1px solid #e2e8f0;border-radius:999px;padding:.25rem .75rem;font-size:.85rem;background:#fff'>{icon} <b>{name}</b> "
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
                "ROAS bulan terakhir", "Tambahan omzet/hari", "Catatan"]
        kinds = {"Budget harian sekarang": "money", "Budget harian usulan": "money", "Perubahan/hari": "money", "Tambahan omzet/hari": "money",
                 "Anggota": "count", "ROAS bulan terakhir": "dec", "Target ROAS Shopee": "dec"}
        settings = pd.DataFrame([
            {"Setelan": "Bulan", "Nilai": month_name}, {"Setelan": "Minggu", "Nilai": week_text}, {"Setelan": "Target sales", "Nilai": fmt_idr(target)},
            {"Setelan": "Target ROAS", "Nilai": fmt_num(roas, 1)}, {"Setelan": f"Budget sisa {days_left} hari", "Nilai": fmt_idr(budget)},
            {"Setelan": "Proyeksi dengan rencana", "Nilai": f"{fmt_idr(final)} ({fmt_pct(reach, 1)})"},
        ])
        batched_view(
            len(shown), key="adt-units", noun="iklan",
            render=lambda lo, hi: show_table(shown.iloc[lo:hi][cols], kinds=kinds, max_height=10_000,
                                             column_config={"Iklan": st.column_config.TextColumn(width="medium"), "Catatan": st.column_config.TextColumn(width="large"),
                                                            "Target ROAS Shopee": st.column_config.Column(help="ROAS rata-rata iklan ini pada budget usulan (maks. 30); isi di pengaturan iklan GMV Max ROAS Shopee")}),
            download=lambda: download_excel({"Setelan": settings, "Rencana per iklan": acts[cols], "Pemilihan produk": selection}, f"strategi_iklan_{periode}.xlsx", key="xl-adt"),
        )
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
        f"<b>Senin {week_start:%d/%m}</b> — ubah susunan produk (langkah 3) serta budget harian & Target ROAS tiap iklan (langkah 4) di Shopee, lalu tekan Simpan di bawah. "
        "Budget naik maks. 2× atau turun ke ≥ ½ agar ROAS protection tetap aktif.",
        "<b>Selasa–Minggu</b> — jangan ubah budget; biarkan algoritma Shopee belajar. Pantau stok produk yang ditandai ⚠️.",
        f"<b>Senin {next_monday:%d/%m}</b> — unggah laporan iklan minggu lalu, buka menu ini, evaluasi pencapaian; bila masih di bawah target, "
        "naikkan lagi budget iklan yang efektif (maks. 2×) atau turunkan target ROAS lewat tombol pilihan.",
        "<b>Akhir bulan</b> — evaluasi di Laporan › Iklan; unggah target bulan berikutnya di Ubah data latih › Menu upload › Target.",
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
                                "di luar batas itu ROAS protection Shopee mati"),
            ("Siklus", "rencana berlaku Senin–Minggu dan dievaluasi tiap Senin dengan laporan iklan terbaru; proyeksi menganggap budget minggu ini dipakai sampai akhir bulan"),
            ("Pemilihan produk", "per produk: ROAS & porsi omzet di grup (2 bulan terakhir), prediksi omzet dari analisa, dan stok"),
            ("Margin & stok", "tidak membatasi rencana; tampil sebagai catatan per iklan"),
            ("Proyeksi tanpa perubahan", "penjualan aktual bulan ini + prediksi harian × sisa hari (sama dengan Kalkulator biaya)"),
        ])
    if st.button(f"Simpan rencana minggu {week_text}", key="adt-save", type="primary", disabled=not can_edit):
        from auth.ui import require

        require("rekomendasi", "edit")
        payload = {
            "target_roas": roas, "budget_sisa": budget, "hari": days_left, "strategi": "Kejar target", "minggu": week_start.isoformat(),
            "total_harian": used_daily,
            "produk": {r["Kode produk"]: r["Saran"] for r in selection.to_dict("records") if not str(r["Saran"]).startswith("Pertahankan")} if not selection.empty else {},
            "iklan": {r["Iklan"]: {"tindakan": r["Tindakan"], "budget_harian": r["Budget harian usulan"], "target_roas": r["Target ROAS Shopee"]}
                      for r in acts.to_dict("records") if r["Tindakan"] != "Pertahankan"} if not acts.empty else {},
        }
        features.replace(
            "sales_target",
            [{"periode": periode, "target_sales_bersih": target, "margin_min_pct": float(saved.get("margin_min_pct", 0) or 0), "strategi": "Kejar target",
              "budget_json": json.dumps(payload, default=float), "set_by": username}],
            keys=["periode"], username=username, action="kirim:rencana_iklan",
        )
        bump(st.session_state)
        st.success(f"Target {month_name}, target ROAS {fmt_num(roas, 1)}, budget {fmt_idr(budget)}, dan rencana per iklan tersimpan.")
