"""Cek DATABASE_URL dari laptop sebelum ditempel di Streamlit Cloud.

Pakai:
    .venv/bin/python scripts/cek_database.py
lalu tempel connection string saat diminta (tidak tampil di layar, tidak disimpan).
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from auth.ui import database_error_text  # noqa: E402
from src.core.db import database_url, make_engine  # noqa: E402


def main() -> int:
    raw = getpass.getpass("Tempel DATABASE_URL lalu Enter: ").strip().strip('"').strip("'")
    if not raw:
        print("DATABASE_URL kosong.")
        return 1
    if any(ch.isspace() for ch in raw):
        print("PERINGATAN: URL berisi spasi atau baris baru. Di Secrets tulis dalam satu baris tanpa spasi.")
        raw = "".join(raw.split())
    url = database_url({"DATABASE_URL": raw})
    if url.startswith("sqlite"):
        print("Ini bukan URL Postgres (harus diawali postgresql://).")
        return 1
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version()")).scalar()
    except Exception as exc:  # noqa: BLE001
        print("GAGAL tersambung:", database_error_text(exc))
        return 1
    print("BERHASIL tersambung:", str(version).split(",")[0])
    print('Tempel di Secrets dalam satu baris: DATABASE_URL = "<url tadi>"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
