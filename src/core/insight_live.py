"""Bahan kotak Insight Ringkasan: restock bulan berjalan, iklan yang sedang berjalan, dan outstanding PO/TR/TO."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.core.dc_stock import DC_SITES, _clean_sku, transfer_plan
from src.core.inventory import snapshot_time

def month_restock(top: pd.DataFrame) -> dict | None:
    """Restock untuk sisa bulan berjalan per SKU = prediksi sisa bulan (unit utuh) + SS − stok Site 10037, lalu DC → PO."""
    if top is None or top.empty or not {"run_rest_qty", "ss", "stok"} <= set(top.columns):
        return None
    known = top["ada_data_stok"].astype(bool) if "ada_data_stok" in top.columns else top["stok"].notna()
    rest = np.floor(pd.to_numeric(top["run_rest_qty"], errors="coerce").fillna(0.0) + 1e-9)
    need = rest + pd.to_numeric(top["ss"], errors="coerce").fillna(0.0)
    stok = pd.to_numeric(top["stok"], errors="coerce").fillna(0.0)
    gap = np.ceil((need - stok).clip(lower=0)).where(known, 0.0)
    codes = [code for code, _n, _s in DC_SITES]
    from_dc = po = 0.0
    full = partly = po_only = 0
    for idx in gap.index[gap > 0]:
        available = {code: (None if f"stok_{code}" not in top.columns or pd.isna(top.at[idx, f"stok_{code}"]) else float(top.at[idx, f"stok_{code}"]))
                     for code in codes}
        take, remaining = transfer_plan(float(gap.at[idx]), available)
        got = sum(take.values())
        from_dc += got
        po += remaining
        if remaining <= 0:
            full += 1
        elif got > 0:
            partly += 1
        else:
            po_only += 1
    return {
        "prediksi": float(rest.sum()),
        "ss": float(pd.to_numeric(top["ss"], errors="coerce").fillna(0.0).sum()),
        "kurang_sku": int((gap > 0).sum()),
        "restock": float(gap.sum()),
        "dari_dc": from_dc,
        "po": po,
        "dc_penuh": full,
        "dc_sebagian": partly,
        "po_saja": po_only,
        "gap": gap,
    }


def _latest_upload(frame: pd.DataFrame | None, cutoff) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    """Baris unggahan terakhir yang disimpan sebelum cutoff (waktu analisa dijalankan)."""
    if frame is None or frame.empty:
        return pd.DataFrame(), None
    if "_submitted_at" not in frame.columns:
        return frame, None
    stamp = snapshot_time(frame["_submitted_at"].astype(str))
    keep = stamp.notna()
    if cutoff is not None and pd.notna(cutoff):
        keep &= stamp.le(pd.Timestamp(cutoff))
    if not keep.any():
        return pd.DataFrame(), None
    last = stamp.loc[keep].max()
    return frame.loc[keep & stamp.eq(last)].copy(), last


def _running(status) -> bool:
    return "berjalan" in str(status or "").lower()


def running_ads(ads: dict[str, pd.DataFrame], stock: pd.DataFrame | None, cutoff=None) -> dict | None:
    """SKU di iklan yang berstatus Berjalan pada unggahan laporan iklan terakhir sebelum cutoff.

    ads: {"ads_group", "ads_overall", "ads_auto"}. Grup: anggota grup Berjalan; produk tunggal: baris Berjalan di Semua Laporan Iklan;
    otomatis: produk yang berbiaya di laporan iklan otomatis bila iklan otomatis Berjalan (status dari Semua Laporan Iklan).
    """
    from src.core.ads import _variant_pairs
    from src.core.ads_strategy import parse_units

    group, group_at = _latest_upload(ads.get("ads_group"), cutoff)
    overall, overall_at = _latest_upload(ads.get("ads_overall"), cutoff)
    auto, auto_at = _latest_upload(ads.get("ads_auto"), cutoff)
    if group.empty and overall.empty and auto.empty:
        return None
    units, members = parse_units(group if not group.empty else None, overall if not overall.empty else None, None)
    auto_status = "Berjalan"
    if not overall.empty and "Status" in overall.columns:
        name_col = "Nama Iklan" if "Nama Iklan" in overall.columns else "product_name"
        auto_rows = overall.loc[overall[name_col].astype(str).str.lower().str.contains("otomatis")]
        if not auto_rows.empty:
            auto_status = str(auto_rows["Status"].iloc[-1])
    run_units = [u for u in units if _running(u.status) and u.key != "auto"]
    codes: set[str] = set()
    for unit in run_units:
        if not members.empty:
            part = members.loc[members["unit"] == unit.key]
            part = part.loc[part["periode"] == part["periode"].max()] if not part.empty else part
            codes |= set(part["product_code"].astype(str))
        codes |= set(unit.members)
    auto_codes: set[str] = set()
    if not auto.empty and _running(auto_status) and "product_code" in auto.columns:
        code = auto["product_code"].fillna("").astype(str).str.strip()
        cost = pd.to_numeric(auto.get("cost", 0), errors="coerce").fillna(0.0)
        auto_codes = set(code.loc[code.ne("") & code.ne("-") & cost.gt(0)])
    pairs = _variant_pairs(stock)
    to_sku = pairs.groupby("product_code")["sku"].apply(set).to_dict() if not pairs.empty else {}
    skus = {s for c in codes | auto_codes for s in to_sku.get(c, set())}
    stamps = [t for t in (group_at, overall_at, auto_at) if t is not None]
    periods = []
    for frame in (group, overall, auto):
        if not frame.empty and "Periode laporan (teks)" in frame.columns:
            periods += [str(v) for v in frame["Periode laporan (teks)"].dropna().unique()]
    return {
        "skus": skus,
        "grup": sum(1 for u in run_units if u.jenis == "Grup"),
        "tunggal": sum(1 for u in run_units if u.jenis.startswith("Produk tunggal")),
        "otomatis": bool(auto_codes),
        "kode": len(codes | auto_codes),
        "kode_tanpa_sku": len({c for c in codes | auto_codes if c not in to_sku}),
        "diunggah": max(stamps) if stamps else None,
        "periode": sorted(set(periods))[-1] if periods else "",
    }


def outstanding_10037(repl: pd.DataFrame | None) -> pd.DataFrame:
    """Outstanding per SKU dari Replenishment Calculation by Date Site 10037: po, tr, to, tr_toko_lain, masuk (jumlah keempatnya).

    Snapshot lama (sebelum kolom TO & TR dari toko lain disimpan) terbaca 0 untuk kedua kolom itu."""
    columns = ["po", "tr", "to", "tr_toko_lain", "masuk"]
    if repl is None or repl.empty or "sku" not in repl.columns:
        return pd.DataFrame(columns=columns)
    source = {"po": "out_po", "tr": "out_tr", "to": "out_to", "tr_toko_lain": "out_tr_lain"}
    work = pd.DataFrame({"sku": _clean_sku(repl["sku"].astype(str))})
    for name, column in source.items():
        work[name] = pd.to_numeric(repl[column], errors="coerce").fillna(0.0).to_numpy() if column in repl.columns else 0.0
    out = work.loc[work["sku"].ne("")].groupby("sku")[list(source)].sum()
    out["masuk"] = out[list(source)].sum(axis=1)
    return out


def attach_outstanding(table: pd.DataFrame, repl: pd.DataFrame | None) -> pd.DataFrame:
    """Tambah kolom outstanding_10037 ("PO 10 · TR 5", kosong bila tidak ada) per SKU dari replenishment Site 10037 terbaru."""
    if table is None or table.empty or "sku" not in table.columns:
        return table
    pending = outstanding_10037(repl)
    if pending.empty:
        return table.assign(outstanding_10037="")
    keys = _clean_sku(table["sku"].fillna("").astype(str))
    return table.assign(outstanding_10037=[outstanding_text(pending.loc[k]) if k in pending.index else "" for k in keys])


def outstanding_text(row) -> str:
    """'PO 10 · TR 5 · TO 2' (hanya yang > 0)."""
    if row is None:
        return ""
    labels = (("po", "PO"), ("tr", "TR"), ("to", "TO"), ("tr_toko_lain", "TR toko lain"))
    parts = [f"{label} {int(round(float(row[name]))):,}".replace(",", ".") for name, label in labels if float(row.get(name, 0) or 0) > 0]
    return " · ".join(parts)


OUT_TYPES = {"po": "out_po", "tr": "out_tr", "to": "out_to", "tr_toko_lain": "out_tr_lain"}


def outstanding_age(history: pd.DataFrame | None, today=None) -> pd.DataFrame:
    """Sejak kapan outstanding SKU Site 10037 terlihat terus-menerus di snapshot replenishment.

    Per jenis (PO/TR/TO/TR toko lain) dicari snapshot pertama dari rangkaian terakhir yang nilainya > 0. Rangkaian berhenti di snapshot
    bernilai 0; bila berhenti karena kolom belum tercatat (kosong di snapshot lama) atau sampai snapshot tertua, umur = minimal (≥).
    Kolom: sejak, umur_hari, minimal, snapshot (jumlah snapshot berturut-turut), terakhir."""
    columns = ["sejak", "umur_hari", "minimal", "snapshot", "terakhir"]
    if history is None or history.empty or not {"sku", "snapshot_date"} <= set(history.columns):
        return pd.DataFrame(columns=columns)
    work = history.copy()
    work["sku"] = _clean_sku(work["sku"].astype(str))
    work["snapshot_date"] = pd.to_datetime(work["snapshot_date"], errors="coerce").dt.normalize()
    work = work.dropna(subset=["snapshot_date"])
    dates = sorted(work["snapshot_date"].unique(), reverse=True)
    if not dates:
        return pd.DataFrame(columns=columns)
    latest, oldest = dates[0], dates[-1]
    ref = pd.Timestamp(today).normalize() if today is not None else pd.Timestamp(latest)
    values = {}
    for name, column in OUT_TYPES.items():
        raw = pd.to_numeric(work[column], errors="coerce") if column in work.columns else pd.Series(np.nan, index=work.index)
        grid = work.assign(v=raw).groupby(["sku", "snapshot_date"])["v"].sum(min_count=1).unstack("snapshot_date")
        recorded = work.assign(v=raw).groupby("snapshot_date")["v"].apply(lambda s: s.notna().any())
        # Kolom tercatat di snapshot itu: SKU yang tidak ada / kosong = 0. Belum tercatat (snapshot lama): tetap NaN = tidak diketahui.
        for day in grid.columns:
            if bool(recorded.get(day, False)):
                grid[day] = grid[day].fillna(0.0)
        values[name] = grid
    now = values["po"].index
    rows = {}
    for sku in now:
        best, minimal, count = None, False, 0
        for name, table in values.items():
            row = table.loc[sku] if sku in table.index else None
            if row is None or not (row.get(latest, 0) > 0):
                continue
            since, run, short = latest, 0, False
            for day in dates:
                value = row.get(day, np.nan)
                if pd.isna(value):
                    short = True
                    break
                if value <= 0:
                    break
                since, run = day, run + 1
            else:
                short = True
            short = short or since == oldest
            if best is None or since < best:
                best, minimal, count = since, short, run
            elif since == best:
                minimal = minimal or short
        if best is not None:
            rows[sku] = {"sejak": pd.Timestamp(best), "umur_hari": int((ref - pd.Timestamp(best)).days), "minimal": minimal,
                         "snapshot": count, "terakhir": pd.Timestamp(latest)}
    return pd.DataFrame.from_dict(rows, orient="index", columns=columns)


def stuck_outstanding(table: pd.DataFrame, repl: pd.DataFrame | None, history: pd.DataFrame | None, today=None, top_n: int = 50) -> pd.DataFrame:
    """SKU yang Kosong/Kurang di Site 10037 padahal stok Site 10062/10036 ada, dengan outstanding dan umurnya."""
    if table is None or table.empty or not {"sku", "stok", "m_butuh"} <= set(table.columns):
        return pd.DataFrame()
    status = table["m_status"].astype(str).str.split(" · ").str[0].replace({"Tipis": "Kurang"}) if "m_status" in table.columns else pd.Series("", index=table.index)
    dc_cols = [c for c in ("stok_10062", "stok_10036") if c in table.columns]
    if not dc_cols:
        return pd.DataFrame()
    dc = table[dc_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    work = table.loc[status.isin({"Kosong", "Kurang"}) & dc.sum(axis=1).gt(0)].copy()
    if work.empty:
        return pd.DataFrame()
    keys = _clean_sku(work["sku"].astype(str))
    pending = outstanding_10037(repl)
    age = outstanding_age(history, today)
    stok = pd.to_numeric(work["stok"], errors="coerce").fillna(0.0)
    need = np.ceil((pd.to_numeric(work["m_butuh"], errors="coerce").fillna(0.0) - stok).clip(lower=0))
    out_total = keys.map(pending["masuk"]).fillna(0.0) if not pending.empty else pd.Series(0.0, index=work.index)
    since = keys.map(age["sejak"]) if not age.empty else pd.Series(pd.NaT, index=work.index)
    days = keys.map(age["umur_hari"]) if not age.empty else pd.Series(np.nan, index=work.index)
    minimal = keys.map(age["minimal"]).eq(True) if not age.empty else pd.Series(False, index=work.index)
    rank = pd.Series(range(1, len(table) + 1), index=table.index).loc[work.index]

    def process(total, need_units, day, short) -> str:
        if total <= 0:
            return "Belum ada outstanding · buat TR/TO dari DC"
        if pd.notna(day) and day > 0:
            text = f"Outstanding {'≥ ' if short else ''}{int(day)} hari belum diterima"
        elif short:
            text = "Outstanding mulai tercatat di unggahan ini, umur sebenarnya belum diketahui"
        else:
            text = "Outstanding baru muncul di unggahan terakhir"
        if total < need_units:
            text += f" · kurang {int(need_units - total)} dari kebutuhan"
        return text

    result = pd.DataFrame(
        {
            "Rank": rank.where(rank <= top_n),
            "SKU": work["sku"].astype(str),
            "Produk": work["product_name"].astype(str) if "product_name" in work.columns else "",
            "Status Site 10037": status.loc[work.index],
            "Stok Site 10037": stok,
            "Stok Site 10062": dc["stok_10062"].loc[work.index] if "stok_10062" in dc else np.nan,
            "Stok Site 10036": dc["stok_10036"].loc[work.index] if "stok_10036" in dc else np.nan,
            "Kebutuhan restock": need,
            "Outstanding": [outstanding_text(pending.loc[k]) if not pending.empty and k in pending.index else "" for k in keys],
            "Total outstanding": out_total,
            "Outstanding sejak": [(("≤ " if m else "") + f"{d:%d/%m/%Y}") if pd.notna(d) else "" for d, m in zip(since, minimal)],
            "Umur outstanding (hari)": days,
            "Keterangan": [process(t, n, d, m) for t, n, d, m in zip(out_total, need, days, minimal)],
        }
    )
    result["_kosong"] = result["Status Site 10037"].eq("Kosong")
    result = result.sort_values(["_kosong", "Umur outstanding (hari)", "Kebutuhan restock"], ascending=False, na_position="last")
    return result.drop(columns="_kosong").reset_index(drop=True)


def outstanding_for(skus: list[str], repl_10037: pd.DataFrame | None, repl_date=None) -> dict | None:
    """Outstanding Site 10037 untuk daftar SKU: total per jenis dan per SKU."""
    table = outstanding_10037(repl_10037)
    if table.empty:
        return None
    keys = [_clean_sku(pd.Series([s])).iat[0] for s in skus]
    part = table.reindex(keys).fillna(0.0)
    part.index = list(skus)
    return {
        "tanggal": repl_date,
        "total": {name: float(part[name].sum()) for name in ("po", "tr", "to", "tr_toko_lain", "masuk")},
        "sku_ada": int((part["masuk"] > 0).sum()),
        "per_sku": part,
    }


def po_coverage(need_po: pd.Series, inbound: pd.Series) -> dict:
    """Kebutuhan PO per SKU dibanding barang masuk yang sudah dalam proses (outstanding PO/TR)."""
    need = pd.to_numeric(need_po, errors="coerce").fillna(0.0)
    have = pd.to_numeric(inbound, errors="coerce").fillna(0.0).reindex(need.index).fillna(0.0)
    mask = need > 0
    covered = np.minimum(need, have).where(mask, 0.0)
    return {
        "sku_perlu_po": int(mask.sum()),
        "unit_perlu_po": float(need.where(mask, 0.0).sum()),
        "sku_tertutup": int((mask & (have >= need)).sum()),
        "sku_sebagian": int((mask & (have > 0) & (have < need)).sum()),
        "sku_belum": int((mask & (have <= 0)).sum()),
        "unit_tertutup": float(covered.sum()),
        "unit_po_baru": float((need - have).clip(lower=0).where(mask, 0.0).sum()),
    }
