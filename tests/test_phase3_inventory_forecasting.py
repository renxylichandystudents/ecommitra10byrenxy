from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from src.core.forecasting import current_month_projection, sales_forecast_from_recent_price
from src.core.inventory import (
    current_month_forecast,
    inventory_decision,
    safety_stock_general,
    safety_stock_import,
    safety_stock_local,
    service_level_to_z,
    stock_zero_duration,
)
from src.core.optimization import eoq, monte_carlo_stock_scenarios, optimize_restock


class InventoryFormulaTests(unittest.TestCase):
    def test_current_month_forecast_never_below_actual(self) -> None:
        self.assertEqual(current_month_forecast(10_157, 0), 10_157)
        self.assertEqual(current_month_forecast(10_157, 500), 10_657)

    def test_safety_stock_formulas_and_rop(self) -> None:
        z = service_level_to_z(95)
        self.assertAlmostEqual(z, 1.64485, places=3)
        local = safety_stock_local(z=z, sigma_d=4, lead_time_days=7)
        general = safety_stock_general(z=z, d_avg=10, sigma_d=4, l_avg=7, sigma_l=1)
        imported = safety_stock_import(l_max=90, l_avg=60, d_avg=3)
        self.assertGreater(local, 0)
        self.assertGreater(general, local)
        self.assertEqual(imported, 90)

    def test_inventory_decision_outputs_need_status_and_days_cover(self) -> None:
        result = inventory_decision(
            forecast_qty=100,
            current_stock=80,
            sigma_d=5,
            service_level_pct=95,
            horizon_days=30,
            lead_time_days=7,
        )
        self.assertAlmostEqual(result.kebutuhan, result.forecast_qty + result.safety_stock)
        self.assertGreater(result.rop, result.safety_stock)
        self.assertIn(result.status_stok.split(" · ")[0], {"Aman", "Tipis", "Kurang", "Kosong", "di bawah SS"})
        self.assertGreater(result.hari_cukup, 0)

    def test_stock_zero_duration_from_snapshots(self) -> None:
        snapshots = pd.DataFrame(
            {
                "sku": ["A", "A", "A", "B"],
                "stock_dc_cikupa": [3, 0, 0, 5],
                "_submitted_at": ["2026-10-01", "2026-10-03", "2026-10-05", "2026-10-05"],
            }
        )
        duration = stock_zero_duration(snapshots, today=date(2026, 10, 8)).set_index("sku")
        self.assertEqual(int(duration.loc["A", "lama_kosong_hari"]), 5)
        self.assertNotIn("B", duration.index)


class ForecastingFormulaTests(unittest.TestCase):
    def test_current_month_projection_adds_actual_and_remaining(self) -> None:
        orders = pd.DataFrame(
            {
                "item_key": ["A", "A"],
                "order_time": ["2026-10-01", "2026-10-15"],
                "qty": [5, 7],
            }
        )
        future = pd.DataFrame(
            {
                "item_key": ["A", "A"],
                "date": ["2026-10-31", "2026-11-01"],
                "pred_qty": [3, 99],
            }
        )
        projection = current_month_projection(orders, future, today=date(2026, 10, 31)).set_index("item_key")
        self.assertEqual(float(projection.loc["A", "actual_month_to_yesterday"]), 12)
        self.assertEqual(float(projection.loc["A", "pred_bulan_ini"]), 15)

    def test_sales_forecast_uses_last_4_week_net_price(self) -> None:
        orders = pd.DataFrame(
            {
                "item_key": ["A", "A", "A"],
                "order_time": ["2026-10-01", "2026-10-20", "2026-09-01"],
                "qty": [2, 2, 10],
                "sales": [20_000, 30_000, 1_000],
            }
        )
        qty = pd.DataFrame({"item_key": ["A"], "pred_qty": [10]})
        sales = sales_forecast_from_recent_price(orders, qty, today=date(2026, 10, 31)).set_index("item_key")
        self.assertEqual(float(sales.loc["A", "pred_sales"]), 125_000)


class OptimizationTests(unittest.TestCase):
    def test_eoq_and_fallback_optimizer(self) -> None:
        self.assertGreater(eoq(annual_demand=1200, order_cost=50, holding_cost=2), 0)
        items = pd.DataFrame({"item_key": ["A", "B"], "kebutuhan": [100, 20], "current_stock": [70, 50]})
        result = optimize_restock(items, capacity=100, moq=5)
        self.assertIn("restock_qty", result.columns)
        self.assertEqual(float(result.loc[result["item_key"].eq("B"), "restock_qty"].iloc[0]), 0)

    def test_monte_carlo_outputs_three_scenarios(self) -> None:
        scenarios = monte_carlo_stock_scenarios(
            demand_mean=5,
            demand_sigma=1,
            lead_time_mean=7,
            lead_time_sigma=1,
            current_stock=20,
            safety_stock=5,
            simulations=100,
        )
        self.assertEqual(set(scenarios["Skenario"]), {"Pesimistis", "Moderat", "Optimistis"})


if __name__ == "__main__":
    unittest.main()

