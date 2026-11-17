"""Cache kinerja: hasil sama dengan hitung langsung, dan data baru langsung terbaca setelah ditulis."""

from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import create_engine, func, select

from src.core import memo
from src.core.feature_store import FeatureStore, prediction_snapshot
from src.core.metrics import _normalize_lines, normalize_lines, order_metrics
from src.core.runs import RunRepository


def _orders() -> pd.DataFrame:
    return pd.DataFrame({
        "order_id": ["A", "A", "B", "C"],
        "order_time": pd.to_datetime(["2026-11-01 10:00", "2026-11-01 10:00", "2026-11-02 09:00", "2026-11-03 12:00"]),
        "sku": ["S1", "S2", "S1", "S3"],
        "product_name": ["P1", "P2", "P1", "P3"],
        "status": ["Selesai", "Selesai", "Batal", "Selesai"],
        "qty": [1, 2, 1, 3],
        "gross_sales": [10_000, 20_000, 10_000, 30_000],
        "order_amount": [30_000, 30_000, 10_000, 30_000],
    })


def test_memo_same_object_hits_and_new_object_recomputes():
    memo.clear()
    frame = pd.DataFrame({"a": [1, 2]})
    calls = []
    assert memo.by_frame("t", frame, (), lambda: calls.append(1) or 5) == 5
    assert memo.by_frame("t", frame, (), lambda: calls.append(1) or 6) == 5
    assert len(calls) == 1
    other = frame.copy()
    assert memo.by_frame("t", other, (), lambda: calls.append(1) or 7) == 7
    # Bentuk berubah (baris ditambah di tempat) → dihitung ulang.
    frame.loc[2] = [3]
    assert memo.by_frame("t", frame, (), lambda: 8) == 8


def test_normalize_lines_cached_equals_direct_and_is_copy():
    frame = _orders()
    first = normalize_lines(frame)
    pd.testing.assert_frame_equal(first, _normalize_lines(frame))
    first["sku"] = "rusak"
    pd.testing.assert_frame_equal(normalize_lines(frame), _normalize_lines(frame))
    assert order_metrics(frame) == order_metrics(frame.copy())


def test_feature_store_read_cache_invalidated_on_write(tmp_path):
    store = FeatureStore(create_engine(f"sqlite:///{tmp_path / 'f.db'}"))
    assert store.read("excluded_sku").empty
    store.insert("excluded_sku", [{"sku": "X1", "nama": "n", "jenis": "j", "added_at": pd.Timestamp("2026-11-15")}], username="u")
    assert store.read("excluded_sku")["sku"].tolist() == ["X1"]
    frame = store.read("excluded_sku")
    frame["sku"] = "ubah"
    assert store.read("excluded_sku")["sku"].tolist() == ["X1"]

    query = select(func.count()).select_from(prediction_snapshot)
    assert store.fetch(query, tables=["prediction_snapshot"])[0][0] == 0
    snap = pd.DataFrame({"target_date": [date(2026, 11, 20)], "sku": ["X1"], "varian": [""], "pred_qty": [1.0], "pred_sales": [10.0]})
    store.save_prediction_snapshot(1, snap, username="u")
    assert store.fetch(query, tables=["prediction_snapshot"])[0][0] == 1


def test_run_repository_cache_sees_new_and_deleted_runs(tmp_path):
    repo = RunRepository(create_engine(f"sqlite:///{tmp_path / 'r.db'}"), runs_root=tmp_path / "runs")
    assert repo.list_runs() == []
    record = repo.save({"orders": _orders(), "period": "bulan"}, run_by="u", periode="bulan", tgl_mulai="2026-11-01",
                       tgl_akhir="2026-11-30", parameter="qty", safety_stock=95, exclude=True, data_hash="h", duration=1.0)
    assert [r.id for r in repo.list_runs()] == [record.id]
    assert repo.last_success().id == record.id
    _rec, first = repo.load(record.id)
    _rec, second = repo.load(record.id)
    assert first is not second and first["orders"] is second["orders"]
    repo.delete(record.id)
    assert repo.list_runs() == [] and repo.get(record.id) is None
