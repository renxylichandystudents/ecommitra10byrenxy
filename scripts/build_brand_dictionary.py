"""Bangun data/brand_dictionary.csv dari katalog sendiri (Data stok + Deskripsi produk).

Pemakaian:
    PYTHONPATH=. python scripts/build_brand_dictionary.py <file_stok.xlsx> [<file_deskripsi.xlsx>]
Tanpa argumen: membaca data tersimpan di folder data latih lokal.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from src.core.naming import BRAND_DICTIONARY_PATH, build_brand_dictionary
from src.core.schemas import SOURCE_SPECS, canonicalize_frame
from src.core.storage import LocalDataStore, read_upload_file


def _read(path: str, key: str) -> pd.DataFrame:
    raw = read_upload_file(Path(path).read_bytes(), Path(path).name, SOURCE_SPECS[key])
    return canonicalize_frame(raw, SOURCE_SPECS[key])[0]


def main(argv: list[str]) -> None:
    if argv:
        stock = _read(argv[0], "stock")
        desc = _read(argv[1], "product_descriptions") if len(argv) > 1 else pd.DataFrame()
    else:
        store = LocalDataStore()
        stock = store.read_source("stock")
        desc = store.read_source("product_descriptions")
    names = stock.get("product_name", pd.Series(dtype=str)).dropna().astype(str).tolist()
    texts = desc.get("description", pd.Series(dtype=str)).dropna().astype(str).tolist() if not desc.empty else []
    frame = build_brand_dictionary(names, texts)
    BRAND_DICTIONARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(BRAND_DICTIONARY_PATH, index=False)
    print(f"{len(frame)} merek -> {BRAND_DICTIONARY_PATH}")
    print(frame.to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1:])
