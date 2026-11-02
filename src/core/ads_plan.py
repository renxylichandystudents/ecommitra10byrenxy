"""Target penjualan & strategi iklan (Revisi Final 4C).

Kurva respons per SKU:  omzet_iklan_harian = a · ln(1 + biaya_harian / b),  b > 0
ROAS marginal pada biaya harian x:  a / (b + x)
Alokasi tambahan budget: greedy per kenaikan Rp 500.000/bulan, skor = ROAS_marginal × margin_pct.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

STEP_RP = 500_000
DAYS = 30
MIN_POINTS = 20
EFFICIENT_ROAS = 10.0
BOOTSTRAP = 200


@dataclass
class Curve:
    a: float
    b: float
    source: str  # "fit" | "median kategori" | "default"
    residual_sd: float = 0.0

    def sales(self, daily_cost: float) -> float:
        return self.a * math.log1p(max(daily_cost, 0.0) / self.b)

    def marginal(self, daily_cost: float) -> float:
        return self.a / (self.b + max(daily_cost, 0.0))


def fit_curve(costs: np.ndarray, sales: np.ndarray) -> Curve | None:
    """Fit a, b dengan scipy.optimize.curve_fit (b > 0). None bila titik berbiaya < MIN_POINTS."""
    costs = np.asarray(costs, dtype=float)
    sales = np.asarray(sales, dtype=float)
    mask = (costs > 0) & np.isfinite(costs) & np.isfinite(sales)
    if mask.sum() < MIN_POINTS:
        return None
    x, y = costs[mask], sales[mask]
    from scipy.optimize import curve_fit

    def model(value, a, b):
        return a * np.log1p(value / b)

    b0 = max(float(np.median(x)), 1.0)
    a0 = max(float(np.mean(y)) / math.log(2), 1.0)
    try:
        params, _cov = curve_fit(model, x, y, p0=(a0, b0), bounds=((0.0, 1.0), (np.inf, np.inf)), maxfev=5000)
    except Exception:
        return None
    a, b = float(params[0]), float(params[1])
    resid = y - model(x, a, b)
    return Curve(a, b, "fit", float(np.std(resid)))


def default_curve(daily_cost: float, roas: float) -> Curve:
    """Tanpa riwayat harian: kurva melewati titik (biaya sekarang, ROAS sekarang) dengan b = biaya harian."""
    b = max(daily_cost, 50_000.0)
    roas = roas if roas and np.isfinite(roas) and roas > 0 else 5.0
    a = roas * b / math.log(2)
    return Curve(a, b, "default", 0.25 * a)


@dataclass
class Candidate:
    sku: str
    label: str
    margin_pct: float
    daily_cost: float
    curve: Curve
    max_extra_daily: float  # batas biaya harian tambahan karena stok (inf = tak dibatasi)
    decision: str
    reasons: list[str] = field(default_factory=list)
    extra_monthly: float = 0.0


def unit_cap_to_cost(curve: Curve, base_daily: float, extra_units: float, price: float) -> float:
    """Biaya harian tambahan maksimal agar tambahan unit/bulan ≤ extra_units."""
    if extra_units <= 0 or price <= 0:
        return 0.0
    target_sales = extra_units * price / DAYS + curve.sales(base_daily)
    if target_sales >= curve.a * 50:
        return float("inf")
    cost = curve.b * (math.exp(target_sales / curve.a) - 1)
    return max(cost - base_daily, 0.0)


def allocate(candidates: list[Candidate], budget_monthly: float, *, min_marginal: float = 0.0) -> list[Candidate]:
    """Greedy: kenaikan Rp 500.000/bulan ke skor (ROAS_marginal × margin) tertinggi sampai budget habis."""
    for cand in candidates:
        cand.extra_monthly = 0.0
    remaining = float(budget_monthly)
    active = [c for c in candidates if c.decision in ("Iklankan", "Dibatasi stok")]
    while remaining >= STEP_RP and active:
        best, best_score = None, -1.0
        for cand in active:
            daily_now = cand.daily_cost + cand.extra_monthly / DAYS
            if (cand.extra_monthly + STEP_RP) / DAYS > cand.max_extra_daily + 1e-9:
                continue
            marginal = cand.curve.marginal(daily_now + STEP_RP / DAYS / 2)
            if marginal < min_marginal:
                continue
            score = marginal * max(cand.margin_pct, 0.01)
            if score > best_score:
                best, best_score = cand, score
        if best is None:
            break
        best.extra_monthly += STEP_RP
        remaining -= STEP_RP
    return candidates


def extra_sales(candidates: list[Candidate]) -> float:
    return float(sum((c.curve.sales(c.daily_cost + c.extra_monthly / DAYS) - c.curve.sales(c.daily_cost)) * DAYS for c in candidates))


def budget_for_gap(candidates: list[Candidate], gap: float, *, cap: float = 2_000_000_000) -> float:
    """Kejar target: budget minimal sehingga omzet tambahan (p50) ≥ gap (cari biner, kelipatan Rp 500.000)."""
    if gap <= 0:
        return 0.0
    lo, hi = 0, int(cap // STEP_RP)
    allocate(candidates, hi * STEP_RP)
    if extra_sales(candidates) < gap:
        return float(hi * STEP_RP)
    while lo < hi:
        mid = (lo + hi) // 2
        allocate(candidates, mid * STEP_RP)
        if extra_sales(candidates) >= gap:
            hi = mid
        else:
            lo = mid + 1
    return float(lo * STEP_RP)


def bootstrap_range(candidates: list[Candidate], *, runs: int = BOOTSTRAP, seed: int = 7) -> tuple[float, float]:
    """Persentil 10–90 omzet tambahan dari 200× gangguan residual kurva."""
    rng = np.random.default_rng(seed)
    totals = []
    for _ in range(runs):
        total = 0.0
        for cand in candidates:
            if cand.extra_monthly <= 0:
                continue
            base = cand.curve.sales(cand.daily_cost)
            new = cand.curve.sales(cand.daily_cost + cand.extra_monthly / DAYS)
            noise = rng.normal(0.0, cand.curve.residual_sd) if cand.curve.residual_sd > 0 else 0.0
            scale = max((new - base) + noise * (new - base) / max(cand.curve.a, 1e-9), 0.0)
            total += scale * DAYS
        totals.append(total)
    if not totals:
        return 0.0, 0.0
    return float(np.percentile(totals, 10)), float(np.percentile(totals, 90))


def strategy_rows(
    candidates: list[Candidate],
    *,
    target: float,
    predicted_sales: float,
    predicted_margin: float,
) -> tuple[pd.DataFrame, dict[str, dict[str, float]]]:
    """Tabel tiga strategi + alokasi per strategi {nama: {sku: budget}}."""
    gap = max(target - predicted_sales, 0.0)
    chase = budget_for_gap(candidates, gap)
    balanced = round(chase * 0.6 / 5_000_000) * 5_000_000
    plans = {}
    rows = []
    for name, budget, floor in (("Kejar target", chase, 0.0), ("Seimbang", balanced, 0.0), ("Efisien", chase, EFFICIENT_ROAS)):
        allocate(candidates, budget, min_marginal=floor)
        used = sum(c.extra_monthly for c in candidates)
        add = extra_sales(candidates)
        low, high = bootstrap_range(candidates)
        roas = add / used if used > 0 else float("nan")
        margin_add = sum((c.curve.sales(c.daily_cost + c.extra_monthly / DAYS) - c.curve.sales(c.daily_cost)) * DAYS * c.margin_pct / 100 for c in candidates)
        total = predicted_sales + add
        rows.append(
            {
                "Strategi": name,
                "Budget tambahan": used,
                "Omzet tambahan (p50)": add,
                "Rentang omzet (p10–p90)": (low, high),
                "ROAS tambahan": roas,
                "Rentang ROAS": (low / used if used else float("nan"), high / used if used else float("nan")),
                "% target": total / target * 100 if target > 0 else float("nan"),
                "Margin strategi (%)": (predicted_margin + margin_add - used) / total * 100 if total > 0 else float("nan"),
            }
        )
        plans[name] = {c.sku: c.extra_monthly for c in candidates if c.extra_monthly > 0}
    return pd.DataFrame(rows), plans
