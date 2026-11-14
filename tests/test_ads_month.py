from datetime import date

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
