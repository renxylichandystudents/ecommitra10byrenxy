import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from auth.permissions import (
    ECOMMERCE_SPECIALIST,
    GUDANG,
    IC,
    ROLES,
    SUPER_USER,
    allowed_sheets,
    can,
)
from auth.repository import AuthError, UserRepository
from auth.security import hash_password, password_problem, verify_password
from src.core.db import database_url, make_engine

SHEETS = ("Ringkasan", "Prediksi", "Data", "Folder data", "Rekomendasi", "Laporan", "Evaluasi model")


def _repo(folder: str) -> UserRepository:
    return UserRepository(make_engine(f"sqlite:///{Path(folder) / 'app.db'}"))


class SecurityTests(unittest.TestCase):
    def test_hash_and_verify(self):
        hashed = hash_password("rahasia123")
        self.assertNotEqual(hashed, "rahasia123")
        self.assertTrue(verify_password("rahasia123", hashed))
        self.assertFalse(verify_password("rahasia124", hashed))
        self.assertFalse(verify_password("rahasia123", "bukan-hash"))

    def test_password_minimum_length(self):
        self.assertIsNotNone(password_problem("1234567"))
        self.assertIsNone(password_problem("12345678"))


class PermissionTests(unittest.TestCase):
    def test_matrix(self):
        for role in ROLES:
            for perm in ("beranda", "riwayat_analisa", "jalankan_analisa", "ubah_data_latih", "ringkasan", "prediksi", "ubah_password"):
                self.assertTrue(can(role, perm), (role, perm))
        for perm in ("data", "folder_data", "rekomendasi", "laporan"):
            self.assertTrue(can(SUPER_USER, perm))
            self.assertTrue(can(ECOMMERCE_SPECIALIST, perm))
            self.assertFalse(can(IC, perm))
            self.assertFalse(can(GUDANG, perm))
        for perm in ("evaluasi_model", "kelola_user", "hapus_riwayat"):
            self.assertTrue(can(SUPER_USER, perm))
            for role in (ECOMMERCE_SPECIALIST, IC, GUDANG):
                self.assertFalse(can(role, perm))
        self.assertFalse(can(None, "beranda"))
        self.assertFalse(can(SUPER_USER, "tidak-ada"))

    def test_menu_from_permissions(self):
        self.assertEqual(allowed_sheets(GUDANG, SHEETS), ["Ringkasan", "Prediksi"])
        self.assertEqual(allowed_sheets(ECOMMERCE_SPECIALIST, SHEETS), list(SHEETS[:-1]))
        self.assertEqual(allowed_sheets(SUPER_USER, SHEETS), list(SHEETS))


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = _repo(self.tmp.name)

    def tearDown(self):
        self.repo.engine.dispose()
        self.tmp.cleanup()

    def test_initial_superuser_only_when_empty(self):
        self.assertIsNone(self.repo.ensure_initial_superuser("", ""))
        admin = self.repo.ensure_initial_superuser("Admin", "admin12345")
        self.assertEqual(admin.role, SUPER_USER)
        self.assertFalse(admin.must_change_password)
        self.assertIsNone(self.repo.ensure_initial_superuser("lain", "lain12345"))
        self.assertEqual(self.repo.count(), 1)

    def test_username_case_insensitive_unique(self):
        self.repo.create("Renxy", "password1", SUPER_USER)
        with self.assertRaises(AuthError):
            self.repo.create("renxy", "password2", IC)
        self.assertEqual(self.repo.get("RENXY").username, "Renxy")

    def test_last_super_user_cannot_be_disabled_or_demoted(self):
        self.repo.create("admin", "admin12345", SUPER_USER, must_change=False)
        with self.assertRaises(AuthError):
            self.repo.set_active("admin", False)
        with self.assertRaises(AuthError):
            self.repo.set_role("admin", IC)
        self.repo.create("admin2", "admin12345", SUPER_USER)
        self.repo.set_active("admin", False)
        self.assertFalse(self.repo.get("admin").is_active)
        with self.assertRaises(AuthError):
            self.repo.set_active("admin2", False)

    def test_must_change_password_flow(self):
        self.repo.create("gudang1", "sementara1", GUDANG, created_by="admin")
        user = self.repo.authenticate("gudang1", "sementara1")
        self.assertTrue(user.must_change_password)
        with self.assertRaises(AuthError):
            self.repo.change_password("gudang1", "salah1234", "baru12345")
        with self.assertRaises(AuthError):
            self.repo.change_password("gudang1", "sementara1", "pendek")
        self.repo.change_password("gudang1", "sementara1", "baru12345")
        self.assertFalse(self.repo.get("gudang1").must_change_password)
        self.repo.reset_password("gudang1", "reset12345")
        self.assertTrue(self.repo.get("gudang1").must_change_password)
        self.assertTrue(self.repo.authenticate("gudang1", "reset12345").must_change_password)

    def test_lockout_after_five_failures(self):
        self.repo.create("ic1", "benar1234", IC)
        now = datetime(2026, 11, 1, 9, 0, 0)
        for _ in range(5):
            with self.assertRaises(AuthError):
                self.repo.authenticate("ic1", "salah", now=now)
        with self.assertRaises(AuthError) as ctx:
            self.repo.authenticate("ic1", "benar1234", now=now + timedelta(minutes=4))
        self.assertIn("Coba lagi", str(ctx.exception))
        user = self.repo.authenticate("ic1", "benar1234", now=now + timedelta(minutes=5, seconds=1))
        self.assertEqual(user.username, "ic1")
        self.assertTrue(user.last_login_at.startswith("2026-11-01 09:05"))

    def test_inactive_user_cannot_login(self):
        self.repo.create("admin", "admin12345", SUPER_USER)
        self.repo.create("ec1", "ecom12345", ECOMMERCE_SPECIALIST)
        self.repo.set_active("ec1", False)
        with self.assertRaises(AuthError):
            self.repo.authenticate("ec1", "ecom12345")


class DatabaseUrlTests(unittest.TestCase):
    def test_postgres_url_normalised_and_sqlite_default(self):
        self.assertEqual(database_url({"DATABASE_URL": "postgres://u:p@h/db"}), "postgresql://u:p@h/db")
        self.assertTrue(database_url({}).startswith("sqlite:///"))


if __name__ == "__main__":
    unittest.main()
