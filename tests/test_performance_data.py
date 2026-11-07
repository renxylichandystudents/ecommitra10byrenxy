import io
import tempfile
import unittest
from datetime import date

import pandas as pd

from src.core.performance import clean_performance, parse_day, perf_number
from src.core.schemas import SOURCE_SPECS
from src.core.storage import LocalDataStore, read_upload_file
from src.ui.analysis_dialog import store_performance

HEADER = ["Tanggal", "Total Penjualan (IDR)", "Total Pesanan", "Penjualan per Pesanan", "Total Pengunjung", "Tingkat Konversi Pesanan"]


def _shopee_export() -> bytes:
    """Bentuk ekspor performa Shopee: header, baris total bulanan, baris kosong, header berulang, lalu harian."""
    rows = [
        HEADER,
        ["01-10-2026-31-10-2026", "300.000.000", "30", "10.000.000,00", "3000", "1,00%"],
        [None] * len(HEADER),
        HEADER,
        ["01-10-2026", "100.000.000", "10", "10.000.000,00", "1000", "1,00%"],
        ["02-10-2026", "200.000.000", "20", "10.000.000,00", "2000", "1,50%"],
    ]
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, header=False, index=False)
    return buffer.getvalue()


class PerformanceDataTest(unittest.TestCase):
    def test_numbers_and_percent_indonesian_format(self):
        values = perf_number(pd.Series(["165.841.669", "727.375,74", "1,40%", "11057", "-"]))
        self.assertEqual(values.iloc[0], 165841669.0)
        self.assertAlmostEqual(values.iloc[1], 727375.74)
        self.assertAlmostEqual(values.iloc[2], 1.40)
        self.assertEqual(values.iloc[3], 11057.0)
        self.assertTrue(pd.isna(values.iloc[4]))

    def test_parse_day_rejects_ranges_and_headers(self):
        days = parse_day(pd.Series(["01-10-2026-31-10-2026", "Tanggal", "01-10-2026", "2026-10-02"]))
        self.assertTrue(pd.isna(days.iloc[0]))
        self.assertTrue(pd.isna(days.iloc[1]))
        self.assertEqual(days.iloc[2], pd.Timestamp("2026-10-01"))
        self.assertEqual(days.iloc[3], pd.Timestamp("2026-10-02"))

    def test_upload_keeps_daily_rows_only(self):
        spec = SOURCE_SPECS["performance"]
        frame = read_upload_file(_shopee_export(), "perfoma okt.xlsx", spec)
        self.assertEqual(frame["Tanggal"].tolist(), ["01-10-2026", "02-10-2026"])
        with tempfile.TemporaryDirectory() as folder:
            store = LocalDataStore(folder)
            result = store.submit_source("performance", frame, filenames=["perfoma okt.xlsx"])
            self.assertEqual(result.rows_stored, 2)

    def test_clean_stored_rows_and_summary(self):
        stored = pd.DataFrame(
            {
                "date": ["01-10-2026-31-10-2026", "Tanggal", "01-10-2026", "02-10-2026", "02-10-2026"],
                "visitors": ["3000", "Total Pengunjung", "1000", "1500", "2000"],
                "conversion_rate": ["1,00%", "Tingkat Konversi Pesanan", "1,00%", "1,20%", "1,50%"],
                "_submitted_at": ["a", "a", "a", "a", "b"],
            }
        )
        clean = clean_performance(stored)
        self.assertEqual(len(clean), 2)
        self.assertEqual(clean["visitors"].tolist(), [1000.0, 2000.0])
        summary = store_performance(stored, date(2026, 10, 3))
        self.assertEqual(summary["pengunjung"], 3000.0)
        self.assertAlmostEqual(summary["konversi"], 1.25)


class ExcelMemoTest(unittest.TestCase):
    def test_same_frame_returns_same_bytes(self):
        from src.utils.format import excel_bytes

        frame = pd.DataFrame({"SKU": ["A", "B"], "Sales value": [1000.0, 2000.0]})
        first = excel_bytes(frame)
        self.assertIs(excel_bytes(frame.copy()), first)
        changed = frame.copy()
        changed.loc[0, "Sales value"] = 1500.0
        self.assertIsNot(excel_bytes(changed), first)


if __name__ == "__main__":
    unittest.main()
