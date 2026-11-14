"""Rekomendasi harga & promo per SKU agar tetap untung dan bersaing.

Semua biaya (modal/harga beli, potongan Shopee, iklan per unit, affiliate) adalah pengeluaran yang dihitung `shopee_fee.margin`.
- Harga minimal (impas)      = harga jual terendah dengan margin bersih ≥ 0, termasuk iklan per unit sekarang.
- Harga minimal sehat        = harga jual terendah dengan margin bersih ≥ batas acuan (margin rendah) toko.
- Harga jual disarankan      = harga normal sekarang bila sudah ≥ harga impas; bila tidak, naik ke harga impas (tidak rugi).
- Promo historis             = diskon dari harga awal (list price) di transaksi 90 hari terakhir: median diskon pada transaksi
                               yang berpromo, maksimum, dan porsi transaksi berpromo. Dianggap "perlu promo" bila ≥ 20% transaksi berpromo.
- Promo disarankan           = sebesar promo historis (agar tetap bersaing) tetapi tidak membuat harga setelah promo di bawah harga
                               sehat; bila ruang sehat tidak ada, maksimal sampai harga impas (promo tipis); bila tidak ada ruang, 0%.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd

from src.core import shopee_fee as fee

HISTORY_DAYS = 90


def price_history(orders: pd.DataFrame | None, *, days: int = HISTORY_DAYS, ref: date | None = None) -> pd.DataFrame:
    """Per SKU: harga awal terakhir (list price), harga transaksi median & terendah, diskon median & maksimum (%), jumlah transaksi."""
    cols = ["sku", "harga_awal", "harga_median", "harga_terendah", "diskon_median", "diskon_maks", "porsi_promo", "transaksi"]
    if orders is None or orders.empty or not {"list_price", "net_price", "sku", "order_time"} <= set(orders.columns):
        return pd.DataFrame(columns=cols)
    work = orders
    if "status" in work.columns:
        from src.ingest import cancelled_status_mask

        work = work.loc[~cancelled_status_mask(work["status"])]
    stamp = pd.to_datetime(work["order_time"], errors="coerce")
    end = pd.Timestamp(ref) if ref is not None else stamp.max()
    work = work.loc[stamp >= end.normalize() - pd.Timedelta(days=days - 1)].assign(_t=stamp)
    lp = pd.to_numeric(work["list_price"], errors="coerce")
    np_ = pd.to_numeric(work["net_price"], errors="coerce")
    work = work.assign(_lp=lp, _np=np_).loc[(lp > 0) & (np_ > 0)]
    if work.empty:
        return pd.DataFrame(columns=cols)
    work = work.assign(_d=(1 - work["_np"] / work["_lp"]).clip(lower=0) * 100, sku=work["sku"].astype(str))
    last = work.sort_values("_t").groupby("sku")["_lp"].last()
    out = work.groupby("sku").agg(harga_median=("_np", "median"), harga_terendah=("_np", "min"), diskon_maks=("_d", "max"), transaksi=("_np", "size"))
    promo = work.loc[work["_d"] >= 0.5]
    out["diskon_median"] = promo.groupby("sku")["_d"].median()
    out["porsi_promo"] = (promo.groupby("sku").size() / out["transaksi"] * 100).fillna(0.0)
    out["diskon_median"] = out["diskon_median"].fillna(0.0)
    out["harga_awal"] = last
    return out.reset_index()[cols]


def _ceil100(value: float) -> float:
    return float(math.ceil(value / 100.0) * 100) if np.isfinite(value) else float("nan")


def plan(inp: fee.Inputs, *, normal: float, target_pct: float, hist_disc: float = float("nan"), hist_share: float = 100.0,
         known: bool = True) -> dict:
    """Rekomendasi harga & promo satu SKU. inp = kondisi sekarang (harga transaksi, voucher, iklan, modal, potongan Shopee).

    normal = harga awal/normal sekarang (list price). Harga di sini = harga sebelum voucher penjual (voucher sekarang tetap dihitung)."""
    out = {"harga_normal": normal, "harga_impas": np.nan, "harga_sehat": np.nan, "harga_disarankan": np.nan, "promo_pct": np.nan,
           "harga_promo": np.nan, "margin_promo": np.nan, "margin_promo_pct": np.nan, "catatan": ""}
    if not known:
        out["catatan"] = "modal belum diketahui (harga beli/File margin kosong)"
        return out
    base = replace(inp, diskon=0.0)
    impas = fee.min_price(base, 0.0)
    sehat = fee.min_price(base, target_pct) if np.isfinite(target_pct) and target_pct > 0 else impas
    if not np.isfinite(sehat):
        sehat = impas
    normal = float(normal) if normal and np.isfinite(normal) and normal > 0 else float(inp.harga)
    suggested = max(normal, impas) if np.isfinite(impas) else normal
    notes: list[str] = []
    if np.isfinite(impas) and normal < impas:
        notes.append(f"harga normal {_rp(normal)} rugi: naikkan minimal ke {_rp(_ceil100(impas))}"
                     + (f" (margin sehat di {_rp(_ceil100(sehat))})" if np.isfinite(sehat) and sehat > impas else ""))
    suggested = _ceil100(suggested)
    room_sehat = (1 - sehat / suggested) * 100 if np.isfinite(sehat) and suggested > 0 else float("nan")
    room_impas = (1 - impas / suggested) * 100 if np.isfinite(impas) and suggested > 0 else float("nan")
    # Promo historis dianggap kebutuhan bersaing bila ≥ 20% transaksi memakai promo.
    want = hist_disc if np.isfinite(hist_disc) and hist_disc > 0 and hist_share >= 20 else 0.0
    if np.isfinite(room_sehat) and room_sehat >= 1:
        promo = math.floor(min(want, room_sehat)) if want > 0 else math.floor(min(room_sehat, 10.0))
        why = "sesuai promo historis" if want > 0 and want <= room_sehat else ("dibatasi agar margin tetap sehat" if want > 0 else "ruang promo sehat (tanpa histori promo)")
    elif np.isfinite(room_impas) and room_impas >= 1:
        promo = math.floor(min(want, room_impas)) if want > 0 else 0
        why = "promo tipis: margin di bawah batas sehat, hanya sampai impas" if promo > 0 else "tidak disarankan promo (tidak ada ruang margin sehat)"
    else:
        promo, why = 0, "tidak ada ruang promo: harga setelah diskon akan rugi"
    if want > 0 and promo < want - 5:
        notes.append(f"promo historis {want:.0f}% lebih dalam dari ruang margin: penjualan bisa turun bila promo dikurangi")
    price_after = _ceil100(suggested * (1 - promo / 100))
    value, pct = fee.margin(replace(base, harga=price_after))
    notes.insert(0, why)
    out.update({"harga_normal": normal, "harga_impas": impas, "harga_sehat": sehat, "harga_disarankan": suggested, "promo_pct": float(promo),
                "harga_promo": price_after, "margin_promo": value, "margin_promo_pct": pct, "catatan": "; ".join(notes)})
    return out


def _rp(value: float) -> str:
    return "Rp " + f"{value:,.0f}".replace(",", ".") if np.isfinite(value) else "–"
