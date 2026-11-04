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


if __name__ == "__main__":
    unittest.main()
