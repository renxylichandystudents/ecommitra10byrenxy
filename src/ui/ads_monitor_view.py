"""UI Pantau rencana tersimpan: review harian hasil campaign vs Seller Center + item yang harus diiklankan."""

from __future__ import annotations

import html
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src.core import ads_monitor as Mon
from src.core import ads_month as M
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

ACT_COLS = ["Tindakan", "Iklan", "Jenis", "Anggota", "Budget harian sekarang", "Budget harian usulan", "Perubahan/hari",
            "Target ROAS Shopee", "ROAS bulan terakhir", "Omzet iklan usulan/hari", "Catatan"]
ACT_KINDS = {"Budget harian sekarang": "money", "Budget harian usulan": "money", "Perubahan/hari": "money",
             "Omzet iklan usulan/hari": "money", "Anggota": "count", "ROAS bulan terakhir": "dec", "Target ROAS Shopee": "dec"}
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
        f"<div style='font-weight:800;color:{color};margin-bottom:.3rem'>{title}</div>"
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
        f"Review campaign · bisa dicek setiap hari</div>"
        f"<div style='font-size:1.35rem;font-weight:800;margin-top:.2rem'>{html.escape(verdict['title'])}</div>"
        f"<div style='opacity:.9;margin-top:.35rem;line-height:1.55;max-width:52rem'>{html.escape(verdict['blurb'])}</div></div>"
        f"<div style='background:{color};color:#fff;border-radius:999px;padding:.45rem .9rem;font-weight:800;font-size:var(--fs-sm)'>"
        f"{verdict['done']}/{verdict['total'] or '–'} iklan sesuai</div></div></div>",
        unsafe_allow_html=True,
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


def _period_sales(track: dict | None, factor: float) -> dict:
    """Sales & TACoS sejak campaign disimpan: produk (sejajar performa iklan) vs bersih (definisi toko)."""
    empty = {"produk": float("nan"), "bersih": float("nan"), "tacos_produk": float("nan"), "tacos_bersih": float("nan"),
             "produk_hint": "menunggu data baru", "bersih_hint": "menunggu data baru",
             "tacos_produk_hint": "menunggu data baru", "tacos_bersih_hint": "menunggu data baru", "est": False}
    if not track or track.get("status") == "Menunggu data":
        return empty
    cost = float(track.get("biaya_baru") or 0)
    bersih = float(track.get("sales_baru") or 0)
    produk = track.get("produk_baru")
    est = False
    if produk == produk and produk is not None and float(produk) > 0:
        produk_v = float(produk)
        produk_hint = "semua pesanan produk sejak disimpan (termasuk belum bayar & batal) · sejajar performa iklan"
    elif bersih > 0 and factor > 0:
        produk_v = bersih / factor
        est = True
        produk_hint = "taksiran dari sales bersih ÷ faktor (rencana lama tanpa mtd_produk) · simpan rencana baru agar tepat"
    else:
        produk_v = float("nan")
        produk_hint = "sales produk sejak disimpan belum tersedia"
    tacos_produk = cost / produk_v * 100 if produk_v == produk_v and produk_v > 0 else float("nan")
    tacos_bersih = float(track["tacos_bersih"]) if track.get("tacos_bersih") == track.get("tacos_bersih") else (
        cost / bersih * 100 if bersih > 0 else float("nan"))
    return {
        "produk": produk_v, "bersih": bersih, "tacos_produk": tacos_produk, "tacos_bersih": tacos_bersih, "est": est,
        "produk_hint": produk_hint,
        "bersih_hint": "Total Pembayaran − batal − Belum Bayar − retur · sama definisi di seluruh menu",
        "tacos_produk_hint": "biaya iklan ÷ sales produk · sejajar klaim performa iklan (batal/belum bayar ikut)",
        "tacos_bersih_hint": "biaya iklan ÷ sales bersih · hemat biaya terhadap target toko",
    }


def render_monitor(cur: dict, *, units, members, products, contribution, projection: float, mtd: float, target_now: float,
                   today: date, factor: float, first_open: date, month_end: date, periode: str, has_ads: bool,
                   track: dict | None = None, project_fn=None, ads_overall=None, spent_month: float = 0.0,
                   mtd_produk: float = 0.0) -> None:
    from src.ui.ads_target import VIEW_REC  # late import

    s = cur.get("setelan") or {}
    start, end = C.as_date(cur["mulai"]), C.as_date(cur["selesai"])
    acts_saved = cmp.frame_of(cur.get("iklan"))
    sel_saved = cmp.frame_of(cur.get("produk"))
    target = float(s.get("target") or 0)
    goal = target_now if target_now > 0 else target
    roas = float(s.get("roas") or 8.0)
    budget_daily = float(s.get("biaya_harian_rencana") or s.get("budget_harian") or 0)
    horizon_start, horizon_end = Mon.week_window(today)

    # ---- Performa toko dari laporan keseluruhan (sejajar Seller Center › Keseluruhan iklan)
    last_data = first_open - timedelta(days=1)
    since_start = (track["mulai"] + timedelta(days=1)) if track and track.get("mulai") else (start + timedelta(days=0))
    if since_start <= last_data and ads_overall is not None:
        store_since = M.ad_spend(ads_overall, since_start, last_data)
    else:
        store_since = {"biaya": 0.0, "omzet": 0.0, "hari": 0}
    days_since = int(track["hari"]) if track and track.get("hari") is not None else int(store_since.get("hari") or 0)
    # Utamakan laporan keseluruhan; fallback ke jalur track bila laporan belum terunggah untuk rentang itu
    spent_since = float(store_since["biaya"]) if store_since.get("biaya") else float((track or {}).get("biaya_baru") or 0)
    omzet_since = float(store_since.get("omzet") or 0)
    store_roas = omzet_since / spent_since if spent_since > 0 else float("nan")
    days_left_plan = max((end - max(today, start)).days + 1, 0)
    wallet = Mon.budget_wallet(s, spent_month=spent_month, spent_since=spent_since, days_since=max(days_since, 0),
                               days_left_plan=days_left_plan)

    # ---- evaluasi per iklan
    reasons: list[str] = []
    if s.get("periode_target") and s["periode_target"] != periode:
        reasons.append(f"campaign untuk {s['periode_target']}, data sekarang {periode}")
    if target_now > 0 and abs(target_now - target) > max(1.0, 0.01 * target):
        reasons.append(f"target berubah: {fmt_idr(target)} → {fmt_idr(target_now)}")

    classified, summary = pd.DataFrame(), {}
    base = cur.get("baseline") or {}
    current = A.month_totals(units) if units else {}
    report_end = _report_end(current)
    weekly = cmp.frame_of(cur.get("iklan_minggu"))
    running_keys = {u.key for u in (units or []) if A._running(u) and u.daily_cost > 0}
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
            classified = Mon.classify_rows(frame, target_roas=roas, running_keys=running_keys)

    verdict = Mon.rollup(classified, summary, track=track, target_roas=roas, store_roas=store_roas)
    _hero(verdict)

    # -------- A. Hasil sejak campaign (bisa review harian)
    st.markdown("### A · Hasil sejak campaign ditetapkan")
    st.caption(
        f"Sumber biaya & omzet iklan: laporan **Keseluruhan iklan** (sama keluarga angka Seller Center). "
        f"Periode: {fmt_date(since_start)} – {fmt_date(last_data) if store_since.get('hari') else '–'} "
        f"({fmt_num(store_since.get('hari') or days_since)} hari). "
        "Sales produk = semua pesanan produk (sejajar performa iklan); sales bersih = tanpa batal / Belum Bayar / retur."
    )
    period = _period_sales(track, factor)
    a = st.columns(4)
    card(a[0], "Biaya iklan sejak disimpan", fmt_idr(spent_since),
         hint=f"jalur rencana {fmt_idr(wallet['jalur_sejak'])} · <b>{(track or {}).get('biaya_status', '–')}</b>")
    card(a[1], "Omzet iklan sejak disimpan", fmt_idr(omzet_since),
         hint="klaim Shopee (termasuk pesanan belum bayar) · dari laporan keseluruhan")
    card(a[2], "Sales produk sejak disimpan",
         fmt_idr(period["produk"]) if period["produk"] == period["produk"] else "–",
         hint=period["produk_hint"])
    card(a[3], "Sales bersih sejak disimpan",
         fmt_idr(period["bersih"]) if period["bersih"] == period["bersih"] else "–",
         hint=period["bersih_hint"])

    b = st.columns(4)
    card(b[0], "ROAS iklan (SC)", fmt_num(store_roas, 1) if store_roas == store_roas else "–",
         hint=f"target {fmt_num(roas, 1)} · <b style='color:{_tone(store_roas >= roas * 0.9 if store_roas == store_roas else False)}'>"
              f"{'sesuai' if store_roas == store_roas and store_roas >= roas * 0.9 else 'di bawah / menunggu'}</b>")
    card(b[1], "TACoS vs sales produk",
         fmt_pct(period["tacos_produk"], 1) if period["tacos_produk"] == period["tacos_produk"] else "–",
         hint=period["tacos_produk_hint"] + " · makin kecil makin hemat")
    card(b[2], "TACoS vs sales bersih",
         fmt_pct(period["tacos_bersih"], 1) if period["tacos_bersih"] == period["tacos_bersih"] else "–",
         hint=period["tacos_bersih_hint"] + " · makin kecil makin hemat")
    if track and track.get("status") not in (None, "Menunggu data"):
        on = track["status"] == "On track"
        card(b[3], "Jalur sales bersih", "✅ On track" if on else "⚠️ Tertinggal",
             hint=f"{track['hari']} hari · {fmt_pct(track['pct_sales'], 1)} jalur · target toko memakai sales bersih")
    else:
        card(b[3], "Jalur sales bersih", "–", hint="menunggu data baru setelah campaign disimpan")

    # MTD: pasangan sales produk & sales bersih (konsisten menu lain)
    c = st.columns(2)
    produk_mtd = float(mtd_produk) if mtd_produk is not None else float("nan")
    bersih_mtd = float(mtd) if mtd is not None else float("nan")
    card(c[0], "Sales produk MTD", fmt_idr(produk_mtd) if produk_mtd == produk_mtd else "–",
         hint="bulan berjalan · semua pesanan produk (termasuk belum bayar & batal) · pembanding performa iklan")
    jalur_hint = ""
    if track and track.get("status") not in (None, "Menunggu data"):
        jalur_hint = f"jalur {fmt_idr(track['jalur_sales'])} · {_signed(track['selisih_sales'])} · "
    card(c[1], "Sales bersih MTD", fmt_idr(bersih_mtd) if bersih_mtd == bersih_mtd else "–",
         hint=f"{jalur_hint}tanpa batal / Belum Bayar / retur · acuan target toko")

    tip = Mon.spend_gap_tip(wallet, store_since, summary)
    if tip:
        st.caption(tip)

    # -------- B. Dompet budget (bukan 1 angka)
    st.markdown("### B · Dompet budget campaign")
    st.caption("Satu angka total saja membingungkan — baca berurutan: total → terpakai bulan → sisa → rencana harian → realisasi sejak disimpan.")
    w = st.columns(4)
    card(w[0], "1. Budget total campaign", fmt_idr(wallet["budget_total"]),
         hint=f"setelan saat disimpan · Target ROAS {fmt_num(wallet['roas_target'], 1)}")
    card(w[1], "2. Terpakai bulan ini", fmt_idr(wallet["terpakai_bulan"]),
         hint="semua biaya iklan 1 s.d. hari data terakhir (laporan keseluruhan)")
    card(w[2], "3. Sisa budget bulan", fmt_idr(wallet["sisa_bulan"]),
         hint=f"total − terpakai · sisa periode rencana {fmt_num(wallet['sisa_hari_rencana'])} hari")
    card(w[3], "4. Rencana harian", fmt_idr(wallet["rencana_harian"]),
         hint=f"pembagian sisa saat disimpan · realisasi sejak ≈ {fmt_idr(spent_since / days_since if days_since else 0)}/hari")

    if goal > 0:
        gap = max(goal - projection, 0)
        st.markdown(
            f"<div class='field-hint'>Target sales bersih bulan <b>{fmt_idr(goal)}</b> · aktual <b>{fmt_idr(mtd)}</b> "
            f"({fmt_pct(mtd / goal * 100, 1)}) · proyeksi tanpa ubah iklan <b>{fmt_idr(projection)}</b>"
            + (f" · kekurangan ±{fmt_idr(gap)}" if gap > 0 else " · target pada jalur proyeksi")
            + f" · periode rencana {fmt_date(start)} – {fmt_date(end)}</div>",
            unsafe_allow_html=True,
        )

    if reasons:
        _box("Perlu tinjau ulang rencana",
             "<br>".join(f"• {html.escape(r)}" for r in reasons)
             + "<br>Susun rencana baru di Rekomendasi sistem bila target sudah berubah jauh.", WARN)
        st.button("Buka Rekomendasi sistem", key="adt-renew", type="primary",
                  on_click=st.session_state.__setitem__, args=("adt-view-next", VIEW_REC))

    # -------- 1. Pelaksanaan per iklan
    st.markdown("### 1 · Pelaksanaan per iklan (sejak disimpan)")
    st.caption(
        "Angka per iklan dari laporan **produk tunggal + grup** (selisih sejak baseline campaign). "
        f"Minimum Shopee: {fmt_idr(A.SHOPEE_MIN_SINGLE)} tunggal · {fmt_idr(A.SHOPEE_MIN_GROUP)} grup. "
        "Status SC = terlihat berjalan di laporan terbaru."
    )
    if not base:
        st.info("Campaign tanpa baseline evaluasi. Simpan ulang sebagai campaign baru agar bisa dibanding harian.")
    elif report_end is None or report_end < start:
        st.info(f"Laporan iklan s.d. {fmt_date(report_end) if report_end else '–'} belum melewati mulai campaign {fmt_date(start)}. Unggah laporan hari kemarin.")
    elif not summary:
        st.info("Belum ada hari baru sejak campaign disimpan. Unggah laporan iklan esok hari.")
    else:
        c = st.columns(4)
        card(c[0], "Iklan aktif di rencana", f"{fmt_num(summary.get('dijalankan', 0))} / {fmt_num(summary.get('iklan_aktif_rencana', summary['iklan']))}",
             hint=f"laporan s.d. {fmt_date(report_end)} · {fmt_num(summary['hari'])} hari"
                  + (f" · {fmt_num(summary.get('batas_shopee', 0))} di min. Shopee" if summary.get("batas_shopee") else ""))
        card(c[1], "Biaya sejak disimpan (per iklan)", fmt_idr(summary.get("biaya_total", summary["biaya_harian"] * summary["hari"])),
             hint=f"≈ {fmt_idr(summary['biaya_harian'])}/hari · acuan efektif {fmt_idr(summary.get('budget_efektif_harian', 0))}/hari")
        card(c[2], "Omzet iklan sejak disimpan", fmt_idr(summary.get("omzet_total", summary["omzet_harian"] * summary["hari"])),
             hint=f"≈ {fmt_idr(summary['omzet_harian'])}/hari · hanya iklan di rencana aktif")
        ok_roas = summary["roas"] >= roas * 0.9 if summary.get("roas") == summary.get("roas") else False
        card(c[3], "ROAS per iklan (rencana)", fmt_num(summary["roas"], 1),
             hint=f"target {fmt_num(roas, 1)} · <b style='color:{_tone(ok_roas)}'>{'sesuai' if ok_roas else 'di bawah'}</b>")

        # tampilkan dulu yang perlu tindakan + yang aktif
        focus = classified.loc[
            (classified["Tindakan"] != "Pertahankan") | (classified.get("Budget efektif Shopee/hari", 0) > 0)
        ] if not classified.empty else classified
        actions = Mon.priority_actions(classified, limit=8)
        if actions:
            st.markdown("**Tindakan hari ini** (kerjakan di Seller Center, lalu unggah laporan)")
            for i, item in enumerate(actions, 1):
                color = DOWN if item["tindakan"].startswith(("Jeda", "Turunkan")) else WARN
                st.markdown(
                    f"<div style='display:flex;gap:.75rem;padding:.65rem .8rem;margin:.35rem 0;border:1px solid #e2e8f0;"
                    f"border-radius:12px;background:#fff'><div style='background:{color};color:#fff;border-radius:8px;"
                    f"min-width:1.7rem;height:1.7rem;display:flex;align-items:center;justify-content:center;font-weight:800'>{i}</div>"
                    f"<div><div style='font-weight:800'>{html.escape(item['iklan'])} · "
                    f"<span style='color:{color}'>{html.escape(item['tindakan'])}</span></div>"
                    f"<div style='color:#475569;font-size:var(--fs-sm);margin-top:.15rem'>{html.escape(item['saran'])}</div>"
                    f"</div></div>",
                    unsafe_allow_html=True,
                )
        else:
            _box("Pelaksanaan sejalan", "Tidak ada tindakan mendesak hari ini.", UP)

        view_cols = ["Iklan", "Jenis", "Status SC", "Status goals", "Tindakan", "Budget usulan/hari", "Budget efektif Shopee/hari",
                     "Biaya sejak disimpan", "Omzet iklan sejak disimpan", "Biaya aktual/hari", "ROAS aktual", "Saran"]
        view = focus[[c for c in view_cols if c in focus.columns]].head(60)
        with st.expander(f"Tabel iklan fokus · {fmt_num(len(view))} baris (bukan semua katalog)", expanded=False):
            show_table(view, kinds={"Budget usulan/hari": "money", "Budget efektif Shopee/hari": "money", "Biaya sejak disimpan": "money",
                                    "Omzet iklan sejak disimpan": "money", "Biaya aktual/hari": "money", "ROAS aktual": "dec"},
                       column_config={"Iklan": st.column_config.TextColumn(width="large"), "Saran": st.column_config.TextColumn(width="large")})
            download_excel(view, f"pantau_iklan_{cur['id']}.xlsx", key="xl-adt-mon", label="Unduh pantauan")

    # -------- 2. Apa yang harus diiklankan
    st.markdown(f"### 2 · Yang harus diiklankan · {fmt_date(horizon_start)} – {fmt_date(horizon_end)}")
    st.caption("Fokus aksi: pertahankan yang kuat, buat iklan baru yang layak, jeda yang lemah. Bukan daftar panjang 'jangan iklan'.")
    room = max(wallet["rencana_harian"] * 0.5, A.SHOPEE_MIN_GROUP * 2)
    week = Mon.must_advertise(products, classified if not classified.empty else None, sel_saved, units,
                              target_roas=roas, daily_budget_room=room, limit=12)
    if week.empty:
        st.info("Belum ada usulan — pastikan laporan iklan & analisa sudah diunggah.")
    else:
        go = week.loc[~week["Keputusan"].astype(str).str.contains("Jeda", case=False)]
        stop = week.loc[week["Keputusan"].astype(str).str.contains("Jeda", case=False)]
        k = st.columns(3)
        card(k[0], "Wajib jalan / naikkan", fmt_num(int(go["Keputusan"].str.contains("Pertahankan", case=False).sum())),
             hint="ROAS kuat — jangan dipotong")
        card(k[1], "Buat iklan baru", fmt_num(int(go["Keputusan"].str.contains("Buat", case=False).sum())),
             hint="prediksi tinggi + stok · mulai 25 rb")
        card(k[2], "Jeda / alihkan", fmt_num(len(stop)), hint="ROAS lemah — pindahkan budget")
        show_table(week, kinds={"Budget/hari": "money", "Prediksi omzet/hari": "money", "Stok": "count",
                                "ROAS terkini": "dec", "Biaya kini/hari": "money", "Prioritas": "count"},
                   column_config={"Produk": st.column_config.TextColumn(width="medium"), "Alasan": st.column_config.TextColumn(width="large")})
        download_excel(week, f"wajib_iklan_{horizon_start}.xlsx", key="xl-adt-week", label="Unduh daftar wajib iklan")
        _box("Urutan kerja",
             "1) Kerjakan <b>Tindakan hari ini</b> di poin 1.<br>"
             "2) Aktifkan baris <b>Buat iklan tunggal</b> (25 rb, Target ROAS sama rencana).<br>"
             "3) Jeda baris ROAS lemah agar budget pindah ke yang kuat.<br>"
             "4) Unggah laporan iklan esok hari — review ulang tanpa menunggu seminggu.", UP)

    # -------- 3. Rencana tersimpan (ringkas)
    st.markdown("### 3 · Cuplikan rencana tersimpan")
    st.caption("Hanya iklan berbudget / berubah (bukan seluruh katalog). Budget usulan = angka yang disimpan saat campaign dibuat; "
               "budget sekarang = kondisi laporan saat itu.")
    focus_acts = Mon.active_plan_ads(acts_saved, limit=40)
    if focus_acts.empty:
        st.info("Campaign tidak menyimpan baris budget per iklan.")
    else:
        cols = [c for c in ACT_COLS if c in focus_acts.columns]
        batched_view(
            len(focus_acts), key="adt-lock-units", noun="iklan berbudget",
            render=lambda lo, hi: show_table(focus_acts.iloc[lo:hi][cols], kinds=ACT_KINDS, max_height=10_000,
                                             column_config={"Iklan": st.column_config.TextColumn(width="medium"),
                                                            "Catatan": st.column_config.TextColumn(width="large")}),
            download=lambda: download_excel(focus_acts[cols], f"rencana_iklan_fokus_{cur['id']}.xlsx", key="xl-adt-lock"),
        )
    focus_sel = Mon.selection_focus(sel_saved, limit=25)
    if not focus_sel.empty:
        with st.expander(f"Pemilihan produk prioritas · {fmt_num(len(focus_sel))} dari {fmt_num(len(sel_saved))} (disaring)", expanded=False):
            st.caption("Ditampilkan tindakan aktif + prediksi tertinggi saja, supaya prioritas jelas.")
            show_table(focus_sel.drop(columns=["_unit"], errors="ignore"), kinds=SEL_KINDS,
                       column_config={"Produk": st.column_config.TextColumn(width="medium"),
                                      "Alasan": st.column_config.TextColumn(width="large")})
