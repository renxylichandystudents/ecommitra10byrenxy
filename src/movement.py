"""Simpan hasil tiap Jalankan analisis dan bandingkan dengan hasil sebelumnya."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.aggregate import PERIOD_SPECS
from src.library import month_label

RUNS_DIR = Path(__file__).resolve().parents[1] / "uploads" / "analysis_runs"
KEEP_RUNS = 40


def configure_root(root: Path) -> None:
    global RUNS_DIR
    RUNS_DIR = Path(root) / "analysis_runs"
SNAPSHOT_COLUMNS = (
    "item_key",
    "item_label",
    "pred_qty",
    "pred_sales",
    "safety_stock",
    "stok_disarankan",
    "rank_qty",
    "rank_sales",
)


def _directory(directory: Path | None) -> Path:
    folder = directory or RUNS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _index_path(directory: Path) -> Path:
    return directory / "index.json"


def _read_index(directory: Path) -> list[dict]:
    path = _index_path(directory)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    runs = data.get("runs", [])
    return runs if isinstance(runs, list) else []


def _write_index(directory: Path, runs: list[dict]) -> None:
    _index_path(directory).write_text(
        json.dumps({"runs": runs}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _whole(series: pd.Series) -> pd.Series:
    return np.rint(pd.to_numeric(series, errors="coerce").fillna(0)).astype(int)


def frame_from_stock(stock: pd.DataFrame | None) -> pd.DataFrame:
    """Angka keputusan yang disimpan: prediksi, cadangan, stok, dan peringkat prediksi."""
    if stock is None or not isinstance(stock, pd.DataFrame) or stock.empty:
        return pd.DataFrame(columns=list(SNAPSHOT_COLUMNS))
    frame = stock.copy()
    if "item_label" not in frame.columns:
        frame["item_label"] = frame.get("item_key", "")
    for column in SNAPSHOT_COLUMNS:
        if column not in frame.columns:
            frame[column] = 0 if column != "item_label" else ""
    kept = frame.loc[:, list(SNAPSHOT_COLUMNS)].copy()
    kept["item_key"] = kept["item_key"].astype(str)
    kept["item_label"] = kept["item_label"].fillna("").astype(str)
    for column in ("pred_qty", "pred_sales", "safety_stock", "stok_disarankan", "rank_qty", "rank_sales"):
        kept[column] = _whole(kept[column])
    return kept.drop_duplicates("item_key").reset_index(drop=True)


def record_run(
    stock: pd.DataFrame | None,
    meta: dict,
    directory: Path | None = None,
) -> tuple[str, str | None]:
    """Simpan analisis ini. Kembalikan id baru dan id analisis sebelumnya."""
    frame = frame_from_stock(stock)
    if frame.empty:
        return "", None
    folder = _directory(directory)
    runs = _read_index(folder)
    previous_id = str(runs[-1]["id"]) if runs else None
    stamp = datetime.now().astimezone().replace(microsecond=0)
    run_id = stamp.strftime("%Y%m%dT%H%M%S")
    if any(str(item.get("id")) == run_id for item in runs):
        run_id = f"{run_id}-{len(runs) + 1}"
    frame.to_csv(folder / f"{run_id}.csv", index=False)
    entry = {
        "id": run_id,
        "saved_at": stamp.isoformat(timespec="seconds"),
        "period": str(meta.get("period", "")),
        "period_text": str(meta.get("period_text", "")),
        "metric": str(meta.get("metric", "qty")),
        "service": int(meta.get("service", 0) or 0),
        "exclude_return_cancel": bool(meta.get("exclude_return_cancel", False)),
        "months": [str(key) for key in meta.get("months", [])],
        "window_start": str(meta.get("window_start", "")),
        "window_end": str(meta.get("window_end", "")),
    }
    runs.append(entry)
    removed = runs[:-KEEP_RUNS]
    runs = runs[-KEEP_RUNS:]
    for old in removed:
        path = folder / f"{old.get('id')}.csv"
        if path.exists():
            path.unlink()
    _write_index(folder, runs)
    if previous_id and previous_id not in {item["id"] for item in runs}:
        previous_id = None
    return run_id, previous_id


def load_run(run_id: str | None, directory: Path | None = None) -> tuple[dict, pd.DataFrame] | None:
    if not run_id:
        return None
    folder = _directory(directory)
    meta = next((item for item in _read_index(folder) if str(item.get("id")) == str(run_id)), None)
    path = folder / f"{run_id}.csv"
    if meta is None or not path.exists():
        return None
    frame = pd.read_csv(path, dtype={"item_key": str, "item_label": str})
    return meta, frame_from_stock(frame)


def list_runs(directory: Path | None = None) -> list[dict]:
    """Analisis tersimpan, dari yang paling lama ke yang paling baru."""
    return _read_index(_directory(directory))


def compare_runs(current: pd.DataFrame, previous: pd.DataFrame, metric: str = "qty") -> pd.DataFrame:
    """Satu baris per SKU. Arah memakai prediksi QTY. Geser peringkat positif berarti naik."""
    rank_column = "rank_sales" if metric == "sales" else "rank_qty"
    now = frame_from_stock(current).set_index("item_key")
    then = frame_from_stock(previous).set_index("item_key")
    rows: list[dict] = []
    for key in now.index.union(then.index):
        in_now = key in now.index
        in_then = key in then.index
        current_row = now.loc[key] if in_now else None
        previous_row = then.loc[key] if in_then else None
        if isinstance(current_row, pd.DataFrame):
            current_row = current_row.iloc[0]
        if isinstance(previous_row, pd.DataFrame):
            previous_row = previous_row.iloc[0]
        label = ""
        if in_now and str(current_row["item_label"]).strip():
            label = str(current_row["item_label"])
        elif in_then:
            label = str(previous_row["item_label"])
        pred_now = int(current_row["pred_qty"]) if in_now else 0
        pred_then = int(previous_row["pred_qty"]) if in_then else 0
        sales_now = int(current_row["pred_sales"]) if in_now else 0
        sales_then = int(previous_row["pred_sales"]) if in_then else 0
        stok_now = int(current_row["stok_disarankan"]) if in_now else 0
        stok_then = int(previous_row["stok_disarankan"]) if in_then else 0
        rank_now = int(current_row[rank_column]) if in_now else 0
        rank_then = int(previous_row[rank_column]) if in_then else 0
        if in_now and not in_then:
            arah = "Baru"
            shift = 0
        elif in_then and not in_now:
            arah = "Keluar"
            shift = 0
        else:
            delta = pred_now - pred_then
            shift = rank_then - rank_now
            stok_delta = stok_now - stok_then
            if delta > 0:
                arah = "Naik"
            elif delta < 0:
                arah = "Turun"
            elif shift != 0 or stok_delta != 0:
                arah = "Geser"
            else:
                arah = "Tetap"
        rows.append(
            {
                "item_key": key,
                "item_label": label,
                "pred_qty_now": pred_now,
                "pred_qty_then": pred_then,
                "delta_qty": pred_now - pred_then if in_now and in_then else (pred_now if in_now else -pred_then),
                "pred_sales_now": sales_now,
                "pred_sales_then": sales_then,
                "delta_sales": sales_now - sales_then if in_now and in_then else (sales_now if in_now else -sales_then),
                "stok_now": stok_now,
                "stok_then": stok_then,
                "delta_stok": stok_now - stok_then if in_now and in_then else (stok_now if in_now else -stok_then),
                "rank_now": rank_now,
                "rank_then": rank_then,
                "rank_shift": shift,
                "arah": arah,
            }
        )
    detail = pd.DataFrame(rows)
    if detail.empty:
        return detail
    return detail.sort_values(["delta_qty", "item_key"], ascending=[False, True], kind="mergesort").reset_index(drop=True)


def setup_notes(current: dict, previous: dict) -> list[str]:
    """Kalimat perubahan input. Kosong bila pengaturan analisis sama."""
    notes: list[str] = []
    current_months = [str(key) for key in current.get("months", [])]
    previous_months = [str(key) for key in previous.get("months", [])]
    added = [month_label(key) for key in current_months if key not in set(previous_months)]
    removed = [month_label(key) for key in previous_months if key not in set(current_months)]
    if added:
        notes.append("Data latih bertambah: " + ", ".join(added) + ".")
    if removed:
        notes.append("Data latih berkurang: " + ", ".join(removed) + ".")
    if str(current.get("period", "")) != str(previous.get("period", "")):
        before = PERIOD_SPECS.get(str(previous.get("period", "")), None)
        after = PERIOD_SPECS.get(str(current.get("period", "")), None)
        before_label = before.label if before else str(previous.get("period", ""))
        after_label = after.label if after else str(current.get("period", ""))
        notes.append(f"Periode prediksi berubah dari {before_label} menjadi {after_label}.")
    if str(current.get("metric", "qty")) != str(previous.get("metric", "qty")):
        names = {"qty": "Quantity terjual", "sales": "Sales volume"}
        notes.append(
            "Parameter peringkat berubah dari "
            f"{names.get(str(previous.get('metric')), 'sebelumnya')} "
            f"menjadi {names.get(str(current.get('metric')), 'sekarang')}."
        )
    if int(current.get("service", 0) or 0) != int(previous.get("service", 0) or 0):
        notes.append(
            f"Safety stock berubah dari {int(previous.get('service', 0) or 0)}% "
            f"menjadi {int(current.get('service', 0) or 0)}%. "
            "Prediksi QTY tidak berubah karena persentase ini; yang berubah cadangan dan stok disarankan."
        )
    if bool(current.get("exclude_return_cancel", False)) != bool(previous.get("exclude_return_cancel", False)):
        state = "menyala" if current.get("exclude_return_cancel") else "mati"
        notes.append(f"Exclude return dan batal sekarang {state}.")
    if str(current.get("window_start", "")) != str(previous.get("window_start", "")):
        notes.append("Tanggal mulai prediksi bergeser, jadi horizon dihitung dari hari analisis yang baru.")
    return notes
