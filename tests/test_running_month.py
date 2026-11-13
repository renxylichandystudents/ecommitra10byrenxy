from datetime import date

import pandas as pd


def _orders():
    days = pd.date_range("2026-09-01", "2026-11-12", freq="D")
    return pd.DataFrame({
        "order_time": days + pd.Timedelta(hours=23, minutes=30), "item_key": "A", "sku": "A", "qty": 10.0,
        "sales": 1_000_000.0, "status": "Selesai", "order_id": [f"o{i}" for i in range(len(days))],
    })


def test_running_month_actual_plus_rest():
    from src.ui.dashboard import running_month

    orders = _orders()
    table = pd.DataFrame({"item_key": ["A"], "pred_harian": [10.0]})
    total, hint = running_month(table, orders, orders, date(2026, 11, 13))
    # aktual 1–12 Nov = 120 unit; sisa 13–30 Nov = 18 hari × laju 10 × pola (rata-rata ±1)
    assert hint.startswith("aktual terjual 1–12 Nov: 120 + prediksi 13–30 Nov: ")
    assert 120 + 18 * 10 * 0.6 < total < 120 + 18 * 10 * 1.4


def test_running_month_without_orders_uses_whole_rest():
    from src.ui.dashboard import running_month

    table = pd.DataFrame({"item_key": ["A"], "pred_harian": [2.0]})
    total, _hint = running_month(table, None, None, date(2026, 11, 13))
    assert total == 2.0 * 18


def test_running_month_sales_and_all_items():
    from src.ui.dashboard import running_month_parts

    orders = _orders()
    other = orders.assign(item_key="B", sku="B", qty=1.0, sales=50_000.0)
    both = pd.concat([orders, other], ignore_index=True)
    table = pd.DataFrame({"item_key": ["A"], "pred_harian": [10.0], "harga_bersih": [100_000.0]})
    top = running_month_parts(table, both, both, date(2026, 11, 13))
    assert top["actual_qty"] == 120 and top["actual_sales"] == 12 * 1_000_000
    assert abs(top["rest_sales"] - top["rest_qty"] * 100_000) < 1e-6
    whole = running_month_parts(table, both, both, date(2026, 11, 13), all_items=True)
    assert whole["actual_sales"] == 12 * 1_050_000


def test_achievement_line_names_net_sales_and_dates():
    from src.ingest import clean_order_frame
    from src.ui.targets_view import achievement_line

    rows = []
    for day in range(1, 14):
        hour = "23:30" if day < 13 else "10:00"
        rows.append({
            "No. Pesanan": f"N{day}", "Status Pesanan": "Selesai", "Alasan Pembatalan": "", "Waktu Pesanan Dibuat": f"2026-11-{day:02d} {hour}",
            "Nomor Referensi SKU": "100", "Nama Produk": "Produk", "Nama Variasi": "", "Harga Setelah Diskon": 100_000,
            "Jumlah": 1, "Returned quantity": 0, "Total Pembayaran": 90_000, "Username (Pembeli)": "a",
        })
    orders = clean_order_frame(pd.DataFrame(rows))
    text = achievement_line(0.0, date(2026, 11, 1), date(2026, 11, 13), targets={"2026-11": 3_000_000}, orders=orders)
    assert "sales bersih 1 Nov 2026 – 12 Nov 2026" in text
    assert "13 Nov 2026 belum penuh" in text
    assert "s.d. 12 Nov 2026" in text
