"""SKU dikecualikan dan gate promosi (Revisi Final 2D).

promo_eligible dipakai Iklan, Flash sale, dan Exposure:
  stok_dc ≥ prediksi_window + SS  (iklan: "Dibatasi stok" bila stok ≥ SS)
  AND margin_pct ≥ margin_min (bawaan 0% = asal tidak rugi, sama dengan business_targets; flash sale: margin flash ≥ 0)
  AND tingkat_batal_sku_30hari ≤ 15%
  AND SKU tidak dikecualikan
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.core.decision_table import stock_need
from src.core.naming import extract_packing_tag

SEED_EXCLUDED = {"40030033": "Extra Packing Kayu Tambahan"}
SERVICE_HINTS = ("packing", "bubble wrap", "biaya", "ongkir")
CANCEL_LIMIT_PCT = 15.0


def exclusion_suggestions(products: pd.DataFrame, excluded: set[str]) -> pd.DataFrame:
    """Usulan SKU jasa: nama mengandung packing/bubble wrap/biaya/ongkir (user yang mengonfirmasi)."""
    columns = ["sku", "nama", "alasan"]
    rows = [{"sku": sku, "nama": name, "alasan": "Isi awal (SKU jasa)"} for sku, name in SEED_EXCLUDED.items() if sku not in excluded]
    if products is not None and not products.empty and {"sku", "product_name"} <= set(products.columns):
        names = products.drop_duplicates("sku")[["sku", "product_name"]]
        for sku, name in zip(names["sku"].astype(str), names["product_name"].fillna("").astype(str)):
            if sku in excluded or sku in SEED_EXCLUDED:
                continue
            # Label kemasan ("[INCLUDE PACKING KAYU]", "Proteksi Ganda Extra Bubble Wrap") dibuang dulu:
            # produk fisik yang dikirim dengan packing kayu bukan SKU jasa.
            remainder, tag = extract_packing_tag(name)
            lower = remainder.lower()
            hit = next((hint for hint in SERVICE_HINTS if hint in lower), None)
            if hit:
                rows.append({"sku": sku, "nama": name, "alasan": f'Nama berisi "{hit}"'})
            elif tag and len(remainder.split()) <= 2:
                rows.append({"sku": sku, "nama": name, "alasan": f'Nama hanya berisi "{tag}"'})
    return pd.DataFrame(rows, columns=columns)


def drop_excluded(frame: pd.DataFrame, excluded: set[str], column: str = "sku") -> pd.DataFrame:
    """Filter di awal pipeline: SKU dikecualikan keluar dari peringkat, SS, iklan, flash sale, exposure."""
    if frame is None or frame.empty or not excluded or column not in frame.columns:
        return frame
    sku = frame[column].astype(str).str.strip().str.replace(r"\.0+$", "", regex=True)
    return frame.loc[~sku.isin(excluded)]


def cancel_rate_30d(orders_all: pd.DataFrame, today: date, *, key: str = "sku") -> dict[str, float]:
    """Tingkat batal (%) per SKU 30 hari terakhir, dihitung per pesanan."""
    if orders_all is None or orders_all.empty or key not in orders_all.columns or "status" not in orders_all.columns:
        return {}
    from src.ingest import cancelled_status_mask

    times = pd.to_datetime(orders_all["order_time"], errors="coerce")
    end = pd.Timestamp(today)
    part = orders_all.loc[times.ge(end - pd.Timedelta(days=30)) & times.lt(end + pd.Timedelta(days=1))]
    if part.empty:
        return {}
    order = part["order_id"] if "order_id" in part.columns else part.index.to_series()
    frame = pd.DataFrame({"sku": part[key].astype(str), "order": order.astype(str), "batal": cancelled_status_mask(part["status"]).to_numpy()})
    frame = frame.drop_duplicates(["sku", "order"])
    rate = frame.groupby("sku")["batal"].mean() * 100
    return {str(k): float(v) for k, v in rate.items()}


def promo_eligible(
    row,
    *,
    excluded: set[str],
    margin_pct: float | None,
    cancel_pct: float | None,
    margin_min: float = 0.0,
    mode: str = "iklan",
    flash_margin_pct: float | None = None,
) -> tuple[bool, list[str], str]:
    """(lolos, alasan gagal, keputusan). keputusan: Iklankan / Dibatasi stok / Tahan / SKU jasa."""
    sku = str(row.get("sku", ""))
    if sku in excluded:
        return False, ["SKU jasa"], "SKU jasa"
    reasons: list[str] = []
    stok = row.get("stok")
    known = bool(row.get("ada_data_stok", stok is not None and not pd.isna(stok)))
    need = stock_need(row)
    ss = float(row.get("ss", 0) or 0)
    limited = False
    if not known:
        reasons.append("Data stok belum ada")
    else:
        stok = float(stok)
        if stok < need:
            if mode == "iklan" and stok >= ss and stok > 0:
                limited = True
            else:
                reasons.append("Stok kurang")
    if mode == "flash":
        value = flash_margin_pct if flash_margin_pct is not None else margin_pct
        if value is not None and np.isfinite(value) and value < 0:
            reasons.append("Margin minus")
    elif margin_pct is not None and np.isfinite(margin_pct):
        if margin_pct < 0:
            reasons.append("Margin minus")
        elif margin_pct < margin_min:
            reasons.append(f"Margin {margin_pct:.1f}% < {margin_min:.0f}%".replace(".", ","))
    if cancel_pct is not None and np.isfinite(cancel_pct) and cancel_pct > CANCEL_LIMIT_PCT:
        reasons.append(f"Batal tinggi {cancel_pct:.0f}%")
    if reasons:
        return False, reasons, "Tahan · " + ", ".join(reasons).lower()
    if limited:
        return True, [], "Dibatasi stok"
    return True, [], "Iklankan"


def product_label(sku: object, name: object, variant: object) -> str:
    """SKU · nama produk · varian, tidak dipotong."""
    parts = [str(sku or "").strip(), str(name or "").strip()]
    variant = str(variant or "").strip()
    if variant and variant.lower() not in {"nan", "-", "tanpa variasi"}:
        parts.append(variant)
    return " · ".join(p for p in parts if p)


def name_variant(name: object, variant: object) -> str:
    variant = str(variant or "").strip()
    base = str(name or "").strip()
    return f"{base} · {variant}" if variant and variant.lower() not in {"nan", "-", "tanpa variasi"} else base


def momentum_14d(orders: pd.DataFrame, today: date, key: str = "sku") -> dict[str, float]:
    """(QTY 14 hari terakhir − 14 hari sebelumnya) / 14 hari sebelumnya, dibatasi −1..+2."""
    if orders is None or orders.empty or key not in orders.columns:
        return {}
    times = pd.to_datetime(orders["order_time"], errors="coerce").dt.date
    end = today
    recent = orders.loc[(times > end - timedelta(days=14)) & (times <= end)].groupby(orders[key].astype(str))["qty"].sum()
    before = orders.loc[(times > end - timedelta(days=28)) & (times <= end - timedelta(days=14))].groupby(orders[key].astype(str))["qty"].sum()
    out = {}
    for sku in set(recent.index) | set(before.index):
        b = float(before.get(sku, 0.0))
        r = float(recent.get(sku, 0.0))
        out[sku] = float(np.clip((r - b) / b, -1, 2)) if b > 0 else (1.0 if r > 0 else 0.0)
    return out
