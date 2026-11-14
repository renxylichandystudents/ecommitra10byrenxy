"""Bahan kotak Insight Ringkasan: restock bulan berjalan, iklan yang sedang berjalan, dan outstanding PO/TR/TO."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.core.dc_stock import DC_SITES, _clean_sku, transfer_plan
from src.core.inventory import snapshot_time

def month_restock(top: pd.DataFrame) -> dict | None:
    """Restock untuk sisa bulan berjalan per SKU = prediksi sisa bulan (unit utuh) + SS − stok Site 10037, lalu DC → PO."""
    if top is None or top.empty or not {"run_rest_qty", "ss", "stok"} <= set(top.columns):
        return None
    known = top["ada_data_stok"].astype(bool) if "ada_data_stok" in top.columns else top["stok"].notna()
    rest = np.floor(pd.to_numeric(top["run_rest_qty"], errors="coerce").fillna(0.0) + 1e-9)
    need = rest + pd.to_numeric(top["ss"], errors="coerce").fillna(0.0)
    stok = pd.to_numeric(top["stok"], errors="coerce").fillna(0.0)
    gap = np.ceil((need - stok).clip(lower=0)).where(known, 0.0)
    codes = [code for code, _n, _s in DC_SITES]
    from_dc = po = 0.0
    full = partly = po_only = 0
    for idx in gap.index[gap > 0]:
        available = {code: (None if f"stok_{code}" not in top.columns or pd.isna(top.at[idx, f"stok_{code}"]) else float(top.at[idx, f"stok_{code}"]))
                     for code in codes}
        take, remaining = transfer_plan(float(gap.at[idx]), available)
        got = sum(take.values())
        from_dc += got
        po += remaining
        if remaining <= 0:
            full += 1
        elif got > 0:
            partly += 1
        else:
            po_only += 1
    return {
        "prediksi": float(rest.sum()),
        "ss": float(pd.to_numeric(top["ss"], errors="coerce").fillna(0.0).sum()),
        "kurang_sku": int((gap > 0).sum()),
        "restock": float(gap.sum()),
        "dari_dc": from_dc,
        "po": po,
        "dc_penuh": full,
        "dc_sebagian": partly,
        "po_saja": po_only,
        "gap": gap,
    }


def _latest_upload(frame: pd.DataFrame | None, cutoff) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    """Baris unggahan terakhir yang disimpan sebelum cutoff (waktu analisa dijalankan)."""
    if frame is None or frame.empty:
        return pd.DataFrame(), None
    if "_submitted_at" not in frame.columns:
        return frame, None
    stamp = snapshot_time(frame["_submitted_at"].astype(str))
    keep = stamp.notna()
    if cutoff is not None and pd.notna(cutoff):
        keep &= stamp.le(pd.Timestamp(cutoff))
    if not keep.any():
        return pd.DataFrame(), None
    last = stamp.loc[keep].max()
    return frame.loc[keep & stamp.eq(last)].copy(), last


def _running(status) -> bool:
    return "berjalan" in str(status or "").lower()


def running_ads(ads: dict[str, pd.DataFrame], stock: pd.DataFrame | None, cutoff=None) -> dict | None:
    """SKU di iklan yang berstatus Berjalan pada unggahan laporan iklan terakhir sebelum cutoff.

    ads: {"ads_group", "ads_overall", "ads_auto"}. Grup: anggota grup Berjalan; produk tunggal: baris Berjalan di Semua Laporan Iklan;
    otomatis: produk yang berbiaya di laporan iklan otomatis bila iklan otomatis Berjalan (status dari Semua Laporan Iklan).
    """
    from src.core.ads import _variant_pairs
    from src.core.ads_strategy import parse_units

    group, group_at = _latest_upload(ads.get("ads_group"), cutoff)
    overall, overall_at = _latest_upload(ads.get("ads_overall"), cutoff)
    auto, auto_at = _latest_upload(ads.get("ads_auto"), cutoff)
    if group.empty and overall.empty and auto.empty:
        return None
    units, members = parse_units(group if not group.empty else None, overall if not overall.empty else None, None)
    auto_status = "Berjalan"
    if not overall.empty and "Status" in overall.columns:
        name_col = "Nama Iklan" if "Nama Iklan" in overall.columns else "product_name"
        auto_rows = overall.loc[overall[name_col].astype(str).str.lower().str.contains("otomatis")]
        if not auto_rows.empty:
            auto_status = str(auto_rows["Status"].iloc[-1])
    run_units = [u for u in units if _running(u.status) and u.key != "auto"]
    codes: set[str] = set()
    for unit in run_units:
        if not members.empty:
            part = members.loc[members["unit"] == unit.key]
            part = part.loc[part["periode"] == part["periode"].max()] if not part.empty else part
            codes |= set(part["product_code"].astype(str))
        codes |= set(unit.members)
    auto_codes: set[str] = set()
    if not auto.empty and _running(auto_status) and "product_code" in auto.columns:
        code = auto["product_code"].fillna("").astype(str).str.strip()
        cost = pd.to_numeric(auto.get("cost", 0), errors="coerce").fillna(0.0)
        auto_codes = set(code.loc[code.ne("") & code.ne("-") & cost.gt(0)])
    pairs = _variant_pairs(stock)
    to_sku = pairs.groupby("product_code")["sku"].apply(set).to_dict() if not pairs.empty else {}
    skus = {s for c in codes | auto_codes for s in to_sku.get(c, set())}
    stamps = [t for t in (group_at, overall_at, auto_at) if t is not None]
    periods = []
    for frame in (group, overall, auto):
        if not frame.empty and "Periode laporan (teks)" in frame.columns:
            periods += [str(v) for v in frame["Periode laporan (teks)"].dropna().unique()]
    return {
        "skus": skus,
        "grup": sum(1 for u in run_units if u.jenis == "Grup"),
        "tunggal": sum(1 for u in run_units if u.jenis.startswith("Produk tunggal")),
        "otomatis": bool(auto_codes),
        "kode": len(codes | auto_codes),
        "kode_tanpa_sku": len({c for c in codes | auto_codes if c not in to_sku}),
        "diunggah": max(stamps) if stamps else None,
        "periode": sorted(set(periods))[-1] if periods else "",
    }


def outstanding_10037(repl: pd.DataFrame | None) -> pd.DataFrame:
    """Outstanding per SKU dari Replenishment Calculation by Date Site 10037: po, tr, to, tr_toko_lain, masuk (jumlah keempatnya).

    Snapshot lama (sebelum kolom TO & TR dari toko lain disimpan) terbaca 0 untuk kedua kolom itu."""
    columns = ["po", "tr", "to", "tr_toko_lain", "masuk"]
    if repl is None or repl.empty or "sku" not in repl.columns:
        return pd.DataFrame(columns=columns)
    source = {"po": "out_po", "tr": "out_tr", "to": "out_to", "tr_toko_lain": "out_tr_lain"}
    work = pd.DataFrame({"sku": _clean_sku(repl["sku"].astype(str))})
    for name, column in source.items():
        work[name] = pd.to_numeric(repl[column], errors="coerce").fillna(0.0).to_numpy() if column in repl.columns else 0.0
    out = work.loc[work["sku"].ne("")].groupby("sku")[list(source)].sum()
    out["masuk"] = out[list(source)].sum(axis=1)
    return out


def outstanding_text(row) -> str:
    """'PO 10 · TR 5 · TO 2' (hanya yang > 0)."""
    if row is None:
        return ""
    labels = (("po", "PO"), ("tr", "TR"), ("to", "TO"), ("tr_toko_lain", "TR toko lain"))
    parts = [f"{label} {int(round(float(row[name]))):,}".replace(",", ".") for name, label in labels if float(row.get(name, 0) or 0) > 0]
    return " · ".join(parts)


def outstanding_for(skus: list[str], repl_10037: pd.DataFrame | None, repl_date=None) -> dict | None:
    """Outstanding Site 10037 untuk daftar SKU: total per jenis dan per SKU."""
    table = outstanding_10037(repl_10037)
    if table.empty:
        return None
    keys = [_clean_sku(pd.Series([s])).iat[0] for s in skus]
    part = table.reindex(keys).fillna(0.0)
    part.index = list(skus)
    return {
        "tanggal": repl_date,
        "total": {name: float(part[name].sum()) for name in ("po", "tr", "to", "tr_toko_lain", "masuk")},
        "sku_ada": int((part["masuk"] > 0).sum()),
        "per_sku": part,
    }


def po_coverage(need_po: pd.Series, inbound: pd.Series) -> dict:
    """Kebutuhan PO per SKU dibanding barang masuk yang sudah dalam proses (outstanding PO/TR)."""
    need = pd.to_numeric(need_po, errors="coerce").fillna(0.0)
    have = pd.to_numeric(inbound, errors="coerce").fillna(0.0).reindex(need.index).fillna(0.0)
    mask = need > 0
    covered = np.minimum(need, have).where(mask, 0.0)
    return {
        "sku_perlu_po": int(mask.sum()),
        "unit_perlu_po": float(need.where(mask, 0.0).sum()),
        "sku_tertutup": int((mask & (have >= need)).sum()),
        "sku_sebagian": int((mask & (have > 0) & (have < need)).sum()),
        "sku_belum": int((mask & (have <= 0)).sum()),
        "unit_tertutup": float(covered.sum()),
        "unit_po_baru": float((need - have).clip(lower=0).where(mask, 0.0).sum()),
    }
