import pandas as pd

from src.core.insight_live import month_restock, outstanding_for, outstanding_text, po_coverage, running_ads


def test_month_restock_splits_dc_and_po():
    top = pd.DataFrame(
        {
            "sku": ["A", "B", "C", "D"],
            "run_rest_qty": [10.7, 5.0, 8.0, 1.0],
            "ss": [2, 1, 2, 0],
            "stok": [0, 3, 1, 9],
            "ada_data_stok": [True, True, True, True],
            "stok_10062": [20, 1, 0, 0],
            "stok_10036": [0, 0, 0, 0],
        }
    )
    plan = month_restock(top)
    assert plan["prediksi"] == 24  # 10 + 5 + 8 + 1, dibulatkan ke bawah per SKU
    assert plan["kurang_sku"] == 3
    assert plan["restock"] == 12 + 3 + 9
    assert plan["dari_dc"] == 12 + 1
    assert plan["po"] == 2 + 9
    assert (plan["dc_penuh"], plan["dc_sebagian"], plan["po_saja"]) == (1, 1, 1)


def _ads():
    group = pd.DataFrame(
        {
            "period": ["2026-11-01"] * 4 + ["2026-11-01"],
            "Periode laporan (teks)": ["01/11/2026 - 13/11/2026"] * 4 + ["01/11/2026 - 14/11/2026"],
            "Urutan": [1, 2, 3, 4, 1],
            "Nama Iklan/Produk": ["Grup Kloset", "Kloset A", "Grup Lama", "Keran B", "Grup Kloset"],
            "Status": ["Berjalan", "-", "Berakhir", "-", "Dijeda"],
            "product_code": ["-", "111", "-", "222", "-"],
            "cost": [100, 50, 10, 5, 0],
            "ad_sales": [1000, 500, 0, 0, 0],
            "products_sold": [0, 0, 0, 0, 0],
            "_submitted_at": ["2026-11-13T20:00:00+07:00"] * 4 + ["2026-11-14T07:00:00+07:00"],
        }
    )
    overall = pd.DataFrame(
        {
            "period": ["2026-11-01"] * 2,
            "Periode laporan (teks)": ["01/11/2026 - 13/11/2026"] * 2,
            "Nama Iklan": ["Iklan Produk Otomatis", "Cat C"],
            "Status": ["Dijeda", "Berjalan"],
            "product_code": ["-", "333"],
            "cost": [10, 20],
            "ad_sales": [100, 200],
            "_submitted_at": ["2026-11-13T20:00:00+07:00"] * 2,
        }
    )
    auto = pd.DataFrame({"product_code": ["-", "444"], "cost": [10, 5], "_submitted_at": ["2026-11-13T20:00:00+07:00"] * 2})
    return {"ads_group": group, "ads_overall": overall, "ads_auto": auto}


def _stock():
    return pd.DataFrame({"product_code": ["111", "222", "333", "444"], "sku": ["A", "B", "C", "D"], "_submitted_at": ["2026-11-13T20:00:00+07:00"] * 4})


def test_running_ads_uses_upload_before_analysis():
    live = running_ads(_ads(), _stock(), cutoff=pd.Timestamp("2026-11-13 22:00"))
    # Grup Berjalan → A; grup Berakhir (B) tidak; produk tunggal Berjalan → C; otomatis Dijeda → D tidak.
    assert live["skus"] == {"A", "C"}
    assert (live["grup"], live["tunggal"], live["otomatis"]) == (1, 1, False)
    assert live["diunggah"] == pd.Timestamp("2026-11-13 20:00")


def test_running_ads_latest_upload_changes_result():
    live = running_ads(_ads(), _stock(), cutoff=None)
    # Unggahan grup 14/11: grup dijeda → hanya produk tunggal C yang berjalan.
    assert live["skus"] == {"C"}
    assert live["diunggah"] == pd.Timestamp("2026-11-14 07:00")


def test_outstanding_10037_and_po_coverage():
    repl = pd.DataFrame(
        {
            "sku": ["A", "B", "Z", "C"],
            "out_po": [10, 0, 99, 0],
            "out_tr": [5, 2, 0, 0],
            "out_to": [1, 0, 0, 0],
            "out_tr_lain": [0, 1, 0, 0],
        }
    )
    info = outstanding_for(["A", "B", "C"], repl, "2026-11-13")
    assert info["total"]["po"] == 10 and info["total"]["to"] == 1 and info["total"]["tr_toko_lain"] == 1
    assert info["sku_ada"] == 2
    inbound = info["per_sku"]["masuk"]
    assert inbound.to_dict() == {"A": 16, "B": 3, "C": 0}
    assert outstanding_text(info["per_sku"].loc["A"]) == "PO 10 · TR 5 · TO 1"
    cover = po_coverage(pd.Series({"A": 12, "B": 5, "C": 4}), inbound)
    assert (cover["sku_tertutup"], cover["sku_sebagian"], cover["sku_belum"]) == (1, 1, 1)
    assert cover["unit_po_baru"] == 2 + 4


def test_outstanding_old_snapshot_without_to_columns():
    repl = pd.DataFrame({"sku": ["A"], "out_po": [3.0], "out_tr": [None]})
    info = outstanding_for(["A"], repl)
    assert info["per_sku"].loc["A", "masuk"] == 3


def test_feature_store_adds_new_nullable_columns(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from src.core.feature_store import FeatureStore

    engine = create_engine(f"sqlite:///{tmp_path / 'f.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE warehouse_replenishment (id INTEGER PRIMARY KEY, snapshot_date DATE NOT NULL, sku VARCHAR(64) NOT NULL, out_po FLOAT)"))
    FeatureStore(engine)
    names = {c["name"] for c in inspect(engine).get_columns("warehouse_replenishment")}
    assert {"out_to", "out_tr_lain", "out_tr"} <= names
