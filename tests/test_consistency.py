"""Angka yang sama di halaman berbeda harus dihitung dengan definisi yang sama (audit 11 Nov 2026)."""

from datetime import date

import numpy as np
import pandas as pd

from src.core import month_track as M
from src.core.metrics import net_sku_sales, sold_lines
from src.core.pred_actual import daily_comparison
from src.ingest import clean_order_frame


def _row(order, status, sku, qty, price, total, day, *, returned=0):
    return {
        "No. Pesanan": order, "Status Pesanan": status, "Alasan Pembatalan": "", "Waktu Pesanan Dibuat": day,
        "Nomor Referensi SKU": sku, "Nama Produk": f"Produk {sku}", "Nama Variasi": "", "Harga Setelah Diskon": price,
        "Jumlah": qty, "Returned quantity": returned, "Total Pembayaran": total, "Username (Pembeli)": "a",
    }


def _orders() -> pd.DataFrame:
    return clean_order_frame(pd.DataFrame([
        _row("A1", "Selesai", "100", 2, 50_000, 110_000, "2026-11-05 10:00"),
        _row("A2", "Selesai", "100", 3, 50_000, 160_000, "2026-11-05 11:00", returned=1),
        _row("A3", "Batal", "100", 4, 50_000, 205_000, "2026-11-05 12:00"),
        _row("A4", "Belum Bayar", "100", 1, 50_000, 55_000, "2026-11-05 13:00"),
    ]))


def _toggle_off(frame: pd.DataFrame) -> pd.DataFrame:
    """Saklar "Kecualikan batal & retur" mati: qty/sales diganti nilai kotor (seperti app.prepare_analysis_orders)."""
    return frame.assign(qty=frame["gross_qty"], sales=frame["gross_sales"])


def test_sold_lines_is_net_regardless_of_toggle():
    orders = _orders()
    net = net_sku_sales(orders)
    for frame in (orders, _toggle_off(orders)):
        sold = sold_lines(frame)
        assert float(sold["qty"].sum()) == 4.0
        assert float(sold["sales"].sum()) == float(net["sales"].sum()) == 200_000.0


def test_pred_vs_actual_uses_net_sales_with_toggle_off():
    gross = _toggle_off(_orders()).assign(sku=lambda f: f["sku"].astype(str))
    snap = pd.DataFrame({"tanggal": [date(2026, 11, 5)], "sku": ["100"], "varian": [""], "pred_qty": [4.0], "pred_sales": [200_000.0]})
    raw = daily_comparison(snap, gross, date(2026, 11, 5))
    assert float(raw["aktual_sales"].iloc[0]) == 500_000.0
    fixed = daily_comparison(snap, gross, date(2026, 11, 5), sold=sold_lines(gross))
    assert float(fixed["aktual_sales"].iloc[0]) == 200_000.0
    assert float(fixed["aktual_qty"].iloc[0]) == 4.0


def test_ad_cost_per_unit_uses_ad_window_qty():
    from src.ui.feature_data import ad_cost_map

    table = pd.DataFrame({"sku": ["A"], "biaya_iklan": [3_000_000.0], "qty_total": [1_200.0], "qty_sku": [100.0]})
    assert ad_cost_map(table) == {"A": 30_000.0}
    assert ad_cost_map(table.drop(columns="qty_sku")) == {"A": 2_500.0}


def test_stock_action_restocks_to_need_plus_ss():
    table = pd.DataFrame([
        {"sku": "A", "product_name": "Pipa", "pred_harian": 2.0, "harga_bersih": 100_000.0, "ada_data_stok": True, "stok": 30.0, "ss": 10.0,
         "stok_10062": np.nan, "stok_10036": np.nan},
    ])
    top = M.priority_actions(table, today=date(2026, 11, 10), rest_days=20)
    row = top.iloc[0]
    assert row["Jenis"] == "Stok"
    assert "20 unit" in row["Tindakan"]
    assert row["Potensi omzet"] == 10 * 100_000


def test_lead_time_follows_import_mode():
    from src.core.inventory import lead_time_days

    assert lead_time_days({"lead_time": {"lokal_hari": 7, "impor_aktif": False, "impor_rata_hari": 60}}) == 7
    assert lead_time_days({"lead_time": {"lokal_hari": 7, "impor_aktif": True, "impor_rata_hari": 60}}) == 60


def test_safety_stock_rounds_up():
    from src.core.decision_table import build_decision_table

    stock = pd.DataFrame({"item_key": ["A"], "sku": ["A"], "product_name": ["Pipa"], "variation_name": [""], "pred_qty": [30.0],
                          "pred_sales": [3_000_000.0], "safety_stock": [2.3]})
    table = build_decision_table(stock, period="bulan", today=date(2026, 11, 10), horizon_days=30)
    assert float(table["ss"].iloc[0]) == 3.0


def test_tiny_forecast_with_stock_has_no_overflow_date():
    from src.core.decision_table import build_decision_table

    view = pd.DataFrame({"item_key": ["A", "B"], "sku": ["A", "B"], "product_name": ["Pipa", "Semen"], "variation_name": ["", ""],
                         "pred_qty": [1e-9, 30.0], "pred_sales": [0.001, 3_000_000.0], "safety_stock": [0.0, 0.0]})
    stock = pd.DataFrame({"sku": ["A", "B"], "stock_dc_cikupa": [500, 60]})
    table = build_decision_table(view, period="bulan", today=date(2026, 11, 13), horizon_days=30, stock_frame=stock).set_index("sku")
    assert table.loc["A", "tanggal_habis"] is None
    assert isinstance(table.loc["B", "tanggal_habis"], date)


def test_today_follows_day_pattern_month_window_does_not():
    from src.core.decision_table import build_decision_table

    stock = pd.DataFrame({"item_key": ["A"], "sku": ["A"], "product_name": ["Pipa"], "variation_name": [""], "pred_qty": [300.0],
                          "pred_sales": [30_000_000.0], "safety_stock": [0.0]})
    flat = build_decision_table(stock, period="bulan", today=date(2026, 11, 12), horizon_days=30)
    shaped = build_decision_table(stock, period="bulan", today=date(2026, 11, 12), horizon_days=30, day_factor=0.84)
    assert float(flat["d_qty_exp"].iloc[0]) == 10.0
    assert abs(float(shaped["d_qty_exp"].iloc[0]) - 8.4) < 1e-9
    assert float(shaped["d_qty"].iloc[0]) == 8.0
    assert float(shaped["m_qty"].iloc[0]) == float(flat["m_qty"].iloc[0]) == 300.0


def test_ads_break_even_uses_margin_before_ads():
    row = {"sku": "B", "product_name": "Cat", "pred_harian": 2.0, "harga_bersih": 200_000.0, "ada_data_stok": True, "stok": 500.0, "ss": 5.0,
           "biaya_harian": 50_000.0, "biaya_iklan": 1_500_000.0, "omzet_iklan": 30_000_000.0, "stok_10062": np.nan, "stok_10036": np.nan}
    table = pd.DataFrame([row])
    after_ads = M.priority_actions(table, today=date(2026, 11, 10), rest_days=20, margin_pct={"B": 5.0})
    before_ads = M.priority_actions(table, today=date(2026, 11, 10), rest_days=20, margin_pct={"B": 5.0}, ad_per_unit={"B": 30_000.0})
    assert after_ads.empty
    assert "titik impas 5,0" in before_ads.iloc[0]["Alasan"]


def test_margin_report_deducts_seller_voucher_like_calculator():
    from src.core import margin_file as mf
    from src.core import margin_report as mr

    shopee = pd.DataFrame({"sku": ["1"], "item_code": ["01"], "nama": ["A"], "sales_incl": [1100.0], "sales_excl": [1000.0], "gm_value": [550.0]})
    orders = pd.DataFrame({"order_time": pd.to_datetime(["2026-10-03"]), "sku": ["1"], "qty": [2], "sales": [200_000.0],
                           "seller_voucher": [20_000.0], "status": ["Selesai"], "product_name": ["A"]})
    sales = mr.sales_by_sku(orders)
    row = mr.build(sales, mf.lookup(shopee, None), programs={}, order_fee=0, admin={"1": 10}).iloc[0]
    assert row["penjualan"] == 200_000 and row["penjualan_akhir"] == 180_000 and row["harga"] == 90_000
    assert round(row["kotor_rp"]) == 90_000 and round(row["bersih_rp"]) == 72_000 and round(row["bersih_pct"]) == 40


def test_slow_sku_prediction_floors_not_rounds():
    from src.core.decision_table import build_decision_table

    stock = pd.DataFrame({"item_key": ["A"], "sku": ["A"], "pred_qty": [2.7], "pred_sales": [270_000.0], "safety_stock": [0.0]})
    table = build_decision_table(stock, period="kuartal", today=date(2026, 11, 10), horizon_days=90)
    assert float(table["p_qty"].iloc[0]) == 2.0
    assert float(table["p_sales"].iloc[0]) == 200_000.0


def test_top_n_hits_ignores_unsold_ties():
    from src.core.evaluation import top_n_hits

    actual = np.array([5.0, 3.0, 0.0, 0.0, 0.0])
    pred = np.array([0.0, 0.0, 0.0, 4.0, 2.0])
    assert top_n_hits(actual, pred, n=50) == 0
    assert top_n_hits(actual, np.array([4.0, 1.0, 0.0, 0.0, 0.0]), n=50) == 2


def test_nested_evaluation_uses_only_earlier_folds():
    from src.models import evaluate as E

    rng = np.random.default_rng(1)
    n = 30
    actuals = [rng.poisson(10, n).astype(float) for _ in range(4)]
    singles = {E.MODEL_MA: [(a, a * 1.2) for a in actuals], E.MODEL_LEVEL: [(a, a * 0.9) for a in actuals]}
    valid = [np.ones(n, dtype=bool)] * 4
    segments = np.array(["AX"] * n, dtype=object)
    w_first, f_first, _ = E.fit_combination(singles, valid, segments, [0])
    # Fold 3 berubah ekstrem: setelan untuk lipatan 1 (hanya dari lipatan 0) tidak boleh ikut berubah.
    changed = {k: v[:3] + [(v[3][0], v[3][1] * 5)] for k, v in singles.items()}
    w_again, f_again, _ = E.fit_combination(changed, valid, segments, [0])
    assert w_first == w_again and f_first == f_again
    out, preds = E._nested_scores(singles, valid, segments, fold_classes_list=[np.array(["A"] * n, dtype=object)] * 4,
                                  fold_dates=["d0", "d1", "d2", "d3"])
    assert out["lipatan_dinilai"] == ["d1", "d2", "d3"]
    assert {"ensemble", "ensemble_segmen", "ma28", "level_terkini"} <= set(out["models"])
    assert len(preds[E.MODEL_SEGMENT]) == 3


def test_production_weights_follow_chosen_model():
    from src.models import evaluate as E

    weights = {E.MODEL_ES: 0.6, E.MODEL_MA: 0.4, E.BIAS_KEY: 1.1, E.SEGMENT_KEY: {"AX": E.MODEL_ES}}
    assert E.production_weights(weights, E.MODEL_SEGMENT) == weights
    assert E.SEGMENT_KEY not in E.production_weights(weights, E.MODEL_ENSEMBLE)
    assert E.production_weights(weights, E.MODEL_ES) == {E.MODEL_ES: 1.0}


def test_ss_calibration_scales_sigma_to_lead_time_error():
    from src.models.evaluate import ss_calibration
    from src.stock import recommend_stock

    assert abs(ss_calibration(np.full(100, 2.0)) - 2.0 / 0.6745) < 1e-9
    heavy = np.r_[np.full(95, 0.6745), np.full(5, 40.0)]
    assert abs(ss_calibration(heavy) - 1.0) < 1e-9
    assert ss_calibration(np.ones(5)) == 1.0
    combined = pd.DataFrame({"item_key": ["A"], "item_label": ["A"], "pred_qty": [30.0], "pred_sales": [300.0], "error_sigma": [2.0],
                             "rank_qty": [1], "rank_sales": [1], "rank_komposit": [1]})
    base = recommend_stock(None, combined, "hari", service_level_pct=95, lead_time_days=7, review_days=7)
    scaled = recommend_stock(None, combined, "hari", service_level_pct=95, lead_time_days=7, review_days=7, sigma_scale=2.0)
    assert abs(float(scaled["safety_stock"].iloc[0]) - 2 * float(base["safety_stock"].iloc[0])) < 1e-6


def test_service_level_per_abc_class():
    from src.core.service_level import abc_by_qty, class_service_levels
    from src.stock import recommend_stock

    assert class_service_levels(97, {}) == {"A": 99.0, "B": 97.0, "C": 90.0}
    assert class_service_levels(85, {"layanan_kelas": {"C": -10}})["C"] == 80.0
    days = pd.date_range("2026-10-01", periods=30)
    hist = pd.DataFrame({"item_key": ["A"] * 30 + ["B"] * 30 + ["C"] * 30, "period_start": list(days) * 3,
                         "qty": [80.0] * 30 + [15.0] * 30 + [5.0] * 30})
    assert abc_by_qty(hist) == {"A": "A", "B": "B", "C": "C"}
    combined = pd.DataFrame({"item_key": ["A", "C"], "item_label": ["A", "C"], "pred_qty": [30.0, 30.0], "pred_sales": [300.0, 300.0],
                             "error_sigma": [2.0, 2.0], "rank_qty": [1, 2], "rank_sales": [1, 2], "rank_komposit": [1, 2]})
    out = recommend_stock(None, combined, "hari", service_level_pct=97, lead_time_days=7, review_days=7,
                          item_service_pct={"A": 99.0, "C": 90.0}).set_index("item_key")
    assert out.loc["A", "safety_stock"] > out.loc["C", "safety_stock"]
    assert out.loc["A", "target_layanan_pct"] == 99.0


def test_full_day_cutoff_one_rule():
    from datetime import date

    from src.core.pred_actual import complete_through
    from src.ui.month_track_view import full_day_cutoff

    late = pd.Timestamp("2026-11-11 23:40")
    assert full_day_cutoff(late, date(2026, 11, 11)) == date(2026, 11, 10)
    assert full_day_cutoff(late, date(2026, 11, 12)) == date(2026, 11, 11)
    assert full_day_cutoff(pd.Timestamp("2026-11-08 08:29"), date(2026, 11, 11)) == date(2026, 11, 7)
    for stamp, today in ((late, date(2026, 11, 11)), (late, date(2026, 11, 12))):
        assert full_day_cutoff(stamp, today) == complete_through(stamp, today)


def test_prediction_window_label_is_not_calendar_month():
    from datetime import date

    from src.core.periods import format_period_label

    assert format_period_label("prediksi", date(2026, 11, 11)) == "Prediksi 30 hari (11 Nov – 10 Des 2026)"
    assert format_period_label("prediksi", date(2026, 12, 15)) == "Prediksi 31 hari (15 Des 2026 – 14 Jan 2027)"


def test_range_target_follows_day_pattern():
    from datetime import date

    from src.core import targets as T

    goal = {"2026-11": 3_000_000.0}
    flat, _ = T.range_target(goal, date(2026, 11, 1), date(2026, 11, 10))
    assert abs(flat - 1_000_000.0) < 1e-6
    peak = lambda d: 3.0 if d.day == 11 else 1.0  # noqa: E731
    before, _ = T.range_target(goal, date(2026, 11, 1), date(2026, 11, 10), peak)
    whole, _ = T.range_target(goal, date(2026, 11, 1), date(2026, 11, 30), peak)
    assert abs(before - 3_000_000.0 * 10 / 32) < 1e-6
    assert abs(whole - 3_000_000.0) < 1e-6


def test_period_actuals_skip_partial_last_day():
    from datetime import date

    from src.core.decision_table import period_actuals

    orders = pd.DataFrame({
        "order_time": pd.to_datetime(["2026-11-07 10:00", "2026-11-07 22:00", "2026-11-08 08:00"]),
        "item_key": ["A", "A", "A"], "qty": [3.0, 2.0, 1.0], "sales": [30.0, 20.0, 10.0],
    })
    out = period_actuals(orders, ["A"], period="bulan", today=date(2026, 11, 11))
    assert out["d"]["qty"] == 5.0 and "7" in out["d"]["label"]


def test_period_actuals_gross_and_net_with_dates():
    from datetime import date

    from src.core.decision_table import period_actuals
    from src.ingest import clean_order_frame

    def row(order, status, sku, qty, day, *, returned=0, reason=""):
        return {"No. Pesanan": order, "Status Pesanan": status, "Alasan Pembatalan": reason, "Waktu Pesanan Dibuat": day,
                "Nomor Referensi SKU": sku, "Nama Produk": f"Produk {sku}", "Nama Variasi": "", "Harga Setelah Diskon": 10_000,
                "Jumlah": qty, "Returned quantity": returned, "Total Pembayaran": qty * 9_000, "Username (Pembeli)": "a"}

    raw = pd.DataFrame([
        row("O1", "Selesai", "100", 4, "2026-10-05 10:00", returned=1),
        row("O2", "Batal", "100", 2, "2026-10-06 10:00", reason="Ubah pesanan"),
        row("O3", "Belum Bayar", "100", 1, "2026-10-07 10:00"),
        row("O4", "Selesai", "200", 5, "2026-10-08 10:00"),
        row("O5", "Selesai", "100", 1, "2026-11-10 23:30"),
    ])
    orders = clean_order_frame(raw)
    key = str(orders.loc[orders["sku"].astype(str) == "100", "item_key"].iloc[0])
    out = period_actuals(orders, [key], period="bulan", today=date(2026, 11, 11))["m"]
    assert (out["start"], out["end"]) == (date(2026, 10, 1), date(2026, 10, 31))
    assert out["qty_masuk"] == 7 and out["qty"] == 3          # 4 + 2 + 1 masuk; bersih 4 − 1 retur
    assert out["sales_masuk"] == 70_000 and out["sales"] == 30_000
    assert out["store_sales"] == 80_000                         # + SKU 200 (5 × 10.000)
    assert out["store_net"] == 4 * 9_000 - 10_000 + 5 * 9_000   # Total Pembayaran − retur (batal & Belum Bayar keluar)


def test_ads_plan_never_sells_beyond_stock():
    from src.core import ads_strategy as A
    from src.core.ads_fixed import stock_capped

    unit = A.Unit(key="u", nama="Iklan", jenis="Produk tunggal", status="Berjalan", mode="", daily_cost=100.0, daily_sales=1000.0,
                  a=2000.0, b=200.0, spread=0.2, members=["P1"], demand=1000.0, lift=0.5, stock_room=100.0)
    capped = stock_capped([unit])[0]
    assert A.ad_sales(capped, 10_000.0) - A._now_sales(capped) <= 100.0 + 1e-6


def test_net_factor_single_rule():
    from src.ui.month_track_view import net_factor

    days = pd.date_range("2026-10-01", "2026-11-09")
    net = pd.Series(90.0, index=days)
    product = pd.Series(100.0, index=days)
    assert abs(net_factor(net, product, date(2026, 11, 1), date(2026, 11, 9)) - 0.9) < 1e-9
    assert net_factor(net * 0.1, product, date(2026, 11, 1), date(2026, 11, 9)) == 0.5
    empty = product.where(product.index < pd.Timestamp("2026-11-01"), 0.0)
    assert abs(net_factor(net, empty, date(2026, 11, 1), date(2026, 10, 31), date(2026, 10, 31)) - 0.9) < 1e-9
