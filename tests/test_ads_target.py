import unittest

from src.core import ads_strategy as A


def unit(key, *, cost, a, b, status="Berjalan", jenis="Produk tunggal", contribution=0.2, stock_room=float("inf")):
    return A.Unit(key=key, nama=key, jenis=jenis, status=status, mode="GMV Max", daily_cost=cost, daily_sales=a * __import__("math").log1p(cost / b) if cost else 0.0,
                  a=a, b=b, spread=0.2, contribution=contribution, stock_room=stock_room)


class AllocateTargetTest(unittest.TestCase):
    def setUp(self):
        # strong: marginal ROAS di 100 rb = 6 jt / 400 rb = 15; weak: 300 rb / 150 rb = 2.
        self.strong = unit("strong", cost=100_000, a=6_000_000, b=300_000)
        self.weak = unit("weak", cost=100_000, a=300_000, b=50_000, contribution=-0.05, stock_room=1_000)
        self.units = [self.strong, self.weak]

    def test_moves_budget_to_effective_ads_and_keeps_average_roas(self):
        plan = A.allocate_target(self.units, gap_daily=200_000, target_roas=8, budget_daily=200_000)
        self.assertLess(plan.cost["weak"], 100_000)
        self.assertGreater(plan.cost["strong"], 100_000)
        self.assertLessEqual(sum(plan.cost.values()), 200_000 + 1)
        self.assertGreaterEqual(A.plan_effect(self.units, plan, days=1)["roas_rencana"], 8)

    def test_high_target_roas_trims_only_until_average_is_met(self):
        before = sum(A.ad_sales(u, u.daily_cost) for u in self.units) / 200_000
        target = before + 3
        plan = A.allocate_target(self.units, gap_daily=0, target_roas=target, budget_daily=None)
        eff = A.plan_effect(self.units, plan, days=1)
        self.assertGreaterEqual(eff["roas_rencana"], target)
        self.assertGreater(plan.cost["strong"], 0)

    def test_lower_roas_never_gives_less_sales(self):
        prev = None
        for roas in (30, 20, 12, 8, 4, 2):
            extra = A.plan_effect(self.units, A.allocate_target(self.units, gap_daily=3_000_000, target_roas=roas, budget_daily=300_000), days=1)["omzet_tambahan"]
            if prev is not None:
                self.assertGreaterEqual(extra + 1, prev)
            prev = extra

    def test_budget_cap_respected(self):
        plan = A.allocate_target(self.units, gap_daily=10_000_000, target_roas=2, budget_daily=150_000)
        self.assertLessEqual(sum(plan.cost.values()), 150_000 + 1)

    def test_margin_and_stock_do_not_block_but_are_noted(self):
        plan = A.allocate_target(self.units, gap_daily=5_000_000, target_roas=1.5, budget_daily=None)
        acts = A.target_actions(self.units, plan, target_roas=1.5)
        weak = acts.loc[acts["key"] == "weak"].iloc[0]
        self.assertEqual(weak["Tindakan"], "Naikkan budget")
        self.assertIn("stok kurang", weak["Catatan"])
        self.assertIn("margin minus", weak["Catatan"])

    def test_paused_ad_counts_from_zero(self):
        paused = unit("paused", cost=100_000, a=6_000_000, b=300_000, status="Dijeda")
        plan = A.allocate_target([paused], gap_daily=500_000, target_roas=4, budget_daily=200_000)
        eff = A.plan_effect([paused], plan, days=10)
        self.assertGreater(plan.cost["paused"], 0)
        self.assertAlmostEqual(eff["omzet_tambahan"], paused.sales_at(plan.cost["paused"]) * 10, places=0)
        acts = A.target_actions([paused], plan, target_roas=4)
        self.assertEqual(acts.iloc[0]["Tindakan"], "Aktifkan kembali")
        self.assertEqual(acts.iloc[0]["Budget harian sekarang"], 0.0)

    def test_budget_needed_and_roas_for_budget_close_the_gap(self):
        gap = 300_000
        need, _extra = A.budget_needed(self.units, gap_daily=gap, target_roas=8)
        self.assertIsNotNone(need)
        plan = A.allocate_target(self.units, gap_daily=gap, target_roas=8, budget_daily=need)
        self.assertGreaterEqual(A.plan_effect(self.units, plan, days=1)["omzet_tambahan"], gap - 1)

        roas = A.roas_for_budget(self.units, gap_daily=gap, budget_daily=need)
        self.assertIsNotNone(roas)
        self.assertGreaterEqual(roas, 8)

    def test_unreachable_gap(self):
        need, extra = A.budget_needed(self.units, gap_daily=1e12, target_roas=8)
        self.assertIsNone(need)
        self.assertGreater(extra, 0)
        self.assertIsNone(A.roas_for_budget(self.units, gap_daily=1e12, budget_daily=1e9))


if __name__ == "__main__":
    unittest.main()
