"""Riwayat penilaian Nama & deskripsi: simpan snapshot setiap kali data deskripsi/stok baru dianalisa, lalu bandingkan
listing saat ini dengan penilaian sebelumnya untuk melihat apakah tim mengikuti rekomendasi atau mengubah di luar rekomendasi.

Status per produk (dibanding snapshot sebelumnya dengan data berbeda):
- Mengikuti rekomendasi : nama/deskripsi berubah dan mirip rekomendasi saat itu (judul ≥ 85% kata sama; deskripsi ≥ 60% kemiripan)
- Diubah di luar rekomendasi : berubah tetapi tidak mirip rekomendasi
- Belum diubah : nama & deskripsi sama seperti penilaian sebelumnya
- Baru dinilai : belum ada di penilaian sebelumnya
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from src.core.nlp_competitor import clean_text, desc_hash, title_similarity

STATUSES = ("Mengikuti rekomendasi", "Diubah di luar rekomendasi", "Belum diubah", "Baru dinilai")
ICON = {"Mengikuti rekomendasi": "✅ Ikuti rekomendasi", "Diubah di luar rekomendasi": "✏️ Di luar rekomendasi",
        "Belum diubah": "⏸ Belum diubah", "Baru dinilai": "🆕 Baru dinilai"}
KEEP_SNAPSHOTS = 24


def snapshot_rows(recs: pd.DataFrame, data_stamp: str, at: datetime | None = None) -> pd.DataFrame:
    at = at or datetime.now()
    return pd.DataFrame({
        "snapshot_at": at, "data_stamp": data_stamp, "product_code": recs["item_key"].astype(str),
        "nama": recs["Nama produk saat ini"].astype(str), "desc_hash": recs.get("Hash deskripsi saat ini", "").astype(str),
        "status_nama": recs["Status skor"].astype(str), "poin_nama": pd.to_numeric(recs["Poin skor"], errors="coerce").fillna(0).astype(int),
        "skor_seo": pd.to_numeric(recs.get("Skor SEO saat ini", 0), errors="coerce").fillna(0).astype(int),
        "rek_nama": recs["Rekomendasi nama baru"].astype(str), "rek_deskripsi": recs["Rekomendasi deskripsi"].astype(str),
        "skor_seo_rek": pd.to_numeric(recs.get("Skor SEO", 0), errors="coerce").fillna(0).astype(int),
    })


def _text_similarity(a: str, b: str) -> float:
    wa, wb = set(clean_text(a).split()), set(clean_text(b).split())
    return len(wa & wb) / max(len(wa | wb), 1)


def previous_snapshot(history: pd.DataFrame, data_stamp: str) -> pd.DataFrame:
    """Snapshot terbaru dengan data berbeda dari data saat ini (penilaian sebelum unggahan terakhir)."""
    if history is None or history.empty:
        return pd.DataFrame()
    older = history.loc[history["data_stamp"].astype(str) != str(data_stamp)]
    if older.empty:
        return pd.DataFrame()
    last = older["snapshot_at"].max()
    return older.loc[older["snapshot_at"] == last].drop_duplicates("product_code", keep="last")


def compare(recs: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    """Satu baris per item_key: perubahan, keterangan, skor SEO lalu & kini, tanggal penilaian lalu."""
    cols = ["item_key", "perubahan", "keterangan", "skor_lalu", "skor_kini", "selisih", "tanggal_lalu"]
    if recs is None or recs.empty:
        return pd.DataFrame(columns=cols)
    prev = previous.set_index("product_code") if previous is not None and not previous.empty else pd.DataFrame()
    rows = []
    for r in recs.to_dict("records"):
        key = str(r["item_key"])
        now_score = float(r.get("Skor SEO saat ini", np.nan))
        if prev.empty or key not in prev.index:
            rows.append({"item_key": key, "perubahan": "Baru dinilai", "keterangan": "Belum ada penilaian sebelumnya", "skor_lalu": np.nan,
                         "skor_kini": now_score, "selisih": np.nan, "tanggal_lalu": pd.NaT})
            continue
        p = prev.loc[key]
        name_now = str(r["Nama produk saat ini"])
        name_changed = clean_text(name_now) != clean_text(str(p["nama"]))
        hash_now = str(r.get("Hash deskripsi saat ini", "") or desc_hash(r.get("Deskripsi saat ini", "")))
        desc_changed = bool(hash_now) and bool(p["desc_hash"]) and hash_now != str(p["desc_hash"])
        name_follow = name_changed and title_similarity(name_now, str(p["rek_nama"])) >= 0.85
        desc_follow = desc_changed and _text_similarity(str(r.get("Deskripsi saat ini", "")), str(p["rek_deskripsi"])) >= 0.60
        parts = []
        if name_changed:
            parts.append("Nama: " + ("mengikuti rekomendasi" if name_follow else "diubah sendiri"))
        if desc_changed:
            parts.append("Deskripsi: " + ("mengikuti rekomendasi" if desc_follow else "diubah sendiri"))
        if not (name_changed or desc_changed):
            status = "Belum diubah"
        elif name_follow or desc_follow:
            status = "Mengikuti rekomendasi"
        else:
            status = "Diubah di luar rekomendasi"
        before = float(p["skor_seo"])
        delta = now_score - before if np.isfinite(now_score) else np.nan
        if np.isfinite(delta) and (name_changed or desc_changed):
            parts.append(f"Skor SEO {before:.0f} → {now_score:.0f} ({'+' if delta >= 0 else ''}{delta:.0f})")
        rows.append({"item_key": key, "perubahan": status, "keterangan": "; ".join(parts) or "Sama seperti penilaian sebelumnya",
                     "skor_lalu": before, "skor_kini": now_score, "selisih": delta, "tanggal_lalu": p["snapshot_at"]})
    return pd.DataFrame(rows, columns=cols)
