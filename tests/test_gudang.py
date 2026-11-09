from io import BytesIO

import openpyxl
import pandas as pd

from src.core import gudang


def _raw():
    head = [["UserID: x"], ["Replenishment Calculation by Date"], [], ["Site: 10037 - ECommerce Jakarta, Category: (ALL), Replenishment Date: 23 Sep 2026"]]
    cols = ["Item No", "Item Name", "Item Category", "Spesifikasi Barang", "Pick Locatoin", "Minimum Stock", "Maximum Stock", "Reorder Point", "Stock On Hand", "Outstanding PO", "Outstanding TR"]
    rows = [
        ["0300002038", "Kran", "PLUMBING", "Kecil", "G010010401", 2, 10, 3, 0, 0, 0],
        ["0100024295", "Vinyl", "FLOORING AND WALL", "Besar", None, 14, 20, 4, 56, 0, 0],
        ["0900007910", "Obeng", "TOOLS", "Kecil", None, 1, 5, 2, 4, 0, 0],
    ]
    width = len(cols)
    return pd.DataFrame([r + [None] * (width - len(r)) for r in head] + [cols] + rows)


def _locations():
    rows = [["G", "01", "001", lvl, "01", f"G01001{lvl}01", "PLUMBING"] for lvl in ("01", "02", "03", "04")]
    rows += [["R", "04", f"{b:03d}", "01", "01", f"R04{b:03d}0101", "FLOORING & WALL"] for b in (11, 12)]
    return gudang.parse_location_sheet(pd.DataFrame(rows))


def test_parse_and_view():
    repl, snap = gudang.parse_replenishment(_raw())
    assert str(snap) == "2026-09-23"
    assert repl["sku"].tolist() == ["300002038", "100024295", "900007910"]
    assert repl.loc[1, "kategori"] == "FLOORING & WALL"
    view = gudang.build_view(_locations(), repl, stock={"300002038": 0.0})
    items = view["items"].set_index("sku")
    assert items.loc["300002038", "status"] == "Kosong"
    assert "Isi ulang ±10" in items.loc["300002038", "saran"]
    assert items.loc["100024295", "status"] == "Stok berlebih"
    assert "lokasi ambil" in items.loc["900007910", "saran"]
    loc = view["locations"].set_index("lokasi")
    assert bool(loc.loc["G010010401", "terisi"]) and not bool(loc.loc["G010010201", "terisi"])
    cats = view["categories"].set_index("kategori")
    assert cats.loc["FLOORING & WALL", "rak_pct"] == 50.0
    value, note = gudang.capacity_card(view)
    assert "dari 6 lokasi" in note


def test_build_denah_maps_bay_cells():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "LAY OUT"
    ws["H25"] = 30
    ws["J25"] = 31
    ws["H60"] = 15
    ws["G24"] = "R01"
    buffer = BytesIO()
    wb.save(buffer)
    found = gudang.read_layout_workbook(buffer.getvalue())
    keys = {c["k"] for c in found["denah"]["cells"] if c.get("k")}
    assert keys == {"R01-030", "R01-031", "G01-015"}



def test_master_applied_and_incomplete_listed():
    old, _ = gudang.parse_replenishment(_raw())
    master = gudang.master_from_repl(old)
    assert master["sku"].tolist() == ["300002038", "100024295", "900007910"]
    new, _ = gudang.parse_replenishment(_raw().drop(columns=[3, 4]))
    new = pd.concat([new, pd.DataFrame([{"sku": "123", "nama": "Baru", "kategori": "TOOLS"}])], ignore_index=True).fillna("")
    filled = gudang.apply_master(new, master)
    assert filled["spesifikasi"].tolist() == ["Kecil", "Besar", "Kecil", ""]
    assert filled["pick_location"].tolist() == ["G010010401", "", "", ""]
    todo = gudang.incomplete_items(filled)
    assert dict(zip(todo["sku"], todo["kurang"])) == {"900007910": "Pick Location", "123": "Spesifikasi Barang"}
    edit = pd.DataFrame([{"sku": "123", "spesifikasi": "Besar", "pick_location": ""}])
    master = pd.concat([master, edit], ignore_index=True)
    assert gudang.incomplete_items(gudang.apply_master(new, master))["sku"].tolist() == ["900007910"]


def test_master_upload_parsed_and_validated():
    raw = pd.DataFrame([
        ["Item No", "Item Name", "Spesifikasi Barang", "Pick Location"],
        ["0300002038", "Kran", "kecil", "g010010401"],
        ["123", "Baru", "Sedang", None],
        ["456", "Lain", "Kecil", "Z999"],
        ["789", "Kosong", None, None],
    ])
    rows = gudang.parse_master_upload(raw)
    assert rows.loc[0, ["sku", "spesifikasi", "pick_location"]].tolist() == ["300002038", "Kecil", "G010010401"]
    problems = gudang.master_problems(rows, {"G010010401"})
    assert problems["sku"].tolist() == ["123", "456"]


def test_missing_master_table_created_on_use_and_seeded_from_older_snapshot():
    from datetime import date as _date

    from sqlalchemy import create_engine, inspect, text

    from src.core.feature_store import FeatureStore
    from src.ui import gudang_view

    engine = create_engine("sqlite://")
    store = FeatureStore(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE warehouse_item_master"))
    store._ready.discard("warehouse_item_master")
    old = pd.DataFrame({"snapshot_date": [_date(2026, 9, 23)] * 2, "sku": ["111", "222"], "spesifikasi": ["Besar", "Kecil"], "pick_location": ["", "G-01"]})
    new = pd.DataFrame({"snapshot_date": [_date(2026, 11, 9)] * 2, "sku": ["111", "222"], "spesifikasi": ["", ""], "pick_location": ["", ""]})
    store.insert("warehouse_replenishment", pd.concat([old, new]).assign(uploaded_by="t", uploaded_at=pd.Timestamp("2026-11-09 10:00")))
    master = gudang_view.load_master(store, store.snapshot_dates("warehouse_replenishment"))
    assert "warehouse_item_master" in inspect(engine).get_table_names()
    assert sorted(master["sku"]) == ["111", "222"]
    assert len(store.read("warehouse_item_master")) == 2
