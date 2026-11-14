"""Exposure konten Shopee Video & media sosial: produk mana dibuatkan konten, kapan tayang, dan brief-nya.

Pemilihan produk (hanya SKU yang terjual 90 hari terakhir dan stoknya cukup ≥ 14 hari termasuk DC, supaya penonton
yang tertarik tidak menemui stok habis):
- Produk andalan   : prediksi omzet tertinggi (top 30).
- Sedang naik      : penjualan 14 hari terakhir naik ≥ 30% dibanding 14 hari sebelumnya.
- Stok lebih       : stok toko di atas SS cukup ≥ 90 hari → konten membantu memutar stok.
- Potensi viral    : nama/deskripsi punya unsur yang mudah jadi konten viral (demo visual, before–after, masalah→solusi, fitur unik,
                     harga terjangkau) → skor viral ≥ 0,5.
- Banyak dilihat, jarang dibeli: klik iklan ≥ 50 tetapi konversi < 1% → konten demo/penjelasan untuk menaikkan konversi.
Video Shopee terus di-crawl selama produk tidak diturunkan, jadi produk bernilai tinggi diutamakan.
Skor = 30% peringkat prediksi omzet + 15% nilai produk (harga) + 15% potensi viral + 15% margin + 15% tren 14 hari + 5% kesiapan
stok + 5% bonus segmen naik/stok lebih/viral.
Jadwal: tiap minggu `per_week` konten, ditaruh di hari & jam dengan pesanan terbanyak untuk kategori produk itu
(dari riwayat pesanan), maks. 2 konten per hari, produk yang sama tidak diulang dalam 14 hari.
"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta

import numpy as np
import pandas as pd

HERO = "Produk andalan"
RISING = "Sedang naik"
OVERSTOCK = "Stok lebih"
LOW_CONV = "Banyak dilihat, jarang dibeli"
VIRAL = "Potensi viral"
SEGMENTS = (HERO, RISING, OVERSTOCK, VIRAL, LOW_CONV)
VIRAL_MIN = 0.5
VIRAL_CUES = (
    ("demo visual", r"otomatis|sensor|lipat|portable|portabel|magnet|led\b|lampu|semprot|jet|putar|spin|teleskopik|anti\s*air|kedap|waterproof|tahan\s*panas"),
    ("before–after", r"estetik|minimalis|modern|motif|mewah|glossy|granit|granite|marmer|kayu|dekor"),
    ("masalah → solusi", r"anti\s*(karat|rayap|bocor|mampet|bau|slip|jamur)|hemat\s*(air|listrik)|tanpa\s*bor|mudah\s*dipasang|praktis|cepat\s*kering|bersih"),
    ("fitur unik", r"multifungsi|serbaguna|2\s*in\s*1|3\s*in\s*1|buy\s*\d|gratis|bonus|set\s*lengkap|garansi\s*\d+"),
)
READY_DAYS = 14
HERO_TOP = 30
REPEAT_DAYS = 14
WEEKDAYS = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")

# kategori: (kata kunci nama, format utama, sudut cerita, hook masalah, hashtag)
PLAYBOOK: tuple[tuple[str, tuple[str, ...], str, str, str, str], ...] = (
    ("Water heater", ("water heater", "pemanas air"), "Shopee Video 30 dtk: uji air panas + hemat listrik (watt)",
     "mandi air hangat tanpa tagihan listrik membengkak", "Mandi pagi masih kedinginan? Air hangat siap dalam hitungan menit.", "#waterheater #airpanas #kamarmandi"),
    ("Kloset", ("kloset", "closet", "toilet"), "Shopee Video 30–45 dtk: before–after kamar mandi + uji siram",
     "kamar mandi lama jadi modern, hemat air", "Kloset lama sering mampet & boros air? Ganti yang sekali siram bersih.", "#kloset #kamarmandiminimalis #renovasikamarmandi"),
    ("Bak cuci piring", ("cuci piring", "kitchen sink", "bak cuci", "dapur"), "Shopee Video: before–after area cuci dapur + uji lebar bak",
     "dapur lebih rapi, cuci piring lebih lega", "Cuci piring numpuk & bak sempit? Bak granit lebar, dapur lebih rapi.", "#dapur #bakcucipiring #dapurminimalis"),
    ("Wastafel", ("wastafel", "washtafel", "lavatory", "sink"), "Shopee Video: before–after sudut wastafel + ukuran pas",
     "ruang sempit terasa lega", "Sudut kamar mandi sempit? Wastafel gantung bikin ruang terasa lega.", "#wastafel #kamarmandi #interiorrumah"),
    ("Shower", ("shower", "jet shower", "hand shower", "bidet"), "Shopee Video: uji tekanan air + panas–dingin",
     "mandi lebih nyaman seperti di hotel", "Air shower lemah? Rasakan semburan rata seperti di hotel.", "#shower #kamarmandihotel #renovasirumah"),
    ("Pintu & jendela", ("pintu", "jendela", "upvc", "door"), "Shopee Video: anti rayap & anti air + cara buka-tutup",
     "tidak lapuk, tidak dimakan rayap", "Pintu kamar mandi lapuk & dimakan rayap? Ganti uPVC, tahan air seumur pakai.", "#pintukamarmandi #upvc #antirayap"),
    ("Pompa", ("pompa", "pump"), "Shopee Video: demo daya sedot + suara halus",
     "air lancar ke lantai atas", "Air di lantai atas kecil? Pompa yang tepat bikin keran deras lagi.", "#pompaair #airlancar #rumah"),
    ("Sealant & lem", ("sealant", "silicone", "silikon", "lem ", "lem-", "epoxy", "glue", "perekat"), "Shopee Video 15–20 dtk: uji rekat / uji kedap air",
     "perbaikan sendiri tanpa tukang", "Celah bocor & sambungan lepas? Perbaiki sendiri dalam 5 menit.", "#lem #sealant #diyrumah"),
    ("Glass block & lantai", ("glass block", "glassblock", "vinyl", "lantai", "keramik"), "Shopee Video: before–after ruangan",
     "ruangan estetik tanpa renovasi besar", "Dinding & lantai membosankan? Ubah suasana ruangan tanpa bongkar total.", "#glassblock #vinyllantai #dekorasirumah"),
    ("Pembersih", ("mop", "pel", "sapu", "pembersih", "wiper", "clean"), "Shopee Video 15 dtk: uji bersih sekali usap",
     "bersih-bersih lebih cepat", "Ngepel bikin pegal? Sekali dorong lantai langsung bersih & kering.", "#alatkebersihan #rumahbersih #lifehack"),
    ("Rak & gantungan", ("rak", "gantungan", "hook", "kait"), "Shopee Video: pasang tanpa bor + uji beban",
     "rapi tanpa bor dinding", "Kamar mandi berantakan? Rak tempel tanpa bor, langsung rapi.", "#rakdinding #tanpabor #rumahrapi"),
    ("Kunci & handle", ("handle", "gagang", "kunci", "lock", "engsel"), "Shopee Video: detail material + cara pasang",
     "pintu lebih aman & awet", "Gagang pintu goyang & berkarat? Ganti yang anti karat dan kokoh.", "#handlepintu #kuncipintu #rumahaman"),
    ("Perkakas", ("tool", "tang", "obeng", "gergaji", "bor", "meteran", "tangga", "mirror"), "Shopee Video: demo fungsi di proyek nyata",
     "kerja proyek lebih cepat", "Proyek rumah sering tertunda? Alat yang tepat bikin kerja dua kali lebih cepat.", "#perkakas #tukang #diy"),
)
DEFAULT_PLAY = ("Aksesoris", (), "Shopee Video: tunjukkan produk terpasang di rumah", "melengkapi renovasi",
                "Detail kecil yang membuat renovasi terasa selesai.", "#renovasirumah #rumahminimalis")
BRANDS = ("Tidy", "Ceramax", "Dextone", "Heatsafe", "Aquamax", "Zehn", "Grandeur", "Meny", "Quickie", "Doorway", "Looma")
NAME_POINTS = (
    (re.compile(r"garansi\s*(\d+)\s*(tahun|th)", re.I), "Garansi {0} tahun"),
    (re.compile(r"include packing kayu", re.I), "Dikirim dengan packing kayu, aman sampai rumah"),
    (re.compile(r"anti\s*karat|sus\s*304|stainless", re.I), "Anti karat (stainless)"),
    (re.compile(r"anti\s*rayap", re.I), "Anti rayap"),
    (re.compile(r"tanpa\s*bor", re.I), "Pasang tanpa bor"),
    (re.compile(r"(\d+(?:[.,]\d+)?(?:/\d+)?)\s*(?:l|liter)\b", re.I), "Kapasitas {0} liter"),
    (re.compile(r"(\d+)\s*x\s*(\d+)\s*(?:x\s*(\d+)\s*)?cm", re.I), "Ukuran {0}×{1} cm"),
    (re.compile(r"hemat\s*(air|listrik)", re.I), "Hemat {0}"),
)


def play_for(name: str) -> tuple[str, tuple[str, ...], str, str, str, str]:
    lower = f" {str(name or '').lower()} "
    for play in PLAYBOOK:
        if any(hint in lower for hint in play[1]):
            return play
    return DEFAULT_PLAY


def category_of(name: str) -> str:
    return play_for(name)[0]


def selling_points(name: str, description_points: list[str] | None = None, limit: int = 4) -> list[str]:
    """Poin jual dari nama produk (garansi, packing kayu, material, ukuran) + kalimat terukur dari deskripsi."""
    out: list[str] = []
    for pattern, template in NAME_POINTS:
        match = pattern.search(str(name or ""))
        if match:
            out.append(template.format(*[g for g in match.groups() if g] or [""]))
    for point in description_points or []:
        point = str(point or "").strip()
        if not _clean_point(point) or point in out:
            continue
        out.append(point if len(point) <= 110 else point[:107].rsplit(" ", 1)[0] + "…")
    return out[:limit]


def _clean_point(point: str) -> bool:
    """Kalimat deskripsi utuh: diawali huruf besar, kurung seimbang, tidak sekadar sisa potongan."""
    if len(point) < 12 or not point[0].isupper():
        return False
    return point.count("(") == point.count(")")


def brand_of(name: str) -> str:
    lower = str(name or "").lower()
    return next((b for b in BRANDS if b.lower() in lower), "")


def timing(orders: pd.DataFrame | None, category_by_key: dict[str, str], key: str = "sku") -> dict[str, tuple[int, str]]:
    """Hari (0=Senin) dan jam tayang (2 jam) dengan pesanan terbanyak per kategori; kunci "*" = seluruh toko.

    Jam malam 00–06 tidak dipakai. Konten diunggah ±1 jam sebelum jam ramai itu."""
    out: dict[str, tuple[int, str]] = {"*": (5, "19.00–21.00")}
    if orders is None or orders.empty or "order_time" not in orders.columns or key not in orders.columns:
        return out
    times = pd.to_datetime(orders["order_time"], errors="coerce")
    frame = pd.DataFrame({"cat": orders[key].astype(str).map(category_by_key).fillna(""), "dow": times.dt.dayofweek, "hour": times.dt.hour}).dropna()
    frame = frame.loc[frame["hour"] >= 6]

    def best(part: pd.DataFrame) -> tuple[int, str]:
        dow = int(part["dow"].value_counts().idxmax())
        hours = part["hour"].value_counts().reindex(range(6, 24), fill_value=0)
        pair = (hours + hours.shift(-1, fill_value=0)).iloc[:-1]
        start = int(pair.idxmax())
        return dow, f"{start:02d}.00–{start + 2:02d}.00"

    if not frame.empty:
        out["*"] = best(frame)
        for cat, part in frame.loc[frame["cat"] != ""].groupby("cat"):
            if len(part) >= 30:
                out[str(cat)] = best(part)
    return out


def viral_score(name: str, description: str = "", price: float = 0.0) -> tuple[float, list[str]]:
    """Skor 0–1 seberapa mudah produk dibuat konten yang viral: unsur demo visual, before–after, masalah→solusi, fitur unik
    (dari nama + deskripsi), ditambah harga terjangkau (< Rp 500 rb mudah dibeli spontan dari video)."""
    text = f"{name} {description}".lower()
    hits = [label for label, pattern in VIRAL_CUES if re.search(pattern, text)]
    score = len(hits) / len(VIRAL_CUES) * 0.8 + (0.2 if 0 < price < 500_000 else 0.1 if 0 < price < 1_500_000 else 0.0)
    return min(score, 1.0), hits


def pick(items: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(kandidat konten berskor & bersegmen, ditunda karena stok). items: sku, label, nama, harga, harian, m_sales, stok,
    ada_stok, ss, dc, terjual, momentum, margin_pct, klik, terjual_iklan, poin_deskripsi (list)."""
    cols = ["sku", "label", "nama", "segmen", "skor", "kategori", "harga", "omzet_30", "hari_stok", "momentum", "alasan", "poin"]
    if items is None or items.empty:
        return pd.DataFrame(columns=cols), pd.DataFrame(columns=["SKU · produk · varian", "Alasan"])
    work = items.loc[(pd.to_numeric(items["harga"], errors="coerce") > 0) & (pd.to_numeric(items["terjual"], errors="coerce") > 0)].copy()
    if work.empty:
        return pd.DataFrame(columns=cols), pd.DataFrame(columns=["SKU · produk · varian", "Alasan"])
    def num(column: str, default: float = 0.0) -> pd.Series:
        if column not in work.columns:
            return pd.Series(default, index=work.index, dtype=float)
        return pd.to_numeric(work[column], errors="coerce").fillna(default)

    daily, stok, ss, dc = num("harian"), num("stok"), num("ss"), num("dc").clip(lower=0)
    known = work["ada_stok"].fillna(False).astype(bool)
    site = stok.where(known, 0.0)
    ready = (site + dc) / daily.where(daily > 0)
    cover = ((site - ss) / daily.where(daily > 0)).where(known)
    excess = (site - ss - daily * 30).where(known)
    klik, sold_ads = num("klik"), num("terjual_iklan")
    conv = (sold_ads / klik.where(klik > 0)) * 100
    momentum, margin = num("momentum"), num("margin_pct", np.nan)
    m_sales = num("m_sales")
    rank = m_sales.rank(ascending=False, method="first")
    desc = work["deskripsi"].fillna("").astype(str) if "deskripsi" in work.columns else pd.Series("", index=work.index)
    viral = [viral_score(n, d, p) for n, d, p in zip(work["nama"].astype(str), desc, num("harga"))]
    work = work.assign(_ready=ready, _cover=cover, _excess=excess, _conv=conv, _mom=momentum, _rank=rank, _m=m_sales,
                       _viral=[v for v, _h in viral], _viral_hits=[h for _v, h in viral])
    delayed = work.loc[~(work["_ready"] >= READY_DAYS)]
    skipped = pd.DataFrame({"SKU · produk · varian": delayed["label"],
                            "Alasan": [f"stok hanya cukup {r:.0f} hari (toko + DC): restock dulu sebelum dibuatkan konten" if r == r else "data stok belum ada"
                                       for r in delayed["_ready"]]})
    work = work.loc[work["_ready"] >= READY_DAYS]

    def segment(r) -> str:
        if r["_mom"] >= 0.3 and r["_m"] > 0 and r["_rank"] <= HERO_TOP * 4:
            return RISING
        if r["_cover"] == r["_cover"] and r["_cover"] >= 90 and r["_excess"] >= 5:
            return OVERSTOCK
        if r["_rank"] <= HERO_TOP:
            return HERO
        if r["_viral"] >= VIRAL_MIN and r["_rank"] <= HERO_TOP * 6:
            return VIRAL
        if klik.get(r.name, 0) >= 50 and r["_conv"] == r["_conv"] and r["_conv"] < 1:
            return LOW_CONV
        return ""

    work["segmen"] = work.apply(segment, axis=1)
    work = work.loc[work["segmen"] != ""]
    if work.empty:
        return pd.DataFrame(columns=cols), skipped
    rank_pct = 1 - work["_m"].rank(pct=True, ascending=False) + 1 / len(work)
    margin_n = (margin.reindex(work.index).clip(-10, 40).fillna(10) + 10) / 50
    mom_n = (work["_mom"].clip(-0.5, 1.0) + 0.5) / 1.5
    ready_n = (work["_ready"] / 60).clip(0, 1)
    bonus = work["segmen"].isin([RISING, OVERSTOCK, VIRAL]).astype(float)
    value_n = num("harga").reindex(work.index).clip(lower=1).map(math.log10).rank(pct=True)
    work["skor"] = (0.30 * rank_pct + 0.15 * value_n + 0.15 * work["_viral"] + 0.15 * margin_n + 0.15 * mom_n + 0.05 * ready_n + 0.05 * bonus) * 100
    reasons = []
    for _i, r in work.iterrows():
        bits = [f"prediksi omzet peringkat {int(r['_rank'])}"]
        if r["_mom"]:
            bits.append(f"tren 14 hari {r['_mom'] * 100:+.0f}%")
        if r["segmen"] == OVERSTOCK:
            bits.append(f"stok cukup {r['_cover']:.0f} hari")
        if r["_viral_hits"]:
            bits.append("potensi viral: " + ", ".join(r["_viral_hits"]))
        if r["segmen"] == LOW_CONV:
            bits.append(f"{klik[r.name]:.0f} klik, konversi {r['_conv']:.1f}%".replace(".", ","))
        bits.append(f"stok siap {min(r['_ready'], 999):.0f} hari")
        reasons.append("; ".join(bits))
    work["alasan"] = reasons
    work["kategori"] = work["nama"].map(category_of)
    # Prediksi 30 hari = laju harian × harga × 30, sama dengan "Prediksi omzet 30 hari" di Kapasitas gudang
    # (m_sales memakai jendela bulan 28–31 hari dan QTY dibulatkan ke bawah).
    work["omzet_30"] = num("harga").reindex(work.index) * daily.reindex(work.index) * 30
    work["hari_stok"] = work["_ready"]
    work["momentum"] = work["_mom"]
    work["poin"] = [selling_points(n, p) for n, p in zip(work["nama"], work.get("poin_deskripsi", pd.Series([[]] * len(work), index=work.index)))]
    return work.sort_values("skor", ascending=False)[cols].reset_index(drop=True), skipped


def _price_text(value: float) -> str:
    return "Rp " + f"{math.floor(value / 1000) * 1000:,.0f}".replace(",", ".")


def brief(row: dict, slot_index: int = 0) -> dict:
    """Brief konten satu produk: format, hook, poin jual, ajakan harga, hashtag, dan naskah 30 detik."""
    play = play_for(row["nama"])
    points = list(row.get("poin") or [])
    brand = brand_of(row["nama"])
    price = float(row.get("harga") or 0)
    hook = play[4] if row.get("segmen") != LOW_CONV else f"Masih ragu pilih {play[0].lower()}? Lihat langsung cara pakainya."
    if row.get("segmen") == OVERSTOCK:
        cta = f"Harga spesial mulai {_price_text(price)} — stok terbatas di Mitra10 Official Store, klik keranjang kuning."
    else:
        cta = f"Mulai {_price_text(price)} di Mitra10 Official Store — klik keranjang kuning di video."
    tags = " ".join(dict.fromkeys(f"#mitra10 #mitra10officialstore {play[5]}".split() + ([f"#{brand.lower()}"] if brand else [])))
    live = price >= 500_000 and row.get("segmen") in (HERO, LOW_CONV)
    fmt = play[2] + (" · lanjutkan sesi Shopee Live tanya-jawab (produk bernilai tinggi)" if live else "") + " · unggah ulang ke Reels & TikTok"
    p = points + ["", "", ""]
    script = "\n".join([
        f"0–3 dtk  : {hook}",
        f"3–12 dtk : tunjukkan {p[0] or 'produk terpasang di rumah'}" + (f" dan {p[1]}" if p[1] else ""),
        f"12–22 dtk: {(p[2] + '; ') if p[2] else ''}tunjukkan hasilnya: {play[3]}",
        f"22–30 dtk: {cta}",
    ])
    return {"Format": fmt, "Hook": hook, "Poin jual": " • ".join(points) if points else "–", "Ajakan": cta, "Hashtag": tags, "Naskah 30 dtk": script}


def calendar(cands: pd.DataFrame, start: date, *, weeks: int = 4, per_week: int = 5, times: dict[str, tuple[int, str]] | None = None,
             per_day: int = 2) -> pd.DataFrame:
    """Jadwal konten mingguan dengan brief per baris. start = Senin minggu pertama."""
    cols = ["Tanggal", "Hari", "Jam tayang", "Segmen", "SKU", "Produk", "Kategori", "Format", "Hook", "Poin jual", "Ajakan", "Hashtag",
            "Omzet 30 hari", "Stok siap (hari)", "Alasan dipilih", "Naskah 30 dtk"]
    if cands is None or cands.empty:
        return pd.DataFrame(columns=cols)
    times = times or {"*": (5, "19.00–21.00")}
    pool = cands.to_dict("records")
    by_seg = {s: [r for r in pool if r["segmen"] == s] for s in SEGMENTS}
    used: dict[str, date] = {}
    rows = []
    for week in range(weeks):
        monday = start + timedelta(days=7 * week)
        load: dict[int, int] = {}
        chosen: list[dict] = []
        turn = 0
        while len(chosen) < per_week:
            progressed = False
            for seg in (HERO, VIRAL, OVERSTOCK, RISING, HERO, LOW_CONV, VIRAL):
                if len(chosen) >= per_week:
                    break
                for r in by_seg[seg]:
                    last = used.get(r["sku"])
                    if r in chosen or (last is not None and (monday - last).days < REPEAT_DAYS):
                        continue
                    chosen.append(r)
                    progressed = True
                    break
            turn += 1
            if not progressed or turn > per_week * 3:
                break
        for index, r in enumerate(chosen):
            dow, hours = times.get(r["kategori"], times["*"])
            for shift in range(7):
                d = (dow + shift) % 7
                if load.get(d, 0) < per_day:
                    break
            load[d] = load.get(d, 0) + 1
            day = monday + timedelta(days=d)
            used[r["sku"]] = monday
            b = brief(r, index)
            rows.append({"Tanggal": day, "Hari": WEEKDAYS[d], "Jam tayang": hours, "Segmen": r["segmen"], "SKU": r["sku"], "Produk": r["label"],
                         "Kategori": r["kategori"], "Format": b["Format"], "Hook": b["Hook"], "Poin jual": b["Poin jual"], "Ajakan": b["Ajakan"],
                         "Hashtag": b["Hashtag"], "Omzet 30 hari": r["omzet_30"], "Stok siap (hari)": min(r["hari_stok"], 999),
                         "Alasan dipilih": r["alasan"], "Naskah 30 dtk": b["Naskah 30 dtk"]})
    return pd.DataFrame(rows, columns=cols).sort_values(["Tanggal", "Jam tayang"]).reset_index(drop=True)
