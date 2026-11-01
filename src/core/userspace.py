"""Folder data per pengguna.

Lokal (laptop): ~/.prediksi_shopee. Server (Streamlit Community Cloud): satu folder
per ID browser, supaya pengunjung publik tidak saling melihat data. ID disimpan di
localStorage browser bila komponen tersedia, atau di parameter URL sebagai cadangan.
Isi data tidak pernah disimpan di localStorage.
"""

from __future__ import annotations

import os
import re
import tempfile
import uuid
from pathlib import Path

LOCAL_ROOT = Path.home() / ".prediksi_shopee"
SERVER_ROOT = Path(os.getenv("PREDIKSI_SERVER_ROOT", Path(tempfile.gettempdir()) / "prediksi_shopee"))
_UID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def deploy_mode() -> str:
    """"server" di Streamlit Cloud atau bila PREDIKSI_DEPLOY_MODE=server, selain itu "lokal"."""
    forced = os.getenv("PREDIKSI_DEPLOY_MODE", "").strip().lower()
    if forced in {"server", "lokal"}:
        return forced
    here = str(Path(__file__).resolve())
    if here.startswith("/mount/src") or os.getenv("STREAMLIT_SHARING_MODE") or os.getenv("HOSTNAME", "") == "streamlit":
        return "server"
    return "lokal"


def valid_uid(value: object) -> bool:
    return bool(_UID_PATTERN.match(str(value or "")))


def new_uid() -> str:
    return uuid.uuid4().hex


def user_root(uid: str | None = None) -> Path:
    if deploy_mode() == "lokal":
        root = LOCAL_ROOT
    else:
        safe = uid if valid_uid(uid) else "anon"
        root = SERVER_ROOT / safe
    root.mkdir(parents=True, exist_ok=True)
    return root


def team_root() -> Path:
    """Folder data bersama untuk semua user yang login (satu tim Mitra10)."""
    root = LOCAL_ROOT if deploy_mode() == "lokal" else SERVER_ROOT / "shared"
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_browser_uid(st) -> str | None:
    """Ambil/buat ID browser di mode server. Mode lokal tidak butuh ID."""
    if deploy_mode() == "lokal":
        return None
    cached = st.session_state.get("_browser_uid")
    if valid_uid(cached):
        return cached
    uid: str | None = None
    storage = None
    try:
        from streamlit_local_storage import LocalStorage

        storage = LocalStorage()
        stored = storage.getItem("prediksi_shopee_uid")
        if valid_uid(stored):
            uid = str(stored)
    except Exception:
        storage = None
    if uid is None:
        param = st.query_params.get("uid")
        if valid_uid(param):
            uid = str(param)
    if uid is None:
        uid = new_uid()
    if storage is not None:
        try:
            storage.setItem("prediksi_shopee_uid", uid)
        except Exception:
            pass
    st.query_params["uid"] = uid
    st.session_state["_browser_uid"] = uid
    return uid
