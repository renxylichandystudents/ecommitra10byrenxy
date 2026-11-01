"""Label produk: Terlaris, Populer, Paling diminati, Perlu perhatian."""

from __future__ import annotations

import numpy as np
import pandas as pd

LABEL_ICONS = {
    "Terlaris": "🏆",
    "Populer": "👁",
    "Paling diminati": "👆",
    "Perlu perhatian": "⚠",
}
LABEL_LEGEND = (
    "🏆 Terlaris: 10 besar QTY dan sales sekaligus · "
    "👁 Populer: 10% teratas dilihat · "
    "👆 Paling diminati: 10% teratas klik/CTR · "
    "⚠ Perlu perhatian: batal > 15% atau > 2× median toko. "
    "Data dilihat/klik dari laporan iklan; produk tanpa iklan tidak mendapat label Populer/Paling diminati."
)


def ads_by_sku(
    ads_frames: list[pd.DataFrame],
    stock_frame: pd.DataFrame | None,
    *,
    orders: pd.DataFrame | None = None,
    start=None,
    end=None,
) -> pd.DataFrame:
    """Metrik iklan per SKU (lihat src.core.ads.attribute_ads untuk aturan periode & pembagian varian)."""
    from src.core.ads import attribute_ads

    return attribute_ads(ads_frames, stock_frame, orders=orders, start=start, end=end).per_sku


def product_labels(
    table: pd.DataFrame,
    *,
    orders: pd.DataFrame | None = None,
    ads: pd.DataFrame | None = None,
    params: dict | None = None,
) -> pd.DataFrame:
    """Tambah kolom `label` (list) dan `label_text` pada tabel produk (punya item_key, sku, qty_total, sales_total)."""
    out = table.copy()
    if out.empty:
        out["label"] = []
        out["label_text"] = []
        return out
    cfg = (params or {}).get("label", {})
    top_n = int(cfg.get("terlaris_top_n", 10))
    pop_pct = float(cfg.get("populer_top_pct", 10)) / 100
    want_pct = float(cfg.get("diminati_top_pct", 10)) / 100
    cancel_limit = float(cfg.get("perlu_perhatian_batal_pct", 15)) / 100
    cancel_times = float(cfg.get("perlu_perhatian_kali_median", 2))
    labels: list[list[str]] = [[] for _ in range(len(out))]

    if {"qty_total", "sales_total"} <= set(out.columns):
        qty_rank = out["qty_total"].rank(ascending=False, method="first")
        sales_rank = out["sales_total"].rank(ascending=False, method="first")
        best = (qty_rank <= top_n) & (sales_rank <= top_n)
        for index in np.flatnonzero(best.to_numpy()):
            labels[index].append("Terlaris")

    if ads is not None and not ads.empty and "sku" in out.columns:
        key = out["sku"].fillna("").astype(str).str.strip()
        joined = pd.DataFrame({"sku": key}).merge(ads, on="sku", how="left")
        views = joined["dilihat"].fillna(0.0).to_numpy()
        clicks = joined["klik"].fillna(0.0).to_numpy()
        advertised = views > 0
        if advertised.any():
            view_cut = np.quantile(views[advertised], 1 - pop_pct)
            ctr = np.where(views > 0, clicks / np.maximum(views, 1), 0.0)
            click_cut = np.quantile(clicks[advertised], 1 - want_pct)
            ctr_cut = np.quantile(ctr[advertised], 1 - want_pct)
            for index in range(len(out)):
                if not advertised[index]:
                    continue
                if views[index] >= view_cut:
                    labels[index].append("Populer")
                if clicks[index] >= click_cut or (ctr[index] >= ctr_cut and clicks[index] > 0):
                    labels[index].append("Paling diminati")

    if orders is not None and not orders.empty and {"item_key", "status"} <= set(orders.columns):
        from src.ingest import cancelled_status_mask

        work = orders[["item_key", "status"]].copy()
        work["batal"] = cancelled_status_mask(work["status"]).astype(float)
        rate = work.groupby("item_key")["batal"].mean()
        median = float(rate[rate > 0].median()) if (rate > 0).any() else 0.0
        attention = rate[(rate > cancel_limit) | ((median > 0) & (rate > cancel_times * median))]
        flagged = set(attention.index.astype(str))
        for index, key in enumerate(out["item_key"].astype(str)):
            if key in flagged:
                labels[index].append("Perlu perhatian")

    out["label"] = labels
    out["label_text"] = [" ".join(f"{LABEL_ICONS[name]} {name}" for name in names) for names in labels]
    return out
