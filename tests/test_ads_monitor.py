"""Pantauan campaign: TACoS sales produk, dompet budget, item wajib iklan."""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from src.core import ads_monitor as Mon
from src.core import ads_month as M
from src.core import ads_strategy as A
from src.core import campaigns as C


class SellerMinBudgetTest(unittest.TestCase):
    def test_single_and_group_floors(self):
        self.assertEqual(A.seller_min_budget("Produk tunggal"), 25_000)
        self.assertEqual(A.seller_min_budget("grup:Kloset"), 100_000)
        self.assertEqual(A.implementable_budget(50_000, "Grup"), 100_000)


class EvaluateSellerFloorTest(unittest.TestCase):
    def test_group_at_shopee_min_counts_as_applied(self):
        base = {"grup:A": {"periode": "2026-11-01", "hari": 5, "biaya": 250_000, "omzet": 2_500_000}}
        now = {"grup:A": {"periode": "2026-11-01", "hari": 7, "biaya": 450_000, "omzet": 4_500_000}}
        frame, summary = A.evaluate(base, now, {"grup:A": 50_000}, target_roas=8, jenis={"grup:A": "Grup"})
        self.assertEqual(frame.iloc[0]["Rekomendasi dijalankan"], "Ya")
        self.assertEqual(frame.iloc[0]["Budget efektif Shopee/hari"], 100_000)
        self.assertAlmostEqual(frame.iloc[0]["Biaya sejak disimpan"], 200_000)
        self.assertEqual(summary["batas_shopee"], 1)
        self.assertIn("biaya_total", summary)

    def test_paused_plan_not_inflating_active_summary(self):
        base = {
            "produk:1": {"periode": "2026-11-01", "hari": 5, "biaya": 100_000, "omzet": 1_000_000},
            "produk:2": {"periode": "2026-11-01", "hari": 5, "biaya": 100_000, "omzet": 200_000},
        }
        now = {
            "produk:1": {"periode": "2026-11-01", "hari": 6, "biaya": 200_000, "omzet": 2_200_000},
            "produk:2": {"periode": "2026-11-01", "hari": 6, "biaya": 105_000, "omzet": 210_000},
        }
        # produk:2 dijeda (usulan 0); biaya kecil sisa tidak menggelembungkan ringkasan aktif
        _frame, summary = A.evaluate(base, now, {"produk:1": 100_000, "produk:2": 0}, target_roas=8)
        self.assertEqual(summary["iklan_aktif_rencana"], 1)
        self.assertAlmostEqual(summary["biaya_harian"], 100_000, delta=1)


class TacosSalesProdukTest(unittest.TestCase):
    def test_tacos_uses_product_sales_not_net(self):
        s = {"periode_target": "2026-11", "data_sampai": "2026-11-13", "hari_sisa": 17, "mtd": 1_600.0, "mtd_produk": 2_000.0,
             "terpakai": 130.0, "proyeksi": 5_000.0, "proyeksi_tanpa": 3_400.0, "budget_harian": 60.0}
        # 3 hari: sales bersih 2200 (+600), produk 2800 (+800), biaya 310 (+180)
        out = M.plan_track(s, mtd=2_200.0, last=date(2026, 11, 16), spent=310.0, periode="2026-11", mtd_produk=2_800.0)
        self.assertAlmostEqual(out["produk_baru"], 800.0)
        self.assertAlmostEqual(out["tacos"], 180.0 / 800.0 * 100)
        self.assertNotAlmostEqual(out["tacos"], 180.0 / 600.0 * 100)


class BudgetWalletTest(unittest.TestCase):
    def test_wallet_splits_total_used_remaining(self):
        w = Mon.budget_wallet({"budget_bulan": 162_000_000, "biaya_harian_rencana": 9_500_000, "roas": 22},
                              spent_month=40_000_000, spent_since=22_000_000, days_since=3, days_left_plan=14)
        self.assertEqual(w["budget_total"], 162_000_000)
        self.assertEqual(w["terpakai_bulan"], 40_000_000)
        self.assertEqual(w["sisa_bulan"], 122_000_000)
        self.assertEqual(w["jalur_sejak"], 9_500_000 * 3)


class MustAdvertiseTest(unittest.TestCase):
    def test_focuses_on_create_and_keep_not_jangan(self):
        products = pd.DataFrame([
            {"product_code": "1", "nama": "Kosong", "omzet_harian": 5_000_000, "stok": 0, "stok_room": 0},
            {"product_code": "2", "nama": "Laris", "omzet_harian": 4_000_000, "stok": 40, "stok_room": 1e6},
            {"product_code": "3", "nama": "Biasa", "omzet_harian": 100_000, "stok": 10, "stok_room": 1e6},
        ])
        classified = pd.DataFrame([{
            "_key": "produk:9", "Iklan": "Lem", "Jenis": "Produk tunggal",
            "Budget usulan/hari": 100_000, "Budget efektif Shopee/hari": 100_000,
            "Biaya aktual/hari": 100_000, "ROAS aktual": 25.0, "Rekomendasi dijalankan": "Ya",
        }])
        out = Mon.must_advertise(products, classified, None, [], target_roas=10, daily_budget_room=500_000, limit=12)
        self.assertTrue(len(out) >= 1)
        self.assertFalse(out["Keputusan"].astype(str).str.contains("Jangan", case=False).any())
        self.assertTrue(out["Keputusan"].astype(str).str.contains("Buat|Pertahankan", case=False).any())

    def test_selection_focus_limits_rows(self):
        sel = pd.DataFrame({
            "Kode produk": [str(i) for i in range(100)],
            "Saran": ["Sudah di iklan lain"] * 90 + ["Buat iklan tunggal"] * 10,
            "Prediksi omzet/hari": list(range(100)),
        })
        out = Mon.selection_focus(sel, limit=25)
        self.assertLessEqual(len(out), 25)
        self.assertTrue((out["Saran"] == "Buat iklan tunggal").sum() >= 1)


class CompareBudgetsFloorTest(unittest.TestCase):
    def test_group_floor_not_flagged_as_changed(self):
        saved = pd.DataFrame({"Iklan": ["Grup Kloset"], "Jenis": ["Grup"], "Budget harian usulan": [50_000]})
        fresh = pd.DataFrame({"Iklan": ["Grup Kloset"], "Jenis": ["Grup"], "Budget harian usulan": [100_000]})
        diff = C.compare_budgets(saved, fresh).set_index("Iklan")
        self.assertFalse(bool(diff.loc["Grup Kloset", "Berubah"]))


if __name__ == "__main__":
    unittest.main()
