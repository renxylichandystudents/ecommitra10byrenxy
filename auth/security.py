"""Hash password bcrypt dan aturan password."""

from __future__ import annotations

import bcrypt

MIN_PASSWORD_LENGTH = 10
PASSWORD_RULE = "Minimal 10 karakter, ada huruf besar, huruf kecil, dan angka; bukan password umum; tidak sama dengan username."
COMMON_PASSWORDS = frozenset(
    {
        "password", "password1", "password12", "password123", "password1234", "passw0rd", "qwerty123",
        "qwertyuiop", "1234567890", "12345678910", "admin12345", "administrator", "welcome123",
        "iloveyou123", "abc1234567", "mitra10123", "mitra101234", "shopee1234", "shopee12345",
        "rahasia123", "rahasia1234", "indonesia1", "jakarta123", "bismillah1", "sayang1234",
    }
)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(str(password or "").encode("utf-8"), str(hashed or "").encode("ascii"))
    except (ValueError, TypeError):
        return False


def password_problem(password: str, username: str = "") -> str | None:
    """Pesan kesalahan (Bahasa Indonesia) atau None bila password boleh dipakai."""
    text = str(password or "")
    if len(text) < MIN_PASSWORD_LENGTH:
        return f"Password minimal {MIN_PASSWORD_LENGTH} karakter."
    if len(text.encode("utf-8")) > 72:
        return "Password maksimal 72 byte."
    if not any(ch.isupper() for ch in text) or not any(ch.islower() for ch in text):
        return "Password harus memuat huruf besar dan huruf kecil."
    if not any(ch.isdigit() for ch in text):
        return "Password harus memuat angka."
    if text.lower() in COMMON_PASSWORDS:
        return "Password terlalu umum. Pakai kombinasi lain."
    if username and text.strip().lower() == str(username).strip().lower():
        return "Password tidak boleh sama dengan username."
    return None
