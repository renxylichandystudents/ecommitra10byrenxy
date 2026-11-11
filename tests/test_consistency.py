"""Angka yang sama di halaman berbeda harus dihitung dengan definisi yang sama (audit 11 Nov 2026)."""

from datetime import date

import numpy as np
import pandas as pd

from src.core import month_track as M
from src.core.metrics import net_sku_sales, sold_lines
from src.core.pred_actual import daily_comparison
from src.ingest import clean_order_frame


def _row(order, status, sku, qty, price, total, day, *, returned=0):
    return {
        "No. Pesanan": order, "Status Pesanan": status, "Alasan Pembatalan": "", "Waktu Pesanan Dibuat": day,
        "Nomor Referensi SKU": sku, "Nama Produk": f"Produk {sku}", "Nama Variasi": "", "Harga Setelah Diskon": price,
        "Jumlah": qty, "Returned quantity": returned, "Total Pembayaran": total, "Username (Pembeli)": "a",
    }


def _orders() -> pd.DataFrame:
    return clean_order_frame(pd.DataFrame([
        _row("A1", "Selesai", "100", 2, 50_000, 110_000, "2026-11-05 10:00"),
        _row("A2", "Selesai", "100", 3, 50_000, 160_000, "2026-11-05 11:00", returned=1),
        _row("A3", "Batal", "100", 4, 50_000, 205_000, "2026-11-05 12:00"),
        _row("A4", "Belum Bayar", "100", 1, 50_000, 55_000, "2026-11-05 13:00"),
    ]))


def _toggle_off(frame: pd.DataFrame) -> pd.DataFrame:
    """Saklar "Kecualikan batal & retur" mati: qty/sales diganti nilai kotor (seperti app.prepare_analysis_orders)."""
    return frame.assign(qty=frame["gross_qty"], sales=frame["gross_sales"])


def test_sold_lines_is_net_regardless_of_toggle():
    orders = _orders()
    net = net_sku_sales(orders)
    for frame in (orders, _toggle_off(orders)):
        sold = sold_lines(frame)
        assert float(sold["qty"].sum()) == 4.0
        assert float(sold["sales"].sum()) == float(net["sales"].sum()) == 200_000.0


def test_pred_vs_actual_uses_net_sales_with_toggle_off():
    gross = _toggle_off(_orders()).assign(sku=lambda f: f["sku"].astype(str))
    snap = pd.DataFrame({"tanggal": [date(2026, 11, 5)], "sku": ["100"], "varian": [""], "pred_qty": [4.0], "pred_sales": [200_000.0]})
    raw = daily_comparison(snap, gross, date(2026, 11, 5))
    assert float(raw["aktual_sales"].iloc[0]) == 500_000.0
    fixed = daily_comparison(snap, gross, date(2026, 11, 5), sold=sold_lines(gross))
    assert float(fixed["aktual_sales"].iloc[0]) == 200_000.0
    assert float(fixed["aktual_qty"].iloc[0]) == 4.0


def test_ad_cost_per_unit_uses_ad_window_qty():
    from src.ui.feature_data import ad_cost_map

    table = pd.DataFrame({"sku": ["A"], "biaya_iklan": [3_000_000.0], "qty_total": [1_200.0], "qty_sku": [100.0]})
    assert ad_cost_map(table) == {"A": 30_000.0}
    assert ad_cost_map(table.drop(columns="qty_sku")) == {"A": 2_500.0}


def test_stock_action_restocks_to_need_plus_ss():
    table = pd.DataFrame([
        {"sku": "A", "product_name": "Pipa", "pred_harian": 2.0, "harga_bersih": 100_000.0, "ada_data_stok": True, "stok": 30.0, "ss": 10.0,
         "stok_10062": np.nan, "stok_10036": np.nan},
    ])
    top = M.priority_actions(table, today=date(2026, 11, 10), rest_days=20)
    row = top.iloc[0]
    assert row["Jenis"] == "Stok"
    assert "20 unit" in row["Tindakan"]
    assert row["Potensi omzet"] == 10 * 100_000


def test_lead_time_follows_import_mode():
    from src.core.inventory import lead_time_days

    assert lead_time_days({"lead_time": {"lokal_hari": 7, "impor_aktif": False, "impor_rata_hari": 60}}) == 7
    assert lead_time_days({"lead_time": {"lokal_hari": 7, "impor_aktif": True, "impor_rata_hari": 60}}) == 60


def test_safety_stock_rounds_up():
    from src.core.decision_table import build_decision_table

    stock = pd.DataFrame({"item_key": ["A"], "sku": ["A"], "product_name": ["Pipa"], "variation_name": [""], "pred_qty": [30.0],
                          "pred_sales": [3_000_000.0], "safety_stock": [2.3]})
    table = build_decision_table(stock, period="bulan", today=date(2026, 11, 10), horizon_days=30)
    assert float(table["ss"].iloc[0]) == 3.0


def test_ads_break_even_uses_margin_before_ads():
    row = {"sku": "B", "product_name": "Cat", "pred_harian": 2.0, "harga_bersih": 200_000.0, "ada_data_stok": True, "stok": 500.0, "ss": 5.0,
           "biaya_harian": 50_000.0, "biaya_iklan": 1_500_000.0, "omzet_iklan": 30_000_000.0, "stok_10062": np.nan, "stok_10036": np.nan}
    table = pd.DataFrame([row])
    after_ads = M.priority_actions(table, today=date(2026, 11, 10), rest_days=20, margin_pct={"B": 5.0})
    before_ads = M.priority_actions(table, today=date(2026, 11, 10), rest_days=20, margin_pct={"B": 5.0}, ad_per_unit={"B": 30_000.0})
    assert after_ads.empty
    assert "titik impas 5,0" in before_ads.iloc[0]["Alasan"]


def test_net_factor_single_rule():
    from src.ui.month_track_view import net_factor

    days = pd.date_range("2026-10-01", "2026-11-09")
    net = pd.Series(90.0, index=days)
    product = pd.Series(100.0, index=days)
    assert abs(net_factor(net, product, date(2026, 11, 1), date(2026, 11, 9)) - 0.9) < 1e-9
    assert net_factor(net * 0.1, product, date(2026, 11, 1), date(2026, 11, 9)) == 0.5
    empty = product.where(product.index < pd.Timestamp("2026-11-01"), 0.0)
    assert abs(net_factor(net, empty, date(2026, 11, 1), date(2026, 10, 31), date(2026, 10, 31)) - 0.9) < 1e-9
