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
    """Sales & TACoS **sejak campaign** saja (bukan MTD)."""
    empty = {"produk": float("nan"), "bersih": float("nan"), "tacos_produk": float("nan"), "tacos_bersih": float("nan"),
             "est": False}
    if not track or track.get("status") == "Menunggu data":
        return empty
    cost = float(track.get("biaya_baru") or 0)
    bersih = float(track.get("sales_baru") or 0)
    produk = track.get("produk_baru")
    est = bool(track.get("produk_est"))
    if produk == produk and produk is not None and float(produk) > 0:
        produk_v = float(produk)
    elif bersih > 0 and factor > 0:
        produk_v = bersih / factor
        est = True
    else:
        produk_v = float("nan")
    tacos_produk = cost / produk_v * 100 if produk_v == produk_v and produk_v > 0 else float("nan")
    tacos_bersih = float(track["tacos_bersih"]) if track.get("tacos_bersih") == track.get("tacos_bersih") else (
        cost / bersih * 100 if bersih > 0 else float("nan"))
    return {"produk": produk_v, "bersih": bersih, "tacos_produk": tacos_produk, "tacos_bersih": tacos_bersih, "est": est}


def _tacos_pair(cost: float, produk: float, bersih: float) -> tuple[float, float]:
    tp = cost / produk * 100 if produk == produk and produk > 0 and cost == cost else float("nan")
    tb = cost / bersih * 100 if bersih == bersih and bersih > 0 and cost == cost else float("nan")
    return tp, tb


def _fmt_hari(value: float) -> str:
    return f"{fmt_idr(value)}/hari" if value == value else "–"


def _ad_row_card(r: pd.Series, *, cur: dict, report_end: date | None, prefix: str, cid: int) -> None:
    """Satu baris rekap iklan: insight singkat + budget + 2 angka terpakai + expander historis."""
    name = str(r.get("Iklan") or r.get("_key") or "")
    key = str(r.get("_key") or "")
    act = str(r.get("Tindakan") or "–")
    color = DOWN if act.startswith(("Jeda", "Turunkan")) else (UP if act == "Pertahankan" else WARN)
    plan = float(r.get("Budget usulan/hari") or r.get("Budget di rencana/hari") or 0)
    setup = float(r.get("Budget efektif Shopee/hari") or r.get("Budget di Shopee/hari") or 0)
    since = float(r.get("Biaya aktual/hari") or r.get("Terpakai sejak campaign/hari") or 0)
    month = r.get("Biaya bulan ini/hari")
    month_v = float(month) if month == month and month is not None else float("nan")
    omzet = float(r.get("Omzet iklan sejak disimpan") or 0)
    biaya = float(r.get("Biaya sejak disimpan") or 0)
    roas = float(r["ROAS aktual"]) if r.get("ROAS aktual") == r.get("ROAS aktual") else float("nan")
    hasil = (
        f"Hasil iklan sejak campaign: {fmt_idr(omzet)}"
        + (f" · ROAS {fmt_num(roas, 1)}×" if roas == roas else "")
    )
    st.markdown(
        f"<div style='border:1px solid #e2e8f0;border-radius:12px;padding:.75rem .9rem;margin:.4rem 0;background:#fff'>"
        f"<div style='display:flex;flex-wrap:wrap;gap:.5rem 1rem;justify-content:space-between;align-items:baseline'>"
        f"<div style='font-weight:800'>{html.escape(name)} · "
        f"<span style='color:{color}'>{html.escape(act)}</span></div>"
        f"<div style='color:#475569;font-size:var(--fs-sm)'>{hasil}</div></div>"
        f"<div style='color:#475569;font-size:var(--fs-sm);margin-top:.35rem;line-height:1.5'>"
        f"{html.escape(str(r.get('Saran') or r.get('Status goals') or ''))}</div>"
        f"<div style='display:flex;flex-wrap:wrap;gap:.75rem 1.25rem;margin-top:.45rem;font-size:var(--fs-sm)'>"
        f"<span><b>Di rencana</b> {_fmt_hari(plan)}</span>"
        f"<span><b>Di Shopee</b> {_fmt_hari(setup)}</span>"
        f"<span><b>Terpakai bulan ini</b> {_fmt_hari(month_v)}</span>"
        f"<span><b>Terpakai sejak campaign</b> {_fmt_hari(since)}</span></div></div>",
        unsafe_allow_html=True,
    )
    with st.expander("Lihat riwayat harian", expanded=False):
        st.caption(
            "Catatan harian tersimpan setiap kali Pantau dibuka atau laporan diunggah. "
            "Sebelum fitur ini aktif, yang tampil hanya titik saat campaign disimpan dan hari ini."
        )
        base_dt = None
        if cur.get("setelan", {}).get("data_sampai"):
            try:
                base_dt = str(cur["setelan"]["data_sampai"])[:10]
            except Exception:
                base_dt = None
        today_row = {
            "tanggal": report_end.isoformat() if report_end else "",
            "biaya": biaya, "omzet": omzet, "roas": (omzet / biaya) if biaya > 0 else float("nan"),
            "biaya_hari": since, "budget_plan": plan, "budget_setup": setup, "tindakan": act,
        }
        hist = Mon.daily_history_for(
            cur, key,
            baseline_row={"tanggal": base_dt or "baseline", "budget_plan": plan, "budget_setup": setup},
            today_row=today_row,
        )
        if hist.empty:
            st.info("Belum ada catatan harian untuk iklan ini.")
        else:
            show_table(
                hist,
                kinds={"Biaya sejak disimpan": "money", "Omzet iklan sejak disimpan": "money", "ROAS": "dec",
                       "Actual pemakaian/hari": "money", "Budget plan": "money", "Budget setup SC": "money"},
                key=f"hist-{prefix}-{cid}-{key}",
            )


def render_monitor(cur: dict, *, units, members, products, contribution, projection: float, mtd: float, target_now: float,
                   today: date, factor: float, first_open: date, month_end: date, periode: str, has_ads: bool,
                   track: dict | None = None, project_fn=None, ads_overall=None, spent_month: float = 0.0,
                   mtd_produk: float = 0.0, features=None, username: str = "") -> None:
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
    in_plan, out_plan = pd.DataFrame(), pd.DataFrame()
    planned: dict[str, float] = {}
    base = cur.get("baseline") or {}
    current = A.month_totals(units) if units else {}
    report_end = _report_end(current)
    weekly = cmp.frame_of(cur.get("iklan_minggu"))
    running_keys = {u.key for u in (units or []) if A._running(u) and u.daily_cost > 0}
    names = {u.key: (u.nama, "Produk tunggal" if u.jenis.startswith("Produk tunggal") else u.jenis) for u in (units or [])}
    if not weekly.empty and {"_key", "Iklan", "Jenis"} <= set(weekly.columns):
        names.update({str(k): (str(n), "Produk tunggal" if str(j).startswith("Produk tunggal") else str(j))
                      for k, n, j in zip(weekly["_key"], weekly["Iklan"], weekly["Jenis"])})
    if not acts_saved.empty and "key" in acts_saved.columns:
        for k, n, j in zip(acts_saved["key"], acts_saved.get("Iklan", acts_saved["key"]),
                           acts_saved.get("Jenis", pd.Series(["Produk tunggal"] * len(acts_saved)))):
            names.setdefault(str(k), (str(n), "Produk tunggal" if str(j).startswith("Produk tunggal") else str(j)))
    kinds = _kinds_from(units, weekly, acts_saved)
    if base and report_end is not None and report_end >= start:
        planned = _planned_budgets(cur, start=start, report_end=report_end)
        frame, summary = A.evaluate(base, current, planned, target_roas=roas, jenis=kinds)
        if not frame.empty:
            frame.insert(1, "Iklan", frame["_key"].map(lambda k: names.get(k, (k, ""))[0]))
            if "Jenis" not in frame.columns or frame["Jenis"].isna().all():
                frame["Jenis"] = frame["_key"].map(lambda k: names.get(k, ("", "Produk tunggal"))[1])
            classified = Mon.classify_rows(frame, target_roas=roas, running_keys=running_keys)
        in_plan, out_plan = Mon.split_in_out_plan(
            classified, planned, current, base, names=names, kinds=kinds, target_roas=roas, running_keys=running_keys)
        in_plan = Mon.attach_month_daily(in_plan, current)
        out_plan = Mon.attach_month_daily(out_plan, current)
        classified = in_plan
        # Checkpoint harian ke depan (satu entri per tanggal laporan)
        if features is not None and not in_plan.empty and report_end is not None:
            merged = in_plan if out_plan.empty else pd.concat([in_plan, out_plan], ignore_index=True)
            updated, changed = Mon.record_daily_checkpoint(cur, report_date=report_end, rows=merged)
            if changed:
                store = C.Store(features, "iklan")
                all_c = [updated if int(c.get("id", 0)) == int(updated.get("id", 0)) else c for c in store.all()]
                # jaga campaign yang belum di store.all (edge)
                if not any(int(c.get("id", 0)) == int(updated.get("id", 0)) for c in all_c):
                    all_c.append(updated)
                try:
                    store.save(all_c, username=username or "system")
                    cur = updated
                except Exception:
                    pass

    verdict = Mon.rollup(classified, summary, track=track, target_roas=roas, store_roas=store_roas)
    _hero(verdict)

    # -------- A. Hasil sejak campaign + pembanding bulan vs sejak campaign
    biaya_status = str((track or {}).get("biaya_status") or "")
    biaya_status_label = {
        "kurang terserap": "masih di bawah rencana",
        "lebih boros": "di atas rencana",
        "sesuai": "sesuai rencana",
    }.get(biaya_status, biaya_status or "–")
    st.markdown("### A · Hasil sejak campaign ditetapkan")
    st.caption(
        f"Angka iklan mengikuti laporan **Keseluruhan iklan** di Seller Center. "
        f"Periode: {fmt_date(since_start)} – {fmt_date(last_data) if store_since.get('hari') else '–'} "
        f"({fmt_num(store_since.get('hari') or days_since)} hari). "
        "Omzet iklan = penjualan yang dikaitkan ke iklan. Sales produk = penjualan produk seluruh toko "
        "(bukan angka yang sama)."
    )
    period = _period_sales(track, factor)
    a = st.columns(4)
    card(a[0], "Biaya iklan sejak disimpan", fmt_idr(spent_since),
         hint=f"rencana {fmt_idr(wallet['jalur_sejak'])} · <b>{biaya_status_label}</b>")
    card(a[1], "Omzet dari iklan sejak disimpan", fmt_idr(omzet_since),
         hint="penjualan yang dikaitkan ke iklan di Seller Center (bukan sales toko keseluruhan)")
    card(a[2], "ROAS iklan", fmt_num(store_roas, 1) if store_roas == store_roas else "–",
         hint=f"target {fmt_num(roas, 1)} · <b style='color:{_tone(store_roas >= roas * 0.9 if store_roas == store_roas else False)}'>"
              f"{'sudah mendekati target' if store_roas == store_roas and store_roas >= roas * 0.9 else 'masih di bawah target'}</b>")
    if track and track.get("status") not in (None, "Menunggu data"):
        on = track["status"] == "On track"
        card(a[3], "Status sales bersih", "✅ On track" if on else "⚠️ Tertinggal",
             hint=f"{track['hari']} hari · mencapai {fmt_pct(track['pct_sales'], 1)} dari jalur rencana")
    else:
        card(a[3], "Status sales bersih", "–", hint="menunggu data baru setelah campaign disimpan")

    produk_mtd = float(mtd_produk) if mtd_produk is not None else float("nan")
    bersih_mtd = float(mtd) if mtd is not None else float("nan")
    tacos_mtd_p, tacos_mtd_b = _tacos_pair(float(spent_month or 0), produk_mtd, bersih_mtd)
    st.markdown("#### Pembanding · bulan berjalan vs sejak campaign")
    st.caption(
        "Kiri: dari tanggal 1 bulan ini. Kanan: hanya sejak campaign disimpan. "
        "Persentase biaya iklan dihitung pada periode yang sama agar perbandingannya adil."
        + (" Angka sales produk di kanan masih perkiraan — simpan ulang rencana agar lebih tepat."
           if period.get("est") else "")
    )
    left, right = st.columns(2)
    left.markdown("**Bulan berjalan**")
    card(left, "Sales produk bulan ini", fmt_idr(produk_mtd) if produk_mtd == produk_mtd else "–",
         hint="nilai jual produk toko sejak tanggal 1 sampai data terakhir")
    card(left, "Sales bersih bulan ini", fmt_idr(bersih_mtd) if bersih_mtd == bersih_mtd else "–",
         hint="acuan target toko (setelah batal, belum bayar, dan retur)"
         + (f" · jalur {fmt_idr(track['jalur_sales'])} · {_signed(track['selisih_sales'])}"
            if track and track.get("status") not in (None, "Menunggu data") else ""))
    card(left, "Persentase biaya vs sales produk",
         fmt_pct(tacos_mtd_p, 1) if tacos_mtd_p == tacos_mtd_p else "–",
         hint="berapa persen biaya iklan dari sales produk bulan ini · makin kecil makin hemat")
    card(left, "Persentase biaya vs sales bersih",
         fmt_pct(tacos_mtd_b, 1) if tacos_mtd_b == tacos_mtd_b else "–",
         hint="berapa persen biaya iklan dari sales bersih bulan ini · makin kecil makin hemat")
    right.markdown("**Sejak campaign disimpan**")
    card(right, "Sales produk sejak campaign",
         fmt_idr(period["produk"]) if period["produk"] == period["produk"] else "–",
         hint=("perkiraan sementara · simpan ulang rencana agar angka pasti"
               if period.get("est") else "nilai jual produk toko sejak campaign disimpan"))
    card(right, "Sales bersih sejak campaign",
         fmt_idr(period["bersih"]) if period["bersih"] == period["bersih"] else "–",
         hint="sales bersih toko sejak campaign disimpan")
    card(right, "Persentase biaya vs sales produk",
         fmt_pct(period["tacos_produk"], 1) if period["tacos_produk"] == period["tacos_produk"] else "–",
         hint="biaya iklan sejak campaign dibanding sales produk periode yang sama")
    card(right, "Persentase biaya vs sales bersih",
         fmt_pct(period["tacos_bersih"], 1) if period["tacos_bersih"] == period["tacos_bersih"] else "–",
         hint="biaya iklan sejak campaign dibanding sales bersih periode yang sama")

    tip = Mon.spend_gap_tip(wallet, store_since, summary)
    if tip:
        st.caption(tip)

    # -------- B. Dompet budget
    st.markdown("### B · Dompet budget campaign")
    st.caption(
        "Urutan baca: (1) total budget campaign → (2) sudah terpakai bulan ini → (3) sisa bulan → "
        "(4) patokan budget harian di rencana. Kartu 4 bukan sisa harian dan bukan rata-rata terpakai."
    )
    avg_since = spent_since / days_since if days_since else 0.0
    plan_daily = float(wallet["rencana_harian"] or 0)
    if days_since and plan_daily > 0:
        if avg_since > plan_daily * 1.05:
            vs_plan = "di atas patokan"
        elif avg_since < plan_daily * 0.95:
            vs_plan = "di bawah patokan"
        else:
            vs_plan = "mendekati patokan"
        daily_hint = (
            f"Ini patokan budget/hari saat campaign disimpan — bukan sisa budget. "
            f"Rata-rata terpakai sejak campaign: {fmt_idr(avg_since)}/hari ({vs_plan})."
        )
    else:
        daily_hint = "Patokan budget per hari yang disimpan di campaign (bukan sisa bulan ÷ sisa hari)."
    w = st.columns(4)
    card(w[0], "1. Budget total campaign", fmt_idr(wallet["budget_total"]),
         hint=f"disimpan saat campaign dibuat · Target ROAS {fmt_num(wallet['roas_target'], 1)}")
    card(w[1], "2. Terpakai bulan ini", fmt_idr(wallet["terpakai_bulan"]),
         hint="seluruh biaya iklan dari tanggal 1 sampai data terakhir")
    card(w[2], "3. Sisa budget bulan", fmt_idr(wallet["sisa_bulan"]),
         hint=f"total dikurangi yang sudah terpakai · masih ada {fmt_num(wallet['sisa_hari_rencana'])} hari di periode rencana")
    card(w[3], "4. Patokan budget harian", fmt_idr(plan_daily), hint=daily_hint)

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

    # -------- 1. Semua iklan campaign: urut omzet, insight, Detailed, di luar plan
    st.markdown("### 1 · Pelaksanaan per iklan (sejak disimpan)")
    if not base:
        st.info("Campaign tanpa baseline evaluasi. Simpan ulang sebagai campaign baru agar bisa dibanding harian.")
    elif report_end is None or report_end < start:
        st.info(f"Laporan iklan s.d. {fmt_date(report_end) if report_end else '–'} belum melewati mulai campaign {fmt_date(start)}. Unggah laporan hari kemarin.")
    elif not planned and classified.empty:
        st.info("Belum ada hari baru sejak campaign disimpan. Unggah laporan iklan esok hari.")
    else:
        aktif = fmt_num(summary.get("dijalankan", 0)) if summary else "0"
        rencana = fmt_num(len(in_plan)) if not in_plan.empty else fmt_num(len(planned))
        st.caption(
            f"Daftar semua iklan di campaign, diurut dari omzet terbesar. "
            f"{aktif}/{rencana} sudah sesuai rencana · data s.d. {fmt_date(report_end)} "
            f"({fmt_num(summary.get('hari', 0) if summary else 0)} hari). "
            f"Di rencana = budget campaign · Di Shopee = yang harus diisi "
            f"(minimal {fmt_idr(A.SHOPEE_MIN_SINGLE)} tunggal / {fmt_idr(A.SHOPEE_MIN_GROUP)} grup). "
            "Terpakai bulan ini = rata-rata sejak tanggal 1. "
            "Terpakai sejak campaign = rata-rata setelah campaign disimpan."
        )
        cid = int(cur.get("id") or 0)
        if in_plan.empty:
            st.info("Tidak ada baris iklan di rencana tersimpan.")
        else:
            need = in_plan.loc[in_plan["Tindakan"] != "Pertahankan"] if "Tindakan" in in_plan.columns else in_plan.iloc[0:0]
            if not need.empty:
                st.markdown(f"**Perlu tindakan** · {fmt_num(len(need))} iklan (dari analisa terakhir)")
            for _, r in in_plan.iterrows():
                _ad_row_card(r, cur=cur, report_end=report_end, prefix="in", cid=cid)

            view = Mon.rename_budget_triad(in_plan)
            view_cols = [c for c in [
                "Iklan", "Jenis", "Status SC", "Status goals", "Tindakan",
                "Budget di rencana/hari", "Budget di Shopee/hari",
                "Terpakai bulan ini/hari", "Terpakai sejak campaign/hari",
                "Biaya sejak disimpan", "Omzet iklan sejak disimpan", "ROAS aktual", "Saran",
            ] if c in view.columns]
            money_kinds = {c: "money" for c in view_cols if c.endswith("/hari") or c.startswith(("Biaya", "Omzet"))}
            money_kinds["ROAS aktual"] = "dec"
            with st.expander(f"Tabel ringkas rencana · {fmt_num(len(view))} iklan", expanded=False):
                show_table(
                    view[view_cols], kinds=money_kinds,
                    column_config={"Iklan": st.column_config.TextColumn(width="large"),
                                   "Saran": st.column_config.TextColumn(width="large")},
                )
                download_excel(view[view_cols], f"pantau_iklan_{cid}.xlsx", key="xl-adt-mon", label="Unduh pantauan")

        if not out_plan.empty:
            st.markdown("### Di luar rencana campaign")
            st.caption(
                f"{fmt_num(len(out_plan))} iklan sedang berbiaya di Seller Center tetapi tidak masuk campaign tersimpan. "
                "Ditampilkan terpisah supaya tidak tercampur dengan rencana."
            )
            for _, r in out_plan.iterrows():
                _ad_row_card(r, cur=cur, report_end=report_end, prefix="out", cid=cid)
            out_view = Mon.rename_budget_triad(out_plan)
            out_cols = [c for c in [
                "Iklan", "Jenis", "Status SC", "Status goals", "Tindakan",
                "Budget di rencana/hari", "Budget di Shopee/hari",
                "Terpakai bulan ini/hari", "Terpakai sejak campaign/hari",
                "Biaya sejak disimpan", "Omzet iklan sejak disimpan", "ROAS aktual", "Saran",
            ] if c in out_view.columns]
            out_kinds = {c: "money" for c in out_cols if c.endswith("/hari") or c.startswith(("Biaya", "Omzet"))}
            out_kinds["ROAS aktual"] = "dec"
            with st.expander(f"Tabel di luar plan · {fmt_num(len(out_view))} iklan", expanded=False):
                show_table(
                    out_view[out_cols], kinds=out_kinds,
                    column_config={"Iklan": st.column_config.TextColumn(width="large"),
                                   "Saran": st.column_config.TextColumn(width="large")},
                )
                download_excel(out_view[out_cols], f"pantau_luar_plan_{cid}.xlsx", key="xl-adt-out", label="Unduh di luar plan")

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
