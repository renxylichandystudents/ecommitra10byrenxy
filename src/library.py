from __future__ import annotations

import json
import zlib
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.activity import ledger_from_raw, scope_ledger
from src.ingest import _clean_token, _parse_datetime, map_columns, order_revenue

LIBRARY_DIR = Path(__file__).resolve().parents[1] / "uploads" / "library"
CATALOG_PATH = LIBRARY_DIR / "catalog.json"


def configure_root(root: Path) -> None:
    """Arahkan penyimpanan bulanan ke folder pengguna (dipakai saat deploy publik)."""
    global LIBRARY_DIR, CATALOG_PATH
    LIBRARY_DIR = Path(root) / "library"
    CATALOG_PATH = LIBRARY_DIR / "catalog.json"

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


def month_label(key: str) -> str:
    if key == "tanpa-bulan":
        return "Tanpa bulan"
    year, month = key.split("-", 1)
    try:
        name = ID_MONTHS[int(month) - 1]
    except (ValueError, IndexError):
        return key
    return f"{name} {year}"


def year_of(key: str) -> str:
    return key.split("-", 1)[0] if key[:4].isdigit() else "Lainnya"


def _read_catalog() -> dict:
    if not CATALOG_PATH.exists():
        return {"months": {}, "history": []}
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"months": {}, "history": []}
    data.setdefault("months", {})
    data.setdefault("history", [])
    return data


def _write_catalog(catalog: dict) -> None:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")


def bundle_stamp(keys: list[str]) -> tuple[float, ...]:
    """Waktu ubah file bulan. Dipakai agar cache ikut berubah saat data diganti."""
    stamps: list[float] = []
    for key in keys:
        path = LIBRARY_DIR / f"{key}.pkl"
        try:
            stamps.append(path.stat().st_mtime)
        except OSError:
            stamps.append(0.0)
    try:
        stamps.append(CATALOG_PATH.stat().st_mtime)
    except OSError:
        stamps.append(0.0)
    # Cache Streamlit dipakai bersama semua pengunjung; folder pengguna ikut jadi kunci.
    stamps.append(float(zlib.crc32(str(LIBRARY_DIR).encode("utf-8"))))
    return tuple(stamps)


def list_months() -> list[dict]:
    """Daftar bulan yang sudah tersimpan, terbaru di depan."""
    months = _read_catalog().get("months", {})
    rows = []
    for key, info in months.items():
        rows.append(
            {
                "key": key,
                "label": info.get("label") or month_label(key),
                "rows": int(info.get("rows") or 0),
                "orders": int(info.get("orders") or 0),
                "files": list(info.get("files") or []),
                "updated_at": info.get("updated_at") or "",
            }
        )
    rows.sort(key=lambda item: item["key"], reverse=True)
    return rows


def _unique_order_count(ledger: pd.DataFrame, mask: pd.Series) -> int:
    if ledger.empty or not bool(mask.any()):
        return 0
    ids = ledger.loc[mask, "order_id"].fillna("").astype(str).str.strip()
    ids = ids[~ids.str.lower().isin({"", "nan", "none", "-"})]
    return int(ids.nunique())


def month_status_counts(source: pd.DataFrame | None) -> dict[str, float]:
    """Pesanan, qty, dan sales. QTY serta sales bersih sudah mengurangi retur dan batal."""
    empty = {
        "return_orders": 0,
        "cancel_orders": 0,
        "success_orders": 0,
        "qty_net": 0.0,
        "sales_net": 0.0,
        "qty_return": 0.0,
        "sales_return": 0.0,
        "qty_batal": 0.0,
        "sales_batal": 0.0,
    }
    if source is None or source.empty:
        return empty
    ledger = ledger_from_raw(source)
    if ledger.empty:
        return empty
    cancel = ledger.loc[ledger["is_cancel"]]
    kept = scope_ledger(ledger, include_cancel=False, include_return=False)
    return {
        "return_orders": _unique_order_count(ledger, ledger["returned_qty"] > 0),
        "cancel_orders": _unique_order_count(ledger, ledger["is_cancel"]),
        "success_orders": _unique_order_count(ledger, ledger["is_success"]),
        "qty_net": float(kept["qty"].sum()) if not kept.empty else 0.0,
        "sales_net": float(order_revenue(kept)) if not kept.empty else 0.0,
        "qty_return": float(ledger["returned_qty"].sum()),
        "sales_return": float(ledger["return_value"].sum()),
        "qty_batal": float(cancel["qty"].sum()) if not cancel.empty else 0.0,
        "sales_batal": float(order_revenue(cancel)) if not cancel.empty else 0.0,
    }


def folder_frame() -> pd.DataFrame:
    """Tabel folder: bulan tersimpan plus return, batal, dan berhasil."""
    columns = [
        "Bulan",
        "Baris",
        "No. Pesanan",
        "Berhasil",
        "QTY terjual",
        "Sales",
        "QTY return",
        "Sales return",
        "QTY batal",
        "Sales batal",
        "Return",
        "Batal",
        "File terakhir",
        "Diperbarui",
    ]
    saved = list_months()
    if not saved:
        return pd.DataFrame(columns=columns)
    rows = []
    for item in saved:
        bundle = _load_bundle(item["key"])
        source = bundle.get("source") if isinstance(bundle, dict) else None
        counts = month_status_counts(source if isinstance(source, pd.DataFrame) else None)
        rows.append(
            {
                "Bulan": item["label"],
                "Baris": item["rows"],
                "No. Pesanan": item["orders"],
                "Berhasil": counts["success_orders"],
                "QTY terjual": int(round(counts["qty_net"])),
                "Sales": int(round(counts["sales_net"])),
                "QTY return": int(round(counts["qty_return"])),
                "Sales return": int(round(counts["sales_return"])),
                "QTY batal": int(round(counts["qty_batal"])),
                "Sales batal": int(round(counts["sales_batal"])),
                "Return": counts["return_orders"],
                "Batal": counts["cancel_orders"],
                "File terakhir": ", ".join(item["files"]),
                "Diperbarui": item["updated_at"],
            }
        )
    return pd.DataFrame(rows)


def history_frame() -> pd.DataFrame:
    columns = ["Tanggal perubahan", "Data", "File", "Perubahan"]
    history = _read_catalog().get("history", [])
    if not history:
        return pd.DataFrame(columns=columns)
    rows = []
    for item in history:
        rows.append(
            {
                "Tanggal perubahan": item.get("at") or "",
                "Data": item.get("data") or "",
                "File": item.get("files") or "",
                "Perubahan": item.get("change") or "",
            }
        )
    return pd.DataFrame(rows)


def _month_series(source: pd.DataFrame) -> pd.Series:
    table = source.drop(columns=["Nama file"], errors="ignore")
    mapping = map_columns(table)
    if "order_time" not in mapping:
        return pd.Series("tanpa-bulan", index=source.index)
    times = _parse_datetime(table[mapping["order_time"]])
    keys = times.dt.to_period("M").astype(str)
    return keys.where(times.notna(), "tanpa-bulan")


def _order_count(source: pd.DataFrame) -> int:
    table = source.drop(columns=["Nama file"], errors="ignore")
    mapping = map_columns(table)
    if "order_id" not in mapping or source.empty:
        return 0
    ids = table[mapping["order_id"]].map(_clean_token)
    return int(ids[ids.ne("")].nunique())


def _load_bundle(key: str) -> dict | None:
    path = LIBRARY_DIR / f"{key}.pkl"
    if not path.exists():
        return None
    bundle = pd.read_pickle(path)
    if not isinstance(bundle, dict):
        return None
    return bundle


def load_months(keys: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    sources = []
    orders = []
    for key in keys:
        bundle = _load_bundle(key)
        if bundle is None:
            continue
        source = bundle.get("source")
        order = bundle.get("orders")
        if isinstance(source, pd.DataFrame) and not source.empty:
            sources.append(source)
        if isinstance(order, pd.DataFrame) and not order.empty:
            orders.append(order)
    source_raw = pd.concat(sources, ignore_index=True) if sources else pd.DataFrame()
    orders_raw = pd.concat(orders, ignore_index=True) if orders else pd.DataFrame()
    if not source_raw.empty:
        source_raw = source_raw.drop_duplicates().reset_index(drop=True)
    if not orders_raw.empty:
        orders_raw = orders_raw.drop_duplicates().reset_index(drop=True)
    return source_raw, orders_raw


def _fmt_count(value: float) -> str:
    return f"{int(round(float(value))):,}".replace(",", ".")


def _month_facts(source: pd.DataFrame) -> dict[str, float]:
    table = source.drop(columns=["Nama file"], errors="ignore").drop_duplicates()
    ledger = ledger_from_raw(table)
    if ledger.empty:
        return {
            "rows": float(len(table)),
            "orders": 0.0,
            "qty": 0.0,
            "payment": 0.0,
            "cancel_orders": 0.0,
            "cancel_nominal": 0.0,
            "return_qty": 0.0,
            "return_nominal": 0.0,
        }
    cancel = ledger.loc[ledger["is_cancel"]]
    named = ledger["order_id"].fillna("").astype(str).str.strip()
    orders = int(named[named.ne("")].nunique())
    cancel_orders = 0
    if not cancel.empty:
        cancel_ids = cancel["order_id"].fillna("").astype(str).str.strip()
        cancel_orders = int(cancel_ids[cancel_ids.ne("")].nunique())
    return {
        "rows": float(len(table)),
        "orders": float(orders),
        "qty": float(ledger["qty"].sum()),
        "payment": float(order_revenue(ledger)),
        "cancel_orders": float(cancel_orders),
        "cancel_nominal": float(order_revenue(cancel)) if not cancel.empty else 0.0,
        "return_qty": float(ledger["returned_qty"].sum()),
        "return_nominal": float(ledger["return_value"].sum()),
    }


def _fingerprint(source: pd.DataFrame) -> int:
    table = source.drop(columns=["Nama file"], errors="ignore").drop_duplicates()
    if table.empty:
        return 0
    ordered = table.reindex(sorted(table.columns), axis=1).astype(str).fillna("")
    return int(pd.util.hash_pandas_object(ordered, index=False).sum())


def _change_note(label: str, previous_source: pd.DataFrame | None, source_part: pd.DataFrame) -> tuple[str, bool]:
    """Teks perubahan dan apakah isi bulan ini benar-benar berbeda."""
    if previous_source is None or previous_source.empty:
        facts = _month_facts(source_part)
        note = (
            f"{label} ditambahkan. {_fmt_count(facts['rows'])} baris, "
            f"{_fmt_count(facts['orders'])} No. Pesanan."
        )
        return note, True
    if _fingerprint(previous_source) == _fingerprint(source_part):
        return f"{label}: Tidak ada perubahan data", False
    before = _month_facts(previous_source)
    after = _month_facts(source_part)
    labels = (
        ("rows", "Baris", False),
        ("orders", "No. Pesanan", False),
        ("qty", "Jumlah", False),
        ("payment", "Total pembayaran", True),
        ("cancel_orders", "Invoice batal", False),
        ("cancel_nominal", "Nominal batal", True),
        ("return_qty", "Unit retur", False),
        ("return_nominal", "Nominal retur", True),
    )
    parts = []
    for key, title, money in labels:
        old = float(before[key])
        new = float(after[key])
        if abs(old - new) < 0.5:
            continue
        if money:
            parts.append(f"{title} Rp {_fmt_count(old)} menjadi Rp {_fmt_count(new)}")
        else:
            parts.append(f"{title} {_fmt_count(old)} menjadi {_fmt_count(new)}")
    if not parts:
        parts.append("isi sel berubah, jumlah baris dan nilai utama tetap")
    return f"{label} diperbarui. " + ". ".join(parts) + ".", True


def store_upload(source: pd.DataFrame, orders: pd.DataFrame, filenames: list[str]) -> tuple[list[str], list[str]]:
    """Simpan unggahan per bulan. Bulan yang sama diganti hanya bila isinya berubah."""
    if source is None or source.empty:
        return [], []
    catalog = _read_catalog()
    stamps = _month_series(source)
    order_months = (
        pd.to_datetime(orders["order_time"], errors="coerce").dt.to_period("M").astype(str)
        if orders is not None and not orders.empty and "order_time" in orders.columns
        else pd.Series(dtype=str)
    )
    now = datetime.now().strftime("%d-%m-%Y %H:%M")
    file_text = ", ".join(filenames) if filenames else "Lampiran"
    notes: list[str] = []
    saved_keys: list[str] = []
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    for key in sorted(set(stamps.tolist())):
        source_part = source.loc[stamps.eq(key)].reset_index(drop=True)
        if not order_months.empty and key != "tanpa-bulan":
            order_part = orders.loc[order_months.eq(key)].reset_index(drop=True)
        elif key == "tanpa-bulan":
            order_part = orders.iloc[0:0].copy() if orders is not None else pd.DataFrame()
        else:
            order_part = pd.DataFrame()
        previous = catalog["months"].get(key)
        previous_bundle = _load_bundle(key) if previous else None
        previous_source = None
        if previous_bundle is not None and isinstance(previous_bundle.get("source"), pd.DataFrame):
            previous_source = previous_bundle["source"]
        rows_now = int(len(source_part))
        orders_now = _order_count(source_part)
        label = month_label(key)
        change, changed = _change_note(label, previous_source, source_part)
        if changed:
            pd.to_pickle({"source": source_part, "orders": order_part}, LIBRARY_DIR / f"{key}.pkl")
            catalog["months"][key] = {
                "label": label,
                "rows": rows_now,
                "orders": orders_now,
                "files": list(filenames),
                "updated_at": now,
            }
        catalog["history"].insert(
            0,
            {"at": now, "data": label, "files": file_text, "change": change},
        )
        notes.append(change)
        saved_keys.append(key)
    _write_catalog(catalog)
    return saved_keys, notes
