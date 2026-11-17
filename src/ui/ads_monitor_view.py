"""UI Pantau rencana tersimpan: cockpit marketing untuk pelaksanaan campaign vs Seller Center."""

from __future__ import annotations

import html
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src.core import ads_monitor as Mon
from src.core import ads_strategy as A
from src.core import campaigns as C
from src.core.fmt import fmt_date
from src.ui import campaign_ui as cmp
from src.ui.common import batched_view, card, download_excel, fmt_idr, fmt_num, fmt_pct
from src.utils.format import show_table as _show_table
from functools import partial

show_table = partial(_show_table, dash_missing=True)

UP, WARN, DOWN, MUTED = "#059669", "#d97706", "#dc2626", "#64748b"
LEVEL_COLOR = {"ok": UP, "warn": WARN, "alert": DOWN, "info": MUTED}

ACT_COLS = ["Tindakan", "Iklan", "Jenis", "Anggota", "Budget harian sekarang", "Budget harian usulan", "Perubahan/hari", "Target ROAS Shopee",
            "ROAS bulan terakhir", "Prediksi omzet produk/hari", "Omzet iklan usulan/hari", "Tambahan omzet/hari", "Catatan"]
ACT_KINDS = {"Budget harian sekarang": "money", "Budget harian usulan": "money", "Perubahan/hari": "money", "Tambahan omzet/hari": "money",
             "Prediksi omzet produk/hari": "money", "Omzet iklan usulan/hari": "money",
             "Anggota": "count", "ROAS bulan terakhir": "dec", "Target ROAS Shopee": "dec"}
SEL_KINDS = {"Biaya iklan/hari": "money", "Omzet iklan/hari": "money", "ROAS 2 bulan": "dec", "Porsi omzet grup": "pct",
             "Prediksi omzet/hari": "money", "Prediksi qty/hari": "dec", "Stok": "count", "Budget usulan iklan/hari": "money"}


def _tone(ok: bool) -> str:
    return UP if ok else DOWN


def _signed(value: float) -> str:
    return ("+" if value >= 0 else "−") + fmt_idr(abs(value))


def _box(title: str, body: str, color: str) -> None:
    st.markdown(
        f"<div style='border:1px solid #e2e8f0;border-left:5px solid {color};border-radius:14px;background:#fff;"
        f"padding:.85rem 1.05rem;margin:.55rem 0;box-shadow:0 8px 24px rgba(15,23,42,.04)'>"
        f"<div style='font-weight:800;color:{color};margin-bottom:.3rem;letter-spacing:.01em'>{title}</div>"
        f"<div style='font-size:var(--fs-base);line-height:1.65;color:#1f2937'>{body}</div></div>",
        unsafe_allow_html=True,
    )


def _hero(verdict: dict) -> None:
    color = LEVEL_COLOR.get(verdict["level"], MUTED)
    st.markdown(
        f"<div style='border-radius:18px;padding:1.1rem 1.25rem;margin:.2rem 0 .85rem;"
        f"background:linear-gradient(135deg,#0f172a 0%,#1e293b 55%,#334155 100%);color:#fff;"
        f"box-shadow:0 12px 32px rgba(15,23,42,.18)'>"
        f"<div style='display:flex;flex-wrap:wrap;gap:.75rem 1.25rem;align-items:center;justify-content:space-between'>"
        f"<div><div style='font-size:var(--fs-xs);opacity:.75;text-transform:uppercase;letter-spacing:.08em;font-weight:700'>"
        f"Pantau rencana tersimpan</div>"
        f"<div style='font-size:1.35rem;font-weight:800;margin-top:.2rem'>{html.escape(verdict['title'])}</div>"
        f"<div style='opacity:.9;margin-top:.35rem;line-height:1.55;max-width:52rem'>{html.escape(verdict['blurb'])}</div></div>"
        f"<div style='background:{color};color:#fff;border-radius:999px;padding:.45rem .9rem;font-weight:800;font-size:var(--fs-sm);white-space:nowrap'>"
        f"{verdict['done']}/{verdict['total']} sesuai Seller Center</div></div></div>",
        unsafe_allow_html=True,
    )


def _progress_bar(actual: float, rest: float, extra: float, target: float) -> str:
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
        "<div style='position:relative;margin:1.4rem 0 .2rem'>"
        "<div style='display:flex;height:22px;border-radius:999px;overflow:hidden;background:#e2e8f0'>"
        + seg(actual, "#1e3a8a", "Aktual") + seg(rest, "#93c5fd", "Prediksi sisa bulan") + seg(extra, "#ee4d2d", "Tambahan iklan")
        + "</div>" + marker + "</div>" + legend
    )


def _report_end(totals: dict[str, dict]) -> date | None:
    ends = [date.fromisoformat(str(v["periode"])[:10]) + timedelta(days=int(v["hari"]) - 1) for v in totals.values() if v.get("hari")]
    return max(ends) if ends else None


def _kinds_from(units, weekly, acts_saved) -> dict[str, str]:
    kinds: dict[str, str] = {}
    for u in units or []:
        kinds[u.key] = "Grup" if u.jenis.startswith("Grup") else "Produk tunggal"
    if isinstance(weekly, pd.DataFrame) and not weekly.empty and {"_key", "Jenis"} <= set(weekly.columns):
        for k, j in zip(weekly["_key"], weekly["Jenis"]):
            kinds[str(k)] = "Grup" if str(j).startswith("Grup") else "Produk tunggal"
    if isinstance(acts_saved, pd.DataFrame) and not acts_saved.empty and {"key", "Jenis"} <= set(acts_saved.columns):
        for k, j in zip(acts_saved["key"], acts_saved["Jenis"]):
            kinds[str(k)] = "Grup" if str(j).startswith("Grup") else "Produk tunggal"
    return kinds


def _planned_budgets(cur: dict, *, start: date, report_end: date | None) -> dict[str, float]:
    weekly = cmp.frame_of(cur.get("iklan_minggu"))
    week_no = ((report_end - start).days // 7 + 1) if report_end else 1
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
    return planned


def render_monitor(cur: dict, *, units, members, products, contribution, projection: float, mtd: float, target_now: float,
                   today: date, factor: float, first_open: date, month_end: date, periode: str, has_ads: bool,
                   track: dict | None = None, project_fn=None) -> None:
    """Tampilan utama Pantau rencana tersimpan."""
    from src.ui.ads_target import VIEW_REC, _blocks, _not_advertised, _calendar_view  # late import: hindari siklus

    s = cur.get("setelan") or {}
    start, end = C.as_date(cur["mulai"]), C.as_date(cur["selesai"])
    acts_saved = cmp.frame_of(cur.get("iklan"))
    sel_saved = cmp.frame_of(cur.get("produk"))
    target = float(s.get("target") or 0)
    goal = target_now if target_now > 0 else target
    roas = float(s.get("roas") or 8.0)
    budget_daily = float(s.get("budget_harian") or 0)
    week_start, week_end = Mon.week_window(today)

    # ---- hitung ulang proyeksi & beda saran (toleransi minimum Shopee)
    reasons: list[str] = []
    if s.get("periode_target") and s["periode_target"] != periode:
        reasons.append(f"campaign dibuat untuk target bulan lain ({s['periode_target']}), data sekarang {periode}")
    if target_now > 0 and abs(target_now - target) > max(1.0, 0.01 * target):
        reasons.append(f"target bulan berubah dari {fmt_idr(target)} menjadi {fmt_idr(target_now)}")
    lift = float(s.get("daya_dorong") or A.DEMAND_LIFT)
    blocks = _blocks(max(start, today), max(end, today), first_open, month_end)
    weeks = [(b - a).days + 1 for a, b in blocks]
    run_days = max(sum(weeks), 1)
    extra, final, diff = 0.0, projection, pd.DataFrame()
    if has_ads and units and goal > 0:
        with st.spinner("Mencocokkan campaign dengan data & laporan terbaru..."):
            fresh_units, fresh_plan, _sel = A.build_plan(
                units, members, products, contribution, gap_daily=(goal - projection) / factor / run_days,
                target_roas=roas, budget_daily=budget_daily, lift=lift, stock_cap=True)
            steps = A.ramp(fresh_units, weeks=weeks, gap_total=(goal - projection) / factor, target_roas=roas,
                           budget_total=budget_daily * run_days, first=fresh_plan)
            eff = A.ramp_effect(fresh_units, steps)
            fresh_acts = A.target_actions(fresh_units, fresh_plan, target_roas=roas)
        extra = eff["omzet_tambahan"] * factor
        final = projection + extra
        if project_fn is not None:
            final, extra = project_fn(goal, roas)
        diff = C.compare_budgets(acts_saved, fresh_acts)
        changed = int(diff["Berubah"].sum()) if not diff.empty else 0
        if diff.shape[0] and changed / diff.shape[0] > 0.35:
            reasons.append(f"{fmt_num(changed)} dari {fmt_num(len(diff))} iklan: saran budget hari ini beda nyata dari rencana "
                           "(sudah memperhitungkan minimum Shopee 25 rb / 100 rb)")
        saved_reach = float(s.get("capaian") or 0)
        reach = final / goal * 100
        if reach < min(saved_reach, 100.0) - 5:
            reasons.append(f"proyeksi turun: saat disimpan {fmt_pct(saved_reach, 1)} target → sekarang {fmt_pct(reach, 1)}")

    # ---- evaluasi pelaksanaan
    classified, summary = pd.DataFrame(), {}
    base = cur.get("baseline") or {}
    current = A.month_totals(units) if units else {}
    report_end = _report_end(current)
    weekly = cmp.frame_of(cur.get("iklan_minggu"))
    if base and report_end is not None and report_end >= start:
        planned = _planned_budgets(cur, start=start, report_end=report_end)
        kinds = _kinds_from(units, weekly, acts_saved)
        frame, summary = A.evaluate(base, current, planned, target_roas=roas, jenis=kinds)
        if not frame.empty:
            names = {u.key: (u.nama, "Produk tunggal" if u.jenis.startswith("Produk tunggal") else u.jenis) for u in units}
            if not weekly.empty and {"_key", "Iklan", "Jenis"} <= set(weekly.columns):
                names.update({str(k): (str(n), "Produk tunggal" if str(j).startswith("Produk tunggal") else str(j))
                              for k, n, j in zip(weekly["_key"], weekly["Iklan"], weekly["Jenis"])})
            frame.insert(1, "Iklan", frame["_key"].map(lambda k: names.get(k, (k, ""))[0]))
            if "Jenis" not in frame.columns or frame["Jenis"].isna().all():
                frame["Jenis"] = frame["_key"].map(lambda k: names.get(k, ("", "Produk tunggal"))[1])
            classified = Mon.classify_rows(frame, target_roas=roas)

    verdict = Mon.rollup(classified, summary, track=track, target_roas=roas)
    _hero(verdict)

    # ---- jalur sales (ringkas)
    if track and track.get("status") not in (None, "Menunggu data"):
        on = track["status"] == "On track"
        k = st.columns(4)
        card(k[0], "Jalur sales", "✅ On track" if on else "⚠️ Tertinggal",
             hint=f"{track['hari']} hari data sejak {fmt_date(track['mulai'])} · {fmt_pct(track['pct_sales'], 1)} jalur")
        card(k[1], "Sales bersih", fmt_idr(track["sales"]),
             hint=f"jalur {fmt_idr(track['jalur_sales'])} · {_signed(track['selisih_sales'])}")
        card(k[2], "Biaya sejak disimpan", fmt_idr(track["biaya_baru"]),
             hint=f"rencana {fmt_idr(track['jalur_biaya'] - track['terpakai_awal'])} · <b>{track['biaya_status']}</b>")
        card(k[3], "TACoS sejak disimpan",
             fmt_pct(track["biaya_baru"] / track["sales_baru"] * 100, 1) if track["sales_baru"] > 0 else "–",
             hint="biaya iklan ÷ sales bersih (makin kecil makin hemat)")
        tip = Mon.spend_gap_tip(summary, track)
        if tip:
            st.caption(tip)

    if goal > 0:
        st.markdown(_progress_bar(mtd, projection - mtd, extra, goal), unsafe_allow_html=True)
    k = st.columns(4)
    card(k[0], "Target bulan", fmt_idr(goal),
         hint=f"aktual {fmt_idr(mtd)} · <b style='color:{_tone(mtd >= goal)}'>{fmt_pct(mtd / goal * 100 if goal else 0, 1)}</b>")
    card(k[1], "Proyeksi + campaign", fmt_idr(final),
         hint=f"data {fmt_date(today)} · <b style='color:{_tone(final >= goal)}'>{fmt_pct(final / goal * 100 if goal else 0, 1)}</b> target")
    card(k[2], "Budget campaign", fmt_idr(float(s.get("budget") or 0)),
         hint=f"≈ {fmt_idr(budget_daily)}/hari · Target ROAS {fmt_num(roas, 1)}")
    card(k[3], "Periode rencana", f"{(end - start).days + 1} hari",
         hint=f"{fmt_date(start)} – {fmt_date(end)} · sisa {max((end - max(today, start)).days + 1, 0)} hari")

    if reasons:
        _box("Perlu tinjau ulang rencana",
             "<br>".join(f"• {html.escape(r)}" for r in reasons)
             + "<br><br>Bila target atau kondisi pasar sudah berubah jauh, susun rencana baru di <b>Rekomendasi sistem</b> "
             "(rencana ini berhenti otomatis saat rencana baru disimpan).", WARN)
        st.button("Buka Rekomendasi sistem", key="adt-renew", type="primary",
                  on_click=st.session_state.__setitem__, args=("adt-view-next", VIEW_REC))

    # ---- 1. Pelaksanaan Seller Center
    st.markdown("### 1 · Pelaksanaan di Seller Center")
    st.caption("Membandingkan laporan iklan yang Anda unggah dengan budget rencana. Minimum Shopee: "
               f"**{fmt_idr(A.SHOPEE_MIN_SINGLE)}/hari** iklan tunggal · **{fmt_idr(A.SHOPEE_MIN_GROUP)}/hari** iklan grup "
               "— di bawah itu sistem memakai batas Shopee sebagai acuan (bukan dianggap gagal).")
    if not base:
        st.info("Campaign ini disimpan sebelum evaluasi otomatis tersedia. Simpan ulang sebagai campaign baru agar bisa dipantau harian.")
    elif report_end is None or report_end < start:
        st.info(f"Laporan iklan terakhir s.d. {fmt_date(report_end) if report_end else '–'}, campaign mulai {fmt_date(start)}. "
                "Unggah laporan iklan esok hari di Upload data.")
    elif not summary:
        st.info(f"Belum ada hari baru di laporan sejak campaign disimpan (laporan s.d. {fmt_date(report_end)}). Unggah laporan esok hari.")
    else:
        ok_roas = summary["roas"] >= roas * 0.9 if summary.get("roas") == summary.get("roas") else False
        c = st.columns(4)
        card(c[0], "Sesuai acuan Shopee", f"{fmt_num(summary['dijalankan'])} / {fmt_num(summary['iklan'])}",
             hint=f"laporan s.d. {fmt_date(report_end)} · {fmt_num(summary['hari'])} hari dievaluasi"
                  + (f" · {fmt_num(summary.get('batas_shopee', 0))} di min. Shopee" if summary.get("batas_shopee") else ""))
        card(c[1], "Biaya aktual", f"{fmt_idr(summary['biaya_harian'])}/hari",
             hint=f"acuan efektif {fmt_idr(summary.get('budget_efektif_harian', summary['budget_usulan_harian']))}/hari")
        card(c[2], "Omzet iklan", f"{fmt_idr(summary['omzet_harian'])}/hari", hint="produk tunggal & grup di campaign")
        card(c[3], "ROAS aktual", fmt_num(summary["roas"], 1),
             hint=f"target {fmt_num(roas, 1)} · <b style='color:{_tone(ok_roas)}'>{'sesuai' if ok_roas else 'di bawah target'}</b>")

        actions = Mon.priority_actions(classified, limit=8)
        if actions:
            st.markdown("**Tindakan prioritas hari ini**")
            for i, a in enumerate(actions, 1):
                color = DOWN if a["tindakan"].startswith(("Jeda", "Turunkan")) else WARN
                st.markdown(
                    f"<div style='display:flex;gap:.75rem;align-items:flex-start;padding:.65rem .8rem;margin:.35rem 0;"
                    f"border:1px solid #e2e8f0;border-radius:12px;background:#fff'>"
                    f"<div style='background:{color};color:#fff;border-radius:8px;min-width:1.7rem;height:1.7rem;"
                    f"display:flex;align-items:center;justify-content:center;font-weight:800'>{i}</div>"
                    f"<div><div style='font-weight:800'>{html.escape(a['iklan'])} · "
                    f"<span style='color:{color}'>{html.escape(a['tindakan'])}</span></div>"
                    f"<div style='color:#475569;font-size:var(--fs-sm);line-height:1.55;margin-top:.15rem'>"
                    f"{html.escape(a['saran'])}</div></div></div>",
                    unsafe_allow_html=True,
                )
        else:
            _box("Semua iklan sejalan", "Tidak ada tindakan mendesak. Pantau lagi setelah unggah laporan berikutnya.", UP)

        view_cols = ["Iklan", "Jenis", "Status goals", "Tindakan", "Budget usulan/hari", "Budget efektif Shopee/hari",
                     "Biaya aktual/hari", "Omzet iklan aktual/hari", "ROAS aktual", "Saran", "Catatan batas"]
        view = classified[[c for c in view_cols if c in classified.columns]].copy()
        with st.expander(f"Tabel lengkap per iklan · {fmt_num(len(view))} baris", expanded=False):
            show_table(view, kinds={"Budget usulan/hari": "money", "Budget efektif Shopee/hari": "money", "Biaya aktual/hari": "money",
                                    "Omzet iklan aktual/hari": "money", "ROAS aktual": "dec"},
                       column_config={"Iklan": st.column_config.TextColumn(width="large"), "Saran": st.column_config.TextColumn(width="large")})
            download_excel(view, f"pantau_iklan_{cur['id']}.xlsx", key="xl-adt-mon", label="Unduh pantauan")

    # ---- 2. Strategi minggu depan
    st.markdown(f"### 2 · Strategi minggu depan · {fmt_date(week_start)} – {fmt_date(week_end)}")
    st.caption("Disusun dari prediksi omzet produk, stok Site 10037, dan hasil pantauan ROAS. "
               "Tujuan: ROAS tinggi, biaya terkendali, fokus hanya item yang pantas diiklankan.")
    room = max(budget_daily - float(summary.get("biaya_harian") or 0), budget_daily * 0.15) if budget_daily else A.SHOPEE_MIN_GROUP * 3
    week = Mon.next_week_strategy(products, classified if not classified.empty else None, sel_saved,
                                  target_roas=roas, daily_budget_room=room, limit=15)
    if week.empty:
        st.info("Belum ada usulan minggu depan — pastikan analisa & laporan iklan sudah diunggah.")
    else:
        keep = int((week["Keputusan"].astype(str).str.contains("Pertahankan|naikkan|rencana", case=False)).sum())
        make = int((week["Keputusan"].astype(str).str.contains("Buat", case=False)).sum())
        stop = int((week["Keputusan"].astype(str).str.contains("Jangan|Jeda", case=False)).sum())
        w = st.columns(3)
        card(w[0], "Pertahankan / naikkan", fmt_num(keep), hint="sudah jalan & layak dilanjut")
        card(w[1], "Buat iklan baru", fmt_num(make), hint="prediksi tinggi, belum di rencana")
        card(w[2], "Jangan / jeda", fmt_num(stop), hint="stok kosong atau ROAS lemah")
        show_table(week, kinds={"Budget/hari": "money", "Prediksi omzet/hari": "money", "Stok": "count", "ROAS terkini": "dec", "Prioritas": "count"},
                   column_config={"Produk": st.column_config.TextColumn(width="medium"), "Alasan": st.column_config.TextColumn(width="large")})
        download_excel(week, f"strategi_minggu_iklan_{week_start}.xlsx", key="xl-adt-week", label="Unduh strategi minggu depan")
        _box("Cara pakai di Seller Center",
             "1) Kerjakan <b>Tindakan prioritas</b> dulu (hari ini).<br>"
             "2) Senin: sesuaikan budget menurut kolom Budget/hari (naik maks. 2× dari budget berjalan).<br>"
             "3) Buat iklan tunggal baru hanya untuk baris <b>Buat iklan tunggal</b>, mulai 25 rb, Target ROAS sama dengan rencana.<br>"
             "4) Jangan iklan item stok kosong — restock Site 10037 dulu.<br>"
             "5) Unggah laporan iklan esok hari agar pantauan ini terbarui.", UP)

    # ---- 3. Rencana terkunci (detail)
    st.markdown("### 3 · Rincian rencana tersimpan")
    if acts_saved.empty:
        st.info("Campaign ini tidak menyimpan perubahan per iklan.")
    else:
        cols = [c for c in ACT_COLS if c in acts_saved.columns]
        settings = pd.DataFrame([{"Setelan": k_, "Nilai": v} for k_, v in (
            ("Campaign", f"#{cur['id']} {cur.get('nama', '')}"), ("Periode", f"{fmt_date(start)} – {fmt_date(end)}"),
            ("Target sales", fmt_idr(target)), ("Target ROAS", fmt_num(roas, 1)),
            ("Budget campaign", fmt_idr(float(s.get("budget") or 0))),
            ("Disimpan", f"{cur.get('dibuat_oleh', '')} {cur.get('dibuat', '')}"))])
        batched_view(
            len(acts_saved), key="adt-lock-units", noun="iklan",
            render=lambda lo, hi: show_table(acts_saved.iloc[lo:hi][cols], kinds=ACT_KINDS, max_height=10_000,
                                             column_config={"Iklan": st.column_config.TextColumn(width="medium"),
                                                            "Catatan": st.column_config.TextColumn(width="large")}),
            download=lambda: download_excel(
                {"Setelan": settings, "Rencana per iklan": acts_saved[cols], "Pemilihan produk": sel_saved,
                 "Beda dengan saran hari ini": diff},
                f"campaign_iklan_{cur['id']}.xlsx", key="xl-adt-lock"),
        )

    weekly_saved = cmp.frame_of(cur.get("jadwal_minggu"), ("Mulai", "Selesai"))
    if len(weekly_saved) > 1:
        with st.expander(f"Jadwal budget per minggu · {fmt_num(len(weekly_saved))} minggu"):
            show_table(weekly_saved, kinds={"Budget/hari": "money", "Omzet iklan/hari": "money", "ROAS": "dec",
                                            "Tambahan omzet": "money", "Hari": "count", "Iklan aktif": "count"})
            per_unit = cmp.frame_of(cur.get("iklan_minggu"))
            if not per_unit.empty:
                download_excel(per_unit.drop(columns=["_key"], errors="ignore"),
                               f"budget_iklan_per_minggu_{cur['id']}.xlsx", key="xl-adt-lock-weeks",
                               label="Unduh budget per iklan per minggu")
    calendar_saved = cmp.frame_of(cur.get("kalender_harian"), ("Tanggal",))
    if not calendar_saved.empty:
        with st.expander(f"Kalender budget harian · {fmt_num(len(calendar_saved))} hari"):
            show_table(_calendar_view(calendar_saved),
                       kinds={"Budget/hari": "money", "Omzet iklan/hari": "money", "ROAS hari": "dec",
                              "Pola hari": "dec", "Pengali budget": "dec", "Minggu": "count"})
    if not diff.empty:
        with st.expander(f"Beda vs saran hari ini · {fmt_num(int(diff['Berubah'].sum()))} berubah (min. Shopee sudah diperhitungkan)"):
            st.caption("Membandingkan budget efektif Seller Center (bukan angka usulan mentah di bawah minimum).")
            show_table(diff, kinds={"Budget tersimpan/hari": "money", "Budget saran hari ini/hari": "money",
                                    "Efektif tersimpan/hari": "money", "Efektif saran/hari": "money", "Selisih/hari": "money"},
                       column_config={"Iklan": st.column_config.TextColumn(width="large")})
    if not sel_saved.empty:
        with st.expander(f"Pemilihan produk · {fmt_num(len(sel_saved))} produk"):
            batched_view(
                len(sel_saved), key="adt-lock-sel", noun="produk",
                render=lambda lo, hi: show_table(sel_saved.iloc[lo:hi].drop(columns=["_unit"], errors="ignore"),
                                                 kinds=SEL_KINDS, max_height=10_000,
                                                 column_config={"Produk": st.column_config.TextColumn(width="medium"),
                                                                "Alasan": st.column_config.TextColumn(width="large")}),
            )
    _not_advertised(products, sel_saved, key="adt-lock-noads", periode=periode)
