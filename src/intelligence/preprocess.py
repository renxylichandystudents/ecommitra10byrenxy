"""Pembersihan numerik untuk salinan uji.

Lonjakan atas dipotong (winsorize), bukan dihapus. Hari atau baris bernilai nol
tetap nol: pada bahan bangunan itu adalah hari tanpa pesanan, bukan noise.
Hasil fungsi ini tidak dipakai oleh prediksi stok produksi.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

METHODS = ("iqr", "zscore", "isolation_forest")


@dataclass(frozen=True)
class CleanReport:
    rows_in: int
    missing_filled: int
    values_clipped: int
    method: str
    note: str


def clean_series(values: np.ndarray, method: str = "iqr") -> tuple[np.ndarray, int]:
    """Potong lonjakan atas pada satu deret. Nilai non-finite menjadi 0."""
    array = np.asarray(values, dtype=float).copy()
    if array.size == 0:
        return array, 0
    invalid = ~np.isfinite(array)
    array[invalid] = 0.0
    lo, hi, ready = _upper_fence(array, method)
    if not ready:
        return array, 0
    mask = array > hi
    array[mask] = hi
    if lo > 0:
        low = (array > 0) & (array < lo)
        array[low] = lo
        mask = mask | low
    return array, int(mask.sum())


def clean_frame(
    frame: pd.DataFrame,
    method: str = "iqr",
    columns: tuple[str, ...] = ("qty", "sales"),
) -> tuple[pd.DataFrame, CleanReport]:
    """Isi angka kosong dengan median, lalu potong lonjakan atas pada salinan."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame() if not isinstance(frame, pd.DataFrame) else frame.copy(), CleanReport(
            0, 0, 0, _method(method), "Tidak ada baris untuk dibersihkan."
        )
    out = frame.copy()
    present = [column for column in columns if column in out.columns]
    if not present:
        return out, CleanReport(
            len(out),
            0,
            0,
            _method(method),
            "Kolom qty dan sales tidak ada. Uji memakai data apa adanya.",
        )
    filled = 0
    clipped = 0
    notes: list[str] = []
    for column in present:
        numeric = pd.to_numeric(out[column], errors="coerce")
        missing = int(numeric.isna().sum())
        if missing and numeric.notna().any():
            numeric = numeric.fillna(float(numeric.median()))
            filled += missing
        elif missing:
            numeric = numeric.fillna(0.0)
            notes.append(f"{column} kosong")
        cleaned, count = clean_series(numeric.to_numpy(dtype=float), method)
        clipped += count
        out[column] = cleaned
    note = "Lonjakan atas dipotong pada salinan uji. Prediksi stok tidak ikut berubah."
    if notes:
        note = f"{note} {' '.join(notes)}."
    return out, CleanReport(len(out), filled, clipped, _method(method), note)


def _method(method: str) -> str:
    key = str(method or "iqr").strip().lower()
    return key if key in METHODS else "iqr"


def _upper_fence(values: np.ndarray, method: str) -> tuple[float, float, bool]:
    positive = values[values > 0]
    if positive.size < 8:
        return 0.0, 0.0, False
    chosen = _method(method)
    if chosen == "zscore":
        center = float(np.mean(positive))
        spread = float(np.std(positive, ddof=1))
        if spread <= 0:
            return 0.0, 0.0, False
        return 0.0, center + 3.0 * spread, True
    if chosen == "isolation_forest":
        try:
            return _forest_fence(positive)
        except Exception:
            return _iqr_fence(positive)
    return _iqr_fence(positive)


def _iqr_fence(positive: np.ndarray) -> tuple[float, float, bool]:
    q1, q3 = np.quantile(positive, [0.25, 0.75])
    iqr = float(q3 - q1)
    if iqr <= 0:
        return 0.0, 0.0, False
    return float(q1 - 1.5 * iqr), float(q3 + 1.5 * iqr), True


def _forest_fence(positive: np.ndarray) -> tuple[float, float, bool]:
    from sklearn.ensemble import IsolationForest

    sample = positive
    if positive.size > 4000:
        rng = np.random.default_rng(42)
        sample = positive[rng.choice(positive.size, 4000, replace=False)]
    model = IsolationForest(
        n_estimators=40,
        contamination="auto",
        random_state=42,
        n_jobs=1,
    )
    label = model.fit_predict(sample.reshape(-1, 1))
    inliers = sample[label == 1]
    if inliers.size < 4:
        return _iqr_fence(positive)
    return float(np.min(inliers)), float(np.max(inliers)), True
