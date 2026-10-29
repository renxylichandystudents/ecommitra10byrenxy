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
    "cancel_reason": (
        "alasan pembatalan",
        "cancellation reason",
        "cancel reason",
    ),
    "return_reason": (
        "status pembatalan/ pengembalian",
        "status pembatalan/pengembalian",
        "status pengembalian",
        "return status",
    ),
    "buyer": (
        "username (pembeli)",
        "username pembeli",
        "nama akun pembeli",
        "akun pembeli",
        "buyer username",
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

SUCCESS_STATUSES = (
    "pesanan diterima",
    "sedang dikirim",
    "selesai",
    "telah dikirim",
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


LINE_PROMO_COLUMNS: dict[str, tuple[str, ...]] = {
    "list_price": ("harga awal",),
    "net_price": ("harga setelah diskon",),
    "seller_discount": ("diskon dari penjual",),
    "shopee_discount": ("diskon dari shopee",),
}

ORDER_PROMO_COLUMNS: dict[str, tuple[str, ...]] = {
    "seller_voucher": ("voucher ditanggung penjual",),
    "coin_cashback": ("cashback koin",),
    "shopee_voucher": ("voucher ditanggung shopee",),
    "coin_deduction": ("potongan koin shopee",),
    "card_discount": ("diskon kartu kredit",),
    "buyer_shipping": ("ongkos kirim dibayar oleh pembeli", "ongkos kirim dibayar pembeli"),
    "shipping_rebate": ("estimasi potongan biaya pengiriman",),
}

ORDER_TEXT_COLUMNS: dict[str, tuple[str, ...]] = {
    "shipping_option": ("opsi pengiriman",),
    "payment_method": ("metode pembayaran",),
}


def _exact_column(table: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    """Hanya nama kolom yang persis sama, supaya tidak tertukar dengan kolom harga atau qty."""
    normalized = {_normalize_header(col): col for col in table.columns}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return None


def _attach_promo_columns(frame: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    """Harga, diskon, voucher, koin, ongkir, opsi kirim, dan metode bayar.

    Kolom baris dibaca apa adanya. Kolom pesanan (voucher, koin, kartu kredit, ongkir)
    diulang Shopee di setiap baris pesanan, jadi dibagi ke baris menurut porsi subtotal.
    QTY dan sales tidak disentuh.
    """
    for name, aliases in LINE_PROMO_COLUMNS.items():
        column = _exact_column(table, aliases)
        frame[name] = (
            _parse_number(table.loc[frame.index, column]).fillna(0).clip(lower=0) if column else float("nan")
        )
    for name, aliases in ORDER_TEXT_COLUMNS.items():
        column = _exact_column(table, aliases)
        frame[name] = clean_text_series(table.loc[frame.index, column]) if column else ""
    base = frame["net_price"].where(frame["net_price"] > 0, frame["list_price"]).fillna(0) * frame["gross_qty"]
    if "order_id" in frame.columns and frame["order_id"].astype(str).str.strip().ne("").any():
        order_total = base.groupby(frame["order_id"]).transform("sum")
        lines = frame.groupby("order_id")["order_id"].transform("size").astype(float)
        share = (base / order_total.where(order_total > 0)).fillna(1.0 / lines)
    else:
        share = pd.Series(1.0, index=frame.index)
    for name, aliases in ORDER_PROMO_COLUMNS.items():
        column = _exact_column(table, aliases)
        if column:
            frame[name] = _parse_number(table.loc[frame.index, column]).fillna(0).clip(lower=0) * share
        else:
            frame[name] = float("nan")
    return frame


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
    frame = clean_order_frame(raw)
    imported = raw.copy()
    return frame.reset_index(drop=True), imported.reset_index(drop=True)


def clean_order_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Satu baris pesanan. Qty bersih dikurangi retur; qty kotor tetap disimpan."""
    table = raw.drop(columns=["Nama file"], errors="ignore").copy()
    table.columns = [str(column).strip() for column in table.columns]
    mapping = map_columns(table)
    frame = pd.DataFrame()
    frame["order_time"] = _parse_datetime(table[mapping["order_time"]])
    frame["product_name"] = clean_text_series(table[mapping["product_name"]])
    frame["gross_qty"] = _parse_number(table[mapping["qty"]]).fillna(0).clip(lower=0)
    frame["returned_qty"] = 0.0
    if "returned_qty" in mapping:
        frame["returned_qty"] = _parse_number(table[mapping["returned_qty"]]).fillna(0).clip(lower=0)
    frame["qty"] = (frame["gross_qty"] - frame["returned_qty"]).clip(lower=0)

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
        unit = _parse_number(table[mapping["unit_price"]]).fillna(0).clip(lower=0)
        frame["gross_sales"] = unit * frame["gross_qty"]
        frame["sales"] = unit * frame["qty"]
    elif "sales" in mapping:
        frame["sales"] = _parse_number(table[mapping["sales"]])
        frame["gross_sales"] = frame["sales"]
    else:
        raise ValueError(
            "Tidak ada kolom omzet/harga. Pastikan laporan berisi 'Total Harga' "
            "atau 'Harga Setelah Diskon'."
        )

    if "status" in mapping:
        frame["status"] = normalize_status_series(table[mapping["status"]])
    else:
        frame["status"] = "Selesai"

    if "order_id" in mapping:
        frame["order_id"] = table[mapping["order_id"]].astype(str)
    else:
        frame["order_id"] = ""

    if "order_amount" in mapping:
        frame["order_amount"] = _parse_number(table[mapping["order_amount"]])
    else:
        frame["order_amount"] = frame["sales"]

    frame = _attach_promo_columns(frame, table)
    frame = frame.dropna(subset=["order_time", "product_name", "qty", "sales"])
    frame = frame[(frame["qty"] > 0) | (frame["gross_qty"] > 0)]
    frame = frame[frame["gross_sales"].fillna(frame["sales"]).fillna(0) >= 0]
    frame["item_key"] = item_key_series(frame)
    frame = apply_latest_identity(frame)
    return frame.reset_index(drop=True)


def _clean_status(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def _is_cancelled_status(value: str) -> bool:
    text = str(value).strip().lower()
    return any(hint in text for hint in CANCEL_HINTS)


def _is_success_status(value: str) -> bool:
    """Pesanan diterima, sedang dikirim, selesai, dan telah dikirim."""
    return str(value).strip().lower() in SUCCESS_STATUSES


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


def _clean_sku(value: object) -> str:
    """Nomor referensi SKU tanpa ekor .0 dari sel angka Excel."""
    if isinstance(value, str):
        text = _clean_token(value)
        if re.fullmatch(r"\d+\.0+", text):
            return text.split(".", 1)[0]
        return text
    if value is None or isinstance(value, bool):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _clean_token(value)
    if pd.isna(number):
        return ""
    if number.is_integer():
        return str(int(number))
    return _clean_token(value)


def order_month_keys(source: pd.DataFrame) -> pd.Series:
    """Kunci YYYY-MM dari waktu pesanan pada tabel mentah."""
    if source is None or source.empty:
        return pd.Series(dtype="object")
    table = source.drop(columns=["Nama file"], errors="ignore")
    mapping = map_columns(table)
    if "order_time" not in mapping:
        return pd.Series("tanpa-bulan", index=source.index)
    times = _parse_datetime(source[mapping["order_time"]])
    keys = times.dt.to_period("M").astype(str)
    return keys.where(times.notna(), "tanpa-bulan")


def clean_sku_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Rapikan kolom referensi SKU pada tabel mentah yang masih bertipe angka."""
    if frame is None or frame.empty:
        return frame
    work = frame.copy()
    for column in work.columns:
        label = str(column).strip().lower()
        if label in {"sku", "seller sku", "sku reference", "parent sku", "sku induk"} or "referensi sku" in label:
            work[column] = clean_sku_series(work[column])
    return work


_EMPTY_TOKENS = {"", "nan", "none", "-", "—", "tidak ada"}


def clean_text_series(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip()
    return text.mask(text.str.lower().isin(_EMPTY_TOKENS), "")


def clean_sku_series(series: pd.Series) -> pd.Series:
    """Sama dengan _clean_sku, untuk satu kolom sekaligus."""
    if pd.api.types.is_bool_dtype(series):
        return pd.Series("", index=series.index, dtype=object)
    if pd.api.types.is_numeric_dtype(series):
        numbers = pd.to_numeric(series, errors="coerce")
        text = pd.Series("", index=series.index, dtype=object)
        valid = numbers.notna()
        whole = valid & (numbers % 1 == 0)
        if bool(whole.any()):
            text.loc[whole] = numbers.loc[whole].round().astype("int64").astype(str)
        fractional = valid & ~whole
        if bool(fractional.any()):
            text.loc[fractional] = numbers.loc[fractional].map(_clean_token)
        return text
    text = clean_text_series(series)
    return text.str.replace(r"^(\d+)\.0+$", r"\1", regex=True)


def item_key_series(frame: pd.DataFrame) -> pd.Series:
    index = frame.index
    sku = clean_text_series(frame["sku"]) if "sku" in frame.columns else pd.Series("", index=index)
    name = clean_text_series(frame["product_name"]) if "product_name" in frame.columns else pd.Series("", index=index)
    variation = clean_text_series(frame["variation"]) if "variation" in frame.columns else pd.Series("", index=index)
    base = name.where(name.ne(""), "Produk")
    fallback = base.where(variation.eq(""), base.str.cat(variation, sep="||"))
    return sku.where(sku.ne(""), fallback)


def item_label_series(frame: pd.DataFrame) -> pd.Series:
    index = frame.index
    name = clean_text_series(frame["product_name"]) if "product_name" in frame.columns else pd.Series("", index=index)
    sku = clean_text_series(frame["sku"]) if "sku" in frame.columns else pd.Series("", index=index)
    variation = clean_text_series(frame["variation"]) if "variation" in frame.columns else pd.Series("", index=index)
    base = name.where(name.ne(""), sku.where(sku.ne(""), "Produk"))
    return base.where(variation.eq(""), base.str.cat(variation, sep=" — "))


def normalize_status_series(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip()
    text = text.mask(text.str.lower().isin({"", "nan", "none"}), "")
    text = text.str.replace(_RETURN_WINDOW, "", regex=True).str.strip(" .")
    lower = text.str.lower()
    return text.mask(lower.isin({"pesanan diterima", "diterima"}), "Pesanan Diterima")


def cancelled_status_mask(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip().str.lower()
    mask = pd.Series(False, index=series.index)
    for hint in CANCEL_HINTS:
        mask = mask | text.str.contains(hint, regex=False)
    return mask


def success_status_mask(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().isin(SUCCESS_STATUSES)


def _item_key(row: pd.Series) -> str:
    """Acuan produk adalah Nomor Referensi SKU. Nama hanya dipakai bila SKU kosong."""
    sku = _clean_token(row.get("sku"))
    if sku:
        return sku
    name = _clean_token(row.get("product_name"))
    variation = _clean_token(row.get("variation"))
    identity = name or "Produk"
    if variation:
        return f"{identity}||{variation}"
    return identity


def _item_label(row: pd.Series) -> str:
    name = _clean_token(row.get("product_name")) or _clean_token(row.get("sku")) or "Produk"
    variation = _clean_token(row.get("variation"))
    if variation:
        return f"{name} — {variation}"
    return name


def _last_text(series: pd.Series) -> str:
    for value in reversed(series.tolist()):
        text = _clean_token(value)
        if text:
            return text
    return ""


def apply_latest_identity(frame: pd.DataFrame) -> pd.DataFrame:
    """Satu SKU memakai nama dan variasi pada pesanan terakhir."""
    if frame.empty or "item_key" not in frame.columns or "order_time" not in frame.columns:
        return frame
    ordered = frame.sort_values(["item_key", "order_time"], kind="mergesort")
    if "product_name" not in ordered.columns:
        ordered["product_name"] = ""
    if "variation" not in ordered.columns:
        ordered["variation"] = ""
    latest = ordered.groupby("item_key", as_index=False).agg(
        product_name=("product_name", _last_text),
        variation=("variation", _last_text),
    )
    work = frame.drop(columns=["product_name", "variation"], errors="ignore")
    work = work.merge(latest, on="item_key", how="left")
    work["item_label"] = item_label_series(work)
    return work
