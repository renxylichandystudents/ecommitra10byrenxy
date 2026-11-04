"""Brankas file di database: data latih dan hasil analisa tetap ada walau disk server terhapus.

Disk Streamlit Community Cloud bersifat sementara (hilang saat app tidur, restart, atau redeploy).
Folder data tetap dipakai seperti biasa; brankas ini menyalin setiap file yang berubah ke tabel
`file_vault` dan menulis ulang file yang hilang saat proses server baru mulai. Aktif hanya bila
database bukan SQLite (mis. Postgres Neon lewat DATABASE_URL).
"""

from __future__ import annotations

import hashlib
import os
import threading
from datetime import datetime
from pathlib import Path

from sqlalchemy import BigInteger, Column, LargeBinary, MetaData, String, Table, delete, insert, select, update
from sqlalchemy.engine import Engine

MAX_FILE_BYTES = 200 * 1024 * 1024
SKIP_SUFFIXES = (".tmp", ".lock", ".pyc")

_meta = MetaData()
VAULT = Table(
    "file_vault",
    _meta,
    Column("path", String(512), primary_key=True),
    Column("size", BigInteger, nullable=False),
    Column("sha1", String(40), nullable=False),
    Column("updated_at", String(32), nullable=False),
    Column("data", LargeBinary, nullable=False),
)


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def vault_enabled(engine: Engine) -> bool:
    forced = os.getenv("PREDIKSI_FILE_VAULT", "").strip().lower()
    if forced in {"0", "off", "false"}:
        return False
    if forced in {"1", "on", "true"}:
        return True
    return engine.dialect.name != "sqlite"


class FileVault:
    """Sinkron dua arah sederhana: disk → database setiap ada perubahan, database → disk bila file hilang."""

    def __init__(self, engine: Engine, areas: dict[str, Path]) -> None:
        self.engine = engine
        self.areas = {name: Path(root) for name, root in areas.items()}
        self._seen: dict[str, tuple[int, int]] = {}
        self._hashes: dict[str, str] = {}
        self._lock = threading.Lock()
        _meta.create_all(engine, tables=[VAULT])

    def _local_files(self) -> dict[str, Path]:
        files: dict[str, Path] = {}
        for area, root in self.areas.items():
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.name.startswith(".") or path.suffix in SKIP_SUFFIXES or "__pycache__" in path.parts:
                    continue
                files[f"{area}/{path.relative_to(root).as_posix()}"] = path
        return files

    def _path_for(self, key: str) -> Path | None:
        area, _, rel = key.partition("/")
        root = self.areas.get(area)
        if root is None or not rel or ".." in Path(rel).parts:
            return None
        return root / rel

    def restore(self) -> int:
        """Tulis ulang file yang ada di database tetapi tidak ada di disk. Hasil: jumlah file dipulihkan."""
        restored = 0
        with self._lock, self.engine.connect() as conn:
            rows = conn.execute(select(VAULT.c.path, VAULT.c.sha1)).all()
            for key, digest in rows:
                target = self._path_for(key)
                if target is None:
                    continue
                self._hashes[key] = digest
                if target.exists():
                    continue
                data = conn.execute(select(VAULT.c.data).where(VAULT.c.path == key)).scalar()
                if data is None:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                partial = target.with_name(target.name + ".tmp")
                partial.write_bytes(bytes(data))
                partial.replace(target)
                restored += 1
        return restored

    def push(self) -> int:
        """Simpan file baru/berubah ke database dan hapus yang sudah dihapus di disk. Hasil: jumlah perubahan."""
        changes = 0
        with self._lock:
            files = self._local_files()
            with self.engine.begin() as conn:
                for key, path in files.items():
                    try:
                        info = path.stat()
                    except OSError:
                        continue
                    stamp = (info.st_size, info.st_mtime_ns)
                    if self._seen.get(key) == stamp or info.st_size > MAX_FILE_BYTES:
                        continue
                    data = path.read_bytes()
                    digest = _sha1(data)
                    self._seen[key] = stamp
                    if self._hashes.get(key) == digest:
                        continue
                    values = {"size": len(data), "sha1": digest, "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"), "data": data}
                    done = conn.execute(update(VAULT).where(VAULT.c.path == key).values(**values)).rowcount
                    if not done:
                        conn.execute(insert(VAULT).values(path=key, **values))
                    self._hashes[key] = digest
                    changes += 1
                for key in [key for key in self._seen if key not in files]:
                    conn.execute(delete(VAULT).where(VAULT.c.path == key))
                    self._seen.pop(key, None)
                    self._hashes.pop(key, None)
                    changes += 1
        return changes

    def summary(self) -> tuple[int, int]:
        """(jumlah file, total byte) yang tersimpan di brankas."""
        from sqlalchemy import func

        with self.engine.connect() as conn:
            count, total = conn.execute(select(func.count(), func.coalesce(func.sum(VAULT.c.size), 0))).one()
        return int(count or 0), int(total or 0)
