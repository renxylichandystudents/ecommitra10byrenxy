"""Satu-satunya sumber angka pesanan, batal, retur, sales, belum bayar, ROAS, dan cakupan SKU.

Ringkasan, Data, Folder data, Laporan, dan Rekomendasi memanggil fungsi di sini agar angka
periode yang sama selalu identik di semua halaman.

Fungsi menerima dua bentuk frame transaksi:
- frame Data (`src.activity.ledger_from_raw`): `qty` = Jumlah, `returned_qty`, `line_value`, `return_value`;
- frame analisis (`src.ingest.clean_order_frame`): `gross_qty` = Jumlah, `qty` = bersih retur, `gross_sales`.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from src.ingest import cancelled_status_mask, item_key_series

BLANK_IDS = {"", "nan", "none", "-"}
UNPAID_HINTS = ("belum dibayar", "belum bayar")

METRIC_DEFINITIONS: dict[str, str] = {
    "pesanan_semua": "Jumlah No. Pesanan unik pada periode, semua status.",
    "sales_bruto": "Total Pembayaran semua status, dihitung sekali tiap No. Pesanan.",
    "pesanan_batal": "Jumlah No. Pesanan unik berstatus batal (termasuk pembatalan otomatis karena belum bayar).",
    "nominal_batal": "Total Pembayaran pesanan batal, sekali tiap No. Pesanan.",
    "belum_bayar": (
        "Pesanan batal karena belum dibayar. Pembeli yang punya pesanan terbayar untuk SKU yang sama "
        "pada periode ini tidak dihitung."
    ),
    "belum_bayar_akun": "Jumlah akun pembeli unik pada pesanan belum bayar.",
    "retur_unit": "Jumlah unit pada baris pengembalian yang disetujui (kolom Returned quantity).",
    "nominal_retur": "Returned quantity × Harga Setelah Diskon pada baris pengembalian.",
    "pesanan_retur_penuh": "Pesanan yang semua baris produknya diretur penuh.",
    "pesanan_bersih": "Pesanan semua status − pesanan batal − pesanan retur penuh.",
    "sales_bersih": "Sales bruto − nominal batal − nominal retur.",
    "qty_bersih": "QTY pesanan selain batal − unit retur.",
    "tingkat_batal": "Pesanan batal ÷ pesanan semua status.",
    "biaya_iklan": "Biaya iklan produk pada periode, setelah baris ringkasan laporan iklan dibuang.",
    "omzet_iklan": "Omzet iklan per SKU, dibatasi sales bersih SKU itu pada periode yang sama.",
    "roas": "Omzet iklan ÷ biaya iklan.",
    "sku_terjual_bersih": "SKU dengan QTY bersih > 0 pada periode.",
    "sku_non_batal": "SKU yang punya pesanan selain batal pada periode (termasuk yang kemudian diretur).",
    "sku_data_latih": "SKU yang pernah terjual (selain batal) di seluruh data latih terpilih.",
    "sku_katalog": "SKU di data produk (snapshot stok terakhir).",
}

METRIC_LABELS: dict[str, str] = {
    "pesanan_semua": "Pesanan semua status",
    "sales_bruto": "Sales bruto",
    "pesanan_batal": "Pesanan batal",
    "nominal_batal": "Nominal batal",
    "belum_bayar": "Pesanan belum bayar",
    "belum_bayar_akun": "Akun belum bayar",
    "retur_unit": "Unit retur",
    "nominal_retur": "Nominal retur",
    "pesanan_retur_penuh": "Pesanan retur penuh",
    "pesanan_bersih": "Pesanan bersih",
    "sales_bersih": "Sales bersih",
    "qty_bersih": "QTY bersih",
    "tingkat_batal": "Tingkat batal",
    "biaya_iklan": "Biaya iklan",
    "omzet_iklan": "Omzet iklan",
    "roas": "ROAS",
    "sku_terjual_bersih": "SKU terjual bersih",
    "sku_non_batal": "SKU non-batal",
    "sku_data_latih": "SKU data latih",
    "sku_katalog": "SKU katalog",
}

EMPTY_ORDER_METRICS: dict[str, float] = {
    "pesanan_semua": 0,
    "sales_bruto": 0.0,
    "pesanan_batal": 0,
    "nominal_batal": 0.0,
    "belum_bayar": 0,
    "belum_bayar_akun": 0,
    "belum_bayar_semua": 0,
    "retur_unit": 0.0,
    "nominal_retur": 0.0,
    "pesanan_retur": 0,
    "pesanan_retur_penuh": 0,
    "pesanan_bersih": 0,
    "sales_bersih": 0.0,
    "qty_bersih": 0.0,
    "tingkat_batal": 0.0,
}


def _num(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default).astype(float)


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=object)
    from src.ingest import via_unique

    def _clean(part: pd.Series) -> pd.Series:
        values = part.fillna("").astype(str).str.strip()
        return values.mask(values.str.lower().isin(BLANK_IDS), "")

    return via_unique(frame[column], _clean)


def normalize_lines(frame: pd.DataFrame | None) -> pd.DataFrame:
    """Satu baris per produk pada pesanan, dengan kolom baku untuk semua metrik."""
    columns = [
        "order_id", "order_key", "order_time", "sku", "item_key", "product_name", "variation",
        "status", "is_cancel", "cancel_reason", "buyer", "gross_qty", "returned_qty",
        "line_value", "return_value", "order_amount",
    ]
    if frame is None or frame.empty:
        return pd.DataFrame(columns=columns)
    work = frame
    out = pd.DataFrame(index=work.index)
    out["order_id"] = _text(work, "order_id")
    out["order_key"] = out["order_id"].where(out["order_id"].ne(""), "baris:" + work.index.astype(str))
    out["order_time"] = pd.to_datetime(work["order_time"], errors="coerce") if "order_time" in work.columns else pd.NaT
    for column in ("sku", "product_name", "variation", "status", "cancel_reason", "buyer"):
        out[column] = _text(work, column)
    out["item_key"] = work["item_key"].astype(str) if "item_key" in work.columns else item_key_series(out)
    if "is_cancel" in work.columns:
        out["is_cancel"] = work["is_cancel"].fillna(False).astype(bool)
    else:
        out["is_cancel"] = cancelled_status_mask(out["status"])

    gross = _num(work, "gross_qty") if "gross_qty" in work.columns else _num(work, "qty")
    out["gross_qty"] = gross.clip(lower=0)
    out["returned_qty"] = _num(work, "returned_qty").clip(lower=0)
    if "gross_sales" in work.columns:
        line = _num(work, "gross_sales")
    elif "line_value" in work.columns:
        line = _num(work, "line_value")
    elif "unit_price" in work.columns:
        line = _num(work, "unit_price") * out["gross_qty"]
    else:
        line = _num(work, "sales")
    out["line_value"] = line.clip(lower=0)
    unit = np.where(out["gross_qty"] > 0, out["line_value"] / out["gross_qty"].where(out["gross_qty"] > 0, 1.0), 0.0)
    out["return_value"] = unit * np.minimum(out["returned_qty"], out["gross_qty"])
    amount = work["order_amount"] if "order_amount" in work.columns else pd.Series(np.nan, index=work.index)
    out["order_amount"] = pd.to_numeric(amount, errors="coerce")
    return out.reset_index(drop=True)


def slice_dates(lines: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    """Baris dengan tanggal pesanan di [start, end] (inklusif, per hari)."""
    if lines.empty or (start is None and end is None):
        return lines
    day = pd.to_datetime(lines["order_time"], errors="coerce").dt.normalize()
    keep = day.notna()
    if start is not None:
        keep &= day >= pd.Timestamp(start).normalize()
    if end is not None:
        keep &= day <= pd.Timestamp(end).normalize()
    return lines.loc[keep]


def _order_money(lines: pd.DataFrame) -> float:
    """Total Pembayaran sekali tiap No. Pesanan; bila kosong/0, jumlah nilai baris pesanan itu."""
    if lines.empty:
        return 0.0
    once = lines.groupby("order_key", sort=False).agg(amount=("order_amount", "first"), line=("line_value", "sum"))
    chosen = once["amount"].where(once["amount"].fillna(0) > 0, once["line"])
    return float(chosen.fillna(0).sum())


def _unpaid(lines: pd.DataFrame) -> tuple[int, int, int]:
    """(pesanan belum bayar, akun unik, semua pesanan batal beralasan belum bayar)."""
    named = lines.loc[lines["order_id"].ne("")]
    if named.empty:
        return 0, 0, 0
    reason = named["cancel_reason"].str.lower()
    unpaid = named["is_cancel"] & reason.apply(lambda text: any(hint in text for hint in UNPAID_HINTS))
    if not bool(unpaid.any()):
        return 0, 0, 0
    all_unpaid = int(named.loc[unpaid, "order_id"].nunique())
    buyer = named["buyer"].str.casefold()
    buyer = buyer.where(buyer.ne(""), "order:" + named["order_id"])
    keys = [buyer, named["item_key"]]
    paid_any = (~named["is_cancel"]).groupby(keys).transform("any")
    picked = unpaid & ~paid_any
    orders = int(named.loc[picked, "order_id"].nunique())
    accounts = int(buyer.loc[picked].nunique())
    return orders, accounts, all_unpaid


def order_metrics(frame: pd.DataFrame | None, start=None, end=None, *, normalized: bool = False) -> dict[str, float]:
    """Angka pesanan periode [start, end]. `frame` berisi semua status (batal & retur tidak dibuang)."""
    lines = frame if normalized else normalize_lines(frame)
    lines = slice_dates(lines, start, end)
    if lines is None or lines.empty:
        return dict(EMPTY_ORDER_METRICS)
    cancel = lines.loc[lines["is_cancel"]]
    active = lines.loc[~lines["is_cancel"]]
    returned = active.loc[active["returned_qty"] > 0]
    pesanan_semua = int(lines["order_key"].nunique())
    pesanan_batal = int(cancel["order_key"].nunique())
    sales_bruto = _order_money(lines)
    nominal_batal = _order_money(cancel)
    retur_unit = float(returned["returned_qty"].sum())
    nominal_retur = float(returned["return_value"].sum())
    if active.empty:
        full_orders = 0
    else:
        fully = (active["gross_qty"] > 0) & (active["returned_qty"] >= active["gross_qty"])
        full_orders = int(fully.groupby(active["order_key"]).all().sum())
    unpaid_orders, unpaid_accounts, unpaid_all = _unpaid(lines)
    return {
        "pesanan_semua": pesanan_semua,
        "sales_bruto": sales_bruto,
        "pesanan_batal": pesanan_batal,
        "nominal_batal": nominal_batal,
        "belum_bayar": unpaid_orders,
        "belum_bayar_akun": unpaid_accounts,
        "belum_bayar_semua": unpaid_all,
        "retur_unit": retur_unit,
        "nominal_retur": nominal_retur,
        "pesanan_retur": int(returned["order_key"].nunique()),
        "pesanan_retur_penuh": full_orders,
        "pesanan_bersih": pesanan_semua - pesanan_batal - full_orders,
        "sales_bersih": sales_bruto - nominal_batal - nominal_retur,
        "qty_bersih": float(active["gross_qty"].sum()) - retur_unit,
        "tingkat_batal": pesanan_batal / pesanan_semua if pesanan_semua else 0.0,
    }


def net_sku_sales(frame: pd.DataFrame | None, start=None, end=None, *, normalized: bool = False) -> pd.DataFrame:
    """Sales & QTY bersih per SKU (selain batal, dikurangi retur). Kolom: sku, order_time, sales, qty."""
    lines = frame if normalized else normalize_lines(frame)
    lines = slice_dates(lines, start, end)
    if lines is None or lines.empty:
        return pd.DataFrame(columns=["sku", "order_time", "sales", "qty"])
    active = lines.loc[~lines["is_cancel"]]
    return pd.DataFrame(
        {
            "sku": active["sku"],
            "order_time": active["order_time"],
            "sales": active["line_value"] - active["return_value"],
            "qty": active["gross_qty"] - np.minimum(active["returned_qty"], active["gross_qty"]),
        }
    ).reset_index(drop=True)


def ads_metrics(ads_frames, stock_frame, frame: pd.DataFrame | None, start=None, end=None) -> dict[str, float]:
    """Biaya, omzet, dan ROAS iklan pada periode yang sama dengan angka pesanan."""
    from src.core.ads import attribute_ads

    if start is None and end is None and frame is not None and not frame.empty and "order_time" in frame.columns:
        stamps = pd.to_datetime(frame["order_time"], errors="coerce")
        start, end = stamps.min(), stamps.max()
    lines = net_sku_sales(frame, start, end)
    result = attribute_ads(list(ads_frames or []), stock_frame, orders=lines, start=start, end=end)
    cost, sales = result.cost, result.sales
    product_sales = float(lines["sales"].sum()) if not lines.empty else 0.0
    return {
        "biaya_iklan": cost,
        "omzet_iklan": sales,
        "roas": sales / cost if cost > 0 else float("nan"),
        # Pembanding porsi iklan: dasar sama dengan batas omzet iklan per SKU (Harga Setelah Diskon × QTY, tanpa batal, dikurangi retur).
        "sales_produk_bersih": product_sales,
        "porsi_sales_iklan_pct": sales / product_sales * 100 if product_sales > 0 else float("nan"),
        "biaya_iklan_file": result.file_cost,
        "biaya_iklan_tanpa_sku": result.unmapped_cost,
        "result": result,
    }


def _sku_set(values: pd.Series) -> set[str]:
    text = values.fillna("").astype(str).str.strip().str.replace(r"^(\d+)\.0+$", r"\1", regex=True)
    return set(text[~text.str.lower().isin(BLANK_IDS)])


def sku_coverage(
    frame: pd.DataFrame | None,
    start=None,
    end=None,
    *,
    training: pd.DataFrame | None = None,
    catalog: pd.DataFrame | None = None,
) -> dict[str, int]:
    """Empat definisi jumlah SKU yang dipakai di aplikasi."""
    lines = slice_dates(normalize_lines(frame), start, end)
    active = lines.loc[~lines["is_cancel"]] if not lines.empty else lines
    if active.empty:
        sold, non_cancel = 0, 0
    else:
        net_qty = (active["gross_qty"] - np.minimum(active["returned_qty"], active["gross_qty"])).groupby(active["item_key"]).sum()
        sold = int((net_qty > 0).sum())
        non_cancel = int(active["item_key"].nunique())
    train_lines = normalize_lines(training) if training is not None else normalize_lines(frame)
    train_active = train_lines.loc[~train_lines["is_cancel"]] if not train_lines.empty else train_lines
    catalog_count = 0
    if catalog is not None and not catalog.empty and "sku" in catalog.columns:
        snap = catalog
        if "_submitted_at" in snap.columns:
            stamp = snap["_submitted_at"].astype(str)
            snap = snap.loc[stamp.eq(stamp.max())]
        catalog_count = len(_sku_set(snap["sku"]))
    return {
        "sku_terjual_bersih": sold,
        "sku_non_batal": non_cancel,
        "sku_data_latih": int(train_active["item_key"].nunique()) if not train_active.empty else 0,
        "sku_katalog": catalog_count,
    }


def legacy_summary_sales(frame: pd.DataFrame | None, start=None, end=None, *, normalized: bool = False) -> float:
    """Sales kartu Ringkasan sebelum revisi: Total Pembayaran pesanan non-batal yang masih punya QTY setelah retur."""
    lines = slice_dates(frame if normalized else normalize_lines(frame), start, end)
    if lines.empty:
        return 0.0
    kept = lines.loc[~lines["is_cancel"] & (lines["gross_qty"] > lines["returned_qty"])]
    return _order_money(kept)


def sales_gap_breakdown(frame: pd.DataFrame | None, start=None, end=None) -> dict[str, object]:
    """Uraikan selisih sales Ringkasan lama dan sales bersih (bruto − batal − retur).

    lama − bersih = Σ nominal retur pada pesanan yang masih punya baris tersisa
                    − Σ (Total Pembayaran − nominal retur) pada pesanan yang seluruh barisnya habis diretur.
    """
    lines = slice_dates(normalize_lines(frame), start, end)
    metrics = order_metrics(lines, normalized=True)
    legacy = legacy_summary_sales(lines, normalized=True)
    active = lines.loc[~lines["is_cancel"]] if not lines.empty else lines
    detail = pd.DataFrame(columns=["No. Pesanan", "Jenis", "Total Pembayaran", "Nominal retur", "Pengaruh ke selisih"])
    partial_sum = full_sum = 0.0
    if not active.empty:
        remaining = (active["gross_qty"] > active["returned_qty"]).groupby(active["order_key"]).any()
        has_return = (active["returned_qty"] > 0).groupby(active["order_key"]).any()
        per_order = active.groupby("order_key").agg(
            order_id=("order_id", "first"),
            amount=("order_amount", "first"),
            line=("line_value", "sum"),
            retur=("return_value", "sum"),
        )
        per_order["amount"] = per_order["amount"].where(per_order["amount"].fillna(0) > 0, per_order["line"])
        partial = per_order.loc[has_return & remaining]
        full = per_order.loc[has_return & ~remaining]
        partial_sum = float(partial["retur"].sum())
        full_sum = float((full["amount"] - full["retur"]).sum())
        rows = [
            {"No. Pesanan": r.order_id, "Jenis": "Retur sebagian", "Total Pembayaran": r.amount, "Nominal retur": r.retur, "Pengaruh ke selisih": r.retur}
            for r in partial.itertuples()
        ] + [
            {"No. Pesanan": r.order_id, "Jenis": "Retur penuh", "Total Pembayaran": r.amount, "Nominal retur": r.retur, "Pengaruh ke selisih": -(r.amount - r.retur)}
            for r in full.itertuples()
        ]
        if rows:
            detail = pd.DataFrame(rows).sort_values("Pengaruh ke selisih", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
    return {
        "sales_lama": legacy,
        "sales_bersih": metrics["sales_bersih"],
        "selisih": legacy - metrics["sales_bersih"],
        "retur_sebagian": partial_sum,
        "retur_penuh_ongkir_voucher": full_sum,
        "detail": detail,
    }


def period_bounds(frame: pd.DataFrame | None) -> tuple[date | None, date | None]:
    if frame is None or frame.empty or "order_time" not in frame.columns:
        return None, None
    stamps = pd.to_datetime(frame["order_time"], errors="coerce").dropna()
    if stamps.empty:
        return None, None
    return stamps.min().date(), stamps.max().date()
