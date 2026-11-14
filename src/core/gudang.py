"""Gudang Site 10037 (E-commerce Jakarta): denah, lokasi, data replenishment harian, dan analisa kapasitas.

Sumber:
- Denah & lokasi: dari file LAYOUT_ECOM (sheet "LAY OUT" dan "Location") yang diunggah sekali di menu
  Kapasitas gudang dan disimpan di database aplikasi (tidak disimpan di repositori). Jarang berubah.
- Replenishment: laporan "Replenishment Calculation by Date" dari sistem, diunggah harian. Kolom
  "Pick Locatoin" = lokasi gondola untuk barang Kecil; barang Besar disimpan di racking menurut kategori.
- Stok: data stok Site 10037 yang diunggah di aplikasi (kolom stok di tabel analisa); bila SKU tidak ada,
  memakai Stock On Hand dari replenishment.

Model kapasitas (dinyatakan di layar):
- Gondola: 1 lokasi pick terisi bila dipetakan ke ≥1 SKU (dari Pick Location).
- Racking: tidak ada pemetaan per lokasi, jadi diperkirakan per kategori: SKU Besar yang masih berstok ÷ lokasi rak
  kategori itu (1 SKU ≈ 1 lokasi rak).
"""

from __future__ import annotations

import re
from datetime import date, datetime

import numpy as np
import pandas as pd

SITE = "10037"
SITE_NAME = "E-commerce Jakarta"

# Nama kategori di replenishment ↔ kategori lokasi (penulisan di file layout berbeda-beda).
_CATEGORY_ALIASES = {
    "FLOORING AND WALL": "FLOORING & WALL",
    "DOORS AND WINDOWS": "DOOR AND WINDOWS",
    "HOUSEWARE & HOBBIES": "HOUSEWARE & HOBBIES",
    "HOUSWARE & HOBBIES": "HOUSEWARE & HOBBIES",
    "BUILDING MATERILAL": "BUILDING MATERIAL",
    "PAINT AND SUNDRIES": "PAINT & SUNDRIES",
    "ELECTRICAL AND LIGHTING": "ELECTRICAL",
}

REPL_COLUMNS = {
    "Item No": "sku",
    "Item Name": "nama",
    "Item Category": "kategori",
    "Item Sub Category": "sub_kategori",
    "Spesifikasi Barang": "spesifikasi",
    "Pick Locatoin": "pick_location",
    "Pick Location": "pick_location",
    "Average Sales": "avg_sales",
    "Minimum Stock": "min_stock",
    "Maximum Stock": "max_stock",
    "Reorder Point": "rop",
    "Stock On Hand": "soh",
    "Outstanding PO": "out_po",
    "Outstanding TR": "out_tr",
    "Outstanding TO": "out_to",
    "Outstanding TR from other Store": "out_tr_lain",
    "Over Stock Qty": "over_stock_qty",
    "ABC Class": "abc",
    "Stock Out": "stock_out",
    "Vendor Name": "vendor",
    "Date": "tanggal",
    "Site No": "site",
}
INCOMING = ("out_po", "out_tr", "out_to", "out_tr_lain")  # barang menuju Site 10037: PO, TR, TO, TR dari toko lain
NUMERIC = ("avg_sales", "min_stock", "max_stock", "rop", "soh", "out_po", "out_tr", "out_to", "out_tr_lain", "over_stock_qty")


def norm_sku(value) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\.0+$", "", text)
    return text.lstrip("0") or text


def norm_category(value) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip().upper())
    return _CATEGORY_ALIASES.get(text, text)


# Kolom sel bay → lorong per blok baris pada sheet "LAY OUT" (label R01/R02/GONDOLA di file LAYOUT_ECOM).
_UPPER = (25, 54, {"H": "R01", "J": "R01", "M": "R02", "O": "R02", "R": "R03", "T": "R03", "W": "R04", "Y": "R04"})
_LOWER = (60, 74, {"G": "R01", "H": "G01", "J": "G01", "K": "R01", "L": "R02", "M": "G02", "O": "G02", "P": "R02", "Q": "R03", "R": "G03"})
_THEME_INDEX = ["lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6"]
_BORDER_W = {"thin": 1, "hair": 0.5, "dotted": 1, "dashed": 1, "dashDotDot": 1, "mediumDashDot": 2, "slantDashDot": 2, "mediumDashed": 2,
             "medium": 2, "double": 2.5, "thick": 3}


def _theme_colors(wb) -> dict[str, str]:
    raw = wb.loaded_theme.decode() if isinstance(wb.loaded_theme, bytes) else (wb.loaded_theme or "")
    scheme = re.search(r"<a:clrScheme.*?</a:clrScheme>", raw, re.S)
    return dict(re.findall(r'<a:(\w+)>\s*<a:(?:srgbClr val|sysClr val="\w+" lastClr)="(\w+)"', scheme.group(0))) if scheme else {}


def _tint(hex_rgb: str, tint: float) -> str:
    import colorsys

    r, g, b = (int(hex_rgb[i : i + 2], 16) / 255 for i in (0, 2, 4))
    h, light, sat = colorsys.rgb_to_hls(r, g, b)
    light = light * (1 + tint) if tint < 0 else light * (1 - tint) + tint
    r, g, b = colorsys.hls_to_rgb(h, light, sat)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def _cell_color(color, theme: dict[str, str]) -> str | None:
    if color is None:
        return None
    if color.type == "rgb" and isinstance(color.rgb, str) and color.rgb != "00000000":
        return "#" + color.rgb[-6:].lower()
    if color.type == "theme" and color.theme is not None and color.theme < len(_THEME_INDEX):
        base = theme.get(_THEME_INDEX[color.theme])
        return _tint(base, float(color.tint or 0)) if base else None
    return None


def build_denah(wb) -> dict | None:
    """Sheet "LAY OUT" → geometri sel (ukuran kolom/baris asli), warna, garis, dan kode bay per sel angka."""
    from openpyxl.utils import get_column_letter

    if "LAY OUT" not in wb.sheetnames:
        return None
    ws = wb["LAY OUT"]
    theme = _theme_colors(wb)
    first_col, last_col, first_row, last_row = 5, 29, 1, min(ws.max_row, 100)  # kolom E..AC
    widths, heights = [], []
    for c in range(first_col, last_col + 1):
        dim = ws.column_dimensions.get(get_column_letter(c))
        width = dim.width if dim and dim.width else ws.sheet_format.defaultColWidth or 8.43
        widths.append(round(width * 7 + 5, 1))
    for r in range(first_row, last_row + 1):
        dim = ws.row_dimensions.get(r)
        heights.append(round((dim.height if dim and dim.height else 15.0) * 4 / 3, 1))
    xs, ys = [0.0], [0.0]
    for w in widths:
        xs.append(round(xs[-1] + w, 1))
    for h in heights:
        ys.append(round(ys[-1] + h, 1))
    bays = {}
    for top, bottom, cols in (_UPPER, _LOWER):
        for letter, lorong in cols.items():
            for r in range(top, bottom + 1):
                value = ws[f"{letter}{r}"].value
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    bays[(r, letter)] = f"{lorong}-{int(value):03d}"
    cells = []
    for r in range(first_row, last_row + 1):
        for c in range(first_col, last_col + 1):
            cell = ws.cell(r, c)
            fill = _cell_color(cell.fill.fgColor, theme) if cell.fill and cell.fill.fill_type == "solid" else None
            fill = None if fill == "#ffffff" else fill
            border = []
            for side in ("top", "right", "bottom", "left"):
                spec = getattr(cell.border, side)
                border.append(_BORDER_W.get(spec.style, 0) if spec and spec.style else 0)
            value = cell.value
            text = "" if value is None else (str(int(value)) if isinstance(value, float) and value.is_integer() else str(value))
            letter = get_column_letter(c)
            key = bays.get((r, letter))
            if not (fill or any(border) or text):
                continue
            i, j = c - first_col, r - first_row
            entry = {"x": xs[i], "y": ys[j], "w": widths[i], "h": heights[j], "f": fill, "b": border, "t": text, "k": key}
            # Sel pengisi di kolom bay (warna kategori asli file) → diberi warna netral saat denah diwarnai status.
            if not key and any(top <= r <= bottom and letter in cols for top, bottom, cols in (_UPPER, _LOWER)):
                entry["s"] = 1
            cells.append(entry)
    return {"w": xs[-1], "h": ys[-1], "cells": cells}


def _prepare_locations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["lokasi"] = out["lokasi"].astype(str).str.strip()
    out["area"] = np.where(out["rak"].astype(str).str.upper().str.startswith("G"), "Gondola", "Racking")
    out["lorong_kode"] = out["rak"].astype(str).str.upper().str[0] + out["lorong"].astype(str).str.zfill(2)
    out["bay_kode"] = out["lorong_kode"] + "-" + out["bay"].astype(str).str.zfill(3)
    out["kategori"] = out["kategori"].map(norm_category)
    return out


def parse_location_sheet(raw: pd.DataFrame) -> pd.DataFrame:
    """Sheet "Location" (Rack, Lorong, Bay, Level, Slot, Location, Category) → tabel lokasi."""
    work = raw.iloc[:, :7].copy()
    work.columns = ["rak", "lorong", "bay", "level", "slot", "lokasi", "kategori"]
    work = work.dropna(subset=["lokasi"]).astype(str)
    return _prepare_locations(work)


def parse_replenishment(raw: pd.DataFrame) -> tuple[pd.DataFrame, date | None]:
    """Laporan Replenishment Calculation by Date (baris judul di atas tabel) → satu baris per SKU."""
    header_row = None
    for index in range(min(len(raw), 40)):
        values = [str(v).strip() for v in raw.iloc[index].tolist()]
        if "Item No" in values:
            header_row = index
            break
    if header_row is None:
        raise ValueError("Kolom 'Item No' tidak ditemukan. Unggah laporan Replenishment Calculation by Date dari sistem.")
    table = raw.iloc[header_row + 1 :].copy()
    table.columns = [str(v).strip() for v in raw.iloc[header_row].tolist()]
    table = table.loc[:, [c for c in table.columns if c in REPL_COLUMNS]]
    table = table.rename(columns=REPL_COLUMNS)
    table = table.loc[:, ~table.columns.duplicated()]
    if "sku" not in table.columns:
        raise ValueError("Kolom 'Item No' kosong.")
    table = table.dropna(subset=["sku"])
    table["sku"] = table["sku"].map(norm_sku)
    table = table.loc[table["sku"].ne("") & table["sku"].str.lower().ne("nan")]
    for column in NUMERIC:
        if column in table.columns:
            table[column] = pd.to_numeric(table[column], errors="coerce").fillna(0.0)
        else:
            table[column] = 0.0
    for column in ("nama", "kategori", "sub_kategori", "spesifikasi", "pick_location", "abc", "stock_out", "vendor"):
        table[column] = table[column].fillna("").astype(str).str.strip() if column in table.columns else ""
    table["pick_location"] = table["pick_location"].str.upper().replace({"NAN": "", "NONE": ""})
    table["kategori"] = table["kategori"].map(norm_category)
    snapshot = None
    if "tanggal" in table.columns:
        stamp = pd.to_datetime(table["tanggal"], errors="coerce").dropna()
        snapshot = stamp.max().date() if not stamp.empty else None
    if snapshot is None:
        title = " ".join(str(v) for v in raw.iloc[: header_row].fillna("").to_numpy().ravel())
        found = re.search(r"Replenishment Date:\s*(\d{1,2} \w{3} \d{4})", title)
        if found:
            snapshot = pd.to_datetime(found.group(1), errors="coerce").date()
    sites = sorted({norm_sku(v) for v in table["site"].dropna()} - {"", "nan"}) if "site" in table.columns else []
    table = table.drop(columns=["tanggal", "site"], errors="ignore").drop_duplicates("sku", keep="last").reset_index(drop=True)
    table.attrs["sites"] = sites
    return table, snapshot


MASTER_COLUMNS = ("spesifikasi", "pick_location")


SPESIFIKASI = ("Besar", "Kecil")


def norm_spesifikasi(value) -> str:
    text = str(value or "").strip().lower()
    return {"besar": "Besar", "kecil": "Kecil", "b": "Besar", "k": "Kecil"}.get(text, "")


def norm_location(value) -> str:
    text = str(value or "").strip().upper()
    return "" if text in ("NAN", "NONE", "-") else re.sub(r"\.0+$", "", text)


def master_from_repl(repl: pd.DataFrame) -> pd.DataFrame:
    """Baris master (sku, spesifikasi, pick_location) dari snapshot yang masih membawa kolom definisi tim."""
    cols = ["sku", "spesifikasi", "pick_location"]
    if repl is None or repl.empty:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame({
        "sku": repl["sku"].map(norm_sku),
        "spesifikasi": repl.get("spesifikasi", pd.Series("", index=repl.index)).map(norm_spesifikasi),
        "pick_location": repl.get("pick_location", pd.Series("", index=repl.index)).map(norm_location),
    })
    out = out.loc[out["spesifikasi"].ne("") | out["pick_location"].ne("")]
    return out.drop_duplicates("sku", keep="last").reset_index(drop=True)


def apply_master(repl: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    """Spesifikasi dan Pick Location dari master per SKU (definisi tim); SKU di luar master memakai isi file (bila ada)."""
    out = repl.copy()
    if master is None or master.empty or out.empty:
        return out
    ref = master.assign(sku=master["sku"].map(norm_sku)).drop_duplicates("sku", keep="last").set_index("sku")
    known = out["sku"].isin(ref.index)
    for column in MASTER_COLUMNS:
        current = out[column].fillna("").astype(str) if column in out.columns else pd.Series("", index=out.index)
        out[column] = current.where(~known, out["sku"].map(ref[column]).fillna("").astype(str))
    return out


def incomplete_items(repl: pd.DataFrame) -> pd.DataFrame:
    """SKU yang perlu dilengkapi tim: Spesifikasi kosong, atau barang Kecil tanpa Pick Location."""
    if repl is None or repl.empty:
        return pd.DataFrame(columns=["sku", "nama", "kategori", "spesifikasi", "pick_location", "kurang"])
    spec = repl["spesifikasi"].map(norm_spesifikasi)
    pick = repl["pick_location"].map(norm_location)
    kurang = np.where(spec.eq(""), "Spesifikasi Barang", np.where(spec.eq("Kecil") & pick.eq(""), "Pick Location", ""))
    out = repl.assign(spesifikasi=spec, pick_location=pick, kurang=kurang)
    return out.loc[out["kurang"].ne(""), ["sku", "nama", "kategori", "spesifikasi", "pick_location", "kurang"]].reset_index(drop=True)


def parse_master_upload(raw: pd.DataFrame) -> pd.DataFrame:
    """File isian tim (Item No, Spesifikasi Barang, Pick Location) → sku, spesifikasi, pick_location, spesifikasi_asli."""
    aliases = {
        "item no": "sku", "sku": "sku", "spesifikasi barang": "spesifikasi", "spesifikasi": "spesifikasi",
        "pick location": "pick_location", "pick locatoin": "pick_location",
    }
    header_row = None
    for index in range(min(len(raw), 40)):
        values = [str(v).strip().lower() for v in raw.iloc[index].tolist()]
        if "item no" in values or "sku" in values:
            header_row = index
            break
    if header_row is None:
        raise ValueError("Kolom 'Item No' tidak ditemukan. Pakai template dari tombol Unduh template.")
    table = raw.iloc[header_row + 1 :].copy()
    table.columns = [aliases.get(str(v).strip().lower(), str(v).strip()) for v in raw.iloc[header_row].tolist()]
    table = table.loc[:, ~pd.Index(table.columns).duplicated()]
    if not {"spesifikasi", "pick_location"} & set(table.columns):
        raise ValueError("Kolom 'Spesifikasi Barang' atau 'Pick Location' tidak ditemukan.")
    table = table.dropna(subset=["sku"])
    out = pd.DataFrame({"sku": table["sku"].map(norm_sku)})
    raw_spec = table["spesifikasi"].fillna("").astype(str).str.strip() if "spesifikasi" in table.columns else pd.Series("", index=table.index)
    out["spesifikasi"] = raw_spec.map(norm_spesifikasi)
    out["spesifikasi_asli"] = raw_spec.where(raw_spec.str.lower().ne("nan"), "")
    out["pick_location"] = table["pick_location"].map(norm_location) if "pick_location" in table.columns else ""
    out = out.loc[out["sku"].ne("") & out["sku"].str.lower().ne("nan")]
    return out.drop_duplicates("sku", keep="last").reset_index(drop=True)


def master_problems(master: pd.DataFrame, known_locations: set[str]) -> pd.DataFrame:
    """Baris isian yang tidak bisa dipakai: Spesifikasi bukan Besar/Kecil, atau Pick Location tidak ada di denah."""
    notes = []
    for r in master.itertuples(index=False):
        bad = []
        original = getattr(r, "spesifikasi_asli", r.spesifikasi)
        if original and not r.spesifikasi:
            bad.append(f"Spesifikasi '{original}' bukan Besar/Kecil")
        if r.pick_location and known_locations and r.pick_location not in known_locations:
            bad.append(f"Pick Location {r.pick_location} tidak ada di denah")
        notes.append("; ".join(bad))
    out = master.assign(masalah=notes)
    return out.loc[out["masalah"].ne(""), ["sku", "masalah"]].reset_index(drop=True)


def read_layout_workbook(data) -> dict:
    """File LAYOUT_ECOM atau laporan replenishment (xlsx) → {"denah", "locations", "repl", "snapshot"} (yang ditemukan saja)."""
    from io import BytesIO

    import openpyxl

    out: dict = {"denah": None, "locations": None, "repl": None, "snapshot": None}
    try:
        wb = openpyxl.load_workbook(BytesIO(data), data_only=True)
        out["denah"] = build_denah(wb)
    except Exception:  # noqa: BLE001 - file .xls atau bukan workbook openpyxl: lewati denah
        out["denah"] = None
    book = pd.read_excel(BytesIO(data), sheet_name=None, header=None, dtype=object)
    for name, sheet in book.items():
        if name.strip().lower() == "location" and sheet.shape[1] >= 7:
            head = sheet.iloc[0].astype(str).str.strip().tolist()
            if "Location" in head:
                body = sheet.iloc[1:].copy()
                body.columns = head
                out["locations"] = parse_location_sheet(body)
        if out["repl"] is None:
            try:
                out["repl"], out["snapshot"] = parse_replenishment(sheet)
            except ValueError:
                continue
    return out


# --------------------------------------------------------------------------- analisa


def build_view(
    locations: pd.DataFrame,
    repl: pd.DataFrame,
    *,
    stock: dict[str, float] | None = None,
    names: dict[str, str] | None = None,
    pred_daily: dict[str, float] | None = None,
    price: dict[str, float] | None = None,
    sales: pd.DataFrame | None = None,
) -> dict:
    """Gabungkan lokasi + replenishment + stok 10037 + prediksi aplikasi → tabel SKU, lokasi gondola, kategori, bay.

    sales: hasil `sales_summary` (QTY & omzet 30 hari terakhir dan 30 hari sebelumnya per SKU)."""
    stock = stock or {}
    price = price or {}
    names = names or {}
    pred_daily = pred_daily or {}
    items = repl.copy() if repl is not None else pd.DataFrame(columns=["sku", *NUMERIC])
    if items.empty:
        items = pd.DataFrame(columns=["sku", "nama", "kategori", "spesifikasi", "pick_location", *NUMERIC])
    items["stok"] = [float(stock[s]) if s in stock else float(soh) for s, soh in zip(items["sku"], items["soh"])]
    items["sumber_stok"] = ["Data stok 10037" if s in stock else "SOH replenishment" for s in items["sku"]]
    items["nama"] = [names.get(s) or n for s, n in zip(items["sku"], items["nama"])]
    # SKU tanpa prediksi di analisa = prediksi 0 (analisa hanya menyimpan SKU dengan laju > 0).
    items["pred_30"] = [float(pred_daily.get(s, 0.0)) * 30 if pred_daily else np.nan for s in items["sku"]]
    # Omzet: penjualan 30 hari terakhir, tren vs 30 hari sebelumnya, dan prediksi 30 hari (QTY × harga bersih).
    if sales is not None and not sales.empty:
        joined = sales.reindex(items["sku"])
        items["qty_30"] = joined["q30"].fillna(0.0).to_numpy()
        items["omzet_30"] = joined["s30"].fillna(0.0).to_numpy()
        prev = joined["sprev"].fillna(0.0).to_numpy()
        items["tren_pct"] = np.where(prev > 0, (items["omzet_30"] - prev) / np.where(prev > 0, prev, 1) * 100, np.where(items["omzet_30"] > 0, np.inf, np.nan))
    else:
        items["qty_30"], items["omzet_30"], items["tren_pct"] = np.nan, np.nan, np.nan
    unit_price = [
        float(price[s]) if s in price and price[s] else (float(o) / float(q) if q and q == q and q > 0 else np.nan)
        for s, o, q in zip(items["sku"], items["omzet_30"], items["qty_30"])
    ]
    items["pred_omzet_30"] = (items["pred_30"] * pd.Series(unit_price, index=items.index)).where(items["pred_30"].ne(0), 0.0)
    items["hari_cukup"] = [
        float(st_) / (p / 30) if p == p and p > 0 else np.nan for st_, p in zip(items["stok"], items["pred_30"])
    ]
    # Dampak omzet = prediksi omzet 30 hari (bila ada), selain itu omzet 30 hari terakhir.
    items["dampak_omzet"] = items["pred_omzet_30"].where(items["pred_omzet_30"].notna(), items["omzet_30"]).fillna(0.0)
    known = set(locations["lokasi"])
    items["lokasi_valid"] = items["pick_location"].isin(known)
    loc_cat = locations.set_index("lokasi")["kategori"].to_dict()
    items["kategori_lokasi"] = items["pick_location"].map(loc_cat).fillna("")
    items["status"] = [_item_status(r) for r in items.itertuples(index=False)]
    for column in INCOMING:  # snapshot lama belum punya TO & TR dari toko lain → 0
        items[column] = pd.to_numeric(items[column], errors="coerce").fillna(0.0) if column in items.columns else 0.0
    items["di_jalan"] = items[list(INCOMING)].sum(axis=1)
    items["saran"] = [_item_action(r) for r in items.itertuples(index=False)]

    # Lokasi gondola: SKU yang menempati (bisa >1 per lokasi).
    small = items.loc[items["pick_location"].ne("")]
    occupants = small.groupby("pick_location").agg(
        sku_list=("sku", lambda s: list(s)), n_sku=("sku", "size"), stok=("stok", "sum")
    )
    loc = locations.copy()
    loc = loc.join(occupants, on="lokasi")
    loc["n_sku"] = loc["n_sku"].fillna(0).astype(int)
    loc["stok"] = loc["stok"].fillna(0.0)
    loc["terisi"] = loc["n_sku"] > 0

    # Kategori: lokasi rak/gondola vs SKU besar/kecil.
    rows = []
    for category in sorted(set(loc["kategori"]) | set(items["kategori"].replace("", np.nan).dropna())):
        part_loc = loc.loc[loc["kategori"] == category]
        rack_n = int((part_loc["area"] == "Racking").sum())
        gon = part_loc.loc[part_loc["area"] == "Gondola"]
        gon_n, gon_used = int(len(gon)), int(gon["terisi"].sum())
        part_items = items.loc[items["kategori"] == category]
        big = part_items.loc[part_items["spesifikasi"].str.lower().eq("besar")]
        small_items = part_items.loc[~part_items["spesifikasi"].str.lower().eq("besar")]
        big_stocked = int((big["stok"] > 0).sum())
        rows.append({
            "kategori": category,
            "lokasi_rak": rack_n,
            "sku_besar": int(len(big)),
            "sku_besar_berstok": big_stocked,
            "rak_pct": big_stocked / rack_n * 100 if rack_n else (np.nan if big_stocked == 0 else 999.0),
            "lokasi_gondola": gon_n,
            "gondola_terisi": gon_used,
            "gondola_pct": gon_used / gon_n * 100 if gon_n else np.nan,
            "sku_kecil": int(len(small_items)),
            "kecil_tanpa_lokasi": int((small_items["pick_location"].eq("")).sum()),
            "stok": float(part_items["stok"].sum()),
            "over_unit": float((part_items["stok"] - part_items["max_stock"]).clip(lower=0).where(part_items["max_stock"] > 0, 0).sum()),
            "perlu_replenish": int(part_items["status"].isin(["Kosong", "Hampir habis"]).sum()),
        })
    categories = pd.DataFrame(rows, columns=[
        "kategori", "lokasi_rak", "sku_besar", "sku_besar_berstok", "rak_pct", "lokasi_gondola", "gondola_terisi",
        "gondola_pct", "sku_kecil", "kecil_tanpa_lokasi", "stok", "over_unit", "perlu_replenish",
    ])

    # Bay (untuk denah): ringkasan per bay_kode.
    bay = loc.groupby("bay_kode").agg(
        area=("area", "first"), kategori=("kategori", lambda s: ", ".join(sorted(set(s)))),
        lokasi=("lokasi", "size"), terisi=("terisi", "sum"), stok=("stok", "sum"),
    )
    status_by_loc = small.groupby("pick_location")["status"].agg(list).to_dict()
    bay["masalah"] = [
        sum(1 for l in loc.loc[loc["bay_kode"] == b, "lokasi"] for s in status_by_loc.get(l, []) if s in ("Kosong", "Hampir habis"))
        for b in bay.index
    ]
    cat_rack_pct = categories.set_index("kategori")["rak_pct"].to_dict()
    bay["rak_pct"] = [cat_rack_pct.get(str(k).split(", ")[0], np.nan) for k in bay["kategori"]]
    return {"items": items, "locations": loc, "categories": categories, "bays": bay}


def _item_status(row) -> str:
    stock, max_stock, rop, min_stock = float(row.stok), float(row.max_stock), float(row.rop), float(row.min_stock)
    if stock <= 0:
        return "Kosong"
    if (rop > 0 and stock <= rop) or (min_stock > 0 and stock < min_stock):
        return "Hampir habis"
    if max_stock > 0 and stock > max_stock:
        return "Stok berlebih"
    return "Aman"


def _item_action(row) -> str:
    stock, max_stock = float(row.stok), float(row.max_stock)
    incoming = float(row.di_jalan)
    notes = []
    if row.status in ("Kosong", "Hampir habis"):
        need = max(max_stock - stock - incoming, 0)
        def num(value: float) -> str:
            return f"{value:,.0f}".replace(",", ".")

        on_way = f", {num(incoming)} di jalan" if incoming > 0 else ""
        notes.append(f"Isi ulang ±{num(need)} unit (s.d. Max {num(max_stock)}{on_way})"
                     if need > 0 else f"Tunggu barang di jalan ({num(incoming)} unit)")
    elif row.status == "Stok berlebih":
        notes.append(f"Lebih {stock - max_stock:,.0f} unit: tahan isi / promo".replace(",", "."))
    if str(row.spesifikasi).lower() != "besar" and not row.pick_location:
        notes.append("Barang kecil belum punya lokasi ambil di gondola")
    elif row.pick_location and not row.lokasi_valid:
        notes.append(f"Lokasi {row.pick_location} tidak ada di denah")
    elif row.pick_location and row.kategori_lokasi and row.kategori and row.kategori_lokasi != row.kategori:
        notes.append(f"Lokasi zona {row.kategori_lokasi.title()}, kategori barang {row.kategori.title()}")
    pred = float(row.pred_30) if row.pred_30 == row.pred_30 else np.nan
    if np.isfinite(pred) and max_stock > 0:
        if pred > max_stock * 1.2:
            notes.append(f"Prediksi 30 hr {pred:,.0f} > Max: naikkan Max".replace(",", "."))
        elif pred * 3 < max_stock and max_stock >= 6:
            notes.append(f"Prediksi 30 hr {pred:,.0f} ≪ Max: turunkan Max".replace(",", "."))
    return "; ".join(notes) or "—"


def restock_capacity(repl: pd.DataFrame | None) -> dict | None:
    """Kapasitas pembelian (unit) = Σ ruang kosong sampai batas Max tiap SKU di replenishment Site 10037.

    SKU yang stoknya sudah di atas Max dihitung 0 (tidak mengurangi ruang SKU lain)."""
    if repl is None or repl.empty or "max_stock" not in repl.columns:
        return None
    max_stock = pd.to_numeric(repl["max_stock"], errors="coerce").fillna(0.0)
    soh = pd.to_numeric(repl.get("soh", 0), errors="coerce").fillna(0.0).clip(lower=0)
    has_max = max_stock > 0
    if not has_max.any():
        return None
    room = (max_stock - soh).clip(lower=0).where(has_max, 0.0)
    return {
        "unit": float(room.sum()), "sku": int(has_max.sum()), "sku_ada_ruang": int((room > 0).sum()),
        "max_total": float(max_stock[has_max].sum()), "soh_total": float(soh[has_max].sum()),
    }


def capacity_card(view: dict) -> tuple[str, str]:
    """(nilai, keterangan) untuk kartu Kapasitas gudang di dashboard."""
    loc = view["locations"]
    gon = loc.loc[loc["area"] == "Gondola"]
    cat = view["categories"]
    rack_total = int(cat["lokasi_rak"].sum())
    rack_used = int(np.minimum(cat["sku_besar_berstok"], cat["lokasi_rak"]).sum())
    used = int(gon["terisi"].sum()) + rack_used
    total = int(len(loc))
    pct = used / total * 100 if total else np.nan
    note = f"{used:,} dari {total:,} lokasi · gondola {int(gon['terisi'].sum())}/{len(gon)} · rak ±{rack_used}/{rack_total}".replace(",", ".")
    return (f"{pct:.1f}%".replace(".", ",") if np.isfinite(pct) else "–"), note


def location_of(view: dict | None, sku: str) -> str:
    """Teks lokasi SKU di gudang 10037 untuk dialog analisa."""
    if not view:
        return ""
    items = view["items"]
    row = items.loc[items["sku"] == norm_sku(sku)]
    if row.empty:
        return ""
    r = row.iloc[0]
    where = f"pick {r['pick_location']}" if r["pick_location"] else ("racking zona " + str(r["kategori"]).title() if str(r["spesifikasi"]).lower() == "besar" else "belum ada pick location")
    return f"{where} · Min {r['min_stock']:,.0f} / ROP {r['rop']:,.0f} / Max {r['max_stock']:,.0f} · {r['status']}".replace(",", ".")


def snapshot_stamp(value) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    return str(value or "")


def sales_summary(orders: pd.DataFrame | None, days: int = 30) -> pd.DataFrame:
    """Per SKU: QTY & omzet `days` hari terakhir (q30, s30) dan periode sebelumnya (qprev, sprev); pesanan batal dibuang."""
    columns = ["q30", "s30", "qprev", "sprev"]
    if orders is None or orders.empty or not {"sku", "order_time", "qty", "sales"} <= set(orders.columns):
        return pd.DataFrame(columns=columns)
    work = orders
    if "status" in work.columns:
        from src.ingest import cancelled_status_mask

        work = work.loc[~cancelled_status_mask(work["status"])]
    stamp = pd.to_datetime(work["order_time"], errors="coerce").dt.normalize()
    if stamp.dropna().empty:
        return pd.DataFrame(columns=columns)
    end = stamp.max()
    lo = end - pd.Timedelta(days=days - 1)
    prev_lo = lo - pd.Timedelta(days=days)
    frame = pd.DataFrame({
        "sku": work["sku"].map(norm_sku), "d": stamp,
        "q": pd.to_numeric(work["qty"], errors="coerce").fillna(0.0), "s": pd.to_numeric(work["sales"], errors="coerce").fillna(0.0),
    })
    now = frame.loc[frame["d"] >= lo].groupby("sku")[["q", "s"]].sum().rename(columns={"q": "q30", "s": "s30"})
    before = frame.loc[(frame["d"] >= prev_lo) & (frame["d"] < lo)].groupby("sku")[["q", "s"]].sum().rename(columns={"q": "qprev", "s": "sprev"})
    out = now.join(before, how="outer").fillna(0.0)
    out.attrs["end"] = end.date()
    return out[columns]
