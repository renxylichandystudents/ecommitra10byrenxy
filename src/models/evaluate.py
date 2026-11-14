"""Walk-forward CV per horizon (Revisi Final 2A).

Satu record per horizon {hari, minggu, bulan, kuartal}. Semua tabel, grafik, KPI dan kalimat
kesimpulan di tab Evaluasi model dibaca dari record ini (tidak ada angka lain).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.ensemble import (
    BIAS_KEY,
    MODEL_ENSEMBLE,
    MODEL_ES,
    MODEL_GBM,
    MODEL_GBM_FALLBACK,
    MODEL_LEVEL,
    MODEL_LGBM,
    MODEL_MA,
    MODEL_PROPHET,
    DemandMatrix,
    blend,
    ensemble_weights,
    model_forecasts_multi,
)
from src.core.evaluation import MAPE_TARGET_PCT, WalkForwardResult, bias_pct, mape, rmse, top_n_hits, wape

HORIZONS = {"hari": 1, "minggu": 7, "bulan": 30, "kuartal": 91}
HORIZON_LABELS = {"hari": "Hari", "minggu": "Minggu", "bulan": "Bulan", "kuartal": "Kuartal"}
PERIOD_TO_HORIZON = {"hari": "hari", "minggu": "minggu", "bulan": "bulan", "kuartal": "kuartal", "semester": "kuartal", "tahun": "kuartal"}
MODEL_KEYS = {
    MODEL_LEVEL: "level_terkini",
    MODEL_MA: "ma28",
    MODEL_ES: "exp_smoothing",
    MODEL_GBM: "xgboost_global",
    MODEL_GBM_FALLBACK: "xgboost_global",
    MODEL_LGBM: "lightgbm_global",
    MODEL_PROPHET: "prophet",
    MODEL_ENSEMBLE: "ensemble",
    "Ensemble per segmen": "ensemble_segmen",
}
FOLDS = 6
SEGMENT_KEY = "_model_per_segmen"
MODEL_SEGMENT = "Ensemble per segmen"
MIN_TRAIN_DAYS = 35
BIAS_FACTOR_LIMITS = (0.5, 1.5)
SS_CALIBRATION_LIMITS = (0.5, 5.0)
SS_CALIBRATION_KEY = "_kalibrasi_ss"
SS_CLASS_KEY = "_pengali_ss_kelas"  # pengali SS per kelas ABC (kuantil empiris galat) untuk metode "empiris"
SS_METHODS = {"normal": "Normal Z × r (MAD)", "empiris": "Kuantil empiris galat per kelas (conformal)"}
MAD_TO_SIGMA = 0.6745
SERVICE_LEAD_DAYS = 7
SIGMA_DAYS = 180  # jendela simpangan harian untuk SS (sama dengan produksi, src.forecast.SIGMA_DAYS)


def month_cutoffs(dates: pd.DatetimeIndex, folds: int = FOLDS) -> list[int]:
    """Titik potong = tanggal 1 tiap bulan (enam bulan terakhir yang punya ≥ 35 hari latih)."""
    if len(dates) == 0:
        return []
    starts = [i for i, day in enumerate(dates) if day.day == 1 and i >= MIN_TRAIN_DAYS]
    return starts[-folds:]


def abc_classes(matrix: DemandMatrix, end: int) -> np.ndarray:
    """ABC dari QTY 90 hari sebelum titik potong pertama: A ≤ 80%, B ≤ 95%, sisanya C."""
    if not len(matrix.keys):
        return np.array([], dtype=object)
    volume = matrix.filled[:, max(end - 90, 0) : end].sum(axis=1)
    order = np.argsort(-volume)
    share = np.cumsum(volume[order]) / max(volume.sum(), 1e-9)
    labels = np.empty(len(volume), dtype=object)
    labels[order] = np.where(share <= 0.80, "A", np.where(share <= 0.95, "B", "C"))
    labels[volume <= 0] = "C"
    return labels


def xyz_classes(matrix: DemandMatrix, end: int) -> np.ndarray:
    """XYZ dari koefisien variasi permintaan mingguan 12 minggu: X ≤ 0,5, Y ≤ 1,0, Z sisanya."""
    if not len(matrix.keys):
        return np.array([], dtype=object)
    lo = max(end - 84, 0)
    part = matrix.filled[:, lo:end]
    weeks = part.shape[1] // 7
    if weeks < 2:
        return np.full(len(matrix.keys), "Z", dtype=object)
    weekly = part[:, -weeks * 7 :].reshape(len(matrix.keys), weeks, 7).sum(axis=2)
    mean = weekly.mean(axis=1)
    cv = np.where(mean > 0, weekly.std(axis=1) / np.maximum(mean, 1e-9), np.inf)
    return np.where(cv <= 0.5, "X", np.where(cv <= 1.0, "Y", "Z")).astype(object)


def _num(value: float) -> float | None:
    return None if value is None or not np.isfinite(value) else round(float(value), 4)


def _scores(actual: np.ndarray, pred: np.ndarray, classes: np.ndarray, aggregate: list[tuple[float, float]]) -> dict:
    per_class = {}
    for name in ("A", "B", "C"):
        mask = classes == name
        per_class[name] = _num(mape(actual[mask], pred[mask])) if mask.any() else None
    agg_a = np.array([a for a, _ in aggregate])
    agg_p = np.array([p for _, p in aggregate])
    return {
        "mape": _num(mape(actual, pred)),
        "mape_agregat": _num(mape(agg_a, agg_p)),
        "wape": _num(wape(actual, pred)),
        "bias": _num(bias_pct(actual, pred)),
        "rmse": _num(rmse(actual, pred)),
        "mape_per_kelas_ABC": per_class,
    }


def evaluate_horizon(
    matrix: DemandMatrix,
    horizon_name: str,
    *,
    fold_forecasts: dict[int, dict[int, dict[str, np.ndarray]]],
    cutoffs: list[int],
    top_n: int = 50,
) -> dict:
    """Record satu horizon dari prediksi per lipatan yang sudah dihitung."""
    days = HORIZONS[horizon_name]
    total_days = matrix.values.shape[1] if matrix.values.size else 0
    usable = [cut for cut in cutoffs if cut + days <= total_days and cut in fold_forecasts]
    record = {
        "horizon": horizon_name,
        "days": days,
        "fold_dates": [str(matrix.dates[cut].date()) for cut in usable],
        "n_sku": len(matrix.keys),
        "models": {},
        "notes": [],
    }
    if not usable:
        record["notes"].append(f"Riwayat belum cukup untuk walk-forward horizon {HORIZON_LABELS[horizon_name].lower()} ({days} hari).")
        return record
    classes = abc_classes(matrix, usable[0])
    segments = classes + xyz_classes(matrix, usable[0])
    common = set.intersection(*(set(fold_forecasts[cut][days]) for cut in usable))
    for name in sorted(set.union(*(set(fold_forecasts[cut][days]) for cut in usable)) - common):
        record["notes"].append(f"{name} tidak tersedia di semua lipatan, tidak ikut dibandingkan.")
    pairs: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
    valid = [~np.isnan(matrix.values[:, cut : cut + days]).any(axis=1) for cut in usable]
    dropped = sum(int((~v).sum()) for v in valid)
    if dropped:
        record["notes"].append(f"{dropped} pasangan SKU-lipatan tidak dinilai karena ada hari stok kosong di periode uji "
                               "(permintaan aslinya tidak terlihat, bukan 0).")
    for cut in usable:
        actual = matrix.filled[:, cut : cut + days].sum(axis=1)
        for name in sorted(common):
            pairs.setdefault(name, []).append((actual, np.asarray(fold_forecasts[cut][days][name], dtype=float)))

    def stacked(name: str) -> tuple[np.ndarray, np.ndarray, list[tuple[float, float]]]:
        items = [(a[v], p[v]) for (a, p), v in zip(pairs[name], valid)]
        return (
            np.concatenate([a for a, _ in items]),
            np.concatenate([p for _, p in items]),
            [(float(a.sum()), float(p.sum())) for a, p in items],
        )

    fold_classes = np.concatenate([classes[v] for v in valid])
    fold_segments = np.concatenate([segments[v] for v in valid])
    for name in list(pairs):
        actual, pred, aggregate = stacked(name)
        record["models"][MODEL_KEYS.get(name, name)] = {"label": name, **_scores(actual, pred, fold_classes, aggregate)}

    singles = {name: record["models"][MODEL_KEYS.get(name, name)]["wape"] for name in pairs}
    weights = ensemble_weights({k: (v if v is not None else np.nan) for k, v in singles.items()})
    raw = [(a, blend({n: pairs[n][i][1] for n in pairs}, weights)) for i, (a, _p) in enumerate(pairs[MODEL_LEVEL])]
    raw_bias = bias_pct(np.concatenate([a[v] for (a, _), v in zip(raw, valid)]), np.concatenate([p[v] for (_, p), v in zip(raw, valid)]))
    factor = 1.0 / (1.0 + raw_bias / 100.0) if np.isfinite(raw_bias) and raw_bias > -100 else 1.0
    factor = float(np.clip(factor, *BIAS_FACTOR_LIMITS))
    pairs[MODEL_ENSEMBLE] = [(a, p * factor) for a, p in raw]
    actual, pred, aggregate = stacked(MODEL_ENSEMBLE)
    record["models"]["ensemble"] = {"label": MODEL_ENSEMBLE, **_scores(actual, pred, fold_classes, aggregate)}
    for key, info in record["models"].items():
        info["bobot_ensemble"] = round(float(weights.get(info["label"], 0.0)), 4) if key != "ensemble" else None
        hits = [top_n_hits(a[v], p[v], top_n) for (a, p), v in zip(pairs[info["label"]], valid)]
        info["top50_tepat"] = round(float(np.mean(hits)), 1) if hits else None
    record["bias_sebelum_koreksi"] = _num(raw_bias)
    record["faktor_koreksi_bias"] = round(factor, 4)
    record["weights"] = {**{k: round(float(v), 4) for k, v in weights.items()}, BIAS_KEY: round(factor, 4)}

    choice = {}
    for segment in sorted(set(segments)):
        mask = fold_segments == segment
        if not mask.any() or actual[mask].sum() <= 0:
            continue
        ens = wape(actual[mask], pred[mask])
        best_name, best_score = None, ens
        for name in pairs:
            if name == MODEL_ENSEMBLE:
                continue
            a, p, _ = stacked(name)
            score = wape(a[mask], p[mask])
            if np.isfinite(score) and score < best_score:
                best_name, best_score = name, score
        if best_name is not None:
            choice[segment] = {"model": best_name, "wape_model": _num(best_score), "wape_ensemble": _num(ens)}
    record["model_per_segmen"] = choice
    record["weights"][SEGMENT_KEY] = {segment: info["model"] for segment, info in choice.items()}
    if choice:
        picked = [(a, p.copy()) for a, p in pairs[MODEL_ENSEMBLE]]
        for segment, info in choice.items():
            mask = segments == segment
            for index, (a, p) in enumerate(picked):
                p[mask] = pairs[info["model"]][index][1][mask]
        pairs[MODEL_SEGMENT] = picked
        actual_s, pred_s, aggregate_s = stacked(MODEL_SEGMENT)
        record["models"]["ensemble_segmen"] = {
            "label": MODEL_SEGMENT,
            **_scores(actual_s, pred_s, fold_classes, aggregate_s),
            "bobot_ensemble": None,
            "top50_tepat": round(float(np.mean([top_n_hits(a[v], p[v], top_n) for (a, p), v in zip(picked, valid)])), 1),
        }
        record["notes"].append(
            f"{MODEL_SEGMENT} = model yang dipakai prediksi produksi. Bobot ensemble, faktor koreksi bias, dan pilihan model per segmen "
            "ditentukan dari lipatan yang sama dengan penilaiannya (in-sample), jadi angka Ensemble & Ensemble per segmen cenderung sedikit optimis "
            "dibanding model tunggal."
        )

    ranked = sorted(
        (info for info in record["models"].values() if info["wape"] is not None),
        key=lambda info: info["wape"],
    )
    record["best_model"] = MODEL_KEYS.get(ranked[0]["label"], ranked[0]["label"]) if ranked else None
    singles_only = {name: pairs[name] for name in pairs if name not in (MODEL_ENSEMBLE, MODEL_SEGMENT)}
    record["luar_sampel"], oos_preds = _nested_scores(singles_only, valid, segments, fold_classes_list=[classes[v] for v in valid],
                                                      fold_dates=record["fold_dates"])
    prod_key = (record["luar_sampel"] or {}).get("best_model") or record["best_model"]
    prod_label = next((info["label"] for key, info in record["models"].items() if key == prod_key), MODEL_SEGMENT)
    record["model_produksi"] = prod_key
    record["weights_produksi"] = production_weights(record["weights"], prod_label)
    record["per_lipatan"] = _fold_totals(matrix, usable, valid, pairs, oos_preds, prod_label, days)
    if days == HORIZONS["bulan"]:
        # Prediksi luar sampel model produksi (lipatan 2 dst.); tanpa uji luar sampel, prediksi lipatan uji biasa.
        preds = {k + 1: p for k, (_a, p) in enumerate(oos_preds.get(prod_label, []))} if oos_preds.get(prod_label) else \
            {k: p for k, (_a, p) in enumerate(pairs.get(prod_label) or pairs.get(MODEL_SEGMENT) or pairs[MODEL_ENSEMBLE])}
        record["simulasi_ss"] = _service_simulation(matrix, usable, preds, days)
    record["kesimpulan"] = conclusion_text(record)
    return record


def _fold_totals(matrix: DemandMatrix, usable: list[int], valid: list[np.ndarray], pairs: dict, oos_preds: dict, prod_label: str,
                 days: int) -> list[dict]:
    """Total toko per lipatan: aktual, aktual periode sebelumnya (perubahan permintaan), prediksi model produksi (luar sampel bila
    tersedia) dan MA28. Menjelaskan dari mana MAPE agregat & bias berasal (mis. satu bulan kampanye yang melonjak)."""
    out = []
    oos = oos_preds.get(prod_label) or []
    for index, cut in enumerate(usable):
        mask = valid[index]
        actual = float(matrix.filled[mask, cut : cut + days].sum())
        before = float(matrix.filled[mask, max(cut - days, 0) : cut].sum())
        if index >= 1 and len(oos) >= index:
            pred, basis = float(np.asarray(oos[index - 1][1])[mask].sum()), "luar sampel"
        elif prod_label in pairs:
            pred, basis = float(np.asarray(pairs[prod_label][index][1])[mask].sum()), "lipatan uji"
        else:
            pred, basis = float("nan"), "–"
        ma = pairs.get(MODEL_MA)
        ma_pred = float(np.asarray(ma[index][1])[mask].sum()) if ma else float("nan")
        out.append({
            "tanggal": str(matrix.dates[cut].date()), "aktual": round(actual, 1), "aktual_sebelumnya": round(before, 1),
            "perubahan_pct": _num((actual / before - 1) * 100) if before > 0 else None,
            "prediksi": round(pred, 1) if np.isfinite(pred) else None, "galat_pct": _num((pred / actual - 1) * 100) if actual > 0 and np.isfinite(pred) else None,
            "prediksi_ma28": round(ma_pred, 1) if np.isfinite(ma_pred) else None,
            "galat_ma28_pct": _num((ma_pred / actual - 1) * 100) if actual > 0 and np.isfinite(ma_pred) else None, "dasar": basis,
        })
    return out


def fit_combination(singles: dict[str, list[tuple[np.ndarray, np.ndarray]]], valid: list[np.ndarray], segments: np.ndarray,
                    folds: list[int]) -> tuple[dict, float, dict]:
    """(bobot 1/WAPE, faktor koreksi bias, model per segmen) dari lipatan `folds` saja — aturan yang sama dengan record."""
    def stack(name: str) -> tuple[np.ndarray, np.ndarray]:
        return (np.concatenate([singles[name][i][0][valid[i]] for i in folds]),
                np.concatenate([singles[name][i][1][valid[i]] for i in folds]))

    first = next(iter(singles))
    scores = {}
    for name in singles:
        a, p = stack(name)
        scores[name] = wape(a, p)
    weights = ensemble_weights(scores)
    actual = np.concatenate([singles[first][i][0][valid[i]] for i in folds])
    raw = np.concatenate([blend({n: singles[n][i][1] for n in singles}, weights)[valid[i]] for i in folds])
    raw_bias = bias_pct(actual, raw)
    factor = 1.0 / (1.0 + raw_bias / 100.0) if np.isfinite(raw_bias) and raw_bias > -100 else 1.0
    factor = float(np.clip(factor, *BIAS_FACTOR_LIMITS))
    ens = raw * factor
    seg = np.concatenate([segments[valid[i]] for i in folds])
    choice = {}
    for segment in sorted(set(segments)):
        mask = seg == segment
        if not mask.any() or actual[mask].sum() <= 0:
            continue
        best_name, best_score = None, wape(actual[mask], ens[mask])
        for name in singles:
            a, p = stack(name)
            score = wape(a[mask], p[mask])
            if np.isfinite(score) and score < best_score:
                best_name, best_score = name, score
        if best_name is not None:
            choice[segment] = best_name
    return weights, factor, choice


def production_weights(weights: dict, label: str) -> dict:
    """Bobot yang dipakai prediksi produksi untuk model terpilih (WAPE luar sampel terkecil).

    Ensemble per segmen = semua bobot; Ensemble = tanpa pilihan segmen; model tunggal = bobot 1 tanpa koreksi bias
    (skor luar sampelnya juga tanpa koreksi)."""
    if label == MODEL_SEGMENT:
        return dict(weights)
    if label == MODEL_ENSEMBLE:
        return {k: v for k, v in weights.items() if k != SEGMENT_KEY}
    return {label: 1.0}


def _nested_scores(singles: dict[str, list[tuple[np.ndarray, np.ndarray]]], valid: list[np.ndarray], segments: np.ndarray, *,
                   fold_classes_list: list[np.ndarray], fold_dates: list[str]) -> tuple[dict, dict]:
    """Uji luar sampel (nested walk-forward): lipatan k dinilai dengan bobot, faktor bias, dan pilihan segmen yang dihitung
    hanya dari lipatan sebelum k. Lipatan pertama tidak dinilai. Model tunggal dinilai pada lipatan yang sama agar setara.
    Mengembalikan (ringkasan untuk record, prediksi per model untuk lipatan 2 dst.)."""
    count = len(valid)
    if count < 2 or not singles:
        return {}, {}
    combo: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {MODEL_ENSEMBLE: [], MODEL_SEGMENT: []}
    for k in range(1, count):
        weights, factor, choice = fit_combination(singles, valid, segments, list(range(k)))
        actual = next(iter(singles.values()))[k][0]
        ens = blend({n: singles[n][k][1] for n in singles}, weights) * factor
        picked = ens.copy()
        for segment, model in choice.items():
            picked = np.where(segments == segment, singles[model][k][1], picked)
        combo[MODEL_ENSEMBLE].append((actual, ens))
        combo[MODEL_SEGMENT].append((actual, picked))
    classes = np.concatenate(fold_classes_list[1:])
    models = {}
    preds = {**{n: v[1:] for n, v in singles.items()}, **combo}
    for name, items in preds.items():
        scored = [(a[valid[k + 1]], p[valid[k + 1]]) for k, (a, p) in enumerate(items)]
        actual = np.concatenate([a for a, _ in scored])
        pred = np.concatenate([p for _, p in scored])
        models[MODEL_KEYS.get(name, name)] = {"label": name, **_scores(actual, pred, classes, [(float(a.sum()), float(p.sum())) for a, p in scored])}
    ranked = sorted((info for info in models.values() if info["wape"] is not None), key=lambda info: info["wape"])
    return {
        "lipatan_dinilai": fold_dates[1:],
        "models": models,
        "best_model": MODEL_KEYS.get(ranked[0]["label"], ranked[0]["label"]) if ranked else None,
        "catatan": "Bobot ensemble, faktor koreksi bias, dan model per segmen untuk lipatan k dihitung hanya dari lipatan sebelum k "
                   "(tanpa melihat lipatan yang dinilai). Lipatan pertama hanya dipakai untuk menyetel. "
                   "Model dengan WAPE luar sampel terkecil dipakai prediksi produksi.",
    }, preds


def ss_method(params: dict | None = None) -> str:
    """Metode SS produksi dari parameter bisnis (safety_stock.metode): "normal" (bawaan) atau "empiris"."""
    if params is None:
        from src.core.config import default_params

        params = default_params()
    value = str(((params or {}).get("safety_stock") or {}).get("metode", "normal")).strip().lower()
    return value if value in SS_METHODS else "normal"


def production_ss_settings() -> tuple[float, float, float, float]:
    """(tingkat layanan %, Z, lead time, periode tinjau) yang dipakai SS produksi: tingkat layanan rekomendasi
    periode Bulan dan lead time lokal + review dari config/business_params.yaml (SS = Z × σ × √(L + R))."""
    from src.core.config import default_params
    from src.core.inventory import service_level_to_z
    from src.core.service_level import recommended_service_level

    params = default_params()
    lead = params.get("lead_time", {})
    pct = float(recommended_service_level("bulan", params).pct)
    return pct, service_level_to_z(pct), float(lead.get("lokal_hari", SERVICE_LEAD_DAYS) or 0), float(lead.get("review_hari", 0) or 0)


def ss_calibration(z_scores: np.ndarray) -> float:
    """Faktor r agar σ galat L + R hari = r × σ harian × √(L + R), ditaksir robust: median |galat terstandar| ÷ 0,6745 (MAD).
    Dipakai sebagai pembanding (asumsi galat normal); SS produksi memakai kuantil empiris per kelas (conformal_quantiles)."""
    z_scores = np.asarray(z_scores, dtype=float)
    z_scores = z_scores[np.isfinite(z_scores)]
    if z_scores.size < 30:
        return 1.0
    return float(np.clip(np.median(np.abs(z_scores)) / MAD_TO_SIGMA, *SS_CALIBRATION_LIMITS))


MIN_CONFORMAL = 30          # galat terstandar minimal per kelas; kurang dari ini memakai gabungan semua kelas
CONFORMAL_LIMITS = (0.0, 25.0)


def conformal_quantiles(z_scores: np.ndarray, classes: np.ndarray, levels: dict[str, float]) -> dict[str, float]:
    """Pengali SS per kelas ABC dari kuantil empiris galat terstandar (split conformal prediction):
    q_kelas = kuantil ke-target layanan dari (aktual − prediksi) ÷ (σ harian × √(L + R)) lipatan sebelumnya, dengan koreksi
    sampel hingga ⌈(n + 1)·p⌉ / n. SS = q_kelas × σ harian × √(L + R). Tidak mengasumsikan galat normal, sehingga ekor tebal
    (pesanan proyek) ikut tertutup sesuai target kelasnya."""
    z_scores, classes = np.asarray(z_scores, dtype=float), np.asarray(classes, dtype=object)
    ok = np.isfinite(z_scores)
    z_scores, classes = z_scores[ok], classes[ok]
    out = {}
    for name, level in levels.items():
        part = z_scores[classes == name]
        if part.size < MIN_CONFORMAL:
            part = z_scores
        if part.size < MIN_CONFORMAL:
            from src.core.inventory import service_level_to_z

            out[name] = float(service_level_to_z(level))
            continue
        n = part.size
        p = min(np.ceil((n + 1) * level / 100.0) / n, 1.0)
        out[name] = float(np.clip(np.quantile(part, p, method="higher"), *CONFORMAL_LIMITS))
    return out


def _service_simulation(matrix: DemandMatrix, cutoffs: list[int], preds: dict[int, np.ndarray], days: int) -> dict:
    """Cycle service level: SS melindungi permintaan selama lead time + periode tinjau, jadi diuji pada L + R hari pertama tiap
    lipatan: stok = laju harian prediksi × (L + R) + SS dibanding permintaan aktual L + R hari itu.

    SS = q(kelas ABC) × σ harian SIGMA_DAYS hari × √(L + R). q = kuantil empiris galat terstandar (conformal) yang dihitung dari
    lipatan sebelum lipatan yang dinilai saja; pembanding: Z normal × r (MAD). Pengali akhir (semua lipatan) dipakai SS produksi.
    Target layanan per kelas ABC (A lebih tinggi, C lebih rendah) sama dengan produksi."""
    from src.core.config import default_params
    from src.core.inventory import service_level_to_z
    from src.core.service_level import class_service_levels

    pct, _z, lead_days, review_days = production_ss_settings()
    levels = class_service_levels(pct, default_params())
    z_of = {name: service_level_to_z(level) for name, level in levels.items()}
    span = int(min(max(round(lead_days + review_days), 1), days))
    root = np.sqrt(lead_days + review_days)
    folds = []
    censored_caught, censored_total = 0, 0
    for index in sorted(preds):
        if index >= len(cutoffs):
            continue
        cut = cutoffs[index]
        sigma = np.nan_to_num(np.nanstd(matrix.values[:, max(cut - SIGMA_DAYS, 0) : cut], axis=1))
        window = matrix.values[:, cut : cut + span]
        actual = np.nan_to_num(window, nan=0.0).sum(axis=1)
        pred = np.asarray(preds[index], dtype=float) * span / days
        had_stockout = np.isnan(window).any(axis=1)
        classes = abc_classes(matrix, cut)
        # Pasangan dengan hari stok kosong tidak dinilai: permintaan aslinya tidak terlihat, jadi "terlayani" tidak bisa dibuktikan.
        active = ((actual > 0) | (pred > 0)) & ~had_stockout
        scale = sigma * root
        zs = np.where(active & (scale > 0), (actual - pred) / np.where(scale > 0, scale, 1.0), np.nan)
        z_sku = np.array([z_of.get(c, z_of["B"]) for c in classes], dtype=float)
        folds.append({"a": actual[active], "p": pred[active], "s": scale[active], "z": zs[active], "zn": z_sku[active], "c": classes[active]})
        censored_total += int(had_stockout.sum())
        censored_caught += int((had_stockout & (pred > 0)).sum())

    def run(items, mults) -> tuple[np.ndarray, float, float]:
        """(terlayani per SKU-lipatan, Σ stok, Σ permintaan) untuk pengali SS per SKU tiap lipatan."""
        if not items:
            return np.array([], dtype=bool), 0.0, 0.0
        stock = [f["p"] + np.ceil(m * f["s"] - 1e-9) for f, m in zip(items, mults)]
        ok = np.concatenate([st >= f["a"] for st, f in zip(stock, items)])
        return ok, float(sum(st.sum() for st in stock)), float(sum(f["a"].sum() for f in items))

    def normal_mult(f, r):
        return f["zn"] * r

    def conformal_mult(f, q):
        return np.array([max(q.get(c, q.get("B", 0.0)), 0.0) for c in f["c"]], dtype=float)

    scored = folds[1:] if len(folds) > 1 else folds
    raw, _, _ = run(folds, [normal_mult(f, 1.0) for f in folds])
    mad = [ss_calibration(np.concatenate([f["z"] for f in folds[:k]])) for k in range(1, len(folds))] if len(folds) > 1 else [1.0] * len(folds)
    old, old_stock, demand = run(scored, [normal_mult(f, r) for f, r in zip(scored, mad)])
    conf_q = [conformal_quantiles(np.concatenate([f["z"] for f in folds[:k]]), np.concatenate([f["c"] for f in folds[:k]]), levels)
              for k in range(1, len(folds))] if len(folds) > 1 else [dict(z_of)] * len(folds)
    cal, cal_stock, _ = run(scored, [conformal_mult(f, q) for f, q in zip(scored, conf_q)])
    cal_classes = np.concatenate([f["c"] for f in scored]) if scored else np.array([], dtype=object)
    every_z = np.concatenate([f["z"] for f in folds]) if folds else np.array([])
    every_c = np.concatenate([f["c"] for f in folds]) if folds else np.array([], dtype=object)
    factor = ss_calibration(every_z) if folds else 1.0
    final_q = conformal_quantiles(every_z, every_c, levels) if folds else dict(z_of)
    method = ss_method()
    norm_classes = cal_classes
    chosen, chosen_stock = (cal, cal_stock) if method == "empiris" else (old, old_stock)
    per_class = {name: {"target_pct": levels[name], "tercapai_pct": _num(chosen[cal_classes == name].mean() * 100) if (cal_classes == name).any() else None,
                        "tercapai_empiris_pct": _num(cal[cal_classes == name].mean() * 100) if (cal_classes == name).any() else None,
                        "tercapai_normal_pct": _num(old[norm_classes == name].mean() * 100) if (norm_classes == name).any() else None,
                        "sku_lipatan": int((cal_classes == name).sum()), "pengali_ss": round(final_q.get(name, 0.0), 3),
                        "z_normal": round(z_of[name], 3)} for name in ("A", "B", "C")}
    goal = float(np.mean([levels.get(c, pct) for c in cal_classes])) if cal_classes.size else pct
    return {
        "metode_ss": method,
        "metode_ss_label": SS_METHODS[method],
        "tingkat_layanan_pct": _num(chosen.mean() * 100) if chosen.size else None,
        "tingkat_layanan_tanpa_kalibrasi_pct": _num(raw.mean() * 100) if raw.size else None,
        "tingkat_layanan_normal_mad_pct": _num(old.mean() * 100) if old.size else None,
        "tingkat_layanan_empiris_pct": _num(cal.mean() * 100) if cal.size else None,
        "stok_per_permintaan": round(chosen_stock / demand, 3) if demand else None,
        "stok_per_permintaan_normal_mad": round(old_stock / demand, 3) if demand else None,
        "stok_per_permintaan_empiris": round(cal_stock / demand, 3) if demand else None,
        "faktor_kalibrasi_ss": round(factor, 4),
        "pengali_ss_kelas": {k: round(v, 4) for k, v in final_q.items()},
        "per_kelas": per_class,
        "sku_lipatan": int(cal.size),
        "stok_kosong_tertangkap_pct": _num(censored_caught / censored_total * 100) if censored_total else None,
        "sku_stok_kosong": censored_total,
        "target_layanan_pct": round(goal, 2),
        "rumus_ss": ((f"q kelas (A {final_q.get('A', 0):.2f}, B {final_q.get('B', 0):.2f}, C {final_q.get('C', 0):.2f}; kuantil empiris galat untuk target "
                      f"A {levels['A']:.0f}%, B {levels['B']:.0f}%, C {levels['C']:.0f}%)") if method == "empiris" else
                     f"Z(kelas A {levels['A']:.0f}%, B {levels['B']:.0f}%, C {levels['C']:.0f}%) × r {factor:.2f}"
                     ).replace(".", ",") + f" × σ {SIGMA_DAYS} hari × √({lead_days:g} + {review_days:g})".replace(".", ","),
        "jendela_hari": span,
        "sigma_hari": SIGMA_DAYS,
    }


def fmt_num_id(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "–"
    text = f"{abs(value):,.{digits}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return ("-" if value < 0 else "") + text


def conclusion_text(record: dict) -> str:
    """Kalimat kesimpulan dari record (template Revisi Final 2A)."""
    best_key = record.get("best_model")
    if not best_key:
        return " ".join(record.get("notes") or ["Hasil uji belum tersedia."])
    best = record["models"][best_key]
    label = HORIZON_LABELS[record["horizon"]].lower()
    value = best.get("mape_agregat")
    parts = [f"Model terbaik horizon {label} (WAPE terkecil): {best['label']}, WAPE {fmt_num_id(best.get('wape'))}%."]
    if value is not None:
        gap = value - MAPE_TARGET_PCT
        side = "di atas" if gap > 0 else "di bawah"
        parts[0] += (f" MAPE agregat toko {fmt_num_id(value)}% — {fmt_num_id(abs(gap))} poin {side} target {MAPE_TARGET_PCT:.0f}%"
                     f" (MAPE per SKU {fmt_num_id(best.get('mape'))}%).")
    oos = record.get("luar_sampel") or {}
    prod_key = record.get("model_produksi") or best_key
    prod = (oos.get("models") or {}).get(prod_key)
    if prod and prod.get("wape") is not None:
        parts.append(f"Model produksi = WAPE luar sampel terkecil ({len(oos.get('lipatan_dinilai') or [])} lipatan, setelan dari lipatan sebelumnya saja): "
                     f"{prod['label']}, WAPE {fmt_num_id(prod['wape'])}%, MAPE agregat {fmt_num_id(prod.get('mape_agregat'))}%, "
                     f"bias {fmt_num_id(prod.get('bias'))}%.")
    ens = record["models"].get("ensemble")
    if ens and prod_key == "ensemble_segmen":
        parts.append(
            f"Ensemble murni (WAPE {fmt_num_id(ens['wape'])}%, bias setelah koreksi {fmt_num_id(ens['bias'])}%, "
            f"sebelum koreksi {fmt_num_id(record.get('bias_sebelum_koreksi'))}%) kalah di {len(record.get('model_per_segmen') or {})} segmen ABC-XYZ, "
            "sehingga prediksi memakai model terbaik per segmen."
        )
    elif ens and best_key != "ensemble":
        parts.append(
            f"Ensemble kalah dari {best['label']} karena WAPE {fmt_num_id(ens['wape'])}% vs {fmt_num_id(best['wape'])}% "
            f"(bias setelah koreksi {fmt_num_id(ens['bias'])}%, sebelum koreksi {fmt_num_id(record.get('bias_sebelum_koreksi'))}%)."
        )
    classes = best.get("mape_per_kelas_ABC") or {}
    parts.append(f"Galat (MAPE) kelas A {fmt_num_id(classes.get('A'))}%, kelas C {fmt_num_id(classes.get('C'))}% (makin kecil makin akurat).")
    return " ".join(parts)


def evaluate_all(matrix: DemandMatrix, *, folds: int = FOLDS, progress=None) -> dict[str, dict]:
    """Record untuk keempat horizon. Model dilatih sekali per titik potong untuk semua horizon."""
    cutoffs = month_cutoffs(matrix.dates, folds)
    total_days = matrix.values.shape[1] if matrix.values.size else 0
    fold_forecasts: dict[int, dict[int, dict[str, np.ndarray]]] = {}
    for index, cut in enumerate(cutoffs):
        if progress:
            progress(index / max(len(cutoffs), 1), f"Walk-forward lipatan {index + 1}/{len(cutoffs)} (s.d. {matrix.dates[cut - 1].date()})")
        wanted = [d for d in HORIZONS.values() if cut + d <= total_days]
        if not wanted:
            continue
        fold_forecasts[cut], _availability = model_forecasts_multi(matrix.cut(cut), wanted)
    return {name: evaluate_horizon(matrix, name, fold_forecasts=fold_forecasts, cutoffs=cutoffs) for name in HORIZONS}


def record_frame(record: dict) -> pd.DataFrame:
    """Tabel satu horizon untuk ditampilkan, persis dari record."""
    rows = []
    for key, info in (record.get("models") or {}).items():
        classes = info.get("mape_per_kelas_ABC") or {}
        rows.append(
            {
                "Model": info["label"],
                # Urutan: metrik utama untuk keputusan stok (WAPE, MAPE agregat) lebih dulu, MAPE per SKU sebagai pelengkap.
                "WAPE (%)": info["wape"],
                "MAPE agregat (%)": info["mape_agregat"],
                "MAPE (%)": info["mape"],
                "Bias (%)": info["bias"],
                "RMSE": info["rmse"],
                "MAPE kelas A (%)": classes.get("A"),
                "MAPE kelas C (%)": classes.get("C"),
                "Top 50 tepat": info.get("top50_tepat"),
                "Bobot ensemble": info.get("bobot_ensemble") if info.get("bobot_ensemble") is not None else np.nan,
            }
        )
    frame = pd.DataFrame(rows)
    return frame.sort_values("WAPE (%)", na_position="last").reset_index(drop=True) if not frame.empty else frame


def walk_forward_results(records: dict[str, dict]) -> list[WalkForwardResult]:
    """Bentuk lama (WalkForwardResult) agar komponen lain tetap bisa membaca hasil uji."""
    out = []
    for record in records.values():
        frame = record_frame(record)
        metrics = frame.rename(columns={"MAPE (%)": "MAPE SKU (%)"}) if not frame.empty else frame
        out.append(
            WalkForwardResult(
                horizon=int(record["days"]),
                folds=len(record.get("fold_dates") or []),
                metrics=metrics,
                fold_detail=pd.DataFrame(),
                weights={k: v for k, v in (record.get("weights") or {}).items()},
                notes=list(record.get("notes") or []),
            )
        )
    return out


def segment_blend(matrix: DemandMatrix, forecasts: dict[str, np.ndarray], weights: dict) -> np.ndarray:
    """Ensemble terkoreksi bias; SKU di segmen ABC-XYZ tempat ensemble kalah memakai model terbaik segmen itu."""
    out = blend(forecasts, weights)
    choice = weights.get(SEGMENT_KEY) or {}
    if not choice or not len(matrix.keys):
        return out
    end = matrix.values.shape[1]
    segments = abc_classes(matrix, end) + xyz_classes(matrix, end)
    for segment, model in choice.items():
        if model in forecasts:
            mask = segments == segment
            out = np.where(mask, forecasts[model], out)
    return out


def save_eval_files(records: dict[str, dict], folder: Path) -> list[Path]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, record in records.items():
        path = folder / f"eval_{name}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        paths.append(path)
    return paths
