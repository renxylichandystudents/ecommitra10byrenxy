"""Pantauan campaign iklan tersimpan: status per iklan, saran perbaikan, strategi minggu depan.

Membaca hasil `ads_strategy.evaluate` + data prediksi/stok, lalu menyusun tindakan yang bisa dikerjakan di Seller Center
(naikkan/turunkan budget, jeda, buat iklan baru) tanpa mengubah rumus prediksi atau safety stock.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.core import ads_strategy as A

# Urutan prioritas status (kecil = lebih mendesak ditindak)
_STATUS_RANK = {
    "Jeda / hentikan": 0,
    "Turunkan budget": 1,
    "Naikkan budget": 2,
    "Buat / aktifkan": 3,
    "Naikkan Target ROAS": 4,
    "Pertahankan": 5,
}


def _kind_of(key: str, jenis: str | None = None) -> str:
    if jenis:
        return "Grup" if str(jenis).lower().startswith("grup") else "Produk tunggal"
    return "Grup" if str(key).startswith("grup:") else "Produk tunggal"


def classify_rows(frame: pd.DataFrame, *, target_roas: float) -> pd.DataFrame:
    """Lengkapi baris evaluasi dengan Status goals, Tindakan, Saran (bahasa manajer)."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    actions, goals, tips = [], [], []
    for _, r in out.iterrows():
        plan = float(r.get("Budget usulan/hari") or 0)
        expected = float(r.get("Budget efektif Shopee/hari") or A.implementable_budget(plan, r.get("Jenis") or r.get("_key")))
        cost = float(r.get("Biaya aktual/hari") or 0)
        roas = float(r.get("ROAS aktual")) if r.get("ROAS aktual") == r.get("ROAS aktual") else float("nan")
        done = str(r.get("Rekomendasi dijalankan")) == "Ya"
        weak = cost > 0 and roas == roas and target_roas > 0 and roas < target_roas * 0.9
        strong = cost > 0 and roas == roas and target_roas > 0 and roas >= target_roas * 1.1

        if expected <= 0:
            if done:
                goal, act, tip = "Sesuai goals", "Pertahankan", "Iklan dijeda sesuai rencana; biarkan sampai Senin evaluasi."
            else:
                goal, act, tip = "Di luar goals", "Jeda / hentikan", (
                    f"Masih memakan ±{cost:,.0f}/hari padahal rencana jeda. Pause di Seller Center agar biaya tidak bocor.".replace(",", ".")
                )
        elif not done and cost > expected * 1.4:
            goal, act, tip = "Di luar goals", "Turunkan budget", (
                f"Biaya aktual ±{cost:,.0f}/hari di atas acuan Shopee ±{expected:,.0f}/hari. Turunkan budget harian ke "
                f"{expected:,.0f} (kelipatan 25 rb) agar TACoS tidak membengkak.".replace(",", ".")
            )
        elif not done and cost < expected * 0.6:
            goal, act, tip = "Di luar goals", "Naikkan budget", (
                f"Biaya aktual ±{cost:,.0f}/hari di bawah acuan ±{expected:,.0f}/hari"
                + (f" (usulan {plan:,.0f} dinaikkan ke min Shopee)" if expected > plan + 1 else "")
                + f". Isi budget harian {expected:,.0f} di Seller Center, atau cek Target ROAS terlalu tinggi sehingga budget tidak terserap."
            ).replace(",", ".")
        elif weak:
            goal, act, tip = "ROAS di bawah target", "Naikkan Target ROAS", (
                f"Budget sudah dijalankan, tetapi ROAS {roas:.1f} < 90% target {target_roas:.1f}. "
                "Naikkan Target ROAS bertahap (+1 s.d. +2) atau pindahkan budget ke iklan dengan ROAS lebih tinggi."
            )
        elif strong and done:
            goal, act, tip = "Di atas goals", "Pertahankan", (
                f"ROAS {roas:.1f} di atas target. Pertahankan budget; evaluasi naik bertahap maks. 2× hanya di Senin."
            )
        elif done and expected > plan + 1:
            goal, act, tip = "Sesuai goals", "Pertahankan", (
                f"Budget diisi di batas minimum Shopee ({expected:,.0f}/hari); ini wajar meski usulan rencana lebih rendah. "
                "Jangan ditandai gagal.".replace(",", ".")
            )
        elif done:
            goal, act, tip = "Sesuai goals", "Pertahankan", "Budget & ROAS sejalan dengan rencana. Biarkan algoritma Shopee belajar."
        else:
            goal, act, tip = "Perlu dicek", "Naikkan budget", "Sesuaikan budget harian di Seller Center ke acuan efektif, lalu unggah laporan esok hari."

        goals.append(goal)
        actions.append(act)
        tips.append(tip)
    out["Status goals"] = goals
    out["Tindakan"] = actions
    out["Saran"] = tips
    out["_rank"] = out["Tindakan"].map(lambda t: _STATUS_RANK.get(t, 9))
    return out.sort_values(["_rank", "Biaya aktual/hari"], ascending=[True, False]).drop(columns=["_rank"])


def priority_actions(classified: pd.DataFrame, *, limit: int = 8) -> list[dict]:
    """Daftar tindakan prioritas (bukan 'Pertahankan') untuk kartu kerja harian."""
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


def next_week_strategy(products: pd.DataFrame, classified: pd.DataFrame | None, sel_saved: pd.DataFrame | None,
                       *, target_roas: float, daily_budget_room: float, limit: int = 15) -> pd.DataFrame:
    """Usulan item untuk strategi 7 hari ke depan: iklan / jangan iklan / naikkan, berdasar prediksi + hasil pantauan.

    Tidak mengubah prediksi; hanya menyusun prioritas kerja dari angka yang sudah ada."""
    cols = ["Prioritas", "Produk", "Kode produk", "Keputusan", "Budget/hari", "Alasan", "Prediksi omzet/hari", "Stok", "ROAS terkini"]
    if products is None or not isinstance(products, pd.DataFrame) or products.empty:
        return pd.DataFrame(columns=cols)

    roas_by_code: dict[str, float] = {}
    cost_by_code: dict[str, float] = {}
    if isinstance(classified, pd.DataFrame) and not classified.empty and "Iklan" in classified.columns:
        # ROAS/biaya di level iklan; untuk tunggal key mengandung kode produk.
        for _, r in classified.iterrows():
            key = str(r.get("_key") or "")
            if key.startswith(("produk:", "pisah:", "baru:")):
                code = key.split(":", 1)[1]
                roas_by_code[code] = float(r["ROAS aktual"]) if r.get("ROAS aktual") == r.get("ROAS aktual") else float("nan")
                cost_by_code[code] = float(r.get("Biaya aktual/hari") or 0)

    in_plan: dict[str, str] = {}
    if isinstance(sel_saved, pd.DataFrame) and not sel_saved.empty and "Kode produk" in sel_saved.columns:
        saran_col = "Saran" if "Saran" in sel_saved.columns else None
        for _, r in sel_saved.iterrows():
            code = str(r.get("Kode produk") or "")
            if code:
                in_plan[code] = str(r.get(saran_col) or "di rencana") if saran_col else "di rencana"

    work = products.copy()
    if "product_code" not in work.columns:
        return pd.DataFrame(columns=cols)
    work["product_code"] = work["product_code"].astype(str)
    work["omzet_harian"] = pd.to_numeric(work.get("omzet_harian"), errors="coerce").fillna(0.0)
    work["qty_harian"] = pd.to_numeric(work.get("qty_harian"), errors="coerce").fillna(0.0)
    work["stok"] = pd.to_numeric(work.get("stok"), errors="coerce").fillna(0.0)
    work["stok_room"] = pd.to_numeric(work.get("stok_room"), errors="coerce").fillna(work["stok"])
    work = work.sort_values("omzet_harian", ascending=False)

    rows, spent = [], 0.0
    room = max(float(daily_budget_room or 0), 0.0)
    for i, r in enumerate(work.itertuples(index=False), start=1):
        code = str(r.product_code)
        name = str(getattr(r, "nama", code) or code)
        pred = float(r.omzet_harian)
        stok = float(r.stok)
        room_stock = float(getattr(r, "stok_room", stok) or 0)
        roas = roas_by_code.get(code, float("nan"))
        cost_now = cost_by_code.get(code, 0.0)
        planned = code in in_plan

        if stok <= 0 or room_stock <= 0:
            decision, budget, why = "Jangan iklan", 0.0, "Stok Site 10037 kosong / tidak ada ruang jual — isi stok dulu sebelum budget."
        elif roas == roas and roas < max(target_roas * 0.7, 3.0) and cost_now > 0:
            decision, budget, why = "Jeda / turunkan", 0.0, (
                f"ROAS terkini {roas:.1f} jauh di bawah target {target_roas:.1f}; budget lebih baik dialihkan ke item ROAS tinggi."
            )
        elif planned and cost_now > 0 and (roas != roas or roas >= target_roas * 0.9):
            bump = A.round_budget(cost_now * 1.25, min_floor=A.SHOPEE_MIN_SINGLE) if (roas == roas and roas >= target_roas) else A.implementable_budget(cost_now, "Produk tunggal")
            if spent + max(bump - cost_now, 0) <= room + 1 or room <= 0:
                decision, budget, why = "Pertahankan / naikkan bertahap", bump, (
                    f"Sudah di rencana dan berjalan{' · ROAS ' + f'{roas:.1f}' if roas == roas else ''}. "
                    "Naikkan maks. 2× hanya di Senin bila stok aman."
                )
                spent += max(bump - cost_now, 0)
            else:
                decision, budget, why = "Pertahankan", A.implementable_budget(cost_now, "Produk tunggal"), "Pertahankan budget sekarang; sisa ruang budget minggu ini terbatas."
        elif pred >= work["omzet_harian"].quantile(0.85) and stok > 0 and not planned:
            start = A.SHOPEE_MIN_SINGLE
            if spent + start <= room + 1 or room <= 0:
                decision, budget, why = "Buat iklan tunggal", start, (
                    f"Prediksi omzet tinggi (±{pred:,.0f}/hari) tetapi belum di rencana iklan. Mulai di minimum Shopee 25 rb, Target ROAS {target_roas:.0f}.".replace(",", ".")
                )
                spent += start
            else:
                decision, budget, why = "Antrikan", 0.0, "Kandidat kuat, tetapi budget minggu ini sudah penuh — masukkan saat ada ruang."
        elif planned:
            decision, budget, why = "Pertahankan di rencana", A.implementable_budget(max(cost_now, A.SHOPEE_MIN_SINGLE), "Produk tunggal"), "Tetap di pemilihan produk rencana; pantau ROAS 3 hari."
        else:
            continue

        rows.append({
            "Prioritas": len(rows) + 1, "Produk": name, "Kode produk": code, "Keputusan": decision,
            "Budget/hari": budget, "Alasan": why, "Prediksi omzet/hari": pred, "Stok": int(stok),
            "ROAS terkini": roas if roas == roas else np.nan,
        })
        if len(rows) >= limit:
            break
    return pd.DataFrame(rows, columns=cols)


def week_window(today: date | None = None) -> tuple[date, date]:
    """Senin–Minggu minggu berjalan (atau minggu depan bila hari ini Minggu malam setelah evaluasi)."""
    today = today or date.today()
    start = today - timedelta(days=today.weekday())
    # Strategi kerja: dari hari ini s.d. Minggu minggu ini; bila sisa < 2 hari, tampilkan Senin–Minggu depan.
    end = start + timedelta(days=6)
    if (end - today).days < 1:
        start = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
        end = start + timedelta(days=6)
    return start, end


def rollup(classified: pd.DataFrame, summary: dict, *, track: dict | None, target_roas: float) -> dict:
    """Satu verdict pantauan untuk hero UI."""
    total = int(summary.get("iklan") or 0)
    done = int(summary.get("dijalankan") or 0)
    floor_hits = int(summary.get("batas_shopee") or 0)
    roas = float(summary.get("roas")) if summary.get("roas") == summary.get("roas") else float("nan")
    on_sales = track is None or track.get("status") in (None, "On track", "Menunggu data")
    actions = priority_actions(classified, limit=50)
    need = len(actions)
    roas_ok = not (roas == roas and target_roas > 0 and roas < target_roas * 0.9)

    if total == 0:
        level, title, blurb = "info", "Menunggu laporan iklan baru", "Unggah laporan iklan Seller Center agar pelaksanaan campaign bisa dinilai."
    elif done / max(total, 1) >= 0.7 and roas_ok and on_sales and need <= max(2, total * 0.15):
        level, title, blurb = "ok", "Campaign on track", (
            f"{done}/{total} iklan sesuai acuan Seller Center"
            + (f" · {floor_hits} memakai minimum Shopee (bukan penyimpangan)" if floor_hits else "")
            + (f" · ROAS {roas:.1f}" if roas == roas else "")
            + ". Lanjutkan; evaluasi budget besar hanya di Senin."
        )
    elif done / max(total, 1) >= 0.7 and not roas_ok:
        level, title, blurb = "warn", "Budget dijalankan, ROAS masih lemah", (
            f"ROAS aktual {roas:.1f} vs target {target_roas:.1f}. Rapikan iklan ROAS rendah (lihat tindakan prioritas) sebelum menambah budget."
        )
    elif on_sales and need > 0:
        level, title, blurb = "warn", "Sales on track, pelaksanaan iklan perlu rapikan", (
            f"{done}/{total} iklan sesuai acuan"
            + (f" · {floor_hits} sudah di batas minimum Shopee" if floor_hits else "")
            + f" · {need} iklan perlu tindakan di Seller Center."
        )
    else:
        level, title, blurb = "alert", "Perlu tindakan agar rencana berhasil", (
            f"Hanya {done}/{total} iklan sesuai acuan Seller Center. Kerjakan tindakan prioritas, lalu unggah laporan esok hari."
        )
    return {
        "level": level, "title": title, "blurb": blurb, "done": done, "total": total,
        "floor_hits": floor_hits, "need": need, "roas": roas, "roas_ok": roas_ok, "on_sales": on_sales,
    }


def spend_gap_tip(summary: dict, track: dict | None) -> str:
    """Satu kalimat penjelasan selisih biaya vs jalur rencana, dengan konteks minimum Shopee."""
    if not summary:
        return ""
    efektif = float(summary.get("budget_efektif_harian") or summary.get("budget_usulan_harian") or 0)
    aktual = float(summary.get("biaya_harian") or 0)
    floor = int(summary.get("batas_shopee") or 0)
    bits = [f"Acuan efektif Seller Center ±{efektif:,.0f}/hari · aktual ±{aktual:,.0f}/hari".replace(",", ".")]
    if floor:
        bits.append(f"{floor} iklan memakai minimum 25 rb (tunggal) / 100 rb (grup) — ini limitasi Shopee, bukan gagal rencana")
    if track and track.get("biaya_status") == "kurang terserap":
        bits.append("Biaya total masih di bawah jalur: cek Target ROAS terlalu tinggi atau budget belum diubah di Seller Center")
    elif track and track.get("biaya_status") == "lebih boros":
        bits.append("Biaya total di atas jalur: turunkan iklan yang Status-nya 'Budget terlalu tinggi'")
    return " · ".join(bits)
