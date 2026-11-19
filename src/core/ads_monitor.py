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


def _rp(value: float) -> str:
    return f"Rp {value:,.0f}".replace(",", ".")


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
        nama = str(r.get("Iklan") or key)
        total_sejak = float(r.get("Biaya sejak disimpan") or 0)
        omzet_sejak = float(r.get("Omzet iklan sejak disimpan") or 0)
        days_eval = int(r.get("Hari dievaluasi") or 0)
        if days_eval <= 0 and cost > 0 and total_sejak > 0:
            days_eval = max(int(round(total_sejak / cost)), 1)

        if expected <= 0:
            if done or cost <= 5_000:
                goal, act, tip = "Sesuai rencana", "Pertahankan", (
                    "Iklan ini tetap tercatat di campaign, tetapi budget rencananya Rp 0 "
                    "(sengaja dihentikan). Tidak perlu diubah."
                )
            else:
                # Jangan campur omzet dengan biaya; sebutkan hari agar rata-rata × hari = total masuk akal.
                biaya_bit = (
                    f"biaya {_rp(total_sejak)}"
                    + (f" / {days_eval} hari" if days_eval > 0 else "")
                    + f" (rata-rata {_rp_hari(cost)})"
                    if total_sejak > 0 else spend_bits
                )
                month_bit = f"; bulan ini rata-rata {_rp_hari(month_v)}" if month_v == month_v else ""
                omzet_bit = f"; omzet {_rp(omzet_sejak)}" if omzet_sejak > 0 else ""
                window_note = ""
                if month_v == month_v and cost > 0 and month_v + 1 < cost:
                    window_note = (
                        " Bulan ini boleh lebih kecil: dihitung dari tgl 1 "
                        "(termasuk hari sebelum campaign disimpan)."
                    )
                goal, act, tip = "Tidak sesuai rencana", "Jeda / hentikan", (
                    f"Budget rencana Rp 0 (sengaja dihentikan), tetapi laporan masih mencatat "
                    f"biaya pada iklan «{nama}» di Seller Center — {biaya_bit}{month_bit}{omzet_bit}. "
                    f"Pause / hentikan iklan «{nama}» di SC (cari nama yang sama)."
                    + window_note
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
            "Prediksi omzet/hari", "Stok 10037", "Stok 10062", "Stok 10036", "ROAS terkini", "Biaya kini/hari"]
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
        stock = stock_summary_for_ad(products, key)
        rows.append({
            "Prioritas": len(rows) + 1, "Produk": name, "Kode / iklan": key, "Jenis": jenis,
            "Keputusan": "Pertahankan / naikkan", "Budget/hari": bump,
            "Alasan": (
                f"ROAS {roas:.1f} ≥ target · iklan ini yang menopang omzet; naikkan bertahap hanya di Senin. "
                + stock["teks"]
            ),
            "Prediksi omzet/hari": np.nan,
            "Stok 10037": stock["stok_10037"], "Stok 10062": stock["stok_10062"], "Stok 10036": stock["stok_10036"],
            "ROAS terkini": roas, "Biaya kini/hari": cost,
        })
        spent += max(bump - cost, 0)

    # 2) Produk baru layak iklan (prediksi tinggi + stok toko 10037)
    if isinstance(products, pd.DataFrame) and not products.empty and "product_code" in products.columns:
        work = products.copy()
        work["product_code"] = work["product_code"].astype(str)
        work["omzet_harian"] = pd.to_numeric(work.get("omzet_harian"), errors="coerce").fillna(0.0)
        work["stok"] = pd.to_numeric(work.get("stok_10037", work.get("stok")), errors="coerce").fillna(0.0)
        work["stok_room"] = pd.to_numeric(work.get("stok_room"), errors="coerce").fillna(work["stok"])
        for col in ("stok_10062", "stok_10036"):
            if col not in work.columns:
                work[col] = np.nan
            else:
                work[col] = pd.to_numeric(work[col], errors="coerce")
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
            sig = _product_signal(products, code)
            rows.append({
                "Prioritas": len(rows) + 1, "Produk": str(getattr(r, "nama", code) or code),
                "Kode / iklan": code, "Jenis": "Produk tunggal (baru)",
                "Keputusan": "Buat iklan tunggal", "Budget/hari": start,
                "Alasan": (
                    f"Prediksi omzet tinggi (±{float(r.omzet_harian):,.0f}/hari), stok toko ada"
                    + (", belum di pemilihan rencana" if code not in in_plan else ", sudah di rencana tetapi belum aktif")
                    + f". Mulai {start:,.0f}/hari, Target ROAS {target_roas:.0f}. "
                    + stock_sites_text(sig, short=False)
                ).replace(",", "."),
                "Prediksi omzet/hari": float(r.omzet_harian),
                "Stok 10037": sig["stok_10037"], "Stok 10062": sig["stok_10062"], "Stok 10036": sig["stok_10036"],
                "ROAS terkini": roas_by_code.get(code, np.nan), "Biaya kini/hari": cost_by_code.get(code, 0.0),
            })
            spent += start

    # 3) Penghematan: max 3 iklan lemah
    for name, key, jenis, cost, roas, expected in sorted(weak_ads, key=lambda x: x[4])[:3]:
        stock = stock_summary_for_ad(products, key)
        rows.append({
            "Prioritas": len(rows) + 1, "Produk": name, "Kode / iklan": key, "Jenis": jenis,
            "Keputusan": "Jeda / alihkan budget", "Budget/hari": 0.0,
            "Alasan": (
                f"ROAS {roas:.1f} jauh di bawah target {target_roas:.1f} · pindahkan budget ke item di atas. "
                + stock["teks"]
            ),
            "Prediksi omzet/hari": np.nan,
            "Stok 10037": stock["stok_10037"], "Stok 10062": stock["stok_10062"], "Stok 10036": stock["stok_10036"],
            "ROAS terkini": roas, "Biaya kini/hari": cost,
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


def report_alias(key: str) -> str:
    """Kunci laporan Seller Center untuk usulan pisah/baru → produk:kode."""
    k = str(key or "")
    if k.startswith(("pisah:", "baru:")):
        return "produk:" + k.split(":", 1)[1]
    return k


def plan_coverage(planned: dict[str, float] | None) -> set[str]:
    """Semua kunci yang dianggap 'dalam rencana' (termasuk alias laporan)."""
    covered: set[str] = set()
    for key in planned or {}:
        k = str(key)
        covered.add(k)
        covered.add(report_alias(k))
    return covered


def split_in_out_plan(classified: pd.DataFrame, planned: dict[str, float], current: dict[str, dict],
                     baseline: dict[str, dict], *, names: dict[str, tuple[str, str]], kinds: dict[str, str],
                     target_roas: float, running_keys: set[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pisah ketat: hanya kunci campaign → dalam rencana; berbiaya di SC tanpa kunci campaign → luar rencana."""
    planned = planned or {}
    plan_keys = {str(k) for k in planned}
    covered = plan_coverage(planned)
    in_plan = complete_plan_rows(classified, planned, names=names, target_roas=target_roas, running_keys=running_keys)
    if not in_plan.empty and "_key" in in_plan.columns:
        # Pertahankan hanya kunci yang benar-benar tersimpan di campaign (bukan alias laporan).
        in_plan = sort_by_omzet(in_plan.loc[in_plan["_key"].astype(str).isin(plan_keys)].copy())

    # Di luar plan: ada di laporan sekarang, tidak tertutup kunci/alias campaign, dan ada biaya sejak baseline
    outsider_planned = {}
    for key, cur in (current or {}).items():
        k = str(key)
        if k in covered or report_alias(k) in covered:
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
            # Jaga-jaga: buang bila ternyata alias dari kunci rencana
            if not out_frame.empty:
                out_frame = out_frame.loc[
                    ~out_frame["_key"].astype(str).isin(covered)
                    & ~out_frame["_key"].astype(str).map(report_alias).isin(covered)
                ].copy()
                out_frame = sort_by_omzet(out_frame)
    return in_plan, out_frame


def partition_plan_rows(in_plan: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Sub-grup dalam rencana: belum setup SC / jeda tertinggal / pantau (sisanya)."""
    empty = pd.DataFrame()
    if in_plan is None or in_plan.empty or "Tindakan" not in in_plan.columns:
        return {"belum_setup": empty, "jeda_tertinggal": empty, "pantau": empty}
    act = in_plan["Tindakan"].astype(str)
    mask_belum = act == "Buat / aktifkan"
    mask_jeda = act.str.startswith("Jeda")
    return {
        "belum_setup": sort_by_omzet(in_plan.loc[mask_belum].copy()),
        "jeda_tertinggal": sort_by_omzet(in_plan.loc[mask_jeda].copy()),
        "pantau": sort_by_omzet(in_plan.loc[~mask_belum & ~mask_jeda].copy()),
    }


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
        hari = int(r.get("Hari dievaluasi") or 0)
        if hari <= 0:
            rate = float(r.get("Biaya aktual/hari") or 0)
            if rate > 0 and biaya > 0:
                hari = max(int(round(biaya / rate)), 1)
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
            "hari": hari,
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
    """Riwayat evaluasi campaign per tanggal catatan Pantau (bukan buku harian Shopee).

    Kolom:
    - Budget di rencana/Shopee = yang diset di campaign (bukan uang terpakai)
    - Naik sejak catatan lalu = selisih total kumulatif vs baris sebelumnya (bisa > 1 hari laporan)
    - Total sejak campaign = akumulasi sejak campaign disimpan
    - Rata-rata biaya/hari = total ÷ hari evaluasi (bukan sama dengan kolom naik)
    """
    raw: list[dict] = []
    for entry in campaign.get("pantau_harian") or []:
        day = str(entry.get("tanggal") or "")[:10]
        for it in entry.get("items") or []:
            if str(it.get("key")) != str(key):
                continue
            month = it.get("biaya_bulan_hari")
            hari = int(it.get("hari") or 0)
            biaya_v = float(it.get("biaya") or 0)
            rate = float(it.get("biaya_hari") or 0)
            if hari <= 0 and rate > 0 and biaya_v > 0:
                hari = max(int(round(biaya_v / rate)), 1)
            raw.append({
                "tanggal": day,
                "biaya": biaya_v,
                "omzet": float(it.get("omzet") or 0),
                "roas": it.get("roas"),
                "biaya_hari": rate,
                "biaya_bulan_hari": float(month) if month is not None and month == month else float("nan"),
                "budget_plan": float(it.get("budget_plan") or 0),
                "budget_setup": float(it.get("budget_setup") or 0),
                "hari": hari,
                "tindakan": str(it.get("tindakan") or ""),
            })
    if not raw and baseline_row is not None:
        raw.append({
            "tanggal": str(baseline_row.get("tanggal") or "baseline")[:10],
            "biaya": 0.0, "omzet": 0.0, "roas": None, "biaya_hari": 0.0,
            "biaya_bulan_hari": float("nan"),
            "budget_plan": float(baseline_row.get("budget_plan") or 0),
            "budget_setup": float(baseline_row.get("budget_setup") or 0),
            "hari": 0,
            "tindakan": "titik awal campaign",
        })
    if today_row is not None:
        day = str(today_row.get("tanggal") or "")[:10]
        if day and not any(r["tanggal"] == day for r in raw):
            month = today_row.get("biaya_bulan_hari")
            biaya_v = float(today_row.get("biaya") or 0)
            rate = float(today_row.get("biaya_hari") or 0)
            hari = int(today_row.get("hari") or 0)
            if hari <= 0 and rate > 0 and biaya_v > 0:
                hari = max(int(round(biaya_v / rate)), 1)
            raw.append({
                "tanggal": day or "hari ini",
                "biaya": biaya_v,
                "omzet": float(today_row.get("omzet") or 0),
                "roas": today_row.get("roas"),
                "biaya_hari": rate,
                "biaya_bulan_hari": float(month) if month is not None and month == month else float("nan"),
                "budget_plan": float(today_row.get("budget_plan") or 0),
                "budget_setup": float(today_row.get("budget_setup") or 0),
                "hari": hari,
                "tindakan": str(today_row.get("tindakan") or ""),
            })
    raw = sorted(raw, key=lambda r: str(r.get("tanggal") or ""))
    rows = []
    prev = None
    for item in raw:
        biaya = float(item["biaya"])
        omzet = float(item["omzet"])
        hari = int(item.get("hari") or 0)
        if prev is None:
            add_biaya = float("nan")
            add_omzet = float("nan")
            add_hari = float("nan")
        else:
            add_biaya = biaya - float(prev["biaya"])
            add_omzet = omzet - float(prev["omzet"])
            prev_hari = int(prev.get("hari") or 0)
            add_hari = float(hari - prev_hari) if hari > 0 and prev_hari > 0 else float("nan")
        roas = item.get("roas")
        rows.append({
            "Tanggal catatan": item["tanggal"],
            "Hari evaluasi": hari if hari > 0 else float("nan"),
            "Budget di rencana/hari": float(item["budget_plan"]),
            "Budget di Shopee/hari": float(item["budget_setup"]),
            "Naik biaya sejak catatan lalu": add_biaya,
            "Naik omzet sejak catatan lalu": add_omzet,
            "Hari laporan di antara catatan": add_hari,
            "Total biaya sejak campaign": biaya,
            "Total omzet sejak campaign": omzet,
            "ROAS sejak campaign": float(roas) if roas is not None and roas == roas else float("nan"),
            "Rata-rata biaya/hari sejak campaign": float(item["biaya_hari"]),
            "Rata-rata biaya/hari bulan ini": float(item["biaya_bulan_hari"]),
            "Saran saat itu": item["tindakan"],
        })
        prev = item
    return pd.DataFrame(rows)


_MEMBER_RANK = {
    "Sudah diiklankan di tempat lain": 0,
    "Tidak perlu di-setup": 1,
    "Keluarkan dari grup": 2,
    "Kurangi porsi / tinjau": 3,
    "Pisahkan jadi iklan tunggal": 4,
    "Layak di-setup di grup ini": 5,
    "Pertahankan di grup": 6,
}

# Grup belum setup: tampilkan dulu yang masih perlu keputusan setup (layak), baru yang tidak perlu / sudah di tempat lain.
_MEMBER_RANK_SETUP = {
    "Layak di-setup di grup ini": 0,
    "Tidak perlu di-setup": 1,
    "Sudah diiklankan di tempat lain": 2,
}


def _member_unit_slice(members: pd.DataFrame, group_key: str) -> pd.DataFrame:
    key = str(group_key)
    work = members.loc[members["unit"].astype(str) == key]
    if not work.empty:
        return work
    tail = key.split(":", 1)[-1].strip().lower()
    return members.loc[
        members["unit"].astype(str).str.startswith("grup:")
        & members["unit"].astype(str).str.lower().str.endswith(tail)
    ]


def _elsewhere_for_codes(
    members: pd.DataFrame | None,
    units,
    *,
    group_key: str,
    codes: set[str],
) -> dict[str, list[dict]]:
    """Iklan lain (tunggal/grup) yang memuat kode produk yang sama dan sedang berbiaya / berjalan."""
    out: dict[str, list[dict]] = {c: [] for c in codes}
    if not codes:
        return out
    by_unit = {getattr(u, "key", ""): u for u in (units or [])}
    # Unit produk tunggal langsung dari daftar unit
    for code in codes:
        for prefix in ("produk:", "pisah:", "baru:"):
            ukey = f"{prefix}{code}"
            unit = by_unit.get(ukey)
            if unit is None:
                continue
            running = bool(A._running(unit) and float(getattr(unit, "daily_cost", 0) or 0) > 0)
            if not running and float(getattr(unit, "daily_cost", 0) or 0) <= 0:
                continue
            out[code].append({
                "unit": ukey,
                "nama": str(getattr(unit, "nama", "") or ukey),
                "jenis": "Produk tunggal",
                "biaya": float(getattr(unit, "daily_cost", 0) or 0),
                "omzet": float(getattr(unit, "daily_sales", 0) or 0),
            })
    if members is None or getattr(members, "empty", True):
        return out
    need = {"unit", "periode", "product_code", "biaya", "omzet"}
    if not need <= set(members.columns):
        return out
    other = members.loc[
        members["product_code"].astype(str).isin(codes)
        & (members["unit"].astype(str) != str(group_key))
        & (members["unit"].astype(str) != "auto")
    ]
    if other.empty:
        return out
    latest = other.loc[other["periode"] == other.groupby("unit")["periode"].transform("max")]
    for r in latest.itertuples(index=False):
        code = str(r.product_code)
        ukey = str(r.unit)
        if ukey.startswith(("produk:", "pisah:", "baru:")):
            continue  # sudah dari units
        biaya = float(r.biaya or 0)
        omzet = float(r.omzet or 0)
        unit = by_unit.get(ukey)
        running = bool(unit is not None and A._running(unit) and float(getattr(unit, "daily_cost", 0) or 0) > 0)
        if not running and biaya <= 0 and omzet <= 0:
            continue
        nama = str(getattr(unit, "nama", "") or ukey.split(":", 1)[-1])
        # hindari duplikat unit
        if any(x["unit"] == ukey for x in out.get(code, [])):
            continue
        out.setdefault(code, []).append({
            "unit": ukey,
            "nama": nama,
            "jenis": "Grup" if ukey.startswith("grup:") else "Iklan lain",
            "biaya": biaya if biaya > 0 else float(getattr(unit, "daily_cost", 0) or 0),
            "omzet": omzet if omzet > 0 else float(getattr(unit, "daily_sales", 0) or 0),
        })
    return out


def _num_cell(row, *names: str) -> float:
    for name in names:
        if name in getattr(row, "index", []) or (hasattr(row, "__contains__") and name in row):
            try:
                val = row[name]
            except Exception:
                continue
            if val is not None and val == val:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
    return float("nan")


def _product_signal(products: pd.DataFrame | None, code: str) -> dict:
    """Sinyal produk + triad stok Site 10037 (toko) / 10062 (DC Cikupa) / 10036 (DC Cipeucang)."""
    empty = {
        "omzet_harian": float("nan"), "qty_harian": float("nan"),
        "stok": float("nan"), "stok_room": float("nan"), "nama": "",
        "stok_10037": float("nan"), "stok_10062": float("nan"), "stok_10036": float("nan"),
    }
    if products is None or getattr(products, "empty", True) or "product_code" not in products.columns:
        return empty
    hit = products.loc[products["product_code"].astype(str) == str(code)]
    if hit.empty:
        return empty
    row = hit.iloc[0]
    s37 = _num_cell(row, "stok_10037", "stok")
    s62 = _num_cell(row, "stok_10062")
    s36 = _num_cell(row, "stok_10036")
    return {
        "omzet_harian": _num_cell(row, "omzet_harian"),
        "qty_harian": _num_cell(row, "qty_harian"),
        "stok": s37,
        "stok_room": _num_cell(row, "stok_room"),
        "nama": str(row["nama"]) if "nama" in hit.columns else "",
        "stok_10037": s37,
        "stok_10062": s62,
        "stok_10036": s36,
    }


def stock_sites_text(sig: dict | None, *, short: bool = False) -> str:
    """Teks stok 10037/10062/10036 untuk kartu & saran kelayakan iklan."""
    if not sig:
        return "Stok 10037/10062/10036: belum ada data"
    def _u(v: float) -> str:
        if v != v:
            return "–"
        return f"{v:,.0f}".replace(",", ".")

    s37, s62, s36 = sig.get("stok_10037", float("nan")), sig.get("stok_10062", float("nan")), sig.get("stok_10036", float("nan"))
    if short:
        return f"10037 {_u(s37)} · 10062 {_u(s62)} · 10036 {_u(s36)}"
    return f"Stok Site 10037 {_u(s37)} · Site 10062 {_u(s62)} · Site 10036 {_u(s36)}"


def stock_worthiness(sig: dict | None) -> tuple[str, str]:
    """(status, penjelasan singkat) kelayakan iklan dari triad stok harian.

    status: ada_toko | isi_dari_dc | kosong | belum_data
    """
    if not sig:
        return "belum_data", "Stok 10037/10062/10036 belum terbaca — unggah Data stok harian."
    s37 = sig.get("stok_10037", float("nan"))
    s62 = sig.get("stok_10062", float("nan"))
    s36 = sig.get("stok_10036", float("nan"))
    if s37 != s37 and s62 != s62 and s36 != s36:
        return "belum_data", "Stok 10037/10062/10036 belum terbaca — unggah Data stok harian."
    toko = s37 if s37 == s37 else 0.0
    dc = (s62 if s62 == s62 else 0.0) + (s36 if s36 == s36 else 0.0)
    if toko > 0:
        return "ada_toko", f"{stock_sites_text(sig, short=True)} — stok toko ada, iklan bisa jalan."
    if dc > 0:
        return "isi_dari_dc", (
            f"{stock_sites_text(sig, short=True)} — toko kosong, tetapi DC ada. "
            "Restock/TR dulu ke Site 10037 sebelum naikkan budget iklan."
        )
    return "kosong", (
        f"{stock_sites_text(sig, short=True)} — toko & DC kosong. "
        "Iklan tidak layak diaktifkan sampai ada stok."
    )


def codes_for_ad_key(key: str, units=None, members: pd.DataFrame | None = None) -> list[str]:
    """Kode produk yang terkait satu kunci iklan (tunggal / anggota grup)."""
    k = str(key or "")
    if k.startswith(("produk:", "pisah:", "baru:")):
        return [k.split(":", 1)[1]]
    if units:
        for u in units:
            if getattr(u, "key", "") == k and getattr(u, "members", None):
                return [str(c) for c in u.members]
    if members is not None and not getattr(members, "empty", True) and k.startswith("grup:"):
        work = _member_unit_slice(members, k)
        if not work.empty and "product_code" in work.columns:
            return sorted({str(c) for c in work["product_code"].astype(str) if c and c != "nan"})
    return []


def stock_summary_for_ad(
    products: pd.DataFrame | None,
    key: str,
    *,
    units=None,
    members: pd.DataFrame | None = None,
) -> dict:
    """Ringkasan triad stok untuk satu iklan (agregat anggota bila grup)."""
    codes = codes_for_ad_key(key, units=units, members=members)
    if not codes:
        return {
            "stok_10037": float("nan"), "stok_10062": float("nan"), "stok_10036": float("nan"),
            "status": "belum_data", "teks": "Stok 10037/10062/10036: belum terpetakan ke produk",
            "n": 0, "kosong": 0, "dc_only": 0,
        }
    s37 = s62 = s36 = 0.0
    known37 = known62 = known36 = False
    kosong = dc_only = 0
    for code in codes:
        sig = _product_signal(products, code)
        st, _ = stock_worthiness(sig)
        if st == "kosong":
            kosong += 1
        elif st == "isi_dari_dc":
            dc_only += 1
        if sig["stok_10037"] == sig["stok_10037"]:
            s37 += sig["stok_10037"]; known37 = True
        if sig["stok_10062"] == sig["stok_10062"]:
            s62 += sig["stok_10062"]; known62 = True
        if sig["stok_10036"] == sig["stok_10036"]:
            s36 += sig["stok_10036"]; known36 = True
    sig = {
        "stok_10037": s37 if known37 else float("nan"),
        "stok_10062": s62 if known62 else float("nan"),
        "stok_10036": s36 if known36 else float("nan"),
    }
    status, _tip = stock_worthiness(sig)
    bits = [stock_sites_text(sig, short=False)]
    if len(codes) > 1:
        bits.append(f"{len(codes)} produk")
        if kosong:
            bits.append(f"{kosong} kosong total")
        if dc_only:
            bits.append(f"{dc_only} hanya ada di DC")
    return {
        **sig, "status": status, "teks": " · ".join(bits),
        "n": len(codes), "kosong": kosong, "dc_only": dc_only,
    }


def _hist_perf_for_code(work: pd.DataFrame, code: str) -> tuple[float, float, float]:
    """Rata-rata biaya/omzet/ROAS historis saat produk pernah berbiaya di grup ini (campaign sebelumnya)."""
    part = work.loc[work["product_code"].astype(str) == str(code)]
    if part.empty:
        return 0.0, 0.0, float("nan")
    active = part.loc[(part["biaya"].fillna(0) > 0) | (part["omzet"].fillna(0) > 0)]
    use = active if not active.empty else part
    biaya = float(use["biaya"].mean() or 0)
    omzet = float(use["omzet"].mean() or 0)
    roas = omzet / biaya if biaya > 0 else float("nan")
    return biaya, omzet, roas


def group_members_review(
    members: pd.DataFrame | None,
    group_key: str,
    *,
    target_roas: float,
    contribution: dict[str, float] | None = None,
    group_active: bool = True,
    units=None,
    products: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Performa + saran tiap produk di dalam satu iklan grup.

    - Grup aktif: evaluasi biaya/omzet periode terakhir (keluarkan yang lemah).
    - Grup belum di-setup: urut Layak → Tidak perlu → Sudah di tempat lain. Layak hanya bila
      prediksi mendorong target (batas 95% sales toko / qty laku) atau histori ROAS kuat + stok toko;
      saran menjelaskan kenapa harus diiklankan.
    """
    cols = [
        "Produk", "Kode produk",
        "Stok 10037", "Stok 10062", "Stok 10036",
        "Prediksi omzet/hari", "Biaya/hari", "Omzet/hari", "ROAS",
        "Porsi omzet grup", "Porsi biaya grup", "Iklan lain", "Tindakan", "Saran",
    ]
    if members is None or getattr(members, "empty", True) or not group_key:
        return pd.DataFrame(columns=cols)
    key = str(group_key)
    if not key.startswith("grup:"):
        return pd.DataFrame(columns=cols)
    need = {"unit", "periode", "product_code", "nama", "biaya", "omzet"}
    if not need <= set(members.columns):
        return pd.DataFrame(columns=cols)
    work = _member_unit_slice(members, key)
    if work.empty:
        return pd.DataFrame(columns=cols)
    latest = str(sorted(work["periode"].astype(str).unique())[-1])
    part = (
        work.loc[work["periode"].astype(str) == latest]
        .groupby("product_code", as_index=False)
        .agg(nama=("nama", "last"), biaya=("biaya", "mean"), omzet=("omzet", "mean"))
    )
    if part.empty:
        return pd.DataFrame(columns=cols)
    # Bila periode terakhir semua nol (grup belum setup), pakai histori berbiaya bila ada
    if float(part["biaya"].sum()) <= 0 and float(part["omzet"].sum()) <= 0:
        hist_rows = []
        for code in part["product_code"].astype(str):
            b, o, _ = _hist_perf_for_code(work, code)
            nama = str(part.loc[part["product_code"].astype(str) == code, "nama"].iloc[0])
            hist_rows.append({"product_code": code, "nama": nama, "biaya": b, "omzet": o})
        if any(r["biaya"] > 0 or r["omzet"] > 0 for r in hist_rows):
            part = pd.DataFrame(hist_rows)

    total_omzet = float(part["omzet"].sum())
    total_biaya = float(part["biaya"].sum())
    group_roas = total_omzet / total_biaya if total_biaya > 0 else float("nan")
    contrib = contribution or {}
    codes = set(part["product_code"].astype(str))
    elsewhere = _elsewhere_for_codes(members, units, group_key=key, codes=codes)
    sales_floor, qty_floor = A.potential_floors(products) if products is not None else (0.0, float("inf"))
    rows = []
    for r in part.itertuples(index=False):
        code = str(r.product_code)
        biaya = float(r.biaya or 0)
        omzet = float(r.omzet or 0)
        roas = omzet / biaya if biaya > 0 else float("nan")
        share_o = omzet / total_omzet if total_omzet > 0 else 0.0
        share_c = biaya / total_biaya if total_biaya > 0 else 0.0
        margin = contrib.get(code)
        alts = elsewhere.get(code) or []
        alt_label = "; ".join(
            f"{a['nama']} ({a['jenis']}"
            + (f", {_rp_hari(a['biaya'])}" if a.get("biaya") else "")
            + ")"
            for a in alts[:3]
        ) if alts else "–"

        sig = _product_signal(products, code)
        stock_status, stock_tip = stock_worthiness(sig)
        demand = sig["omzet_harian"]
        qty_day = sig["qty_harian"]
        demand_v = demand if demand == demand else 0.0
        qty_v = qty_day if qty_day == qty_day else 0.0
        pushes_target = (
            (sales_floor > 0 and demand_v >= sales_floor)
            or (qty_floor < float("inf") and qty_v >= qty_floor)
        )

        if not group_active:
            # Mode belum di-setup: jangan bilang "pertahankan" — bandingkan setup & kelayakan
            if alts:
                act = "Sudah diiklankan di tempat lain"
                tip = (
                    f"Sudah aktif di: {alt_label}. "
                    "Jangan masukkan lagi ke grup ini agar budget tidak dobel. "
                    + stock_tip
                )
            else:
                hist_b, hist_o, hist_roas = _hist_perf_for_code(work, code)
                strong_hist = (
                    hist_b > 0
                    and hist_o > 0
                    and hist_roas == hist_roas
                    and target_roas > 0
                    and hist_roas >= target_roas * 0.8
                )
                ok_hist = (
                    hist_o > 0
                    and (
                        hist_roas != hist_roas
                        or hist_roas >= max(target_roas * 0.5, 1.0)
                    )
                )
                if margin is not None and margin <= 0:
                    act = "Tidak perlu di-setup"
                    tip = (
                        "Margin kotor di bawah potongan Shopee — rugi bila diiklankan. "
                        "Jangan masukkan ke grup baru. " + stock_tip
                    )
                elif stock_status == "kosong":
                    act = "Tidak perlu di-setup"
                    tip = stock_tip
                elif hist_b > 0 and hist_o <= 0:
                    act = "Tidak perlu di-setup"
                    tip = (
                        f"Di campaign/grup sebelumnya berbiaya {_rp_hari(hist_b)} tanpa omzet. "
                        "Jangan ikut di-setup di grup ini. " + stock_tip
                    )
                elif hist_b > 0 and hist_roas == hist_roas and target_roas > 0 and hist_roas < target_roas * 0.5:
                    act = "Tidak perlu di-setup"
                    tip = (
                        f"Histori di grup ini ROAS {hist_roas:.1f}× jauh di bawah target {target_roas:.1f}×. "
                        "Tidak layak di-setup ulang di grup ini. " + stock_tip
                    )
                elif stock_status == "isi_dari_dc":
                    act = "Tidak perlu di-setup"
                    tip = (
                        stock_tip
                        + " Setelah stok masuk Site 10037, baru masukkan ke grup."
                    )
                elif not pushes_target and not strong_hist:
                    # Prediksi tidak mendorong target → tidak perlu setup
                    floor_txt = (
                        f"≥ {_rp_hari(sales_floor)} (produk pembentuk 95% sales toko)"
                        if sales_floor > 0 else "batas sales toko"
                    )
                    qty_txt = (
                        f" atau ≥ {qty_floor:.1f} unit/hari".replace(".", ",")
                        if qty_floor < float("inf") else ""
                    )
                    tip = (
                        f"Prediksi sales {_rp_hari(demand_v)}"
                        + (f" ({qty_v:.1f} unit/hari)".replace(".", ",") if qty_v > 0 else "")
                        + f" di bawah batas kejar target ({floor_txt}{qty_txt}). "
                        "Tidak mendorong target — tidak perlu di-setup di grup ini. "
                        + stock_tip
                    )
                    act = "Tidak perlu di-setup"
                elif stock_status == "ada_toko" and (pushes_target or strong_hist or ok_hist):
                    act = "Layak di-setup di grup ini"
                    why = ["belum diiklankan di tempat lain"]
                    if pushes_target:
                        why.append(
                            f"prediksi sales {_rp_hari(demand_v)}"
                            + (f" / {qty_v:.1f} unit".replace(".", ",") if qty_v > 0 else "")
                            + " mendorong target"
                            + (f" (≥ {_rp_hari(sales_floor)} = 95% sales toko)" if sales_floor > 0 else "")
                        )
                    if strong_hist or (ok_hist and hist_roas == hist_roas and hist_b > 0):
                        why.append(
                            f"histori di grup ini ROAS {hist_roas:.1f}×"
                            + (f" vs target {target_roas:.1f}×" if target_roas > 0 else "")
                            + f" (biaya {_rp_hari(hist_b)} → omzet {_rp_hari(hist_o)})"
                        )
                    elif ok_hist and hist_o > 0:
                        why.append(f"pernah menghasilkan omzet iklan {_rp_hari(hist_o)} di grup ini")
                    why.append(stock_sites_text(sig, short=True) + " — stok toko ada")
                    tip = (
                        "Kenapa harus diiklankan: " + "; ".join(why) + ". "
                        "Masukkan produk ini saat grup diaktifkan di Seller Center."
                    )
                else:
                    act = "Tidak perlu di-setup"
                    tip = (
                        "Belum ada bukti kuat (prediksi mendorong target / histori ROAS / stok toko) "
                        "bahwa produk ini layak ikut grup baru. Tunda dulu; fokus ke item yang sudah jelas. "
                        + stock_tip
                    )
        elif stock_status == "kosong" and biaya > 0:
            act = "Keluarkan dari grup"
            tip = (
                f"Masih berbiaya {_rp_hari(biaya)} padahal {stock_tip} "
                "Keluarkan dari grup / jeda sampai ada stok."
            )
        elif alts and biaya <= 0 and omzet <= 0:
            act = "Sudah diiklankan di tempat lain"
            tip = f"Di grup ini belum berbiaya, tetapi sudah aktif di: {alt_label}. Hindari dobel budget. {stock_tip}"
        elif biaya > 0 and omzet <= 0:
            act = "Keluarkan dari grup"
            tip = (
                f"Ada biaya {_rp_hari(biaya)} tanpa omzet di laporan terakhir. "
                "Keluarkan dari grup agar tidak menyerap budget anggota lain. " + stock_tip
            )
        elif margin is not None and margin <= 0 and biaya > 0:
            act = "Keluarkan dari grup"
            tip = (
                "Margin kotor di bawah potongan Shopee (rugi per unit) tetapi masih berbiaya di grup. "
                "Keluarkan dari grup. " + stock_tip
            )
        elif (
            biaya > 0
            and roas == roas
            and (
                (target_roas > 0 and roas < target_roas * 0.5)
                or (group_roas == group_roas and roas < group_roas * 0.4)
            )
        ):
            act = "Keluarkan dari grup"
            tip = (
                f"ROAS {roas:.1f}× jauh di bawah "
                + (f"target {target_roas:.1f}×" if target_roas > 0 else "acuan")
                + (f" dan rata-rata grup {group_roas:.1f}×" if group_roas == group_roas else "")
                + f". Porsi biaya {share_c * 100:.0f}% — keluarkan agar grup tidak menopang item lemah. "
                + stock_tip
            )
        elif (
            biaya > 0
            and roas == roas
            and (
                (target_roas > 0 and roas < target_roas * 0.9)
                or (group_roas == group_roas and roas < group_roas * 0.7)
            )
        ):
            act = "Kurangi porsi / tinjau"
            tip = (
                f"ROAS {roas:.1f}× masih lemah vs grup"
                + (f" ({group_roas:.1f}×)" if group_roas == group_roas else "")
                + ". Jangan naikkan budget grup demi item ini; tinjau di Seller Center atau keluarkan bila tetap lemah. "
                + stock_tip
            )
        elif (
            share_o >= 0.3
            and len(part) > 2
            and roas == roas
            and (
                (target_roas > 0 and roas >= target_roas * 0.8)
                or (group_roas == group_roas and roas >= group_roas)
            )
        ):
            act = "Pisahkan jadi iklan tunggal"
            tip = (
                f"Andalan grup ({share_o * 100:.0f}% omzet, ROAS {roas:.1f}×). "
                "Pertimbangkan iklan produk tunggal agar budget & Target ROAS dikendalikan sendiri. "
                + stock_tip
            )
        else:
            act = "Pertahankan di grup"
            if biaya <= 0 and omzet <= 0:
                tip = "Belum ada biaya/omzet di laporan terakhir — belum menyerap budget grup. " + stock_tip
            elif roas == roas:
                tip = (
                    f"ROAS {roas:.1f}× sejalan dengan grup"
                    + (f" ({group_roas:.1f}×)" if group_roas == group_roas else "")
                    + f". Porsi omzet {share_o * 100:.0f}% — aman dilanjutkan di grup. "
                    + stock_tip
                )
            else:
                tip = "Belum cukup data ROAS; pantau lagi setelah laporan berikutnya. " + stock_tip
        rows.append({
            "Produk": str(r.nama or code),
            "Kode produk": code,
            "Stok 10037": sig.get("stok_10037", float("nan")),
            "Stok 10062": sig.get("stok_10062", float("nan")),
            "Stok 10036": sig.get("stok_10036", float("nan")),
            "Prediksi omzet/hari": demand if demand == demand else float("nan"),
            "Biaya/hari": biaya,
            "Omzet/hari": omzet,
            "ROAS": roas,
            "Porsi omzet grup": share_o * 100,
            "Porsi biaya grup": share_c * 100,
            "Iklan lain": alt_label,
            "Tindakan": act,
            "Saran": tip,
        })
    frame = pd.DataFrame(rows, columns=cols)
    if frame.empty:
        return frame
    rank_map = _MEMBER_RANK_SETUP if not group_active else _MEMBER_RANK
    frame["_rank"] = frame["Tindakan"].map(lambda t: rank_map.get(t, 9))
    # Belum setup: dalam blok Layak urut prediksi tertinggi dulu (yang paling mendorong target).
    sort_cols = ["_rank", "Prediksi omzet/hari"] if not group_active else ["_rank", "Biaya/hari"]
    return (
        frame.sort_values(sort_cols, ascending=[True, False], na_position="last")
        .drop(columns=["_rank"])
        .reset_index(drop=True)
    )


def group_members_summary(member_frame: pd.DataFrame) -> str:
    """Satu kalimat ringkas untuk kartu grup dari hasil `group_members_review`."""
    if member_frame is None or member_frame.empty or "Tindakan" not in member_frame.columns:
        return ""
    acts = member_frame["Tindakan"].astype(str)
    already = int((acts == "Sudah diiklankan di tempat lain").sum())
    skip = int((acts == "Tidak perlu di-setup").sum())
    layak = int((acts == "Layak di-setup di grup ini").sum())
    out = int((acts == "Keluarkan dari grup").sum())
    tinjau = int((acts == "Kurangi porsi / tinjau").sum())
    andalan = int((acts == "Pisahkan jadi iklan tunggal").sum())
    ok = int((acts == "Pertahankan di grup").sum())
    bits = []
    # Urutan sama dengan tabel belum-setup: layak (belum di-setting) dulu.
    if layak:
        bits.append(f"{layak} produk belum di-setup & layak ikut saat grup diaktifkan")
    if skip:
        bits.append(f"{skip} produk tidak perlu di-setup di grup ini")
    if already:
        bits.append(f"{already} produk sudah diiklankan di tempat lain (jangan dobel)")
    if out:
        bits.append(f"{out} produk sebaiknya dikeluarkan (menyedot budget tanpa hasil)")
    if tinjau:
        bits.append(f"{tinjau} produk lemah — jangan naikkan budget grup demi item ini")
    if andalan:
        bits.append(f"{andalan} andalan layak dipertimbangkan jadi iklan tunggal")
    if not bits and ok:
        return f"Isi grup sehat: {ok} produk sejalan dengan performa grup."
    if not bits:
        return ""
    return "Anggota grup: " + "; ".join(bits) + "."


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
