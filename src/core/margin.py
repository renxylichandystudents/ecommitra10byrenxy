"""Margin per unit, harga minimal, dan komponen biaya berperiode (Revisi Final 4F).

Harga jual selalu dari data produk (tanpa input net price terpisah).
  biaya_pct = komisi_pct + layanan_pct + transaksi_pct
  margin    = harga × (1 − biaya_pct) − hpp − packing − iklan_per_unit − voucher − ongkir_penjual
  harga_minimal(m) = (hpp + packing + iklan_per_unit + voucher + ongkir) / (1 − biaya_pct − m), dibulatkan ke atas ke Rp 100
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

COMPONENT_COLUMNS = ("hpp", "komisi_pct", "layanan_pct", "transaksi_pct", "packing", "voucher", "ongkir_penjual")
TEMPLATE_COLUMNS = ("sku", "varian", *COMPONENT_COLUMNS, "berlaku_mulai")
MARGIN_MIN_DEFAULT = 8.0
THIN_MARGIN_PCT = 5.0


@dataclass(frozen=True)
class Components:
    hpp: float = 0.0
    komisi_pct: float = 0.0
    layanan_pct: float = 0.0
    transaksi_pct: float = 0.0
    packing: float = 0.0
    voucher: float = 0.0
    ongkir_penjual: float = 0.0

    @property
    def biaya_pct(self) -> float:
        return (self.komisi_pct + self.layanan_pct + self.transaksi_pct) / 100.0

    @classmethod
    def from_row(cls, row) -> "Components":
        def num(name: str) -> float:
            value = row.get(name) if hasattr(row, "get") else None
            try:
                number = float(value)
            except (TypeError, ValueError):
                return 0.0
            return number if math.isfinite(number) else 0.0

        return cls(**{name: num(name) for name in COMPONENT_COLUMNS})


def unit_margin(harga: float, comp: Components, iklan_per_unit: float = 0.0) -> tuple[float, float]:
    """(margin Rp per unit, margin % dari harga)."""
    harga = float(harga or 0.0)
    margin = harga * (1 - comp.biaya_pct) - comp.hpp - comp.packing - float(iklan_per_unit or 0.0) - comp.voucher - comp.ongkir_penjual
    return margin, (margin / harga * 100.0 if harga > 0 else float("nan"))


def harga_minimal(comp: Components, iklan_per_unit: float = 0.0, margin_pct: float = MARGIN_MIN_DEFAULT) -> float:
    """Harga jual minimal agar margin ≥ margin_pct, dibulatkan ke atas ke Rp 100. NaN bila tidak mungkin."""
    denom = 1 - comp.biaya_pct - margin_pct / 100.0
    if denom <= 0:
        return float("nan")
    base = comp.hpp + comp.packing + float(iklan_per_unit or 0.0) + comp.voucher + comp.ongkir_penjual
    return float(math.ceil(base / denom / 100.0) * 100)


def breakdown(harga: float, comp: Components, iklan_per_unit: float = 0.0) -> pd.DataFrame:
    """Rincian per unit (Rp) untuk SKU terpilih."""
    rows = [
        ("Harga jual", harga),
        ("Komisi", -harga * comp.komisi_pct / 100),
        ("Biaya layanan", -harga * comp.layanan_pct / 100),
        ("Biaya transaksi", -harga * comp.transaksi_pct / 100),
        ("HPP", -comp.hpp),
        ("Packing", -comp.packing),
        ("Iklan per unit", -float(iklan_per_unit or 0.0)),
        ("Voucher", -comp.voucher),
        ("Ongkir penjual", -comp.ongkir_penjual),
    ]
    margin, pct = unit_margin(harga, comp, iklan_per_unit)
    rows.append(("Margin", margin))
    frame = pd.DataFrame(rows, columns=["Komponen", "Rp per unit"])
    frame["% harga"] = frame["Rp per unit"] / harga * 100 if harga else np.nan
    return frame


def normalize_components(frame: pd.DataFrame) -> pd.DataFrame:
    """Rapikan upload template; persen boleh ditulis 8 atau 0,08 (≤ 1 dianggap pecahan)."""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=list(TEMPLATE_COLUMNS))
    work = frame.copy()
    work.columns = [str(c).strip().lower() for c in work.columns]
    for column in TEMPLATE_COLUMNS:
        if column not in work.columns:
            work[column] = "" if column in ("sku", "varian") else np.nan
    work["sku"] = work["sku"].astype(str).str.strip().str.replace(r"\.0+$", "", regex=True)
    work["varian"] = work["varian"].fillna("").astype(str).str.strip().replace({"nan": ""})
    for column in COMPONENT_COLUMNS:
        values = work[column]
        if values.dtype == object:
            values = values.astype(str).str.replace("%", "", regex=False).str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
        work[column] = pd.to_numeric(values, errors="coerce")
    for column in ("komisi_pct", "layanan_pct", "transaksi_pct"):
        small = work[column].notna() & (work[column] <= 1)
        work.loc[small, column] = work.loc[small, column] * 100
    work["berlaku_mulai"] = pd.to_datetime(work["berlaku_mulai"], errors="coerce", dayfirst=True).dt.date
    return work.loc[work["sku"].ne("")][list(TEMPLATE_COLUMNS)]


def effective_components(history: pd.DataFrame, sku: str, varian: str = "", on: date | None = None) -> Components | None:
    """Komponen yang berlaku pada tanggal `on` (baris dengan berlaku_mulai ≤ on < berlaku_selesai)."""
    if history is None or history.empty:
        return None
    part = history.loc[history["sku"].astype(str) == str(sku)]
    if varian and "varian" in part.columns and (part["varian"].astype(str) == varian).any():
        part = part.loc[part["varian"].astype(str) == varian]
    if part.empty:
        return None
    on = on or date.today()
    start = pd.to_datetime(part["berlaku_mulai"], errors="coerce").dt.date
    end = pd.to_datetime(part.get("berlaku_selesai"), errors="coerce").dt.date if "berlaku_selesai" in part.columns else pd.Series([None] * len(part), index=part.index)
    valid = [(s is not None and not pd.isna(s) and s <= on) and (e is None or pd.isna(e) or on < e) for s, e in zip(start, end)]
    chosen = part.loc[valid]
    if chosen.empty:
        return None
    return Components.from_row(chosen.sort_values("berlaku_mulai").iloc[-1])


def close_previous_periods(existing: pd.DataFrame, new_rows: pd.DataFrame) -> pd.DataFrame:
    """Baris baru menutup berlaku_selesai baris lama (sku, varian sama) yang masih terbuka."""
    if existing is None or existing.empty or new_rows is None or new_rows.empty:
        return existing.iloc[0:0] if isinstance(existing, pd.DataFrame) else pd.DataFrame()
    updates = []
    for _, new in new_rows.iterrows():
        mask = (existing["sku"].astype(str) == str(new["sku"])) & (existing["varian"].fillna("").astype(str) == str(new.get("varian", "")))
        if "berlaku_selesai" in existing.columns:
            mask &= existing["berlaku_selesai"].isna()
        start = pd.to_datetime(existing["berlaku_mulai"], errors="coerce").dt.date
        mask &= start < new["berlaku_mulai"]
        for index in existing.index[mask]:
            row = existing.loc[index].to_dict()
            row["berlaku_selesai"] = new["berlaku_mulai"]
            updates.append(row)
    return pd.DataFrame(updates)


def ad_cost_per_unit(ad_per_sku: pd.DataFrame | None, net_qty: pd.Series | None) -> dict[str, float]:
    """Biaya iklan SKU pada periode ÷ QTY bersih SKU pada periode yang sama."""
    if ad_per_sku is None or ad_per_sku.empty or net_qty is None or net_qty.empty:
        return {}
    cost = ad_per_sku.groupby(ad_per_sku["sku"].astype(str))["biaya_iklan"].sum()
    qty = net_qty.groupby(net_qty.index.astype(str)).sum()
    out = {}
    for sku, value in cost.items():
        units = float(qty.get(sku, 0.0))
        if units > 0 and value > 0:
            out[sku] = float(value) / units
    return out


def sku_margin_table(
    products: pd.DataFrame,
    components: pd.DataFrame,
    *,
    iklan_per_unit: dict[str, float] | None = None,
    on: date | None = None,
    margin_min_pct: float = MARGIN_MIN_DEFAULT,
) -> pd.DataFrame:
    """Margin per SKU dengan harga terkini dari data produk (kolom sku, product_name, variation, price)."""
    columns = ["sku", "varian", "harga", "margin", "margin_pct", "harga_minimal", "lengkap", "ada_hpp"]
    if products is None or products.empty or "sku" not in products.columns:
        return pd.DataFrame(columns=columns)
    iklan_per_unit = iklan_per_unit or {}
    rows = []
    work = products.drop_duplicates("sku")
    for _, product in work.iterrows():
        sku = str(product["sku"])
        varian = str(product.get("variation", "") or "")
        harga = float(pd.to_numeric(product.get("price"), errors="coerce") or 0.0)
        comp = effective_components(components, sku, varian, on)
        if comp is None or harga <= 0:
            rows.append({"sku": sku, "varian": varian, "harga": harga, "margin": np.nan, "margin_pct": np.nan, "harga_minimal": np.nan, "lengkap": False, "ada_hpp": False})
            continue
        ad = iklan_per_unit.get(sku, 0.0)
        margin, pct = unit_margin(harga, comp, ad)
        rows.append(
            {
                "sku": sku,
                "varian": varian,
                "harga": harga,
                "margin": margin,
                "margin_pct": pct,
                "harga_minimal": harga_minimal(comp, ad, margin_min_pct),
                "lengkap": all(getattr(comp, name) > 0 for name in ("hpp", "komisi_pct")),
                "ada_hpp": comp.hpp > 0,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def transaction_margins(lines: pd.DataFrame, components: pd.DataFrame, iklan_per_unit: dict[str, float] | None = None) -> pd.DataFrame:
    """Margin per baris transaksi bersih memakai komponen yang berlaku pada tanggal transaksi.

    Harga jual = harga setelah diskon pada baris transaksi itu (harga data produk pada tanggal transaksi).
    """
    if lines is None or lines.empty or components is None or components.empty:
        return pd.DataFrame(columns=["sku", "qty", "margin_unit", "margin_total", "komponen_terbesar"])
    iklan_per_unit = iklan_per_unit or {}
    work = lines[["sku", "order_time", "qty", "sales"]].copy()
    work = work.loc[pd.to_numeric(work["qty"], errors="coerce").fillna(0) > 0]
    work["day"] = pd.to_datetime(work["order_time"], errors="coerce").dt.date
    out = []
    cache: dict[tuple[str, date], Components | None] = {}
    for sku, day, qty, sales in zip(work["sku"].astype(str), work["day"], work["qty"].astype(float), work["sales"].astype(float)):
        key = (sku, day)
        if key not in cache:
            cache[key] = effective_components(components, sku, "", day)
        comp = cache[key]
        if comp is None or qty <= 0:
            continue
        harga = sales / qty
        ad = iklan_per_unit.get(sku, 0.0)
        margin, _pct = unit_margin(harga, comp, ad)
        costs = {
            "Komisi & biaya Shopee": harga * comp.biaya_pct,
            "HPP": comp.hpp,
            "Packing": comp.packing,
            "Iklan": ad,
            "Voucher": comp.voucher,
            "Ongkir penjual": comp.ongkir_penjual,
        }
        out.append({"sku": sku, "qty": qty, "harga": harga, "margin_unit": margin, "margin_total": margin * qty, **costs})
    frame = pd.DataFrame(out)
    if frame.empty:
        return pd.DataFrame(columns=["sku", "qty", "margin_unit", "margin_total"])
    return frame
