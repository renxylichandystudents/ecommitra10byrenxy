"""Saran harga ongkir per Area Provinsi Shopee (template 3 kolom).

## Rumus (setelah perbaikan berat + volume metrik)

1. **Biaya ongkir transaksi** per No. Pesanan:
   `Perkiraan Ongkos Kirim`, atau bila kosong `Ongkos Kirim Dibayar Pembeli + Estimasi Potongan Biaya Pengiriman`.
2. **Berat aktual** (kg): kolom `Total Berat` laporan (gram → kg).
3. **Berat volumetrik** (kg), bila ada ukuran paket:
   `(panjang_cm × lebar_cm × tinggi_cm) / 6000` per unit karton (aturan Shopee Reguler / Hemat Kargo),
   dijumlahkan per pesanan (qty × volume unit). Sumber ukuran: kolom dimensi di laporan bila ada,
   atau tabel `carton_dimension` (Setting gudang).
4. **Berat dikenakan (chargeable)** = `max(berat aktual, berat volumetrik)` —
   sama dengan jasa kirim Shopee (memakai yang lebih tinggi). Bila hanya salah satu ada, pakai yang ada.
5. **Dasar saran per kota/kabupaten**:
   - Bila ada berat dikenakan: `median(ongkir / berat_dikenakan) × median(berat_dikenakan)` di kota itu
     (tarif Rp/kg khas × paket khas kota itu — tidak tertarik paket ringan/berat mentah).
   - Bila tidak ada berat: fallback `median(ongkir)` seperti sebelumnya.
6. **Saran** = `round(dasar × 1,15)` bilangan bulat. Ongkir template yang sudah terisi **tidak diganti**.
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import numpy as np
import openpyxl
import pandas as pd

MARKUP = 1.15
# Shopee ID: Reguler & Hemat Kargo memakai (P×L×T cm) / 6000 → kg volumetrik.
VOLUMETRIC_DIVISOR = 6000.0
DEFAULT_TEMPLATE = Path(__file__).resolve().parents[2] / "data" / "Area_Provinsi_Pengiriman_Shopee.xlsx"

# Tiga blok kolom di template Shopee: Provinsi | Area | Ongkir
_BLOCKS = ((1, 2, 3), (5, 6, 7), (9, 10, 11))

_SPACE = re.compile(r"\s+")
_KABUPATEN = re.compile(r"^KABUPATEN\s+", re.IGNORECASE)
_KAB_DOT = re.compile(r"^KAB\.\s*", re.IGNORECASE)
_KOTA_DOT = re.compile(r"^KOTA\.\s*", re.IGNORECASE)
def normalize_area_key(name: str) -> str:
    """Kunci cocok Area template ↔ Kota/Kabupaten transaksi."""
    text = _SPACE.sub(" ", str(name or "").strip().upper())
    if not text or text in {"NAN", "NONE", "TIDAK DIKETAHUI"}:
        return ""
    text = _KABUPATEN.sub("KAB. ", text)
    text = _KAB_DOT.sub("KAB. ", text)
    text = _KOTA_DOT.sub("KOTA ", text)
    return _SPACE.sub(" ", text).strip()


def suggest_price(cost: float) -> int | None:
    """Dasar ongkir × 1,15 → bilangan bulat (None bila biaya tidak valid)."""
    if cost is None or not np.isfinite(cost) or cost < 0:
        return None
    return int(round(float(cost) * MARKUP))


def volumetric_kg(panjang_cm: float, lebar_cm: float, tinggi_cm: float, *, qty: float = 1.0) -> float:
    """Berat volumetrik Shopee (kg) = P×L×T / 6000 × qty."""
    if not all(np.isfinite(v) and v > 0 for v in (panjang_cm, lebar_cm, tinggi_cm)):
        return float("nan")
    units = float(qty) if np.isfinite(qty) and qty > 0 else 1.0
    return (float(panjang_cm) * float(lebar_cm) * float(tinggi_cm) / VOLUMETRIC_DIVISOR) * units


def chargeable_kg(actual_kg: float | None, volumetric: float | None) -> float:
    """Berat dikenakan = max(aktual, volumetrik); NaN bila keduanya kosong."""
    vals = [float(v) for v in (actual_kg, volumetric) if v is not None and np.isfinite(v) and v > 0]
    return max(vals) if vals else float("nan")


def _cell_text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none"} else text


def _ongkir_number(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        number = float(value)
        return number if np.isfinite(number) else None
    text = str(value).strip().replace(" ", "").replace(".", "").replace(",", ".")
    if not text or text.lower() in {"nan", "none", "-", "ongkir"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if np.isfinite(number) else None


def _parse_grams_to_kg(series: pd.Series) -> pd.Series:
    """Total Berat laporan Shopee ID biasanya gram → kg."""
    nums = series.astype(str).str.extract(r"([\d.,]+)")[0].str.replace(",", ".", regex=False)
    grams = pd.to_numeric(nums, errors="coerce")
    return grams / 1000.0


def parse_area_template(source: str | Path | bytes | BinaryIO | None = None) -> pd.DataFrame:
    """Baca template Area Provinsi (3 blok) → baris Provinsi, Area, Ongkir terisi."""
    path_or_bytes = source if source is not None else DEFAULT_TEMPLATE
    if isinstance(path_or_bytes, (str, Path)):
        wb = openpyxl.load_workbook(Path(path_or_bytes), data_only=True)
    elif isinstance(path_or_bytes, bytes):
        wb = openpyxl.load_workbook(BytesIO(path_or_bytes), data_only=True)
    else:
        data = path_or_bytes.read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        wb = openpyxl.load_workbook(BytesIO(data), data_only=True)
    ws = wb.active
    rows: list[dict] = []
    for block_i, (prov_c, area_c, ong_c) in enumerate(_BLOCKS):
        province = ""
        for r in range(2, (ws.max_row or 1) + 1):
            prov_cell = _cell_text(ws.cell(r, prov_c).value)
            if prov_cell and prov_cell.lower() != "provinsi":
                province = prov_cell.upper()
            area = _cell_text(ws.cell(r, area_c).value)
            if not area or area.lower() == "area":
                continue
            existing = _ongkir_number(ws.cell(r, ong_c).value)
            rows.append(
                {
                    "block": block_i,
                    "row": r,
                    "prov_col": prov_c,
                    "area_col": area_c,
                    "ongkir_col": ong_c,
                    "Provinsi": province,
                    "Area": area.strip(),
                    "area_key": normalize_area_key(area),
                    "Ongkir terisi": existing,
                }
            )
    return pd.DataFrame(rows)


def _shipping_cost_series(frame: pd.DataFrame) -> pd.Series:
    """Perkiraan Ongkos Kirim bila ada; jika tidak, ongkir pembeli + potongan pengiriman."""
    estimated = pd.to_numeric(frame.get("estimated_shipping"), errors="coerce")
    buyer = pd.to_numeric(frame.get("buyer_shipping"), errors="coerce").fillna(0)
    rebate = pd.to_numeric(frame.get("shipping_rebate"), errors="coerce").fillna(0)
    fallback = buyer + rebate
    if estimated is None:
        return fallback
    return estimated.where(estimated.notna() & (estimated > 0), fallback)


def _carton_lookup(cartons: pd.DataFrame | None) -> pd.DataFrame:
    """SKU (+varian opsional) → volume unit kg (P×L×T/6000 / isi_per_karton)."""
    empty = pd.DataFrame(columns=["sku", "varian", "vol_unit_kg"])
    if cartons is None or cartons.empty:
        return empty
    need = {"sku", "panjang_cm", "lebar_cm", "tinggi_cm"}
    if not need <= set(cartons.columns):
        return empty
    work = cartons.copy()
    work["sku"] = work["sku"].astype(str).str.strip().str.replace(r"\.0+$", "", regex=True)
    work["varian"] = work["varian"].astype(str).str.strip() if "varian" in work.columns else ""
    isi = pd.to_numeric(work.get("isi_per_karton"), errors="coerce").replace(0, np.nan).fillna(1.0)
    work["vol_unit_kg"] = (
        pd.to_numeric(work["panjang_cm"], errors="coerce")
        * pd.to_numeric(work["lebar_cm"], errors="coerce")
        * pd.to_numeric(work["tinggi_cm"], errors="coerce")
        / VOLUMETRIC_DIVISOR
        / isi
    )
    work = work.loc[work["sku"].ne("") & work["vol_unit_kg"].gt(0)]
    return work[["sku", "varian", "vol_unit_kg"]].drop_duplicates(["sku", "varian"], keep="last")


def _line_volumetric_from_cartons(work: pd.DataFrame, cartons: pd.DataFrame | None) -> pd.Series:
    """Volumetrik per baris SKU dari carton_dimension (kg)."""
    lookup = _carton_lookup(cartons)
    out = pd.Series(np.nan, index=work.index, dtype=float)
    if lookup.empty or "sku" not in work.columns:
        return out
    sku = work["sku"].astype(str).str.strip().str.replace(r"\.0+$", "", regex=True)
    varian = work["variation"].astype(str).str.strip() if "variation" in work.columns else pd.Series("", index=work.index)
    qty = pd.to_numeric(work.get("qty", work.get("gross_qty")), errors="coerce").fillna(1.0).clip(lower=0)
    # Cocokkan SKU+varian dulu, lalu SKU saja (varian kosong di master).
    by_both = lookup.set_index(["sku", "varian"])["vol_unit_kg"]
    by_sku = lookup.drop_duplicates("sku", keep="last").set_index("sku")["vol_unit_kg"]
    keys = list(zip(sku, varian))
    unit = pd.Series([by_both.get(k, np.nan) for k in keys], index=work.index, dtype=float)
    unit = unit.where(unit.notna(), sku.map(by_sku))
    return unit * qty


def _line_volumetric_from_columns(work: pd.DataFrame) -> pd.Series:
    """Volumetrik dari kolom panjang/lebar/tinggi di laporan (bila ada)."""
    from src.ingest import _exact_column

    p = _exact_column(work, ("panjang", "panjang (cm)", "panjang cm", "package length"))
    l = _exact_column(work, ("lebar", "lebar (cm)", "lebar cm", "package width"))
    t = _exact_column(work, ("tinggi", "tinggi (cm)", "tinggi cm", "package height"))
    if not (p and l and t):
        return pd.Series(np.nan, index=work.index, dtype=float)
    if "qty" in work.columns:
        qty_series = pd.to_numeric(work["qty"], errors="coerce").fillna(1.0).clip(lower=0)
    elif "Jumlah" in work.columns:
        qty_series = pd.to_numeric(work["Jumlah"], errors="coerce").fillna(1.0).clip(lower=0)
    else:
        qty_series = pd.Series(1.0, index=work.index)
    return (
        pd.to_numeric(work[p], errors="coerce")
        * pd.to_numeric(work[l], errors="coerce")
        * pd.to_numeric(work[t], errors="coerce")
        / VOLUMETRIC_DIVISOR
        * qty_series
    )


def _weight_kg_series(work: pd.DataFrame, index: pd.Index) -> pd.Series:
    """Total Berat (gram) → kg; atau kolom weight_kg kanonis."""
    if "weight_kg" in work.columns:
        return pd.to_numeric(work.loc[index, "weight_kg"], errors="coerce")
    from src.ingest import _exact_column

    col = _exact_column(work, ("total berat", "total weight", "total weight per order", "berat total"))
    if not col:
        return pd.Series(np.nan, index=index, dtype=float)
    return _parse_grams_to_kg(work.loc[index, col])


def order_shipping_lines(
    source: pd.DataFrame,
    *,
    cartons: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Satu baris per No. Pesanan: ongkir, berat aktual/volumetrik/dikenakan, dasar saran."""
    cols = [
        "order_id",
        "province",
        "city",
        "area_key",
        "shipping",
        "actual_kg",
        "volumetric_kg",
        "chargeable_kg",
        "rate_per_kg",
        "basis",
        "method",
    ]
    empty = pd.DataFrame(columns=cols)
    if source is None or source.empty:
        return empty

    work = source.drop(columns=["Nama file"], errors="ignore").copy()
    work.columns = [str(c).strip() for c in work.columns]

    cleaned = {"city", "order_id"} <= set(work.columns) and (
        "estimated_shipping" in work.columns
        or "buyer_shipping" in work.columns
        or "shipping_rebate" in work.columns
    )

    if cleaned:
        frame = pd.DataFrame(
            {
                "order_id": work["order_id"].astype(str).str.strip(),
                "province": work["province"].astype(str).str.strip().str.upper()
                if "province" in work.columns
                else "",
                "city": work["city"].astype(str).str.strip().str.upper(),
            },
            index=work.index,
        )
        if "sku" in work.columns:
            frame["sku"] = work["sku"]
        if "variation" in work.columns:
            frame["variation"] = work["variation"]
        if "qty" in work.columns or "gross_qty" in work.columns:
            frame["qty"] = pd.to_numeric(work.get("qty", work.get("gross_qty")), errors="coerce")
        frame["shipping"] = _shipping_cost_series(work)
        ship_agg = "sum"
        frame["_vol"] = _line_volumetric_from_cartons(work, cartons) if "sku" in work.columns else np.nan
        frame["_vol_report"] = _line_volumetric_from_columns(work)
        frame["actual_kg"] = _weight_kg_series(work, frame.index)
    else:
        ship_agg = "max"
        from src.ingest import (
            _exact_column,
            _parse_datetime,
            _parse_money,
            cancel_only_mask,
            clean_sku_series,
            clean_text_series,
            map_columns,
            normalize_status_series,
            open_unpaid_mask,
            _parse_number,
        )

        try:
            mapping = map_columns(work)
        except ValueError:
            return empty
        if "order_id" not in mapping or not ({"city", "province"} & set(mapping)):
            return empty
        frame = pd.DataFrame(index=work.index)
        frame["order_id"] = clean_text_series(work[mapping["order_id"]])
        frame["province"] = (
            clean_text_series(work[mapping["province"]]).str.upper() if "province" in mapping else ""
        )
        frame["city"] = clean_text_series(work[mapping["city"]]).str.upper() if "city" in mapping else ""
        if "order_time" in mapping:
            stamp = _parse_datetime(work[mapping["order_time"]])
            frame = frame.loc[stamp.notna()].copy()
        if "status" in mapping:
            status = normalize_status_series(work[mapping["status"]])
            drop = cancel_only_mask(status) | open_unpaid_mask(status)
            frame = frame.loc[~drop.reindex(frame.index).fillna(False)].copy()

        est_col = _exact_column(work, ("perkiraan ongkos kirim",))
        buy_col = _exact_column(
            work, ("ongkos kirim dibayar oleh pembeli", "ongkos kirim dibayar pembeli")
        )
        reb_col = _exact_column(work, ("estimasi potongan biaya pengiriman",))
        estimated = (
            _parse_money(work.loc[frame.index, est_col]).fillna(0).clip(lower=0)
            if est_col
            else pd.Series(0.0, index=frame.index)
        )
        buyer = (
            _parse_money(work.loc[frame.index, buy_col]).fillna(0).clip(lower=0)
            if buy_col
            else pd.Series(0.0, index=frame.index)
        )
        rebate = (
            _parse_money(work.loc[frame.index, reb_col]).fillna(0).clip(lower=0)
            if reb_col
            else pd.Series(0.0, index=frame.index)
        )
        frame["shipping"] = estimated.where(estimated > 0, buyer + rebate)
        frame["actual_kg"] = _weight_kg_series(work, frame.index)
        if "sku" in mapping:
            frame["sku"] = clean_sku_series(work.loc[frame.index, mapping["sku"]])
        if "variation" in mapping:
            frame["variation"] = clean_text_series(work.loc[frame.index, mapping["variation"]])
        if "qty" in mapping:
            frame["qty"] = _parse_number(work.loc[frame.index, mapping["qty"]]).fillna(1.0)
        # Volumetrik: laporan dulu, lalu carton_dimension.
        frame["_vol_report"] = _line_volumetric_from_columns(work.loc[frame.index])
        carton_src = frame.copy()
        if "sku" in frame.columns:
            carton_src["sku"] = frame["sku"]
        frame["_vol"] = _line_volumetric_from_cartons(carton_src, cartons) if "sku" in frame.columns else np.nan

    frame = frame.loc[frame["order_id"].ne("") & frame["city"].astype(str).ne("")].copy()
    frame["city"] = frame["city"].replace({"NAN": "", "NONE": ""})
    frame = frame.loc[frame["city"].ne("")].copy()
    if frame.empty:
        return empty

    vol_line = pd.to_numeric(frame.get("_vol"), errors="coerce")
    vol_rep = pd.to_numeric(frame.get("_vol_report"), errors="coerce")
    frame["_vol_line"] = vol_line.where(vol_line.notna() & (vol_line > 0), vol_rep)

    # Agregasi pesanan: ongkir & berat aktual level pesanan; volumetrik = jumlah baris.
    agg = {
        "province": ("province", "first"),
        "city": ("city", "first"),
        "shipping": ("shipping", ship_agg),
        "actual_kg": ("actual_kg", "max"),
        "volumetric_kg": ("_vol_line", "sum"),
    }
    per_order = frame.groupby("order_id", sort=False).agg(**agg).reset_index()
    per_order = per_order.loc[per_order["shipping"].fillna(0) > 0].copy()
    if per_order.empty:
        return empty

    per_order["chargeable_kg"] = [
        chargeable_kg(a, v) for a, v in zip(per_order["actual_kg"], per_order["volumetric_kg"])
    ]
    per_order["chargeable_kg"] = pd.to_numeric(per_order["chargeable_kg"], errors="coerce")
    has_w = per_order["chargeable_kg"].notna() & (per_order["chargeable_kg"] > 0)
    per_order["rate_per_kg"] = np.where(has_w, per_order["shipping"] / per_order["chargeable_kg"], np.nan)
    # Dasar per pesanan: bila ada berat → tarif×berat ( = ongkir ); dipakai untuk median rate×median kg di kota.
    per_order["basis"] = per_order["shipping"].astype(float)
    per_order["method"] = np.where(has_w, "berat_dikenakan", "ongkir_saja")
    per_order["area_key"] = per_order["city"].map(normalize_area_key)
    per_order = per_order.loc[per_order["area_key"].ne("")].copy()
    return per_order[cols]


def order_shipping_by_city(
    source: pd.DataFrame,
    *,
    cartons: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Satu baris per kota/kabupaten: dasar saran (sadar berat dikenakan) + statistik berat."""
    empty = pd.DataFrame(
        columns=[
            "area_key",
            "Provinsi",
            "Kota/Kabupaten",
            "Ongkir median",
            "Invoice",
            "Berat dikenakan median (kg)",
            "Rp per kg median",
            "Metode",
        ]
    )
    lines = order_shipping_lines(source, cartons=cartons)
    if lines.empty:
        return empty

    rows = []
    for key, part in lines.groupby("area_key", sort=False):
        weighed = part.loc[part["method"].eq("berat_dikenakan")]
        if len(weighed) >= 1:
            rate = float(weighed["rate_per_kg"].median())
            kg = float(weighed["chargeable_kg"].median())
            base = rate * kg
            method = "berat_dikenakan"
            invoice = int(weighed["order_id"].nunique())
        else:
            base = float(part["shipping"].median())
            rate = float("nan")
            kg = float("nan")
            method = "ongkir_saja"
            invoice = int(part["order_id"].nunique())
        rows.append(
            {
                "area_key": key,
                "Provinsi": part["province"].iloc[0],
                "Kota/Kabupaten": part["city"].iloc[0],
                "Ongkir median": base,
                "Invoice": invoice,
                "Berat dikenakan median (kg)": kg,
                "Rp per kg median": rate,
                "Metode": method,
            }
        )
    return pd.DataFrame(rows)


def build_suggestions(
    template: pd.DataFrame,
    shipping: pd.DataFrame,
) -> pd.DataFrame:
    """Gabung template + dasar transaksi. Ongkir terisi dipertahankan; sisanya saran +15%."""
    if template is None or template.empty:
        return pd.DataFrame(
            columns=[
                "Provinsi",
                "Area",
                "Ongkir terisi",
                "Ongkir median transaksi",
                "Berat dikenakan median (kg)",
                "Rp per kg median",
                "Metode",
                "Saran ongkir",
                "Ongkir usulan",
                "Status",
                "Invoice",
                "area_key",
                "block",
                "row",
                "ongkir_col",
            ]
        )
    ship = shipping.copy() if isinstance(shipping, pd.DataFrame) else pd.DataFrame()
    if ship.empty:
        ship = pd.DataFrame(
            columns=["area_key", "Ongkir median", "Invoice", "Berat dikenakan median (kg)", "Rp per kg median", "Metode"]
        )
    lookup = ship.set_index("area_key") if "area_key" in ship.columns else ship

    out = template.copy()
    median = out["area_key"].map(lookup["Ongkir median"] if "Ongkir median" in lookup.columns else {})
    invoices = out["area_key"].map(lookup["Invoice"] if "Invoice" in lookup.columns else {})
    out["Ongkir median transaksi"] = pd.to_numeric(median, errors="coerce")
    out["Invoice"] = pd.to_numeric(invoices, errors="coerce").fillna(0).astype(int)
    for col in ("Berat dikenakan median (kg)", "Rp per kg median"):
        out[col] = pd.to_numeric(
            out["area_key"].map(lookup[col] if col in lookup.columns else {}),
            errors="coerce",
        )
    out["Metode"] = out["area_key"].map(lookup["Metode"] if "Metode" in lookup.columns else {}).fillna("")
    out["Saran ongkir"] = out["Ongkir median transaksi"].map(
        lambda v: suggest_price(v) if pd.notna(v) else None
    )

    filled = pd.to_numeric(out["Ongkir terisi"], errors="coerce")
    saran = out["Saran ongkir"]
    usulan = []
    status = []
    for exist, tip in zip(filled, saran):
        if pd.notna(exist):
            usulan.append(int(round(float(exist))))
            status.append("Tetap (sudah diisi)")
        elif tip is not None and pd.notna(tip):
            usulan.append(int(tip))
            status.append("Saran dari transaksi")
        else:
            usulan.append(None)
            status.append("Belum ada data transaksi")
    out["Ongkir usulan"] = pd.Series(usulan, dtype=object)
    out["Saran ongkir"] = pd.Series(list(out["Saran ongkir"]), dtype=object)
    out["Status"] = status
    return out


def export_area_excel(
    suggestions: pd.DataFrame,
    *,
    template_source: str | Path | bytes | BinaryIO | None = None,
) -> bytes:
    """Excel layout sama dengan template: isi Ongkir kosong dengan saran; yang terisi tidak diubah."""
    path_or_bytes = template_source if template_source is not None else DEFAULT_TEMPLATE
    if isinstance(path_or_bytes, (str, Path)):
        wb = openpyxl.load_workbook(Path(path_or_bytes))
    elif isinstance(path_or_bytes, bytes):
        wb = openpyxl.load_workbook(BytesIO(path_or_bytes))
    else:
        data = path_or_bytes.read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        wb = openpyxl.load_workbook(BytesIO(data))
    ws = wb.active

    for _, row in suggestions.iterrows():
        if str(row.get("Status") or "") != "Saran dari transaksi":
            continue
        value = row.get("Ongkir usulan")
        if value is None or (isinstance(value, float) and not np.isfinite(value)):
            continue
        r = int(row["row"])
        c = int(row["ongkir_col"])
        current = _ongkir_number(ws.cell(r, c).value)
        if current is not None:
            continue
        ws.cell(r, c).value = int(value)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def summary_counts(suggestions: pd.DataFrame) -> dict[str, int]:
    """Ringkas untuk kartu UI."""
    if suggestions is None or suggestions.empty:
        return {"total": 0, "tetap": 0, "saran": 0, "kosong": 0, "pakai_berat": 0}
    status = suggestions["Status"].astype(str)
    metode = suggestions["Metode"].astype(str) if "Metode" in suggestions.columns else pd.Series("", index=suggestions.index)
    return {
        "total": int(len(suggestions)),
        "tetap": int(status.str.startswith("Tetap").sum()),
        "saran": int(status.eq("Saran dari transaksi").sum()),
        "kosong": int(status.eq("Belum ada data transaksi").sum()),
        "pakai_berat": int((status.eq("Saran dari transaksi") & metode.eq("berat_dikenakan")).sum()),
    }
