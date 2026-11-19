"""Pantauan campaign: TACoS MTD vs sejak, dompet budget, split plan, checkpoint harian."""

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
        _frame, summary = A.evaluate(base, now, {"produk:1": 100_000, "produk:2": 0}, target_roas=8)
        self.assertEqual(summary["iklan_aktif_rencana"], 1)
        self.assertAlmostEqual(summary["biaya_harian"], 100_000, delta=1)


class TacosSalesProdukTest(unittest.TestCase):
    def test_tacos_versus_produk_and_bersih(self):
        s = {"periode_target": "2026-11", "data_sampai": "2026-11-13", "hari_sisa": 17, "mtd": 1_600.0, "mtd_produk": 2_000.0,
             "terpakai": 130.0, "proyeksi": 5_000.0, "proyeksi_tanpa": 3_400.0, "budget_harian": 60.0}
        out = M.plan_track(s, mtd=2_200.0, last=date(2026, 11, 16), spent=310.0, periode="2026-11", mtd_produk=2_800.0)
        self.assertAlmostEqual(out["produk_baru"], 800.0)
        self.assertAlmostEqual(out["sales_baru"], 600.0)
        self.assertAlmostEqual(out["tacos"], 180.0 / 800.0 * 100)
        self.assertAlmostEqual(out["tacos_bersih"], 180.0 / 600.0 * 100)
        self.assertNotAlmostEqual(out["tacos"], out["tacos_bersih"])
        self.assertFalse(out["produk_est"])

    def test_produk_baru_without_mtd_produk_not_full_mtd(self):
        """Rencana lama tanpa mtd_produk: jangan pakai MTD penuh sebagai sejak campaign."""
        s = {"periode_target": "2026-11", "data_sampai": "2026-11-13", "hari_sisa": 17, "mtd": 1_600.0,
             "terpakai": 130.0, "proyeksi": 5_000.0, "proyeksi_tanpa": 3_400.0, "budget_harian": 60.0}
        # mtd_produk sekarang 2800 (= MTD penuh); delta bersih = 600 → taksiran produk = 600/0.8 = 750
        out = M.plan_track(s, mtd=2_200.0, last=date(2026, 11, 16), spent=310.0, periode="2026-11",
                           mtd_produk=2_800.0, factor=0.8)
        self.assertTrue(out["produk_est"])
        self.assertAlmostEqual(out["produk_baru"], 600.0 / 0.8)
        self.assertNotAlmostEqual(out["produk_baru"], 2_800.0)
        self.assertAlmostEqual(out["tacos"], 180.0 / (600.0 / 0.8) * 100)

    def test_period_sales_helper_shows_both_tacos(self):
        from src.ui.ads_monitor_view import _period_sales

        track = {"status": "On track", "biaya_baru": 180.0, "produk_baru": 800.0, "sales_baru": 600.0,
                 "tacos_bersih": 180.0 / 600.0 * 100, "produk_est": False}
        out = _period_sales(track, factor=0.8)
        self.assertAlmostEqual(out["produk"], 800.0)
        self.assertAlmostEqual(out["bersih"], 600.0)
        self.assertAlmostEqual(out["tacos_produk"], 180.0 / 800.0 * 100)
        self.assertAlmostEqual(out["tacos_bersih"], 180.0 / 600.0 * 100)


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


class PlanSplitAndHistoryTest(unittest.TestCase):
    def test_sort_by_omzet_descending(self):
        frame = pd.DataFrame([
            {"_key": "a", "Omzet iklan sejak disimpan": 100},
            {"_key": "b", "Omzet iklan sejak disimpan": 500},
            {"_key": "c", "Omzet iklan sejak disimpan": 200},
        ])
        out = Mon.sort_by_omzet(frame)
        self.assertEqual(list(out["_key"]), ["b", "c", "a"])

    def test_complete_plan_adds_missing_keys(self):
        classified = pd.DataFrame([{
            "_key": "produk:1", "Iklan": "A", "Jenis": "Produk tunggal",
            "Budget usulan/hari": 50_000, "Budget efektif Shopee/hari": 50_000,
            "Biaya aktual/hari": 50_000, "Omzet iklan aktual/hari": 500_000,
            "Biaya sejak disimpan": 100_000, "Omzet iklan sejak disimpan": 1_000_000,
            "ROAS aktual": 10.0, "Rekomendasi dijalankan": "Ya",
        }])
        classified = Mon.classify_rows(classified, target_roas=8)
        out = Mon.complete_plan_rows(
            classified, {"produk:1": 50_000, "produk:2": 25_000},
            names={"produk:2": ("B", "Produk tunggal")}, target_roas=8,
        )
        keys = set(out["_key"].astype(str))
        self.assertIn("produk:1", keys)
        self.assertIn("produk:2", keys)

    def test_split_out_of_plan(self):
        base = {
            "produk:1": {"periode": "2026-11-01", "hari": 5, "biaya": 100_000, "omzet": 1_000_000},
            "produk:9": {"periode": "2026-11-01", "hari": 5, "biaya": 50_000, "omzet": 200_000},
        }
        now = {
            "produk:1": {"periode": "2026-11-01", "hari": 7, "biaya": 300_000, "omzet": 3_000_000},
            "produk:9": {"periode": "2026-11-01", "hari": 7, "biaya": 250_000, "omzet": 800_000},
        }
        planned = {"produk:1": 100_000}
        frame, _ = A.evaluate(base, now, planned, target_roas=10, jenis={"produk:1": "Produk tunggal"})
        frame.insert(1, "Iklan", "A")
        classified = Mon.classify_rows(frame, target_roas=10)
        in_plan, out_plan = Mon.split_in_out_plan(
            classified, planned, now, base,
            names={"produk:1": ("A", "Produk tunggal"), "produk:9": ("Luar", "Produk tunggal")},
            kinds={"produk:1": "Produk tunggal", "produk:9": "Produk tunggal"},
            target_roas=10,
        )
        self.assertTrue((in_plan["_key"] == "produk:1").any())
        self.assertTrue((out_plan["_key"] == "produk:9").any())
        self.assertFalse((in_plan["_key"] == "produk:9").any())

    def test_checkpoint_and_history(self):
        campaign = {"id": 1, "setelan": {"data_sampai": "2026-11-13"}}
        rows = pd.DataFrame([{
            "_key": "produk:1", "Iklan": "A",
            "Biaya sejak disimpan": 100_000, "Omzet iklan sejak disimpan": 1_500_000,
            "Biaya aktual/hari": 50_000, "Budget usulan/hari": 50_000,
            "Budget efektif Shopee/hari": 50_000, "Tindakan": "Pertahankan",
        }])
        updated, changed = Mon.record_daily_checkpoint(campaign, report_date=date(2026, 11, 17), rows=rows)
        self.assertTrue(changed)
        self.assertEqual(len(updated["pantau_harian"]), 1)
        again, changed2 = Mon.record_daily_checkpoint(updated, report_date=date(2026, 11, 17), rows=rows)
        self.assertFalse(changed2)
        hist = Mon.daily_history_for(
            again, "produk:1",
            baseline_row={"tanggal": "2026-11-13", "budget_plan": 50_000, "budget_setup": 50_000},
            today_row=None,
        )
        self.assertGreaterEqual(len(hist), 1)
        self.assertEqual(hist.iloc[-1]["Tanggal"], "2026-11-17")

    def test_rename_budget_triad(self):
        frame = pd.DataFrame([{
            "Budget usulan/hari": 1, "Budget efektif Shopee/hari": 2,
            "Biaya bulan ini/hari": 4, "Biaya aktual/hari": 3,
        }])
        out = Mon.rename_budget_triad(frame)
        self.assertIn("Budget di rencana/hari", out.columns)
        self.assertIn("Budget di Shopee/hari", out.columns)
        self.assertIn("Terpakai bulan ini/hari", out.columns)
        self.assertIn("Terpakai sejak campaign/hari", out.columns)

    def test_attach_month_daily_differs_from_since_campaign(self):
        frame = pd.DataFrame([{
            "_key": "produk:1", "Biaya aktual/hari": 50_000,  # sejak campaign
        }])
        current = {"produk:1": {"periode": "2026-11-01", "hari": 10, "biaya": 1_000_000, "omzet": 5_000_000}}
        out = Mon.attach_month_daily(frame, current)
        self.assertAlmostEqual(out.iloc[0]["Biaya bulan ini/hari"], 100_000)
        self.assertAlmostEqual(out.iloc[0]["Biaya aktual/hari"], 50_000)


if __name__ == "__main__":
    unittest.main()
