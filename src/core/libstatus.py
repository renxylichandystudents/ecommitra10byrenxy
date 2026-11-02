"""Cek import library model saat start. Hanya ditampilkan ke super_user (panel Status library)."""

from __future__ import annotations

import importlib

LIBRARIES = (
    ("prophet", "Prophet", "Prediksi total toko + kalender promo"),
    ("lightgbm", "LightGBM", "Model global LightGBM"),
    ("xgboost", "XGBoost", "Model global XGBoost"),
    ("shap", "SHAP", "Kepentingan fitur"),
    ("sentence_transformers", "Sentence-BERT", "Kemiripan nama kompetitor (fallback TF-IDF)"),
    ("pulp", "PuLP", "Optimasi restock (MILP)"),
)


def library_status() -> list[dict[str, str]]:
    rows = []
    for module, name, use in LIBRARIES:
        try:
            loaded = importlib.import_module(module)
            status, version = "Terpasang", str(getattr(loaded, "__version__", "") or "-")
        except Exception as exc:  # noqa: BLE001
            status, version = "Tidak tersedia", type(exc).__name__
        rows.append({"Library": name, "Status": status, "Versi / galat": version, "Dipakai untuk": use})
    return rows
