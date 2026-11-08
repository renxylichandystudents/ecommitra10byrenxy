from src.core.business import business_targets


def test_targets_priority():
    params = {"margin": {"hpp_pct_harga": 55, "margin_min_pct": 30}, "target": {"sales_bulanan_rp": 5_500_000_000}}
    goals = business_targets(params, None)
    assert goals.target_sales == 5_500_000_000 and goals.target_source == "Pengaturan bisnis"
    # Margin minimum tidak lagi dari Pengaturan bisnis: bawaan 0 (asal tidak rugi).
    assert goals.margin_min_pct == 0
    saved = business_targets(params, {"target_sales_bersih": 6_000_000_000, "margin_min_pct": 25})
    assert saved.target_sales == 6_000_000_000 and saved.margin_min_pct == 25
    assert business_targets({}).target_source == "belum diisi"
