from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import pandas as pd

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "order_id": (
        "no. pesanan",
        "no pesanan",
        "order id",
        "orderid",
        "nomor pesanan",
    ),
    "status": (
        "status pesanan",
        "order status",
        "status",
    ),
    "order_time": (
        "waktu pesanan dibuat",
        "waktu pembayaran dilakukan",
        "order create time",
        "create time",
        "tanggal pesanan",
        "waktu pesanan",
        "order time",
        "date",
        "tanggal",
    ),
    "sku": (
        "nomor referensi sku",
        "sku reference",
        "seller sku",
    ),
    "parent_sku": (
        "sku induk",
        "parent sku",
    ),
    "product_name": (
        "nama produk",
        "product name",
        "nama barang",
        "item name",
    ),
    "variation": (
        "nama variasi",
        "variation name",
        "variasi",
        "variant",
    ),
    "qty": (
        "jumlah",
        "quantity",
        "qty",
        "jumlah produk di pesan",
        "jumlah produk dipesan",
    ),
    "returned_qty": (
        "returned quantity",
        "jumlah dikembalikan",
        "jumlah retur",
    ),
    "unit_price": (
        "harga setelah diskon",
        "harga awal",
        "harga",
        "product price",
        "harga satuan",
    ),
    "sales": (
        "total harga",
        "total harga produk",
        "subtotal",
        "sales",
        "omzet",
        "amount",
        "grand total",
    ),
    "order_amount": (
        "total pembayaran",
        "total payment",
    ),
}

VALID_STATUS_HINTS = (
    "selesai",
    "completed",
    "complete",
    "dikirim",
    "shipped",
    "to ship",
    "to receive",
    "sedang dikirim",
    "perlu dikirim",
    "processed",
    "processing",
    "paid",
    "dibayar",
)

CANCEL_HINTS = (
    "batal",
    "cancel",
    "cancelled",
    "canceled",
    "unpaid",
    "belum bayar",
)


DATE_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
)


def _parse_datetime(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    remaining = parsed.isna()
    for fmt in DATE_FORMATS:
        if not remaining.any():
            break
        attempt = pd.to_datetime(text[remaining], format=fmt, errors="coerce")
        parsed.loc[remaining] = attempt
        remaining = parsed.isna()
    if remaining.any():
        fallback = pd.to_datetime(text[remaining], errors="coerce", dayfirst=True)
        parsed.loc[remaining] = fallback
    return parsed


_RETURN_WINDOW = re.compile(
    r",?\s*namun pembeli masih dapat mengajukan pengembalian"
    r"(?:\s+hingga\s+\d{4}-\d{2}-\d{2})?\.?$",
    re.IGNORECASE,
)


def _parse_number_token(value: str) -> float:
    """Angka laporan Shopee, termasuk format Indonesia 1.226.842 dan 49.000."""
    text = str(value).strip().replace(" ", "")
    if text.lower() in {"", "nan", "none", "-", "—"}:
        return float("nan")
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    text = text.strip("()").lstrip("+-")
    if text.lower().startswith("rp"):
        text = text[2:]
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            text = "".join(parts)
        else:
            text = text.replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    elif text.count(".") == 1:
        left, right = text.split(".")
        if right.isdigit() and len(right) == 3 and left.isdigit():
            text = left + right
    try:
        number = float(text)
    except ValueError:
        return float("nan")
    return -number if negative else number


def _parse_number(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    return series.map(_parse_number_token)


def _normalize_status(value: str) -> str:
    text = str(value).strip()
    if text.lower() in {"", "nan", "none"}:
        return ""
    text = _RETURN_WINDOW.sub("", text).strip(" .")
    if text.lower() in {"pesanan diterima", "diterima"}:
        return "Pesanan Diterima"
    return text


def _looks_like_excel(data: bytes, name: str) -> bool:
    lower = name.lower()
    if lower.endswith((".xlsx", ".xlsm", ".xls")):
        return True
    return data.startswith(b"PK\x03\x04") or data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")


def _normalize_header(value: str) -> str:
    return " ".join(str(value).strip().lower().replace("_", " ").split())


def _detect_column(columns: list[str], aliases: tuple[str, ...]) -> str | None:
    normalized = {_normalize_header(col): col for col in columns}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    for alias in aliases:
        if len(alias) < 8:
            continue
        for norm, original in normalized.items():
            if alias in norm or norm in alias:
                return original
    return None


def map_columns(df: pd.DataFrame) -> dict[str, str]:
    columns = [str(c) for c in df.columns]
    mapping: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        found = _detect_column(columns, aliases)
        if found:
            mapping[canonical] = found
    required = {"order_time", "product_name", "qty"}
    missing = required - set(mapping)
    if missing:
        raise ValueError(
            "Kolom laporan Shopee tidak lengkap. Wajib ada tanggal pesanan, "
            f"nama produk, dan jumlah. Yang belum terdeteksi: {', '.join(sorted(missing))}."
        )
    return mapping


def _read_csv_bytes(data: bytes) -> pd.DataFrame:
    encodings = ("utf-8-sig", "utf-8", "utf-16", "cp1252", "latin-1")
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            return pd.read_csv(BytesIO(data), encoding=encoding)
        except Exception as exc:  # noqa: BLE001 - try next encoding
            last_error = exc
    raise ValueError(f"CSV tidak bisa dibaca. Error terakhir: {last_error}")


def load_shopee_report(
    source: str | Path | BinaryIO | bytes,
    filename: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if isinstance(source, (str, Path)):
        data = Path(source).read_bytes()
        name = filename or str(source)
    elif isinstance(source, bytes):
        data = source
        name = filename or ""
    else:
        data = source.read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        name = filename or str(getattr(source, "name", "") or "")

    if _looks_like_excel(data, name):
        try:
            raw = pd.read_excel(BytesIO(data))
        except Exception as exc:  # noqa: BLE001 - surface a readable upload error
            raise ValueError(f"File Excel tidak bisa dibaca. Error terakhir: {exc}") from exc
    else:
        raw = _read_csv_bytes(data)

    raw.columns = [str(c).strip() for c in raw.columns]
    mapping = map_columns(raw)
    frame = pd.DataFrame()
    frame["order_time"] = _parse_datetime(raw[mapping["order_time"]])
    frame["product_name"] = raw[mapping["product_name"]].map(_clean_token)
    frame["qty"] = _parse_number(raw[mapping["qty"]])
    if "returned_qty" in mapping:
        returned = _parse_number(raw[mapping["returned_qty"]]).fillna(0).clip(lower=0)
        frame["qty"] = (frame["qty"] - returned).clip(lower=0)

    if "variation" in mapping:
        frame["variation"] = raw[mapping["variation"]].map(_clean_token)
    else:
        frame["variation"] = ""

    if "sku" in mapping:
        frame["sku"] = raw[mapping["sku"]].map(_clean_token)
    elif "parent_sku" in mapping:
        frame["sku"] = raw[mapping["parent_sku"]].map(_clean_token)
    else:
        frame["sku"] = ""

    if "unit_price" in mapping:
        unit = _parse_number(raw[mapping["unit_price"]])
        frame["sales"] = unit * frame["qty"]
    elif "sales" in mapping:
        frame["sales"] = _parse_number(raw[mapping["sales"]])
    else:
        raise ValueError(
            "Tidak ada kolom omzet/harga. Pastikan laporan berisi 'Total Harga' "
            "atau 'Harga Setelah Diskon'."
        )

    if "status" in mapping:
        frame["status"] = raw[mapping["status"]].map(_normalize_status)
    else:
        frame["status"] = "Selesai"

    if "order_id" in mapping:
        frame["order_id"] = raw[mapping["order_id"]].astype(str)
    else:
        frame["order_id"] = ""

    if "order_amount" in mapping:
        frame["order_amount"] = _parse_number(raw[mapping["order_amount"]])
    else:
        frame["order_amount"] = frame["sales"]

    frame = frame.dropna(subset=["order_time", "product_name", "qty", "sales"])
    frame = frame[frame["qty"] > 0]
    frame = frame[frame["sales"] >= 0]
    frame["item_key"] = frame.apply(_item_key, axis=1)
    frame["item_label"] = frame.apply(_item_label, axis=1)
    key_count = frame.groupby("item_label")["item_key"].transform("nunique")
    collision = key_count > 1
    if collision.any():
        suffix = frame.loc[collision, "sku"].where(frame.loc[collision, "sku"].ne(""), frame.loc[collision, "item_key"])
        frame.loc[collision, "item_label"] = frame.loc[collision, "item_label"] + " (" + suffix + ")"
    imported = raw.copy()
    return frame.reset_index(drop=True), imported.reset_index(drop=True)


def _clean_status(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def _is_cancelled_status(value: str) -> bool:
    text = str(value).strip().lower()
    return any(hint in text for hint in CANCEL_HINTS)


def available_statuses(df: pd.DataFrame) -> list[str]:
    """Status unik pada laporan, tanpa nilai kosong."""
    if df.empty or "status" not in df.columns:
        return []
    statuses = _clean_status(df["status"])
    statuses = statuses[~statuses.str.lower().isin({"", "nan", "none"})]
    return sorted(statuses.unique().tolist(), key=str.casefold)


def default_statuses(statuses: list[str]) -> list[str]:
    """Default analisis: semua status kecuali batal, cancel, atau unpaid."""
    kept = [status for status in statuses if not _is_cancelled_status(status)]
    return kept if kept else list(statuses)


def order_revenue(df: pd.DataFrame) -> float:
    """Omzet transaksi: Total Pembayaran dihitung sekali untuk tiap No. Pesanan."""
    if df.empty:
        return 0.0
    amount_col = "order_amount" if "order_amount" in df.columns else "sales"
    ids = (
        df["order_id"].fillna("").astype(str).str.strip()
        if "order_id" in df.columns
        else pd.Series("", index=df.index)
    )
    blank = ids.str.lower().isin({"", "nan", "none", "-"})
    total = 0.0
    if (~blank).any():
        named = df.loc[~blank].copy()
        named["_oid"] = ids.loc[~blank].to_numpy()
        once = named.groupby("_oid", as_index=False).agg(amount=(amount_col, "first"), line=("sales", "sum"))
        chosen = once["amount"].where(once["amount"].fillna(0) > 0, once["line"])
        total += float(chosen.fillna(0).sum())
    if blank.any():
        total += float(df.loc[blank, "sales"].sum())
    return total


def filter_by_statuses(df: pd.DataFrame, statuses: list[str]) -> pd.DataFrame:
    """Pertahankan pesanan yang statusnya dipilih user."""
    if df.empty or not statuses:
        return df.iloc[0:0].copy()
    selected = {str(status).strip() for status in statuses}
    mask = _clean_status(df["status"]).isin(selected)
    return df.loc[mask].copy()


def filter_valid_orders(df: pd.DataFrame, include_processing: bool = True) -> pd.DataFrame:
    status = df["status"].astype(str).str.lower()
    cancelled = status.apply(lambda value: any(hint in value for hint in CANCEL_HINTS))
    valid = status.apply(lambda value: any(hint in value for hint in VALID_STATUS_HINTS))
    if include_processing:
        keep = (~cancelled) & (valid | status.eq("") | status.eq("nan"))
    else:
        keep = (~cancelled) & valid
    if keep.any():
        return df.loc[keep].copy()
    return df.loc[~cancelled].copy()


def _clean_token(value: object) -> str:
    text = str(value).strip() if value is not None and not (isinstance(value, float) and pd.isna(value)) else ""
    if text.lower() in {"", "nan", "none", "-", "—", "tidak ada"}:
        return ""
    return text


def _item_key(row: pd.Series) -> str:
    """Produk diklasifikasi Nomor Referensi SKU. Varian dipisah Nama Variasi."""
    sku = _clean_token(row.get("sku"))
    name = _clean_token(row.get("product_name"))
    variation = _clean_token(row.get("variation"))
    identity = sku or name
    if variation:
        return f"{identity}||{variation}"
    return identity


def _item_label(row: pd.Series) -> str:
    name = _clean_token(row.get("product_name")) or _clean_token(row.get("sku")) or "Produk"
    variation = _clean_token(row.get("variation"))
    if variation:
        return f"{name} — {variation}"
    return name
