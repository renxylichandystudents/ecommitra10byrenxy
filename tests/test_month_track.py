from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from src.core import month_track as M
from src.core.metrics import normalize_lines, order_metrics
from src.ingest import clean_order_frame


def _row(order, status, sku, qty, price, total, day, *, returned=0, reason=""):
    return {
        "No. Pesanan": order, "Status Pesanan": status, "Alasan Pembatalan": reason, "Waktu Pesanan Dibuat": day,
        "Nomor Referensi SKU": sku, "Nama Produk": f"Produk {sku}", "Nama Variasi": "", "Harga Setelah Diskon": price,
        "Jumlah": qty, "Returned quantity": returned, "Total Pembayaran": total, "Username (Pembeli)": "a",
    }


def test_daily_net_sales_matches_order_metrics_per_day():
    raw = pd.DataFrame([
        _row("A1", "Selesai", "100", 2, 50_000, 110_000, "2026-10-05 10:00"),
        _row("A2", "Selesai", "100", 1, 50_000, 120_000, "2026-10-05 11:00"),
        _row("A2", "Selesai", "200", 2, 30_000, 120_000, "2026-10-05 11:00", returned=1),
        _row("A3", "Batal", "200", 4, 30_000, 125_000, "2026-10-06 09:00", reason="Pembatalan otomatis: belum dibayar"),
        _row("A4", "Belum Bayar", "100", 1, 50_000, 55_000, "2026-10-06 12:00"),
        _row("A5", "Selesai", "300", 3, 20_000, 65_000, "2026-10-06 13:00"),
    ])
    lines = normalize_lines(clean_order_frame(raw))
    daily = M.daily_net_sales(lines, date(2026, 10, 5), date(2026, 10, 7))
    for day in (date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)):
        assert abs(daily[pd.Timestamp(day)] - order_metrics(lines, day, day, normalized=True)["sales_bersih"]) < 1e-6


def _history(days: int = 120, promo_lift: float = 1.8) -> pd.Series:
    index = pd.date_range(date(2026, 6, 1), periods=days, freq="D")
    values = [1_000_000 * (promo_lift if M.day_type(d.date()) != "Normal" else 1.0) * (1.2 if d.dayofweek == 0 else 1.0) for d in index]
    return pd.Series(values, index=index)


def test_seasonal_profile_detects_promo_and_weekday():
    profile = M.seasonal_profile(_history())
    assert profile.uplift["Gajian"] > 1.5
    assert profile.uplift["Tanggal kembar"] > 1.2
    assert profile.weekday[0] > profile.weekday[2]
    assert M.seasonal_profile(_history(days=10)).uplift["Gajian"] == 1.0


def test_as_of_prediction_uses_run_before_the_day():
    runs = pd.DataFrame([
        {"run_id": 1, "run_at": datetime(2026, 11, 3, 8), "target_date": date(2026, 11, 4), "pred": 100.0},
        {"run_id": 1, "run_at": datetime(2026, 11, 3, 8), "target_date": date(2026, 11, 5), "pred": 100.0},
        {"run_id": 2, "run_at": datetime(2026, 11, 4, 8), "target_date": date(2026, 11, 5), "pred": 200.0},
    ])
    out = M.as_of_predictions(runs, [date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 20)])
    assert np.isnan(out["pred_datar"].iloc[0])
    assert out["pred_datar"].tolist()[1:] == [100.0, 200.0, 200.0]
    assert out["run_id"].tolist()[1:] == [1, 2, 2]


def test_month_table_keeps_totals_and_projects():
    first = date(2026, 11, 1)
    days = [first + timedelta(days=i) for i in range(30)]
    preds = pd.DataFrame({"tanggal": days, "pred_datar": 1_000_000.0, "run_id": 1, "run_at": pd.Timestamp("2026-10-31")})
    actual = pd.Series(900_000.0, index=pd.date_range(first, date(2026, 11, 9)))
    profile = M.seasonal_profile(_history())
    table = M.month_table(month_first=first, cutoff=date(2026, 11, 9), actual=actual, predictions=preds, factor=0.9,
                          profile=profile, target_month=30_000_000)
    assert abs(table["target"].sum() - 30_000_000) < 1
    assert abs(table["prediksi"].sum() - 30 * 900_000) < 1
    assert table.loc[table["tanggal"].eq(date(2026, 11, 11)), "pola"].iat[0] > table.loc[table["tanggal"].eq(date(2026, 11, 12)), "pola"].iat[0]
    summary = M.month_summary(table, date(2026, 11, 9), 30_000_000)
    assert summary["mtd"] == 9 * 900_000
    assert summary["sisa_hari"] == 21
    assert abs(summary["proyeksi"] - (summary["mtd"] + table.loc[table["tanggal"] > date(2026, 11, 9), "prediksi"].sum())) < 1
    assert abs(summary["kurang"] - (30_000_000 - summary["proyeksi"])) < 1
    assert summary["kemarin"]["tanggal"] == date(2026, 11, 9)
    assert summary["besok"]["tanggal"] == date(2026, 11, 11)


def test_priority_actions_ranks_stock_and_ads():
    table = pd.DataFrame([
        {"sku": "A", "product_name": "Pipa", "pred_harian": 10.0, "harga_bersih": 100_000.0, "ada_data_stok": True, "stok": 20.0, "ss": 5.0,
         "stok_10062": 100.0, "stok_10036": np.nan, "biaya_harian": 0.0},
        {"sku": "B", "product_name": "Cat", "pred_harian": 2.0, "harga_bersih": 200_000.0, "ada_data_stok": True, "stok": 500.0, "ss": 5.0,
         "biaya_harian": 50_000.0, "biaya_iklan": 1_500_000.0, "omzet_iklan": 30_000_000.0, "stok_10062": np.nan, "stok_10036": np.nan},
        {"sku": "X", "product_name": "Jasa", "pred_harian": 5.0, "harga_bersih": 50_000.0, "ada_data_stok": True, "stok": 0.0, "ss": 0.0},
    ])
    top = M.priority_actions(table, today=date(2026, 11, 10), rest_days=20, margin_pct={"B": 20.0}, excluded={"X"}, unpaid=1_000_000, unpaid_orders=3)
    assert top["Prioritas"].tolist() == list(range(1, len(top) + 1))
    assert top["Potensi omzet"].is_monotonic_decreasing
    first = top.iloc[0]
    assert first["SKU"] == "A" and first["Jenis"] == "Stok" and "10062" in first["Tindakan"]
    assert first["Potensi omzet"] == 180 * 100_000
    assert "B" in set(top.loc[top["Jenis"].eq("Iklan"), "SKU"])
    assert "X" not in set(top["SKU"])
    assert "Kejar bayar" in set(top["Jenis"])


def test_listing_priority_only_when_sku_drops_below_its_own_pace():
    table = pd.DataFrame([
        {"sku": "D", "product_name": "Turun", "pred_harian": 5.0, "harga_bersih": 100_000.0, "ada_data_stok": False},
        {"sku": "O", "product_name": "Prediksi ketinggian", "pred_harian": 5.0, "harga_bersih": 100_000.0, "ada_data_stok": False},
    ])
    recent = pd.DataFrame([
        {"sku": "D", "qty": 7.0, "qty_sebelum": 112.0},
        {"sku": "O", "qty": 7.0, "qty_sebelum": 28.0},
    ])
    top = M.priority_actions(table, today=date(2026, 11, 10), rest_days=20, recent=recent)
    assert top["SKU"].tolist() == ["D"]
    assert top.iloc[0]["Jenis"] == "Harga & listing"
    assert abs(top.iloc[0]["Potensi omzet"] - (4.0 - 1.0) * 100_000 * 20) < 1
