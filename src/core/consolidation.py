from __future__ import annotations

import numpy as np
import pandas as pd

from src.core.inventory import snapshot_time
from src.core.schemas import SOURCE_SPECS, find_columns, validation_report
from src.core.storage import LocalDataStore
from src.utils.format import tanggal


def _clean_key(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def _date_range(frame: pd.DataFrame, fields: tuple[str, ...]) -> str:
    for field in fields:
        if field not in frame.columns:
            continue
        values = frame[field]
        iso = values.astype(str).str.match(r"^\d{4}-\d{2}-\d{2}")
        # Tanggal tersimpan ISO (2026-11-01) tidak boleh dibaca dayfirst (jadi 11 Jan); teks laporan dd/mm/yyyy tetap dayfirst.
        dates = pd.to_datetime(values.where(iso), errors="coerce", format="mixed").fillna(pd.to_datetime(values.where(~iso), errors="coerce", dayfirst=True))
        if dates.notna().any():
            return f"{tanggal(dates.min())} – {tanggal(dates.max())}"
    return "-"


def _shopee_header(spec, name: str) -> str:
    """Nama kolom internal (order_id) → nama kolom di laporan Shopee (No. Pesanan) untuk tampilan."""
    aliases = spec.aliases.get(name) or ()
    if not aliases:
        return name
    label = " ".join(word.capitalize() if not word.isupper() else word for word in str(aliases[0]).split())
    for short in ("Sku", "Id", "Roas", "Ctr", "Gmv", "Dc"):
        label = label.replace(short, short.upper()) if label.split().count(short) else label
    return label


def _source_summary_row(source_key: str, frame: pd.DataFrame) -> dict[str, object]:
    spec = SOURCE_SPECS[source_key]
    report = validation_report(frame, spec)
    return {
        "Sumber": spec.label,
        "Status": report["status"],
        "Cakupan tanggal": _date_range(frame, spec.date_fields),
        "Jumlah baris": int(len(frame)),
        "Kolom wajib terbaca": ", ".join(_shopee_header(spec, name) for name in report["found_required"]) or "-",
        "Kolom wajib hilang": ", ".join(_shopee_header(spec, name) for name in report["missing_required"]) or "-",
        "Kegunaan": spec.utility,
    }


def consolidation_summary(store: LocalDataStore) -> tuple[pd.DataFrame, dict[str, float | int]]:
    frames = {key: store.read_source(key) for key in SOURCE_SPECS}
    rows = [_source_summary_row(key, frame) for key, frame in frames.items()]
    metrics = {
        "sku_transaksi_cocok_stok_pct": _transaction_stock_match(frames["transactions"], frames["stock"]),
        "produk_iklan_terpetakan_sku_pct": _ads_mapping_match(frames),
        "snapshot_stok": store.snapshot_count(),
        "sku_transaksi": _nunique_nonblank(frames["transactions"], "sku"),
        "sku_stok": _nunique_nonblank(frames["stock"], "sku"),
    }
    return pd.DataFrame(rows), metrics


def _nunique_nonblank(frame: pd.DataFrame, column: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    values = _clean_key(frame[column])
    return int(values[values.ne("")].nunique())


def _transaction_stock_match(transactions: pd.DataFrame, stock: pd.DataFrame) -> float:
    if transactions.empty or stock.empty or "sku" not in transactions.columns or "sku" not in stock.columns:
        return 0.0
    tx = set(_clean_key(transactions["sku"]))
    st = set(_clean_key(stock["sku"]))
    tx.discard("")
    st.discard("")
    if not tx:
        return 0.0
    return round(len(tx & st) / len(tx) * 100, 2)


def _product_code_to_sku(stock: pd.DataFrame) -> dict[str, str]:
    if stock.empty:
        return {}
    mapping = find_columns(stock.columns, SOURCE_SPECS["stock"])
    code_col = mapping.get("product_code", "product_code")
    sku_col = mapping.get("sku", "sku")
    if code_col not in stock.columns or sku_col not in stock.columns:
        return {}
    pairs = stock[[code_col, sku_col]].dropna().copy()
    pairs[code_col] = _clean_key(pairs[code_col])
    pairs[sku_col] = _clean_key(pairs[sku_col])
    pairs = pairs.loc[pairs[code_col].ne("") & pairs[sku_col].ne("")]
    return dict(zip(pairs[code_col], pairs[sku_col]))


def _ads_mapping_match(frames: dict[str, pd.DataFrame]) -> float:
    code_to_sku = _product_code_to_sku(frames.get("stock", pd.DataFrame()))
    if not code_to_sku:
        return 0.0
    codes: set[str] = set()
    for key in ("ads_auto", "ads_group", "ads_overall"):
        frame = frames.get(key, pd.DataFrame())
        if frame.empty or "product_code" not in frame.columns:
            continue
        values = _clean_key(frame["product_code"])
        codes |= set(values[~values.str.lower().isin({"", "-", "nan", "none"})])
    # Satu Kode Produk dihitung sekali walau muncul di beberapa laporan (otomatis, grup, all iklan).
    if not codes:
        return 0.0
    return round(len(codes & set(code_to_sku)) / len(codes) * 100, 2)


def latest_stock_frame(store: LocalDataStore) -> pd.DataFrame:
    stock = store.read_source("stock")
    if stock.empty or "_submitted_at" not in stock.columns:
        return stock
    latest = str(stock["_submitted_at"].max())
    return stock.loc[stock["_submitted_at"].astype(str).eq(latest)].copy()


def stock_zero_streaks(store: LocalDataStore) -> pd.DataFrame:
    stock = store.read_source("stock")
    if stock.empty or not {"sku", "stock_dc_cikupa", "_submitted_at"} <= set(stock.columns):
        return pd.DataFrame(columns=["sku", "zero_since", "snapshots_zero"])
    work = stock.copy()
    work["_submitted_at"] = snapshot_time(work["_submitted_at"])
    work["sku"] = _clean_key(work["sku"])
    work["stock_dc_cikupa"] = pd.to_numeric(work["stock_dc_cikupa"], errors="coerce").fillna(0)
    work = work.dropna(subset=["_submitted_at"]).sort_values(["sku", "_submitted_at"])
    rows: list[dict[str, object]] = []
    for sku, group in work.groupby("sku", sort=False):
        if not sku:
            continue
        streak = group.loc[group["stock_dc_cikupa"].le(0)]
        if streak.empty or group.iloc[-1]["stock_dc_cikupa"] > 0:
            continue
        # Ambil rangkaian nol terakhir, berhenti saat snapshot sebelumnya stoknya positif.
        latest_zero = []
        for _, row in group.iloc[::-1].iterrows():
            if float(row["stock_dc_cikupa"]) > 0:
                break
            latest_zero.append(row)
        if not latest_zero:
            continue
        zero_since = min(pd.Timestamp(row["_submitted_at"]) for row in latest_zero)
        rows.append({"sku": sku, "zero_since": zero_since, "snapshots_zero": len(latest_zero)})
    return pd.DataFrame(rows)



def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    text = frame[column].astype(str).str.replace(r"[^\d,.\-]", "", regex=True)
    # Format Indonesia "1.234.567,8" → 1234567.8; angka biasa tetap.
    indo = text.str.contains(r"\.\d{3}(?:[.,]|$)", regex=True) | text.str.contains(",", regex=False)
    text = text.where(~indo, text.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(text, errors="coerce").fillna(0.0)


def _unsold_active(stock: pd.DataFrame, sold: set[str], dc_qty: dict[str, pd.Series], tx_start, ref) -> pd.DataFrame:
    """SKU di snapshot Data stok terbaru (listing aktif) yang tidak pernah muncul di Data transaksi.

    Umur tidak terjual dihitung dari awal data transaksi; SKU yang baru muncul di Data stok setelah unggahan
    stok pertama (listing baru) dihitung dari tanggal kemunculannya.
    """
    if stock.empty or "sku" not in stock.columns:
        return pd.DataFrame()
    work = stock.copy()
    work["sku"] = _clean_key(work["sku"])
    work = work.loc[work["sku"].ne("")]
    if "_submitted_at" in work.columns:
        work["_snap"] = snapshot_time(work["_submitted_at"].astype(str))
        latest = work.loc[work["_submitted_at"].astype(str).eq(str(work["_submitted_at"].astype(str).max()))]
        first_upload = work["_snap"].min()
        first_seen = work.groupby("sku")["_snap"].min()
    else:
        latest, first_upload, first_seen = work, pd.NaT, pd.Series(dtype="datetime64[ns]")
    latest = latest.loc[~latest["sku"].isin(sold)].drop_duplicates("sku", keep="last")
    if latest.empty:
        return pd.DataFrame()
    start = pd.Timestamp(tx_start).normalize() if tx_start is not None and pd.notna(tx_start) else pd.NaT
    seen = latest["sku"].map(first_seen).dt.normalize()
    is_new = seen.notna() & pd.notna(first_upload) & seen.gt(pd.Timestamp(first_upload).normalize())
    since = seen.where(is_new | pd.isna(start), start)
    end = pd.Timestamp(ref).normalize() if ref is not None and pd.notna(ref) else pd.NaT
    days = (end - since).dt.days.clip(lower=0) if pd.notna(end) else pd.Series(np.nan, index=latest.index)
    stok_10037 = _num(latest, "stock_dc_cikupa")
    table = pd.DataFrame(
        {
            "SKU": latest["sku"],
            "Produk": latest["product_name"].astype(str) if "product_name" in latest.columns else "",
            "Variasi": latest["variation"].fillna("").astype(str).replace({"nan": "", "-": ""}) if "variation" in latest.columns else "",
            "Stok Site 10037": stok_10037,
            **{f"Stok Site {code}": latest["sku"].map(qty).fillna(0.0) if len(qty) else 0.0 for code, qty in sorted(dc_qty.items())},
            "Tidak terjual sejak": [
                "-" if pd.isna(d) else (f"{tanggal(d)} (listing baru)" if new else f"≤ {tanggal(d)} (awal data transaksi)")
                for d, new in zip(since, is_new)
            ],
            "Umur tidak terjual (hari)": days,
        }
    )
    stock_cols = [c for c in table.columns if c.startswith("Stok Site")]
    table["_total"] = table[stock_cols].sum(axis=1)
    table = table.sort_values(["_total", "Umur tidak terjual (hari)"], ascending=False).drop(columns="_total")
    if not table["Variasi"].astype(str).str.strip().ne("").any():
        table = table.drop(columns="Variasi")
    return table.reset_index(drop=True)


def match_diagnostics(store: LocalDataStore, today=None) -> dict[str, object]:
    """Rincian tiga angka konsolidasi: SKU yang tidak cocok, kode iklan yang tidak terpetakan, dan daftar snapshot.

    Persentase di kartu dihitung per kode unik; rincian ini menambahkan bobot QTY/Sales/biaya iklan,
    kapan terakhir terjual, dan apakah kode itu ada di stok Site 10062/10036.
    """
    from src.core.dc_stock import DC_SITES, latest_site_stock

    tx = store.read_source("transactions")
    stock = store.read_source("stock")
    out: dict[str, object] = {}
    dc_skus: set[str] = set()
    dc_qty: dict[str, pd.Series] = {}
    for code, _name, source in DC_SITES:
        site = latest_site_stock(store.read_source(source))
        dc_skus |= set(site["sku"].astype(str))
        dc_qty[code] = site.set_index("sku")["qty"] if not site.empty else pd.Series(dtype=float)

    # 1) SKU transaksi vs SKU di Data stok Site 10037
    if not tx.empty and "sku" in tx.columns:
        work = tx.copy()
        work["sku"] = _clean_key(work["sku"])
        blank_rows = int(work["sku"].eq("").sum())
        work = work.loc[work["sku"].ne("")]
        work["qty_n"] = _num(work, "qty")
        price = _num(work, "net_price")
        work["sales_n"] = work["qty_n"] * price
        work["day"] = pd.to_datetime(work["order_time"], errors="coerce") if "order_time" in work.columns else pd.NaT
        stock_skus = set(_clean_key(stock["sku"])) - {""} if not stock.empty and "sku" in stock.columns else set()
        per = work.groupby("sku").agg(
            produk=("product_name", "last") if "product_name" in work.columns else ("sku", "last"),
            qty=("qty_n", "sum"),
            sales=("sales_n", "sum"),
            terakhir=("day", "max"),
            pesanan=("sku", "size"),
        )
        per["cocok"] = per.index.isin(stock_skus)
        per["di_dc"] = per.index.isin(dc_skus)
        ref = pd.Timestamp(today) if today is not None else work["day"].max()
        per["hari_sejak"] = (ref - per["terakhir"]).dt.days
        miss = per.loc[~per["cocok"]]
        days = work["day"].dropna()
        out["tx_period"] = (days.min(), days.max()) if not days.empty else (None, None)
        out["tx"] = {
            "sku_total": int(len(per)),
            "sku_cocok": int(per["cocok"].sum()),
            "baris_tanpa_sku": blank_rows,
            "qty_cocok_pct": float(per.loc[per["cocok"], "qty"].sum() / per["qty"].sum() * 100) if per["qty"].sum() else 0.0,
            "sales_cocok_pct": float(per.loc[per["cocok"], "sales"].sum() / per["sales"].sum() * 100) if per["sales"].sum() else 0.0,
            "miss_30": int((miss["hari_sejak"] <= 30).sum()),
            "miss_90": int(((miss["hari_sejak"] > 30) & (miss["hari_sejak"] <= 90)).sum()),
            "miss_lama": int((miss["hari_sejak"] > 90).sum()),
            "miss_di_dc": int(miss["di_dc"].sum()),
            "stok_tanpa_transaksi": int(len(stock_skus - set(per.index))),
            "sku_stok": int(len(stock_skus)),
        }
        table = miss.sort_values("sales", ascending=False).reset_index()
        out["tx_miss"] = pd.DataFrame(
            {
                "SKU": table["sku"],
                "Produk": table["produk"].astype(str),
                "QTY terjual": table["qty"].round(),
                "Sales value": table["sales"].round(),
                "Terakhir terjual": table["terakhir"].map(lambda d: tanggal(d) if pd.notna(d) else "-"),
                **{f"Stok Site {code}": table["sku"].map(qty).fillna(0.0) if len(qty) else np.nan for code, qty in dc_qty.items()},
            }
        )
        out["stock_unsold"] = _unsold_active(stock, set(per.index), dc_qty, out["tx_period"][0], ref)

    # 2) Kode produk iklan vs Kode Produk di Data stok Site 10037
    code_to_sku = _product_code_to_sku(stock)
    name_to_variants: dict[str, str] = {}
    if not tx.empty and {"product_name", "sku"} <= set(tx.columns):
        names = tx["product_name"].astype(str).str.lower().str.replace(r"\s*\[\d+\]\s*$", "", regex=True).str.split().str.join(" ")
        variant = tx["variation"].fillna("").astype(str).str.strip() if "variation" in tx.columns else pd.Series("", index=tx.index)
        pairs = pd.DataFrame({"name": names, "sku": _clean_key(tx["sku"]), "var": variant}).drop_duplicates()
        pairs = pairs.loc[pairs["sku"].ne("")]
        for name, part in pairs.groupby("name"):
            name_to_variants[name] = "; ".join(f"{s}" + (f" ({v})" if v and v.lower() not in {"nan", "-"} else "") for s, v in zip(part["sku"], part["var"]))
    from src.core.ads import _ranges

    ad_lo, ad_hi = None, None
    rows = []
    for key in ("ads_auto", "ads_group", "ads_overall"):
        frame = store.read_source(key)
        if frame.empty or "product_code" not in frame.columns:
            continue
        part = pd.DataFrame(
            {
                "kode": _clean_key(frame["product_code"]),
                "nama": frame["product_name"].astype(str) if "product_name" in frame.columns else "",
                "biaya": _num(frame, "cost"),
                "omzet": _num(frame, "ad_sales"),
                "laporan": SOURCE_SPECS[key].label.replace("Data ", ""),
            }
        )
        rows.append(part)
        if "period" in frame.columns:
            lo, hi = _ranges(frame)
            if lo.notna().any():
                ad_lo = lo.min() if ad_lo is None else min(ad_lo, lo.min())
                ad_hi = hi.max() if ad_hi is None else max(ad_hi, hi.max())
    out["ads_period"] = (ad_lo, ad_hi)
    if rows:
        ads = pd.concat(rows, ignore_index=True)
        blank = ads["kode"].eq("") | ads["kode"].isin({"-", "0", "nan"})
        ads_named = ads.loc[~blank]
        per = ads_named.groupby("kode").agg(nama=("nama", "last"), laporan=("laporan", lambda v: ", ".join(sorted(set(v)))))
        # Biaya/omzet per kode lewat mesin atribusi: laporan tumpang tindih tidak dobel, periode penuh semua laporan.
        from src.core.ads import ad_product_rows

        frames_ads = [store.read_source(key) for key in ("ads_auto", "ads_group", "ads_overall")]
        clean, _lo, _hi = ad_product_rows(frames_ads, start=ad_lo, end=ad_hi)
        sums = clean.groupby("product_code")[["biaya_iklan", "omzet_iklan"]].sum()
        per["biaya"] = per.index.map(sums["biaya_iklan"]).fillna(0.0) if not sums.empty else 0.0
        per["omzet"] = per.index.map(sums["omzet_iklan"]).fillna(0.0) if not sums.empty else 0.0
        per["cocok"] = per.index.isin(code_to_sku)
        total_cost = float(per["biaya"].sum())
        miss = per.loc[~per["cocok"]]
        out["ads"] = {
            "kode_total": int(len(per)),
            "kode_cocok": int(per["cocok"].sum()),
            "baris_tanpa_kode": int(blank.sum()),
            "biaya_cocok_pct": float(per.loc[per["cocok"], "biaya"].sum() / total_cost * 100) if total_cost else 0.0,
            "biaya_miss": float(miss["biaya"].sum()),
            "omzet_miss": float(miss["omzet"].sum()),
            "kode_di_stok": int(len(code_to_sku)),
        }
        # Urut dampak terbesar: omzet iklan yang hilang dari ROAS per SKU, lalu biaya.
        table = miss.sort_values(["omzet", "biaya"], ascending=False).reset_index()
        key_names = table["nama"].astype(str).str.lower().str.replace(r"\s*\[\d+\]\s*$", "", regex=True).str.split().str.join(" ")
        out["ads_miss"] = pd.DataFrame(
            {
                "Kode produk": table["kode"],
                "SKU (varian) dari Data transaksi": key_names.map(name_to_variants).fillna("tidak ditemukan"),
                "Nama di laporan iklan": table["nama"],
                "Biaya iklan": table["biaya"].round(),
                "Omzet iklan": table["omzet"].round(),
                "Laporan": table["laporan"],
            }
        )

    # 3) Snapshot stok Site 10037
    if not stock.empty and "_submitted_at" in stock.columns:
        snaps = stock.groupby(stock["_submitted_at"].astype(str)).agg(baris=("sku", "size"), kosong=("stock_dc_cikupa", lambda v: int((pd.to_numeric(v, errors="coerce").fillna(0) <= 0).sum())))
        snaps = snaps.sort_index().reset_index()
        out["snapshots"] = pd.DataFrame(
            {
                "Diunggah": snaps["_submitted_at"].map(lambda v: tanggal(v, jam=True)),
                "Jumlah SKU": snaps["baris"],
                "SKU stok 0": snaps["kosong"],
            }
        )
    return out
