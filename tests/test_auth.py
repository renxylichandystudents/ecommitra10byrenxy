import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from auth.permissions import (
    ECOMMERCE_SPECIALIST,
    ROLES,
    SUPER_USER,
    TEAM_DC as GUDANG,
    TEAM_ICMD as IC,
    allowed_sheets,
    can,
)
from src.core.access import allowed, setting_tabs
from auth.repository import AuthError, UserRepository
from auth.security import hash_password, password_problem, verify_password
from src.core.db import database_url, make_engine

SHEETS = ("Ringkasan", "Prediksi", "Data", "Folder data", "Rekomendasi", "Laporan", "Evaluasi model")


def _repo(folder: str) -> UserRepository:
    return UserRepository(make_engine(f"sqlite:///{Path(folder) / 'app.db'}"))


class SecurityTests(unittest.TestCase):
    def test_hash_and_verify(self):
        hashed = hash_password("Rahasia1234")
        self.assertNotEqual(hashed, "Rahasia1234")
        self.assertTrue(verify_password("Rahasia1234", hashed))
        self.assertFalse(verify_password("Rahasia1235", hashed))
        self.assertFalse(verify_password("Rahasia1234", "bukan-hash"))

    def test_password_policy(self):
        self.assertIsNotNone(password_problem("Abc12345"))  # < 10
        self.assertIsNotNone(password_problem("abcdefgh12"))  # tanpa huruf besar
        self.assertIsNotNone(password_problem("ABCDEFGH12"))  # tanpa huruf kecil
        self.assertIsNotNone(password_problem("Abcdefghij"))  # tanpa angka
        self.assertIsNotNone(password_problem("Password123"))  # umum
        self.assertIsNotNone(password_problem("Gudang12345", "gudang12345"))  # sama dengan username
        self.assertIsNone(password_problem("Gudang12345", "gudang1"))


class PermissionTests(unittest.TestCase):
    def test_roles(self):
        self.assertEqual(ROLES, ("super_user", "ecommerce_specialist", "team_dc", "team_icmd"))

    def test_matrix(self):
        for role in ROLES:
            for perm in ("beranda", "riwayat_analisa", "ringkasan", "prediksi", "prediksi_vs_aktual", "ubah_password"):
                self.assertTrue(can(role, perm), (role, perm))
        for perm in ("data", "folder_data", "rekomendasi", "laporan", "jalankan_analisa", "ubah_data_latih"):
            self.assertTrue(can(SUPER_USER, perm))
            self.assertTrue(can(ECOMMERCE_SPECIALIST, perm))
            self.assertFalse(can(IC, perm))
            self.assertFalse(can(GUDANG, perm))
        self.assertTrue(can(ECOMMERCE_SPECIALIST, "evaluasi_model"))
        self.assertFalse(allowed(ECOMMERCE_SPECIALIST, "evaluasi_model", "edit"))
        for perm in ("kelola_user", "hapus_riwayat"):
            self.assertTrue(can(SUPER_USER, perm))
            for role in (ECOMMERCE_SPECIALIST, IC, GUDANG):
                self.assertFalse(can(role, perm))
        self.assertFalse(can(None, "beranda"))
        self.assertFalse(can(SUPER_USER, "tidak-ada"))

    def test_special_levels(self):
        self.assertTrue(allowed(GUDANG, "setting_kapasitas_gudang", "upload"))
        self.assertFalse(allowed(GUDANG, "setting_kapasitas_gudang", "edit"))
        self.assertFalse(allowed(IC, "setting_kapasitas_gudang", "upload"))
        self.assertTrue(allowed(IC, "setting_kedatangan_impor", "write_note"))
        self.assertFalse(allowed(GUDANG, "setting_kedatangan_impor", "write_note"))
        self.assertTrue(allowed(SUPER_USER, "setting_kedatangan_impor", "write_note"))
        self.assertFalse(allowed(GUDANG, "data_latih"))
        self.assertEqual([t[1] for t in setting_tabs(GUDANG)], ["Kapasitas gudang", "Kedatangan impor"])
        self.assertIn("Kelola user", [t[1] for t in setting_tabs(SUPER_USER)])
        self.assertNotIn("Kelola user", [t[1] for t in setting_tabs(ECOMMERCE_SPECIALIST)])

    def test_menu_from_permissions(self):
        self.assertEqual(allowed_sheets(GUDANG, SHEETS), ["Ringkasan", "Prediksi"])
        self.assertEqual(allowed_sheets(ECOMMERCE_SPECIALIST, SHEETS), list(SHEETS))
        self.assertEqual(allowed_sheets(SUPER_USER, SHEETS), list(SHEETS))
        self.assertEqual(allowed_sheets("GUDANG", SHEETS), ["Ringkasan", "Prediksi"])


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = _repo(self.tmp.name)

    def tearDown(self):
        self.repo.engine.dispose()
        self.tmp.cleanup()

    def test_initial_superuser_only_when_empty(self):
        self.assertIsNone(self.repo.ensure_initial_superuser("", ""))
        admin = self.repo.ensure_initial_superuser("Admin", "Admin12345x")
        self.assertEqual(admin.role, SUPER_USER)
        self.assertFalse(admin.must_change_password)
        self.assertIsNone(self.repo.ensure_initial_superuser("lain", "Lain123456"))
        self.assertEqual(self.repo.count(), 1)

    def test_username_case_insensitive_unique(self):
        self.repo.create("Renxy", "Renxy12345x", SUPER_USER)
        with self.assertRaises(AuthError):
            self.repo.create("renxy", "Renxy12345y", IC)
        self.assertEqual(self.repo.get("RENXY").username, "Renxy")

    def test_last_super_user_cannot_be_disabled_or_demoted(self):
        self.repo.create("admin", "Admin12345x", SUPER_USER, must_change=False)
        with self.assertRaises(AuthError):
            self.repo.set_active("admin", False)
        with self.assertRaises(AuthError):
            self.repo.set_role("admin", IC)
        self.repo.create("admin2", "Admin12345x", SUPER_USER)
        self.repo.set_active("admin", False)
        self.assertFalse(self.repo.get("admin").is_active)
        with self.assertRaises(AuthError):
            self.repo.set_active("admin2", False)

    def test_must_change_password_flow(self):
        self.repo.create("gudang1", "Sementara12", GUDANG, created_by="admin")
        user = self.repo.authenticate("gudang1", "Sementara12")
        self.assertTrue(user.must_change_password)
        with self.assertRaises(AuthError):
            self.repo.change_password("gudang1", "Salah123456", "Baru1234567")
        with self.assertRaises(AuthError):
            self.repo.change_password("gudang1", "Sementara12", "pendek")
        self.repo.change_password("gudang1", "Sementara12", "Baru1234567")
        self.assertFalse(self.repo.get("gudang1").must_change_password)
        self.repo.reset_password("gudang1", "Reset123456")
        self.assertTrue(self.repo.get("gudang1").must_change_password)
        self.assertTrue(self.repo.authenticate("gudang1", "Reset123456").must_change_password)

    def test_lockout_after_five_failures(self):
        self.repo.create("ic1", "Benar123456", IC)
        now = datetime(2026, 11, 1, 9, 0, 0)
        for _ in range(5):
            with self.assertRaises(AuthError):
                self.repo.authenticate("ic1", "salah", now=now)
        with self.assertRaises(AuthError) as ctx:
            self.repo.authenticate("ic1", "Benar123456", now=now + timedelta(minutes=14))
        self.assertIn("Coba lagi", str(ctx.exception))
        user = self.repo.authenticate("ic1", "Benar123456", now=now + timedelta(minutes=15, seconds=1))
        self.assertEqual(user.username, "ic1")
        self.assertTrue(user.last_login_at.startswith("2026-11-01 09:15"))

    def test_failure_message_shows_remaining_attempts(self):
        self.repo.create("ic1", "Benar123456", IC)
        with self.assertRaises(AuthError) as ctx:
            self.repo.authenticate("ic1", "salah")
        self.assertIn("Sisa percobaan: 4", str(ctx.exception))

    def test_legacy_roles_and_forced_password_change_migrate_once(self):
        engine = self.repo.engine
        self.repo.create("lama", "Lama1234567", SUPER_USER, must_change=False)
        with engine.begin() as conn:
            conn.exec_driver_sql("UPDATE users SET role = 'GUDANG' WHERE username = 'lama'")
            conn.exec_driver_sql("DELETE FROM auth_migrations")
        UserRepository(engine)
        migrated = self.repo.get("lama")
        self.assertEqual(migrated.role, GUDANG)
        self.assertTrue(migrated.must_change_password)
        self.repo.change_password("lama", "Lama1234567", "Baru1234567")
        UserRepository(engine)
        self.assertFalse(self.repo.get("lama").must_change_password)

    def test_inactive_user_cannot_login(self):
        self.repo.create("admin", "Admin12345x", SUPER_USER)
        self.repo.create("ec1", "Ecom1234567", ECOMMERCE_SPECIALIST)
        self.repo.set_active("ec1", False)
        with self.assertRaises(AuthError):
            self.repo.authenticate("ec1", "Ecom1234567")

    def test_session_token_restore_and_expiry(self):
        user = self.repo.create("ec1", "Ecom1234567", ECOMMERCE_SPECIALIST, must_change=False)
        now = datetime(2026, 11, 1, 9, 0, 0)
        token = self.repo.create_session(user, now=now)
        self.assertGreaterEqual(len(token), 32)
        with self.repo.engine.connect() as conn:
            stored = [row[0] for row in conn.exec_driver_sql("SELECT token_hash FROM sessions")]
        self.assertNotIn(token, stored)
        self.assertEqual(self.repo.user_for_token(token, now=now + timedelta(hours=11)).username, "ec1")
        self.assertIsNone(self.repo.user_for_token(token, now=now + timedelta(hours=12, seconds=1)))
        self.assertIsNone(self.repo.user_for_token("palsu", now=now))
        self.assertIsNone(self.repo.user_for_token(None, now=now))

    def test_logout_deletes_only_that_token(self):
        user = self.repo.create("ec1", "Ecom1234567", ECOMMERCE_SPECIALIST, must_change=False)
        first, second = self.repo.create_session(user), self.repo.create_session(user)
        self.repo.delete_session(first)
        self.assertIsNone(self.repo.user_for_token(first))
        self.assertIsNotNone(self.repo.user_for_token(second))

    def test_deactivate_and_reset_revoke_all_sessions(self):
        self.repo.create("admin", "Admin12345x", SUPER_USER, must_change=False)
        user = self.repo.create("ec1", "Ecom1234567", ECOMMERCE_SPECIALIST, must_change=False)
        tokens = [self.repo.create_session(user) for _ in range(2)]
        self.repo.reset_password("ec1", "Reset123456")
        self.assertTrue(all(self.repo.user_for_token(t) is None for t in tokens))
        token = self.repo.create_session(self.repo.get("ec1"))
        self.repo.set_active("ec1", False)
        self.assertIsNone(self.repo.user_for_token(token))


    def test_sliding_expiry_is_throttled(self):
        user = self.repo.create("ec1", "Ecom1234567", ECOMMERCE_SPECIALIST, must_change=False)
        now = datetime(2026, 11, 1, 9, 0, 0)
        token = self.repo.create_session(user, hours=12, now=now)
        _user, expires, seen = self.repo.session_for_token(token, now=now)
        self.assertEqual(expires, now + timedelta(hours=12))
        self.assertIsNone(self.repo.touch_session(token, hours=12, last_seen=seen, now=now + timedelta(minutes=2)))
        later = now + timedelta(hours=11)
        self.assertEqual(self.repo.touch_session(token, hours=12, last_seen=seen, now=later), later + timedelta(hours=12))
        self.assertIsNotNone(self.repo.user_for_token(token, now=now + timedelta(hours=20)))
        self.assertIsNone(self.repo.touch_session(token, hours=12, now=later + timedelta(hours=13)))

    def test_role_read_from_users_and_role_change_revokes(self):
        self.repo.create("admin", "Admin12345x", SUPER_USER, must_change=False)
        user = self.repo.create("ec1", "Ecom1234567", ECOMMERCE_SPECIALIST, must_change=False)
        token = self.repo.create_session(user)
        with self.repo.engine.begin() as conn:
            conn.exec_driver_sql("UPDATE sessions SET role = 'super_user'")
        self.assertEqual(self.repo.user_for_token(token).role, ECOMMERCE_SPECIALIST)
        self.repo.set_role("ec1", GUDANG)
        self.assertIsNone(self.repo.user_for_token(token))

    def test_change_password_revokes_all_sessions(self):
        user = self.repo.create("ec1", "Ecom1234567", ECOMMERCE_SPECIALIST, must_change=False)
        tokens = [self.repo.create_session(user) for _ in range(2)]
        self.repo.change_password("ec1", "Ecom1234567", "Baru1234567x")
        self.assertTrue(all(self.repo.user_for_token(t) is None for t in tokens))

    def test_old_sessions_table_gets_last_seen_column(self):
        with self.repo.engine.begin() as conn:
            conn.exec_driver_sql("DROP TABLE sessions")
            conn.exec_driver_sql(
                "CREATE TABLE sessions (token_hash VARCHAR(64) PRIMARY KEY, username VARCHAR(80) NOT NULL, "
                "role VARCHAR(40) NOT NULL, created_at VARCHAR(32) NOT NULL, expires_at VARCHAR(32) NOT NULL)"
            )
        repo = UserRepository(self.repo.engine)
        user = repo.create("ec1", "Ecom1234567", ECOMMERCE_SPECIALIST, must_change=False)
        self.assertIsNotNone(repo.session_for_token(repo.create_session(user))[2])


class DatabaseUrlTests(unittest.TestCase):
    def test_postgres_url_normalised_and_sqlite_default(self):
        self.assertEqual(database_url({"DATABASE_URL": "postgres://u:p@h/db"}), "postgresql+psycopg2://u:p@h/db")
        self.assertEqual(database_url({"DATABASE_URL": "postgresql+psycopg://u:p@h/db"}), "postgresql+psycopg2://u:p@h/db")
        self.assertEqual(database_url({"DATABASE_URL": " postgresql://u:p@h/db?sslmode=require "}), "postgresql+psycopg2://u:p@h/db?sslmode=require")
        self.assertTrue(database_url({}).startswith("sqlite:///"))


if __name__ == "__main__":
    unittest.main()
