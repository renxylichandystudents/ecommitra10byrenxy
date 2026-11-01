from __future__ import annotations

import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.config import changed_from_default, default_params, load_params, load_rules, save_params
from src.core.decision_table import build_decision_table, period_groups, safety_stock_summary
from src.core.ensemble import MODEL_ENSEMBLE, MODEL_LEVEL, build_demand_matrix, model_forecasts
from src.core.evaluation import MAPE_TARGET_PCT, mape, walk_forward, wape
from src.core.expert_system import action_steps, evaluate_rules, fishbone, sku_facts, swot
from src.core.inventory import service_level_to_z, safety_stock_import, stock_zero_duration
from src.core.labels import ads_by_sku, product_labels
from src.core.nlp_competitor import build_name_recommendations, clean_text, score_name, synthesize_title
from src.core.optimization import optimize_restock
from src.core.recommendations import ads_plan, flash_sale_plan

TODAY = date(2026, 10, 31)


def _history(days: int = 200, skus: int = 30, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    start = pd.Timestamp(TODAY) - pd.Timedelta(days=days)
    rows = []
    for s in range(skus):
        base = 2 + s * 0.5
        for d in range(days):
            day = start + pd.Timedelta(days=d)
            weekly = 1.2 if day.dayofweek in (5, 6) else 0.95
            qty = rng.poisson(base * weekly)
            if qty:
                rows.append({"item_key": f"SKU{s:03d}", "period_start": day, "qty": float(qty), "sales": float(qty * 10_000)})
    return pd.DataFrame(rows)


def _view() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "item_key": ["A", "B", "C"],
            "sku": ["A", "B", "C"],
            "product_name": ["Cat Tembok Avian 5 kg", "Pipa PVC Rucika 3 inch 4 m", "Semen Tiga Roda 40 kg"],
            "variasi_tampil": ["Putih", "Tanpa variasi", "Tanpa variasi"],
            "pred_qty": [300.0, 30.0, 0.0],
            "pred_sales": [3_000_000.0, 900_000.0, 0.0],
            "safety_stock": [20.0, 5.0, 0.0],
            "qty_total": [280.0, 25.0, 3.0],
            "sales_total": [2_800_000.0, 750_000.0, 150_000.0],
        }
    )


class DecisionTableTests(unittest.TestCase):
    def test_period_groups_follow_rule(self) -> None:
        self.assertEqual([g.prefix for g in period_groups("bulan", TODAY)], ["d", "m"])
        groups = period_groups("kuartal", TODAY)
        self.assertEqual([g.prefix for g in groups], ["d", "m", "p"])
        self.assertEqual(groups[2].label, "Quartal")

    def test_month_forecast_not_below_actual_and_need_formula(self) -> None:
        orders = pd.DataFrame(
            {
                "item_key": ["A"] * 30,
                "order_time": pd.date_range("2026-10-01", periods=30, freq="D"),
                "qty": [20.0] * 30,
                "sales": [200_000.0] * 30,
            }
        )
        stock = pd.DataFrame({"sku": ["A", "B", "C"], "stock_dc_cikupa": [100, 0, 50], "_submitted_at": ["2026-10-31T08:00:00"] * 3})
        table = build_decision_table(_view(), period="bulan", today=TODAY, horizon_days=30, orders=orders, stock_frame=stock)
        a = table.set_index("item_key").loc["A"]
        self.assertGreaterEqual(a["m_qty"], a["actual_mtd_qty"])
        self.assertEqual(a["actual_mtd_qty"], 600.0)
        self.assertEqual(a["m_butuh"], np.ceil(a["pred_harian"] * 1 + a["ss"]))
        self.assertEqual(a["d_butuh"], np.ceil(a["pred_harian"] + a["ss"]))
        self.assertEqual(a["m_selisih"], a["stok"] - a["m_butuh"])
        b = table.set_index("item_key").loc["B"]
        self.assertEqual(b["m_status"].split(" · ")[0], "Kosong")
        summary = safety_stock_summary(table)
        self.assertEqual(summary["total_ss"], 25.0)
        self.assertNotIn("p_qty", table.columns)

    def test_extra_period_columns_only_for_long_period(self) -> None:
        table = build_decision_table(_view(), period="semester", today=TODAY, horizon_days=181)
        self.assertIn("p_qty", table.columns)
        self.assertEqual(table.loc[0, "p_butuh"], np.ceil(300 + 20))
        self.assertTrue((table["m_status"] == "Tanpa data stok").all())

    def test_zero_stock_duration_from_snapshots(self) -> None:
        snaps = pd.DataFrame(
            {
                "sku": ["A"] * 3,
                "stock_dc_cikupa": [5, 0, 0],
                "_submitted_at": ["2026-10-20", "2026-10-25", "2026-10-30"],
            }
        )
        out = stock_zero_duration(snaps, today=TODAY)
        self.assertEqual(int(out.iloc[0]["lama_kosong_hari"]), 6)
        self.assertEqual(str(out.iloc[0]["zero_since"]), "2026-10-25")


class ForecastEvaluationTests(unittest.TestCase):
    def test_ensemble_and_walk_forward_mape_target(self) -> None:
        matrix = build_demand_matrix(_history())
        forecasts, availability = model_forecasts(matrix, 28)
        self.assertIn(MODEL_LEVEL, forecasts)
        self.assertIn(MODEL_LEVEL, availability.active)
        result = walk_forward(matrix, 28, folds=3)
        self.assertEqual(result.folds, 3)
        self.assertIn(MODEL_ENSEMBLE, set(result.metrics["Model"]))
        ens = result.metrics.set_index("Model").loc[MODEL_ENSEMBLE]
        # Target 4.9 no. 1: MAPE ≤ 15% pada level agregat (data sintetis stabil).
        self.assertLessEqual(ens["MAPE agregat (%)"], MAPE_TARGET_PCT)
        self.assertAlmostEqual(sum(result.weights.values()), 1.0, places=6)

    def test_censored_days_not_read_as_low_demand(self) -> None:
        hist = _history(days=120, skus=2)
        zero_since = {"SKU001": pd.Timestamp(TODAY) - pd.Timedelta(days=14)}
        cut = hist.loc[~((hist["item_key"] == "SKU001") & (hist["period_start"] >= zero_since["SKU001"]))]
        censored = build_demand_matrix(cut, zero_since=zero_since)
        naive = build_demand_matrix(cut)
        row = censored.keys.index("SKU001")
        self.assertTrue(np.isnan(censored.values[row, -1]))
        f_c, _ = model_forecasts(censored, 28)
        f_n, _ = model_forecasts(naive, 28)
        self.assertGreater(f_c["Moving Average 28"][row], f_n["Moving Average 28"][row])

    def test_metrics(self) -> None:
        self.assertTrue(np.isnan(mape(np.array([0.0]), np.array([1.0]))))
        self.assertAlmostEqual(mape(np.array([100.0, 0.0]), np.array([90.0, 5.0])), 10.0)
        self.assertAlmostEqual(wape(np.array([100.0, 100.0]), np.array([90.0, 120.0])), 15.0)


class StockStressTests(unittest.TestCase):
    def test_import_delay_simulation_zero_stockout(self) -> None:
        # Target 4.9 no. 2: stok = ROP dengan SS impor → 0% stockout pada simulasi delay s.d. L_max.
        d_avg, l_avg, l_max = 12.0, 60.0, 90.0
        ss = safety_stock_import(l_max=l_max, l_avg=l_avg, d_avg=d_avg)
        rop = d_avg * l_avg + ss
        rng = np.random.default_rng(1)
        delays = rng.uniform(l_avg, l_max, 5000)
        stockouts = (d_avg * delays > rop + 1e-9).mean()
        self.assertEqual(stockouts, 0.0)

    def test_milp_never_infeasible(self) -> None:
        # Target 4.9 no. 3: soft constraint + slack → 0% infeasible walau kapasitas sempit.
        rng = np.random.default_rng(3)
        for capacity in (10, 500, 100_000):
            items = pd.DataFrame({"kebutuhan": rng.integers(10, 400, 25).astype(float), "current_stock": rng.integers(0, 100, 25).astype(float)})
            out = optimize_restock(items, capacity=capacity, moq=5)
            self.assertIn(out["optimizer_status"].iloc[0], {"Optimal", "fallback EOQ/ROP"})
            self.assertLessEqual(out["restock_qty"].sum(), capacity + 1e-6)


class ExpertNlpTests(unittest.TestCase):
    def test_rules_fire_and_block_ads_when_stock_short(self) -> None:
        rules = load_rules()
        self.assertGreater(len(rules), 5)
        row = pd.Series({"m_status": "Kurang", "m_butuh": 100, "stok": 40, "ss": 10, "rop": 50, "hari_cukup": 4,
                         "biaya_iklan": 100_000, "omzet_iklan": 1_200_000, "dilihat": 5000, "klik": 20, "terjual_iklan": 1,
                         "abc": "C", "harga_vs_kompetitor_pct": 12.0, "batal_belum_bayar_pct": 20})
        facts = sku_facts(row, today=TODAY)
        advices = evaluate_rules(facts, rules)
        ids = {a.rule_id for a in advices}
        self.assertIn("stok_kurang_tahan_iklan", ids)
        self.assertIn("kelas_c_mahal", ids)
        steps = action_steps(advices, facts)
        self.assertLessEqual(len(steps), 3)
        self.assertFalse(any("Naikkan budget" in step for step in steps))

    def test_swot_fishbone_filled(self) -> None:
        result = swot({"sales_growth_pct": 5.0, "cancel_pct": 8.0, "top50_short": 3})
        self.assertTrue(all(result[k] for k in ("Strength", "Weakness", "Opportunity", "Threat")))
        fb = fishbone(pd.DataFrame({"reason": ["Belum bayar", "Ongkir mahal", "Ubah pesanan"], "orders": [10, 4, 2]}))
        self.assertIn("Belum bayar: 10 pesanan", fb["Pembayaran"])

    def test_name_scoring_and_description(self) -> None:
        params = default_params()
        self.assertEqual(clean_text("Cat 🎨 TEMBOK!!!"), "cat tembok")
        good = score_name("Avian Cat Tembok Interior Anti Jamur Akrilik 5 kg Putih", ["cat tembok"], params["merek"], min_len=25, max_len=120)
        poor = score_name("CAT!!!", ["cat tembok"], params["merek"], min_len=25, max_len=120)
        self.assertEqual(poor.label, "Poor")
        self.assertIn(good.label, {"Standard", "Excellence"})
        title = synthesize_title("cat tembok avian 5kg", "Putih", ["cat tembok interior"], params["merek"], max_len=120)
        self.assertTrue(title.startswith("Avian"))
        own = _view().assign(harga_bersih=10_000.0)
        comp = pd.DataFrame({"shop_name": ["Toko X", "Toko Y"], "product_name": ["Cat Tembok Avian 5kg Interior Putih", "Pipa PVC 3 inch Rucika AW"],
                             "price": ["Rp95.000", "Rp30.000"], "sold": ["1,2RB terjual", "300"]})
        names, note = build_name_recommendations(own, None, comp, {}, params)
        self.assertEqual(len(names), 3)
        self.assertTrue(note)
        for text in names["Rekomendasi deskripsi"]:
            self.assertLessEqual(len(text), params["shopee"]["deskripsi_maks_karakter"])
            self.assertNotRegex(text, r"<[a-z]+|\*\*|#")


class LabelsConfigRecommendationTests(unittest.TestCase):
    def test_labels(self) -> None:
        table = _view()
        orders = pd.DataFrame({"item_key": ["A", "B", "B", "B"], "status": ["Selesai", "Batal", "Batal", "Selesai"]})
        out = product_labels(table, orders=orders, params=default_params())
        self.assertIn("Terlaris", out.loc[0, "label"])
        self.assertIn("Perlu perhatian", out.loc[1, "label"])

    def test_ads_mapping_proportional(self) -> None:
        ads = pd.DataFrame({"product_code": ["111"], "views": [1000], "clicks": [50], "cost": [10_000], "ad_sales": [80_000]})
        stock = pd.DataFrame({"product_code": ["111", "111"], "sku": ["A", "B"]})
        mapped = ads_by_sku([ads], stock)
        self.assertAlmostEqual(mapped["dilihat"].sum(), 1000)
        self.assertAlmostEqual(mapped.set_index("sku").loc["A", "dilihat"], 500)

    def test_config_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            params = load_params(Path(tmp))
            self.assertFalse(changed_from_default(params, "lead_time.lokal_hari"))
            params["lead_time"]["lokal_hari"] = 3
            save_params(params, Path(tmp))
            again = load_params(Path(tmp))
            self.assertEqual(again["lead_time"]["lokal_hari"], 3)
            self.assertTrue(changed_from_default(again, "lead_time.lokal_hari"))

    def test_ads_and_flash_respect_stock(self) -> None:
        stock = pd.DataFrame({"sku": ["A", "B", "C"], "stock_dc_cikupa": [5000, 0, 50]})
        table = build_decision_table(_view(), period="bulan", today=TODAY, horizon_days=30, stock_frame=stock)
        table["label"] = [[], [], []]
        plan = ads_plan(table, orders=None, start=TODAY, end=TODAY + timedelta(days=29), target_roas=5, budget_max=1_000_000, params=default_params())
        self.assertIn("B", set(plan["tidak"]["SKU"]))
        flash = flash_sale_plan(table, start=TODAY, params=default_params())
        self.assertFalse(flash.empty)
        self.assertNotIn("B", set(flash["SKU"]))
        self.assertTrue((flash["Harga flash sale"] >= flash["Harga saat ini"] * 0.8 * 1.08 - 1).all())


class PerformanceTests(unittest.TestCase):
    def test_decision_table_fast(self) -> None:
        # Target 4.9 no. 5: perhitungan tabel untuk 3.000 SKU jauh di bawah 3 detik.
        n = 3000
        view = pd.DataFrame(
            {
                "item_key": [f"S{i}" for i in range(n)],
                "sku": [f"S{i}" for i in range(n)],
                "pred_qty": np.arange(n, dtype=float),
                "pred_sales": np.arange(n, dtype=float) * 1000,
                "safety_stock": np.ones(n),
            }
        )
        stock = pd.DataFrame({"sku": view["sku"], "stock_dc_cikupa": np.arange(n)})
        started = time.perf_counter()
        build_decision_table(view, period="tahun", today=TODAY, horizon_days=365, stock_frame=stock)
        self.assertLess(time.perf_counter() - started, 3.0)


if __name__ == "__main__":
    unittest.main()
