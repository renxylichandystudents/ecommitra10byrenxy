from datetime import date

import numpy as np
import pandas as pd

from src.ui.decision_view import _round_label, past_stock_path


def test_past_stock_path_from_uploads_and_sales():
    days = pd.date_range("2026-11-01", "2026-11-30")
    sold = pd.Series(0.0, index=days)
    sold["2026-11-09"], sold["2026-11-10"], sold["2026-11-13"] = 159, 21, 12
    hist = pd.DataFrame({"_submitted_at": ["2026-11-05 10:00", "2026-11-12 09:00"], "stok": [200, 195]})
    values, notes = past_stock_path(days, date(2026, 11, 14), 183.0, sold, hist)
    assert values[0] == 200 and "mundur" in notes[0]          # 1 Nov: sebelum unggahan pertama
    assert values[4] == 200 and "tercatat" in notes[4]        # 5 Nov: unggahan
    assert values[9] == 20                                    # 10 Nov: 200 − 159 − 21
    assert values[11] == 195                                  # 12 Nov: unggahan
    assert values[12] == 183 and values[13] == 183            # 13 Nov: 195 − 12; 14 Nov: stok hari ini
    assert np.isnan(values[14])                               # mulai besok = proyeksi prediksi


def test_past_stock_path_without_uploads_goes_back_from_today():
    days = pd.date_range("2026-11-01", "2026-11-30")
    sold = pd.Series(0.0, index=days)
    sold["2026-11-09"] = 10
    values, _ = past_stock_path(days, date(2026, 11, 14), 5.0, sold, None)
    assert values[0] == 15 and values[8] == 5 and values[13] == 5


def test_chart_labels_are_whole_numbers():
    assert _round_label(False)(10.6) == "11"
    assert _round_label(True)(5_169_499.6) == "5.169.500"
