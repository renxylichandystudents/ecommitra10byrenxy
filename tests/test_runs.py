import tempfile
import unittest
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from src.core.db import make_engine
from src.core.runs import RunRepository, data_hash


@dataclass
class _Outcome:
    weights: dict = field(default_factory=dict)
    evaluations: list = field(default_factory=list)


def _result() -> dict:
    orders = pd.DataFrame(
        {
            "order_time": pd.to_datetime(["2026-10-01 10:00", "2026-10-02 11:00"]),
            "item_key": ["A", "B"],
            "qty": [2.0, 3.0],
        }
    )
    combined = pd.DataFrame({"item_key": ["A", "B"], "pred_qty": [10.5, 4.0], "label": [["Naik"], []]})
    return {
        "orders": orders,
        "orders_all": orders,
        "combined": combined,
        "stock": pd.DataFrame({"item_key": ["A"], "stok": [7]}),
        "demand_outcome": _Outcome(weights={"ets": 0.6, "croston": 0.4}),
        "ensemble_weights": {"ets": 0.6, "croston": 0.4},
        "period": "bulan",
        "service": 95,
        "run_id": "abc",
    }


class RunRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo = RunRepository(make_engine(f"sqlite:///{root / 'app.db'}"), runs_root=root / "runs")

    def tearDown(self):
        self.repo.engine.dispose()
        self.tmp.cleanup()

    def _save(self, *, now=None, hash_="h1", ss=95, parameter="qty", exclude=False):
        return self.repo.save(
            _result(),
            run_by="renxy",
            periode="bulan",
            tgl_mulai=date(2026, 11, 1),
            tgl_akhir=date(2026, 11, 30),
            parameter=parameter,
            safety_stock=ss,
            exclude=exclude,
            data_hash=hash_,
            duration=12.345,
            now=now,
        )

    def test_save_and_load_roundtrip(self):
        record = self._save()
        self.assertEqual(record.status, "sukses")
        folder = Path(self.tmp.name) / "runs" / str(record.id)
        self.assertTrue((folder / "stock.parquet").exists())
        self.assertTrue((folder / "combined.pkl").exists())
        loaded_record, loaded = self.repo.load(record.id)
        self.assertEqual(loaded_record.run_by, "renxy")
        pd.testing.assert_frame_equal(loaded["orders"], _result()["orders"])
        self.assertIs(loaded["orders"], loaded["orders_all"])
        self.assertEqual(list(loaded["combined"]["label"]), [["Naik"], []])
        self.assertEqual(loaded["demand_outcome"].weights, {"ets": 0.6, "croston": 0.4})
        self.assertEqual(loaded["service"], 95)
        self.repo.save_extra(record.id, "katalog", pd.DataFrame({"sku": ["1"], "pred": [1.0]}))
        self.assertIn("katalog", self.repo.load(record.id)[1])
        cache = {"key|2026-10-31": pd.DataFrame({"item_key": ["A"], "stok": [3]})}
        self.repo.save_blob(record.id, "movement_asof", cache)
        restored = self.repo.load(record.id)[1]["movement_asof"]
        pd.testing.assert_frame_equal(restored["key|2026-10-31"], cache["key|2026-10-31"])

    def test_history_survives_new_repository(self):
        record = self._save()
        reopened = RunRepository(self.repo.engine, runs_root=self.repo.runs_root)
        self.assertEqual(reopened.last_success().id, record.id)
        self.assertEqual(len(reopened.list_runs()), 1)

    def test_duplicate_detection_same_day_same_parameters(self):
        today = datetime(2026, 11, 1, 9, 30)
        record = self._save(now=today)
        found = self.repo.find_duplicate(data_hash="h1", periode="bulan", parameter="qty", safety_stock=95, exclude=False, day=today.date())
        self.assertEqual(found.id, record.id)
        for kwargs in (
            {"data_hash": "h2", "safety_stock": 95, "parameter": "qty", "exclude": False},
            {"data_hash": "h1", "safety_stock": 90, "parameter": "qty", "exclude": False},
            {"data_hash": "h1", "safety_stock": 95, "parameter": "sales", "exclude": False},
            {"data_hash": "h1", "safety_stock": 95, "parameter": "qty", "exclude": True},
        ):
            self.assertIsNone(self.repo.find_duplicate(periode="bulan", day=today.date(), **kwargs), kwargs)
        self.assertIsNone(
            self.repo.find_duplicate(data_hash="h1", periode="bulan", parameter="qty", safety_stock=95, exclude=False, day=today.date() + timedelta(days=1))
        )

    def test_newest_first_delete_and_cleanup(self):
        old = self._save(now=datetime.now() - timedelta(days=91))
        new = self._save(now=datetime.now())
        self.assertEqual([r.id for r in self.repo.list_runs()], [new.id, old.id])
        self.assertEqual(self.repo.cleanup(), 1)
        self.assertFalse((self.repo.runs_root / str(old.id)).exists())
        self.repo.delete(new.id)
        self.assertEqual(self.repo.list_runs(), [])
        self.assertIsNone(self.repo.last_success())

    def test_missing_files_after_restart(self):
        older = self._save(now=datetime.now() - timedelta(hours=2))
        newer = self._save(now=datetime.now())
        import shutil

        shutil.rmtree(self.repo.runs_root / str(newer.id))
        self.assertFalse(self.repo.available(self.repo.get(newer.id)))
        self.assertEqual(self.repo.last_success().id, older.id)
        with self.assertRaises(FileNotFoundError):
            self.repo.load(newer.id)
        shutil.rmtree(self.repo.runs_root / str(older.id))
        self.assertIsNone(
            self.repo.find_duplicate(data_hash="h1", periode="bulan", parameter="qty", safety_stock=95, exclude=False)
        )

    def test_data_hash_uses_content(self):
        folder = Path(self.tmp.name)
        a, b = folder / "2026-10.pkl", folder / "2026-11.pkl"
        a.write_bytes(b"isi-a")
        b.write_bytes(b"isi-b")
        first = data_hash([a, b])
        a.write_bytes(b"isi-a")
        self.assertEqual(first, data_hash([b, a]))
        a.write_bytes(b"isi-lain")
        self.assertNotEqual(first, data_hash([a, b]))


if __name__ == "__main__":
    unittest.main()
