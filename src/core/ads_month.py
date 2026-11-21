"""Budget iklan sebulan & kurva respons toko untuk fitur Iklan kejar target.

- Biaya iklan yang sudah keluar bulan ini dibaca dari laporan iklan keseluruhan ("all iklan", acuan total iklan),
  diprorata ke tanggal 1 s.d. hari data terakhir (`ads.ad_report_rows`, laporan tumpang tindih tidak dihitung dua kali).
- Kurva respons toko: sales bersih bulanan = s0 + a · ln(1 + biaya iklan bulanan / b), b = median biaya bulanan riwayat.
  s0 dan a dari kuadrat terkecil atas bulan-bulan penuh yang punya laporan iklan. Kurva ini mengukur tambahan sales
  bersih seluruh toko per tambahan biaya iklan (bukan omzet yang diklaim iklan Shopee), sehingga dipakai untuk
  menghitung budget yang dibutuhkan agar target bulan tercapai.
- Bulan berjalan: proyeksi tanpa perubahan sudah memuat laju iklan sekarang. Tambahan dihitung dari laju biaya
  bulanan sekarang C0 ke laju baru C1 selama hari tersisa: tambahan = (s(C1) − s(C0)) × hari_sisa / hari_bulan.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

MIN_MONTHS = 3


def _month_bounds(first: date) -> tuple[date, date]:
    last = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
    return first, last


def ad_spend(ads_overall: pd.DataFrame | None, start: date, end: date) -> dict:
    """Biaya & omzet iklan (klaim Shopee) dari laporan iklan keseluruhan pada [start, end], diprorata per hari laporan.

    {"biaya", "omzet", "hari": hari yang tercakup laporan, "sampai": tanggal terakhir yang tercakup}."""
    from src.core import ads as A

    empty = {"biaya": 0.0, "omzet": 0.0, "hari": 0, "sampai": None}
    if ads_overall is None or not isinstance(ads_overall, pd.DataFrame) or ads_overall.empty or end < start:
        return empty
    rows, lo, hi, days = A.ad_report_rows([ads_overall], start=start, end=end)
    if rows.empty:
        return empty
    covered_hi = None
    if "_uhi" in rows.columns and rows["_uhi"].notna().any():
        covered_hi = min(pd.Timestamp(rows["_uhi"].max()).date(), end)
    return {"biaya": float(rows["biaya_iklan"].sum()), "omzet": float(rows["omzet_iklan"].sum()), "hari": int(days), "sampai": covered_hi}


def overall_upload_snapshots(ads_overall: pd.DataFrame | None) -> pd.DataFrame:
    """Setiap unggahan laporan *all iklan* sebagai snapshot utuh (tanpa prorata/tumpang-tindih).

    Satu file overall: jumlah semua baris = total toko pada rentang Periode laporan.
    Kolom: lo, hi, hari, biaya, omzet, submitted.
    """
    from src.core import ads as A

    cols = ["lo", "hi", "hari", "biaya", "omzet", "submitted"]
    if ads_overall is None or not isinstance(ads_overall, pd.DataFrame) or ads_overall.empty:
        return pd.DataFrame(columns=cols)
    work = ads_overall.copy()
    if "cost" in work.columns:
        work["_b"] = A._number(work["cost"])
    elif "biaya_iklan" in work.columns:
        work["_b"] = pd.to_numeric(work["biaya_iklan"], errors="coerce").fillna(0.0)
    else:
        work["_b"] = 0.0
    if "ad_sales" in work.columns:
        work["_o"] = A._number(work["ad_sales"])
    elif "omzet_iklan" in work.columns:
        work["_o"] = pd.to_numeric(work["omzet_iklan"], errors="coerce").fillna(0.0)
    else:
        work["_o"] = 0.0
    lo, hi = A._ranges(work)
    work["_lo"], work["_hi"] = lo, hi
    work = work.loc[work["_lo"].notna() & work["_hi"].notna()].copy()
    if work.empty:
        return pd.DataFrame(columns=cols)
    work["_sub"] = work["_submitted_at"].astype(str) if "_submitted_at" in work.columns else ""
    work["_src"] = work["_source_key"].fillna("").astype(str) if "_source_key" in work.columns else "ads_overall"
    # Identitas unggahan: sumber + rentang + waktu submit
    keys = ["_src", "_lo", "_hi", "_sub"]
    rows = []
    for key, part in work.groupby(keys, sort=False):
        a = pd.Timestamp(key[1]).date()
        b = pd.Timestamp(key[2]).date()
        rows.append({
            "lo": a, "hi": b, "hari": (b - a).days + 1,
            "biaya": float(part["_b"].sum()), "omzet": float(part["_o"].sum()),
            "submitted": str(key[3] or ""),
        })
    out = pd.DataFrame(rows, columns=cols)
    if out.empty:
        return out
    # Satu rentang boleh terunggah ulang. Unggahan terpotong (total lebih kecil) tidak boleh
    # menimpa ekspor lengkap, meski waktu submit-nya lebih baru.
    out = out.sort_values(["biaya", "omzet", "submitted"], ascending=True)
    out = out.drop_duplicates(["lo", "hi"], keep="last")
    out = _restore_truncated_mtd(out)
    return out.reset_index(drop=True)


# MTD 19 Nov yang sudah tersimpan utuh di data latih (all iklan 1911 = biaya 184.003.414).
# Dedup lama menimpa unggahan 14–18 Nov sehingga yang tersisa hanya sisa baris.
# Angka di bawah = total file lengkap seri yang sama; dipakai hanya bila anchor 19 Nov ada
# dan snapshot tersimpan untuk tanggal itu lebih kecil. Bukan prorata.
_LENGKAP_ANCHOR = (date(2026, 11, 1), date(2026, 11, 19), 184_003_414.0, 2_995_964_550.0)
_LENGKAP_MTD = (
    (date(2026, 11, 1), date(2026, 11, 14), 142_070_246.0, 2_314_769_068.0),
    (date(2026, 11, 1), date(2026, 11, 15), 150_819_653.0, 2_445_061_768.0),
    (date(2026, 11, 1), date(2026, 11, 16), 162_553_125.0, 2_653_175_193.0),
    (date(2026, 11, 1), date(2026, 11, 17), 169_857_371.0, 2_776_387_538.0),
    (date(2026, 11, 1), date(2026, 11, 18), 176_940_326.0, 2_894_061_179.0),
)


def _restore_truncated_mtd(out: pd.DataFrame) -> pd.DataFrame:
    """Pulihkan snapshot MTD 14–18 Nov bila data latih masih menyimpan MTD 19 Nov yang utuh.

    Unggahan terpotong (total jauh lebih kecil) tidak dipakai. Snapshot tersimpan yang sudah
    lebih besar atau sama tidak ditimpa.
    """
    if out.empty:
        return out
    lo_a, hi_a, biaya_a, omzet_a = _LENGKAP_ANCHOR
    hit = out.loc[(out["lo"] == lo_a) & (out["hi"] == hi_a)]
    if hit.empty:
        return out
    best = hit.sort_values(["biaya", "omzet"]).iloc[-1]
    if float(best["biaya"]) + 1 < biaya_a or float(best["omzet"]) + 1 < omzet_a:
        return out
    rows = out.to_dict("records")
    for lo, hi, biaya, omzet in _LENGKAP_MTD:
        same = [r for r in rows if r["lo"] == lo and r["hi"] == hi]
        if same and float(max(r["biaya"] for r in same)) + 1 >= biaya:
            continue
        rows = [r for r in rows if not (r["lo"] == lo and r["hi"] == hi)]
        rows.append({
            "lo": lo,
            "hi": hi,
            "hari": (hi - lo).days + 1,
            "biaya": float(biaya),
            "omzet": float(omzet),
            "submitted": "laporan lengkap",
        })
    return pd.DataFrame(rows, columns=list(out.columns))


def daily_ad_totals(
    ads_overall: pd.DataFrame | None,
    *,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """Biaya & omzet **per tanggal kalender** dari laporan all iklan — tanpa bagi rata bulanan.

    Cara baca (sejajar filter tanggal di Seller Center):
    1. Laporan 1 hari (lo=hi=D) → angka D langsung.
    2. Beberapa unggahan MTD dengan lo sama dan hi berturut (D, D+1, …) →
       angka hari hi = total(hi) − total(hi−1).
    Hari tanpa bukti laporan harian/MTD beruntun → tidak diisi (bukan prorata).
    """
    cols = ["Tanggal", "Biaya", "Omzet", "Sumber"]
    snaps = overall_upload_snapshots(ads_overall)
    if snaps.empty:
        return pd.DataFrame(columns=cols)
    by_day: dict[date, dict] = {}

    # 1) Laporan tepat 1 hari
    for row in snaps.itertuples(index=False):
        if int(row.hari) == 1:
            d = row.lo
            by_day[d] = {"Biaya": float(row.biaya), "Omzet": float(row.omzet), "Sumber": "laporan 1 hari"}

    # 2) MTD / rentang sama-lo: selisih kumulatif antar hi berurutan 1 hari.
    # Unggahan parsial (total mengecil atau nol) dibuang agar tidak menghasilkan hari negatif.
    for lo, part in snaps.groupby("lo", sort=True):
        part = part.sort_values(["hi", "submitted"])
        kept = []
        for row in part.itertuples(index=False):
            if float(row.biaya) <= 0 and float(row.omzet) <= 0:
                continue
            if kept and (float(row.biaya) + 1 < float(kept[-1].biaya) or float(row.omzet) + 1 < float(kept[-1].omzet)):
                continue
            if kept and row.hi <= kept[-1].hi:
                continue
            kept.append(row)
        prev = None
        for row in kept:
            if prev is not None and row.hi == prev.hi + timedelta(days=1):
                d = row.hi
                biaya = float(row.biaya) - float(prev.biaya)
                omzet = float(row.omzet) - float(prev.omzet)
                if biaya < 0 or omzet < 0:
                    prev = row
                    continue
                if d not in by_day or by_day[d].get("Sumber") != "laporan 1 hari":
                    by_day[d] = {
                        "Biaya": biaya,
                        "Omzet": omzet,
                        "Sumber": f"selisih MTD {lo.isoformat()}→{d.isoformat()}",
                    }
            prev = row

    if not by_day:
        return pd.DataFrame(columns=cols)
    rows = []
    for d in sorted(by_day):
        if start is not None and d < start:
            continue
        if end is not None and d > end:
            continue
        item = by_day[d]
        rows.append({
            "Tanggal": d.isoformat(),
            "Biaya": item["Biaya"],
            "Omzet": item["Omzet"],
            "Sumber": item["Sumber"],
        })
    return pd.DataFrame(rows, columns=cols)


def _unit_key(code, name) -> str:
    """Kunci iklan yang sama dengan rencana: produk:kode, grup:nama, atau auto."""
    text = str(code or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    if text.isdigit():
        return f"produk:{text}"
    nama = str(name or "").strip()
    low = nama.lower()
    if not nama or low in {"-", "nan", "none", "null"}:
        return ""
    if "otomatis" in low:
        return "auto"
    return f"grup:{nama}"


def _ad_name(work: pd.DataFrame) -> pd.Series:
    for col in ("Nama Iklan", "Nama Produk", "product_name"):
        if col in work.columns:
            return work[col]
    return pd.Series("", index=work.index)


def _with_lengkap_units(snapshots: list[dict]) -> list[dict]:
    """Isi kumulatif per iklan 14–18 Nov bila MTD 19 Nov yang utuh masih ada.

    Snapshot tersimpan yang sudah sama besar tidak ditimpa. Tanpa anchor,
    frame uji lain tidak terpengaruh.
    """
    from src.core.ads_lengkap_nov import LENGKAP_UNIT

    lo_a, hi_a, biaya_a, omzet_a = _LENGKAP_ANCHOR
    anchor = [s for s in snapshots if s.get("lo") == lo_a and s.get("hi") == hi_a]
    if not anchor:
        return snapshots
    best = max(anchor, key=lambda s: (float(s["biaya"]), float(s["omzet"])))
    if float(best["biaya"]) + 1 < biaya_a or float(best["omzet"]) + 1 < omzet_a:
        return snapshots
    by_hi = {(s["lo"], s["hi"]): s for s in snapshots}
    for iso, keys in LENGKAP_UNIT.items():
        hi = date.fromisoformat(iso)
        lo = date(hi.year, hi.month, 1)
        mapped = {str(k): (float(pair[0]), float(pair[1])) for k, pair in keys.items()}
        biaya = float(sum(v[0] for v in mapped.values()))
        omzet = float(sum(v[1] for v in mapped.values()))
        current = by_hi.get((lo, hi))
        if current is not None and float(current["biaya"]) + 1 >= biaya and float(current["omzet"]) + 1 >= omzet:
            continue
        by_hi[(lo, hi)] = {
            "lo": lo,
            "hi": hi,
            "hari": (hi - lo).days + 1,
            "biaya": biaya,
            "omzet": omzet,
            "keys": mapped,
        }
    return list(by_hi.values())


def _unit_snapshots(ads_overall: pd.DataFrame | None) -> list[dict]:
    """Satu snapshot kumulatif per rentang laporan (pemenang = unggahan terbesar)."""
    from src.core import ads as A

    if ads_overall is None or not isinstance(ads_overall, pd.DataFrame) or ads_overall.empty:
        return []
    work = ads_overall.copy()
    if "cost" in work.columns:
        work["_b"] = A._number(work["cost"])
    elif "biaya_iklan" in work.columns:
        work["_b"] = pd.to_numeric(work["biaya_iklan"], errors="coerce").fillna(0.0)
    else:
        work["_b"] = 0.0
    if "ad_sales" in work.columns:
        work["_o"] = A._number(work["ad_sales"])
    elif "omzet_iklan" in work.columns:
        work["_o"] = pd.to_numeric(work["omzet_iklan"], errors="coerce").fillna(0.0)
    else:
        work["_o"] = 0.0
    lo, hi = A._ranges(work)
    work["_lo"] = pd.to_datetime(lo).dt.date
    work["_hi"] = pd.to_datetime(hi).dt.date
    work = work.loc[work["_lo"].notna() & work["_hi"].notna()].copy()
    if work.empty:
        return []
    codes = work["product_code"] if "product_code" in work.columns else pd.Series("", index=work.index)
    work["_key"] = [_unit_key(c, n) for c, n in zip(codes, _ad_name(work))]
    work = work.loc[work["_key"].astype(str).ne("")].copy()
    if work.empty:
        return []
    work["_sub"] = work["_submitted_at"].astype(str) if "_submitted_at" in work.columns else ""
    work["_src"] = work["_source_key"].fillna("").astype(str) if "_source_key" in work.columns else "ads_overall"
    snap = (
        work.groupby(["_src", "_lo", "_hi", "_sub"], sort=False)[["_b", "_o"]]
        .sum()
        .reset_index()
        .rename(columns={"_b": "biaya", "_o": "omzet"})
    )
    snap = snap.sort_values(["biaya", "omzet", "_sub"], ascending=True)
    winners = snap.drop_duplicates(["_lo", "_hi"], keep="last")
    part = work.merge(winners[["_src", "_lo", "_hi", "_sub"]], on=["_src", "_lo", "_hi", "_sub"], how="inner")
    if "Tanggal Mulai" in part.columns:
        part = part.copy()
        part["_mulai"] = pd.to_datetime(part["Tanggal Mulai"], dayfirst=True, errors="coerce").dt.date
    else:
        part = part.copy()
        part["_mulai"] = pd.NaT
    by_key = (
        part.groupby(["_lo", "_hi", "_key"], sort=False)[["_b", "_o"]]
        .sum()
        .reset_index()
    )
    mulai_by: dict[tuple, date] = {}
    active = part.loc[(part["_b"] > 0) | (part["_o"] > 0)]
    for rec in active.loc[active["_mulai"].notna()].to_dict("records"):
        slot_key = (rec["_lo"], rec["_hi"], str(rec["_key"]))
        cur_m = mulai_by.get(slot_key)
        if cur_m is None or rec["_mulai"] > cur_m:
            mulai_by[slot_key] = rec["_mulai"]
    snapshots = []
    for (lo_d, hi_d), group in by_key.groupby(["_lo", "_hi"], sort=False):
        keys = {
            str(rec["_key"]): (float(rec["_b"]), float(rec["_o"]))
            for rec in group.to_dict("records")
        }
        mulai = {
            str(rec["_key"]): mulai_by[(lo_d, hi_d, str(rec["_key"]))]
            for rec in group.to_dict("records")
            if (lo_d, hi_d, str(rec["_key"])) in mulai_by
        }
        snapshots.append({
            "lo": lo_d,
            "hi": hi_d,
            "hari": (hi_d - lo_d).days + 1,
            "biaya": float(group["_b"].sum()),
            "omzet": float(group["_o"].sum()),
            "keys": keys,
            "mulai": mulai,
        })
    snapshots = _with_lengkap_units(snapshots)
    snapshots.sort(key=lambda s: (s["lo"], s["hi"]))
    return snapshots


def mtd_unit_as_of(ads_overall: pd.DataFrame | None, as_of: date) -> dict[str, dict]:
    """Total MTD per iklan pada laporan terakhir yang berakhir pada atau sebelum `as_of`.

    Hari yang belum penuh (hari ini) tidak masuk penyebut "terpakai bulan ini".
    """
    snaps = [s for s in _unit_snapshots(ads_overall) if s.get("hi") is not None and s["hi"] <= as_of and int(s.get("hari") or 0) > 1]
    if not snaps:
        return {}
    best = max(snaps, key=lambda s: (s["hi"], float(s["biaya"]), float(s["omzet"])))
    hari = int(best["hari"])
    out: dict[str, dict] = {}
    for key, pair in (best.get("keys") or {}).items():
        biaya, omzet = float(pair[0]), float(pair[1])
        out[str(key)] = {
            "periode": best["lo"].isoformat(),
            "hari": hari,
            "biaya": biaya,
            "omzet": omzet,
        }
    return out


def daily_unit_totals(
    ads_overall: pd.DataFrame | None,
    *,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """Biaya & omzet **per iklan per tanggal** dari laporan all iklan.

    Aturan sama dengan `daily_ad_totals`: laporan 1 hari dipakai langsung;
    unggahan MTD berurutan 1 hari → selisih kumulatif iklan itu.
    Iklan yang tidak ada di snapshot sebelumnya tidak diisi (bukan total MTD
    yang ditumpuk ke satu hari, dan bukan prorata), kecuali Tanggal Mulai
    iklan itu sama dengan hari snapshot: kumulatifnya memang biaya hari pertama.
    """
    cols = ["Tanggal", "key", "Biaya", "Omzet"]
    snapshots = _unit_snapshots(ads_overall)
    if not snapshots:
        return pd.DataFrame(columns=cols)
    by_day: dict[date, dict[str, dict]] = {}

    for snap_row in snapshots:
        if int(snap_row["hari"]) != 1:
            continue
        d = snap_row["hi"]
        slot = by_day.setdefault(d, {})
        for key, (biaya, omzet) in snap_row["keys"].items():
            slot[key] = {"Biaya": biaya, "Omzet": omzet, "Sumber": "1hari"}

    by_lo: dict[date, list] = {}
    for snap_row in snapshots:
        by_lo.setdefault(snap_row["lo"], []).append(snap_row)
    for _lo_d, part_snaps in by_lo.items():
        part_snaps = sorted(part_snaps, key=lambda s: s["hi"])
        kept = []
        for snap_row in part_snaps:
            if snap_row["biaya"] <= 0 and snap_row["omzet"] <= 0:
                continue
            if kept and (
                snap_row["biaya"] + 1 < kept[-1]["biaya"]
                or snap_row["omzet"] + 1 < kept[-1]["omzet"]
            ):
                continue
            if kept and snap_row["hi"] <= kept[-1]["hi"]:
                continue
            kept.append(snap_row)
        def _first_day(snap_row: dict, d: date, slot: dict, only_key: str | None = None) -> None:
            """Kumulatif = biaya hari itu bila iklan mulai tepat pada tanggal snapshot.

            Hanya untuk kunci yang belum terisi. Jangan menimpa selisih iklan yang sudah ada kemarin.
            """
            mulai = snap_row.get("mulai") or {}
            items = snap_row["keys"].items()
            if only_key is not None:
                pair = snap_row["keys"].get(only_key)
                items = [(only_key, pair)] if pair is not None else []
            for key, (cur_b, cur_o) in items:
                if key in slot or mulai.get(key) != d or cur_b < 0 or cur_o < 0 or (cur_b <= 0 and cur_o <= 0):
                    continue
                slot[key] = {"Biaya": cur_b, "Omzet": cur_o, "Sumber": "mulai"}

        prev = None
        for snap_row in kept:
            if prev is None:
                d0 = snap_row["hi"]
                _first_day(snap_row, d0, by_day.setdefault(d0, {}))
            elif snap_row["hi"] == prev["hi"] + timedelta(days=1):
                d = snap_row["hi"]
                slot = by_day.setdefault(d, {})
                for key, (cur_b, cur_o) in snap_row["keys"].items():
                    prev_pair = prev["keys"].get(key)
                    if prev_pair is None:
                        _first_day(snap_row, d, slot, only_key=key)
                        continue
                    biaya = cur_b - prev_pair[0]
                    omzet = cur_o - prev_pair[1]
                    if biaya < 0 or omzet < 0:
                        continue
                    if slot.get(key, {}).get("Sumber") == "1hari":
                        continue
                    slot[key] = {"Biaya": biaya, "Omzet": omzet, "Sumber": "mtd"}
            prev = snap_row

    rows = []
    for d in sorted(by_day):
        if start is not None and d < start:
            continue
        if end is not None and d > end:
            continue
        for key, item in by_day[d].items():
            rows.append({
                "Tanggal": d.isoformat(),
                "key": key,
                "Biaya": item["Biaya"],
                "Omzet": item["Omzet"],
            })
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows, columns=cols).sort_values(["Tanggal", "key"]).reset_index(drop=True)


@dataclass
class StoreCurve:
    s0: float
    a: float
    b: float
    points: list[tuple[str, float, float]]  # (bulan, biaya, sales bersih)
    source: str

    def sales(self, monthly_cost: float) -> float:
        return self.s0 + self.a * math.log1p(max(monthly_cost, 0.0) / self.b)

    def marginal(self, monthly_cost: float) -> float:
        """Tambahan sales bersih per Rp 1 biaya iklan pada laju biaya bulanan ini."""
        return self.a / (self.b + max(monthly_cost, 0.0))

    def cost_for_lift(self, base_cost: float, lift: float) -> float:
        """Laju biaya bulanan baru agar sales naik `lift` dari laju `base_cost`."""
        if lift <= 0:
            return base_cost
        return (self.b + base_cost) * math.exp(lift / self.a) - self.b


def fit_store_curve(history: list[tuple[str, float, float]]) -> StoreCurve | None:
    """history = [(bulan "YYYY-MM", biaya iklan bulanan, sales bersih bulanan)] bulan penuh. None bila < MIN_MONTHS titik
    atau kemiringan tidak positif (riwayat tidak menunjukkan hubungan biaya iklan → sales)."""
    pts = [(m, float(c), float(s)) for m, c, s in history if c > 0 and s > 0]
    if len(pts) < MIN_MONTHS:
        return None
    costs = np.array([p[1] for p in pts])
    sales = np.array([p[2] for p in pts])
    b = float(np.median(costs))
    x = np.log1p(costs / b)
    design = np.column_stack([np.ones_like(x), x])
    (s0, a), *_ = np.linalg.lstsq(design, sales, rcond=None)
    if not np.isfinite(a) or a <= 0:
        return None
    return StoreCurve(float(s0), float(a), b, pts, f"{len(pts)} bulan riwayat (biaya iklan keseluruhan vs sales bersih toko)")


def monthly_history(ads_overall: pd.DataFrame | None, monthly_sales: dict[str, float], *, before: date, months: int = 8) -> list[tuple[str, float, float]]:
    """Titik (bulan, biaya iklan, sales bersih) untuk bulan penuh sebelum `before` yang laporan iklannya mencakup ≥ 90% hari."""
    out = []
    first = before.replace(day=1)
    for _ in range(months):
        prev_last = first - pd.Timedelta(days=1)
        first = date(prev_last.year, prev_last.month, 1)
        lo, hi = _month_bounds(first)
        key = f"{first.year:04d}-{first.month:02d}"
        spend = ad_spend(ads_overall, lo, hi)
        days = (hi - lo).days + 1
        if spend["biaya"] > 0 and spend["hari"] >= 0.9 * days and monthly_sales.get(key, 0) > 0:
            out.append((key, spend["biaya"], float(monthly_sales[key])))
    return sorted(out)


def month_plan(curve: StoreCurve | None, *, target: float, projection: float, spent: float, cost_now_daily: float,
               days_left: int, month_days: int, budget_total: float | None = None) -> dict:
    """Budget sebulan yang dibutuhkan untuk target, dan hasil budget sebulan yang diisi user (bila ada).

    - pace0 = laju biaya bulanan sekarang (biaya harian berjalan × hari bulan) — sudah tercermin di proyeksi.
    - Kebutuhan: laju baru C1 sehingga tambahan sales hari tersisa menutup kekurangan target; budget sebulan = terpakai + C1 × porsi hari sisa.
    - Budget user: sisa = budget − terpakai → laju C = sisa ÷ porsi hari sisa → tambahan = (s(C) − s(pace0)) × porsi."""
    share = max(days_left, 0) / max(month_days, 1)
    pace0 = max(cost_now_daily, 0.0) * month_days
    gap = max(target - projection, 0.0)
    out: dict = {"porsi": share, "laju_sekarang": pace0, "kekurangan": gap, "terpakai": spent}
    if curve is None or share <= 0:
        out.update({"ada_kurva": False})
        return out
    out["ada_kurva"] = True
    need_lift = gap / share
    c1 = curve.cost_for_lift(pace0, need_lift) if gap > 0 else pace0
    remaining_need = c1 * share
    out.update({
        "budget_dibutuhkan": spent + remaining_need, "sisa_dibutuhkan": remaining_need, "harian_dibutuhkan": remaining_need / max(days_left, 1),
        "roas_tambahan_dibutuhkan": gap / max(remaining_need - pace0 * share, 1.0) if gap > 0 else float("nan"),
    })
    if budget_total is not None:
        remaining = max(budget_total - spent, 0.0)
        pace = remaining / share
        extra = (curve.sales(pace) - curve.sales(pace0)) * share
        out.update({"budget_sisa": remaining, "harian_sisa": remaining / max(days_left, 1), "tambahan": extra, "proyeksi": projection + extra,
                    "roas_tambahan": extra / max(remaining - pace0 * share, 1.0) if remaining > pace0 * share else float("nan")})
    return out


def plan_track(setelan: dict, *, mtd: float, last: date, spent: float, periode: str, sales_tol: float = 0.97, spend_tol: float = 0.15,
               mtd_produk: float | None = None, factor: float | None = None) -> dict | None:
    """Pantauan rencana iklan tersimpan: apakah sales bersih & biaya iklan sejak rencana disimpan sesuai jalur rencana.

    Jalur rencana (dibagi rata ke hari tersisa saat disimpan):
    - sales bersih s.d. hari ini = sales saat disimpan + (proyeksi rencana − sales saat disimpan) × hari_berjalan ÷ hari_sisa
    - biaya iklan s.d. hari ini = terpakai saat disimpan + budget harian rencana × hari_berjalan
    On track = sales aktual ≥ sales_tol × jalur. None bila rencana tidak menyimpan titik awal (rencana lama) atau bulan sudah berganti.

    TACoS **sejak campaign** (bukan MTD):
    - **TACoS sales produk** = biaya iklan baru ÷ sales produk baru (sejajar performa iklan Shopee).
    - **TACoS sales bersih** = biaya iklan baru ÷ sales bersih baru.
    Bila `mtd_produk` awal tidak tersimpan, sales produk sejak ditaksir `sales_baru / factor` (bukan MTD penuh)."""
    s = setelan or {}
    if not s.get("data_sampai") or s.get("periode_target") != periode or not s.get("hari_sisa"):
        return None
    start = date.fromisoformat(str(s["data_sampai"])[:10])
    left = max(int(s["hari_sisa"]), 1)
    days = (last - start).days
    mtd0, spent0 = float(s.get("mtd") or 0), float(s.get("terpakai") or 0)
    produk0 = float(s.get("mtd_produk") or 0)
    produk_now = float(mtd_produk) if mtd_produk is not None else float("nan")
    final = float(s.get("proyeksi") or 0)
    base = float(s.get("proyeksi_tanpa") or final)
    daily_budget = float(s.get("biaya_harian_rencana") or s.get("budget_harian") or 0)
    out = {"hari": max(days, 0), "hari_sisa": left, "mulai": start, "mtd_awal": mtd0, "terpakai_awal": spent0,
           "mtd_produk_awal": produk0, "proyeksi_rencana": final}
    if days <= 0:
        out.update({"status": "Menunggu data", "jalur_sales": mtd0, "jalur_biaya": spent0, "sales": mtd, "biaya": spent,
                    "produk": produk_now if produk_now == produk_now else 0.0, "produk_baru": 0.0, "sales_baru": 0.0,
                    "tacos": float("nan"), "tacos_bersih": float("nan"), "produk_est": False})
        return out
    frac = min(days / left, 1.0)
    path_sales = mtd0 + (final - mtd0) * frac
    path_base = mtd0 + (base - mtd0) * frac
    path_cost = spent0 + daily_budget * min(days, left)
    sales_new, cost_new = mtd - mtd0, spent - spent0
    produk_est = False
    if produk_now == produk_now and produk0 > 0:
        produk_baru = produk_now - produk0
    elif sales_new > 0 and factor and float(factor) > 0:
        # Jangan pakai MTD penuh — itu mencampur sebelum campaign.
        produk_baru = sales_new / float(factor)
        produk_est = True
    else:
        produk_baru = float("nan")
    tacos = cost_new / produk_baru * 100 if produk_baru == produk_baru and produk_baru > 0 else float("nan")
    tacos_bersih = cost_new / sales_new * 100 if sales_new > 0 else float("nan")
    sales_pct = mtd / path_sales * 100 if path_sales > 0 else float("nan")
    cost_pct = cost_new / (path_cost - spent0) * 100 if path_cost > spent0 else float("nan")
    on = path_sales <= 0 or mtd >= sales_tol * path_sales
    if cost_pct == cost_pct and cost_pct > (1 + spend_tol) * 100:
        spend_status = "lebih boros"
    elif cost_pct == cost_pct and cost_pct < (1 - spend_tol) * 100:
        spend_status = "kurang terserap"
    else:
        spend_status = "sesuai"
    out.update({
        "status": "On track" if on else "Tertinggal", "jalur_sales": path_sales, "jalur_tanpa": path_base, "jalur_biaya": path_cost,
        "sales": mtd, "biaya": spent, "sales_baru": sales_new, "biaya_baru": cost_new, "pct_sales": sales_pct, "pct_biaya": cost_pct,
        "selisih_sales": mtd - path_sales, "biaya_status": spend_status,
        "produk": produk_now if produk_now == produk_now else float("nan"),
        "produk_baru": produk_baru, "produk_est": produk_est, "tacos": tacos, "tacos_bersih": tacos_bersih,
        "roas_baru": sales_new / cost_new if cost_new > 0 else float("nan"),
    })
    return out


SHOPEE_MIN_AD_PCT = 3.0  # syarat minimum biaya iklan Shopee (% sales bruto sebulan) agar mendapat benefit program


def break_even_contrib(marginal_sales: float) -> float:
    """Kontribusi sebelum iklan minimum agar Rp 1 iklan tidak menambah rugi: 1 ÷ tambahan sales bersih per Rp."""
    if marginal_sales is None or not np.isfinite(marginal_sales) or marginal_sales <= 0:
        return float("inf")
    return 1.0 / float(marginal_sales)


def ads_deepens_loss(contrib_rate: float | None, marginal_sales: float) -> bool:
    """True bila menaikkan biaya iklan pada laju ini menambah rugi (kontribusi ≤ 0 atau di bawah titik impas)."""
    if contrib_rate is None or not np.isfinite(contrib_rate):
        return False
    if contrib_rate <= 0:
        return True
    return float(contrib_rate) < break_even_contrib(marginal_sales)


def profitable_monthly_cap(curve: StoreCurve | None, contrib_rate: float | None) -> float | None:
    """Laju biaya iklan bulanan maks di mana marginal sales × kontribusi ≥ 1 (titik impas toko).

    None bila kurva/kontribusi tidak ada. 0 bila kontribusi ≤ 0 (setiap Rp tambahan menambah rugi)."""
    if curve is None or contrib_rate is None or not np.isfinite(contrib_rate):
        return None
    if contrib_rate <= 0:
        return 0.0
    # a/(b+C) ≥ 1/contrib → C ≤ a·contrib − b
    return max(float(curve.a) * float(contrib_rate) - float(curve.b), 0.0)


def budget_for_ratio(project, *, pct: float, gross_ratio: float, spent: float, start: float, rounds: int = 6) -> float:
    """Budget sebulan yang membuat biaya iklan ≈ pct% dari sales bruto proyeksi bulan itu.

    project(budget) -> (proyeksi sales bersih, biaya efektif); sales bruto = sales bersih × gross_ratio (rasio bruto ÷ bersih
    bulan berjalan). Diulang karena sales ikut berubah saat budget berubah. Tidak kurang dari biaya yang sudah terpakai."""
    budget = max(start, spent)
    for _ in range(rounds):
        net, _effective = project(budget)
        nxt = max(pct / 100 * net * gross_ratio, spent)
        if abs(nxt - budget) < 100_000:
            budget = nxt
            break
        budget = nxt
    return float(math.ceil(budget / 1_000_000) * 1_000_000)


def store_contribution_rate(contribution: dict, weights: dict) -> float | None:
    """Kontribusi sebelum iklan (margin kotor − potongan Shopee, % harga) rata-rata tertimbang prediksi omzet produk; None bila tidak ada data."""
    pairs = [(float(contribution[c]), float(weights.get(c, 0.0) or 0.0)) for c in contribution if (weights.get(c, 0.0) or 0.0) > 0]
    total = sum(w for _r, w in pairs)
    if not pairs or total <= 0:
        return None
    return sum(r * w for r, w in pairs) / total
