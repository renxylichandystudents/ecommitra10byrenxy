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


def test_push_score_components_transparent_and_no_invented_ctr():
    base = A.push_score_components(
        pred_omzet=2_000_000, stok_room=1_500_000, stok=120, qty_harian=2.0,
        roas=9.0, contrib=0.20, occupied=False, gap_daily=5_000_000,
    )
    assert 0 <= base["score"] <= 100
    assert base["gap"] > 0 and base["roas_bep"] > 0 and base["margin"] > 0
    assert base["free"] == 10.0
    assert base["ctr_pen"] == 0.0  # tanpa kolom CTR: jangan invent

    weak = A.push_score_components(
        pred_omzet=2_000_000, stok_room=1_500_000, stok=120, qty_harian=2.0,
        roas=9.0, contrib=0.20, occupied=False, gap_daily=5_000_000,
        ctr=0.005, has_ctr=True,
    )
    assert weak["ctr_pen"] < 0
    assert weak["score"] < base["score"]

    loss = A.push_score_components(
        pred_omzet=500_000, stok_room=100_000, stok=5, qty_harian=2.0,
        roas=2.0, contrib=-0.10, occupied=True, gap_daily=5_000_000,
    )
    assert loss["margin"] < 5
    assert loss["free"] == 0.0
    assert abs(A.safe_bep_roas(0.20) - (1.0 / 0.20 * A.SAFE_BEP_BUFFER)) < 1e-9


def test_enrich_push_scores_routes_and_top_tables():
    products = pd.DataFrame([
        {"product_code": "9", "nama": "Laris", "omzet_harian": 2_000_000, "qty_harian": 4, "stok_room": 1e6, "stok": 80},
        {"product_code": "2", "nama": "Lemah", "omzet_harian": 50_000, "qty_harian": 0.2, "stok_room": 1e5, "stok": 3},
    ])
    selection = pd.DataFrame([
        {"Saran": "Buat iklan tunggal", "Produk": "Laris", "Kode produk": "9", "Iklan sekarang": "Belum diiklankan",
         "Biaya iklan/hari": 0.0, "Omzet iklan/hari": 0.0, "ROAS 2 bulan": float("nan"), "Porsi omzet grup": float("nan"),
         "Prediksi omzet/hari": 2_000_000, "Prediksi qty/hari": 4.0, "Stok": 80, "Alasan": "kandidat", "_unit": ""},
        {"Saran": "Tambahkan ke grup", "Produk": "Lemah", "Kode produk": "2", "Iklan sekarang": "Belum diiklankan",
         "Biaya iklan/hari": 0.0, "Omzet iklan/hari": 0.0, "ROAS 2 bulan": 3.0, "Porsi omzet grup": float("nan"),
         "Prediksi omzet/hari": 50_000, "Prediksi qty/hari": 0.2, "Stok": 3, "Alasan": "mid", "_unit": ""},
        {"Saran": "Sudah di iklan lain", "Produk": "Busy", "Kode produk": "7", "Iklan sekarang": "Iklan aktif lain",
         "Biaya iklan/hari": 0.0, "Omzet iklan/hari": 0.0, "ROAS 2 bulan": float("nan"), "Porsi omzet grup": float("nan"),
         "Prediksi omzet/hari": 100_000, "Prediksi qty/hari": 1.0, "Stok": 10, "Alasan": "occupied", "_unit": ""},
    ])
    out = A.enrich_push_scores(selection, products, {"9": 0.25, "2": 0.05, "7": 0.2}, gap_daily=4_000_000, occupied={"7"})
    assert "Push skor" in out.columns and "Aksi push" in out.columns and "Alasan chip" in out.columns
    assert set(out["Aksi push"]).issubset(set(A.PUSH_ACTIONS))
    row9 = out.set_index("Kode produk").loc["9"]
    assert row9["Rute"] == A.ROUTE_SINGLE
    assert row9["Aksi push"] in (A.PUSH_PRIORITIZE, A.PUSH_HOLD, A.PUSH_SCALE)
    assert 0 <= float(row9["% gap tertutup"]) <= 100
    busy = out.set_index("Kode produk").loc["7"]
    assert busy["Aksi push"] == A.PUSH_PAUSE
    single, group = A.push_top_tables(out, top_n=5)
    assert not single.empty
    assert "Push skor" in single.columns
