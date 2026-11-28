"""Input ekonomi iklan untuk Ads OS (Rekomendasi › Iklan).

Dipisah dari rekomendasi_plus agar tab Iklan tidak ikut memuat Flash sale / Exposure / Ranking.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st


def ads_inputs(table: pd.DataFrame, features, frames, days_left: int):
    """Unit iklan + ekonomi per Kode Produk: kontribusi sebelum iklan (margin kotor − potongan Shopee) dan ruang stok (Rp/hari).

    Hasil disimpan per sesi agar buka Rekomendasi sistem tidak menghitung ulang fee/margin tiap rerun Streamlit.
    Mengembalikan (units, members, contribution, products, occupied) — occupied = kode di **iklan yang sedang
    berjalan** (termasuk otomatis aktif) supaya saran tidak membuat iklan dobel aktif. Kode hanya di iklan dijeda
    tidak menghalangi usulan iklan baru."""
    from src.core import ads_strategy as A
    from src.core import shopee_fee as fee
    from src.core.margin_file import sku_key
    from src.ui.kalkulator import KEY_SKU_CAT, _category_fees, _programs
    from src.ui.margin_data import load_margin

    ads = list(getattr(frames, "ads", []) or [])
    auto, group, overall = (ads + [pd.DataFrame()] * 3)[:3]
    stamp = (
        len(table), float(pd.to_numeric(table.get("sales_total"), errors="coerce").fillna(0).sum()) if table is not None and not table.empty else 0.0,
        days_left,
        len(auto) if isinstance(auto, pd.DataFrame) else 0,
        len(group) if isinstance(group, pd.DataFrame) else 0,
        len(overall) if isinstance(overall, pd.DataFrame) else 0,
        str(getattr(frames, "stock", pd.DataFrame()).get("_submitted_at", pd.Series(dtype=str)).astype(str).max())
        if isinstance(getattr(frames, "stock", None), pd.DataFrame) and not getattr(frames, "stock").empty and "_submitted_at" in frames.stock.columns
        else "-",
        st.session_state.get("_feature-version", 0),
        "occupied-active-v1",  # bump cache setelah occupied = aktif saja
    )
    cached = st.session_state.get("_ads-inputs-cache")
    if isinstance(cached, tuple) and cached[0] == stamp:
        return cached[1]

    units, members = A.parse_units(group, overall, auto)
    if not units:
        empty = ([], members, {}, pd.DataFrame(), frozenset())
        st.session_state["_ads-inputs-cache"] = (stamp, empty)
        return empty
    recent = sorted({p for u in units for p, _c, _s in u.history})[-2:]
    units = [u for u in units if u.status.lower().startswith(("berjalan", "dijeda")) or (u.history and u.history[-1][0] in recent)]
    # Hanya kode di iklan yang SEDANG BERJALAN (hindari dobel aktif; iklan dijeda tidak mengunci produk).
    occupied = {c for u in units if A._running(u) for c in u.members}
    stock = getattr(frames, "stock", pd.DataFrame())
    code_of: dict[str, str] = {}
    if isinstance(stock, pd.DataFrame) and not stock.empty and {"sku", "product_code"} <= set(stock.columns):
        snap = stock.loc[stock["_submitted_at"].astype(str).eq(stock["_submitted_at"].astype(str).max())] if "_submitted_at" in stock.columns else stock
        code_of = {sku_key(s): str(c).strip() for s, c in zip(snap["sku"].astype(str), snap["product_code"])}
    md = load_margin(features)
    kotor = md.kotor_map({sku_key(r.get("sku", "")): float(r.get("harga_bersih", 0) or 0) for r in table.to_dict("records")}) if md.ready else {}
    programs, order_fee, _ = _programs(features)
    fees = _category_fees(features)
    sku_cat = features.get_json(KEY_SKU_CAT, {}) or {} if features is not None else {}
    contrib: dict[str, list[tuple[float, float]]] = {}
    room: dict[str, float] = {}
    rows = []
    for r in table.to_dict("records"):
        key = sku_key(r.get("sku", ""))
        code = code_of.get(key, "")
        price = float(r.get("harga_bersih", 0) or 0)
        sales = float(r.get("sales_total", 0) or 0)
        if code and price > 0:
            k = kotor.get(key, md.store_kotor_pct if md.ready else np.nan)
            if k == k:
                inp = fee.Inputs(harga=price, admin_pct=fee.admin_for(r.get("sku", ""), r.get("product_name", ""), fees, sku_cat)[1],
                                 programs=programs, order_fee=order_fee, ukuran_khusus="packing kayu" in str(r.get("product_name", "")).lower())
                contrib.setdefault(code, []).append((k / 100 - fee.shopee_fees(inp) / price, max(sales, 1.0)))
            stok = float(r.get("stok", 0) or 0) if r.get("ada_data_stok", False) else np.nan
            if stok == stok:
                guard = float(r.get("ss", r.get("safety_stock", 0)) or 0)
                spare = max(stok - float(r.get("pred_harian", 0) or 0) * days_left - (guard if guard == guard else 0.0), 0.0)
                room[code] = room.get(code, 0.0) + spare * price / max(days_left, 1)
            s62 = float(r["stok_10062"]) if r.get("stok_10062") == r.get("stok_10062") and r.get("stok_10062") is not None else np.nan
            s36 = float(r["stok_10036"]) if r.get("stok_10036") == r.get("stok_10036") and r.get("stok_10036") is not None else np.nan
            rows.append({
                "product_code": code, "nama": r.get("product_name", ""),
                "omzet_harian": float(r.get("pred_harian", 0) or 0) * price,
                "qty_harian": float(r.get("pred_harian", 0) or 0),
                "stok": stok, "stok_10037": stok, "stok_10062": s62, "stok_10036": s36,
            })
    contribution = {c: sum(v * w for v, w in vals) / sum(w for _v, w in vals) for c, vals in contrib.items()}
    A.attach_economics(units, members, contribution, room)
    products = (
        pd.DataFrame(rows).groupby(["product_code"], as_index=False).agg(
            nama=("nama", "first"),
            omzet_harian=("omzet_harian", "sum"),
            qty_harian=("qty_harian", "sum"),
            stok=("stok", lambda v: v.sum(min_count=1)),
            stok_10037=("stok_10037", lambda v: v.sum(min_count=1)),
            stok_10062=("stok_10062", lambda v: v.sum(min_count=1)),
            stok_10036=("stok_10036", lambda v: v.sum(min_count=1)),
        )
        if rows else pd.DataFrame(columns=[
            "product_code", "nama", "omzet_harian", "qty_harian", "stok",
            "stok_10037", "stok_10062", "stok_10036",
        ])
    )
    if "stok_10037" not in products.columns and "stok" in products.columns:
        products["stok_10037"] = products["stok"]
    products["stok_room"] = products["product_code"].map(room)
    # Fokus kejar target: hanya iklan produk tunggal & grup; iklan baru diusulkan oleh pemilihan produk (A.build_plan).
    units = [u for u in units if u.jenis in A.TARGET_KINDS]
    result = (units, members, contribution, products, frozenset(occupied))
    st.session_state["_ads-inputs-cache"] = (stamp, result)
    return result
