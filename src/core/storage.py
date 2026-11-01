from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from src.core.schemas import SOURCE_SPECS, SourceSpec, canonicalize_frame, validation_report


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


def _read_csv_bytes(data: bytes) -> pd.DataFrame:
    encodings = ("utf-8-sig", "utf-8", "utf-16", "cp1252", "latin-1")
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            return pd.read_csv(BytesIO(data), encoding=encoding)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise ValueError(f"CSV tidak bisa dibaca. Error terakhir: {last_error}")


def _looks_like_excel(data: bytes, filename: str) -> bool:
    lower = str(filename).lower()
    return lower.endswith((".xlsx", ".xlsm", ".xls")) or data.startswith(b"PK\x03\x04")


def read_upload_file(source: BinaryIO | bytes, filename: str) -> pd.DataFrame:
    data = source if isinstance(source, bytes) else source.read()
    if isinstance(data, str):
        data = data.encode("utf-8")
    if _looks_like_excel(data, filename):
        return pd.read_excel(BytesIO(data))
    return _read_csv_bytes(data)


def read_many_uploads(files: list[BinaryIO]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for uploaded in files:
        name = str(getattr(uploaded, "name", "Lampiran"))
        frame = read_upload_file(uploaded, name)
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

