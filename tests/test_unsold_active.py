import pandas as pd

from src.core.consolidation import _unsold_active


def _stock():
    return pd.DataFrame(
        {
            "sku": ["A", "B", "C", "A", "B", "C", "D"],
            "product_name": ["Kloset", "Keran", "Cat", "Kloset", "Keran", "Cat", "Semen"],
            "stock_dc_cikupa": [5, 0, 3, 5, 0, 0, 2],
            "_submitted_at": ["2026-11-07T23:00:00+07:00"] * 3 + ["2026-11-13T20:00:00+07:00"] * 4,
        }
    )


def test_unsold_active_uses_latest_snapshot_and_ages():
    dc = {"10062": pd.Series({"B": 4.0}), "10036": pd.Series(dtype=float)}
    table = _unsold_active(_stock(), {"A"}, dc, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-11-14"))
    assert table["SKU"].tolist() == ["B", "D", "C"]
    assert [c for c in table.columns if c.startswith("Stok")] == ["Stok Site 10037", "Stok Site 10036", "Stok Site 10062"]
    row = table.set_index("SKU")
    assert row.loc["B", "Stok Site 10062"] == 4
    assert row.loc["C", "Umur tidak terjual (hari)"] == 317
    assert row.loc["D", "Umur tidak terjual (hari)"] == 1
    assert "listing baru" in row.loc["D", "Tidak terjual sejak"]


def test_unsold_active_empty_when_all_sold():
    table = _unsold_active(_stock(), {"A", "B", "C", "D"}, {}, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-11-14"))
    assert table.empty
