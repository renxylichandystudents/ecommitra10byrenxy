"""Tes modul inti Revisi Final: margin, promo gate, restock, gudang, impor, iklan, kalender, format."""

from __future__ import annotations

import unittest
from datetime import date

import numpy as np
import pandas as pd

from src.core import ads_plan, cancel_reasons, fmt, margin, promo, promo_calendar, ranking_score, restock, warehouse
from src.core.pred_actual import achievement_status, cause
from src.core.product_features import features_from_description, hook_for


class MarginTests(unittest.TestCase):
    def test_contoh_200019936(self):
        comp = margin.Components(hpp=905_000, komisi_pct=8, layanan_pct=4, transaksi_pct=1.8, packing=45_000, voucher=25_000)
        value, pct = margin.unit_margin(1_205_000, comp, 38_500)
        self.assertAlmostEqual(value, 25_210, places=0)
        self.assertEqual(round(pct, 1), 2.1)

    def test_harga_minimal_dibulatkan_ke_100(self):
        comp = margin.Components(hpp=30_000, komisi_pct=8, layanan_pct=4, transaksi_pct=1.8, packing=1_000)
        price = margin.harga_minimal(comp, 0, 8)
        self.assertEqual(price % 100, 0)
        _value, pct = margin.unit_margin(price, comp)
        self.assertGreaterEqual(pct, 8)

    def test_komponen_berperiode(self):
        history = pd.DataFrame(
            [
                {"sku": "1", "varian": "", "hpp": 100, "komisi_pct": 8, "berlaku_mulai": date(2026, 1, 1), "berlaku_selesai": date(2026, 6, 1)},
                {"sku": "1", "varian": "", "hpp": 120, "komisi_pct": 8, "berlaku_mulai": date(2026, 6, 1), "berlaku_selesai": None},
            ]
        )
        self.assertEqual(margin.effective_components(history, "1", on=date(2026, 3, 1)).hpp, 100)
        self.assertEqual(margin.effective_components(history, "1", on=date(2026, 7, 1)).hpp, 120)

    def test_close_previous_periods(self):
        existing = pd.DataFrame([{"sku": "1", "varian": "", "hpp": 100, "berlaku_mulai": date(2026, 1, 1), "berlaku_selesai": None}])
        new = pd.DataFrame([{"sku": "1", "varian": "", "hpp": 120, "berlaku_mulai": date(2026, 6, 1)}])
        closed = margin.close_previous_periods(existing, new)
        self.assertEqual(closed.iloc[0]["berlaku_selesai"], date(2026, 6, 1))

    def test_normalize_persen_pecahan(self):
        frame = pd.DataFrame([{"sku": "1.0", "hpp": "1000", "komisi_pct": 0.08, "berlaku_mulai": "01/11/2026"}])
        out = margin.normalize_components(frame)
        self.assertEqual(out.iloc[0]["sku"], "1")
        self.assertAlmostEqual(out.iloc[0]["komisi_pct"], 8)


class PromoTests(unittest.TestCase):
    row = {"sku": "1", "stok": 100, "ada_data_stok": True, "m_qty": 50, "ss": 10}

    def test_lolos(self):
        ok, reasons, decision = promo.promo_eligible(self.row, excluded=set(), margin_pct=12, cancel_pct=5)
        self.assertTrue(ok)
        self.assertEqual(decision, "Iklankan")

    def test_sku_jasa(self):
        ok, reasons, decision = promo.promo_eligible({**self.row, "sku": "40030033"}, excluded=set(promo.SEED_EXCLUDED), margin_pct=12, cancel_pct=5)
        self.assertFalse(ok)
        self.assertEqual(decision, "SKU jasa")

    def test_alasan_gagal(self):
        ok, reasons, _ = promo.promo_eligible({**self.row, "stok": 5}, excluded=set(), margin_pct=-3, cancel_pct=19)
        self.assertFalse(ok)
        self.assertIn("Stok kurang", reasons)
        self.assertIn("Margin minus", reasons)
        self.assertIn("Batal tinggi 19%", reasons)

    def test_dibatasi_stok(self):
        ok, _reasons, decision = promo.promo_eligible({**self.row, "stok": 30}, excluded=set(), margin_pct=12, cancel_pct=0)
        self.assertTrue(ok)
        self.assertEqual(decision, "Dibatasi stok")

    def test_usulan_dan_filter(self):
        products = pd.DataFrame(
            {
                "sku": ["9", "8", "7"],
                "product_name": ["Bubble Wrap Tambahan", "Sealant Bening", "Kloset Duduk Tidy FSA0089 [INCLUDE PACKING KAYU]"],
            }
        )
        usulan = promo.exclusion_suggestions(products, set())
        self.assertNotIn("7", set(usulan["sku"]))
        self.assertIn("40030033", set(usulan["sku"]))
        self.assertIn("9", set(usulan["sku"]))
        self.assertNotIn("8", set(usulan["sku"]))
        frame = pd.DataFrame({"sku": ["40030033", "8"]})
        self.assertEqual(list(promo.drop_excluded(frame, {"40030033"})["sku"]), ["8"])

    def test_label(self):
        self.assertEqual(promo.product_label("1", "Lem", "Putih"), "1 · Lem · Putih")
        self.assertEqual(promo.product_label("1", "Lem", "nan"), "1 · Lem")


class RestockTests(unittest.TestCase):
    def table(self):
        return pd.DataFrame(
            [
                {"sku": "A", "product_name": "Kloset", "variasi_tampil": "", "ada_data_stok": True, "stok": 2, "m_qty": 60, "ss": 10, "pred_harian": 2, "harga_bersih": 1000},
                {"sku": "B", "product_name": "Lem", "variasi_tampil": "", "ada_data_stok": True, "stok": 500, "m_qty": 30, "ss": 5, "pred_harian": 1, "harga_bersih": 1000},
                {"sku": "C", "product_name": "Sealant", "variasi_tampil": "", "ada_data_stok": True, "stok": 0, "m_qty": 30, "ss": 5, "pred_harian": 1, "harga_bersih": 1000},
            ]
        )

    def test_prioritas_dan_pic(self):
        po = {"A": {"no_po": "PO1", "qty": 100, "eta": date(2026, 11, 20)}}
        records = restock.recommendation_records(self.table(), date(2026, 11, 2), po=po)
        first = records.iloc[0]
        self.assertEqual(first["prioritas"], 1)
        rec_a = records.set_index("sku").loc["A"]
        self.assertEqual(rec_a["restock"], 68)
        self.assertEqual(rec_a["pic"], "Team IC/MD")
        rec_c = records.set_index("sku").loc["C"]
        self.assertEqual(rec_c["tenggat"], "Segera")
        self.assertEqual(rec_c["pic"], "Team DC")
        self.assertEqual(records.set_index("sku").loc["B"]["prioritas"], 3)

    def test_restock_priority_urutan(self):
        frame = restock.restock_priority(self.table(), date(2026, 11, 2))
        self.assertEqual(list(frame["sku"]), ["C", "A", "B"])
        self.assertEqual(frame.set_index("sku").loc["C", "Status"], "Kosong")
        self.assertEqual(frame.set_index("sku").loc["B", "Status"], "Aman")


class WarehouseTests(unittest.TestCase):
    def test_kapasitas_zona(self):
        layout, _bad = warehouse.normalize_layout(pd.DataFrame([{"kode_rak": "R1", "zona": "Saniter", "panjang_cm": 100, "lebar_cm": 100, "tinggi_cm": 100, "faktor_isi": None}]))
        cap = warehouse.zone_capacity(layout)
        self.assertAlmostEqual(cap["Saniter"], 0.85)

    def test_warna(self):
        self.assertEqual(warehouse.capacity_color(50), "#16a34a")
        self.assertEqual(warehouse.capacity_color(80), "#ea580c")
        self.assertEqual(warehouse.capacity_color(95), "#dc2626")

    def test_validasi_impor(self):
        frame = pd.DataFrame(
            [
                {"no_po": "PO1", "tanggal_catatan": "01/11/2026", "sku": "A", "qty": 10, "eta_terbaru": "20/11/2026", "status": "Di kapal", "author": "palsu"},
                {"no_po": "PO2", "tanggal_catatan": "xx", "sku": "Z", "qty": 1, "status": "Hilang"},
            ]
        )
        good, bad = warehouse.validate_import_rows(frame, {"A"}, "renxy")
        self.assertEqual(len(good), 1)
        self.assertEqual(good.iloc[0]["author"], "renxy")
        self.assertEqual(len(bad), 1)
        self.assertTrue(bad.iloc[0]["alasan"])


class AdsPlanTests(unittest.TestCase):
    def test_fit_kurva(self):
        rng = np.random.default_rng(0)
        cost = rng.uniform(10_000, 200_000, 40)
        sales = 500_000 * np.log1p(cost / 50_000) + rng.normal(0, 5_000, 40)
        curve = ads_plan.fit_curve(cost, sales)
        self.assertIsNotNone(curve)
        self.assertGreater(curve.b, 0)
        self.assertLess(abs(curve.a - 500_000) / 500_000, 0.2)

    def test_kurang_dari_20_titik(self):
        self.assertIsNone(ads_plan.fit_curve(np.ones(10) * 1000, np.ones(10)))

    def test_greedy_dan_kejar_target(self):
        cands = [
            ads_plan.Candidate("A", "A", 20, 10_000, ads_plan.Curve(300_000, 20_000, "fit"), float("inf"), "Iklankan"),
            ads_plan.Candidate("B", "B", 5, 10_000, ads_plan.Curve(100_000, 20_000, "fit"), float("inf"), "Iklankan"),
            ads_plan.Candidate("C", "C", 30, 10_000, ads_plan.Curve(900_000, 20_000, "fit"), float("inf"), "SKU jasa"),
        ]
        ads_plan.allocate(cands, 2_000_000)
        spent = sum(c.extra_monthly for c in cands)
        self.assertGreater(spent, 0)
        self.assertLessEqual(spent, 2_000_000)
        self.assertEqual(cands[2].extra_monthly, 0)
        self.assertGreater(cands[0].extra_monthly, cands[1].extra_monthly)
        # Tiap SKU berhenti di titik impas: Rp 500.000 terakhir masih untung.
        for cand in cands[:2]:
            if cand.extra_monthly > 0:
                last = cand.daily_cost + (cand.extra_monthly - ads_plan.STEP_RP) / ads_plan.DAYS
                self.assertTrue(ads_plan.is_profitable(cand, last))
        budget = ads_plan.budget_for_gap(cands, 50_000)
        ads_plan.allocate(cands, budget)
        self.assertGreaterEqual(ads_plan.extra_sales(cands), 50_000)
        self.assertEqual(budget % ads_plan.STEP_RP, 0)

    def test_tidak_ada_budget_untuk_roas_nol(self):
        # SKU dengan ROAS marginal mendekati 0 tidak boleh menerima tambahan berapa pun budgetnya.
        weak = ads_plan.Candidate("S", "Sapu", 30, 1_775, ads_plan.Curve(2_000, 50_000, "default"), float("inf"), "Iklankan")
        ads_plan.allocate([weak], 2_000_000_000)
        self.assertEqual(weak.extra_monthly, 0)
        self.assertFalse(ads_plan.is_profitable(weak))

    def test_batas_tambahan_per_sku(self):
        strong = ads_plan.Candidate("K", "Kloset", 30, 100_000, ads_plan.Curve(50_000_000, 100_000, "fit"), float("inf"), "Iklankan")
        ads_plan.allocate([strong], 2_000_000_000)
        self.assertLessEqual(strong.extra_monthly, ads_plan.extra_cap_monthly(strong))


class CalendarTests(unittest.TestCase):
    def test_tanggal_spesial(self):
        days = dict(promo_calendar.special_days(2026, 11))
        self.assertIn(date(2026, 11, 11), days)
        self.assertIn(date(2026, 11, 25), days)
        self.assertIn(date(2026, 12, 12), dict(promo_calendar.special_days(2026, 12)))

    def test_harga_dan_kuota_flash(self):
        self.assertEqual(promo_calendar.flash_price(100_000, 0.1, 95_000), 95_000)
        self.assertEqual(promo_calendar.flash_quota(100, 10, 2, 60), 6)
        self.assertEqual(promo_calendar.flash_quota(10, 10, 2, 60), 0)

    def test_exposure_jarak_5_hari(self):
        ranked = pd.DataFrame({"sku": list("ABCDEFG"), "label": list("ABCDEFG"), "kategori": "Lem", "prioritas": range(7, 0, -1)})
        cal = promo_calendar.exposure_calendar(ranked, 2026, 11)
        self.assertFalse(cal.empty)
        self.assertLessEqual(cal.groupby("tanggal").size().max(), 2)
        for _sku, part in cal.groupby("sku"):
            days = sorted(d.day for d in part["tanggal"])
            self.assertTrue(all(b - a >= 5 for a, b in zip(days, days[1:])))

    def test_flash_jarak_7_hari(self):
        cands = pd.DataFrame([{"sku": "A", "label": "A", "kuota": 5, "harga": 1000, "harga_flash": 900, "skor": 1.0}])
        sched = promo_calendar.schedule_flash(cands, date(2026, 11, 1), months=2)
        days = sorted(sched["Tanggal"])
        self.assertTrue(all((b - a).days >= 7 for a, b in zip(days, days[1:])))


class MiscTests(unittest.TestCase):
    def test_status_capaian(self):
        self.assertEqual(achievement_status(110, 100), "Melebihi")
        self.assertEqual(achievement_status(100, 100), "Tercapai")
        self.assertEqual(achievement_status(85, 100), "Hampir")
        self.assertEqual(achievement_status(10, 100), "Tidak")
        self.assertEqual(achievement_status(1, 0), "Melebihi")

    def test_penyebab(self):
        self.assertEqual(cause(stock=0, pred=5, ad_cost_day=None, ad_cost_avg7=None, price_day=None, price_avg7=None), "Stok kosong")
        self.assertEqual(cause(stock=3, pred=5, ad_cost_day=None, ad_cost_avg7=None, price_day=None, price_avg7=None), "Stok tinggal 3")

    def test_alasan_batal(self):
        self.assertEqual(cancel_reasons.categorize("Need to change delivery address"), "Pembeli")
        self.assertEqual(cancel_reasons.categorize("Pesanan belum dibayar"), "Belum bayar")
        self.assertEqual(cancel_reasons.categorize("Stok habis"), "Penjual")
        self.assertEqual(cancel_reasons.categorize("Dibatalkan otomatis oleh sistem"), "Sistem Shopee")
        self.assertEqual(cancel_reasons.categorize("xyz aneh"), "Pembeli")

    def test_fmt(self):
        self.assertEqual(fmt.fmt_date(date(2026, 11, 2)), "2 Nov 2026")
        self.assertEqual(fmt.fmt_date_short(date(2026, 11, 2)), "02/11/2026")
        self.assertEqual(fmt.fmt_pct(16.114), "16,11%")
        self.assertEqual(fmt.fmt_rp(1_234_567), "Rp 1.234.567")
        self.assertEqual(fmt.fmt_int(1234), "1.234")

    def test_fitur_deskripsi(self):
        text = "Selamat datang di toko kami. Sealant tahan air hingga 10 tahun. Isi 300 ml. Hubungi chat untuk info."
        features = features_from_description(text)
        self.assertIn("Sealant tahan air hingga 10 tahun", features)
        self.assertIn("Isi 300 ml", features)
        self.assertFalse(any("toko kami" in f for f in features))
        self.assertTrue(hook_for("Sealant"))

    def test_skor_ranking(self):
        scores = ranking_score.readiness({"product_name": "Sealant Silikon Bening 300ml", "harga_bersih": 50_000, "batal_pct": 5}, rating=4.8, competitor_median=60_000)
        self.assertAlmostEqual(scores["skor"], 15 + 12 + 15 + 15)
        self.assertIsNone(scores["video"])
        steps = ranking_score.priority_steps(scores, 1_000_000)
        self.assertEqual(len(steps), 3)


if __name__ == "__main__":
    unittest.main()
