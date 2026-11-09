"""Strategi budget & ROAS tetap: hasil terbesar dengan budget maksimal dan ROAS minimal yang ditetapkan pengguna.

Rencana iklan memakai alur yang sama dengan Kejar target (`ads_strategy.build_plan` + `ramp`), dengan dua tambahan:
- tambahan omzet tiap iklan dibatasi juga oleh ruang stok produknya, supaya budget tidak dipakai untuk barang yang akan habis;
- budget mingguan disebar per tanggal mengikuti pola hari (gajian, tanggal kembar, hari dalam minggu), total budget tetap.
Pada budget terkunci, Target ROAS dipilih otomatis (`pick_roas`) dan dibandingkan dengan ROAS yang dibutuhkan target (`needed_roas`).
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, timedelta
from typing import Callable

import numpy as np
import pandas as pd

from src.core import ads_strategy as A

DAY_LO, DAY_HI, DAY_STEP = 0.7, 1.4, 0.05   # pengali budget harian; 1,4 ÷ 0,7 = 2× (batas perubahan Shopee)


def stock_capped(units: list[A.Unit]) -> list[A.Unit]:
    """Batas tambahan omzet iklan = min(daya dorong × prediksi, ruang stok). Unit tanpa data stok tidak dibatasi."""
    out = []
    for u in units:
        if u.locked or not np.isfinite(u.stock_room) or u.lift <= 0:
            out.append(u)
            continue
        cap = max(u.stock_room, 0.0) / u.lift
        out.append(replace(u, demand=cap) if cap < u.demand else u)
    return out


def stock_limited(u: A.Unit) -> bool:
    """Tambahan omzet iklan ini dibatasi stok (bukan permintaan)."""
    return not u.locked and np.isfinite(u.stock_room) and np.isfinite(u.demand) and abs(A.uplift_cap(u) - max(u.stock_room, 0.0)) < 1.0


def can_grow(u: A.Unit, cost: float) -> bool:
    """Budget iklan ini masih menambah omzet (ROAS marginal ≥ 1 untuk +10% budget): belum mentok permintaan/stok."""
    if cost <= 0 or u.locked:
        return False
    return (A.ad_sales(u, cost * 1.1) - A.ad_sales(u, cost)) / (cost * 0.1) >= 1.0


def day_plan(units: list[A.Unit], steps: list[tuple[int, A.Plan]], blocks: list[tuple[date, date]],
             shape: Callable[[date], float]) -> tuple[pd.DataFrame, dict]:
    """Budget per tanggal: dalam tiap minggu, total budget tetap, pengali harian 0,7–1,4 disebar ke hari yang paling ramai.

    Omzet iklan hari d = pola(d) × omzet iklan pada budget × pengali (kurva respons cekung), jadi menambah budget di hari
    ramai dan mengurangi di hari sepi memberi omzet lebih besar dengan biaya sama. Pengali hanya untuk iklan yang masih
    bisa tumbuh (`can_grow`); iklan yang sudah mentok permintaan/stok tetap datar. Dicari dengan alokasi serakah per
    langkah 0,05 (optimal untuk kurva cekung). Mengembalikan (kalender, ringkasan; `ikut` = kunci iklan yang ikut pengali)."""
    grid = np.round(np.arange(DAY_LO, DAY_HI + 1e-9, DAY_STEP), 4)
    one = int(np.argmin(np.abs(grid - 1.0)))
    rows, flat_total, opt_total, cost_total, follow = [], 0.0, 0.0, 0.0, set()
    for week, ((_days, plan), (a, b)) in enumerate(zip(steps, blocks), start=1):
        dates = [a + timedelta(days=i) for i in range((b - a).days + 1)]
        cost = sum(plan.cost.values())
        s = np.array([max(float(shape(d)), 0.0) for d in dates])
        if cost <= 0 or not dates:
            rows += [{"Tanggal": d, "Minggu": week, "Pola hari": v, "Pengali budget": 1.0, "Budget/hari": 0.0, "Omzet iklan/hari": 0.0}
                     for d, v in zip(dates, s)]
            continue
        free = [u for u in units if can_grow(u, plan.cost.get(u.key, 0.0))]
        fixed = [u for u in units if u not in free]
        follow |= {u.key for u in free}
        free_cost = sum(plan.cost[u.key] for u in free)
        fixed_sales = sum(A.ad_sales(u, plan.cost.get(u.key, 0.0)) for u in fixed)
        curve = np.array([fixed_sales + sum(A.ad_sales(u, plan.cost[u.key] * m) for u in free) for m in grid])
        idx = np.zeros(len(dates), dtype=int)
        for _ in range(int(round(len(dates) * one))):
            room = idx < len(grid) - 1
            inc = np.where(room, s * (curve[np.minimum(idx + 1, len(grid) - 1)] - curve[idx]) + 1e-9 * s, -np.inf)
            j = int(np.argmax(inc))
            if not np.isfinite(inc[j]):
                break
            idx[j] += 1
        flat_total += float(s.sum() * curve[one])
        opt_total += float((s * curve[idx]).sum())
        cost_total += cost * len(dates)
        rows += [{"Tanggal": d, "Minggu": week, "Pola hari": v, "Pengali budget": float(grid[i]),
                  "Budget/hari": cost - free_cost + free_cost * float(grid[i]), "Omzet iklan/hari": v * float(curve[i])} for d, v, i in zip(dates, s, idx)]
    frame = pd.DataFrame(rows, columns=["Tanggal", "Minggu", "Pola hari", "Pengali budget", "Budget/hari", "Omzet iklan/hari"])
    frame["ROAS hari"] = (frame["Omzet iklan/hari"] / frame["Budget/hari"]).where(frame["Budget/hari"] > 0)
    return frame, {"tambahan": opt_total - flat_total, "omzet_rata": flat_total, "omzet_atur": opt_total, "biaya": cost_total, "ikut": follow}


def pick_roas(gain_at: Callable[[float], float], *, grid: tuple[float, ...] = A.ROAS_GRID, tol: float = 0.005) -> float:
    """Target ROAS dengan tambahan omzet iklan terbesar pada budget terkunci; bila beberapa hampir sama (selisih ≤ tol), yang tertinggi.

    Semua ROAS di grid dicoba karena hasilnya tidak selalu naik saat ROAS diturunkan (pemilihan produk ikut bergantung pada ROAS)."""
    gains = {float(r): gain_at(float(r)) for r in grid if 1.0 <= r <= A.MAX_SHOPEE_ROAS}
    top = max(gains.values())
    return max(r for r, g in gains.items() if g >= top - abs(top) * tol)


def selection_roas(units: list[A.Unit]) -> float:
    """ROAS acuan pemilihan produk pada budget terkunci: ROAS iklan berjalan sekarang (kelipatan 0,5, maks. 30), tetap saat ROAS dicoba."""
    return shopee_roas(A._store_roas(units))


def shopee_roas(roas: float) -> float:
    """Target ROAS yang diisi di Shopee: ROAS rata-rata rencana dibulatkan ke bawah ke kelipatan 0,5, dalam batas 1–30."""
    if not roas == roas or roas <= 0:
        return 1.0
    return min(max(math.floor(roas * 2) / 2, 1.0), A.MAX_SHOPEE_ROAS)


def needed_roas(*, sales_now_daily: float, gap: float, days: int, budget: float) -> float:
    """ROAS rata-rata seluruh budget agar target tercapai: (omzet iklan sekarang × hari + kekurangan omzet) ÷ budget."""
    return (sales_now_daily * days + gap) / budget if budget > 0 else float("inf")
