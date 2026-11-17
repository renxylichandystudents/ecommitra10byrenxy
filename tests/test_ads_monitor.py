"""Pantauan campaign: minimum Shopee, klasifikasi goals, strategi minggu depan."""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from src.core import ads_monitor as Mon
from src.core import ads_strategy as A
from src.core import campaigns as C


class SellerMinBudgetTest(unittest.TestCase):
    def test_single_and_group_floors(self):
        self.assertEqual(A.seller_min_budget("Produk tunggal"), 25_000)
        self.assertEqual(A.seller_min_budget("produk:1"), 25_000)
        self.assertEqual(A.seller_min_budget("Grup"), 100_000)
        self.assertEqual(A.seller_min_budget("grup:Kloset"), 100_000)

    def test_implementable_raises_to_shopee_min(self):
        self.assertEqual(A.implementable_budget(10_000, "Produk tunggal"), 25_000)
        self.assertEqual(A.implementable_budget(50_000, "Grup"), 100_000)
        self.assertEqual(A.implementable_budget(150_000, "Grup"), 150_000)
        self.assertEqual(A.implementable_budget(0, "Grup"), 0.0)


class EvaluateSellerFloorTest(unittest.TestCase):
    def test_group_at_shopee_min_counts_as_applied(self):
        """Usulan 50 rb grup → di Seller Center jadi 100 rb; aktual 100 rb = sesuai, bukan 'Belum'."""
        base = {"grup:A": {"periode": "2026-11-01", "hari": 5, "biaya": 250_000, "omzet": 2_500_000}}
        now = {"grup:A": {"periode": "2026-11-01", "hari": 7, "biaya": 450_000, "omzet": 4_500_000}}
        # 2 hari baru × 100 rb = 200 rb tambahan biaya
        frame, summary = A.evaluate(base, now, {"grup:A": 50_000}, target_roas=8, jenis={"grup:A": "Grup"})
        self.assertEqual(frame.iloc[0]["Rekomendasi dijalankan"], "Ya")
        self.assertEqual(frame.iloc[0]["Status pelaksanaan"], "Sesuai (batas Shopee)")
        self.assertEqual(frame.iloc[0]["Budget efektif Shopee/hari"], 100_000)
        self.assertEqual(summary["dijalankan"], 1)
        self.assertEqual(summary["batas_shopee"], 1)

    def test_single_below_min_expected_is_25k(self):
        base = {"produk:1": {"periode": "2026-11-01", "hari": 5, "biaya": 50_000, "omzet": 500_000}}
        now = {"produk:1": {"periode": "2026-11-01", "hari": 6, "biaya": 75_000, "omzet": 800_000}}
        frame, _ = A.evaluate(base, now, {"produk:1": 15_000}, target_roas=8)
        self.assertEqual(frame.iloc[0]["Budget efektif Shopee/hari"], 25_000)
        self.assertEqual(frame.iloc[0]["Rekomendasi dijalankan"], "Ya")


class CompareBudgetsFloorTest(unittest.TestCase):
    def test_group_floor_not_flagged_as_changed(self):
        saved = pd.DataFrame({"Iklan": ["Grup Kloset"], "Jenis": ["Grup"], "Budget harian usulan": [50_000]})
        fresh = pd.DataFrame({"Iklan": ["Grup Kloset"], "Jenis": ["Grup"], "Budget harian usulan": [100_000]})
        diff = C.compare_budgets(saved, fresh).set_index("Iklan")
        self.assertFalse(bool(diff.loc["Grup Kloset", "Berubah"]))


class ClassifyAndWeekTest(unittest.TestCase):
    def test_classify_and_priority(self):
        frame = pd.DataFrame([{
            "_key": "produk:1", "Iklan": "Lem", "Jenis": "Produk tunggal", "Hari dievaluasi": 2,
            "Budget usulan/hari": 100_000, "Budget efektif Shopee/hari": 100_000,
            "Biaya aktual/hari": 30_000, "Omzet iklan aktual/hari": 200_000, "ROAS aktual": 6.7,
            "Rekomendasi dijalankan": "Belum", "Catatan batas": "",
        }])
        out = Mon.classify_rows(frame, target_roas=10)
        self.assertEqual(out.iloc[0]["Tindakan"], "Naikkan budget")
        acts = Mon.priority_actions(out)
        self.assertEqual(len(acts), 1)

    def test_next_week_skips_empty_stock(self):
        products = pd.DataFrame([
            {"product_code": "1", "nama": "Kosong", "omzet_harian": 2_000_000, "qty_harian": 5, "stok": 0, "stok_room": 0},
            {"product_code": "2", "nama": "Laris", "omzet_harian": 1_800_000, "qty_harian": 4, "stok": 40, "stok_room": 1e6},
        ])
        week = Mon.next_week_strategy(products, None, None, target_roas=8, daily_budget_room=200_000, limit=10)
        self.assertTrue((week["Kode produk"] == "1").any())
        row = week.set_index("Kode produk").loc["1"]
        self.assertIn("Jangan", row["Keputusan"])

    def test_rollup_ok_when_mostly_applied(self):
        classified = pd.DataFrame([{"Tindakan": "Pertahankan", "Iklan": "A", "Jenis": "Produk tunggal",
                                    "Saran": "ok", "Biaya aktual/hari": 1, "Budget efektif Shopee/hari": 1, "ROAS aktual": 12}])
        summary = {"iklan": 10, "dijalankan": 9, "roas": 12.0, "batas_shopee": 2}
        v = Mon.rollup(classified, summary, track={"status": "On track"}, target_roas=10)
        self.assertEqual(v["level"], "ok")


class WeekWindowTest(unittest.TestCase):
    def test_returns_seven_days(self):
        a, b = Mon.week_window(date(2026, 11, 17))  # Selasa
        self.assertEqual((b - a).days, 6)


if __name__ == "__main__":
    unittest.main()
