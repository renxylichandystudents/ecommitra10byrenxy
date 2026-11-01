from __future__ import annotations

import unittest

import pandas as pd

from src.core.preprocessing import (
    complete_daily_sku_frame,
    impute_numeric_frame,
    normalize_product_text,
    winsorize_outliers,
)
from src.core.segmentation import (
    abc_xyz_segments,
    association_rules,
    cluster_products,
    label_productivity,
    product_feature_table,
)


class PreprocessingPhase2Tests(unittest.TestCase):
    def test_daily_calendar_fills_missing_sales_days_with_zero(self) -> None:
        orders = pd.DataFrame(
            {
                "item_key": ["A", "A"],
                "order_time": ["2026-10-01", "2026-10-03"],
                "qty": [2, 4],
                "sales": [20_000, 40_000],
            }
        )
        dense = complete_daily_sku_frame(orders)
        self.assertEqual(len(dense), 3)
        middle = dense.loc[dense["date"].eq(pd.Timestamp("2026-10-02"))].iloc[0]
        self.assertEqual(float(middle["qty"]), 0.0)
        self.assertEqual(float(middle["sales"]), 0.0)

    def test_imputer_does_not_touch_qty_and_sales(self) -> None:
        frame = pd.DataFrame({"qty": [1, 0], "sales": [10, 0], "views": [100, None], "clicks": [10, 20]})
        imputed, filled, note = impute_numeric_frame(frame, columns=["qty", "sales", "views", "clicks"], method="median")
        self.assertEqual(filled, 1)
        self.assertEqual(imputed["qty"].tolist(), [1, 0])
        self.assertEqual(imputed["sales"].tolist(), [10, 0])
        self.assertIn("MEDIAN", note)

    def test_promo_spike_is_flagged_but_not_winsorized(self) -> None:
        frame = pd.DataFrame(
            {
                "qty": [1, 1, 1, 1, 2, 2, 2, 2, 80, 90],
                "sales": [10] * 10,
                "is_promo": [False] * 9 + [True],
            }
        )
        cleaned, stats = winsorize_outliers(frame, columns=("qty",), method="iqr")
        self.assertGreater(stats["flagged"], 0)
        self.assertGreater(stats["promo_kept"], 0)
        self.assertEqual(float(cleaned.loc[9, "qty"]), 90.0)
        self.assertLess(float(cleaned.loc[8, "qty"]), 80.0)

    def test_normalize_product_text_removes_noise(self) -> None:
        text = normalize_product_text("CAT TEMBOK!!! Premium untuk Dinding 😊")
        self.assertIn("cat", text)
        self.assertIn("tembok", text)
        self.assertNotIn("untuk", text)


class SegmentationPhase2Tests(unittest.TestCase):
    def test_abc_xyz_segments_are_created(self) -> None:
        daily = pd.DataFrame(
            {
                "item_key": ["A"] * 3 + ["B"] * 3 + ["C"] * 3,
                "date": pd.date_range("2026-10-01", periods=3).tolist() * 3,
                "qty": [10, 10, 10, 3, 8, 1, 0, 0, 1],
                "sales": [1000, 1000, 1000, 300, 800, 100, 0, 0, 10],
            }
        )
        segments = abc_xyz_segments(daily).set_index("item_key")
        self.assertEqual(segments.loc["A", "abc"], "A")
        self.assertEqual(segments.loc["A", "xyz"], "X")
        self.assertIn(segments.loc["C", "xyz"], {"Y", "Z"})

    def test_productivity_labels_and_clustering(self) -> None:
        sales = pd.DataFrame(
            {
                "item_key": ["A", "A", "B", "C", "D"],
                "date": pd.date_range("2026-10-01", periods=5),
                "qty": [10, 9, 3, 1, 0],
                "sales": [1000, 900, 300, 100, 0],
            }
        )
        features = product_feature_table(sales)
        labeled = label_productivity(features)
        clustered = cluster_products(labeled)
        self.assertIn("productivity_label", labeled.columns)
        self.assertIn("cluster", clustered.columns)
        self.assertEqual(len(clustered), features["item_key"].nunique())

    def test_association_rules_from_orders(self) -> None:
        orders = pd.DataFrame(
            {
                "order_id": ["1", "1", "2", "2", "3", "3", "4"],
                "item_key": ["A", "B", "A", "B", "A", "C", "C"],
            }
        )
        rules = association_rules(orders, min_support=0.2, min_confidence=0.2)
        pairs = set(zip(rules["antecedent"], rules["consequent"]))
        self.assertIn(("A", "B"), pairs)


if __name__ == "__main__":
    unittest.main()

