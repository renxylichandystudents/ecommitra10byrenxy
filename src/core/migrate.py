"""Pindahkan isi database & file data dari laptop ke Postgres baru (mis. Supabase).

Tabel dibuat lewat kode aplikasi (skema sama persis dengan yang dipakai app), lalu baris
disalin. File data disimpan ke `file_vault` dengan kunci yang dipakai server Streamlit Cloud:
data latih di `team/…`, hasil analisa di `runs/<id>/…`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from sqlalchemy import Boolean, MetaData, delete, func, insert, inspect, select, text, update
from sqlalchemy.engine import Engine

from src.core.filevault import SKIP_SUFFIXES, VAULT, FileVault, _sha1, pack

SKIP_TABLES = {"sqlite_sequence", "file_vault"}


def prepare_schema(target: Engine, runs_root: Path) -> None:
    from auth.repository import UserRepository
    from src.core.feature_store import FeatureStore
    from src.core.runs import RunRepository

    UserRepository(target)
    FeatureStore(target)
    RunRepository(target, runs_root=runs_root)
    FileVault(target, {})


def target_has_data(target: Engine) -> dict[str, int]:
    names = set(inspect(target).get_table_names())
    counts = {}
    with target.connect() as conn:
        for name in ("users", "analysis_runs", "file_vault"):
            if name in names:
                counts[name] = int(conn.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar() or 0)
    return counts


def copy_tables(source: Engine, target: Engine, log: Callable[[str], None] = print) -> dict[str, int]:
    """Salin semua tabel yang ada di kedua database; isi tabel tujuan diganti."""
    src_meta, dst_meta = MetaData(), MetaData()
    src_meta.reflect(source)
    dst_meta.reflect(target)
    copied: dict[str, int] = {}
    with source.connect() as read, target.begin() as write:
        for name, table in src_meta.tables.items():
            if name in SKIP_TABLES or name not in dst_meta.tables:
                continue
            dest = dst_meta.tables[name]
            shared = [c.name for c in table.columns if c.name in dest.columns]
            flags = {c for c in shared if isinstance(dest.columns[c].type, Boolean)}
            rows = [
                {c: (bool(row[c]) if c in flags and row[c] is not None else row[c]) for c in shared}
                for row in read.execute(select(*[table.c[c] for c in shared])).mappings()
            ]
            write.execute(delete(dest))
            if rows:
                write.execute(insert(dest), rows)
            copied[name] = len(rows)
            if target.dialect.name == "postgresql" and "id" in dest.columns and rows:
                write.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), (SELECT COALESCE(MAX(id), 1) FROM {name}))"
                ))
            log(f"  {name}: {len(rows)} baris")
    return copied


def vault_files(areas: dict[str, Path], run_ids: set[int] | None = None) -> dict[str, Path]:
    """Kunci brankas → file lokal. `areas` memetakan awalan kunci (mis. "team/library") ke folder."""
    files: dict[str, Path] = {}
    for prefix, root in areas.items():
        root = Path(root)
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.name.startswith(".") or path.suffix in SKIP_SUFFIXES or "__pycache__" in path.parts:
                continue
            rel = path.relative_to(root)
            if prefix == "runs" and run_ids is not None and (not rel.parts[0].isdigit() or int(rel.parts[0]) not in run_ids):
                continue
            files[f"{prefix}/{rel.as_posix()}"] = path
    return files


def upload_files(target: Engine, files: dict[str, Path], log: Callable[[str], None] = print) -> tuple[int, int, int]:
    """Simpan file (dikompres) ke file_vault. Hasil: (jumlah file, byte asli, byte tersimpan)."""
    count = raw = stored = 0
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    for key, path in sorted(files.items()):
        data = path.read_bytes()
        body = pack(data)
        values = {"size": len(data), "sha1": _sha1(data), "updated_at": stamp, "data": body}
        with target.begin() as conn:
            if not conn.execute(update(VAULT).where(VAULT.c.path == key).values(**values)).rowcount:
                conn.execute(insert(VAULT).values(path=key, **values))
        count, raw, stored = count + 1, raw + len(data), stored + len(body)
        if count % 25 == 0:
            log(f"  {count}/{len(files)} file…")
    return count, raw, stored


def vault_usage(target: Engine) -> tuple[int, int]:
    with target.connect() as conn:
        count, stored = conn.execute(select(func.count(), func.coalesce(func.sum(func.length(VAULT.c.data)), 0))).one()
    return int(count or 0), int(stored or 0)
