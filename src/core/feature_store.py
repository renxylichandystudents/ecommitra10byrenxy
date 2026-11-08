"""Tabel data fitur baru (Revisi Final Tahap 1B).

Disimpan di database aplikasi yang sama dengan user dan riwayat analisa (`DATABASE_URL`;
Postgres di Streamlit Cloud, SQLite `data/app.db` di lokal) sehingga tidak hilang saat redeploy.

Data latih (9 menu upload) TIDAK disimpan atau ditulis di sini; fitur baru hanya membacanya
lewat loader yang sudah ada.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable, Mapping

import pandas as pd
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    delete,
    insert,
    select,
)
from sqlalchemy.engine import Engine

metadata = MetaData()


def _id() -> Column:
    return Column("id", Integer, primary_key=True, autoincrement=True)


prediction_snapshot = Table(
    "prediction_snapshot",
    metadata,
    _id(),
    Column("run_id", Integer, nullable=False, index=True),
    Column("created_at", DateTime, nullable=False),
    Column("target_date", Date, nullable=False),
    Column("sku", String(64), nullable=False),
    Column("varian", String(200), nullable=False, default=""),
    Column("pred_qty", Float, nullable=False),
    Column("pred_sales", Float, nullable=False),
)

report_meta = Table(
    "report_meta",
    metadata,
    Column("run_id", Integer, primary_key=True, autoincrement=False),
    Column("report_period", String(20), nullable=False),
)

excluded_sku = Table(
    "excluded_sku",
    metadata,
    Column("sku", String(64), primary_key=True),
    Column("nama", String(300), nullable=False, default=""),
    Column("jenis", String(60), nullable=False, default=""),
    Column("added_by", String(80), nullable=False, default=""),
    Column("added_at", DateTime, nullable=False),
)

cost_component = Table(
    "cost_component",
    metadata,
    _id(),
    Column("sku", String(64), nullable=False, index=True),
    Column("varian", String(200), nullable=False, default=""),
    Column("hpp", Float),
    Column("komisi_pct", Float),
    Column("layanan_pct", Float),
    Column("transaksi_pct", Float),
    Column("packing", Float),
    Column("voucher", Float),
    Column("ongkir_penjual", Float),
    Column("berlaku_mulai", Date, nullable=False),
    Column("berlaku_selesai", Date),
    Column("uploaded_by", String(80), nullable=False, default=""),
)

carton_dimension = Table(
    "carton_dimension",
    metadata,
    Column("sku", String(64), primary_key=True),
    Column("varian", String(200), primary_key=True, default=""),
    Column("panjang_cm", Float, nullable=False),
    Column("lebar_cm", Float, nullable=False),
    Column("tinggi_cm", Float, nullable=False),
    Column("isi_per_karton", Float, nullable=False, default=1),
)

warehouse_rack = Table(
    "warehouse_rack",
    metadata,
    _id(),
    Column("layout_version", String(40), nullable=False, index=True),
    Column("kode_rak", String(60), nullable=False),
    Column("zona", String(80), nullable=False),
    Column("panjang_cm", Float, nullable=False),
    Column("lebar_cm", Float, nullable=False),
    Column("tinggi_cm", Float, nullable=False),
    Column("faktor_isi", Float, nullable=False, default=0.85),
    UniqueConstraint("layout_version", "kode_rak", name="warehouse_rack_version_kode"),
)

# Gudang Site 10037: data replenishment harian dari sistem (satu snapshot per tanggal) dan lokasi denah (bila diperbarui).
warehouse_replenishment = Table(
    "warehouse_replenishment",
    metadata,
    _id(),
    Column("snapshot_date", Date, nullable=False, index=True),
    Column("sku", String(64), nullable=False),
    Column("nama", String(300), nullable=False, default=""),
    Column("kategori", String(120), nullable=False, default=""),
    Column("sub_kategori", String(120), nullable=False, default=""),
    Column("spesifikasi", String(40), nullable=False, default=""),
    Column("pick_location", String(40), nullable=False, default=""),
    Column("avg_sales", Float),
    Column("min_stock", Float),
    Column("max_stock", Float),
    Column("rop", Float),
    Column("soh", Float),
    Column("out_po", Float),
    Column("out_tr", Float),
    Column("over_stock_qty", Float),
    Column("abc", String(10), nullable=False, default=""),
    Column("stock_out", String(10), nullable=False, default=""),
    Column("vendor", String(200), nullable=False, default=""),
    Column("uploaded_by", String(80), nullable=False, default=""),
    Column("uploaded_at", DateTime, nullable=False),
)

warehouse_denah = Table(
    "warehouse_denah",
    metadata,
    _id(),
    Column("created_at", DateTime, nullable=False),
    Column("uploaded_by", String(80), nullable=False, default=""),
    Column("content", Text, nullable=False),
)

warehouse_location = Table(
    "warehouse_location",
    metadata,
    Column("lokasi", String(40), primary_key=True),
    Column("rak", String(10), nullable=False),
    Column("lorong", String(10), nullable=False),
    Column("bay", String(10), nullable=False),
    Column("level", String(10), nullable=False),
    Column("slot", String(10), nullable=False),
    Column("kategori", String(120), nullable=False, default=""),
)

import_po = Table(
    "import_po",
    metadata,
    _id(),
    Column("no_po", String(60), nullable=False, index=True),
    Column("sku", String(64), nullable=False),
    Column("varian", String(200), nullable=False, default=""),
    Column("qty", Float, nullable=False),
    Column("eta_rencana", Date),
    Column("eta_terbaru", Date),
    Column("status", String(40), nullable=False),
)

import_note = Table(
    "import_note",
    metadata,
    _id(),
    Column("no_po", String(60), nullable=False, index=True),
    Column("tanggal_catatan", Date, nullable=False),
    Column("status", String(40), nullable=False),
    Column("kondisi_barang", String(200), nullable=False, default=""),
    Column("catatan", Text, nullable=False, default=""),
    Column("author", String(80), nullable=False),
    Column("created_at", DateTime, nullable=False),
)

brand_portal = Table(
    "brand_portal",
    metadata,
    _id(),
    Column("periode", String(20), nullable=False, index=True),
    Column("kategori", String(120), nullable=False),
    Column("brand", String(120), nullable=False),
    Column("peringkat", Integer),
    Column("pangsa", Float),
)

sales_target = Table(
    "sales_target",
    metadata,
    Column("periode", String(20), primary_key=True),
    Column("target_sales_bersih", Float, nullable=False),
    Column("margin_min_pct", Float, nullable=False, default=8.0),
    Column("strategi", String(40), nullable=False, default=""),
    Column("budget_json", Text, nullable=False, default="{}"),
    Column("set_by", String(80), nullable=False, default=""),
)

run_info = Table(
    "run_info",
    metadata,
    Column("run_id", Integer, primary_key=True, autoincrement=False),
    Column("data_until", Date),
)

exposure_schedule = Table(
    "exposure_schedule",
    metadata,
    _id(),
    Column("periode", String(20), nullable=False, index=True),
    Column("tanggal", Date, nullable=False),
    Column("sku", String(64), nullable=False),
    Column("label", String(400), nullable=False, default=""),
    Column("kanal", String(40), nullable=False, default=""),
    Column("kategori", String(60), nullable=False, default=""),
    Column("spesial", String(60), nullable=False, default=""),
    Column("saved_by", String(80), nullable=False, default=""),
)

audit_log = Table(
    "audit_log",
    metadata,
    _id(),
    Column("at", DateTime, nullable=False, index=True),
    Column("username", String(80), nullable=False),
    Column("action", String(80), nullable=False),
    Column("detail_json", Text, nullable=False, default="{}"),
)

TABLES: dict[str, Table] = {table.name: table for table in metadata.sorted_tables}

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
IMPORT_STATUSES = ("Produksi", "Di kapal", "Tiba pelabuhan", "Bea cukai", "Dalam perjalanan ke DC", "Diterima DC")


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.to_pydatetime()
    if value is pd.NaT:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return value.item()
        except (ValueError, AttributeError):
            return value
    return value


def _records(rows: pd.DataFrame | Iterable[Mapping], table: Table) -> list[dict]:
    names = set(table.columns.keys())
    items = rows.to_dict("records") if isinstance(rows, pd.DataFrame) else [dict(row) for row in rows]
    out = []
    for item in items:
        record = {key: _clean(value) for key, value in item.items() if key in names}
        for column in table.columns:
            value = record.get(column.name)
            is_datetime = isinstance(column.type, DateTime)
            if isinstance(value, str) and isinstance(column.type, (Date, DateTime)):
                iso = bool(ISO_DATE.match(value.strip()))
                parsed = pd.to_datetime(value.strip(), dayfirst=not iso, errors="coerce")
                record[column.name] = None if pd.isna(parsed) else (parsed.to_pydatetime() if is_datetime else parsed.date())
            elif isinstance(value, datetime) and isinstance(column.type, Date) and not is_datetime:
                record[column.name] = value.date()
        out.append(record)
    return out


def _where(table: Table, filters: Mapping | None):
    if not filters:
        return None
    return and_(*[table.c[key] == value for key, value in filters.items()])


class FeatureStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        metadata.create_all(engine, checkfirst=True)

    def _table(self, name: str) -> Table:
        if name not in TABLES:
            raise KeyError(f"Tabel fitur tidak dikenal: {name}")
        return TABLES[name]

    def audit(self, username: str, action: str, detail: Mapping | None = None, *, conn=None) -> None:
        row = {"at": _now(), "username": username or "-", "action": action, "detail_json": json.dumps(dict(detail or {}), ensure_ascii=False, default=str)}
        if conn is not None:
            conn.execute(insert(audit_log), [row])
            return
        with self.engine.begin() as own:
            own.execute(insert(audit_log), [row])

    def insert(self, name: str, rows, *, username: str = "", action: str | None = None) -> int:
        table = self._table(name)
        records = _records(rows, table)
        if not records:
            return 0
        with self.engine.begin() as conn:
            conn.execute(insert(table), records)
            if name != "audit_log":
                self.audit(username, action or f"tambah:{name}", {"baris": len(records)}, conn=conn)
        return len(records)

    def replace(self, name: str, rows, *, keys: Iterable[str], username: str = "", action: str | None = None) -> int:
        """Hapus baris dengan kunci yang sama lalu sisipkan (upsert portabel SQLite/Postgres)."""
        table = self._table(name)
        records = _records(rows, table)
        if not records:
            return 0
        keys = list(keys)
        with self.engine.begin() as conn:
            for record in records:
                conn.execute(delete(table).where(_where(table, {key: record.get(key) for key in keys})))
            conn.execute(insert(table), records)
            self.audit(username, action or f"simpan:{name}", {"baris": len(records)}, conn=conn)
        return len(records)

    def remove(self, name: str, filters: Mapping, *, username: str = "", action: str | None = None) -> int:
        if not filters:
            raise ValueError("Hapus tanpa filter tidak diizinkan.")
        table = self._table(name)
        with self.engine.begin() as conn:
            count = conn.execute(delete(table).where(_where(table, filters))).rowcount or 0
            self.audit(username, action or f"hapus:{name}", {"filter": dict(filters), "baris": count}, conn=conn)
        return int(count)

    def clear(self, name: str, *, username: str = "", action: str | None = None) -> int:
        """Kosongkan seluruh tabel (dipakai saat denah gudang diganti total)."""
        table = self._table(name)
        with self.engine.begin() as conn:
            count = conn.execute(delete(table)).rowcount or 0
            self.audit(username, action or f"kosongkan:{name}", {"baris": count}, conn=conn)
        return int(count)

    def read(self, name: str, filters: Mapping | None = None) -> pd.DataFrame:
        table = self._table(name)
        query = select(table)
        clause = _where(table, filters)
        if clause is not None:
            query = query.where(clause)
        with self.engine.connect() as conn:
            rows = conn.execute(query).mappings().all()
        return pd.DataFrame(rows, columns=list(table.columns.keys()))

    def snapshot_dates(self, name: str, column: str = "snapshot_date") -> list:
        """Tanggal snapshot yang tersimpan (terbaru di depan)."""
        from sqlalchemy import distinct

        table = self._table(name)
        with self.engine.connect() as conn:
            rows = conn.execute(select(distinct(table.c[column])).order_by(table.c[column].desc())).all()
        return [row[0] for row in rows if row[0] is not None]

    def prune_snapshots(self, name: str, keep: int, column: str = "snapshot_date") -> int:
        """Simpan hanya `keep` snapshot terbaru agar tabel harian tidak terus membesar."""
        dates = self.snapshot_dates(name, column)
        if len(dates) <= keep:
            return 0
        table = self._table(name)
        with self.engine.begin() as conn:
            count = conn.execute(delete(table).where(table.c[column] < dates[keep - 1])).rowcount or 0
        return int(count)

    def save_prediction_snapshot(self, run_id: int, frame: pd.DataFrame, *, username: str = "") -> int:
        """frame: target_date, sku, varian, pred_qty, pred_sales (satu baris per SKU × tanggal window)."""
        if frame is None or frame.empty:
            return 0
        work = frame.copy()
        work["run_id"] = int(run_id)
        work["created_at"] = _now()
        work["varian"] = work["varian"].fillna("").astype(str) if "varian" in work.columns else ""
        with self.engine.begin() as conn:
            conn.execute(delete(prediction_snapshot).where(prediction_snapshot.c.run_id == int(run_id)))
            records = _records(work, prediction_snapshot)
            conn.execute(insert(prediction_snapshot), records)
            self.audit(username, "simpan:prediction_snapshot", {"run_id": int(run_id), "baris": len(records)}, conn=conn)
        return len(records)

    def set_report_period(self, run_id: int, period: str, *, username: str = "") -> None:
        self.replace("report_meta", [{"run_id": int(run_id), "report_period": str(period)}], keys=["run_id"], username=username, action="simpan:periode_laporan")

    def report_period(self, run_id: int) -> str | None:
        frame = self.read("report_meta", {"run_id": int(run_id)})
        return None if frame.empty else str(frame.iloc[0]["report_period"])
