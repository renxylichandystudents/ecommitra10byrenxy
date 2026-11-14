"""Laporan margin per item untuk periode kalender bebas.

File margin berisi total setahun (tanpa tanggal), jadi dipakai sebagai TARIF margin per SKU; volume per periode diambil dari
data transaksi Shopee pada rentang tanggal yang dipilih:
  penjualan         = Σ sales transaksi (tidak batal) pada periode, termasuk pajak
  penjualan akhir   = penjualan − voucher ditanggung penjual (sama dengan harga akhir Kalkulator biaya)
  margin kotor Rp   = penjualan akhir × margin kotor % (File margin: Gross Margin ÷ Sales Include Tax; Shopee → Nasional)
  potongan Shopee % = admin kategori + program Shopee Mall + proses pesanan, dari harga akhir rata-rata
  iklan %           = biaya iklan per unit ÷ harga akhir rata-rata
  margin bersih Rp  = margin kotor − penjualan akhir × (potongan Shopee % + iklan %); persen dari penjualan akhir
Status: Rugi (< 0) · Rendah (untung, di bawah rata-rata item yang untung) · Tinggi · Data tidak wajar · Tanpa data margin.
SKU nonaktif (tidak ada di unggahan stok terakhir) dipisah: tidak ikut analisa, tetapi dampaknya per bulan tetap dihitung.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.core import margin_file as mf
from src.core import shopee_fee as fee

GAP_NASIONAL_PP = 5.0  # margin Shopee lebih rendah ≥ 5 poin dari nasional → harga/diskon Shopee perlu ditinjau
COLUMNS = ["sku", "nama", "penjualan", "penjualan_akhir", "qty", "harga", "kotor_rp", "kotor_pct", "kotor_file_pct", "sumber", "shopee_pct", "iklan_pct",
           "bersih_rp", "bersih_pct", "nasional_pct", "selisih_nasional", "status", "rugi_rp", "kurang_rp", "tindak_lanjut", "catatan"]


def _pc(x: float) -> str:
    return f"{x:.1f}%".replace(".", ",")


def sales_by_sku(orders: pd.DataFrame | None, start=None, end=None) -> pd.DataFrame:
    """sku (kunci tanpa nol depan), nama, penjualan, voucher (ditanggung penjual), qty, pertama, terakhir, bulan dari transaksi tidak batal."""
    cols = ["sku", "nama", "penjualan", "voucher", "qty", "pertama", "terakhir", "bulan"]
    if orders is None or orders.empty:
        return pd.DataFrame(columns=cols)
    work = orders
    if "status" in work.columns:
        from src.ingest import cancelled_status_mask

        work = work.loc[~cancelled_status_mask(work["status"])]
    stamp = pd.to_datetime(work["order_time"], errors="coerce")
    if start is not None:
        keep = stamp.dt.normalize().between(pd.Timestamp(start), pd.Timestamp(end))
        work, stamp = work.loc[keep], stamp.loc[keep]
    if work.empty:
        return pd.DataFrame(columns=cols)
    frame = pd.DataFrame({
        "sku": work["sku"].astype(str).map(mf.sku_key), "nama": work.get("product_name", pd.Series("", index=work.index)).fillna("").astype(str),
        "penjualan": pd.to_numeric(work["sales"], errors="coerce").fillna(0.0), "qty": pd.to_numeric(work["qty"], errors="coerce").fillna(0.0), "t": stamp,
        "voucher": pd.to_numeric(work["seller_voucher"], errors="coerce").fillna(0.0) if "seller_voucher" in work.columns else 0.0,
    })
    out = frame.groupby("sku").agg(nama=("nama", "last"), penjualan=("penjualan", "sum"), voucher=("voucher", "sum"), qty=("qty", "sum"),
                                   pertama=("t", "min"), terakhir=("t", "max")).reset_index()
    first, last = out["pertama"].dt.to_period("M"), out["terakhir"].dt.to_period("M")
    out["bulan"] = [(b - a).n + 1 if pd.notna(a) and pd.notna(b) else 1 for a, b in zip(first, last)]
    return out.loc[out["penjualan"] > 0, cols].reset_index(drop=True)


def build(sales: pd.DataFrame, lookup: pd.DataFrame, *, admin: dict[str, float] | None = None, ad_unit: dict[str, float] | None = None,
          programs: dict | None = None, order_fee: float = fee.DEFAULT_ORDER_FEE, big: set[str] | None = None,
          acuan_pct: float | None = None, cost: dict[str, float] | None = None, cost_label: str = "Harga beli") -> pd.DataFrame:
    """Satu baris per SKU terjual. sales: sku, nama, penjualan, qty. lookup: margin_file.lookup(...).

    cost (sku → harga beli belum PPN, file merchandising): bila ada, margin kotor = (harga akhir × (1 − PPN) − harga beli) ÷ harga akhir;
    selain itu dari File margin."""
    if sales is None or sales.empty:
        out = pd.DataFrame(columns=COLUMNS)
        out.attrs.update({"acuan_pct": float("nan"), "overall_pct": float("nan")})
        return out
    programs = programs if programs is not None else fee.DEFAULT_PROGRAMS
    admin, ad_unit, big = admin or {}, ad_unit or {}, big or set()
    look = lookup.set_index("sku") if lookup is not None and not lookup.empty else pd.DataFrame()
    rows = []
    for r in sales.itertuples(index=False):
        voucher = min(max(float(getattr(r, "voucher", 0.0) or 0.0), 0.0), float(r.penjualan))
        net_rp = float(r.penjualan) - voucher
        price = net_rp / float(r.qty) if r.qty else 0.0
        base = price if price > 0 else 100_000.0
        inp = fee.Inputs(harga=base, admin_pct=float(admin.get(r.sku, fee.DEFAULT_ADMIN_PCT)), programs=programs,
                         order_fee=order_fee if price > 0 else 0.0, ukuran_khusus=r.sku in big)
        shopee_pct = fee.shopee_fees(inp) / base * 100
        iklan_pct = float(ad_unit.get(r.sku, 0) or 0) / price * 100 if price > 0 else 0.0
        hit = look.loc[r.sku] if not look.empty and r.sku in look.index else None
        kotor = float(hit["margin_kotor_pct"]) if hit is not None else np.nan
        source = hit["sumber"] if hit is not None else ""
        unit_cost = (cost or {}).get(r.sku)
        if unit_cost and price > 0:
            kotor, source = (price * (1 - mf.DEFAULT_TAX_SHARE) - unit_cost) / price * 100, cost_label
        sales_rp = float(r.penjualan)
        kotor_rp = net_rp * kotor / 100 if np.isfinite(kotor) else np.nan
        bersih_rp = kotor_rp - net_rp * (shopee_pct + iklan_pct) / 100 if np.isfinite(kotor) else np.nan
        nas = float(hit["margin_nasional_pct"]) if hit is not None and pd.notna(hit["margin_nasional_pct"]) else np.nan
        rows.append({
            "sku": r.sku, "nama": r.nama, "penjualan": sales_rp, "penjualan_akhir": net_rp, "qty": float(r.qty), "harga": price,
            "kotor_rp": kotor_rp, "kotor_pct": kotor,
            "kotor_file_pct": float(hit["margin_file_pct"]) if hit is not None and pd.notna(hit["margin_file_pct"]) else np.nan,
            "sumber": source, "shopee_pct": shopee_pct, "iklan_pct": iklan_pct, "bersih_rp": bersih_rp,
            "bersih_pct": bersih_rp / net_rp * 100 if np.isfinite(bersih_rp) and net_rp else np.nan,
            "nasional_pct": nas, "selisih_nasional": kotor - nas if np.isfinite(kotor) and np.isfinite(nas) else np.nan,
            "_odd": hit is not None and not np.isfinite(kotor) and not unit_cost, "_inp": inp,
        })
    frame = pd.DataFrame(rows)
    valid = frame.loc[frame["bersih_rp"].notna()]
    overall = float(valid["bersih_rp"].sum() / valid["penjualan_akhir"].sum() * 100) if valid["penjualan_akhir"].sum() > 0 else float("nan")
    if acuan_pct is None:
        # Batas "margin rendah" = rata-rata margin bersih item yang untung (tetap bermakna walau rata-rata toko minus).
        gain = valid.loc[valid["bersih_rp"] >= 0]
        acuan_pct = float(gain["bersih_rp"].sum() / gain["penjualan_akhir"].sum() * 100) if gain["penjualan_akhir"].sum() > 0 else float("nan")
    acuan = acuan_pct
    frame["status"] = [("Data tidak wajar" if odd else "Tanpa data margin") if not np.isfinite(p) else mf.classify(p, acuan)
                       for p, odd in zip(frame["bersih_pct"], frame["_odd"])]
    frame["rugi_rp"] = (-frame["bersih_rp"]).clip(lower=0).where(frame["status"] == "Rugi", 0.0).fillna(0.0)
    frame["kurang_rp"] = (frame["penjualan_akhir"] * (acuan - frame["bersih_pct"]).clip(lower=0) / 100).where(frame["status"] == "Rendah", 0.0).fillna(0.0)
    frame["tindak_lanjut"] = [_action(row, acuan) for row in frame.to_dict("records")]
    frame["catatan"] = np.select(
        [frame["status"] == "Data tidak wajar", frame["status"] == "Tanpa data margin", frame["sumber"] == "Nasional",
         frame["sumber"].astype(str).str.startswith("Harga beli")],
        ["Margin di file di luar −100%…95% (kemungkinan retur/penyesuaian); cek ke tim finance", "SKU tidak ada di harga beli maupun File margin",
         "Tidak ada di sheet Shopee, memakai margin nasional", "Memakai harga beli (file merchandising), PPN dari harga jual"], "")
    order = {"Rugi": 0, "Rendah": 1, "Tinggi": 2, "Data tidak wajar": 3, "Tanpa data margin": 4}
    frame["_o"] = frame["status"].map(order)
    frame["_v"] = np.select([frame["status"] == "Rugi", frame["status"] == "Rendah", frame["status"] == "Tinggi"],
                            [frame["rugi_rp"], frame["kurang_rp"], frame["bersih_rp"]], frame["penjualan"])
    frame = frame.sort_values(["_o", "_v", "penjualan"], ascending=[True, False, False]).reset_index(drop=True)
    out = frame[COLUMNS].copy()
    out.attrs.update({"acuan_pct": acuan, "overall_pct": overall})
    return out


def _action(row: dict, acuan: float) -> str:
    status, inp, price = row["status"], row["_inp"], row["harga"]
    kotor, shopee, iklan = row["kotor_pct"], row["shopee_pct"], row["iklan_pct"]
    gap_nas = row["selisih_nasional"]
    if status == "Data tidak wajar":
        return "Cek data margin item ini ke tim finance sebelum diambil keputusan"
    if status == "Tanpa data margin":
        return "Margin belum ada di File margin"
    steps: list[str] = []
    if status == "Rugi":
        if kotor < 0:
            steps.append(f"Harga jual di bawah modal (margin kotor {_pc(kotor)}): naikkan harga atau hentikan diskon/promo")
        else:
            steps.append(f"Potongan Shopee {_pc(shopee)} + iklan {_pc(iklan)} melebihi margin kotor {_pc(kotor)}")
    elif status == "Rendah":
        steps.append(f"Untung tipis: margin bersih {_pc(row['bersih_pct'])} di bawah batas {_pc(acuan)}")
    if status in ("Rugi", "Rendah") and price > 0 and kotor >= 0:
        tax = mf.DEFAULT_TAX_SHARE
        trial = fee.Inputs(harga=price, admin_pct=inp.admin_pct, programs=inp.programs, order_fee=inp.order_fee, ukuran_khusus=inp.ukuran_khusus,
                           iklan=iklan / 100 * price, pajak_share=tax, hpp=max(price * (1 - tax - kotor / 100), 0.0))
        steps += fee.fixes(trial, 0.0 if status == "Rugi" else acuan)[:2]
    if status in ("Rugi", "Rendah") and np.isfinite(gap_nas) and gap_nas <= -GAP_NASIONAL_PP:
        steps.append(f"Margin kotor Shopee {_pc(-gap_nas)} poin di bawah nasional: tinjau harga/diskon di Shopee")
    if status == "Tinggi":
        steps.append("Pertahankan harga; dorong penjualan (iklan, flash sale, exposure)" if iklan < 5 else "Pertahankan; iklan masih sehat")
    return "; ".join(steps) if steps else "—"


def inactive_impact(history: pd.DataFrame, lookup: pd.DataFrame, *, acuan_pct: float, **kwargs) -> pd.DataFrame:
    """SKU nonaktif: margin bersih rata-rata per bulan selama masih terjual (riwayat transaksi).

    dampak_bulan > 0 → potensi margin yang hilang karena dinonaktifkan; < 0 → kerugian yang berhenti."""
    cols = COLUMNS + ["pertama", "terakhir", "bulan", "penjualan_bulan", "dampak_bulan"]
    if history is None or history.empty:
        return pd.DataFrame(columns=cols)
    report = build(history, lookup, acuan_pct=acuan_pct, **kwargs)
    extra = history.set_index("sku")[["pertama", "terakhir", "bulan"]]
    report = report.join(extra, on="sku")
    report["penjualan_bulan"] = report["penjualan"] / report["bulan"].clip(lower=1)
    report["dampak_bulan"] = report["bersih_rp"] / report["bulan"].clip(lower=1)
    report = report.sort_values("dampak_bulan", ascending=False, na_position="last").reset_index(drop=True)
    return report[cols]
