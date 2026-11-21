"""Saran harga ongkir per Area Provinsi Shopee (template 3 kolom).

Dasar: median ongkir transaksi per kota/kabupaten × 1,15, dibulatkan ke bilangan bulat.
Harga Ongkir yang sudah terisi di template tidak diganti.
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
    """Ongkir transaksi × 1,15 → bilangan bulat (None bila biaya tidak valid)."""
    if cost is None or not np.isfinite(cost) or cost < 0:
        return None
    return int(round(float(cost) * MARKUP))


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


def order_shipping_by_city(source: pd.DataFrame) -> pd.DataFrame:
    """Satu baris per kota/kabupaten: median ongkir transaksi (per No. Pesanan)."""
    empty = pd.DataFrame(columns=["area_key", "Provinsi", "Kota/Kabupaten", "Ongkir median", "Invoice"])
    if source is None or source.empty:
        return empty

    work = source.drop(columns=["Nama file"], errors="ignore").copy()
    work.columns = [str(c).strip() for c in work.columns]

    # Sudah bersih (kolom kanonis) atau laporan mentah Shopee.
    if {"city", "order_id"} <= set(work.columns) and (
        "estimated_shipping" in work.columns
        or "buyer_shipping" in work.columns
        or "shipping_rebate" in work.columns
    ):
        frame = pd.DataFrame(
            {
                "order_id": work["order_id"].astype(str).str.strip(),
                "province": work["province"].astype(str).str.strip().str.upper()
                if "province" in work.columns
                else "",
                "city": work["city"].astype(str).str.strip().str.upper(),
            }
        )
        frame["shipping"] = _shipping_cost_series(work)
        # Kolom ongkir di frame bersih dibagi porsi baris SKU → jumlahkan per pesanan.
        ship_agg = "sum"
    else:
        ship_agg = "max"
        from src.ingest import (
            _parse_datetime,
            _parse_money,
            cancel_only_mask,
            clean_text_series,
            map_columns,
            normalize_status_series,
            open_unpaid_mask,
        )

        try:
            mapping = map_columns(work)
        except ValueError:
            return empty
        if "order_id" not in mapping or not ({"city", "province"} & set(mapping)):
            return empty
        frame = pd.DataFrame()
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

        # Perkiraan Ongkos Kirim / fallback dari kolom exact (hindari tertukar harga).
        from src.ingest import _exact_column

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

    frame = frame.loc[frame["order_id"].ne("") & frame["city"].ne("")].copy()
    frame["city"] = frame["city"].replace({"NAN": "", "NONE": ""})
    frame = frame.loc[frame["city"].ne("")].copy()
    if frame.empty:
        return empty

    # Bersih: jumlah porsi baris = ongkir pesanan. Mentah: kolom diulang Shopee → max.
    per_order = (
        frame.groupby("order_id", sort=False)
        .agg(province=("province", "first"), city=("city", "first"), shipping=("shipping", ship_agg))
        .reset_index()
    )
    per_order = per_order.loc[per_order["shipping"].fillna(0) > 0].copy()
    if per_order.empty:
        return empty

    per_order["area_key"] = per_order["city"].map(normalize_area_key)
    per_order = per_order.loc[per_order["area_key"].ne("")].copy()
    grouped = (
        per_order.groupby("area_key", sort=False)
        .agg(
            **{
                "Provinsi": ("province", "first"),
                "Kota/Kabupaten": ("city", "first"),
                "Ongkir median": ("shipping", "median"),
                "Invoice": ("order_id", "nunique"),
            }
        )
        .reset_index()
    )
    grouped["Ongkir median"] = grouped["Ongkir median"].astype(float)
    return grouped


def build_suggestions(
    template: pd.DataFrame,
    shipping: pd.DataFrame,
) -> pd.DataFrame:
    """Gabung template + median transaksi. Ongkir terisi dipertahankan; sisanya saran +15%."""
    if template is None or template.empty:
        return pd.DataFrame(
            columns=[
                "Provinsi",
                "Area",
                "Ongkir terisi",
                "Ongkir median transaksi",
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
        ship = pd.DataFrame(columns=["area_key", "Ongkir median", "Invoice"])
    lookup = ship.set_index("area_key") if "area_key" in ship.columns else ship

    out = template.copy()
    median = out["area_key"].map(lookup["Ongkir median"] if "Ongkir median" in lookup.columns else {})
    invoices = out["area_key"].map(lookup["Invoice"] if "Invoice" in lookup.columns else {})
    out["Ongkir median transaksi"] = pd.to_numeric(median, errors="coerce")
    out["Invoice"] = pd.to_numeric(invoices, errors="coerce").fillna(0).astype(int)
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

    # Peta (block, row) → usulan hanya untuk sel yang sebelumnya kosong.
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
        return {"total": 0, "tetap": 0, "saran": 0, "kosong": 0}
    status = suggestions["Status"].astype(str)
    return {
        "total": int(len(suggestions)),
        "tetap": int(status.str.startswith("Tetap").sum()),
        "saran": int(status.eq("Saran dari transaksi").sum()),
        "kosong": int(status.eq("Belum ada data transaksi").sum()),
    }
