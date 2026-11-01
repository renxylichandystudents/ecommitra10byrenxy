"""Repository user: SQLite (default) atau Postgres lewat connection string yang sama."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

from auth.permissions import ROLES, SUPER_USER
from auth.security import hash_password, password_problem, verify_password
from src.core.db import id_column

MAX_FAILED = 5
LOCK_MINUTES = 5


class AuthError(ValueError):
    """Pesan untuk ditampilkan ke pengguna."""


@dataclass
class User:
    id: int
    username: str
    role: str
    is_active: bool
    must_change_password: bool
    created_at: str = ""
    created_by: str = ""
    last_login_at: str = ""


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


class UserRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.init_schema()

    def init_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    f"""
                    CREATE TABLE IF NOT EXISTS users (
                        id {id_column(self.engine)},
                        username VARCHAR(80) NOT NULL,
                        password_hash VARCHAR(200) NOT NULL,
                        role VARCHAR(40) NOT NULL,
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at VARCHAR(32) NOT NULL,
                        created_by VARCHAR(80),
                        last_login_at VARCHAR(32)
                    )
                    """
                )
            )
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS users_username_ci ON users (lower(username))"))
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS login_attempts (
                        username VARCHAR(80) PRIMARY KEY,
                        failed INTEGER NOT NULL DEFAULT 0,
                        locked_until VARCHAR(32)
                    )
                    """
                )
            )

    @staticmethod
    def _user(row) -> User | None:
        if row is None:
            return None
        m = row._mapping
        return User(
            id=int(m["id"]),
            username=str(m["username"]),
            role=str(m["role"]),
            is_active=bool(m["is_active"]),
            must_change_password=bool(m["must_change_password"]),
            created_at=str(m["created_at"] or ""),
            created_by=str(m["created_by"] or ""),
            last_login_at=str(m["last_login_at"] or ""),
        )

    def count(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0)

    def get(self, username: str) -> User | None:
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM users WHERE lower(username) = lower(:u)"), {"u": username.strip()}).first()
        return self._user(row)

    def list_users(self) -> list[User]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM users ORDER BY lower(username)")).all()
        return [self._user(r) for r in rows]

    def _hash_of(self, username: str) -> str | None:
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT password_hash FROM users WHERE lower(username) = lower(:u)"), {"u": username.strip()}).scalar()

    def create(self, username: str, password: str, role: str, *, created_by: str = "", must_change: bool = True) -> User:
        name = username.strip()
        if not name or len(name) > 80:
            raise AuthError("Username wajib diisi (maks. 80 karakter).")
        if role not in ROLES:
            raise AuthError("Role tidak dikenal.")
        problem = password_problem(password)
        if problem:
            raise AuthError(problem)
        if self.get(name) is not None:
            raise AuthError(f"Username {name} sudah dipakai.")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (username, password_hash, role, is_active, must_change_password, created_at, created_by) "
                    "VALUES (:u, :h, :r, :a, :m, :c, :b)"
                ),
                {"u": name, "h": hash_password(password), "r": role, "a": True, "m": bool(must_change), "c": _now().isoformat(sep=" "), "b": created_by},
            )
        return self.get(name)

    def ensure_initial_superuser(self, username: str | None, password: str | None) -> User | None:
        """Buat super user pertama dari secrets bila tabel users masih kosong."""
        if self.count() > 0 or not username or not password:
            return None
        return self.create(username, password, SUPER_USER, created_by="secrets", must_change=False)

    def _active_super_count(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(text("SELECT COUNT(*) FROM users WHERE role = :r AND is_active = :a"), {"r": SUPER_USER, "a": True}).scalar() or 0)

    def _guard_last_super(self, target: User) -> None:
        if target.role == SUPER_USER and target.is_active and self._active_super_count() <= 1:
            raise AuthError("Super user terakhir tidak boleh dinonaktifkan atau diturunkan role-nya.")

    def set_role(self, username: str, role: str) -> None:
        target = self.get(username)
        if target is None:
            raise AuthError("User tidak ditemukan.")
        if role not in ROLES:
            raise AuthError("Role tidak dikenal.")
        if role != SUPER_USER:
            self._guard_last_super(target)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE users SET role = :r WHERE id = :i"), {"r": role, "i": target.id})

    def set_active(self, username: str, active: bool) -> None:
        target = self.get(username)
        if target is None:
            raise AuthError("User tidak ditemukan.")
        if not active:
            self._guard_last_super(target)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE users SET is_active = :a WHERE id = :i"), {"a": bool(active), "i": target.id})

    def reset_password(self, username: str, new_password: str) -> None:
        """Oleh super user: password sementara, user wajib menggantinya saat login berikutnya."""
        self._store_password(username, new_password, must_change=True)
        self.clear_failures(username)

    def change_password(self, username: str, old_password: str, new_password: str) -> None:
        hashed = self._hash_of(username)
        if hashed is None or not verify_password(old_password, hashed):
            raise AuthError("Password lama salah.")
        if old_password == new_password:
            raise AuthError("Password baru harus berbeda dari password lama.")
        self._store_password(username, new_password, must_change=False)

    def _store_password(self, username: str, password: str, *, must_change: bool) -> None:
        problem = password_problem(password)
        if problem:
            raise AuthError(problem)
        target = self.get(username)
        if target is None:
            raise AuthError("User tidak ditemukan.")
        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE users SET password_hash = :h, must_change_password = :m WHERE id = :i"),
                {"h": hash_password(password), "m": bool(must_change), "i": target.id},
            )

    def _attempt(self, username: str) -> tuple[int, datetime | None]:
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT failed, locked_until FROM login_attempts WHERE username = :u"), {"u": username.strip().lower()}).first()
        if row is None:
            return 0, None
        until = datetime.fromisoformat(row[1]) if row[1] else None
        return int(row[0] or 0), until

    def clear_failures(self, username: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM login_attempts WHERE username = :u"), {"u": username.strip().lower()})

    def _register_failure(self, username: str, now: datetime) -> int:
        failed, _until = self._attempt(username)
        failed += 1
        locked = (now + timedelta(minutes=LOCK_MINUTES)).isoformat(sep=" ") if failed >= MAX_FAILED else None
        key = username.strip().lower()
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM login_attempts WHERE username = :u"), {"u": key})
            conn.execute(
                text("INSERT INTO login_attempts (username, failed, locked_until) VALUES (:u, :f, :l)"),
                {"u": key, "f": 0 if locked else failed, "l": locked},
            )
        return failed

    def authenticate(self, username: str, password: str, *, now: datetime | None = None) -> User:
        now = now or _now()
        _failed, until = self._attempt(username)
        if until is not None and until > now:
            wait = max(int((until - now).total_seconds() // 60) + 1, 1)
            raise AuthError(f"Terlalu banyak percobaan gagal. Coba lagi dalam {wait} menit.")
        user = self.get(username)
        hashed = self._hash_of(username) if user else None
        if user is None or hashed is None or not verify_password(password, hashed):
            failed = self._register_failure(username, now)
            if failed >= MAX_FAILED:
                raise AuthError(f"Login gagal {MAX_FAILED}× berturut-turut. Tunggu {LOCK_MINUTES} menit sebelum mencoba lagi.")
            raise AuthError(f"Username atau password salah ({failed}/{MAX_FAILED}).")
        if not user.is_active:
            raise AuthError("Akun ini dinonaktifkan. Hubungi super user.")
        self.clear_failures(username)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE users SET last_login_at = :t WHERE id = :i"), {"t": now.isoformat(sep=" "), "i": user.id})
        return self.get(username)
