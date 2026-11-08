import unittest

import pandas as pd

from src.core import instant as I
from src.core import order_ops as O
from tests.test_instant import RAW

EXTRA = {
    "A1": ("Online Payment", "1300 gr", "2026-10-05 10:30"),
    "A2": ("QRIS", "2600 gr", "2026-10-06 23:59"),
    "A3": ("Online Payment", "1300 gr", "2026-10-06 23:59"),
    "B1": ("QRIS", "60500 gr", "2026-10-07 23:59"),
    "B2": ("Online Payment", "25000 gr", "2026-10-07 23:59"),
}


class OrderOpsTest(unittest.TestCase):
    def setUp(self):
        raw = RAW.copy()
        raw["Metode Pembayaran"] = raw["No. Pesanan"].map(lambda o: EXTRA[o][0])
        raw["Total Berat"] = raw["No. Pesanan"].map(lambda o: EXTRA[o][1])
        raw["Pesanan Harus Dikirimkan Sebelum (Menghindari keterlambatan)"] = raw["No. Pesanan"].map(lambda o: EXTRA[o][2])
        self.orders = I.order_frame(I.instant_lines(raw))

    def test_payment_cancel_rates(self):
        pay = O.payment_table(self.orders).set_index("Metode pembayaran")
        self.assertEqual(pay.loc["Online Payment", "Invoice"], 3)
        self.assertAlmostEqual(pay.loc["Online Payment", "% batal"], 200 / 3)
        self.assertAlmostEqual(pay.loc["Online Payment", "% batal belum bayar"], 100 / 3)
        self.assertEqual(pay.loc["QRIS", "% batal"], 0)

    def test_weight_bins(self):
        weight = O.weight_table(self.orders).set_index("Berat paket")
        self.assertEqual(weight.loc["< 5 kg", "Invoice"], 3)
        self.assertEqual(weight.loc["20–50 kg", "% batal"], 100)
        self.assertEqual(weight.loc["50–100 kg", "Lewat kargo (%)"], 100)

    def test_late_shipping_ignores_cancelled(self):
        ship = O.shipping_summary(self.orders)
        self.assertEqual(ship["dinilai"], 3)
        self.assertEqual(ship["terlambat"], 1)
        self.assertAlmostEqual(ship["median_jam"], 0.5833, places=3)
        self.assertEqual(int(O.late_by(self.orders, "layanan").set_index("Layanan").loc["Instant", "Terlambat"]), 1)


if __name__ == "__main__":
    unittest.main()
