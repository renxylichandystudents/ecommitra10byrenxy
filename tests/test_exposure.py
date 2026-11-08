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


if __name__ == "__main__":
    unittest.main()
