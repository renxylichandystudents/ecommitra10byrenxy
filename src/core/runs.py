"""Riwayat analisa: metadata di tabel analysis_runs, hasil lengkap di data/runs/<id>/."""

from __future__ import annotations

import hashlib
import json
import pickle
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.core.db import id_column

DEFAULT_RUNS_ROOT = Path(__file__).resolve().parents[2] / "data" / "runs"
RETENTION_DAYS = 90
STATUS_OK = "sukses"
STATUS_FAILED = "gagal"
STATE_FILE = "state.pkl"
MANIFEST_FILE = "manifest.json"


@dataclass
class RunRecord:
    id: int
    run_at: str
    run_by: str
    periode: str
    tgl_mulai: str
    tgl_akhir: str
    parameter: str
    safety_stock: int
    exclude_batal_retur: bool
    data_hash: str
    status: str
    durasi_detik: float
    result_path: str


def data_hash(paths: Iterable[Path], extra: str = "") -> str:
    """Sidik isi file data latih (bukan waktu ubah), supaya unggah ulang file yang sama tetap terdeteksi sama."""
    digest = hashlib.sha256(extra.encode("utf-8"))
    for path in sorted(Path(p) for p in paths):
        digest.update(path.name.encode("utf-8"))
        try:
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
        except OSError:
            digest.update(b"<missing>")
    return digest.hexdigest()


def _has_nested(frame: pd.DataFrame) -> bool:
    """Parquet mengembalikan list/dict sebagai numpy array; kolom seperti itu disimpan pickle agar identik."""
    for column in frame.columns[frame.dtypes.eq(object)]:
        sample = frame[column].dropna().head(500)
        if sample.map(lambda value: isinstance(value, (list, tuple, dict, set, frozenset)) or hasattr(value, "shape")).any():
            return True
    return False


def _write_frame(frame: pd.DataFrame, folder: Path, name: str) -> str:
    target = folder / f"{name}.parquet"
    fallback = folder / f"{name}.pkl"
    if not _has_nested(frame):
        try:
            frame.to_parquet(target, index=True)
            return target.name
        except Exception:
            target.unlink(missing_ok=True)
    frame.to_pickle(fallback)
    return fallback.name


def save_result(folder: Path, result: dict) -> None:
    """DataFrame → Parquet (pickle bila kolomnya tidak didukung Parquet); objek lain → state.pkl."""
    folder.mkdir(parents=True, exist_ok=True)
    frames: dict[str, str] = {}
    aliases: dict[str, str] = {}
    seen: dict[int, str] = {}
    state: dict = {}
    for key, value in result.items():
        if isinstance(value, pd.DataFrame):
            if id(value) in seen:
                aliases[key] = seen[id(value)]
                continue
            seen[id(value)] = key
            frames[key] = _write_frame(value, folder, key)
        else:
            state[key] = value
    with open(folder / STATE_FILE, "wb") as handle:
        pickle.dump(state, handle, protocol=pickle.HIGHEST_PROTOCOL)
    (folder / MANIFEST_FILE).write_text(json.dumps({"frames": frames, "aliases": aliases}), encoding="utf-8")


def load_result(folder: Path) -> dict:
    manifest = json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))
    with open(folder / STATE_FILE, "rb") as handle:
        result = dict(pickle.load(handle))
    for key, filename in manifest.get("frames", {}).items():
        path = folder / filename
        result[key] = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_pickle(path)
    for key, source in manifest.get("aliases", {}).items():
        result[key] = result[source]
    for key, filename in manifest.get("blobs", {}).items():
        with open(folder / filename, "rb") as handle:
            result[key] = pickle.load(handle)
    return result


class RunRepository:
    def __init__(self, engine: Engine, runs_root: Path | None = None) -> None:
        self.engine = engine
        self.runs_root = Path(runs_root or DEFAULT_RUNS_ROOT)
        self.runs_root.mkdir(parents=True, exist_ok=True)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    f"""
                    CREATE TABLE IF NOT EXISTS analysis_runs (
                        id {id_column(self.engine)},
                        run_at VARCHAR(32) NOT NULL,
                        run_by VARCHAR(80) NOT NULL,
                        periode VARCHAR(20) NOT NULL,
                        tgl_mulai VARCHAR(10),
                        tgl_akhir VARCHAR(10),
                        parameter VARCHAR(20) NOT NULL,
                        safety_stock INTEGER NOT NULL,
                        exclude_batal_retur BOOLEAN NOT NULL,
                        data_hash VARCHAR(64) NOT NULL,
                        status VARCHAR(20) NOT NULL,
                        durasi_detik REAL,
                        result_path VARCHAR(400)
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS analysis_runs_hash ON analysis_runs (data_hash, run_at)"))

    @staticmethod
    def _record(row) -> RunRecord | None:
        if row is None:
            return None
        m = row._mapping
        return RunRecord(
            id=int(m["id"]),
            run_at=str(m["run_at"]),
            run_by=str(m["run_by"]),
            periode=str(m["periode"]),
            tgl_mulai=str(m["tgl_mulai"] or ""),
            tgl_akhir=str(m["tgl_akhir"] or ""),
            parameter=str(m["parameter"]),
            safety_stock=int(m["safety_stock"]),
            exclude_batal_retur=bool(m["exclude_batal_retur"]),
            data_hash=str(m["data_hash"]),
            status=str(m["status"]),
            durasi_detik=float(m["durasi_detik"] or 0.0),
            result_path=str(m["result_path"] or ""),
        )

    def save(
        self,
        result: dict,
        *,
        run_by: str,
        periode: str,
        tgl_mulai: date | str,
        tgl_akhir: date | str,
        parameter: str,
        safety_stock: int,
        exclude: bool,
        data_hash: str,
        duration: float,
        now: datetime | None = None,
    ) -> RunRecord:
        """Catat analisa sukses dan simpan hasil lengkapnya."""
        stamp = (now or datetime.now()).replace(microsecond=0)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO analysis_runs (run_at, run_by, periode, tgl_mulai, tgl_akhir, parameter, safety_stock, "
                    "exclude_batal_retur, data_hash, status, durasi_detik, result_path) "
                    "VALUES (:run_at, :run_by, :periode, :mulai, :akhir, :parameter, :ss, :exclude, :hash, :status, :durasi, '')"
                ),
                {
                    "run_at": stamp.isoformat(sep=" "),
                    "run_by": run_by,
                    "periode": periode,
                    "mulai": str(tgl_mulai)[:10],
                    "akhir": str(tgl_akhir)[:10],
                    "parameter": parameter,
                    "ss": int(safety_stock),
                    "exclude": bool(exclude),
                    "hash": data_hash,
                    "status": STATUS_OK,
                    "durasi": round(float(duration), 2),
                },
            )
            run_id = int(conn.execute(text("SELECT MAX(id) FROM analysis_runs")).scalar())
        folder = self.runs_root / str(run_id)
        try:
            save_result(folder, result)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            with self.engine.begin() as conn:
                conn.execute(text("UPDATE analysis_runs SET status = :s WHERE id = :i"), {"s": STATUS_FAILED, "i": run_id})
            raise
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE analysis_runs SET result_path = :p WHERE id = :i"), {"p": str(folder), "i": run_id})
        return self.get(run_id)

    def save_extra(self, run_id: int, name: str, frame: pd.DataFrame) -> None:
        """Tambahan tabel hasil (mis. katalog prediksi lengkap) ke folder run yang sudah ada."""
        record = self.get(run_id)
        if record is None or not self.available(record):
            return
        folder = self.folder_of(record)
        manifest_path = folder / MANIFEST_FILE
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.setdefault("frames", {})[name] = _write_frame(frame, folder, name)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def save_blob(self, run_id: int, name: str, value: object) -> None:
        """Objek Python tambahan (mis. cache pergerakan stok) agar Buka tidak menghitung ulang."""
        record = self.get(run_id)
        if record is None or not self.available(record):
            return
        folder = self.folder_of(record)
        filename = f"blob_{name}.pkl"
        with open(folder / filename, "wb") as handle:
            pickle.dump(value, handle, protocol=pickle.HIGHEST_PROTOCOL)
        manifest_path = folder / MANIFEST_FILE
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.setdefault("blobs", {})[name] = filename
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def get(self, run_id: int) -> RunRecord | None:
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM analysis_runs WHERE id = :i"), {"i": int(run_id)}).first()
        return self._record(row)

    def list_runs(self, limit: int = 50) -> list[RunRecord]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM analysis_runs ORDER BY run_at DESC, id DESC LIMIT :n"), {"n": int(limit)}).all()
        return [self._record(r) for r in rows]

    def folder_of(self, record: RunRecord) -> Path:
        folder = Path(record.result_path) if record.result_path else self.runs_root / str(record.id)
        return folder if folder.exists() else self.runs_root / str(record.id)

    def available(self, record: RunRecord) -> bool:
        """File hasil masih ada (di server sementara, file bisa hilang saat restart walau baris DB tetap)."""
        return record.status == STATUS_OK and (self.folder_of(record) / MANIFEST_FILE).exists()

    def last_success(self) -> RunRecord | None:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM analysis_runs WHERE status = :s AND result_path <> '' ORDER BY run_at DESC, id DESC LIMIT 20"),
                {"s": STATUS_OK},
            ).all()
        for row in rows:
            record = self._record(row)
            if self.available(record):
                return record
        return None

    def find_duplicate(
        self,
        *,
        data_hash: str,
        periode: str,
        parameter: str,
        safety_stock: int,
        exclude: bool,
        day: date | None = None,
    ) -> RunRecord | None:
        """Analisa sukses hari ini dengan data latih dan parameter yang sama."""
        day = day or date.today()
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT * FROM analysis_runs WHERE status = :s AND data_hash = :h AND periode = :p AND parameter = :m "
                    "AND safety_stock = :ss AND exclude_batal_retur = :e AND run_at >= :lo AND run_at < :hi AND result_path <> '' "
                    "ORDER BY run_at DESC, id DESC LIMIT 1"
                ),
                {
                    "s": STATUS_OK,
                    "h": data_hash,
                    "p": periode,
                    "m": parameter,
                    "ss": int(safety_stock),
                    "e": bool(exclude),
                    "lo": day.isoformat(),
                    "hi": (day + timedelta(days=1)).isoformat(),
                },
            ).first()
        record = self._record(row)
        return record if record is not None and self.available(record) else None

    def load(self, run_id: int) -> tuple[RunRecord, dict]:
        record = self.get(run_id)
        if record is None or not self.available(record):
            raise FileNotFoundError("file hasil tidak ditemukan (server mungkin sudah restart).")
        return record, load_result(self.folder_of(record))

    def delete(self, run_id: int) -> None:
        record = self.get(run_id)
        if record is None:
            return
        shutil.rmtree(self.runs_root / str(record.id), ignore_errors=True)
        if record.result_path:
            shutil.rmtree(record.result_path, ignore_errors=True)
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM analysis_runs WHERE id = :i"), {"i": record.id})

    def cleanup(self, *, days: int = RETENTION_DAYS, now: datetime | None = None) -> int:
        cutoff = ((now or datetime.now()) - timedelta(days=days)).isoformat(sep=" ")
        with self.engine.connect() as conn:
            ids = [int(r[0]) for r in conn.execute(text("SELECT id FROM analysis_runs WHERE run_at < :c"), {"c": cutoff}).all()]
        for run_id in ids:
            self.delete(run_id)
        return len(ids)
