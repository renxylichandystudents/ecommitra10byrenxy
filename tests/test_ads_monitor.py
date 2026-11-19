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

    def test_split_filters_stray_classified_and_alias(self):
        # classified keliru memuat produk luar → harus dibuang dari in_plan
        classified = pd.DataFrame([
            {"_key": "produk:1", "Iklan": "A", "Jenis": "Produk tunggal",
             "Budget usulan/hari": 100_000, "Budget efektif Shopee/hari": 100_000,
             "Biaya aktual/hari": 100_000, "Omzet iklan aktual/hari": 1_000_000,
             "Biaya sejak disimpan": 200_000, "Omzet iklan sejak disimpan": 2_000_000,
             "ROAS aktual": 10.0, "Rekomendasi dijalankan": "Ya"},
            {"_key": "produk:9", "Iklan": "Luar", "Jenis": "Produk tunggal",
             "Budget usulan/hari": 0, "Budget efektif Shopee/hari": 0,
             "Biaya aktual/hari": 80_000, "Omzet iklan aktual/hari": 100_000,
             "Biaya sejak disimpan": 160_000, "Omzet iklan sejak disimpan": 200_000,
             "ROAS aktual": 1.25, "Rekomendasi dijalankan": "Belum"},
        ])
        classified = Mon.classify_rows(classified, target_roas=10)
        base = {
            "produk:1": {"periode": "2026-11-01", "hari": 5, "biaya": 100_000, "omzet": 1_000_000},
            "produk:9": {"periode": "2026-11-01", "hari": 5, "biaya": 50_000, "omzet": 200_000},
            "produk:55": {"periode": "2026-11-01", "hari": 5, "biaya": 10_000, "omzet": 50_000},
        }
        now = {
            "produk:1": {"periode": "2026-11-01", "hari": 7, "biaya": 300_000, "omzet": 3_000_000},
            "produk:9": {"periode": "2026-11-01", "hari": 7, "biaya": 250_000, "omzet": 800_000},
            "produk:55": {"periode": "2026-11-01", "hari": 7, "biaya": 100_000, "omzet": 500_000},
        }
        # pisah:55 di rencana → produk:55 tidak boleh jadi luar rencana
        planned = {"produk:1": 100_000, "pisah:55": 50_000}
        in_plan, out_plan = Mon.split_in_out_plan(
            classified, planned, now, base,
            names={"produk:1": ("A", "Produk tunggal"), "pisah:55": ("Pisah", "Produk tunggal"),
                   "produk:9": ("Luar", "Produk tunggal")},
            kinds={"produk:1": "Produk tunggal", "pisah:55": "Produk tunggal", "produk:9": "Produk tunggal"},
            target_roas=10,
        )
        self.assertEqual(set(in_plan["_key"].astype(str)), {"produk:1", "pisah:55"})
        self.assertTrue((out_plan["_key"] == "produk:9").any())
        self.assertFalse((out_plan["_key"] == "produk:55").any())

    def test_partition_plan_rows(self):
        frame = pd.DataFrame([
            {"_key": "a", "Tindakan": "Buat / aktifkan", "Omzet iklan sejak disimpan": 0},
            {"_key": "b", "Tindakan": "Jeda / hentikan", "Omzet iklan sejak disimpan": 100},
            {"_key": "c", "Tindakan": "Turunkan budget", "Omzet iklan sejak disimpan": 500},
            {"_key": "d", "Tindakan": "Pertahankan", "Omzet iklan sejak disimpan": 300},
        ])
        parts = Mon.partition_plan_rows(frame)
        self.assertEqual(list(parts["belum_setup"]["_key"]), ["a"])
        self.assertEqual(list(parts["jeda_tertinggal"]["_key"]), ["b"])
        self.assertEqual(list(parts["pantau"]["_key"]), ["c", "d"])

    def test_checkpoint_and_history(self):
        campaign = {"id": 1, "setelan": {"data_sampai": "2026-11-13"}}
        rows = pd.DataFrame([{
            "_key": "produk:1", "Iklan": "A",
            "Biaya sejak disimpan": 100_000, "Omzet iklan sejak disimpan": 1_500_000,
            "Biaya aktual/hari": 50_000, "Biaya bulan ini/hari": 80_000,
            "Budget usulan/hari": 50_000, "Budget efektif Shopee/hari": 50_000, "Tindakan": "Pertahankan",
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
        self.assertIn("Total biaya sejak campaign", hist.columns)
        self.assertIn("Rata-rata terpakai bulan ini", hist.columns)
        self.assertAlmostEqual(hist.iloc[-1]["Rata-rata terpakai bulan ini"], 80_000)

    def test_history_shows_day_delta_and_mtd_separate(self):
        campaign = {
            "pantau_harian": [
                {"tanggal": "2026-11-18", "items": [{
                    "key": "produk:1", "biaya": 78_521_003, "omzet": 1_538_347_407, "roas": 19.59,
                    "biaya_hari": 19_630_251, "biaya_bulan_hari": 18_000_000,
                    "budget_plan": 4_750_000, "budget_setup": 4_750_000, "tindakan": "Turunkan budget",
                }]},
                {"tanggal": "2026-11-19", "items": [{
                    "key": "produk:1", "biaya": 87_686_532, "omzet": 1_716_947_237, "roas": 19.58,
                    "biaya_hari": 17_537_306, "biaya_bulan_hari": 17_000_000,
                    "budget_plan": 4_750_000, "budget_setup": 4_750_000, "tindakan": "Turunkan budget",
                }]},
            ]
        }
        hist = Mon.daily_history_for(campaign, "produk:1")
        self.assertEqual(len(hist), 2)
        self.assertTrue(pd.isna(hist.iloc[0]["Tambahan biaya hari ini"]))  # baris pertama: belum ada selisih
        self.assertAlmostEqual(hist.iloc[1]["Tambahan biaya hari ini"], 87_686_532 - 78_521_003)
        self.assertAlmostEqual(hist.iloc[1]["Total biaya sejak campaign"], 87_686_532)
        self.assertAlmostEqual(hist.iloc[1]["Rata-rata terpakai sejak campaign"], 17_537_306)
        self.assertAlmostEqual(hist.iloc[1]["Rata-rata terpakai bulan ini"], 17_000_000)
        self.assertNotIn("Actual pemakaian/hari", hist.columns)

    def test_group_members_review_flags_weak_and_strong(self):
        members = pd.DataFrame([
            {"unit": "grup:G1", "periode": "2026-11", "product_code": "A", "nama": "Andalan",
             "biaya": 50_000, "omzet": 1_200_000, "terjual": 10},
            {"unit": "grup:G1", "periode": "2026-11", "product_code": "B", "nama": "Lemah",
             "biaya": 40_000, "omzet": 40_000, "terjual": 1},
            {"unit": "grup:G1", "periode": "2026-11", "product_code": "C", "nama": "Mati",
             "biaya": 30_000, "omzet": 0, "terjual": 0},
            {"unit": "grup:G1", "periode": "2026-11", "product_code": "D", "nama": "Biasa",
             "biaya": 20_000, "omzet": 400_000, "terjual": 5},
        ])
        # target 22 → A ROAS 24 kuat + porsi besar; B ROAS 1 lemah; C tanpa omzet; D ROAS 20 hampir target
        out = Mon.group_members_review(members, "grup:G1", target_roas=22.0)
        self.assertEqual(len(out), 4)
        by = out.set_index("Kode produk")["Tindakan"].to_dict()
        self.assertEqual(by["C"], "Keluarkan dari grup")
        self.assertEqual(by["B"], "Keluarkan dari grup")
        self.assertEqual(by["A"], "Pisahkan jadi iklan tunggal")
        self.assertEqual(by["D"], "Pertahankan di grup")
        tip = Mon.group_members_summary(out)
        self.assertIn("dikeluarkan", tip)
        self.assertIn("andalan", tip.lower())

    def test_group_members_review_empty_for_single(self):
        members = pd.DataFrame([
            {"unit": "produk:1", "periode": "2026-11", "product_code": "1", "nama": "X",
             "biaya": 10_000, "omzet": 100_000, "terjual": 1},
        ])
        out = Mon.group_members_review(members, "produk:1", target_roas=8.0)
        self.assertTrue(out.empty)

    def test_stock_worthiness_triad(self):
        ada, tip = Mon.stock_worthiness({"stok_10037": 10, "stok_10062": 0, "stok_10036": 5})
        self.assertEqual(ada, "ada_toko")
        self.assertIn("10037", tip)
        dc, tip2 = Mon.stock_worthiness({"stok_10037": 0, "stok_10062": 8, "stok_10036": 0})
        self.assertEqual(dc, "isi_dari_dc")
        self.assertIn("DC", tip2)
        kosong, tip3 = Mon.stock_worthiness({"stok_10037": 0, "stok_10062": 0, "stok_10036": 0})
        self.assertEqual(kosong, "kosong")
        self.assertIn("kosong", tip3.lower())

    def test_group_member_shows_stock_columns(self):
        members = pd.DataFrame([
            {"unit": "grup:G1", "periode": "2026-11", "product_code": "A", "nama": "Ada",
             "biaya": 10_000, "omzet": 200_000, "terjual": 2},
            {"unit": "grup:G1", "periode": "2026-11", "product_code": "B", "nama": "Kosong",
             "biaya": 10_000, "omzet": 0, "terjual": 0},
        ])
        products = pd.DataFrame([
            {"product_code": "A", "nama": "Ada", "omzet_harian": 100_000,
             "stok": 5, "stok_10037": 5, "stok_10062": 20, "stok_10036": 3, "stok_room": 1e6},
            {"product_code": "B", "nama": "Kosong", "omzet_harian": 50_000,
             "stok": 0, "stok_10037": 0, "stok_10062": 0, "stok_10036": 0, "stok_room": 0},
        ])
        out = Mon.group_members_review(members, "grup:G1", target_roas=8.0, products=products)
        self.assertIn("Stok 10037", out.columns)
        self.assertIn("Stok 10062", out.columns)
        self.assertIn("Stok 10036", out.columns)
        by = out.set_index("Kode produk")
        self.assertAlmostEqual(by.loc["A", "Stok 10037"], 5)
        self.assertAlmostEqual(by.loc["A", "Stok 10062"], 20)
        self.assertEqual(by.loc["B", "Tindakan"], "Keluarkan dari grup")
        self.assertIn("10037", str(by.loc["B", "Saran"]))

    def test_group_members_review_pending_setup_compares_elsewhere(self):
        members = pd.DataFrame([
            # Grup belum setup: periode terakhir semua 0
            {"unit": "grup:G0", "periode": "2026-11", "product_code": "A", "nama": "Sudah tunggal",
             "biaya": 0, "omzet": 0, "terjual": 0},
            {"unit": "grup:G0", "periode": "2026-11", "product_code": "B", "nama": "Lemah dulu",
             "biaya": 0, "omzet": 0, "terjual": 0},
            {"unit": "grup:G0", "periode": "2026-11", "product_code": "C", "nama": "Layak baru",
             "biaya": 0, "omzet": 0, "terjual": 0},
            {"unit": "grup:G0", "periode": "2026-11", "product_code": "D", "nama": "Prediksi kecil",
             "biaya": 0, "omzet": 0, "terjual": 0},
            # Histori campaign sebelumnya
            {"unit": "grup:G0", "periode": "2026-10", "product_code": "B", "nama": "Lemah dulu",
             "biaya": 50_000, "omzet": 0, "terjual": 0},
            {"unit": "grup:G0", "periode": "2026-10", "product_code": "C", "nama": "Layak baru",
             "biaya": 40_000, "omzet": 900_000, "terjual": 5},
            # A sudah jalan sebagai iklan tunggal
            {"unit": "produk:A", "periode": "2026-11", "product_code": "A", "nama": "Sudah tunggal",
             "biaya": 80_000, "omzet": 1_600_000, "terjual": 8},
        ])
        units = [
            A.Unit("produk:A", "Sudah tunggal", "Produk tunggal", "Berjalan", "GMV Max ROAS",
                   80_000, 1_600_000, 0.0, 0.0, 0.5, ["A"], []),
            A.Unit("grup:G0", "Grup 01", "Grup", "Dijeda", "GMV Max ROAS",
                   0.0, 0.0, 0.0, 0.0, 0.5, ["A", "B", "C", "D"], []),
        ]
        # C = prediksi tinggi (mendorong target); D = prediksi kecil + tanpa histori kuat → tidak perlu
        products = pd.DataFrame([
            {"product_code": "A", "nama": "Sudah tunggal", "omzet_harian": 100_000, "qty_harian": 2,
             "stok": 10, "stok_10037": 10, "stok_10062": 0, "stok_10036": 0, "stok_room": 1_000_000},
            {"product_code": "B", "nama": "Lemah dulu", "omzet_harian": 5_000, "qty_harian": 0.1,
             "stok": 5, "stok_10037": 5, "stok_10062": 0, "stok_10036": 0, "stok_room": 50_000},
            {"product_code": "C", "nama": "Layak baru", "omzet_harian": 200_000, "qty_harian": 4,
             "stok": 20, "stok_10037": 20, "stok_10062": 50, "stok_10036": 10, "stok_room": 2_000_000},
            {"product_code": "D", "nama": "Prediksi kecil", "omzet_harian": 8_000, "qty_harian": 0.2,
             "stok": 15, "stok_10037": 15, "stok_10062": 0, "stok_10036": 0, "stok_room": 100_000},
        ])
        out = Mon.group_members_review(
            members, "grup:G0", target_roas=22.0, group_active=False,
            units=units, products=products, contribution={"A": 0.3, "B": 0.2, "C": 0.25, "D": 0.2},
        )
        by = out.set_index("Kode produk")
        self.assertEqual(by.loc["A", "Tindakan"], "Sudah diiklankan di tempat lain")
        self.assertEqual(by.loc["B", "Tindakan"], "Tidak perlu di-setup")
        self.assertEqual(by.loc["C", "Tindakan"], "Layak di-setup di grup ini")
        self.assertEqual(by.loc["D", "Tindakan"], "Tidak perlu di-setup")
        self.assertIn("Kenapa harus diiklankan", str(by.loc["C", "Saran"]))
        self.assertIn("tidak mendorong target", str(by.loc["D", "Saran"]).lower())
        # Urutan: Layak dulu, lalu Tidak perlu, lalu Sudah di tempat lain
        self.assertEqual(out.iloc[0]["Kode produk"], "C")
        tip = Mon.group_members_summary(out)
        self.assertIn("layak", tip.lower())
        self.assertIn("sudah diiklankan", tip.lower())
        self.assertNotIn("sehat", tip.lower())
        # Ringkasan menyebut layak sebelum "sudah diiklankan"
        self.assertLess(tip.lower().find("layak"), tip.lower().find("sudah diiklankan"))

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

    def test_paused_plan_zero_budget_tip_explains_intentional(self):
        # 5 hari × 6.592.242 = 32.961.210 biaya; omzet 200 jt → ROAS ≈ 6,1× (bukan biaya 200 jt)
        frame = pd.DataFrame([{
            "_key": "produk:9", "Iklan": "Shower Column Set Tidy", "Jenis": "Produk tunggal",
            "Budget usulan/hari": 0, "Budget efektif Shopee/hari": 0,
            "Hari dievaluasi": 5,
            "Biaya aktual/hari": 6_592_242, "Biaya bulan ini/hari": 4_073_599,
            "Biaya sejak disimpan": 32_961_210,
            "Omzet iklan sejak disimpan": 200_142_652,
            "Omzet iklan aktual/hari": 40_028_530, "ROAS aktual": 6.1,
            "Rekomendasi dijalankan": "Belum",
        }])
        out = Mon.classify_rows(frame, target_roas=22)
        tip = str(out.iloc[0]["Saran"])
        self.assertEqual(out.iloc[0]["Tindakan"], "Jeda / hentikan")
        tip_l = tip.lower()
        self.assertIn("budget rencana rp 0", tip_l)
        self.assertIn("sengaja dihentikan", tip_l)
        self.assertIn("shower column set tidy", tip_l)
        self.assertIn("biaya", tip_l)
        self.assertIn("5 hari", tip_l)
        self.assertIn("omzet", tip_l)
        self.assertIn("tgl 1", tip_l)  # jelaskan kenapa bulan < sejak campaign
        self.assertNotIn("200.142.652/hari", tip)  # jangan tampilkan omzet sebagai seolah biaya/hari
        from src.ui.ads_monitor_view import _plan_setup_labels
        plan_txt, setup_ok = _plan_setup_labels(0.0, 0.0)
        self.assertIn("dihentikan", plan_txt)
        self.assertIn("tidak diisi", setup_ok)
        _, setup_spend = _plan_setup_labels(0.0, 0.0, actual_since=6_592_242, actual_month=4_073_599)
        self.assertIn("masih berbiaya", setup_spend)
        self.assertIn("pause belum efektif", setup_spend)
        # Di Shopee ≠ rata-rata terpakai (jangan tempel Rp/hari di label setup)
        self.assertNotIn("6.592.242", setup_spend)
        self.assertNotIn("/hari", setup_spend)

    def test_turunkan_tip_mentions_shopee_budget_not_duplicate_acuan(self):
        frame = pd.DataFrame([{
            "_key": "produk:1", "Jenis": "Produk tunggal",
            "Budget usulan/hari": 4_750_000, "Budget efektif Shopee/hari": 4_750_000,
            "Biaya aktual/hari": 17_537_306, "Biaya bulan ini/hari": 16_000_000,
            "Omzet iklan aktual/hari": 200_000_000, "ROAS aktual": 11.0,
            "Rekomendasi dijalankan": "Belum",
        }])
        out = Mon.classify_rows(frame, target_roas=22)
        tip = str(out.iloc[0]["Saran"])
        self.assertEqual(out.iloc[0]["Tindakan"], "Turunkan budget")
        self.assertIn("sejak campaign", tip)
        self.assertIn("Terpakai bulan ini", tip)
        self.assertIn("budget di Shopee", tip)
        self.assertNotIn("acuan", tip)
        self.assertNotIn("±", tip)
        self.assertIn("Seller Center", tip)


if __name__ == "__main__":
    unittest.main()
