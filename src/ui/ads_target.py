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
from src.core import campaigns as C
from src.core.business import business_targets
from src.core.campaigns import as_date
from src.core.fmt import fmt_date
from src.ui import campaign_ui as cmp
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


ACT_COLS = ["Tindakan", "Iklan", "Jenis", "Anggota", "Budget harian sekarang", "Budget harian usulan", "Perubahan/hari", "Target ROAS Shopee",
            "ROAS bulan terakhir", "Prediksi omzet produk/hari", "Omzet iklan usulan/hari", "Tambahan omzet/hari", "Catatan"]
ACT_KINDS = {"Budget harian sekarang": "money", "Budget harian usulan": "money", "Perubahan/hari": "money", "Tambahan omzet/hari": "money",
             "Prediksi omzet produk/hari": "money", "Omzet iklan usulan/hari": "money",
             "Anggota": "count", "ROAS bulan terakhir": "dec", "Target ROAS Shopee": "dec"}
SEL_KINDS = {"Biaya iklan/hari": "money", "Omzet iklan/hari": "money", "ROAS 2 bulan": "dec", "Porsi omzet grup": "pct",
             "Prediksi omzet/hari": "money", "Stok": "count", "Budget usulan iklan/hari": "money"}


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
    full = (*key, tuple(weeks), round(gap), lift, len(units), round(sum(u.daily_cost for u in units)))
    if full not in cache:
        if len(cache) > 8:
            cache.clear()
        cache[full] = A.recommend(units, members, products, contribution, weeks=weeks, gap_total=gap, lift=lift)
    return cache[full]


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


def _locked_view(cur: dict, *, units, members, products, contribution, projection: float, mtd: float, target_now: float, today: date,
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
            fresh_units, fresh_plan, _sel = A.build_plan(units, members, products, contribution, gap_daily=(goal - projection) / run_days,
                                                         target_roas=roas, budget_daily=budget_daily, lift=lift)
            steps = A.ramp(fresh_units, weeks=weeks, gap_total=goal - projection, target_roas=roas, budget_total=budget_daily * run_days, first=fresh_plan)
            eff = A.ramp_effect(fresh_units, steps)
            fresh_acts = A.target_actions(fresh_units, fresh_plan, target_roas=roas)
        extra, final = eff["omzet_tambahan"], projection + eff["omzet_tambahan"]
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
             + "<br>Saran: buat campaign baru dari saran hari ini. Campaign ini baru dihentikan saat campaign baru disimpan.", DOWN)
        st.button("Buat campaign baru dari saran", key="adt-renew", on_click=cmp.switch_to_new, args=("iklan",), type="primary")
    else:
        _box("✅ Campaign masih sejalan dengan target",
             f"Dicek dengan data {fmt_date(today)}: target sama, budget saran per iklan tidak jauh berbeda, proyeksi {fmt_idr(final)}"
             + (f" ({fmt_pct(final / goal * 100, 1)} target)" if goal > 0 else "") + ". Jalankan budget per iklan di bawah sampai periode selesai.", UP)
    if goal > 0:
        st.markdown(_progress_bar(mtd, projection - mtd, extra, goal), unsafe_allow_html=True)
    k = st.columns(4)
    card(k[0], "Target", fmt_idr(goal), hint=f"aktual {fmt_idr(mtd)} · <b style='color:{_tone(mtd >= goal)}'>{fmt_pct(mtd / goal * 100 if goal else 0, 1)}</b> tercapai")
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
    mode, cur = cmp.panel("iklan", features=features, today=today, can_edit=can_edit, username=username, describe=_describe)

    has_ads = frames is not None and any(isinstance(f, pd.DataFrame) and not f.empty for f in (getattr(frames, "ads", []) or []))
    units, members, contribution, products = [], pd.DataFrame(), {}, pd.DataFrame()
    if has_ads and inputs is not None:
        with st.spinner("Membaca riwayat iklan produk tunggal & grup..."):
            units, members, contribution, products = inputs(table, features, frames, days_left)
    running = [u for u in units if u.daily_cost > 0 and A._running(u)]
    cost_now = sum(u.daily_cost for u in running)
    sales_now = sum(u.daily_sales for u in running)
    projection, mtd = float(outlook["projection"]), float(outlook["mtd"])

    if mode == cmp.SAVED and cur is not None:
        _locked_view(cur, units=units, members=members, products=products, contribution=contribution, projection=projection, mtd=mtd,
                     target_now=float(goals.target_sales), today=today, first_open=first_open, month_end=month_end, periode=periode, has_ads=has_ads)
        return

    # ---------------- 1. Setelan
    hi = max(month_end, today + timedelta(days=6))
    default_start = max(today, first_open) if max(today, first_open) <= month_end else today
    with st.container(border=True):
        start, end = cmp.period_picker(key=f"adt-period-{periode}", today=today, hi=hi,
                                       default=(default_start, month_end if month_end >= default_start else default_start + timedelta(days=6)))
    period_days = (end - start).days + 1
    week_text = f"{fmt_date(start)} – {fmt_date(end)}"
    _step(1, "Setelan", f"· {month_name}, sisa {days_left} hari data · campaign {week_text} ({period_days} hari), dievaluasi tiap Senin")
    key_target, key_roas, key_budget = f"adt-target-{periode}", f"adt-roas-{periode}", f"adt-budget-{periode}-{start}-{end}"
    key_lift = f"adt-lift-{periode}"
    current_roas = min(math.floor(sales_now / cost_now * 2) / 2, A.MAX_SHOPEE_ROAS) if cost_now > 0 else 0.0
    default_roas = min(float(saved_plan.get("target_roas") or target_roas_for(features, periode) or current_roas or 8.0), A.MAX_SHOPEE_ROAS)
    default_budget = float(cost_now * period_days)
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([1.2, 0.7, 1.2, 0.9])
        with c1:
            target = float(input_rupiah(f"Target sales {month_name}", int(goals.target_sales), key=key_target,
                                        help="Bawaan dari Upload data › Target sales bulanan. Simpan di sini untuk mengganti target bulan ini."))
        if key_roas not in st.session_state or float(st.session_state[key_roas]) > A.MAX_SHOPEE_ROAS:
            st.session_state[key_roas] = default_roas
        roas = float(c2.number_input("Target ROAS", min_value=1.0, max_value=A.MAX_SHOPEE_ROAS, step=0.5, key=key_roas,
                                     help="ROAS rata-rata minimal seluruh iklan produk tunggal & grup di rencana (total omzet iklan ÷ total biaya iklan). "
                                          "Makin rendah, makin banyak budget yang bisa dipakai untuk mengejar omzet. Maks. 30 (batas Shopee; di atasnya ROAS protection mati). "
                                          "Hasil per iklan boleh berbeda-beda; yang dijaga rata-ratanya."))
        with c3:
            budget = float(input_rupiah(f"Budget iklan campaign ({period_days} hari)", int(default_budget), key=key_budget,
                                        help="Total budget iklan produk tunggal + grup untuk periode campaign, dibagi rata per hari."))
        if st.session_state.get(key_lift) not in LIFTS:
            st.session_state[key_lift] = A.DEMAND_LIFT
        lift = float(c4.selectbox("Daya dorong iklan maks.", LIFTS, format_func=LIFT_LABELS.get, key=key_lift,
                                  help="Asumsi berapa besar iklan bisa menambah omzet sebuah produk dibanding prediksi omzetnya tanpa iklan. "
                                       "Konservatif +50% = bawaan. Makin besar, makin banyak budget yang dianggap masih menghasilkan omzet."))
        budget_daily = budget / period_days
        st.markdown(
            f"<div class='field-hint'>Budget ≈ <b>{fmt_idr(budget_daily)}/hari</b> · saat ini {fmt_num(len(running))} iklan produk tunggal & grup berjalan "
            f"{fmt_idr(cost_now)}/hari → omzet iklan {fmt_idr(sales_now)}/hari (ROAS {fmt_num(sales_now / cost_now if cost_now else 0, 1)}). "
            f"Sumber target: {html.escape(goals.target_source)}.</div>",
            unsafe_allow_html=True,
        )

    rest_pred = projection - mtd
    gap = target - projection
    if target <= 0:
        _box("Target bulan ini belum ada", f"Isi target {month_name} di atas atau unggah di Upload data › Target sales bulanan.", DOWN)
        return
    if not has_ads or not units:
        _step(2, "Posisi target")
        st.markdown(_progress_bar(mtd, rest_pred, 0, target), unsafe_allow_html=True)
        st.info("Laporan iklan (grup / keseluruhan) belum diunggah atau tidak ada iklan produk tunggal & grup: rencana iklan butuh riwayat biaya & omzet per iklan.")
        return

    blocks = _blocks(start, end, first_open, month_end)
    weeks = [(b - a).days + 1 for a, b in blocks]
    run_days = sum(weeks)
    gap_daily = gap / run_days
    base_units = units
    rec = alt = None
    if gap > 0:
        with st.spinner("Mencari target ROAS & budget yang menutup target dengan iklan saja..."):
            rec = _recommendation(base_units, members, products, contribution, weeks=weeks, gap=gap, lift=lift, key=(periode, start, end))
            if not rec["tercapai"]:
                for other in (x for x in LIFTS if x > lift):
                    alt = _recommendation(base_units, members, products, contribution, weeks=weeks, gap=gap, lift=other, key=(periode, start, end))
                    if alt["tercapai"]:
                        alt = {**alt, "lift": other}
                        break
                    alt = None

    with st.spinner("Menyusun pemilihan produk & budget per iklan..."):
        units, plan, selection = A.build_plan(base_units, members, products, contribution, gap_daily=gap_daily, target_roas=roas, budget_daily=budget_daily, lift=lift)
        steps = A.ramp(units, weeks=weeks, gap_total=gap, target_roas=roas, budget_total=budget_daily * run_days, first=plan)
    eff = A.ramp_effect(units, steps)
    week_table = A.weekly_table(units, steps, blocks)
    final = projection + eff["omzet_tambahan"]
    reach = final / target * 100
    used_daily = sum(plan.cost.values())
    avg_daily = eff["biaya_total"] / run_days
    unused = budget_daily * run_days - eff["biaya_total"]

    # ---------------- Rekomendasi
    rec_budget = math.ceil(rec["budget"] / run_days * period_days / 1_000_000) * 1_000_000 if rec else 0.0
    rec_used = bool(rec) and abs(roas - rec["roas"]) < 0.01 and abs(budget - rec_budget) <= max(0.01 * rec_budget, 1.0)
    if rec is not None:
        rec_final = projection + rec["tambahan"]
        head = (f"Target ROAS <b>{fmt_num(rec['roas'], 1)}</b> · budget <b>{fmt_idr(rec_budget)}</b> untuk {period_days} hari "
                f"(rata-rata {fmt_idr(rec['budget'] / run_days)}/hari, naik bertahap tiap minggu) → proyeksi <b>{fmt_idr(rec_final)}</b> "
                f"(<b style='color:{_tone(rec['tercapai'])}'>{fmt_pct(rec_final / target * 100, 1)}</b> target).")
        if rec["tercapai"]:
            body = head + " Ini target ROAS tertinggi yang masih menutup target dengan iklan saja; flash sale & exposure jadi tambahan di atasnya."
        else:
            body = (head + f"<br>Dengan asumsi daya dorong iklan maks. +{lift * 100:.0f}%, iklan saja paling banyak mencapai angka di atas: "
                    f"masih kurang <b>{fmt_idr(target - rec_final)}</b>. Menurunkan ROAS lebih jauh tidak menambah omzet karena permintaan produk yang diiklankan sudah penuh.")
            if alt is not None:
                alt_budget = math.ceil(alt["budget"] / run_days * period_days / 1_000_000) * 1_000_000
                body += (f"<br>Bila iklan dianggap bisa mendorong sampai +{alt['lift'] * 100:.0f}% prediksi omzet produk, target tercapai dengan "
                         f"target ROAS <b>{fmt_num(alt['roas'], 1)}</b> dan budget <b>{fmt_idr(alt_budget)}</b>.")
            else:
                body += "<br>Kekurangannya dikejar lewat kegiatan tambahan (flash sale, exposure, voucher) yang tidak dihitung di sini."
        if rec_used:
            body += "<br>✓ Setelan di atas sudah memakai rekomendasi ini."
        _box("💡 Rekomendasi sistem" + ("" if rec["tercapai"] else " (maksimal dari iklan)"), body, UP if rec["tercapai"] else "#b45309")
        b1, b2, _b3 = st.columns([1, 1.4, 1.6])
        b1.button("Pakai rekomendasi", key="adt-use-rec", type="primary", disabled=rec_used, use_container_width=True,
                  on_click=_apply, args=(key_roas, rec["roas"], key_budget, rec_budget))
        if alt is not None:
            b2.button(f"Pakai asumsi +{alt['lift'] * 100:.0f}% & rekomendasinya", key="adt-use-alt", use_container_width=True,
                      on_click=_apply, args=(key_roas, alt["roas"], key_budget, alt_budget), kwargs={"lift_key": key_lift, "lift": alt["lift"]})

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
    card(k[3], "Budget iklan terpakai", fmt_idr(eff["biaya_total"]),
         hint=f"rata-rata {fmt_idr(avg_daily)}/hari · minggu 1 {fmt_idr(used_daily)}/hari · ROAS rencana {fmt_num(eff['roas_rencana'], 1)}"
              + (f" · <b style='color:{DOWN}'>tidak terserap {fmt_idr(unused)}</b>" if unused > max(0.01 * budget, 1.0) else " · budget terpakai penuh"))
    base_sales = sum(A._now_sales(u) for u in units)
    plan_sales = eff["omzet_iklan"] / run_days
    demand_total = sum(u.demand for u in units if not u.locked and np.isfinite(u.demand))
    st.markdown(
        "<div class='field-hint' style='margin-top:.4rem'><b>Cek angka:</b> "
        f"omzet iklan sekarang {fmt_idr(base_sales)}/hari → rencana rata-rata {fmt_idr(plan_sales)}/hari "
        f"(budget rata-rata {fmt_idr(avg_daily)}/hari × ROAS rencana {fmt_num(eff['roas_rencana'], 1)}). "
        f"Selisih {_signed(plan_sales - base_sales)}/hari × {run_days} hari = <b>{_signed(eff['omzet_tambahan'])}</b>, "
        f"jadi proyeksi {fmt_idr(projection)} {_signed(eff['omzet_tambahan'])} = <b>{fmt_idr(final)}</b>. "
        f"Tambahan tiap iklan dibatasi maks. +{lift * 100:.0f}% dari prediksi omzet produknya "
        f"(total prediksi produk yang diiklankan {fmt_idr(demand_total)}/hari; satu produk dihitung di satu iklan saja). "
        "Flash sale & exposure tidak dihitung.</div>",
        unsafe_allow_html=True,
    )

    # ---------------- Kesimpulan
    if gap <= 0:
        _box("✅ Target sudah terkejar tanpa tambahan iklan",
             f"Proyeksi {fmt_idr(projection)} sudah di atas target. Rencana di bawah menjaga ROAS rata-rata ≥ {fmt_num(roas, 1)} "
             "dan memindahkan budget dari iklan yang kurang efektif ke yang lebih efektif.", UP)
    elif final >= target - 1:
        _box("✅ Target tercapai dengan setelan ini",
             f"Budget {fmt_idr(eff['biaya_total'])} untuk {run_days} hari (minggu 1 {fmt_idr(used_daily)}/hari, lalu naik bertahap) dengan target ROAS "
             f"{fmt_num(roas, 1)} menambah omzet {_signed(eff['omzet_tambahan'])}. Jalankan langkah 3 & 4 mulai {fmt_date(start)}.", UP)
    else:
        lines = [f"Dengan budget {fmt_idr(budget)} dan target ROAS {fmt_num(roas, 1)}, proyeksi {fmt_idr(final)} (<b>{fmt_pct(reach, 1)}</b>); "
                 f"masih kurang <b>{fmt_idr(target - final)}</b>."]
        if unused > max(0.01 * budget, 1.0):
            lines.append(f"<b>{fmt_idr(unused)}</b> budget tidak terserap: pada target ROAS {fmt_num(roas, 1)} iklan tidak bisa memakai lebih banyak tanpa "
                         f"ROAS rata-rata turun di bawah {fmt_num(roas, 1)}, jadi menaikkan budget saja tidak mengubah hasil. Turunkan target ROAS.")
        else:
            lines.append("Budget terpakai penuh: naikkan budget (target ROAS bisa tetap) agar omzet iklan bertambah.")
        if rec is not None and not rec_used:
            lines.append("Atau tekan <b>Pakai rekomendasi</b> di atas.")
        _box("⚠️ Target belum tercapai dengan setelan ini", "<br>".join(lines), DOWN)

    # ---------------- Skenario ROAS
    if rec is not None and not rec["tabel"].empty:
        with st.expander("Bandingkan target ROAS lain (budget tidak dibatasi)", expanded=False):
            frame = rec["tabel"].rename(columns={"roas": "Target ROAS", "budget": "Budget terserap", "tambahan": "Omzet tambahan", "roas_rencana": "ROAS rencana"})
            frame["Budget terserap"] = frame["Budget terserap"] / run_days * period_days
            frame["% target"] = (projection + frame["Omzet tambahan"]) / target * 100
            frame["Target ROAS"] = frame["Target ROAS"].map(lambda r: fmt_num(r, 1) + (" ← rekomendasi" if abs(r - rec["roas"]) < 0.01 else ""))
            show_table(frame, kinds={"Budget terserap": "money", "Omzet tambahan": "money", "% target": "pct", "ROAS rencana": "dec"},
                       column_config={"Budget terserap": st.column_config.Column(help=f"Budget campaign ({period_days} hari) yang bisa dipakai pada ROAS ini; di atasnya tidak terserap")})
            st.caption(f"Dicoba dari ROAS tertinggi; berhenti saat target tercapai atau omzet tidak bertambah lagi. Asumsi daya dorong iklan maks. +{lift * 100:.0f}%.")

    acts = A.target_actions(units, plan, target_roas=roas)

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
        selection = selection.drop(columns=["_unit"], errors="ignore")
        sel_view = selection.loc[selection["Saran"].isin(picked)] if picked else selection
        sel_kinds = {"Biaya iklan/hari": "money", "Omzet iklan/hari": "money", "ROAS 2 bulan": "dec", "Porsi omzet grup": "pct",
                     "Prediksi omzet/hari": "money", "Stok": "count", "Budget usulan iklan/hari": "money"}
        batched_view(
            len(sel_view), key="adt-sel", noun="produk",
            render=lambda lo, hi: show_table(sel_view.iloc[lo:hi], kinds=sel_kinds, max_height=10_000,
                                             column_config={"Produk": st.column_config.TextColumn(width="medium"), "Alasan": st.column_config.TextColumn(width="large"),
                                                            "Prediksi omzet/hari": st.column_config.Column(help="Prediksi omzet harian produk dari analisa (semua kanal penjualan)"),
                                                            "Iklan di rencana": st.column_config.Column(help="Iklan tempat produk ini berada sesudah perubahan; sama dengan baris di langkah 4"),
                                                            "Budget usulan iklan/hari": st.column_config.Column(help="Budget harian usulan iklan tersebut di langkah 4 (untuk grup: budget seluruh grup)")}),
            download=lambda: download_excel(selection, f"pemilihan_produk_iklan_{periode}.xlsx", key="xl-adt-sel"),
        )
        dup_count = int((selection["Saran"] == "Sudah di iklan lain").sum())
        if dup_count:
            st.caption(f"{fmt_num(dup_count)} baris lain adalah produk di iklan yang sudah dijeda/berakhir yang juga ada di iklan aktif: "
                       "tidak perlu tindakan, omzetnya hanya dihitung di iklan aktifnya (ada di unduhan Excel).")
        st.caption(f"Dasar: hasil iklan 2 bulan terakhir per produk, prediksi omzet dari analisa, stok, dan target ROAS {fmt_num(roas, 1)}. "
                   "Jadikan tunggal = porsi omzet ≥ 30% di grup dan ROAS ≥ 80% target; keluarkan/pindahkan = ROAS < 50% target atau biaya tanpa omzet. "
                   "Satu produk hanya di satu iklan. Budget di langkah 4 sudah dihitung dengan susunan ini: produk yang dikeluarkan/dijeda tidak lagi "
                   "dihitung omzetnya, iklan tunggal hasil pisah mengambil budget dari grup asalnya. Kerjakan bersamaan dengan perubahan budget hari Senin.")

    # ---------------- 4. Rencana per iklan
    _step(4, "Budget per iklan", f"· ubah di Shopee mulai {fmt_date(start)}, berlaku s.d. {fmt_date(end)}")
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
        f"<b>{fmt_date(start)}</b> — ubah susunan produk (langkah 3) serta budget harian & Target ROAS tiap iklan (langkah 4) di Shopee, lalu simpan sebagai campaign di bawah agar terkunci. "
        "Budget naik maks. 2× atau turun ke ≥ ½ agar ROAS protection tetap aktif.",
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
                                "di luar batas itu ROAS protection Shopee mati"),
            ("Siklus", "rencana dibagi per minggu: budget tiap iklan boleh naik maks. 2× dari minggu sebelumnya, jadi budget bisa naik bertahap sampai akhir bulan; "
                       "pelaksanaan dievaluasi tiap hari dari laporan iklan terbaru"),
            ("Rekomendasi", "dicoba dari target ROAS tertinggi (30) ke bawah; dipilih ROAS tertinggi yang menutup kekurangan target dengan iklan saja, "
                            "budgetnya = budget yang terserap pada ROAS itu. Flash sale & exposure tidak dihitung (tambahan di luar iklan)"),
            ("Pemilihan produk", "per produk: ROAS & porsi omzet di grup (2 bulan terakhir), prediksi omzet dari analisa, dan stok"),
            ("Satu alur", "pemilihan produk dihitung dulu, lalu susunan iklan diubah (anggota keluar/dijeda dilepas, andalan dipisah jadi iklan tunggal, "
                          "produk laris belum diiklankan dibuatkan iklan), baru budget dibagi. Usulan iklan tunggal yang tidak kebagian budget dikembalikan ke grup"),
            ("Daya dorong iklan", f"tambahan omzet sebuah iklan maks. +{lift * 100:.0f}% dari prediksi omzet produk anggotanya (setelan), "
                                 "supaya rencana tidak menjanjikan omzet melebihi permintaan; produk yang ada di beberapa iklan dihitung di satu iklan saja"),
            ("Margin & stok", "tidak membatasi rencana; tampil sebagai catatan per iklan"),
            ("Proyeksi tanpa perubahan", "penjualan aktual bulan ini + prediksi harian × sisa hari (sama dengan Kalkulator biaya)"),
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

        keep = selection.loc[selection["Saran"] != "Sudah di iklan lain"] if not selection.empty else selection
        cmp.save_controls(
            "iklan", features=features, today=today, start=start, end=end, cur=cur, can_edit=can_edit, username=username, after_save=_to_target,
            default_name=f"Iklan {month_name} · ROAS {fmt_num(roas, 1)} · {fmt_date(start)} – {fmt_date(end)}",
            payload={"setelan": {"periode_target": periode, "target": target, "roas": roas, "budget": budget, "budget_harian": budget_daily,
                                 "budget_rencana_harian": used_daily, "proyeksi": final, "capaian": reach, "hari_hitung": run_days, "daya_dorong": lift},
                     "rekomendasi": ({"roas": rec["roas"], "budget": rec_budget, "proyeksi": projection + rec["tambahan"],
                                      "capaian": (projection + rec["tambahan"]) / target * 100, "tercapai": rec["tercapai"], "dipakai": rec_used} if rec else None),
                     "jadwal_minggu": cmp.records_of(week_table),
                     "iklan_minggu": cmp.records_of(unit_weeks),
                     "baseline": A.month_totals(base_units),
                     "iklan": cmp.records_of(acts.reindex(columns=[*ACT_COLS, "key"])) if not acts.empty else [],
                     "produk": cmp.records_of(keep)},
        )
