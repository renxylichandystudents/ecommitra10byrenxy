"""Kapasitas gudang dan kedatangan impor (Revisi Final 4G)."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.core.feature_store import IMPORT_STATUSES

LAYOUT_COLUMNS = ("kode_rak", "zona", "panjang_cm", "lebar_cm", "tinggi_cm", "faktor_isi")
CARTON_COLUMNS = ("sku", "varian", "panjang_cm", "lebar_cm", "tinggi_cm", "isi_per_karton")
IMPORT_COLUMNS = ("no_po", "tanggal_catatan", "sku", "varian", "qty", "eta_rencana", "eta_terbaru", "status", "kondisi_barang", "catatan")
CATEGORY_ZONES = (
    ("Saniter", ("kloset", "closet", "wastafel", "shower", "kran", "keran", "urinoir", "bathtub", "jet washer")),
    ("Lem & sealant", ("lem", "sealant", "silicone", "silikon", "epoxy", "perekat")),
    ("Glass block", ("glass block", "glassblock", "kaca")),
    ("Cat & pelapis", ("cat ", "cat-", "pelapis", "waterproof", "plamir", "thinner")),
    ("Keramik & lantai", ("keramik", "granit", "lantai", "nat ")),
    ("Aksesoris", ()),
)


def _numbers(frame: pd.DataFrame, columns) -> pd.DataFrame:
    for column in columns:
        values = frame[column]
        if values.dtype == object:
            values = values.astype(str).str.replace(",", ".", regex=False)
        frame[column] = pd.to_numeric(values, errors="coerce")
    return frame


def normalize_layout(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(baris valid, baris gagal + alasan)."""
    work = frame.copy()
    work.columns = [str(c).strip().lower() for c in work.columns]
    if "faktor_isi" not in work.columns:
        work["faktor_isi"] = 0.85
    missing = [c for c in LAYOUT_COLUMNS if c not in work.columns]
    if missing:
        return pd.DataFrame(columns=list(LAYOUT_COLUMNS)), pd.DataFrame({"baris": ["-"], "alasan": ["Kolom hilang: " + ", ".join(missing)]})
    work = _numbers(work, ("panjang_cm", "lebar_cm", "tinggi_cm", "faktor_isi"))
    work["faktor_isi"] = work["faktor_isi"].fillna(0.85)
    work["kode_rak"] = work["kode_rak"].astype(str).str.strip()
    work["zona"] = work["zona"].astype(str).str.strip()
    bad = work[["panjang_cm", "lebar_cm", "tinggi_cm"]].isna().any(axis=1) | work["kode_rak"].eq("") | work["zona"].eq("")
    bad |= work.duplicated("kode_rak", keep="first")
    errors = pd.DataFrame({"baris": (work.index[bad] + 2).astype(str), "alasan": "Dimensi kosong, kode rak/zona kosong, atau kode rak dobel"})
    return work.loc[~bad, list(LAYOUT_COLUMNS)].reset_index(drop=True), errors


def zone_capacity(layout: pd.DataFrame) -> pd.Series:
    """kapasitas_zona_m3 = Σ (p × l × t / 1e6) × faktor_isi."""
    if layout is None or layout.empty:
        return pd.Series(dtype=float)
    volume = layout["panjang_cm"] * layout["lebar_cm"] * layout["tinggi_cm"] / 1e6 * layout["faktor_isi"]
    return volume.groupby(layout["zona"]).sum()


def unit_volume(cartons: pd.DataFrame) -> dict[str, float]:
    """volume_unit_m3 = (p × l × t karton / 1e6) / isi_per_karton."""
    if cartons is None or cartons.empty:
        return {}
    isi = cartons["isi_per_karton"].replace(0, np.nan).fillna(1.0)
    volume = cartons["panjang_cm"] * cartons["lebar_cm"] * cartons["tinggi_cm"] / 1e6 / isi
    return {str(sku): float(v) for sku, v in zip(cartons["sku"], volume) if np.isfinite(v)}


def zone_for(name: str, zones: list[str]) -> str:
    lower = f" {str(name or '').lower()} "
    for zone, hints in CATEGORY_ZONES:
        if any(hint in lower for hint in hints):
            if not zones or zone in zones:
                return zone
    return "Aksesoris" if not zones or "Aksesoris" in zones else (zones[0] if zones else "Aksesoris")


def zone_usage(table: pd.DataFrame, volumes: dict[str, float], zones: list[str]) -> tuple[pd.Series, pd.DataFrame]:
    """(terpakai per zona m³, SKU tanpa dimensi karton)."""
    if table is None or table.empty:
        return pd.Series(dtype=float), pd.DataFrame(columns=["sku", "Produk"])
    work = table.loc[table.get("ada_data_stok", pd.Series(False, index=table.index)).astype(bool)].copy()
    work["zona"] = [zone_for(name, zones) for name in work["product_name"]]
    work["vol"] = work["sku"].astype(str).map(volumes)
    missing = work.loc[work["vol"].isna() & (work["stok"].fillna(0) > 0), ["sku", "product_name"]].rename(columns={"product_name": "Produk"})
    used = (work["stok"].fillna(0) * work["vol"].fillna(0)).groupby(work["zona"]).sum()
    return used, missing.reset_index(drop=True)


def weekly_projection(
    table: pd.DataFrame,
    volumes: dict[str, float],
    capacity: pd.Series,
    zones: list[str],
    import_po: pd.DataFrame | None,
    today: date,
    weeks: int = 12,
) -> pd.DataFrame:
    """stok_t = stok_0 + Σ inbound (eta_terbaru ≤ t) − Σ prediksi_harian s.d. t, per zona (% kapasitas)."""
    if table is None or table.empty or capacity.empty:
        return pd.DataFrame()
    work = table.loc[table.get("ada_data_stok", pd.Series(False, index=table.index)).astype(bool)].copy()
    work["zona"] = [zone_for(name, zones) for name in work["product_name"]]
    work["vol"] = work["sku"].astype(str).map(volumes).fillna(0.0)
    inbound = pd.DataFrame(columns=["sku", "qty", "eta"])
    if import_po is not None and not import_po.empty:
        inbound = import_po.loc[import_po["status"].astype(str) != "Diterima DC"].copy()
        inbound["eta"] = pd.to_datetime(inbound["eta_terbaru"].fillna(inbound.get("eta_rencana")), errors="coerce").dt.date
    rows = []
    for week in range(weeks + 1):
        day = today + timedelta(days=7 * week)
        stock = (work["stok"].fillna(0) - work["pred_harian"].fillna(0) * 7 * week).clip(lower=0)
        if not inbound.empty:
            arrived = inbound.loc[inbound["eta"].notna() & (inbound["eta"] <= day)].groupby(inbound["sku"].astype(str))["qty"].sum()
            stock = stock + work["sku"].astype(str).map(arrived).fillna(0.0)
        used = (stock * work["vol"]).groupby(work["zona"]).sum()
        for zone, cap in capacity.items():
            rows.append({"minggu": day, "zona": zone, "terpakai_m3": float(used.get(zone, 0.0)), "kapasitas_m3": float(cap), "pct": float(used.get(zone, 0.0)) / float(cap) * 100 if cap > 0 else np.nan})
    return pd.DataFrame(rows)


def capacity_color(pct: float) -> str:
    if pct is None or not np.isfinite(pct):
        return "#94a3b8"
    return "#1d4ed8" if pct < 75 else ("#ea580c" if pct <= 90 else "#dc2626")


def first_full(projection: pd.DataFrame) -> tuple[str, date] | None:
    """Zona pertama penuh = tanggal pertama > 100%."""
    if projection is None or projection.empty:
        return None
    full = projection.loc[projection["pct"] > 100].sort_values("minggu")
    if full.empty:
        return None
    first = full.iloc[0]
    return str(first["zona"]), first["minggu"]


def validate_import_rows(frame: pd.DataFrame, known_skus: set[str], author: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validasi catatan impor: sku ada di data produk, tanggal valid, status baku. author dari login."""
    work = frame.copy()
    work.columns = [str(c).strip().lower() for c in work.columns]
    for column in IMPORT_COLUMNS:
        if column not in work.columns:
            work[column] = ""
    work["sku"] = work["sku"].astype(str).str.strip().str.replace(r"\.0+$", "", regex=True)
    work["no_po"] = work["no_po"].astype(str).str.strip()
    errors, good = [], []
    for index, row in work.iterrows():
        problems = []
        if not row["no_po"] or row["no_po"].lower() == "nan":
            problems.append("no_po kosong")
        if known_skus and row["sku"] not in known_skus:
            problems.append(f"SKU {row['sku']} tidak ada di data produk")
        dates = {}
        for column in ("tanggal_catatan", "eta_rencana", "eta_terbaru"):
            text = str(row[column] or "").strip()
            if not text or text.lower() in {"nan", "nat", "none"}:
                dates[column] = None
                if column == "tanggal_catatan":
                    problems.append("tanggal_catatan kosong")
                continue
            iso = bool(len(text) >= 10 and text[4] == "-")
            parsed = pd.to_datetime(text, errors="coerce", dayfirst=not iso)
            if pd.isna(parsed):
                problems.append(f"{column} bukan tanggal")
            dates[column] = None if pd.isna(parsed) else parsed.date()
        status = str(row["status"] or "").strip()
        if status not in IMPORT_STATUSES:
            problems.append(f"status '{status}' bukan status baku")
        qty = pd.to_numeric(str(row["qty"]).replace(",", "."), errors="coerce")
        if pd.isna(qty) or qty <= 0:
            problems.append("qty tidak valid")
        if problems:
            errors.append({"baris": index + 2, "no_po": row["no_po"], "alasan": "; ".join(problems)})
            continue
        good.append(
            {
                "no_po": row["no_po"],
                "tanggal_catatan": dates["tanggal_catatan"],
                "sku": row["sku"],
                "varian": str(row["varian"] or "").replace("nan", ""),
                "qty": float(qty),
                "eta_rencana": dates["eta_rencana"],
                "eta_terbaru": dates["eta_terbaru"],
                "status": status,
                "kondisi_barang": str(row["kondisi_barang"] or "").replace("nan", ""),
                "catatan": str(row["catatan"] or "").replace("nan", ""),
                "author": author,
            }
        )
    return pd.DataFrame(good), pd.DataFrame(errors, columns=["baris", "no_po", "alasan"])


def actual_lead_times(notes: pd.DataFrame) -> pd.DataFrame:
    """Lead time impor aktual = tanggal Diterima DC − tanggal catatan pertama PO (tanggal PO)."""
    if notes is None or notes.empty:
        return pd.DataFrame(columns=["no_po", "lead_time_hari"])
    work = notes.copy()
    work["tanggal_catatan"] = pd.to_datetime(work["tanggal_catatan"], errors="coerce")
    rows = []
    for po, part in work.groupby("no_po"):
        received = part.loc[part["status"] == "Diterima DC", "tanggal_catatan"]
        if received.empty:
            continue
        rows.append({"no_po": po, "lead_time_hari": int((received.min() - part["tanggal_catatan"].min()).days)})
    return pd.DataFrame(rows, columns=["no_po", "lead_time_hari"])


def lead_time_stats(notes: pd.DataFrame) -> tuple[float, float] | None:
    """(L_rata, L_maks) dari PO yang sudah Diterima DC; None bila belum ada."""
    lead = actual_lead_times(notes)
    lead = lead.loc[lead["lead_time_hari"] > 0]
    if lead.empty:
        return None
    return float(lead["lead_time_hari"].mean()), float(lead["lead_time_hari"].max())


def delay_impact(po: pd.DataFrame, table: pd.DataFrame, today: date) -> pd.DataFrame:
    """hari kosong = max(0, eta_terbaru − tanggal_stok_habis); potensi sales hilang = hari kosong × prediksi sales harian."""
    if po is None or po.empty or table is None or table.empty:
        return pd.DataFrame(columns=["no_po", "sku", "eta_terbaru", "stok_habis", "hari_kosong", "potensi_sales_hilang"])
    lookup = table.drop_duplicates("sku").set_index(table["sku"].astype(str).drop_duplicates())
    rows = []
    for _, row in po.loc[po["status"].astype(str) != "Diterima DC"].iterrows():
        sku = str(row["sku"])
        if sku not in lookup.index:
            continue
        item = lookup.loc[sku]
        daily = float(item.get("pred_harian", 0) or 0)
        stok = float(item.get("stok", 0) or 0) if bool(item.get("ada_data_stok", False)) else 0.0
        habis = today + timedelta(days=int(stok // daily)) if daily > 0 else None
        eta = pd.to_datetime(row.get("eta_terbaru") or row.get("eta_rencana"), errors="coerce")
        eta = None if pd.isna(eta) else eta.date()
        gap = max(0, (eta - habis).days) if eta and habis else 0
        rows.append(
            {
                "no_po": row["no_po"],
                "sku": sku,
                "eta_terbaru": eta,
                "stok_habis": habis,
                "hari_kosong": gap,
                "potensi_sales_hilang": gap * daily * float(item.get("harga_bersih", 0) or 0),
            }
        )
    return pd.DataFrame(rows)


def po_from_notes(notes: pd.DataFrame) -> pd.DataFrame:
    """Status PO terkini dari catatan terbaru per (no_po, sku)."""
    if notes is None or notes.empty:
        return pd.DataFrame(columns=["no_po", "sku", "varian", "qty", "eta_rencana", "eta_terbaru", "status"])
    work = notes.sort_values(["tanggal_catatan", "created_at"] if "created_at" in notes.columns else ["tanggal_catatan"])
    return work.groupby(["no_po", "sku"], as_index=False).last()[["no_po", "sku", "varian", "qty", "eta_rencana", "eta_terbaru", "status"]]
