"""Skor kesiapan ranking kategori per SKU (0–100) dan data Brand Portal (Revisi Final 4E).

Shopee tidak memublikasikan bobot algoritma; skor ini indikator internal.
Faktor tanpa data di sistem (atribut, video, ulasan berfoto, Gratis Ongkir) bernilai 0 dan ditandai "–".
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BRAND_COLUMNS = ("periode", "kategori", "brand", "peringkat", "pangsa")
FACTORS = (
    ("judul", "Judul (keyword di 40 karakter awal)", 15),
    ("atribut", "Atribut lengkap", 10),
    ("video", "Video produk", 10),
    ("rating", "Rating", 15),
    ("ulasan_foto", "Ulasan berfoto", 10),
    ("harga", "Harga ≤ median 5 kompetitor", 15),
    ("batal", "Batal rendah", 15),
    ("gratis_ongkir", "Gratis Ongkir", 10),
)


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return float(min(max(value, lo), hi))


def keyword_of(name: str) -> str:
    """Keyword utama = dua kata pertama yang bukan merek/angka."""
    words = [w for w in str(name or "").lower().replace("-", " ").split() if w.isalpha() and len(w) > 2]
    return " ".join(words[:2])


def readiness(
    row: dict,
    *,
    category_keyword: str | None = None,
    rating: float | None = None,
    competitor_median: float | None = None,
    has_attributes: bool | None = None,
    has_video: bool | None = None,
    has_photo_review: bool | None = None,
    free_shipping: bool | None = None,
) -> dict[str, float | None]:
    """Nilai per faktor (None = data belum ada) dan skor total."""
    name = str(row.get("product_name", ""))
    keyword = category_keyword or keyword_of(name)
    out: dict[str, float | None] = {}
    out["judul"] = 15.0 if keyword and keyword.split()[0] in name[:40].lower() else 0.0
    out["atribut"] = None if has_attributes is None else (10.0 if has_attributes else 0.0)
    out["video"] = None if has_video is None else (10.0 if has_video else 0.0)
    out["rating"] = None if rating is None or not np.isfinite(rating) else 15 * clamp((rating - 4.0) / 1.0)
    out["ulasan_foto"] = None if has_photo_review is None else (10.0 if has_photo_review else 0.0)
    price = float(row.get("harga_bersih", 0) or 0)
    out["harga"] = None if not competitor_median or price <= 0 else (15.0 if price <= competitor_median else 0.0)
    batal = float(row.get("batal_pct", 0) or 0)
    out["batal"] = 15 * clamp((20 - batal) / 15)
    out["gratis_ongkir"] = None if free_shipping is None else (10.0 if free_shipping else 0.0)
    out["skor"] = float(sum(v for v in out.values() if v is not None))
    return out


def priority_steps(scores: dict[str, float | None], sales: float, limit: int = 3) -> list[str]:
    """3 faktor dengan (bobot hilang × sales SKU) terbesar."""
    losses = []
    for key, label, weight in FACTORS:
        value = scores.get(key)
        lost = weight - (value or 0.0)
        if lost > 0:
            losses.append((lost * max(sales, 1.0), label))
    return [label for _loss, label in sorted(losses, reverse=True)[:limit]]


def normalize_brand_portal(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    work = frame.copy()
    work.columns = [str(c).strip().lower() for c in work.columns]
    missing = [c for c in BRAND_COLUMNS if c not in work.columns]
    if missing:
        return pd.DataFrame(columns=list(BRAND_COLUMNS)), ["Kolom hilang: " + ", ".join(missing)]
    work["periode"] = work["periode"].astype(str).str.strip().str.slice(0, 7)
    work["peringkat"] = pd.to_numeric(work["peringkat"], errors="coerce").astype("Int64")
    pangsa = work["pangsa"].astype(str).str.replace("%", "", regex=False).str.replace(",", ".", regex=False)
    work["pangsa"] = pd.to_numeric(pangsa, errors="coerce")
    work = work.dropna(subset=["kategori", "brand"])
    return work[list(BRAND_COLUMNS)], []


def brand_changes(portal: pd.DataFrame) -> pd.DataFrame:
    """Rank & pangsa periode terbaru + perubahan vs periode sebelumnya per (kategori, brand)."""
    if portal is None or portal.empty:
        return pd.DataFrame()
    periods = sorted(portal["periode"].astype(str).unique())
    now = portal.loc[portal["periode"] == periods[-1]].copy()
    if len(periods) > 1:
        prev = portal.loc[portal["periode"] == periods[-2], ["kategori", "brand", "peringkat", "pangsa"]].rename(columns={"peringkat": "peringkat_lalu", "pangsa": "pangsa_lalu"})
        now = now.merge(prev, on=["kategori", "brand"], how="left")
        now["perubahan_peringkat"] = now["peringkat_lalu"] - now["peringkat"]
        now["perubahan_pangsa"] = now["pangsa"] - now["pangsa_lalu"]
    return now.sort_values(["kategori", "peringkat"]).reset_index(drop=True)
