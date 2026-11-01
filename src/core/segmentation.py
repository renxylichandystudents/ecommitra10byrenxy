from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN, KMeans
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.preprocessing import StandardScaler


PRODUCTIVITY_LABELS = ("Sangat Produktif", "Produktif", "Perlu Dorongan", "Slow-Moving", "Dead Stock")


def abc_xyz_segments(
    daily: pd.DataFrame,
    *,
    sku_col: str = "item_key",
    qty_col: str = "qty",
    sales_col: str = "sales",
) -> pd.DataFrame:
    if daily is None or daily.empty or sku_col not in daily.columns:
        return pd.DataFrame(columns=[sku_col, "abc", "xyz", "cv_qty", "sales_total", "qty_total"])
    grouped = daily.groupby(sku_col, as_index=False).agg(
        sales_total=(sales_col, "sum") if sales_col in daily.columns else (sku_col, "size"),
        qty_total=(qty_col, "sum") if qty_col in daily.columns else (sku_col, "size"),
        qty_mean=(qty_col, "mean") if qty_col in daily.columns else (sku_col, "size"),
        qty_std=(qty_col, "std") if qty_col in daily.columns else (sku_col, "size"),
    )
    grouped["qty_std"] = grouped["qty_std"].fillna(0.0)
    grouped["cv_qty"] = np.where(grouped["qty_mean"].gt(0), grouped["qty_std"] / grouped["qty_mean"], np.inf)
    grouped = grouped.sort_values(["sales_total", "qty_total", sku_col], ascending=[False, False, True], kind="mergesort")
    total_sales = float(grouped["sales_total"].sum())
    if total_sales > 0:
        grouped["sales_share_cum"] = grouped["sales_total"].cumsum() / total_sales
    else:
        grouped["sales_share_cum"] = 1.0
    prior_share = grouped["sales_share_cum"].shift(fill_value=0.0)
    grouped["abc"] = np.select(
        [prior_share.lt(0.70), prior_share.lt(0.90)],
        ["A", "B"],
        default="C",
    )
    grouped["xyz"] = np.select(
        [grouped["cv_qty"].le(0.50), grouped["cv_qty"].le(1.00)],
        ["X", "Y"],
        default="Z",
    )
    grouped.loc[grouped["qty_total"].le(0), "xyz"] = "Z"
    return grouped.reset_index(drop=True)


def product_feature_table(
    sales: pd.DataFrame,
    ads: pd.DataFrame | None = None,
    performance: pd.DataFrame | None = None,
    *,
    sku_col: str = "item_key",
) -> pd.DataFrame:
    if sales is None or sales.empty or sku_col not in sales.columns:
        return pd.DataFrame()
    features = sales.groupby(sku_col, as_index=False).agg(
        qty_total=("qty", "sum") if "qty" in sales.columns else (sku_col, "size"),
        sales_total=("sales", "sum") if "sales" in sales.columns else (sku_col, "size"),
        active_days=("date", "nunique") if "date" in sales.columns else (sku_col, "size"),
    )
    if ads is not None and not ads.empty:
        code_col = "sku" if "sku" in ads.columns else ("item_key" if "item_key" in ads.columns else None)
        if code_col is not None:
            ad_features = ads.groupby(code_col, as_index=False).agg(
                ad_sales=("ad_sales", "sum") if "ad_sales" in ads.columns else (code_col, "size"),
                ad_cost=("cost", "sum") if "cost" in ads.columns else (code_col, "size"),
                clicks=("clicks", "sum") if "clicks" in ads.columns else (code_col, "size"),
                views=("views", "sum") if "views" in ads.columns else (code_col, "size"),
            )
            ad_features = ad_features.rename(columns={code_col: sku_col})
            features = features.merge(ad_features, on=sku_col, how="left")
    for column in ("ad_sales", "ad_cost", "clicks", "views"):
        if column not in features.columns:
            features[column] = 0.0
    features["roas"] = np.where(features["ad_cost"].gt(0), features["ad_sales"] / features["ad_cost"], 0.0)
    features["conversion_rate"] = np.where(features["views"].gt(0), features["clicks"] / features["views"], 0.0)
    if performance is not None and not performance.empty:
        if "conversion_rate" in performance.columns:
            features["store_conversion_rate"] = float(pd.to_numeric(performance["conversion_rate"], errors="coerce").mean())
        if "visitors" in performance.columns:
            features["store_visitors"] = float(pd.to_numeric(performance["visitors"], errors="coerce").mean())
    return features.fillna(0.0)


def cluster_products(features: pd.DataFrame, *, method: str = "kmeans", n_clusters: int = 4) -> pd.DataFrame:
    if features is None or features.empty or "item_key" not in features.columns:
        return pd.DataFrame()
    numeric_cols = [
        column
        for column in ("qty_total", "sales_total", "roas", "conversion_rate", "active_days")
        if column in features.columns
    ]
    out = features.copy()
    if len(out) < 3 or not numeric_cols:
        out["cluster"] = 0
        out["cluster_method"] = "fallback"
        return out
    matrix = StandardScaler().fit_transform(out[numeric_cols].astype(float))
    try:
        if method == "dbscan":
            labels = DBSCAN(eps=1.25, min_samples=max(2, min(5, len(out) // 8))).fit_predict(matrix)
            out["cluster_method"] = "DBSCAN"
        else:
            k = max(2, min(n_clusters, len(out)))
            labels = KMeans(n_clusters=k, random_state=42, n_init=10).fit_predict(matrix)
            out["cluster_method"] = "K-Means"
        out["cluster"] = labels
    except Exception:
        out["cluster"] = _quantile_cluster(out["qty_total"], out["sales_total"])
        out["cluster_method"] = "fallback"
    return out


def label_productivity(features: pd.DataFrame) -> pd.DataFrame:
    if features is None or features.empty:
        return pd.DataFrame()
    out = features.copy()
    sales_rank = out["sales_total"].rank(pct=True) if "sales_total" in out.columns else pd.Series(0, index=out.index)
    qty_rank = out["qty_total"].rank(pct=True) if "qty_total" in out.columns else pd.Series(0, index=out.index)
    roas_rank = out["roas"].rank(pct=True) if "roas" in out.columns else pd.Series(0, index=out.index)
    score = 0.45 * sales_rank + 0.35 * qty_rank + 0.20 * roas_rank
    out["productivity_score"] = score
    out["productivity_label"] = np.select(
        [
            score.ge(0.85),
            score.ge(0.65),
            score.ge(0.40),
            score.ge(0.15),
        ],
        list(PRODUCTIVITY_LABELS[:-1]),
        default=PRODUCTIVITY_LABELS[-1],
    )
    return out


def train_productivity_classifier(features: pd.DataFrame):
    labeled = label_productivity(features)
    if labeled.empty or len(labeled["productivity_label"].unique()) < 2:
        return None, "Data belum cukup untuk classifier produktivitas."
    columns = [column for column in ("qty_total", "sales_total", "roas", "conversion_rate", "active_days") if column in labeled.columns]
    if len(labeled) < 20:
        model = RandomForestClassifier(n_estimators=50, max_depth=4, random_state=42, class_weight="balanced")
    else:
        model = GradientBoostingClassifier(random_state=42)
    try:
        model.fit(labeled[columns].astype(float), labeled["productivity_label"])
        return model, f"Classifier produktivitas aktif dengan {len(columns)} fitur."
    except Exception as exc:  # noqa: BLE001
        return None, f"Classifier produktivitas dilewati: {exc}"


def association_rules(
    orders: pd.DataFrame,
    *,
    order_col: str = "order_id",
    item_col: str = "item_key",
    min_support: float = 0.02,
    min_confidence: float = 0.20,
) -> pd.DataFrame:
    columns = ["antecedent", "consequent", "support", "confidence", "lift"]
    if orders is None or orders.empty or order_col not in orders.columns or item_col not in orders.columns:
        return pd.DataFrame(columns=columns)
    baskets = (
        orders[[order_col, item_col]]
        .dropna()
        .assign(**{order_col: lambda df: df[order_col].astype(str), item_col: lambda df: df[item_col].astype(str)})
    )
    grouped = baskets.groupby(order_col)[item_col].apply(lambda items: sorted(set(item for item in items if item)))
    grouped = grouped[grouped.map(len).ge(2)]
    total = len(grouped)
    if total == 0:
        return pd.DataFrame(columns=columns)
    item_count: dict[str, int] = {}
    pair_count: dict[tuple[str, str], int] = {}
    for items in grouped:
        for item in items:
            item_count[item] = item_count.get(item, 0) + 1
        for left, right in combinations(items, 2):
            pair_count[(left, right)] = pair_count.get((left, right), 0) + 1
            pair_count[(right, left)] = pair_count.get((right, left), 0) + 1
    rows = []
    for (left, right), count in pair_count.items():
        support = count / total
        confidence = count / max(item_count.get(left, 1), 1)
        consequent_support = item_count.get(right, 0) / total
        lift = confidence / consequent_support if consequent_support > 0 else 0.0
        if support >= min_support and confidence >= min_confidence:
            rows.append(
                {
                    "antecedent": left,
                    "consequent": right,
                    "support": round(support, 4),
                    "confidence": round(confidence, 4),
                    "lift": round(lift, 4),
                }
            )
    return pd.DataFrame(rows, columns=columns).sort_values(["lift", "confidence"], ascending=[False, False])


def sequential_pattern_insights(daily: pd.DataFrame) -> pd.DataFrame:
    columns = ["pola", "support_days", "insight"]
    if daily is None or daily.empty or "date" not in daily.columns:
        return pd.DataFrame(columns=columns)
    work = daily.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    total = work.groupby("date", as_index=False).agg(
        qty=("qty", "sum") if "qty" in work.columns else ("date", "size"),
        clicks=("clicks", "sum") if "clicks" in work.columns else ("date", "size"),
        ad_cost=("cost", "sum") if "cost" in work.columns else ("date", "size"),
    )
    if len(total) < 4:
        return pd.DataFrame(columns=columns)
    total["ad_up"] = total["ad_cost"].diff().gt(0)
    total["click_up_next"] = total["clicks"].shift(-1).gt(total["clicks"])
    total["qty_up_next"] = total["qty"].shift(-1).gt(total["qty"])
    mask = total["ad_up"] & total["click_up_next"] & total["qty_up_next"]
    support = int(mask.sum())
    if support == 0:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(
        [
            {
                "pola": "biaya iklan naik -> klik naik -> penjualan naik",
                "support_days": support,
                "insight": f"Pola muncul {support} hari; pakai sebagai kandidat tanggal iklan, tetap cek stok sebelum menaikkan budget.",
            }
        ]
    )


def _quantile_cluster(qty: pd.Series, sales: pd.Series) -> pd.Series:
    score = qty.rank(pct=True) * 0.5 + sales.rank(pct=True) * 0.5
    return pd.cut(score, bins=[-0.01, 0.25, 0.50, 0.75, 1.0], labels=[3, 2, 1, 0]).astype(int)

