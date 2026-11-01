"""Gabungkan katalog prediksi dengan stok, iklan, label, segmen, batal, dan tren per SKU."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from src.core.decision_table import build_decision_table
from src.core.inventory import stock_zero_duration
from src.core.labels import ads_by_sku, product_labels
from src.core.segmentation import abc_xyz_segments, label_productivity, product_feature_table
from src.core.storage import LocalDataStore

AD_SOURCES = ("ads_auto", "ads_group", "ads_overall")


@dataclass
class StoreFrames:
    stock: pd.DataFrame = field(default_factory=pd.DataFrame)
    ads: list[pd.DataFrame] = field(default_factory=list)
    ads_search: pd.DataFrame = field(default_factory=pd.DataFrame)
    performance: pd.DataFrame = field(default_factory=pd.DataFrame)
    descriptions: pd.DataFrame = field(default_factory=pd.DataFrame)
    competitors: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def has_stock(self) -> bool:
        return not self.stock.empty

    @property
    def has_ads(self) -> bool:
        return any(not frame.empty for frame in self.ads)


def load_store_frames(store: LocalDataStore) -> StoreFrames:
    def read(key: str) -> pd.DataFrame:
        try:
            return store.read_source(key)
        except Exception:
            return pd.DataFrame()

    return StoreFrames(
        stock=read("stock"),
        ads=[read(key) for key in AD_SOURCES],
        ads_search=read("ads_search"),
        performance=read("performance"),
        descriptions=read("product_descriptions"),
        competitors=read("competitors"),
    )


def zero_since_map(stock: pd.DataFrame, today: date) -> tuple[pd.DataFrame, dict[str, pd.Timestamp]]:
    if stock is None or stock.empty or "sku" not in stock.columns:
        return pd.DataFrame(columns=["sku", "zero_since", "lama_kosong_hari"]), {}
    work = stock.copy()
    work["sku"] = work["sku"].fillna("").astype(str).str.strip().str.replace(r"^(\d+)\.0+$", r"\1", regex=True)
    durations = stock_zero_duration(work, today=today)
    mapping = {str(row["sku"]): pd.Timestamp(row["zero_since"]) for _, row in durations.iterrows()}
    return durations, mapping


def cancel_stats(orders_all: pd.DataFrame) -> pd.DataFrame:
    """Tingkat batal dan batal karena belum bayar per SKU (dari seluruh status pesanan)."""
    columns = ["item_key", "batal_pct", "batal_belum_bayar_pct", "alasan_batal"]
    if orders_all is None or orders_all.empty or not {"item_key", "status"} <= set(orders_all.columns):
        return pd.DataFrame(columns=columns)
    from src.ingest import cancelled_status_mask

    work = orders_all[["item_key", "status"]].copy()
    work["batal"] = cancelled_status_mask(work["status"]).astype(float)
    reason = orders_all["cancel_reason"].fillna("").astype(str) if "cancel_reason" in orders_all.columns else pd.Series("", index=orders_all.index)
    work["reason"] = reason
    work["unpaid"] = (work["batal"] > 0) & reason.str.lower().str.contains("bayar|pembayaran", regex=True)
    grouped = work.groupby("item_key").agg(batal=("batal", "mean"), unpaid=("unpaid", "mean"))
    reasons = (
        work.loc[(work["batal"] > 0) & work["reason"].ne("")]
        .groupby("item_key")["reason"]
        .agg(lambda values: [text for text, _count in pd.Series(values).value_counts().head(3).items() if text])
    )
    out = pd.DataFrame(
        {
            "item_key": grouped.index.astype(str),
            "batal_pct": grouped["batal"].to_numpy() * 100,
            "batal_belum_bayar_pct": grouped["unpaid"].to_numpy() * 100,
        }
    )
    out["alasan_batal"] = out["item_key"].map(reasons).map(lambda value: value if isinstance(value, list) else [])
    return out


def trend_pct(orders: pd.DataFrame, today: date) -> pd.DataFrame:
    """QTY 28 hari terakhir dibanding 28 hari sebelumnya per SKU."""
    if orders is None or orders.empty:
        return pd.DataFrame(columns=["item_key", "tren_pct"])
    end = min(pd.Timestamp(today).normalize(), pd.to_datetime(orders["order_time"]).max().normalize() + pd.Timedelta(days=1))
    days = pd.to_datetime(orders["order_time"]).dt.normalize()
    recent = orders.loc[days.ge(end - pd.Timedelta(days=28)) & days.lt(end)].groupby("item_key")["qty"].sum()
    prior = orders.loc[days.ge(end - pd.Timedelta(days=56)) & days.lt(end - pd.Timedelta(days=28))].groupby("item_key")["qty"].sum()
    joined = pd.concat([recent.rename("r"), prior.rename("p")], axis=1).fillna(0.0)
    pct = np.where(joined["p"] > 0, (joined["r"] - joined["p"]) / joined["p"] * 100, np.nan)
    return pd.DataFrame({"item_key": joined.index.astype(str), "tren_pct": pct})


def enrich_catalog(
    catalog: pd.DataFrame,
    *,
    period: str,
    today: date,
    horizon_days: int,
    orders_used: pd.DataFrame,
    orders_all: pd.DataFrame,
    frames: StoreFrames,
    params: dict,
) -> pd.DataFrame:
    if catalog is None or catalog.empty:
        return catalog
    zero_frame, _ = zero_since_map(frames.stock, today)
    lead = float(params.get("lead_time", {}).get("lokal_hari", 7))
    table = build_decision_table(
        catalog,
        period=period,
        today=today,
        horizon_days=horizon_days,
        orders=orders_used,
        stock_frame=frames.stock if frames.has_stock else None,
        zero_duration=zero_frame,
        lead_time_days=lead,
    )
    ads = ads_by_sku(frames.ads, frames.stock, orders=orders_used) if frames.has_ads and frames.has_stock else pd.DataFrame()
    if not ads.empty:
        key = table["sku"].fillna("").astype(str).str.strip()
        table = table.assign(_sku=key).merge(ads.rename(columns={"sku": "_sku"}), on="_sku", how="left").drop(columns="_sku")
    for column in ("dilihat", "klik", "biaya_iklan", "omzet_iklan", "omzet_iklan_shopee", "terjual_iklan", "keranjang"):
        if column not in table.columns:
            table[column] = 0.0
        table[column] = table[column].fillna(0.0)
    table = product_labels(table, orders=orders_all, ads=ads if not ads.empty else None, params=params)
    daily = orders_used.assign(date=pd.to_datetime(orders_used["order_time"]).dt.normalize()) if orders_used is not None and not orders_used.empty else pd.DataFrame()
    if not daily.empty:
        per_day = daily.groupby(["item_key", "date"], as_index=False).agg(qty=("qty", "sum"), sales=("sales", "sum"))
        segments = abc_xyz_segments(per_day)[["item_key", "abc", "xyz"]]
        features = product_feature_table(per_day)
        if not ads.empty:
            ad_feat = table[["item_key", "omzet_iklan", "biaya_iklan", "klik", "dilihat"]].rename(
                columns={"omzet_iklan": "ad_sales", "biaya_iklan": "ad_cost", "klik": "clicks", "dilihat": "views"}
            )
            features = features.drop(columns=["ad_sales", "ad_cost", "clicks", "views", "roas", "conversion_rate"], errors="ignore").merge(ad_feat, on="item_key", how="left").fillna(0.0)
            features["roas"] = np.where(features["ad_cost"] > 0, features["ad_sales"] / features["ad_cost"].replace(0, np.nan), 0.0)
        productivity = label_productivity(features)[["item_key", "productivity_label"]] if not features.empty else pd.DataFrame(columns=["item_key", "productivity_label"])
        table = table.merge(segments, on="item_key", how="left").merge(productivity, on="item_key", how="left")
    for column, default in (("abc", "C"), ("xyz", "Z"), ("productivity_label", "")):
        if column not in table.columns:
            table[column] = default
        table[column] = table[column].fillna(default)
    table = table.merge(cancel_stats(orders_all), on="item_key", how="left")
    table["batal_pct"] = table["batal_pct"].fillna(0.0)
    table["batal_belum_bayar_pct"] = table["batal_belum_bayar_pct"].fillna(0.0)
    table["alasan_batal"] = table["alasan_batal"].map(lambda value: value if isinstance(value, list) else [])
    table = table.merge(trend_pct(orders_used, today), on="item_key", how="left")
    table["lead_time"] = lead
    return table
