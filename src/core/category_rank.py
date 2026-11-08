"""Ranking kategori Shopee: peluang produk Mitra10 masuk Top 10 dari unggahan data kompetitor.

Data unggahan (menu Kompetitor): kolom Daftar (satu daftar ranking kategori), Ranking, Change of Rank, Shop Name,
Products Name, Toko sendiri. Tiap daftar berisi ±20 produk teratas + produk toko sendiri ("My Shop") dengan peringkatnya.
- Nama kategori tidak ada di data, disimpulkan dari kata/frasa yang paling sering muncul di nama produk daftar itu.
- Produk kita = baris "Toko sendiri" atau nama toko berisi "Mitra10".
- Perkiraan kebutuhan penjualan memakai pola umum marketplace (hukum Zipf): penjualan ≈ berbanding terbalik dengan
  peringkat, sehingga dari peringkat r ke peringkat 10 butuh ± r/10 × penjualan sekarang. Bila daftar itu memuat produk
  kita yang sudah Top 10 dan penjualannya diketahui, angka itu dipakai sebagai patokan. Ini perkiraan, bukan data Shopee.
"""

from __future__ import annotations

import re
from collections import Counter

import numpy as np
import pandas as pd

from src.core.exposure import category_of

TOP = 10
TIERS = ((10, "Sudah Top 10"), (50, "Dekat"), (500, "Menengah"), (float("inf"), "Jauh"))
UNRANKED = "Belum masuk ranking"
STATUS_ORDER = tuple(name for _l, name in TIERS) + (UNRANKED,)
STOP = set("""
dan atau untuk dengan yang di ke dari pada ini itu juga bisa sangat lebih tanpa serta per isi set pcs pc buah unit
official store shop toko original ori asli new baru murah promo ready stock stok termurah terlaris best seller hot sale
gratis free bonus cod garansi tahun bulan ukuran size variasi varian warna motif model type tipe series seri
cm mm m ml l liter kg gr gram g w watt inch x
""".split())
PROMO_TAGS = (
    ("COD", re.compile(r"\bcod\b", re.I)),
    ("Gratis/bonus", re.compile(r"gratis|free|bonus", re.I)),
    ("Garansi", re.compile(r"garansi|warranty", re.I)),
    ("Harga/promo", re.compile(r"turun harga|promo|diskon|murah|termurah|sale", re.I)),
    ("Banyak ukuran/varian", re.compile(r"\d+\s*(?:l|cm|liter)?\s*/\s*\d+|\d+x\d+.*\d+x\d+", re.I)),
)


def _tokens(name: object) -> list[str]:
    words = re.findall(r"[a-z][a-z0-9]+", str(name or "").lower())
    return [w for w in words if w not in STOP and not re.fullmatch(r"[a-z]?\d+[a-z]*", w) and len(w) > 2]


def _norm(name: object) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(name or "").lower()))


def prepare(competitors: pd.DataFrame | None) -> pd.DataFrame:
    cols = ["daftar", "rank", "change", "shop", "product", "ours"]
    if competitors is None or competitors.empty or not {"rank", "product_name"} <= set(competitors.columns):
        return pd.DataFrame(columns=cols)
    c = competitors
    daftar = c["Daftar"] if "Daftar" in c.columns else pd.Series(1, index=c.index)
    shop = c.get("shop_name", pd.Series("", index=c.index)).fillna("").astype(str)
    own = c.get("own_shop", pd.Series(False, index=c.index)).astype(str).str.lower().isin({"true", "1", "ya", "yes"})
    out = pd.DataFrame({
        "daftar": pd.to_numeric(daftar, errors="coerce"),
        "rank": pd.to_numeric(c["rank"].astype(str).str.replace(r"[^\d]", "", regex=True), errors="coerce"),
        "change": c.get("rank_change", pd.Series("", index=c.index)).astype(str).replace({"None": "", "nan": "", "My Shop": ""}),
        "shop": shop, "product": c["product_name"].fillna("").astype(str),
        "ours": own | shop.str.lower().str.contains("mitra10", regex=False),
    })
    return out.dropna(subset=["daftar", "rank"]).astype({"daftar": int, "rank": int})[cols]


def category_label(names: list[str]) -> str:
    """Frasa 2 kata (atau kata) yang muncul di nama produk terbanyak dalam satu daftar."""
    docs = [_tokens(n) for n in names if str(n).strip()]
    if not docs:
        return "-"
    bigrams = Counter(b for d in docs for b in dict.fromkeys(f"{x} {y}" for x, y in zip(d, d[1:])))
    unigrams = Counter(w for d in docs for w in dict.fromkeys(d))
    labels = []
    for phrase, n in bigrams.most_common(3):
        if n >= max(2, 0.3 * len(docs)):
            labels.append(phrase)
    if not labels:
        labels = [w for w, n in unigrams.most_common(2) if n >= 2] or [unigrams.most_common(1)[0][0]]
    seen: list[str] = []
    for label in labels:
        if not any(set(label.split()) <= set(s.split()) for s in seen):
            seen.append(label)
    return " / ".join(s.title() for s in seen[:2])


def tier_of(rank: float) -> str:
    return next(name for limit, name in TIERS if rank <= limit)


def patterns(top: pd.DataFrame) -> dict:
    """Pola Top 10: kata kunci umum (≥ 30% nama), tag promo, porsi official store."""
    names = top["product"].tolist()
    n = max(len(names), 1)
    brands = {w for shop in top["shop"] for w in _tokens(shop)}
    words = Counter(w for name in names for w in set(_tokens(name)) if w not in brands)
    common = [w for w, k in words.most_common(15) if k >= max(2, 0.3 * n)]
    strong = [w for w, k in words.most_common(15) if k >= max(2, 0.5 * n)]
    tags = {label: sum(bool(rx.search(name)) for name in names) / n for label, rx in PROMO_TAGS}
    official = top["shop"].str.contains("official|mall|authorized", case=False, regex=True).mean() if len(top) else 0.0
    return {"kata": common, "kuat": strong, "tag": tags, "official": float(official)}


def missing_keywords(our_name: str, strong: list[str]) -> list[str]:
    """Kata yang dipakai ≥ 50% judul Top 10 tetapi belum ada di judul kita; kosong bila produk kita beda jenis
    (tidak ada satu pun kata yang sama)."""
    mine = set(_tokens(our_name))
    if not mine & set(strong):
        return []
    return [w for w in strong if w not in mine]


def match_products(names: pd.Series, catalog: pd.DataFrame) -> pd.Series:
    """Nama produk ranking → baris katalog kita (indeks), cocok persis setelah dinormalisasi atau kemiripan kata ≥ 60%."""
    if catalog is None or catalog.empty:
        return pd.Series([None] * len(names), index=names.index)
    norm = catalog["nama"].map(_norm)
    exact = {v: i for i, v in zip(catalog.index, norm)}
    token_sets = [(i, set(v.split())) for i, v in zip(catalog.index, norm)]
    out = []
    for name in names:
        key = _norm(name)
        if key in exact:
            out.append(exact[key])
            continue
        words = set(key.split())
        best, score = None, 0.0
        for i, other in token_sets:
            if not other:
                continue
            s = len(words & other) / len(words | other)
            if s > score:
                best, score = i, s
        out.append(best if score >= 0.6 else None)
    return pd.Series(out, index=names.index)


def analyze(competitors: pd.DataFrame | None, catalog: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(ringkasan per daftar, peluang per produk kita).

    catalog: nama, sku, qty_bulan (prediksi unit/bulan), omzet_bulan, stok, ada_stok, harga, iklan (bool)."""
    data = prepare(competitors)
    list_cols = ["Kelompok", "Daftar", "Kategori", "Produk kita terbaik", "Peringkat terbaik", "Status", "Produk kita", "Official store di Top 10", "Kata kunci Top 10"]
    opp_cols = ["Status", "Kategori", "Daftar", "Peringkat", "Produk", "SKU", "Penjualan/bulan", "Perlu/bulan (perkiraan)", "Kali lipat",
                "Stok", "Diiklankan", "Kata kunci yang belum ada", "Langkah"]
    if data.empty:
        return pd.DataFrame(columns=list_cols), pd.DataFrame(columns=opp_cols)
    catalog = catalog if catalog is not None else pd.DataFrame(columns=["nama", "sku", "qty_bulan", "omzet_bulan", "stok", "ada_stok", "harga", "iklan"])
    ours_all = data.loc[data["ours"]].copy()
    ours_all["cat"] = match_products(ours_all["product"], catalog) if not ours_all.empty else pd.Series(dtype=object)
    lists, opps = [], []
    for daftar, part in data.groupby("daftar"):
        others = part.loc[~part["ours"]].sort_values("rank")
        top = part.loc[part["rank"] <= TOP].sort_values("rank")
        label = category_label(others["product"].tolist() or part["product"].tolist())
        pat = patterns(top if not top.empty else others.head(TOP))
        mine = ours_all.loc[ours_all["daftar"] == daftar].sort_values("rank")
        anchor = None
        for r in mine.itertuples():
            idx = r.cat
            qty = float(catalog.loc[idx, "qty_bulan"] or 0) if pd.notna(idx) else 0.0
            if r.rank <= TOP and qty > 0 and (anchor is None or qty > anchor[1]):
                anchor = (r.rank, qty)
        best = int(mine["rank"].min()) if not mine.empty else None
        groups = Counter(category_of(n) for n in (others["product"].tolist() or part["product"].tolist()))
        lists.append({"Kelompok": groups.most_common(1)[0][0] if groups else "Lainnya", "Daftar": int(daftar), "Kategori": label, "Produk kita terbaik": mine["product"].iloc[0] if not mine.empty else "",
                      "Peringkat terbaik": best, "Status": tier_of(best) if best else "Belum ada produk kita",
                      "Produk kita": len(mine), "Official store di Top 10": pat["official"] * 100, "Kata kunci Top 10": ", ".join(pat["kata"][:8])})
        for r in mine.drop_duplicates("product").itertuples():
            idx = r.cat if pd.notna(r.cat) else None
            row = catalog.loc[idx] if idx is not None else None
            qty = float(row["qty_bulan"]) if row is not None and pd.notna(row["qty_bulan"]) else np.nan
            need = (anchor[1] * anchor[0] / TOP) if anchor else (qty * r.rank / TOP if qty == qty and qty > 0 else np.nan)
            mult = need / qty if qty == qty and qty > 0 and need == need else r.rank / TOP
            stok = float(row["stok"]) if row is not None and bool(row.get("ada_stok")) else np.nan
            advertised = bool(row["iklan"]) if row is not None else False
            gaps = missing_keywords(r.product, pat["kuat"])
            opps.append({
                "Status": tier_of(r.rank), "Kategori": label, "Daftar": int(daftar), "Peringkat": int(r.rank), "Produk": r.product,
                "SKU": str(row["sku"]) if row is not None else "", "Penjualan/bulan": qty, "Perlu/bulan (perkiraan)": max(need, qty) if need == need else np.nan,
                "Kali lipat": max(mult, 1.0) if r.rank > TOP else 1.0, "Stok": stok, "Diiklankan": "Ya" if advertised else "Tidak",
                "Kata kunci yang belum ada": ", ".join(gaps[:6]), "Langkah": "; ".join(actions(r.rank, stok, qty, advertised, gaps, pat)),
            })
    order = {name: i for i, (_l, name) in enumerate(TIERS)}
    opp = pd.DataFrame(opps, columns=opp_cols)
    if not opp.empty:
        opp = opp.assign(_o=opp["Status"].map(order), _k=opp["Kali lipat"]).sort_values(["_o", "_k", "Peringkat"]).drop(columns=["_o", "_k"]).reset_index(drop=True)
    summary = pd.DataFrame(lists, columns=list_cols)
    summary = summary.assign(_b=summary["Peringkat terbaik"].fillna(10**9)).sort_values("_b").drop(columns="_b").reset_index(drop=True)
    return summary, opp


def actions(rank: int, stok: float, qty: float, advertised: bool, gaps: list[str], pat: dict) -> list[str]:
    """Langkah prioritas masuk / bertahan di Top 10."""
    out: list[str] = []
    if stok == stok and stok <= 0:
        out.append("restock dulu: produk tanpa stok turun peringkat")
    elif stok == stok and qty == qty and qty > 0 and stok < qty * 0.5:
        out.append("tambah stok: ranking naik butuh penjualan lebih besar dari stok sekarang")
    if rank <= TOP:
        out.append("pertahankan: jaga stok, harga, dan iklan; pantau pesaing yang naik")
    else:
        out.append("naikkan budget iklan produk ini (Rekomendasi › Iklan)" if advertised else "buat iklan produk tunggal (Rekomendasi › Iklan)")
        if rank <= 500:
            out.append("masukkan ke Flash sale toko untuk lonjakan penjualan")
        if gaps:
            out.append("tambahkan kata kunci di judul bila sesuai produk: " + ", ".join(gaps[:4]))
        popular = [label for label, share in pat["tag"].items() if share >= 0.4 and label != "Banyak ukuran/varian"]
        if popular:
            out.append("pesaing Top 10 menonjolkan " + ", ".join(popular).lower() + ": pertimbangkan di judul/voucher")
        out.append("buat konten Shopee Video (Rekomendasi › Exposure)")
    return out


def by_product(competitors: pd.DataFrame | None, catalog: pd.DataFrame | None, summary: pd.DataFrame, opp: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(satu baris per produk katalog saat ini, produk di ranking yang tidak ada di katalog).

    Produk di beberapa daftar memakai peringkat terbaiknya; produk yang belum muncul di daftar mana pun berstatus
    "Belum masuk ranking" dengan kategori perkiraan dari kata kunci Top 10 yang paling cocok dengan namanya."""
    cols = ["Kelompok", "Kategori", "Status", "Peringkat", "Daftar", "Daftar lain", "Produk", "SKU", "Jumlah SKU", "Penjualan/bulan",
            "Perlu/bulan (perkiraan)", "Kali lipat", "Stok", "Diiklankan", "Kata kunci yang belum ada", "Langkah"]
    if catalog is None or catalog.empty:
        return pd.DataFrame(columns=cols), opp.iloc[0:0] if opp is not None else pd.DataFrame()
    data = prepare(competitors)
    words: dict[int, tuple[set[str], list[str]]] = {}
    for daftar, part in data.groupby("daftar"):
        top = part.loc[part["rank"] <= TOP]
        pat = patterns(top if not top.empty else part.sort_values("rank").head(TOP))
        words[int(daftar)] = (set(pat["kata"]), pat["kuat"])
    label = dict(zip(summary["Daftar"], summary["Kategori"])) if not summary.empty else {}
    ranked = opp.loc[opp["SKU"].astype(str) != ""] if opp is not None and not opp.empty else pd.DataFrame(columns=list(opp.columns) if opp is not None else [])
    by_sku = {sku: g.sort_values("Peringkat") for sku, g in ranked.groupby(ranked["SKU"].astype(str))} if not ranked.empty else {}
    rows = []
    for r in catalog.to_dict("records"):
        sku = str(r.get("sku", ""))
        base = {"Kelompok": category_of(r["nama"]), "Produk": r["nama"], "SKU": sku, "Jumlah SKU": int(r["n_sku"]) if pd.notna(r.get("n_sku")) else 1}
        hit = by_sku.get(sku)
        if hit is not None:
            best = hit.iloc[0]
            others = [f"#{int(p)} di daftar {int(d)}" for p, d in zip(hit["Peringkat"].iloc[1:], hit["Daftar"].iloc[1:])]
            rows.append({**best.to_dict(), **base, "Daftar lain": ", ".join(others)})
            continue
        tokens = set(_tokens(r["nama"]))
        scored = sorted(((len(tokens & kata), -d) for d, (kata, _strong) in words.items()), reverse=True)
        daftar = -scored[0][1] if scored and scored[0][0] >= 2 else None
        gaps = missing_keywords(r["nama"], words[daftar][1]) if daftar is not None else []
        qty = float(r.get("qty_bulan") or 0)
        stok = float(r["stok"]) if bool(r.get("ada_stok")) and pd.notna(r.get("stok")) else np.nan
        advertised = bool(r.get("iklan"))
        steps = []
        if stok == stok and stok <= 0:
            steps.append("restock dulu")
        steps.append("naikkan budget iklan agar mulai muncul di ranking" if advertised else "buat iklan produk tunggal (Rekomendasi › Iklan)")
        if gaps:
            steps.append("tambahkan kata kunci di judul bila sesuai produk: " + ", ".join(gaps[:4]))
        steps.append("masukkan ke Flash sale toko & konten Shopee Video")
        rows.append({**base, "Kategori": f"{label.get(daftar, '-')} (perkiraan)" if daftar is not None else "-", "Status": UNRANKED,
                     "Peringkat": np.nan, "Daftar": daftar if daftar is not None else np.nan, "Daftar lain": "", "Penjualan/bulan": qty,
                     "Perlu/bulan (perkiraan)": np.nan, "Kali lipat": np.nan, "Stok": stok, "Diiklankan": "Ya" if advertised else "Tidak",
                     "Kata kunci yang belum ada": ", ".join(gaps[:6]), "Langkah": "; ".join(steps)})
    out = pd.DataFrame(rows).reindex(columns=cols)
    order = {name: i for i, name in enumerate(STATUS_ORDER)}
    out = (out.assign(_s=out["Status"].map(order), _p=out["Peringkat"].fillna(10**9), _q=-out["Penjualan/bulan"].fillna(0))
              .sort_values(["_s", "_p", "_q"]).drop(columns=["_s", "_p", "_q"]).reset_index(drop=True))
    missing = opp.loc[opp["SKU"].astype(str) == ""] if opp is not None and not opp.empty else pd.DataFrame()
    return out, missing
