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
    return Vectorizer("TF-IDF", "TF-IDF + cosine similarity (Sentence-BERT tidak terpasang)", matrix, vec)


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
        "Panjang sesuai batas Shopee": min_len <= len(text) <= max_len,
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


def _title_case(text: str) -> str:
    keep_upper = {"pvc", "upvc", "ppr", "hpl", "mdf", "spc", "led", "sni", "ac", "dc"}
    out = []
    for word in text.split():
        low = word.lower()
        if low in keep_upper:
            out.append(low.upper())
        elif SIZE_PATTERN.fullmatch(word) or any(ch.isdigit() for ch in word):
            out.append(word)
        else:
            out.append(word.capitalize())
    return " ".join(out)


def synthesize_title(name: str, variation: str, primary: list[str], brands: list[str], *, max_len: int) -> str:
    """[Brand] + [Jenis Produk] + [Material/Ukuran] + [Keunggulan Utama]."""
    low = clean_text(name)
    brand = _brand(name, brands)
    material = next((m for m in MATERIALS if re.search(rf"\b{m}\b", low)), "")
    size_match = SIZE_PATTERN.search(f"{name} {variation}")
    size = size_match.group(0) if size_match else ""
    usage = next((hint for hint in USAGE_HINTS if hint in low), "")
    used = {brand.lower(), material, size.lower(), usage}
    product_words = [w for w in tokens(name) if w not in used and w not in brand.lower().split() and not SIZE_PATTERN.fullmatch(w)]
    product_type = " ".join(product_words[:4])
    keyword = next((k for k in primary if k not in low), "")
    parts = [brand, product_type, material, size, usage, keyword]
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
        title = title[:max_len].rsplit(" ", 1)[0]
    return title or _title_case(str(name))[:max_len]


def description_strengths(description: str) -> dict[str, bool]:
    low = clean_text(description)
    return {aspect: any(word in low for word in words) for aspect, words in DESCRIPTION_ASPECTS.items()}


def _spec_lines(description: str, name: str, variation: str) -> list[str]:
    lines = []
    for raw in re.split(r"[\n\r]+", str(description or "")):
        line = " ".join(raw.replace("•", "-").split()).strip("-* ")
        if not line or len(line) > 120:
            continue
        if ":" in line or SIZE_PATTERN.search(line):
            lines.append(line)
    if not lines:
        size = SIZE_PATTERN.search(f"{name} {variation}")
        if size:
            lines.append(f"Ukuran/isi: {size.group(0)}")
        if variation and variation.lower() not in {"", "tanpa variasi"}:
            lines.append(f"Varian: {variation}")
    return lines[:8]


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
) -> str:
    """Deskripsi teks polos siap tempel ke Shopee (tanpa HTML/markdown)."""
    low = clean_text(name)
    usage = [hint for hint in USAGE_HINTS if hint in low][:3]
    material = next((m for m in MATERIALS if re.search(rf"\b{m}\b", low)), "")
    key_main = primary[0] if primary else " ".join(tokens(name)[:3])
    usage_text = ", ".join(usage) if usage else "kebutuhan renovasi dan perbaikan rumah"
    intro = (
        f"{title} adalah pilihan {key_main} untuk {usage_text}. "
        f"Produk ini dikirim dari gudang Mitra10 sehingga stok dan kualitasnya terjaga."
    )
    sections = [intro, ""]
    sections += ["FITUR DAN MANFAAT"]
    features = [f"- {k.capitalize()} sesuai kebutuhan proyek" for k in (primary[1:3] or [])]
    if material:
        features.insert(0, f"- Bahan {material} yang kuat dan awet")
    features.append("- Produk resmi, kondisi baru, dikemas aman untuk pengiriman")
    sections += features + [""]
    sections += ["KEGUNAAN", f"Cocok untuk {usage_text}. Dapat dipakai untuk proyek rumah tinggal, ruko, maupun kontraktor.", ""]
    specs = _spec_lines(description, name, variation)
    if specs:
        sections += ["SPESIFIKASI"] + [f"- {line}" for line in specs] + [""]
    sections += [
        "CARA PEMASANGAN / PENGAPLIKASIAN",
        "1. Pastikan permukaan atau area pemasangan bersih dan kering.",
        "2. Ikuti petunjuk pada kemasan atau gunakan tenaga tukang berpengalaman.",
        "3. Periksa kembali hasil pemasangan sebelum digunakan.",
        "",
        "KENAPA MEMILIH PRODUK INI",
        "- Harga bersaing dengan kualitas terjamin dari Mitra10",
        "- Stok tersedia dan dikirim cepat",
        "- Dapat konsultasi produk melalui chat sebelum membeli",
        "",
    ]
    reason_text = " ".join(cancel_reasons).lower()
    shipping = ["INFORMASI PENGIRIMAN", "- Produk berat atau besar dikirim dengan ekspedisi yang sesuai."]
    if any(word in reason_text for word in ("ongkir", "pengiriman", "kirim", "alamat", "lama")):
        shipping.append("- Ongkos kirim dihitung otomatis di checkout; tanyakan estimasi pengiriman melalui chat.")
    if any(word in reason_text for word in ("bayar", "pembayaran")):
        shipping.append("- Selesaikan pembayaran agar pesanan langsung kami proses hari ini.")
    sections += shipping + [""]
    if supporting:
        sections += ["Kata kunci: " + ", ".join(supporting[:6]), ""]
    sections += ["Pesan sekarang dan pastikan proyek Anda selesai tepat waktu."]
    text = "\n".join(sections).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 3].rsplit("\n", 1)[0]
    return text


def description_summary(text: str, limit: int = 60) -> str:
    """Kalimat pertama deskripsi, maks. `limit` karakter + "…"."""
    first = re.split(r"(?<=[.!?])\s", str(text or "").strip().split("\n")[0], maxsplit=1)[0].strip()
    if len(first) <= limit:
        return first
    return first[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def build_name_recommendations(
    own: pd.DataFrame,
    descriptions: pd.DataFrame | None,
    competitors: pd.DataFrame | None,
    cancel_reasons: dict[str, list[str]] | None,
    params: dict,
) -> tuple[pd.DataFrame, str]:
    """Satu baris per SKU: skor nama lama, nama baru, kata kunci, deskripsi siap upload, analisa."""
    shopee = params.get("shopee", {})
    max_len = int(shopee.get("judul_maks_karakter", 120))
    min_len = int(shopee.get("judul_min_karakter", 25))
    max_desc = int(shopee.get("deskripsi_maks_karakter", 3000))
    desc_texts = descriptions["description"].astype(str).tolist() if descriptions is not None and not descriptions.empty and "description" in descriptions.columns else []
    brands = sorted(brand_set(own.get("product_name", pd.Series(dtype=str)).astype(str).tolist(), desc_texts, [str(b) for b in params.get("merek", [])]))
    desc_map: dict[str, str] = {}
    if descriptions is not None and not descriptions.empty and "description" in descriptions.columns:
        key_col = "sku" if "sku" in descriptions.columns else None
        for _, row in descriptions.iterrows():
            if key_col and str(row.get(key_col, "")).strip():
                desc_map[str(row[key_col]).strip()] = str(row.get("description", ""))
            name_key = clean_text(row.get("product_name", ""))
            if name_key:
                desc_map.setdefault(name_key, str(row.get("description", "")))
    comp = competitors if competitors is not None else pd.DataFrame()
    if not comp.empty and "own_shop" in comp.columns:
        comp = comp.loc[~comp["own_shop"].astype(str).str.lower().isin({"true", "1"})].reset_index(drop=True)
    matches, _scores, vec_note = match_competitors(own, comp)
    if not comp.empty and "sold" in comp.columns:
        comp_sold = comp["sold"].map(_sold_number).tolist()
    elif not comp.empty and "rank" in comp.columns:
        ranks = pd.to_numeric(comp["rank"], errors="coerce").fillna(20.0)
        comp_sold = (21.0 - ranks.clip(1, 20)).tolist()
    else:
        comp_sold = [1.0] * len(comp)
    rows = []
    for _, item in own.iterrows():
        key = str(item["item_key"])
        name = str(item.get("product_name", ""))
        clean_name, tag = extract_packing_tag(name)
        variation = str(item.get("variasi_tampil", item.get("variation", "")) or "")
        picked = matches.get(key, [])
        titles = [strip_packing_words(comp.iloc[i]["product_name"]) for i in picked] if picked else []
        sold = [comp_sold[i] for i in picked] if picked else []
        current_desc = desc_map.get(str(item.get("sku", "")).strip()) or desc_map.get(clean_text(name), "")
        vocab = vocabulary(clean_name, current_desc, variation, set(brands))
        primary, supporting = keyword_set(clean_name, titles, sold)
        primary = [k for k in primary if allowed_keyword(k, vocab)] or [k for k in tokens(clean_name)[:3] if allowed_keyword(k, vocab)]
        supporting = [k for k in supporting if allowed_keyword(k, vocab) and k not in primary]
        old = score_name(clean_name, primary, brands, min_len=min_len, max_len=max_len)
        room = max_len - (len(tag) + 1 if tag else 0)
        new_title = synthesize_title(clean_name, variation, primary, brands, max_len=room)
        rejected = foreign_words(new_title, vocab)
        status = "Siap pakai"
        if rejected:
            new_title, status = clean_name, MANUAL_CHECK
        new_score = score_name(new_title, primary, brands, min_len=min_len, max_len=max_len)
        if new_score.points < old.points:
            new_title, new_score = clean_name, old
        final_title = with_tag(new_title, tag, max_len)
        strengths = description_strengths(current_desc)
        description = generate_description(
            title=new_title,
            name=clean_name,
            variation=variation,
            description=current_desc,
            primary=primary,
            supporting=supporting,
            cancel_reasons=(cancel_reasons or {}).get(key, []),
            max_chars=max_desc,
        )
        rows.append(
            {
                "item_key": key,
                "SKU": str(item.get("sku", "")),
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
                "Rekomendasi deskripsi": description,
                "Alasan skor": "; ".join(old.reasons) or "Semua kriteria terpenuhi",
                "Kriteria": old.checks,
                "Kekuatan deskripsi lama": strengths,
                "Ada deskripsi lama": bool(current_desc.strip()),
                "Kompetitor dibandingkan": len(titles),
            }
        )
    return pd.DataFrame(rows), vec_note
