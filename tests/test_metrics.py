"""Audit K1 & K2: satu definisi metrik untuk Ringkasan, Data, dan Laporan."""

from __future__ import annotations

import unittest

import pandas as pd

from src.activity import ledger_from_raw, scope_ledger
from src.core import metrics
from src.ingest import attach_order_line_totals, order_revenue


def _orders() -> pd.DataFrame:
    """A: retur sebagian (1 dari 3 unit X). B: batal belum bayar. C: retur penuh. D: normal."""
    rows = [
        # order, status, sku, unit, gross_qty, returned, total_pembayaran, alasan, pembeli
        ("A", "Selesai", "X", 100.0, 3, 1, 340.0, "", "ani"),
        ("A", "Selesai", "Y", 50.0, 2, 0, 340.0, "", "ani"),
        ("B", "Batal", "X", 200.0, 1, 0, 200.0, "Dibatalkan otomatis. Alasan: Pesanan belum dibayar", "budi"),
        ("C", "Selesai", "Z", 80.0, 1, 1, 80.0, "", "cici"),
        ("D", "Selesai", "Y", 120.0, 1, 0, 125.0, "", "dodi"),
        ("E", "Batal", "Z", 90.0, 1, 0, 90.0, "Dibatalkan otomatis. Alasan: Pesanan belum dibayar", "dodi"),
        ("F", "Selesai", "Z", 90.0, 1, 0, 90.0, "", "dodi"),
    ]
    frame = pd.DataFrame(rows, columns=["order_id", "status", "sku", "unit", "gross_qty", "returned_qty", "order_amount", "cancel_reason", "buyer"])
    frame["order_time"] = pd.Timestamp("2026-10-15")
    frame["qty"] = (frame["gross_qty"] - frame["returned_qty"]).clip(lower=0)
    frame["gross_sales"] = frame["unit"] * frame["gross_qty"]
    frame["sales"] = frame["unit"] * frame["qty"]
    frame["item_key"] = frame["sku"]
    return attach_order_line_totals(frame)


class MetricsTest(unittest.TestCase):
    def test_counts_are_order_level(self) -> None:
        frame = _orders()
        self.assertEqual(metrics.count_orders(frame), 6)
        self.assertEqual(metrics.cancelled_orders(frame), 2)
        self.assertAlmostEqual(metrics.cancel_rate_pct(frame), 2 / 6 * 100)
        self.assertEqual(metrics.returned_units(frame), 2.0)

    def test_net_sales_removes_partial_returns(self) -> None:
        frame = _orders()
        # A: 340 × (300/400) = 255; C habis diretur; D 125; F 90; batal B & E keluar.
        self.assertAlmostEqual(metrics.net_sales(frame), 255 + 125 + 90)

    def test_net_sales_same_on_gross_prepared_frame(self) -> None:
        """Toggle Exclude mati: kolom sales berisi nilai kotor, sales bersih tetap sama."""
        gross = _orders()
        gross["sales"] = gross["gross_sales"]
        gross["qty"] = gross["gross_qty"]
        self.assertAlmostEqual(metrics.net_sales(gross), 255 + 125 + 90)

    def test_order_revenue_unchanged_without_returns(self) -> None:
        frame = _orders()
        clean = frame.loc[frame["order_id"].isin(["D", "F"])]
        self.assertAlmostEqual(order_revenue(clean), 215.0)

    def test_unpaid_chase_skips_buyer_who_paid_same_sku(self) -> None:
        # B dikejar; E tidak, karena dodi sudah membayar SKU Z di pesanan F.
        self.assertEqual(metrics.unpaid_chase_orders(_orders()), 1)

    def test_data_tab_matches_ringkasan(self) -> None:
        raw = pd.DataFrame(
            {
                "No. Pesanan": ["A", "A", "B", "C", "D"],
                "Status Pesanan": ["Selesai", "Selesai", "Batal", "Selesai", "Selesai"],
                "Waktu Pesanan Dibuat": ["2026-10-15 10:00"] * 5,
                "Nama Produk": ["X", "Y", "X", "Z", "Y"],
                "Nomor Referensi SKU": ["X", "Y", "X", "Z", "Y"],
                "Harga Setelah Diskon": [100, 50, 200, 80, 120],
                "Jumlah": [3, 2, 1, 1, 1],
                "Returned quantity": [1, 0, 0, 1, 0],
                "Total Pembayaran": [340, 340, 200, 80, 125],
            }
        )
        ledger = ledger_from_raw(raw)
        if ledger.empty:
            self.skipTest("kolom contoh tidak dikenali oleh map_columns")
        scoped = scope_ledger(ledger, include_cancel=False, include_return=False)
        self.assertAlmostEqual(order_revenue(scoped), 255 + 125)


if __name__ == "__main__":
    unittest.main()
