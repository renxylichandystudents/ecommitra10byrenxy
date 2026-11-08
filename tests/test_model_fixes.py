import unittest

import numpy as np
import pandas as pd

from src.core.ensemble import DemandMatrix, forecast_moving_average
from src.core.optimization import monte_carlo_stock_scenarios
from src.core.preprocessing import winsorize_outliers
from src.core.segmentation import abc_xyz_segments


class ModelFixTests(unittest.TestCase):
    def test_ma28_uses_last_observed_days_after_long_stockout(self) -> None:
        values = np.array([[4.0] * 30 + [np.nan] * 35, [1.0] * 65])
        matrix = DemandMatrix(["A", "B"], pd.date_range("2026-08-01", periods=65), values)
        out = forecast_moving_average(matrix, 7)
        self.assertAlmostEqual(out[0], 28.0)
        self.assertAlmostEqual(out[1], 7.0)

    def test_winsorize_bounds_are_per_sku(self) -> None:
        frame = pd.DataFrame({
            "item_key": ["besar"] * 10 + ["kecil"] * 10,
            "qty": [100, 104, 95, 105, 98, 102, 101, 99, 103, 97] + [1, 1, 2, 1, 2, 1, 1, 2, 1, 40],
        })
        cleaned, stats = winsorize_outliers(frame, columns=("qty",))
        self.assertEqual(cleaned.loc[:9, "qty"].tolist(), frame.loc[:9, "qty"].astype(float).tolist())
        self.assertLess(float(cleaned.loc[19, "qty"]), 40)
        self.assertEqual(stats["winsorized"], 1)

    def test_xyz_counts_days_without_sales_as_zero(self) -> None:
        dates = pd.date_range("2026-10-01", periods=30)
        daily = pd.DataFrame({
            "item_key": ["rutin"] * 30 + ["jarang"] * 3,
            "date": list(dates) + [dates[0], dates[14], dates[29]],
            "qty": [5] * 30 + [5, 5, 5],
            "sales": [500] * 30 + [500, 500, 500],
        })
        seg = abc_xyz_segments(daily).set_index("item_key")
        self.assertEqual(seg.loc["rutin", "xyz"], "X")
        self.assertEqual(seg.loc["jarang", "xyz"], "Z")

    def test_monte_carlo_scales_sigma_with_sqrt_lead_time(self) -> None:
        mc = monte_carlo_stock_scenarios(demand_mean=10, demand_sigma=5, lead_time_mean=16, lead_time_sigma=0,
                                         current_stock=160, safety_stock=50, simulations=20_000).set_index("Skenario")
        self.assertAlmostEqual(mc.loc["Moderat", "Kebutuhan"], 160, delta=2)
        self.assertAlmostEqual(mc.loc["Pesimistis", "Kebutuhan"], 160 + 1.2816 * 20, delta=2)
        self.assertAlmostEqual(mc.loc["Moderat", "Risiko stockout"], 50, delta=2)


if __name__ == "__main__":
    unittest.main()
