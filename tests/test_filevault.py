import shutil
import tempfile
import unittest
from pathlib import Path

from src.core.db import make_engine
from src.core.filevault import FileVault


class FileVaultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.engine = make_engine(f"sqlite:///{base / 'vault.db'}")
        self.team = base / "server" / "shared"
        self.runs = base / "server" / "runs"
        (self.team / "library").mkdir(parents=True)
        (self.runs / "7").mkdir(parents=True)
        (self.team / "library" / "2026-10.pkl").write_bytes(b"oktober" * 1000)
        (self.team / "registry.json").write_text('{"sources": {}}', encoding="utf-8")
        (self.runs / "7" / "manifest.json").write_text("{}", encoding="utf-8")

    def tearDown(self):
        self.engine.dispose()
        self.tmp.cleanup()

    def _vault(self):
        return FileVault(self.engine, {"team": self.team, "runs": self.runs})

    def test_files_survive_wiped_disk(self):
        self.assertEqual(self._vault().push(), 3)
        shutil.rmtree(self.team.parent)
        fresh = self._vault()
        self.assertEqual(fresh.restore(), 3)
        self.assertEqual((self.team / "library" / "2026-10.pkl").read_bytes(), b"oktober" * 1000)
        self.assertTrue((self.runs / "7" / "manifest.json").exists())
        self.assertEqual(fresh.push(), 0)

    def test_changes_and_deletes_follow_disk(self):
        vault = self._vault()
        vault.push()
        self.assertEqual(vault.push(), 0)
        (self.team / "registry.json").write_text('{"sources": {"stock": {}}}', encoding="utf-8")
        shutil.rmtree(self.runs / "7")
        self.assertEqual(vault.push(), 2)
        self.assertEqual(vault.summary()[0], 2)
        shutil.rmtree(self.team.parent)
        self._vault().restore()
        self.assertIn("stock", (self.team / "registry.json").read_text(encoding="utf-8"))
        self.assertFalse((self.runs / "7").exists())

    def test_repetitive_files_are_stored_compressed(self):
        vault = self._vault()
        vault.push()
        files, size, stored = vault.summary()
        self.assertEqual(files, 3)
        self.assertLess(stored, size / 5)

    def test_uncompressed_rows_from_old_vault_still_restore(self):
        from sqlalchemy import insert

        from src.core.filevault import VAULT, _sha1

        FileVault(self.engine, {})
        with self.engine.begin() as conn:
            conn.execute(insert(VAULT).values(path="team/lama.csv", size=3, sha1=_sha1(b"a,b"), updated_at="-", data=b"a,b"))
        self._vault().restore()
        self.assertEqual((self.team / "lama.csv").read_bytes(), b"a,b")


class MigrateTest(unittest.TestCase):
    def test_copies_tables_and_uploads_files_with_server_keys(self):
        from sqlalchemy import text

        from auth.repository import UserRepository
        from src.core import migrate
        from src.core.runs import RunRepository

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = make_engine(f"sqlite:///{base / 'laptop.db'}")
            target = make_engine(f"sqlite:///{base / 'cloud.db'}")
            UserRepository(source).ensure_initial_superuser("renxy", "Rahasia-123x")
            RunRepository(source, runs_root=base / "runs")
            with source.begin() as conn:
                conn.execute(text("INSERT INTO analysis_runs (id, run_at, run_by, periode, parameter, safety_stock, exclude_batal_retur, "
                                  "data_hash, status) VALUES (3, '2026-11-08', 'renxy', 'bulan', 'qty', 95, 1, 'x', 'ok')"))
            for run in ("3", "9"):
                (base / "runs" / run).mkdir(parents=True)
                (base / "runs" / run / "manifest.json").write_text("{}", encoding="utf-8")
            (base / "library").mkdir()
            (base / "library" / "2026-10.pkl").write_bytes(b"x" * 500)

            migrate.prepare_schema(target, base / "cloud_runs")
            copied = migrate.copy_tables(source, target, log=lambda _: None)
            self.assertEqual(copied["users"], 1)
            self.assertEqual(copied["analysis_runs"], 1)
            files = migrate.vault_files({"team/library": base / "library", "runs": base / "runs"}, {3})
            self.assertEqual(sorted(files), ["runs/3/manifest.json", "team/library/2026-10.pkl"])
            migrate.upload_files(target, files, log=lambda _: None)
            server_team = base / "server" / "shared"
            FileVault(target, {"team": server_team, "runs": base / "server" / "runs"}).restore()
            self.assertEqual((server_team / "library" / "2026-10.pkl").read_bytes(), b"x" * 500)
            self.assertTrue(UserRepository(target).authenticate("renxy", "Rahasia-123x"))
            source.dispose()
            target.dispose()


if __name__ == "__main__":
    unittest.main()
