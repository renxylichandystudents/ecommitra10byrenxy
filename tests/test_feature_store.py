import hashlib
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import inspect

from src.core.db import make_engine
from src.core.feature_store import TABLES, FeatureStore

LIBRARY = Path(__file__).resolve().parents[1] / "uploads" / "library"


def _hash_dir(folder: Path) -> dict[str, tuple[int, str]]:
    return {
        path.name: (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(folder.glob("*"))
        if path.is_file()
    }


class FeatureStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.url = f"sqlite:///{Path(self.tmp.name) / 'app.db'}"
        self.store = FeatureStore(make_engine(self.url))

    def tearDown(self):
        self.store.engine.dispose()
        self.tmp.cleanup()

    def test_all_tables_created(self):
        names = set(inspect(self.store.engine).get_table_names())
        for table in (
            "prediction_snapshot", "report_meta", "excluded_sku", "cost_component", "carton_dimension",
            "warehouse_rack", "import_po", "import_note", "brand_portal", "sales_target", "audit_log",
        ):
            self.assertIn(table, names)
        self.assertEqual(set(TABLES), {*names} & set(TABLES))

    def test_data_survives_restart(self):
        self.store.insert("excluded_sku", [{"sku": "40030033", "nama": "Extra Packing Kayu Tambahan", "jenis": "SKU jasa", "added_by": "renxy", "added_at": "02/11/2026"}], username="renxy")
        self.store.engine.dispose()
        reopened = FeatureStore(make_engine(self.url))
        frame = reopened.read("excluded_sku")
        self.assertEqual(frame["sku"].tolist(), ["40030033"])
        self.assertEqual(pd.Timestamp(frame.iloc[0]["added_at"]).date(), date(2026, 11, 2))
        reopened.engine.dispose()

    def test_replace_is_upsert_and_writes_audit(self):
        row = {"sku": "200019936", "varian": "", "panjang_cm": 60, "lebar_cm": 40, "tinggi_cm": 80, "isi_per_karton": 1}
        self.store.replace("carton_dimension", [row], keys=["sku", "varian"], username="dc1")
        self.store.replace("carton_dimension", [{**row, "tinggi_cm": 85}], keys=["sku", "varian"], username="dc1")
        frame = self.store.read("carton_dimension")
        self.assertEqual(len(frame), 1)
        self.assertEqual(float(frame.iloc[0]["tinggi_cm"]), 85.0)
        log = self.store.read("audit_log")
        self.assertEqual(len(log), 2)
        self.assertEqual(set(log["username"]), {"dc1"})

    def test_remove_requires_filter(self):
        with self.assertRaises(ValueError):
            self.store.remove("excluded_sku", {})

    def test_prediction_snapshot_replaced_per_run(self):
        frame = pd.DataFrame({"target_date": ["2026-11-02", "2026-11-03"], "sku": ["200019936"] * 2, "varian": [None, None], "pred_qty": [30.0, 31.0], "pred_sales": [3.6e7, 3.7e7]})
        self.store.save_prediction_snapshot(7, frame)
        self.store.save_prediction_snapshot(7, frame.head(1))
        saved = self.store.read("prediction_snapshot", {"run_id": 7})
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved.iloc[0]["target_date"], date(2026, 11, 2))

    def test_report_period_roundtrip(self):
        self.assertIsNone(self.store.report_period(3))
        self.store.set_report_period(3, "2026-10")
        self.store.set_report_period(3, "2026-09")
        self.assertEqual(self.store.report_period(3), "2026-09")

    @unittest.skipUnless(LIBRARY.exists(), "data latih lokal tidak tersedia")
    def test_training_data_untouched(self):
        before = _hash_dir(LIBRARY)
        self.store.insert("brand_portal", [{"periode": "2026-10", "kategori": "Sealant", "brand": "X", "peringkat": 1, "pangsa": 12.5}])
        self.store.insert("import_po", [{"no_po": "PO1", "sku": "200019936", "qty": 100, "eta_rencana": "2026-11-20", "status": "Di kapal"}])
        self.store.replace("sales_target", [{"periode": "2026-11", "target_sales_bersih": 3e9}], keys=["periode"])
        self.assertEqual(before, _hash_dir(LIBRARY))


if __name__ == "__main__":
    unittest.main()
