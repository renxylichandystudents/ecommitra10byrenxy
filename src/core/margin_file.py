"""File margin dari sistem (Margin Nasional & Margin Shopee) → margin kotor per SKU.

File berisi per Item Code: Sales Include Tax, Sales Exclude Tax, Gross Margin Value, Gross Margin (%, pecahan dari
Sales Exclude Tax). Dihasilkan dari penjualan yang terjadi, jadi dipakai sebagai acuan estimasi (bukan HPP resmi).

Dasar hitung di aplikasi = harga jual akhir di Shopee (sudah termasuk pajak), karena potongan Shopee dihitung dari harga itu:
  margin kotor % (harga jual) = Gross Margin Value ÷ Sales Include Tax
  porsi pajak dalam harga       = 1 − Sales Exclude Tax ÷ Sales Include Tax
  modal per unit (estimasi)     = harga akhir × (1 − porsi pajak − margin kotor %)
  margin bersih                 = margin kotor − potongan Shopee − komisi affiliate − iklan
Sumber per SKU: sheet Shopee → bila tidak ada / tidak wajar, sheet Nasional → bila tidak ada, rata-rata toko.
"""

from __future__ import annotations

import io
import re

import numpy as np
import pandas as pd

ID_MONTHS = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember")
SOURCES = {"shopee": "Shopee", "nasional": "Nasional"}
PLAUSIBLE = (-100.0, 95.0)  # margin kotor % di luar rentang ini dianggap data tidak wajar (retur/penyesuaian)
DEFAULT_TAX_SHARE = 1 - 1 / 1.1
LEVELS = ("Rugi", "Rendah", "Tinggi", "Tanpa data")


def sku_key(value) -> str:
    """Kode item tanpa nol di depan & tanpa ".0" (SKU Shopee "0200012180" = "200012180")."""
    text = str(value if value is not None else "").strip()
    text = re.sub(r"\.0+$", "", text)
    return text.lstrip("0") or text


def _find(raw: pd.DataFrame, label: str) -> int | None:
    for index in range(min(len(raw), 15)):
        if str(raw.iloc[index, 0]).strip().lower() == label.lower():
            return index
    return None


def _period_hint(raws: list[pd.DataFrame]) -> str:
    """Label periode dari baris 'Year - Month - Date' (mis. 10 → Oktober, 2026 → tahun)."""
    month = year = None
    for raw in raws:
        row = _find(raw, "Year - Month - Date")
        if row is None:
            continue
        value = str(raw.iloc[row, 1]).strip().replace(".0", "")
        if value.isdigit():
            number = int(value)
            if 1 <= number <= 12:
                month = number
            elif 2000 <= number <= 2100:
                year = number
    if month and year:
        return f"{ID_MONTHS[month - 1]} {year}"
    if month:
        return ID_MONTHS[month - 1]
    return str(year or "")


def parse_sheet(raw: pd.DataFrame, sheet: str) -> tuple[str, pd.DataFrame, dict] | None:
    """(sumber 'shopee'/'nasional', item, total) dari satu sheet; None bila bukan sheet margin."""
    header = _find(raw, "Item Code")
    if header is None:
        return None
    customer = _find(raw, "Customer Name")
    who = str(raw.iloc[customer, 1]) if customer is not None else ""
    source = "shopee" if "shopee" in (who + " " + sheet).lower() else "nasional"
    table = raw.iloc[header + 1 :].copy()
    table.columns = [str(c).strip() for c in raw.iloc[header].tolist()]
    cols = {c.lower(): c for c in table.columns}

    def col(*names: str) -> str:
        for name in names:
            for key, original in cols.items():
                if key.startswith(name):
                    return original
        raise ValueError(f"Kolom '{names[0]}' tidak ditemukan di sheet {sheet}.")

    code = table[col("item code")].astype(str).str.strip()
    total_mask = code.str.lower().str.contains("total")
    num = lambda c: pd.to_numeric(table[col(c)], errors="coerce").fillna(0.0)  # noqa: E731
    frame = pd.DataFrame({
        "item_code": code, "nama": table[col("item name")].fillna("").astype(str).str.strip(),
        "sales_incl": num("sales include"), "sales_excl": num("sales exclude"), "gm_value": num("gross margin value"),
    })
    total_row = frame.loc[total_mask]
    frame = frame.loc[~total_mask & code.str.fullmatch(r"\d{4,}")]
    frame = frame.loc[(frame["sales_incl"] != 0) | (frame["gm_value"] != 0)].copy()
    frame["sku"] = frame["item_code"].map(sku_key)
    frame = frame.groupby("sku", as_index=False).agg(item_code=("item_code", "first"), nama=("nama", "first"),
                                                     sales_incl=("sales_incl", "sum"), sales_excl=("sales_excl", "sum"), gm_value=("gm_value", "sum"))
    total = {
        "sales_incl": float(total_row["sales_incl"].iloc[0]) if len(total_row) else float(frame["sales_incl"].sum()),
        "sales_excl": float(total_row["sales_excl"].iloc[0]) if len(total_row) else float(frame["sales_excl"].sum()),
        "gm_value": float(total_row["gm_value"].iloc[0]) if len(total_row) else float(frame["gm_value"].sum()),
    }
    return source, frame.reset_index(drop=True), total


def read_margin_workbook(data: bytes) -> dict:
    """{'periode': label usulan, 'sheets': {sumber: {'sheet', 'items', 'total'}}}."""
    book = pd.ExcelFile(io.BytesIO(data))
    raws = {name: pd.read_excel(book, name, header=None, dtype=object) for name in book.sheet_names}
    sheets: dict[str, dict] = {}
    for name, raw in raws.items():
        parsed = parse_sheet(raw, name)
        if parsed is None:
            continue
        source, items, total = parsed
        if source not in sheets or len(items) > len(sheets[source]["items"]):
            sheets[source] = {"sheet": name, "items": items, "total": total}
    if not sheets:
        raise ValueError("Sheet margin tidak ditemukan (butuh kolom Item Code, Sales Include Tax, Sales Exclude Tax, Gross Margin Value).")
    return {"periode": _period_hint(list(raws.values())), "sheets": sheets}


# --------------------------------------------------------------------------- lookup per SKU


def _pct(gm: pd.Series, base: pd.Series) -> pd.Series:
    return (gm / base.where(base > 0)) * 100


def with_pct(items: pd.DataFrame) -> pd.DataFrame:
    """Tambahkan margin_kotor_pct (dari harga termasuk pajak), margin_file_pct (seperti di file), porsi_pajak, wajar."""
    out = items.copy()
    for column in ("sales_incl", "sales_excl", "gm_value"):
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0.0)
    out["margin_file_pct"] = _pct(out["gm_value"], out["sales_excl"])
    out["margin_kotor_pct"] = _pct(out["gm_value"], out["sales_incl"])
    share = 1 - out["sales_excl"] / out["sales_incl"].where(out["sales_incl"] > 0)
    out["porsi_pajak"] = share.where(share.between(0, 0.2), DEFAULT_TAX_SHARE).fillna(DEFAULT_TAX_SHARE)
    out["wajar"] = (out["sales_excl"] > 0) & out["margin_file_pct"].between(*PLAUSIBLE)
    return out


def store_average(items: pd.DataFrame) -> float:
    """Margin kotor toko (% harga termasuk pajak) dari baris yang wajar; NaN bila kosong."""
    if items is None or items.empty:
        return float("nan")
    work = with_pct(items)
    work = work.loc[work["wajar"]]
    sales = float(work["sales_incl"].sum())
    return float(work["gm_value"].sum()) / sales * 100 if sales > 0 else float("nan")


def lookup(shopee: pd.DataFrame | None, nasional: pd.DataFrame | None) -> pd.DataFrame:
    """Satu baris per SKU: margin_kotor_pct, porsi_pajak, sumber ('Shopee'/'Nasional'), margin_nasional_pct, catatan."""
    columns = ["sku", "nama", "margin_kotor_pct", "margin_file_pct", "porsi_pajak", "sumber", "margin_nasional_pct", "catatan"]
    parts = []
    nas = with_pct(nasional) if nasional is not None and not nasional.empty else pd.DataFrame(columns=["sku", "margin_kotor_pct", "wajar"])
    nas_ok = nas.loc[nas["wajar"].astype(bool)].set_index("sku") if not nas.empty else nas.set_index("sku")
    shop = with_pct(shopee) if shopee is not None and not shopee.empty else pd.DataFrame(columns=["sku", "wajar"])
    used: set[str] = set()
    if not shop.empty:
        good = shop.loc[shop["wajar"].astype(bool)]
        part = good.assign(sumber="Shopee", catatan="")
        parts.append(part)
        used |= set(good["sku"])
        odd = shop.loc[~shop["wajar"].astype(bool) & ~shop["sku"].isin(nas_ok.index)]
        if not odd.empty:
            parts.append(odd.assign(sumber="Shopee", catatan="Margin di file tidak wajar, perlu dicek", margin_kotor_pct=np.nan))
            used |= set(odd["sku"])
    if not nas_ok.empty:
        rest = nas_ok.loc[~nas_ok.index.isin(used)].reset_index()
        parts.append(rest.assign(sumber="Nasional", catatan="Tidak ada di sheet Shopee, memakai margin nasional"))
    if not parts:
        return pd.DataFrame(columns=columns)
    out = pd.concat(parts, ignore_index=True)
    out["margin_nasional_pct"] = out["sku"].map(nas_ok["margin_kotor_pct"]) if not nas_ok.empty else np.nan
    return out[columns].drop_duplicates("sku").reset_index(drop=True)


def classify(net_pct: float, acuan_pct: float) -> str:
    """Rugi (< 0) · Rendah (untung, di bawah batas acuan) · Tinggi (≥ batas acuan) · Tanpa data."""
    if net_pct is None or not np.isfinite(net_pct):
        return "Tanpa data"
    if net_pct < 0:
        return "Rugi"
    if np.isfinite(acuan_pct) and net_pct < acuan_pct:
        return "Rendah"
    return "Tinggi"
