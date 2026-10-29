import unittest
import tempfile
from pathlib import Path

import pandas as pd

from src.movement import compare_runs, frame_from_stock, load_run, record_run, setup_notes


def _stock(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class MovementTest(unittest.TestCase):
    def test_compare_naik_turun_baru_dan_keluar(self) -> None:
        previous = _stock(
            [
                {"item_key": "A", "item_label": "Semen", "pred_qty": 10, "pred_sales": 100, "safety_stock": 2, "stok_disarankan": 12, "rank_qty": 2, "rank_sales": 2},
                {"item_key": "B", "item_label": "Pasir", "pred_qty": 8, "pred_sales": 80, "safety_stock": 1, "stok_disarankan": 9, "rank_qty": 1, "rank_sales": 1},
            ]
        )
        current = _stock(
            [
                {"item_key": "A", "item_label": "Semen", "pred_qty": 14, "pred_sales": 140, "safety_stock": 2, "stok_disarankan": 16, "rank_qty": 1, "rank_sales": 1},
                {"item_key": "C", "item_label": "Cat", "pred_qty": 4, "pred_sales": 40, "safety_stock": 1, "stok_disarankan": 5, "rank_qty": 2, "rank_sales": 2},
            ]
        )
        detail = compare_runs(current, previous, "qty")
        by_key = detail.set_index("item_key")
        self.assertEqual(by_key.loc["A", "arah"], "Naik")
        self.assertEqual(int(by_key.loc["A", "delta_qty"]), 4)
        self.assertEqual(int(by_key.loc["A", "rank_shift"]), 1)
        self.assertEqual(by_key.loc["B", "arah"], "Keluar")
        self.assertEqual(by_key.loc["C", "arah"], "Baru")

    def test_geser_saat_qty_tetap_tetapi_stok_berubah(self) -> None:
        previous = _stock(
            [
                {"item_key": "A", "item_label": "Semen", "pred_qty": 10, "pred_sales": 100, "safety_stock": 2, "stok_disarankan": 12, "rank_qty": 1, "rank_sales": 1},
            ]
        )
        current = _stock(
            [
                {"item_key": "A", "item_label": "Semen", "pred_qty": 10, "pred_sales": 100, "safety_stock": 4, "stok_disarankan": 14, "rank_qty": 1, "rank_sales": 1},
            ]
        )
        detail = compare_runs(current, previous, "qty")
        self.assertEqual(detail.loc[0, "arah"], "Geser")
        self.assertEqual(int(detail.loc[0, "delta_stok"]), 2)
        self.assertEqual(int(detail.loc[0, "delta_qty"]), 0)

    def test_catatan_data_latih_dan_penyimpanan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            first = _stock(
                [
                    {"item_key": "A", "item_label": "Semen", "pred_qty": 10, "pred_sales": 100, "safety_stock": 1, "stok_disarankan": 11, "rank_qty": 1, "rank_sales": 1},
                ]
            )
            first_id, previous = record_run(first, {"period": "bulan", "metric": "qty", "service": 95, "months": ["2026-09"]}, directory)
            self.assertTrue(first_id)
            self.assertIsNone(previous)
            second_id, previous = record_run(first, {"period": "bulan", "metric": "qty", "service": 95, "months": ["2026-09", "2026-10"]}, directory)
            self.assertEqual(previous, first_id)
            loaded = load_run(first_id, directory)
            self.assertIsNotNone(loaded)
            meta, frame = loaded
            self.assertEqual(meta["months"], ["2026-09"])
            self.assertEqual(int(frame.loc[0, "pred_qty"]), 10)
            notes = setup_notes(
                {"period": "bulan", "metric": "qty", "service": 95, "months": ["2026-09", "2026-10"], "exclude_return_cancel": False, "window_start": "2026-10-27"},
                {"period": "bulan", "metric": "qty", "service": 95, "months": ["2026-09"], "exclude_return_cancel": False, "window_start": "2026-10-26"},
            )
            self.assertTrue(any("bertambah" in note and "Oktober 2026" in note for note in notes))
            self.assertTrue(any("horizon" in note for note in notes))
            self.assertTrue(frame_from_stock(pd.DataFrame()).empty)
            self.assertEqual(record_run(pd.DataFrame(), {}, directory), ("", None))


if __name__ == "__main__":
    unittest.main()
