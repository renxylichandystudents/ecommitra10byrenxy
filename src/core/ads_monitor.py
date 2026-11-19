"""Pantauan campaign iklan tersimpan: status per iklan, saran perbaikan, item yang harus diiklankan.

Membaca hasil `ads_strategy.evaluate` + data prediksi/stok, lalu menyusun tindakan yang bisa dikerjakan di Seller Center
tanpa mengubah rumus prediksi atau safety stock.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.core import ads_strategy as A

_STATUS_RANK = {
    "Jeda / hentikan": 0,
    "Turunkan budget": 1,
    "Naikkan budget": 2,
    "Buat / aktifkan": 3,
    "Naikkan Target ROAS": 4,
    "Pertahankan": 5,
}


def _rp_hari(value: float) -> str:
    return f"Rp {value:,.0f}/hari".replace(",", ".")


def classify_rows(frame: pd.DataFrame, *, target_roas: float, running_keys: set[str] | None = None) -> pd.DataFrame:
    """Lengkapi baris evaluasi dengan Status goals, Status SC, Tindakan, Saran (bahasa manajer)."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    running = running_keys or set()
    actions, goals, tips, sc = [], [], [], []
    for _, r in out.iterrows():
        key = str(r.get("_key") or "")
        plan = float(r.get("Budget usulan/hari") or 0)
        expected = float(r.get("Budget efektif Shopee/hari") or A.implementable_budget(plan, r.get("Jenis") or key))
        cost = float(r.get("Biaya aktual/hari") or 0)  # terpakai sejak campaign
        month = r.get("Biaya bulan ini/hari")
        month_v = float(month) if month == month and month is not None else float("nan")
        roas = float(r.get("ROAS aktual")) if r.get("ROAS aktual") == r.get("ROAS aktual") else float("nan")
        done = str(r.get("Rekomendasi dijalankan")) == "Ya"
        is_run = key in running or any(k for k in running if k == key or key.endswith(":" + k.split(":")[-1]))
        if not is_run and running:
            report = "produk:" + key.split(":", 1)[1] if key.startswith(("pisah:", "baru:")) else key
            is_run = report in running or key in running
        sc_label = "Berjalan" if is_run or cost > max(expected * 0.3, 10_000) else "Tidak aktif / rendah"
        weak = cost > 0 and roas == roas and target_roas > 0 and roas < target_roas * 0.9
        spend_bits = f"Terpakai sejak campaign {_rp_hari(cost)}"
        if month_v == month_v:
            spend_bits = f"Terpakai bulan ini {_rp_hari(month_v)}; sejak campaign {_rp_hari(cost)}"

        if expected <= 0:
            if done or cost <= 5_000:
                goal, act, tip = "Sesuai rencana", "Pertahankan", (
                    "Iklan ini tetap tercatat di campaign, tetapi budget rencananya Rp 0 "
                    "(sengaja dihentikan). Tidak perlu diubah."
                )
            else:
                goal, act, tip = "Tidak sesuai rencana", "Jeda / hentikan", (
                    f"Iklan ini masuk campaign dengan budget rencana Rp 0 (sengaja dihentikan), "
                    f"tetapi masih berbiaya — {spend_bits}. "
                    "Pause / hentikan di Seller Center agar tidak terus berbiaya."
                )
        elif sc_label.startswith("Tidak") and expected > 0:
            goal, act, tip = "Belum aktif", "Buat / aktifkan", (
                f"Di rencana budget {_rp_hari(expected)}, tetapi iklan belum terlihat aktif di laporan. "
                "Aktifkan atau buat di Seller Center, lalu unggah laporan."
            )
        elif not done and cost > expected * 1.4:
            goal, act, tip = "Tidak sesuai rencana", "Turunkan budget", (
                f"{spend_bits} — lebih tinggi dari budget di Shopee ({_rp_hari(expected)}). "
                f"Di Seller Center, turunkan budget harian menjadi {_rp_hari(expected)}."
            )
        elif not done and cost < expected * 0.6:
            floor_note = (
                f" (rencana {_rp_hari(plan)}, dinaikkan ke minimum Shopee)"
                if expected > plan + 1 else ""
            )
            goal, act, tip = "Tidak sesuai rencana", "Naikkan budget", (
                f"{spend_bits} — masih di bawah budget di Shopee ({_rp_hari(expected)}){floor_note}. "
                "Naikkan budget harian di Seller Center, atau longgarkan Target ROAS agar budget terserap."
            )
        elif weak:
            goal, act, tip = "ROAS lemah", "Naikkan Target ROAS", (
                f"ROAS {roas:.1f}× masih di bawah target campaign {target_roas:.1f}×. "
                "Naikkan Target ROAS di Shopee atau pindahkan budget ke iklan yang lebih kuat."
            )
        elif done and expected > plan + 1:
            goal, act, tip = "Sesuai rencana", "Pertahankan", (
                f"Berjalan di batas minimum Shopee ({_rp_hari(expected)}) — wajar, bukan gagal rencana."
            )
        elif done:
            goal, act, tip = "Sesuai rencana", "Pertahankan", (
                f"{spend_bits}. Budget dan ROAS sejalan dengan rencana campaign."
            )
        else:
            goal, act, tip = "Perlu dicek", "Naikkan budget", (
                f"{spend_bits}. Samakan budget di Seller Center ke {_rp_hari(expected)}, lalu unggah laporan esok hari."
            )

        goals.append(goal)
        actions.append(act)
        tips.append(tip)
        sc.append(sc_label)
    out["Status SC"] = sc
    out["Status goals"] = goals
    out["Tindakan"] = actions
    out["Saran"] = tips
    out["_rank"] = out["Tindakan"].map(lambda t: _STATUS_RANK.get(t, 9))
    return out.sort_values(["_rank", "Biaya aktual/hari"], ascending=[True, False]).drop(columns=["_rank"])


def refresh_tips_after_month(frame: pd.DataFrame, *, target_roas: float, running_keys: set[str] | None = None) -> pd.DataFrame:
    """Tulis ulang Status/Tindakan/Saran setelah `Biaya bulan ini/hari` terisi; urutan baris tetap."""
    if frame is None or frame.empty or "Biaya bulan ini/hari" not in getattr(frame, "columns", []):
        return frame if frame is not None else pd.DataFrame()
    core = frame.drop(columns=["Status SC", "Status goals", "Tindakan", "Saran"], errors="ignore")
    fresh = classify_rows(core, target_roas=target_roas, running_keys=running_keys)
    if fresh.empty or "_key" not in fresh.columns:
        return frame
    by_key = {str(k): r for k, r in fresh.set_index("_key", drop=False).iterrows()}
    tips, acts, goals, scs = [], [], [], []
    for key in frame["_key"].astype(str):
        row = by_key.get(str(key))
        if row is None:
            tips.append(str(frame.loc[frame["_key"].astype(str) == key, "Saran"].iloc[0]) if "Saran" in frame.columns else "")
            acts.append(str(frame.loc[frame["_key"].astype(str) == key, "Tindakan"].iloc[0]) if "Tindakan" in frame.columns else "")
            goals.append(str(frame.loc[frame["_key"].astype(str) == key, "Status goals"].iloc[0]) if "Status goals" in frame.columns else "")
            scs.append(str(frame.loc[frame["_key"].astype(str) == key, "Status SC"].iloc[0]) if "Status SC" in frame.columns else "")
            continue
        tips.append(str(row["Saran"]))
        acts.append(str(row["Tindakan"]))
        goals.append(str(row["Status goals"]))
        scs.append(str(row["Status SC"]))
    out = frame.copy()
    out["Saran"], out["Tindakan"], out["Status goals"], out["Status SC"] = tips, acts, goals, scs
    return out


def priority_actions(classified: pd.DataFrame, *, limit: int = 8) -> list[dict]:
    if classified is None or classified.empty:
        return []
    work = classified.loc[classified["Tindakan"] != "Pertahankan"].head(limit)
    out = []
    for _, r in work.iterrows():
        out.append({
            "iklan": str(r.get("Iklan") or r.get("_key") or ""),
            "jenis": str(r.get("Jenis") or ""),
            "tindakan": str(r["Tindakan"]),
            "saran": str(r["Saran"]),
            "biaya": float(r.get("Biaya aktual/hari") or 0),
            "efektif": float(r.get("Budget efektif Shopee/hari") or 0),
            "roas": float(r["ROAS aktual"]) if r.get("ROAS aktual") == r.get("ROAS aktual") else float("nan"),
        })
    return out


def budget_wallet(setelan: dict, *, spent_month: float, spent_since: float, days_since: int, days_left_plan: int) -> dict:
    """Kartu baca budget: total rencana, terpakai bulan, terpakai sejak disimpan, sisa, pembagian harian."""
    s = setelan or {}
    total = float(s.get("budget_bulan") or s.get("budget") or 0)
    daily = float(s.get("biaya_harian_rencana") or s.get("budget_harian") or 0)
    path_since = daily * max(days_since, 0)
    remaining = max(total - spent_month, 0.0)
    return {
        "budget_total": total,
        "terpakai_bulan": float(spent_month),
        "sisa_bulan": remaining,
        "rencana_harian": daily,
        "terpakai_sejak": float(spent_since),
        "jalur_sejak": path_since,
        "sisa_hari_rencana": max(int(days_left_plan), 0),
        "roas_target": float(s.get("roas") or 0),
    }


def must_advertise(products: pd.DataFrame, classified: pd.DataFrame | None, sel_saved: pd.DataFrame | None,
                   units, *, target_roas: float, daily_budget_room: float, limit: int = 12) -> pd.DataFrame:
    """Daftar item yang HARUS diiklankan / dinaikkan (bukan daftar 'jangan iklan').

    Urutan: (1) iklan berjalan ROAS kuat → pertahankan/naikkan, (2) produk prediksi tinggi + stok → buat baru,
    (3) iklan ROAS lemah berbiaya → jeda (maks 3 baris di akhir sebagai penghematan)."""
    cols = ["Prioritas", "Produk", "Kode / iklan", "Jenis", "Keputusan", "Budget/hari", "Alasan",
            "Prediksi omzet/hari", "Stok", "ROAS terkini", "Biaya kini/hari"]
    rows: list[dict] = []

    # Peta performa iklan tunggal
    roas_by_code, cost_by_code = {}, {}
    weak_ads = []
    strong_ads = []
    if isinstance(classified, pd.DataFrame) and not classified.empty:
        for _, r in classified.iterrows():
            key = str(r.get("_key") or "")
            name = str(r.get("Iklan") or key)
            jenis = str(r.get("Jenis") or "")
            cost = float(r.get("Biaya aktual/hari") or 0)
            roas = float(r["ROAS aktual"]) if r.get("ROAS aktual") == r.get("ROAS aktual") else float("nan")
            expected = float(r.get("Budget efektif Shopee/hari") or 0)
            if key.startswith(("produk:", "pisah:", "baru:")):
                code = key.split(":", 1)[1]
                roas_by_code[code] = roas
                cost_by_code[code] = cost
            if expected > 0 and cost > 0 and roas == roas and roas >= target_roas * 0.9:
                strong_ads.append((name, key, jenis, cost, roas, expected))
            elif expected > 0 and cost > expected * 0.4 and roas == roas and roas < target_roas * 0.7:
                weak_ads.append((name, key, jenis, cost, roas, expected))

    in_plan = set()
    if isinstance(sel_saved, pd.DataFrame) and not sel_saved.empty and "Kode produk" in sel_saved.columns:
        in_plan = {str(c) for c in sel_saved["Kode produk"].astype(str) if c and c != "nan"}

    spent = 0.0
    room = max(float(daily_budget_room or 0), 0.0)

    # 1) Pertahankan / naikkan iklan kuat
    for name, key, jenis, cost, roas, expected in sorted(strong_ads, key=lambda x: -x[3])[:8]:
        bump = A.round_budget(max(cost, expected) * 1.15, min_floor=A.seller_min_budget(jenis))
        if room > 0 and spent + max(bump - cost, 0) > room + 1:
            bump = A.implementable_budget(cost, jenis)
        rows.append({
            "Prioritas": len(rows) + 1, "Produk": name, "Kode / iklan": key, "Jenis": jenis,
            "Keputusan": "Pertahankan / naikkan", "Budget/hari": bump,
            "Alasan": f"ROAS {roas:.1f} ≥ target · iklan ini yang menopang omzet; naikkan bertahap hanya di Senin.",
            "Prediksi omzet/hari": np.nan, "Stok": np.nan, "ROAS terkini": roas, "Biaya kini/hari": cost,
        })
        spent += max(bump - cost, 0)

    # 2) Produk baru layak iklan (prediksi tinggi + stok)
    if isinstance(products, pd.DataFrame) and not products.empty and "product_code" in products.columns:
        work = products.copy()
        work["product_code"] = work["product_code"].astype(str)
        work["omzet_harian"] = pd.to_numeric(work.get("omzet_harian"), errors="coerce").fillna(0.0)
        work["stok"] = pd.to_numeric(work.get("stok"), errors="coerce").fillna(0.0)
        work["stok_room"] = pd.to_numeric(work.get("stok_room"), errors="coerce").fillna(work["stok"])
        q = float(work["omzet_harian"].quantile(0.80)) if len(work) else 0.0
        cand = work.loc[(work["stok"] > 0) & (work["stok_room"] > 0) & (work["omzet_harian"] >= max(q, 1.0))]
        cand = cand.sort_values("omzet_harian", ascending=False)
        for r in cand.itertuples(index=False):
            if len([x for x in rows if str(x["Keputusan"]).startswith("Buat")]) >= 6:
                break
            code = str(r.product_code)
            if code in cost_by_code and cost_by_code[code] > 0:
                continue  # sudah punya iklan tunggal berjalan
            start = A.SHOPEE_MIN_SINGLE
            if room > 0 and spent + start > room + 1:
                break
            rows.append({
                "Prioritas": len(rows) + 1, "Produk": str(getattr(r, "nama", code) or code),
                "Kode / iklan": code, "Jenis": "Produk tunggal (baru)",
                "Keputusan": "Buat iklan tunggal", "Budget/hari": start,
                "Alasan": (
                    f"Prediksi omzet tinggi (±{float(r.omzet_harian):,.0f}/hari), stok ada"
                    + (", belum di pemilihan rencana" if code not in in_plan else ", sudah di rencana tetapi belum aktif")
                    + f". Mulai {start:,.0f}/hari, Target ROAS {target_roas:.0f}."
                ).replace(",", "."),
                "Prediksi omzet/hari": float(r.omzet_harian), "Stok": int(r.stok),
                "ROAS terkini": roas_by_code.get(code, np.nan), "Biaya kini/hari": cost_by_code.get(code, 0.0),
            })
            spent += start

    # 3) Penghematan: max 3 iklan lemah
    for name, key, jenis, cost, roas, expected in sorted(weak_ads, key=lambda x: x[4])[:3]:
        rows.append({
            "Prioritas": len(rows) + 1, "Produk": name, "Kode / iklan": key, "Jenis": jenis,
            "Keputusan": "Jeda / alihkan budget", "Budget/hari": 0.0,
            "Alasan": f"ROAS {roas:.1f} jauh di bawah target {target_roas:.1f} · pindahkan budget ke item di atas.",
            "Prediksi omzet/hari": np.nan, "Stok": np.nan, "ROAS terkini": roas, "Biaya kini/hari": cost,
        })

    # rapikan prioritas 1..n dan potong
    out = pd.DataFrame(rows[:limit], columns=cols)
    if not out.empty:
        out["Prioritas"] = range(1, len(out) + 1)
    return out


def active_plan_ads(acts_saved: pd.DataFrame, *, limit: int = 40) -> pd.DataFrame:
    """Hanya iklan rencana yang relevan: budget usulan > 0 atau ada perubahan, diurut budget terbesar."""
    if acts_saved is None or acts_saved.empty:
        return pd.DataFrame()
    work = acts_saved.copy()
    col = "Budget harian usulan"
    if col not in work.columns:
        return work.head(limit)
    work["_b"] = pd.to_numeric(work[col], errors="coerce").fillna(0.0)
    now = pd.to_numeric(work.get("Budget harian sekarang"), errors="coerce").fillna(0.0) if "Budget harian sekarang" in work.columns else 0.0
    focus = work.loc[(work["_b"] > 0) | (now > 0)].sort_values("_b", ascending=False)
    return focus.drop(columns=["_b"]).head(limit)


def selection_focus(sel_saved: pd.DataFrame, *, limit: int = 25) -> pd.DataFrame:
    """Pemilihan produk ringkas: prioritas tindakan aktif + prediksi tertinggi, bukan 600+ baris."""
    if sel_saved is None or sel_saved.empty:
        return pd.DataFrame()
    work = sel_saved.copy()
    if "Saran" in work.columns:
        hot = work["Saran"].astype(str).str.contains(
            r"Buat|Tambah|Pindah|Keluarkan|tunggal|naik|prioritas", case=False, na=False)
        prefer = work.loc[hot]
        rest = work.loc[~hot]
    else:
        prefer, rest = work, work.iloc[0:0]
    if "Prediksi omzet/hari" in work.columns:
        rest = rest.assign(_p=pd.to_numeric(rest["Prediksi omzet/hari"], errors="coerce").fillna(0)).sort_values("_p", ascending=False)
        prefer = prefer.assign(_p=pd.to_numeric(prefer["Prediksi omzet/hari"], errors="coerce").fillna(0)).sort_values("_p", ascending=False)
        rest = rest.drop(columns=["_p"], errors="ignore")
        prefer = prefer.drop(columns=["_p"], errors="ignore")
    out = pd.concat([prefer, rest], ignore_index=True).head(limit)
    return out


def week_window(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    start = today
    end = today + timedelta(days=6)
    return start, end


def rollup(classified: pd.DataFrame, summary: dict, *, track: dict | None, target_roas: float,
           store_roas: float | None = None) -> dict:
    total = int(summary.get("iklan_aktif_rencana") or summary.get("iklan") or 0)
    done = int(summary.get("dijalankan") or 0)
    floor_hits = int(summary.get("batas_shopee") or 0)
    roas = float(store_roas) if store_roas == store_roas and store_roas is not None else (
        float(summary.get("roas")) if summary.get("roas") == summary.get("roas") else float("nan"))
    on_sales = track is None or track.get("status") in (None, "On track", "Menunggu data")
    actions = priority_actions(classified, limit=50)
    need = len(actions)
    roas_ok = not (roas == roas and target_roas > 0 and roas < target_roas * 0.9)

    if total == 0 and not summary:
        level, title, blurb = "info", "Menunggu laporan iklan baru", "Unggah laporan iklan Seller Center (hari kemarin) agar hasil campaign bisa dinilai hari ini."
    elif done / max(total, 1) >= 0.7 and roas_ok and on_sales and need <= max(2, total * 0.2):
        level, title, blurb = "ok", "Campaign on track", (
            f"{done}/{total} iklan aktif sesuai acuan"
            + (f" · {floor_hits} di min. Shopee" if floor_hits else "")
            + (f" · ROAS iklan {roas:.1f}" if roas == roas else "")
            + ". Lanjut; review besar di Senin."
        )
    elif done / max(total, 1) >= 0.7 and not roas_ok:
        level, title, blurb = "warn", "Budget jalan, ROAS masih lemah", (
            f"ROAS iklan {roas:.1f} vs target {target_roas:.1f}. Rapikan iklan lemah dulu (lihat tindakan prioritas)."
        )
    elif on_sales and need > 0:
        level, title, blurb = "warn", "Sales on track — rapikan pelaksanaan iklan", (
            f"{done}/{max(total, 1)} sesuai acuan · {need} iklan perlu tindakan hari ini di Seller Center."
        )
    else:
        level, title, blurb = "alert", "Perlu tindakan agar rencana berhasil", (
            f"Hanya {done}/{max(total, 1)} iklan sesuai acuan. Kerjakan prioritas, unggah laporan esok hari."
        )
    return {
        "level": level, "title": title, "blurb": blurb, "done": done, "total": max(total, 1) if summary else 0,
        "floor_hits": floor_hits, "need": need, "roas": roas, "roas_ok": roas_ok, "on_sales": on_sales,
    }


def spend_gap_tip(wallet: dict, store_since: dict, summary: dict) -> str:
    bits = []
    if store_since:
        bits.append(
            f"Sejak campaign: biaya Rp {store_since.get('biaya', 0):,.0f} · omzet dari iklan Rp {store_since.get('omzet', 0):,.0f}"
            .replace(",", ".")
        )
        if store_since.get("biaya", 0) > 0:
            bits.append(f"ROAS {store_since['omzet'] / store_since['biaya']:.1f}")
    if wallet.get("rencana_harian"):
        bits.append(
            f"Patokan harian Rp {wallet['rencana_harian']:,.0f} · "
            f"terpakai sejak campaign Rp {wallet['terpakai_sejak']:,.0f} "
            f"(patokan kumulatif Rp {wallet['jalur_sejak']:,.0f})".replace(",", ".")
        )
    if summary.get("batas_shopee"):
        bits.append(
            f"{summary['batas_shopee']} iklan memakai batas minimum Shopee "
            "(Rp 25.000 tunggal / Rp 100.000 grup) — itu wajar, bukan gagal rencana"
        )
    return " · ".join(bits)


def complete_plan_rows(classified: pd.DataFrame, planned: dict[str, float], *, names: dict[str, tuple[str, str]],
                       target_roas: float, running_keys: set[str] | None = None) -> pd.DataFrame:
    """Pastikan semua kunci campaign tersimpan muncul, meski belum ada di laporan terbaru."""
    have = set(classified["_key"].astype(str)) if isinstance(classified, pd.DataFrame) and not classified.empty and "_key" in classified.columns else set()
    rows = []
    for key, plan in (planned or {}).items():
        if str(key) in have:
            continue
        kind = (names.get(str(key)) or ("", "Grup" if str(key).startswith("grup:") else "Produk tunggal"))[1]
        nama = (names.get(str(key)) or (str(key), kind))[0]
        expected = A.implementable_budget(float(plan or 0), kind)
        rows.append({
            "_key": str(key), "Iklan": nama, "Jenis": kind, "Hari dievaluasi": 0,
            "Budget usulan/hari": float(plan or 0), "Budget efektif Shopee/hari": expected,
            "Biaya aktual/hari": 0.0, "Omzet iklan aktual/hari": 0.0,
            "Biaya sejak disimpan": 0.0, "Omzet iklan sejak disimpan": 0.0, "ROAS aktual": float("nan"),
            "Rasio vs efektif": float("nan"), "Status pelaksanaan": "Belum ada di laporan",
            "Rekomendasi dijalankan": "Belum", "Catatan batas": "",
        })
    extra = pd.DataFrame(rows)
    if extra.empty:
        frame = classified.copy() if isinstance(classified, pd.DataFrame) else pd.DataFrame()
    elif classified is None or classified.empty:
        frame = classify_rows(extra, target_roas=target_roas, running_keys=running_keys)
    else:
        frame = pd.concat([classified, classify_rows(extra, target_roas=target_roas, running_keys=running_keys)],
                          ignore_index=True)
    return sort_by_omzet(frame)


def sort_by_omzet(frame: pd.DataFrame) -> pd.DataFrame:
    """Urut omzet iklan sejak disimpan terbesar (prioritas sales)."""
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame
    out = frame.copy()
    col = "Omzet iklan sejak disimpan"
    if col not in out.columns:
        return out
    out["_omz"] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    return out.sort_values("_omz", ascending=False).drop(columns=["_omz"]).reset_index(drop=True)


def split_in_out_plan(classified: pd.DataFrame, planned: dict[str, float], current: dict[str, dict],
                     baseline: dict[str, dict], *, names: dict[str, tuple[str, str]], kinds: dict[str, str],
                     target_roas: float, running_keys: set[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pisah iklan di dalam rencana campaign vs yang berbiaya di laporan tetapi tidak ada di plan."""
    plan_keys = {str(k) for k in (planned or {})}
    in_plan = complete_plan_rows(classified, planned or {}, names=names, target_roas=target_roas, running_keys=running_keys)

    # Di luar plan: ada di laporan sekarang, tidak ada di kunci campaign, dan ada biaya sejak baseline
    outsider_planned = {}
    for key, cur in (current or {}).items():
        k = str(key)
        if k in plan_keys:
            continue
        base = (baseline or {}).get(k) or {}
        if base and base.get("periode") == cur.get("periode"):
            days = int(cur.get("hari", 0)) - int(base.get("hari", 0))
            cost = float(cur.get("biaya", 0)) - float(base.get("biaya", 0))
        else:
            days, cost = int(cur.get("hari", 0)), float(cur.get("biaya", 0))
        if days > 0 and cost > 5_000:
            outsider_planned[k] = 0.0  # tidak di plan → acuan jeda

    out_frame = pd.DataFrame()
    if outsider_planned:
        frame, _ = A.evaluate(baseline or {}, current or {}, outsider_planned, target_roas=target_roas, jenis=kinds)
        if not frame.empty:
            frame.insert(1, "Iklan", frame["_key"].map(lambda k: (names.get(str(k)) or (str(k), ""))[0]))
            if "Jenis" not in frame.columns or frame["Jenis"].isna().all():
                frame["Jenis"] = frame["_key"].map(
                    lambda k: kinds.get(str(k)) or ((names.get(str(k)) or ("", "Produk tunggal"))[1]))
            out_frame = sort_by_omzet(classify_rows(frame, target_roas=target_roas, running_keys=running_keys))
    return in_plan, out_frame


def record_daily_checkpoint(campaign: dict, *, report_date: date | None, rows: pd.DataFrame) -> tuple[dict, bool]:
    """Simpan/timpa checkpoint harian per iklan di campaign['pantau_harian']. True bila ada perubahan."""
    if report_date is None or rows is None or (isinstance(rows, pd.DataFrame) and rows.empty):
        return campaign, False
    day = report_date.isoformat()
    items = []
    for _, r in rows.iterrows():
        key = str(r.get("_key") or "")
        if not key:
            continue
        biaya = float(r.get("Biaya sejak disimpan") or 0)
        omzet = float(r.get("Omzet iklan sejak disimpan") or 0)
        month = r.get("Biaya bulan ini/hari")
        month_v = float(month) if month == month and month is not None else None
        items.append({
            "key": key,
            "iklan": str(r.get("Iklan") or key),
            "biaya": round(biaya, 2),
            "omzet": round(omzet, 2),
            "roas": round(omzet / biaya, 4) if biaya > 0 else None,
            "biaya_hari": round(float(r.get("Biaya aktual/hari") or 0), 2),
            "biaya_bulan_hari": round(month_v, 2) if month_v is not None else None,
            "budget_plan": round(float(r.get("Budget usulan/hari") or 0), 2),
            "budget_setup": round(float(r.get("Budget efektif Shopee/hari") or 0), 2),
            "tindakan": str(r.get("Tindakan") or ""),
        })
    entry = {"tanggal": day, "items": items}
    log = list(campaign.get("pantau_harian") or [])
    prev = next((e for e in log if str(e.get("tanggal") or "")[:10] == day), None)
    if prev is not None and prev.get("items") == items:
        return campaign, False
    log = [e for e in log if str(e.get("tanggal") or "")[:10] != day]
    log.append(entry)
    log = sorted(log, key=lambda e: str(e.get("tanggal") or ""))[-60:]
    return {**campaign, "pantau_harian": log}, True


def daily_history_for(campaign: dict, key: str, *, baseline_row: dict | None = None,
                      today_row: dict | None = None) -> pd.DataFrame:
    """Riwayat evaluasi campaign per tanggal — patokan, pergerakan, kumulatif, dan rata-rata bulan ini.

    Kolom disusun agar atribusi jelas:
    - Patokan di rencana / di Shopee = acuan campaign (bukan realisasi)
    - Tambahan hari ini = selisih vs catatan sebelumnya (pergerakan)
    - Total sejak campaign = akumulasi sejak campaign disimpan
    - Rata-rata terpakai sejak campaign vs rata-rata bulan ini (MTD)
    """
    raw: list[dict] = []
    for entry in campaign.get("pantau_harian") or []:
        day = str(entry.get("tanggal") or "")[:10]
        for it in entry.get("items") or []:
            if str(it.get("key")) != str(key):
                continue
            month = it.get("biaya_bulan_hari")
            raw.append({
                "tanggal": day,
                "biaya": float(it.get("biaya") or 0),
                "omzet": float(it.get("omzet") or 0),
                "roas": it.get("roas"),
                "biaya_hari": float(it.get("biaya_hari") or 0),
                "biaya_bulan_hari": float(month) if month is not None and month == month else float("nan"),
                "budget_plan": float(it.get("budget_plan") or 0),
                "budget_setup": float(it.get("budget_setup") or 0),
                "tindakan": str(it.get("tindakan") or ""),
            })
    if not raw and baseline_row is not None:
        raw.append({
            "tanggal": str(baseline_row.get("tanggal") or "baseline")[:10],
            "biaya": 0.0, "omzet": 0.0, "roas": None, "biaya_hari": 0.0,
            "biaya_bulan_hari": float("nan"),
            "budget_plan": float(baseline_row.get("budget_plan") or 0),
            "budget_setup": float(baseline_row.get("budget_setup") or 0),
            "tindakan": "titik awal campaign",
        })
    if today_row is not None:
        day = str(today_row.get("tanggal") or "")[:10]
        if day and not any(r["tanggal"] == day for r in raw):
            month = today_row.get("biaya_bulan_hari")
            raw.append({
                "tanggal": day or "hari ini",
                "biaya": float(today_row.get("biaya") or 0),
                "omzet": float(today_row.get("omzet") or 0),
                "roas": today_row.get("roas"),
                "biaya_hari": float(today_row.get("biaya_hari") or 0),
                "biaya_bulan_hari": float(month) if month is not None and month == month else float("nan"),
                "budget_plan": float(today_row.get("budget_plan") or 0),
                "budget_setup": float(today_row.get("budget_setup") or 0),
                "tindakan": str(today_row.get("tindakan") or ""),
            })
    raw = sorted(raw, key=lambda r: str(r.get("tanggal") or ""))
    rows = []
    prev = None
    for item in raw:
        biaya = float(item["biaya"])
        omzet = float(item["omzet"])
        if prev is None:
            add_biaya = float("nan")
            add_omzet = float("nan")
        else:
            add_biaya = biaya - float(prev["biaya"])
            add_omzet = omzet - float(prev["omzet"])
        roas = item.get("roas")
        rows.append({
            "Tanggal": item["tanggal"],
            "Patokan di rencana": float(item["budget_plan"]),
            "Patokan di Shopee": float(item["budget_setup"]),
            "Tambahan biaya hari ini": add_biaya,
            "Tambahan omzet hari ini": add_omzet,
            "Total biaya sejak campaign": biaya,
            "Total omzet sejak campaign": omzet,
            "ROAS sejak campaign": float(roas) if roas is not None and roas == roas else float("nan"),
            "Rata-rata terpakai sejak campaign": float(item["biaya_hari"]),
            "Rata-rata terpakai bulan ini": float(item["biaya_bulan_hari"]),
            "Saran saat itu": item["tindakan"],
        })
        prev = item
    return pd.DataFrame(rows)


def attach_month_daily(frame: pd.DataFrame, current: dict[str, dict] | None) -> pd.DataFrame:
    """Tambah `Biaya bulan ini/hari` = total biaya laporan bulan berjalan ÷ hari laporan.

    Berbeda dari `Biaya aktual/hari` (rata-rata sejak campaign disimpan)."""
    if frame is None or frame.empty:
        return frame if frame is not None else pd.DataFrame()
    out = frame.copy()
    cur_map = current or {}

    def lookup(key: str) -> dict | None:
        if key in cur_map:
            return cur_map[key]
        tail = key.split(":", 1)[-1]
        for k, v in cur_map.items():
            if str(k).split(":", 1)[-1] == tail:
                return v
        return None

    vals = []
    for key in out["_key"].astype(str) if "_key" in out.columns else []:
        cur = lookup(str(key))
        days = int((cur or {}).get("hari") or 0)
        vals.append(float(cur["biaya"]) / days if cur and days > 0 else float("nan"))
    if "_key" in out.columns:
        out["Biaya bulan ini/hari"] = vals
    return out


def rename_budget_triad(frame: pd.DataFrame) -> pd.DataFrame:
    """Label baku untuk tabel unduhan."""
    if frame is None or frame.empty:
        return frame if frame is not None else pd.DataFrame()
    out = frame.copy()
    rename = {
        "Budget usulan/hari": "Budget di rencana/hari",
        "Budget efektif Shopee/hari": "Budget di Shopee/hari",
        "Biaya bulan ini/hari": "Terpakai bulan ini/hari",
        "Biaya aktual/hari": "Terpakai sejak campaign/hari",
    }
    return out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
