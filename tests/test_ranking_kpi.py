import io
import unittest

import numpy as np
import pandas as pd

from src.core import ranking_kpi as K


def rows(periode, kategori, grup, ours_rank, *, dasar="", n=12, sales=True):
    out = []
    for r in range(1, n + 1):
        out.append({"periode": periode, "daftar": 1, "kategori": kategori, "grup": grup, "dasar": dasar, "rank": r, "change": "",
                    "shop": f"Toko {r}", "product": f"Kloset {r}", "ours": False,
                    "sales": 1000.0 / r if sales else np.nan, "qty": 100.0 / r if sales else np.nan, "views": 5000.0 / r if sales else np.nan})
    if ours_rank:
        out.append({"periode": periode, "daftar": 1, "kategori": kategori, "grup": grup, "dasar": dasar, "rank": ours_rank, "change": "",
                    "shop": "Mitra10 Official Store", "product": "Kloset Mitra", "ours": True,
                    "sales": 50.0 if sales else np.nan, "qty": 5.0 if sales else np.nan, "views": 400.0 if sales else np.nan})
    return pd.DataFrame(out)


class PeriodTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(K.parse_period("2026-07"), "2026-07")
        self.assertEqual(K.parse_period("07/2026"), "2026-07")
        self.assertEqual(K.parse_period("Juli 2026"), "2026-07")
        self.assertEqual(K.parse_period("Q3 2026"), "2026-Q3")
        self.assertEqual(K.parse_period("Kuartal 3 2026"), "2026-Q3")
        self.assertEqual(K.parse_period("Q4 OKT - DES", 2026), "2026-Q4")
        self.assertEqual(K.parse_period("Jul - Sep 2026"), "2026-Q3")
        self.assertEqual(K.parse_period("Semester 2 2026"), "2026-S2")
        self.assertEqual(K.parse_period("2026"), "2026")

    def test_months_and_contains(self):
        self.assertEqual(K.months_of("2026-Q3"), [(2026, 7), (2026, 8), (2026, 9)])
        self.assertTrue(K.contains("2026-S2", "2026-Q3"))
        self.assertTrue(K.contains("2026", "2026-08"))
        self.assertFalse(K.contains("2026-Q2", "2026-07"))
        self.assertEqual(K.period_label("2026-Q3"), "Q3 2026 (Jul–Sep)")


class ParseTest(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(K.parse_number("Rp1.234.567"), 1234567)
        self.assertEqual(K.parse_number("1,2jt"), 1_200_000)
        self.assertEqual(K.parse_number("15,3RB"), 15_300)
        self.assertEqual(K.parse_number("12,5"), 12.5)
        self.assertTrue(np.isnan(K.parse_number("-")))

    def test_shopee_two_row_export_with_metrics(self):
        raw = [
            ["Ranking", "Change of Rank", "Shop Name", "Products Name", "Sales", "Qty", "Views"],
            [1, "+2", "Toko A", None, "Rp1.000.000", 100, "5,1RB"],
            [None, None, None, "Kloset Duduk A", None, None, None],
            [2, "-1", "Toko B", None, "Rp800.000", 80, 4000],
            [None, None, None, "Kloset Duduk B", None, None, None],
            ["My Shop", None, None, None, None, None, None],
            [262, "My Shop", "Mitra10 Official Store", None, "Rp50.000", 5, 300],
            [None, None, None, "Kloset Mitra10", None, None, None],
            ["Ranking", "Change of Rank", "Shop Name", "Products Name", "Sales", "Qty", "Views"],
            [1, "", "Toko C", None, 10, 1, 10],
            [None, None, None, "Water Heater C", None, None, None],
        ]
        buf = io.BytesIO()
        with pd.ExcelWriter(buf) as w:
            pd.DataFrame(raw).to_excel(w, sheet_name="Kamar Mandi", header=False, index=False)
        out = K.parse_upload(buf.getvalue(), "rank.xlsx")
        self.assertEqual(len(out), 4)
        mine = out.loc[out["ours"]].iloc[0]
        self.assertEqual(mine["rank"], 262)
        self.assertEqual(mine["sales"], 50_000)
        self.assertEqual(out.loc[out["product"] == "Kloset Duduk A", "views"].iloc[0], 5100)
        self.assertEqual(out["daftar"].nunique(), 2)
        self.assertEqual(set(out["kategori"]), {"Kamar Mandi"})

    def test_flat_csv_with_category_path_and_basis(self):
        text = ("Periode,Kategori,Dasar Ranking,Ranking,Nama Toko,Nama Produk,Sales,Qty,Views\n"
                "Q3 2026,Perlengkapan Rumah > Kamar Mandi,Sales,1,Toko A,Kloset A,100,10,1000\n"
                "Q3 2026,Perlengkapan Rumah > Kamar Mandi,Sales,40,Mitra10,Kloset M,10,1,100\n"
                "Q3 2026,Elektronik > Peralatan Rumah Tangga Besar,Qty,3,Mitra10,Water Heater,5,2,30\n")
        out = K.parse_upload(text.encode(), "rank.csv")
        self.assertEqual(list(out["grup"]), [K.HL, K.HL, K.EL])
        self.assertEqual(out["kategori"].iloc[0], "Kamar Mandi")
        self.assertEqual(list(out["dasar"]), ["Sales", "Sales", "Qty"])
        self.assertEqual(K.parse_period(out["periode"].iloc[0]), "2026-Q3")
        self.assertEqual(out["daftar"].nunique(), 2)


class RecapTest(unittest.TestCase):
    def setUp(self):
        self.master = K.default_master()
        data = pd.concat([
            rows("2026-07", "Kamar Mandi", K.HL, 30),
            rows("2026-08", "Kamar Mandi", K.HL, 12),
            rows("2026-Q2", "Kamar Mandi", K.HL, 80),
            rows("2026-Q3", "Peralatan Rumah Tangga Besar", K.EL, 5),
            rows("2026-Q3", "TV & Aksesoris", K.EL, None),
        ], ignore_index=True)
        self.summary = K.list_summary(data)

    def test_summary_metrics(self):
        r = self.summary.set_index(["periode", "kategori"]).loc[("2026-08", "Kamar Mandi")]
        self.assertEqual(r["peringkat"], 12)
        self.assertEqual(r["status"], "Dekat")
        self.assertEqual(r["sales_10"], 100.0)
        self.assertEqual(r["sales_kita"], 50.0)

    def test_quarter_from_months_and_year(self):
        v = K.value_for(self.summary, "2026-Q3", K.HL, "Kamar Mandi", K.ANY_BASIS)
        self.assertEqual(v["peringkat"], 12)
        self.assertEqual(v["terbaik"], 12)
        self.assertEqual(v["rata"], 21)
        self.assertEqual(v["cakupan"], 2)
        y = K.value_for(self.summary, "2026", K.HL, "Kamar Mandi", K.ANY_BASIS)
        self.assertEqual(y["peringkat"], 12)          # periode terakhir = Agustus
        self.assertEqual(y["terbaik"], 12)

    def test_tracked_categories(self):
        cats = K.tracked_categories(self.summary, self.master)
        hl = cats.loc[cats["Grup"] == K.HL, "Kategori"].tolist()
        self.assertIn("Dekorasi", hl)                       # semua Home & Living tetap dipantau walau tanpa data
        el = cats.loc[cats["Grup"] == K.EL, "Kategori"].tolist()
        self.assertIn("Peralatan Rumah Tangga Besar", el)  # ada produk kita
        self.assertNotIn("TV & Aksesoris", el)              # tidak ada produk kita

    def test_recap_and_insights(self):
        wide, long = K.recap(self.summary, self.master, "Kuartal", 2026, K.ANY_BASIS)
        line = wide.set_index("Kategori").loc["Kamar Mandi"]
        self.assertEqual(line["Q2 2026"], 80)
        self.assertEqual(line["Q3 2026"], 12)
        self.assertTrue(np.isnan(wide.set_index("Kategori").loc["Dekorasi", "Q3 2026"]))
        notes = K.insights(self.summary, self.master, "2026-Q3", K.ANY_BASIS, ["2026-Q2", "2026-Q3", "2026-07", "2026-08"])
        self.assertTrue(any("Naik dibanding Q2 2026" in n and "#80→#12" in n for n in notes))
        self.assertTrue(any("Peralatan Rumah Tangga Besar" in n for n in notes))

    def test_guess_category(self):
        g, k, _s = K.guess_category(["Kloset Duduk Toto", "Shower Set Wasser", "Kran Air Wastafel"], self.master)
        self.assertEqual((g, k), (K.HL, "Kamar Mandi"))


if __name__ == "__main__":
    unittest.main()
