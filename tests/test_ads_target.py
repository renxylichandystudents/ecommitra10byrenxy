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


class ShopeeLimitsTest(unittest.TestCase):
    def test_budget_change_within_2x_or_paused(self):
        strong = unit("strong", cost=100_000, a=6_000_000, b=300_000)
        weak = unit("weak", cost=200_000, a=300_000, b=50_000)
        plan = A.allocate_target([strong, weak], gap_daily=50_000_000, target_roas=2, budget_daily=None)
        self.assertLessEqual(plan.cost["strong"], 200_000 + 1)
        w = plan.cost["weak"]
        self.assertTrue(w == 0 or 100_000 - 1 <= w <= 400_000 + 1, w)

    def test_shopee_target_roas_capped_at_30(self):
        star = unit("star", cost=50_000, a=40_000_000, b=500_000)
        plan = A.allocate_target([star], gap_daily=0, target_roas=8, budget_daily=None)
        acts = A.target_actions([star], plan, target_roas=8)
        self.assertLessEqual(acts.iloc[0]["Target ROAS Shopee"], 30)
        self.assertIn("maks. Shopee", acts.iloc[0]["Catatan"])


class ProductSelectionTest(unittest.TestCase):
    def test_classifies_group_members_and_unadvertised(self):
        import pandas as pd

        group = A.Unit(key="grup:Semen", nama="Semen", jenis="Grup", status="Berjalan", mode="GMV Max", daily_cost=60_000, daily_sales=900_000,
                       a=1, b=1, spread=0.2, members=["1", "2", "3", "4"])
        members = pd.DataFrame([
            {"unit": "grup:Semen", "periode": "2026-10", "product_code": "1", "nama": "Bintang", "biaya": 20_000, "omzet": 600_000, "terjual": 5},
            {"unit": "grup:Semen", "periode": "2026-10", "product_code": "2", "nama": "Kosong", "biaya": 15_000, "omzet": 0, "terjual": 0},
            {"unit": "grup:Semen", "periode": "2026-10", "product_code": "3", "nama": "Lemah", "biaya": 20_000, "omzet": 60_000, "terjual": 1},
            {"unit": "grup:Semen", "periode": "2026-10", "product_code": "4", "nama": "Biasa", "biaya": 5_000, "omzet": 240_000, "terjual": 2},
        ])
        products = pd.DataFrame([
            {"product_code": "1", "nama": "Bintang", "omzet_harian": 900_000, "stok_room": 1e6, "stok": 50},
            {"product_code": "9", "nama": "Laris belum iklan", "omzet_harian": 2_000_000, "stok_room": 1e6, "stok": 20},
            {"product_code": "8", "nama": "Habis", "omzet_harian": 1_500_000, "stok_room": 0, "stok": 0},
        ])
        sel = A.product_selection(members, [group], products, {}, target_roas=15).set_index("Kode produk")
        self.assertEqual(sel.loc["1", "Saran"], "Jadikan iklan tunggal")
        self.assertEqual(sel.loc["2", "Saran"], "Keluarkan dari grup")
        self.assertEqual(sel.loc["3", "Saran"], "Keluarkan dari grup")
        self.assertEqual(sel.loc["4", "Saran"], "Pertahankan di grup")
        self.assertEqual(sel.loc["9", "Saran"], "Buat iklan tunggal")
        self.assertNotIn("8", sel.index)


class RestockCapacityTest(unittest.TestCase):
    def test_room_to_max_per_sku(self):
        import pandas as pd
        from src.core.gudang import restock_capacity

        repl = pd.DataFrame({"max_stock": [50, 30, 0], "soh": [20, 40, 5]})
        room = restock_capacity(repl)
        self.assertEqual(room["unit"], 30)
        self.assertEqual(room["sku_ada_ruang"], 1)
        self.assertIsNone(restock_capacity(pd.DataFrame()))


if __name__ == "__main__":
    unittest.main()
