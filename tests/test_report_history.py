import unittest
from datetime import date

import numpy as np
import pandas as pd

from src.activity import ledger_from_raw
from src.core import model_history as H
from src.core import report_data as R
from src.core.metrics import order_metrics
from tests.test_metrics import RAW


class FakeFeatures:
    def __init__(self):
        self.kv = {}

    def get_json(self, key, default=None):
        value = self.kv.get(key)
        return default if value is None else value

    def set_json(self, key, value, username=""):
        self.kv[key] = value


class ReportDataTest(unittest.TestCase):
    def test_json_roundtrip_keeps_frames_and_numbers(self):
        snap = {"meta": {"mulai": date(2026, 10, 1)}, "kpi": {"x": np.float64(1.5), "nan": float("nan")},
                "daily": pd.DataFrame({"Tanggal": pd.to_datetime(["2026-10-01"]), "Sales": [10.0]})}
        back = R.from_json(R.to_json(snap))
        self.assertEqual(back["meta"]["mulai"], "2026-10-01")
        self.assertEqual(back["kpi"]["x"], 1.5)
        self.assertIsNone(back["kpi"]["nan"])
        self.assertEqual(list(back["daily"].columns), ["Tanggal", "Sales"])
        self.assertEqual(back["daily"].iloc[0]["Sales"], 10.0)

    def test_store_save_open_delete(self):
        store = R.ReportStore(FakeFeatures())
        snap = {"meta": {"mulai": "2026-10-01", "selesai": "2026-10-31"}, "top": pd.DataFrame({"SKU": ["1"]})}
        first = store.save(snap, name="Oktober", username="renxy")
        second = store.save(snap, name="Oktober 2", username="renxy")
        self.assertEqual([r["id"] for r in store.all()], [second, first])
        opened = store.get(first)
        self.assertEqual(opened["meta"]["nama"], "Oktober")
        self.assertEqual(opened["top"].iloc[0]["SKU"], "1")
        store.delete(first, username="renxy")
        self.assertEqual([r["id"] for r in store.all()], [second])
        self.assertIsNone(store.get(first))

    def test_daily_orders_matches_order_metrics(self):
        ledger = ledger_from_raw(RAW)
        daily = R.daily_orders(ledger, date(2026, 10, 1), date(2026, 10, 31))
        facts = order_metrics(ledger, "2026-10-01", "2026-10-31")
        self.assertEqual(len(daily), 31)
        self.assertAlmostEqual(float(daily["Sales bersih"].sum()), float(facts["sales_bersih"]))
        self.assertEqual(int(daily["Pesanan"].sum()), int(facts["pesanan_semua"]))
        self.assertEqual(int(daily["Pesanan batal"].sum()), int(facts["pesanan_batal"]))


class ModelHistoryTest(unittest.TestCase):
    def test_skill_score(self):
        self.assertAlmostEqual(H.skill_score(30, 40), 0.25)
        self.assertTrue(np.isnan(H.skill_score(30, 0)))

    def test_demand_profile_patterns(self):
        days = pd.date_range("2026-01-01", periods=60)
        smooth = pd.DataFrame({"item_key": "a", "item_label": "A", "period_start": days, "qty": 5})
        rare = pd.DataFrame({"item_key": "b", "item_label": "B", "period_start": days[::10], "qty": [1, 20, 1, 30, 2, 40]})
        profile = H.demand_profile(pd.concat([smooth, rare]))
        pattern = profile.set_index("item_key")["Pola"]
        self.assertEqual(pattern["a"], H.PATTERNS[0])
        self.assertEqual(pattern["b"], H.PATTERNS[3])

    def test_method_checks_flags(self):
        record = {"best_model": "seg", "fold_dates": ["a", "b", "c"], "simulasi_ss": {"tingkat_layanan_pct": 95},
                  "models": {"seg": {"label": H.SEGMENT_LABEL, "wape": 30, "mape_agregat": 10, "bias": -4, "top50_tepat": 40},
                             "ma": {"label": H.BASELINE_LABEL, "wape": 40}}}
        checks = H.method_checks(record).set_index("Uji")["Status"]
        self.assertEqual(checks["Mengalahkan pembanding MA28"], "✅ Sesuai")
        self.assertEqual(checks["Akurasi total toko"], "✅ Sesuai")
        self.assertEqual(checks["Lebih baik dari metode lama (Level terkini)"], "–")

    def test_forward_test_only_after_run(self):
        snap = pd.DataFrame({"run_id": [1, 1, 1], "target_date": ["2026-11-01", "2026-11-02", "2026-11-03"], "pred_qty": [10, 10, 10]})
        actual = pd.Series([8.0, 12.0], index=pd.to_datetime(["2026-11-02", "2026-11-03"]))
        runs = pd.DataFrame({"id": [1], "run_at": ["2026-11-01 20:00"]})
        out = H.forward_test(snap, actual, runs)
        self.assertEqual(list(out["Tanggal"].dt.day), [2, 3])
        self.assertAlmostEqual(out["Galat (%)"].iloc[0], 25.0)


if __name__ == "__main__":
    unittest.main()
