import unittest
from datetime import date

import pandas as pd

from src.core.ads import ad_validation, attribute_ads
from src.core.recommendations import ads_plan, allocate_budget


def _ads(period="2026-10-01", **extra):
    rows = [
        {"period": period, "product_code": "-", "product_name": "Grup A", "cost": 300.0, "ad_sales": 3000.0},
        {"period": period, "product_code": "111", "product_name": "Kloset", "cost": 200.0, "ad_sales": 2000.0},
        {"period": period, "product_code": "222", "product_name": "Pompa", "cost": 100.0, "ad_sales": 1000.0},
    ]
    return pd.DataFrame(rows)


STOCK = pd.DataFrame(
    {
        "product_code": ["111", "111", "222"],
        "sku": ["600007312", "600007313", "1300003198"],
    }
)


def _orders(day="2026-10-05"):
    return pd.DataFrame(
        {
            "sku": ["600007312", "600007313", "1300003198"],
            "sales": [750.0, 250.0, 5000.0],
            "qty": [3, 1, 10],
            "order_time": pd.to_datetime([day] * 3),
        }
    )


class AdAttributionTest(unittest.TestCase):
    def test_variant_split_proportional_to_sales(self):
        result = attribute_ads([_ads()], STOCK, orders=_orders(), start="2026-10-01", end="2026-10-31")
        per = result.per_sku.set_index("sku")
        self.assertAlmostEqual(per.loc["600007312", "biaya_iklan"], 150.0)
        self.assertAlmostEqual(per.loc["600007313", "biaya_iklan"], 50.0)
        self.assertNotEqual(per.loc["600007312", "biaya_iklan"], per.loc["600007313", "biaya_iklan"])
        self.assertAlmostEqual(result.cost, 300.0)
        self.assertAlmostEqual(result.file_cost, 300.0)

    def test_equal_split_without_sales(self):
        result = attribute_ads([_ads()], STOCK, orders=None, start="2026-10-01", end="2026-10-31")
        per = result.per_sku.set_index("sku")
        self.assertAlmostEqual(per.loc["600007312", "biaya_iklan"], 100.0)
        self.assertAlmostEqual(per.loc["600007313", "biaya_iklan"], 100.0)

    def test_summary_rows_and_other_periods_excluded(self):
        frames = [_ads("2026-10-01"), _ads("2026-09-01")]
        result = attribute_ads(frames, STOCK, orders=_orders(), start="2026-10-01", end="2026-10-31")
        self.assertAlmostEqual(result.file_cost, 300.0)
        latest = attribute_ads(frames, STOCK, orders=_orders())
        # Tanpa rentang: 30 hari yang berakhir di hari terakhir laporan iklan, diprorata per hari.
        self.assertEqual(latest.end, pd.Timestamp("2026-10-31"))
        self.assertEqual(latest.start, pd.Timestamp("2026-10-02"))
        self.assertAlmostEqual(latest.file_cost, 300.0 * 30 / 31)

    def test_omzet_follows_shopee_and_validation(self):
        result = attribute_ads([_ads()], STOCK, orders=_orders(), start="2026-10-01", end="2026-10-31")
        per = result.per_sku.set_index("sku")
        # Omzet tidak dipotong sales SKU: sama dengan laporan Shopee (dibagi ke varian menurut sales).
        self.assertAlmostEqual(per.loc["600007312", "omzet_iklan"], 1500.0)
        self.assertAlmostEqual(result.sales, 3000.0)
        warnings, notes = ad_validation(result, 1000.0)
        self.assertEqual(warnings, [])
        self.assertTrue(any("Shopee" in n for n in notes))

    def test_validation_flags_unmapped_cost(self):
        ads = pd.concat([_ads(), pd.DataFrame([{"period": "2026-10-01", "product_code": "999", "product_name": "X", "cost": 50_000.0, "ad_sales": 0.0}])])
        result = attribute_ads([ads], STOCK, orders=_orders(), start="2026-10-01", end="2026-10-31")
        warnings, _notes = ad_validation(result, 6000.0)
        self.assertTrue(any("belum ada di Data stok" in w for w in warnings))


class AllIklanReferenceTest(unittest.TestCase):
    """All iklan = acuan total; otomatis + grup + iklan satu produk = rincian; laporan tumpang tindih tidak dobel."""

    def _frames(self):
        text = {"Periode laporan (teks)": "01/11/2026 - 07/11/2026", "period": "2026-11-01", "_submitted_at": "2026-11-07T14:00"}
        overall = pd.DataFrame(
            [
                {"product_code": "-", "product_name": "Iklan Produk Otomatis", "cost": 700.0, "ad_sales": 7000.0},
                {"product_code": "-", "product_name": "Grup Closet", "cost": 200.0, "ad_sales": 3000.0},
                {"product_code": "111", "product_name": "Kloset (iklan satu produk)", "cost": 100.0, "ad_sales": 1000.0},
            ]
        ).assign(_source_key="ads_overall", **text)
        auto = pd.DataFrame(
            [
                {"product_code": "-", "product_name": "Iklan Produk Otomatis", "cost": 700.0, "ad_sales": 7000.0},
                {"product_code": "222", "product_name": "Pompa", "cost": 700.0, "ad_sales": 7000.0},
            ]
        ).assign(_source_key="ads_auto", **text)
        group = pd.DataFrame(
            [
                {"product_code": "-", "product_name": "Grup Closet", "cost": 200.0, "ad_sales": 3000.0},
                {"product_code": "111", "product_name": "Kloset", "cost": 200.0, "ad_sales": 3000.0},
            ]
        ).assign(_source_key="ads_group", **text)
        return overall, auto, group

    def test_total_sama_dengan_all_iklan_dan_rincian_cocok(self):
        overall, auto, group = self._frames()
        result = attribute_ads([auto, group, overall], STOCK, start="2026-11-01", end="2026-11-07")
        self.assertAlmostEqual(result.total_cost, 1000.0)
        self.assertAlmostEqual(result.total_sales, 11000.0)
        self.assertAlmostEqual(result.file_cost, 1000.0)  # 700 otomatis + 200 grup + 100 iklan satu produk
        self.assertEqual(result.days, 7)
        per = result.per_sku.set_index("sku")
        self.assertAlmostEqual(per.loc["1300003198", "biaya_iklan"], 700.0)
        self.assertAlmostEqual(per.loc["1300003198", "biaya_harian"], 100.0)

    def test_unggahan_ulang_rentang_lebih_panjang_tidak_dobel(self):
        overall, auto, group = self._frames()
        older = overall.assign(**{"Periode laporan (teks)": "01/11/2026 - 05/11/2026", "_submitted_at": "2026-11-05T09:00"})
        result = attribute_ads([auto, group, overall, older], STOCK, start="2026-11-01", end="2026-11-07")
        self.assertAlmostEqual(result.total_cost, 1000.0)

    def test_prorata_laporan_bulanan(self):
        overall, _auto, _group = self._frames()
        october = overall.assign(**{"Periode laporan (teks)": "01/10/2026 - 31/10/2026", "period": "2026-10-01", "_submitted_at": "2026-11-01T09:00"})
        result = attribute_ads([october, overall], STOCK, start="2026-10-25", end="2026-11-07")
        self.assertAlmostEqual(result.total_cost, 1000.0 * 7 / 31 + 1000.0)
        self.assertEqual(result.days, 14)


def _eligible():
    return pd.DataFrame(
        {
            "roas_est": [12.0, 10.0, 9.0],
            "sales_periode": [10_000_000.0, 5_000_000.0, 2_000_000.0],
            "stok": [100.0, 5.0, 50.0],
            "ss": [10.0, 10.0, 5.0],
            "harga_bersih": [200_000.0, 100_000.0, 50_000.0],
            "ada_data_stok": [True, True, True],
        }
    )


class BudgetAllocationTest(unittest.TestCase):
    def test_small_budget_never_exceeded_and_prioritises_stock(self):
        alloc = allocate_budget(_eligible(), budget_max=100_000, target_roas=8, ad_share=0.3)
        self.assertLessEqual(alloc.sum(), 100_000)
        self.assertGreater(alloc.iloc[0], 0)
        self.assertEqual(alloc.iloc[1], 0)

    def test_large_budget_uses_more_but_respects_capacity(self):
        small = allocate_budget(_eligible(), budget_max=100_000, target_roas=8, ad_share=0.3)
        large = allocate_budget(_eligible(), budget_max=250_000_000, target_roas=8, ad_share=0.3)
        self.assertGreater(large.sum(), small.sum())
        self.assertLessEqual(large.sum(), 250_000_000)
        cap = _eligible()["sales_periode"] / _eligible()["roas_est"]
        self.assertTrue((large <= cap + 1).all())

    def test_plan_target_too_high_excludes_everything(self):
        table = pd.DataFrame(
            {
                "item_key": ["a", "b"],
                "sku": ["a", "b"],
                "product_name": ["Kloset", "Pompa"],
                "pred_harian": [2.0, 1.0],
                "harga_bersih": [1_000_000.0, 500_000.0],
                "sales_total": [10_000_000.0, 5_000_000.0],
                "biaya_iklan": [100_000.0, 100_000.0],
                "omzet_iklan": [600_000.0, 500_000.0],
                "m_status": ["Aman", "Aman"],
                "stok": [100.0, 100.0],
                "ss": [5.0, 5.0],
                "ada_data_stok": [True, True],
                "hari_cukup": [50.0, 100.0],
                "label": [[], []],
            }
        )
        start, end = date(2026, 11, 1), date(2026, 11, 30)
        plan = ads_plan(table, orders=None, start=start, end=end, target_roas=50, budget_max=1_000_000, params={}, rules=None)
        self.assertEqual(plan["ringkasan"]["item_diiklankan"], 0)
        self.assertEqual(plan["ringkasan"]["budget"], 0)
        self.assertEqual(len(plan["tidak"]), 2)
        ok = ads_plan(table, orders=None, start=start, end=end, target_roas=4, budget_max=1_000_000, params={}, rules=None)
        self.assertLessEqual(ok["ringkasan"]["budget"], 1_000_000)
        self.assertEqual(ok["ringkasan"]["budget_input"], 1_000_000)
        big = ads_plan(table, orders=None, start=start, end=end, target_roas=4, budget_max=250_000_000, params={}, rules=None)
        self.assertGreater(big["ringkasan"]["budget"], ok["ringkasan"]["budget"])
        self.assertLessEqual(big["ringkasan"]["budget"], 250_000_000)


if __name__ == "__main__":
    unittest.main()
