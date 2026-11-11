"""Riwayat analisa & detail uji model untuk tab Evaluasi model (bahan tesis).

Semua angka dibaca dari hasil analisa yang tersimpan (data/runs/<id>/state.pkl: eval_records walk-forward).
Detail per lipatan (aktual vs prediksi per SKU) dihitung ulang sekali dari base_history run dengan fungsi model
yang sama (`model_forecasts_multi`, `segment_blend`) lalu disimpan di folder run (eval_detail.pkl).
"""

from __future__ import annotations

import pickle
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.evaluation import MAPE_TARGET_PCT, bias_pct, mape, rmse, wape

STATE_FILE = "state.pkl"
DETAIL_FILE = "eval_detail.pkl"
DETAIL_VERSION = 2
HORIZON_ORDER = ("hari", "minggu", "bulan", "kuartal")
HORIZON_NAMES = {"hari": "Hari", "minggu": "Minggu", "bulan": "Bulan", "kuartal": "Kuartal"}
SEGMENT_LABEL = "Ensemble per segmen"
BASELINE_LABEL = "Moving Average 28"
LEVEL_LABEL = "Level terkini"
MODEL_COLORS = {
    SEGMENT_LABEL: "#ee4d2d", "Ensemble": "#f6a58f", LEVEL_LABEL: "#64748b", BASELINE_LABEL: "#0f766e",
    "Exponential Smoothing": "#1b3da6", "Gradient Boosting global": "#7c3aed", "XGBoost global": "#7c3aed",
    "LightGBM global": "#a855f7", "Prophet": "#0891b2", "Aktual": "#0f172a",
}


def color_of(label: str) -> str:
    return MODEL_COLORS.get(label, "#94a3b8")


def read_state(folder: Path) -> dict | None:
    """Isi state.pkl run (tanpa memuat tabel besar)."""
    try:
        with open(Path(folder) / STATE_FILE, "rb") as handle:
            return dict(pickle.load(handle))
    except Exception:
        return None


def run_time(stamp: str) -> datetime | None:
    """"20261108T194709" → datetime."""
    try:
        return datetime.strptime(str(stamp), "%Y%m%dT%H%M%S")
    except (TypeError, ValueError):
        return None


def _records(state: dict) -> dict:
    outcome = state.get("demand_outcome")
    return dict(getattr(outcome, "eval_records", None) or {})


def _model(record: dict, label: str) -> dict:
    for info in (record.get("models") or {}).values():
        if info.get("label") == label:
            return info
    return {}


def skill_score(model_wape: float | None, base_wape: float | None) -> float:
    """Skill terhadap pembanding = 1 − WAPE model ÷ WAPE pembanding (> 0 berarti lebih baik dari pembanding)."""
    if model_wape is None or base_wape is None or not np.isfinite(base_wape) or base_wape <= 0:
        return float("nan")
    return 1.0 - float(model_wape) / float(base_wape)


def history_frame(runs_root: Path, db_runs: dict[str, dict] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(ringkasan per run, metrik panjang run × horizon × model) dari semua folder run yang masih ada.

    db_runs: {path folder: {"id", "run_by", "periode", ...}} dari tabel analysis_runs; folder tanpa baris DB = arsip."""
    rows, long_rows = [], []
    db_runs = db_runs or {}
    root = Path(runs_root)
    folders = sorted((p for p in root.iterdir() if p.is_dir() and (p / STATE_FILE).exists()), key=lambda p: p.stat().st_mtime) if root.exists() else []
    for folder in folders:
        state = read_state(folder)
        if not state:
            continue
        records = _records(state)
        stamp = str(state.get("run_id") or "")
        when = run_time(stamp) or datetime.fromtimestamp((folder / STATE_FILE).stat().st_mtime)
        meta = db_runs.get(str(folder.resolve())) or {}
        outcome = state.get("demand_outcome")
        weights = dict(getattr(outcome, "weights", None) or {})
        month = records.get("bulan") or {}
        best = (month.get("models") or {}).get(month.get("best_model") or "", {})
        base = _model(month, BASELINE_LABEL)
        per_model = getattr(outcome, "per_model", None)
        pred_total = float(per_model["Ensemble"].sum()) if isinstance(per_model, pd.DataFrame) and "Ensemble" in per_model.columns else np.nan
        row = {
            "_folder": str(folder), "_stamp": stamp, "Waktu analisa": when, "Run": f"#{meta['id']}" if meta.get("id") else f"arsip {folder.name}",
            "Oleh": meta.get("run_by", ""), "Periode prediksi": state.get("period", ""), "Parameter": state.get("metric", ""),
            "Safety stock (%)": state.get("service"), "Hari riwayat": getattr(outcome, "history_days", None),
            "SKU dievaluasi": getattr(outcome, "evaluated_skus", None), "SKU tersensor": getattr(outcome, "censored_skus", None),
            "Lipatan (bulan)": len(month.get("fold_dates") or []), "Lipatan pertama": (month.get("fold_dates") or [""])[0],
            "Lipatan terakhir": (month.get("fold_dates") or [""])[-1], "Model terbaik": best.get("label", ""),
            "WAPE (%)": best.get("wape"), "MAPE agregat (%)": best.get("mape_agregat"), "MAPE (%)": best.get("mape"),
            "Bias (%)": best.get("bias"), "RMSE": best.get("rmse"), "Top 50 tepat": best.get("top50_tepat"),
            "WAPE MA28 (%)": base.get("wape"), "Skill vs MA28": skill_score(best.get("wape"), base.get("wape")),
            "Faktor koreksi bias": month.get("faktor_koreksi_bias"), "Tingkat layanan simulasi (%)": (month.get("simulasi_ss") or {}).get("tingkat_layanan_pct"),
            "Prediksi QTY ensemble": pred_total,
            "_weights": {k: v for k, v in weights.items() if not str(k).startswith("_")},
            "_segments": dict(weights.get("_model_per_segmen") or {}),
        }
        rows.append(row)
        for horizon in HORIZON_ORDER:
            record = records.get(horizon) or {}
            for key, info in (record.get("models") or {}).items():
                long_rows.append({
                    "_folder": str(folder), "Run": row["Run"], "Waktu analisa": when, "Horizon": HORIZON_NAMES[horizon], "Model": info.get("label", key),
                    "Terbaik": key == record.get("best_model"), "WAPE (%)": info.get("wape"), "MAPE agregat (%)": info.get("mape_agregat"),
                    "MAPE (%)": info.get("mape"), "Bias (%)": info.get("bias"), "RMSE": info.get("rmse"), "Top 50 tepat": info.get("top50_tepat"),
                    "Bobot ensemble": info.get("bobot_ensemble"), "MAPE A (%)": (info.get("mape_per_kelas_ABC") or {}).get("A"),
                    "MAPE B (%)": (info.get("mape_per_kelas_ABC") or {}).get("B"), "MAPE C (%)": (info.get("mape_per_kelas_ABC") or {}).get("C"),
                })
    summary = pd.DataFrame(rows)
    if not summary.empty:
        summary = summary.sort_values("Waktu analisa").reset_index(drop=True)
    return summary, pd.DataFrame(long_rows)


def method_checks(record: dict, history: pd.DataFrame | None = None) -> pd.DataFrame:
    """Apakah algoritma & metode sudah sesuai: tiap uji punya target, nilai, status, dan arti untuk tesis."""
    rows = []
    best = (record.get("models") or {}).get(record.get("best_model") or "", {})
    base = _model(record, BASELINE_LABEL)
    level = _model(record, LEVEL_LABEL)

    def add(name: str, target: str, value: str, ok: bool | None, meaning: str) -> None:
        rows.append({"Uji": name, "Target": target, "Hasil": value, "Status": "✅ Sesuai" if ok else ("⚠️ Belum" if ok is not None else "–"), "Arti": meaning})

    def pct(v) -> str:
        return "–" if v is None or not np.isfinite(v) else f"{v:.1f}%".replace(".", ",")

    skill = skill_score(best.get("wape"), base.get("wape"))
    add("Mengalahkan pembanding MA28", "skill > 0", pct(skill * 100) if np.isfinite(skill) else "–", bool(np.isfinite(skill) and skill > 0) if np.isfinite(skill) else None,
        "Model terpilih harus lebih akurat daripada rata-rata 28 hari; bila tidak, kerumitan model tidak terbayar.")
    skill_level = skill_score(best.get("wape"), level.get("wape"))
    add("Lebih baik dari metode lama (Level terkini)", "skill > 0", pct(skill_level * 100) if np.isfinite(skill_level) else "–",
        bool(np.isfinite(skill_level) and skill_level > 0) if np.isfinite(skill_level) else None, "Membuktikan kontribusi metode baru dibanding cara sebelumnya.")
    agg = best.get("mape_agregat")
    add("Akurasi total toko", f"MAPE agregat ≤ {MAPE_TARGET_PCT:.0f}%", pct(agg), agg is not None and agg <= MAPE_TARGET_PCT if agg is not None else None,
        "Dipakai untuk rencana stok & target bulanan (kesalahan total, ditimbang volume).")
    oos = record.get("luar_sampel") or {}
    oos_models = oos.get("models") or {}
    oos_best = oos_models.get(record.get("best_model") or "", {})
    # Bias ensemble setelah koreksi pada lipatan yang sama selalu ≈ 0 (faktornya disetel di situ); pakai bias luar sampel.
    bias = oos_best.get("bias") if oos_best.get("bias") is not None else best.get("bias")
    basis = "luar sampel" if oos_best.get("bias") is not None else "lipatan uji"
    add("Tidak bias sistematis", "|bias| ≤ 10%", pct(bias) + f" ({basis})" if bias is not None else "–", abs(bias) <= 10 if bias is not None else None,
        "Bias negatif = cenderung kurang prediksi (risiko stok kurang); positif = berlebih (stok menumpuk). "
        "Diukur di luar sampel: faktor koreksi bias disetel dari lipatan sebelumnya saja.")
    top = best.get("top50_tepat")
    add("Mengenali produk terlaris", "≥ 35 dari 50", "–" if top is None else f"{top:.1f}".replace(".", ","), top >= 35 if top is not None else None,
        "Top 50 prediksi yang benar masuk Top 50 aktual: penting untuk prioritas restock & iklan.")
    sim = record.get("simulasi_ss") or {}
    service = sim.get("tingkat_layanan_pct")
    goal = float(sim.get("target_layanan_pct") or 90)
    add("Tingkat layanan simulasi", f"≥ {goal:.0f}%".replace(".", ","), pct(service), service >= goal if service is not None else None,
        "Stok = prediksi + safety stock (rumus SS produksi" + (f": {sim['rumus_ss']}" if sim.get("rumus_ss") else "")
        + ") cukup memenuhi permintaan aktual pada lipatan uji; target = tingkat layanan yang dipakai SS.")
    folds = len(record.get("fold_dates") or [])
    add("Jumlah lipatan walk-forward", "≥ 3", str(folds), folds >= 3, "Lipatan lebih banyak = hasil uji lebih bisa dipercaya (tidak bergantung satu bulan).")
    if history is not None and len(history) >= 2 and history["WAPE (%)"].notna().sum() >= 2:
        values = history["WAPE (%)"].dropna().astype(float)
        spread = float(values.std())
        add("Stabil antar analisa", "simpangan WAPE ≤ 5 poin", f"{spread:.1f} poin".replace(".", ","), spread <= 5,
            f"WAPE model terbaik di {len(values)} analisa tersimpan; stabil = metode tidak sensitif terhadap tanggal analisa.")
        names = history["Model terbaik"].astype(str)
        share = float(names.eq(names.iloc[-1]).mean() * 100)
        add("Model terpilih konsisten", "≥ 60% analisa", pct(share), share >= 60, "Model yang sama terpilih di sebagian besar analisa.")
    if oos_best and oos_best.get("wape") is not None:
        oos_skill = skill_score(oos_best.get("wape"), (oos_models.get("ma28") or {}).get("wape"))
        add("Unggul di luar sampel", "skill vs MA28 > 0", pct(oos_skill * 100) if np.isfinite(oos_skill) else "–",
            bool(np.isfinite(oos_skill) and oos_skill > 0) if np.isfinite(oos_skill) else None,
            f"WAPE {pct(oos_best.get('wape'))} pada {len(oos.get('lipatan_dinilai') or [])} lipatan; bobot, faktor bias, dan model per segmen "
            "disetel dari lipatan sebelumnya saja, jadi angka ini bebas dari penyetelan pada data uji.")
    elif record.get("model_per_segmen"):
        add("Pemilihan per segmen di luar sampel", "uji terpisah", "in-sample", False,
            "Segmen dipilih dari lipatan yang sama dengan pengujian; skor ensemble per segmen cenderung optimistis (catat sebagai keterbatasan).")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- profil permintaan

ADI_CUT, CV2_CUT = 1.32, 0.49
PATTERNS = ("Halus (smooth)", "Tidak menentu (erratic)", "Jarang (intermittent)", "Jarang & tidak menentu (lumpy)")


def demand_profile(base_history: pd.DataFrame) -> pd.DataFrame:
    """Klasifikasi pola permintaan Syntetos–Boylan per SKU: ADI (rata-rata jarak antar hari laku) dan CV² ukuran permintaan."""
    cols = ["item_key", "Produk", "QTY total", "Hari laku", "ADI", "CV²", "Rata-rata/hari", "Pola"]
    if base_history is None or base_history.empty:
        return pd.DataFrame(columns=cols)
    work = base_history.loc[pd.to_numeric(base_history["qty"], errors="coerce") > 0, ["item_key", "item_label", "period_start", "qty"]].copy()
    if work.empty:
        return pd.DataFrame(columns=cols)
    dates = pd.to_datetime(base_history["period_start"])
    span = max((dates.max() - dates.min()).days + 1, 1)
    work["qty"] = work["qty"].astype(float)
    grouped = work.groupby("item_key")
    out = pd.DataFrame({
        "Produk": grouped["item_label"].first(), "QTY total": grouped["qty"].sum(), "Hari laku": grouped["qty"].size(),
        "mean": grouped["qty"].mean(), "std": grouped["qty"].std(ddof=0),
    }).reset_index()
    out["ADI"] = span / out["Hari laku"]
    out["CV²"] = (out["std"] / out["mean"]) ** 2
    out["Rata-rata/hari"] = out["QTY total"] / span
    smooth_adi, smooth_cv = out["ADI"] < ADI_CUT, out["CV²"] < CV2_CUT
    out["Pola"] = np.select([smooth_adi & smooth_cv, smooth_adi, smooth_cv], PATTERNS[:3], PATTERNS[3])
    return out[cols].sort_values("QTY total", ascending=False).reset_index(drop=True)


def pareto(profile: pd.DataFrame) -> pd.DataFrame:
    """Kurva Pareto: % SKU (urut QTY terbesar) vs % kumulatif QTY."""
    if profile is None or profile.empty:
        return pd.DataFrame(columns=["% SKU", "% QTY kumulatif"])
    qty = profile["QTY total"].sort_values(ascending=False).to_numpy(float)
    return pd.DataFrame({"% SKU": np.arange(1, len(qty) + 1) / len(qty) * 100, "% QTY kumulatif": np.cumsum(qty) / qty.sum() * 100})


# ---------------------------------------------------------------- detail per lipatan

def compute_detail(base_history: pd.DataFrame, weights: dict, *, horizons=(7, 30), eval_limit: int = 800, zero_since: dict | None = None) -> dict:
    """Prediksi tiap model per lipatan walk-forward (replikasi pengujian analisa) untuk grafik aktual vs prediksi."""
    from src.core.ensemble import build_demand_matrix, model_forecasts_multi
    from src.core.pipeline import _evaluation_subset
    from src.models.evaluate import abc_classes, month_cutoffs, segment_blend, xyz_classes

    matrix = _evaluation_subset(build_demand_matrix(base_history, zero_since=zero_since), eval_limit)
    total = matrix.values.shape[1] if matrix.values.size else 0
    cutoffs = month_cutoffs(matrix.dates)
    out = {"version": DETAIL_VERSION, "keys": list(matrix.keys), "folds": [], "daily_total": None}
    if not cutoffs:
        return out
    classes = abc_classes(matrix, cutoffs[0])
    out["abc"] = list(classes)
    out["segment"] = list(classes + xyz_classes(matrix, cutoffs[0]))
    out["daily_total"] = pd.Series(matrix.filled.sum(axis=0), index=matrix.dates)
    for cut in cutoffs:
        wanted = [d for d in horizons if cut + d <= total]
        if not wanted:
            continue
        forecasts, _availability = model_forecasts_multi(matrix.cut(cut), wanted)
        for days in wanted:
            preds = {name: np.asarray(values, dtype=float) for name, values in forecasts[days].items()}
            preds[SEGMENT_LABEL] = np.asarray(segment_blend(matrix.cut(cut), dict(preds), weights), dtype=float)
            valid = ~np.isnan(matrix.values[:, cut:cut + days]).any(axis=1)
            out["folds"].append({"cut": str(matrix.dates[cut].date()), "days": days, "actual": matrix.filled[:, cut:cut + days].sum(axis=1),
                                 "pred": preds, "valid": valid})
    return out


def load_detail(folder: Path) -> dict | None:
    try:
        with open(Path(folder) / DETAIL_FILE, "rb") as handle:
            detail = pickle.load(handle)
        return detail if detail.get("version") == DETAIL_VERSION else None
    except Exception:
        return None


def save_detail(folder: Path, detail: dict) -> None:
    try:
        with open(Path(folder) / DETAIL_FILE, "wb") as handle:
            pickle.dump(detail, handle, protocol=pickle.HIGHEST_PROTOCOL)
    except OSError:
        pass


def fold_totals(detail: dict, days: int) -> pd.DataFrame:
    """Total toko per lipatan: aktual & prediksi tiap model."""
    rows = []
    for fold in detail.get("folds", []):
        if fold["days"] != days:
            continue
        valid = fold.get("valid", np.ones(len(fold["actual"]), dtype=bool))
        row = {"Lipatan": fold["cut"], "Aktual": float(fold["actual"][valid].sum())}
        row.update({name: float(p[valid].sum()) for name, p in fold["pred"].items()})
        rows.append(row)
    return pd.DataFrame(rows)


def sku_pairs(detail: dict, days: int, model: str) -> pd.DataFrame:
    """Aktual vs prediksi per SKU × lipatan untuk satu model."""
    frames = []
    abc = detail.get("abc") or ["?"] * len(detail.get("keys", []))
    seg = detail.get("segment") or abc
    for fold in detail.get("folds", []):
        if fold["days"] != days or model not in fold["pred"]:
            continue
        part = pd.DataFrame({"Lipatan": fold["cut"], "SKU": detail["keys"], "Kelas ABC": abc, "Segmen": seg,
                             "Aktual": fold["actual"], "Prediksi": fold["pred"][model]})
        frames.append(part[fold.get("valid", np.ones(len(part), dtype=bool))])
    if not frames:
        return pd.DataFrame(columns=["Lipatan", "SKU", "Kelas ABC", "Segmen", "Aktual", "Prediksi", "Galat"])
    out = pd.concat(frames, ignore_index=True)
    out["Galat"] = out["Prediksi"] - out["Aktual"]
    return out


def model_scores(detail: dict, days: int) -> pd.DataFrame:
    """Metrik per model dari detail (untuk kurva & cek konsistensi dengan record)."""
    rows = []
    names = sorted({n for f in detail.get("folds", []) if f["days"] == days for n in f["pred"]})
    for name in names:
        pairs = sku_pairs(detail, days, name)
        if pairs.empty:
            continue
        a, p = pairs["Aktual"].to_numpy(float), pairs["Prediksi"].to_numpy(float)
        rows.append({"Model": name, "WAPE (%)": wape(a, p), "MAPE (%)": mape(a, p), "Bias (%)": bias_pct(a, p), "RMSE": rmse(a, p)})
    return pd.DataFrame(rows)


def error_curve(pairs: pd.DataFrame, points: int = 41) -> pd.DataFrame:
    """Kurva akurasi kumulatif: % SKU-lipatan (aktual > 0) dengan galat absolut relatif ≤ x%."""
    part = pairs.loc[pairs["Aktual"] > 0]
    if part.empty:
        return pd.DataFrame(columns=["Batas galat (%)", "% SKU"])
    rel = (part["Galat"].abs() / part["Aktual"] * 100).to_numpy()
    grid = np.linspace(0, 200, points)
    return pd.DataFrame({"Batas galat (%)": grid, "% SKU": [(rel <= g).mean() * 100 for g in grid]})


# ---------------------------------------------------------------- uji maju (prediksi tersimpan vs aktual sesudahnya)

def forward_test(snapshot: pd.DataFrame, actual_daily: pd.Series, runs: pd.DataFrame) -> pd.DataFrame:
    """snapshot: run_id, target_date, pred_qty (sudah dijumlah per tanggal); actual_daily: QTY aktual per tanggal.

    Hanya tanggal sesudah analisa dibuat dan sudah punya aktual (prediksi benar-benar ke depan)."""
    if snapshot is None or snapshot.empty or actual_daily is None or actual_daily.empty:
        return pd.DataFrame(columns=["run_id", "Tanggal", "Prediksi", "Aktual", "Galat (%)"])
    made = dict(zip(runs["id"].astype(int), pd.to_datetime(runs["run_at"]).dt.normalize())) if runs is not None and not runs.empty else {}
    work = snapshot.copy()
    work["Tanggal"] = pd.to_datetime(work["target_date"]).dt.normalize()
    work = work.groupby(["run_id", "Tanggal"], as_index=False)["pred_qty"].sum().rename(columns={"pred_qty": "Prediksi"})
    work = work.loc[work.apply(lambda r: r["Tanggal"] > made.get(int(r["run_id"]), pd.Timestamp.min), axis=1)]
    actual = actual_daily.copy()
    actual.index = pd.to_datetime(actual.index).normalize()
    work["Aktual"] = work["Tanggal"].map(actual)
    work = work.dropna(subset=["Aktual"])
    work["Galat (%)"] = np.where(work["Aktual"] > 0, (work["Prediksi"] - work["Aktual"]) / work["Aktual"] * 100, np.nan)
    return work.reset_index(drop=True)
