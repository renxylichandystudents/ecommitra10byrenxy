import unittest
from pathlib import Path

import pandas as pd

from src.activity import ledger_from_raw, unpaid_buyer_table
from src.core.metrics import (
    METRIC_DEFINITIONS,
    ads_metrics,
    order_metrics,
    sales_gap_breakdown,
    sku_coverage,
)
from src.ingest import clean_order_frame
from src.library import month_status_counts

LIBRARY = Path(__file__).resolve().parents[1] / "uploads" / "library"


def _row(order, status, sku, qty, price, total, *, returned=0, reason="", buyer="a", day="2026-10-05 10:00"):
    return {
        "No. Pesanan": order,
        "Status Pesanan": status,
        "Alasan Pembatalan": reason,
        "Waktu Pesanan Dibuat": day,
        "Nomor Referensi SKU": sku,
        "Nama Produk": f"Produk {sku}",
        "Nama Variasi": "",
        "Harga Setelah Diskon": price,
        "Jumlah": qty,
        "Returned quantity": returned,
        "Total Pembayaran": total,
        "Username (Pembeli)": buyer,
    }


RAW = pd.DataFrame(
    [
        _row("A1", "Selesai", "100", 2, 50_000, 110_000, buyer="budi"),
        _row("A2", "Selesai", "100", 1, 50_000, 120_000, buyer="cici"),
        _row("A2", "Selesai", "200", 2, 30_000, 120_000, returned=1, buyer="cici"),
        _row("A3", "Selesai", "200", 3, 30_000, 85_000, returned=3, buyer="dedi"),
        _row("A4", "Batal", "100", 1, 50_000, 55_000, reason="Pembatalan otomatis: belum dibayar", buyer="eka"),
        _row("A5", "Batal", "200", 4, 30_000, 125_000, reason="Pembatalan otomatis: belum dibayar", buyer="budi"),
        _row("A6", "Batal", "100", 1, 50_000, 52_000, reason="Pembatalan otomatis: belum dibayar", buyer="budi"),
        _row("A7", "Batal", "300", 1, 10_000, 12_000, reason="Ubah alamat", buyer="fani"),
        _row("A8", "Sedang Dikirim", "300", 5, 10_000, 55_000, buyer="gita", day="2026-09-30 23:00"),
    ]
)


def _analysis_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Frame orders_all yang dipakai Ringkasan & Laporan (prepare_analysis_orders tanpa exclude)."""
    orders = clean_order_frame(raw)
    orders["qty"] = orders["gross_qty"]
    orders["sales"] = orders["gross_sales"]
    return orders.loc[orders["qty"] > 0].reset_index(drop=True)


class OrderMetricsTest(unittest.TestCase):
    def setUp(self):
        self.facts = order_metrics(ledger_from_raw(RAW), "2026-10-01", "2026-10-31")

    def test_counts_and_units(self):
        f = self.facts
        self.assertEqual(f["pesanan_semua"], 7)
        self.assertEqual(f["pesanan_batal"], 4)
        self.assertEqual(f["retur_unit"], 4.0)
        self.assertEqual(f["pesanan_retur_penuh"], 1)
        self.assertEqual(f["pesanan_retur"], 2)
        self.assertAlmostEqual(f["nominal_retur"], 4 * 30_000)
        self.assertAlmostEqual(f["tingkat_batal"], 4 / 7)

    def test_identities(self):
        f = self.facts
        self.assertAlmostEqual(f["sales_bersih"], f["sales_bruto"] - f["nominal_batal"] - f["nominal_retur"])
        self.assertEqual(f["pesanan_bersih"], f["pesanan_semua"] - f["pesanan_batal"] - f["pesanan_retur_penuh"])
        self.assertAlmostEqual(f["sales_bruto"], 110_000 + 120_000 + 85_000 + 55_000 + 125_000 + 52_000 + 12_000)
        self.assertAlmostEqual(f["qty_bersih"], (2 + 1 + 2 + 3) - 4)

    def test_unpaid_excludes_buyer_who_paid_same_sku(self):
        f = self.facts
        self.assertEqual(f["belum_bayar_semua"], 3)
        self.assertEqual(f["belum_bayar"], 2)
        self.assertEqual(f["belum_bayar_akun"], 2)
        table = unpaid_buyer_table(RAW, start="2026-10-01", end="2026-10-31")
        self.assertEqual(table["No. Pesanan"].nunique(), f["belum_bayar"])

    def test_period_filter(self):
        september = order_metrics(ledger_from_raw(RAW), "2026-09-01", "2026-09-30")
        self.assertEqual(september["pesanan_semua"], 1)
        self.assertEqual(september["pesanan_batal"], 0)

    def test_all_page_builders_identical(self):
        """Data (ledger), Ringkasan/Laporan (orders_all), Folder data (month_status_counts) memakai fungsi yang sama."""
        data_page = order_metrics(ledger_from_raw(RAW), "2026-10-01", "2026-10-31")
        summary_page = order_metrics(_analysis_frame(RAW), "2026-10-01", "2026-10-31")
        self.assertEqual(data_page, summary_page)
        october = RAW.loc[RAW["Waktu Pesanan Dibuat"].str.startswith("2026-10")]
        folder = month_status_counts(october)
        self.assertAlmostEqual(folder["sales_net"], data_page["sales_bersih"])
        self.assertEqual(folder["cancel_orders"], data_page["pesanan_batal"])
        self.assertEqual(folder["qty_return"], data_page["retur_unit"])

    def test_every_metric_has_definition(self):
        for key in ("pesanan_semua", "sales_bruto", "pesanan_batal", "retur_unit", "sales_bersih", "pesanan_bersih", "roas", "belum_bayar"):
            self.assertIn(key, METRIC_DEFINITIONS)


class SalesGapTest(unittest.TestCase):
    def test_gap_is_partial_return_minus_full_return_extras(self):
        gap = sales_gap_breakdown(ledger_from_raw(RAW), "2026-10-01", "2026-10-31")
        self.assertAlmostEqual(gap["selisih"], gap["retur_sebagian"] - gap["retur_penuh_ongkir_voucher"])
        self.assertAlmostEqual(gap["retur_sebagian"], 30_000)
        self.assertAlmostEqual(gap["retur_penuh_ongkir_voucher"], 85_000 - 90_000)
        self.assertAlmostEqual(gap["sales_lama"], 110_000 + 120_000)


class CoverageAndAdsTest(unittest.TestCase):
    def test_sku_coverage(self):
        cover = sku_coverage(ledger_from_raw(RAW), "2026-10-01", "2026-10-31", catalog=pd.DataFrame({"sku": ["100", "200", "300", "400"]}))
        self.assertEqual(cover["sku_terjual_bersih"], 2)
        self.assertEqual(cover["sku_non_batal"], 2)
        self.assertEqual(cover["sku_data_latih"], 3)
        self.assertEqual(cover["sku_katalog"], 4)

    def test_ads_roas(self):
        ads = pd.DataFrame([{"period": "2026-10-01", "product_code": "P1", "cost": 10_000.0, "ad_sales": 90_000.0}])
        stock = pd.DataFrame({"product_code": ["P1"], "sku": ["100"]})
        result = ads_metrics([ads], stock, ledger_from_raw(RAW), "2026-10-01", "2026-10-31")
        self.assertAlmostEqual(result["biaya_iklan"], 10_000.0)
        self.assertAlmostEqual(result["omzet_iklan"], 90_000.0)
        self.assertAlmostEqual(result["roas"], 9.0)

    def test_ads_share_uses_product_sales_basis(self):
        ads = pd.DataFrame([{"period": "2026-10-01", "product_code": "P1", "cost": 10_000.0, "ad_sales": 90_000.0}])
        stock = pd.DataFrame({"product_code": ["P1"], "sku": ["100"]})
        ledger = ledger_from_raw(RAW)
        result = ads_metrics([ads], stock, ledger, "2026-10-01", "2026-10-31")
        from src.core.metrics import net_sku_sales

        basis = float(net_sku_sales(ledger, "2026-10-01", "2026-10-31")["sales"].sum())
        self.assertAlmostEqual(result["sales_produk_bersih"], basis)
        self.assertAlmostEqual(result["porsi_sales_iklan_pct"], result["omzet_iklan"] / basis * 100)
        self.assertLessEqual(result["porsi_sales_iklan_pct"], 100.0)


@unittest.skipUnless((LIBRARY / "2026-10.pkl").exists(), "data latih Oktober 2026 tidak tersedia")
class October2026Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.library import load_months

        cls.raw, _ = load_months(["2026-10"])

    def test_target_outlook_uses_sales_bersih(self):
        from datetime import date

        from src.ui.targets_view import month_outlook

        outlook = month_outlook(_analysis_frame(self.raw.drop_duplicates()), None, date(2026, 10, 15))
        self.assertAlmostEqual(outlook["mtd"], 2_848_905_957, places=0)
        self.assertAlmostEqual(outlook["faktor"], outlook["mtd"] / outlook["mtd_produk"], places=6)

    def test_pages_identical_on_real_data(self):
        data_page = order_metrics(ledger_from_raw(self.raw), "2026-10-01", "2026-10-31")
        summary_page = order_metrics(_analysis_frame(self.raw.drop_duplicates()), "2026-10-01", "2026-10-31")
        for key, value in data_page.items():
            self.assertAlmostEqual(float(value), float(summary_page[key]), places=2, msg=key)
        self.assertAlmostEqual(data_page["sales_bersih"], data_page["sales_bruto"] - data_page["nominal_batal"] - data_page["nominal_menunggu_bayar"]
                               - data_page["nominal_retur"])
        self.assertAlmostEqual(data_page["sales_bersih"], 2_848_905_957, places=0)
        self.assertEqual(data_page["pesanan_menunggu_bayar"], 6)
        unpaid = unpaid_buyer_table(self.raw, months=["2026-10"])
        self.assertEqual(unpaid["No. Pesanan"].nunique(), data_page["belum_bayar"])


if __name__ == "__main__":
    unittest.main()
