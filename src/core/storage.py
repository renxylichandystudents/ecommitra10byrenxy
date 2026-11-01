from __future__ import annotations

import csv
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from src.core.schemas import (
    SOURCE_SPECS,
    SourceSpec,
    canonicalize_frame,
    find_columns,
    normalize_header,
    validation_report,
)


DEFAULT_DATA_DIR = Path.home() / ".prediksi_shopee"
REGISTRY_NAME = "registry.json"


@dataclass(frozen=True)
class SubmitResult:
    source_key: str
    source_label: str
    rows_received: int
    rows_stored: int
    rows_added: int
    rows_replaced: int
    status: str
    files: tuple[str, ...]
    message: str


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


HEADER_SCAN_ROWS = 30
IDENTITY_FIELDS = ("order_id", "sku", "product_code", "product_name", "shop_name", "date", "views")


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" not in text:
            return text
    return data.decode("latin-1")


def _header_score(values: list[object], spec: SourceSpec | None) -> int:
    cells = [str(value).strip() for value in values if str(value).strip() not in {"", "nan", "None"}]
    if spec is None:
        return len(cells)
    return len(find_columns(cells, spec))


def _pick_header(rows: list[list[object]], spec: SourceSpec | None) -> int:
    """Baris header = baris dengan kolom sumber paling banyak dikenali (preamble Shopee dilewati)."""
    best_index, best_score = 0, -1
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        score = _header_score(row, spec)
        if score > best_score:
            best_index, best_score = index, score
    if spec is not None and best_score <= 0:
        return _pick_header(rows, None)
    return best_index


def _report_period(preamble: list[list[str]]) -> str | None:
    for row in preamble:
        if len(row) >= 2 and normalize_header(row[0]) in {"periode", "periode laporan"} and str(row[1]).strip():
            return str(row[1]).strip()
    return None


def _period_start(text: str) -> str:
    first = str(text).split(" - ")[0].strip()
    parsed = pd.to_datetime(first, dayfirst=True, errors="coerce")
    return parsed.date().isoformat() if pd.notna(parsed) else text


def _read_csv_bytes(data: bytes, spec: SourceSpec | None = None) -> pd.DataFrame:
    text = _decode_text(data)
    lines = text.splitlines()
    rows = list(csv.reader(lines[:HEADER_SCAN_ROWS]))
    header = _pick_header(rows, spec)
    try:
        frame = pd.read_csv(StringIO("\n".join(lines[header:])), dtype=str, keep_default_na=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"CSV tidak bisa dibaca. Error terakhir: {exc}") from exc
    period = _report_period(rows[:header])
    if period and spec is not None and "period" in spec.aliases and "period" not in find_columns(frame.columns, spec):
        frame.insert(0, "Periode Laporan", _period_start(period))
        frame.insert(1, "Periode laporan (teks)", period)
    return frame


def _looks_like_excel(data: bytes, filename: str) -> bool:
    lower = str(filename).lower()
    return lower.endswith((".xlsx", ".xlsm", ".xls")) or data.startswith(b"PK\x03\x04")


_PANE_VALUE = re.compile(rb'((?:activePane|pane)=")(top|bottom)_(left|right)(")')


def _fix_excel_panes(data: bytes) -> bytes:
    """Ekspor Shopee menulis activePane="bottom_left"; openpyxl hanya menerima bottomLeft."""
    if not data.startswith(b"PK\x03\x04"):
        return data
    try:
        source = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile:
        return data
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename.startswith("xl/worksheets/") and info.filename.endswith(".xml"):
                content = _PANE_VALUE.sub(lambda m: m.group(1) + m.group(2) + m.group(3).capitalize() + m.group(4), content)
            target.writestr(info, content)
    return out.getvalue()


def _unique_columns(values: list[object]) -> list[str]:
    seen: dict[str, int] = {}
    names: list[str] = []
    for index, value in enumerate(values):
        name = str(value).strip()
        if name in {"", "nan", "None"}:
            name = f"Kolom {index + 1}"
        count = seen.get(name, 0)
        seen[name] = count + 1
        names.append(name if count == 0 else f"{name} ({count + 1})")
    return names


def _read_excel_bytes(data: bytes, spec: SourceSpec | None = None) -> pd.DataFrame:
    sheets = pd.read_excel(BytesIO(_fix_excel_panes(data)), sheet_name=None, header=None, dtype=object)
    best: pd.DataFrame | None = None
    best_score = -1
    for raw in sheets.values():
        raw = raw.dropna(how="all")
        if raw.empty:
            continue
        rows = raw.head(HEADER_SCAN_ROWS).values.tolist()
        header = _pick_header(rows, spec)
        score = _header_score(rows[header], spec)
        if score > best_score:
            frame = raw.iloc[header + 1 :].copy()
            frame.columns = _unique_columns(rows[header])
            best, best_score = frame.reset_index(drop=True), score
    return best if best is not None else pd.DataFrame()


def _drop_template_rows(frame: pd.DataFrame, spec: SourceSpec | None) -> pd.DataFrame:
    """Buang baris petunjuk template ("Wajib", "Masukkan stok ...") yang tidak punya identitas data."""
    if spec is None or frame.empty:
        return frame
    mapping = find_columns(frame.columns, spec)
    identity = [mapping[field] for field in IDENTITY_FIELDS if field in mapping]
    if not identity:
        return frame
    filled = frame[identity].apply(lambda col: col.notna() & col.astype(str).str.strip().ne("")).any(axis=1)
    return frame.loc[filled].reset_index(drop=True)


def _collapse_ranked_listing(frame: pd.DataFrame) -> pd.DataFrame:
    """Ekspor peringkat kompetitor Shopee: satu produk = 2 baris (peringkat + toko, lalu nama produk)."""
    columns = {normalize_header(column): column for column in frame.columns}
    rank_col, change_col = columns.get("ranking"), columns.get("change of rank")
    name_col, shop_col = columns.get("products name"), columns.get("shop name")
    if not (rank_col and name_col and shop_col):
        return frame
    records: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    block, own_section, position = 0, False, 0
    for _, row in frame.iterrows():
        rank = row[rank_col]
        rank_text = "" if pd.isna(rank) else str(rank).strip()
        if normalize_header(rank_text) == "ranking":
            block += 1
            own_section, position = False, 0
            continue
        if rank_text and not rank_text.replace(".0", "").isdigit():
            own_section = True
            continue
        shop = row[shop_col]
        name = row[name_col]
        change = row[change_col] if change_col else None
        if pd.notna(shop) and str(shop).strip():
            if not own_section:
                position += 1
            current = {
                "Daftar": block or 1,
                "Ranking": rank_text.replace(".0", "") or (None if own_section else str(position)),
                "Change of Rank": None if change is None or pd.isna(change) else str(change).strip(),
                "Shop Name": str(shop).strip(),
                "Products Name": None,
                "Toko sendiri": own_section or str(change).strip().lower() == "my shop",
            }
            records.append(current)
        if pd.notna(name) and str(name).strip() and current is not None and not current["Products Name"]:
            current["Products Name"] = str(name).strip()
    out = pd.DataFrame(records)
    if out.empty:
        return frame
    return out.dropna(subset=["Products Name"]).reset_index(drop=True)


def read_upload_file(source: BinaryIO | bytes, filename: str, spec: SourceSpec | None = None) -> pd.DataFrame:
    data = source if isinstance(source, bytes) else source.read()
    if isinstance(data, str):
        data = data.encode("utf-8")
    if _looks_like_excel(data, filename):
        frame = _read_excel_bytes(data, spec)
    else:
        frame = _read_csv_bytes(data, spec)
    if spec is not None and spec.key == "competitors":
        frame = _collapse_ranked_listing(frame)
    return _drop_template_rows(frame, spec)


def read_many_uploads(files: list[BinaryIO], spec: SourceSpec | None = None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for uploaded in files:
        name = str(getattr(uploaded, "name", "Lampiran"))
        frame = read_upload_file(uploaded, name, spec)
        frame.insert(0, "Nama file", name)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


class LocalDataStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else DEFAULT_DATA_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "sources").mkdir(exist_ok=True)

    @property
    def registry_path(self) -> Path:
        return self.root / REGISTRY_NAME

    def _read_registry(self) -> dict:
        if not self.registry_path.exists():
            return {"sources": {}, "history": []}
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"sources": {}, "history": []}
        data.setdefault("sources", {})
        data.setdefault("history", [])
        return data

    def _write_registry(self, registry: dict) -> None:
        self.registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

    def _source_base(self, source_key: str) -> Path:
        return self.root / "sources" / source_key

    def _source_path(self, source_key: str, fmt: str = "parquet") -> Path:
        suffix = "parquet" if fmt == "parquet" else "pkl"
        return self._source_base(source_key).with_suffix(f".{suffix}")

    def _write_frame(self, source_key: str, frame: pd.DataFrame) -> str:
        parquet = self._source_path(source_key, "parquet")
        try:
            frame.to_parquet(parquet, index=False)
            legacy = self._source_path(source_key, "pickle")
            if legacy.exists():
                legacy.unlink()
            return "parquet"
        except Exception:
            frame.to_pickle(self._source_path(source_key, "pickle"))
            return "pickle"

    def read_source(self, source_key: str) -> pd.DataFrame:
        registry = self._read_registry()
        fmt = str(registry.get("sources", {}).get(source_key, {}).get("format", "parquet"))
        primary = self._source_path(source_key, fmt)
        if not primary.exists():
            primary = self._source_path(source_key, "parquet")
        if primary.exists() and primary.suffix == ".parquet":
            try:
                return pd.read_parquet(primary)
            except Exception:
                fallback = self._source_path(source_key, "pickle")
                return pd.read_pickle(fallback) if fallback.exists() else pd.DataFrame()
        fallback = self._source_path(source_key, "pickle")
        return pd.read_pickle(fallback) if fallback.exists() else pd.DataFrame()

    def submit_source(
        self,
        source_key: str,
        frame: pd.DataFrame,
        *,
        filenames: list[str] | None = None,
        submitted_at: str | None = None,
    ) -> SubmitResult:
        if source_key not in SOURCE_SPECS:
            raise KeyError(f"Sumber data tidak dikenal: {source_key}")
        spec = SOURCE_SPECS[source_key]
        filenames = list(filenames or [])
        stamp = submitted_at or _now()
        incoming, mapping = canonicalize_frame(frame, spec)
        incoming = incoming.copy()
        incoming["_submitted_at"] = stamp
        incoming["_source_key"] = source_key
        incoming["_row_hash"] = pd.util.hash_pandas_object(
            incoming.drop(columns=["_submitted_at"], errors="ignore").astype(str).fillna(""),
            index=False,
        ).astype(str)
        previous = self.read_source(source_key)
        before_rows = int(len(previous))

        if source_key == "stock":
            merged = pd.concat([previous, incoming], ignore_index=True) if not previous.empty else incoming
            # Stok adalah snapshot; jangan menimpa submit lama, hanya rapikan duplikasi dalam submit yang sama.
            subset = [key for key in (*spec.dedup_keys, "_submitted_at") if key in merged.columns]
            if subset:
                merged = merged.drop_duplicates(subset=subset, keep="last")
        else:
            merged = pd.concat([previous, incoming], ignore_index=True) if not previous.empty else incoming
            subset = _usable_dedup_keys(merged, spec)
            if subset:
                merged = merged.drop_duplicates(subset=subset, keep="last")
            else:
                merged = merged.drop_duplicates("_row_hash", keep="last")

        fmt = self._write_frame(source_key, merged.reset_index(drop=True))
        registry = self._read_registry()
        report = validation_report(incoming, spec)
        entry = {
            "label": spec.label,
            "rows": int(len(merged)),
            "format": fmt,
            "updated_at": stamp,
            "files": filenames,
            "status": report["status"],
            "required_missing": report["missing_required"],
            "mapping": mapping,
        }
        registry["sources"][source_key] = entry
        registry["history"].insert(
            0,
            {
                "at": stamp,
                "source_key": source_key,
                "source_label": spec.label,
                "files": ", ".join(filenames),
                "rows_received": int(len(incoming)),
                "rows_stored": int(len(merged)),
            },
        )
        self._write_registry(registry)
        after_rows = int(len(merged))
        added = max(after_rows - before_rows, 0)
        replaced = max(int(len(incoming)) - added, 0) if source_key != "stock" else 0
        if source_key == "stock":
            message = f"{spec.label}: snapshot stok disimpan ({len(incoming)} baris baru)."
        elif before_rows == 0:
            message = f"{spec.label}: {after_rows} baris tersimpan."
        else:
            message = f"{spec.label}: {added} baris baru, {replaced} baris diperbarui/deduplikasi."
        return SubmitResult(
            source_key=source_key,
            source_label=spec.label,
            rows_received=int(len(incoming)),
            rows_stored=after_rows,
            rows_added=added,
            rows_replaced=replaced,
            status=str(report["status"]),
            files=tuple(filenames),
            message=message,
        )

    def source_summaries(self) -> pd.DataFrame:
        registry = self._read_registry()
        rows: list[dict[str, object]] = []
        for spec in SOURCE_SPECS.values():
            info = registry.get("sources", {}).get(spec.key, {})
            frame = self.read_source(spec.key)
            report = validation_report(frame, spec)
            rows.append(
                {
                    "Menu": spec.label,
                    "Status": info.get("status") or report["status"],
                    "Baris tersimpan": int(info.get("rows") or len(frame)),
                    "Kolom wajib terbaca": len(report["found_required"]),
                    "Kolom wajib hilang": ", ".join(report["missing_required"]) or "-",
                    "File terakhir": ", ".join(info.get("files") or []),
                    "Diperbarui": info.get("updated_at") or "-",
                    "Kegunaan": spec.utility,
                }
            )
        return pd.DataFrame(rows)

    def snapshot_count(self) -> int:
        stock = self.read_source("stock")
        if stock.empty or "_submitted_at" not in stock.columns:
            return 0
        return int(stock["_submitted_at"].nunique())


def _usable_dedup_keys(frame: pd.DataFrame, spec: SourceSpec) -> list[str]:
    keys = [key for key in spec.dedup_keys if key in frame.columns]
    usable: list[str] = []
    for key in keys:
        values = frame[key].fillna("").astype(str).str.strip()
        if values.ne("").any():
            usable.append(key)
    return usable

