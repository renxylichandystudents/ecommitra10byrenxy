import unittest

import numpy as np
import pandas as pd

from src.core.config import default_params
from src.core.service_level import MAX_PCT, MIN_PCT, recommended_service_level, safety_impact, z_value


class ServiceLevelTest(unittest.TestCase):
    def test_longer_period_never_raises_recommendation(self):
        params = default_params()
        values = [recommended_service_level(p, params).pct for p in ("bulan", "kuartal", "semester", "tahun")]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertTrue(all(MIN_PCT <= v <= MAX_PCT for v in values))

    def test_higher_holding_cost_lowers_recommendation(self):
        params = default_params()
        base = recommended_service_level("kuartal", params).pct
        params["gudang"]["biaya_simpan_pct_tahun"] = 60
        self.assertLess(recommended_service_level("kuartal", params).pct, base)

    def test_impact_scales_with_z_ratio(self):
        stock = pd.DataFrame({"safety_stock": [10.0, 20.0], "pred_qty": [30.0, 60.0], "pred_sales": [300000.0, 600000.0]})
        same = safety_impact(stock, stored_pct=95, rec_pct=95, new_pct=95, hpp_pct=80)
        self.assertEqual(same["units_delta"], 0)
        higher = safety_impact(stock, stored_pct=95, rec_pct=95, new_pct=99, hpp_pct=80)
        expected = np.ceil(np.array([10.0, 20.0]) * z_value(99) / z_value(95)).sum() - 30
        self.assertAlmostEqual(higher["units_delta"], expected)
        self.assertGreater(higher["rp_delta"], 0)
        self.assertAlmostEqual(higher["modal_delta"], higher["rp_delta"] * 0.8)
        self.assertEqual(higher["risk_new"], 1.0)


if __name__ == "__main__":
    unittest.main()
