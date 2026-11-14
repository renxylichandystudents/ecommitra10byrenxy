import pandas as pd

from src.core.decision_table import stock_shortage


def test_shortage_parts_add_up_to_total():
    table = pd.DataFrame(
        {
            "m_status": ["Kosong", "Kurang · 3 hari", "Kurang", "Tipis", "Aman", "Tanpa data stok", "Kosong"],
            "di_bawah_ss": [True, True, False, False, False, False, False],
        }
    )
    out = stock_shortage(table)
    assert out["kurang"] == 5
    assert out["kosong"] == 2
    assert out["bawah_ss_berstok"] == 1
    assert out["di_atas_ss"] == 2
    assert out["kosong"] + out["bawah_ss_berstok"] + out["di_atas_ss"] == out["kurang"]
    assert out["aman"] == 1 and out["tanpa_data"] == 1
    assert out["kurang"] + out["aman"] + out["tanpa_data"] == len(table)
