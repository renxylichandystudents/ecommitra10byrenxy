"""Koneksi database aplikasi (user & riwayat analisa).

Default SQLite di data/app.db. Di Streamlit Community Cloud file ini hilang setiap redeploy;
isi `DATABASE_URL` (mis. postgresql://user:pass@host:5432/db) di secrets agar data tetap ada.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "app.db"


def database_url(secrets: object | None = None) -> str:
    url = ""
    if secrets is not None:
        try:
            url = str(secrets.get("DATABASE_URL", "") or "")
        except Exception:
            url = ""
    url = url or os.getenv("DATABASE_URL", "")
    url = url.strip()
    scheme, sep, rest = url.partition("://")
    if sep and scheme.split("+")[0] in {"postgres", "postgresql"}:
        # Driver yang terpasang hanya psycopg2-binary (lihat requirements.txt).
        url = "postgresql+psycopg2://" + rest
    if not url:
        DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{DEFAULT_DB_PATH}"
    return url


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False}, future=True)
    # Pool kecil: Streamlit Cloud cukup 1–2 koneksi, hemat slot pooler Supabase gratis.
    return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=3, pool_recycle=300, future=True)


def is_sqlite(engine: Engine) -> bool:
    return engine.dialect.name == "sqlite"


def id_column(engine: Engine) -> str:
    return "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite(engine) else "SERIAL PRIMARY KEY"
