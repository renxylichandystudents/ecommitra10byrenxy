import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import insert, text

from src.core import storage_guard
from src.core.db import make_engine
from src.core.feature_store import FeatureStore, audit_log, prediction_snapshot
from src.core.filevault import VAULT, FileVault
from src.core.runs import RunRepository


class StorageGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.engine = make_engine(f"sqlite:///{base / 'app.db'}")
        self.repo = RunRepository(self.engine, runs_root=base / "runs")
        FeatureStore(self.engine)
        FileVault(self.engine, {})
        with self.engine.begin() as conn:
            for run_id in range(1, 9):
                conn.execute(text("INSERT INTO analysis_runs (id, run_at, run_by, periode, parameter, safety_stock, exclude_batal_retur, "
                                  "data_hash, status) VALUES (:i, :t, 'renxy', 'bulan', 'qty', 95, 1, 'x', 'sukses')"),
                             {"i": run_id, "t": f"2026-11-0{run_id} 08:00:00"})
                (base / "runs" / str(run_id)).mkdir(parents=True)
                conn.execute(insert(VAULT).values(path=f"runs/{run_id}/state.pkl", size=1, sha1="x", updated_at="-", data=b"x"))
                conn.execute(insert(prediction_snapshot).values(run_id=run_id, created_at=datetime(2026, 11, run_id), target_date=date(2026, 11, 10),
                                                                sku="A", varian="", pred_qty=1.0, pred_sales=1.0))
            conn.execute(insert(VAULT).values(path="runs/99/state.pkl", size=1, sha1="x", updated_at="-", data=b"x"))
            conn.execute(insert(VAULT).values(path="team/library/2026-10.pkl", size=1, sha1="x", updated_at="-", data=b"x"))
            conn.execute(insert(audit_log), [{"at": datetime(2026, 1, 1), "username": "a", "action": "lama", "detail_json": "{}"},
                                             {"at": datetime(2026, 11, 8), "username": "a", "action": "baru", "detail_json": "{}"}])
        self.base = base

    def tearDown(self):
        self.engine.dispose()
        self.tmp.cleanup()

    def test_keeps_newest_runs_and_cleans_related_rows(self):
        params = {"penyimpanan": {"maks_riwayat_analisa": 3, "maks_snapshot_prediksi": 5, "hari_log_aktivitas": 30}}
        report = storage_guard.enforce(self.engine, self.repo, params, now=datetime(2026, 11, 9))
        self.assertEqual(sorted(report.runs_deleted), [1, 2, 3, 4, 5])
        with self.engine.connect() as conn:
            self.assertEqual([r[0] for r in conn.execute(text("SELECT id FROM analysis_runs ORDER BY id"))], [6, 7, 8])
            vault = sorted(r[0] for r in conn.execute(text("SELECT path FROM file_vault")))
            snaps = sorted(r[0] for r in conn.execute(text("SELECT DISTINCT run_id FROM prediction_snapshot")))
            actions = [r[0] for r in conn.execute(text("SELECT action FROM audit_log"))]
        self.assertEqual(vault, ["runs/6/state.pkl", "runs/7/state.pkl", "runs/8/state.pkl", "team/library/2026-10.pkl"])
        self.assertEqual(snaps, [4, 5, 6, 7, 8])
        self.assertEqual(actions, ["baru"])
        self.assertFalse((self.base / "runs" / "1").exists())
        self.assertTrue((self.base / "runs" / "8").exists())

    def test_emergency_limit_never_goes_below_minimum(self):
        params = {"penyimpanan": {"maks_riwayat_analisa": 12, "batas_darurat_mb": 0, "minimal_tersisa": 2}}
        storage_guard.enforce(self.engine, self.repo, params, now=datetime(2026, 11, 9))
        with self.engine.connect() as conn:
            self.assertEqual([r[0] for r in conn.execute(text("SELECT id FROM analysis_runs ORDER BY id"))], [7, 8])

    def test_settings_fall_back_to_defaults(self):
        cfg = storage_guard.settings({"penyimpanan": {"maks_riwayat_analisa": "x"}})
        self.assertEqual(cfg["maks_riwayat_analisa"], 12)
        self.assertEqual(cfg["kuota_mb"], 500)
        self.assertGreater(timedelta(days=cfg["hari_log_aktivitas"]), timedelta(days=90))


if __name__ == "__main__":
    unittest.main()
