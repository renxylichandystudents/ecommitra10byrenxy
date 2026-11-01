"""Satu sumber definisi metrik transaksi untuk semua halaman (Ringkasan, Data, Laporan).

Temuan audit K1 & K2: angka batal, retur, sales bersih, tingkat batal, dan pesanan belum bayar
sempat berbeda antar halaman karena tiap halaman menghitung sendiri (periode berbeda, baris vs
pesanan, harga baris vs Total Pembayaran). Semua halaman sekarang memanggil fungsi di sini.

Definisi (lihat juga README bagian "Kamus metrik"):
- Jumlah pesanan      : No. Pesanan unik, semua status.
- Pesanan batal       : No. Pesanan unik berstatus batal.
- Tingkat batal       : pesanan batal ÷ jumlah pesanan × 100 (tingkat pesanan, bukan baris).
- Unit retur          : Jumlah − QTY bersih pada baris yang tidak batal.
- Sales bersih        : Total Pembayaran sekali per No. Pesanan, tanpa pesanan batal, dikurangi
                        porsi baris yang diretur (termasuk retur sebagian).
- Belum bayar dikejar : pesanan batal karena belum dibayar, kecuali pembeli itu sudah punya
                        pesanan terbayar untuk SKU yang sama pada periode yang sama.
"""

from __future__ import annotations

import pandas as pd

from src.ingest import ORDER_LINES_GROSS, attach_order_line_totals, cancelled_status_mask, order_revenue

UNPAID_HINTS = ("belum dibayar", "belum bayar")


def _order_ids(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty or "order_id" not in frame.columns:
        return pd.Series(dtype=str)
    ids = frame["order_id"].fillna("").astype(str).str.strip()
    return ids.where(~ids.str.lower().isin({"", "nan", "none", "-"}), "row:" + frame.index.astype(str))


def cancel_mask(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty or "status" not in frame.columns:
        return pd.Series(False, index=frame.index if frame is not None else [])
    return cancelled_status_mask(frame["status"])


def count_orders(frame: pd.DataFrame) -> int:
    ids = _order_ids(frame)
    return int(ids.nunique()) if not ids.empty else 0


def cancelled_orders(frame: pd.DataFrame) -> int:
    if frame is None or frame.empty:
        return 0
    return count_orders(frame.loc[cancel_mask(frame)])


def cancel_rate_pct(frame: pd.DataFrame) -> float:
    total = count_orders(frame)
    return cancelled_orders(frame) / total * 100 if total else 0.0


def returned_units(frame: pd.DataFrame) -> float:
    """Unit retur pada baris yang tidak batal (Jumlah − QTY bersih)."""
    if frame is None or frame.empty:
        return 0.0
    active = frame.loc[~cancel_mask(frame)]
    if "returned_qty" in active.columns:
        return float(pd.to_numeric(active["returned_qty"], errors="coerce").fillna(0).clip(lower=0).sum())
    if {"gross_qty", "qty"} <= set(active.columns):
        return float((active["gross_qty"] - active["qty"]).clip(lower=0).sum())
    return 0.0


def net_lines(frame: pd.DataFrame) -> pd.DataFrame:
    """Baris yang dihitung sebagai penjualan bersih: tanpa batal, QTY & sales setelah retur.

    Bekerja untuk data bersih maupun kotor (toggle Exclude mati): nilai baris dihitung ulang
    dari Jumlah − Returned quantity bila kolomnya tersedia.
    """
    if frame is None or frame.empty:
        return frame
    if ORDER_LINES_GROSS not in frame.columns:
        frame = attach_order_line_totals(frame)
    work = frame.loc[~cancel_mask(frame)].copy()
    if {"gross_sales", "gross_qty", "returned_qty"} <= set(work.columns):
        gross_qty = pd.to_numeric(work["gross_qty"], errors="coerce").fillna(0)
        net_qty = (gross_qty - pd.to_numeric(work["returned_qty"], errors="coerce").fillna(0)).clip(lower=0)
        share = (net_qty / gross_qty.where(gross_qty > 0)).fillna(0)
        work["sales"] = pd.to_numeric(work["gross_sales"], errors="coerce").fillna(0) * share
        work["qty"] = net_qty
    if "qty" in work.columns:
        work = work.loc[pd.to_numeric(work["qty"], errors="coerce").fillna(0) > 0]
    return work


def net_sales(frame: pd.DataFrame) -> float:
    """Sales bersih: Total Pembayaran sekali per pesanan, tanpa batal, retur (termasuk sebagian) dikurangi."""
    if frame is None or frame.empty:
        return 0.0
    return float(order_revenue(net_lines(frame)))


def store_roas(ads_frames, stock_frame, orders: pd.DataFrame, start, end) -> tuple[float, float, float]:
    """(biaya iklan, omzet iklan, ROAS) untuk satu rentang tanggal, dipakai tab Data dan Laporan.

    Omzet iklan per SKU dibatasi sales bersih SKU itu pada rentang yang sama.
    """
    from src.core.ads import attribute_ads

    result = attribute_ads(ads_frames, stock_frame, orders=net_lines(orders), start=start, end=end)
    cost, sales = float(result.cost), float(result.sales)
    return cost, sales, (sales / cost if cost > 0 else float("nan"))


def removed_counts(frame: pd.DataFrame) -> tuple[int, float]:
    """(pesanan batal, unit retur) untuk kartu Exclude return & batal pada periode yang sama."""
    return cancelled_orders(frame), returned_units(frame)


def unpaid_chase_orders(frame: pd.DataFrame) -> int:
    """Pesanan batal karena belum bayar yang masih bisa dikejar lewat chat.

    Aturan sama dengan tabel "Pembeli batal karena belum bayar" di tab Data: pesanan tidak
    dihitung bila akun pembeli punya pesanan terbayar untuk SKU yang sama pada periode ini.
    """
    if frame is None or frame.empty or "cancel_reason" not in frame.columns:
        return 0
    work = frame.copy()
    work["_oid"] = _order_ids(work)
    reason = work["cancel_reason"].fillna("").astype(str).str.lower()
    cancelled = cancel_mask(work)
    work["_unpaid"] = cancelled & reason.apply(lambda text: any(hint in text for hint in UNPAID_HINTS))
    if not work["_unpaid"].any():
        return 0
    buyer = work["buyer"].fillna("").astype(str).str.casefold() if "buyer" in work.columns else pd.Series("", index=work.index)
    buyer = buyer.where(buyer.ne(""), "order:" + work["_oid"])
    item = work["item_key"].astype(str) if "item_key" in work.columns else work.get("sku", pd.Series("", index=work.index)).astype(str)
    keys = [buyer, item]
    paid_any = (~cancelled).groupby(keys).transform("any")
    chase = work.loc[work["_unpaid"] & ~paid_any, "_oid"]
    return int(chase.nunique())
