"""Flash sale toko Shopee yang tetap berjalan saat stok terbatas.

Per SKU (yang laku dan punya prediksi):
- Tujuan: "Habiskan stok lebih" bila stok di atas SS cukup untuk ≥ 90 hari dan lebih ≥ 5 unit dari kebutuhan 30 hari;
  selain itu "Pendorong omzet".
- Kuota target: pendorong = maks(3, 3 × prediksi harian); habiskan stok = 20% kelebihan stok 30 hari, min. 5, tidak lebih
  dari penjualan normal 30 hari (min. 5) dan 100.
- Batal: SKU dengan batal > maks(15%, 1,5 × rata-rata batal toko tertimbang omzet) tidak dijadwalkan; batal > 15% tetap
  boleh dengan batas beli 1/pembeli.
- Sumber kuota (urut): stok toko di atas SS + kebutuhan 7 hari → transfer dari DC 10062/10036 (dikirim paling lambat
  H-3) → kuota kecil dari stok di atas SS (maks. separuhnya). Stok 0 / di bawah SS dan DC kosong → tidak dijadwalkan.
- Harga flash = harga × (1 − diskon) dibulatkan ke atas Rp 100, tidak di bawah harga impas (margin 0, tanpa biaya iklan
  karena pesanan flash sale tidak lewat iklan). Diskon dicoba dari yang terbesar: pendorong 10/7/5%, habiskan stok
  20/15/10/5%. Mode prioritas omzet: bila tidak ada ruang, diskon minimal dipakai dan rugi per unit dicatat.
- Stok flash per SKU dibagi ke semua slotnya (slot berulang tidak memakai stok yang sama dua kali).
- Jadwal harian: tiap hari `per_day` SKU (+3 di tanggal kembar, gajian 25, Harbolnas), campuran pendorong & habiskan
  stok, SKU sama berjarak ≥ 7 hari (≥ 3 hari bila kandidat kurang), SKU dari DC baru boleh tampil ≥ 3 hari setelah hari
  ini (waktu transfer).
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.core.promo_calendar import SLOT_HOURS, special_days

DRIVER = "Pendorong omzet"
CLEAR = "Habiskan stok lebih"
SRC_SITE = "Stok toko"
SRC_DC = "Transfer dari DC"
SRC_THIN = "Kuota kecil (stok tipis)"
DISCOUNTS = {DRIVER: (0.10, 0.07, 0.05), CLEAR: (0.20, 0.15, 0.10, 0.05)}
TRANSFER_DAYS = 3
MIN_GAP_DAYS = 3          # bila kandidat kurang, SKU boleh diulang setelah 3 hari agar flash sale tetap jalan
OVERSTOCK_DAYS = 90
CANCEL_LIMIT = 15.0

INPUT_COLUMNS = ("sku", "label", "nama", "harga", "stok", "ada_stok", "ss", "harian", "dc", "terjual", "m_sales", "batal_pct", "floor", "momentum", "bottom")
CANDIDATE_COLUMNS = ["sku", "label", "nama", "tujuan", "sumber", "kuota", "harga", "harga_flash", "diskon", "skor", "stok", "dc", "hari_stok",
                     "batas_beli", "margin_unit", "alasan", "stok_flash", "bottom"]


def bottom_price_cap(price: float, bottom: float) -> tuple[float, float] | None:
    """(harga promo, diskon) tepat di bottom price (dibulatkan ke atas Rp 100) bila bottom < harga normal; None bila tidak ada ruang."""
    if not np.isfinite(bottom) or bottom <= 0 or price <= 0:
        return None
    value = float(math.ceil(bottom / 100.0) * 100)
    if value >= price:
        return None
    return value, 1 - value / price


def _num(value, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if np.isfinite(out) else default


def flash_price(price: float, discounts: tuple[float, ...], floor: float | None) -> tuple[float, float] | None:
    """(harga flash, diskon) dengan diskon terbesar yang harganya masih ≥ harga impas; None bila tidak ada."""
    for disc in discounts:
        value = float(math.ceil(price * (1 - disc) / 100.0) * 100)
        if floor is None or not np.isfinite(floor) or value >= floor:
            return value, disc
    return None


def candidates(items: pd.DataFrame, *, excluded: set[str] | None = None, below_floor: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(kandidat, tidak dijadwalkan). items: kolom INPUT_COLUMNS (lihat `rekomendasi_plus._flash_items`).

    below_floor=True (prioritas omzet): SKU yang harga impasnya tidak memberi ruang diskon tetap ikut dengan diskon minimal
    5%, rugi per unit dicatat. False: SKU itu tidak dijadwalkan."""
    excluded = excluded or set()
    limit = cancel_limit(items)
    rows, skipped = [], []
    for r in items.to_dict("records"):
        sku, label = str(r["sku"]), str(r.get("label") or r["sku"])
        price, daily = _num(r.get("harga"), 0.0), _num(r.get("harian"), 0.0)
        known = bool(r.get("ada_stok"))
        stok = _num(r.get("stok"), 0.0) if known else float("nan")
        ss, dc = _num(r.get("ss"), 0.0), max(_num(r.get("dc"), 0.0), 0.0)
        cancel = _num(r.get("batal_pct"))

        def skip(reason: str) -> None:
            skipped.append({"SKU · produk · varian": label, "Stok toko": stok, "Stok DC": dc, "Alasan": reason})

        if sku in excluded:
            skip("SKU jasa")
            continue
        if price <= 0 or daily <= 0 or _num(r.get("terjual"), 0.0) <= 0:
            skip("tidak terjual 90 hari terakhir / belum ada harga")
            continue
        if cancel == cancel and cancel > limit:
            skip(f"batal tinggi {cancel:.0f}% (batas {limit:.0f}%): flash sale memperbanyak pesanan batal")
            continue
        above_ss = stok - ss if known else float("nan")
        free = above_ss - daily * 7 if known else float("nan")
        excess = above_ss - daily * 30 if known else float("nan")
        cover = above_ss / daily if known else float("nan")
        purpose = CLEAR if known and cover >= OVERSTOCK_DAYS and excess >= 5 else DRIVER
        if purpose == DRIVER:
            target = max(3, math.ceil(daily * 3))
        else:
            target = min(max(5, math.ceil(excess * 0.2)), max(5, math.ceil(daily * 30)), 100)
        notes: list[str] = []
        if cancel == cancel and cancel > CANCEL_LIMIT:
            notes.append(f"batal {cancel:.0f}%: batas beli 1/pembeli, kejar bayar pesanan flash lewat chat")
        if known and free >= 2:
            pool = math.floor(free)
            source, quota = SRC_SITE, int(min(target, pool))
            notes.append(f"stok toko {stok:.0f}, sisa {free:.0f} setelah SS + kebutuhan 7 hari")
        elif dc >= 2:
            pool = math.floor(dc / 2)
            source, quota = SRC_DC, int(min(target, pool))
            notes.append(f"stok toko {'belum ada datanya' if not known else f'{stok:.0f} (tipis)'}; DC {dc:.0f}: transfer {quota} unit")
        elif known and above_ss >= 2:
            pool = math.floor(above_ss / 2)
            source, quota = SRC_THIN, int(min(target, pool))
            notes.append(f"stok {stok:.0f} sedikit di atas SS {ss:.0f}: kuota kecil, ajukan restock")
        else:
            skip("data stok belum ada dan DC kosong" if not known else "stok 0 / di bawah SS dan DC kosong: restock dulu")
            continue
        floor = _num(r.get("floor"))
        bottom = _num(r.get("bottom"))
        if floor != floor:
            notes.append("margin belum diketahui (File margin/harga beli): cek harga impas sebelum dijalankan")
        if bottom == bottom and bottom >= price:
            skip(f"bottom price merchandising Rp {bottom:,.0f} ≥ harga normal: tidak ada ruang promo".replace(",", "."))
            continue
        # Harga flash mengikuti bottom price MD (harga promo terendah yang disetujui) selama ≥ harga impas dan diskonnya ≥ 5%.
        # Tanpa bottom price MD: diskon terbesar 10/7/5% (habiskan stok 20…5%) yang ≥ harga impas → diusulkan sebagai bottom price ke codif.
        priced = None
        if bottom == bottom and (floor != floor or bottom >= floor):
            priced = bottom_price_cap(price, bottom)
            if priced is not None and priced[1] < 0.05:
                skip(f"bottom price MD Rp {bottom:,.0f} hanya memberi diskon {priced[1] * 100:.1f}% (< 5%): tidak layak flash sale".replace(",", "."))
                continue
            if priced is not None:
                notes.append(f"harga flash = bottom price MD Rp {bottom:,.0f}".replace(",", "."))
        if priced is None:
            price_floor = max(v for v in (floor, bottom) if v == v) if (floor == floor or bottom == bottom) else None
            priced = flash_price(price, DISCOUNTS[purpose], price_floor)
            if priced is not None and bottom != bottom:
                notes.append("belum ada bottom price MD: ajukan harga flash ini sebagai bottom price ke codif")
            elif priced is not None:
                notes.append(f"bottom price MD Rp {bottom:,.0f} di bawah impas: harga flash dinaikkan ke ≥ impas".replace(",", "."))
        if priced is None and not below_floor:
            skip("harga impas / bottom price tidak memberi ruang diskon")
            continue
        if priced is None:
            priced = flash_price(price, (min(DISCOUNTS[purpose]),), bottom if bottom == bottom else None) or bottom_price_cap(price, bottom)
            if priced is None:
                skip("bottom price tidak memberi ruang diskon")
                continue
            if floor == floor and priced[0] < floor:
                notes.append(f"di bawah impas: rugi ±Rp {floor - priced[0]:,.0f}/unit (diskon minimal)".replace(",", "."))
        flash, disc = priced
        momentum = _num(r.get("momentum"), 0.0)
        if purpose == DRIVER:
            score = _num(r.get("m_sales"), price * daily * 30) * (1 + max(momentum, -0.5))
            notes.append("laris" + (f", tren 14 hari {momentum * 100:+.0f}%" if momentum else ""))
        else:
            score = excess * price
            notes.append(f"stok cukup {cover:.0f} hari: diskon lebih besar untuk memutar stok")
        alert = ""
        if not known or stok <= 0:
            alert = "stok 10037 kosong: tambah/transfer stok dulu sebelum flash sale"
        elif source != SRC_SITE:
            alert = f"stok 10037 tipis ({stok:.0f}): tambah/transfer stok dulu"
        if alert:
            notes.insert(0, "⚠️ " + alert)
        rows.append({"sku": sku, "label": label, "nama": str(r.get("nama") or label), "tujuan": purpose, "sumber": source, "kuota": max(quota, 1),
                     "harga": price, "harga_flash": flash, "diskon": disc * 100, "skor": score, "stok": stok, "dc": dc,
                     "hari_stok": cover, "batas_beli": 1 if cancel == cancel and cancel > CANCEL_LIMIT else None,
                     "margin_unit": flash - floor if floor == floor else np.nan, "alasan": "; ".join(notes), "stok_flash": max(pool, 1),
                     "bottom": bottom, "nilai": _num(r.get("m_sales"), price * daily * 30), "qty_hari": daily,
                     "margin_pct": (flash - floor) / flash * 100 if floor == floor and flash > 0 else np.nan, "peringatan_stok": alert})
    frame = pd.DataFrame(rows, columns=CANDIDATE_COLUMNS + ["nilai", "qty_hari", "margin_pct", "peringatan_stok"])
    if not frame.empty:
        # Skor gabungan: volume value (40%), volume qty (30%), margin di harga flash (30%) — peringkat persentil antar kandidat;
        # pendorong omzet memakai prediksi omzet × tren, habiskan stok memakai nilai stok berlebih sebagai "value".
        rank = lambda s: pd.to_numeric(s, errors="coerce").rank(pct=True).fillna(0.0)  # noqa: E731
        frame["skor"] = 0.4 * rank(frame["skor"]) + 0.3 * rank(frame["qty_hari"]) + 0.3 * rank(frame["margin_pct"])
    return frame, pd.DataFrame(skipped, columns=["SKU · produk · varian", "Stok toko", "Stok DC", "Alasan"])


def cancel_limit(items: pd.DataFrame) -> float:
    """Batas batal flash sale = maks(15%, 1,5 × rata-rata batal toko tertimbang prediksi omzet).

    Produk bulky di toko ini wajar batal 25–35% (belum bayar); batas tetap 15% akan membuang semua produk andalan."""
    if items is None or items.empty or "batal_pct" not in items.columns:
        return CANCEL_LIMIT
    rate = pd.to_numeric(items["batal_pct"], errors="coerce")
    weight = pd.to_numeric(items.get("m_sales", pd.Series(0.0, index=items.index)), errors="coerce").fillna(0.0).clip(lower=0)
    ok = rate.notna() & (weight > 0)
    if not ok.any():
        return CANCEL_LIMIT
    return float(max(CANCEL_LIMIT, 1.5 * float((rate[ok] * weight[ok]).sum() / weight[ok].sum())))


def schedule(cands: pd.DataFrame, start: date, *, today: date, days: int = 14, per_day: int = 5, special_extra: int = 3,
             gap_days: int = 7, clear_share: float = 0.4) -> pd.DataFrame:
    """Jadwal harian flash sale toko. Selalu terisi selama ada kandidat."""
    cols = ["Tanggal", "Momen", "Jam", "Tujuan", "SKU", "Produk", "Harga normal", "Bottom price", "Harga flash", "Diskon (%)", "Kuota", "Batas beli/pembeli",
            "Sumber stok", "Kirim dari DC paling lambat", "Estimasi omzet maks.", "Margin/unit", "Margin (%)", "Peringatan stok 10037", "Alasan"]
    if cands is None or cands.empty:
        return pd.DataFrame(columns=cols)
    specials: dict[date, str] = {}
    cursor = date(start.year, start.month, 1)
    while cursor <= start + timedelta(days=days):
        specials.update(dict(special_days(cursor.year, cursor.month)))
        cursor = (pd.Timestamp(cursor) + pd.DateOffset(months=1)).date()
    pools = {p: cands.loc[cands["tujuan"] == p].sort_values("skor", ascending=False).to_dict("records") for p in (DRIVER, CLEAR)}
    used: dict[str, date] = {}
    left = {str(item["sku"]): int(item.get("stok_flash", item["kuota"]) or item["kuota"]) for pool in pools.values() for item in pool}
    rows = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        label = specials.get(day, "")
        count = per_day + (special_extra if label else 0)
        n_clear = round(count * clear_share) if pools[CLEAR] else 0
        wanted = [(CLEAR, n_clear), (DRIVER, count - n_clear)]
        picked: list[dict] = []

        def take(pool: list[dict], n: int, gap: int = gap_days) -> None:
            for item in pool:
                if n <= 0:
                    break
                if item in picked or (item["sku"] in used and (day - used[item["sku"]]).days < gap) or left.get(str(item["sku"]), 0) < 1:
                    continue
                if item["sumber"] == SRC_DC and (day - today).days < TRANSFER_DAYS:
                    continue
                picked.append(item)
                n -= 1

        for purpose, n in wanted:
            take(pools[purpose], n)
        if len(picked) < count:
            take(pools[DRIVER] + pools[CLEAR], count - len(picked))
        if len(picked) < count:
            take(pools[DRIVER] + pools[CLEAR], count - len(picked), gap=MIN_GAP_DAYS)
        for slot, item in enumerate(picked):
            used[item["sku"]] = day
            quota = int(min(int(item["kuota"]), left.get(str(item["sku"]), int(item["kuota"]))))
            left[str(item["sku"])] = left.get(str(item["sku"]), quota) - quota
            rows.append({
                "Tanggal": day, "Momen": label or "Harian", "Jam": SLOT_HOURS[slot % len(SLOT_HOURS)], "Tujuan": item["tujuan"],
                "SKU": item["sku"], "Produk": item["label"], "Harga normal": item["harga"], "Bottom price": item.get("bottom", np.nan),
                "Harga flash": item["harga_flash"],
                "Diskon (%)": item["diskon"], "Kuota": quota,
                "Batas beli/pembeli": int(item["batas_beli"]) if pd.notna(item.get("batas_beli")) else int(min(max(quota // 5, 1), 5)),
                "Sumber stok": item["sumber"],
                "Kirim dari DC paling lambat": day - timedelta(days=TRANSFER_DAYS) if item["sumber"] == SRC_DC else None,
                "Estimasi omzet maks.": quota * item["harga_flash"], "Margin/unit": item.get("margin_unit", np.nan),
                "Margin (%)": item.get("margin_pct", np.nan), "Peringatan stok 10037": item.get("peringatan_stok", ""), "Alasan": item["alasan"],
            })
    return pd.DataFrame(rows, columns=cols)


def transfers(plan: pd.DataFrame) -> pd.DataFrame:
    """Daftar transfer DC → toko untuk SKU flash sale bersumber DC: total unit dan tanggal kirim paling lambat."""
    cols = ["SKU", "Produk", "Unit transfer", "Kirim paling lambat", "Jumlah slot"]
    if plan is None or plan.empty:
        return pd.DataFrame(columns=cols)
    part = plan.loc[plan["Sumber stok"] == SRC_DC]
    if part.empty:
        return pd.DataFrame(columns=cols)
    out = part.groupby(["SKU", "Produk"], as_index=False).agg(**{"Unit transfer": ("Kuota", "sum"), "Kirim paling lambat": ("Kirim dari DC paling lambat", "min"),
                                                                  "Jumlah slot": ("Tanggal", "count")})
    return out.sort_values("Kirim paling lambat").reset_index(drop=True)[cols]


def shopee_template(plan: pd.DataFrame) -> pd.DataFrame:
    """Kolom isian flash sale toko di Seller Centre."""
    cols = ["Tanggal", "Jam", "SKU", "Nama Produk", "Harga Normal", "Harga Flash Sale", "Stok Flash Sale", "Batas Pembelian"]
    if plan is None or plan.empty:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame({
        "Tanggal": pd.to_datetime(plan["Tanggal"]).dt.strftime("%d/%m/%Y"), "Jam": plan["Jam"], "SKU": plan["SKU"], "Nama Produk": plan["Produk"],
        "Harga Normal": plan["Harga normal"].round(0), "Harga Flash Sale": plan["Harga flash"].round(0), "Stok Flash Sale": plan["Kuota"],
        "Batas Pembelian": plan["Batas beli/pembeli"],
    })[cols]
