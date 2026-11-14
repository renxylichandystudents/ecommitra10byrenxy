import unittest
from datetime import date

import pandas as pd

from src.core import harga_beli as H
from src.core import pricing as P
from src.core import shopee_fee as fee


class PricingTest(unittest.TestCase):
    def test_plan_keeps_promo_above_healthy_price(self):
        inp = fee.Inputs(harga=1_000_000, admin_pct=8.0, hpp=600_000, iklan=50_000)
        out = P.plan(inp, normal=1_100_000, target_pct=5.0, hist_disc=20.0)
        self.assertGreaterEqual(out["harga_promo"], out["harga_sehat"] - 100)
        self.assertGreater(out["harga_sehat"], out["harga_impas"])
        self.assertGreaterEqual(out["margin_promo_pct"], 5.0 - 0.2)
        self.assertLessEqual(out["promo_pct"], 20.0)

    def test_plan_raises_price_when_normal_loses(self):
        inp = fee.Inputs(harga=500_000, admin_pct=8.0, hpp=480_000)
        out = P.plan(inp, normal=500_000, target_pct=3.0, hist_disc=10.0)
        self.assertGreater(out["harga_disarankan"], 500_000)
        self.assertGreaterEqual(out["harga_disarankan"], out["harga_impas"])
        self.assertIn("naikkan", out["catatan"])
        _v, pct = fee.margin(fee.Inputs(harga=out["harga_promo"], admin_pct=8.0, hpp=480_000))
        self.assertGreaterEqual(pct, 0)

    def test_unknown_cost(self):
        out = P.plan(fee.Inputs(harga=100_000), normal=100_000, target_pct=5, known=False)
        self.assertIn("modal belum diketahui", out["catatan"])

    def test_price_history(self):
        orders = pd.DataFrame({"order_time": pd.to_datetime(["2026-11-01", "2026-11-05", "2026-11-10"]), "sku": ["1", "1", "1"],
                               "list_price": [100_000, 100_000, 110_000], "net_price": [80_000, 90_000, 99_000], "status": ["Selesai"] * 3})
        h = P.price_history(orders, ref=date(2026, 11, 12)).set_index("sku")
        self.assertEqual(h.loc["1", "harga_awal"], 110_000)
        self.assertAlmostEqual(h.loc["1", "diskon_maks"], 20.0)
        self.assertAlmostEqual(h.loc["1", "diskon_median"], 10.0)
        self.assertAlmostEqual(h.loc["1", "porsi_promo"], 100.0)


class HargaBeliParseTest(unittest.TestCase):
    def test_parse_marketplace_sheet(self):
        raw = pd.DataFrame([
            ["Promo On Line", None, None, None, None, None, None, None, None, None, None, None, None],
            ["Periode : ", "Q4 OKT - DES", None, None, None, None, None, None, None, None, None, None, None],
            ["Category Name", "Item No", "Item Name", "Variasi", "Campaign", "H.Beli (JBD)", "H.Jual (10037)", "% Promo Offline (JBD/NAS)",
             "H.Jual NETT (10037)", "Margin Promo (10037)", "Bottom Price (Marketplace)", "ZONA / AREA BERLAKU", "Keterangan"],
            ["APPLIANCES", "01100008723", "Air Purifier", None, None, 2971961.73, 6187000, 30.7, 4284693.9, 0.3, 4184693.9, "NASIONAL", None],
            ["APPLIANCES", "1100008724", "Kosong", None, None, None, 100000, None, None, None, None, "NASIONAL", None],
        ])
        items, periode = H.parse_sheet(raw)
        self.assertEqual(periode, "Q4 OKT - DES")
        row = items.set_index("sku").loc["1100008723"]
        self.assertAlmostEqual(row["harga_beli"], 2971961.73)
        self.assertAlmostEqual(row["bottom_price"], 4184693.9)
        self.assertTrue(pd.isna(items.set_index("sku").loc["1100008724", "harga_beli"]))
        self.assertAlmostEqual(H.margin_pct(4284693.9, 2971961.73), 30.64, places=1)


if __name__ == "__main__":
    unittest.main()
