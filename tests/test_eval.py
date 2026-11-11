import re
import unittest

import numpy as np
import pandas as pd

from src.core.ensemble import BIAS_KEY, MODEL_LEVEL, MODEL_MA, DemandMatrix, blend, ensemble_weights
from src.models.evaluate import HORIZONS, evaluate_all, fmt_num_id, month_cutoffs, record_frame


def _matrix(skus: int = 40, start: str = "2026-01-01", end: str = "2026-10-31") -> DemandMatrix:
    dates = pd.date_range(start, end, freq="D")
    rng = np.random.default_rng(3)
    base = rng.gamma(1.5, 2.0, size=(skus, 1))
    weekday = 1 + 0.3 * (dates.dayofweek.to_numpy() >= 5)
    values = rng.poisson(base * weekday).astype(float)
    values[:5, -20:-10] = np.nan
    return DemandMatrix([f"SKU{i}" for i in range(skus)], dates, values)


class EvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = _matrix()
        cls.records = evaluate_all(cls.matrix)

    def test_censored_test_windows_are_excluded(self):
        notes = " ".join(self.records["bulan"]["notes"])
        self.assertIn("5 pasangan SKU-lipatan tidak dinilai", notes)

    def test_six_month_cutoffs_may_to_oct(self):
        cuts = month_cutoffs(self.matrix.dates)
        self.assertEqual([str(self.matrix.dates[c].date()) for c in cuts], [f"2026-{m:02d}-01" for m in range(5, 11)])

    def test_one_record_per_horizon(self):
        self.assertEqual(set(self.records), set(HORIZONS))
        for name in ("hari", "minggu", "bulan"):
            self.assertTrue(self.records[name]["models"], name)
        self.assertEqual(len(self.records["kuartal"]["fold_dates"]), 4)

    def test_conclusion_numbers_equal_table(self):
        for name, record in self.records.items():
            if not record.get("best_model"):
                continue
            best = record["models"][record["best_model"]]
            frame = record_frame(record)
            row = frame.loc[frame["Model"] == best["label"]].iloc[0]
            self.assertEqual(row["MAPE (%)"], best["mape"])
            self.assertIn(f"MAPE per SKU {fmt_num_id(best['mape'])}%", record["kesimpulan"], name)
            self.assertIn(f"MAPE agregat toko {fmt_num_id(best['mape_agregat'])}%", record["kesimpulan"], name)
            self.assertIn(best["label"], record["kesimpulan"])
            numbers = re.findall(r"MAPE (-?[\d.]+,\d)%", record["kesimpulan"])
            allowed = {fmt_num_id(v) for v in frame[["MAPE (%)", "MAPE kelas A (%)", "MAPE kelas C (%)"]].to_numpy().ravel() if pd.notna(v)}
            for value in numbers:
                self.assertIn(value, allowed, name)

    def test_best_model_has_lowest_wape(self):
        record = self.records["bulan"]
        frame = record_frame(record)
        self.assertEqual(frame.iloc[0]["Model"], record["models"][record["best_model"]]["label"])

    def test_weights_only_models_beating_ma28(self):
        weights = ensemble_weights({MODEL_MA: 20.0, MODEL_LEVEL: 25.0, "Exponential Smoothing": 10.0})
        self.assertEqual(set(weights), {"Exponential Smoothing"})
        self.assertEqual(ensemble_weights({MODEL_MA: 20.0, MODEL_LEVEL: 25.0}), {MODEL_MA: 1.0})

    def test_bias_factor_applied_in_blend(self):
        out = blend({MODEL_MA: np.array([10.0])}, {MODEL_MA: 1.0, BIAS_KEY: 0.8})
        self.assertAlmostEqual(float(out[0]), 8.0)
        record = self.records["bulan"]
        self.assertIn(BIAS_KEY, record["weights"])
        self.assertLessEqual(abs(record["models"]["ensemble"]["bias"]), abs(record["bias_sebelum_koreksi"]) + 1e-6)

    def test_mape_ignores_zero_actuals(self):
        from src.core.evaluation import mape

        self.assertAlmostEqual(mape(np.array([0.0, 10.0]), np.array([5.0, 8.0])), 20.0)


if __name__ == "__main__":
    unittest.main()
