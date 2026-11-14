"""Rekomendasi harga & promo per SKU agar tetap untung dan bersaing.

Semua biaya (modal/harga beli, potongan Shopee, iklan per unit, affiliate) adalah pengeluaran yang dihitung `shopee_fee.margin`.
- Harga minimal (impas)      = harga jual terendah dengan margin bersih ≥ 0, termasuk iklan per unit sekarang.
- Harga minimal sehat        = harga jual terendah dengan margin bersih ≥ batas acuan (margin rendah) toko.
- Harga jual disarankan      = harga normal sekarang, dinaikkan bila perlu agar tidak rugi DAN setelah promo disarankan margin
                               bersih tetap ≥ batas sehat (min. MIN_PROFIT_PCT).
- Promo historis             = diskon dari harga awal (list price) di transaksi 90 hari terakhir: median diskon pada transaksi
                               yang berpromo, maksimum, dan porsi transaksi berpromo. Dianggap "perlu promo" bila ≥ 20% transaksi berpromo.
- Promo disarankan           = selalu ada (min. MIN_PROMO, maks. MAX_PROMO): kebiasaan promo transaksi bila ≥ 20% transaksi berpromo,
                               selain itu ruang margin sehat (maks. 10%) atau promo minimal; harga normal disesuaikan agar tetap untung.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd

from src.core import shopee_fee as fee

HISTORY_DAYS = 90
MIN_PROMO = 5.0          # promo minimal (%) agar tetap menarik; tidak pernah 0%
MAX_PROMO = 30.0         # batas atas promo dari kebiasaan transaksi
MIN_PROFIT_PCT = 2.0     # margin bersih minimal setelah promo (tetap untung)


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
    # Harga setelah promo terendah: margin sehat (batas margin rendah toko), minimal tetap untung MIN_PROFIT_PCT.
    floor = np.nanmax([fee.min_price(base, MIN_PROFIT_PCT), sehat]) if np.isfinite(sehat) else fee.min_price(base, MIN_PROFIT_PCT)
    if not np.isfinite(floor):
        floor = impas
    normal = float(normal) if normal and np.isfinite(normal) and normal > 0 else float(inp.harga)
    notes: list[str] = []
    # Promo selalu ada (0% tidak menarik): ikuti kebiasaan promo transaksi bila ≥ 20% transaksi berpromo, selain itu ruang sehat
    # (maks. 10%), minimal MIN_PROMO, maksimal MAX_PROMO.
    want = hist_disc if np.isfinite(hist_disc) and hist_disc > 0 and hist_share >= 20 else 0.0
    room_sehat = (1 - sehat / normal) * 100 if np.isfinite(sehat) and normal > 0 else float("nan")
    if want > 0:
        promo, why = want, "sesuai kebiasaan promo transaksi"
    elif np.isfinite(room_sehat) and room_sehat >= MIN_PROMO:
        promo, why = min(room_sehat, 10.0), "ruang promo sehat (tanpa kebiasaan promo)"
    else:
        promo, why = MIN_PROMO, f"promo minimal {MIN_PROMO:.0f}% agar tetap menarik"
    if promo > MAX_PROMO:
        notes.append(f"promo historis {promo:.0f}% dibatasi {MAX_PROMO:.0f}%")
        promo = MAX_PROMO
    promo = float(math.floor(max(promo, MIN_PROMO)))
    # Harga normal disarankan: tidak rugi tanpa promo, dan setelah promo tetap untung dengan margin sehat.
    need = max(impas, floor / (1 - promo / 100)) if np.isfinite(impas) else float("nan")
    suggested = _ceil100(max(normal, need) if np.isfinite(need) else normal)
    if np.isfinite(need) and need > normal:
        notes.append(f"harga normal {_rp(normal)} dinaikkan ke {_rp(suggested)} agar setelah promo {promo:.0f}% margin tetap sehat")
    price_after = _ceil100(suggested * (1 - promo / 100))
    value, pct = fee.margin(replace(base, harga=price_after))
    notes.insert(0, why)
    out.update({"harga_normal": normal, "harga_impas": impas, "harga_sehat": sehat, "harga_disarankan": suggested, "promo_pct": promo,
                "harga_promo": price_after, "margin_promo": value, "margin_promo_pct": pct, "catatan": "; ".join(notes)})
    return out


def _rp(value: float) -> str:
    return "Rp " + f"{value:,.0f}".replace(",", ".") if np.isfinite(value) else "–"
