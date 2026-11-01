import unittest
from datetime import date

import pandas as pd

from src.core.naming import allowed_keyword, category_label, extract_packing_tag, foreign_words, vocabulary, with_tag
from src.core.nlp_competitor import build_name_recommendations
from src.core.recommendations import exposure_plan, flash_sale_plan


class PackingTagTest(unittest.TestCase):
    CASES = [
        ("Kloset Duduk Tidy FSA0089 [INCLUDE PACKING KAYU]", "Kloset Duduk Tidy FSA0089", "[INCLUDE PACKING KAYU]"),
        ("Wastafel Granite [INCLUDE BUBBLE WRAP]", "Wastafel Granite", "[INCLUDE BUBBLE WRAP]"),
        ("Pompa Semi Jet Aquamax Kuning- Proteksi Ganda Extra Bubble Wrap", "Pompa Semi Jet Aquamax Kuning", "Proteksi Ganda Extra Bubble Wrap"),
        ("Rak Dinding Zehn Extra Bubble Wrap", "Rak Dinding Zehn", "Extra Bubble Wrap"),
        ("Pintu PVC 70x195 (Packing Kayu)", "Pintu PVC 70x195", "(Packing Kayu)"),
        ("Kran Air Tembok + Packing Kayu", "Kran Air Tembok", "+ Packing Kayu"),
        ("Closet Jongkok include packing kayu", "Closet Jongkok", "include packing kayu"),
        ("Water Heater 15L - Free Bubble Wrap", "Water Heater 15L", "Free Bubble Wrap"),
        ("Jendela UPVC [Free Packing Kayu] Putih", "Jendela UPVC Putih", "[Free Packing Kayu]"),
        ("Bathtub Akrilik [INCLUDE PACKING KAYU] [INCLUDE BUBBLE WRAP]", "Bathtub Akrilik", "[INCLUDE PACKING KAYU] [INCLUDE BUBBLE WRAP]"),
        ("Lem Silicone Sealant 300ml - Dextone", "Lem Silicone Sealant 300ml - Dextone", None),
        ("Pintu Kayu Jati Solid 80x200", "Pintu Kayu Jati Solid 80x200", None),
    ]

    def test_variants(self):
        for name, clean, tag in self.CASES:
            with self.subTest(name=name):
                self.assertEqual(extract_packing_tag(name), (clean, tag))

    def test_with_tag_appends_original_and_respects_limit(self):
        title = with_tag("Kloset Duduk Tidy " * 10, "[INCLUDE PACKING KAYU]", 60)
        self.assertTrue(title.endswith("[INCLUDE PACKING KAYU]"))
        self.assertLessEqual(len(title), 60)
        self.assertEqual(with_tag("Rak Dinding", None, 60), "Rak Dinding")


class VocabularyTest(unittest.TestCase):
    def test_packing_not_keyword_and_foreign_words(self):
        vocab = vocabulary("Kloset Duduk Tidy FSA0089 Closet One Piece", "", "", {"tidy"})
        self.assertFalse(allowed_keyword("include packing kayu", vocab))
        self.assertFalse(allowed_keyword("packing kayu", vocab))
        self.assertTrue(allowed_keyword("kloset duduk", vocab))
        self.assertEqual(foreign_words("Tidy Kloset Duduk Kayu", vocab), ["kayu"])
        self.assertEqual(foreign_words("Water Heater 15/30L", vocabulary("Water Heater 15/30L", "", "", set())), [])

    def test_category_label_ignores_packing(self):
        self.assertEqual(category_label("Kloset Duduk Tidy [INCLUDE PACKING KAYU]"), "kloset")
        self.assertEqual(category_label("Pompa Semi Jet - Proteksi Ganda Extra Bubble Wrap"), "pompa air")
        self.assertNotIn("packing", category_label("Dudukan Anak Ceramax [INCLUDE PACKING KAYU]"))


def _own(*names):
    return pd.DataFrame(
        {
            "item_key": [str(i) for i in range(len(names))],
            "sku": [str(100 + i) for i in range(len(names))],
            "product_name": list(names),
            "variation": [""] * len(names),
            "qty_total": [10.0] * len(names),
        }
    )


class NameRecommendationTest(unittest.TestCase):
    def test_kayu_case(self):
        name = "Kloset Toilet WC Duduk Tidy FSA0089 Closet One Piece Washdown As 25cm - Garansi 15 Tahun [INCLUDE PACKING KAYU]"
        comp = pd.DataFrame({"product_name": ["Kloset Duduk Kayu Jati Include Packing Kayu", "Closet Duduk Packing Kayu Murah"], "shop_name": ["A", "B"]})
        recs, _note = build_name_recommendations(_own(name), None, comp, {}, {"merek": ["Tidy"]})
        row = recs.iloc[0]
        new = row["Rekomendasi nama baru"]
        self.assertTrue(new.endswith("[INCLUDE PACKING KAYU]"))
        self.assertNotIn("kayu", new.replace("[INCLUDE PACKING KAYU]", "").lower())
        self.assertNotIn("packing", (row["Kata kunci utama"] + row["Kata kunci pendukung"]).lower())
        self.assertNotIn("Kloset Duduk Kayu", new)

    def test_seasee_case(self):
        name = "All Variant Hand Filter 3 Pcs Shower Ceramax Looma"
        comp = pd.DataFrame(
            {
                "product_name": ["[All Variant] SEASEE Shower Filter Kit - Basic", "SEASEE Monster Multipurpose Filter Kit", "SEASEE Shower Filter Refill"],
                "shop_name": ["Seasee Official Store"] * 3,
                "rank": [1, 2, 3],
            }
        )
        recs, _note = build_name_recommendations(_own(name), None, comp, {}, {"merek": ["Ceramax"]})
        row = recs.iloc[0]
        self.assertNotIn("seasee", row["Rekomendasi nama baru"].lower())
        self.assertNotIn("seasee", (row["Kata kunci utama"] + row["Kata kunci pendukung"]).lower())
        self.assertIn(row["Status saran"], {"Siap pakai", "Perlu cek manual"})


def _table(stok, butuh):
    return pd.DataFrame(
        {
            "item_key": ["a", "b"],
            "sku": ["a", "b"],
            "product_name": ["Kloset Duduk [INCLUDE PACKING KAYU]", "Pompa Air Semi Jet"],
            "stok": stok,
            "ss": [2.0, 2.0],
            "m_butuh": butuh,
            "ada_data_stok": [True, True],
            "harga_bersih": [1_000_000.0, 500_000.0],
            "qty_total": [10.0, 5.0],
            "pred_qty": [10.0, 5.0],
            "sales_total": [10_000_000.0, 2_500_000.0],
            "m_status": ["Aman", "Aman"],
            "label": [[], []],
            "label_text": ["", ""],
        }
    )


class FlashAndExposureTest(unittest.TestCase):
    PARAMS = {"margin": {"hpp_pct_harga": 70, "margin_min_pct": 5}, "shopee": {"flash_sale_diskon_pct": [10]}}

    def test_flash_never_empty_when_selling(self):
        plan = flash_sale_plan(_table([5.0, 3.0], [20.0, 20.0]), start=date(2026, 11, 2), params=self.PARAMS, days=3)
        self.assertFalse(plan.empty)
        self.assertTrue(plan["Alasan"].str.startswith("Stok terbatas").all())
        surplus = flash_sale_plan(_table([100.0, 3.0], [20.0, 20.0]), start=date(2026, 11, 2), params=self.PARAMS, days=3)
        self.assertTrue(surplus["Alasan"].str.startswith("Surplus").all())

    def test_exposure_hook_uses_clean_category(self):
        plan = exposure_plan(_table([100.0, 100.0], [5.0, 5.0]), names=None, cancel_reasons={"a": ["Ingin mengubah alamat"]}, start=date(2026, 11, 1), ad_days=[], flash=None)
        hooks = " ".join(plan["Hook masalah"]).lower()
        self.assertNotIn("packing", hooks)
        self.assertNotIn("alamat", hooks)
        self.assertIn("kloset", hooks)

    def test_month_grid_monday_first(self):
        from src.ui.rekomendasi import month_grid

        grid = month_grid(2026, 11)
        self.assertEqual(len(grid[0]), 7)
        first = next(d for d in grid[0] if d is not None)
        self.assertEqual(first, date(2026, 11, 1))
        self.assertEqual(grid[0].index(first), 6)


if __name__ == "__main__":
    unittest.main()
