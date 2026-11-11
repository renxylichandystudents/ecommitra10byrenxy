"""Atribusi laporan iklan Shopee ke SKU, dengan "Semua Laporan Iklan" (all iklan) sebagai acuan total.

Struktur laporan (dicek dengan ekspor 01–07/11/2026):
- All iklan: satu baris = satu pengaturan iklan. Baris "Iklan Produk Otomatis" dan setiap grup iklan
  tidak punya Kode Produk; iklan satu produk punya Kode Produk. Jumlah semua baris = total toko.
- Iklan produk otomatis: baris ringkasan "Iklan Produk Otomatis" (tanpa kode) + rincian per produk.
- Grup iklan: per grup satu baris kepala (tanpa kode) + rincian produk anggota grup.
- Rincian per produk = produk otomatis + produk grup + iklan satu produk di all iklan; jumlahnya sama
  dengan total all iklan (selisih hanya karena jam unduh berbeda).

Aturan hitung:
- Total biaya/omzet/ROAS = all iklan pada periode yang diminta. Tanpa all iklan, total = jumlah rincian.
- Periode: setiap laporan punya rentang (mis. 01/11–07/11). Nilai laporan dibagi rata per hari lalu
  diambil sesuai irisan dengan jendela yang diminta (prorata), jadi laporan bulanan dan mingguan bisa
  dipakai bersama tanpa dobel. Laporan dari menu yang sama yang rentangnya tumpang tindih → yang
  diunggah paling akhir dipakai.
- Tanpa rentang: jendela 30 hari yang berakhir di hari terakhir laporan iklan.
- Biaya/omzet satu Kode Produk dibagi ke SKU variannya proporsional sales varian (sama rata bila
  belum ada sales). Omzet memakai angka Shopee apa adanya (sama dengan Seller Centre).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.core.schemas import clean_code

METRICS = {
    "views": "dilihat",
    "clicks": "klik",
    "cost": "biaya_iklan",
    "ad_sales": "omzet_iklan",
    "products_sold": "terjual_iklan",
    "cart_adds": "keranjang",
}
SKU_COLUMNS = ["sku", *METRICS.values(), "omzet_iklan_shopee", "sales_sku", "qty_sku", "hari_iklan", "biaya_harian"]
SUMMARY_CODES = {"", "-", "nan", "none", "null"}
OVERALL = "ads_overall"
DEFAULT_WINDOW_DAYS = 30
PERIOD_TEXT = "Periode laporan (teks)"


@dataclass
class AdAttribution:
    per_sku: pd.DataFrame
    start: pd.Timestamp | None = None
    end: pd.Timestamp | None = None
    file_cost: float = 0.0
    file_sales: float = 0.0
    unmapped_cost: float = 0.0
    unmapped_codes: int = 0
    notes: list[str] = field(default_factory=list)
    overall_cost: float = 0.0
    overall_sales: float = 0.0
    has_overall: bool = False
    days: int = 0

    @property
    def cost(self) -> float:
        """Biaya iklan yang terpetakan ke SKU (rincian per produk)."""
        return float(self.per_sku["biaya_iklan"].sum()) if not self.per_sku.empty else 0.0

    @property
    def sales(self) -> float:
        return float(self.per_sku["omzet_iklan"].sum()) if not self.per_sku.empty else 0.0

    @property
    def total_cost(self) -> float:
        """Acuan: all iklan bila ada, selain itu jumlah rincian laporan."""
        return self.overall_cost if self.has_overall else self.file_cost

    @property
    def total_sales(self) -> float:
        return self.overall_sales if self.has_overall else self.file_sales


def _codes(values: pd.Series) -> pd.Series:
    return clean_code(values).fillna("").astype(str).str.strip()


def _number(values: pd.Series) -> pd.Series:
    """Angka laporan iklan: "5800468", "17366.67", "4.16%", "-" → float (format Indonesia ikut terbaca)."""
    if pd.api.types.is_numeric_dtype(values):
        return pd.to_numeric(values, errors="coerce").fillna(0.0)
    from src.ingest import _parse_number_token

    text = values.astype(str).str.replace("%", "", regex=False)
    direct = pd.to_numeric(text, errors="coerce")
    missing = direct.isna() & text.str.strip().ne("") & ~text.str.strip().isin({"-", "nan", "None"})
    if missing.any():
        direct.loc[missing] = text.loc[missing].map(_parse_number_token)
    return direct.fillna(0.0)


def _ranges(ads: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Awal & akhir periode tiap baris: dari teks "01/11/2026 - 07/11/2026", atau satu bulan penuh."""
    start = pd.to_datetime(ads["period"], errors="coerce", format="mixed") if "period" in ads.columns else pd.Series(pd.NaT, index=ads.index)
    start = start.dt.normalize()
    end = pd.Series(pd.NaT, index=ads.index, dtype="datetime64[ns]")
    if PERIOD_TEXT in ads.columns:
        parts = ads[PERIOD_TEXT].astype(str).str.split(" - ", n=1, expand=True)
        if parts.shape[1] == 2:
            first = pd.to_datetime(parts[0].str.strip(), dayfirst=True, errors="coerce")
            last = pd.to_datetime(parts[1].str.strip(), dayfirst=True, errors="coerce")
            start = start.fillna(first)
            end = last.where(last.notna(), end)
    month_end = (start + pd.offsets.MonthEnd(0)).dt.normalize()
    end = end.fillna(month_end)
    end = end.where(end >= start, start)
    return start, end


def _drop_overlapping_reports(ads: pd.DataFrame) -> pd.DataFrame:
    """Per menu upload: hari yang sudah dicakup laporan yang lebih baru tidak dihitung dua kali.

    Laporan lama yang hanya sebagian tumpang tindih tetap dipakai untuk hari yang belum dicakup
    (mis. laporan 1 Okt–1 Nov + laporan baru 1–8 Nov → laporan Oktober tetap dipakai untuk 1–31 Okt).
    Kolom _ulo/_uhi = rentang yang dipakai; _lo/_hi tetap rentang asli (penyebut prorata)."""
    if ads.empty:
        return ads
    stamp = ads["_submitted_at"].astype(str) if "_submitted_at" in ads.columns else pd.Series("", index=ads.index)
    keys = pd.DataFrame({"src": ads["_src"], "lo": ads["_lo"], "hi": ads["_hi"], "at": stamp})
    reports = keys.drop_duplicates().sort_values(["at", "hi", "lo"], ascending=False)
    covered: dict[str, set] = {}
    keep_rows = []
    for row in reports.itertuples(index=False):
        taken = covered.setdefault(row.src, set())
        days = pd.date_range(row.lo, row.hi, freq="D")
        free = [day for day in days if day not in taken]
        if not free:
            continue
        # Rentang bebas terpanjang yang bersambung (tumpang tindih biasanya di tepi laporan).
        best, current = [], [free[0]]
        for day in free[1:]:
            if day - current[-1] == pd.Timedelta(days=1):
                current.append(day)
            else:
                best = current if len(current) > len(best) else best
                current = [day]
        best = current if len(current) > len(best) else best
        taken.update(best)
        keep_rows.append((row.src, row.lo, row.hi, row.at, best[0], best[-1]))
    keep = pd.DataFrame(keep_rows, columns=["src", "lo", "hi", "at", "_ulo", "_uhi"])
    merged = keys.reset_index().merge(keep, on=["src", "lo", "hi", "at"], how="inner").set_index("index")
    out = ads.loc[ads.index.isin(merged.index)].copy()
    out["_ulo"] = merged.loc[out.index, "_ulo"]
    out["_uhi"] = merged.loc[out.index, "_uhi"]
    return out


def _prepare(ads_frames: list[pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for position, frame in enumerate(ads_frames):
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            continue
        work = frame.copy()
        if "_source_key" in work.columns:
            work["_src"] = work["_source_key"].fillna("").astype(str).replace("", f"laporan-{position}")
        else:
            work["_src"] = f"laporan-{position}"
        frames.append(work)
    if not frames:
        return pd.DataFrame()
    ads = pd.concat(frames, ignore_index=True)
    ads["product_code"] = _codes(ads["product_code"]) if "product_code" in ads.columns else ""
    for source, target in METRICS.items():
        ads[target] = _number(ads[source]) if source in ads.columns else 0.0
    ads["_lo"], ads["_hi"] = _ranges(ads)
    ads = ads.loc[ads["_lo"].notna()] if ads["_lo"].notna().any() else ads
    if ads["_lo"].notna().any():
        ads = _drop_overlapping_reports(ads)
    if "_ulo" not in ads.columns:
        ads["_ulo"], ads["_uhi"] = ads["_lo"], ads["_hi"]
    return ads


def _window(ads: pd.DataFrame, start, end) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    lo = pd.Timestamp(start).normalize() if start is not None else None
    hi = pd.Timestamp(end).normalize() if end is not None else None
    if ads.empty or ads["_lo"].isna().all():
        return lo, hi
    if hi is None:
        hi = ads["_hi"].max() if lo is None else max(lo, ads["_hi"].max())
    if lo is None:
        lo = hi - pd.Timedelta(days=DEFAULT_WINDOW_DAYS - 1)
    return lo, hi


def _weight(ads: pd.DataFrame, lo, hi) -> pd.Series:
    """Porsi hari laporan yang jatuh di jendela [lo, hi]."""
    if lo is None or hi is None or ads["_lo"].isna().all():
        return pd.Series(1.0, index=ads.index)
    days = (ads["_hi"] - ads["_lo"]).dt.days + 1
    use_lo = ads["_ulo"] if "_ulo" in ads.columns else ads["_lo"]
    use_hi = ads["_uhi"] if "_uhi" in ads.columns else ads["_hi"]
    first = use_lo.where(use_lo > lo, lo)
    last = use_hi.where(use_hi < hi, hi)
    overlap = ((last - first).dt.days + 1).clip(lower=0)
    return (overlap / days.where(days > 0, 1)).fillna(0.0)


def _covered_days(ads: pd.DataFrame, lo, hi) -> int:
    if ads.empty or lo is None or hi is None or ads["_lo"].isna().all():
        return 0
    days: set[pd.Timestamp] = set()
    cols = ["_ulo", "_uhi"] if "_ulo" in ads.columns else ["_lo", "_hi"]
    for a, b in ads[cols].drop_duplicates().itertuples(index=False):
        a, b = max(a, lo), min(b, hi)
        if a <= b:
            days.update(pd.date_range(a, b, freq="D"))
    return len(days)


def ad_report_rows(ads_frames: list[pd.DataFrame], *, start=None, end=None) -> tuple[pd.DataFrame, pd.Timestamp | None, pd.Timestamp | None, int]:
    """Semua baris laporan (termasuk ringkasan) yang sudah diprorata ke jendela. (rows, lo, hi, hari)."""
    ads = _prepare(ads_frames)
    if ads.empty:
        return pd.DataFrame(columns=["product_code", "_src", *METRICS.values()]), None, None, 0
    lo, hi = _window(ads, start, end)
    weight = _weight(ads, lo, hi)
    ads = ads.loc[weight > 0].copy()
    weight = weight.loc[ads.index]
    for column in METRICS.values():
        ads[column] = ads[column] * weight
    return ads, lo, hi, _covered_days(ads, lo, hi)


def ad_product_rows(ads_frames: list[pd.DataFrame], *, start=None, end=None) -> tuple[pd.DataFrame, pd.Timestamp | None, pd.Timestamp | None]:
    """Baris iklan level produk (punya Kode Produk) pada jendela, sudah diprorata."""
    rows, lo, hi, _days = ad_report_rows(ads_frames, start=start, end=end)
    if rows.empty:
        return pd.DataFrame(columns=["product_code", *METRICS.values()]), lo, hi
    detail = rows.loc[~rows["product_code"].str.lower().isin(SUMMARY_CODES)]
    return detail[["product_code", *METRICS.values()]], lo, hi


def _variant_pairs(stock_frame: pd.DataFrame | None) -> pd.DataFrame:
    if stock_frame is None or stock_frame.empty or not {"product_code", "sku"} <= set(stock_frame.columns):
        return pd.DataFrame(columns=["product_code", "sku"])
    stock = stock_frame
    if "_submitted_at" in stock.columns:
        stamp = stock["_submitted_at"].astype(str)
        stock = stock.loc[stamp.eq(stamp.max())]
    pairs = pd.DataFrame({"product_code": _codes(stock["product_code"]), "sku": _codes(stock["sku"])})
    return pairs.loc[pairs["product_code"].ne("") & pairs["sku"].ne("")].drop_duplicates()


def _sku_sales(orders: pd.DataFrame | None, lo, hi) -> pd.DataFrame:
    if orders is None or orders.empty or "sku" not in orders.columns:
        return pd.DataFrame(columns=["sku", "sales_sku", "qty_sku"])
    work = orders
    if "order_time" in work.columns and (lo is not None or hi is not None):
        day = pd.to_datetime(work["order_time"], errors="coerce").dt.normalize()
        keep = pd.Series(True, index=work.index)
        if lo is not None:
            keep &= day >= lo
        if hi is not None:
            keep &= day <= hi
        work = work.loc[keep]
    frame = pd.DataFrame(
        {
            "sku": _codes(work["sku"]),
            "sales_sku": pd.to_numeric(work.get("sales", 0.0), errors="coerce").fillna(0.0),
            "qty_sku": pd.to_numeric(work.get("qty", 0.0), errors="coerce").fillna(0.0),
        }
    )
    return frame.groupby("sku", as_index=False)[["sales_sku", "qty_sku"]].sum()


def attribute_ads(
    ads_frames: list[pd.DataFrame],
    stock_frame: pd.DataFrame | None,
    *,
    orders: pd.DataFrame | None = None,
    start=None,
    end=None,
) -> AdAttribution:
    rows, lo, hi, days = ad_report_rows(ads_frames, start=start, end=end)
    empty = pd.DataFrame(columns=SKU_COLUMNS)
    if rows.empty:
        return AdAttribution(empty, lo, hi)
    summary = rows["product_code"].str.lower().isin(SUMMARY_CODES)
    overall_rows = rows.loc[rows["_src"].eq(OVERALL)]
    has_overall = not overall_rows.empty
    overall_cost = float(overall_rows["biaya_iklan"].sum())
    overall_sales = float(overall_rows["omzet_iklan"].sum())
    detail = rows.loc[~summary]
    per_code = detail.groupby("product_code", as_index=False)[list(METRICS.values())].sum()
    file_cost = float(per_code["biaya_iklan"].sum())
    file_sales = float(per_code["omzet_iklan"].sum())
    pairs = _variant_pairs(stock_frame)
    base = dict(start=lo, end=hi, file_cost=file_cost, file_sales=file_sales, overall_cost=overall_cost, overall_sales=overall_sales, has_overall=has_overall, days=days)
    if pairs.empty or per_code.empty:
        return AdAttribution(empty, unmapped_cost=file_cost, unmapped_codes=int(len(per_code)), **base)
    sales = _sku_sales(orders, lo, hi)
    pairs = pairs.merge(sales, on="sku", how="left")
    for column in ("sales_sku", "qty_sku"):
        pairs[column] = pd.to_numeric(pairs[column], errors="coerce").fillna(0.0)
    code_sales = pairs.groupby("product_code")["sales_sku"].transform("sum")
    code_count = pairs.groupby("product_code")["sku"].transform("count")
    pairs["share"] = np.where(code_sales > 0, pairs["sales_sku"] / code_sales.where(code_sales > 0, 1.0), 1.0 / code_count)
    merged = pairs.merge(per_code, on="product_code", how="inner")
    for column in METRICS.values():
        merged[column] = merged[column] * merged["share"]
    per_sku = merged.groupby("sku", as_index=False).agg(
        **{column: (column, "sum") for column in METRICS.values()},
        sales_sku=("sales_sku", "first"),
        qty_sku=("qty_sku", "first"),
    )
    per_sku["omzet_iklan_shopee"] = per_sku["omzet_iklan"]
    per_sku["hari_iklan"] = days
    per_sku["biaya_harian"] = per_sku["biaya_iklan"] / days if days > 0 else per_sku["biaya_iklan"] / DEFAULT_WINDOW_DAYS
    mapped = set(merged["product_code"])
    unmapped = per_code.loc[~per_code["product_code"].isin(mapped)]
    return AdAttribution(per_sku[SKU_COLUMNS], unmapped_cost=float(unmapped["biaya_iklan"].sum()), unmapped_codes=int(len(unmapped)), **base)


def ad_history(ads_frames: list[pd.DataFrame], stock_frame: pd.DataFrame | None, *, months: int = 6) -> pd.DataFrame:
    """Riwayat iklan per SKU per bulan (biaya, omzet, ROAS) dari semua laporan tersimpan."""
    ads = _prepare(ads_frames)
    if ads.empty or ads["_lo"].isna().all():
        return pd.DataFrame(columns=["sku", "bulan", "biaya_iklan", "omzet_iklan", "roas"])
    last = ads["_hi"].max().to_period("M")
    out = []
    for step in range(months):
        month = last - step
        lo, hi = month.start_time.normalize(), month.end_time.normalize()
        result = attribute_ads(ads_frames, stock_frame, start=lo, end=hi)
        if result.per_sku.empty:
            continue
        part = result.per_sku[["sku", "biaya_iklan", "omzet_iklan"]].copy()
        part["bulan"] = str(month)
        out.append(part)
    if not out:
        return pd.DataFrame(columns=["sku", "bulan", "biaya_iklan", "omzet_iklan", "roas"])
    frame = pd.concat(out, ignore_index=True)
    frame["roas"] = np.where(frame["biaya_iklan"] > 0, frame["omzet_iklan"] / frame["biaya_iklan"].where(frame["biaya_iklan"] > 0, 1), np.nan)
    return frame


def ad_validation(result: AdAttribution, total_sales: float) -> tuple[list[str], list[str]]:
    """(peringatan, catatan): kecocokan rincian per produk dengan all iklan dan cara hitung."""
    from src.utils.format import persen, rupiah

    issues: list[str] = []
    notes: list[str] = []
    if result.per_sku.empty and not result.has_overall:
        return issues, notes
    if result.has_overall:
        gap = result.overall_cost - result.file_cost
        if abs(gap) > max(1000.0, result.overall_cost * 0.005):
            issues.append(
                f"Total biaya all iklan {rupiah(result.overall_cost)}, sedangkan rincian per produk (otomatis + grup + iklan satu produk) "
                f"{rupiah(result.file_cost)}: selisih {rupiah(gap)}. Unggah laporan iklan otomatis dan grup untuk periode yang sama agar terinci."
            )
    if result.unmapped_cost > max(1000.0, result.file_cost * 0.005):
        issues.append(
            f"{rupiah(result.unmapped_cost)} biaya iklan dari {result.unmapped_codes} kode produk belum ada di Data stok Site 10037, "
            "jadi belum masuk ke ROAS per SKU."
        )
    share = result.total_sales / total_sales * 100 if total_sales > 0 else np.nan
    if np.isfinite(share) and share > 100:
        notes.append(
            f"Omzet iklan Shopee {rupiah(result.total_sales)} = {persen(share)} dari sales produk bersih: definisi Shopee menghitung semua belanja "
            "pembeli setelah klik iklan (termasuk produk lain dan pesanan yang kemudian batal)."
        )
    return issues, notes


HISTORY_DAYS = 90
RECENT_WEIGHT = 0.6


def roas_estimate(row, default: float) -> tuple[float, str]:
    """ROAS untuk perencanaan: 60% ROAS 30 hari terakhir + 40% ROAS 90 hari (riwayat iklan), default bila belum pernah beriklan."""
    def ratio(sales_key: str, cost_key: str) -> float | None:
        cost = float(row.get(cost_key, 0) or 0)
        return float(row.get(sales_key, 0) or 0) / cost if cost > 0 else None

    recent = ratio("omzet_iklan", "biaya_iklan")
    history = ratio("omzet_iklan_90", "biaya_iklan_90")
    if recent is not None and history is not None:
        return RECENT_WEIGHT * recent + (1 - RECENT_WEIGHT) * history, "30 & 90 hari"
    if recent is not None:
        return recent, "30 hari"
    if history is not None:
        return history, "90 hari"
    return float(default), "default"
