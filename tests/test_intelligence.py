"""Uji pembersihan data dan pemilihan model pada data sintetik."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.intelligence.benchmark import benchmark_cancel_risk, benchmark_daily_demand
from src.intelligence.preprocess import clean_frame, clean_series


class PreprocessTests(unittest.TestCase):
    def test_iqr_clips_spike_and_keeps_zero(self) -> None:
        values = np.array([1, 1, 1, 1, 2, 2, 2, 2, 0, 80], dtype=float)
        cleaned, clipped = clean_series(values, "iqr")
        self.assertGreater(clipped, 0)
        self.assertLess(cleaned[-1], 80)
        self.assertEqual(cleaned[-2], 0)

    def test_missing_numeric_uses_median(self) -> None:
        frame = pd.DataFrame({"qty": [1, np.nan, 3, 4, 5, 6, 7, 8, 100], "sales": [10] * 9})
        cleaned, report = clean_frame(frame, "zscore")
        self.assertEqual(report.missing_filled, 1)
        self.assertTrue(np.isfinite(cleaned["qty"]).all())
        self.assertEqual(len(cleaned), len(frame))

    def test_missing_columns_do_not_crash(self) -> None:
        frame = pd.DataFrame({"sku": ["A", "B"]})
        cleaned, report = clean_frame(frame, "isolation_forest")
        self.assertEqual(len(cleaned), 2)
        self.assertIn("tidak ada", report.note.lower())

    def test_empty_frame(self) -> None:
        cleaned, report = clean_frame(pd.DataFrame(), "iqr")
        self.assertTrue(cleaned.empty)
        self.assertEqual(report.rows_in, 0)


class BenchmarkTests(unittest.TestCase):
    def test_regression_selects_one_winner(self) -> None:
        days = pd.date_range("2026-01-01", periods=40, freq="D")
        qty = np.linspace(10, 18, 40) + np.array([0 if i % 7 else 2 for i in range(40)])
        history = pd.DataFrame({"period_start": days, "qty": qty})
        table, note = benchmark_daily_demand(history, "iqr")
        self.assertFalse(table.empty, note)
        self.assertEqual(int((table["Peran"] == "Pemenang uji").sum()), 1)
        for column in ("RMSE", "MAE", "R²", "Latensi (ms)", "Memori (KB)"):
            self.assertIn(column, table.columns)
        winner = table.loc[table["Peran"].eq("Pemenang uji")].iloc[0]
        self.assertEqual(winner["Status"], "Selesai")
        self.assertGreaterEqual(float(winner["RMSE"]), 0)

    def test_short_history_returns_note(self) -> None:
        history = pd.DataFrame(
            {"period_start": pd.date_range("2026-01-01", periods=4, freq="D"), "qty": [1, 2, 0, 1]}
        )
        table, note = benchmark_daily_demand(history, "iqr")
        self.assertTrue(table.empty)
        self.assertIn("16 hari", note)

    def test_cancel_risk_prefers_separable_signal(self) -> None:
        rng = np.random.default_rng(7)
        qty = np.concatenate([rng.normal(2, 0.3, 80), rng.normal(12, 0.4, 80)])
        sales = qty * 2_000_000
        status = ["Selesai"] * 80 + ["Batal"] * 80
        clock = pd.date_range("2026-01-01", periods=160, freq="h")
        orders = pd.DataFrame({"qty": qty, "sales": sales, "status": status, "order_time": clock})
        table, note = benchmark_cancel_risk(orders, "iqr")
        self.assertFalse(table.empty, note)
        self.assertEqual(int((table["Peran"] == "Pemenang uji").sum()), 1)
        winner = table.loc[table["Peran"].eq("Pemenang uji")].iloc[0]
        self.assertGreater(float(winner["F1"]), 0.8)
        self.assertIn("ROC-AUC", table.columns)

    def test_cancel_risk_without_status_does_not_crash(self) -> None:
        orders = pd.DataFrame({"qty": [1, 2], "sales": [10, 20]})
        table, note = benchmark_cancel_risk(orders, "zscore")
        self.assertTrue(table.empty)
        self.assertIn("status", note)


if __name__ == "__main__":
    unittest.main()
