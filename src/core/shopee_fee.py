"""Kalkulator margin Shopee Mall: biaya administrasi kategori, biaya program Shopee Mall, komisi affiliate, iklan.

Semua biaya persen dihitung dari harga jual akhir per unit (harga − diskon penjual − voucher penjual per unit),
dibatasi maksimum per kuantitas bila ada (mis. Biaya Pembayaran maks. Rp50.000/kuantitas).
  margin bersih = harga akhir − pajak dalam harga − modal (estimasi file margin) − Σ biaya Shopee − komisi affiliate − iklan per unit
Modal per unit tidak diinput tim: diturunkan dari file margin (lihat src/core/margin_file.py) dan tetap dalam Rupiah saat harga disimulasikan.
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
    hpp: float = 0.0             # modal per unit (estimasi dari file margin), bukan input tim
    pajak_share: float = 0.0     # porsi pajak di dalam harga jual (1 − exclude ÷ include)
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
    """Rincian per unit: komponen, dasar, tarif, Rp (negatif = biaya), % dari harga akhir. Diakhiri baris Margin bersih."""
    base = inp.harga_akhir
    rows = [("Harga jual", "harga data produk", "", float(inp.harga))]
    if inp.diskon:
        rows.append(("Diskon penjual", "per unit", "", -float(inp.diskon)))
    if inp.voucher:
        rows.append(("Voucher penjual", "per unit", "", -float(inp.voucher)))
    rows.append(("Harga jual akhir", "dasar biaya Shopee", "", base))
    if inp.pajak_share or inp.hpp:
        tax = base * float(inp.pajak_share)
        rows.append(("Pajak dalam harga (PPN)", "harga akhir", f"{inp.pajak_share * 100:.2f}%".replace(".", ","), -tax))
        rows.append(("Modal barang (estimasi file margin)", "tetap per unit", "", -float(inp.hpp)))
        rows.append(("Margin kotor", "sebelum potongan Shopee", "", base - tax - float(inp.hpp)))
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
    if inp.packing:
        rows.append(("Packing", "per unit", "", -float(inp.packing)))
    if inp.ongkir:
        rows.append(("Ongkir ditanggung penjual", "per unit", "", -float(inp.ongkir)))
    value, _pct = margin(inp)
    rows.append(("Margin bersih" if (inp.pajak_share or inp.hpp) else "Penerimaan bersih", "setelah semua potongan", "", value))
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
    value = base - base * float(inp.pajak_share) - shopee_fees(inp) - affiliate - inp.iklan - inp.hpp - inp.packing - inp.ongkir
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


def potongan(inp: Inputs) -> float:
    """Potongan Shopee + komisi affiliate + iklan per unit (tanpa pajak & modal)."""
    affiliate = _capped(inp.harga_akhir, inp.affiliate_pct, 0) if inp.affiliate_on else 0.0
    return shopee_fees(inp) + affiliate + float(inp.iklan)


def kotor_pct(inp: Inputs) -> float:
    """Margin kotor % harga akhir (sebelum potongan Shopee)."""
    base = inp.harga_akhir
    return (base - base * inp.pajak_share - inp.hpp) / base * 100 if base > 0 else float("nan")


def cost_pct(inp: Inputs) -> float:
    """Total potongan (Shopee + affiliate + iklan) dalam % harga akhir."""
    base = inp.harga_akhir
    return potongan(inp) / base * 100 if base > 0 else float("nan")


def _rp(x: float) -> str:
    return ("−" if x < 0 else "") + "Rp" + f"{abs(x):,.0f}".replace(",", ".")


def _pc(x: float) -> str:
    return f"{x:.1f}%".replace(".", ",")


def fixes(inp: Inputs, target_pct: float, roas: float | None = None) -> list[str]:
    """Langkah agar margin bersih ≥ target, dari tuas terbesar yang bisa dikendalikan tim e-commerce."""
    out: list[str] = []
    base = inp.harga_akhir
    _value, pct = margin(inp)
    if base <= 0 or not np.isfinite(pct) or pct >= target_pct:
        return out
    goal = "impas" if target_pct <= 0 else f"margin {_pc(target_pct)}"
    if inp.iklan > 0:
        cap = max_iklan(inp, target_pct)
        if cap > 0:
            text = f"Turunkan iklan ke ≤ {_rp(cap)}/unit (ROAS ≥ " + f"{base / cap:.1f}".replace(".", ",") + ")"
            if roas and np.isfinite(roas):
                text += " — ROAS sekarang " + f"{roas:.1f}".replace(".", ",")
            out.append(text)
        else:
            out.append(f"Hentikan iklan: tanpa iklan pun belum {goal}")
    if inp.affiliate_on and inp.affiliate_pct > 0:
        cap_aff = max_affiliate_pct(inp, target_pct)
        out.append(f"Turunkan komisi affiliate ke ≤ {_pc(max(cap_aff, 0))}")
    optional = sorted([(program_cost(inp, k), k) for k, v in inp.programs.items() if v.get("on") and not v.get("wajib")], reverse=True)
    for cost, key in optional[:2]:
        if cost > 0:
            out.append(f"Tinjau {_rate(inp, key, inp.programs[key])[2]} (memotong {_rp(cost)}/unit)")
    if inp.diskon or inp.voucher:
        out.append(f"Kurangi diskon/voucher penjual ({_rp(inp.diskon + inp.voucher)}/unit)")
    floor = min_price(replace(inp, iklan=0.0), target_pct)
    if np.isfinite(floor) and floor > inp.harga:
        out.append(f"Atau naikkan harga ke ≥ {_rp(floor)} ({goal} tanpa iklan)")
    return out


def analysis(inp: Inputs, *, target_pct: float, qty_30: float | None = None, pred_qty_30: float | None = None,
             roas: float | None = None, sumber: str = "") -> list[tuple[str, str]]:
    """Daftar (tingkat, kalimat) untuk kotak analisa: 'ok' / 'warn' / 'bad' / 'info'. target = batas margin rendah (rata-rata margin bersih SKU yang untung)."""
    notes: list[tuple[str, str]] = []
    value, pct = margin(inp)
    base = inp.harga_akhir
    if base <= 0:
        return [("bad", "Harga jual akhir 0: isi harga jual.")]
    kotor = kotor_pct(inp)
    shopee = shopee_fees(inp) / base * 100
    aff = (_capped(base, inp.affiliate_pct, 0) / base * 100) if inp.affiliate_on else 0.0
    ads = float(inp.iklan) / base * 100
    if pct < 0:
        notes.append(("bad", f"Rugi {_rp(-value)}/unit (margin bersih {_pc(pct)}): potongan {_pc(shopee + aff + ads)} lebih besar dari margin kotor {_pc(kotor)}."))
    elif pct < target_pct:
        notes.append(("warn", f"Margin bersih {_pc(pct)} ({_rp(value)}/unit) di bawah batas margin rendah {_pc(target_pct)}."))
    else:
        notes.append(("ok", f"Margin bersih {_pc(pct)} ({_rp(value)}/unit), di atas batas margin rendah {_pc(target_pct)}."))
    text = f"Margin kotor {_pc(kotor)}" + (f" (file margin, sumber {sumber})" if sumber else "") + f" − potongan Shopee {_pc(shopee)}"
    if aff:
        text += f" − affiliate {_pc(aff)}"
    notes.append(("info", text + f" − iklan {_pc(ads)} = margin bersih {_pc(pct)}."))
    frame = breakdown(inp)
    skip = ["Diskon penjual", "Voucher penjual", "Pajak dalam harga (PPN)", "Modal barang (estimasi file margin)", "Margin kotor", "Margin bersih", "Penerimaan bersih"]
    costs = frame.loc[(frame["Rp per unit"] < 0) & ~frame["Komponen"].isin(skip)]
    if not costs.empty:
        top = costs.sort_values("Rp per unit").head(3)
        notes.append(("info", "Potongan terbesar: " + ", ".join(f"{r.Komponen} {_rp(-r._4)} ({_pc(-r._5)})" for r in top.itertuples())))
    for goal, label in ((0.0, "impas"), (target_pct, f"margin {_pc(target_pct)}")):
        cap = max_iklan(inp, goal)
        if cap > 0:
            line = f"Iklan maksimal {_rp(cap)}/unit agar {label} → ROAS minimal " + f"{base / cap:.1f}".replace(".", ",")
            if roas and np.isfinite(roas):
                line += "; ROAS sekarang " + f"{roas:.1f}".replace(".", ",") + (" ✓" if roas >= base / cap else " ✗")
            notes.append(("info" if inp.iklan <= cap else "warn", line))
        else:
            notes.append(("warn", f"Tanpa iklan pun belum {label}: iklan untuk SKU ini menambah rugi."))
            break
    for step in fixes(inp, max(target_pct, 0.0) if pct >= 0 else 0.0, roas):
        notes.append(("warn", "Perbaiki: " + step))
    if qty_30:
        notes.append(("info", "Periode terpilih: " + f"{qty_30:,.0f}".replace(",", ".") + f" unit → margin bersih ±{_rp(value * qty_30)}."))
    if pred_qty_30:
        notes.append(("info", "Prediksi 30 hari: " + f"{pred_qty_30:,.0f}".replace(",", ".") + f" unit → margin bersih ±{_rp(value * pred_qty_30)}."))
    return notes


def portfolio(rows: pd.DataFrame, *, programs: dict, order_fee: float, fallback_kotor_pct: float = float("nan"),
              acuan_pct: float | None = None, affiliate_on: bool = False) -> pd.DataFrame:
    """Margin bersih per SKU. rows: sku, nama, kategori, harga, diskon_unit, voucher_unit, admin_pct, affiliate_pct, iklan_unit, roas,
    qty_30, omzet_30, ukuran_khusus, margin_kotor_pct (dari file; NaN → rata-rata toko), pajak_share, sumber.

    Status: Rugi (< 0) · Rendah (untung, di bawah batas) · Tinggi (≥ batas). Batas (acuan_pct) bawaan = rata-rata margin bersih SKU yang
    untung. Prioritas = Rugi menurut kerugian Rp 30 hari, lalu Rendah menurut selisih Rp ke batas (omzet × selisih %), lalu Tinggi
    menurut omzet. attrs: acuan_pct (batas), overall_pct (rata-rata toko seluruh SKU)."""
    from src.core.margin_file import DEFAULT_TAX_SHARE, classify

    out = []
    for r in rows.itertuples(index=False):
        kotor = getattr(r, "margin_kotor_pct", np.nan)
        sumber = getattr(r, "sumber", "") or ""
        if kotor is None or not np.isfinite(kotor):
            kotor, sumber = fallback_kotor_pct, ("Rata-rata toko" if np.isfinite(fallback_kotor_pct) else "")
        tax = getattr(r, "pajak_share", np.nan)
        tax = DEFAULT_TAX_SHARE if tax is None or not np.isfinite(tax) else float(tax)
        inp = Inputs(
            harga=float(r.harga), diskon=float(r.diskon_unit), voucher=float(r.voucher_unit), admin_pct=float(r.admin_pct),
            programs=programs, order_fee=order_fee, affiliate_pct=float(r.affiliate_pct or 0), affiliate_on=affiliate_on and bool(r.affiliate_pct),
            iklan=float(r.iklan_unit or 0), ukuran_khusus=bool(r.ukuran_khusus),
        )
        base = inp.harga_akhir
        known = np.isfinite(kotor)
        if known:
            inp = replace(inp, pajak_share=tax, hpp=max(base * (1 - tax - kotor / 100.0), 0.0))
        value, pct = margin(inp) if known else (np.nan, np.nan)
        omzet = float(r.omzet_30 or 0)
        out.append({
            "sku": r.sku, "nama": r.nama, "kategori": r.kategori, "harga_akhir": base, "qty_30": float(r.qty_30 or 0), "omzet_30": omzet,
            "kotor_pct": kotor if known else np.nan, "sumber": sumber, "shopee_pct": shopee_fees(inp) / base * 100 if base else np.nan,
            "iklan_unit": float(r.iklan_unit or 0), "iklan_pct": float(r.iklan_unit or 0) / base * 100 if base else np.nan, "roas": r.roas,
            "affiliate_pct": float(r.affiliate_pct or 0), "total_pct": cost_pct(inp), "bersih_unit": value, "bersih_pct": pct,
            "bersih_30": value * float(r.qty_30 or 0) if known else np.nan, "_inp": inp,
        })
    frame = pd.DataFrame(out)
    if frame.empty:
        return frame
    part = frame.loc[frame["sumber"].isin(["Shopee", "Nasional"]) & frame["bersih_30"].notna()]
    overall = float(part["bersih_30"].sum() / part["omzet_30"].sum() * 100) if part["omzet_30"].sum() > 0 else float("nan")
    if acuan_pct is None:
        # Batas "margin rendah" = rata-rata margin bersih SKU yang untung (tetap bermakna walau rata-rata toko minus).
        gain = part.loc[part["bersih_pct"] >= 0]
        acuan_pct = float(gain["bersih_30"].sum() / gain["omzet_30"].sum() * 100) if gain["omzet_30"].sum() > 0 else float("nan")
    frame.attrs["overall_pct"] = overall
    frame["status"] = [classify(p, acuan_pct) for p in frame["bersih_pct"]]
    frame["rugi_30"] = (frame["omzet_30"] * (-frame["bersih_pct"]).clip(lower=0) / 100).fillna(0.0)
    frame["selisih_30"] = (frame["omzet_30"] * (acuan_pct - frame["bersih_pct"]).clip(lower=0) / 100).fillna(0.0) if np.isfinite(acuan_pct) else 0.0
    steps = []
    for row, inp in zip(frame.itertuples(index=False), frame["_inp"]):
        roas = row.roas if row.roas == row.roas else None
        if row.status == "Rugi":
            todo = fixes(inp, 0.0, roas)
        elif row.status == "Rendah":
            todo = fixes(inp, acuan_pct, roas)
        elif row.status == "Tinggi":
            cap = max_iklan(inp, acuan_pct) if np.isfinite(acuan_pct) else 0.0
            todo = ["Pertahankan; layak didorong" + (f" (iklan s.d. {_rp(cap)}/unit, ROAS ≥ " + f"{row.harga_akhir / cap:.1f}".replace(".", ",") + ")" if cap > 0 else "")]
        else:
            todo = ["Margin belum ada di file margin"]
        steps.append("; ".join(todo) if todo else "—")
    frame["perbaikan"] = steps
    frame.attrs["acuan_pct"] = acuan_pct
    order = {"Rugi": 0, "Rendah": 1, "Tinggi": 2, "Tanpa data": 3}
    frame["_o"] = frame["status"].map(order)
    frame["_v"] = np.where(frame["status"] == "Rugi", frame["rugi_30"], np.where(frame["status"] == "Rendah", frame["selisih_30"], frame["omzet_30"]))
    frame = frame.sort_values(["_o", "_v", "omzet_30"], ascending=[True, False, False]).drop(columns=["_o", "_v", "_inp"]).reset_index(drop=True)
    frame.attrs.update({"acuan_pct": acuan_pct, "overall_pct": overall})
    return frame


# --------------------------------------------------------------------------- kategori per SKU & margin bersih ringkas

_SUGGEST: dict[tuple[str, int], int | None] = {}


def admin_for(sku: str, name: str, fees: pd.DataFrame, sku_cat: dict | None) -> tuple[int | None, float]:
    """(baris kategori, biaya admin %) SKU: kategori tersimpan → usulan dari nama produk (di-cache) → 11,70%."""
    idx = None
    saved = (sku_cat or {}).get(str(sku))
    if saved:
        hit = fees.index[(fees["kategori"] == saved.get("kategori")) & (fees["jenis_produk"] == saved.get("jenis_produk"))]
        idx = int(hit[0]) if len(hit) else None
    if idx is None:
        key = (str(name), len(fees))
        if key not in _SUGGEST:
            _SUGGEST[key] = suggest_category(name, fees)
        idx = _SUGGEST[key]
    admin = float(fees.loc[idx, "biaya_admin_pct"]) if idx is not None and pd.notna(fees.loc[idx, "biaya_admin_pct"]) else DEFAULT_ADMIN_PCT
    return idx, admin


def net_margin_map(products: pd.DataFrame, kotor: dict[str, float], *, programs: dict, order_fee: float, fees: pd.DataFrame,
                   sku_cat: dict | None, ad_per_unit: dict[str, float] | None, fallback_kotor_pct: float = float("nan"),
                   inputs: dict | None = None) -> tuple[dict[str, float], float]:
    """Margin bersih % per SKU (margin kotor file − potongan Shopee − iklan) dari harga data produk; juga rata-rata sederhana.

    Dipakai menu lain (iklan, promo) yang butuh margin per SKU tanpa membuka Kalkulator. kotor: sku_key → margin kotor %."""
    from src.core.margin_file import DEFAULT_TAX_SHARE, sku_key

    out: dict[str, float] = {}
    ads = ad_per_unit or {}
    for row in products.drop_duplicates("sku").itertuples(index=False):
        price = float(row.price or 0)
        if price <= 0:
            continue
        value = kotor.get(sku_key(row.sku), fallback_kotor_pct)
        if value is None or not np.isfinite(value):
            continue
        _idx, admin = admin_for(row.sku, row.product_name, fees, sku_cat)
        inp = Inputs(harga=price, admin_pct=admin, programs=programs, order_fee=order_fee, iklan=float(ads.get(str(row.sku), 0.0) or 0.0),
                     ukuran_khusus="packing kayu" in str(row.product_name).lower())
        inp = replace(inp, pajak_share=DEFAULT_TAX_SHARE, hpp=max(price * (1 - DEFAULT_TAX_SHARE - value / 100.0), 0.0))
        out[str(row.sku)] = margin(inp)[1]
        if inputs is not None:
            inputs[str(row.sku)] = inp
    mean = float(np.nanmedian(list(out.values()))) if out else float("nan")
    return out, mean
