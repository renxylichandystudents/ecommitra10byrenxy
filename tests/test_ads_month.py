from datetime import date

import unittest

import pandas as pd

from src.core import ads_month as M


def _overall(rows):
    return pd.DataFrame([{"Periode laporan (teks)": f"{a} - {b}", "Kode Produk": "1", "Biaya": c, "Omzet Penjualan": s, "Nama Iklan": "x", "cost": c, "ad_sales": s,
                          "product_code": "1"} for a, b, c, s in rows])


def test_store_curve_and_month_plan():
    hist = [("2026-05", 74e6, 1744e6), ("2026-06", 107e6, 1790e6), ("2026-07", 124e6, 1827e6),
            ("2026-08", 208e6, 2511e6), ("2026-09", 250e6, 2472e6), ("2026-10", 260e6, 2849e6)]
    curve = M.fit_store_curve(hist)
    assert curve is not None and curve.a > 0
    assert curve.sales(400e6) > curve.sales(200e6) and curve.marginal(400e6) < curve.marginal(200e6)
    plan = M.month_plan(curve, target=4979e6, projection=3354e6, spent=122e6, cost_now_daily=10e6, days_left=18, month_days=30, budget_total=418e6)
    # Budget yang dibutuhkan menutup tepat kekurangan target.
    need = M.month_plan(curve, target=4979e6, projection=3354e6, spent=122e6, cost_now_daily=10e6, days_left=18, month_days=30,
                        budget_total=plan["budget_dibutuhkan"])
    assert abs(need["proyeksi"] - 4979e6) < 1e3
    assert plan["proyeksi"] < 4979e6 < need["proyeksi"] + 1e3
    assert plan["budget_sisa"] == 418e6 - 122e6


def test_curve_needs_three_months_and_positive_slope():
    assert M.fit_store_curve([("2026-09", 1e8, 2e9), ("2026-10", 2e8, 3e9)]) is None
    assert M.fit_store_curve([("a", 1e8, 3e9), ("b", 2e8, 2e9), ("c", 3e8, 1e9)]) is None


def test_ad_spend_prorates_month_to_date():
    ov = _overall([("01/10/2026", "31/10/2026", 31e6, 400e6), ("01/11/2026", "10/11/2026", 10e6, 150e6)])
    out = M.ad_spend(ov, date(2026, 11, 1), date(2026, 11, 10))
    assert round(out["biaya"]) == 10e6 and out["hari"] == 10


def test_daily_ad_totals_from_single_day_uploads():
    # Sejajar SC filter 1 hari / Kemarin — jangan bagi rata bulanan
    ov = pd.DataFrame([
        {"Periode laporan (teks)": "17/11/2026 - 17/11/2026", "period": "2026-11-17",
         "cost": 7e6, "ad_sales": 100e6, "product_code": "", "Nama Iklan": "x",
         "_submitted_at": "2026-11-18T08:00:00+07:00", "_source_key": "ads_overall"},
        {"Periode laporan (teks)": "18/11/2026 - 18/11/2026", "period": "2026-11-18",
         "cost": 8_154_135, "ad_sales": 128_168_508, "product_code": "", "Nama Iklan": "x",
         "_submitted_at": "2026-11-19T08:00:00+07:00", "_source_key": "ads_overall"},
    ])
    daily = M.daily_ad_totals(ov, start=date(2026, 11, 17), end=date(2026, 11, 18))
    assert list(daily["Tanggal"]) == ["2026-11-17", "2026-11-18"]
    assert round(daily.iloc[1]["Biaya"]) == 8_154_135
    assert daily.iloc[0]["Biaya"] != daily.iloc[1]["Biaya"]


def test_daily_ad_totals_from_consecutive_mtd():
    ov = pd.DataFrame([
        {"Periode laporan (teks)": "01/11/2026 - 17/11/2026", "period": "2026-11-01",
         "cost": 100e6, "ad_sales": 1000e6, "product_code": "", "Nama Iklan": "x",
         "_submitted_at": "2026-11-18T08:00:00+07:00", "_source_key": "ads_overall"},
        {"Periode laporan (teks)": "01/11/2026 - 18/11/2026", "period": "2026-11-01",
         "cost": 108_154_135, "ad_sales": 1128_168_508, "product_code": "", "Nama Iklan": "x",
         "_submitted_at": "2026-11-19T08:00:00+07:00", "_source_key": "ads_overall"},
    ])
    daily = M.daily_ad_totals(ov, start=date(2026, 11, 18), end=date(2026, 11, 18))
    assert len(daily) == 1
    assert round(daily.iloc[0]["Biaya"]) == 8_154_135


def test_daily_ad_totals_skips_shrinking_snapshot():
    # Unggahan parsial (total mengecil) tidak boleh menghasilkan biaya/omzet negatif
    ov = pd.DataFrame([
        {"Periode laporan (teks)": "01/11/2026 - 14/11/2026", "period": "2026-11-01",
         "cost": 142_070_246, "ad_sales": 2_314_769_000, "product_code": "", "Nama Iklan": "x",
         "_submitted_at": "2026-11-14T07:00:00+07:00", "_source_key": "ads_overall"},
        {"Periode laporan (teks)": "01/11/2026 - 15/11/2026", "period": "2026-11-01",
         "cost": 150_819_653, "ad_sales": 2_445_061_768, "product_code": "", "Nama Iklan": "x",
         "_submitted_at": "2026-11-15T20:00:00+07:00", "_source_key": "ads_overall"},
        {"Periode laporan (teks)": "01/11/2026 - 11/11/2026", "period": "2026-11-01",
         "cost": 0, "ad_sales": 0, "product_code": "", "Nama Iklan": "x",
         "_submitted_at": "2026-11-11T08:00:00+07:00", "_source_key": "ads_overall"},
    ])
    daily = M.daily_ad_totals(ov, start=date(2026, 11, 15), end=date(2026, 11, 15))
    assert len(daily) == 1
    assert round(daily.iloc[0]["Biaya"]) == 8_749_407
    assert daily.iloc[0]["Biaya"] > 0 and daily.iloc[0]["Omzet"] > 0


def test_same_range_keeps_larger_snapshot_not_later_partial():
    ov = pd.DataFrame([
        {"Periode laporan (teks)": "01/11/2026 - 15/11/2026", "period": "2026-11-01",
         "cost": 150_819_653, "ad_sales": 2_445_061_768, "product_code": "", "Nama Iklan": "x",
         "_submitted_at": "2026-11-15T20:00:00+07:00", "_source_key": "ads_overall"},
        {"Periode laporan (teks)": "01/11/2026 - 15/11/2026", "period": "2026-11-01",
         "cost": 192_737, "ad_sales": 1_779_798, "product_code": "", "Nama Iklan": "x",
         "_submitted_at": "2026-11-15T22:00:00+07:00", "_source_key": "ads_overall"},
        {"Periode laporan (teks)": "01/11/2026 - 14/11/2026", "period": "2026-11-01",
         "cost": 142_070_246, "ad_sales": 2_314_769_068, "product_code": "", "Nama Iklan": "x",
         "_submitted_at": "2026-11-14T07:00:00+07:00", "_source_key": "ads_overall"},
    ])
    daily = M.daily_ad_totals(ov, start=date(2026, 11, 15), end=date(2026, 11, 15))
    assert len(daily) == 1
    assert round(daily.iloc[0]["Biaya"]) == 8_749_407


def test_truncated_mtd_restored_when_nov19_anchor_is_stored():
    # Data latih: sisa baris 15 Nov + file 19 Nov utuh. Jangan minta unggah ulang.
    ov = pd.DataFrame([
        {"Periode laporan (teks)": "01/11/2026 - 15/11/2026", "period": "2026-11-01",
         "cost": 192_737, "ad_sales": 1_779_798, "product_code": "", "Nama Iklan": "x",
         "_submitted_at": "2026-11-15T07:09:27+07:00", "_source_key": "ads_overall"},
        {"Periode laporan (teks)": "01/11/2026 - 19/11/2026", "period": "2026-11-01",
         "cost": 184_003_414, "ad_sales": 2_995_964_550, "product_code": "", "Nama Iklan": "x",
         "_submitted_at": "2026-11-19T06:57:37+07:00", "_source_key": "ads_overall"},
    ])
    daily = M.daily_ad_totals(ov, start=date(2026, 11, 14), end=date(2026, 11, 18))
    assert list(daily["Tanggal"]) == ["2026-11-15", "2026-11-16", "2026-11-17", "2026-11-18"]
    assert round(daily.iloc[0]["Biaya"]) == 8_749_407
    assert round(daily.iloc[3]["Biaya"]) == 7_082_955
    assert round(daily["Omzet"].sum()) == 579_292_111


def test_daily_ad_totals_does_not_invent_prorata_from_month_blob():
    ov = _overall([("01/11/2026", "18/11/2026", 18e6, 200e6)])
    daily = M.daily_ad_totals(ov, start=date(2026, 11, 1), end=date(2026, 11, 18))
    assert daily.empty  # tidak mengarang 1 jt/hari


class PlanTrackTest(unittest.TestCase):
    def setUp(self):
        self.s = {"periode_target": "2026-11", "data_sampai": "2026-11-13", "hari_sisa": 17, "mtd": 1_600.0, "terpakai": 130.0,
                  "proyeksi": 5_000.0, "proyeksi_tanpa": 3_400.0, "budget_harian": 60.0}

    def test_old_plan_without_start_point(self):
        from src.core.ads_month import plan_track
        self.assertIsNone(plan_track({"periode_target": "2026-11"}, mtd=1, last=date(2026, 11, 20), spent=1, periode="2026-11"))
        self.assertIsNone(plan_track(self.s, mtd=1, last=date(2026, 12, 2), spent=1, periode="2026-12"))

    def test_on_track_and_behind(self):
        from src.core.ads_month import plan_track
        # 3,4 hari dari 17: jalur sales = 1600 + 3400 × 3/17 = 2200; jalur biaya = 130 + 60 × 3 = 310
        good = plan_track(self.s, mtd=2_200.0, last=date(2026, 11, 16), spent=310.0, periode="2026-11")
        self.assertAlmostEqual(good["jalur_sales"], 2_200.0)
        self.assertAlmostEqual(good["jalur_biaya"], 310.0)
        self.assertEqual(good["status"], "On track")
        self.assertEqual(good["biaya_status"], "sesuai")
        bad = plan_track(self.s, mtd=2_000.0, last=date(2026, 11, 16), spent=200.0, periode="2026-11")
        self.assertEqual(bad["status"], "Tertinggal")
        self.assertEqual(bad["biaya_status"], "kurang terserap")

    def test_waiting_for_new_data(self):
        from src.core.ads_month import plan_track
        self.assertEqual(plan_track(self.s, mtd=1_600.0, last=date(2026, 11, 13), spent=130.0, periode="2026-11")["status"], "Menunggu data")


class RatioBudgetTest(unittest.TestCase):
    def test_budget_hits_three_percent_of_gross(self):
        from src.core.ads_month import budget_for_ratio, store_contribution_rate
        project = lambda b: (1_000_000_000 + 2 * b, b)  # noqa: E731
        b = budget_for_ratio(project, pct=3.0, gross_ratio=1.5, spent=10_000_000, start=100_000_000)
        net, _ = project(b)
        self.assertAlmostEqual(b / (net * 1.5) * 100, 3.0, delta=0.05)
        self.assertEqual(budget_for_ratio(project, pct=3.0, gross_ratio=1.5, spent=90_000_000, start=1), 90_000_000)
        self.assertAlmostEqual(store_contribution_rate({"a": 0.1, "b": -0.2}, {"a": 3, "b": 1}), 0.025)
        self.assertIsNone(store_contribution_rate({}, {}))
