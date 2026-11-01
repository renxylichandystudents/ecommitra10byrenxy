from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.impute import KNNImputer, SimpleImputer
from sklearn.preprocessing import MinMaxScaler, StandardScaler

try:  # IterativeImputer is experimental in sklearn.
    from sklearn.experimental import enable_iterative_imputer  # noqa: F401
    from sklearn.impute import IterativeImputer
except Exception:  # pragma: no cover - optional sklearn surface
    IterativeImputer = None


STOPWORDS_ID = {
    "dan",
    "atau",
    "yang",
    "untuk",
    "dengan",
    "di",
    "ke",
    "dari",
    "ini",
    "itu",
    "pada",
    "dalam",
    "adalah",
    "produk",
    "barang",
}


@dataclass(frozen=True)
class PreprocessReport:
    rows_in: int
    rows_out: int
    missing_filled: int
    outliers_flagged: int
    outliers_winsorized: int
    promo_spikes_kept: int
    method: str
    note: str


PROMO_DAY_REGEX = re.compile(r"(\b|[-/])(9|10|11|12)\2(9|10|11|12)(\b|[-/])")


def promo_flag(dates: pd.Series) -> pd.Series:
    stamps = pd.to_datetime(dates, errors="coerce")
    day = stamps.dt.day
    month = stamps.dt.month
    payday = day.between(25, 31) | day.between(1, 3)
    twin = day.eq(month)
    harbolnas = (month.eq(12) & day.eq(12)) | (month.eq(11) & day.eq(11)) | (month.eq(10) & day.eq(10))
    return (payday | twin | harbolnas).fillna(False)


def complete_daily_sku_frame(
    orders: pd.DataFrame,
    *,
    sku_col: str = "item_key",
    date_col: str = "order_time",
    qty_col: str = "qty",
    sales_col: str = "sales",
    status_columns: tuple[str, ...] = ("stock_dc_cikupa", "price", "is_advertised"),
) -> pd.DataFrame:
    """Bangun kalender harian lengkap per SKU.

    Tanggal tanpa transaksi berarti penjualan 0. Kolom status boleh ffill/bfill,
    tetapi qty dan sales tidak pernah diimpute.
    """
    if orders is None or orders.empty or sku_col not in orders.columns or date_col not in orders.columns:
        return pd.DataFrame(columns=[sku_col, "date", qty_col, sales_col, "is_promo"])
    work = orders.copy()
    work["date"] = pd.to_datetime(work[date_col], errors="coerce").dt.normalize()
    work = work.dropna(subset=["date"])
    if work.empty:
        return pd.DataFrame(columns=[sku_col, "date", qty_col, sales_col, "is_promo"])
    grouped = (
        work.groupby([sku_col, "date"], as_index=False)
        .agg(
            **{
                qty_col: (qty_col, "sum") if qty_col in work.columns else (sku_col, "size"),
                sales_col: (sales_col, "sum") if sales_col in work.columns else (sku_col, "size"),
            }
        )
        .sort_values([sku_col, "date"])
    )
    dates = pd.date_range(grouped["date"].min(), grouped["date"].max(), freq="D")
    pieces: list[pd.DataFrame] = []
    status_present = [column for column in status_columns if column in work.columns]
    status_daily = pd.DataFrame()
    if status_present:
        status_daily = work.groupby([sku_col, "date"], as_index=False)[status_present].last()
    for sku, item in grouped.groupby(sku_col, sort=False):
        base = item.set_index("date").reindex(dates)
        base[sku_col] = sku
        base[qty_col] = base[qty_col].fillna(0.0)
        base[sales_col] = base[sales_col].fillna(0.0)
        if status_present:
            status_item = status_daily.loc[status_daily[sku_col].eq(sku)].set_index("date").reindex(dates)
            for column in status_present:
                base[column] = status_item[column].ffill().bfill()
        pieces.append(base.reset_index(names="date"))
    dense = pd.concat(pieces, ignore_index=True)
    dense["is_promo"] = promo_flag(dense["date"])
    return dense.sort_values([sku_col, "date"]).reset_index(drop=True)


def impute_numeric_frame(
    frame: pd.DataFrame,
    *,
    columns: list[str],
    method: str = "auto",
    exclude: tuple[str, ...] = ("qty", "sales"),
) -> tuple[pd.DataFrame, int, str]:
    present = [column for column in columns if column in frame.columns and column not in set(exclude)]
    if not present:
        return frame.copy(), 0, "Tidak ada kolom numerik non-penjualan untuk imputasi."
    out = frame.copy()
    numeric = out[present].apply(pd.to_numeric, errors="coerce")
    missing = int(numeric.isna().sum().sum())
    if missing == 0:
        return out, 0, "Tidak ada missing value."
    chosen = method.lower()
    if chosen == "auto":
        ratio = missing / max(numeric.size, 1)
        chosen = "median" if ratio < 0.03 else ("knn" if len(present) <= 4 else "mice")
    try:
        if chosen == "knn":
            values = KNNImputer(n_neighbors=min(5, max(len(numeric) - 1, 1))).fit_transform(numeric)
        elif chosen == "mice" and IterativeImputer is not None:
            values = IterativeImputer(random_state=42, max_iter=10, sample_posterior=False).fit_transform(numeric)
        elif chosen == "mean":
            values = SimpleImputer(strategy="mean").fit_transform(numeric)
        elif chosen == "mode":
            values = SimpleImputer(strategy="most_frequent").fit_transform(numeric)
        else:
            values = SimpleImputer(strategy="median").fit_transform(numeric)
            chosen = "median"
    except Exception:
        values = SimpleImputer(strategy="median").fit_transform(numeric)
        chosen = "median"
    out[present] = values
    return out, missing, f"Missing value diisi memakai {chosen.upper()}."


def winsorize_outliers(
    frame: pd.DataFrame,
    *,
    columns: tuple[str, ...] = ("qty", "sales"),
    method: str = "iqr",
    promo_col: str = "is_promo",
) -> tuple[pd.DataFrame, dict[str, int]]:
    out = frame.copy()
    stats = {"flagged": 0, "winsorized": 0, "promo_kept": 0}
    promo = out[promo_col].fillna(False).astype(bool) if promo_col in out.columns else pd.Series(False, index=out.index)
    for column in columns:
        if column not in out.columns:
            continue
        values = pd.to_numeric(out[column], errors="coerce")
        positive = values[values > 0]
        if len(positive) < 8:
            continue
        lo, hi = _outlier_bounds(positive, method)
        mask = values.gt(hi) | ((values.gt(0)) & values.lt(lo))
        if not bool(mask.any()):
            continue
        out[f"{column}_outlier"] = mask
        promo_mask = mask & promo
        normal_mask = mask & ~promo
        stats["flagged"] += int(mask.sum())
        stats["promo_kept"] += int(promo_mask.sum())
        if bool(normal_mask.any()):
            if not pd.api.types.is_float_dtype(out[column]):
                out[column] = out[column].astype(float)
            out.loc[normal_mask, column] = values.loc[normal_mask].clip(lower=max(lo, 0), upper=hi)
            stats["winsorized"] += int(normal_mask.sum())
    return out, stats


def _outlier_bounds(values: pd.Series, method: str) -> tuple[float, float]:
    method = str(method or "iqr").lower()
    if method == "zscore":
        mean = float(values.mean())
        std = float(values.std(ddof=1))
        if std <= 0:
            return 0.0, float(values.max())
        return mean - 3 * std, mean + 3 * std
    q1, q3 = values.quantile([0.25, 0.75])
    iqr = float(q3 - q1)
    if iqr <= 0:
        return 0.0, float(values.max())
    return float(q1 - 1.5 * iqr), float(q3 + 1.5 * iqr)


def scale_features(frame: pd.DataFrame, columns: list[str], *, method: str = "standard") -> pd.DataFrame:
    present = [column for column in columns if column in frame.columns]
    if not present:
        return frame.copy()
    scaler = MinMaxScaler() if method == "minmax" else StandardScaler()
    out = frame.copy()
    out[present] = scaler.fit_transform(out[present].apply(pd.to_numeric, errors="coerce").fillna(0.0))
    return out


def normalize_product_text(text: object, *, stem: bool = True) -> str:
    raw = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    raw = raw.lower()
    raw = re.sub(r"[^a-z0-9\s]", " ", raw)
    tokens = [token for token in raw.split() if token and token not in STOPWORDS_ID]
    if stem:
        tokens = _stem_tokens(tokens)
    return " ".join(tokens)


def _stem_tokens(tokens: list[str]) -> list[str]:
    try:
        from Sastrawi.Stemmer.StemmerFactory import StemmerFactory

        stemmer = StemmerFactory().create_stemmer()
        return [stemmer.stem(token) for token in tokens]
    except Exception:
        suffixes = ("nya", "lah", "kah", "pun", "kan", "an", "i")
        cleaned = []
        for token in tokens:
            for suffix in suffixes:
                if len(token) > len(suffix) + 3 and token.endswith(suffix):
                    token = token[: -len(suffix)]
                    break
            cleaned.append(token)
        return cleaned


def preprocess_sales_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, PreprocessReport]:
    if frame is None or frame.empty:
        empty = pd.DataFrame() if frame is None else frame.copy()
        return empty, PreprocessReport(0, 0, 0, 0, 0, 0, "none", "Tidak ada data.")
    dense = complete_daily_sku_frame(frame)
    numeric_candidates = [column for column in dense.columns if pd.api.types.is_numeric_dtype(dense[column])]
    imputed, missing, note = impute_numeric_frame(dense, columns=numeric_candidates)
    cleaned, stats = winsorize_outliers(imputed)
    report = PreprocessReport(
        rows_in=len(frame),
        rows_out=len(cleaned),
        missing_filled=missing,
        outliers_flagged=stats["flagged"],
        outliers_winsorized=stats["winsorized"],
        promo_spikes_kept=stats["promo_kept"],
        method="daily_sku_iqr",
        note=note,
    )
    return cleaned, report

