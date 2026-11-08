"""Pindahkan user, riwayat analisa, setting, dan data latih dari laptop ke Supabase (sekali jalan).

Pakai:
    .venv/bin/python scripts/pindah_ke_supabase.py
lalu tempel URI Session pooler dari Supabase (tidak tampil di layar, tidak disimpan).

Sumber: database lokal data/app.db, folder ~/.prediksi_shopee, uploads/library,
uploads/analysis_runs, dan data/runs (hanya analisa yang tercatat di database).
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from auth.ui import database_error_text  # noqa: E402
from src.core import migrate  # noqa: E402
from src.core.db import DEFAULT_DB_PATH, database_url, make_engine  # noqa: E402
from src.core.runs import DEFAULT_RUNS_ROOT  # noqa: E402
from src.core.userspace import LOCAL_ROOT  # noqa: E402


def main() -> int:
    if not DEFAULT_DB_PATH.exists():
        print(f"Database lokal tidak ditemukan: {DEFAULT_DB_PATH}")
        return 1
    raw = "".join(getpass.getpass("Tempel URI Session pooler Supabase lalu Enter: ").strip().strip('"').strip("'").split())
    url = database_url({"DATABASE_URL": raw})
    if url.startswith("sqlite"):
        print("Ini bukan URL Postgres (harus diawali postgresql://).")
        return 1
    target = make_engine(url)
    try:
        with target.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        print("GAGAL tersambung:", database_error_text(exc))
        return 1
    source = make_engine(f"sqlite:///{DEFAULT_DB_PATH}")

    print("1/3 Menyiapkan tabel di Supabase…")
    migrate.prepare_schema(target, DEFAULT_RUNS_ROOT)
    existing = {k: v for k, v in migrate.target_has_data(target).items() if v}
    if existing:
        print("Supabase sudah berisi data:", ", ".join(f"{k} {v} baris" for k, v in existing.items()))
        if input("Timpa dengan data laptop? ketik YA: ").strip().upper() != "YA":
            print("Dibatalkan, tidak ada yang diubah.")
            return 1

    print("2/3 Menyalin tabel (user, riwayat analisa, setting, target, gudang, margin)…")
    migrate.copy_tables(source, target)

    with source.connect() as conn:
        run_ids = {int(r[0]) for r in conn.execute(text("SELECT id FROM analysis_runs")).all()}
    files = migrate.vault_files(
        {
            "team": LOCAL_ROOT,
            "team/library": ROOT / "uploads" / "library",
            "team/analysis_runs": ROOT / "uploads" / "analysis_runs",
            "runs": DEFAULT_RUNS_ROOT,
        },
        run_ids,
    )
    print(f"3/3 Mengunggah {len(files)} file data (dikompres)…")
    count, size, stored = migrate.upload_files(target, files)
    total_files, total_stored = migrate.vault_usage(target)
    print(f"Selesai: {count} file, {size / 1e6:.1f} MB → {stored / 1e6:.1f} MB setelah kompresi.")
    print(f"Brankas Supabase sekarang {total_files} file, {total_stored / 1e6:.1f} MB dari kuota gratis 500 MB.")
    print('Tempel di Streamlit Cloud › Settings › Secrets: DATABASE_URL = "<URI tadi>", lalu Reboot app.')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
