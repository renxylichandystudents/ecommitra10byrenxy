import unittest
from datetime import date

import pandas as pd

from src.core import targets as T
from src.core.business import business_targets


class BusinessTargetTest(unittest.TestCase):
    def test_targets_priority(self):
        params = {"margin": {"hpp_pct_harga": 55, "margin_min_pct": 30}, "target": {"sales_bulanan_rp": 5_500_000_000}}
        # Satu angka target untuk semua bulan tidak lagi berlaku untuk semua bulan.
        goals = business_targets(params, None)
        self.assertEqual(goals.target_sales, 0)
        self.assertEqual(goals.target_source, "belum diisi")
        self.assertEqual(goals.margin_min_pct, 0)
        saved = business_targets(params, {"target_sales_bersih": 6_000_000_000, "margin_min_pct": 25})
        self.assertEqual(saved.target_sales, 6_000_000_000)
        self.assertEqual(saved.margin_min_pct, 25)
        self.assertEqual(saved.target_source, "target bulanan")

    def test_parse_target_file_formats(self):
        raw = pd.DataFrame({
            "Bulan": ["2026-11", "Des 2026", pd.Timestamp("2027-01-01"), "02/2027"],
            "Target (Rp)": ["Rp 5.500.000.000", 6_000_000_000, "4,5 M", "3.000.000.000"],
        })
        out = T.parse_target_file(raw)
        self.assertEqual(out["periode"].tolist(), ["2026-11", "2026-12", "2027-01", "2027-02"])
        self.assertEqual(out["target"].tolist(), [5.5e9, 6e9, 4.5e9, 3e9])

    def test_parse_target_file_rejects_bad_rows(self):
        with self.assertRaises(ValueError):
            T.parse_target_file(pd.DataFrame({"Bulan": ["bukan bulan"], "Target": [1]}))
        with self.assertRaises(ValueError):
            T.parse_target_file(pd.DataFrame({"Periode": ["2026-11"]}))

    def test_range_target_prorata_and_missing(self):
        targets = {"2026-11": 3_000_000_000, "2026-10": 3_100_000_000}
        value, missing = T.range_target(targets, date(2026, 11, 1), date(2026, 11, 8))
        self.assertEqual(missing, [])
        self.assertAlmostEqual(value, 3e9 * 8 / 30)
        value, _ = T.range_target(targets, date(2026, 10, 10), date(2026, 11, 8))
        self.assertAlmostEqual(value, 3.1e9 * 22 / 31 + 3e9 * 8 / 30)
        value, missing = T.range_target(targets, date(2026, 12, 1), date(2026, 12, 5))
        self.assertIsNone(value)
        self.assertEqual(missing, ["2026-12"])

    def test_achievement_single_month(self):
        result, _ = T.achievement(1_000_000_000, date(2026, 11, 1), date(2026, 11, 8), {"2026-11": 3_000_000_000})
        self.assertEqual(result.single_month, "2026-11")
        self.assertFalse(result.full_months)
        self.assertAlmostEqual(result.month_pct, 100 / 3)
        self.assertAlmostEqual(result.pct, 1e9 / (3e9 * 8 / 30) * 100)


if __name__ == "__main__":
    unittest.main()
