"""Alasan batal → 4 kategori: Pembeli, Belum bayar, Penjual, Sistem Shopee (config/cancel_reasons.yaml)."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

CONFIG = Path(__file__).resolve().parents[2] / "config" / "cancel_reasons.yaml"
CATEGORIES = ("Pembeli", "Belum bayar", "Penjual", "Sistem Shopee")
LOG = logging.getLogger("mitra10.cancel_reasons")


@lru_cache(maxsize=1)
def _rules() -> tuple[tuple[str, tuple[str, ...]], ...]:
    try:
        data = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    return tuple((str(cat), tuple(str(p).lower() for p in phrases or ())) for cat, phrases in data.items())


# Teks alasan Shopee yang sama artinya tetapi berbeda tulisan/bahasa → satu label tampilan.
REASON_ALIASES = {
    "need to change delivery address": "Perlu mengubah alamat pengiriman",
    "change delivery address": "Perlu mengubah alamat pengiriman",
    "alasan lainnya": "Lainnya",
    "others": "Lainnya",
    "ubah pesanan yang ada": "Perlu mengubah pesanan",
    "modify existing order": "Perlu mengubah pesanan",
    "change of mind": "Tidak ingin membeli lagi",
    "pesanan belum dibayar": "Belum dibayar",
}
REASON_PREFIXES = (
    ("dibatalkan oleh pembeli. alasan:", "Pembeli"),
    ("dibatalkan secara otomatis oleh sistem shopee. alasan:", "Sistem Shopee"),
    ("dibatalkan oleh penjual. alasan:", "Penjual"),
)


def short_reason(reason: object) -> str:
    """"Dibatalkan oleh Pembeli. Alasan: Need to change delivery address" → "Pembeli · Perlu mengubah alamat pengiriman"."""
    text = " ".join(str(reason or "").split())
    if not text or text.lower() in {"nan", "none", "-"}:
        return "Tanpa alasan"
    who = ""
    lower = text.lower()
    for prefix, label in REASON_PREFIXES:
        if lower.startswith(prefix):
            who, text = label, text[len(prefix):].strip()
            break
    text = REASON_ALIASES.get(text.lower(), text)
    text = text[:1].upper() + text[1:] if text else "Tanpa alasan"
    return f"{who} · {text}" if who else text


def categorize(reason: object) -> str:
    text = str(reason or "").strip().lower()
    if not text or text in {"nan", "none", "-"}:
        return "Pembeli"
    for category, phrases in _rules():
        if any(phrase in text for phrase in phrases):
            return category
    LOG.info("Alasan batal belum dipetakan, masuk Pembeli: %s", text)
    return "Pembeli"


def categorize_series(reasons: pd.Series) -> pd.Series:
    unique = {value: categorize(value) for value in reasons.dropna().astype(str).unique()}
    return reasons.astype(str).map(unique).fillna("Pembeli")


def unknown_reasons(reasons: pd.Series) -> list[str]:
    """Teks alasan yang tidak cocok dengan frasa mana pun (untuk ditambahkan ke mapping)."""
    out = []
    for value in reasons.dropna().astype(str).str.strip().unique():
        text = value.lower()
        if text and not any(any(p in text for p in phrases) for _c, phrases in _rules()):
            out.append(value)
    return sorted(out)
