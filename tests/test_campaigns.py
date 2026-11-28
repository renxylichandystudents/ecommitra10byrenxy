import unittest
from datetime import date

import pandas as pd

from src.core import campaigns as C


def camp(cid, mulai, selesai, stopped=None, **extra):
    row = {"id": cid, "nama": f"c{cid}", "mulai": mulai, "selesai": selesai, "dihentikan": stopped}
    row.update(extra)
    return row


class CampaignTest(unittest.TestCase):
    def test_status_and_current(self):
        today = date(2026, 11, 8)
        items = [camp(1, "2026-11-01", "2026-11-07"), camp(2, "2026-11-08", "2026-11-30"), camp(3, "2026-12-01", "2026-12-31"),
                 camp(4, "2026-11-01", "2026-11-30", stopped="2026-11-05 10:00")]
        self.assertEqual([C.status_of(c, today) for c in items], [C.DONE, C.RUNNING, C.SCHEDULED, C.STOPPED])
        self.assertEqual(C.current(items, today)["id"], 2)
        self.assertEqual(C.current(items[:1] + items[2:], today)["id"], 3)
        self.assertIsNone(C.current(items[:1], today))

    def test_add_stops_overlapping_live_campaign_only(self):
        today = date(2026, 11, 8)
        items = [camp(1, "2026-11-08", "2026-11-30"), camp(2, "2026-12-01", "2026-12-31")]
        out, stopped = C.add(items, {"nama": "baru", "mulai": date(2026, 11, 10), "selesai": date(2026, 11, 24)}, today=today, username="u", now="n")
        self.assertEqual([c["id"] for c in stopped], [1])
        self.assertEqual(out[-1]["id"], 3)
        self.assertEqual(out[-1]["mulai"], "2026-11-10")
        self.assertEqual(out[-1]["lifecycle"], C.EXPORTED)
        self.assertEqual(stopped[0]["lifecycle"], C.ENDED)
        self.assertIsNone(next(c for c in out if c["id"] == 2)["dihentikan"])
        self.assertEqual(C.current(out, today)["id"], 3)

    def test_stop_and_remove(self):
        items = [camp(1, "2026-11-08", "2026-11-30", produk=[{"Kode produk": "SKU1"}])]
        stopped = C.stop(items, 1, username="u", now="n")[0]
        self.assertEqual(C.status_of(stopped, date(2026, 11, 9)), C.STOPPED)
        self.assertEqual(stopped["lifecycle"], C.ENDED)
        self.assertEqual(stopped["freed_skus"], ["SKU1"])
        self.assertEqual(C.remove(items, 1), [])

    def test_compare_budgets_ignores_small_changes(self):
        saved = pd.DataFrame({"Iklan": ["A", "B", "C"], "Budget harian usulan": [100_000, 50_000, 0]})
        fresh = pd.DataFrame({"Iklan": ["A", "B", "D"], "Budget harian usulan": [110_000, 80_000, 30_000]})
        diff = C.compare_budgets(saved, fresh).set_index("Iklan")
        self.assertFalse(diff.loc["A", "Berubah"])
        self.assertTrue(diff.loc["B", "Berubah"])
        self.assertFalse(diff.loc["C", "Berubah"])
        self.assertTrue(diff.loc["D", "Berubah"])


class AdsOsLifecycleTest(unittest.TestCase):
    def test_learning_lock_seven_days(self):
        c = camp(1, "2026-11-01", "2026-11-30", lifecycle=C.EXPORTED)
        self.assertEqual(C.learning_exit_date(c), date(2026, 11, 7))
        self.assertTrue(C.in_learning(c, date(2026, 11, 1)))
        self.assertTrue(C.in_learning(c, date(2026, 11, 7)))
        self.assertFalse(C.in_learning(c, date(2026, 11, 8)))
        self.assertEqual(C.lifecycle_of(c, date(2026, 11, 3)), C.LEARNING_LOCKED)
        self.assertEqual(C.lifecycle_of(c, date(2026, 11, 8)), C.STABLE)

    def test_propose_auto_end_not_during_learning_unless_stock(self):
        c = camp(1, "2026-11-01", "2026-11-30", lifecycle=C.EXPORTED, produk=[{"Kode produk": "A"}])
        self.assertIsNone(C.propose_auto_end(c, date(2026, 11, 3), roas=2.0, safe_bep=8.0, underperform_days=10))
        stock = C.propose_auto_end(c, date(2026, 11, 3), stock_critical=True)
        self.assertIsNotNone(stock)
        self.assertTrue(stock["konfirmasi_wajib"])

    def test_propose_auto_end_after_learning_roas_below_bep(self):
        c = camp(1, "2026-11-01", "2026-11-30", lifecycle=C.STABLE, produk=[{"Kode produk": "SKU9"}])
        prop = C.propose_auto_end(
            c, date(2026, 11, 20), roas=3.0, safe_bep=8.0, underperform_days=7,
        )
        self.assertIsNotNone(prop)
        self.assertEqual(prop["lifecycle"], C.ENDING_PROPOSED)
        self.assertIn("SKU9", prop["skus"])
        marked = C.apply_end_proposal(c, prop)
        self.assertEqual(marked["lifecycle"], C.ENDING_PROPOSED)

    def test_skip_and_keep_override_block_auto_end(self):
        c = camp(1, "2026-11-01", "2026-11-30", lifecycle=C.STABLE)
        skipped = C.set_override(c, C.OVERRIDE_SKIP_AUTO_END, username="u", now="n")
        self.assertIsNone(C.propose_auto_end(skipped, date(2026, 11, 20), roas=1.0, safe_bep=8.0, underperform_days=10))
        kept = C.set_override(
            {**c, "lifecycle": C.ENDING_PROPOSED, "end_proposal": {"alasan": ["x"]}},
            C.OVERRIDE_KEEP, username="u", now="n",
        )
        self.assertEqual(kept["lifecycle"], C.STABLE)
        self.assertIsNone(C.propose_auto_end(kept, date(2026, 11, 20), roas=1.0, safe_bep=8.0, underperform_days=10))

    def test_confirm_end_frees_skus(self):
        items = [camp(1, "2026-11-01", "2026-11-30", lifecycle=C.ENDING_PROPOSED,
                      produk=[{"Kode produk": "P1"}, {"Kode produk": "P2"}],
                      iklan=[{"key": "produk:P3", "Kode produk": "P3"}])]
        out, ended = C.confirm_end(items, 1, username="u", now="n", reason="ok")
        self.assertEqual(ended["lifecycle"], C.ENDED)
        self.assertEqual(set(ended["freed_skus"]), {"P1", "P2", "P3"})
        self.assertEqual(C.lifecycle_of(out[0], date(2026, 11, 20)), C.ENDED)
        self.assertEqual(C.free_skus_after_end(ended), {"P1", "P2", "P3"})

    def test_hub_status_empty_and_learning(self):
        empty = C.hub_status(None, date(2026, 11, 8))
        self.assertEqual(empty["state"], "empty")
        self.assertTrue(empty["next_cta"])
        c = camp(1, "2026-11-05", "2026-11-30", lifecycle=C.EXPORTED)
        hub = C.hub_status(c, date(2026, 11, 8))
        self.assertEqual(hub["lifecycle"], C.LEARNING_LOCKED)
        self.assertTrue(hub["learning"])

    def test_occupied_excluding_ended(self):
        ended = camp(1, "2026-11-01", "2026-11-10", stopped="n", lifecycle=C.ENDED,
                     produk=[{"Kode produk": "FREE"}])
        occ = C.occupied_excluding_ended({"FREE", "BUSY"}, [ended], date(2026, 11, 20))
        self.assertEqual(occ, frozenset({"BUSY"}))


if __name__ == "__main__":
    unittest.main()
