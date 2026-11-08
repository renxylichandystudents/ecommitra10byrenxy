from src.core.business import business_targets


def test_targets_priority_and_limit():
    params = {"margin": {"hpp_pct_harga": 55, "margin_min_pct": 30}, "target": {"sales_bulanan_rp": 5_500_000_000}}
    goals = business_targets(params, None)
    assert goals.target_sales == 5_500_000_000 and goals.target_source == "Pengaturan bisnis"
    assert goals.cost_limit_pct == 15
    saved = business_targets(params, {"target_sales_bersih": 6_000_000_000, "margin_min_pct": 25})
    assert saved.target_sales == 6_000_000_000 and saved.margin_min_pct == 25 and saved.cost_limit_pct == 20
    assert business_targets({"margin": {"hpp_pct_harga": 80, "margin_min_pct": 30}}).cost_limit_pct == 0
