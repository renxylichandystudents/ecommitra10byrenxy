"""Penjaga kapasitas database agar muat di kuota gratis (Supabase 500 MB).

Batas diatur di config/business_params.yaml bagian `penyimpanan`. Urutan pembersihan:
riwayat analisa di luar N terbaru (file hasil + barisnya), snapshot prediksi di luar M analisa
terbaru, log aktivitas lama, file brankas milik analisa yang sudah dihapus. Bila ukuran database
masih di atas batas darurat, analisa tertua dihapus satu per satu (minimal tersisa `minimal_tersisa`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

DEFAULTS = {
    "maks_riwayat_analisa": 12,
    "maks_snapshot_prediksi": 30,
    "hari_log_aktivitas": 180,
    "batas_darurat_mb": 400,
    "kuota_mb": 500,
    "minimal_tersisa": 3,
}


@dataclass
class GuardReport:
    runs_deleted: list[int] = field(default_factory=list)
    snapshot_runs_deleted: int = 0
    audit_deleted: int = 0
    vault_deleted: int = 0
    size_mb: float | None = None

    @property
    def changed(self) -> bool:
        return bool(self.runs_deleted or self.snapshot_runs_deleted or self.audit_deleted or self.vault_deleted)


def settings(params: dict | None) -> dict:
    raw = dict((params or {}).get("penyimpanan") or {})
    out = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        try:
            out[key] = type(default)(raw.get(key, default))
        except (TypeError, ValueError):
            pass
    return out


def database_size_mb(engine: Engine) -> float | None:
    try:
        if engine.dialect.name == "postgresql":
            with engine.connect() as conn:
                return float(conn.execute(text("SELECT pg_database_size(current_database())")).scalar() or 0) / 1e6
        if engine.dialect.name == "sqlite" and engine.url.database:
            path = Path(engine.url.database)
            return path.stat().st_size / 1e6 if path.exists() else 0.0
    except Exception:
        return None
    return None


def _tables(engine: Engine) -> set[str]:
    from sqlalchemy import inspect

    return set(inspect(engine).get_table_names())


def _run_ids(engine: Engine) -> list[int]:
    with engine.connect() as conn:
        return [int(r[0]) for r in conn.execute(text("SELECT id FROM analysis_runs ORDER BY id DESC")).all()]


def _trim_snapshots(engine: Engine, keep: int) -> int:
    with engine.begin() as conn:
        ids = [int(r[0]) for r in conn.execute(text("SELECT DISTINCT run_id FROM prediction_snapshot ORDER BY run_id DESC")).all()]
        old = ids[keep:]
        for run_id in old:
            conn.execute(text("DELETE FROM prediction_snapshot WHERE run_id = :r"), {"r": run_id})
    return len(old)


def _trim_vault_orphans(engine: Engine, live: set[int]) -> int:
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT path FROM file_vault WHERE path LIKE 'runs/%'")).all()
        orphan = [p for (p,) in rows if not (p.split("/")[1].isdigit() and int(p.split("/")[1]) in live)]
        for path in orphan:
            conn.execute(text("DELETE FROM file_vault WHERE path = :p"), {"p": path})
    return len(orphan)


def _vacuum(engine: Engine, tables: list[str], *, full: bool = False) -> None:
    """VACUUM biasa membuat ruang bisa dipakai ulang; FULL mengembalikan ruang sehingga ukuran database turun."""
    if engine.dialect.name != "postgresql":
        return
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            for name in tables:
                conn.execute(text(f"VACUUM {'FULL ' if full else ''}{name}"))
    except Exception:
        pass


def enforce(engine: Engine, repo, params: dict | None = None, *, now: datetime | None = None) -> GuardReport:
    """Jalankan semua batas. `repo` = RunRepository (hapus folder hasil + baris analisa)."""
    cfg = settings(params)
    report = GuardReport()
    names = _tables(engine)
    keep_runs = max(int(cfg["maks_riwayat_analisa"]), int(cfg["minimal_tersisa"]), 1)
    if "analysis_runs" in names:
        for run_id in _run_ids(engine)[keep_runs:]:
            repo.delete(run_id)
            report.runs_deleted.append(run_id)
    if "prediction_snapshot" in names:
        report.snapshot_runs_deleted = _trim_snapshots(engine, max(int(cfg["maks_snapshot_prediksi"]), 1))
    if "audit_log" in names:
        cutoff = (now or datetime.now()) - timedelta(days=max(int(cfg["hari_log_aktivitas"]), 1))
        with engine.begin() as conn:
            report.audit_deleted = int(conn.execute(text("DELETE FROM audit_log WHERE at < :c"), {"c": cutoff}).rowcount or 0)
    if "file_vault" in names and "analysis_runs" in names:
        report.vault_deleted = _trim_vault_orphans(engine, set(_run_ids(engine)))

    size = database_size_mb(engine)
    if size is not None and size > float(cfg["batas_darurat_mb"]):
        _vacuum(engine, ["file_vault", "prediction_snapshot", "audit_log"], full=True)
        size = database_size_mb(engine)
    floor = max(int(cfg["minimal_tersisa"]), 1)
    while size is not None and size > float(cfg["batas_darurat_mb"]) and "analysis_runs" in names:
        ids = _run_ids(engine)
        if len(ids) <= floor:
            break
        oldest = ids[-1]
        repo.delete(oldest)
        report.runs_deleted.append(oldest)
        with engine.begin() as conn:
            if "prediction_snapshot" in names:
                conn.execute(text("DELETE FROM prediction_snapshot WHERE run_id = :r"), {"r": oldest})
        if "file_vault" in names:
            report.vault_deleted += _trim_vault_orphans(engine, set(_run_ids(engine)))
        _vacuum(engine, ["file_vault", "prediction_snapshot"], full=True)
        size = database_size_mb(engine)
    if report.changed:
        _vacuum(engine, ["file_vault", "prediction_snapshot", "audit_log"])
    report.size_mb = database_size_mb(engine)
    return report
