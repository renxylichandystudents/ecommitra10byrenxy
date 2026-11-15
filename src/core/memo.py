"""Cache hasil hitung per objek DataFrame (identitas objek), untuk frame besar yang sama di setiap klik.

Frame transaksi/katalog analisa disimpan di session_state atau cache Streamlit dan tetap objek yang sama
antar-rerun. Menghash isinya (st.cache_data) untuk frame 60 ribu baris memakan waktu hampir sama dengan
menghitung ulang, jadi kunci cache memakai identitas objek + bentuk + nama kolom. Entri dibuang otomatis
saat frame asal dibuang dari memori (weakref).
"""

from __future__ import annotations

import threading
import weakref
from typing import Any, Callable

import pandas as pd

_STORE: dict[tuple, tuple[weakref.ref, Any]] = {}
_LOCK = threading.Lock()
MAX_ENTRIES = 256


def _signature(frame: pd.DataFrame) -> tuple:
    return (id(frame), frame.shape, tuple(map(str, frame.columns)))


def by_frame(name: str, frame: pd.DataFrame | None, extra: tuple, compute: Callable[[], Any]) -> Any:
    """Hasil compute() untuk frame ini (+ argumen tambahan `extra` yang harus hashable)."""
    if not isinstance(frame, pd.DataFrame):
        return compute()
    key = (name, _signature(frame), extra)
    with _LOCK:
        hit = _STORE.get(key)
    if hit is not None and hit[0]() is frame:
        return hit[1]
    value = compute()
    try:
        ref = weakref.ref(frame, lambda _ref, k=key: _STORE.pop(k, None))
    except TypeError:
        return value
    with _LOCK:
        if len(_STORE) >= MAX_ENTRIES:
            _STORE.pop(next(iter(_STORE)), None)
        _STORE[key] = (ref, value)
    return value


def clear() -> None:
    with _LOCK:
        _STORE.clear()


def fingerprint(frame: pd.DataFrame | None, columns: list[str] | None = None) -> tuple:
    """Sidik isi frame kecil–menengah (mis. katalog ±800 SKU) untuk kunci cache bila objeknya dibuat ulang tiap klik."""
    if not isinstance(frame, pd.DataFrame):
        return (None,)
    use = [c for c in (columns or list(frame.columns)) if c in frame.columns]
    try:
        values = pd.util.hash_pandas_object(frame[use].astype(str), index=False).values
        return (frame.shape, tuple(use), hash(values.tobytes()))
    except Exception:  # noqa: BLE001
        return (id(frame), frame.shape)


_SHARED: dict[str, dict] = {}


def shared(name: str, limit: int = 8) -> dict:
    """Wadah hasil hitung bersama antar-sesi (per proses server). Pemanggil memangkas sendiri lewat trim()."""
    box = _SHARED.setdefault(name, {})
    box.setdefault("__limit__", limit)
    return box


def remember(box: dict, key, value) -> None:
    limit = int(box.get("__limit__", 8))
    box[key] = value
    keys = [k for k in box if k != "__limit__"]
    while len(keys) > limit:
        box.pop(keys.pop(0), None)
