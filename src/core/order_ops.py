"""Pembayaran, berat paket, dan ketepatan kirim per pesanan (dari `instant.order_frame`).

- Metode pembayaran: Metode Pembayaran pada laporan pesanan. Batal belum bayar = batal dengan alasan belum dibayar.
- Berat: Total Berat pesanan (gram → kg), dikelompokkan; produk bulky di toko ini cenderung lebih sering batal.
- Terlambat kirim: Waktu Pengiriman Diatur > Pesanan Harus Dikirimkan Sebelum, hanya pesanan tidak batal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

WEIGHT_BINS = (0, 5, 20, 50, 100, float("inf"))
WEIGHT_LABELS = ("< 5 kg", "5–20 kg", "20–50 kg", "50–100 kg", "≥ 100 kg")
WEEKDAYS = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")


def _group(orders: pd.DataFrame, key: pd.Series, label: str, order: list[str] | None = None) -> pd.DataFrame:
    cols = [label, "Invoice", "Porsi invoice (%)", "% batal", "% batal belum bayar", "Sales bersih", "AOV"]
    if orders is None or orders.empty:
        return pd.DataFrame(columns=cols)
    work = orders.assign(_k=key.values)
    rows = []
    for name, part in work.groupby("_k", sort=False, observed=True):
        net = part.loc[~part["cancelled"] & (part["qty_bersih"] > 0)]
        rows.append({label: str(name), "Invoice": len(part), "% batal": part["cancelled"].mean() * 100, "% batal belum bayar": part["unpaid"].mean() * 100,
                     "Sales bersih": float(part["sales_bersih"].sum()), "AOV": float(part["sales_bersih"].sum() / len(net)) if len(net) else np.nan})
    out = pd.DataFrame(rows)
    out["Porsi invoice (%)"] = out["Invoice"] / out["Invoice"].sum() * 100
    if order:
        out["_o"] = out[label].map({n: i for i, n in enumerate(order)})
        out = out.sort_values("_o").drop(columns="_o")
    else:
        out = out.sort_values("Invoice", ascending=False)
    return out.reset_index(drop=True)[cols]


def payment_table(orders: pd.DataFrame) -> pd.DataFrame:
    if orders is None or orders.empty:
        return _group(orders, pd.Series(dtype=str), "Metode pembayaran")
    return _group(orders, orders["payment_method"], "Metode pembayaran")


def weight_table(orders: pd.DataFrame) -> pd.DataFrame:
    if orders is None or orders.empty:
        return _group(orders, pd.Series(dtype=str), "Berat paket")
    known = orders.loc[orders["weight_kg"].notna()]
    bins = pd.cut(known["weight_kg"], WEIGHT_BINS, labels=WEIGHT_LABELS, right=False)
    out = _group(known, bins.astype(str), "Berat paket", list(WEIGHT_LABELS))
    cargo = known.groupby(bins.astype(str))["layanan"].apply(lambda s: (s == "Hemat Kargo / Trucking").mean() * 100)
    out.insert(3, "Lewat kargo (%)", out["Berat paket"].map(cargo))
    return out


def total_row(orders: pd.DataFrame, label: str, *, weight: bool = False) -> pd.DataFrame:
    """Baris Total dengan rumus yang sama (bukan rata-rata persen per baris): % dihitung dari semua pesanan sekaligus."""
    if orders is None or orders.empty:
        return pd.DataFrame()
    part = orders.loc[orders["weight_kg"].notna()] if weight else orders
    out = _group(part, pd.Series("Total", index=part.index), label)
    if weight and not out.empty:
        out.insert(3, "Lewat kargo (%)", float((part["layanan"] == "Hemat Kargo / Trucking").mean() * 100))
    return out


def shipping_summary(orders: pd.DataFrame) -> dict:
    """Pesanan tidak batal dengan batas kirim: jumlah, terlambat, porsi, median keterlambatan (jam)."""
    if orders is None or orders.empty:
        return {"dinilai": 0, "terlambat": 0, "porsi": np.nan, "median_jam": np.nan}
    part = orders.loc[~orders["cancelled"] & orders["ship_deadline"].notna() & orders["ship_time"].notna()]
    late = part.loc[part["terlambat"]]
    hours = (late["ship_time"] - late["ship_deadline"]).dt.total_seconds() / 3600
    return {"dinilai": len(part), "terlambat": len(late), "porsi": len(late) / len(part) * 100 if len(part) else np.nan,
            "median_jam": float(hours.median()) if len(hours) else np.nan}


def late_by(orders: pd.DataFrame, by: str) -> pd.DataFrame:
    """Keterlambatan kirim per layanan pengiriman (`by="layanan"`) atau hari pesanan dibuat (`by="hari"`)."""
    label = "Layanan" if by == "layanan" else "Hari pesanan"
    cols = [label, "Pesanan dinilai", "Terlambat", "% terlambat"]
    if orders is None or orders.empty:
        return pd.DataFrame(columns=cols)
    part = orders.loc[~orders["cancelled"] & orders["ship_deadline"].notna() & orders["ship_time"].notna()]
    if part.empty:
        return pd.DataFrame(columns=cols)
    key = part["layanan"] if by == "layanan" else part["order_time"].dt.dayofweek.map(dict(enumerate(WEEKDAYS)))
    out = part.groupby(key.values).agg(n=("terlambat", "size"), late=("terlambat", "sum")).reset_index().rename(columns={"index": label})
    out.columns = [label, "Pesanan dinilai", "Terlambat"]
    out["% terlambat"] = out["Terlambat"] / out["Pesanan dinilai"] * 100
    if by == "hari":
        out["_o"] = out[label].map({n: i for i, n in enumerate(WEEKDAYS)})
        return out.sort_values("_o").drop(columns="_o").reset_index(drop=True)[cols]
    return out.sort_values("Pesanan dinilai", ascending=False).reset_index(drop=True)[cols]
