"""Hash password bcrypt dan aturan password."""

from __future__ import annotations

import bcrypt

MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(str(password or "").encode("utf-8"), str(hashed or "").encode("ascii"))
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str | None:
    """Pesan kesalahan (Bahasa Indonesia) atau None bila password boleh dipakai."""
    if len(str(password or "")) < MIN_PASSWORD_LENGTH:
        return f"Password minimal {MIN_PASSWORD_LENGTH} karakter."
    if len(str(password).encode("utf-8")) > 72:
        return "Password maksimal 72 byte."
    return None
