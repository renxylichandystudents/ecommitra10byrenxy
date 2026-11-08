"""Kalkulator margin Shopee Mall: biaya administrasi kategori, biaya program Shopee Mall, komisi affiliate, iklan.

Semua biaya persen dihitung dari harga jual akhir per unit (harga − diskon penjual − voucher penjual per unit),
dibatasi maksimum per kuantitas bila ada (mis. Biaya Pembayaran maks. Rp50.000/kuantitas).
  margin bersih = harga akhir − Σ biaya Shopee − komisi affiliate − iklan per unit − HPP − packing − ongkir penjual
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd

ASSET = Path(__file__).resolve().parents[2] / "assets" / "shopee_mall_fee.csv"
DEFAULT_ADMIN_PCT = 11.70

# Biaya program Shopee Mall yang diikuti (Seller Centre › Program Saya). Tarif dalam % harga akhir, maks Rp per kuantitas.
DEFAULT_PROGRAMS = {
    "pembayaran": {"label": "Biaya Pembayaran Shopee Mall", "pct": 1.80, "cap": 50_000.0, "on": True, "wajib": True},
    "pajak": {"label": "Pajak", "pct": 0.50, "cap": 0.0, "on": True, "wajib": True},
    "gratis_ongkir": {"label": "Gratis Ongkir XTRA (ukuran biasa)", "pct": 8.0, "cap": 40_000.0, "on": True, "wajib": False,
                      "pct_khusus": 9.5, "cap_khusus": 60_000.0, "rentang": "biasa 0,5–8% (maks Rp40.000) · khusus 2–9,5% (maks Rp60.000)"},
    "promo_xtra": {"label": "Promo XTRA", "pct": 4.50, "cap": 60_000.0, "on": True, "wajib": False},
    "live_xtra": {"label": "Shopee Live XTRA", "pct": 2.00, "cap": 20_000.0, "on": True, "wajib": False, "rentang": "2–3%; 2% karena ikut Promo XTRA"},
    "video_xtra": {"label": "Shopee Video XTRA", "pct": 2.00, "cap": 20_000.0, "on": True, "wajib": False, "rentang": "2–3%; 2% karena ikut Promo XTRA"},
    "spaylater": {"label": "SPayLater XTRA 0% (cicilan)", "pct": 2.50, "cap": 0.0, "on": False, "wajib": False, "rentang": "3 bulan 2,5% · 6 bulan 4%; hanya pesanan cicilan"},
    "asuransi": {"label": "Asuransi Pengiriman Shopee", "pct": 0.50, "cap": 0.0, "on": True, "wajib": False},
}
DEFAULT_ORDER_FEE = 1_250.0  # Biaya Proses Pesanan per pesanan selesai
DEFAULT_COST_LIMIT = 40.0    # batas total potongan (% harga akhir) sebelum dianggap menggerus margin


@dataclass
class Inputs:
    harga: float
    diskon: float = 0.0          # diskon penjual per unit (Rp)
    voucher: float = 0.0         # voucher penjual per unit (Rp)
    qty_per_order: float = 1.0
    admin_pct: float = DEFAULT_ADMIN_PCT
    programs: dict = field(default_factory=lambda: {k: dict(v) for k, v in DEFAULT_PROGRAMS.items()})
    order_fee: float = DEFAULT_ORDER_FEE
    affiliate_pct: float = 0.0
    affiliate_on: bool = False
    iklan: float = 0.0           # biaya iklan per unit (Rp)
    ukuran_khusus: bool = False  # Gratis Ongkir XTRA ukuran khusus (barang besar)
    hpp: float = 0.0             # tidak dipakai di layar (tim e-commerce tidak memegang HPP)
    packing: float = 0.0
    ongkir: float = 0.0

    @property
    def harga_akhir(self) -> float:
        return max(float(self.harga) - float(self.diskon) - float(self.voucher), 0.0)


def _rate(inp: "Inputs", key: str, prog: dict) -> tuple[float, float, str]:
    """(tarif %, maks Rp, label) program; Gratis Ongkir memakai tarif ukuran khusus bila barang besar."""
    if key == "gratis_ongkir" and inp.ukuran_khusus:
        return float(prog.get("pct_khusus", prog["pct"])), float(prog.get("cap_khusus", prog.get("cap") or 0)), "Gratis Ongkir XTRA (ukuran khusus)"
    return float(prog["pct"]), float(prog.get("cap") or 0), prog["label"]


def _capped(base: float, pct: float, cap: float) -> float:
    value = base * pct / 100.0
    return min(value, cap) if cap and cap > 0 else value


def breakdown(inp: Inputs) -> pd.DataFrame:
    """Rincian per unit: komponen, dasar, tarif, Rp (negatif = biaya), % dari harga akhir."""
    base = inp.harga_akhir
    rows = [("Harga jual", "harga data produk", "", float(inp.harga))]
    if inp.diskon:
        rows.append(("Diskon penjual", "per unit", "", -float(inp.diskon)))
    if inp.voucher:
        rows.append(("Voucher penjual", "per unit", "", -float(inp.voucher)))
    rows.append(("Harga jual akhir", "dasar biaya Shopee", "", base))
    rows.append(("Biaya administrasi kategori", "harga akhir", f"{inp.admin_pct:.2f}%".replace(".", ","), -_capped(base, inp.admin_pct, 0)))
    for key, prog in inp.programs.items():
        if not prog.get("on"):
            continue
        pct, cap, label = _rate(inp, key, prog)
        tarif = f"{pct:.2f}%".replace(".", ",") + (f" (maks Rp{cap:,.0f})".replace(",", ".") if cap else "")
        rows.append((label, "harga akhir", tarif, -_capped(base, pct, cap)))
    per_order = float(inp.order_fee) / max(float(inp.qty_per_order or 1), 1.0)
    rows.append(("Biaya Proses Pesanan", f"Rp{inp.order_fee:,.0f}/pesanan ÷ {inp.qty_per_order:g} unit".replace(",", "."), "", -per_order))
    if inp.affiliate_on and inp.affiliate_pct:
        rows.append(("Komisi affiliate", "harga akhir", f"{inp.affiliate_pct:.2f}%".replace(".", ","), -_capped(base, inp.affiliate_pct, 0)))
    rows.append(("Biaya iklan per unit", "data iklan", "", -float(inp.iklan)))
    if inp.hpp:
        rows.append(("HPP", "per unit", "", -float(inp.hpp)))
    if inp.packing:
        rows.append(("Packing", "per unit", "", -float(inp.packing)))
    if inp.ongkir:
        rows.append(("Ongkir ditanggung penjual", "per unit", "", -float(inp.ongkir)))
    frame = pd.DataFrame(rows, columns=["Komponen", "Dasar", "Tarif", "Rp per unit"])
    frame["% harga akhir"] = frame["Rp per unit"] / base * 100 if base > 0 else np.nan
    return frame


def shopee_fees(inp: Inputs) -> float:
    """Total potongan Shopee per unit (admin + program + proses pesanan), tanpa affiliate & iklan."""
    base = inp.harga_akhir
    total = _capped(base, inp.admin_pct, 0)
    for key, prog in inp.programs.items():
        if prog.get("on"):
            pct, cap, _label = _rate(inp, key, prog)
            total += _capped(base, pct, cap)
    return total + float(inp.order_fee) / max(float(inp.qty_per_order or 1), 1.0)


def margin(inp: Inputs) -> tuple[float, float]:
    """(margin bersih Rp per unit, % dari harga akhir)."""
    base = inp.harga_akhir
    affiliate = _capped(base, inp.affiliate_pct, 0) if inp.affiliate_on else 0.0
    value = base - shopee_fees(inp) - affiliate - inp.iklan - inp.hpp - inp.packing - inp.ongkir
    return value, (value / base * 100 if base > 0 else float("nan"))


def min_price(inp: Inputs, target_pct: float) -> float:
    """Harga jual (sebelum diskon/voucher) minimal agar margin ≥ target_pct dari harga akhir. NaN bila tak tercapai."""
    def ok(price: float) -> bool:
        value, pct = margin(replace(inp, harga=price))
        return value >= 0 if target_pct <= 0 else pct >= target_pct

    lo, hi = float(inp.diskon + inp.voucher), max(float(inp.harga), 1.0) * 2 + inp.hpp * 3 + 100_000
    if not ok(hi):
        hi *= 20
        if not ok(hi):
            return float("nan")
    for _ in range(60):
        mid = (lo + hi) / 2
        if ok(mid):
            hi = mid
        else:
            lo = mid
    return float(math.ceil(hi / 100.0) * 100)


def max_iklan(inp: Inputs, target_pct: float) -> float:
    """Biaya iklan per unit maksimal agar margin tetap ≥ target."""
    value, _pct = margin(replace(inp, iklan=0.0))
    return value - inp.harga_akhir * target_pct / 100.0


def max_affiliate_pct(inp: Inputs, target_pct: float) -> float:
    base = inp.harga_akhir
    if base <= 0:
        return float("nan")
    value, _ = margin(replace(inp, affiliate_on=False))
    return (value - base * target_pct / 100.0) / base * 100.0


# --------------------------------------------------------------------------- tabel kategori & komisi


def load_category_fees(saved: pd.DataFrame | None = None) -> pd.DataFrame:
    """Tabel biaya administrasi kategori Shopee Mall (versi unggahan bila ada, selain itu bawaan)."""
    frame = saved if saved is not None and not saved.empty else pd.read_csv(ASSET)
    frame = frame.copy()
    for column in ("kategori", "sub_kategori", "jenis_produk", "catatan"):
        frame[column] = frame[column].fillna("").astype(str).str.strip() if column in frame.columns else ""
    frame["biaya_admin_pct"] = pd.to_numeric(frame["biaya_admin_pct"].astype(str).str.replace(",", ".").str.rstrip("%"), errors="coerce")
    frame["label"] = frame["kategori"] + " › " + frame["sub_kategori"] + " › " + frame["jenis_produk"].str.slice(0, 60)
    return frame.reset_index(drop=True)


def parse_category_upload(raw: pd.DataFrame) -> pd.DataFrame:
    work = raw.copy()
    work.columns = [str(c).strip().lower().replace(" ", "_") for c in work.columns]
    alias = {"biaya_administrasi": "biaya_admin_pct", "biaya_admin": "biaya_admin_pct", "tarif": "biaya_admin_pct", "biaya_administrasi_shopee_mall": "biaya_admin_pct"}
    work = work.rename(columns={k: v for k, v in alias.items() if k in work.columns})
    missing = [c for c in ("kategori", "sub_kategori", "jenis_produk", "biaya_admin_pct") if c not in work.columns]
    if missing:
        raise ValueError("Kolom hilang: " + ", ".join(missing))
    if "catatan" not in work.columns:
        work["catatan"] = ""
    return load_category_fees(work[["kategori", "sub_kategori", "jenis_produk", "biaya_admin_pct", "catatan"]].dropna(subset=["jenis_produk"]))


def _tokens(text: str) -> set[str]:
    stop = {"dan", "&", "lainnya", "untuk", "set", "dengan", "-", "x", "cm", "mm", "pcs", "warna", "putih", "hitam"}
    return {w for w in re.findall(r"[a-z]{3,}", str(text).lower()) if w not in stop}


def suggest_category(name: str, fees: pd.DataFrame) -> int | None:
    """Usulan baris kategori dari kemiripan kata nama produk dengan daftar jenis produk."""
    words = _tokens(name)
    if not words or fees.empty:
        return None
    # Kata di depan nama produk biasanya jenis barangnya (mis. "Cat Tembok …", "Kran Air …") → bobot lebih besar.
    head = _tokens(" ".join(re.findall(r"[A-Za-z]+", str(name))[:3]))
    first = _tokens(" ".join(re.findall(r"[A-Za-z]+", str(name))[:1]))
    best, best_score = None, 0.0
    for index, row in fees.iterrows():
        for item in str(row["jenis_produk"]).split(","):
            item_words = _tokens(item)
            if not item_words:
                continue
            hit = len(words & item_words)
            score = hit / len(item_words) + hit * 0.1 + len(head & item_words) * 0.5 + len(first & item_words) * 0.6
            if hit and score > best_score:
                best, best_score = index, score
    return best


def parse_affiliate(raw: pd.DataFrame) -> pd.DataFrame:
    """File komisi affiliate Shopee (Produk ID, Nama Produk, Persentase Komisi) → product_code, nama, komisi_pct."""
    header = None
    for index in range(min(len(raw), 10)):
        values = [str(v).strip() for v in raw.iloc[index].tolist()]
        if "Produk ID" in values and "Persentase Komisi" in values:
            header = index
            break
    if header is None:
        raise ValueError("Kolom 'Produk ID' dan 'Persentase Komisi' tidak ditemukan.")
    table = raw.iloc[header + 1 :].copy()
    table.columns = [str(v).strip() for v in raw.iloc[header].tolist()]
    table = table.loc[table["Produk ID"].astype(str).str.fullmatch(r"\d{5,}")]
    out = pd.DataFrame({
        "product_code": table["Produk ID"].astype(str).str.strip(),
        "nama": table.get("Nama Produk", "").astype(str),
        "komisi_pct": pd.to_numeric(table["Persentase Komisi"].astype(str).str.replace(",", ".").str.rstrip("%"), errors="coerce"),
    }).dropna(subset=["komisi_pct"])
    return out.drop_duplicates("product_code", keep="last").reset_index(drop=True)


# --------------------------------------------------------------------------- analisa


def program_cost(inp: Inputs, key: str) -> float:
    prog = inp.programs[key]
    if not prog.get("on"):
        return 0.0
    pct, cap, _ = _rate(inp, key, prog)
    return _capped(inp.harga_akhir, pct, cap)


def cost_pct(inp: Inputs) -> float:
    """Total potongan (Shopee + affiliate + iklan) dalam % harga akhir."""
    _value, pct = margin(inp)
    return 100.0 - pct if np.isfinite(pct) else float("nan")


def max_iklan_limit(inp: Inputs, limit_pct: float) -> float:
    """Biaya iklan per unit maksimal agar total potongan ≤ batas."""
    base = inp.harga_akhir
    without = cost_pct(replace(inp, iklan=0.0))
    return (limit_pct - without) / 100.0 * base


def max_affiliate_limit(inp: Inputs, limit_pct: float) -> float:
    without = cost_pct(replace(inp, affiliate_on=False))
    return limit_pct - without


def fixes(inp: Inputs, limit_pct: float, roas: float | None = None) -> list[str]:
    """Langkah perbaikan berurutan dari tuas terbesar yang bisa dikendalikan tim e-commerce."""
    out: list[str] = []
    base = inp.harga_akhir
    over = cost_pct(inp) - limit_pct
    if over <= 0 or base <= 0:
        return out

    def rp(x: float) -> str:
        return "Rp" + f"{max(x, 0):,.0f}".replace(",", ".")

    cap_ads = max_iklan_limit(inp, limit_pct)
    shopee_only = shopee_fees(inp) / base * 100
    if shopee_only > limit_pct:
        out.append(f"Potongan Shopee saja {shopee_only:.1f}% — tinjau program opsional atau kategori/ukuran Gratis Ongkir".replace(".", ","))
    if inp.iklan > 0:
        if cap_ads > 0:
            text = f"Turunkan biaya iklan ke ≤ {rp(cap_ads)}/unit (ROAS ≥ " + f"{base / cap_ads:.1f}".replace(".", ",") + ")"
            if roas:
                text += " — ROAS sekarang " + f"{roas:.1f}".replace(".", ",")
            out.append(text)
        else:
            out.append("Hentikan/turunkan iklan: tanpa iklan pun potongan sudah di atas batas")
    if inp.affiliate_on and inp.affiliate_pct > 0:
        cap_aff = max_affiliate_limit(inp, limit_pct)
        out.append(f"Turunkan komisi affiliate ke ≤ {max(cap_aff, 0):.1f}%".replace(".", ","))
    optional = sorted(
        [(program_cost(inp, k), k) for k, v in inp.programs.items() if v.get("on") and not v.get("wajib")], reverse=True,
    )
    for cost, key in optional[:2]:
        if cost > 0:
            out.append(f"Tinjau {inp.programs[key]['label'] if key != 'gratis_ongkir' else _rate(inp, key, inp.programs[key])[2]} (memotong {rp(cost)}/unit)")
    if inp.diskon or inp.voucher:
        out.append(f"Kurangi diskon/voucher penjual ({rp(inp.diskon + inp.voucher)}/unit)")
    return out


def analysis(inp: Inputs, *, limit_pct: float, qty_30: float | None = None, pred_qty_30: float | None = None, roas: float | None = None) -> list[tuple[str, str]]:
    """Daftar (tingkat, kalimat) untuk kotak analisa: 'ok' / 'warn' / 'bad' / 'info'. Tanpa HPP: dinilai dari total potongan."""
    notes: list[tuple[str, str]] = []
    value, pct = margin(inp)
    base = inp.harga_akhir
    total = 100.0 - pct if np.isfinite(pct) else float("nan")

    def rp(x: float) -> str:
        return ("−" if x < 0 else "") + "Rp" + f"{abs(x):,.0f}".replace(",", ".")

    def pc(x: float) -> str:
        return f"{x:.1f}%".replace(".", ",")

    if total > limit_pct:
        notes.append(("bad", f"Total potongan {pc(total)} di atas batas {pc(limit_pct)}: penerimaan bersih {rp(value)}/unit, margin kemungkinan habis."))
    elif total > limit_pct - 5:
        notes.append(("warn", f"Total potongan {pc(total)} mendekati batas {pc(limit_pct)}. Penerimaan bersih {rp(value)}/unit."))
    else:
        notes.append(("ok", f"Total potongan {pc(total)} masih di bawah batas {pc(limit_pct)}. Penerimaan bersih {rp(value)}/unit."))
    frame = breakdown(inp)
    costs = frame.loc[(frame["Rp per unit"] < 0) & ~frame["Komponen"].isin(["Diskon penjual", "Voucher penjual"])]
    if not costs.empty:
        top = costs.sort_values("Rp per unit").head(3)
        notes.append(("info", "Potongan terbesar: " + ", ".join(f"{r.Komponen} {rp(-r._4)} ({pc(-r._5)})" for r in top.itertuples())))
    fees = shopee_fees(inp)
    notes.append(("info", f"Potongan Shopee saja {rp(fees)}/unit = {pc(fees / base * 100 if base else 0)} dari harga akhir."))
    cap_ads = max_iklan_limit(inp, limit_pct)
    if cap_ads > 0:
        text = f"Iklan maksimal {rp(cap_ads)}/unit agar potongan ≤ {pc(limit_pct)} → ROAS minimal " + f"{base / cap_ads:.1f}".replace(".", ",")
        if roas and np.isfinite(roas):
            text += "; ROAS sekarang " + f"{roas:.1f}".replace(".", ",") + (" ✓" if roas >= base / cap_ads else " — iklan memakan margin")
        notes.append(("info" if inp.iklan <= cap_ads else "warn", text))
    for step in fixes(inp, limit_pct, roas):
        notes.append(("warn", "Perbaiki: " + step))
    if qty_30:
        notes.append(("info", "30 hari terakhir: " + f"{qty_30:,.0f}".replace(",", ".") + f" unit → penerimaan bersih ±{rp(value * qty_30)}."))
    if pred_qty_30:
        notes.append(("info", "Prediksi 30 hari: " + f"{pred_qty_30:,.0f}".replace(",", ".") + f" unit → penerimaan bersih ±{rp(value * pred_qty_30)}."))
    return notes


def portfolio(rows: pd.DataFrame, *, programs: dict, order_fee: float, limit_pct: float, affiliate_on: bool = False) -> pd.DataFrame:
    """Hitung potongan per SKU. rows: sku, nama, harga, diskon_unit, voucher_unit, admin_pct, affiliate_pct, iklan_unit, roas,
    qty_30, omzet_30, ukuran_khusus. Prioritas = kebocoran Rp 30 hari di atas batas (omzet × kelebihan %)."""
    out = []
    for r in rows.itertuples(index=False):
        inp = Inputs(
            harga=float(r.harga), diskon=float(r.diskon_unit), voucher=float(r.voucher_unit), admin_pct=float(r.admin_pct),
            programs=programs, order_fee=order_fee, affiliate_pct=float(r.affiliate_pct or 0), affiliate_on=affiliate_on and bool(r.affiliate_pct),
            iklan=float(r.iklan_unit or 0), ukuran_khusus=bool(r.ukuran_khusus),
        )
        value, pct = margin(inp)
        total = 100.0 - pct if np.isfinite(pct) else np.nan
        shopee = shopee_fees(inp)
        base = inp.harga_akhir
        over = max(total - limit_pct, 0.0) if np.isfinite(total) else 0.0
        omzet = float(r.omzet_30 or 0)
        status = "Melebihi batas" if over > 0 else ("Mendekati batas" if np.isfinite(total) and total > limit_pct - 5 else "Aman")
        steps = fixes(inp, limit_pct, r.roas if r.roas == r.roas else None)
        out.append({
            "sku": r.sku, "nama": r.nama, "kategori": r.kategori, "harga_akhir": base, "qty_30": float(r.qty_30 or 0), "omzet_30": omzet,
            "shopee_pct": shopee / base * 100 if base else np.nan, "iklan_unit": float(r.iklan_unit or 0), "roas": r.roas,
            "affiliate_pct": float(r.affiliate_pct or 0), "total_pct": total, "bersih_unit": value, "bersih_30": value * float(r.qty_30 or 0),
            "bocor_30": omzet * over / 100.0, "status": status, "perbaikan": "; ".join(steps) if steps else "—",
        })
    frame = pd.DataFrame(out)
    if frame.empty:
        return frame
    order = {"Melebihi batas": 0, "Mendekati batas": 1, "Aman": 2}
    frame["_o"] = frame["status"].map(order)
    return frame.sort_values(["_o", "bocor_30", "omzet_30"], ascending=[True, False, False]).drop(columns="_o").reset_index(drop=True)
