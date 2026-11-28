"""Input ekonomi iklan untuk Ads OS (Rekomendasi › Iklan).

Dipisah dari rekomendasi_plus agar tab Iklan tidak ikut memuat Flash sale / Exposure / Ranking.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st


def _normalize_ctr(raw) -> float:
    """CTR pecahan 0–1 dari kolom Persentase Klik SC (selalu persen: 1,5 → 0,015; 0,8 → 0,008)."""
    num = pd.to_numeric(raw, errors="coerce")
    if num != num or not np.isfinite(num):
        return float("nan")
    val = float(num)
    if val < 0 or val > 100:
        return float("nan")
    # Ekspor Shopee = persen, bukan pecahan.
    return val / 100.0


def _ctr_by_product_code(*frames) -> dict[str, float]:
    """Ambil CTR per Kode Produk dari laporan iklan (overall / grup / otomatis) bila kolom ada.

    Tidak menginvent CTR: hanya kode yang punya nilai nyata. Unggahan lebih baru menimpa.
    """
    out: dict[str, float] = {}
    for frame in frames:
        if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
            continue
        if "product_code" not in frame.columns:
            continue
        ctr_col = None
        for name in ("ctr", "Persentase Klik", "CTR"):
            if name in frame.columns:
                ctr_col = name
                break
        if ctr_col is None:
            continue
        work = frame
        if "_submitted_at" in work.columns:
            work = work.sort_values("_submitted_at")
        for code, raw in zip(work["product_code"].astype(str), work[ctr_col]):
            text = str(code or "").strip()
            if text.endswith(".0"):
                text = text[:-2]
            if not text.isdigit():
                continue
            val = _normalize_ctr(raw)
            if val == val:
                out[text] = val
    return out


def ads_inputs(table: pd.DataFrame, features, frames, days_left: int):
    """Unit iklan + ekonomi per Kode Produk: kontribusi sebelum iklan (margin kotor − potongan Shopee) dan ruang stok (Rp/hari).

    Hasil disimpan per sesi agar buka Rekomendasi sistem tidak menghitung ulang fee/margin tiap rerun Streamlit.
    Mengembalikan (units, members, contribution, products, occupied) — occupied = kode di **iklan yang sedang
    berjalan** (termasuk otomatis aktif) supaya saran tidak membuat iklan dobel aktif. Kode hanya di iklan dijeda
    tidak menghalangi usulan iklan baru. Kolom `ctr` disuntik bila laporan iklan memuat Persentase Klik."""
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
        "occupied-active-ctr-v1",  # bump: suntik CTR ke products untuk Push skor
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
    # CTR nyata dari laporan iklan → Push skor (penalti hanya jika kolom terisi).
    ctr_map = _ctr_by_product_code(overall, group, auto)
    if ctr_map and not products.empty and "product_code" in products.columns:
        products["ctr"] = products["product_code"].astype(str).map(
            lambda c: ctr_map.get(c, float("nan"))
        )
    else:
        products["ctr"] = float("nan")
    # Fokus kejar target: hanya iklan produk tunggal & grup; iklan baru diusulkan oleh pemilihan produk (A.build_plan).
    units = [u for u in units if u.jenis in A.TARGET_KINDS]
    result = (units, members, contribution, products, frozenset(occupied))
    st.session_state["_ads-inputs-cache"] = (stamp, result)
    return result
