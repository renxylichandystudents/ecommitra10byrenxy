"""Atribusi laporan iklan Shopee ke SKU.

Aturan:
- Baris ringkasan (Kode Produk kosong/"-": total iklan otomatis, header grup iklan) dibuang
  agar biaya/omzet tidak terhitung dua kali.
- Hanya periode laporan yang diminta; tanpa rentang = bulan laporan iklan terakhir.
- Biaya/omzet satu Kode Produk dibagi ke SKU variannya proporsional sales varian pada periode
  yang sama (sama rata bila belum ada sales), bukan disalin.
- Omzet iklan per SKU dibatasi sales aktual SKU itu: omzet Shopee menghitung semua belanja di
  toko setelah klik iklan, sehingga tanpa batas totalnya bisa melebihi sales toko.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.core.schemas import clean_code

METRICS = {
    "views": "dilihat",
    "clicks": "klik",
    "cost": "biaya_iklan",
    "ad_sales": "omzet_iklan",
    "products_sold": "terjual_iklan",
    "cart_adds": "keranjang",
}
SKU_COLUMNS = ["sku", *METRICS.values(), "omzet_iklan_shopee"]
SUMMARY_CODES = {"", "-", "nan", "none", "null"}


@dataclass
class AdAttribution:
    per_sku: pd.DataFrame
    start: pd.Timestamp | None = None
    end: pd.Timestamp | None = None
    file_cost: float = 0.0
    file_sales: float = 0.0
    unmapped_cost: float = 0.0
    unmapped_codes: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def cost(self) -> float:
        return float(self.per_sku["biaya_iklan"].sum()) if not self.per_sku.empty else 0.0

    @property
    def sales(self) -> float:
        return float(self.per_sku["omzet_iklan"].sum()) if not self.per_sku.empty else 0.0


def _codes(values: pd.Series) -> pd.Series:
    return clean_code(values).fillna("").astype(str).str.strip()


def ad_product_rows(ads_frames: list[pd.DataFrame], *, start=None, end=None) -> tuple[pd.DataFrame, pd.Timestamp | None, pd.Timestamp | None]:
    """Baris iklan level produk pada rentang periode laporan. Mengembalikan (rows, start, end)."""
    frames = [f for f in ads_frames if isinstance(f, pd.DataFrame) and not f.empty and "product_code" in f.columns]
    if not frames:
        return pd.DataFrame(columns=["product_code", *METRICS.values()]), None, None
    ads = pd.concat(frames, ignore_index=True)
    ads["product_code"] = _codes(ads["product_code"])
    ads = ads.loc[~ads["product_code"].str.lower().isin(SUMMARY_CODES)].copy()
    for source, target in METRICS.items():
        ads[target] = pd.to_numeric(ads[source], errors="coerce").fillna(0.0) if source in ads.columns else 0.0
    period = pd.to_datetime(ads["period"], errors="coerce") if "period" in ads.columns else pd.Series(pd.NaT, index=ads.index)
    lo = pd.Timestamp(start).normalize() if start is not None else None
    hi = pd.Timestamp(end).normalize() if end is not None else None
    if period.notna().any():
        if lo is None and hi is None:
            latest = period.max()
            lo = latest.to_period("M").to_timestamp()
            hi = (lo + pd.offsets.MonthEnd(0)).normalize()
        month = period.dt.to_period("M").dt.to_timestamp()
        keep = pd.Series(True, index=ads.index)
        if lo is not None:
            keep &= month >= lo.to_period("M").to_timestamp()
        if hi is not None:
            keep &= month <= hi
        ads = ads.loc[keep.fillna(False)]
    return ads[["product_code", *METRICS.values()]], lo, hi


def _variant_pairs(stock_frame: pd.DataFrame | None) -> pd.DataFrame:
    if stock_frame is None or stock_frame.empty or not {"product_code", "sku"} <= set(stock_frame.columns):
        return pd.DataFrame(columns=["product_code", "sku"])
    stock = stock_frame
    if "_submitted_at" in stock.columns:
        stamp = stock["_submitted_at"].astype(str)
        stock = stock.loc[stamp.eq(stamp.max())]
    pairs = pd.DataFrame({"product_code": _codes(stock["product_code"]), "sku": _codes(stock["sku"])})
    return pairs.loc[pairs["product_code"].ne("") & pairs["sku"].ne("")].drop_duplicates()


def _sku_sales(orders: pd.DataFrame | None, lo, hi) -> pd.DataFrame:
    if orders is None or orders.empty or "sku" not in orders.columns:
        return pd.DataFrame(columns=["sku", "sales_sku", "qty_sku"])
    work = orders
    if "order_time" in work.columns and (lo is not None or hi is not None):
        day = pd.to_datetime(work["order_time"], errors="coerce").dt.normalize()
        keep = pd.Series(True, index=work.index)
        if lo is not None:
            keep &= day >= lo
        if hi is not None:
            keep &= day <= hi
        work = work.loc[keep]
    frame = pd.DataFrame(
        {
            "sku": _codes(work["sku"]),
            "sales_sku": pd.to_numeric(work.get("sales", 0.0), errors="coerce").fillna(0.0),
            "qty_sku": pd.to_numeric(work.get("qty", 0.0), errors="coerce").fillna(0.0),
        }
    )
    return frame.groupby("sku", as_index=False)[["sales_sku", "qty_sku"]].sum()


def attribute_ads(
    ads_frames: list[pd.DataFrame],
    stock_frame: pd.DataFrame | None,
    *,
    orders: pd.DataFrame | None = None,
    start=None,
    end=None,
) -> AdAttribution:
    rows, lo, hi = ad_product_rows(ads_frames, start=start, end=end)
    empty = pd.DataFrame(columns=SKU_COLUMNS)
    if rows.empty:
        return AdAttribution(empty, lo, hi)
    per_code = rows.groupby("product_code", as_index=False)[list(METRICS.values())].sum()
    file_cost = float(per_code["biaya_iklan"].sum())
    file_sales = float(per_code["omzet_iklan"].sum())
    pairs = _variant_pairs(stock_frame)
    if pairs.empty:
        return AdAttribution(empty, lo, hi, file_cost, file_sales, file_cost, int(len(per_code)))
    sales = _sku_sales(orders, lo, hi)
    pairs = pairs.merge(sales, on="sku", how="left")
    for column in ("sales_sku", "qty_sku"):
        pairs[column] = pd.to_numeric(pairs[column], errors="coerce").fillna(0.0)
    code_sales = pairs.groupby("product_code")["sales_sku"].transform("sum")
    code_count = pairs.groupby("product_code")["sku"].transform("count")
    pairs["share"] = np.where(code_sales > 0, pairs["sales_sku"] / code_sales.where(code_sales > 0, 1.0), 1.0 / code_count)
    merged = pairs.merge(per_code, on="product_code", how="inner")
    for column in METRICS.values():
        merged[column] = merged[column] * merged["share"]
    per_sku = merged.groupby("sku", as_index=False).agg(
        **{column: (column, "sum") for column in METRICS.values()},
        sales_sku=("sales_sku", "first"),
        qty_sku=("qty_sku", "first"),
    )
    per_sku["omzet_iklan_shopee"] = per_sku["omzet_iklan"]
    if orders is not None and not orders.empty:
        per_sku["omzet_iklan"] = np.minimum(per_sku["omzet_iklan"], per_sku["sales_sku"])
        per_sku["terjual_iklan"] = np.minimum(per_sku["terjual_iklan"], per_sku["qty_sku"])
    mapped = set(merged["product_code"])
    unmapped = per_code.loc[~per_code["product_code"].isin(mapped)]
    return AdAttribution(
        per_sku[SKU_COLUMNS],
        lo,
        hi,
        file_cost,
        file_sales,
        float(unmapped["biaya_iklan"].sum()),
        int(len(unmapped)),
    )


def ad_validation(result: AdAttribution, total_sales: float) -> tuple[list[str], list[str]]:
    """(peringatan, catatan): peringatan bila angka iklan tidak masuk akal, catatan cara hitung."""
    from src.utils.format import persen, rupiah

    issues: list[str] = []
    notes: list[str] = []
    if result.per_sku.empty:
        return issues, notes
    if total_sales > 0 and result.sales > total_sales + 1:
        issues.append(f"Omzet iklan {rupiah(result.sales)} melebihi total sales periode {rupiah(total_sales)}.")
    share = result.sales / total_sales * 100 if total_sales > 0 else np.nan
    if np.isfinite(share) and share > 100:
        issues.append(f"Porsi sales dari iklan {persen(share)} melebihi 100%.")
    gap = result.file_cost - result.cost
    if abs(gap) > max(1.0, result.file_cost * 0.001):
        issues.append(
            f"Total biaya iklan per SKU {rupiah(result.cost)} belum sama dengan total file {rupiah(result.file_cost)}: "
            f"{rupiah(result.unmapped_cost)} dari {result.unmapped_codes} kode produk belum ada di Data stok."
        )
    raw = float(result.per_sku["omzet_iklan_shopee"].sum())
    if raw > result.sales + 1:
        notes.append(
            f"Omzet iklan versi Shopee {rupiah(raw)} mencakup belanja produk lain setelah klik iklan; "
            f"yang dipakai {rupiah(result.sales)} (dibatasi sales aktual tiap SKU)."
        )
    return issues, notes
