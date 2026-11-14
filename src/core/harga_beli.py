"""File harga beli & bottom price dari tim merchandising (per kuartal, sheet "Marketplace").

Kolom yang dipakai (baris judul dicari otomatis): Category Name, Item No, Item Name, Variasi, Campaign, H.Beli (JBD),
H.Jual (10037), % Promo Offline, H.Jual NETT (10037), Bottom Price (Marketplace), ZONA / AREA BERLAKU, Keterangan.

- Harga beli = modal per unit, belum termasuk PPN. PPN dihitung dari harga jual Shopee (sudah termasuk PPN):
  margin kotor = harga jual − PPN − harga beli. Bila harga beli kosong, aplikasi memakai estimasi dari File margin.
- Bottom price = harga jual paling rendah yang boleh dipakai untuk promo; hanya dipakai untuk Flash sale toko dan Exposure
  media sosial (harga promo tidak boleh di bawahnya).
"""

from __future__ import annotations

import io
import re

import numpy as np
import pandas as pd

from src.core.margin_file import sku_key

COLUMNS = {
    "kategori": ("category name",),
    "sku": ("item no",),
    "nama": ("item name",),
    "variasi": ("variasi",),
    "campaign": ("campaign",),
    "harga_beli": ("h.beli",),
    "harga_jual_offline": ("h.jual (",),
    "promo_offline_pct": ("% promo offline",),
    "harga_jual_nett": ("h.jual nett",),
    "bottom_price": ("bottom price",),
    "zona": ("zona",),
    "keterangan": ("keterangan",),
}
ITEM_COLUMNS = list(COLUMNS)


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _header_row(raw: pd.DataFrame) -> int | None:
    for index in range(min(len(raw), 30)):
        cells = [_norm(v) for v in raw.iloc[index].tolist()]
        if any(c == "item no" for c in cells) and any(c.startswith("h.beli") for c in cells):
            return index
    return None


def _period(raw: pd.DataFrame, header: int) -> str:
    for index in range(header):
        cells = [str(v).strip() for v in raw.iloc[index].tolist() if pd.notna(v) and str(v).strip()]
        if cells and _norm(cells[0]).startswith("periode"):
            rest = [c for c in cells[1:]] or [cells[0].split(":", 1)[-1]]
            return " ".join(rest).strip(" :")
    return ""


def _money(series: pd.Series) -> pd.Series:
    def one(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return np.nan
        if isinstance(v, (int, float, np.number)):
            return float(v)
        text = re.sub(r"[^0-9,.\-]", "", str(v))
        if not text:
            return np.nan
        if text.count(",") == 1 and text.count(".") >= 1:
            text = text.replace(".", "").replace(",", ".")
        elif text.count(",") == 1:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
        try:
            return float(text)
        except ValueError:
            return np.nan

    out = series.map(one).astype(float)
    return out.where(out > 0)


def parse_sheet(raw: pd.DataFrame) -> tuple[pd.DataFrame, str] | None:
    header = _header_row(raw)
    if header is None:
        return None
    names = [_norm(v) for v in raw.iloc[header].tolist()]
    picks: dict[str, int] = {}
    for key, prefixes in COLUMNS.items():
        for i, name in enumerate(names):
            if i in picks.values():
                continue
            if any(name.startswith(p) for p in prefixes):
                if key == "harga_jual_offline" and "nett" in name:
                    continue
                picks[key] = i
                break
    if "sku" not in picks or "harga_beli" not in picks:
        return None
    body = raw.iloc[header + 1:]
    frame = pd.DataFrame({key: body.iloc[:, i].values for key, i in picks.items()})
    for key in ITEM_COLUMNS:
        if key not in frame.columns:
            frame[key] = np.nan
    frame["sku"] = frame["sku"].map(lambda v: sku_key(v) if pd.notna(v) and str(v).strip() else "")
    frame = frame.loc[frame["sku"].str.fullmatch(r"\d+", na=False)]
    for key in ("harga_beli", "harga_jual_offline", "harga_jual_nett", "bottom_price"):
        frame[key] = _money(frame[key])
    frame["promo_offline_pct"] = pd.to_numeric(frame["promo_offline_pct"], errors="coerce")
    for key in ("kategori", "nama", "variasi", "campaign", "zona", "keterangan"):
        frame[key] = frame[key].map(lambda v: "" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v).strip())
    # Satu baris per SKU: bila dobel (mis. beda zona), ambil harga beli terkecil yang terisi & bottom price tertinggi (paling aman).
    frame = (frame.sort_values(["sku", "harga_beli"]).groupby("sku", as_index=False)
             .agg({**{k: "first" for k in ITEM_COLUMNS if k not in ("sku", "bottom_price")}, "bottom_price": "max"}))
    return frame[ITEM_COLUMNS].reset_index(drop=True), _period(raw, header)


def read_workbook(data: bytes) -> dict:
    """{'periode', 'sheet', 'items'} dari sheet Marketplace (atau sheet pertama yang punya kolom Item No & H.Beli)."""
    book = pd.ExcelFile(io.BytesIO(data))
    names = sorted(book.sheet_names, key=lambda n: (_norm(n) != "marketplace", book.sheet_names.index(n)))
    for name in names:
        raw = pd.read_excel(book, name, header=None, dtype=object)
        parsed = parse_sheet(raw)
        if parsed is not None and not parsed[0].empty:
            items, periode = parsed
            return {"periode": periode, "sheet": name, "items": items}
    raise ValueError("Kolom Item No dan H.Beli tidak ditemukan (butuh sheet Marketplace dari file Bottom Price).")


def margin_pct(price: float, cost: float, tax_share: float | None = None) -> float:
    """Margin kotor % dari harga jual Shopee (termasuk PPN) memakai harga beli (belum termasuk PPN)."""
    from src.core.margin_file import DEFAULT_TAX_SHARE

    if not price or price <= 0 or cost is None or not np.isfinite(cost):
        return float("nan")
    share = DEFAULT_TAX_SHARE if tax_share is None else tax_share
    return (price * (1 - share) - cost) / price * 100
