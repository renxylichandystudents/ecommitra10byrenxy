from datetime import date

import pandas as pd


def test_empty_status_shows_age_and_stockout_date():
    from src.core.decision_table import build_decision_table
    from src.core.enrich import zero_since_map
    from src.core.restock import restock_priority
    from src.ui.dashboard import restock_view, status_badges

    today = date(2026, 11, 13)
    snaps = pd.DataFrame({
        "sku": ["A", "A", "A", "B", "B", "C"],
        "stock_dc_cikupa": [20, 0, 0, 0, 0, 50],
        "_submitted_at": ["2026-11-01T08:00:00", "2026-11-05T08:00:00", "2026-11-13T08:00:00",
                          "2026-11-03T08:00:00", "2026-11-13T08:00:00", "2026-11-13T08:00:00"],
    })
    view = pd.DataFrame({"item_key": list("ABC"), "sku": list("ABC"), "product_name": ["Semen", "Cat", "Pipa"], "variation_name": ["", "", ""],
                         "pred_qty": [30.0, 30.0, 30.0], "pred_sales": [3e6, 3e6, 3e6], "safety_stock": [2.0, 2.0, 2.0], "peringkat": [1, 2, 3]})
    zero, _ = zero_since_map(snaps, today)
    table = build_decision_table(view, period="bulan", today=today, horizon_days=30, stock_frame=snaps, zero_duration=zero)
    shown = status_badges(restock_view(restock_priority(table, today))).set_index("SKU")
    assert shown.loc["A", "Status"] == "🔴 Kosong · 8 hari (sejak 5 Nov 2026)"
    assert shown.loc["A", "Stok habis"] == "Habis 5 Nov 2026"
    assert shown.loc["B", "Status"] == "🔴 Kosong · ≥ 10 hari"
    assert shown.loc["B", "Stok habis"] == "Habis ≤ 3 Nov 2026"
    assert shown.loc["C", "Stok habis"] not in ("", "–") and "Kosong" not in shown.loc["C", "Status"]
