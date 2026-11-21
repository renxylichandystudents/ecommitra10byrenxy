import unittest
from datetime import date

import pandas as pd

from src.core import exposure as E


def item(sku, name, *, m_sales, stok=100, ss=5, harian=1.0, dc=0, momentum=0.0, klik=0, sold_ads=0, ada_stok=True):
    return {"sku": sku, "label": f"{sku} · {name}", "nama": name, "harga": 500_000, "harian": harian, "m_sales": m_sales, "stok": stok, "ada_stok": ada_stok,
            "ss": ss, "dc": dc, "terjual": 5, "momentum": momentum, "margin_pct": 15.0, "klik": klik, "terjual_iklan": sold_ads, "poin_deskripsi": []}


class PickTest(unittest.TestCase):
    def test_segments_and_stock_gate(self):
        items = pd.DataFrame([
            item("hero", "Kloset Duduk Tidy Garansi 15 Tahun [INCLUDE PACKING KAYU]", m_sales=9e8, stok=60, harian=3),
            item("rise", "Lem Silicone Sealant 300ml", m_sales=1e7, stok=60, harian=2, momentum=0.8),
            item("slow", "Rak Dinding Tanpa Bor", m_sales=1e6, stok=200, harian=0.5),
            item("empty", "Water Heater 15L", m_sales=8e8, stok=2, harian=3, dc=0),
        ])
        cands, delayed = E.pick(items)
        seg = dict(zip(cands["sku"], cands["segmen"]))
        self.assertEqual(seg["hero"], E.HERO)
        self.assertEqual(seg["rise"], E.RISING)
        self.assertEqual(seg["slow"], E.OVERSTOCK)
        self.assertNotIn("empty", seg)
        self.assertEqual(len(delayed), 1)
        points = cands.set_index("sku").loc["hero", "poin"]
        self.assertIn("Garansi 15 tahun", points)
        self.assertIn("Dikirim dengan packing kayu, aman sampai rumah", points)

    def test_dc_stock_counts_as_ready(self):
        cands, _ = E.pick(pd.DataFrame([item("dc", "Kloset Tidy", m_sales=9e8, stok=1, harian=3, dc=500)]))
        self.assertEqual(list(cands["sku"]), ["dc"])

    def test_broken_description_fragments_dropped(self):
        points = E.selling_points("Wastafel", ["hung hemat ruang)", "Model wall hung hemat ruang, ideal untuk kamar mandi kecil"])
        self.assertEqual(points, ["Model wall hung hemat ruang, ideal untuk kamar mandi kecil"])


class CalendarTest(unittest.TestCase):
    def test_weekly_schedule_uses_category_peak_and_no_repeat(self):
        items = pd.DataFrame([item(f"k{i}", f"Kloset Tidy {i}", m_sales=1e8 - i) for i in range(6)])
        cands, _ = E.pick(items)
        orders = pd.DataFrame({"sku": ["k0"] * 40, "order_time": pd.date_range("2026-11-04 10:00", periods=40, freq="7D")})
        times = E.timing(orders, {f"k{i}": "Kloset" for i in range(6)})
        self.assertEqual(times["Kloset"][0], 2)
        plan = E.calendar(cands, date(2026, 11, 9), weeks=2, per_week=3, times=times)
        self.assertEqual(len(plan), 6)
        self.assertLessEqual(plan.groupby("Tanggal").size().max(), 2)
        self.assertEqual(plan["SKU"].nunique(), 6)
        self.assertTrue(plan["Naskah 30 dtk"].str.contains("keranjang kuning").all())
        self.assertTrue((plan["Caption"].str.len() > 20).all())
        self.assertTrue(plan["Hook"].str.contains("Kloset|Tidy|ragu", case=False, regex=True).all())

    def test_max_per_day_allows_more_than_two_without_weekly_cap(self):
        items = pd.DataFrame([item(f"k{i}", f"Kloset Tidy Garansi 10 Tahun {i}", m_sales=1e8 - i * 1e5) for i in range(20)])
        cands, _ = E.pick(items)
        start, end = date(2026, 11, 16), date(2026, 11, 18)  # 3 hari
        plan = E.calendar(cands, start, end=end, max_per_day=5)
        self.assertGreater(len(plan), 6)  # lebih dari plafon lama 2/hari × 3
        self.assertLessEqual(plan.groupby("Tanggal").size().max(), 5)
        self.assertEqual(plan["SKU"].nunique(), len(plan))

    def test_period_bounds_day_week_month(self):
        d = date(2026, 11, 21)  # Sabtu
        self.assertEqual(E.period_bounds(d, E.HORIZON_DAY), (d, d))
        mon, sun = E.period_bounds(d, E.HORIZON_WEEK)
        self.assertEqual(mon.weekday(), 0)
        self.assertEqual((sun - mon).days, 6)
        first, last = E.period_bounds(d, E.HORIZON_MONTH)
        self.assertEqual(first, date(2026, 11, 1))
        self.assertEqual(last, date(2026, 11, 30))

    def test_brief_caption_mentions_product_and_hashtags(self):
        row = {
            "nama": "Kloset Toilet WC Duduk Tidy FSA0040 Garansi 15 Tahun",
            "label": "FSA0040 · Kloset Toilet WC Duduk Tidy",
            "segmen": E.HERO, "harga": 1_200_000,
            "poin": ["Garansi 15 tahun", "Dikirim dengan packing kayu, aman sampai rumah"],
        }
        b = E.brief(row)
        self.assertIn("Tidy", b["Hook"] + b["Caption"])
        self.assertIn("#mitra10", b["Hashtag"])
        self.assertIn("keranjang", b["Ajakan"].lower())
        self.assertGreater(len(b["Caption"]), 40)
        self.assertNotEqual(b["Hook"], E.play_for(row["nama"])[4])  # hook dipersonalisasi, bukan template mentah saja


if __name__ == "__main__":
    unittest.main()
