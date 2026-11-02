"""Fitur & benefit dari deskripsi produk SKU itu sendiri (Revisi Final 2D.3) dan hook per kategori."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

HOOKS = Path(__file__).resolve().parents[2] / "config" / "hooks.yaml"
UNIT = re.compile(r"\d+(?:[.,]\d+)?\s?(?:mm|cm|m|ml|l|liter|kg|gr|gram|g|watt|w|psi|bar|inch|in|pcs|lembar|m2|m²|tahun|jam|menit)\b", re.I)
USE_WORDS = ("tahan", "anti", "kedap", "kuat", "cepat", "mudah", "hemat", "awet", "garansi", "cocok", "untuk", "food grade", "sni")
TEMPLATE_HINTS = ("selamat datang", "toko kami", "mitra10", "jam operasional", "pengiriman", "retur", "komplain", "chat", "ready stock", "harga dapat berubah")


@lru_cache(maxsize=1)
def hooks() -> dict[str, list[str]]:
    try:
        data = yaml.safe_load(HOOKS.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    return {str(k): [str(x) for x in (v or [])] for k, v in data.items()}


def hook_for(category: str, index: int = 0) -> str:
    items = hooks().get(category) or hooks().get("Aksesoris") or [""]
    return items[index % len(items)]


def features_from_description(description: object, limit: int = 3) -> list[str]:
    """Kalimat berisi angka+satuan atau kata kegunaan; kalimat template toko dibuang."""
    text = str(description or "")
    if not text.strip() or text.lower() == "nan":
        return []
    pieces = re.split(r"[\n\r•\-–;]+|(?<=[.!?])\s+", text)
    picked: list[str] = []
    for piece in pieces:
        sentence = " ".join(piece.split()).strip(" .:")
        lower = sentence.lower()
        if len(sentence) < 8 or len(sentence) > 140 or any(h in lower for h in TEMPLATE_HINTS):
            continue
        if UNIT.search(sentence) or any(word in lower for word in USE_WORDS):
            if sentence not in picked:
                picked.append(sentence)
        if len(picked) >= limit:
            break
    return picked
