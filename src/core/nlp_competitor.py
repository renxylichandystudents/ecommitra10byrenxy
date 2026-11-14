"""NLP kompetitor & SEO untuk nama dan deskripsi produk bahan bangunan di Shopee.

Vektorisasi default TF-IDF + cosine similarity (Sentence-BERT/Word2Vec opsional).
Kata kunci: N-gram dari judul kompetitor terlaris, RAKE sederhana, dan frequent itemset.
Judul baru: template [Brand] + [Jenis Produk] + [Material/Ukuran] + [Keunggulan Utama].
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import combinations

import numpy as np
import pandas as pd

from src.core.naming import (
    MANUAL_CHECK,
    SHOPEE_TITLE_HARD,
    fit_title,
    allowed_keyword,
    brand_set,
    extract_packing_tag,
    foreign_words,
    strip_packing_words,
    vocabulary,
    with_tag,
)

STOPWORDS = {
    "dan", "atau", "yang", "untuk", "dengan", "di", "ke", "dari", "ini", "itu", "pada", "dalam", "adalah",
    "juga", "akan", "bisa", "dapat", "sudah", "telah", "ada", "tidak", "bukan", "agar", "supaya", "karena",
    "jika", "kami", "kita", "anda", "kamu", "saya", "nya", "pun", "lah", "per", "sebagai", "oleh", "serta",
    "lebih", "sangat", "paling", "hanya", "setiap", "semua", "termasuk", "tanpa", "harga", "murah", "promo",
    "original", "ori", "asli", "ready", "stok", "stock", "termurah", "best", "seller", "new", "baru", "gratis",
    "ongkir", "cod", "produk", "barang", "jual", "pcs", "unit", "free", "sale", "diskon",
}
MATERIALS = (
    "besi", "baja", "kayu", "pvc", "upvc", "ppr", "keramik", "granit", "marmer", "aluminium", "alumunium",
    "stainless", "galvanis", "galvalum", "zincalume", "akrilik", "kaca", "tembaga", "kuningan", "semen", "beton",
    "gypsum", "kalsiboard", "gipsum", "karet", "plastik", "nylon", "fiber", "polycarbonate", "vinyl", "spc",
    "hpl", "multiplek", "triplek", "mdf", "bitumen", "silikon", "epoxy", "akrilik", "porselen",
)
FINISHES = ("chrome", "krom", "matte", "glossy", "doff", "satin", "brushed", "gun grey", "black", "hitam", "putih", "gold")
USAGE_HINTS = (
    "anti bocor", "anti karat", "anti jamur", "anti lumut", "tahan", "waterproof", "kedap", "dinding", "lantai",
    "atap", "plafon", "kamar mandi", "dapur", "taman", "eksterior", "interior", "outdoor", "indoor", "pipa",
    "saluran", "kunci", "pintu", "jendela", "listrik", "lampu", "cat", "pelapis", "perekat", "lem", "nat",
    "sealant", "keran", "wastafel", "closet", "shower", "talang", "rangka", "pagar", "kanopi",
)
SIZE_PATTERN = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:x\s?\d+(?:[.,]\d+)?\s?)?(?:kg|gr|g|gram|l|lt|liter|ml|m|meter|cm|mm|inch|inci|\"|w|watt|v|volt|"
    r"pcs|lembar|roll|sak|dus|m2|mtr|in|kgs|ltr|galon|pail)\b",
    re.IGNORECASE,
)
EMOJI_PATTERN = re.compile("[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U0001F000-\U0001F2FF\u2600-\u26FF]+")
SCORE_LABELS = ("Poor", "Standard", "Excellence")
DESCRIPTION_ASPECTS = {
    "Fitur & benefit": ("fitur", "keunggulan", "benefit", "manfaat", "kelebihan"),
    "Kegunaan": ("kegunaan", "digunakan untuk", "cocok untuk", "untuk "),
    "Cara pakai": ("cara pakai", "cara penggunaan", "petunjuk", "langkah"),
    "Keunggulan dibanding produk lain": ("dibanding", "lebih awet", "lebih kuat", "lebih hemat", "terbaik"),
    "Kenapa memilih produk ini": ("kenapa", "mengapa", "alasan memilih", "pilih"),
    "Manfaat setelah dibeli": ("garansi", "awet", "tahan lama", "hemat", "aman"),
    "Cara pasang / pengaplikasian": ("cara pasang", "pemasangan", "aplikasi", "pengaplikasian", "instalasi"),
    "Spesifikasi": ("spesifikasi", "ukuran", "dimensi", "berat", "isi", "bahan", "material", "warna"),
    "Ajakan membeli": ("beli sekarang", "pesan sekarang", "checkout", "order sekarang", "segera"),
}


@lru_cache(maxsize=1)
def _stemmer():
    try:
        from Sastrawi.Stemmer.StemmerFactory import StemmerFactory

        return fast_dictionary(StemmerFactory().create_stemmer())
    except Exception:
        return None


def fast_dictionary(stemmer):
    """Kamus Sastrawi 1.0.1 berupa list (lookup O(n), ±200 detik untuk 300 judul); ubah ke set."""
    inner = getattr(stemmer, "delegatedStemmer", stemmer)
    dictionary = getattr(inner, "dictionary", None)
    if dictionary is not None and isinstance(getattr(dictionary, "words", None), list):
        dictionary.words = set(dictionary.words)
    return stemmer


@lru_cache(maxsize=50_000)
def stem_token(token: str) -> str:
    stemmer = _stemmer()
    if stemmer is None or token.isdigit() or len(token) <= 3:
        return token
    try:
        return stemmer.stem(token) or token
    except Exception:
        return token


def clean_text(text: object) -> str:
    raw = EMOJI_PATTERN.sub(" ", str(text or ""))
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii").lower()
    raw = re.sub(r"https?://\S+", " ", raw)
    raw = re.sub(r"[^a-z0-9\s.,x\"/-]", " ", raw)
    raw = re.sub(r"(?<!\d)[.,/-]|[.,/-](?!\d)", " ", raw)
    return " ".join(raw.split())


def tokens(text: object, *, stem: bool = False) -> list[str]:
    words = [word for word in clean_text(text).split() if word not in STOPWORDS and len(word) > 1]
    return [stem_token(word) for word in words] if stem else words


def ngrams(words: list[str], n: int) -> list[str]:
    return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]


def rake_phrases(text: object) -> list[tuple[str, float]]:
    """RAKE sederhana: frasa dipisah stopword/tanda baca, skor = jumlah degree/frekuensi kata."""
    raw = clean_text(text)
    phrases: list[list[str]] = []
    current: list[str] = []
    for word in raw.split():
        if word in STOPWORDS or len(word) <= 1:
            if current:
                phrases.append(current)
            current = []
        else:
            current.append(word)
    if current:
        phrases.append(current)
    freq: Counter = Counter()
    degree: Counter = Counter()
    for phrase in phrases:
        for word in phrase:
            freq[word] += 1
            degree[word] += len(phrase)
    scored = {" ".join(p): sum(degree[w] / freq[w] for w in p) for p in phrases if 1 <= len(p) <= 4}
    return sorted(scored.items(), key=lambda item: -item[1])


def frequent_itemsets(titles: list[str], *, min_support: float = 0.2) -> list[tuple[tuple[str, ...], float]]:
    """Apriori sederhana (1- dan 2-itemset) dari token judul kompetitor terlaris."""
    baskets = [set(tokens(title)) for title in titles if str(title).strip()]
    if not baskets:
        return []
    total = len(baskets)
    single = Counter(word for basket in baskets for word in basket)
    frequent = {word for word, count in single.items() if count / total >= min_support}
    pairs: Counter = Counter()
    for basket in baskets:
        for pair in combinations(sorted(basket & frequent), 2):
            pairs[pair] += 1
    out = [((word,), count / total) for word, count in single.items() if word in frequent]
    out += [(pair, count / total) for pair, count in pairs.items() if count / total >= min_support]
    return sorted(out, key=lambda item: (-item[1], -len(item[0])))


@dataclass
class Vectorizer:
    name: str
    note: str
    matrix: object = None
    model: object = None


SBERT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


def _cache_resource(fn):
    try:
        import streamlit as st

        return st.cache_resource(show_spinner=False)(fn)
    except Exception:
        return lru_cache(maxsize=1)(fn)


@_cache_resource
def sbert_model():
    """Model Sentence-BERT sekali muat per server; None bila paket tidak terpasang (fallback TF-IDF)."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        return SentenceTransformer(SBERT_MODEL)
    except Exception:
        return None


def _vectorize(texts: list[str]) -> Vectorizer:
    model = sbert_model()
    if model is not None:
        try:
            return Vectorizer("Sentence-BERT", SBERT_MODEL, model.encode(texts, normalize_embeddings=True), model)
        except Exception:
            pass
    from sklearn.feature_extraction.text import TfidfVectorizer

    vec = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1, sublinear_tf=True)
    stemmed = [" ".join(tokens(text, stem=True)) for text in texts]
    matrix = vec.fit_transform(stemmed if any(stemmed) else [" "])
    return Vectorizer("TF-IDF", "TF-IDF + cosine similarity", matrix, vec)


def match_competitors(own: pd.DataFrame, competitors: pd.DataFrame, *, top_k: int = 5) -> tuple[dict[str, list[int]], dict[str, list[float]], str]:
    """Kompetitor paling mirip per produk sendiri (index baris kompetitor)."""
    if own is None or own.empty or competitors is None or competitors.empty or "product_name" not in competitors.columns:
        return {}, {}, "Data kompetitor kosong"
    own_names = own["product_name"].fillna("").astype(str).tolist()
    comp_names = competitors["product_name"].fillna("").astype(str).tolist()
    vec = _vectorize(own_names + comp_names)
    matrix = vec.matrix
    own_m = matrix[: len(own_names)]
    comp_m = matrix[len(own_names) :]
    if vec.name == "TF-IDF":
        sims = (own_m @ comp_m.T).toarray()
    else:
        sims = np.asarray(own_m) @ np.asarray(comp_m).T
    matches: dict[str, list[int]] = {}
    scores: dict[str, list[float]] = {}
    for row, key in enumerate(own["item_key"].astype(str)):
        order = np.argsort(-sims[row])[:top_k]
        keep = [int(i) for i in order if sims[row, i] > 0.1]
        matches[key] = keep
        scores[key] = [float(sims[row, i]) for i in keep]
    return matches, scores, vec.note


def _num(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.replace(r"[^0-9,.\-]", "", regex=True)
    text = text.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(text, errors="coerce")


def _sold_number(value: object) -> float:
    text = str(value or "").lower().replace("terjual", "").strip()
    multiplier = 1.0
    if "rb" in text or "k" in text:
        multiplier = 1000.0
    if "jt" in text:
        multiplier = 1_000_000.0
    digits = re.sub(r"[^0-9,.]", "", text).replace(".", "").replace(",", ".")
    try:
        return float(digits) * multiplier
    except ValueError:
        return 0.0


def competitor_benchmark(
    own: pd.DataFrame,
    competitors: pd.DataFrame,
    matches: dict[str, list[int]],
) -> pd.DataFrame:
    """Skor benchmark (0–100): rasio harga, rating, terjual, kecocokan kata kunci; plus market share gap."""
    rows = []
    comp = competitors.copy() if competitors is not None else pd.DataFrame()
    if not comp.empty:
        comp["_price"] = _num(comp["price"]) if "price" in comp.columns else np.nan
        comp["_sold"] = comp["sold"].map(_sold_number) if "sold" in comp.columns else 0.0
        comp["_rating"] = pd.to_numeric(comp["rating"].astype(str).str.replace(",", "."), errors="coerce") if "rating" in comp.columns else np.nan
    for _, item in own.iterrows():
        key = str(item["item_key"])
        picked = comp.iloc[matches.get(key, [])] if not comp.empty and matches.get(key) else pd.DataFrame()
        own_price = float(item.get("harga_bersih", 0) or 0)
        own_sold = float(item.get("qty_total", 0) or 0)
        if picked.empty:
            rows.append({"item_key": key, "harga_kompetitor": np.nan, "harga_vs_kompetitor_pct": np.nan, "terjual_kompetitor": np.nan,
                         "rating_kompetitor": np.nan, "kecocokan_kata_pct": np.nan, "skor_benchmark": np.nan, "market_share_gap_pct": np.nan,
                         "toko_kompetitor": ""})
            continue
        comp_price = float(picked["_price"].median()) if picked["_price"].notna().any() else np.nan
        price_ratio = own_price / comp_price if comp_price and comp_price > 0 and own_price > 0 else np.nan
        own_words = set(tokens(item.get("product_name", ""), stem=True))
        comp_words = set(word for name in picked["product_name"] for word in tokens(name, stem=True))
        overlap = len(own_words & comp_words) / max(len(comp_words), 1)
        sold_comp = float(picked["_sold"].sum())
        rating = float(picked["_rating"].mean()) if picked["_rating"].notna().any() else np.nan
        price_score = 1.0 if np.isnan(price_ratio) else float(np.clip(1.5 - price_ratio, 0, 1))
        rating_score = 0.5 if np.isnan(rating) else float(np.clip(rating / 5, 0, 1))
        sold_score = own_sold / (own_sold + sold_comp / max(len(picked), 1)) if (own_sold + sold_comp) > 0 else 0.5
        score = 100 * (0.35 * price_score + 0.15 * rating_score + 0.25 * sold_score + 0.25 * overlap)
        share = own_sold / (own_sold + sold_comp) * 100 if (own_sold + sold_comp) > 0 else np.nan
        fair = 100 / (len(picked) + 1)
        rows.append(
            {
                "item_key": key,
                "harga_kompetitor": comp_price,
                "harga_vs_kompetitor_pct": (price_ratio - 1) * 100 if not np.isnan(price_ratio) else np.nan,
                "terjual_kompetitor": sold_comp,
                "rating_kompetitor": rating,
                "kecocokan_kata_pct": overlap * 100,
                "skor_benchmark": score,
                "market_share_gap_pct": (share - fair) if not np.isnan(share) else np.nan,
                "toko_kompetitor": ", ".join(sorted(set(picked.get("shop_name", pd.Series(dtype=str)).astype(str)))[:3]),
            }
        )
    return pd.DataFrame(rows)


def keyword_set(own_name: str, comp_titles: list[str], comp_sold: list[float] | None = None, *, limit: int = 8) -> tuple[list[str], list[str]]:
    """Kata kunci utama (dari n-gram judul kompetitor terlaris + RAKE + itemset) dan pendukung."""
    weights = comp_sold or [1.0] * len(comp_titles)
    score: Counter = Counter()
    for title, weight in zip(comp_titles, weights):
        words = tokens(title)
        w = 1.0 + np.log1p(max(float(weight), 0.0))
        for n in (1, 2, 3):
            for gram in ngrams(words, n):
                if any(ch.isalpha() for ch in gram):
                    score[gram] += w * (1.0 + 0.5 * (n - 1))
    for phrase, value in rake_phrases(own_name)[:5]:
        score[phrase] += value
    for itemset, support in frequent_itemsets(comp_titles)[:10]:
        score[" ".join(itemset)] += support * 5
    if not score:
        base = tokens(own_name)
        return base[:3], base[3:limit]
    ranked = [word for word, _ in score.most_common(40)]
    primary: list[str] = []
    for word in ranked:
        if any(word in other or other in word for other in primary):
            continue
        primary.append(word)
        if len(primary) >= 3:
            break
    supporting = [word for word in ranked if word not in primary and not any(word in p for p in primary)][: max(limit - 3, 0)]
    return primary, supporting


def _brand(name: str, brands: list[str]) -> str:
    low = clean_text(name)
    for brand in sorted(brands, key=len, reverse=True):
        if re.search(rf"\b{re.escape(brand.lower())}\b", low):
            return brand.title() if brand.islower() else brand
    return ""


@dataclass
class NameScore:
    label: str
    points: int
    checks: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


def score_name(name: str, primary_keywords: list[str], brands: list[str], *, min_len: int, max_len: int) -> NameScore:
    text = str(name or "").strip()
    low = clean_text(text)
    words = low.split()
    repeated = [word for word, count in Counter(words).items() if count > 1 and len(word) > 2 and not word.isdigit()]
    checks = {
        "Merek": bool(_brand(text, brands)),
        "Tipe / jenis produk": len([w for w in words if w not in STOPWORDS and not w.isdigit()]) >= 2,
        "Ukuran": bool(SIZE_PATTERN.search(text)),
        "Material": any(re.search(rf"\b{m}\b", low) for m in MATERIALS),
        "Kegunaan": any(hint in low for hint in USAGE_HINTS),
        "Kata kunci utama": bool(primary_keywords) and sum(1 for k in primary_keywords if k in low) >= max(1, len(primary_keywords) // 2),
        "Tanpa pengulangan / tanda baca berlebihan": not repeated and not re.search(r"[!?*#~]{2,}|[A-Z]{12,}", text),
        "Panjang ideal (25–120 karakter)": min_len <= len(text) <= max_len,
    }
    points = sum(checks.values())
    label = "Excellence" if points >= 7 else ("Standard" if points >= 4 else "Poor")
    reasons = [f"Belum ada {name.lower()}" for name, ok in checks.items() if not ok]
    if repeated:
        reasons.append("Kata berulang: " + ", ".join(repeated[:3]))
    if len(text) > max_len:
        reasons.append(f"Panjang {len(text)} karakter, batas {max_len}")
    elif len(text) < min_len:
        reasons.append(f"Panjang {len(text)} karakter, minimal {min_len}")
    return NameScore(label, points, checks, reasons)


# Kode tipe/model (FSA0089, LT809, YKF-403): huruf lalu angka. Dipertahankan di judul karena dicari pembeli.
MODEL_CODE = re.compile(r"[a-z]{1,5}-?\d{2,}[a-z0-9-]*")
WARRANTY = re.compile(r"garansi\s+\d+\s*(?:tahun|thn|bulan|bln)", re.IGNORECASE)


def _title_case(text: str) -> str:
    keep_upper = {"pvc", "upvc", "ppr", "hpl", "mdf", "spc", "led", "sni", "ac", "dc", "wc", "sus304", "abs", "pp"}
    out = []
    for word in text.split():
        low = word.lower()
        if low in keep_upper:
            out.append(low.upper())
        elif MODEL_CODE.fullmatch(low):
            out.append(word.upper())
        elif SIZE_PATTERN.fullmatch(word) or any(ch.isdigit() for ch in word):
            out.append(word)
        else:
            out.append(word.capitalize())
    return " ".join(out)


def synthesize_title(name: str, variation: str, primary: list[str], brands: list[str], *, max_len: int) -> str:
    """[Brand] + [Jenis Produk] + [Kode tipe] + [Material/Ukuran] + [Keunggulan Utama] + [Garansi]."""
    name, _packing = extract_packing_tag(name)  # "[INCLUDE PACKING KAYU]" bukan material produk
    low = clean_text(name)
    brand = _brand(name, brands)
    material = next((m for m in MATERIALS if re.search(rf"\b{m}\b", low)), "")
    size_match = SIZE_PATTERN.search(f"{name} {variation}")
    size = size_match.group(0) if size_match else ""
    usage = next((hint for hint in USAGE_HINTS if hint in low), "")
    used = {brand.lower(), material, size.lower(), usage}
    model = next((w for w in tokens(name) if MODEL_CODE.fullmatch(w) and not SIZE_PATTERN.fullmatch(w) and not w.startswith("sus")), "")
    warranty_match = WARRANTY.search(str(name))
    warranty = warranty_match.group(0) if warranty_match else ""
    used |= {model}
    product_words = [w for w in tokens(name) if w not in used and w not in brand.lower().split() and not SIZE_PATTERN.fullmatch(w)]
    product_type = " ".join(product_words[:6])
    keyword = next((k for k in primary if k not in low), "")
    parts = [brand, product_type, model, material, size, usage, keyword, warranty]
    title = _title_case(" ".join(part for part in parts if part))
    seen: set[str] = set()
    deduped = []
    for word in title.split():
        if word.lower() in seen and not any(ch.isdigit() for ch in word):
            continue
        seen.add(word.lower())
        deduped.append(word)
    title = " ".join(deduped)
    if len(title) > max_len:
        title = fit_title(title, max_len)
    return title or fit_title(_title_case(str(name)), max_len)


def description_strengths(description: str) -> dict[str, bool]:
    low = clean_text(description)
    return {aspect: any(word in low for word in words) for aspect, words in DESCRIPTION_ASPECTS.items()}


def _spec_lines(description: str, name: str, variation: str) -> list[str]:
    """Baris spesifikasi "Atribut: nilai" (atribut pendek) atau ukuran; kalimat fitur panjang tidak termasuk."""
    lines = []
    for raw in re.split(r"[\n\r]+", str(description or "")):
        line = " ".join(raw.replace("•", "-").split()).strip("-* ")
        if not line or len(line) > 120:
            continue
        head = line.split(":", 1)[0]
        if ":" in line and len(head) <= 28 and len(head.split()) <= 4 and line.split(":", 1)[1].strip():
            lines.append(line)
        elif SIZE_PATTERN.search(line) and len(line) <= 60:
            lines.append(line)
    if not lines:
        size = SIZE_PATTERN.search(f"{name} {variation}")
        if size:
            lines.append(f"Ukuran/isi: {size.group(0)}")
        if variation and variation.lower() not in {"", "tanpa variasi"}:
            lines.append(f"Varian: {variation}")
    return lines[:8]


# --------------------------------------------------------------------------- USP & SEO

STORE_HINTS = ("selamat datang", "toko kami", "jam operasional", "harga dapat berubah", "follow", "chat admin", "whatsapp", "wa ", "http", "www.",
               "kebijakan", "komplain", "retur", "pengembalian", "video unboxing", "klaim")
CONTACT = re.compile(r"(https?://|www\.|\b08\d{8,}\b|\+62\d{8,}|@[a-z0-9_.]{3,})", re.IGNORECASE)


def _sentences(text: str) -> list[str]:
    out = []
    for piece in re.split(r"[\n\r]+|(?<=[.!?])\s+", str(text or "")):
        sentence = " ".join(piece.replace("•", " ").split()).strip(" -*:")
        low = sentence.lower()
        if len(sentence) < 12 or any(h in low for h in STORE_HINTS) or CONTACT.search(sentence):
            continue
        out.append(sentence)
    return out


def _years(text: str) -> float:
    match = re.search(r"(\d+)\s*(tahun|thn|bulan|bln)", str(text).lower())
    if not match:
        return 0.0
    value = float(match.group(1))
    return value / 12 if match.group(2).startswith("b") else value


def usp_points(name: str, description: str, variation: str, comp_titles: list[str], brands: list[str], *, limit: int = 5) -> list[tuple[str, bool]]:
    """Keunggulan (USP) dari fakta produk sendiri; (kalimat, unik) — unik = jarang disebut judul kompetitor di daftar yang sama.

    Tidak mengarang klaim: setiap poin berasal dari nama, variasi, atau deskripsi produk itu sendiri."""
    clean_name, tag = extract_packing_tag(name)
    description = strip_packing_words(description)
    name_low = clean_text(f"{clean_name} {variation}")
    low = clean_text(f"{clean_name} {variation} {description}")
    comp_low = [clean_text(t) for t in comp_titles]

    def rare(*words: str) -> bool:
        words = [w for w in words if w]
        if not comp_low or not words:
            return False
        hits = sum(1 for t in comp_low if any(w.lower() in t for w in words))
        return hits / len(comp_low) < 0.2

    points: list[tuple[str, bool]] = []
    warranty = WARRANTY.search(f"{clean_name} {description}")
    if warranty:
        years = _years(warranty.group(0))
        comp_years = [_years(m.group(0)) for t in comp_titles for m in [WARRANTY.search(t)] if m]
        longest = max(comp_years) if comp_years else 0
        period = warranty.group(0).lower().replace("garansi", "").strip()
        if comp_years and years > longest:
            points.append((f"Garansi resmi {period} — lebih panjang dari produk sejenis teratas (maks. {longest:g} tahun)", True))
        else:
            points.append((f"Garansi resmi {period} — perlindungan jangka panjang setelah pembelian", rare("garansi")))
    # Material: utamakan yang tertulis di nama, baru deskripsi (urutan kemunculan, bukan urutan daftar).
    def _first_material(text: str) -> str:
        found = [(m.start(), mat) for mat in MATERIALS for m in [re.search(rf"\b{mat}\b", text)] if m]
        return min(found)[1] if found else ""

    # Material hanya dari kalimat yang memang menyebut bahan, atau nama produk untuk bahan yang tidak ambigu
    # ("sendok semen" bukan berbahan semen; "pasang keramik" bukan berbahan keramik).
    english = {"ceramic": "keramik", "brass": "kuningan", "wood": "kayu", "stainless steel": "stainless", "aluminum": "aluminium", "glass": "kaca", "copper": "tembaga"}
    material = ""
    for sentence in _sentences(description):
        sl = clean_text(sentence)
        if any(k in sl for k in ("bahan", "material", "terbuat dari")):
            for eng, ind in english.items():
                sl = sl.replace(eng, ind)
            material = _first_material(sl)
            if material:
                break
    if not material:
        candidate = _first_material(name_low)
        material = "" if candidate in {"semen", "beton", "keramik", "kayu", "kaca", "granit", "marmer", "gypsum", "gipsum"} else candidate
    grade = re.search(r"\b(?:sus|stainless(?: steel)?)\s?(304|316|201)\b", low)
    if grade:
        points.append((f"Material stainless {grade.group(1)} — tahan karat untuk pemakaian harian", rare(grade.group(1))))
    elif material:
        points.append((f"Bahan {material} — kuat dan awet", rare(material)))
    brand_keys = {re.sub(r"[^a-z0-9]", "", b.lower()) for b in brands}
    model = next((w for w in tokens(clean_name) if MODEL_CODE.fullmatch(w) and not SIZE_PATTERN.fullmatch(w) and not w.startswith("sus")
                  and re.sub(r"[^a-z0-9]", "", w) not in brand_keys), "")  # merek berangka (mis. Mitra10) bukan kode tipe
    if model:
        points.append((f"Kode tipe {model.upper()} tercantum jelas — mudah dicocokkan dengan kebutuhan & suku cadang", rare(model)))
    size = SIZE_PATTERN.search(f"{clean_name} {variation}")
    if size:
        points.append((f"Ukuran/isi {size.group(0)} — sesuaikan dengan area atau kebutuhan pemakaian", rare(size.group(0))))
    for sentence in _sentences(description):
        sl = sentence.lower()
        if any(k in sl for k in ("anti ", "tahan ", "hemat", "kedap", "mudah dipasang", "mudah dibersihkan", "sni", "food grade", "otomatis", "soft clos", "dual flush")):
            text = re.sub(r"^(keunggulan|fitur|kelebihan|unggulan)\s*[:\-–]?\s*", "", sentence, flags=re.IGNORECASE)
            text = re.sub(r"^[A-Za-z &/]{3,30}\s[-–:]\s", "", text)
            if 15 <= len(text) <= 140 and not any(text.lower()[:40] in p[0].lower() for p in points):
                distinct = [w for w in tokens(text) if w not in STOPWORDS and len(w) > 3]
                points.append((text[0].upper() + text[1:], rare(*distinct[:2])))
        if len(points) >= limit + 3:
            break
    if tag:
        points.append(("Dikirim dengan packing kayu — aman untuk barang besar/mudah pecah sampai tujuan", rare("packing kayu")))
    brand = _brand(clean_name, brands)
    if brand:
        points.append((f"Produk original {brand} dari Mitra10 Official Store", False))
    # Pembeda (jarang di kompetitor) diletakkan paling atas.
    points.sort(key=lambda p: not p[1])
    seen, out = set(), []
    for text, unique in points:
        key = text.lower()[:30]
        if key in seen:
            continue
        seen.add(key)
        out.append((text, unique))
    return out[:limit]


def hashtags(primary: list[str], supporting: list[str], brand: str, *, limit: int = 8, title: str = "") -> list[str]:
    """5–10 hashtag relevan (tanpa spasi), dari kata kunci yang juga ada di judul produk (tidak menyesatkan)."""
    out: list[str] = []
    allowed = set(clean_text(title).split()) if title else None
    type_words = [w for w in clean_text(title).split() if w not in STOPWORDS and not any(ch.isdigit() for ch in w) and w != clean_text(brand)][:3] if title else []
    phrases = [brand, *primary, " ".join(type_words[:2]), *supporting, *type_words]
    for phrase in phrases:
        if allowed is not None and not all(w in allowed for w in clean_text(phrase).split()):
            continue
        tag = re.sub(r"[^a-z0-9]", "", str(phrase).lower())
        if 3 <= len(tag) <= 30 and tag not in out and not any(ch.isdigit() for ch in tag):
            out.append(tag)
        if len(out) >= limit:
            break
    return ["#" + t for t in out]


def _usage_line(description: str, name: str) -> str:
    """Kalimat kegunaan dari deskripsi sendiri (tidak dikarang)."""
    for sentence in _sentences(description):
        sl = sentence.lower()
        if any(k in sl for k in ("cocok untuk", "digunakan untuk", "ideal untuk", "untuk area", "fungsi:", "sempurna untuk")) and len(sentence) <= 220:
            return sentence
    usage = [hint for hint in USAGE_HINTS if hint in clean_text(name)][:3]
    return f"Cocok untuk kebutuhan {', '.join(usage)} di rumah maupun proyek." if len(usage) >= 2 else ""


def generate_description(
    *,
    title: str,
    name: str,
    variation: str,
    description: str,
    primary: list[str],
    supporting: list[str],
    cancel_reasons: list[str],
    max_chars: int,
    usp: list[tuple[str, bool]] | None = None,
    variants: list[str] | None = None,
    brands: list[str] | None = None,
) -> str:
    """Deskripsi teks polos siap tempel ke Shopee: unik per produk (USP & detail dari deskripsi sendiri), kata kunci utama
    di kalimat pertama, subjudul jelas, spesifikasi, varian, dan 5–8 hashtag di akhir. Tanpa HTML/markdown/link/kontak."""
    clean_name, tag = extract_packing_tag(name)
    usp = usp if usp is not None else usp_points(name, description, variation, [], brands or [])
    key_main = primary[0] if primary else " ".join(tokens(clean_name)[:3])
    lead_usp = [t.split(" — ")[0] for t, _u in usp if not t.startswith("Produk original")][:2]
    first = f"Jual {title} original di Mitra10 Official Store" + (f": {', '.join(u[0].lower() + u[1:] for u in lead_usp)}." if lead_usp else ".")
    if key_main not in clean_text(first):
        first = f"{key_main.capitalize()} — {first}"
    specs = _spec_lines(description, clean_name, variation)
    own_sentences = [s for s in _sentences(strip_packing_words(description))
                     if not s.lower().startswith(("pilihan varian", "spesifikasi", "keunggulan utama", "fitur utama"))
                     and not any(s.strip(" .") in line or line.strip(" .") in s for line in specs) and len(s.split()) >= 4]
    intro = " ".join(own_sentences[:2]) if own_sentences else ""
    if len(intro) > 400:
        # Potong di akhir kalimat/kata terdekat, bukan di tengah kata ("… langsung di r").
        cut = intro[:400]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        intro = cut[: end + 1] if end >= 200 else cut.rsplit(" ", 1)[0].rstrip(",;:") + "…"
    if not intro:
        usage = _usage_line(description, clean_name)
        intro = f"{usage} Dikirim langsung dari gudang Mitra10, stok dan kualitas terjaga.".strip()
    sections = [first, intro, ""]
    if usp:
        sections += ["KEUNGGULAN UTAMA"] + [f"- {t}" for t, _u in usp] + [""]
    if variants and len(variants) > 1:
        sections += ["PILIHAN VARIAN"] + [f"- {v}" for v in variants[:10]] + [""]
    if specs:
        sections += ["SPESIFIKASI"] + [f"- {line}" for line in specs] + [""]
    usage = _usage_line(description, clean_name)
    if usage and usage not in intro:
        sections += ["KEGUNAAN", usage, ""]
    detail = [s for s in own_sentences[2:] if s not in usage and not any(s[:30] in t for t, _u in usp)]
    if detail:
        sections += ["DETAIL PRODUK"] + detail[:6] + [""]
    shipping = ["PENGIRIMAN"]
    shipping.append("- Dikemas dengan packing kayu agar aman sampai tujuan." if tag else "- Dikemas aman dan dikirim dari gudang Mitra10.")
    reason_text = " ".join(cancel_reasons).lower()
    if any(word in reason_text for word in ("ongkir", "pengiriman", "kirim", "alamat", "lama")):
        shipping.append("- Ongkos kirim dan estimasi tiba tampil otomatis saat checkout.")
    if any(word in reason_text for word in ("bayar", "pembayaran")):
        shipping.append("- Selesaikan pembayaran agar pesanan langsung diproses hari ini.")
    sections += shipping + [""]
    sections += ["Pesan sekarang di Mitra10 Official Store — stok dari gudang Mitra10, dikirim cepat."]
    tags = hashtags(primary, supporting, _brand(clean_name, brands or []), title=f"{title} {clean_name}")
    tail = ("\n\n" + " ".join(tags)) if tags else ""
    text = "\n".join(sections).strip()
    budget = max_chars - len(tail)
    if len(text) > budget:
        text = text[: budget - 1].rsplit("\n", 1)[0].rstrip()
    return text + tail


def seo_title_checks(title: str, primary: list[str], brands: list[str], *, max_len: int) -> dict[str, bool]:
    """Kaidah judul Shopee: kata kunci utama di 40 karakter awal, 60–maks karakter, merek, tanpa pengulangan/simbol/huruf kapital semua."""
    low = clean_text(title)
    head = clean_text(title[:40])
    # Label "[INCLUDE PACKING KAYU]" wajib untuk produk berpacking kayu, jadi tidak dihitung dalam panjang ideal judul
    # maupun pengulangan kata (mis. "Cermin Kayu … [INCLUDE PACKING KAYU]").
    core = re.sub(r"\s*\[[^\]]*packing[^\]]*\]", "", str(title), flags=re.IGNORECASE).strip()
    # Kode tipe (mis. L-XKS, ZN-30A-2) dihitung sebagai satu kata: "Xks … L-XKS" bukan pengulangan kata.
    words = [w for w in (re.sub(r"[^a-z0-9/-]", "", t.lower()) for t in core.split()) if len(w) > 2 and not w.isdigit()]
    return {
        "Kata kunci di awal judul": bool(primary) and any(k in head for k in primary[:2]),
        f"Panjang 60–{max_len} karakter": 60 <= len(core) <= max_len,
        "Ada merek": bool(_brand(title, brands)),
        "Ada ukuran/tipe/material": bool(SIZE_PATTERN.search(title) or MODEL_CODE.search(low) or MODEL_CODE.search(str(title).lower())
                                         or any(re.search(rf"\b{m}\b", low) for m in (*MATERIALS, *FINISHES))),
        "Tanpa kata berulang": len(words) == len(set(words)),
        "Tanpa simbol/emoji/kapital berlebih": not EMOJI_PATTERN.search(title) and not re.search(r"[!?*#~]{1,}|\b[A-Z]{8,}\b", title.replace("[INCLUDE PACKING KAYU]", "")),
    }


def keyword_count(body: str, keyword: str) -> int:
    """Kemunculan kata kunci yang dihitung sebagai penjejalan: tidak termasuk hashtag, nama toko ("Mitra10 Official Store",
    "gudang Mitra10"), serta bagian SPESIFIKASI dan PILIHAN VARIAN (data faktual seperti jenis produk & nama varian)."""
    narrative, skip = [], False
    for line in str(body or "").split("\n"):
        if re.fullmatch(r"[A-Z &/]{6,}", line.strip()):
            skip = line.strip() in ("SPESIFIKASI", "PILIHAN VARIAN")
            continue
        if not skip:
            narrative.append(line)
    text = re.sub(r"#\w+|mitra10 official store|gudang mitra10", " ", "\n".join(narrative), flags=re.IGNORECASE)
    return clean_text(text).count(keyword) if keyword else 0


def seo_description_checks(text: str, primary: list[str], *, max_chars: int, similarity: float = 0.0) -> dict[str, bool]:
    body = str(text or "")
    first = clean_text(body.split("\n", 1)[0])
    # Hashtag di akhir dan nama toko ("Mitra10 Official Store", "gudang Mitra10") tidak dihitung dalam kepadatan kata kunci.
    low = clean_text(re.sub(r"#\w+", " ", body))  # hashtag di akhir tidak dihitung dalam kepadatan kata kunci
    tags = re.findall(r"#\w+", body)
    density = (keyword_count(body, primary[0]) * max(len(primary[0].split()), 1) / max(len(low.split()), 1) * 100) if primary else 0
    return {
        "Kata kunci di kalimat pertama": bool(primary) and primary[0] in first,
        "Panjang 600–3.000 karakter": 600 <= len(body) <= max_chars,
        "Ada subjudul & poin": bool(re.search(r"^[A-Z ]{6,}$", body, re.M)) and "\n- " in body,
        "Ada spesifikasi/ukuran": "SPESIFIKASI" in body or bool(SIZE_PATTERN.search(body)),
        "Hashtag 3–10": 3 <= len(tags) <= 10,
        "Kata kunci tidak berlebihan (≤3%)": density <= 3.0,
        "Tanpa link/kontak": not CONTACT.search(body.replace("#", " ")),
        "Unik (mirip ≤60% dengan produk lain)": similarity <= 0.60,
    }


def description_similarity(texts: list[str]) -> tuple[list[float], list[int]]:
    """Kemiripan tertinggi tiap deskripsi dengan deskripsi produk lain (TF-IDF cosine, tanpa hashtag)."""
    if len(texts) < 2:
        return [0.0] * len(texts), [-1] * len(texts)
    from sklearn.feature_extraction.text import TfidfVectorizer

    clean = [re.sub(r"#\w+", " ", str(t or "")) for t in texts]
    if not any(re.search(r"[a-z0-9]{2,}", c.lower()) for c in clean):
        return [0.0] * len(texts), [-1] * len(texts)
    matrix = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1, sublinear_tf=True).fit_transform(clean)
    sims = (matrix @ matrix.T).toarray()
    np.fill_diagonal(sims, 0.0)
    idx = sims.argmax(axis=1)
    return [float(sims[i, j]) for i, j in enumerate(idx)], [int(j) for j in idx]


def competitor_lists(own: pd.DataFrame, competitors: pd.DataFrame) -> tuple[dict[str, dict], pd.DataFrame]:
    """Kompetitor per produk dari daftar peringkat Shopee yang sama (kolom Daftar).

    1) Produk sendiri yang tercantum di daftar (Toko sendiri = True) → pembanding = produk lain di daftar itu, posisi kita tercatat.
    2) Selain itu → daftar yang judulnya paling mirip (TF-IDF), pembanding = 5 produk termirip di daftar itu.
    Bobot pembanding = 1 ÷ log2(peringkat + 1): peringkat atas lebih berpengaruh pada kata kunci."""
    comp = competitors.copy() if competitors is not None else pd.DataFrame()
    if comp.empty or "product_name" not in comp.columns:
        return {}, comp
    comp["product_name"] = comp["product_name"].fillna("").astype(str)
    comp["_rank"] = pd.to_numeric(comp.get("rank", pd.Series(np.nan, index=comp.index)), errors="coerce")
    comp["_change"] = pd.to_numeric(comp.get("rank_change", pd.Series(np.nan, index=comp.index)), errors="coerce")
    comp["_list"] = comp["Daftar"].astype(str) if "Daftar" in comp.columns else "1"
    own_flag = comp["own_shop"].astype(str).str.lower().isin({"true", "1"}) if "own_shop" in comp.columns else pd.Series(False, index=comp.index)
    comp["_own"] = own_flag
    comp["_w"] = 1.0 / np.log2(comp["_rank"].fillna(50).clip(lower=1) + 1)
    others = comp.loc[~comp["_own"]]
    mine = comp.loc[comp["_own"]]
    names = own["product_name"].fillna("").astype(str).tolist()
    keys = own["item_key"].astype(str).tolist()
    vec = _vectorize([strip_packing_words(n) for n in names] + [strip_packing_words(n) for n in comp["product_name"]])
    m = vec.matrix
    own_m, comp_m = m[: len(names)], m[len(names):]
    sims = (own_m @ comp_m.T).toarray() if vec.name == "TF-IDF" else np.asarray(own_m) @ np.asarray(comp_m).T
    pos = {idx: i for i, idx in enumerate(comp.index)}
    out: dict[str, dict] = {}
    for row, key in enumerate(keys):
        info = {"daftar": "", "posisi": np.nan, "perubahan": np.nan, "pembanding": [], "bobot": [], "sumber": ""}
        own_hits = [(sims[row, pos[i]], i) for i in mine.index if sims[row, pos[i]] >= 0.75]
        if own_hits:
            _sim, hit = max(own_hits)
            lst = comp.at[hit, "_list"]
            part = others.loc[others["_list"] == lst].sort_values("_rank")
            info.update(daftar=lst, posisi=comp.at[hit, "_rank"], perubahan=comp.at[hit, "_change"], sumber="Produk kita ada di daftar ini")
        else:
            cand = [(sims[row, pos[i]], i) for i in others.index]
            cand = [c for c in cand if c[0] > 0.1]
            if not cand:
                out[key] = info
                continue
            score: dict[str, float] = {}
            for sim, i in cand:
                score[comp.at[i, "_list"]] = score.get(comp.at[i, "_list"], 0.0) + sim
            lst = max(score, key=score.get)
            ranked = sorted([c for c in cand if comp.at[c[1], "_list"] == lst], reverse=True)[:5]
            part = others.loc[[i for _s, i in ranked]].sort_values("_rank")
            info.update(daftar=lst, sumber="Daftar paling mirip")
        info["pembanding"] = [pos[i] for i in part.index[:10]]
        info["bobot"] = part["_w"].tolist()[:10]
        out[key] = info
    return out, comp


def description_summary(text: str, limit: int = 60) -> str:
    """Kalimat pertama deskripsi, maks. `limit` karakter + "…"."""
    first = re.split(r"(?<=[.!?])\s", str(text or "").strip().split("\n")[0], maxsplit=1)[0].strip()
    if len(first) <= limit:
        return first
    return first[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def desc_hash(text: object) -> str:
    """Sidik deskripsi (abaikan spasi & huruf besar) untuk mendeteksi perubahan antar unggahan."""
    import hashlib

    norm = " ".join(str(text or "").lower().split())
    return hashlib.md5(norm.encode("utf-8")).hexdigest() if norm else ""


def title_similarity(a: str, b: str) -> float:
    """Kemiripan dua judul (Jaccard kata, tanpa tag packing) 0–1."""
    wa = set(clean_text(strip_packing_words(a)).split())
    wb = set(clean_text(strip_packing_words(b)).split())
    return len(wa & wb) / max(len(wa | wb), 1)


def _distinct_words(name: str, other: str) -> list[str]:
    """Kata/kode/ukuran di nama ini yang tidak ada di nama produk pembanding (urutan asli)."""
    theirs = set(clean_text(strip_packing_words(other)).split())
    words = strip_packing_words(name).replace(" - ", " ").split()
    out = []
    for i, word in enumerate(words):
        low = clean_text(word)
        if low and low not in theirs and low not in STOPWORDS:
            # Angka saja ("5") dibawa bersama kata berikutnya ("5 Hook") agar bermakna.
            phrase = f"{word} {words[i + 1]}" if word.isdigit() and i + 1 < len(words) else word
            if phrase not in out:
                out.append(phrase)
    return out[:6]


def _fit_long_title(clean_name: str, max_len: int) -> str:
    """Nama lama yang terlalu panjang: buang bagian 'Variasi …' / setelah ' - ', lalu potong per kata."""
    base = re.split(r"\s+-\s+Variasi\b|\bVariasi\b", clean_name, maxsplit=1, flags=re.IGNORECASE)[0].strip(" -")
    return fit_title(base, max_len)


def complete_title(title: str, *, name: str, variation: str, description: str, primary: list[str], supporting: list[str],
                   brands: list[str], vocab: set[str], max_len: int) -> tuple[str, list[str]]:
    """Lengkapi judul rekomendasi agar lolos cek SEO judul, hanya dengan kata yang ada di produk sendiri
    (nama, varian, deskripsi) atau kata kunci kompetitor yang lolos `allowed_keyword`. Mengembalikan (judul, catatan)."""
    notes: list[str] = []
    out = EMOJI_PATTERN.sub("", str(title or ""))
    out = re.sub(r"[!?*#~]+", " ", out)
    out = re.sub(r"\s+", " ", out).strip()

    def dedupe(text: str) -> str:
        seen: set[str] = set()
        words = []
        for word in text.split():
            key = re.sub(r"[^a-z0-9]", "", word.lower())
            if key and key in seen and len(key) > 2 and not key.isdigit():
                continue
            seen.add(key)
            words.append(word)
        return " ".join(words)

    out = dedupe(out)
    keys = [k for k in primary if allowed_keyword(k, vocab)]
    if keys and not any(k in clean_text(out[:40]) for k in keys[:2]):
        brand = _brand(out, brands)
        rest = out[len(brand):].strip() if brand and out.lower().startswith(brand.lower()) else out
        out = dedupe(" ".join(p for p in (brand, _title_case(keys[0]), rest) if p))
        notes.append(f"Kata kunci utama \"{keys[0]}\" dipindah ke awal judul (dicari pembeli & dipakai kompetitor teratas)")
    if len(out) < 60:
        low_all = clean_text(f"{name} {variation} {description}")
        size = SIZE_PATTERN.search(f"{variation} {name}")
        material = next((m for m in MATERIALS if re.search(rf"\b{m}\b", low_all)), "")
        # Hanya petunjuk kegunaan yang bermakna sendiri (bukan kata lepas seperti "tahan", "lem").
        usage = next((h for h in USAGE_HINTS if h in low_all and (" " in h or h in ("waterproof", "outdoor", "indoor", "eksterior", "interior"))), "")
        warranty = WARRANTY.search(f"{name} {description}")
        extras = [size.group(0) if size else "", material, usage, *[k for k in supporting if allowed_keyword(k, vocab)],
                  warranty.group(0) if warranty else ""]
        added = []
        for extra in extras:
            if len(out) >= 60:
                break
            if not extra or clean_text(extra) in clean_text(out):
                continue
            candidate = dedupe(f"{out} {_title_case(extra)}")
            if len(candidate) <= max_len:
                out = candidate
                added.append(extra)
        if len(out) < 60:
            # Kata dari nama asli yang belum terpakai (sudah pasti benar untuk produk ini).
            for word in str(name).split():
                if len(out) >= 60:
                    break
                key = re.sub(r"[^a-z0-9]", "", word.lower())
                if not key or key.isdigit() or len(key) < 3 or key in re.sub(r"[^a-z0-9 ]", "", out.lower()).split() or key in STOPWORDS:
                    continue
                candidate = f"{out} {word}"
                if len(candidate) <= max_len:
                    out = candidate
                    added.append(word)
        if added:
            notes.append("Judul dilengkapi: " + ", ".join(added) + " (dari data produk & kata kunci kompetitor)")
    out = fit_title(out, max_len)
    if not _brand(out, brands):
        notes.append("Merek belum terbaca di nama/deskripsi: tambahkan merek resmi produk secara manual")
    if not (SIZE_PATTERN.search(out) or MODEL_CODE.search(clean_text(out)) or MODEL_CODE.search(out.lower())
            or any(re.search(rf"\b{m}\b", clean_text(out)) for m in (*MATERIALS, *FINISHES))):
        notes.append("Ukuran/tipe/material tidak ada di data produk: lengkapi manual sebelum upload")
    return out, notes


def complete_description(text: str, *, title: str, name: str, variation: str, primary: list[str], supporting: list[str],
                         brands: list[str], max_chars: int) -> tuple[str, list[str]]:
    """Lengkapi deskripsi agar lolos cek SEO deskripsi: tanpa link/kontak, spesifikasi, panjang ≥600 karakter,
    kepadatan kata kunci utama ≤3%, 3–10 hashtag. Bagian tambahan disisipkan sebelum kalimat penutup "Pesan sekarang"."""
    notes: list[str] = []
    body, sep, tail = str(text or "").rpartition("\n\n")
    if not sep or not tail.strip().startswith("#"):
        body, tail = str(text or ""), ""
    tags = re.findall(r"#\w+", tail)
    lines = [line.lstrip("\\") for line in body.split("\n")]
    kept = [line for line in lines if not CONTACT.search(line.replace("#", " "))]
    if len(kept) < len(lines):
        notes.append("Baris berisi link/kontak dihapus (dilarang Shopee)")
    closing_at = next((i for i, line in enumerate(kept) if line.startswith("Pesan sekarang")), len(kept))
    head, closing = kept[:closing_at], kept[closing_at:]
    added: list[str] = []
    if "SPESIFIKASI" not in body and not SIZE_PATTERN.search(body):
        spec = ["SPESIFIKASI"]
        brand_keys = {re.sub(r"[^a-z0-9]", "", b.lower()) for b in brands}
        model = next((m for m in re.findall(r"[A-Za-z]{1,5}-?\d{2,}[A-Za-z0-9-]*", name) if re.sub(r"[^a-z0-9]", "", m.lower()) not in brand_keys), "")
        if model:
            spec.append(f"- Kode tipe: {model.upper()}")
        if variation and variation.lower() not in ("nan", "-", "tanpa variasi"):
            spec.append(f"- Varian: {variation}")
        brand = _brand(name, brands)
        if brand:
            spec.append(f"- Merek: {brand}")
        if len(spec) == 1:
            spec.append(f"- Nama produk: {title}")
        added += [""] + spec
        notes.append("Ditambah bagian SPESIFIKASI")

    def density(text_: str) -> float:
        low = clean_text(text_)
        if not primary or not low:
            return 0.0
        return keyword_count(text_, primary[0]) * max(len(primary[0].split()), 1) / max(len(low.split()), 1) * 100

    draft = "\n".join(head + added + closing)
    if len(draft) + len(tail) + 2 < 600 or density(draft) > 3.0:
        info = ["", "INFORMASI PEMBELIAN", "- Produk dijual langsung oleh Mitra10 Official Store dan dikirim dari gudang Mitra10.",
                "- Periksa pilihan varian, ukuran, dan warna sebelum checkout agar sesuai kebutuhan.",
                "- Simpan bukti pembelian untuk klaim garansi atau pengembalian sesuai ketentuan Shopee.",
                "- Hubungi chat toko bila butuh bantuan memilih tipe yang tepat sebelum membeli."]
        # Kata kunci pendukung (dari judul kompetitor) yang tidak mengulang kata kunci utama, agar kepadatan tetap ≤3%.
        related = [k for k in supporting if k and (not primary or primary[0] not in k)][:3]
        if related and density("\n".join(head + added + info + closing) + " " + " ".join(related)) <= 3.0:
            info.append("- Cocok juga untuk pencarian: " + ", ".join(related) + ".")
        added += info
        notes.append("Ditambah informasi pembelian (panjang ≥600 karakter & kepadatan kata kunci ≤3%)")
    body = "\n".join(head + added + ([""] if closing and added else []) + closing).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    if len(tags) < 3:
        brand = _brand(name, brands)
        pool = [*(t[1:] for t in tags), re.sub(r"[^a-z0-9]", "", brand.lower()), *[re.sub(r"[^a-z0-9]", "", k.lower()) for k in [*primary, *supporting]],
                "mitra10", "mitra10officialstore"]
        uniq: list[str] = []
        for t in pool:
            if 3 <= len(t) <= 30 and not any(ch.isdigit() for ch in t.replace("mitra10", "")) and t not in uniq:
                uniq.append(t)
        tags = ["#" + t for t in uniq[:8]]
        notes.append("Hashtag dilengkapi menjadi " + str(len(tags)))
    tail = " ".join(tags)
    # Hashtag baru bisa lebih panjang/pendek dari semula: pastikan total tetap ≥600 karakter dengan poin yang berlaku umum
    # (tidak mengarang spesifikasi produk).
    extra_pool = [
        "- Baca spesifikasi dan ukuran di atas untuk memastikan produk sesuai kebutuhan sebelum membeli.",
        "- Bila barang yang diterima rusak atau tidak sesuai, ajukan pengembalian lewat fitur Shopee dengan video unboxing.",
        "- Warna pada foto dapat sedikit berbeda dengan aslinya karena pencahayaan dan layar perangkat.",
    ]
    while len(body) + len(tail) + 2 < 600 and extra_pool:
        line = extra_pool.pop(0)
        at = body.find("\n\nPesan sekarang")
        body = (body[:at] + "\n" + line + body[at:]) if at >= 0 else (body + "\n" + line)
        if "Ditambah poin pembelian umum agar panjang ≥600 karakter" not in notes:
            notes.append("Ditambah poin pembelian umum agar panjang ≥600 karakter")
    budget = max_chars - len(tail) - 2
    if len(body) > budget:
        body = body[:budget].rsplit("\n", 1)[0].rstrip()
    return (body + ("\n\n" + tail if tail else "")), notes


def build_name_recommendations(
    own: pd.DataFrame,
    descriptions: pd.DataFrame | None,
    competitors: pd.DataFrame | None,
    cancel_reasons: dict[str, list[str]] | None,
    params: dict,
) -> tuple[pd.DataFrame, str]:
    """Satu baris per produk (item_key): skor nama lama, nama baru, kata kunci, USP, deskripsi unik siap upload, cek SEO.

    own boleh berisi kolom: item_key, sku, product_name, variasi_tampil, qty_total, harga_bersih, product_code, variants (list), skus (list)."""
    shopee = params.get("shopee", {})
    max_len = int(shopee.get("judul_maks_karakter", 120))
    min_len = int(shopee.get("judul_min_karakter", 25))
    max_desc = int(shopee.get("deskripsi_maks_karakter", 3000))
    desc_texts = descriptions["description"].astype(str).tolist() if descriptions is not None and not descriptions.empty and "description" in descriptions.columns else []
    brands = sorted(brand_set(own.get("product_name", pd.Series(dtype=str)).astype(str).tolist(), desc_texts, [str(b) for b in params.get("merek", [])]))
    desc_map: dict[str, str] = {}
    if descriptions is not None and not descriptions.empty and "description" in descriptions.columns:
        for _, row in descriptions.iterrows():
            text = str(row.get("description", "") or "")
            for col in ("product_code", "sku"):
                value = str(row.get(col, "") or "").strip()
                if value and value.lower() not in {"none", "nan"}:
                    desc_map.setdefault(f"{col}:{value}", text)
            name_key = clean_text(row.get("product_name", ""))
            if name_key:
                desc_map.setdefault(f"name:{name_key}", text)
    lists, comp = competitor_lists(own, competitors if competitors is not None else pd.DataFrame())
    vec_note = "Pembanding dari daftar peringkat Shopee yang sama (kolom Daftar); kecocokan judul TF-IDF + cosine; bobot 1/log2(peringkat+1)" if lists else "Data kompetitor kosong"
    if comp is not None and not comp.empty and "sold" in comp.columns:
        sold_all = comp["sold"].map(_sold_number).tolist()
    else:
        sold_all = None
    rows = []
    for _, item in own.iterrows():
        key = str(item["item_key"])
        name = str(item.get("product_name", ""))
        clean_name, tag = extract_packing_tag(name)
        variation = str(item.get("variasi_tampil", item.get("variation", "")) or "")
        info = lists.get(key, {})
        picked = info.get("pembanding", [])
        titles = [strip_packing_words(comp.iloc[i]["product_name"]) for i in picked] if picked else []
        weights = [sold_all[i] for i in picked] if picked and sold_all else [w * 10 for w in info.get("bobot", [])]
        code = str(item.get("product_code", "") or "").strip()
        current_desc = (desc_map.get(f"product_code:{code}") if code else None) or desc_map.get(f"sku:{str(item.get('sku', '')).strip()}") \
            or desc_map.get(f"name:{clean_text(name)}", "")
        vocab = vocabulary(clean_name, current_desc, variation, set(brands))
        primary, supporting = keyword_set(clean_name, titles, weights)
        primary = [k for k in primary if allowed_keyword(k, vocab)] or [k for k in tokens(clean_name)[:3] if allowed_keyword(k, vocab)]
        supporting = [k for k in supporting if allowed_keyword(k, vocab) and k not in primary]
        old = score_name(clean_name, primary, brands, min_len=min_len, max_len=max_len)
        room = max_len - (len(tag) + 1 if tag else 0)
        new_title = synthesize_title(clean_name, variation if not item.get("variants") else "", primary, brands, max_len=room)
        rejected = foreign_words(new_title, vocab)
        status = "Siap pakai"
        if rejected:
            new_title, status = clean_name, MANUAL_CHECK
        new_score = score_name(new_title, primary, brands, min_len=min_len, max_len=max_len)
        # Judul baru tidak boleh membuang kata yang dicari pembeli: bila < 75% kata penting nama lama masih ada, pakai nama lama.
        old_words = {w for w in clean_text(clean_name).split() if len(w) > 2 and w not in STOPWORDS and not w.isdigit()}
        kept = len(old_words & set(clean_text(new_title).split())) / max(len(old_words), 1)
        # Kode tipe & ukuran (kata berangka, mis. ZT-22, 300ml) wajib tetap ada: sering diketik pembeli saat mencari.
        def _coded(text: str) -> set[str]:
            raw = re.split(r"\bvariasi\b", str(text).lower())[0]
            return {re.sub(r"[^a-z0-9]", "", w) for w in re.findall(r"[a-z0-9][a-z0-9.\-/]*[a-z0-9]", raw) if any(c.isdigit() for c in w) and any(c.isalpha() for c in w)}

        coded = _coded(clean_name)
        if coded and not coded <= _coded(new_title):
            kept = 0.0
        if new_score.points < old.points or (kept < 0.75 and len(clean_name) <= max_len):
            new_title, new_score = clean_name, old
        elif kept < 0.75:
            fitted = _fit_long_title(clean_name, room)
            fitted_kept = len(old_words & set(clean_text(fitted).split())) / max(len(old_words), 1)
            if fitted_kept > kept:
                new_title, new_score = fitted, score_name(fitted, primary, brands, min_len=min_len, max_len=max_len)
        new_title, title_notes = complete_title(new_title, name=clean_name, variation=variation, description=current_desc, primary=primary,
                                                supporting=supporting, brands=brands, vocab=vocab, max_len=room)
        if foreign_words(new_title, vocab):
            new_title, title_notes = clean_name if len(clean_name) <= room else _fit_long_title(clean_name, room), title_notes + ["Judul dikembalikan: ada kata di luar data produk"]
        new_score = score_name(new_title, primary, brands, min_len=min_len, max_len=max_len)
        final_title = with_tag(new_title, tag, SHOPEE_TITLE_HARD, ideal=max_len)
        variants = [v for v in (item.get("variants") or []) if str(v).strip() and str(v).lower() not in {"nan", "none"}]
        usp = usp_points(name, current_desc, variation, titles, brands)
        description = generate_description(
            title=new_title, name=name, variation=variation, description=current_desc, primary=primary, supporting=supporting,
            cancel_reasons=(cancel_reasons or {}).get(key, []), max_chars=max_desc, usp=usp, variants=variants, brands=brands,
        )
        description, desc_notes = complete_description(description, title=new_title, name=clean_name, variation=variation, primary=primary,
                                                       supporting=supporting, brands=brands, max_chars=max_desc)
        posisi = info.get("posisi", np.nan)
        rows.append(
            {
                "item_key": key,
                "SKU": str(item.get("sku", "")),
                "Kode produk": code,
                "Jumlah SKU": int(item.get("n_sku", 1) or 1),
                "Nama produk saat ini": name,
                "Status skor": old.label,
                "Poin skor": old.points,
                "Rekomendasi nama baru": final_title,
                "Skor nama baru": new_score.label,
                "Status saran": status,
                "Kata ditolak": ", ".join(rejected),
                "Tag packing": tag or "",
                "Kata kunci utama": ", ".join(primary),
                "Kata kunci pendukung": ", ".join(supporting),
                "USP": usp,
                "Rekomendasi deskripsi": description,
                "Alasan skor": "; ".join(old.reasons) or "Semua kriteria terpenuhi",
                "Kriteria": old.checks,
                "Kekuatan deskripsi lama": description_strengths(current_desc),
                "Ada deskripsi lama": bool(current_desc.strip()),
                "Kompetitor dibandingkan": len(titles),
                "Daftar kompetitor": info.get("daftar", ""),
                "Peringkat kita": posisi,
                "Perubahan peringkat": info.get("perubahan", np.nan),
                "Sumber pembanding": info.get("sumber", ""),
                "Pembanding teratas": [(comp.iloc[i]["product_name"], comp.iloc[i]["_rank"], comp.iloc[i].get("shop_name", "")) for i in picked[:3]] if picked else [],
                "SEO judul": seo_title_checks(final_title, primary, brands, max_len=max_len),
                "_desc_now": current_desc,
                "SEO judul saat ini": seo_title_checks(name, primary, brands, max_len=max_len),
                "Dilengkapi": title_notes + desc_notes,
                "Kata kunci kompetitor": ", ".join(primary[:3]) if titles else "",
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out, vec_note
    sims, partner = description_similarity(out["Rekomendasi deskripsi"].tolist())
    # Produk satu seri (beda ukuran/kode/warna) sering berbagi deskripsi: tambahkan baris pembeda dari nama masing-masing.
    texts = out["Rekomendasi deskripsi"].tolist()
    changed = False
    for i, (sim, j) in enumerate(zip(sims, partner)):
        if sim <= 0.60 or j < 0:
            continue
        mine_words = _distinct_words(out.iloc[i]["Nama produk saat ini"], out.iloc[j]["Nama produk saat ini"])
        other_words = _distinct_words(out.iloc[j]["Nama produk saat ini"], out.iloc[i]["Nama produk saat ini"])
        if not mine_words:
            continue
        line = f"Pembeda tipe ini: {', '.join(mine_words)}" + (f" (produk serupa: {', '.join(other_words)})" if other_words else "") + " — pastikan memilih tipe yang sesuai kebutuhan."
        head, _sep, rest = texts[i].partition("\n")
        texts[i] = f"{head}\n{line}\n{rest}"
        if len(texts[i]) > max_desc:
            body, _s, tags = texts[i].rpartition("\n\n")
            texts[i] = body[: max_desc - len(tags) - 3].rsplit("\n", 1)[0] + "\n\n" + tags
        changed = True
    if changed:
        out["Rekomendasi deskripsi"] = texts
        sims, partner = description_similarity(texts)
    out["Kemiripan deskripsi"] = [s * 100 for s in sims]
    out["Paling mirip dengan"] = [out.iloc[j]["Nama produk saat ini"] if j >= 0 else "" for j in partner]
    out["SEO deskripsi"] = [
        seo_description_checks(text, [k.strip() for k in str(kw).split(",") if k.strip()], max_chars=max_desc, similarity=sim)
        for text, kw, sim in zip(out["Rekomendasi deskripsi"], out["Kata kunci utama"], sims)
    ]
    # Kondisi listing saat ini (nama & deskripsi yang sedang tayang) — dasar pelacakan perubahan antar unggahan.
    now_sims, _p = description_similarity(out["_desc_now"].fillna("").tolist())
    now_desc = [
        seo_description_checks(text, [k.strip() for k in str(kw).split(",") if k.strip()], max_chars=max_desc, similarity=sim) if str(text).strip()
        else {k: False for k in seo_description_checks("x", ["x"], max_chars=max_desc)}  # belum ada deskripsi = semua kaidah belum terpenuhi
        for text, kw, sim in zip(out["_desc_now"], out["Kata kunci utama"], now_sims)
    ]
    out["Skor SEO saat ini"] = [
        round((sum(a.values()) + sum(b.values())) / max(len(a) + len(b), 1) * 100) for a, b in zip(out["SEO judul saat ini"], now_desc)
    ]
    out["Hash deskripsi saat ini"] = [desc_hash(t) for t in out["_desc_now"]]
    out = out.rename(columns={"_desc_now": "Deskripsi saat ini"})
    out["Skor SEO"] = [
        round((sum(a.values()) + sum(b.values())) / max(len(a) + len(b), 1) * 100)
        for a, b in zip(out["SEO judul"], out["SEO deskripsi"])
    ]
    # Yang masih gagal setelah dilengkapi otomatis = harus dilengkapi manual sebelum upload.
    out["Masih kurang"] = [
        [f"Judul: {k}" for k, ok in a.items() if not ok] + [f"Deskripsi: {k}" for k, ok in b.items() if not ok]
        for a, b in zip(out["SEO judul"], out["SEO deskripsi"])
    ]
    out["Kekurangan saat ini"] = [
        [f"Judul: {k}" for k, ok in a.items() if not ok] + [f"Deskripsi: {k}" for k, ok in b.items() if not ok]
        for a, b in zip(out["SEO judul saat ini"], now_desc)
    ]
    out["Siap upload"] = [not miss for miss in out["Masih kurang"]]
    return out, vec_note
