"""Laporan v2: angka bersih konsisten, analisa SWOT/fishbone dari data, visual, dan snapshot JSON."""

import json
import unittest
from datetime import date

import numpy as np
import pandas as pd

from src.core import report_analysis as RA
from src.core import report_data as R
from src.core.metrics import order_metrics, sales_bridge
from src.ui import report_visuals as V


def _orders():
    rows = []
    for i, (status, qty, ret, price, amount) in enumerate([
        ("Selesai", 2, 0, 100_000, 190_000), ("Selesai", 1, 1, 50_000, 0), ("Batal", 3, 0, 80_000, 240_000),
        ("Selesai", 4, 1, 25_000, 80_000), ("Selesai", 1, 0, 300_000, 290_000)]):
        rows.append({"order_time": pd.Timestamp("2026-10-05") + pd.Timedelta(days=i), "product_name": f"P{i % 3}", "sku": f"S{i % 3}",
                     "gross_qty": qty, "returned_qty": ret, "qty": qty - ret, "gross_sales": qty * price, "sales": (qty - ret) * price,
                     "status": status, "order_id": f"O{i}", "order_amount": amount, "cancel_reason": "Perlu mengubah pesanan" if status == "Batal" else "",
                     "buyer": f"b{i}", "item_key": f"S{i % 3}", "net_price": price, "seller_voucher": 0.0, "shopee_voucher": 10_000.0,
                     "coin_deduction": 0.0, "card_discount": 0.0, "buyer_shipping": 0.0})
    return pd.DataFrame(rows)


class NetNumbersTest(unittest.TestCase):
    def test_top_products_sum_equals_sales_produk_bersih(self):
        frame = _orders()
        a, b = date(2026, 10, 1), date(2026, 10, 31)
        top = R.top_products(frame, a, b, R.previous_range(a, b), limit=100)
        bridge = sales_bridge(frame, a, b)
        facts = order_metrics(frame, a, b)
        self.assertAlmostEqual(float(top["Sales produk bersih"].sum()), bridge["sales_produk"])
        self.assertAlmostEqual(float(top["QTY bersih"].sum()), facts["qty_bersih"])
        self.assertAlmostEqual(float(top["Porsi (%)"].sum()), 100.0)

    def test_daily_sums_match_period(self):
        frame = _orders()
        daily = R.daily_orders(frame, date(2026, 10, 1), date(2026, 10, 31))
        facts = order_metrics(frame, "2026-10-01", "2026-10-31")
        self.assertAlmostEqual(float(daily["Sales bersih"].sum()), facts["sales_bersih"])
        self.assertAlmostEqual(float(daily["QTY bersih"].sum()), facts["qty_bersih"])


class AnalysisTest(unittest.TestCase):
    FACTS = dict(growth=-5.0, sales_bersih=1e9, target_pct=80.0, target_gap=2e8, cancel_pct=22.0, pesanan=1000, belum_bayar=150, roas=12.0,
                 target_roas=8.0, sku_rugi=3, rugi_rp=1e6, sku_rendah=4, acuan_pct=9.0, selisih_rp=2e6, rank_far=5, rank_cats=8, rank_down=2,
                 visitors_change=-12.0, conv=1.1, conv_prev=1.4, cancel_cats={"Pembeli": 300, "Penjual": 30, "Belum bayar": 200})

    def test_problem_statement(self):
        self.assertEqual(RA.problem_statement(self.FACTS), "Sales bersih turun 5,0%")
        self.assertIn("dari target", RA.problem_statement({"growth": 3.0, "target_pct": 90.0}))
        self.assertEqual(RA.problem_statement({}), "Hambatan pertumbuhan sales Shopee")

    def test_fishbone_has_six_bones_sorted_by_level(self):
        bones = RA.fishbone(self.FACTS)
        self.assertEqual(list(bones), list(RA.FISHBONE_BONES))
        order = {lvl: i for i, lvl in enumerate(RA.LEVELS)}
        for items in bones.values():
            self.assertLessEqual(len(items), RA.MAX_ITEMS)
            self.assertEqual([order[i["level"]] for i in items], sorted(order[i["level"]] for i in items))
        proses = " ".join(i["text"] for i in bones["Proses"])
        self.assertIn("22,0%", proses)
        self.assertIn("Batal oleh penjual: 30", proses)
        self.assertTrue(any(i["level"] == "masalah" for i in bones["Tempat / Saluran"]))

    def test_swot_only_from_given_numbers(self):
        out = RA.swot(self.FACTS)
        self.assertEqual(set(out), {"Strength", "Weakness", "Opportunity", "Threat"})
        self.assertTrue(any("ROAS iklan 12,0" in t for t in out["Strength"]))
        self.assertTrue(any("turun 5,0%" in t for t in out["Weakness"]))
        self.assertTrue(any("150 pesanan" in t for t in out["Opportunity"]))
        empty = RA.swot({})
        self.assertTrue(all(len(v) == 1 for v in empty.values()))

    def test_visuals_render(self):
        svg = V.fishbone_svg("Sales bersih turun 5,0%", RA.fishbone(self.FACTS))
        self.assertTrue(svg.startswith("<svg") and svg.endswith("</svg>"))
        for name in RA.FISHBONE_BONES:
            self.assertIn(name.upper().replace("&", "&amp;"), svg)
        page = V.swot_html(RA.swot(self.FACTS), subtitle="Okt 2026")
        for word in ("STRENGTHS", "WEAKNESSES", "OPPORTUNITIES", "THREATS"):
            self.assertIn(word, page)

    def test_snapshot_parts_roundtrip_json(self):
        snap = {"swot": RA.swot(self.FACTS), "analisa": {"masalah": "x", "tulang": RA.fishbone(self.FACTS)},
                "tabel": pd.DataFrame({"a": [1.0, np.nan], "b": ["x", "y"]})}
        back = R.from_json(json.loads(json.dumps(R.to_json(snap))))
        self.assertEqual(back["analisa"]["tulang"], snap["analisa"]["tulang"])
        self.assertEqual(list(back["tabel"].columns), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
