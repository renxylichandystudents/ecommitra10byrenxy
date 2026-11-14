import numpy as np

from src.forecast import demand_sigma
from src.models import evaluate as E


def test_conformal_quantile_covers_target_for_heavy_tail():
    rng = np.random.default_rng(0)
    z = rng.standard_t(df=2, size=2000)  # galat berekor tebal
    q = E.conformal_quantiles(z, np.array(["A"] * 2000, dtype=object), {"A": 95.0})
    fresh = rng.standard_t(df=2, size=20000)
    assert (fresh <= q["A"]).mean() >= 0.94
    # Z normal 95% (1,645) kurang untuk ekor tebal
    assert (fresh <= 1.645).mean() < 0.94


def test_conformal_falls_back_to_pooled_then_normal():
    z = np.linspace(-1, 3, 100)
    q = E.conformal_quantiles(z, np.array(["A"] * 100, dtype=object), {"A": 90.0, "C": 90.0})
    assert q["C"] == q["A"]  # kelas C tanpa sampel memakai gabungan
    q2 = E.conformal_quantiles(np.array([0.5] * 5), np.array(["A"] * 5, dtype=object), {"A": 95.0})
    assert abs(q2["A"] - 1.6449) < 1e-3  # sampel terlalu sedikit → Z normal


def test_demand_sigma_uses_long_window():
    daily = np.zeros(200)
    daily[10] = 50  # pesanan proyek 190 hari lalu: di luar 180 hari
    daily[100] = 30  # di dalam jendela 180 hari
    daily[-30:] = 1
    sigma = demand_sigma(daily)
    assert sigma > 1.0  # lonjakan dalam 180 hari ikut terhitung
    assert sigma < np.std(daily)  # lonjakan di luar jendela tidak
