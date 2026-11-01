"""Sistem pakar (production rules If-Then) dan analisa akar masalah.

Aturan dibaca dari config/rules.yaml. Fakta per SKU dibentuk dari tabel keputusan
(prediksi, stok, SS), iklan, batal, segmentasi, dan benchmark kompetitor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.core.config import load_rules

OPS = {
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "in": lambda a, b: a in b,
}


@dataclass
class Advice:
    rule_id: str
    priority: int
    action: str
    text: str


def _fmt(value: object) -> str:
    if isinstance(value, (bool, np.bool_)):
        return "ya" if value else "tidak"
    if isinstance(value, (int, np.integer)):
        return f"{int(value):,}".replace(",", ".")
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(value):
            return "-"
        if abs(value - round(value)) < 1e-9:
            return f"{int(round(value)):,}".replace(",", ".")
        return f"{value:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if isinstance(value, date):
        months = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
        return f"{value.day} {months[value.month - 1]}"
    return str(value)


def _condition_holds(facts: dict, condition: list) -> bool:
    if not isinstance(condition, (list, tuple)) or len(condition) != 3:
        return False
    name, op, expected = condition
    if name not in facts or op not in OPS:
        return False
    value = facts[name]
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return False
    try:
        return bool(OPS[op](value, expected))
    except TypeError:
        return False


def evaluate_rules(facts: dict, rules: list[dict] | None = None) -> list[Advice]:
    rules = load_rules() if rules is None else rules
    out: list[Advice] = []
    for rule in rules:
        conditions = rule.get("jika") or []
        if conditions and all(_condition_holds(facts, cond) for cond in conditions):
            safe = {key: _fmt(value) for key, value in facts.items()}
            try:
                text = str(rule.get("maka", "")).format(**safe)
            except (KeyError, IndexError, ValueError):
                text = str(rule.get("maka", ""))
            out.append(Advice(str(rule.get("id", "")), int(rule.get("prioritas", 9)), str(rule.get("aksi", "")), text))
    return sorted(out, key=lambda advice: advice.priority)


def sku_facts(row: pd.Series, *, prefix: str = "m", today: date | None = None) -> dict:
    """Fakta satu SKU dari tabel keputusan yang sudah digabung iklan/batal/segmen/benchmark."""
    ref = today or date.today()
    need = float(row.get(f"{prefix}_butuh", 0) or 0)
    stok = row.get("stok")
    stok_val = float(stok) if stok is not None and not pd.isna(stok) else np.nan
    gap = need - stok_val if not np.isnan(stok_val) else np.nan
    views = float(row.get("dilihat", 0) or 0)
    clicks = float(row.get("klik", 0) or 0)
    cost = float(row.get("biaya_iklan", 0) or 0)
    ad_sales = float(row.get("omzet_iklan", 0) or 0)
    sold_ads = float(row.get("terjual_iklan", 0) or 0)
    lead = float(row.get("lead_time", 7) or 7)
    return {
        "abc": row.get("abc", ""),
        "xyz": row.get("xyz", ""),
        "status_stok": str(row.get(f"{prefix}_status", "")).split(" · ")[0],
        "di_bawah_ss": bool(row.get("di_bawah_ss", False)),
        "selisih_pct": float(row.get(f"{prefix}_pct", 0) or 0) * 100,
        "kekurangan": max(gap, 0.0) if not np.isnan(gap) else np.nan,
        "batas_tanggal": ref + timedelta(days=max(int(min(row.get("hari_cukup", 0) or 0, 365)) - int(lead), 0)) if pd.notna(row.get("hari_cukup")) else ref,
        "hari_cukup": float(row.get("hari_cukup", np.nan)) if pd.notna(row.get("hari_cukup")) else np.nan,
        "lama_kosong": float(row.get("lama_kosong_hari", np.nan)) if pd.notna(row.get("lama_kosong_hari")) else np.nan,
        "ss": float(row.get("ss", 0) or 0),
        "rop": float(row.get("rop", 0) or 0),
        "stok": stok_val,
        "harga_vs_kompetitor_pct": float(row.get("harga_vs_kompetitor_pct", np.nan)) if pd.notna(row.get("harga_vs_kompetitor_pct")) else np.nan,
        "batal_pct": float(row.get("batal_pct", 0) or 0),
        "batal_belum_bayar_pct": float(row.get("batal_belum_bayar_pct", 0) or 0),
        "dilihat": views,
        "klik": clicks,
        "ctr_pct": clicks / views * 100 if views > 0 else np.nan,
        "konversi_pct": sold_ads / clicks * 100 if clicks > 0 else np.nan,
        "roas": ad_sales / cost if cost > 0 else np.nan,
        "biaya_iklan": cost,
        "tren_pct": float(row.get("tren_pct", np.nan)) if pd.notna(row.get("tren_pct")) else np.nan,
        "productivity_label": row.get("productivity_label", ""),
        "label_terlaris": "Terlaris" in (row.get("label") or []),
    }


def root_cause(facts: dict) -> tuple[str, str]:
    """Pohon keputusan sederhana: stok → traffic → listing (CTR) → konversi/harga."""
    if facts.get("status_stok") in {"Kosong", "Kurang"}:
        return "Stok", "Penjualan tertahan karena stok tidak cukup; restock dulu sebelum menambah traffic."
    trend = facts.get("tren_pct")
    if trend is not None and not np.isnan(trend) and trend >= 0:
        return "Tidak stagnan", "Penjualan tidak turun; pertahankan stok dan iklan."
    views = facts.get("dilihat", 0) or 0
    if views < 500:
        return "Traffic", "Produk kurang terlihat: aktifkan iklan pencarian dengan kata kunci utama dan perbaiki judul."
    ctr = facts.get("ctr_pct")
    if ctr is not None and not np.isnan(ctr) and ctr < 1.0:
        return "Listing", "Banyak dilihat tetapi jarang diklik: ganti foto utama dan judul."
    price_gap = facts.get("harga_vs_kompetitor_pct")
    if price_gap is not None and not np.isnan(price_gap) and price_gap > 5:
        return "Harga", f"Harga {price_gap:.0f}% di atas kompetitor: uji turun harga atau bundling."
    return "Konversi", "Klik ada tetapi pembeli ragu: lengkapi deskripsi, spesifikasi, dan jawab alasan batal."


def drivers_and_risks(facts: dict, row: pd.Series) -> tuple[list[str], list[str]]:
    """Pendorong naik dan penahan/risiko (analisa dua sisi), keduanya selalu terisi."""
    up: list[str] = []
    down: list[str] = []
    trend = facts.get("tren_pct")
    if trend is not None and not np.isnan(trend):
        (up if trend > 0 else down).append(f"Penjualan 28 hari terakhir {'naik' if trend > 0 else 'turun'} {abs(trend):.0f}% dibanding 28 hari sebelumnya")
    roas = facts.get("roas")
    if roas is not None and not np.isnan(roas):
        (up if roas >= 6 else down).append(f"ROAS iklan {roas:.1f}")
    if facts.get("label_terlaris"):
        up.append("Masuk 10 besar QTY dan sales (Terlaris)")
    if str(row.get("abc", "")) == "A":
        up.append("Kelas A: penyumbang 70% omzet")
    if str(row.get("xyz", "")) == "X":
        up.append("Permintaan stabil (kelas X)")
    elif str(row.get("xyz", "")) == "Z":
        down.append("Permintaan sporadis (kelas Z), mudah meleset")
    status = facts.get("status_stok")
    if status in {"Kosong", "Kurang", "Tipis"}:
        down.append(f"Stok {status.lower()}: kurang {_fmt(facts.get('kekurangan'))} unit dari kebutuhan")
    elif status == "Aman":
        up.append(f"Stok aman untuk {_fmt(facts.get('hari_cukup'))} hari")
    if facts.get("batal_pct", 0) > 10:
        down.append(f"Tingkat batal {facts['batal_pct']:.0f}%")
    gap = facts.get("harga_vs_kompetitor_pct")
    if gap is not None and not np.isnan(gap):
        (down if gap > 5 else up).append(f"Harga {abs(gap):.0f}% {'di atas' if gap > 0 else 'di bawah'} kompetitor")
    if not up:
        up.append("Belum ada pendorong kuat dari data; manfaatkan tanggal promo (gajian, tanggal kembar)")
    if not down:
        down.append("Risiko utama: lonjakan permintaan proyek melebihi safety stock")
    return up[:4], down[:4]


def action_steps(advices: list[Advice], facts: dict, *, max_steps: int = 3) -> list[str]:
    """Maks. 3 langkah terukur. Iklan tidak dinaikkan bila stok < kebutuhan."""
    stock_short = facts.get("status_stok") in {"Kosong", "Kurang", "Tipis"}
    steps = []
    for advice in advices:
        if stock_short and advice.action == "iklan" and advice.rule_id != "iklan_boros":
            continue
        if advice.text not in steps:
            steps.append(advice.text)
        if len(steps) >= max_steps:
            break
    if not steps:
        steps.append("Pertahankan stok di atas ROP dan pantau penjualan harian.")
    return steps


def swot(context: dict) -> dict[str, list[str]]:
    """SWOT dari angka nyata (context berisi metrik toko yang sudah dihitung)."""
    s, w, o, t = [], [], [], []
    growth = context.get("sales_growth_pct")
    if growth is not None and np.isfinite(growth):
        (s if growth >= 0 else w).append(f"Sales bersih {'naik' if growth >= 0 else 'turun'} {abs(growth):.1f}% dibanding bulan lalu")
    share = context.get("top50_share_pct")
    if share is not None:
        s.append(f"Top 50 SKU menyumbang {share:.1f}% sales")
    roas = context.get("roas")
    if roas is not None and np.isfinite(roas):
        (s if roas >= context.get("target_roas", 8) else w).append(f"ROAS iklan {roas:.1f} (target {context.get('target_roas', 8)})")
    cancel = context.get("cancel_pct")
    if cancel is not None:
        (w if cancel > 5 else s).append(f"Tingkat batal {cancel:.1f}% dari pesanan")
    short = context.get("top50_short")
    if short:
        w.append(f"{short} SKU Top 50 stoknya kurang dari kebutuhan")
    unpaid = context.get("unpaid_orders")
    if unpaid:
        o.append(f"{unpaid} pesanan batal karena belum bayar bisa dikejar lewat chat pengingat")
    promo_days = context.get("promo_days")
    if promo_days:
        o.append(f"{promo_days} tanggal promo (gajian/tanggal kembar) dalam periode prediksi")
    poor_names = context.get("poor_names")
    if poor_names:
        o.append(f"{poor_names} nama produk berskor Poor bisa diperbaiki untuk SEO")
    comp_cheaper = context.get("competitor_cheaper")
    if comp_cheaper:
        t.append(f"{comp_cheaper} produk lebih mahal dari kompetitor > 5%")
    dead = context.get("dead_stock")
    if dead:
        t.append(f"{dead} SKU Slow-Moving/Dead Stock menahan modal")
    if context.get("zero_stock"):
        t.append(f"{context['zero_stock']} SKU stok kosong di DC Cikupa")
    for bucket, fallback in ((s, "Data belum cukup untuk kekuatan"), (w, "Belum ada kelemahan menonjol dari data"), (o, "Peluang belum terlihat dari data"), (t, "Ancaman belum terlihat dari data")):
        if not bucket:
            bucket.append(fallback)
    return {"Strength": s, "Weakness": w, "Opportunity": o, "Threat": t}


FISHBONE_CATEGORIES = ("Pembayaran", "Pengiriman", "Produk", "Harga & promo", "Pelayanan", "Sistem/data")
_FISHBONE_KEYWORDS = {
    "Pembayaran": ("bayar", "pembayaran", "payment", "cod"),
    "Pengiriman": ("kirim", "ongkir", "alamat", "ekspedisi", "lama", "pengiriman", "kurir"),
    "Produk": ("produk", "stok", "habis", "rusak", "ukuran", "warna", "salah", "variasi"),
    "Harga & promo": ("harga", "voucher", "diskon", "promo", "murah", "mahal"),
    "Pelayanan": ("penjual", "respon", "chat", "berubah pikiran", "ubah"),
    "Sistem/data": ("sistem", "otomatis", "dibatalkan oleh sistem", "aplikasi"),
}


def fishbone(cancel_reasons: pd.DataFrame) -> dict[str, list[str]]:
    """Kelompokkan alasan batal ke 6 kategori, masing-masing dengan angka sumber."""
    out = {category: [] for category in FISHBONE_CATEGORIES}
    if cancel_reasons is None or cancel_reasons.empty:
        return out
    for _, row in cancel_reasons.iterrows():
        reason = str(row.get("reason", "")).strip() or "Tanpa alasan"
        count = int(row.get("orders", 0) or 0)
        low = reason.lower()
        category = next((cat for cat, words in _FISHBONE_KEYWORDS.items() if any(word in low for word in words)), "Pelayanan")
        out[category].append(f"{reason}: {count} pesanan")
    return out


def work_guide(context: dict) -> dict[str, list[tuple[str, str]]]:
    """Panduan kerja harian/mingguan/bulanan dengan ukuran berhasil."""
    target = context.get("target_sales", 0)
    target_text = context.get("target_text", "-")
    daily_target = context.get("daily_target_text", "-")
    roas_target = context.get("target_roas", 8)
    return {
        "Harian": [
            (f"Cek sales harian terhadap target {daily_target}", "Sales kemarin ≥ target harian"),
            ("Kirim chat pengingat ke pembeli yang belum bayar", "Pesanan batal belum bayar turun minggu ini"),
            ("Cek SKU Top 50 berstatus Kurang/Kosong dan ajukan restock", "0 SKU Top 50 kosong"),
            ("Pantau iklan dengan ROAS < 3 dan turunkan bid", f"ROAS harian ≥ {roas_target}"),
        ],
        "Mingguan": [
            ("Upload stok terbaru (snapshot DC Cikupa) dan jalankan analisis", "Prediksi dan lama kosong ter-update"),
            ("Perbaiki 10 nama/deskripsi berskor Poor", "Skor naik ke Standard/Excellence"),
            ("Evaluasi budget iklan per SKU terhadap stok", "Tidak ada iklan aktif pada SKU stok kurang"),
            ("Siapkan flash sale minggu depan dari tab Rekomendasi", "Kuota flash sale terjual ≥ 70%"),
        ],
        "Bulanan": [
            (f"Review pencapaian target sales {target_text}", "Realisasi ≥ 100% target" if target else "Realisasi ≥ prediksi"),
            ("Review akurasi prediksi di Evaluasi model (MAPE/WAPE)", "MAPE agregat ≤ 15%"),
            ("Jadwalkan markdown SKU Slow-Moving/Dead Stock", "Nilai stok mati turun"),
            ("Susun kalender konten media sosial 1 bulan", "10 SKU ter-expose sesuai jadwal"),
        ],
    }
