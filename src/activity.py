from __future__ import annotations

import numpy as np
import pandas as pd

from src.aggregate import period_start
from src.ingest import (
    cancelled_status_mask,
    clean_sku_series,
    clean_text_series,
    item_key_series,
    normalize_status_series,
    success_status_mask,
    _parse_datetime,
    _parse_number,
    apply_latest_identity,
    map_columns,
    order_revenue,
    attach_order_line_totals,
)

ACTIVITY_GRAINS = ("minggu", "bulan", "kuartal", "semester")

ID_MONTHS = (
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)


def activity_period_start(series: pd.Series, grain: str) -> pd.Series:
    """Awal rentang. Minggu dimulai Senin."""
    dates = pd.to_datetime(series)
    if grain == "minggu":
        return dates.dt.to_period("W-SUN").dt.start_time.dt.normalize()
    if grain in {"bulan", "kuartal", "semester"}:
        return period_start(dates, grain)
    raise ValueError(f"Filter tidak dikenali: {grain}")


def activity_period_label(ts: pd.Timestamp, grain: str) -> str:
    stamp = pd.Timestamp(ts)
    if grain == "minggu":
        end = stamp + pd.Timedelta(days=6)
        start_month = ID_MONTHS[stamp.month - 1]
        end_month = ID_MONTHS[end.month - 1]
        if stamp.year == end.year and stamp.month == end.month:
            return f"{stamp.day}–{end.day} {start_month} {stamp.year}"
        if stamp.year == end.year:
            return f"{stamp.day} {start_month}–{end.day} {end_month} {stamp.year}"
        return f"{stamp.day} {start_month} {stamp.year}–{end.day} {end_month} {end.year}"
    if grain == "bulan":
        return f"{ID_MONTHS[stamp.month - 1]} {stamp.year}"
    if grain == "kuartal":
        quarter = ((stamp.month - 1) // 3) + 1
        return f"Kuartal {quarter} {stamp.year}"
    if grain == "semester":
        half = "Januari–Juni" if stamp.month <= 6 else "Juli–Desember"
        return f"Semester {half} {stamp.year}"
    return str(stamp.date())


def ledger_from_raw(raw: pd.DataFrame) -> pd.DataFrame:
    """Satu baris per produk pada pesanan. Batal dan retur tetap disimpan."""
    if raw is None or raw.empty:
        return pd.DataFrame()
    table = raw.drop(columns=["Nama file"], errors="ignore").drop_duplicates().reset_index(drop=True)
    table.columns = [str(column).strip() for column in table.columns]
    mapping = map_columns(table)
    required = {"order_time", "product_name", "qty"}
    if not required <= set(mapping):
        return pd.DataFrame()

    frame = pd.DataFrame()
    frame["order_time"] = _parse_datetime(table[mapping["order_time"]])
    frame["product_name"] = clean_text_series(table[mapping["product_name"]])
    frame["qty"] = _parse_number(table[mapping["qty"]]).fillna(0).clip(lower=0)
    if "returned_qty" in mapping:
        frame["returned_qty"] = _parse_number(table[mapping["returned_qty"]]).fillna(0).clip(lower=0)
    else:
        frame["returned_qty"] = 0.0
    if "variation" in mapping:
        frame["variation"] = clean_text_series(table[mapping["variation"]])
    else:
        frame["variation"] = ""
    if "sku" in mapping:
        frame["sku"] = clean_sku_series(table[mapping["sku"]])
    elif "parent_sku" in mapping:
        frame["sku"] = clean_sku_series(table[mapping["parent_sku"]])
    else:
        frame["sku"] = ""
    if "unit_price" in mapping:
        frame["unit_price"] = _parse_number(table[mapping["unit_price"]]).fillna(0).clip(lower=0)
    else:
        frame["unit_price"] = 0.0
    frame["line_value"] = frame["unit_price"] * frame["qty"]
    frame["return_value"] = frame["unit_price"] * frame["returned_qty"]
    if "status" in mapping:
        frame["status"] = normalize_status_series(table[mapping["status"]])
    else:
        frame["status"] = ""
    if "order_id" in mapping:
        frame["order_id"] = clean_text_series(table[mapping["order_id"]])
    else:
        frame["order_id"] = ""
    if "order_amount" in mapping:
        frame["order_amount"] = _parse_number(table[mapping["order_amount"]])
    else:
        frame["order_amount"] = frame["line_value"]
    if "cancel_reason" in mapping:
        frame["cancel_reason"] = clean_text_series(table[mapping["cancel_reason"]])
    else:
        frame["cancel_reason"] = ""
    if "return_reason" in mapping:
        frame["return_reason"] = clean_text_series(table[mapping["return_reason"]])
    else:
        frame["return_reason"] = ""
    frame["sales"] = frame["line_value"]
    frame = frame.dropna(subset=["order_time"])
    frame = frame[frame["product_name"].ne("") | frame["sku"].ne("")]
    frame["is_cancel"] = cancelled_status_mask(frame["status"])
    frame["is_success"] = success_status_mask(frame["status"])
    frame["item_key"] = item_key_series(frame)
    frame = frame.drop_duplicates(
        subset=[
            "order_id",
            "order_time",
            "sku",
            "variation",
            "qty",
            "returned_qty",
            "status",
            "line_value",
            "cancel_reason",
            "return_reason",
        ]
    )
    frame = apply_latest_identity(frame)
    frame = attach_order_line_totals(frame, gross_col="line_value")
    return frame.reset_index(drop=True)


def period_options(ledger: pd.DataFrame, grain: str) -> list[tuple[pd.Timestamp, str]]:
    if ledger.empty:
        return []
    starts = activity_period_start(ledger["order_time"], grain).dropna().drop_duplicates().sort_values()
    return [(pd.Timestamp(value), activity_period_label(value, grain)) for value in starts]


def slice_period(ledger: pd.DataFrame, grain: str, start: pd.Timestamp | None) -> pd.DataFrame:
    if ledger.empty or start is None:
        return ledger
    stamps = activity_period_start(ledger["order_time"], grain)
    return ledger.loc[stamps.eq(pd.Timestamp(start))].copy()


def _order_money(lines: pd.DataFrame) -> float:
    """Total Pembayaran sekali tiap No. Pesanan. Kalau kosong, pakai nilai baris."""
    if lines.empty:
        return 0.0
    work = lines.copy()
    blank = work["order_id"].eq("")
    work["_order_key"] = work["order_id"].where(~blank, work.index.astype(str))
    once = work.groupby("_order_key", as_index=False).agg(
        order_amount=("order_amount", "first"),
        line=("line_value", "sum"),
    )
    chosen = once["order_amount"].where(once["order_amount"].fillna(0) > 0, once["line"])
    return float(chosen.fillna(0).sum())


def _unique_orders(lines: pd.DataFrame) -> int:
    if lines.empty:
        return 0
    named = lines["order_id"].ne("")
    count = int(lines.loc[named, "order_id"].nunique())
    count += int((~named).sum())
    return count


def scope_ledger(
    ledger: pd.DataFrame,
    *,
    include_cancel: bool = True,
    include_return: bool = True,
) -> pd.DataFrame:
    """Samakan hitungan dengan Ringkasan.

    Tanpa batal: baris status batal keluar. Tanpa retur: QTY menjadi Jumlah
    dikurangi Returned quantity, dan baris yang habis diretur keluar.
    """
    if ledger is None or ledger.empty:
        return ledger
    work = ledger
    if not include_cancel and "is_cancel" in work.columns:
        work = work.loc[~work["is_cancel"]]
    if not include_return and "returned_qty" in work.columns:
        work = work.copy()
        work["qty"] = (work["qty"] - work["returned_qty"]).clip(lower=0)
        if "unit_price" in work.columns:
            # Nilai baris bersih: order_revenue memakai porsi ini untuk mengurangi retur sebagian.
            work["sales"] = work["unit_price"] * work["qty"]
        work = work.loc[work["qty"] > 0]
    elif "qty" in work.columns:
        work = work.loc[work["qty"] > 0]
    return work.reset_index(drop=True)


def activity_report(ledger: pd.DataFrame) -> tuple[dict[str, float], pd.DataFrame, pd.DataFrame]:
    """Ringkasan sederhana dan satu daftar SKU retur serta batal."""
    empty_status = pd.DataFrame(columns=["Status pesanan", "No. Pesanan", "Kontribusi"])
    empty_sku = pd.DataFrame(
        columns=[
            "Peringkat",
            "SKU",
            "Product Name",
            "Product variance",
            "Qty retur",
            "Nominal retur",
            "Alasan retur",
            "Qty batal",
            "Invoice batal",
            "Nominal batal",
            "Alasan batal",
        ]
    )
    if ledger.empty:
        summary = {
            "orders": 0,
            "sku_sold": 0,
            "sku_all": 0,
            "sales_volume": 0.0,
            "invoice_cancel": 0,
            "nominal_cancel": 0.0,
            "sales_return": 0.0,
            "nominal_return": 0.0,
            "sku_issue": 0,
        }
        return summary, empty_status, empty_sku

    cancel = ledger.loc[ledger["is_cancel"]]
    active = ledger.loc[~ledger["is_cancel"]]
    sold = active.loc[active["qty"] > 0]
    summary = {
        "orders": _unique_orders(ledger),
        "sku_sold": int(sold["item_key"].nunique()),
        "sku_all": int(ledger["item_key"].nunique()),
        "sales_volume": order_revenue(ledger),
        "invoice_cancel": _unique_orders(cancel),
        "nominal_cancel": _order_money(cancel),
        "sales_return": float(ledger["returned_qty"].sum()),
        "nominal_return": float(ledger["return_value"].sum()),
        "sku_issue": 0,
    }
    status_rows = []
    for status, group in ledger.groupby(ledger["status"].where(ledger["status"].ne(""), "Tanpa status"), sort=False):
        status_rows.append({"Status pesanan": status, "No. Pesanan": _unique_orders(group)})
    status_table = pd.DataFrame(status_rows).sort_values(["No. Pesanan", "Status pesanan"], ascending=[False, True])
    total_orders = int(status_table["No. Pesanan"].sum()) if not status_table.empty else 0
    if total_orders > 0:
        status_table["Kontribusi"] = status_table["No. Pesanan"] / total_orders * 100
    else:
        status_table["Kontribusi"] = 0.0

    work = ledger.copy()
    work["qty_batal"] = np.where(work["is_cancel"], work["qty"], 0.0)
    work["nominal_batal"] = np.where(work["is_cancel"], work["line_value"], 0.0)
    work["cancel_order"] = np.where(work["is_cancel"] & work["order_id"].ne(""), work["order_id"], np.nan)
    work["alasan_batal"] = np.where(
        work["is_cancel"],
        work["cancel_reason"].where(work["cancel_reason"].ne(""), "Tanpa alasan"),
        "",
    )
    work["alasan_retur"] = np.where(
        work["returned_qty"] > 0,
        work["return_reason"].where(work["return_reason"].ne(""), "Tanpa alasan"),
        "",
    )
    grouped = work.groupby(["sku", "variation", "alasan_batal", "alasan_retur"], as_index=False).agg(
        product_name=("product_name", "first"),
        qty_retur=("returned_qty", "sum"),
        nominal_retur=("return_value", "sum"),
        qty_batal=("qty_batal", "sum"),
        nominal_batal=("nominal_batal", "sum"),
        invoice_batal=("cancel_order", "nunique"),
    )
    grouped = grouped.loc[
        (grouped["qty_retur"] > 0) | (grouped["qty_batal"] > 0) | (grouped["invoice_batal"] > 0)
    ].copy()
    grouped = grouped.sort_values(
        ["qty_retur", "nominal_retur", "qty_batal", "nominal_batal", "sku"],
        ascending=[False, False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    summary["sku_issue"] = int(len(grouped))
    if grouped.empty:
        return summary, status_table.reset_index(drop=True), empty_sku
    sheet = pd.DataFrame(
        {
            "Peringkat": np.arange(1, len(grouped) + 1),
            "SKU": grouped["sku"].where(grouped["sku"].ne(""), "Tanpa SKU"),
            "Product Name": grouped["product_name"].where(grouped["product_name"].ne(""), "Tanpa nama"),
            "Product variance": grouped["variation"].where(grouped["variation"].ne(""), "Tanpa variasi"),
            "Qty retur": grouped["qty_retur"].round().astype(int),
            "Nominal retur": grouped["nominal_retur"].round().astype(int),
            "Alasan retur": grouped["alasan_retur"],
            "Qty batal": grouped["qty_batal"].round().astype(int),
            "Invoice batal": grouped["invoice_batal"].astype(int),
            "Nominal batal": grouped["nominal_batal"].round().astype(int),
            "Alasan batal": grouped["alasan_batal"],
        }
    )
    return summary, status_table.reset_index(drop=True), sheet


def focus_summary(
    summary: dict[str, float],
    *,
    include_return: bool,
    include_cancel: bool,
    return_only: bool,
    cancel_only: bool,
) -> dict[str, float]:
    """Nominal retur hanya saat filter Return. Nominal batal hanya saat filter batal."""
    result = dict(summary)
    if return_only:
        result["sales_volume"] = float(result["nominal_return"])
        result["invoice_cancel"] = 0
        result["nominal_cancel"] = 0.0
        result["sku_sold"] = int(result["sku_all"])
        return result
    if cancel_only:
        result["sales_return"] = 0.0
        result["nominal_return"] = 0.0
        result["sku_sold"] = int(result["sku_all"])
        return result
    if not include_return:
        result["sales_return"] = 0.0
        result["nominal_return"] = 0.0
    if not include_cancel:
        result["invoice_cancel"] = 0
        result["nominal_cancel"] = 0.0
    return result


def append_total_row(
    frame: pd.DataFrame,
    label_column: str,
    sum_columns: list[str],
    label: str = "Total",
) -> pd.DataFrame:
    """Tambah satu baris jumlah di bawah tabel."""
    if frame.empty or label_column not in frame.columns:
        return frame
    total = {column: "" for column in frame.columns}
    total[label_column] = label
    for column in sum_columns:
        if column not in frame.columns:
            continue
        numeric = pd.to_numeric(frame[column], errors="coerce")
        total[column] = float(numeric.fillna(0).sum())
    return pd.concat([frame, pd.DataFrame([total])], ignore_index=True)


def cancel_contribution(ledger: pd.DataFrame) -> tuple[dict[str, float], pd.DataFrame]:
    """Bagian invoice batal terhadap seluruh invoice pada rentang, per status dan alasan."""
    columns = [
        "Status batal",
        "Alasan pembatalan",
        "Invoice",
        "Nominal",
        "Kontribusi invoice",
        "Kontribusi nominal",
    ]
    total_invoice = _unique_orders(ledger)
    total_nominal = _order_money(ledger)
    base = {
        "total_invoice": total_invoice,
        "total_nominal": total_nominal,
        "invoice_cancel": 0,
        "nominal_cancel": 0.0,
    }
    if ledger.empty or total_invoice <= 0:
        return base, pd.DataFrame(columns=columns)
    cancel = ledger.loc[ledger["is_cancel"]].copy()
    base["invoice_cancel"] = _unique_orders(cancel)
    base["nominal_cancel"] = _order_money(cancel)
    if cancel.empty:
        return base, pd.DataFrame(columns=columns)
    cancel["alasan"] = cancel["cancel_reason"].where(cancel["cancel_reason"].ne(""), "Tanpa alasan")
    cancel["status_batal"] = cancel["status"].where(cancel["status"].ne(""), "Batal")
    rows = []
    for (status, reason), group in cancel.groupby(["status_batal", "alasan"], sort=False):
        invoices = _unique_orders(group)
        nominal = _order_money(group)
        invoice_share = invoices / total_invoice * 100 if total_invoice else 0.0
        nominal_share = nominal / total_nominal * 100 if total_nominal else 0.0
        rows.append(
            {
                "Status batal": status,
                "Alasan pembatalan": reason,
                "Invoice": invoices,
                "Nominal": int(round(nominal)),
                "Kontribusi invoice": invoice_share,
                "Kontribusi nominal": nominal_share,
            }
        )
    table = pd.DataFrame(rows).sort_values(
        ["Nominal", "Invoice", "Alasan pembatalan"],
        ascending=[False, False, True],
        kind="mergesort",
    )
    return base, table.reset_index(drop=True)


def unpaid_buyer_table(
    source: pd.DataFrame,
    *,
    months: list[str] | None = None,
    start=None,
    end=None,
) -> pd.DataFrame:
    """Satu akun yang batal karena belum bayar. Tiap No. Pesanan tetap satu baris.

    Nama akun ditulis sekali. Bila akun itu punya pesanan lain untuk SKU yang sama
    dan pesanannya bukan batal belum bayar, pesanan itu tidak masuk.
    """
    columns = [
        "No",
        "Nama akun pembeli",
        "Tanggal pembelian",
        "No. Pesanan",
        "SKU",
        "Product Name",
        "Product variance",
        "QTY",
        "Sales volume",
    ]
    empty = pd.DataFrame(columns=columns)
    if source is None or source.empty:
        return empty
    table = source.drop(columns=["Nama file"], errors="ignore")
    table.columns = [str(column).strip() for column in table.columns]
    mapping = map_columns(table)
    needed = {"order_id", "order_time", "status", "cancel_reason", "buyer", "qty"}
    if not needed <= set(mapping):
        return empty
    frame = pd.DataFrame()
    frame["order_time"] = _parse_datetime(table[mapping["order_time"]])
    frame["order_id"] = clean_text_series(table[mapping["order_id"]])
    frame["buyer"] = clean_text_series(table[mapping["buyer"]])
    frame["status"] = normalize_status_series(table[mapping["status"]])
    frame["cancel_reason"] = clean_text_series(table[mapping["cancel_reason"]])
    frame["qty"] = _parse_number(table[mapping["qty"]]).fillna(0).clip(lower=0)
    if "unit_price" in mapping:
        frame["unit_price"] = _parse_number(table[mapping["unit_price"]]).fillna(0).clip(lower=0)
    else:
        frame["unit_price"] = 0.0
    frame["line_sales"] = frame["unit_price"] * frame["qty"]
    if "sku" in mapping:
        frame["sku"] = clean_sku_series(table[mapping["sku"]])
    elif "parent_sku" in mapping:
        frame["sku"] = clean_sku_series(table[mapping["parent_sku"]])
    else:
        frame["sku"] = ""
    frame["product_name"] = clean_text_series(table[mapping["product_name"]]) if "product_name" in mapping else ""
    frame["variation"] = clean_text_series(table[mapping["variation"]]) if "variation" in mapping else ""
    frame = frame.dropna(subset=["order_time"])
    frame = frame.loc[frame["order_id"].ne("")].copy()
    if frame.empty:
        return empty
    frame["month"] = frame["order_time"].dt.to_period("M").astype(str)
    in_period = pd.Series(True, index=frame.index)
    if months:
        in_period &= frame["month"].isin(list(months))
    if start is not None and end is not None:
        days = frame["order_time"].dt.normalize()
        in_period &= days.ge(pd.Timestamp(start)) & days.le(pd.Timestamp(end))
    if not bool(in_period.any()):
        return empty
    reason = frame["cancel_reason"].str.lower()
    unpaid = cancelled_status_mask(frame["status"]) & (
        reason.str.contains("belum dibayar", regex=False) | reason.str.contains("belum bayar", regex=False)
    )
    frame["unpaid"] = unpaid
    frame["item_key"] = item_key_series(frame)
    frame["buyer_key"] = frame["buyer"].str.casefold()
    blank_buyer = frame["buyer_key"].eq("")
    frame.loc[blank_buyer, "buyer_key"] = "order:" + frame.loc[blank_buyer, "order_id"]
    keys = [frame["buyer_key"], frame["item_key"]]
    paid_any = (~cancelled_status_mask(frame["status"]) & in_period).groupby(keys).transform("any")
    unpaid_any = frame["unpaid"].groupby(keys).transform("any")
    frame["_group"] = frame.groupby(keys, sort=False).ngroup()
    candidates = frame.loc[unpaid_any & ~paid_any & frame["unpaid"] & in_period]
    rows = []
    if not candidates.empty:
        orders = (
            candidates.groupby(["_group", "buyer_key", "item_key", "order_id"], as_index=False, sort=True)
            .agg(
                order_time=("order_time", "max"),
                sku=("sku", "last"),
                product_name=("product_name", "last"),
                variation=("variation", "last"),
                qty=("qty", "sum"),
                line_sales=("line_sales", "sum"),
                buyer=("buyer", "last"),
            )
            .sort_values(["_group", "order_time"], kind="mergesort")
        )
        for record in orders.itertuples(index=False):
            product = str(record.product_name).strip() or "Tanpa nama"
            variation = str(record.variation).strip() or "Tanpa variasi"
            rows.append(
                {
                    "_buyer": str(record.buyer_key),
                    "_name": str(record.buyer).strip() or "Tanpa akun",
                    "_time": pd.Timestamp(record.order_time),
                    "Tanggal pembelian": pd.Timestamp(record.order_time).strftime("%d-%m-%Y"),
                    "No. Pesanan": str(record.order_id),
                    "SKU": str(record.sku).strip() or "Tanpa SKU",
                    "Product Name": product,
                    "Product variance": variation,
                    "QTY": int(round(float(record.qty))),
                    "Sales volume": int(round(float(record.line_sales))),
                }
            )
    if not rows:
        return empty
    result = pd.DataFrame(rows)
    latest = result.groupby("_buyer", as_index=False)["_time"].max().rename(columns={"_time": "_latest"})
    result = result.merge(latest, on="_buyer", how="left")
    result = result.sort_values(
        ["_latest", "_buyer", "_time", "No. Pesanan"],
        ascending=[False, True, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    numbers: list[str] = []
    names: list[str] = []
    seen: set[str] = set()
    number = 0
    order_counts = result.groupby("_buyer")["No. Pesanan"].nunique()
    for buyer, name in zip(result["_buyer"], result["_name"]):
        if buyer not in seen:
            number += 1
            seen.add(buyer)
            numbers.append(str(number))
            names.append(f"{name} ({int(order_counts[buyer])} pesanan)")
        else:
            numbers.append("")
            names.append("")
    result.insert(0, "No", numbers)
    result.insert(1, "Nama akun pembeli", names)
    return result.drop(columns=["_buyer", "_name", "_time", "_latest"]).reset_index(drop=True)
