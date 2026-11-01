from __future__ import annotations

import pandas as pd

from src.core.inventory import snapshot_time
from src.core.schemas import SOURCE_SPECS, find_columns, validation_report
from src.core.storage import LocalDataStore


def _clean_key(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def _date_range(frame: pd.DataFrame, fields: tuple[str, ...]) -> str:
    for field in fields:
        if field not in frame.columns:
            continue
        dates = pd.to_datetime(frame[field], errors="coerce")
        if dates.notna().any():
            return f"{dates.min().date()} - {dates.max().date()}"
    return "-"


def _source_summary_row(source_key: str, frame: pd.DataFrame) -> dict[str, object]:
    spec = SOURCE_SPECS[source_key]
    report = validation_report(frame, spec)
    return {
        "Sumber": spec.label,
        "Status": report["status"],
        "Cakupan tanggal": _date_range(frame, spec.date_fields),
        "Jumlah baris": int(len(frame)),
        "Kolom wajib terbaca": ", ".join(report["found_required"]) or "-",
        "Kolom wajib hilang": ", ".join(report["missing_required"]) or "-",
        "Kegunaan": spec.utility,
    }


def consolidation_summary(store: LocalDataStore) -> tuple[pd.DataFrame, dict[str, float | int]]:
    frames = {key: store.read_source(key) for key in SOURCE_SPECS}
    rows = [_source_summary_row(key, frame) for key, frame in frames.items()]
    metrics = {
        "sku_transaksi_cocok_stok_pct": _transaction_stock_match(frames["transactions"], frames["stock"]),
        "produk_iklan_terpetakan_sku_pct": _ads_mapping_match(frames),
        "snapshot_stok": store.snapshot_count(),
        "sku_transaksi": _nunique_nonblank(frames["transactions"], "sku"),
        "sku_stok": _nunique_nonblank(frames["stock"], "sku"),
    }
    return pd.DataFrame(rows), metrics


def _nunique_nonblank(frame: pd.DataFrame, column: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    values = _clean_key(frame[column])
    return int(values[values.ne("")].nunique())


def _transaction_stock_match(transactions: pd.DataFrame, stock: pd.DataFrame) -> float:
    if transactions.empty or stock.empty or "sku" not in transactions.columns or "sku" not in stock.columns:
        return 0.0
    tx = set(_clean_key(transactions["sku"]))
    st = set(_clean_key(stock["sku"]))
    tx.discard("")
    st.discard("")
    if not tx:
        return 0.0
    return round(len(tx & st) / len(tx) * 100, 2)


def _product_code_to_sku(stock: pd.DataFrame) -> dict[str, str]:
    if stock.empty:
        return {}
    mapping = find_columns(stock.columns, SOURCE_SPECS["stock"])
    code_col = mapping.get("product_code", "product_code")
    sku_col = mapping.get("sku", "sku")
    if code_col not in stock.columns or sku_col not in stock.columns:
        return {}
    pairs = stock[[code_col, sku_col]].dropna().copy()
    pairs[code_col] = _clean_key(pairs[code_col])
    pairs[sku_col] = _clean_key(pairs[sku_col])
    pairs = pairs.loc[pairs[code_col].ne("") & pairs[sku_col].ne("")]
    return dict(zip(pairs[code_col], pairs[sku_col]))


def _ads_mapping_match(frames: dict[str, pd.DataFrame]) -> float:
    code_to_sku = _product_code_to_sku(frames.get("stock", pd.DataFrame()))
    if not code_to_sku:
        return 0.0
    total = 0
    matched = 0
    for key in ("ads_auto", "ads_group", "ads_overall"):
        frame = frames.get(key, pd.DataFrame())
        if frame.empty or "product_code" not in frame.columns:
            continue
        codes = _clean_key(frame["product_code"])
        codes = codes[codes.ne("")]
        total += int(codes.nunique())
        matched += int(codes[codes.isin(code_to_sku)].nunique())
    if total == 0:
        return 0.0
    return round(matched / total * 100, 2)


def latest_stock_frame(store: LocalDataStore) -> pd.DataFrame:
    stock = store.read_source("stock")
    if stock.empty or "_submitted_at" not in stock.columns:
        return stock
    latest = str(stock["_submitted_at"].max())
    return stock.loc[stock["_submitted_at"].astype(str).eq(latest)].copy()


def stock_zero_streaks(store: LocalDataStore) -> pd.DataFrame:
    stock = store.read_source("stock")
    if stock.empty or not {"sku", "stock_dc_cikupa", "_submitted_at"} <= set(stock.columns):
        return pd.DataFrame(columns=["sku", "zero_since", "snapshots_zero"])
    work = stock.copy()
    work["_submitted_at"] = snapshot_time(work["_submitted_at"])
    work["sku"] = _clean_key(work["sku"])
    work["stock_dc_cikupa"] = pd.to_numeric(work["stock_dc_cikupa"], errors="coerce").fillna(0)
    work = work.dropna(subset=["_submitted_at"]).sort_values(["sku", "_submitted_at"])
    rows: list[dict[str, object]] = []
    for sku, group in work.groupby("sku", sort=False):
        if not sku:
            continue
        streak = group.loc[group["stock_dc_cikupa"].le(0)]
        if streak.empty or group.iloc[-1]["stock_dc_cikupa"] > 0:
            continue
        # Ambil rangkaian nol terakhir, berhenti saat snapshot sebelumnya stoknya positif.
        latest_zero = []
        for _, row in group.iloc[::-1].iterrows():
            if float(row["stock_dc_cikupa"]) > 0:
                break
            latest_zero.append(row)
        if not latest_zero:
            continue
        zero_since = min(pd.Timestamp(row["_submitted_at"]) for row in latest_zero)
        rows.append({"sku": sku, "zero_since": zero_since, "snapshots_zero": len(latest_zero)})
    return pd.DataFrame(rows)

