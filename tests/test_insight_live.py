import pandas as pd

from src.core.insight_live import (
    month_restock,
    outstanding_age,
    outstanding_for,
    outstanding_text,
    po_coverage,
    running_ads,
    stuck_outstanding,
)


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


def _history():
    rows = [
        # A: TR terus ada sejak 09/11 (sebelumnya 0); B: TR baru muncul 14/11; C: hanya TO, baru tercatat 14/11 (kolom TO belum ada sebelumnya)
        ("2026-11-05", "A", 0, 0, None), ("2026-11-09", "A", 0, 5, None), ("2026-11-12", "A", 0, 5, None), ("2026-11-14", "A", 0, 5, 0),
        ("2026-11-05", "B", 0, 0, None), ("2026-11-12", "B", 0, 0, None), ("2026-11-14", "B", 0, 3, 0),
        ("2026-11-12", "C", 0, 0, None), ("2026-11-14", "C", 0, 0, 4),
        ("2026-11-14", "D", 0, 0, 0),
    ]
    return pd.DataFrame(rows, columns=["snapshot_date", "sku", "out_po", "out_tr", "out_to"])


def test_outstanding_age_runs_and_minimal():
    age = outstanding_age(_history(), today=pd.Timestamp("2026-11-14"))
    assert age.loc["A", "sejak"] == pd.Timestamp("2026-11-09") and age.loc["A", "umur_hari"] == 5 and not age.loc["A", "minimal"]
    assert age.loc["B", "umur_hari"] == 0 and not age.loc["B", "minimal"]
    assert age.loc["C", "umur_hari"] == 0 and age.loc["C", "minimal"]
    assert "D" not in age.index


def test_stuck_outstanding_only_short_with_dc_stock():
    table = pd.DataFrame(
        {
            "sku": ["A", "B", "C", "D", "E"],
            "product_name": list("abcde"),
            "m_status": ["Kosong", "Kurang", "Kurang · 2 hari", "Kosong", "Aman"],
            "stok": [0, 2, 1, 0, 50],
            "m_butuh": [10, 4, 3, 6, 10],
            "stok_10062": [5, 0, 1, 0, 9],
            "stok_10036": [0, 9, 0, 0, 9],
        }
    )
    hist = _history()
    repl = hist.loc[hist["snapshot_date"] == "2026-11-14"]
    out = stuck_outstanding(table, repl, hist, today=pd.Timestamp("2026-11-14")).set_index("SKU")
    assert set(out.index) == {"A", "B", "C"}  # D: DC kosong; E: aman
    assert out.loc["A", "Umur outstanding (hari)"] == 5
    assert out.loc["A", "Keterangan"] == "Outstanding 5 hari belum diterima · kurang 5 dari kebutuhan"
    assert "belum diketahui" in out.loc["C", "Keterangan"]
    assert out.loc["C", "Outstanding sejak"].startswith("≤ ")


def test_feature_store_adds_new_nullable_columns(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from src.core.feature_store import FeatureStore

    engine = create_engine(f"sqlite:///{tmp_path / 'f.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE warehouse_replenishment (id INTEGER PRIMARY KEY, snapshot_date DATE NOT NULL, sku VARCHAR(64) NOT NULL, out_po FLOAT)"))
    FeatureStore(engine)
    names = {c["name"] for c in inspect(engine).get_columns("warehouse_replenishment")}
    assert {"out_to", "out_tr_lain", "out_tr"} <= names


def test_dc_take_label_appends_outstanding():
    import pandas as pd

    from src.core.dc_stock import dc_take_label, plan_only
    from src.core.insight_live import attach_outstanding

    table = pd.DataFrame({
        "sku": ["A", "B", "C", "D"],
        "sumber_restock": ["Ambil 5 dari Site 10062 · kurang 3 → PO supplier", "Ambil 2 dari Site 10036", "", ""],
    })
    repl = pd.DataFrame({"sku": ["A", "C"], "out_po": [10, 0], "out_tr": [5, 0], "out_to": [0, 4], "out_tr_lain": [0, 0]})
    out = attach_outstanding(table, repl)
    labels = [dc_take_label(r) for _i, r in out.iterrows()]
    assert labels[0] == "Ambil 5 dari Site 10062 · kurang 3 → PO supplier · Outstanding: PO 10 · TR 5"
    assert labels[1] == "Ambil 2 dari Site 10036 · Belum ada outstanding PO/TR/TO"
    assert labels[2] == "Outstanding: TO 4"
    assert labels[3] == ""
    assert plan_only(labels[0]) == "Ambil 5 dari Site 10062 · kurang 3 → PO supplier"
    assert plan_only(labels[2]) == ""
    assert plan_only(labels[1]) == "Ambil 2 dari Site 10036"
    # Tanpa replenishment: kolom ada tapi kosong, teks tetap rencana DC saja.
    assert dc_take_label(attach_outstanding(table, None).iloc[0]) == table["sumber_restock"].iat[0]


def test_outstanding_plan_nets_shortfall_then_dc_then_po():
    import pandas as pd

    from src.core.insight_live import attach_outstanding, outstanding_plan, outstanding_verdict

    table = pd.DataFrame({
        "sku": ["A", "B", "C", "D"], "stok": [10.0, 0.0, 5.0, 50.0], "m_butuh": [100.0, 20.0, 30.0, 40.0],
        "ada_data_stok": [True] * 4, "stok_10062": [40.0, 5.0, 0.0, 0.0], "stok_10036": [10.0, 0.0, 0.0, 0.0],
    })
    repl = pd.DataFrame({"sku": ["A", "B", "D"], "out_po": [20, 0, 0], "out_tr": [10, 25, 0], "out_to": [0, 0, 5], "out_tr_lain": [0, 0, 0]})
    hist = pd.concat([repl.assign(snapshot_date="2026-11-01"), repl.assign(snapshot_date="2026-11-13")])
    out = attach_outstanding(table, repl, hist, today=pd.Timestamp("2026-11-14"), repl_date=pd.Timestamp("2026-11-13"))
    a, b, c, d = (outstanding_plan(out.iloc[i]) for i in range(4))
    # A: kurang 90, outstanding 30 → sisa 60 = 40 dari 10062 + 10 dari 10036 + PO 10; umur 13 hari (> 7) → ditindaklanjuti.
    assert (a["shortfall"], a["total"], a["rest"], a["take"], a["po"]) == (90, 30, 60, {"10062": 40.0, "10036": 10.0}, 10)
    assert a["days"] == 13 and a["stale"] and a["minimal"]
    assert "tindak lanjuti" in outstanding_verdict(a)
    # B: outstanding 25 ≥ kurang 20 → tidak perlu transfer/PO baru.
    assert b["rest"] == 0 and "tidak perlu transfer/PO baru" in outstanding_verdict(b)
    # C: tanpa outstanding, DC kosong → PO seluruhnya.
    assert c["total"] == 0 and c["po"] == 25 and "belum ada outstanding" in outstanding_verdict(c)
    # D: stok cukup, outstanding menambah stok.
    assert d["shortfall"] == 0 and "±55" in outstanding_verdict(d)
    # Tanpa replenishment: kolom outstanding tidak ada → kartu & Analisa menyebut data belum diunggah.
    assert outstanding_plan(attach_outstanding(table, None).iloc[0]) is None
