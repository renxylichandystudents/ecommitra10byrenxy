from datetime import date

import pandas as pd

from src.core.metrics import normalize_lines
from src.core.sku_insight import (
    daily_profile,
    description_review,
    find_description,
    running_month,
    same_span_last_month,
    stock_potential,
    transaction_profile,
)


def _lines():
    rows = [
        # (pesanan, status, waktu, qty, retur, alasan)
        ("O1", "Selesai", "2026-10-03 10:00", 4, 1, ""),
        ("O2", "Batal", "2026-10-05 10:00", 2, 0, "Ubah alamat"),
        ("O3", "Selesai", "2026-10-20 10:00", 5, 0, ""),
        ("O4", "Belum Bayar", "2026-11-02 10:00", 1, 0, ""),
        ("O5", "Selesai", "2026-11-04 10:00", 6, 0, ""),
        ("O6", "Batal", "2026-11-05 10:00", 3, 0, "Ubah alamat"),
    ]
    frame = pd.DataFrame(
        {
            "order_id": [r[0] for r in rows],
            "status": [r[1] for r in rows],
            "order_time": pd.to_datetime([r[2] for r in rows]),
            "qty": [r[3] for r in rows],
            "returned_qty": [r[4] for r in rows],
            "sales": [r[3] * 10_000 for r in rows],
            "cancel_reason": [r[5] for r in rows],
            "buyer": ["a", "b", "a", "c", "d", "e"],
            "item_key": "K",
        }
    )
    return normalize_lines(frame)


def test_transaction_profile_splits_gross_and_net():
    p = transaction_profile(_lines(), "K", date(2026, 10, 1), date(2026, 10, 31))
    assert (p["qty_masuk"], p["qty_batal"], p["qty_belum_bayar"], p["qty_retur"], p["qty_bersih"]) == (11, 2, 0, 1, 8)
    assert p["sales_bersih"] == 80_000 and p["sales_masuk"] == 110_000
    assert p["pesanan"] == 3 and p["pembeli"] == 2
    assert p["alasan_batal"] == [("Ubah alamat", 1)]


def test_daily_profile_matches_period_totals():
    lines = _lines()
    daily = daily_profile(lines, "K", date(2026, 11, 1), date(2026, 11, 12))
    total = transaction_profile(lines, "K", date(2026, 11, 1), date(2026, 11, 12))
    assert len(daily) == 12 and daily.index[0] == pd.Timestamp("2026-11-01")
    for name in ("qty_masuk", "sales_masuk", "qty_bersih", "sales_bersih", "qty_batal", "qty_belum_bayar", "qty_retur"):
        assert daily[name].sum() == total[name]
    assert daily.at[pd.Timestamp("2026-11-04"), "qty_bersih"] == 6 and daily.at[pd.Timestamp("2026-11-05"), "qty_batal"] == 3
    assert daily_profile(lines, "X", date(2026, 11, 1), date(2026, 11, 3)).to_numpy().sum() == 0


def test_running_month_projection_uses_basis_and_dates():
    m = running_month(_lines(), "K", date(2026, 11, 13), date(2026, 11, 12), 18.0, 2.0, 10_000, basis="bersih")
    assert (m["first"], m["cutoff"], m["end"], m["rest_start"], m["rest_days"]) == (
        date(2026, 11, 1), date(2026, 11, 12), date(2026, 11, 30), date(2026, 11, 13), 18)
    assert m["actual"]["qty_masuk"] == 10 and m["actual"]["qty_bersih"] == 6
    assert m["proj_qty"] == 6 + 36 and m["proj_sales"] == 60_000 + 360_000
    assert (m["last_same"]["start"], m["last_same"]["end"]) == (date(2026, 10, 1), date(2026, 10, 12))
    assert m["last_same"]["qty_bersih"] == 3                     # 4 − 1 retur; batal tidak dihitung
    assert m["last_full"]["qty_bersih"] == 8
    gross = running_month(_lines(), "K", date(2026, 11, 13), date(2026, 11, 12), 18.0, 2.0, 10_000, basis="masuk")
    assert gross["proj_qty"] == 10 + 36


def test_same_span_last_month_clips_to_month_end():
    assert same_span_last_month(date(2026, 3, 1), date(2026, 3, 31)) == (date(2026, 2, 1), date(2026, 2, 28))


def test_table_extras_sold_running_month_and_empty_age():
    from src.core.sku_insight import table_extras

    rows = []
    for day in pd.date_range("2026-10-01", "2026-11-12"):
        rows.append({"order_id": f"A{day:%m%d}", "status": "Selesai", "order_time": day + pd.Timedelta(hours=23, minutes=30), "qty": 2, "sales": 20_000,
                     "returned_qty": 0, "item_key": "A"})
        rows.append({"order_id": f"B{day:%m%d}", "status": "Batal", "order_time": day + pd.Timedelta(hours=10), "qty": 1, "sales": 10_000,
                     "returned_qty": 0, "item_key": "A"})
    orders_all = pd.DataFrame(rows)
    table = pd.DataFrame({
        "item_key": ["A", "B"], "pred_harian": [3.0, 1.0], "pred_qty": [90.0, 30.0], "pred_sales": [900_000.0, 300_000.0],
        "harga_bersih": [10_000.0, 10_000.0], "ada_data_stok": [True, True], "stok": [0.0, 5.0],
        "zero_since": [date(2026, 11, 10), None],
    })
    out = table_extras(table, orders_all, date(2026, 11, 13), basis="bersih", sold_span=(date(2026, 11, 1), date(2026, 11, 12)),
                       cutoff=date(2026, 11, 12), rest_weight=18.0)
    a = out.iloc[0]
    assert (a["sold_qty_masuk"], a["sold_qty_bersih"]) == (36, 24)          # 12 hari × (2 + 1 batal) vs 12 × 2
    assert a["run_act_qty"] == 24 and a["run_qty"] == 24 + 54             # + 3/hari × 18 pola hari
    assert a["empty_days"] == 3                                            # 10, 11, 12 Nov s.d. hari penuh terakhir
    assert a["empty_qty"] == 9 - 6                                          # permintaan 3 × 3 hari − terjual bersih 2 × 3
    assert out.iloc[1][["sold_qty_masuk", "run_act_qty"]].tolist() == [0, 0] and pd.isna(out.iloc[1]["empty_days"])


def test_stock_potential_and_description():
    pot = stock_potential(10, 2.0, 10_000, 18.0, 18)
    assert pot["need"] == 36 and pot["covered"] == 10 and pot["short_qty"] == 26 and pot["short_sales"] == 260_000
    assert pd.isna(stock_potential(None, 2.0, 10_000, 18.0, 18)["short_qty"])
    review = description_review("Spesifikasi: ukuran 25 cm. Garansi 15 tahun.")
    assert review["ada"] and "Spesifikasi" in review["lengkap"] and "Cara pakai" in review["kurang"]
    assert description_review("")["ada"] is False
    desc = pd.DataFrame({"product_code": ["123"], "sku": [None], "product_name": ["Kloset Duduk"], "description": ["isi"]})
    assert find_description(desc, product_code="123", sku="", name="") == "isi"
    assert find_description(desc, product_code="", sku="", name="kloset  duduk") == "isi"


def test_order_metrics_qty_masuk_breaks_down_to_net():
    from src.core.metrics import order_metrics

    m = order_metrics(_lines(), date(2026, 10, 1), date(2026, 11, 30), normalized=True)
    assert m["qty_masuk"] == 21 and m["qty_batal"] == 5 and m["qty_menunggu_bayar"] == 1
    assert m["qty_masuk"] - m["qty_batal"] - m["qty_menunggu_bayar"] - m["retur_unit"] == m["qty_bersih"]
