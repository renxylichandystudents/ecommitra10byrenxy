"""ads_inputs: suntik CTR ke frame produk untuk Push skor."""

from __future__ import annotations

import pandas as pd

from src.ui.ads_inputs import _ctr_by_product_code, _normalize_ctr


def test_normalize_ctr_fraction_and_percent():
    assert abs(_normalize_ctr(1.5) - 0.015) < 1e-9
    assert abs(_normalize_ctr(0.8) - 0.008) < 1e-9
    assert _normalize_ctr("") != _normalize_ctr("")  # NaN
    assert _normalize_ctr(-1) != _normalize_ctr(-1)


def test_ctr_by_product_code_from_overall():
    overall = pd.DataFrame([
        {"product_code": "48213626135", "ctr": 1.2, "_submitted_at": "2026-11-27"},
        {"product_code": "48213626135", "ctr": 0.8, "_submitted_at": "2026-11-28"},
        {"product_code": "x", "ctr": 2.0, "_submitted_at": "2026-11-28"},
    ])
    got = _ctr_by_product_code(overall)
    assert "48213626135" in got
    assert abs(got["48213626135"] - 0.008) < 1e-9  # 0,8% → 0,008
    assert "x" not in got


def test_ctr_missing_column_returns_empty():
    assert _ctr_by_product_code(pd.DataFrame([{"product_code": "1", "cost": 1}])) == {}
