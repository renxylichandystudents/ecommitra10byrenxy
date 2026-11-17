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


def classify_rows(frame: pd.DataFrame, *, target_roas: float, running_keys: set[str] | None = None) -> pd.DataFrame:
    """Lengkapi baris evaluasi dengan Status goals, Status SC, Tindakan, Saran."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    running = running_keys or set()
    actions, goals, tips, sc = [], [], [], []
    for _, r in out.iterrows():
        key = str(r.get("_key") or "")
        plan = float(r.get("Budget usulan/hari") or 0)
        expected = float(r.get("Budget efektif Shopee/hari") or A.implementable_budget(plan, r.get("Jenis") or key))
        cost = float(r.get("Biaya aktual/hari") or 0)
        roas = float(r.get("ROAS aktual")) if r.get("ROAS aktual") == r.get("ROAS aktual") else float("nan")
        done = str(r.get("Rekomendasi dijalankan")) == "Ya"
        is_run = key in running or any(k for k in running if k == key or key.endswith(":" + k.split(":")[-1]))
        # cocokkan juga kunci produk: laporan
        if not is_run and running:
            report = "produk:" + key.split(":", 1)[1] if key.startswith(("pisah:", "baru:")) else key
            is_run = report in running or key in running
        sc_label = "Berjalan" if is_run or cost > max(expected * 0.3, 10_000) else "Tidak aktif / rendah"
        weak = cost > 0 and roas == roas and target_roas > 0 and roas < target_roas * 0.9

        if expected <= 0:
            if done or cost <= 5_000:
                goal, act, tip = "Sesuai goals", "Pertahankan", "Iklan dijeda sesuai rencana."
            else:
                goal, act, tip = "Di luar goals", "Jeda / hentikan", (
                    f"Masih memakan ±{cost:,.0f}/hari padahal rencana jeda. Pause di Seller Center.".replace(",", ".")
                )
        elif sc_label.startswith("Tidak") and expected > 0:
            goal, act, tip = "Belum aktif di SC", "Buat / aktifkan", (
                f"Rencana meminta ±{expected:,.0f}/hari tetapi iklan belum terlihat aktif di laporan. "
                "Aktifkan / buat di Seller Center, lalu unggah laporan.".replace(",", ".")
            )
        elif not done and cost > expected * 1.4:
            goal, act, tip = "Di luar goals", "Turunkan budget", (
                f"Biaya ±{cost:,.0f}/hari di atas acuan ±{expected:,.0f}/hari. Turunkan ke {expected:,.0f}.".replace(",", ".")
            )
        elif not done and cost < expected * 0.6:
            goal, act, tip = "Di luar goals", "Naikkan budget", (
                f"Biaya ±{cost:,.0f}/hari di bawah acuan ±{expected:,.0f}/hari"
                + (f" (usulan {plan:,.0f} → min Shopee)" if expected > plan + 1 else "")
                + ". Isi budget di Seller Center atau longgarkan Target ROAS."
            ).replace(",", ".")
        elif weak:
            goal, act, tip = "ROAS di bawah target", "Naikkan Target ROAS", (
                f"ROAS {roas:.1f} < 90% target {target_roas:.1f}. Naikkan Target ROAS atau pindah budget ke iklan lebih kuat."
            )
        elif done and expected > plan + 1:
            goal, act, tip = "Sesuai goals", "Pertahankan", (
                f"Di batas minimum Shopee ({expected:,.0f}/hari) — wajar, bukan gagal rencana.".replace(",", ".")
            )
        elif done:
            goal, act, tip = "Sesuai goals", "Pertahankan", "Budget & ROAS sejalan dengan rencana."
        else:
            goal, act, tip = "Perlu dicek", "Naikkan budget", "Sesuaikan budget ke acuan efektif, unggah laporan esok hari."

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
            f"Laporan keseluruhan sejak campaign: biaya {store_since.get('biaya', 0):,.0f} · omzet iklan {store_since.get('omzet', 0):,.0f}"
            .replace(",", ".")
        )
        if store_since.get("biaya", 0) > 0:
            bits.append(f"ROAS SC {store_since['omzet'] / store_since['biaya']:.1f}")
    if wallet.get("rencana_harian"):
        bits.append(
            f"Rencana harian {wallet['rencana_harian']:,.0f} · terpakai sejak {wallet['terpakai_sejak']:,.0f} vs jalur {wallet['jalur_sejak']:,.0f}"
            .replace(",", ".")
        )
    if summary.get("batas_shopee"):
        bits.append(f"{summary['batas_shopee']} iklan di min. Shopee 25 rb/100 rb (bukan gagal rencana)")
    return " · ".join(bits)
