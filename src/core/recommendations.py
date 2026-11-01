"""Rekomendasi iklan, flash sale toko, dan exposure media sosial.

Semua fungsi membaca tabel keputusan yang sama dengan Ringkasan/Prediksi
(prediksi, stok, SS, kebutuhan, label, iklan), jadi SKU yang stoknya kurang
tidak disarankan untuk iklan maupun flash sale.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.core.preprocessing import promo_flag

SHORT_STATUSES = {"Kosong", "Kurang", "Tipis"}


def _status(row: pd.Series, prefix: str = "m") -> str:
    return str(row.get(f"{prefix}_status", "")).split(" · ")[0]


def demand_days(orders: pd.DataFrame | None, start: date, end: date, *, limit: int = 8) -> list[date]:
    """Tanggal permintaan tinggi: tanggal promo (kembar, gajian, Harbolnas) + hari ramai dari pola harian."""
    days = pd.date_range(start, end, freq="D")
    if len(days) == 0:
        return []
    weekday_weight = np.ones(7)
    if orders is not None and not orders.empty and "order_time" in orders.columns:
        stamps = pd.to_datetime(orders["order_time"], errors="coerce").dropna()
        per_day = orders.assign(_d=stamps.dt.normalize()).groupby("_d")["qty"].sum()
        if not per_day.empty:
            by_dow = per_day.groupby(per_day.index.dayofweek).mean()
            for dow, value in by_dow.items():
                weekday_weight[int(dow)] = float(value)
            weekday_weight = weekday_weight / max(weekday_weight.mean(), 1e-9)
    promo = promo_flag(pd.Series(days)).to_numpy()
    score = weekday_weight[days.dayofweek] + promo * 1.0 + ((days.day == days.month) * 1.0)
    order = np.argsort(-score)[:limit]
    return sorted(days[order].date)


def ads_plan(
    table: pd.DataFrame,
    *,
    orders: pd.DataFrame | None,
    start: date,
    end: date,
    target_roas: float,
    budget_max: float,
    params: dict,
    rules: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame | dict]:
    """Bagi SKU ke Iklan produk, Iklan grup, dan Tidak perlu diiklankan; hitung budget dan estimasi sales."""
    if table is None or table.empty:
        empty = pd.DataFrame()
        return {"produk": empty, "grup": empty, "tidak": empty, "ringkasan": {}}
    cfg = params.get("iklan", {})
    default_roas = float(cfg.get("roas_default", 6))
    ad_share = float(cfg.get("porsi_sales_iklan_default_pct", 30)) / 100
    days = max((end - start).days + 1, 1)
    peak_days = demand_days(orders, start, end)
    date_text = ", ".join(f"{d.day}/{d.month}" for d in peak_days[:5])
    work = table.copy()
    cost = work.get("biaya_iklan", pd.Series(0.0, index=work.index)).fillna(0.0)
    ad_sales = work.get("omzet_iklan", pd.Series(0.0, index=work.index)).fillna(0.0)
    hist_roas = np.where(cost > 0, ad_sales / cost.replace(0, np.nan), np.nan)
    work["roas_hist"] = hist_roas
    work["roas_est"] = pd.Series(hist_roas, index=work.index).fillna(default_roas)
    daily_sales = work["pred_harian"].astype(float) * work["harga_bersih"].astype(float)
    work["sales_periode"] = daily_sales * days
    organic_share = np.where(work["sales_total"].astype(float) > 0, 1 - (ad_sales / work["sales_total"].astype(float).replace(0, np.nan)), 1.0)
    work["porsi_organik"] = pd.Series(organic_share, index=work.index).fillna(1.0).clip(0, 1)
    reasons = []
    for _, row in work.iterrows():
        status = _status(row)
        if status in SHORT_STATUSES:
            reasons.append(f"Stok {status.lower()}: kebutuhan belum tertutup, iklan ditunda")
        elif row["roas_est"] < target_roas:
            reasons.append(f"Estimasi ROAS {row['roas_est']:.1f} di bawah target {target_roas:g}")
        elif row["porsi_organik"] >= 0.9 and row["sales_total"] > 0 and "Terlaris" in (row.get("label") or []):
            reasons.append("Penjualan organik sudah tinggi (≥ 90% tanpa iklan)")
        elif row["sales_periode"] <= 0:
            reasons.append("Belum ada prediksi penjualan")
        else:
            reasons.append("")
    work["alasan_tidak"] = reasons
    eligible = work.loc[work["alasan_tidak"].eq("")].copy()
    eligible["sales_iklan_target"] = eligible["sales_periode"] * ad_share
    eligible["budget_raw"] = eligible["sales_iklan_target"] / target_roas
    total_raw = float(eligible["budget_raw"].sum())
    scale = min(1.0, budget_max / total_raw) if total_raw > 0 and budget_max > 0 else 1.0
    eligible["Budget"] = np.floor(eligible["budget_raw"] * scale / 1000) * 1000
    eligible["Estimasi sales iklan"] = eligible["Budget"] * eligible["roas_est"]
    eligible["Estimasi ROAS"] = np.where(eligible["Budget"] > 0, eligible["Estimasi sales iklan"] / eligible["Budget"], 0.0)
    eligible["Tanggal iklan"] = date_text
    eligible["Analisa"] = [
        f"Stok {_status(r).lower() or 'tersedia'}, hari cukup {r['hari_cukup']:.0f}; ROAS {'historis' if pd.notna(r['roas_hist']) else 'default'} {r['roas_est']:.1f}"
        if pd.notna(r.get("hari_cukup")) and np.isfinite(r.get("hari_cukup", np.nan))
        else f"ROAS {'historis' if pd.notna(r['roas_hist']) else 'default'} {r['roas_est']:.1f}; stok belum diunggah"
        for _, r in eligible.iterrows()
    ]
    group_keys: dict[str, str] = {}
    if rules is not None and not rules.empty:
        keys = set(eligible["item_key"].astype(str))
        for _, rule in rules.iterrows():
            a, c = str(rule["antecedent"]), str(rule["consequent"])
            if a in keys and c in keys and a not in group_keys and c not in group_keys:
                name = f"Grup {len(set(group_keys.values())) + 1}"
                group_keys[a] = name
                group_keys[c] = name
    eligible["Grup"] = eligible["item_key"].astype(str).map(group_keys).fillna("")
    columns = ["SKU", "Produk", "Label", "Tanggal iklan", "Budget", "Estimasi sales iklan", "Estimasi ROAS", "Analisa"]

    def frame(part: pd.DataFrame, with_group: bool = False) -> pd.DataFrame:
        out = pd.DataFrame(
            {
                "SKU": part["sku"].astype(str),
                "Produk": part["product_name"].astype(str),
                "Label": part.get("label_text", pd.Series("", index=part.index)).astype(str),
                "Tanggal iklan": part["Tanggal iklan"],
                "Budget": part["Budget"],
                "Estimasi sales iklan": part["Estimasi sales iklan"],
                "Estimasi ROAS": part["Estimasi ROAS"],
                "Analisa": part["Analisa"],
            }
        )
        if with_group:
            out.insert(0, "Grup", part["Grup"])
        return out[(["Grup"] if with_group else []) + columns]

    produk = frame(eligible.loc[eligible["Grup"].eq("")])
    grup = frame(eligible.loc[eligible["Grup"].ne("")], with_group=True).sort_values("Grup") if (eligible["Grup"] != "").any() else pd.DataFrame(columns=["Grup", *columns])
    tidak_part = work.loc[work["alasan_tidak"].ne("")]
    tidak = pd.DataFrame(
        {
            "SKU": tidak_part["sku"].astype(str),
            "Produk": tidak_part["product_name"].astype(str),
            "Label": tidak_part.get("label_text", pd.Series("", index=tidak_part.index)).astype(str),
            "Alasan": tidak_part["alasan_tidak"],
        }
    )
    total_budget = float(eligible["Budget"].sum())
    total_sales = float(eligible["Estimasi sales iklan"].sum())
    summary = {
        "estimasi_sales": total_sales,
        "estimasi_roas": total_sales / total_budget if total_budget > 0 else 0.0,
        "item_diiklankan": int(len(eligible)),
        "item_tidak": int(len(tidak_part)),
        "budget": total_budget,
        "tanggal": peak_days,
    }
    return {"produk": produk, "grup": grup, "tidak": tidak, "ringkasan": summary}


def flash_sale_plan(
    table: pd.DataFrame,
    *,
    start: date,
    params: dict,
    days: int = 30,
    per_day: int = 5,
) -> pd.DataFrame:
    """Rencana flash sale harian 1 bulan: hanya SKU dengan surplus stok setelah kebutuhan + SS."""
    cfg_margin = params.get("margin", {})
    shopee = params.get("shopee", {})
    hpp_pct = float(cfg_margin.get("hpp_pct_harga", 80)) / 100
    margin_min = float(cfg_margin.get("margin_min_pct", 8)) / 100
    discounts = [float(d) / 100 for d in shopee.get("flash_sale_diskon_pct", [10, 15, 20])]
    quota_pct = float(shopee.get("flash_sale_kuota_pct_surplus", 50)) / 100
    columns = ["Tanggal", "SKU", "Produk", "Harga saat ini", "Stok saat ini", "Saran stok flash sale", "Harga flash sale", "Diskon (%)", "Alasan"]
    if table is None or table.empty or "stok" not in table.columns:
        return pd.DataFrame(columns=columns)
    work = table.loc[table["ada_data_stok"].fillna(False)].copy()
    work["surplus"] = work["stok"].astype(float) - work["m_butuh"].astype(float)
    work = work.loc[work["surplus"] > 0]
    if work.empty:
        return pd.DataFrame(columns=columns)
    views = work.get("dilihat", pd.Series(0.0, index=work.index)).fillna(0.0)
    clicks = work.get("klik", pd.Series(0.0, index=work.index)).fillna(0.0)
    sold_ads = work.get("terjual_iklan", pd.Series(0.0, index=work.index)).fillna(0.0)
    conv = np.where(clicks > 0, sold_ads / clicks.replace(0, np.nan), np.nan)
    work["konversi"] = conv
    interest = views.rank(pct=True) * 0.5 + clicks.rank(pct=True) * 0.5
    low_conv = pd.Series(np.where(np.isnan(conv), 0.5, 1 - pd.Series(conv).rank(pct=True).fillna(0.5)), index=work.index)
    work["skor"] = 0.4 * interest + 0.3 * low_conv + 0.3 * (work["surplus"] / work["stok"].replace(0, np.nan)).fillna(0).clip(0, 1)
    work = work.sort_values("skor", ascending=False)
    rows = []
    cand = work.head(max(per_day * 6, per_day)).reset_index(drop=True)
    for offset in range(days):
        day = start + timedelta(days=offset)
        promo = bool(promo_flag(pd.Series([pd.Timestamp(day)])).iloc[0])
        count = per_day + (2 if promo else 0)
        for slot in range(count):
            if cand.empty:
                break
            row = cand.iloc[(offset * per_day + slot) % len(cand)]
            price = float(row["harga_bersih"])
            if price <= 0:
                continue
            floor = price * hpp_pct * (1 + margin_min)
            disc = next((d for d in sorted(discounts, reverse=True) if price * (1 - d) >= floor), None)
            if disc is None:
                continue
            quota = int(max(np.floor(row["surplus"] * quota_pct / max(days / 7, 1)), 1))
            reason = [f"Surplus {int(row['surplus'])} unit setelah kebutuhan + SS"]
            if row.get("dilihat", 0) and row.get("dilihat", 0) > 0:
                reason.append(f"dilihat {int(row['dilihat'])}, klik {int(row.get('klik', 0))}")
            if pd.notna(row["konversi"]):
                reason.append(f"konversi iklan {row['konversi'] * 100:.1f}%")
            reason.append(f"margin tetap ≥ {margin_min * 100:.0f}%")
            if promo:
                reason.append("tanggal promo")
            rows.append(
                {
                    "Tanggal": day,
                    "SKU": str(row["sku"]),
                    "Produk": str(row["product_name"]),
                    "Harga saat ini": round(price),
                    "Stok saat ini": int(row["stok"]),
                    "Saran stok flash sale": quota,
                    "Harga flash sale": round(price * (1 - disc)),
                    "Diskon (%)": disc * 100,
                    "Alasan": "; ".join(reason),
                }
            )
    return pd.DataFrame(rows, columns=columns)


def flash_sale_template(plan: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Format unggah sesuai kolom template flash sale toko di config."""
    columns = params.get("shopee", {}).get("flash_sale_template_kolom") or ["Tanggal", "SKU", "Nama Produk", "Harga Normal", "Harga Flash Sale", "Stok Flash Sale", "Batas Pembelian"]
    if plan is None or plan.empty:
        return pd.DataFrame(columns=columns)
    source = {
        "Tanggal": plan["Tanggal"].astype(str),
        "SKU": plan["SKU"],
        "Nama Produk": plan["Produk"],
        "Harga Normal": plan["Harga saat ini"],
        "Harga Flash Sale": plan["Harga flash sale"],
        "Stok Flash Sale": plan["Saran stok flash sale"],
        "Batas Pembelian": np.maximum(np.floor(plan["Saran stok flash sale"] / 5), 1).astype(int),
    }
    return pd.DataFrame({column: source.get(column, "") for column in columns})


def exposure_plan(
    table: pd.DataFrame,
    *,
    names: pd.DataFrame | None,
    cancel_reasons: dict[str, list[str]] | None,
    start: date,
    ad_days: list[date],
    flash: pd.DataFrame | None,
    count: int = 10,
) -> pd.DataFrame:
    """10 SKU untuk konten media sosial + hook masalah + poin penting + tanggal tayang."""
    columns = ["Tanggal", "SKU", "Produk", "Label", "Kenapa layak", "Hook masalah", "Poin penting"]
    if table is None or table.empty:
        return pd.DataFrame(columns=columns)
    work = table.copy()
    status = work.apply(_status, axis=1)
    work = work.loc[~status.isin({"Kosong", "Kurang"})]
    labels = work.get("label", pd.Series([[]] * len(work), index=work.index))
    score = (
        work["pred_qty"].rank(pct=True) * 0.4
        + work["sales_total"].rank(pct=True) * 0.3
        + labels.map(lambda items: 0.15 * len(items or [])).astype(float)
        + work.get("dilihat", pd.Series(0.0, index=work.index)).fillna(0).rank(pct=True) * 0.15
    )
    picked = work.assign(_score=score).sort_values("_score", ascending=False).head(count)
    name_map = names.set_index("item_key") if names is not None and not names.empty else pd.DataFrame()
    flash_days = {}
    if flash is not None and not flash.empty:
        for _, row in flash.iterrows():
            flash_days.setdefault(str(row["SKU"]), row["Tanggal"])
    rows = []
    slots = ad_days or [start + timedelta(days=3 * i) for i in range(count)]
    for index, (_, row) in enumerate(picked.iterrows()):
        key = str(row["item_key"])
        sku = str(row["sku"])
        reasons = cancel_reasons.get(key, []) if cancel_reasons else []
        when = flash_days.get(sku)
        when = (pd.Timestamp(when).date() - timedelta(days=1)) if when is not None else slots[index % len(slots)]
        why = [f"Prediksi {int(row['pred_qty'])} unit pada periode prediksi"]
        if row.get("label_text"):
            why.append(str(row["label_text"]))
        if pd.notna(row.get("hari_cukup")) and np.isfinite(row.get("hari_cukup", np.nan)):
            why.append(f"stok cukup {row['hari_cukup']:.0f} hari")
        primary = ""
        if not name_map.empty and key in name_map.index:
            primary = str(name_map.loc[key, "Kata kunci utama"]).split(",")[0].strip()
        product = str(row["product_name"])
        problem = reasons[0] if reasons else ""
        if problem:
            hook = f"Pernah ragu beli {primary or product.split()[0]} online karena {problem.lower()}? Ini jawabannya."
        else:
            hook = f"Renovasi tertunda karena {primary or 'bahan'} habis di toko? Cek {product.split()[0]} yang dipakai kontraktor."
        points = []
        if not name_map.empty and key in name_map.index:
            strengths = name_map.loc[key, "Kekuatan deskripsi lama"]
            if isinstance(strengths, dict):
                points += [aspect for aspect, ok in strengths.items() if ok][:3]
        points += ["Stok tersedia di gudang Mitra10", "Bisa tanya ukuran/estimasi kebutuhan lewat chat"]
        if reasons:
            points.append(f"Jawab keraguan: {reasons[0]}")
        rows.append(
            {
                "Tanggal": when,
                "SKU": sku,
                "Produk": product,
                "Label": str(row.get("label_text", "")),
                "Kenapa layak": "; ".join(why),
                "Hook masalah": hook,
                "Poin penting": "\n".join(f"- {p}" for p in points[:5]),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values("Tanggal").reset_index(drop=True)
