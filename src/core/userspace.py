"""Folder data per pengguna.

Lokal (laptop): ~/.prediksi_shopee. Server (Streamlit Community Cloud): folder bersama tim
yang login. Tidak ada lagi ID browser di URL (?uid=); akses diatur oleh login.
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
