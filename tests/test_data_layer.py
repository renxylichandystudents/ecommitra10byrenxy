from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.core.consolidation import consolidation_summary, stock_zero_streaks
from src.core.schemas import SOURCE_SPECS, SourceStatus, canonicalize_frame, status_for_frame
from src.core.storage import LocalDataStore


FIXTURES = Path(__file__).resolve().parent / "fixtures"


class SchemaTests(unittest.TestCase):
    def test_transaction_headers_are_detected(self) -> None:
        frame = pd.read_csv(FIXTURES / "transactions_fase1.csv")
        status = status_for_frame(frame, SOURCE_SPECS["transactions"])
        self.assertEqual(status, SourceStatus.READY)
        canonical, mapping = canonicalize_frame(frame, SOURCE_SPECS["transactions"])
        self.assertIn("order_id", canonical.columns)
        self.assertEqual(mapping["sku"], "Nomor Referensi SKU")

    def test_wrong_file_is_marked_check_columns(self) -> None:
        frame = pd.DataFrame({"Tanggal": ["2026-10-01"], "Total Pesanan": [1]})
        status = status_for_frame(frame, SOURCE_SPECS["stock"])
        self.assertEqual(status, SourceStatus.CHECK_COLUMNS)


class StorageTests(unittest.TestCase):
    def test_transactions_are_upserted_by_dedup_key(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            store = LocalDataStore(raw)
            first = pd.read_csv(FIXTURES / "transactions_fase1.csv")
            result = store.submit_source("transactions", first, filenames=["a.csv"], submitted_at="2026-10-01T08:00:00+07:00")
            self.assertEqual(result.rows_stored, 2)

            updated = first.copy()
            updated.loc[0, "Jumlah"] = 5
            result = store.submit_source(
                "transactions",
                updated,
                filenames=["b.csv"],
                submitted_at="2026-10-02T08:00:00+07:00",
            )
            saved = store.read_source("transactions")
            self.assertEqual(result.rows_stored, 2)
            self.assertEqual(float(saved.loc[saved["order_id"].eq("INV-1"), "qty"].iloc[0]), 5)

    def test_stock_submit_keeps_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            store = LocalDataStore(raw)
            stock = pd.read_csv(FIXTURES / "stock_fase1.csv")
            store.submit_source("stock", stock, filenames=["stok-1.csv"], submitted_at="2026-10-01T08:00:00+07:00")
            changed = stock.copy()
            changed.loc[changed["SKU"].eq("SKU-2"), "Stok: DC Cikupa"] = 0
            store.submit_source("stock", changed, filenames=["stok-2.csv"], submitted_at="2026-10-03T08:00:00+07:00")
            saved = store.read_source("stock")
            self.assertEqual(len(saved), 4)
            self.assertEqual(store.snapshot_count(), 2)
            streak = stock_zero_streaks(store).set_index("sku")
            self.assertIn("SKU-2", streak.index)
            self.assertEqual(int(streak.loc["SKU-2", "snapshots_zero"]), 2)

    def test_consolidation_summary_match_percentages(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            store = LocalDataStore(raw)
            store.submit_source(
                "transactions",
                pd.read_csv(FIXTURES / "transactions_fase1.csv"),
                submitted_at="2026-10-01T08:00:00+07:00",
            )
            store.submit_source(
                "stock",
                pd.read_csv(FIXTURES / "stock_fase1.csv"),
                submitted_at="2026-10-01T09:00:00+07:00",
            )
            ads = pd.DataFrame({"Kode Produk": ["P-1", "P-X"], "Dilihat": [100, 50], "Jumlah Klik": [10, 2]})
            store.submit_source("ads_auto", ads, submitted_at="2026-10-01T10:00:00+07:00")
            summary, metrics = consolidation_summary(store)
            self.assertEqual(len(summary), len(SOURCE_SPECS))
            self.assertEqual(metrics["sku_transaksi_cocok_stok_pct"], 100.0)
            self.assertEqual(metrics["produk_iklan_terpetakan_sku_pct"], 50.0)


if __name__ == "__main__":
    unittest.main()

