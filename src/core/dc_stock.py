"""Stok DC fisik (Site 10062 DC Cikupa, Site 10036 DC Cipeucang) sebagai sumber pengisian Site 10037.

Site 10037 = stok toko Shopee (kolom "Stok: DC Cikupa" di ekspor Shopee, menu "Data stok Site 10037").
Bila stok Site 10037 kurang dari kebutuhan (prediksi + SS), kekurangan diambil dari Site 10062 dulu,
lalu Site 10036; sisanya tetap perlu PO ke supplier. Stok berstatus Blocked = Yes tidak dihitung.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

SHOPEE_SITE = "10037"
# Urutan pengambilan: DC Cikupa (satu kawasan dengan Site 10037) lalu DC Cipeucang.
DC_SITES: tuple[tuple[str, str, str], ...] = (
    ("10062", "DC Cikupa", "stock_10062"),
    ("10036", "DC Cipeucang", "stock_10036"),
)


def site_label(code: str) -> str:
    name = next((n for c, n, _ in DC_SITES if c == code), "")
    return f"Site {code}" + (f" ({name})" if name else "")


def _clean_sku(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip().str.replace(r"^(\d+)\.0+$", r"\1", regex=True)
    return text.where(~text.str.fullmatch(r"\d+"), text.str.lstrip("0").replace("", "0"))


def latest_site_stock(frame: pd.DataFrame | None) -> pd.DataFrame:
    """Stok tersedia per SKU dari snapshot terakhir: kolom sku, qty, snapshot_at."""
    columns = ["sku", "qty", "snapshot_at"]
    if frame is None or frame.empty or not {"sku", "qty"} <= set(frame.columns):
        return pd.DataFrame(columns=columns)
    work = frame.copy()
    stamp = ""
    if "_submitted_at" in work.columns:
        stamp = str(work["_submitted_at"].astype(str).max())
        work = work.loc[work["_submitted_at"].astype(str).eq(stamp)]
    work["sku"] = _clean_sku(work["sku"])
    work = work.loc[work["sku"].ne("")]
    qty = pd.to_numeric(work["qty"], errors="coerce")
    if "Stock On Hand" in work.columns:
        # Unggahan laporan replenishment lama: qty sempat terbaca dari kolom Quantity PO.
        soh = pd.to_numeric(work["Stock On Hand"], errors="coerce")
        qty = soh.where(soh.notna(), qty)
    qty = qty.fillna(0.0).clip(lower=0)
    if "blocked" in work.columns:
        blocked = work["blocked"].fillna("").astype(str).str.strip().str.lower().isin({"yes", "ya", "y", "true", "1"})
        qty = qty.where(~blocked, 0.0)
    grouped = work.assign(qty=qty).groupby("sku", as_index=False)["qty"].sum()
    grouped["snapshot_at"] = stamp
    return grouped


def site_codes_in(frame: pd.DataFrame | None) -> list[str]:
    """Kode site yang tertulis di kolom Store Code file (untuk mencegah salah menu)."""
    if frame is None or frame.empty or "store_code" not in frame.columns:
        return []
    codes = frame["store_code"].dropna().astype(str).str.strip().str.replace(r"\.0+$", "", regex=True)
    return sorted(code for code in codes.unique() if code and code.lower() != "nan")


def attach_dc_stock(table: pd.DataFrame, dc_frames: dict[str, pd.DataFrame] | None) -> pd.DataFrame:
    """Tambah stok_<site> (NaN bila file site belum diunggah, 0 bila SKU tidak ada di file) dan ada_data_<site>."""
    out = table
    key = out["sku"].fillna("").astype(str).str.strip() if "sku" in out.columns else pd.Series("", index=out.index)
    key = _clean_sku(key)
    for code, _name, source in DC_SITES:
        stock = latest_site_stock((dc_frames or {}).get(source))
        has = not stock.empty
        values = key.map(stock.set_index("sku")["qty"]).fillna(0.0) if has else pd.Series(np.nan, index=out.index)
        out[f"stok_{code}"] = values.to_numpy(dtype=float)
        out[f"ada_data_{code}"] = has
    return out


def transfer_plan(shortfall: float, available: dict[str, float | None]) -> tuple[dict[str, float], float]:
    """Bagi kekurangan ke DC sesuai urutan DC_SITES. Return ({site: unit diambil}, sisa yang belum terpenuhi)."""
    remaining = max(float(shortfall), 0.0)
    take: dict[str, float] = {}
    for code, _name, _source in DC_SITES:
        have = available.get(code)
        if remaining <= 0 or have is None or not math.isfinite(have) or have <= 0:
            continue
        units = float(min(remaining, math.floor(have)))
        if units > 0:
            take[code] = units
            remaining -= units
    return take, remaining


def transfer_text(shortfall: float, take: dict[str, float], remaining: float, any_dc_data: bool) -> str:
    if shortfall <= 0:
        return ""
    if not any_dc_data:
        return "Unggah stok Site 10062/10036"
    parts = [f"{_units(units)} dari Site {code}" for code, units in take.items()]
    if not parts:
        return f"Stok Site 10062 & 10036 kosong · PO {_units(remaining)} ke supplier"
    text = "Ambil " + " + ".join(parts)
    if remaining > 0:
        text += f" · kurang {_units(remaining)} → PO supplier"
    return text


def _units(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", ".")


def add_transfer_columns(table: pd.DataFrame, need_col: str = "m_butuh") -> pd.DataFrame:
    """Kekurangan Site 10037 (kebutuhan − stok) → ambil_<site>, kurang_setelah_dc, sumber_restock."""
    out = table
    if need_col not in out.columns or "stok" not in out.columns:
        return out
    codes = [code for code, _n, _s in DC_SITES]
    any_dc = any(bool(out.get(f"ada_data_{code}", pd.Series(False)).any()) for code in codes)
    takes = {code: [] for code in codes}
    rest, texts = [], []
    known = out["ada_data_stok"] if "ada_data_stok" in out.columns else out["stok"].notna()
    for idx in range(len(out)):
        stok = out["stok"].iat[idx]
        if not bool(known.iat[idx]) or pd.isna(stok):
            for code in codes:
                takes[code].append(np.nan)
            rest.append(np.nan)
            texts.append("")
            continue
        shortfall = max(0.0, math.ceil(float(out[need_col].iat[idx]) - float(stok)))
        available = {code: (None if pd.isna(out[f"stok_{code}"].iat[idx]) else float(out[f"stok_{code}"].iat[idx])) for code in codes}
        take, remaining = transfer_plan(shortfall, available)
        for code in codes:
            takes[code].append(take.get(code, 0.0))
        rest.append(remaining)
        texts.append(transfer_text(shortfall, take, remaining, any_dc))
    for code in codes:
        out[f"ambil_{code}"] = takes[code]
    out["kurang_setelah_dc"] = rest
    out["sumber_restock"] = texts
    return out


OUTSTANDING_SEP = " · Outstanding: "
NO_OUTSTANDING = " · Belum ada outstanding PO/TR/TO"


def dc_take_label(row) -> str:
    """Teks kolom Ambil dari DC: rencana ambil DC/PO + outstanding PO/TR/TO Site 10037.

    Contoh: "Ambil 5 dari Site 10062 · kurang 3 → PO supplier · Outstanding: PO 10 · TR 5 (sejak 05/11, 9 hari)";
    perlu restock tetapi belum ada proses: "… · Belum ada outstanding PO/TR/TO"; tanpa kebutuhan restock: "Outstanding: TR 5".
    Keterangan outstanding hanya muncul bila replenishment Site 10037 sudah diunggah (kolom outstanding_10037 ada)."""
    if row is None:
        return ""

    def text(name: str) -> str:
        value = row.get(name)
        return "" if value is None or (not isinstance(value, str) and pd.isna(value)) else str(value).strip()

    plan, pending = text("sumber_restock"), text("outstanding_10037")
    known = "outstanding_10037" in row
    if pending:
        since, days = row.get("os_sejak"), row.get("os_umur")
        if since is not None and not pd.isna(since) and days is not None and not pd.isna(days):
            mark = "≥ " if bool(row.get("os_minimal", False)) else ""
            pending += f" (sejak {pd.Timestamp(since):%d/%m}, {mark}{int(days)} hari)"
        return f"{plan}{OUTSTANDING_SEP}{pending}" if plan else f"Outstanding: {pending}"
    if plan and known:
        return plan + NO_OUTSTANDING
    return plan


def plan_only(label: str) -> str:
    """Bagian rencana DC/PO dari teks Ambil dari DC (tanpa keterangan outstanding)."""
    label = str(label or "")
    if label.startswith("Outstanding: "):
        return ""
    return label.split(OUTSTANDING_SEP)[0].split(NO_OUTSTANDING)[0]
