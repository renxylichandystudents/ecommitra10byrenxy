"""Data fitur bersama untuk halaman baru: SKU dikecualikan, komponen biaya, margin, PO impor."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from src.core import margin as margin_core
from src.core import promo
from src.core.restock import open_po_map
from src.core.warehouse import po_from_notes


@dataclass
class FeatureData:
    excluded: set[str] = field(default_factory=set)
    components: pd.DataFrame = field(default_factory=pd.DataFrame)
    margin: pd.DataFrame = field(default_factory=pd.DataFrame)
    margin_pct: dict[str, float] = field(default_factory=dict)
    import_po: pd.DataFrame = field(default_factory=pd.DataFrame)
    import_note: pd.DataFrame = field(default_factory=pd.DataFrame)
    po: dict[str, dict] = field(default_factory=dict)
    ad_per_unit: dict[str, float] = field(default_factory=dict)
    target: dict | None = None
    margin_fallback: float | None = None  # margin bersih tipikal toko (dari File margin) untuk SKU tanpa data
    margin_source: str = ""
    margin_inputs: dict = field(default_factory=dict)  # sku → shopee_fee.Inputs (modal dari File margin) untuk harga flash
    replenishment: pd.DataFrame = field(default_factory=pd.DataFrame)  # replenishment Site 10037 terbaru: sku, out_po, out_tr
    replenishment_date: object = None
    replenishment_history: pd.DataFrame = field(default_factory=pd.DataFrame)  # semua snapshot: snapshot_date, sku, out_*


SEED_ACTION = "seed:excluded_sku"


def excluded_skus(features) -> set[str]:
    """Isi tabel excluded_sku. Isi awal 40030033 (SKU jasa) ditanam sekali; setelah itu user yang mengatur."""
    if features is None:
        return set(promo.SEED_EXCLUDED)
    try:
        if features.read("audit_log", {"action": SEED_ACTION}).empty:
            from datetime import datetime

            rows = [{"sku": sku, "nama": name, "jenis": "SKU jasa", "added_by": "sistem", "added_at": datetime.now()} for sku, name in promo.SEED_EXCLUDED.items()]
            features.replace("excluded_sku", rows, keys=["sku"], username="sistem", action=SEED_ACTION)
        frame = features.read("excluded_sku")
    except Exception:
        return set(promo.SEED_EXCLUDED)
    return set(frame["sku"].astype(str))


def product_frame(table: pd.DataFrame) -> pd.DataFrame:
    """Harga jual dari data produk (harga di unggahan stok/produk terakhir), cadangan harga bersih transaksi."""
    if table is None or table.empty:
        return pd.DataFrame(columns=["sku", "product_name", "variation", "price"])
    price = pd.to_numeric(table.get("harga_stok"), errors="coerce") if "harga_stok" in table.columns else pd.Series(np.nan, index=table.index)
    price = price.where(price > 0, pd.to_numeric(table.get("harga_bersih"), errors="coerce"))
    return pd.DataFrame(
        {
            "sku": table["sku"].astype(str),
            "product_name": table["product_name"].astype(str),
            "variation": table.get("variasi_tampil", pd.Series("", index=table.index)).fillna("").astype(str),
            "price": price.fillna(0.0),
        }
    )


def ad_cost_map(table: pd.DataFrame) -> dict[str, float]:
    """Biaya iklan per unit: biaya iklan jendela laporan iklan ÷ QTY terjual di jendela yang sama (qty_sku)."""
    if table is None or table.empty or "biaya_iklan" not in table.columns:
        return {}
    column = "qty_sku" if "qty_sku" in table.columns else "qty_total" if "qty_total" in table.columns else None
    qty = pd.Series(pd.to_numeric(table[column], errors="coerce").fillna(0).to_numpy(), index=table["sku"].astype(str)) if column else None
    ads = pd.DataFrame({"sku": table["sku"].astype(str), "biaya_iklan": pd.to_numeric(table["biaya_iklan"], errors="coerce").fillna(0)})
    return margin_core.ad_cost_per_unit(ads, qty)


def target_for(features, periode: str) -> dict | None:
    if features is None:
        return None
    try:
        frame = features.read("sales_target", {"periode": periode})
    except Exception:
        return None
    if frame.empty or float(frame.iloc[0]["target_sales_bersih"] or 0) <= 0:
        return None
    return frame.iloc[0].to_dict()


def load_feature_data(features, table: pd.DataFrame, today: date, *, periode: str = "") -> FeatureData:
    data = FeatureData(excluded=excluded_skus(features))
    if features is None:
        return data
    try:
        data.components = features.read("cost_component")
        data.import_po = features.read("import_po")
        data.import_note = features.read("import_note")
    except Exception:
        pass
    if data.import_po.empty and not data.import_note.empty and "sku" in data.import_note.columns:
        data.import_po = po_from_notes(data.import_note)
    data.po = open_po_map(data.import_po)
    try:
        dates = features.snapshot_dates("warehouse_replenishment")
        if dates:
            history = features.read("warehouse_replenishment")
            keep = [c for c in ("snapshot_date", "sku", "out_po", "out_tr", "out_to", "out_tr_lain") if c in history.columns]
            data.replenishment_history = history[keep]
            stamp = pd.to_datetime(history["snapshot_date"], errors="coerce").dt.date
            data.replenishment = history.loc[stamp.eq(pd.Timestamp(dates[0]).date())]
            data.replenishment_date = dates[0]
    except Exception:
        pass
    data.ad_per_unit = ad_cost_map(table)
    if not data.components.empty:
        data.margin = margin_core.sku_margin_table(product_frame(table), data.components, iklan_per_unit=data.ad_per_unit, on=today)
        valid = data.margin.dropna(subset=["margin_pct"])
        data.margin_pct = {str(s): float(v) for s, v in zip(valid["sku"], valid["margin_pct"])}
        data.margin_source = "komponen biaya"
    else:
        _margin_from_file(features, table, data)
    if periode:
        data.target = target_for(features, periode)
    return data


def _margin_from_file(features, table: pd.DataFrame, data: FeatureData) -> None:
    """Margin bersih per SKU dari File margin (margin kotor − potongan Shopee − iklan), untuk iklan & promo."""
    try:
        from src.core import shopee_fee as fee
        from src.ui.kalkulator import KEY_SKU_CAT, _category_fees, _programs
        from src.ui.margin_data import _load

        md = _load(features, None)
        if not md.ready:
            return
        programs, order_fee, _limit = _programs(features)
        values, typical = fee.net_margin_map(
            product_frame(table), md.kotor_map(dict(zip(product_frame(table)["sku"], product_frame(table)["price"]))), programs=programs, order_fee=order_fee, fees=_category_fees(features),
            sku_cat=features.get_json(KEY_SKU_CAT, {}) or {}, ad_per_unit=data.ad_per_unit, inputs=data.margin_inputs,
        )
        data.margin_pct = values
        data.margin_fallback = typical if np.isfinite(typical) else None
        data.margin_source = f"File margin {md.periode}"
    except Exception:
        return


def cached_feature_data(state, features, table: pd.DataFrame, today: date, *, periode: str, stamp: object) -> FeatureData:
    """Satu kali baca per rerun + perubahan data fitur (stamp dinaikkan setiap aksi simpan)."""
    key = (stamp, len(table) if table is not None else 0, today.isoformat(), periode, state.get("_feature-version", 0))
    cached = state.get("_feature-data")
    if isinstance(cached, tuple) and cached[0] == key:
        return cached[1]
    data = load_feature_data(features, table, today, periode=periode)
    state["_feature-data"] = (key, data)
    return data


def bump(state) -> None:
    state["_feature-version"] = int(state.get("_feature-version", 0)) + 1
