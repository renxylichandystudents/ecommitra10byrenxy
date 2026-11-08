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

# Biaya program Shopee Mall (dari tabel biaya penjual): (nama, tarif %, maks Rp per kuantitas, dasar, wajib?)
DEFAULT_PROGRAMS = {
    "pembayaran": {"label": "Biaya Pembayaran Shopee Mall", "pct": 1.80, "cap": 50_000.0, "on": True, "wajib": True},
    "pajak": {"label": "Pajak", "pct": 0.50, "cap": 0.0, "on": True, "wajib": True},
    "gratis_ongkir": {"label": "Gratis Ongkir XTRA", "pct": 0.0, "cap": 40_000.0, "on": True, "wajib": False},
    "promo_xtra": {"label": "Promo XTRA", "pct": 4.50, "cap": 60_000.0, "on": True, "wajib": False},
    "live_xtra": {"label": "Live XTRA", "pct": 2.00, "cap": 20_000.0, "on": True, "wajib": False},
    "asuransi": {"label": "Asuransi Pengiriman Shopee", "pct": 0.50, "cap": 0.0, "on": True, "wajib": False},
}
DEFAULT_ORDER_FEE = 1_250.0  # Biaya Proses Pesanan per pesanan selesai


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
    hpp: float = 0.0
    packing: float = 0.0
    ongkir: float = 0.0          # ongkir ditanggung penjual per unit

    @property
    def harga_akhir(self) -> float:
        return max(float(self.harga) - float(self.diskon) - float(self.voucher), 0.0)


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
        cap = float(prog.get("cap") or 0)
        tarif = f"{float(prog['pct']):.2f}%".replace(".", ",") + (f" (maks Rp{cap:,.0f})".replace(",", ".") if cap else "")
        rows.append((prog["label"], "harga akhir", tarif, -_capped(base, float(prog["pct"]), cap)))
    per_order = float(inp.order_fee) / max(float(inp.qty_per_order or 1), 1.0)
    rows.append(("Biaya Proses Pesanan", f"Rp{inp.order_fee:,.0f}/pesanan ÷ {inp.qty_per_order:g} unit".replace(",", "."), "", -per_order))
    if inp.affiliate_on and inp.affiliate_pct:
        rows.append(("Komisi affiliate", "harga akhir", f"{inp.affiliate_pct:.2f}%".replace(".", ","), -_capped(base, inp.affiliate_pct, 0)))
    rows.append(("Biaya iklan per unit", "data iklan", "", -float(inp.iklan)))
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
    for prog in inp.programs.values():
        if prog.get("on"):
            total += _capped(base, float(prog["pct"]), float(prog.get("cap") or 0))
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


def analysis(inp: Inputs, *, target_pct: float, pred_qty_30: float | None = None, roas: float | None = None) -> list[tuple[str, str]]:
    """Daftar (tingkat, kalimat) untuk kotak analisa: 'ok' / 'warn' / 'bad' / 'info'."""
    notes: list[tuple[str, str]] = []
    value, pct = margin(inp)
    base = inp.harga_akhir

    def rp(x: float) -> str:
        return ("−" if x < 0 else "") + "Rp" + f"{abs(x):,.0f}".replace(",", ".")

    def pc(x: float) -> str:
        return f"{x:.1f}%".replace(".", ",")

    if inp.hpp <= 0:
        notes.append(("warn", "HPP belum diisi: margin di bawah belum termasuk harga pokok, jadi terlihat lebih besar dari kenyataan."))
    if inp.hpp <= 0:
        pass
    elif value < 0:
        notes.append(("bad", f"Rugi {rp(-value)} per unit ({pc(pct)}). Setiap unit terjual mengurangi laba."))
    elif pct < target_pct:
        notes.append(("warn", f"Untung tipis: margin {rp(value)} ({pc(pct)}) di bawah target {pc(target_pct)}."))
    else:
        notes.append(("ok", f"Aman: margin {rp(value)} per unit ({pc(pct)}) ≥ target {pc(target_pct)}."))
    frame = breakdown(inp)
    costs = frame.loc[frame["Rp per unit"] < 0].copy()
    costs = costs.loc[~costs["Komponen"].isin(["Diskon penjual", "Voucher penjual"])]
    if not costs.empty:
        top = costs.sort_values("Rp per unit").head(3)
        notes.append(("info", "Biaya terbesar: " + ", ".join(f"{r.Komponen} {rp(-r._4)} ({pc(-r._5)})" for r in top.itertuples())))
    fees = shopee_fees(inp)
    notes.append(("info", f"Total potongan Shopee {rp(fees)} per unit = {pc(fees / base * 100 if base else 0)} dari harga akhir."))
    if inp.hpp > 0:
        need = min_price(inp, target_pct)
        bep = min_price(inp, 0.0)
        if np.isfinite(need):
            notes.append(("info" if inp.harga >= need else "warn",
                          f"Harga minimal untuk margin {pc(target_pct)}: {rp(need)} · titik impas (margin 0): {rp(bep)}."))
        # Program opsional yang paling membebani: apakah mematikannya membuat margin mencapai target?
        if pct < target_pct:
            for key, prog in sorted(inp.programs.items(), key=lambda kv: -_capped(base, float(kv[1]["pct"]), float(kv[1].get("cap") or 0))):
                if prog.get("wajib") or not prog.get("on") or not prog["pct"]:
                    continue
                trial = replace(inp, programs={**inp.programs, key: {**prog, "on": False}})
                v2, p2 = margin(trial)
                notes.append(("info", f"Tanpa {prog['label']}: margin menjadi {rp(v2)} ({pc(p2)})."))
                break
        cap_ads = max_iklan(inp, target_pct)
        if cap_ads <= 0:
            notes.append(("bad", "Tanpa iklan pun margin belum mencapai target: perbaiki harga/HPP sebelum menambah iklan."))
        else:
            min_roas = base / cap_ads
            text = f"Biaya iklan maksimal {rp(cap_ads)} per unit agar margin tetap {pc(target_pct)} → ROAS minimal " + f"{min_roas:.1f}".replace(".", ",")
            if roas and np.isfinite(roas):
                text += "; ROAS iklan saat ini " + f"{roas:.1f}".replace(".", ",") + (" ✓" if roas >= min_roas else " — terlalu rendah, iklan memakan margin")
            notes.append(("info" if inp.iklan <= cap_ads else "warn", text))
        cap_aff = max_affiliate_pct(inp, target_pct)
        if inp.affiliate_pct:
            notes.append(("info" if cap_aff >= inp.affiliate_pct else "warn",
                          f"Komisi affiliate {pc(inp.affiliate_pct)}; maksimal {pc(max(cap_aff, 0))} agar margin tetap {pc(target_pct)}."))
    if pred_qty_30 and pred_qty_30 > 0:
        if inp.hpp > 0:
            notes.append(("info", "Prediksi 30 hari " + f"{pred_qty_30:,.0f}".replace(",", ".") + f" unit × margin {rp(value)} = perkiraan laba {rp(value * pred_qty_30)}."))
    return notes
