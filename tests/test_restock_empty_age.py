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
    # A kosong 5–12 Nov = 8 hari × laju 1 unit/hari; B ≥ 3–12 Nov = 10 hari (minimal); C tidak kosong.
    assert shown.loc["A", "Kosong sejak"] == "5 Nov 2026" and shown.loc["A", "Hari kosong"] == 8
    assert abs(shown.loc["A", "QTY hilang sejak kosong"] - 8.0) < 1e-6
    assert abs(shown.loc["A", "Sales hilang sejak kosong"] - 800_000) < 1e-3
    assert abs(shown.loc["A", "Sales hilang bulan ini"] - 800_000) < 1e-3
    assert shown.loc["B", "Kosong sejak"] == "≤ 3 Nov 2026" and shown.loc["B", "Hari kosong"] == 10
    assert pd.isna(shown.loc["C", "Sales hilang sejak kosong"]) and shown.loc["C", "Kosong sejak"] == ""
    assert "Potensi sales hilang ke depan" in shown.columns


def test_empty_loss_pattern_sales_and_month_split():
    from src.core.restock import empty_loss

    today = date(2026, 11, 3)
    weight = {date(2026, 10, 30): 1.0, date(2026, 10, 31): 2.0, date(2026, 11, 1): 1.5, date(2026, 11, 2): 0.5}
    lost = empty_loss(date(2026, 10, 30), today, 10.0, 1_000.0, day_weight=weight.get, sold_qty=5.0, sold_sales=5_000.0,
                      month_first=date(2026, 11, 1), sold_month=(5.0, 5_000.0))
    # permintaan 10 × (1 + 2 + 1,5 + 0,5) = 50 unit; terjual 5 → hilang 45; bulan ini 10 × 2 = 20 − 5 = 15
    assert lost["hari"] == 4 and abs(lost["qty"] - 45) < 1e-9 and abs(lost["sales"] - 45_000) < 1e-6
    assert abs(lost["qty_bulan"] - 15) < 1e-9 and abs(lost["sales_bulan"] - 15_000) < 1e-6
    assert empty_loss(today, today, 10.0, 1_000.0)["hari"] == 0
    assert empty_loss(None, today, 10.0, 1_000.0)["sales"] == 0.0
