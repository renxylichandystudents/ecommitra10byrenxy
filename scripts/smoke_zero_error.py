#!/usr/bin/env python3
"""Hard zero-error suite for Prediksi Stok Shopee.

Coverage: import app, public src APIs, empty/NaT/NaN/inf, duplicate SKUs,
missing columns, unicode + ID number formats, library multi-file, exclude
batal on/off, periods, safety extremes, bad actual stock, compare_daily lazy.
Target: exit 0 with explicit “0 errors”.
"""

from __future__ import annotations

import io
import math
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- imports under test ---
import app as app_mod  # noqa: E402
from src import activity, aggregate, forecast, ingest, library, ranking, stock  # noqa: E402
from src.activity import (  # noqa: E402
    activity_report,
    cancel_contribution,
    cancel_return_insight,
    ledger_from_raw,
    pareto_share,
    top_reason_table,
    unit_price_trend,
    unpaid_buyer_table,
    unpaid_concentration,
)
from src.aggregate import (  # noqa: E402
    aggregate_item_periods,
    dense_item_series,
    next_period_start,
    period_label,
    period_start,
)
from src.forecast import (  # noqa: E402
    FORECAST_CANDIDATE_LIMIT,
    MODEL_NAME,
    _whole_units,
    compare_daily_algorithms,
    forecast_calendar,
    forecast_items,
    forecast_revenue,
    forecast_series,
    select_top_item_keys,
)
from src.ingest import (  # noqa: E402
    _parse_number_token,
    clean_order_frame,
    load_shopee_report,
    map_columns,
    order_revenue,
)
from src.library import (  # noqa: E402
    bundle_stamp,
    folder_frame,
    history_frame,
    list_months,
    load_months,
    month_label,
    store_upload,
    year_of,
)
from src.ranking import (  # noqa: E402
    combine_forecasts,
    historical_bestsellers,
    model_leaderboard,
    rank_from_orders,
    unique_rank,
)
from src.stock import recommend_stock, stock_priority  # noqa: E402

FAILURES: list[str] = []
CHECKS = 0


def _count() -> None:
    global CHECKS
    CHECKS += 1


def fail(msg: str) -> None:
    _count()
    FAILURES.append(msg)
    print(f"FAIL: {msg}")


def ok(msg: str) -> None:
    _count()
    print(f"OK   {msg}")


def expect(name: str, fn):
    try:
        result = fn()
        ok(name)
        return result
    except Exception as exc:  # noqa: BLE001
        fail(f"{name}: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        return None


def assert_true(cond: bool, msg: str) -> None:
    if cond:
        ok(f"assert {msg}")
    else:
        fail(f"assert {msg}")


def make_csv(rows: list[dict]) -> bytes:
    frame = pd.DataFrame(rows)
    buf = io.StringIO()
    frame.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


SAMPLE_HEADERS = [
    "No. Pesanan",
    "Status Pesanan",
    "Waktu Pesanan Dibuat",
    "SKU Induk",
    "Nama Produk",
    "Nomor Referensi SKU",
    "Nama Variasi",
    "Harga Awal",
    "Harga Setelah Diskon",
    "Jumlah",
    "Total Harga",
]


def row(
    oid: str,
    status: str,
    when: str,
    sku: str,
    name: str,
    var: str,
    qty,
    price,
    total=None,
) -> dict:
    return {
        "No. Pesanan": oid,
        "Status Pesanan": status,
        "Waktu Pesanan Dibuat": when,
        "SKU Induk": sku,
        "Nama Produk": name,
        "Nomor Referensi SKU": sku,
        "Nama Variasi": var,
        "Harga Awal": price,
        "Harga Setelah Diskon": price,
        "Jumlah": qty,
        "Total Harga": total if total is not None else price,
    }


def pipeline(orders: pd.DataFrame, *, period: str = "bulan", horizon: int | None = None, exclude: bool = False, actual=None, service: int = 95):
    prepared = app_mod.prepare_analysis_orders(orders, exclude_return_cancel=exclude)
    if prepared is None or prepared.empty:
        empty = pd.DataFrame()
        qty = forecast_items(empty, "hari", "qty", steps=7, next_label="x")
        sales = forecast_revenue(empty, qty, "hari", steps=7, next_label="x")
        combined = combine_forecasts(qty, sales)
        stock_df = recommend_stock(empty, combined, "hari", app_mod.service_z(service), 7, actual)
        return prepared, empty, empty, qty, sales, combined, stock_df, pd.DataFrame()
    steps = horizon if horizon is not None else {"bulan": 30, "kuartal": 91, "semester": 182, "tahun": 365}.get(period, 30)
    history = aggregate_item_periods(prepared, period if period != "hari" else "bulan")
    base = aggregate_item_periods(prepared, "hari")
    qty = forecast_items(base, "hari", "qty", steps=steps, max_items=FORECAST_CANDIDATE_LIMIT, next_label=period)
    sales = forecast_revenue(base, qty, "hari", steps=steps, next_label=period)
    combined = combine_forecasts(qty, sales)
    stock_df = recommend_stock(
        base,
        combined,
        "hari",
        service_level_z=app_mod.service_z(service),
        horizon_steps=steps,
        actual_stock=actual,
    )
    last = history["period_start"].max() if not history.empty else None
    catalog = app_mod.top_bestsellers(prepared, combined, stock_df, history, "qty", last, period if period != "hari" else "bulan", 50)
    return prepared, history, base, qty, sales, combined, stock_df, catalog


def section_import_and_apis() -> None:
    assert_true(hasattr(app_mod, "main") and callable(app_mod.main), "app.main importable")
    assert_true(hasattr(app_mod, "prepare_analysis_orders"), "prepare_analysis_orders present")
    modules = {
        "ingest": ingest,
        "aggregate": aggregate,
        "forecast": forecast,
        "ranking": ranking,
        "stock": stock,
        "activity": activity,
        "library": library,
    }
    for name, mod in modules.items():
        publics = [n for n in dir(mod) if not n.startswith("_")]
        assert_true(len(publics) > 0, f"{name} has public API ({len(publics)})")


def section_empty_nat_nan_inf() -> None:
    expect("forecast empty", lambda: forecast_items(pd.DataFrame(), "hari", "qty", steps=7))
    expect("revenue empty", lambda: forecast_revenue(pd.DataFrame(), pd.DataFrame(), "hari"))
    expect("combine empty", lambda: combine_forecasts(pd.DataFrame(), pd.DataFrame()))
    expect("stock empty", lambda: recommend_stock(pd.DataFrame(), pd.DataFrame(), "hari"))
    expect("agg empty", lambda: aggregate_item_periods(pd.DataFrame(), "hari"))
    expect("dense empty", lambda: dense_item_series(pd.DataFrame(), "hari"))
    expect("unique_rank empty", lambda: unique_rank(pd.DataFrame(columns=["item_key", "qty", "sales"]), "qty", ["sales"]))
    expect("period_label NaT", lambda: period_label(pd.NaT, "hari"))
    expect("next_period NaT", lambda: next_period_start(pd.NaT, "hari"))
    expect("compare empty", lambda: compare_daily_algorithms(pd.DataFrame()))
    expect("leaderboard empty", lambda: model_leaderboard(pd.DataFrame(), pd.DataFrame()))
    expect("hist bestsellers empty", lambda: historical_bestsellers(pd.DataFrame(), "bulan", pd.Timestamp("2024-01-01")))
    expect("clean empty", lambda: clean_order_frame(pd.DataFrame()))
    expect("charts empty", lambda: (app_mod.item_qty_chart(pd.DataFrame(), "x"), app_mod.item_sales_chart(pd.DataFrame(), "x")))
    expect(
        "prediction bad range",
        lambda: app_mod.prediction_frame(pd.Series({"pred_qty": 1, "pred_sales": 1}), pd.DataFrame(), np.ones(7), date(2024, 2, 1), date(2024, 1, 1)),
    )
    assert_true(_whole_units(0.2, np.array([1.0]), 1, "qty") == 0.0, "whole_units allows 0")
    assert_true(_whole_units(float("inf"), np.array([1.0]), 1, "qty") == 0.0, "whole_units inf -> 0")
    assert_true(_whole_units(float("nan"), np.array([1.0]), 1, "qty") == 0.0, "whole_units nan -> 0")

    hist = pd.DataFrame(
        {
            "item_key": ["A", "A", "A"],
            "item_label": ["A", "A", "A"],
            "period_start": pd.date_range("2024-01-01", periods=3, freq="D"),
            "qty": [1.0, np.nan, np.inf],
            "sales": [10.0, np.nan, -np.inf],
            "orders": [1, 1, 1],
            "period_label": ["a", "b", "c"],
        }
    )
    expect("forecast nan/inf qty", lambda: forecast_items(hist, "hari", "qty", steps=7, max_items=5))
    expect("compare nan/inf", lambda: compare_daily_algorithms(hist))
    expect("forecast_calendar zeros", lambda: forecast_calendar(np.array([1.0, 2.0]), pd.Timestamp("2024-01-01"), pd.DatetimeIndex([]), np.ones(7), 10))


def section_number_formats_unicode_duplicates() -> None:
    cases = [
        ("1.226.842", 1226842.0),
        ("49.000", 49000.0),
        ("1.234,56", 1234.56),
        ("Rp1.000", 1000.0),
        ("(1.000)", -1000.0),
        ("12,5", 12.5),
        ("1,234.56", 1234.56),
        ("—", math.nan),
        ("", math.nan),
    ]
    for token, expected in cases:
        got = _parse_number_token(token)
        if math.isnan(expected):
            assert_true(math.isnan(got), f"parse {token!r} -> nan")
        else:
            assert_true(got == expected, f"parse {token!r} -> {expected}")

    rows = [
        row("U1", "Selesai", "2024-03-01 10:00:00", "SKU-Ü-Hitam", "Produk Ünîcodé 测试", "Hitam", 1, "84.550", "84.550"),
        row("U2", "Selesai", "2024-03-02 11:00:00", "SKU-Ü-Putih", "Produk Ünîcodé 测试", "Putih", 2, "84.550", "169.100"),
        row("U3", "Selesai", "2024-03-03 12:00:00", "SKU-Ü-Hitam", "Produk Ünîcodé 测试", "Hitam", 1, "84.550", "84.550"),
        row("U4", "Selesai", "2024-03-04 12:00:00", "SKU-Ü-Hitam", "Produk Ünîcodé 测试", "Hitam", "1", "1.226.842", "1.226.842"),
    ]
    orders, source = load_shopee_report(make_csv(rows), "unicode.csv")
    assert_true(orders["item_key"].nunique() >= 2, "duplicate variations stay distinct keys")
    assert_true(float(orders["qty"].sum()) == 5.0, "unicode/ID qty sum")
    expect("unicode pipeline", lambda: pipeline(orders, period="bulan", horizon=30))
    expect("unicode ledger", lambda: ledger_from_raw(source))


def section_missing_columns_and_rank() -> None:
    # Missing required should raise ValueError — correct contract for bad uploads.
    for payload in (pd.DataFrame({"x": [1]}), pd.DataFrame({"Nama Produk": ["a"]})):
        try:
            clean_order_frame(payload)
            fail(f"missing cols should raise ValueError for columns={list(payload.columns)}")
        except ValueError:
            ok(f"missing cols raises ValueError for columns={list(payload.columns)}")
        except Exception as exc:  # noqa: BLE001
            fail(f"missing cols unexpected {type(exc).__name__}: {exc}")

    expect("rank empty", lambda: rank_from_orders(pd.DataFrame(), "qty"))
    expect("month_label bad", lambda: month_label("xx"))
    expect("month_label empty", lambda: month_label(""))
    expect("year_of bad", lambda: year_of("xx"))


def section_library_multifile() -> None:
    rows_a = [row("A1", "Selesai", "2024-04-01 09:00:00", "SKU-A", "Alpha", "", 2, "10.000", "20.000")]
    rows_b = [row("B1", "Selesai", "2024-04-15 09:00:00", "SKU-B", "Beta", "L", 1, "15.000", "15.000")]
    oa, sa = load_shopee_report(make_csv(rows_a), "a.csv")
    ob, sb = load_shopee_report(make_csv(rows_b), "b.csv")
    source = pd.concat([sa.assign(**{"Nama file": "a.csv"}), sb.assign(**{"Nama file": "b.csv"})], ignore_index=True)
    orders = pd.concat([oa, ob], ignore_index=True).drop_duplicates().reset_index(drop=True)
    expect("store_upload multi", lambda: store_upload(source, orders, ["a.csv", "b.csv"]))
    keys = sorted({pd.Timestamp(t).strftime("%Y-%m") for t in orders["order_time"]})
    expect("load_months multi", lambda: load_months(keys))
    stamp = bundle_stamp(keys)
    expect("cached_library_frames", lambda: app_mod.cached_library_frames(tuple(keys), stamp))
    expect("cached_ledger", lambda: app_mod.cached_ledger(tuple(keys), stamp))
    expect("cached_merged", lambda: app_mod.cached_merged(tuple(keys), stamp))
    expect("folder_frame", lambda: folder_frame())
    expect("history_frame", lambda: history_frame())
    expect("list_months", lambda: list_months())


def section_exclude_periods_safety_actual() -> None:
    sample = ROOT / "data" / "sample_shopee_orders.csv"
    orders, source = load_shopee_report(sample.read_bytes(), sample.name)
    assert_true(float(orders["qty"].sum()) > 0, "sample qty > 0")
    mapping = map_columns(pd.read_csv(sample))
    assert_true(mapping.get("qty") == "Jumlah", "qty=Jumlah")
    assert_true("returned_qty" not in mapping, "returned_qty not from Jumlah")

    for exclude in (False, True):
        expect(f"pipeline exclude={exclude}", lambda exclude=exclude: pipeline(orders, exclude=exclude, period="bulan", horizon=30))

    for period in ("hari", "bulan", "kuartal", "tahun"):
        expect(f"pipeline period={period}", lambda period=period: pipeline(orders, period=period, exclude=False))

    base = aggregate_item_periods(orders, "hari")
    qty = forecast_items(base, "hari", "qty", steps=30, max_items=FORECAST_CANDIDATE_LIMIT)
    sales = forecast_revenue(base, qty, "hari", steps=30)
    combined = combine_forecasts(qty, sales)
    for pct in (0, 95, 100, 200):
        z = app_mod.service_z(pct)
        assert_true(np.isfinite(z) and z >= 0, f"service_z({pct}) finite >=0")
        expect(
            f"recommend_stock service={pct}",
            lambda z=z: recommend_stock(base, combined, "hari", service_level_z=z, horizon_steps=30),
        )

    key = str(combined.sort_values("pred_qty", ascending=False).iloc[0]["item_key"])
    for actual in (
        {key: 0},
        {key: "12"},
        {key: "bukan-angka"},
        {key: None, "x": float("nan")},
        pd.Series({key: 3.5}),
        {"nope": "zz"},
    ):
        expect(f"actual stock {actual!r}", lambda actual=actual: recommend_stock(base, combined, "hari", 1.65, 30, actual_stock=actual))

    stock0 = recommend_stock(base, combined, "hari", 1.65, 30, actual_stock={key: 0})
    sug = int(stock0.loc[stock0["item_key"] == key, "stok_disarankan"].iloc[0])
    assert_true(int(stock0.loc[stock0["item_key"] == key, "reorder"].iloc[0]) == sug, "reorder actual=0")

    # classic period path (non-hari) still used optionally
    month_hist = aggregate_item_periods(orders, "bulan")
    expect("forecast classic bulan path", lambda: forecast_items(month_hist, "bulan", "qty", steps=1, max_items=10))
    expect("forecast_series short", lambda: forecast_series(np.array([1.0, 2.0, 3.0, 2.0, 4.0, 5.0, 6.0, 7.0]), "bulan", 1))


def section_compare_lazy_and_app_helpers() -> None:
    sample = ROOT / "data" / "sample_shopee_orders.csv"
    orders, source = load_shopee_report(sample.read_bytes(), sample.name)
    base = aggregate_item_periods(orders, "hari")
    comparison = expect("compare_daily lazy", lambda: compare_daily_algorithms(base))
    if isinstance(comparison, pd.DataFrame) and not comparison.empty:
        assert_true("Algoritma" in comparison.columns, "comparison has Algoritma")
        assert_true(MODEL_NAME in set(comparison["Algoritma"].astype(str)), "Level terkini in comparison")

    qty = forecast_items(base, "hari", "qty", steps=30, max_items=FORECAST_CANDIDATE_LIMIT)
    sales = forecast_revenue(base, qty, "hari", steps=30)
    combined = combine_forecasts(qty, sales)
    board = model_leaderboard(qty, sales)
    assert_true(not board.empty, "leaderboard qty present")
    assert_true("sales" not in set(board.get("metrik", pd.Series(dtype=str)).tolist()), "no fake sales board")

    stock_df = recommend_stock(base, combined, "hari", app_mod.service_z(95), 30)
    hist = aggregate_item_periods(orders, "bulan")
    catalog = app_mod.top_bestsellers(orders, combined, stock_df, hist, "qty", hist["period_start"].max(), "bulan", 50)
    expect("leaderboard_frame", lambda: app_mod.leaderboard_frame(catalog, "bulan"))
    display = app_mod.leaderboard_frame(catalog, "bulan")
    assert_true("Stok aktual" not in display.columns, "no fake actual col")
    expect("sort_leaderboard", lambda: app_mod.sort_leaderboard(catalog, "qty_desc"))
    expect("charts sample", lambda: (app_mod.item_qty_chart(catalog.head(10), "s"), app_mod.item_sales_chart(catalog.head(10), "s")))
    if not catalog.empty:
        chosen = catalog.iloc[0]
        expect(
            "prediction_frame+bucket",
            lambda: app_mod.bucket_prediction(
                app_mod.prediction_frame(
                    chosen,
                    orders.loc[orders["item_key"] == chosen["item_key"]],
                    np.ones(7),
                    date.today(),
                    date.today() + timedelta(days=20),
                ),
                "minggu",
            ),
        )

    expect("insights", lambda: (
        activity_report(ledger_from_raw(source)),
        cancel_return_insight(ledger_from_raw(source)),
        cancel_contribution(ledger_from_raw(source)),
        top_reason_table(ledger_from_raw(source), "cancel"),
        top_reason_table(ledger_from_raw(source), "return"),
        unpaid_concentration(source),
        unpaid_buyer_table(source),
        unit_price_trend(orders, 5),
        pareto_share(orders, "qty", 50),
        order_revenue(orders),
    ))
    expect("growth_hint edges", lambda: (
        app_mod.growth_hint(1, 0, "QTY"),
        app_mod.growth_hint(float("nan"), 10, "QTY"),
        app_mod.growth_hint(10, float("nan"), "QTY"),
    ))
    expect("safety_view empty", lambda: app_mod.safety_view({}, 95, "qty"))
    expect("select_top keys", lambda: select_top_item_keys(base, limit=5))
    expect("period_start series", lambda: period_start(orders["order_time"], "bulan"))
    expect("stock_priority edges", lambda: (
        stock_priority(0, 0, None),
        stock_priority(20, 15, 5),
        stock_priority(10, 0, 10),
        stock_priority(10, 5, float("nan")),
        stock_priority("x", "y", "z"),
    ))

    # all-cancel
    cancel_orders, _ = load_shopee_report(
        make_csv([row("C1", "Batal", "2024-05-01 10:00:00", "SKU-C", "Cancel", "", 3, "9.000", "27.000")]),
        "c.csv",
    )
    expect("all-cancel exclude pipeline", lambda: pipeline(cancel_orders, exclude=True))
    expect("all-cancel keep pipeline", lambda: pipeline(cancel_orders, exclude=False, horizon=7))


def main() -> int:
    print("=== HARD ZERO-ERROR SUITE ===")
    section_import_and_apis()
    section_empty_nat_nan_inf()
    section_number_formats_unicode_duplicates()
    section_missing_columns_and_rank()
    section_library_multifile()
    section_exclude_periods_safety_actual()
    section_compare_lazy_and_app_helpers()

    print("\n==========")
    print(f"Checks run: {CHECKS}")
    if FAILURES:
        print(f"SMOKE FAILED: {len(FAILURES)} issue(s)")
        for item in FAILURES:
            print("---")
            print(item)
        return 1
    print("SMOKE PASSED: 0 errors, 0 failed asserts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
