"""Laporan margin per item dari File margin (realisasi penjualan Shopee per periode).

Per item (sheet Margin Shopee periode terpilih):
  margin kotor Rp   = Gross Margin Value (file)
  potongan Shopee % = biaya admin kategori + program Shopee Mall + biaya proses pesanan (estimasi, dari harga jual)
  iklan %           = biaya iklan per unit ÷ harga (data iklan terakhir)
  margin bersih Rp  = margin kotor − penjualan termasuk pajak × (potongan Shopee % + iklan %)
Status: Rugi (margin bersih < 0) · Rendah (untung, di bawah rata-rata item yang untung) · Tinggi (≥ rata-rata itu) · Data tidak wajar.
Prioritas tindak lanjut: Rugi menurut kerugian Rp → Rendah menurut selisih Rp ke batas; Tinggi menurut margin Rp.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.core import margin_file as mf
from src.core import shopee_fee as fee

GAP_NASIONAL_PP = 5.0  # margin Shopee lebih rendah ≥ 5 poin dari nasional → harga/diskon Shopee perlu ditinjau


def _rp(x: float) -> str:
    return ("−" if x < 0 else "") + "Rp" + f"{abs(x):,.0f}".replace(",", ".")


def _pc(x: float) -> str:
    return f"{x:.1f}%".replace(".", ",")


def build(shopee: pd.DataFrame, nasional: pd.DataFrame | None = None, previous: pd.DataFrame | None = None, *,
          price: dict[str, float] | None = None, admin: dict[str, float] | None = None, names: dict[str, str] | None = None,
          ad_unit: dict[str, float] | None = None, programs: dict | None = None, order_fee: float = fee.DEFAULT_ORDER_FEE,
          big: set[str] | None = None) -> pd.DataFrame:
    """Satu baris per item terjual di sheet Shopee. Semua kunci dict memakai margin_file.sku_key."""
    columns = ["sku", "nama", "penjualan", "kotor_rp", "kotor_pct", "kotor_file_pct", "shopee_pct", "iklan_pct", "bersih_rp", "bersih_pct",
               "nasional_pct", "selisih_nasional", "kotor_lalu_pct", "status", "rugi_rp", "kurang_rp", "tindak_lanjut", "catatan"]
    if shopee is None or shopee.empty:
        return pd.DataFrame(columns=columns)
    programs = programs if programs is not None else fee.DEFAULT_PROGRAMS
    price, admin, names, ad_unit, big = price or {}, admin or {}, names or {}, ad_unit or {}, big or set()
    work = mf.with_pct(shopee)
    work = work.loc[work["sales_incl"] > 0].copy()
    nas = mf.with_pct(nasional).set_index("sku") if nasional is not None and not nasional.empty else pd.DataFrame()
    prev = mf.with_pct(previous).set_index("sku") if previous is not None and not previous.empty else pd.DataFrame()
    rows = []
    for r in work.itertuples(index=False):
        p = float(price.get(r.sku, 0) or 0)
        base = p if p > 0 else 100_000.0
        inp = fee.Inputs(harga=base, admin_pct=float(admin.get(r.sku, fee.DEFAULT_ADMIN_PCT)), programs=programs,
                         order_fee=order_fee if p > 0 else 0.0, ukuran_khusus=r.sku in big)
        shopee_pct = fee.shopee_fees(inp) / base * 100
        iklan_pct = float(ad_unit.get(r.sku, 0) or 0) / p * 100 if p > 0 else 0.0
        kotor_pct = float(r.margin_kotor_pct)
        bersih_rp = float(r.gm_value) - float(r.sales_incl) * (shopee_pct + iklan_pct) / 100
        nas_pct = float(nas.loc[r.sku, "margin_kotor_pct"]) if not nas.empty and r.sku in nas.index and bool(nas.loc[r.sku, "wajar"]) else np.nan
        lalu = float(prev.loc[r.sku, "margin_kotor_pct"]) if not prev.empty and r.sku in prev.index and bool(prev.loc[r.sku, "wajar"]) else np.nan
        rows.append({
            "sku": r.sku, "nama": names.get(r.sku) or r.nama, "penjualan": float(r.sales_incl), "kotor_rp": float(r.gm_value), "kotor_pct": kotor_pct,
            "kotor_file_pct": float(r.margin_file_pct), "shopee_pct": shopee_pct, "iklan_pct": iklan_pct, "bersih_rp": bersih_rp,
            "bersih_pct": bersih_rp / float(r.sales_incl) * 100, "nasional_pct": nas_pct, "selisih_nasional": kotor_pct - nas_pct if np.isfinite(nas_pct) else np.nan,
            "kotor_lalu_pct": lalu, "wajar": bool(r.wajar), "_inp": inp, "_price": p,
        })
    frame = pd.DataFrame(rows)
    valid = frame.loc[frame["wajar"]]
    overall = float(valid["bersih_rp"].sum() / valid["penjualan"].sum() * 100) if valid["penjualan"].sum() > 0 else float("nan")
    gain = valid.loc[valid["bersih_rp"] >= 0]
    # Batas "margin rendah" = rata-rata margin bersih item yang untung (tetap bermakna walau rata-rata toko minus).
    acuan = float(gain["bersih_rp"].sum() / gain["penjualan"].sum() * 100) if gain["penjualan"].sum() > 0 else float("nan")
    frame["status"] = [mf.classify(p, acuan) if ok else "Data tidak wajar" for p, ok in zip(frame["bersih_pct"], frame["wajar"])]
    frame["rugi_rp"] = (-frame["bersih_rp"]).clip(lower=0).where(frame["status"] == "Rugi", 0.0)
    frame["kurang_rp"] = (frame["penjualan"] * (acuan - frame["bersih_pct"]).clip(lower=0) / 100).where(frame["status"] == "Rendah", 0.0)
    frame["tindak_lanjut"] = [_action(row, acuan) for row in frame.to_dict("records")]
    frame["catatan"] = np.where(frame["wajar"], "", "Margin di file di luar −100%…95% (kemungkinan retur/penyesuaian); cek ke tim finance")
    order = {"Rugi": 0, "Rendah": 1, "Tinggi": 2, "Data tidak wajar": 3}
    frame["_o"] = frame["status"].map(order)
    frame["_v"] = np.select([frame["status"] == "Rugi", frame["status"] == "Rendah"], [frame["rugi_rp"], frame["kurang_rp"]], frame["bersih_rp"])
    frame = frame.sort_values(["_o", "_v", "penjualan"], ascending=[True, False, False]).reset_index(drop=True)
    out = frame[columns]
    out.attrs.update({"acuan_pct": acuan, "overall_pct": overall})
    return out


def _action(row: dict, acuan: float) -> str:
    status, inp, price = row["status"], row["_inp"], row["_price"]
    kotor, shopee, iklan = row["kotor_pct"], row["shopee_pct"], row["iklan_pct"]
    gap_nas = row["selisih_nasional"]
    if status == "Data tidak wajar":
        return "Cek data margin item ini ke tim finance sebelum diambil keputusan"
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
        target = 0.0 if status == "Rugi" else acuan
        steps += fee.fixes(trial, target)[:2]
    if status in ("Rugi", "Rendah") and np.isfinite(gap_nas) and gap_nas <= -GAP_NASIONAL_PP:
        steps.append(f"Margin kotor Shopee {_pc(-gap_nas)} poin di bawah nasional: tinjau harga/diskon di Shopee")
    if status == "Tinggi":
        steps.append("Pertahankan harga; dorong penjualan (iklan, flash sale, exposure)" if iklan < 5 else "Pertahankan; iklan masih sehat")
    return "; ".join(steps) if steps else "—"
