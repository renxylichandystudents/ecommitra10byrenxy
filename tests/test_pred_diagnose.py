from datetime import date, timedelta

import pandas as pd

from src.core.pred_actual import cause_group, daily_comparison, diagnose


def _lines():
    rows = []
    start = date(2026, 10, 10)
    for i in range(29):
        day = start + timedelta(days=i)
        before = day < date(2026, 11, 1)
        qty = 6 if before else (1 if i % 2 else 0)
        price = 1_430_999 if before else 1_629_000
        if qty:
            rows.append({"order_time": pd.Timestamp(day) + pd.Timedelta(hours=10), "sku": "A", "qty": qty, "sales": qty * price, "list_price": price, "order_id": f"o{i}", "status": "Selesai"})
    return pd.DataFrame(rows)


def test_price_increase_is_diagnosed_with_numbers_and_action():
    lines = _lines()
    day = date(2026, 11, 7)
    snap = pd.DataFrame({"tanggal": [day], "sku": ["A"], "varian": [""], "pred_qty": [3.8], "pred_sales": [3.8 * 1_629_000]})
    rows = diagnose(daily_comparison(snap, lines, day), lines, day)
    text = rows["penyebab"].iloc[0]
    assert text.startswith("Harga naik 13,8% sejak 1 Nov")
    assert "Rp1.430.999 → Rp1.629.000" in text
    assert "Tinjau harga" in rows["aksi"].iloc[0]
    assert cause_group(text) == "Harga naik"


def test_price_increase_not_blamed_when_whole_store_drops_equally():
    lines = _lines()
    # Toko lain ikut turun tajam setelah 1 Nov → penurunan SKU A bukan karena harganya.
    extra = []
    for i in range(29):
        day = date(2026, 10, 10) + timedelta(days=i)
        n = 20 if day < date(2026, 11, 1) else 1
        for k in range(n):
            extra.append({"order_time": pd.Timestamp(day) + pd.Timedelta(hours=11), "sku": "B", "qty": 1, "sales": 10_000, "list_price": 10_000, "order_id": f"b{i}-{k}", "status": "Selesai"})
    lines = pd.concat([lines, pd.DataFrame(extra)], ignore_index=True)
    day = date(2026, 11, 7)
    snap = pd.DataFrame({"tanggal": [day], "sku": ["A"], "varian": [""], "pred_qty": [3.8], "pred_sales": [3.8 * 1_629_000]})
    rows = diagnose(daily_comparison(snap, lines, day), lines, day)
    assert not rows["penyebab"].iloc[0].startswith("Harga naik")


def test_bulk_order_does_not_inflate_rate_before_price_change():
    lines = _lines()
    bulk = {"order_time": pd.Timestamp(date(2026, 10, 25)) + pd.Timedelta(hours=9), "sku": "A", "qty": 40, "sales": 40 * 1_430_999, "list_price": 1_430_999, "order_id": "bulk", "status": "Selesai"}
    lines = pd.concat([lines, pd.DataFrame([bulk])], ignore_index=True)
    day = date(2026, 11, 7)
    snap = pd.DataFrame({"tanggal": [day], "sku": ["A"], "varian": [""], "pred_qty": [3.8], "pred_sales": [3.8 * 1_629_000]})
    text = diagnose(daily_comparison(snap, lines, day), lines, day)["penyebab"].iloc[0]
    # Tanpa batas: (13×6 + 46)/14 ≈ 8,9/hari; dengan batas 2× median (12 pcs) → 6,9/hari.
    assert "laku 6,9 →" in text, text


def test_shopee_voucher_drop_is_diagnosed():
    rows = []
    start = date(2026, 10, 10)
    for i in range(29):
        day = start + timedelta(days=i)
        before = day < date(2026, 11, 1)
        qty = 4 if before else (1 if i % 2 else 0)
        for k in range(qty):
            rows.append({"order_time": pd.Timestamp(day) + pd.Timedelta(hours=10), "sku": "A", "qty": 1, "sales": 500_000, "list_price": 500_000,
                         "shopee_voucher": 100_000 if before else 0.0, "order_id": f"o{i}-{k}", "status": "Selesai"})
    lines = pd.DataFrame(rows)
    day = date(2026, 11, 7)
    snap = pd.DataFrame({"tanggal": [day], "sku": ["A"], "varian": [""], "pred_qty": [3.0], "pred_sales": [1_500_000]})
    out = diagnose(daily_comparison(snap, lines, day), lines, day)
    text = out["penyebab"].iloc[0]
    assert text.startswith("Dukungan Shopee berkurang (hilang)"), text
    assert "Rp400.000 → Rp500.000" in text
    assert cause_group(text) == "Dukungan Shopee berkurang"


def test_money_values_parsed_from_excel_numbers():
    from src.ingest import _money_value

    assert _money_value(171.72) == 171_720
    assert _money_value("171.720") == 171_720
    assert _money_value(171_720.5) == 171_720.5
    assert _money_value(0.0) == 0.0
