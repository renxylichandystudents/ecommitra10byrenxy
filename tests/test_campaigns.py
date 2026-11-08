import unittest
from datetime import date

import pandas as pd

from src.core import campaigns as C


def camp(cid, mulai, selesai, stopped=None):
    return {"id": cid, "nama": f"c{cid}", "mulai": mulai, "selesai": selesai, "dihentikan": stopped}


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
        self.assertIsNone(next(c for c in out if c["id"] == 2)["dihentikan"])
        self.assertEqual(C.current(out, today)["id"], 3)

    def test_stop_and_remove(self):
        items = [camp(1, "2026-11-08", "2026-11-30")]
        self.assertEqual(C.status_of(C.stop(items, 1, username="u", now="n")[0], date(2026, 11, 9)), C.STOPPED)
        self.assertEqual(C.remove(items, 1), [])

    def test_compare_budgets_ignores_small_changes(self):
        saved = pd.DataFrame({"Iklan": ["A", "B", "C"], "Budget harian usulan": [100_000, 50_000, 0]})
        fresh = pd.DataFrame({"Iklan": ["A", "B", "D"], "Budget harian usulan": [110_000, 80_000, 30_000]})
        diff = C.compare_budgets(saved, fresh).set_index("Iklan")
        self.assertFalse(diff.loc["A", "Berubah"])
        self.assertTrue(diff.loc["B", "Berubah"])
        self.assertFalse(diff.loc["C", "Berubah"])
        self.assertTrue(diff.loc["D", "Berubah"])


if __name__ == "__main__":
    unittest.main()
