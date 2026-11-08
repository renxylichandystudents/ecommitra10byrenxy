"""Alur harian: upload data → jalankan analisa → lihat hasil.

Transaksi diunggah setiap hari; data lain cukup diunggah bila berubah. Analisa yang dipakai selalu
analisa sukses terakhir, dan analisa harian mengulang setelannya dengan bulan data terbaru.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

DAILY_SOURCES = frozenset({"transactions"})

STATE_EMPTY = "kosong"
STATE_NEW_DATA = "data_baru"
STATE_CURRENT = "terbaru"
STATE_WAITING = "menunggu_data"

ACTION_UPLOAD = "upload"
ACTION_RUN = "run"
ACTION_VIEW = "view"

STATE_ACTION = {
    STATE_EMPTY: ACTION_UPLOAD,
    STATE_NEW_DATA: ACTION_RUN,
    STATE_CURRENT: ACTION_VIEW,
    STATE_WAITING: ACTION_UPLOAD,
}


def _dated(keys: Iterable[str]) -> list[str]:
    return sorted({str(k) for k in keys if str(k)[:4].isdigit()})


def next_run_keys(previous: Iterable[str], saved: Iterable[str]) -> tuple[str, ...]:
    """Bulan analisa berikutnya: mulai bulan pertama analisa sebelumnya sampai bulan tersimpan terbaru.

    Bulan baru (mis. awal bulan) otomatis ikut; bulan awal yang sengaja tidak dipakai tetap tidak ikut.
    """
    previous = [str(k) for k in previous]
    saved = [str(k) for k in saved]
    dated = _dated(saved)
    before = _dated(previous)
    start = before[0] if before else (dated[0] if dated else "")
    undated = sorted(k for k in set(saved) if not k[:4].isdigit() and (not previous or k in previous))
    return tuple([k for k in dated if k >= start] + undated)


def analysis_state(*, has_run: bool, run_day: date | None, today: date, data_changed: bool) -> str:
    if not has_run:
        return STATE_EMPTY
    if data_changed:
        return STATE_NEW_DATA
    if run_day == today:
        return STATE_CURRENT
    return STATE_WAITING


def upload_due(source_key: str, updated: date | None, today: date) -> bool:
    """Perlu diunggah hari ini: hanya data harian (transaksi) yang belum diunggah hari ini."""
    return source_key in DAILY_SOURCES and (updated is None or updated < today)


def upload_rhythm(source_key: str) -> str:
    return "Setiap hari" if source_key in DAILY_SOURCES else "Bila ada perubahan"
