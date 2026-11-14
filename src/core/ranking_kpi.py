"""KPI ranking kategori Shopee per periode (bulan, kuartal, semester, tahun).

Sumber: unggahan ranking kompetitor per periode. Tiap daftar = satu ranking kategori Shopee (produk teratas + produk
toko sendiri). Kolom yang dibaca: Kategori, Ranking, Change of Rank, Shop Name, Products Name, Toko sendiri, dan bila ada
Sales, Qty, Views (nilai yang menjadi dasar penilaian ranking) serta Dasar ranking (Sales / Qty / Views).

Rekap KPI per kategori:
- Home & Living: SEMUA kategori dipantau (yang belum ada datanya tetap tampil sebagai "Belum ada data").
- Elektronik: hanya kategori yang memuat produk Mitra10 (muncul di daftar ranking, atau ditandai di daftar kategori).
- Periode yang tidak diunggah langsung disusun dari periode lebih kecil di dalamnya (mis. kuartal dari 3 bulan,
  tahun dari kuartal): peringkat = periode terakhir yang ada, plus peringkat terbaik dan rata-rata.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from datetime import date

import numpy as np
import pandas as pd

LEVELS = ("Bulan", "Kuartal", "Semester", "Tahun")
HL, EL = "Home & Living", "Elektronik"
UNMAPPED = "Belum dipetakan"
GROUPS = (HL, EL, UNMAPPED)
BASES = ("Sales", "Qty", "Views")
ANY_BASIS = "Ranking unggahan"
NO_DATA = "Belum ada data"
NOT_LISTED = "Tidak ada produk kita"
TIERS = ((10, "Sudah Top 10"), (50, "Dekat"), (500, "Menengah"), (float("inf"), "Jauh"))
STATUS_ORDER = tuple(name for _l, name in TIERS) + (NOT_LISTED, NO_DATA)
ROW_COLUMNS = ["periode", "daftar", "kategori", "grup", "dasar", "rank", "change", "shop", "product", "ours", "sales", "qty", "views"]

MONTHS = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember")
SHORT = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
_MONTH_WORDS = {**{m.lower(): i + 1 for i, m in enumerate(MONTHS)}, **{s.lower(): i + 1 for i, s in enumerate(SHORT)},
                "january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7, "august": 8, "october": 10, "oct": 10,
                "december": 12, "dec": 12, "aug": 8, "agt": 8, "ags": 8, "sept": 9}

# Daftar awal kategori Shopee (level 2) yang relevan untuk produk Mitra10. Nama mengikuti menu Shopee Indonesia dan bisa
# diubah di aplikasi agar sama persis dengan nama di Seller Centre. Kata kunci dipakai menebak kategori daftar lama
# yang tidak memuat nama kategori.
DEFAULT_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    (HL, "Kamar Mandi", "kloset closet toilet shower wastafel kran keran bathtub drain jet washer sabun tisu urinoir bidet"),
    (HL, "Perkakas & Perbaikan Rumah", "bor gerinda obeng palu tang meteran kunci cat lem dempul semen keramik pipa engsel gembok handle silikon sealant lakban gergaji amplas"),
    (HL, "Peralatan Dapur", "panci wajan pisau talenan sink bak cuci piring rak piring spatula sutil kompor gas regulator"),
    (HL, "Peralatan Makan & Minum", "piring gelas mangkok mug sendok garpu botol tumbler teko"),
    (HL, "Penyimpanan & Rak", "rak box kontainer laci lemari plastik organizer gantungan hanger keranjang"),
    (HL, "Furnitur", "kursi meja sofa kasur ranjang lemari pakaian bufet"),
    (HL, "Dekorasi", "jam dinding cermin vas wallpaper stiker tirai gorden karpet keset bunga hiasan"),
    (HL, "Lampu", "lampu bohlam led downlight panel lamp lampu sorot fitting"),
    (HL, "Perlengkapan Kebersihan", "sapu pel ember tempat sampah sikat pembersih lap kemoceng serokan"),
    (HL, "Taman", "selang sprinkler pot tanaman pupuk gunting rumput taman"),
    (HL, "Perlengkapan Tidur", "sprei bantal guling selimut bed cover"),
    (HL, "Pengharum Ruangan & Aromaterapi", "pengharum diffuser aromaterapi"),
    (HL, "Keamanan & Keselamatan Rumah", "cctv alarm smart lock brankas pemadam apar door lock"),
    (HL, "Perlengkapan Cuci & Jemur", "jemuran gantungan baju keranjang cucian papan setrika"),
    (HL, "Pengendali Hama", "obat nyamuk raket nyamuk perangkap tikus anti rayap"),
    (HL, "Perlengkapan Ibadah", "sajadah tasbih"),
    (HL, "Perlengkapan Pesta", "balon dekorasi pesta"),
    (HL, "Perlengkapan Rumah Lainnya", ""),
    (EL, "Peralatan Dapur Elektronik", "rice cooker blender mixer air fryer microwave oven kompor listrik dispenser kettle juicer"),
    (EL, "Pendingin & Pemanas Ruangan", "ac kipas angin air cooler exhaust pemanas ruangan"),
    (EL, "Peralatan Rumah Tangga Besar", "kulkas mesin cuci water heater pemanas air pompa air freezer"),
    (EL, "Perawatan Rumah Elektronik", "vacuum robot penyedot debu"),
    (EL, "Perawatan Pakaian Elektronik", "setrika steamer"),
    (EL, "TV & Aksesoris", "tv bracket antena"),
    (EL, "Kabel, Stop Kontak & Baterai", "kabel stop kontak terminal colokan baterai saklar"),
    (EL, "Elektronik Lainnya", ""),
)

ALIASES = {
    "periode": ("periode", "period", "bulan", "month"),
    "kategori": ("kategori", "category", "category name", "nama kategori", "kategori shopee"),
    "grup": ("grup", "kategori induk", "parent category", "kategori utama", "main category", "group"),
    "dasar": ("dasar ranking", "ranking by", "metric", "metrik", "dasar"),
    "rank": ("ranking", "peringkat", "rank"),
    "change": ("change of rank", "perubahan peringkat", "perubahan"),
    "shop": ("shop name", "nama toko", "toko", "seller"),
    "product": ("products name", "product name", "nama produk", "judul produk", "produk"),
    "own": ("toko sendiri", "my shop", "toko saya"),
    "sales": ("sales", "sales value", "penjualan", "penjualan (rp)", "omzet", "omset", "gmv", "nilai penjualan"),
    "qty": ("qty", "quantity", "units sold", "unit terjual", "terjual", "produk terjual", "jumlah terjual", "sold"),
    "views": ("views", "view", "dilihat", "product views", "pengunjung", "kunjungan", "page views", "jumlah dilihat"),
}


# ---------------------------------------------------------------- periode


def period_id(level: str, year: int, n: int = 1) -> str:
    if level == "Bulan":
        return f"{year:04d}-{n:02d}"
    if level == "Kuartal":
        return f"{year:04d}-Q{n}"
    if level == "Semester":
        return f"{year:04d}-S{n}"
    return f"{year:04d}"


def level_of(pid: str) -> str:
    pid = str(pid)
    if "-Q" in pid:
        return "Kuartal"
    if "-S" in pid:
        return "Semester"
    if "-" in pid:
        return "Bulan"
    return "Tahun"


def months_of(pid: str) -> list[tuple[int, int]]:
    pid = str(pid)
    year = int(pid[:4])
    level = level_of(pid)
    if level == "Bulan":
        span = [int(pid[5:7])]
    elif level == "Kuartal":
        q = int(pid.split("-Q")[1])
        span = list(range(3 * q - 2, 3 * q + 1))
    elif level == "Semester":
        s = int(pid.split("-S")[1])
        span = list(range(6 * s - 5, 6 * s + 1))
    else:
        span = list(range(1, 13))
    return [(year, m) for m in span]


def period_label(pid: str) -> str:
    pid = str(pid)
    level, year = level_of(pid), int(pid[:4])
    months = months_of(pid)
    if level == "Bulan":
        return f"{MONTHS[months[0][1] - 1]} {year}"
    if level == "Tahun":
        return f"Tahun {year}"
    span = f"{SHORT[months[0][1] - 1]}–{SHORT[months[-1][1] - 1]}"
    n = pid.split("-Q" if level == "Kuartal" else "-S")[1]
    return f"{'Q' if level == 'Kuartal' else 'Semester '}{n} {year} ({span})"


def short_label(pid: str) -> str:
    pid = str(pid)
    level, year = level_of(pid), int(pid[:4])
    if level == "Bulan":
        return f"{SHORT[int(pid[5:7]) - 1]} {year}"
    if level == "Kuartal":
        return f"Q{pid.split('-Q')[1]} {year}"
    if level == "Semester":
        return f"S{pid.split('-S')[1]} {year}"
    return str(year)


def periods_in_year(level: str, year: int) -> list[str]:
    count = {"Bulan": 12, "Kuartal": 4, "Semester": 2, "Tahun": 1}[level]
    return [period_id(level, year, n) for n in range(1, count + 1)]


def end_key(pid: str) -> tuple[int, int, int]:
    """Urutan periode: akhir periode dulu, lalu periode yang lebih pendek (lebih spesifik) belakangan."""
    months = months_of(pid)
    return (months[-1][0], months[-1][1], -len(months))


def contains(outer: str, inner: str) -> bool:
    return set(months_of(inner)) <= set(months_of(outer))


def parse_period(text: object, default_year: int | None = None) -> str | None:
    """Teks periode → id. Contoh: 2026-07, 07/2026, Juli 2026, Q3 2026, Kuartal 3 2026, Q4 OKT - DES, S2 2026, 2026."""
    raw = str(text or "").strip().lower()
    if not raw or raw in {"nan", "none"}:
        return None
    if isinstance(text, (pd.Timestamp, date)):
        return period_id("Bulan", text.year, text.month)
    years = re.findall(r"(20\d{2})", raw)
    year = int(years[0]) if years else (default_year or date.today().year)
    m = re.search(r"\b(?:q|kuartal|quarter|kw|triwulan)\s*-?\s*([1-4])\b", raw) or re.search(r"\b([1-4])\s*q\b", raw)
    if m:
        return period_id("Kuartal", year, int(m.group(1)))
    m = re.search(r"\b(?:s|smt|semester|h)\s*-?\s*([12])\b", raw)
    if m:
        return period_id("Semester", year, int(m.group(1)))
    m = re.fullmatch(r"(20\d{2})[-/.](\d{1,2})(?:[-/.]\d{1,2})?(?: .*)?", raw) or re.fullmatch(r"(\d{1,2})[-/.](20\d{2})", raw)
    if m:
        a, b = m.group(1), m.group(2)
        month = int(b) if len(a) == 4 else int(a)
        if 1 <= month <= 12:
            return period_id("Bulan", year, month)
    words = re.findall(r"[a-z]+", raw)
    months = [_MONTH_WORDS[w] for w in words if w in _MONTH_WORDS]
    if months:
        if len(months) >= 2 and months[-1] - months[0] == 2 and months[0] % 3 == 1:
            return period_id("Kuartal", year, (months[0] + 2) // 3)
        if len(months) >= 2 and months[-1] - months[0] == 5 and months[0] in (1, 7):
            return period_id("Semester", year, 1 if months[0] == 1 else 2)
        return period_id("Bulan", year, months[0])
    if re.fullmatch(r"(?:tahun\s*)?20\d{2}", raw):
        return period_id("Tahun", year)
    return None


# ---------------------------------------------------------------- baca unggahan


def _norm(value: object) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def parse_number(value: object) -> float:
    """'Rp1.234.567', '1,2jt', '15,3RB', '2.5k', 1234 → angka."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    text = str(value).strip().lower().replace("rp", "").replace(" ", "").replace("+", "")
    if not text or text in {"-", "–", "nan", "none"}:
        return np.nan
    mult = 1.0
    for suffix, factor in (("miliar", 1e9), ("jt", 1e6), ("juta", 1e6), ("rb", 1e3), ("ribu", 1e3), ("k", 1e3), ("m", 1e6)):
        if text.endswith(suffix):
            text, mult = text[: -len(suffix)], factor
            break
    if mult != 1.0:
        text = text.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}([.,]\d{3})+", text):
        text = re.sub(r"[.,]", "", text)
    else:
        text = text.replace(".", "").replace(",", ".") if re.search(r"\.\d{3}", text) else text.replace(",", ".")
    try:
        return float(text) * mult
    except ValueError:
        return np.nan


def _header_row(raw: pd.DataFrame) -> int | None:
    for i in range(min(len(raw), 40)):
        cells = {_norm(v) for v in raw.iloc[i].tolist()}
        if cells & set(ALIASES["rank"]) and cells & set(ALIASES["product"]):
            return i
    return None


def _column_map(headers: list[object]) -> dict[str, int]:
    names = [_norm(h) for h in headers]
    out: dict[str, int] = {}
    for field, aliases in ALIASES.items():
        for alias in aliases:
            if alias in names and names.index(alias) not in out.values():
                out[field] = names.index(alias)
                break
    return out


def split_path(text: object) -> tuple[str, str]:
    """'Perlengkapan Rumah > Kamar Mandi' → ('Home & Living', 'Kamar Mandi')."""
    parts = [p.strip() for p in re.split(r"\s*(?:>|›|/|»)\s*", str(text or "").strip()) if p.strip()]
    if not parts:
        return "", ""
    top = group_of_name(parts[0])
    if top and len(parts) > 1:
        return top, " > ".join(parts[1:])
    return "", " > ".join(parts)


def group_of_name(text: object) -> str:
    t = _norm(text)
    if re.search(r"rumah|home|living", t):
        return HL
    if re.search(r"elektronik|electronic", t):
        return EL
    return ""


def basis_of(text: object) -> str:
    t = _norm(text)
    if re.search(r"sales|penjualan|omzet|omset|gmv|nilai", t):
        return "Sales"
    if re.search(r"qty|unit|terjual|sold|kuantitas", t):
        return "Qty"
    if re.search(r"view|dilihat|kunjung|pengunjung", t):
        return "Views"
    return ""


def _sheet_rows(raw: pd.DataFrame, sheet: str, many_sheets: bool) -> list[dict]:
    head = _header_row(raw)
    if head is None:
        return []
    cols = _column_map(raw.iloc[head].tolist())
    if "rank" not in cols or "product" not in cols:
        return []
    header_cells = {_norm(v) for v in raw.iloc[head].tolist()}
    sheet_cat = sheet if many_sheets or not re.fullmatch(r"(sheet|lembar)\s*\d*", _norm(sheet)) else ""
    records: list[dict] = []
    current: dict | None = None
    block, own_section, position, title = 1, False, 0, ""
    starter = "shop" if "shop" in cols else "product"

    def cell(row, field):
        idx = cols.get(field)
        if idx is None:
            return None
        v = row[idx]
        return None if v is None or (isinstance(v, float) and np.isnan(v)) or str(v).strip() == "" else v

    for i in range(head + 1, len(raw)):
        row = raw.iloc[i].tolist()
        rank = cell(row, "rank")
        rank_text = _norm(rank) if rank is not None else ""
        filled = [str(v).strip() for v in row if v is not None and not (isinstance(v, float) and np.isnan(v)) and str(v).strip()]
        if rank_text in ALIASES["rank"] or ({_norm(v) for v in filled} & header_cells and len({_norm(v) for v in filled} & header_cells) >= 2):
            block, own_section, position = block + 1, False, 0
            current = None
            continue
        if len(filled) == 1 and cell(row, starter) is None and cell(row, "product") is None and rank is None:
            title = filled[0]                       # baris judul daftar (mis. nama kategori di atas tabel)
            block, own_section, position = block + 1, False, 0
            current = None
            continue
        if rank_text and not re.fullmatch(r"#?\d+(?:\.0)?", rank_text):
            own_section = True                      # baris pemisah "My Shop" / "Toko saya"
            continue
        start = cell(row, starter)
        if start is not None:
            if not own_section:
                position += 1
            change = cell(row, "change")
            own = cell(row, "own")
            current = {
                "_sheet": sheet, "_block": block, "_title": title,
                "rank": rank_text.lstrip("#").replace(".0", "") or (None if own_section else str(position)),
                "change": "" if change is None else str(change).strip(),
                "shop": str(cell(row, "shop") or "").strip(), "product": None,
                "own_flag": own_section or _norm(change) in {"my shop", "toko saya"} or _norm(own) in {"true", "1", "ya", "yes", "y"},
            }
            for field in ("kategori", "grup", "dasar", "periode", "sales", "qty", "views"):
                current[field] = cell(row, field)
            records.append(current)
        if current is None:
            continue
        name = cell(row, "product")
        if name is not None and not current["product"]:
            current["product"] = str(name).strip()
        for field in ("kategori", "grup", "dasar", "periode", "sales", "qty", "views"):
            if current.get(field) is None:
                current[field] = cell(row, field)
    for r in records:
        if r.get("kategori") is None:
            r["kategori"] = r["_title"] or sheet_cat
    return [r for r in records if r.get("product")]


def parse_upload(data: bytes, filename: str) -> pd.DataFrame:
    """File ranking (ekspor Shopee 2 baris per produk, atau tabel biasa; satu atau banyak sheet) → baris rapi ROW_COLUMNS
    (kolom periode berisi teks dari file bila ada, akan diisi periode pilihan pengguna bila kosong)."""
    if str(filename).lower().endswith((".xlsx", ".xls", ".xlsm")):
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=object)
    else:
        text = data.decode("utf-8-sig", errors="ignore")
        sep = ";" if text.count(";") > text.count(",") else ","
        sheets = {"CSV": pd.read_csv(io.StringIO(text), header=None, dtype=object, sep=sep)}
    many = len(sheets) > 1
    rows: list[dict] = []
    for name, raw in sheets.items():
        rows += _sheet_rows(raw.reset_index(drop=True), str(name), many)
    if not rows:
        return pd.DataFrame(columns=ROW_COLUMNS)
    frame = pd.DataFrame(rows)
    out = pd.DataFrame({
        "periode": frame["periode"].map(lambda v: "" if v is None else str(v)),
        "rank": pd.to_numeric(frame["rank"].astype(str).str.replace(r"[^\d]", "", regex=True), errors="coerce"),
        "change": frame["change"].astype(str).replace({"None": "", "nan": "", "My Shop": "", "my shop": ""}),
        "shop": frame["shop"].astype(str),
        "product": frame["product"].astype(str),
        "ours": frame["own_flag"].astype(bool) | frame["shop"].astype(str).str.lower().str.contains("mitra10|mitra 10", regex=True),
        "sales": frame["sales"].map(parse_number), "qty": frame["qty"].map(parse_number), "views": frame["views"].map(parse_number),
    })
    groups, cats = [], []
    for kat, grp in zip(frame["kategori"], frame["grup"]):
        top, name = split_path(kat)
        cats.append(name)
        groups.append(group_of_name(grp) or top)
    out["kategori"], out["grup"] = cats, groups
    out["dasar"] = frame["dasar"].map(basis_of)
    keys = list(zip(frame["_sheet"], frame["_block"], out["kategori"], out["dasar"]))
    ids = {k: i + 1 for i, k in enumerate(dict.fromkeys(keys))}
    out["daftar"] = [ids[k] for k in keys]
    out = out.dropna(subset=["rank"])
    out["rank"] = out["rank"].astype(int)
    return out[ROW_COLUMNS].reset_index(drop=True)


def from_legacy(competitors: pd.DataFrame | None) -> pd.DataFrame:
    """Data menu Kompetitor lama (tanpa periode & nama kategori) → baris ROW_COLUMNS."""
    from src.core import category_rank as rk

    data = rk.prepare(competitors)
    if data.empty:
        return pd.DataFrame(columns=ROW_COLUMNS)
    out = data.copy()
    out["periode"], out["kategori"], out["grup"], out["dasar"] = "", "", "", ""
    out["sales"], out["qty"], out["views"] = np.nan, np.nan, np.nan
    return out[ROW_COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------- kategori


def default_master() -> pd.DataFrame:
    return pd.DataFrame([{"Grup": g, "Kategori": k, "Kata kunci": w, "Ada produk kita": g == HL} for g, k, w in DEFAULT_CATEGORIES])


def _tokens(text: object) -> set[str]:
    return set(re.findall(r"[a-z]{2,}", str(text or "").lower()))


def guess_category(names: list[str], master: pd.DataFrame) -> tuple[str, str, float]:
    """Tebak kategori daftar dari nama-nama produknya: kategori dengan kata kunci paling banyak cocok. (grup, kategori, skor)."""
    if master is None or master.empty:
        return "", "", 0.0
    counts = Counter(w for n in names for w in _tokens(n))
    best = ("", "", 0.0)
    for g, k, words in zip(master["Grup"], master["Kategori"], master["Kata kunci"]):
        keys = _tokens(words)
        score = sum(counts.get(w, 0) for w in keys) / max(len(names), 1)
        if score > best[2]:
            best = (str(g), str(k), float(score))
    return best if best[2] >= 0.3 else ("", "", best[2])


def canonical_category(name: str, master: pd.DataFrame) -> tuple[str, str]:
    """Nama kategori unggahan → (grup, nama baku) dari daftar kategori bila cocok (tanpa beda huruf besar/kecil & tanda)."""
    key = re.sub(r"[^a-z0-9]", "", str(name).lower())
    if master is not None and not master.empty and key:
        for g, k in zip(master["Grup"], master["Kategori"]):
            if re.sub(r"[^a-z0-9]", "", str(k).lower()) == key:
                return str(g), str(k)
    return "", str(name)


def list_table(rows: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    """Satu baris per daftar dalam unggahan untuk pemetaan kategori: Daftar, contoh produk, tebakan, Grup, Kategori."""
    out = []
    for daftar, part in rows.groupby("daftar", sort=True):
        part = part.sort_values("rank")
        names = part.loc[~part["ours"], "product"].tolist() or part["product"].tolist()
        kategori, grup = str(part["kategori"].iloc[0] or ""), str(part["grup"].iloc[0] or "")
        guess_g, guess_k, _score = guess_category(names, master)
        if kategori:
            canon_g, kategori = canonical_category(kategori, master)
            grup = grup or canon_g
        else:
            kategori, grup = guess_k, grup or guess_g
        from src.core.category_rank import category_label

        mine = part.loc[part["ours"]]
        out.append({"Daftar": int(daftar), "Dasar": part["dasar"].iloc[0] or "", "Isi daftar (kata terbanyak)": category_label(names),
                    "Contoh produk #1": names[0] if names else "", "Produk kita": int(len(mine)),
                    "Peringkat terbaik kita": int(mine["rank"].min()) if not mine.empty else None,
                    "Grup": grup or UNMAPPED, "Kategori": kategori})
    return pd.DataFrame(out)


def apply_mapping(rows: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    """Tulis Grup & Kategori hasil pemetaan per daftar ke baris data."""
    if mapping is None or mapping.empty:
        return rows
    g = dict(zip(mapping["Daftar"].astype(int), mapping["Grup"].astype(str)))
    k = dict(zip(mapping["Daftar"].astype(int), mapping["Kategori"].fillna("").astype(str)))
    out = rows.copy()
    out["grup"] = out["daftar"].astype(int).map(g).fillna(out["grup"]).replace({UNMAPPED: ""})
    out["kategori"] = out["daftar"].astype(int).map(k).fillna(out["kategori"])
    if "Dasar" in mapping.columns:
        d = dict(zip(mapping["Daftar"].astype(int), mapping["Dasar"].fillna("").astype(str)))
        out["dasar"] = out["daftar"].astype(int).map(d).fillna(out["dasar"])
    return out


# ---------------------------------------------------------------- ringkasan & rekap


def tier_of(rank: float) -> str:
    if rank is None or rank != rank:
        return NOT_LISTED
    return next(name for limit, name in TIERS if rank <= limit)


def _at_rank(part: pd.DataFrame, field: str, rank: int) -> float:
    hit = part.loc[(part["rank"] == rank) & ~part["ours"], field]
    if hit.empty:
        hit = part.loc[part["rank"] == rank, field]
    vals = pd.to_numeric(hit, errors="coerce").dropna()
    return float(vals.iloc[0]) if not vals.empty else np.nan


def list_summary(rows: pd.DataFrame) -> pd.DataFrame:
    """Satu baris per (periode, grup, kategori, dasar): posisi produk kita dan nilai Sales/Qty/Views dibanding #1 dan #10.

    Bila satu kategori punya beberapa daftar dengan dasar sama, digabung (peringkat terbaik kita)."""
    cols = ["periode", "grup", "kategori", "dasar", "peringkat", "status", "produk_terbaik", "produk_kita", "top10_kita", "top50_kita",
            "toko_1", "sales_kita", "qty_kita", "views_kita", "sales_10", "qty_10", "views_10", "sales_1", "qty_1", "views_1"]
    if rows is None or rows.empty:
        return pd.DataFrame(columns=cols)
    data = rows.copy()
    data["grup"] = data["grup"].fillna("").replace({"": UNMAPPED})
    data["kategori"] = data["kategori"].fillna("").astype(str)
    data.loc[data["kategori"].str.strip() == "", "kategori"] = "Daftar " + data["daftar"].astype(str)
    data["dasar"] = data["dasar"].fillna("").replace({"": ANY_BASIS})
    out = []
    for (periode, grup, kategori, dasar), part in data.groupby(["periode", "grup", "kategori", "dasar"], sort=False):
        mine = part.loc[part["ours"]].sort_values("rank")
        best = float(mine["rank"].min()) if not mine.empty else np.nan
        top1 = part.loc[~part["ours"]].sort_values("rank")
        item = {"periode": periode, "grup": grup, "kategori": kategori, "dasar": dasar, "peringkat": best, "status": tier_of(best),
                "produk_terbaik": mine["product"].iloc[0] if not mine.empty else "", "produk_kita": int(mine["product"].nunique()),
                "top10_kita": int(mine.loc[mine["rank"] <= 10, "product"].nunique()), "top50_kita": int(mine.loc[mine["rank"] <= 50, "product"].nunique()),
                "toko_1": top1["shop"].iloc[0] if not top1.empty else ""}
        for field in BASES:
            f = field.lower()
            vals = pd.to_numeric(mine[f], errors="coerce")
            item[f"{f}_kita"] = float(vals.sum()) if vals.notna().any() else np.nan
            item[f"{f}_10"] = _at_rank(part, f, 10)
            item[f"{f}_1"] = _at_rank(part, f, 1)
        out.append(item)
    return pd.DataFrame(out, columns=cols)


def tracked_categories(summary: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    """Kategori yang masuk rekap KPI: semua Home & Living (daftar kategori + yang ada di unggahan), Elektronik yang memuat
    produk kita (ada di ranking pada periode mana pun, atau ditandai "Ada produk kita"), dan unggahan yang belum dipetakan."""
    rows: dict[tuple[str, str], str] = {}
    master = master if master is not None else default_master()
    for g, k, ours in zip(master["Grup"], master["Kategori"], master["Ada produk kita"]):
        if g == HL or (g == EL and bool(ours)):
            rows[(str(g), str(k))] = "daftar kategori"
    if summary is not None and not summary.empty:
        for (g, k), part in summary.groupby(["grup", "kategori"]):
            if (g, k) in rows:
                continue
            if g == HL or g == UNMAPPED or (g == EL and part["produk_kita"].sum() > 0):
                rows[(str(g), str(k))] = "unggahan"
    order = {g: i for i, g in enumerate(GROUPS)}
    frame = pd.DataFrame([{"Grup": g, "Kategori": k, "Asal": a} for (g, k), a in rows.items()], columns=["Grup", "Kategori", "Asal"])
    return frame.assign(_o=frame["Grup"].map(order).fillna(9)).sort_values(["_o", "Kategori"]).drop(columns="_o").reset_index(drop=True)


def value_for(summary: pd.DataFrame, target: str, grup: str, kategori: str, dasar: str) -> dict:
    """Peringkat kategori untuk periode target: unggahan periode itu bila ada, kalau tidak disusun dari periode lebih kecil
    di dalamnya (peringkat periode terakhir, terbaik, rata-rata)."""
    part = summary.loc[(summary["grup"] == grup) & (summary["kategori"] == kategori) & (summary["dasar"] == dasar)]
    if part.empty:
        return {"status": NO_DATA}
    exact = part.loc[part["periode"] == target]
    if not exact.empty:
        r = exact.iloc[0]
        return {"peringkat": r["peringkat"], "terbaik": r["peringkat"], "rata": r["peringkat"], "status": r["status"], "sumber": "unggahan " + short_label(target),
                "cakupan": len(months_of(target)), "row": r.to_dict()}
    inner = part.loc[part["periode"].map(lambda p: p != target and contains(target, p))]
    if inner.empty:
        return {"status": NO_DATA}
    inner = inner.assign(_k=inner["periode"].map(end_key)).sort_values("_k")
    # Periode bertumpuk (mis. Juli dan Q3): pakai yang paling spesifik per bulan, hitung cakupan bulan unik.
    covered = {m for p in inner["periode"] for m in months_of(p)}
    last = inner.iloc[-1]
    ranks = pd.to_numeric(inner["peringkat"], errors="coerce")
    return {"peringkat": last["peringkat"], "terbaik": ranks.min() if ranks.notna().any() else np.nan,
            "rata": ranks.mean() if ranks.notna().any() else np.nan, "status": last["status"],
            "sumber": "rekap " + ", ".join(short_label(p) for p in inner["periode"]), "cakupan": len(covered), "row": last.to_dict()}


def recap(summary: pd.DataFrame, master: pd.DataFrame, level: str, year: int, dasar: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(tabel lebar: kategori × periode berisi peringkat terbaik kita, tabel panjang dengan detail tiap sel)."""
    cats = tracked_categories(summary, master)
    targets = periods_in_year(level, year)
    wide, long = [], []
    summary = summary if summary is not None else list_summary(None)
    for g, k in zip(cats["Grup"], cats["Kategori"]):
        line = {"Grup": g, "Kategori": k}
        for t in targets:
            v = value_for(summary, t, g, k, dasar)
            line[short_label(t)] = v.get("peringkat", np.nan) if v["status"] != NO_DATA else np.nan
            if v["status"] == NO_DATA:
                long.append({"Periode": short_label(t), "Grup": g, "Kategori": k, "Status": NO_DATA})
                continue
            row = v["row"]
            item = {"Periode": short_label(t), "Grup": g, "Kategori": k, "Status": v["status"], "Peringkat": v["peringkat"],
                    "Terbaik": v["terbaik"], "Rata-rata": v["rata"], "Sumber": v["sumber"],
                    "Cakupan": f"{v['cakupan']}/{len(months_of(t))} bulan", "Produk terbaik": row.get("produk_terbaik", ""),
                    "Produk kita": row.get("produk_kita"), "Di Top 10": row.get("top10_kita"), "Di Top 50": row.get("top50_kita"),
                    "Toko #1": row.get("toko_1", "")}
            for field in BASES:
                f = field.lower()
                item[f"{field} kita"] = row.get(f"{f}_kita")
                item[f"{field} #10"] = row.get(f"{f}_10")
            long.append(item)
        wide.append(line)
    return pd.DataFrame(wide), pd.DataFrame(long)


def previous_period(pid: str, available: list[str]) -> str | None:
    """Periode sebelumnya dengan tingkat sama (Q3 → Q2, Jul → Jun) bila ada datanya."""
    level, year = level_of(pid), int(str(pid)[:4])
    if level == "Tahun":
        prev = period_id("Tahun", year - 1)
    else:
        seq = periods_in_year(level, year)
        i = seq.index(pid)
        prev = seq[i - 1] if i > 0 else periods_in_year(level, year - 1)[-1]
    return prev if prev in available else None


def insights(summary: pd.DataFrame, master: pd.DataFrame, target: str, dasar: str, all_periods: list[str]) -> list[str]:
    """Catatan analisa singkat untuk satu periode: cakupan, naik/turun dibanding periode sebelumnya, peluang terdekat."""
    notes: list[str] = []
    cats = tracked_categories(summary, master)
    now = {(g, k): value_for(summary, target, g, k, dasar) for g, k in zip(cats["Grup"], cats["Kategori"])}
    hl = [key for key in now if key[0] == HL]
    hl_missing = [k for (g, k), v in now.items() if g == HL and v["status"] == NO_DATA]
    if hl:
        notes.append(f"Home & Living: {len(hl) - len(hl_missing)} dari {len(hl)} kategori sudah ada datanya"
                     + (f"; belum ada: {', '.join(hl_missing[:8])}{' …' if len(hl_missing) > 8 else ''}" if hl_missing else "."))
    unmapped = [k for (g, k) in now if g == UNMAPPED]
    if unmapped:
        notes.append(f"{len(unmapped)} daftar belum dipetakan ke kategori Shopee (Unggah & periode › pemetaan kategori).")
    top = [k for (g, k), v in now.items() if v["status"] == "Sudah Top 10"]
    near = sorted(((v.get("peringkat"), k) for (g, k), v in now.items() if v["status"] == "Dekat"), key=lambda x: x[0])
    if top:
        notes.append(f"Top 10 di {len(top)} kategori: {', '.join(top[:6])}{' …' if len(top) > 6 else ''}.")
    if near:
        notes.append("Paling dekat ke Top 10: " + ", ".join(f"{k} (#{int(r)})" for r, k in near[:5]) + ".")
    prev = previous_period(target, all_periods)
    if prev:
        up, down = [], []
        for (g, k), v in now.items():
            before = value_for(summary, prev, g, k, dasar)
            a, b = v.get("peringkat", np.nan), before.get("peringkat", np.nan)
            if a == a and b == b and a != b:
                (up if a < b else down).append((k, int(b), int(a)))
        if up:
            notes.append(f"Naik dibanding {short_label(prev)}: " + ", ".join(f"{k} #{b}→#{a}" for k, b, a in sorted(up, key=lambda x: x[2] - x[1])[:6]) + ".")
        if down:
            notes.append(f"Turun dibanding {short_label(prev)}: " + ", ".join(f"{k} #{b}→#{a}" for k, b, a in sorted(down, key=lambda x: x[1] - x[2])[:6]) + ".")
    gaps = []
    for (g, k), v in now.items():
        row = v.get("row") or {}
        if v.get("status") in ("Dekat", "Menengah"):
            for field in BASES:
                f = field.lower()
                mine, ten = row.get(f"{f}_kita"), row.get(f"{f}_10")
                if mine and ten and mine == mine and ten == ten and ten > 0:
                    gaps.append((mine / ten, k, field))
    if gaps:
        best = sorted(gaps, reverse=True)[:5]
        notes.append("Selisih terkecil ke peringkat #10: " + ", ".join(f"{k} ({field} kita {ratio * 100:.0f}% dari #10)" for ratio, k, field in best) + ".")
    elif not summary.empty and summary[[f"{b.lower()}_kita" for b in BASES]].isna().all().all():
        notes.append("Unggahan belum memuat Sales/Qty/Views; setelah kolom itu ditambahkan, selisih ke peringkat #10 ikut dihitung.")
    return notes
