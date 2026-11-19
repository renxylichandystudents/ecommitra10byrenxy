"""UI Pantau rencana tersimpan: pelaksanaan campaign vs realisasi Seller Center."""

from __future__ import annotations

import html
from datetime import date, timedelta
from functools import partial

import pandas as pd
import streamlit as st

from src.core import ads_monitor as Mon
from src.core import ads_month as M
from src.core import ads_strategy as A
from src.core import campaigns as C
from src.core.fmt import fmt_date
from src.ui import campaign_ui as cmp
from src.ui.common import card, download_excel, fmt_idr, fmt_num, fmt_pct
from src.utils.format import show_table as _show_table

show_table = partial(_show_table, dash_missing=True)

UP, WARN, DOWN, MUTED = "#059669", "#d97706", "#dc2626", "#64748b"
LEVEL_COLOR = {"ok": UP, "warn": WARN, "alert": DOWN, "info": MUTED}


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
    """Anggota rencana = semua kunci di `iklan` tersimpan. Nilai minggu berjalan hanya menimpa budget, tidak menambah/menghapus anggota."""
    saved_planned: dict[str, float] = {}
    saved = cmp.frame_of(cur.get("iklan"))
    if not saved.empty and "key" in saved.columns and "Budget harian usulan" in saved.columns:
        saved_planned = {str(k): float(v or 0) for k, v in zip(saved["key"], saved["Budget harian usulan"])}

    week_vals: dict[str, float] = {}
    weekly = cmp.frame_of(cur.get("iklan_minggu"))
    week_no = ((report_end - start).days // 7 + 1) if report_end else 1
    if not weekly.empty and "_key" in weekly.columns:
        cols = [c for c in weekly.columns if c.startswith("Minggu ")]
        col = f"Minggu {min(max(week_no, 1), len(cols))}" if cols else None
        if col and col in weekly.columns:
            week_vals = {str(k): float(v or 0) for k, v in zip(weekly["_key"], weekly[col])}

    if saved_planned:
        planned = dict(saved_planned)
        for key, value in week_vals.items():
            if key in planned:
                planned[key] = value
        return planned
    return week_vals


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


def _plan_setup_labels(
    plan: float,
    setup: float,
    *,
    actual_since: float = 0.0,
    actual_month: float = float("nan"),
) -> tuple[str, str]:
    """Budget 0 di campaign = sengaja dihentikan.

    Di Shopee = budget yang diisi di SC, bukan rata-rata terpakai. Jika rencana/setup 0 tetapi
    laporan masih mencatat biaya, label 'masih berbiaya' tanpa menempelkan Rp/hari (itu ada di Terpakai).
    """
    spending = (actual_since or 0) > 5_000 or (actual_month == actual_month and actual_month > 5_000)
    if plan <= 0 and setup <= 0:
        if spending:
            return "dihentikan (Rp 0)", "masih berbiaya — pause belum efektif"
        return "dihentikan (Rp 0)", "tidak diisi (sesuai jeda)"
    if plan <= 0:
        return "dihentikan (Rp 0)", _fmt_hari(setup)
    if setup <= 0:
        return _fmt_hari(plan), "belum diisi"
    return _fmt_hari(plan), _fmt_hari(setup)


def _block_header(title: str, detail: str, *, tone: str = "info") -> None:
    """Pembatas antar blok campaign — lebih menonjol dari caption biasa."""
    palette = {
        "warn": ("#fff7ed", "#9a3412", "#fdba74"),
        "alert": ("#fef2f2", "#991b1b", "#fca5a5"),
        "ok": ("#ecfdf5", "#065f46", "#6ee7b7"),
        "info": ("#f1f5f9", "#0f172a", "#94a3b8"),
    }
    bg, fg, border = palette.get(tone, palette["info"])
    st.markdown(
        f"<div style='margin:1.1rem 0 .55rem;padding:.7rem .95rem;border-radius:10px;"
        f"background:{bg};border:1px solid {border};border-left:6px solid {fg}'>"
        f"<div style='font-size:1.05rem;font-weight:800;color:{fg};letter-spacing:.01em'>"
        f"{html.escape(title)}</div>"
        f"<div style='margin-top:.2rem;font-size:var(--fs-sm);color:#475569;line-height:1.45'>"
        f"{html.escape(detail)}</div></div>",
        unsafe_allow_html=True,
    )


def _ad_row_card(
    r: pd.Series,
    *,
    cur: dict,
    report_end: date | None,
    prefix: str,
    cid: int,
    members: pd.DataFrame | None = None,
    target_roas: float = 8.0,
    contribution: dict | None = None,
    scope: str = "Dalam rencana",
    units=None,
    products: pd.DataFrame | None = None,
    planned_singles: set[str] | frozenset | None = None,
    window_start: date | None = None,
) -> None:
    """Satu baris rekap iklan: insight singkat + budget + 2 angka terpakai + expander historis.

    Untuk iklan grup: lampiran performa & saran tiap produk anggota agar item lemah tidak dipaksa lanjut.
    Grup belum setup: bandingkan anggota vs iklan aktif lain + kelayakan setup.
    """
    name = str(r.get("Iklan") or r.get("_key") or "")
    key = str(r.get("_key") or "")
    jenis = str(r.get("Jenis") or "")
    act = str(r.get("Tindakan") or "–")
    plan = float(r.get("Budget usulan/hari") or r.get("Budget di rencana/hari") or 0)
    setup = float(r.get("Budget efektif Shopee/hari") or r.get("Budget di Shopee/hari") or 0)
    since = float(r.get("Biaya aktual/hari") or r.get("Terpakai sejak campaign/hari") or 0)
    month = r.get("Biaya bulan ini/hari")
    month_v = float(month) if month == month and month is not None else float("nan")
    omzet = float(r.get("Omzet iklan sejak disimpan") or 0)
    biaya = float(r.get("Biaya sejak disimpan") or 0)
    roas = float(r["ROAS aktual"]) if r.get("ROAS aktual") == r.get("ROAS aktual") else float("nan")
    days = int(r.get("Hari dievaluasi") or 0)
    if days <= 0 and since > 0 and biaya > 0:
        days = max(int(round(biaya / since)), 1)
    # Periode eksplisit agar bisa disamakan filter Seller Center (hindari ambigu "5 hari")
    win_lo = window_start
    win_hi = report_end
    if win_lo is None and win_hi is not None and days > 0:
        win_lo = win_hi - timedelta(days=max(days - 1, 0))
    period_txt = ""
    if win_lo is not None and win_hi is not None:
        period_txt = f"{fmt_date(win_lo)}–{fmt_date(win_hi)}"
    plan_txt, setup_txt = _plan_setup_labels(plan, setup, actual_since=since, actual_month=month_v)
    # Omzet ≠ biaya. Status "di tempat lain" sudah di highlight oranye — jangan ulangi di hasil.
    if act == "Sudah diiklankan di tempat lain":
        alts = Mon._alts_for_plan_key(key, units=units, members=members)
        if alts:
            a0 = alts[0]
            hasil = (
                f"Slot rencana Rp 0 · lihat realisasi di «{a0.get('nama') or a0.get('unit')}»: "
                f"biaya {_fmt_hari(float(a0.get('biaya') or 0))}"
                + (f" · omzet {_fmt_hari(float(a0.get('omzet') or 0))}" if float(a0.get("omzet") or 0) > 0 else "")
            )
        else:
            hasil = "Slot rencana Rp 0 · produk aktif di iklan lain (lihat saran)"
    else:
        hasil = (
            (f"Sejak rencana disimpan di fitur · laporan {period_txt}" if period_txt else "Sejak rencana disimpan di fitur")
            + (f" ({fmt_num(days)} hari di file laporan)" if days > 0 else "")
            + f": omzet {fmt_idr(omzet)} · biaya {fmt_idr(biaya)}"
            + (f" · ROAS {fmt_num(roas, 1)}×" if roas == roas else "")
            + (" · samakan rentang ini di Seller Center" if period_txt else "")
        )
    is_group = key.startswith("grup:") or jenis.strip().lower().startswith("grup")
    group_active = not (
        act == "Buat / aktifkan"
        or (since <= 5_000 and (month_v != month_v or month_v <= 5_000) and omzet <= 0)
    )
    member_frame = (
        Mon.group_members_review(
            members, key, target_roas=target_roas, contribution=contribution,
            group_active=group_active, units=units, products=products,
            planned_singles=planned_singles,
        )
        if is_group else pd.DataFrame()
    )
    saran_txt = str(r.get("Saran") or "")
    if is_group and not member_frame.empty:
        act, saran_txt = Mon.group_card_from_members(
            member_frame, act=act, tip=saran_txt,
            expected=setup, cost_since=since, cost_month=month_v,
        )
        member_note = Mon.group_members_summary(member_frame)
        if member_note and member_note not in saran_txt:
            saran_txt = f"{saran_txt} {member_note}".strip()
    color = (
        DOWN if act.startswith(("Jeda", "Turunkan", "Keluarkan"))
        else (UP if act == "Pertahankan" else WARN)
    )
    if act == "Sudah diiklankan di tempat lain":
        color = WARN
    stock_sum = Mon.stock_summary_for_ad(products, key, units=units, members=members)
    if stock_sum.get("kosong"):
        saran_txt = (
            f"{saran_txt} {stock_sum['kosong']} produk stok toko+DC kosong — "
            "jangan naikkan budget demi item kosong."
        ).strip()
    spend_note = ""
    if month_v == month_v and since > 0 and month_v + 1 < since:
        spend_note = (
            "<div style='color:#64748b;font-size:var(--fs-xs);margin-top:.35rem;line-height:1.4'>"
            "Terpakai bulan ini boleh lebih kecil dari sejak campaign: bulan = rata-rata dari tanggal 1 "
            "(termasuk hari sebelum campaign), sejak campaign = hanya setelah campaign disimpan."
            "</div>"
        )
    if plan <= 0 and since > 5_000:
        day_bit = f" / {fmt_num(days)} hari = {_fmt_hari(since)}" if days > 0 else f" · rata-rata {_fmt_hari(since)}"
        month_bit = f" · bulan ini {_fmt_hari(month_v)}" if month_v == month_v else ""
        spend_note += (
            f"<div style='color:#991b1b;font-size:var(--fs-sm);margin-top:.35rem;line-height:1.45'>"
            f"<b>Biaya masih tercatat di SC:</b> «{html.escape(name)}»"
            f" · biaya {fmt_idr(biaya)}{day_bit}{month_bit}."
            f" Pause iklan dengan nama yang sama di Seller Center."
            f"</div>"
        )
    stock_color = (
        DOWN if stock_sum["status"] == "kosong"
        else (WARN if stock_sum["status"] == "isi_dari_dc" else MUTED)
    )
    spend_note += (
        f"<div style='color:{stock_color};font-size:var(--fs-sm);margin-top:.35rem;line-height:1.45'>"
        f"<b>Stok harian (faktor layak iklan):</b> {html.escape(stock_sum['teks'])}"
        f"</div>"
    )
    scope_color = MUTED if scope.startswith("Dalam") else DOWN
    st.markdown(
        f"<div style='border:1px solid #e2e8f0;border-radius:12px;padding:.75rem .9rem;margin:.4rem 0;background:#fff'>"
        f"<div style='display:flex;flex-wrap:wrap;gap:.5rem 1rem;justify-content:space-between;align-items:baseline'>"
        f"<div style='font-weight:800'>"
        f"<span style='font-size:var(--fs-xs);font-weight:700;color:{scope_color};margin-right:.45rem'>"
        f"{html.escape(scope)}</span>"
        f"{html.escape(name)} · "
        f"<span style='color:{color}'>{html.escape(act)}</span></div>"
        f"<div style='color:#475569;font-size:var(--fs-sm)'>{hasil}</div></div>"
        f"<div style='color:#475569;font-size:var(--fs-sm);margin-top:.35rem;line-height:1.5'>"
        f"{html.escape(saran_txt)}</div>"
        f"<div style='display:flex;flex-wrap:wrap;gap:.75rem 1.25rem;margin-top:.45rem;font-size:var(--fs-sm)'>"
        f"<span><b>Di rencana</b> {html.escape(plan_txt)}</span>"
        f"<span><b>Di Shopee</b> {html.escape(setup_txt)}</span>"
        f"<span><b>Terpakai bulan ini</b> {_fmt_hari(month_v)}"
        + (f" <span style='color:#94a3b8'>(rata-rata tgl 1–{fmt_date(win_hi) if win_hi else 'laporan'})</span>" if month_v == month_v else "")
        + f"</span>"
        f"<span><b>Terpakai sejak campaign</b> {_fmt_hari(since)}"
        + (f" · {fmt_num(days)} hari laporan" if days > 0 else "")
        + (f" · {period_txt}" if period_txt else "")
        + f"</span></div>"
        f"{spend_note}</div>",
        unsafe_allow_html=True,
    )
    if is_group:
        n_mem = len(member_frame)
        acts = member_frame["Tindakan"] if n_mem and "Tindakan" in member_frame.columns else pd.Series(dtype=str)
        if not group_active and n_mem:
            n_layak = int((acts == "Layak di-setup di grup ini").sum())
            n_skip = int((acts == "Tidak perlu di-setup").sum())
            n_else = int((acts == "Sudah diiklankan di tempat lain").sum())
            label = (
                f"Anggota grup · belum setup ({fmt_num(n_mem)} produk"
                + (f": {fmt_num(n_layak)} layak" if n_layak else ": 0 layak")
                + (f", {fmt_num(n_skip)} tidak perlu" if n_skip else "")
                + (f", {fmt_num(n_else)} sudah di tempat lain" if n_else else "")
                + ")"
            )
            need_mem = n_layak
        else:
            keep_labels = {"Pertahankan di grup", "Layak di-setup di grup ini"}
            need_mem = int((~acts.isin(keep_labels)).sum()) if n_mem else 0
            label = (
                f"Anggota grup · performa & saran ({fmt_num(n_mem)} produk"
                + (f", {fmt_num(need_mem)} perlu tindakan" if need_mem else "")
                + ")"
            )
        with st.expander(label, expanded=False):
            if group_active:
                st.caption(
                    "Biaya/omzet di tabel = laporan iklan grup periode terakhir "
                    "(bukan rata-rata kartu campaign di atas). "
                    "Jika produk sudah jadi iklan tunggal → keluarkan dari grup (jangan hanya turunkan budget). "
                    "Stok 10037/10062/10036 = faktor layak iklan. Kolom Iklan lain = iklan lain yang memuat produk sama."
                )
            else:
                st.caption(
                    "Urutan: Layak di-setup → Tidak perlu → sudah aktif di iklan lain. "
                    "Layak hanya bila prediksi sales mendorong target (batas 95% sales toko / qty laku) "
                    "atau histori ROAS kuat, plus stok toko 10037. "
                    "Kolom Saran menjelaskan kenapa harus / tidak perlu diiklankan. "
                    "Toko kosong tapi DC ada → restock dulu, jangan langsung setup."
                )
            if member_frame.empty:
                st.info(
                    "Belum ada baris produk di laporan iklan grup untuk campaign ini. "
                    "Unggah laporan iklan grup terbaru, atau aktifkan grup di Seller Center dulu."
                )
            else:
                show_table(
                    member_frame,
                    kinds={
                        "Stok 10037": "count", "Stok 10062": "count", "Stok 10036": "count",
                        "Prediksi omzet/hari": "money",
                        "Biaya di grup/hari": "money", "Omzet di grup/hari": "money",
                        "ROAS di grup": "dec",
                        "Porsi omzet grup": "pct", "Porsi biaya grup": "pct",
                    },
                    column_config={
                        "Produk": st.column_config.TextColumn(width="large"),
                        "Iklan lain": st.column_config.TextColumn(width="medium"),
                        "Saran": st.column_config.TextColumn(width="large"),
                    },
                    key=f"grp-mem-{prefix}-{cid}-{key}",
                )
    with st.expander("Lihat riwayat evaluasi campaign", expanded=False):
        st.caption(
            "Tiap baris = **satu catatan Pantau** (buka halaman / unggah laporan) — "
            f"**bukan** jumlah hari Seller Center"
            + (f". Periode laporan acuan kartu: **{period_txt}** ({fmt_num(days)} hari di file)." if period_txt and days > 0 else ".")
            + " Kolom **Hari laporan sejak campaign** = umur jendela evaluasi di file laporan "
            "(bisa 5 sementara catatan Pantau baru 2). "
            "**Naik sejak catatan lalu** = selisih total kumulatif antar catatan, "
            "bukan biaya 1 hari kalender. Samakan rentang tanggal di SC bila membandingkan angka."
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
            "biaya_hari": since, "biaya_bulan_hari": month_v, "budget_plan": plan, "budget_setup": setup,
            "hari": days, "tindakan": act,
        }
        hist = Mon.daily_history_for(
            cur, key,
            baseline_row={"tanggal": base_dt or "baseline", "budget_plan": plan, "budget_setup": setup},
            today_row=today_row,
        )
        if hist.empty:
            st.info("Belum ada catatan evaluasi untuk iklan ini.")
        else:
            show_table(
                hist,
                kinds={
                    "Hari laporan sejak campaign": "count",
                    "Budget di rencana/hari": "money", "Budget di Shopee/hari": "money",
                    "Naik biaya sejak catatan lalu": "money", "Naik omzet sejak catatan lalu": "money",
                    "Hari laporan di antara catatan": "count",
                    "Total biaya sejak campaign": "money", "Total omzet sejak campaign": "money",
                    "ROAS sejak campaign": "dec",
                    "Rata-rata biaya/hari sejak campaign": "money",
                    "Rata-rata biaya/hari bulan ini": "money",
                },
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
    target = float(s.get("target") or 0)
    goal = target_now if target_now > 0 else target
    roas = float(s.get("roas") or 8.0)
    budget_daily = float(s.get("biaya_harian_rencana") or s.get("budget_harian") or 0)

    # ---- Performa toko dari laporan all iklan per tanggal dalam periode campaign
    # Contoh Campaign 15–22 Nov, hari ini 19 → ambil 15 s.d. 18 (hari penuh; 19 belum dihitung)
    since_start = Mon.campaign_eval_start(cur) or start
    eval_end = Mon.campaign_eval_end(cur, today=today)
    if eval_end is not None and first_open is not None:
        eval_end = min(eval_end, first_open - timedelta(days=1))
    last_data = eval_end
    store_since = {"biaya": 0.0, "omzet": 0.0, "hari": 0}
    if since_start and eval_end and since_start <= eval_end and ads_overall is not None:
        daily_win = M.daily_ad_totals(ads_overall, start=since_start, end=eval_end)
        if not daily_win.empty:
            store_since = {
                "biaya": float(daily_win["Biaya"].sum()),
                "omzet": float(daily_win["Omzet"].sum()),
                "hari": int(len(daily_win)),
            }
    calendar_days = (
        (eval_end - since_start).days + 1
        if since_start and eval_end and eval_end >= since_start
        else 0
    )
    days_since = calendar_days or int(store_since.get("hari") or 0)
    # Hanya angka all iklan per tanggal — jangan jatuh ke prorata bulanan
    spent_since = float(store_since.get("biaya") or 0)
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
            classified = Mon.classify_rows(
                frame, target_roas=roas, running_keys=running_keys, units=units, members=members,
            )
        in_plan, out_plan = Mon.split_in_out_plan(
            classified, planned, current, base, names=names, kinds=kinds, target_roas=roas,
            running_keys=running_keys, units=units, members=members,
        )
        in_plan = Mon.attach_month_daily(in_plan, current)
        out_plan = Mon.attach_month_daily(out_plan, current)
        in_plan = Mon.refresh_tips_after_month(
            in_plan, target_roas=roas, running_keys=running_keys, units=units, members=members,
        )
        out_plan = Mon.refresh_tips_after_month(
            out_plan, target_roas=roas, running_keys=running_keys, units=units, members=members,
        )
        singles = Mon.planned_single_codes(acts_saved)
        in_plan = Mon.enrich_group_actions(
            in_plan, members, target_roas=roas, units=units, products=products,
            contribution=contribution, planned_singles=singles,
        )
        out_plan = Mon.enrich_group_actions(
            out_plan, members, target_roas=roas, units=units, products=products,
            contribution=contribution, planned_singles=singles,
        )
        classified = in_plan
        # Checkpoint hanya untuk hari laporan yang sudah penuh (bukan hari ini)
        checkpoint_day = report_end
        if checkpoint_day is not None and checkpoint_day >= today:
            checkpoint_day = today - timedelta(days=1)
        if features is not None and not in_plan.empty and checkpoint_day is not None and checkpoint_day >= start:
            merged = in_plan if out_plan.empty else pd.concat([in_plan, out_plan], ignore_index=True)
            period_now = _period_sales(track, factor)
            plan_hari = float(pd.to_numeric(merged.get("Budget usulan/hari"), errors="coerce").fillna(0).sum()) if "Budget usulan/hari" in merged.columns else 0.0
            actual_hari = float(pd.to_numeric(merged.get("Budget efektif Shopee/hari"), errors="coerce").fillna(0).sum()) if "Budget efektif Shopee/hari" in merged.columns else 0.0
            # Realisasi hari checkpoint dari laporan all iklan 1 tanggal (bukan prorata)
            day_tot = M.daily_ad_totals(ads_overall, start=checkpoint_day, end=checkpoint_day)
            realisasi_hari = float(day_tot.iloc[0]["Biaya"]) if not day_tot.empty else float("nan")
            toko_snap = Mon.build_toko_snapshot(
                budget_plan_hari=plan_hari,
                budget_actual_hari=actual_hari,
                biaya_sejak=float(spent_since or 0),
                omzet_kotor_sejak=float(omzet_since or 0),
                bersih_sejak=period_now.get("bersih"),
                produk_sejak=period_now.get("produk"),
                produk_mtd=float(mtd_produk) if mtd_produk is not None else float("nan"),
                bersih_mtd=float(mtd) if mtd is not None else float("nan"),
                iklan_tercatat=len(merged),
                realisasi_biaya_hari=realisasi_hari,
                target_roas=roas,
            )
            updated, changed = Mon.record_daily_checkpoint(
                cur, report_date=checkpoint_day, rows=merged, toko=toko_snap,
            )
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
        f"Angka dari laporan **Keseluruhan iklan (all iklan)** per tanggal dalam periode campaign "
        f"**{fmt_date(start)} – {fmt_date(end)}**. "
        f"Yang dihitung sekarang: **{fmt_date(since_start)} – {fmt_date(last_data) if last_data else '–'}** "
        f"({fmt_num(days_since)} hari penuh; hari ini belum dihitung). "
        f"Ada angka harian untuk {fmt_num(store_since.get('hari') or 0)} tanggal. "
        "Omzet iklan = penjualan yang dikaitkan ke iklan di laporan itu."
    )
    period = _period_sales(track, factor)
    a = st.columns(4)
    card(a[0], "Biaya iklan periode campaign", fmt_idr(spent_since),
         hint=f"rencana {fmt_idr(wallet['jalur_sejak'])} · <b>{biaya_status_label}</b> · dari all iklan per tanggal")
    card(a[1], "Omzet dari iklan periode campaign", fmt_idr(omzet_since),
         hint="penjualan dikaitkan ke iklan di laporan all iklan (bukan sales toko keseluruhan)")
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
        # Band sempit (±0,5%) = "sesuai"; di luar itu langsung di atas / di bawah (bukan "mendekati").
        if avg_since > plan_daily * 1.005:
            selisih = avg_since - plan_daily
            vs_plan = f"di atas patokan · lebih {fmt_idr(selisih)}/hari"
        elif avg_since < plan_daily * 0.995:
            selisih = plan_daily - avg_since
            vs_plan = f"di bawah patokan · kurang {fmt_idr(selisih)}/hari"
        else:
            vs_plan = "sesuai patokan"
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

    # -------- Pelaksanaan: campaign vs realisasi SC (poin 2 & 3 dihapus — fokus kecocokan plan)
    st.markdown("### Pelaksanaan · campaign vs realisasi Seller Center")
    if not base:
        st.info("Campaign tanpa baseline evaluasi. Simpan ulang sebagai campaign baru agar bisa dibanding harian.")
    elif report_end is None or report_end < start:
        st.info(
            f"Laporan iklan s.d. {fmt_date(report_end) if report_end else '–'} belum melewati mulai campaign "
            f"{fmt_date(start)}. Unggah laporan hari kemarin."
        )
    elif not planned and classified.empty:
        st.info("Belum ada hari baru sejak campaign disimpan. Unggah laporan iklan esok hari.")
    else:
        cid = int(cur.get("id") or 0)
        singles = Mon.planned_single_codes(acts_saved)
        exe = Mon.partition_execution(in_plan, target_roas=roas)
        counts = Mon.execution_counts(exe)
        luar_n = len(out_plan) if not out_plan.empty else 0
        st.caption(
            "Bandingkan **komitmen campaign** (budget/slot yang disimpan) dengan **realisasi laporan iklan** di Seller Center. "
            f"Data s.d. {fmt_date(report_end)} · Target ROAS {fmt_num(roas, 1)}×. "
            f"Ringkas: **{fmt_num(counts['sesuai'])} sesuai plan** "
            f"({fmt_num(counts['efektif'])} efektif · {fmt_num(counts['tidak_efektif'])} tidak efektif · "
            f"{fmt_num(counts['boros'])} boros) · "
            f"**{fmt_num(counts['tidak'])} tidak sesuai plan** · "
            f"**{fmt_num(luar_n)} di luar plan**."
        )

        # Jendela evaluasi = periode campaign (mulai–selesai), dibatasi hari penuh (kemarin)
        window_start = since_start
        progress_end = eval_end or (today - timedelta(days=1))

        def _render_cards(frame: pd.DataFrame, *, prefix: str, scope: str) -> None:
            for _, r in frame.iterrows():
                _ad_row_card(
                    r, cur=cur, report_end=report_end, prefix=prefix, cid=cid,
                    members=members, target_roas=roas, contribution=contribution, scope=scope,
                    units=units, products=products, planned_singles=singles,
                    window_start=window_start,
                )

        # Progress: tiap hari kalender dalam periode campaign; biaya+omzet dari all iklan per tanggal
        plan_keys = {str(k) for k in (planned or {})}
        period_live = _period_sales(track, factor)
        plan_hari_live = float(
            pd.to_numeric(in_plan.get("Budget usulan/hari"), errors="coerce").fillna(0).sum()
        ) if not in_plan.empty and "Budget usulan/hari" in in_plan.columns else float(
            wallet.get("rencana_harian") or 0
        )
        live_toko = Mon.build_toko_snapshot(
            budget_plan_hari=plan_hari_live,
            budget_actual_hari=0.0,
            biaya_sejak=float(spent_since or 0),
            omzet_kotor_sejak=float(omzet_since or 0),
            bersih_sejak=period_live.get("bersih"),
            produk_sejak=period_live.get("produk"),
            produk_mtd=float(mtd_produk) if mtd_produk is not None else float("nan"),
            bersih_mtd=float(mtd) if mtd is not None else float("nan"),
            iklan_tercatat=len(in_plan) if not in_plan.empty else 0,
            target_roas=roas,
        )
        progress = Mon.campaign_daily_progress(
            cur, plan_keys,
            live_toko=live_toko, live_tanggal=progress_end, target_roas=roas,
            ads_overall=ads_overall, window_start=window_start, window_end=progress_end,
            factor=float(factor or 0), today=today,
        )
        st.markdown("#### Progress harian · periode campaign")
        period_caption = ""
        if window_start and progress_end and progress_end >= window_start:
            period_caption = (
                f" Periode campaign **{fmt_date(start)} – {fmt_date(end)}**. "
                f"Hari penuh yang dihitung: **{fmt_date(window_start)} – {fmt_date(progress_end)}** "
                "(hari ini belum dihitung)."
            )
        if progress.empty:
            st.info(
                "Belum ada hari penuh dalam periode campaign, atau belum ada laporan **Keseluruhan iklan**. "
                "Di Seller Center unduh all iklan filter **1 tanggal** untuk tiap hari campaign yang sudah lewat "
                "(atau unggah MTD berurutan), lalu unggah ke app."
            )
        else:
            st.caption(
                "Tiap baris = **satu tanggal kalender** dalam periode campaign."
                + period_caption
                + " **Realisasi biaya (hari itu)** & **omzet iklan** = dari laporan all iklan tanggal itu "
                "(sama cara baca filter 1 hari / Kemarin di SC — bukan bagi rata bulanan). "
                "**Sales dari iklan** = akumulasi omzet all iklan **bruto** sejak awal campaign s.d. tanggal itu. "
                "**Sales produk all** = akumulasi omzet **bersih** (bruto × faktor toko)."
            )
            with st.expander(f"Tabel progress harian · {fmt_num(len(progress))} catatan", expanded=False):
                show_table(
                    progress,
                    kinds={
                        "Budget plan/hari": "money",
                        "Realisasi biaya iklan (hari itu)": "money",
                        "Sales produk dari iklan sejak campaign": "money",
                        "ROAS iklan": "dec",
                        "Sales produk all sejak campaign": "money",
                        "ROAS sales all": "dec",
                        "Sales MTD produk": "money",
                        "Sales MTD bersih": "money",
                    },
                    column_config={
                        "Analisa keputusan hari itu": st.column_config.TextColumn(width="large"),
                    },
                    key=f"camp-progress-{cid}",
                )

        if in_plan.empty:
            st.info("Tidak ada baris iklan di rencana tersimpan.")
        else:
            # A. Sesuai plan
            st.markdown("#### A · Sesuai plan (slot campaign sudah jalan di kunci yang sama)")
            st.caption(
                "Iklan rencana yang sudah terlihat di laporan dengan kunci yang cocok. "
                "Di sini dinilai: efektif vs target, tidak efektif, atau boros budget."
            )
            if not exe["sesuai_efektif"].empty:
                _block_header(
                    f"Efektif / on target · {fmt_num(len(exe['sesuai_efektif']))} iklan",
                    f"Budget & ROAS sejalan rencana (target ROAS {fmt_num(roas, 1)}×). Pertahankan.",
                    tone="ok",
                )
                _render_cards(exe["sesuai_efektif"], prefix="ok", scope="Sesuai plan · efektif")
            if not exe["sesuai_tidak_efektif"].empty:
                _block_header(
                    f"Tidak efektif vs target · {fmt_num(len(exe['sesuai_tidak_efektif']))} iklan",
                    "Sudah setup sesuai plan, tetapi ROAS lemah atau budget belum terserap. "
                    "Naikkan Target ROAS / budget, atau tinjau isi iklan.",
                    tone="warn",
                )
                _render_cards(
                    exe["sesuai_tidak_efektif"], prefix="lemah", scope="Sesuai plan · tidak efektif",
                )
            if not exe["sesuai_boros"].empty:
                _block_header(
                    f"Boros vs budget plan · {fmt_num(len(exe['sesuai_boros']))} iklan",
                    "Terpakai jauh di atas budget di Shopee/rencana. Turunkan budget di Seller Center.",
                    tone="alert",
                )
                _render_cards(exe["sesuai_boros"], prefix="boros", scope="Sesuai plan · boros")
            if (
                exe["sesuai_efektif"].empty
                and exe["sesuai_tidak_efektif"].empty
                and exe["sesuai_boros"].empty
            ):
                st.info("Belum ada iklan yang masuk kategori sesuai plan. Lihat blok B di bawah.")

            # B. Tidak sesuai plan
            st.markdown("#### B · Tidak sesuai plan (struktur / setup belum cocok)")
            st.caption(
                "Komitmen campaign belum terwujud di slot yang benar: belum dibuat, dobel di iklan lain, "
                "jeda tertinggal, atau isi grup salah."
            )
            if not exe["tidak_belum_setup"].empty:
                _block_header(
                    f"Belum di-setup di Seller Center · {fmt_num(len(exe['tidak_belum_setup']))} iklan",
                    "Belum ada biaya/omzet di laporan untuk kunci iklan ini. Buat/aktifkan di SC.",
                    tone="warn",
                )
                _render_cards(
                    exe["tidak_belum_setup"], prefix="setup", scope="Tidak sesuai · belum setup",
                )
            if not exe["tidak_di_tempat_lain"].empty:
                _block_header(
                    f"Sudah diiklankan di tempat lain · {fmt_num(len(exe['tidak_di_tempat_lain']))} iklan",
                    "Produk aktif di iklan tunggal/grup lain — jangan buat dobel. "
                    "Angka realisasi ada di iklan lain (bukan Rp 0 di slot rencana).",
                    tone="alert",
                )
                # Scope netral — status oranye di kartu sudah cukup, hindari wording dobel
                _render_cards(
                    exe["tidak_di_tempat_lain"], prefix="lain", scope="Tidak sesuai plan",
                )
            if not exe["tidak_jeda"].empty:
                _block_header(
                    f"Jeda di rencana, masih berbiaya · {fmt_num(len(exe['tidak_jeda']))} iklan",
                    "Budget rencana Rp 0, tetapi laporan masih mencatat biaya — pause di SC.",
                    tone="alert",
                )
                _render_cards(exe["tidak_jeda"], prefix="jeda", scope="Tidak sesuai · jeda tertinggal")
            if not exe["tidak_isi_grup"].empty:
                _block_header(
                    f"Isi grup salah · {fmt_num(len(exe['tidak_isi_grup']))} iklan",
                    "Mayoritas anggota harus dikeluarkan (sudah tunggal / tanpa hasil). "
                    "Bersihkan anggota dulu — jangan hanya turunkan budget.",
                    tone="alert",
                )
                _render_cards(exe["tidak_isi_grup"], prefix="grup", scope="Tidak sesuai · isi grup")

            view = Mon.rename_budget_triad(in_plan)
            view_cols = [c for c in [
                "Iklan", "Jenis", "Status SC", "Status goals", "Tindakan",
                "Budget di rencana/hari", "Budget di Shopee/hari",
                "Terpakai bulan ini/hari", "Terpakai sejak campaign/hari",
                "Biaya sejak disimpan", "Omzet iklan sejak disimpan", "ROAS aktual", "Saran",
            ] if c in view.columns]
            money_kinds = {c: "money" for c in view_cols if c.endswith("/hari") or c.startswith(("Biaya", "Omzet"))}
            money_kinds["ROAS aktual"] = "dec"
            with st.expander(f"Tabel ringkas semua iklan dalam plan · {fmt_num(len(view))} iklan", expanded=False):
                show_table(
                    view[view_cols], kinds=money_kinds,
                    column_config={"Iklan": st.column_config.TextColumn(width="large"),
                                   "Saran": st.column_config.TextColumn(width="large")},
                )
                download_excel(view[view_cols], f"pantau_iklan_{cid}.xlsx", key="xl-adt-mon", label="Unduh pantauan")

        # C. Di luar plan
        st.markdown("#### C · Di luar plan (berbiaya di SC, tidak ada di campaign)")
        if out_plan.empty:
            st.caption("Tidak ada iklan berbiaya di luar campaign — bagus.")
        else:
            _block_header(
                f"Di luar rencana campaign · {fmt_num(len(out_plan))} iklan",
                "Berbiaya di Seller Center tetapi tidak masuk campaign tersimpan. "
                "Pause atau masukkan ke rencana baru bila mau dilanjutkan.",
                tone="alert",
            )
            _render_cards(out_plan, prefix="out", scope="Di luar plan")
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
