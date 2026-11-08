import unittest

import pandas as pd

from src.core import instant as I


def _row(order, status, option, sku, qty, price, total, *, returned=0, reason="", day="2026-10-05 10:00", paid="2026-10-05 10:05", ship="2026-10-05 11:05"):
    return {"No. Pesanan": order, "Status Pesanan": status, "Alasan Pembatalan": reason, "Opsi Pengiriman": option, "Waktu Pesanan Dibuat": day,
            "Waktu Pembayaran Dilakukan": paid, "Waktu Pengiriman Diatur": ship, "Waktu Pesanan Selesai": "", "Nomor Referensi SKU": sku,
            "Nama Produk": f"Produk {sku}", "Nama Variasi": "", "Harga Setelah Diskon": price, "Jumlah": qty, "Returned quantity": returned,
            "Total Pembayaran": total, "Username (Pembeli)": order, "Kota/Kabupaten": "KAB. TANGERANG"}


RAW = pd.DataFrame([
    _row("A1", "Selesai", "Instant-SPX Instant", "100", 1, 50_000, 60_000),
    _row("A2", "Selesai", "Same Day-SPX Sameday", "200", 2, 20_000, 45_000, returned=1, ship="2026-10-05 15:05"),
    _row("A3", "Batal", "Instant Prioritas", "100", 1, 50_000, 55_000, reason="Pembatalan otomatis: belum dibayar", paid="", ship=""),
    _row("B1", "Selesai", "Hemat Kargo-JNE Trucking (JTR)", "300", 3, 300_000, 910_000),
    _row("B2", "Batal", "Reguler (Cashless)", "300", 1, 300_000, 310_000, reason="Perlu mengubah pesanan", paid="", ship=""),
])


class InstantTest(unittest.TestCase):
    def setUp(self):
        self.lines = I.instant_lines(RAW)
        self.orders = I.order_frame(self.lines)

    def test_service_classification(self):
        self.assertEqual(I.service_of("Instant Prioritas-GoSend Instant Prioritas"), "Instant Prioritas")
        self.assertEqual(I.service_of("Same Day-GrabExpress Sameday"), "Same Day")
        self.assertEqual(I.service_of("Hemat Kargo-JNE Trucking (JTR)"), "Hemat Kargo / Trucking")
        self.assertEqual(I.courier_of("Instant-Gosend Instant"), "GoSend")

    def test_compare_instant_vs_other(self):
        stats = I.compare(self.orders)
        inst, other = stats["instan"], stats["lain"]
        self.assertEqual(inst["invoice"], 3)
        self.assertEqual(inst["batal"], 1)
        self.assertEqual(inst["belum_bayar"], 1)
        self.assertAlmostEqual(inst["sales_bersih"], 60_000 + 45_000 - 20_000)
        self.assertAlmostEqual(other["sales_bersih"], 910_000)
        self.assertAlmostEqual(inst["proses_median"], 3.0)
        self.assertEqual(inst["proses_lambat"], 1)

    def test_tables(self):
        services = I.service_table(self.orders)
        self.assertEqual(services["Layanan"].iloc[0], "Instant")
        self.assertAlmostEqual(services["Kontribusi sales (%)"].sum(), 100.0)
        top = I.top_products(self.lines)
        self.assertEqual(list(top["SKU"]), ["100", "200"])
        self.assertAlmostEqual(top.set_index("SKU").loc["100", "Porsi instan dari sales SKU (%)"], 100.0)
        daily = I.daily_table(self.orders)
        self.assertAlmostEqual(daily["Porsi instan (%)"].iloc[0], 60.0)


if __name__ == "__main__":
    unittest.main()
