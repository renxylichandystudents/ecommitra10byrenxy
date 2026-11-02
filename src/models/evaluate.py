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
SERVICE_Z = 1.645
SERVICE_LEAD_DAYS = 7


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
    for cut in usable:
        actual = matrix.filled[:, cut : cut + days].sum(axis=1)
        for name in sorted(common):
            pairs.setdefault(name, []).append((actual, np.asarray(fold_forecasts[cut][days][name], dtype=float)))

    def stacked(name: str) -> tuple[np.ndarray, np.ndarray, list[tuple[float, float]]]:
        items = pairs[name]
        return (
            np.concatenate([a for a, _ in items]),
            np.concatenate([p for _, p in items]),
            [(float(a.sum()), float(p.sum())) for a, p in items],
        )

    fold_classes = np.concatenate([classes] * len(usable))
    fold_segments = np.concatenate([segments] * len(usable))
    for name in list(pairs):
        actual, pred, aggregate = stacked(name)
        record["models"][MODEL_KEYS.get(name, name)] = {"label": name, **_scores(actual, pred, fold_classes, aggregate)}

    singles = {name: record["models"][MODEL_KEYS.get(name, name)]["wape"] for name in pairs}
    weights = ensemble_weights({k: (v if v is not None else np.nan) for k, v in singles.items()})
    raw = [(a, blend({n: pairs[n][i][1] for n in pairs}, weights)) for i, (a, _p) in enumerate(pairs[MODEL_LEVEL])]
    raw_bias = bias_pct(np.concatenate([a for a, _ in raw]), np.concatenate([p for _, p in raw]))
    factor = 1.0 / (1.0 + raw_bias / 100.0) if np.isfinite(raw_bias) and raw_bias > -100 else 1.0
    factor = float(np.clip(factor, *BIAS_FACTOR_LIMITS))
    pairs[MODEL_ENSEMBLE] = [(a, p * factor) for a, p in raw]
    actual, pred, aggregate = stacked(MODEL_ENSEMBLE)
    record["models"]["ensemble"] = {"label": MODEL_ENSEMBLE, **_scores(actual, pred, fold_classes, aggregate)}
    for key, info in record["models"].items():
        info["bobot_ensemble"] = round(float(weights.get(info["label"], 0.0)), 4) if key != "ensemble" else None
        hits = [top_n_hits(a, p, top_n) for a, p in pairs[info["label"]]]
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
            "top50_tepat": round(float(np.mean([top_n_hits(a, p, top_n) for a, p in picked])), 1),
        }
        record["notes"].append(
            f"{MODEL_SEGMENT} = model yang dipakai prediksi produksi; pemilihan segmen memakai lipatan yang sama (in-sample)."
        )

    ranked = sorted(
        (info for info in record["models"].values() if info["wape"] is not None),
        key=lambda info: info["wape"],
    )
    record["best_model"] = MODEL_KEYS.get(ranked[0]["label"], ranked[0]["label"]) if ranked else None
    if days == HORIZONS["bulan"]:
        record["simulasi_ss"] = _service_simulation(matrix, usable, pairs.get(MODEL_SEGMENT, pairs[MODEL_ENSEMBLE]), days)
    record["kesimpulan"] = conclusion_text(record)
    return record


def _service_simulation(matrix: DemandMatrix, cutoffs: list[int], ensemble_pairs, days: int) -> dict:
    """Tingkat layanan simulasi: stok = prediksi ensemble + SS (Z 95%, lead time 7 hari)."""
    served, total, censored_caught, censored_total = 0, 0, 0, 0
    for cut, (actual, pred) in zip(cutoffs, ensemble_pairs):
        sigma = np.nanstd(matrix.values[:, max(cut - 28, 0) : cut], axis=1)
        ss = SERVICE_Z * np.nan_to_num(sigma) * np.sqrt(SERVICE_LEAD_DAYS)
        active = (actual > 0) | (pred > 0)
        served += int(((pred + ss) >= actual)[active].sum())
        total += int(active.sum())
        window = matrix.values[:, cut : cut + days]
        had_stockout = np.isnan(window).any(axis=1)
        censored_total += int(had_stockout.sum())
        censored_caught += int((had_stockout & (pred > 0)).sum())
    return {
        "tingkat_layanan_pct": _num(served / total * 100) if total else None,
        "sku_lipatan": total,
        "stok_kosong_tertangkap_pct": _num(censored_caught / censored_total * 100) if censored_total else None,
        "sku_stok_kosong": censored_total,
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
    value = best["mape"]
    gap = (value or 0.0) - MAPE_TARGET_PCT
    side = "di atas" if gap > 0 else "di bawah"
    parts = [
        f"Model terbaik horizon {label}: {best['label']}, MAPE {fmt_num_id(value)}% — "
        f"{fmt_num_id(abs(gap))} poin {side} target {MAPE_TARGET_PCT:.0f}%."
    ]
    parts[0] += f" MAPE agregat toko {fmt_num_id(best.get('mape_agregat'))}%, WAPE {fmt_num_id(best.get('wape'))}%."
    ens = record["models"].get("ensemble")
    if ens and best_key == "ensemble_segmen":
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
    parts.append(f"Akurasi kelas A: MAPE {fmt_num_id(classes.get('A'))}%; kelas C: MAPE {fmt_num_id(classes.get('C'))}%.")
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
                "MAPE (%)": info["mape"],
                "MAPE agregat (%)": info["mape_agregat"],
                "WAPE (%)": info["wape"],
                "Bias (%)": info["bias"],
                "RMSE": info["rmse"],
                "MAPE kelas A (%)": classes.get("A"),
                "MAPE kelas C (%)": classes.get("C"),
                "Top 50 tepat": info.get("top50_tepat"),
                "Bobot ensemble": info.get("bobot_ensemble"),
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
