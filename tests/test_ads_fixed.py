import math
import unittest
from datetime import date

import pandas as pd

from src.core import ads_fixed as F
from src.core import ads_strategy as A


def unit(key, *, cost, a, b, demand=float("inf"), stock_room=float("inf")):
    return A.Unit(key=key, nama=key, jenis="Produk tunggal", status="Berjalan", mode="GMV Max", daily_cost=cost,
                  daily_sales=a * math.log1p(cost / b), a=a, b=b, spread=0.2, stock_room=stock_room, demand=demand)


class StockCapTest(unittest.TestCase):
    def test_uplift_limited_by_stock_room(self):
        u = unit("x", cost=100_000, a=6_000_000, b=300_000, demand=2_000_000, stock_room=200_000)
        capped = F.stock_capped([u])[0]
        self.assertAlmostEqual(A.uplift_cap(capped), 200_000)
        self.assertTrue(F.stock_limited(capped))
        self.assertLessEqual(A.ad_sales(capped, 10_000_000) - u.daily_sales, 200_000 + 1)

    def test_units_without_stock_data_untouched(self):
        u = unit("x", cost=100_000, a=6_000_000, b=300_000, demand=2_000_000)
        self.assertIs(F.stock_capped([u])[0], u)
        self.assertFalse(F.stock_limited(u))

    def test_plan_with_stock_cap_spends_less_on_sold_out_ad(self):
        full = unit("full", cost=100_000, a=6_000_000, b=300_000, demand=10_000_000, stock_room=0.0)
        free = unit("free", cost=100_000, a=5_000_000, b=300_000, demand=10_000_000)
        units = F.stock_capped([full, free])
        plan = A.allocate_target(units, gap_daily=5_000_000, target_roas=5, budget_daily=300_000)
        self.assertGreater(plan.cost["free"], plan.cost["full"])


class DayPlanTest(unittest.TestCase):
    def setUp(self):
        self.units = [unit("a", cost=200_000, a=4_000_000, b=150_000, demand=50_000_000)]
        self.plan = A.Plan("x", {"a": 200_000}, {"a": 5})
        self.blocks = [(date(2026, 11, 9), date(2026, 11, 15))]
        self.shape = lambda d: 2.0 if d.day == 11 else 0.8

    def test_budget_moves_to_busy_day_and_total_kept(self):
        calendar, summary = F.day_plan(self.units, [(7, self.plan)], self.blocks, self.shape)
        self.assertEqual(len(calendar), 7)
        self.assertAlmostEqual(calendar["Budget/hari"].sum(), 200_000 * 7, delta=1)
        busy = calendar.loc[calendar["Tanggal"] == date(2026, 11, 11), "Pengali budget"].iloc[0]
        self.assertGreater(busy, 1.0)
        self.assertTrue(calendar["Pengali budget"].between(F.DAY_LO - 1e-9, F.DAY_HI + 1e-9).all())
        self.assertGreater(summary["tambahan"], 0)

    def test_flat_pattern_keeps_flat_budget(self):
        calendar, summary = F.day_plan(self.units, [(7, self.plan)], self.blocks, lambda d: 1.0)
        self.assertAlmostEqual(calendar["Budget/hari"].sum(), 200_000 * 7, delta=1)
        self.assertAlmostEqual(summary["tambahan"], 0, delta=1)


class PushCandidatesTest(unittest.TestCase):
    def test_respects_stock_room_and_skips_negative_margin(self):
        products = pd.DataFrame({
            "product_code": ["1", "2", "3"], "nama": ["Semen", "Cat", "Keramik"], "omzet_harian": [1_000_000, 800_000, 500_000],
            "stok": [10, 10, 10], "stok_room": [100_000, 1_000_000, 1_000_000],
        })
        margin = {"1": 0.1, "2": -0.05, "3": 0.2}
        out = F.push_candidates(products, margin, need_daily=300_000, lift=0.5)
        self.assertNotIn("2", set(out["Kode produk"]))
        semen = out.loc[out["Kode produk"] == "1", "Tambahan dikejar/hari"].iloc[0]
        self.assertLessEqual(semen, 100_000 + 1)
        self.assertAlmostEqual(out["Tambahan dikejar/hari"].sum(), 300_000, delta=1)
        # Keramik: min(ruang stok 1 jt, 50% × 500 rb) = 250 rb; Semen: ruang stok 100 rb
        self.assertAlmostEqual(F.push_capacity(products, margin, lift=0.5), 350_000)
        self.assertAlmostEqual(F.push_capacity(products, margin, lift=0.5, exclude={"3"}), 100_000)


if __name__ == "__main__":
    unittest.main()
