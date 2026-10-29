"""Perbandingan model pada salinan uji.

Regresi mengukur permintaan harian. Klasifikasi mengukur risiko pesanan batal.
Pemenang uji hanya penanda di dasbor. Prediksi stok produksi tetap Level terkini.
"""

from __future__ import annotations

import os
import time
import tracemalloc
import warnings
from dataclasses import dataclass

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor

from src.intelligence.preprocess import clean_frame, clean_series
from src.ingest import cancelled_status_mask

MAX_CLASS_ROWS = 4000
LAGS = 7


@dataclass
class _Timed:
    value: object
    latency_ms: float
    memory_kb: float
    error: str


def benchmark_daily_demand(history: pd.DataFrame, method: str = "iqr") -> tuple[pd.DataFrame, str]:
    """RMSE, MAE, dan R² pada hari ujian. Deret kosong menghasilkan tabel kosong."""
    series = _daily_series(history)
    if series.size < 16:
        return pd.DataFrame(), "Kalender harian di bawah 16 hari, jadi uji regresi belum dibentuk."
    cleaned, clipped = clean_series(series, method)
    hold = 7 if cleaned.size >= 28 else max(3, cleaned.size // 5)
    train = cleaned[:-hold]
    actual = cleaned[-hold:]
    if train.size < LAGS + 4 or float(np.sum(train)) <= 0:
        return pd.DataFrame(), "Data latih terlalu pendek atau tidak ada penjualan untuk diuji."
    rows = [
        _regression_row("Naive", lambda: np.repeat(float(train[-1]), hold), actual),
        _regression_row(
            "Moving Average",
            lambda: np.repeat(float(np.mean(train[-min(7, train.size) :])), hold),
            actual,
        ),
        _regression_row("Regresi linear", lambda: _linear_forecast(train, hold), actual),
        _regression_row("K-NN", lambda: _lag_forecast(KNeighborsRegressor(n_neighbors=3), train, hold), actual),
        _regression_row(
            "Decision Tree",
            lambda: _lag_forecast(DecisionTreeRegressor(max_depth=3, random_state=42), train, hold),
            actual,
        ),
        _regression_row(
            "Random Forest",
            lambda: _lag_forecast(
                RandomForestRegressor(n_estimators=30, max_depth=4, random_state=42, n_jobs=1),
                train,
                hold,
            ),
            actual,
        ),
        _regression_row(
            "Gradient Boosting",
            lambda: _lag_forecast(
                HistGradientBoostingRegressor(max_iter=40, max_depth=3, random_state=42),
                train,
                hold,
            ),
            actual,
        ),
    ]
    table = _mark_winner(pd.DataFrame(rows), "RMSE", higher_better=False)
    note = (
        f"Uji regresi memakai {hold} hari terakhir sebagai ujian, setelah {clipped} lonjakan harian dipotong. "
        "Pemenang dipilih dari RMSE terendah. Angka ini tidak mengganti Level terkini pada prediksi stok."
    )
    winner = table.loc[table["Peran"].eq("Pemenang uji"), "R²"]
    if not winner.empty and pd.notna(winner.iloc[0]) and float(winner.iloc[0]) < 0:
        note += " R² pemenang negatif: pada jendela ujian ini, model masih kalah dari rata-rata penjualan harian."
    return table, note


def benchmark_cancel_risk(orders: pd.DataFrame, method: str = "iqr") -> tuple[pd.DataFrame, str]:
    """Accuracy, precision, recall, F1, dan ROC-AUC untuk kelas batal."""
    prepared, note = _cancel_matrix(orders, method)
    if prepared is None:
        return pd.DataFrame(), note
    features, target, sample_note = prepared
    x_train, x_test, y_train, y_test = train_test_split(
        features,
        target,
        test_size=0.3,
        random_state=42,
        stratify=target,
    )
    scaler = StandardScaler()
    x_train = scaler.fit_transform(x_train)
    x_test = scaler.transform(x_test)
    neighbors = max(1, min(5, len(x_train) - 1))
    specs = [
        ("Regresi logistik", LogisticRegression(max_iter=200, class_weight="balanced")),
        ("Naive Bayes", GaussianNB()),
        ("Decision Tree", DecisionTreeClassifier(max_depth=4, class_weight="balanced", random_state=42)),
        (
            "Random Forest",
            RandomForestClassifier(
                n_estimators=30,
                max_depth=4,
                class_weight="balanced",
                random_state=42,
                n_jobs=1,
            ),
        ),
        ("K-NN", KNeighborsClassifier(n_neighbors=neighbors)),
        (
            "Gradient Boosting",
            HistGradientBoostingClassifier(max_iter=40, max_depth=3, random_state=42),
        ),
    ]
    rows = [_classification_row(name, model, x_train, y_train, x_test, y_test) for name, model in specs]
    table = _mark_winner(pd.DataFrame(rows), "F1", higher_better=True)
    note = (
        f"{sample_note} Precision, recall, dan F1 dihitung pada kelas batal. "
        "Pemenang dipilih dari F1 tertinggi. Fitur diukur ulang pada data latih supaya nominal rupiah tidak menggagalkan regresi logistik. "
        "Skor ini tidak mengubah stok atau iklan secara otomatis."
    )
    winner = table.loc[table["Peran"].eq("Pemenang uji"), "F1"]
    if not winner.empty and pd.notna(winner.iloc[0]) and float(winner.iloc[0]) < 0.5:
        note += " F1 pemenang masih di bawah 0,5, jadi qty, sales, jam, dan hari belum cukup untuk menandai pesanan yang akan batal."
    return table, note


def _daily_series(history: pd.DataFrame) -> np.ndarray:
    if not isinstance(history, pd.DataFrame) or history.empty:
        return np.asarray([], dtype=float)
    if "period_start" not in history.columns or "qty" not in history.columns:
        return np.asarray([], dtype=float)
    dates = pd.to_datetime(history["period_start"], errors="coerce").dt.normalize()
    daily = history.assign(_day=dates).dropna(subset=["_day"]).groupby("_day")["qty"].sum().sort_index()
    if daily.empty:
        return np.asarray([], dtype=float)
    calendar = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    return daily.reindex(calendar, fill_value=0.0).to_numpy(dtype=float)


def _cancel_matrix(orders: pd.DataFrame, method: str):
    if not isinstance(orders, pd.DataFrame) or orders.empty or "status" not in orders.columns:
        return None, "Uji batal dilewati karena kolom status tidak ada."
    needed = [column for column in ("qty", "sales") if column in orders.columns]
    if len(needed) < 2:
        return None, "Uji batal dilewati karena qty atau sales tidak ada."
    cleaned, _report = clean_frame(orders, method, ("qty", "sales"))
    target = cancelled_status_mask(cleaned["status"]).astype(int)
    if target.nunique() < 2 or int(target.sum()) < 8 or int((target == 0).sum()) < 8:
        return None, "Uji batal dilewati karena salah satu kelas kurang dari 8 pesanan."
    features = cleaned.loc[:, ["qty", "sales"]].astype(float)
    if "order_time" in cleaned.columns:
        clock = pd.to_datetime(cleaned["order_time"], errors="coerce")
        features["jam"] = clock.dt.hour.fillna(0).astype(float)
        features["hari"] = clock.dt.dayofweek.fillna(0).astype(float)
    paired = features.copy()
    paired["_target"] = target.to_numpy()
    if len(paired) > MAX_CLASS_ROWS:
        parts = []
        for _label, group in paired.groupby("_target", sort=False):
            share = max(1, int(round(MAX_CLASS_ROWS * len(group) / len(paired))))
            parts.append(group.sample(min(len(group), share), random_state=42))
        paired = pd.concat(parts, ignore_index=True)
        if len(paired) > MAX_CLASS_ROWS:
            paired = paired.sample(MAX_CLASS_ROWS, random_state=42)
    sample_note = f"Uji batal memakai {len(paired)} pesanan."
    matrix = paired.drop(columns=["_target"]).to_numpy(dtype=float)
    labels = paired["_target"].to_numpy(dtype=int)
    if len(np.unique(labels)) < 2:
        return None, "Uji batal dilewati karena sampel hanya berisi satu kelas."
    return (matrix, labels, sample_note), ""


def _regression_row(name: str, builder, actual: np.ndarray) -> dict[str, object]:
    timed = _measure(builder)
    pred = timed.value
    row = _blank_regression(name, timed)
    if pred is None:
        return row
    pred = np.asarray(pred, dtype=float).reshape(-1)
    if pred.size != actual.size or not np.isfinite(pred).all():
        row["Status"] = "Gagal"
        return row
    pred = np.clip(pred, 0, None)
    row.update(_regression_scores(actual, pred))
    row["Status"] = "Selesai"
    return row


def _classification_row(name, model, x_train, y_train, x_test, y_test) -> dict[str, object]:
    def fit_and_score():
        model.fit(x_train, y_train)
        pred = model.predict(x_test)
        score = None
        if hasattr(model, "predict_proba"):
            score = model.predict_proba(x_test)[:, 1]
        return pred, score

    timed = _measure(fit_and_score)
    row = _blank_classification(name, timed)
    if timed.value is None:
        return row
    pred, score = timed.value
    pred = np.asarray(pred).reshape(-1)
    row["Accuracy"] = round(float(accuracy_score(y_test, pred)), 4)
    row["Precision"] = round(float(precision_score(y_test, pred, pos_label=1, zero_division=0)), 4)
    row["Recall"] = round(float(recall_score(y_test, pred, pos_label=1, zero_division=0)), 4)
    row["F1"] = round(float(f1_score(y_test, pred, pos_label=1, zero_division=0)), 4)
    if score is not None and len(np.unique(y_test)) > 1:
        try:
            row["ROC-AUC"] = round(float(roc_auc_score(y_test, score)), 4)
        except ValueError:
            row["ROC-AUC"] = np.nan
    row["Status"] = "Selesai"
    return row


def _regression_scores(actual: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    rmse = float(np.sqrt(mean_squared_error(actual, pred)))
    mae = float(mean_absolute_error(actual, pred))
    if float(np.var(actual)) <= 1e-12:
        r2 = float("nan")
    else:
        r2 = float(r2_score(actual, pred))
    return {"RMSE": round(rmse, 4), "MAE": round(mae, 4), "R²": round(r2, 4) if np.isfinite(r2) else np.nan}


def _linear_forecast(train: np.ndarray, horizon: int) -> np.ndarray:
    model = LinearRegression()
    model.fit(np.arange(train.size).reshape(-1, 1), train)
    future = np.arange(train.size, train.size + horizon).reshape(-1, 1)
    return model.predict(future)


def _lag_forecast(model, train: np.ndarray, horizon: int) -> np.ndarray:
    rows = np.lib.stride_tricks.sliding_window_view(train, LAGS)
    features = rows[:-1]
    target = train[LAGS:]
    if len(features) < 4:
        raise ValueError("lag pendek")
    model.fit(features, target)
    window = train[-LAGS:].astype(float).copy()
    forecast = np.empty(horizon, dtype=float)
    for step in range(horizon):
        nxt = float(model.predict(window.reshape(1, -1))[0])
        forecast[step] = max(nxt, 0.0)
        window = np.roll(window, -1)
        window[-1] = forecast[step]
    return forecast


def _measure(function) -> _Timed:
    tracemalloc.start()
    started = time.perf_counter()
    error = ""
    value = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            value = function()
    except Exception as exc:
        error = exc.__class__.__name__
        value = None
    latency_ms = (time.perf_counter() - started) * 1000
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return _Timed(value, round(latency_ms, 2), round(peak / 1024, 1), error)


def _mark_winner(table: pd.DataFrame, column: str, higher_better: bool) -> pd.DataFrame:
    work = table.copy()
    work["Peran"] = "Pembanding"
    done = work["Status"].eq("Selesai") & pd.to_numeric(work[column], errors="coerce").notna()
    if not done.any():
        return work
    ranked = work.loc[done].sort_values(
        [column, "Latensi (ms)"],
        ascending=[not higher_better, True],
        kind="mergesort",
    )
    work.loc[ranked.index[0], "Peran"] = "Pemenang uji"
    return work.reset_index(drop=True)


def _blank_regression(name: str, timed: _Timed) -> dict[str, object]:
    return {
        "Algoritma": name,
        "RMSE": np.nan,
        "MAE": np.nan,
        "R²": np.nan,
        "Latensi (ms)": timed.latency_ms,
        "Memori (KB)": timed.memory_kb,
        "Status": "Gagal" if timed.error else "Selesai",
        "Peran": "Pembanding",
    }


def _blank_classification(name: str, timed: _Timed) -> dict[str, object]:
    return {
        "Algoritma": name,
        "Accuracy": np.nan,
        "Precision": np.nan,
        "Recall": np.nan,
        "F1": np.nan,
        "ROC-AUC": np.nan,
        "Latensi (ms)": timed.latency_ms,
        "Memori (KB)": timed.memory_kb,
        "Status": "Gagal" if timed.error else "Selesai",
        "Peran": "Pembanding",
    }
