"""Pembersih nama produk untuk rekomendasi judul: tag packing, kamus merek, dan kosakata terbatas.

- Tag packing ("[INCLUDE PACKING KAYU]", "Extra Bubble Wrap", ...) dipisah dulu agar tidak
  terbaca sebagai material/kata kunci, lalu dipasang kembali di akhir judul apa adanya.
- Kosakata judul baru hanya boleh dari nama + deskripsi produk itu sendiri, kamus merek katalog
  (data/brand_dictionary.csv), dan kata kunci kategori. Kata lain (mis. merek kompetitor) =
  saran ditolak, judul kembali ke nama asli yang bersih, status "Perlu cek manual".
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import pandas as pd

BRAND_DICTIONARY_PATH = Path(__file__).resolve().parents[2] / "data" / "brand_dictionary.csv"
MANUAL_CHECK = "Perlu cek manual"

_PACK_CORE = (
    r"(?:(?:include|includes|incl\.?|termasuk|free|gratis|plus|dengan|extra|ekstra|\+)\s*)*"
    r"(?:(?:packing|packaging|kemasan|paking)\s*(?:kayu|kardus|dus|bubble(?:\s*wrap)?)|bubble\s*wrap)"
)
PACKING_PATTERNS = (
    re.compile(r"\[\s*[^\[\]]*?(?:packing|packaging|paking|bubble\s*wrap)[^\[\]]*\]", re.IGNORECASE),
    re.compile(r"\(\s*[^()]*?(?:packing|packaging|paking|bubble\s*wrap)[^()]*\)", re.IGNORECASE),
    re.compile(r"(?:proteksi\s+ganda\s+)?" + _PACK_CORE, re.IGNORECASE),
)
PACKING_WORDS = {"include", "includes", "incl", "packing", "packaging", "paking", "bubble", "wrap", "proteksi", "ganda", "extra", "ekstra"}

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "kloset": ("kloset", "closet", "toilet", "wc", "kamar mandi"),
    "shower": ("shower", "mandi", "kamar mandi"),
    "keran": ("keran", "kran", "kran air", "air"),
    "wastafel": ("wastafel", "sink", "bak cuci"),
    "pompa": ("pompa", "pompa air", "air"),
    "heater": ("water heater", "pemanas", "pemanas air", "air"),
    "pintu": ("pintu", "rumah"),
    "jendela": ("jendela", "rumah"),
    "cat": ("cat", "tembok", "dinding"),
    "lantai": ("lantai",),
    "rak": ("rak", "dinding"),
    "lampu": ("lampu",),
    "kunci": ("kunci", "pintu"),
    "pipa": ("pipa", "air"),
    "tangga": ("tangga",),
}
CATEGORY_TRIGGERS: dict[str, tuple[str, ...]] = {
    "kloset": ("kloset", "closet", "toilet", "wc"),
    "shower": ("shower",),
    "keran": ("keran", "kran"),
    "wastafel": ("wastafel", "sink"),
    "pompa": ("pompa",),
    "heater": ("heater", "pemanas"),
    "pintu": ("pintu", "door"),
    "jendela": ("jendela", "window"),
    "cat": ("cat",),
    "lantai": ("lantai", "vinyl", "flooring", "spc"),
    "rak": ("rak", "gantungan", "hook"),
    "lampu": ("lampu", "led", "bulb"),
    "kunci": ("kunci", "lock", "gembok"),
    "pipa": ("pipa",),
    "tangga": ("tangga",),
}


CATEGORY_LABELS = {
    "kloset": "kloset", "shower": "shower", "keran": "keran", "wastafel": "wastafel", "pompa": "pompa air",
    "heater": "water heater", "pintu": "pintu", "jendela": "jendela", "cat": "cat tembok", "lantai": "lantai",
    "rak": "rak", "lampu": "lampu", "kunci": "kunci pintu", "pipa": "pipa", "tangga": "tangga",
}


def category_label(name: object) -> str:
    """Nama kategori bersih untuk hook konten: dari kamus kategori, atau dua kata pertama nama tanpa tag packing."""
    from src.core.nlp_competitor import clean_text, tokens

    clean = clean_text(strip_packing_words(name))
    found = detect_categories(clean)
    if found:
        return CATEGORY_LABELS[found[0]]
    words = [w for w in tokens(clean) if not any(ch.isdigit() for ch in w) and w not in PACKING_WORDS]
    return " ".join(words[:2]) or "bahan bangunan"


def extract_packing_tag(name: object) -> tuple[str, str | None]:
    """("Kloset ... [INCLUDE PACKING KAYU]") -> ("Kloset ...", "[INCLUDE PACKING KAYU]"). Tag apa adanya."""
    text = " ".join(str(name or "").split())
    tags: list[str] = []
    for _ in range(3):
        match = next((m for m in (p.search(text) for p in PACKING_PATTERNS) if m), None)
        if match is None:
            break
        tags.append(match.group(0).strip())
        text = (text[: match.start()] + " " + text[match.end() :]).strip()
        text = re.sub(r"\s*[-–|,/+]\s*$", "", text).strip()
        text = re.sub(r"\s{2,}", " ", re.sub(r"\s+[-–]\s+(?=[-–]|$)", " ", text)).strip(" -–")
    return text, (" ".join(tags) if tags else None)


def strip_packing_words(text: object) -> str:
    clean, _tag = extract_packing_tag(text)
    return clean


def detect_categories(clean_name_low: str) -> list[str]:
    words = set(re.findall(r"[a-z0-9]+", clean_name_low))
    return [cat for cat, triggers in CATEGORY_TRIGGERS.items() if any(t in words for t in triggers)]


def category_words(categories: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for cat in categories:
        for phrase in CATEGORY_KEYWORDS.get(cat, ()):
            out.update(phrase.split())
    return out


GENERIC_NOUNS = {
    "bidet", "closet", "set", "kit", "series", "premium", "original", "putih", "hitam", "garansi", "tahun", "bundle",
    "refill", "cartridge", "filter", "sink", "heater", "door", "window", "shower", "only", "variant", "full",
}


def _kbbi_words() -> set[str]:
    try:
        from src.core.nlp_competitor import _stemmer

        stemmer = _stemmer()
        inner = getattr(stemmer, "delegatedStemmer", stemmer)
        return set(getattr(getattr(inner, "dictionary", None), "words", ()) or ())
    except Exception:
        return set()


def build_brand_dictionary(names: Iterable[str], descriptions: Iterable[str] = (), extra: Iterable[str] = ()) -> pd.DataFrame:
    """Kamus merek dari katalog sendiri: kolom "Merek:" di deskripsi, akhiran " - Merek" di nama, dan daftar Pengaturan."""
    counts: Counter = Counter()
    sources: dict[str, set[str]] = {}

    def add(brand: str, source: str) -> None:
        word = " ".join(brand.split()).strip(" -:+").strip()
        if len(word) < 2 or any(ch.isdigit() for ch in word) or word.lower() in PACKING_WORDS:
            return
        key = word.lower()
        counts[key] += 1
        sources.setdefault(key, set()).add(source)

    for text in descriptions:
        for match in re.finditer(r"(?i)\b(?:merek|merk|brand)\s*[:：]\s*([A-Za-z][A-Za-z+]{1,20})", str(text or "")):
            add(match.group(1), "deskripsi")
    generic = category_words(CATEGORY_KEYWORDS) | GENERIC_NOUNS | _kbbi_words()
    for name in names:
        clean, _tag = extract_packing_tag(name)
        match = re.search(r"\s[-–]\s*([A-Z][A-Za-z+]{2,20})\s*$", clean)
        if match and match.group(1).lower() not in generic:
            add(match.group(1), "nama")
    for brand in extra:
        add(str(brand), "pengaturan")
    rows = [{"merek": k, "jumlah": c, "sumber": ", ".join(sorted(sources[k]))} for k, c in counts.most_common()]
    return pd.DataFrame(rows, columns=["merek", "jumlah", "sumber"])


@lru_cache(maxsize=1)
def _saved_brands() -> frozenset[str]:
    try:
        frame = pd.read_csv(BRAND_DICTIONARY_PATH)
        return frozenset(frame["merek"].dropna().astype(str).str.lower())
    except Exception:
        return frozenset()


def brand_set(names: Iterable[str] = (), descriptions: Iterable[str] = (), extra: Iterable[str] = ()) -> set[str]:
    live = build_brand_dictionary(names, descriptions, extra)
    return set(_saved_brands()) | set(live["merek"].astype(str))


def vocabulary(clean_name: str, description: str, variation: str, brands: set[str]) -> set[str]:
    from src.core.nlp_competitor import clean_text

    low = clean_text(f"{clean_name} {variation}")
    words = set(re.findall(r"[a-z0-9.,x\"/-]+", low)) | set(re.findall(r"[a-z0-9]+", low))
    words |= set(re.findall(r"[a-z0-9]+", clean_text(strip_packing_words(description))))
    words |= {part for b in brands for part in b.lower().split()}
    words |= category_words(detect_categories(clean_text(clean_name)))
    return words


def foreign_words(title: str, vocab: set[str]) -> list[str]:
    """Kata pada judul yang tidak ada di kosakata produk itu."""
    from src.core.nlp_competitor import clean_text

    out = []
    for word in clean_text(title).split():
        if word in vocab or word.isdigit() or len(word) <= 1:
            continue
        parts = re.findall(r"[a-z0-9]+", word)
        if parts and all(p in vocab or p.isdigit() for p in parts):
            continue
        out.append(word)
    return out


def allowed_keyword(phrase: str, vocab: set[str]) -> bool:
    words = phrase.lower().split()
    return bool(words) and not any(w in PACKING_WORDS for w in words) and all(w in vocab for w in words)


def with_tag(title: str, tag: str | None, max_len: int) -> str:
    if not tag:
        return title[:max_len].rstrip()
    room = max_len - len(tag) - 1
    base = title if len(title) <= room else title[: max(room, 0)].rsplit(" ", 1)[0]
    return f"{base} {tag}".strip()
