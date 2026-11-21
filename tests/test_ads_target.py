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
        plan = A.allocate_target(self.units, gap_daily=5_000_000, target_roas=1.5, budget_daily=None, min_marginal=0)
        acts = A.target_actions(self.units, plan, target_roas=1.5)
        weak = acts.loc[acts["key"] == "weak"].iloc[0]
        self.assertEqual(weak["Tindakan"], "Naikkan budget")
        self.assertIn("stok kurang", weak["Catatan"])
        self.assertIn("margin minus", weak["Catatan"])

    def test_paused_ad_gets_no_budget_and_no_reactivate_action(self):
        """Iklan dijeda: jangan alokasi budget / 'Aktifkan kembali' — bukan langkah setel ulang Seller Center."""
        paused = unit("paused", cost=100_000, a=6_000_000, b=300_000, status="Dijeda")
        active = unit("active", cost=100_000, a=6_000_000, b=300_000, status="Berjalan")
        plan = A.allocate_target([paused, active], gap_daily=500_000, target_roas=4, budget_daily=200_000)
        self.assertEqual(plan.cost["paused"], 0.0)
        self.assertGreater(plan.cost["active"], 0)
        acts = A.target_actions([paused, active], plan, target_roas=4)
        self.assertFalse((acts["key"] == "paused").any())
        self.assertNotIn("Aktifkan kembali", set(acts["Tindakan"].astype(str)))
        self.assertTrue((acts["key"] == "active").any())

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
        sel = A.product_selection(members, [group], products, {}, target_roas=15, focus=False).set_index("Kode produk")
        self.assertEqual(sel.loc["1", "Saran"], "Jadikan iklan tunggal")
        self.assertEqual(sel.loc["2", "Saran"], "Keluarkan dari grup")
        self.assertEqual(sel.loc["3", "Saran"], "Keluarkan dari grup")
        self.assertEqual(sel.loc["4", "Saran"], "Pertahankan di grup")
        self.assertEqual(sel.loc["9", "Saran"], "Buat iklan tunggal")
        self.assertNotIn("8", sel.index)


class SmallSalesFocusTest(unittest.TestCase):
    def test_small_products_stop_unless_fast_moving(self):
        import pandas as pd

        group = A.Unit(key="grup:G", nama="G", jenis="Grup", status="Berjalan", mode="GMV Max", daily_cost=60_000, daily_sales=900_000,
                       a=1, b=1, spread=0.2, members=["1", "2", "3"])
        members = pd.DataFrame([
            {"unit": "grup:G", "periode": "2026-10", "product_code": "1", "nama": "Besar", "biaya": 10_000, "omzet": 150_000, "terjual": 5},
            {"unit": "grup:G", "periode": "2026-10", "product_code": "2", "nama": "Kecil", "biaya": 3_000, "omzet": 30_000, "terjual": 1},
            {"unit": "grup:G", "periode": "2026-10", "product_code": "3", "nama": "Murah laris", "biaya": 3_000, "omzet": 30_000, "terjual": 9},
        ])
        products = pd.DataFrame([
            {"product_code": "1", "nama": "Besar", "omzet_harian": 9_000_000, "qty_harian": 3, "stok_room": 1e6, "stok": 50},
            {"product_code": "2", "nama": "Kecil", "omzet_harian": 20_000, "qty_harian": 0.1, "stok_room": 1e6, "stok": 50},
            {"product_code": "3", "nama": "Murah laris", "omzet_harian": 40_000, "qty_harian": 8, "stok_room": 1e6, "stok": 50},
            {"product_code": "5", "nama": "Kecil belum iklan", "omzet_harian": 30_000, "qty_harian": 0.2, "stok_room": 1e6, "stok": 50},
        ])
        sales_floor, qty_floor = A.potential_floors(products)
        self.assertEqual(sales_floor, 9_000_000)  # 1 produk sudah membentuk ≥ 95% prediksi sales toko
        self.assertGreaterEqual(qty_floor, 1.0)
        sel = A.product_selection(members, [group], products, {}, target_roas=5).set_index("Kode produk")
        self.assertEqual(sel.loc["2", "Saran"], A.SMALL_SALES)
        self.assertNotEqual(sel.loc["3", "Saran"], A.SMALL_SALES)  # sales kecil tapi qty laku banyak
        self.assertNotEqual(sel.loc["1", "Saran"], A.SMALL_SALES)
        self.assertNotIn("5", sel.index)  # tidak diusulkan iklan baru


class UnifiedPlanTest(unittest.TestCase):
    def setUp(self):
        import pandas as pd

        self.group = A.Unit(key="grup:Kloset", nama="Kloset", jenis="Grup", status="Berjalan", mode="GMV Max", daily_cost=60_000, daily_sales=900_000,
                            a=1_500_000, b=60_000, spread=0.2, members=["1", "2", "3", "4"])
        self.old = A.Unit(key="grup:Lama", nama="Lama", jenis="Grup", status="Berakhir", mode="GMV Max", daily_cost=40_000, daily_sales=300_000,
                          a=600_000, b=40_000, spread=0.2, members=["1", "4"])
        self.single = A.Unit(key="produk:5", nama="Habis", jenis="Produk tunggal", status="Berjalan", mode="GMV Max", daily_cost=30_000,
                             daily_sales=300_000, a=500_000, b=30_000, spread=0.2, members=["5"])
        rows = [("grup:Kloset", "1", "Bintang", 20_000, 600_000), ("grup:Kloset", "2", "Kosong", 15_000, 0),
                ("grup:Kloset", "3", "Lemah", 20_000, 60_000), ("grup:Kloset", "4", "Biasa", 5_000, 240_000),
                ("grup:Lama", "1", "Bintang", 20_000, 100_000), ("grup:Lama", "4", "Biasa", 20_000, 50_000),
                ("produk:5", "5", "Habis", 30_000, 300_000)]
        self.members = pd.DataFrame([{"unit": u, "periode": "2026-10", "product_code": c, "nama": n, "biaya": b, "omzet": o, "terjual": 1}
                                     for u, c, n, b, o in rows])
        self.products = pd.DataFrame([
            {"product_code": "1", "nama": "Bintang", "omzet_harian": 900_000, "stok_room": 1e6, "stok": 50},
            {"product_code": "4", "nama": "Biasa", "omzet_harian": 300_000, "stok_room": 1e6, "stok": 50},
            {"product_code": "5", "nama": "Habis", "omzet_harian": 400_000, "stok_room": 0, "stok": 0},
            {"product_code": "9", "nama": "Laris belum iklan", "omzet_harian": 2_000_000, "stok_room": 1e6, "stok": 20},
        ])

    def test_steps_3_and_4_agree(self):
        units, plan, sel = A.build_plan([self.group, self.old, self.single], self.members, self.products, {},
                                        gap_daily=5_000_000, target_roas=4, budget_daily=None)
        sel = sel.set_index("Kode produk")
        by = {u.key: u for u in units}
        self.assertEqual(sel.loc["5", "Saran"], "Jeda sampai restock")
        self.assertTrue(by["produk:5"].locked)
        self.assertEqual(plan.cost["produk:5"], 0)
        acts = A.target_actions(units, plan, target_roas=4).set_index("key")
        self.assertEqual(acts.loc["produk:5", "Tindakan"], "Jeda")
        self.assertEqual(sel.loc[(sel.index == "1") & (sel["_unit"] == "grup:Kloset"), "Saran"].iloc[0], "Jadikan iklan tunggal")
        self.assertEqual(acts.loc["pisah:1", "Tindakan"], "Pisahkan jadi iklan tunggal")
        self.assertIn("baru:9", acts.index)
        self.assertEqual(sel.loc["9", "Saran"], "Buat iklan tunggal")
        self.assertAlmostEqual(sel.loc["9", "Budget usulan iklan/hari"], plan.cost["baru:9"])
        # Duplikat di iklan berakhir/dijeda = konteks "Biarkan dijeda", bukan langkah Seller Center.
        idle = sel.loc[(sel["Saran"] == A.PAUSED_IDLE) & (sel["_unit"] == "grup:Lama")]
        self.assertEqual(set(idle.index), {"1", "4"})
        self.assertNotIn("1", by["grup:Kloset"].members)
        self.assertAlmostEqual(by["grup:Kloset"].demand, 300_000)

    def test_uplift_capped_by_product_demand(self):
        units, plan, _sel = A.build_plan([self.group, self.old, self.single], self.members, self.products, {},
                                         gap_daily=1e9, target_roas=1, budget_daily=None)
        for u in units:
            if not u.locked:
                self.assertLessEqual(A.ad_sales(u, plan.cost[u.key]) - A._now_sales(u), A.DEMAND_LIFT * u.demand + 1)


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


class RampTest(unittest.TestCase):
    def test_weekly_ramp_lets_budget_grow_beyond_double(self):
        strong = unit("strong", cost=100_000, a=50_000_000, b=2_000_000)
        steps = A.ramp([strong], weeks=[7, 7, 7], gap_total=1e12, target_roas=2, budget_total=None)
        costs = [plan.cost["strong"] for _d, plan in steps]
        self.assertLessEqual(costs[0], 200_000 + 1)
        self.assertGreater(costs[1], 200_000 * 1.5)
        self.assertGreater(costs[2], costs[1])

    def test_ramp_respects_campaign_budget(self):
        strong = unit("strong", cost=100_000, a=50_000_000, b=2_000_000)
        steps = A.ramp([strong], weeks=[7, 7], gap_total=1e12, target_roas=2, budget_total=3_000_000)
        self.assertLessEqual(A.ramp_effect([strong], steps)["biaya_total"], 3_000_000 + 1)

    def test_budget_change_changes_result_when_roas_allows(self):
        strong = unit("strong", cost=100_000, a=50_000_000, b=2_000_000)
        small = A.ramp_effect([strong], A.ramp([strong], weeks=[7, 7], gap_total=1e12, target_roas=2, budget_total=2_000_000))
        big = A.ramp_effect([strong], A.ramp([strong], weeks=[7, 7], gap_total=1e12, target_roas=2, budget_total=4_000_000))
        self.assertGreater(big["omzet_tambahan"], small["omzet_tambahan"])


    def test_ramp_does_not_chase_gap_twice(self):
        units = [unit("a", cost=100_000, a=50_000_000, b=2_000_000), unit("b", cost=100_000, a=40_000_000, b=2_000_000)]
        gap = 2_000_000 * 21
        steps = A.ramp(units, weeks=[7, 7, 7], gap_total=gap, target_roas=2, budget_total=None)
        extra = A.ramp_effect(units, steps)["omzet_tambahan"]
        self.assertGreaterEqual(extra, gap * 0.95)
        self.assertLessEqual(extra, gap * 1.4)


class EvaluateTest(unittest.TestCase):
    def test_detects_applied_and_not_applied(self):
        base = {"a": {"periode": "2026-11-01", "hari": 5, "biaya": 500_000, "omzet": 5_000_000},
                "b": {"periode": "2026-11-01", "hari": 5, "biaya": 500_000, "omzet": 5_000_000}}
        now = {"a": {"periode": "2026-11-01", "hari": 7, "biaya": 900_000, "omzet": 9_000_000},
               "b": {"periode": "2026-11-01", "hari": 7, "biaya": 700_000, "omzet": 6_000_000}}
        frame, summary = A.evaluate(base, now, {"a": 200_000, "b": 400_000}, target_roas=8)
        done = dict(zip(frame["_key"], frame["Rekomendasi dijalankan"]))
        self.assertEqual(done, {"a": "Ya", "b": "Belum"})
        self.assertEqual(summary["hari"], 2)
        self.assertEqual(summary["dijalankan"], 1)
        self.assertAlmostEqual(summary["biaya_harian"], 300_000)

    def test_no_new_days_gives_empty_summary(self):
        base = {"a": {"periode": "2026-11-01", "hari": 7, "biaya": 900_000, "omzet": 9_000_000}}
        frame, summary = A.evaluate(base, base, {"a": 200_000}, target_roas=8)
        self.assertTrue(frame.empty)
        self.assertEqual(summary, {})

    def test_new_single_ad_is_matched_to_report_product_key(self):
        base = {"grup:A": {"periode": "2026-11-01", "hari": 7, "biaya": 700_000, "omzet": 7_000_000}}
        now = {"grup:A": {"periode": "2026-11-01", "hari": 8, "biaya": 800_000, "omzet": 8_000_000},
               "produk:42": {"periode": "2026-11-01", "hari": 8, "biaya": 50_000, "omzet": 600_000}}
        frame, _summary = A.evaluate(base, now, {"grup:A": 100_000, "pisah:42": 50_000}, target_roas=8)
        row = frame.set_index("_key").loc["pisah:42"]
        self.assertEqual(row["Hari dievaluasi"], 1)
        # Tanpa baseline biaya: porsi 1/8 dari MTD — bukan 50 rb seolah semua dibakar dalam 1 hari
        self.assertAlmostEqual(row["Biaya aktual/hari"], 50_000 / 8)
        self.assertAlmostEqual(row["Biaya sejak disimpan"], 50_000 / 8)
        self.assertIn("proporsional", str(row["Catatan batas"]))

    def test_missing_baseline_cost_does_not_inflate_daily_rate(self):
        """Bug jeda tertinggal: baseline hari=14 biaya=0 + MTD 33 jt / 19 hari → jangan jadi 6,5 jt/hari."""
        # Gejala layar: terpakai sejak 6,59 jt vs bulan 4,07 jt untuk total ~33 jt
        base = {"produk:shower": {"periode": "2026-11-01", "hari": 14, "biaya": 0.0, "omzet": 0.0}}
        now = {"produk:shower": {
            "periode": "2026-11-01", "hari": 19,
            "biaya": 4_073_599 * 19, "omzet": (4_073_599 * 19) * 6.1,
        }}
        frame, _ = A.evaluate(base, now, {"produk:shower": 0}, target_roas=8)
        row = frame.set_index("_key").loc["produk:shower"]
        self.assertEqual(row["Hari dievaluasi"], 5)
        # Rata-rata sejak ≈ rata-rata bulan (bukan total_bulan ÷ 5)
        self.assertAlmostEqual(row["Biaya aktual/hari"], 4_073_599, delta=1)
        self.assertLess(row["Biaya aktual/hari"], 5_000_000)  # bukan ~6,5 jt menggelembung
        self.assertIn("proporsional", str(row["Catatan batas"]))


class RoundBudgetTest(unittest.TestCase):
    def test_multiples_of_25k_within_shopee_limits(self):
        self.assertEqual(A.round_budget(0), 0.0)
        self.assertEqual(A.round_budget(3_000), 25_000)
        self.assertEqual(A.round_budget(142_784), 150_000)
        self.assertEqual(A.round_budget(137_000), 125_000)
        self.assertEqual(A.round_budget(110_000, hi=110_000), 100_000)  # tidak melewati batas naik 2×
        self.assertEqual(A.round_budget(60_000, lo=62_000), 75_000)     # tidak di bawah batas turun ½

    def test_plan_budgets_are_rounded(self):
        u = A.Unit(key="produk:1", nama="X", jenis="Produk tunggal", status="Berjalan", mode="GMV Max", daily_cost=73_333, daily_sales=900_000,
                   a=1_500_000, b=70_000, spread=0.2, members=["1"])
        plan = A.allocate_target([u], gap_daily=500_000, target_roas=5, budget_daily=None)
        self.assertEqual(plan.cost["produk:1"] % 25_000, 0)


class ExcludeAndEfficiencyTest(unittest.TestCase):
    def test_excluded_products_leave_ads_and_are_not_proposed(self):
        import pandas as pd

        group = A.Unit(key="grup:G", nama="G", jenis="Grup", status="Berjalan", mode="GMV Max", daily_cost=60_000, daily_sales=900_000,
                       a=1, b=1, spread=0.2, members=["1", "2"])
        members = pd.DataFrame([
            {"unit": "grup:G", "periode": "2026-10", "product_code": "1", "nama": "Kloset", "biaya": 30_000, "omzet": 600_000, "terjual": 5},
            {"unit": "grup:G", "periode": "2026-10", "product_code": "2", "nama": "Lem Dextone", "biaya": 30_000, "omzet": 300_000, "terjual": 5},
        ])
        products = pd.DataFrame([
            {"product_code": "1", "nama": "Kloset", "omzet_harian": 900_000, "qty_harian": 2, "stok_room": 1e6, "stok": 50},
            {"product_code": "2", "nama": "Lem Dextone", "omzet_harian": 800_000, "qty_harian": 5, "stok_room": 1e6, "stok": 50},
            {"product_code": "3", "nama": "Lem Dextone besar", "omzet_harian": 2_000_000, "qty_harian": 5, "stok_room": 1e6, "stok": 50},
        ])
        sel = A.product_selection(members, [group], products, {}, target_roas=5, exclude={"2", "3"}).set_index("Kode produk")
        self.assertEqual(sel.loc["2", "Saran"], A.MANUAL_OUT)
        self.assertNotIn("3", sel.index)

    def test_inefficient_ad_is_cut(self):
        poor = A.Unit(key="produk:9", nama="Boros", jenis="Produk tunggal", status="Berjalan", mode="GMV Max", daily_cost=100_000, daily_sales=200_000,
                      a=300_000, b=100_000, spread=0.2, members=["9"])
        plan = A.allocate_target([poor], gap_daily=1_000_000, target_roas=1.5, budget_daily=None)
        self.assertEqual(plan.cost["produk:9"], 0.0)


class StrictEfficiencySpendsLessTest(unittest.TestCase):
    def test_higher_floor_never_spends_more(self):
        u = A.Unit(key="produk:1", nama="X", jenis="Produk tunggal", status="Berjalan", mode="GMV Max", daily_cost=200_000, daily_sales=2_400_000,
                   a=2_000_000, b=150_000, spread=0.2, members=["1"])
        loose = A.allocate_target([u], gap_daily=5_000_000, target_roas=2, budget_daily=None, min_marginal=2)
        strict = A.allocate_target([u], gap_daily=5_000_000, target_roas=2, budget_daily=None, min_marginal=10)
        self.assertLessEqual(strict.cost["produk:1"], loose.cost["produk:1"])
        for v in (loose.cost["produk:1"], strict.cost["produk:1"]):
            self.assertEqual(v % A.BUDGET_STEP, 0)


class MarginPriorityTest(unittest.TestCase):
    def test_positive_margin_gets_budget_first(self):
        def mk(key, contrib, fast=False):
            u = A.Unit(key=key, nama=key, jenis="Produk tunggal", status="Berjalan", mode="GMV Max", daily_cost=100_000, daily_sales=1_500_000,
                       a=2_000_000, b=100_000, spread=0.2, members=[key], contribution=contrib)
            u.fast = fast
            return u
        good, bad, fast_bad = mk("good", 0.15), mk("bad", -0.1), mk("fastbad", -0.1, fast=True)
        self.assertGreater(A.priority(good), A.priority(fast_bad))
        self.assertGreater(A.priority(fast_bad), A.priority(bad))
        plan = A.allocate_target([good, bad], gap_daily=10_000_000, target_roas=2, budget_daily=250_000)
        self.assertGreater(plan.cost["good"], plan.cost["bad"])


class MarginAwareSelectionTest(unittest.TestCase):
    def test_negative_margin_not_promoted_to_single_and_new_singles_prefer_profit(self):
        import pandas as pd

        group = A.Unit(key="grup:G", nama="G", jenis="Grup", status="Berjalan", mode="GMV Max", daily_cost=100_000, daily_sales=1_200_000,
                       a=1, b=1, spread=0.2, members=["star", "loss", "mid"])
        members = pd.DataFrame([
            {"unit": "grup:G", "periode": "2026-09", "product_code": "star", "nama": "Star", "biaya": 40_000, "omzet": 700_000, "terjual": 5},
            {"unit": "grup:G", "periode": "2026-10", "product_code": "star", "nama": "Star", "biaya": 40_000, "omzet": 700_000, "terjual": 5},
            {"unit": "grup:G", "periode": "2026-09", "product_code": "loss", "nama": "Loss", "biaya": 40_000, "omzet": 400_000, "terjual": 4},
            {"unit": "grup:G", "periode": "2026-10", "product_code": "loss", "nama": "Loss", "biaya": 40_000, "omzet": 400_000, "terjual": 4},
            {"unit": "grup:G", "periode": "2026-09", "product_code": "mid", "nama": "Mid", "biaya": 20_000, "omzet": 100_000, "terjual": 1},
            {"unit": "grup:G", "periode": "2026-10", "product_code": "mid", "nama": "Mid", "biaya": 20_000, "omzet": 100_000, "terjual": 1},
        ])
        products = pd.DataFrame([
            {"product_code": "star", "nama": "Star", "omzet_harian": 900_000, "qty_harian": 3, "stok_room": 1e6, "stok": 50},
            {"product_code": "loss", "nama": "Loss", "omzet_harian": 800_000, "qty_harian": 3, "stok_room": 1e6, "stok": 50},
            {"product_code": "mid", "nama": "Mid", "omzet_harian": 200_000, "qty_harian": 1, "stok_room": 1e6, "stok": 50},
            {"product_code": "new_good", "nama": "New Good", "omzet_harian": 2_000_000, "qty_harian": 5, "stok_room": 1e6, "stok": 40},
            {"product_code": "new_bad", "nama": "New Bad", "omzet_harian": 3_000_000, "qty_harian": 6, "stok_room": 1e6, "stok": 40},
        ])
        contrib = {"star": 0.18, "loss": -0.12, "mid": 0.05, "new_good": 0.22, "new_bad": -0.15}
        sel = A.product_selection(members, [group], products, contrib, target_roas=8, focus=False).set_index("Kode produk")
        self.assertEqual(sel.loc["star", "Saran"], "Jadikan iklan tunggal")
        self.assertEqual(sel.loc["loss", "Saran"], "Keluarkan dari grup")
        self.assertEqual(sel.loc["new_good", "Saran"], "Buat iklan tunggal")
        self.assertEqual(sel.loc["new_bad", "Saran"], "Tambahkan ke grup")
        self.assertIn("margin minus", sel.loc["new_bad", "Alasan"])


class OccupiedNoDuplicateTest(unittest.TestCase):
    def test_occupied_codes_are_not_proposed_as_new_singles(self):
        import pandas as pd

        products = pd.DataFrame([
            {"product_code": "free", "nama": "Free", "omzet_harian": 3_000_000, "qty_harian": 5, "stok_room": 1e6, "stok": 40},
            {"product_code": "busy", "nama": "Busy Auto", "omzet_harian": 5_000_000, "qty_harian": 8, "stok_room": 1e6, "stok": 40},
        ])
        sel = A.product_selection(pd.DataFrame(), [], products, {"free": 0.2, "busy": 0.2}, target_roas=8, focus=False,
                                  occupied={"busy"}).set_index("Kode produk")
        self.assertEqual(sel.loc["busy", "Saran"], "Sudah di iklan lain")
        self.assertEqual(sel.loc["free", "Saran"], "Buat iklan tunggal")
        self.assertIn("dobel", sel.loc["busy", "Alasan"])


class GapCatalogAuditTest(unittest.TestCase):
    """Campaign baru / gap besar: audit katalog prediksi, bukan hanya rapikan iklan yang sedang jalan."""

    def test_large_gap_surfaces_many_new_singles_from_catalog(self):
        import pandas as pd

        # Satu iklan jalan lemah + banyak produk belum diiklan dengan prediksi menengah (di bawah lantai 95% ketat).
        running = A.Unit(key="produk:r", nama="Running", jenis="Produk tunggal", status="Berjalan", mode="GMV Max",
                         daily_cost=80_000, daily_sales=200_000, a=400_000, b=80_000, spread=0.2, members=["r"])
        members = pd.DataFrame([
            {"unit": "produk:r", "periode": "2026-10", "product_code": "r", "nama": "Running", "biaya": 80_000, "omzet": 200_000, "terjual": 2},
        ])
        # Dominan sales → lantai 95% tinggi; produk mid biasanya tersaring tanpa mode gap.
        rows = [{"product_code": "r", "nama": "Running", "omzet_harian": 20_000_000, "qty_harian": 10, "stok_room": 1e6, "stok": 50}]
        for i in range(1, 25):
            rows.append({
                "product_code": f"n{i}", "nama": f"New {i}", "omzet_harian": 400_000 + i * 10_000,
                "qty_harian": 1.2, "stok_room": 1e6, "stok": 30,
            })
        products = pd.DataFrame(rows)
        contrib = {r["product_code"]: 0.12 for r in rows}
        tight = A.product_selection(members, [running], products, contrib, target_roas=8, focus=True, gap_daily=0)
        loose = A.product_selection(members, [running], products, contrib, target_roas=8, focus=True, gap_daily=5_000_000)
        new_tight = int((tight["Saran"] == "Buat iklan tunggal").sum())
        new_loose = int((loose["Saran"] == "Buat iklan tunggal").sum())
        self.assertGreater(new_loose, new_tight)
        self.assertGreaterEqual(new_loose, 8)
        # Produk di iklan aktif tetap tidak digandakan.
        self.assertFalse(((loose["Saran"] == "Buat iklan tunggal") & (loose["Kode produk"] == "r")).any())

    def test_high_sales_margin_minus_single_kept_when_chasing_target(self):
        import pandas as pd

        big = A.Unit(key="produk:1", nama="Star", jenis="Produk tunggal", status="Berjalan", mode="GMV Max",
                     daily_cost=200_000, daily_sales=3_000_000, a=5_000_000, b=200_000, spread=0.2, members=["1"])
        small = A.Unit(key="produk:2", nama="Weak", jenis="Produk tunggal", status="Berjalan", mode="GMV Max",
                       daily_cost=50_000, daily_sales=40_000, a=80_000, b=50_000, spread=0.2, members=["2"])
        members = pd.DataFrame([
            {"unit": "produk:1", "periode": "2026-10", "product_code": "1", "nama": "Star", "biaya": 200_000, "omzet": 3_000_000, "terjual": 20},
            {"unit": "produk:2", "periode": "2026-10", "product_code": "2", "nama": "Weak", "biaya": 50_000, "omzet": 40_000, "terjual": 1},
        ])
        products = pd.DataFrame([
            {"product_code": "1", "nama": "Star", "omzet_harian": 4_000_000, "qty_harian": 8, "stok_room": 1e6, "stok": 40},
            {"product_code": "2", "nama": "Weak", "omzet_harian": 50_000, "qty_harian": 0.2, "stok_room": 1e6, "stok": 40},
        ])
        # Target ROAS tinggi → ROAS star (15) < target, margin minus: dulu selalu Pindahkan; sekarang star dipertahankan.
        sel = A.product_selection(members, [big, small], products, {"1": -0.1, "2": -0.1}, target_roas=20, focus=False,
                                  gap_daily=3_000_000).set_index("Kode produk")
        self.assertEqual(sel.loc["1", "Saran"], "Pertahankan iklan tunggal")
        self.assertIn("mengejar target", sel.loc["1", "Alasan"])
        self.assertEqual(sel.loc["2", "Saran"], "Pindahkan ke grup")

    def test_build_plan_gap_passes_through_to_new_units(self):
        import pandas as pd

        products = pd.DataFrame([
            {"product_code": f"n{i}", "nama": f"N{i}", "omzet_harian": 800_000 + i * 50_000, "qty_harian": 2,
             "stok_room": 1e6, "stok": 40}
            for i in range(12)
        ])
        contrib = {f"n{i}": 0.15 for i in range(12)}
        units, plan, sel = A.build_plan(
            [], pd.DataFrame(), products, contrib,
            gap_daily=4_000_000, target_roas=6, budget_daily=2_000_000,
        )
        news = sel.loc[sel["Saran"] == "Buat iklan tunggal"]
        self.assertGreaterEqual(len(news), 5)
        funded = [u for u in units if u.jenis.endswith("(baru)") and plan.cost.get(u.key, 0) > 0]
        self.assertGreaterEqual(len(funded), 3)


class SellerCenterSetupTest(unittest.TestCase):
    def test_setup_export_has_two_sheets_floors_and_roas_cap(self):
        import pandas as pd

        acts = pd.DataFrame([
            {"Tindakan": "Naikkan budget", "Iklan": "Kloset", "Jenis": "Produk tunggal", "Kode produk": "1",
             "Budget harian usulan": 10_000, "Target ROAS Shopee": 45.0, "Catatan": "x"},
            {"Tindakan": "Buat iklan baru", "Iklan": "Lem baru", "Jenis": "Grup", "Kode produk": "2",
             "Budget harian usulan": 50_000, "Target ROAS Shopee": 12.0, "Catatan": "y"},
        ])
        sheets = A.seller_center_setup(acts, None, campaign="uji", target_roas=40, period="1–10 Nov")
        self.assertEqual(set(sheets), {"Ringkas", "Setelan Seller Center"})
        setup = sheets["Setelan Seller Center"]
        self.assertEqual(list(setup.columns)[0], "Urutan")
        # Floor: tunggal 10rb → 25rb; grup 50rb → 100rb
        by_iklan = setup.set_index("Iklan")
        self.assertEqual(by_iklan.loc["Kloset", "Budget harian isi (Rp)"], A.SHOPEE_MIN_SINGLE)
        self.assertEqual(by_iklan.loc["Lem baru", "Budget harian isi (Rp)"], A.SHOPEE_MIN_GROUP)
        self.assertLessEqual(float(by_iklan.loc["Kloset", "Target ROAS isi"]), A.MAX_SHOPEE_ROAS)
        self.assertIn("30", sheets["Ringkas"]["Nilai"].astype(str).str.cat(sep=" "))

    def test_setup_omits_reactivate_and_paused_selection_rows(self):
        import pandas as pd

        acts = pd.DataFrame([
            {"Tindakan": "Aktifkan kembali", "Iklan": "Lama dijeda", "Jenis": "Produk tunggal", "Kode produk": "9",
             "Budget harian usulan": 50_000, "Target ROAS Shopee": 8.0, "Catatan": "jangan muncul"},
            {"Tindakan": "Naikkan budget", "Iklan": "Aktif", "Jenis": "Produk tunggal", "Kode produk": "1",
             "Budget harian usulan": 50_000, "Target ROAS Shopee": 8.0, "Catatan": "ok"},
        ])
        selection = pd.DataFrame([
            {"Saran": A.PAUSED_IDLE, "Produk": "P", "Kode produk": "9", "Iklan sekarang": "Lama (dijeda)",
             "Alasan": "biarkan", "Biaya iklan/hari": 0, "Omzet iklan/hari": 0},
            {"Saran": "Keluarkan dari grup", "Produk": "Q", "Kode produk": "2", "Iklan sekarang": "Grup Semen",
             "Alasan": "dobel", "Biaya iklan/hari": 10_000, "Omzet iklan/hari": 0},
        ])
        setup = A.seller_center_setup(acts, selection, campaign="uji", target_roas=8, period="1–10")["Setelan Seller Center"]
        text = setup.astype(str).to_string() if not setup.empty else ""
        self.assertNotIn("Aktifkan kembali", text)
        self.assertNotIn("Lama dijeda", text)
        self.assertNotIn("Biarkan dijeda", text)
        self.assertIn("Aktif", text)
        self.assertIn("Keluarkan", text)

    def test_target_actions_never_exceed_roas_30_and_apply_floors(self):
        u = A.Unit(key="produk:1", nama="X", jenis="Produk tunggal", status="Berjalan", mode="GMV Max",
                   daily_cost=25_000, daily_sales=2_000_000, a=5_000_000, b=20_000, spread=0.2, members=["1"], contribution=0.2)
        plan = A.allocate_target([u], gap_daily=10_000_000, target_roas=2, budget_daily=100_000)
        acts = A.target_actions([u], plan, target_roas=2)
        self.assertFalse(acts.empty)
        self.assertTrue((acts["Target ROAS Shopee"].fillna(0) <= A.MAX_SHOPEE_ROAS).all())
        active = acts.loc[acts["Budget harian usulan"] > 0]
        self.assertTrue((active["Budget harian usulan"] >= A.SHOPEE_MIN_SINGLE).all())


class PausedAdsSelectionTest(unittest.TestCase):
    def test_paused_product_labeled_idle_and_can_get_new_ad_if_not_active(self):
        import pandas as pd

        paused = A.Unit(key="produk:9", nama="Keramik lama", jenis="Produk tunggal", status="Dijeda", mode="GMV Max",
                        daily_cost=50_000, daily_sales=0, a=1, b=1, spread=0.2, members=["9"])
        members = pd.DataFrame([
            {"unit": "produk:9", "periode": "2026-10", "product_code": "9", "nama": "Keramik", "biaya": 20_000, "omzet": 100_000, "terjual": 1},
        ])
        products = pd.DataFrame([
            {"product_code": "9", "nama": "Keramik", "omzet_harian": 2_000_000, "qty_harian": 4, "stok_room": 1e6, "stok": 40},
            {"product_code": "8", "nama": "Laris", "omzet_harian": 3_000_000, "qty_harian": 5, "stok_room": 1e6, "stok": 40},
        ])
        sel = A.product_selection(members, [paused], products, {"9": 0.2, "8": 0.2}, target_roas=8, focus=False)
        idle = sel.loc[sel["Saran"] == A.PAUSED_IDLE]
        self.assertFalse(idle.empty)
        self.assertIn("dijeda", idle.iloc[0]["Alasan"].lower())
        # Produk hanya di iklan dijeda boleh diusulkan buat baru (belum di iklan aktif)
        news = sel.loc[sel["Saran"] == "Buat iklan tunggal", "Kode produk"].astype(str).tolist()
        self.assertIn("9", news)
        self.assertIn("8", news)
        plan = A.allocate_target([paused], gap_daily=100_000, target_roas=8, budget_daily=50_000)
        self.assertEqual(plan.cost.get("produk:9", 0), 0.0)
        acts = A.target_actions([paused], plan, target_roas=8)
        self.assertTrue(acts.empty)
        setup = A.seller_center_setup(acts, sel, campaign="uji", target_roas=8)["Setelan Seller Center"]
        # Sheet tindakan tidak memuat iklan dijeda sebagai langkah setel ulang
        if not setup.empty:
            self.assertNotIn("Keramik lama", setup["Iklan"].astype(str).tolist())
            self.assertFalse(setup["Langkah di Seller Center"].astype(str).str.contains("Aktifkan", case=False).any())

    def test_active_ad_still_gets_keep_change_pause(self):
        active = unit("produk:1", cost=100_000, a=6_000_000, b=300_000, status="Berjalan")
        plan = A.allocate_target([active], gap_daily=0, target_roas=30, budget_daily=None)
        acts = A.target_actions([active], plan, target_roas=30)
        self.assertFalse(acts.empty)
        self.assertIn(acts.iloc[0]["Tindakan"], {"Pertahankan", "Turunkan budget", "Jeda", "Naikkan budget"})
        self.assertEqual(acts.iloc[0]["Status iklan"], "Berjalan")


class RecOptionsUnderwaterTest(unittest.TestCase):
    def test_underwater_pick_prefers_contribution_not_max_sales(self):
        from src.ui.ads_target import _rec_options
        from src.core.ads_month import StoreCurve

        # Kurva lemah: marginal di laju tinggi ≈ 1,4 → butuh kontribusi ≥ 71%; kita kasih −10%.
        curve = StoreCurve(s0=2e9, a=2e8, b=1e8, points=[("2026-08", 1e8, 2.2e9), ("2026-09", 2e8, 2.4e9), ("2026-10", 2.5e8, 2.5e9)], source="uji")
        target, projection, spent = 5_000_000_000, 3_300_000_000, 190_000_000
        days_left, month_days, run_days = 10, 30, 10
        spent_daily, cost_now = 9_500_000, 40_000_000
        pace_total = spent + cost_now * days_left

        def best_roas(daily, gap, mm=5.0):
            return 8.0

        def option(r, daily, gap, mm=5.0):
            # "Efisien" menyerap hampir semua daily; lean (mm tinggi) lebih hemat.
            use = daily * (0.4 if mm >= 10 else 0.9)
            return {"biaya_total": use * run_days, "omzet_tambahan": use * 6 * run_days, "roas_rencana": 6.0}

        def project(tgt, budget, roas, mm=5.0):
            used_daily = max(budget - spent, 0) / days_left * (0.4 if mm >= 10 else 0.9)
            effective = spent + used_daily * days_left
            extra = (budget - spent) * 0.02
            return projection + extra, extra, True, effective

        def economics(final, effective):
            return effective / final * 100, final * (-0.101) - effective

        def ratio_budget():
            return 150_000_000

        opts, info = _rec_options(
            target=target, projection=projection, spent=spent, cost_now=cost_now, days_left=days_left, month_days=month_days,
            run_days=run_days, pace_total=pace_total, curve=curve, spent_daily=spent_daily, best_roas=best_roas, option=option,
            project=project, units=[], factor=0.85, month_name="November 2026", economics=economics, ratio_budget=ratio_budget,
            user_budget=300_000_000, contrib_rate=-0.101,
        )
        self.assertTrue(info["underwater"])
        self.assertTrue(info["high_burn"])
        utama = next(o for o in opts if o["utama"])
        self.assertFalse(utama["nama"].startswith("A · Laju tinggi") or "Laju tinggi" in utama["nama"])
        # Saran utama harus punya laba (paling tidak buruk) ≥ opsi sales-max yang lebih boros.
        boros = max(opts, key=lambda o: o["efektif"])
        self.assertGreaterEqual(utama["laba"], boros["laba"])
        self.assertLessEqual(utama["efektif"], boros["efektif"])
        self.assertTrue(any("Kembalikan ke rata-rata" in o["nama"] for o in opts))
        self.assertFalse(any("100% target" in o["nama"] for o in opts))
