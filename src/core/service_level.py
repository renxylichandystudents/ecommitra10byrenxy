"""Rekomendasi persentase safety stock per periode dan dampak bila pengguna mengubahnya.

Critical ratio (newsvendor): CR = Cu / (Cu + Co)
- Cu (biaya kekurangan per rupiah harga) = margin kotor + penalti kehabisan stok
- Co (biaya kelebihan per rupiah harga) = biaya simpan per tahun × hari periode / 365
Lalu disesuaikan campuran ABC penjualan: porsi kelas A menaikkan, porsi kelas C menurunkan.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
import pandas as pd

PERIOD_DAYS = {"bulan": 30, "kuartal": 91, "semester": 182, "tahun": 365}
MIN_PCT = 80
MAX_PCT = 99
ABC_UP_PP = 2.0
ABC_DOWN_PP = 5.0


@dataclass
class ServiceRecommendation:
    pct: int
    critical_ratio: float
    cu: float
    co: float
    share_a: float
    share_c: float
    used_default: bool


def z_value(pct: float) -> float:
    level = float(pct)
    if level <= 0:
        return 0.0
    if level >= 100:
        return float(NormalDist().inv_cdf(0.999)) * level / 100.0
    return float(NormalDist().inv_cdf(level / 100.0))


def abc_sales_share(orders: pd.DataFrame | None) -> tuple[float, float]:
    """Porsi sales kelas A (80% pertama) dan kelas C (5% terakhir) dari data latih."""
    if orders is None or orders.empty or not {"item_key", "sales"} <= set(orders.columns):
        return 0.0, 0.0
    sales = orders.groupby("item_key")["sales"].sum().clip(lower=0).sort_values(ascending=False)
    total = float(sales.sum())
    if total <= 0:
        return 0.0, 0.0
    cum = sales.cumsum() / total
    share_a = float(sales[cum <= 0.80].sum() / total)
    share_c = float(sales[cum > 0.95].sum() / total)
    return share_a, share_c


def recommended_service_level(period: str, params: dict, orders: pd.DataFrame | None = None, used_default: bool = True) -> ServiceRecommendation:
    margin = 1.0 - float(params.get("margin", {}).get("hpp_pct_harga", 80)) / 100.0
    stockout = float(params.get("gudang", {}).get("biaya_kehabisan_pct", 30)) / 100.0
    holding = float(params.get("gudang", {}).get("biaya_simpan_pct_tahun", 20)) / 100.0
    days = PERIOD_DAYS.get(period, 30)
    cu = max(margin, 0.0) + max(stockout, 0.0)
    co = max(holding, 1e-6) * days / 365.0
    ratio = cu / (cu + co) if cu + co > 0 else 0.95
    share_a, share_c = abc_sales_share(orders)
    pct = ratio * 100 + ABC_UP_PP * share_a - ABC_DOWN_PP * share_c
    pct = int(round(min(max(pct, MIN_PCT), MAX_PCT)))
    return ServiceRecommendation(pct, ratio, cu, co, share_a, share_c, used_default)


def safety_impact(stock: pd.DataFrame | None, *, stored_pct: float, rec_pct: float, new_pct: float, hpp_pct: float) -> dict | None:
    """SS baru = SS rekomendasi × z(baru) / z(rekomendasi). Dibaca dari SS hasil analisis terakhir."""
    if stock is None or stock.empty or "safety_stock" not in stock.columns:
        return None
    z_stored = z_value(stored_pct)
    z_rec = z_value(rec_pct)
    if z_stored <= 0 or z_rec <= 0:
        return None
    ss_now = stock["safety_stock"].astype(float).clip(lower=0)
    ss_rec = ss_now * z_rec / z_stored
    ss_new = ss_rec * z_value(new_pct) / z_rec
    qty = stock["pred_qty"].astype(float) if "pred_qty" in stock.columns else pd.Series(0.0, index=stock.index)
    sales = stock["pred_sales"].astype(float) if "pred_sales" in stock.columns else pd.Series(0.0, index=stock.index)
    price = pd.Series(np.where(qty > 0, sales / qty.replace(0, np.nan), 0.0), index=stock.index).fillna(0.0)
    units_rec = float(np.ceil(ss_rec).sum())
    units_new = float(np.ceil(ss_new).sum())
    rp_rec = float((np.ceil(ss_rec) * price).sum())
    rp_new = float((np.ceil(ss_new) * price).sum())
    return {
        "items": int(len(stock)),
        "units_rec": units_rec,
        "units_new": units_new,
        "units_delta": units_new - units_rec,
        "pct_delta": (units_new - units_rec) / units_rec * 100 if units_rec > 0 else 0.0,
        "rp_rec": rp_rec,
        "rp_new": rp_new,
        "rp_delta": rp_new - rp_rec,
        "modal_delta": (rp_new - rp_rec) * hpp_pct / 100.0,
        "risk_new": max(100.0 - float(new_pct), 0.0),
        "risk_rec": max(100.0 - float(rec_pct), 0.0),
    }
