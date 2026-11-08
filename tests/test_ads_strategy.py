import pandas as pd

from src.core import ads_strategy as A


def _group():
    rows = []
    for period, text, cost, sales in (("2026-09-01", "01/09/2026 - 30/09/2026", 3_000_000, 45_000_000), ("2026-10-01", "01/10/2026 - 31/10/2026", 6_000_000, 72_000_000)):
        rows.append({"period": period, "Periode laporan (teks)": text, "Urutan": 1, "Nama Iklan/Produk": "Grup Kloset", "Status": "Berjalan",
                     "Mode Bidding": "GMV Max ROAS", "product_code": "-", "cost": cost, "ad_sales": sales, "products_sold": 10})
        rows.append({"period": period, "Periode laporan (teks)": text, "Urutan": 2, "Nama Iklan/Produk": "Kloset A", "Status": "-",
                     "Mode Bidding": "-", "product_code": "111", "cost": cost * 0.8, "ad_sales": sales, "products_sold": 8})
        rows.append({"period": period, "Periode laporan (teks)": text, "Urutan": 3, "Nama Iklan/Produk": "Kloset B", "Status": "-",
                     "Mode Bidding": "-", "product_code": "222", "cost": cost * 0.2, "ad_sales": 0, "products_sold": 0})
    return pd.DataFrame(rows)


def test_parse_fit_allocate():
    units, members = A.parse_units(_group(), None, None)
    assert len(units) == 1 and units[0].members == ["111", "222"] and len(units[0].history) == 2
    u = units[0]
    assert u.daily_cost > 0 and u.marginal(u.daily_cost) < u.roas  # hasil berkurang
    A.attach_economics(units, members, {"111": 0.20, "222": 0.10}, {"111": 1e12, "222": 1e12})
    assert abs(u.roas_impas - 5.0) < 1.0
    kejar = A.allocate(units, "Kejar target", gap_daily=5_000_000, roas_min=3)
    efisien = A.allocate(units, "Efisien", gap_daily=5_000_000, roas_min=3)
    assert kejar.cost[u.key] >= efisien.cost[u.key] >= u.daily_cost * 0.5
    s = A.summarize(units, kejar, days=20, target=1e9, predicted=8e8)
    assert s["Omzet tambahan"] >= 0 and s["% target"] >= 80
    hyg = A.group_hygiene(members, units, {"111": 0.2, "222": 0.1})
    assert (hyg["Kode produk"] == "222").any()
    assert not A.actions(units, kejar).empty
