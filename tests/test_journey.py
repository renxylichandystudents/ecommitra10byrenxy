import unittest
from datetime import date

from src.core.journey import (
    STATE_CURRENT,
    STATE_EMPTY,
    STATE_NEW_DATA,
    STATE_WAITING,
    analysis_state,
    next_run_keys,
    upload_due,
)


class NextRunKeysTest(unittest.TestCase):
    def test_new_month_joins(self):
        self.assertEqual(next_run_keys(["2026-09", "2026-10"], ["2026-09", "2026-10", "2026-11"]), ("2026-09", "2026-10", "2026-11"))

    def test_start_month_kept(self):
        self.assertEqual(next_run_keys(["2026-10"], ["2026-08", "2026-09", "2026-10", "2026-11"]), ("2026-10", "2026-11"))

    def test_no_previous_uses_all(self):
        self.assertEqual(next_run_keys([], ["2026-10", "2026-09", "tanpa-bulan"]), ("2026-09", "2026-10", "tanpa-bulan"))

    def test_undated_only_when_used_before(self):
        self.assertEqual(next_run_keys(["2026-10"], ["2026-10", "tanpa-bulan"]), ("2026-10",))


class AnalysisStateTest(unittest.TestCase):
    today = date(2026, 11, 8)

    def test_states(self):
        self.assertEqual(analysis_state(has_run=False, run_day=None, today=self.today, data_changed=False), STATE_EMPTY)
        self.assertEqual(analysis_state(has_run=True, run_day=self.today, today=self.today, data_changed=True), STATE_NEW_DATA)
        self.assertEqual(analysis_state(has_run=True, run_day=self.today, today=self.today, data_changed=False), STATE_CURRENT)
        self.assertEqual(analysis_state(has_run=True, run_day=date(2026, 11, 7), today=self.today, data_changed=False), STATE_WAITING)

    def test_upload_due_only_daily(self):
        self.assertTrue(upload_due("transactions", date(2026, 11, 7), self.today))
        self.assertFalse(upload_due("transactions", self.today, self.today))
        self.assertFalse(upload_due("stock", None, self.today))


if __name__ == "__main__":
    unittest.main()
