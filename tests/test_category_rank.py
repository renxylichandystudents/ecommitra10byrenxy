import unittest

import pandas as pd

from src.core import category_rank as R


def comp(daftar, rank, shop, name, own=False, change="1"):
    return {"Daftar": daftar, "rank": str(rank), "rank_change": "My Shop" if own else change, "shop_name": shop, "product_name": name, "own_shop": own}


class CategoryRankTest(unittest.TestCase):
    def setUp(self):
        rows = [comp(1, i, f"Toko {i} Official Store", f"Water Heater Listrik Pemanas Air {i}0L Garansi") for i in range(1, 10)]
        rows += [comp(1, 4, "Mitra10 Official Store", "Water Heater Heatsafe 15L Pemanas Air")]          # sudah top 10, bukan baris "My Shop"
        rows += [comp(1, 40, "Mitra10 Official Store", "Water Heater Heatsafe 30L", own=True)]
        rows += [comp(2, i, f"Toko K{i}", f"Kloset Duduk Toilet Soft Close {i}") for i in range(1, 11)]
        rows += [comp(2, 2000, "Mitra10 Official Store", "Kloset Tidy FSA0089", own=True)]
        self.competitors = pd.DataFrame(rows)
        self.catalog = pd.DataFrame([
            {"nama": "Water Heater Heatsafe 15L Pemanas Air", "sku": "A", "qty_bulan": 100.0, "omzet_bulan": 1e8, "stok": 50.0, "ada_stok": True, "harga": 1e6, "iklan": True},
            {"nama": "Water Heater Heatsafe 30L", "sku": "B", "qty_bulan": 20.0, "omzet_bulan": 2e7, "stok": 0.0, "ada_stok": True, "harga": 1e6, "iklan": False},
            {"nama": "Kloset Tidy FSA0089", "sku": "C", "qty_bulan": 300.0, "omzet_bulan": 3e8, "stok": 500.0, "ada_stok": True, "harga": 1e6, "iklan": True},
        ])

    def test_label_tiers_and_mitra10_rows(self):
        summary, opp = R.analyze(self.competitors, self.catalog)
        s = summary.set_index("Daftar")
        self.assertIn("Water Heater", s.loc[1, "Kategori"])
        self.assertEqual(s.loc[1, "Status"], "Sudah Top 10")
        self.assertEqual(s.loc[2, "Status"], "Jauh")
        o = opp.set_index("SKU")
        self.assertEqual(o.loc["A", "Status"], "Sudah Top 10")
        self.assertEqual(o.loc["B", "Status"], "Dekat")

    def test_need_uses_top10_anchor_and_actions(self):
        _summary, opp = R.analyze(self.competitors, self.catalog)
        o = opp.set_index("SKU")
        self.assertAlmostEqual(o.loc["B", "Perlu/bulan (perkiraan)"], 100 * 4 / 10)
        self.assertAlmostEqual(o.loc["B", "Kali lipat"], 2.0)
        self.assertIn("restock dulu", o.loc["B", "Langkah"])
        self.assertIn("buat iklan produk tunggal", o.loc["B", "Langkah"])
        self.assertAlmostEqual(o.loc["C", "Kali lipat"], 200.0)
        self.assertNotIn("Flash sale", o.loc["C", "Langkah"])

    def test_by_product_covers_whole_catalog(self):
        catalog = pd.concat([self.catalog, pd.DataFrame([
            {"nama": "Water Heater Listrik Pemanas Air Mini", "sku": "D, D2", "n_sku": 2, "qty_bulan": 5.0, "omzet_bulan": 5e6, "stok": 10.0, "ada_stok": True,
             "harga": 1e6, "iklan": False}])], ignore_index=True)
        summary, opp = R.analyze(self.competitors, catalog)
        products, missing = R.by_product(self.competitors, catalog, summary, opp)
        self.assertEqual(len(products), len(catalog))
        self.assertEqual(int(products["Jumlah SKU"].sum()), 5)
        row = products.set_index("SKU").loc["D, D2"]
        self.assertEqual(row["Status"], R.UNRANKED)
        self.assertEqual(row["Daftar"], 1)
        self.assertEqual(row["Kelompok"], "Water heater")
        self.assertIn("Kelompok", summary.columns)
        self.assertTrue(missing.empty)

    def test_keyword_gap_only_for_same_product_type(self):
        self.assertEqual(R.missing_keywords("Kloset Tidy", ["kloset", "duduk", "toilet"]), ["duduk", "toilet"])
        self.assertEqual(R.missing_keywords("Wastafel Gantung", ["floor", "drain"]), [])


if __name__ == "__main__":
    unittest.main()
