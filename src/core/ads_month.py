"""Budget iklan sebulan & kurva respons toko untuk fitur Iklan kejar target.

- Biaya iklan yang sudah keluar bulan ini dibaca dari laporan iklan keseluruhan ("all iklan", acuan total iklan),
  diprorata ke tanggal 1 s.d. hari data terakhir (`ads.ad_report_rows`, laporan tumpang tindih tidak dihitung dua kali).
- Kurva respons toko: sales bersih bulanan = s0 + a · ln(1 + biaya iklan bulanan / b), b = median biaya bulanan riwayat.
  s0 dan a dari kuadrat terkecil atas bulan-bulan penuh yang punya laporan iklan. Kurva ini mengukur tambahan sales
  bersih seluruh toko per tambahan biaya iklan (bukan omzet yang diklaim iklan Shopee), sehingga dipakai untuk
  menghitung budget yang dibutuhkan agar target bulan tercapai.
- Bulan berjalan: proyeksi tanpa perubahan sudah memuat laju iklan sekarang. Tambahan dihitung dari laju biaya
  bulanan sekarang C0 ke laju baru C1 selama hari tersisa: tambahan = (s(C1) − s(C0)) × hari_sisa / hari_bulan.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

MIN_MONTHS = 3


def _month_bounds(first: date) -> tuple[date, date]:
    last = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
    return first, last


def ad_spend(ads_overall: pd.DataFrame | None, start: date, end: date) -> dict:
    """Biaya & omzet iklan (klaim Shopee) dari laporan iklan keseluruhan pada [start, end], diprorata per hari laporan.

    {"biaya", "omzet", "hari": hari yang tercakup laporan, "sampai": tanggal terakhir yang tercakup}."""
    from src.core import ads as A

    empty = {"biaya": 0.0, "omzet": 0.0, "hari": 0, "sampai": None}
    if ads_overall is None or not isinstance(ads_overall, pd.DataFrame) or ads_overall.empty or end < start:
        return empty
    rows, lo, hi, days = A.ad_report_rows([ads_overall], start=start, end=end)
    if rows.empty:
        return empty
    covered_hi = None
    if "_uhi" in rows.columns and rows["_uhi"].notna().any():
        covered_hi = min(pd.Timestamp(rows["_uhi"].max()).date(), end)
    return {"biaya": float(rows["biaya_iklan"].sum()), "omzet": float(rows["omzet_iklan"].sum()), "hari": int(days), "sampai": covered_hi}


@dataclass
class StoreCurve:
    s0: float
    a: float
    b: float
    points: list[tuple[str, float, float]]  # (bulan, biaya, sales bersih)
    source: str

    def sales(self, monthly_cost: float) -> float:
        return self.s0 + self.a * math.log1p(max(monthly_cost, 0.0) / self.b)

    def marginal(self, monthly_cost: float) -> float:
        """Tambahan sales bersih per Rp 1 biaya iklan pada laju biaya bulanan ini."""
        return self.a / (self.b + max(monthly_cost, 0.0))

    def cost_for_lift(self, base_cost: float, lift: float) -> float:
        """Laju biaya bulanan baru agar sales naik `lift` dari laju `base_cost`."""
        if lift <= 0:
            return base_cost
        return (self.b + base_cost) * math.exp(lift / self.a) - self.b


def fit_store_curve(history: list[tuple[str, float, float]]) -> StoreCurve | None:
    """history = [(bulan "YYYY-MM", biaya iklan bulanan, sales bersih bulanan)] bulan penuh. None bila < MIN_MONTHS titik
    atau kemiringan tidak positif (riwayat tidak menunjukkan hubungan biaya iklan → sales)."""
    pts = [(m, float(c), float(s)) for m, c, s in history if c > 0 and s > 0]
    if len(pts) < MIN_MONTHS:
        return None
    costs = np.array([p[1] for p in pts])
    sales = np.array([p[2] for p in pts])
    b = float(np.median(costs))
    x = np.log1p(costs / b)
    design = np.column_stack([np.ones_like(x), x])
    (s0, a), *_ = np.linalg.lstsq(design, sales, rcond=None)
    if not np.isfinite(a) or a <= 0:
        return None
    return StoreCurve(float(s0), float(a), b, pts, f"{len(pts)} bulan riwayat (biaya iklan keseluruhan vs sales bersih toko)")


def monthly_history(ads_overall: pd.DataFrame | None, monthly_sales: dict[str, float], *, before: date, months: int = 8) -> list[tuple[str, float, float]]:
    """Titik (bulan, biaya iklan, sales bersih) untuk bulan penuh sebelum `before` yang laporan iklannya mencakup ≥ 90% hari."""
    out = []
    first = before.replace(day=1)
    for _ in range(months):
        prev_last = first - pd.Timedelta(days=1)
        first = date(prev_last.year, prev_last.month, 1)
        lo, hi = _month_bounds(first)
        key = f"{first.year:04d}-{first.month:02d}"
        spend = ad_spend(ads_overall, lo, hi)
        days = (hi - lo).days + 1
        if spend["biaya"] > 0 and spend["hari"] >= 0.9 * days and monthly_sales.get(key, 0) > 0:
            out.append((key, spend["biaya"], float(monthly_sales[key])))
    return sorted(out)


def month_plan(curve: StoreCurve | None, *, target: float, projection: float, spent: float, cost_now_daily: float,
               days_left: int, month_days: int, budget_total: float | None = None) -> dict:
    """Budget sebulan yang dibutuhkan untuk target, dan hasil budget sebulan yang diisi user (bila ada).

    - pace0 = laju biaya bulanan sekarang (biaya harian berjalan × hari bulan) — sudah tercermin di proyeksi.
    - Kebutuhan: laju baru C1 sehingga tambahan sales hari tersisa menutup kekurangan target; budget sebulan = terpakai + C1 × porsi hari sisa.
    - Budget user: sisa = budget − terpakai → laju C = sisa ÷ porsi hari sisa → tambahan = (s(C) − s(pace0)) × porsi."""
    share = max(days_left, 0) / max(month_days, 1)
    pace0 = max(cost_now_daily, 0.0) * month_days
    gap = max(target - projection, 0.0)
    out: dict = {"porsi": share, "laju_sekarang": pace0, "kekurangan": gap, "terpakai": spent}
    if curve is None or share <= 0:
        out.update({"ada_kurva": False})
        return out
    out["ada_kurva"] = True
    need_lift = gap / share
    c1 = curve.cost_for_lift(pace0, need_lift) if gap > 0 else pace0
    remaining_need = c1 * share
    out.update({
        "budget_dibutuhkan": spent + remaining_need, "sisa_dibutuhkan": remaining_need, "harian_dibutuhkan": remaining_need / max(days_left, 1),
        "roas_tambahan_dibutuhkan": gap / max(remaining_need - pace0 * share, 1.0) if gap > 0 else float("nan"),
    })
    if budget_total is not None:
        remaining = max(budget_total - spent, 0.0)
        pace = remaining / share
        extra = (curve.sales(pace) - curve.sales(pace0)) * share
        out.update({"budget_sisa": remaining, "harian_sisa": remaining / max(days_left, 1), "tambahan": extra, "proyeksi": projection + extra,
                    "roas_tambahan": extra / max(remaining - pace0 * share, 1.0) if remaining > pace0 * share else float("nan")})
    return out


def plan_track(setelan: dict, *, mtd: float, last: date, spent: float, periode: str, sales_tol: float = 0.97, spend_tol: float = 0.15) -> dict | None:
    """Pantauan rencana iklan tersimpan: apakah sales bersih & biaya iklan sejak rencana disimpan sesuai jalur rencana.

    Jalur rencana (dibagi rata ke hari tersisa saat disimpan):
    - sales bersih s.d. hari ini = sales saat disimpan + (proyeksi rencana − sales saat disimpan) × hari_berjalan ÷ hari_sisa
    - biaya iklan s.d. hari ini = terpakai saat disimpan + budget harian rencana × hari_berjalan
    On track = sales aktual ≥ sales_tol × jalur. None bila rencana tidak menyimpan titik awal (rencana lama) atau bulan sudah berganti."""
    s = setelan or {}
    if not s.get("data_sampai") or s.get("periode_target") != periode or not s.get("hari_sisa"):
        return None
    start = date.fromisoformat(str(s["data_sampai"])[:10])
    left = max(int(s["hari_sisa"]), 1)
    days = (last - start).days
    mtd0, spent0 = float(s.get("mtd") or 0), float(s.get("terpakai") or 0)
    final = float(s.get("proyeksi") or 0)
    base = float(s.get("proyeksi_tanpa") or final)
    daily_budget = float(s.get("biaya_harian_rencana") or s.get("budget_harian") or 0)
    out = {"hari": max(days, 0), "hari_sisa": left, "mulai": start, "mtd_awal": mtd0, "terpakai_awal": spent0, "proyeksi_rencana": final}
    if days <= 0:
        out.update({"status": "Menunggu data", "jalur_sales": mtd0, "jalur_biaya": spent0, "sales": mtd, "biaya": spent})
        return out
    frac = min(days / left, 1.0)
    path_sales = mtd0 + (final - mtd0) * frac
    path_base = mtd0 + (base - mtd0) * frac
    path_cost = spent0 + daily_budget * min(days, left)
    sales_new, cost_new = mtd - mtd0, spent - spent0
    sales_pct = mtd / path_sales * 100 if path_sales > 0 else float("nan")
    cost_pct = cost_new / (path_cost - spent0) * 100 if path_cost > spent0 else float("nan")
    on = path_sales <= 0 or mtd >= sales_tol * path_sales
    if cost_pct == cost_pct and cost_pct > (1 + spend_tol) * 100:
        spend = "lebih boros"
    elif cost_pct == cost_pct and cost_pct < (1 - spend_tol) * 100:
        spend = "kurang terserap"
    else:
        spend = "sesuai"
    out.update({
        "status": "On track" if on else "Tertinggal", "jalur_sales": path_sales, "jalur_tanpa": path_base, "jalur_biaya": path_cost,
        "sales": mtd, "biaya": spent, "sales_baru": sales_new, "biaya_baru": cost_new, "pct_sales": sales_pct, "pct_biaya": cost_pct,
        "selisih_sales": mtd - path_sales, "biaya_status": spend,
        "roas_baru": sales_new / cost_new if cost_new > 0 else float("nan"),
    })
    return out


SHOPEE_MIN_AD_PCT = 3.0  # syarat minimum biaya iklan Shopee (% sales bruto sebulan) agar mendapat benefit program


def budget_for_ratio(project, *, pct: float, gross_ratio: float, spent: float, start: float, rounds: int = 6) -> float:
    """Budget sebulan yang membuat biaya iklan ≈ pct% dari sales bruto proyeksi bulan itu.

    project(budget) -> (proyeksi sales bersih, biaya efektif); sales bruto = sales bersih × gross_ratio (rasio bruto ÷ bersih
    bulan berjalan). Diulang karena sales ikut berubah saat budget berubah. Tidak kurang dari biaya yang sudah terpakai."""
    budget = max(start, spent)
    for _ in range(rounds):
        net, _effective = project(budget)
        nxt = max(pct / 100 * net * gross_ratio, spent)
        if abs(nxt - budget) < 100_000:
            budget = nxt
            break
        budget = nxt
    return float(math.ceil(budget / 1_000_000) * 1_000_000)


def store_contribution_rate(contribution: dict, weights: dict) -> float | None:
    """Kontribusi sebelum iklan (margin kotor − potongan Shopee, % harga) rata-rata tertimbang prediksi omzet produk; None bila tidak ada data."""
    pairs = [(float(contribution[c]), float(weights.get(c, 0.0) or 0.0)) for c in contribution if (weights.get(c, 0.0) or 0.0) > 0]
    total = sum(w for _r, w in pairs)
    if not pairs or total <= 0:
        return None
    return sum(r * w for r, w in pairs) / total
