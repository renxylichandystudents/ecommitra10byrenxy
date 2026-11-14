import unittest
from datetime import date

import pandas as pd

from src.core import flash_sale as F


def item(sku, *, stok, ss=5, harian=2.0, dc=0, harga=100_000, floor=None, batal=10.0, ada_stok=True, m_sales=None, terjual=10):
    return {"sku": sku, "label": sku, "nama": sku, "harga": harga, "stok": stok, "ada_stok": ada_stok, "ss": ss, "harian": harian, "dc": dc,
            "terjual": terjual, "m_sales": m_sales if m_sales is not None else harga * harian * 30, "batal_pct": batal, "floor": floor, "momentum": 0.0}


class CandidatesTest(unittest.TestCase):
    def test_stock_source_tiers(self):
        items = pd.DataFrame([
            item("site", stok=100),                       # 100 − 5 − 14 = 81 bebas
            item("dc", stok=10, dc=500),                  # toko tipis, DC ada
            item("thin", stok=12, harian=2.0, dc=0),      # 7 di atas SS, kebutuhan 7 hari 14 → kuota kecil
            item("empty", stok=0, dc=0),                  # tidak bisa
        ])
        cands, skipped = F.candidates(items)
        src = dict(zip(cands["sku"], cands["sumber"]))
        self.assertEqual(src["site"], F.SRC_SITE)
        self.assertEqual(src["dc"], F.SRC_DC)
        self.assertEqual(src["thin"], F.SRC_THIN)
        self.assertNotIn("empty", src)
        self.assertIn("empty", set(skipped["SKU · produk · varian"]))
        self.assertLessEqual(int(cands.set_index("sku").loc["thin", "kuota"]), 3)

    def test_overstock_gets_clearance_and_bigger_discount(self):
        cands, _ = F.candidates(pd.DataFrame([item("slow", stok=300, harian=1.0)]))
        row = cands.iloc[0]
        self.assertEqual(row["tujuan"], F.CLEAR)
        self.assertGreaterEqual(row["diskon"], 19.9)
        self.assertLessEqual(row["kuota"], 30)

    def test_price_never_below_break_even(self):
        cands, skipped = F.candidates(pd.DataFrame([item("tight", stok=100, harga=100_000, floor=94_000),
                                                    item("none", stok=100, harga=100_000, floor=99_000)]), below_floor=False)
        row = cands.set_index("sku").loc["tight"]
        self.assertGreaterEqual(row["harga_flash"], 94_000)
        self.assertGreaterEqual(row["diskon"], 5)
        self.assertIn("none", set(skipped["SKU · produk · varian"]))

    def test_sales_priority_keeps_item_below_break_even_with_loss_noted(self):
        cands, skipped = F.candidates(pd.DataFrame([item("rugi", stok=100, harga=100_000, floor=120_000)]))
        row = cands.set_index("sku").loc["rugi"]
        self.assertGreaterEqual(row["diskon"], 5)
        self.assertEqual(row["margin_unit"], row["harga_flash"] - 120_000)
        self.assertIn("di bawah impas", row["alasan"])
        self.assertTrue(skipped.empty)

    def test_cancel_limit_relative_to_store(self):
        items = pd.DataFrame([item("a", stok=100, batal=30), item("b", stok=100, batal=30), item("c", stok=100, batal=70)])
        self.assertAlmostEqual(F.cancel_limit(items), 1.5 * 130 / 3, places=3)
        cands, skipped = F.candidates(items)
        self.assertEqual(set(cands["sku"]), {"a", "b"})
        self.assertTrue((cands["batas_beli"] == 1).all())


class ScheduleTest(unittest.TestCase):
    def test_always_scheduled_with_gap_and_dc_lead_time(self):
        items = pd.DataFrame([item(f"s{i}", stok=100, m_sales=1e6 - i) for i in range(6)] + [item("dc", stok=0, dc=100, m_sales=2e6)])
        cands, _ = F.candidates(items)
        today = date(2026, 11, 8)
        plan = F.schedule(cands, date(2026, 11, 9), today=today, days=14, per_day=2)
        self.assertEqual(plan.groupby("Tanggal").size().min(), 2)
        dc_days = plan.loc[plan["SKU"] == "dc", "Tanggal"]
        self.assertTrue((dc_days.map(lambda d: (d - today).days) >= F.TRANSFER_DAYS).all())
        for _sku, days in plan.groupby("SKU")["Tanggal"]:
            ordered = sorted(days)
            self.assertTrue(all((b - a).days >= F.MIN_GAP_DAYS for a, b in zip(ordered, ordered[1:])))
        moves = F.transfers(plan)
        self.assertEqual(set(moves["SKU"]), {"dc"})
        self.assertEqual(len(F.shopee_template(plan)), len(plan))

    def test_repeated_slots_share_stock(self):
        items = pd.DataFrame([item("dc", stok=0, dc=20, harian=5.0), item("site", stok=40, harian=2.0)])
        cands, _ = F.candidates(items)
        plan = F.schedule(cands, date(2026, 11, 12), today=date(2026, 11, 8), days=14, per_day=2)
        used = plan.groupby("SKU")["Kuota"].sum()
        self.assertLessEqual(used["dc"], 10)
        self.assertLessEqual(used["site"], 40 - 5 - 14)
        self.assertLessEqual(F.transfers(plan)["Unit transfer"].sum(), 10)


if __name__ == "__main__":
    unittest.main()


class BottomPriceTest(unittest.TestCase):
    def test_flash_price_never_below_bottom(self):
        import pandas as pd

        from src.core import flash_sale as F
        items = pd.DataFrame([
            {"sku": "1", "label": "A", "nama": "A", "harga": 1_000_000, "stok": 100, "ada_stok": True, "ss": 5, "harian": 1, "dc": 0, "terjual": 10,
             "m_sales": 1e6, "batal_pct": 0, "floor": 500_000, "momentum": 0, "bottom": 950_000},
            {"sku": "2", "label": "B", "nama": "B", "harga": 1_000_000, "stok": 100, "ada_stok": True, "ss": 5, "harian": 1, "dc": 0, "terjual": 10,
             "m_sales": 1e6, "batal_pct": 0, "floor": 500_000, "momentum": 0, "bottom": 1_100_000},
        ])
        cands, skipped = F.candidates(items)
        row = cands.set_index("sku").loc["1"]
        self.assertGreaterEqual(row["harga_flash"], 950_000)
        self.assertNotIn("2", set(cands["sku"]))
        self.assertTrue(skipped["Alasan"].str.contains("bottom price").any())


class FlashOfferTest(unittest.TestCase):
    def test_charm_and_strategy(self):
        from src.core import flash_sale as F
        self.assertEqual(F.charm_price(61_234), 60_900)
        self.assertEqual(F.charm_price(189_000, up=True), 189_900)
        self.assertEqual(F.charm_price(1_250_000), 1_199_000)
        # harga 1 jt, transaksi terendah 880 rb → flash di bawahnya, tidak di bawah bottom 800 rb
        price, disc, why = F.flash_offer(1_000_000, purpose=F.DRIVER, floor=700_000, bottom=800_000, low=880_000)
        self.assertLess(price, 880_000)
        self.assertGreaterEqual(price, 800_000)
        self.assertIn("terendah", why)
        # bottom mengikat
        price, disc, why = F.flash_offer(1_000_000, purpose=F.DRIVER, floor=700_000, bottom=930_000)
        self.assertGreaterEqual(price, 930_000)
        self.assertIn("bottom", why)
        self.assertIsNone(F.flash_offer(100_000, purpose=F.DRIVER, floor=99_000, bottom=float("nan")))

    def test_cheap_items_become_hook_and_require_bottom(self):
        from src.core import flash_sale as F
        items = pd.DataFrame([item("murah", stok=100, harga=50_000, floor=30_000), item("nobottom", stok=100)])
        items["bottom"] = [40_000, float("nan")]
        cands, skipped = F.candidates(items, require_bottom=True)
        self.assertEqual(cands.set_index("sku").loc["murah", "tujuan"], F.HOOK)
        self.assertIn("Tidak ada bottom price MD", set(skipped["Kelompok"]))


class ViralScoreTest(unittest.TestCase):
    def test_viral_cues(self):
        from src.core.exposure import viral_score
        high, hits = viral_score("Lampu LED Buy 3 Get 1 Free Hemat Listrik", "", 29_000)
        low, _ = viral_score("Baut 8mm", "", 2_000_000)
        self.assertGreaterEqual(high, 0.5)
        self.assertIn("demo visual", hits)
        self.assertLess(low, 0.5)
