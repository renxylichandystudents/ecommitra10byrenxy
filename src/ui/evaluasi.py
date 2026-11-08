"""Tab Evaluasi model (bahan tesis): ringkasan & uji kesesuaian metode, metodologi, profil data, hasil walk-forward,
kurva aktual vs prediksi, uji maju, riwayat seluruh analisa, fitur, dan lampiran unduhan.

Angka uji dibaca dari hasil analisa tersimpan (eval_records); kurva per lipatan dihitung ulang sekali per run dengan
fungsi model yang sama lalu disimpan di folder run.
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src.core import model_history as H
from src.core.decision_table import PERIOD_LABELS, build_decision_table
from src.core.ensemble import MODEL_LEVEL, build_demand_matrix, feature_importance
from src.core.evaluation import MAPE_TARGET_PCT
from src.core.expert_system import action_steps, evaluate_rules, sku_facts
from src.core.libstatus import library_status
from src.core.optimization import optimize_restock
from src.models.evaluate import HORIZON_LABELS, HORIZONS, MODEL_SEGMENT, PERIOD_TO_HORIZON, record_frame
from src.ui.common import ID_MONTHS_SHORT, card, download_excel, explain, fmt_num, fmt_pct
from src.utils.format import show_table

UP, DOWN = "#1d4ed8", "#dc2626"
METRIC_COLUMNS = ("MAPE (%)", "MAPE agregat (%)", "WAPE (%)", "Bias (%)", "RMSE", "MAPE kelas A (%)", "MAPE kelas C (%)")
METRICS = ("WAPE (%)", "MAPE agregat (%)", "MAPE (%)", "Bias (%)", "RMSE", "Top 50 tepat")
UPLOAD_MENUS = ("Transaksi", "Performa toko", "Iklan produk otomatis", "Iklan produk grup", "Keseluruhan iklan", "Iklan pencarian", "Stok",
                "Produk deskripsi", "Produk kompetitor")
TABS = ("Ringkasan & kesesuaian metode", "Metodologi", "Profil data", "Hasil uji walk-forward", "Kurva aktual vs prediksi",
        "Uji maju", "Riwayat analisa", "Fitur & segmen", "Lampiran")


def _records(outcome) -> dict:
    return dict(getattr(outcome, "eval_records", None) or {}) if outcome is not None else {}


def _short_day(value: str) -> str:
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{stamp.day} {ID_MONTHS_SHORT[stamp.month - 1]} {stamp.year}"


def _plot(fig: go.Figure, key: str, *, height: int = 420, legend_below: bool = True) -> None:
    fig.update_layout(height=height, separators=",.", margin=dict(l=40, r=20, t=40, b=40), template="plotly_white",
                      legend=dict(orientation="h", y=-0.2) if legend_below else None)
    st.plotly_chart(fig, use_container_width=True, key=key)


def _pick_horizon(records: dict, period: str, key: str) -> str | None:
    ready = [name for name in HORIZONS if records.get(name, {}).get("models")]
    if not ready:
        return None
    default = PERIOD_TO_HORIZON.get(period, "bulan")
    index = ready.index(default) if default in ready else len(ready) - 1
    return st.selectbox("Horizon uji", ready, index=index, format_func=lambda h: f"{HORIZON_LABELS[h]} ({HORIZONS[h]} hari)", key=key)


def _caption_figure(number: str, text: str) -> None:
    st.markdown(f"<div style='text-align:center;color:#475569;font-size:.85rem;margin:-.3rem 0 1rem'><b>Gambar {number}.</b> {text}</div>",
                unsafe_allow_html=True)


# ---------------------------------------------------------------- 1. Ringkasan & kesesuaian metode

def _framework(outcome, table: pd.DataFrame, params: dict, today: date, record: dict | None) -> pd.DataFrame:
    """Hasil kerangka pengujian (sub-bab 4.9): forecasting, optimisasi, sistem pakar, kecepatan."""
    rows = []
    best = (record or {}).get("models", {}).get((record or {}).get("best_model") or "", {})
    mape = best.get("mape") if best.get("mape") is not None else np.nan
    rows.append({"No": 1, "Komponen": "Demand forecasting", "Metode": f"Walk-forward {len((record or {}).get('fold_dates') or [])} lipatan · model terbaik {best.get('label') or '-'}",
                 "Target": f"MAPE ≤ {MAPE_TARGET_PCT:.0f}%", "Hasil": fmt_pct(mape) if np.isfinite(mape) else "belum tersedia",
                 "Status": ("Tercapai" if mape <= MAPE_TARGET_PCT else "Belum tercapai") if np.isfinite(mape) else "-"})
    if table is not None and not table.empty:
        top = table.head(50)
        items = pd.DataFrame({"item_key": top["item_key"], "kebutuhan": top["m_butuh"].astype(float), "current_stock": top["stok"].fillna(0).astype(float),
                              "rop": top["rop"].astype(float)})
        try:
            plan = optimize_restock(items, capacity=float(params.get("gudang", {}).get("kapasitas_unit", 100000)), moq=float(params.get("gudang", {}).get("moq_unit", 1)))
            status = str(plan["optimizer_status"].iloc[0]) if "optimizer_status" in plan.columns and not plan.empty else "-"
            ok = not plan.empty and "infeasible" not in status.lower()
        except Exception as exc:
            status, ok = f"gagal: {exc}", False
        rows.append({"No": 2, "Komponen": "Inventory optimization", "Metode": "MILP Big-M pada Top 50 (PuLP, warm start)", "Target": "0% infeasible", "Hasil": status,
                     "Status": "Tercapai" if ok else "Belum tercapai"})
        errors, violations = 0, 0
        for _, row in top.iterrows():
            try:
                facts = sku_facts(row, today=today)
                steps = action_steps(evaluate_rules(facts), facts)
                if facts.get("status_stok") in {"Kosong", "Kurang"} and any("naikkan" in s.lower() and "iklan" in s.lower() for s in steps):
                    violations += 1
            except Exception:
                errors += 1
        rows.append({"No": 3, "Komponen": "Sistem pakar, NLP & SEO", "Metode": "Black-box pada Top 50 + uji unit", "Target": "100% berjalan, saran valid",
                     "Hasil": f"{len(top) - errors}/{len(top)} berjalan, {violations} saran tidak valid", "Status": "Tercapai" if errors == 0 and violations == 0 else "Belum tercapai"})
        start = time.perf_counter()
        build_decision_table(table, period="bulan", today=today, horizon_days=30)
        elapsed = time.perf_counter() - start
        rows.append({"No": 4, "Komponen": "Kecepatan hitung", "Metode": f"Waktu bangun tabel keputusan {fmt_num(len(table))} SKU", "Target": "< 3 detik (dengan cache)",
                     "Hasil": f"{fmt_num(elapsed, 2)} detik", "Status": "Tercapai" if elapsed < 3 else "Belum tercapai"})
    return pd.DataFrame(rows)


def _summary(outcome, records: dict, history: pd.DataFrame, framework: pd.DataFrame) -> pd.DataFrame:
    record = records.get("bulan") or next((r for r in records.values() if r.get("models")), None)
    if not record:
        st.info("Hasil uji walk-forward belum tersedia. Jalankan analisa ulang agar evaluasi model terisi.")
        return pd.DataFrame()
    best = record["models"].get(record.get("best_model") or "", {})
    base = H._model(record, H.BASELINE_LABEL)
    skill = H.skill_score(best.get("wape"), base.get("wape"))
    label = HORIZON_LABELS[record["horizon"]].lower()
    k = st.columns(4)
    card(k[0], "Model terpilih", best.get("label", "–"), hint=f"horizon {label} · {len(record.get('fold_dates') or [])} lipatan walk-forward · {fmt_num(record.get('n_sku'))} SKU")
    agg = best.get("mape_agregat")
    card(k[1], "MAPE agregat toko", fmt_pct(agg, 1), hint=f"target ≤ {MAPE_TARGET_PCT:.0f}% · <b style='color:{UP if agg is not None and agg <= MAPE_TARGET_PCT else DOWN}'>"
                                                         f"{'tercapai' if agg is not None and agg <= MAPE_TARGET_PCT else 'belum'}</b>")
    card(k[2], "WAPE per SKU", fmt_pct(best.get("wape"), 1), hint=f"MA28 {fmt_pct(base.get('wape'), 1)} · skill <b style='color:{UP if skill > 0 else DOWN}'>{fmt_pct(skill * 100, 1, signed=True)}</b>")
    bias = best.get("bias")
    card(k[3], "Bias", fmt_pct(bias, 1, signed=True), hint=f"faktor koreksi {fmt_num(record.get('faktor_koreksi_bias', 1), 3)} · Top 50 tepat {fmt_num(best.get('top50_tepat'), 1)}/50")

    g1, g2 = st.columns([1, 1.4])
    with g1:
        fig = go.Figure(go.Indicator(
            mode="gauge+number+delta", value=float(agg or 0), number={"suffix": "%", "valueformat": ".1f"},
            delta={"reference": MAPE_TARGET_PCT, "increasing": {"color": DOWN}, "decreasing": {"color": UP}},
            title={"text": "MAPE agregat vs target"},
            gauge={"axis": {"range": [0, max(50, float(agg or 0) * 1.3)]}, "bar": {"color": "#ee4d2d"},
                   "steps": [{"range": [0, MAPE_TARGET_PCT], "color": "#dbeafe"}, {"range": [MAPE_TARGET_PCT, 30], "color": "#fef3c7"}],
                   "threshold": {"line": {"color": "#0f172a", "width": 3}, "value": MAPE_TARGET_PCT}}))
        _plot(fig, "eval-gauge", height=300, legend_below=False)
    with g2:
        checks = H.method_checks(record, history if history is not None and not history.empty else None)
        passed = int(checks["Status"].str.startswith("✅").sum())
        st.markdown(f"**Uji kesesuaian algoritma & metode** · {passed} dari {len(checks)} sesuai")
        show_table(checks, column_config={"Arti": st.column_config.TextColumn(width="large")})
    st.markdown("**Kesimpulan per horizon**")
    for name in HORIZONS:
        rec = records.get(name)
        if rec and rec.get("kesimpulan"):
            st.markdown(f"- **{HORIZON_LABELS[name]}** · {rec['kesimpulan']}")
    strengths, weaknesses = [], []
    for _, row in checks.iterrows():
        (strengths if str(row["Status"]).startswith("✅") else weaknesses).append(f"{row['Uji']}: {row['Hasil']} (target {row['Target']}).")
    improve = [
        "Unggah snapshot stok rutin (mingguan) agar hari kosong tercatat sebagai permintaan tersensor, bukan nol.",
        "Tambah riwayat ≥ 12 bulan untuk menangkap musim renovasi (Lebaran, akhir tahun) pada horizon kuartal.",
        "Pilih model per segmen dengan lipatan validasi terpisah (nested walk-forward) agar skor tidak optimistis.",
        "Pertimbangkan model khusus permintaan jarang (Croston/SBA) untuk SKU pola intermittent & lumpy (lihat Profil data).",
    ]
    cols = st.columns(3)
    for column, (title, items) in zip(cols, (("Kekuatan", strengths), ("Kelemahan / keterbatasan", weaknesses), ("Saran penelitian lanjut", improve))):
        with column.container(border=True):
            st.markdown(f"**{title}**")
            st.markdown("\n".join(f"- {i}" for i in items) if items else "–")
    st.markdown("**Hasil kerangka pengujian (sub-bab 4.9)**")
    show_table(framework)
    return checks


# ---------------------------------------------------------------- 2. Metodologi

PIPELINE_DOT = """
digraph G {
  rankdir=LR; node [shape=box, style="rounded,filled", fillcolor="#f8fafc", color="#cbd5e1", fontname="Helvetica", fontsize=11];
  edge [color="#94a3b8"];
  data [label="9 menu upload\\n(transaksi, iklan, stok,\\nperforma, kompetitor)", fillcolor="#e0e7ff"];
  prep [label="Prapemrosesan\\nkalender harian per SKU\\nhari stok 0 = tersensor\\npromo & harga bersih"];
  seg [label="Segmentasi\\nABC · XYZ\\npola ADI/CV²"];
  models [label="Model kandidat\\nLevel terkini · MA28 · ES\\nGradient Boosting · Prophet", fillcolor="#fef3c7"];
  wf [label="Walk-forward CV\\n≤ 6 lipatan bulanan\\n4 horizon", fillcolor="#fee2e2"];
  ens [label="Ensemble 1/WAPE\\n+ koreksi bias\\n+ model per segmen", fillcolor="#ffedd5"];
  ss [label="Safety stock & ROP\\nZ·σ·√L · Monte Carlo\\nMILP restock"];
  rules [label="Sistem pakar\\nJIKA–MAKA"];
  out [label="Keputusan harian\\nstok · iklan · flash sale\\nexposure · laporan", fillcolor="#dcfce7"];
  data -> prep -> seg -> models -> wf -> ens -> ss -> out; ens -> rules -> out; wf -> models [style=dashed, label="skor", fontsize=9];
}
"""


def _methodology(outcome, records: dict, period: str, is_super: bool) -> None:
    st.markdown("**Alur sistem**")
    st.graphviz_chart(PIPELINE_DOT, use_container_width=True)
    _caption_figure("1", "Alur data hingga keputusan; skor walk-forward menentukan bobot ensemble.")
    st.markdown("**Model kandidat**")
    show_table(pd.DataFrame([
        {"Model": "Level terkini", "Peran": "metode lama (pembanding)", "Rumus / ide": "laju harian 28 hari terakhir × hari horizon"},
        {"Model": "Moving Average 28", "Peran": "pembanding baku (baseline)", "Rumus / ide": "ŷ = (1/28) Σ y(t−i), i = 1..28"},
        {"Model": "Exponential Smoothing", "Peran": "statistik", "Rumus / ide": "ℓ(t) = α·y(t) + (1−α)·ℓ(t−1), α = 0,1"},
        {"Model": "Gradient Boosting global", "Peran": "machine learning", "Rumus / ide": "satu model untuk semua SKU; fitur lag, rolling, promo, stok (XGBoost/LightGBM bila tersedia)"},
        {"Model": "Prophet", "Peran": "deret waktu toko", "Rumus / ide": "tren + musiman mingguan + regresor promo pada total toko, dibagi ke SKU"},
        {"Model": "Ensemble", "Peran": "gabungan", "Rumus / ide": "bobot ∝ 1/WAPE (hanya model yang mengalahkan MA28) × faktor koreksi bias"},
        {"Model": MODEL_SEGMENT, "Peran": "dipakai produksi", "Rumus / ide": "per segmen ABC-XYZ dipakai model dengan WAPE terkecil"},
    ]), column_config={"Rumus / ide": st.column_config.TextColumn(width="large")})
    st.markdown("**Metrik evaluasi**")
    c1, c2 = st.columns(2)
    with c1:
        st.latex(r"\text{WAPE}=\frac{\sum_i |y_i-\hat y_i|}{\sum_i y_i}\times100\%")
        st.latex(r"\text{MAPE}=\frac{100\%}{n}\sum_{y_i>0}\left|\frac{y_i-\hat y_i}{y_i}\right|")
        st.latex(r"\text{Skill}=1-\frac{\text{WAPE}_{\text{model}}}{\text{WAPE}_{\text{MA28}}}")
    with c2:
        st.latex(r"\text{Bias}=\frac{\sum_i(\hat y_i-y_i)}{\sum_i y_i}\times100\%")
        st.latex(r"\text{RMSE}=\sqrt{\tfrac{1}{n}\sum_i (y_i-\hat y_i)^2}")
        st.latex(r"\text{MAPE agregat}=\frac{100\%}{K}\sum_{k}\left|\frac{\sum_i y_{ik}-\sum_i\hat y_{ik}}{\sum_i y_{ik}}\right|")
    st.caption("i = SKU × lipatan; k = lipatan (total toko). WAPE & MAPE agregat dipakai untuk keputusan stok karena ditimbang volume; "
               "MAPE per SKU membesar pada SKU jarang laku.")
    record = records.get("bulan") or next((r for r in records.values() if r.get("fold_dates")), None)
    if record and record.get("fold_dates"):
        st.markdown("**Skema walk-forward (expanding window)**")
        fig = go.Figure()
        first = pd.Timestamp(record["fold_dates"][0]) - pd.DateOffset(months=5)
        for index, cut in enumerate(record["fold_dates"], start=1):
            cut_ts = pd.Timestamp(cut)
            fig.add_bar(y=[f"Lipatan {index}"], x=[(cut_ts - first).days], base=[first], orientation="h", marker_color="#93c5fd",
                        name="Data latih", showlegend=index == 1, hovertemplate=f"Latih s.d. {_short_day(str((cut_ts - pd.Timedelta(days=1)).date()))}<extra></extra>")
            fig.add_bar(y=[f"Lipatan {index}"], x=[record["days"]], base=[cut_ts], orientation="h", marker_color="#ee4d2d",
                        name=f"Data uji ({record['days']} hari)", showlegend=index == 1, hovertemplate=f"Uji mulai {_short_day(cut)}<extra></extra>")
        fig.update_layout(barmode="overlay", xaxis_type="date", yaxis=dict(autorange="reversed"))
        _plot(fig, "eval-wf", height=80 + 45 * len(record["fold_dates"]))
        _caption_figure("2", f"Tiap lipatan melatih model dengan data sebelum titik potong lalu menguji {record['days']} hari sesudahnya (horizon bulan).")
    st.markdown("**Alur kerja & aturan data**")
    st.markdown(
        f"- **Target**: QTY terjual per SKU per hari, dijumlah ke horizon periode prediksi ({PERIOD_LABELS.get(period, period)}); sales = prediksi QTY × harga bersih 4 minggu.\n"
        "- **Data**: " + ", ".join(UPLOAD_MENUS).lower() + "; duplikat dibuang, snapshot stok per tanggal unggah.\n"
        "- **Hari stok kosong**: dikeluarkan dari latih & uji (permintaan tersensor), bukan dianggap permintaan nol.\n"
        "- **Safety stock**: SS = Z × σ permintaan × √lead time; ROP = permintaan harian × lead time + SS.\n"
        "- **Tidak ada kebocoran data pada fitur**: fitur hanya dari data sebelum titik potong.\n"
        "- **Keterbatasan**: bobot ensemble, faktor koreksi bias, dan pilihan model per segmen ditentukan dari lipatan yang sama dengan penilaiannya "
        "(in-sample), sehingga skor Ensemble dan Ensemble per segmen sedikit optimis dibanding model tunggal."
    )
    if outcome is not None:
        rows = [{"Algoritma": name, "Status": "Aktif", "Keterangan": note} for name, note in outcome.availability.active.items()]
        rows += [{"Algoritma": name, "Status": "Dilewati", "Keterangan": note} for name, note in outcome.availability.skipped.items()]
        st.markdown("**Ketersediaan algoritma pada analisa ini**")
        show_table(pd.DataFrame(rows), column_config={"Keterangan": st.column_config.TextColumn(width="large")})
        if outcome.censored_skus:
            st.caption(f"{fmt_num(outcome.censored_skus)} SKU punya hari stok kosong yang diperlakukan sebagai permintaan tersensor.")
    if is_super:
        with st.expander("Status library (hanya super user)"):
            show_table(pd.DataFrame(library_status()))


# ---------------------------------------------------------------- 3. Profil data

@st.cache_data(show_spinner=False, max_entries=4)
def _profile(base_history: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    profile = H.demand_profile(base_history)
    daily = base_history.assign(d=pd.to_datetime(base_history["period_start"])).groupby("d")["qty"].sum()
    daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max()), fill_value=0) if not daily.empty else daily
    from src.models.evaluate import abc_classes, xyz_classes

    matrix = build_demand_matrix(base_history)
    end = matrix.values.shape[1]
    seg = pd.DataFrame({"item_key": matrix.keys, "ABC": abc_classes(matrix, end), "XYZ": xyz_classes(matrix, end),
                        "QTY 90 hari": matrix.filled[:, max(end - 90, 0):end].sum(axis=1)})
    return profile, daily, seg


def _data_profile(base_history: pd.DataFrame | None, records: dict) -> dict:
    if base_history is None or base_history.empty:
        st.info("Riwayat harian analisa belum tersedia.")
        return {}
    with st.spinner("Menyusun profil data..."):
        profile, daily, seg = _profile(base_history)
    k = st.columns(4)
    card(k[0], "SKU dengan penjualan", fmt_num(len(profile)), hint=f"{fmt_num(len(daily))} hari riwayat")
    card(k[1], "QTY total", fmt_num(profile["QTY total"].sum()), hint=f"rata-rata {fmt_num(daily.mean(), 1)} unit/hari toko")
    zero = float((profile["ADI"] >= H.ADI_CUT).mean() * 100) if not profile.empty else 0
    card(k[2], "SKU permintaan jarang", fmt_pct(zero, 1), hint="ADI ≥ 1,32 (intermittent + lumpy)")
    top20 = H.pareto(profile)
    share = float(top20.loc[top20["% SKU"] <= 20, "% QTY kumulatif"].max()) if not top20.empty else 0
    card(k[3], "Porsi 20% SKU teratas", fmt_pct(share, 1), hint="dari total QTY (prinsip Pareto)")

    fig = go.Figure()
    fig.add_scatter(x=daily.index, y=daily.values, mode="lines", line=dict(color="#93c5fd", width=1), name="QTY harian toko")
    fig.add_scatter(x=daily.index, y=daily.rolling(7, min_periods=1).mean(), mode="lines", line=dict(color="#1b3da6", width=2.5), name="Rata-rata 7 hari")
    for cut in (records.get("bulan") or {}).get("fold_dates") or []:
        fig.add_vline(x=pd.Timestamp(cut), line_dash="dot", line_color="#ee4d2d")
    fig.update_layout(yaxis_title="Unit", title="Permintaan harian toko & titik potong walk-forward")
    _plot(fig, "eval-daily")
    _caption_figure("3", "Garis merah putus-putus = titik potong lipatan uji; lonjakan biasanya tanggal kembar / promo.")

    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        for name, color in zip(H.PATTERNS, ("#1d4ed8", "#0891b2", "#f59e0b", "#dc2626")):
            part = profile.loc[profile["Pola"] == name]
            fig.add_scatter(x=part["ADI"], y=part["CV²"], mode="markers", name=f"{name} ({len(part)})", marker=dict(color=color, size=6, opacity=.6),
                            text=part["Produk"], hovertemplate="%{text}<br>ADI %{x:.1f} · CV² %{y:.2f}<extra></extra>")
        fig.add_vline(x=H.ADI_CUT, line_dash="dash", line_color="#64748b")
        fig.add_hline(y=H.CV2_CUT, line_dash="dash", line_color="#64748b")
        fig.update_layout(xaxis_type="log", xaxis_title="ADI (hari antar penjualan, log)", yaxis_title="CV² ukuran permintaan", title="Pola permintaan Syntetos–Boylan")
        _plot(fig, "eval-sbc", height=440)
        _caption_figure("4", "Kuadran kiri bawah = halus; kanan = jarang. SKU bahan bangunan banyak di kanan: wajar MAPE per SKU tinggi.")
    with c2:
        counts = profile["Pola"].value_counts().reindex(H.PATTERNS, fill_value=0)
        volume = profile.groupby("Pola")["QTY total"].sum().reindex(H.PATTERNS, fill_value=0)
        fig = make_subplots(rows=1, cols=2, specs=[[{"type": "domain"}, {"type": "domain"}]], subplot_titles=("Jumlah SKU", "Porsi QTY"))
        colors = ["#1d4ed8", "#0891b2", "#f59e0b", "#dc2626"]
        fig.add_pie(labels=list(counts.index), values=counts.values, hole=.5, marker_colors=colors, row=1, col=1)
        fig.add_pie(labels=list(volume.index), values=volume.values, hole=.5, marker_colors=colors, row=1, col=2)
        fig.update_layout(title="Komposisi pola permintaan")
        _plot(fig, "eval-sbc-pie", height=440)
        _caption_figure("5", "Sedikit SKU halus menyumbang porsi QTY besar; itulah mengapa metrik ditimbang volume (WAPE) lebih relevan.")

    c3, c4 = st.columns(2)
    with c3:
        fig = go.Figure(go.Scatter(x=top20["% SKU"], y=top20["% QTY kumulatif"], mode="lines", fill="tozeroy", line=dict(color="#1b3da6")))
        fig.add_scatter(x=[0, 100], y=[0, 100], mode="lines", line=dict(dash="dot", color="#94a3b8"), name="Merata")
        fig.add_vline(x=20, line_dash="dash", line_color="#ee4d2d")
        fig.update_layout(xaxis_title="% SKU (urut QTY terbesar)", yaxis_title="% QTY kumulatif", title="Kurva Pareto", showlegend=False)
        _plot(fig, "eval-pareto", height=400)
        _caption_figure("6", f"20% SKU teratas menyumbang {fmt_pct(share, 1)} QTY.")
    with c4:
        grid = seg.pivot_table(index="ABC", columns="XYZ", values="item_key", aggfunc="count", fill_value=0).reindex(index=["A", "B", "C"], columns=["X", "Y", "Z"], fill_value=0)
        vol = seg.pivot_table(index="ABC", columns="XYZ", values="QTY 90 hari", aggfunc="sum", fill_value=0).reindex(index=["A", "B", "C"], columns=["X", "Y", "Z"], fill_value=0)
        share_vol = vol / max(vol.values.sum(), 1) * 100
        text = [[f"{int(grid.iloc[i, j])} SKU<br>{share_vol.iloc[i, j]:.1f}% QTY".replace(".", ",") for j in range(3)] for i in range(3)]
        fig = go.Figure(go.Heatmap(z=share_vol.values, x=["X (stabil)", "Y (sedang)", "Z (tidak menentu)"], y=["A (80% QTY)", "B", "C"], text=text,
                                   texttemplate="%{text}", colorscale="Blues", showscale=False))
        fig.update_layout(title="Matriks ABC-XYZ (90 hari terakhir)", yaxis=dict(autorange="reversed"))
        _plot(fig, "eval-abcxyz", height=400, legend_below=False)
        _caption_figure("7", "Segmen ini dipakai untuk memilih model per segmen.")
    fig = go.Figure(go.Histogram(x=np.log10(profile["Rata-rata/hari"].clip(lower=1e-3)), nbinsx=40, marker_color="#1b3da6"))
    fig.update_layout(xaxis_title="log10 rata-rata QTY per hari per SKU", yaxis_title="Jumlah SKU", title="Sebaran tingkat permintaan SKU", showlegend=False)
    _plot(fig, "eval-hist-demand", height=340)
    _caption_figure("8", "Sebagian besar SKU terjual < 1 unit per hari (log10 < 0).")
    return {"Profil permintaan SKU": profile, "Segmen ABC-XYZ": seg}


# ---------------------------------------------------------------- 4. Hasil uji walk-forward

def _results(records: dict, period: str) -> dict:
    horizon = _pick_horizon(records, period, "eval-res-horizon")
    if horizon is None:
        st.info("Hasil uji walk-forward belum tersedia. Jalankan analisa ulang.")
        return {}
    record = records[horizon]
    explain([
        ("Uji", f"walk-forward {len(record['fold_dates'])} lipatan, titik potong " + ", ".join(_short_day(d) for d in record["fold_dates"])),
        ("SKU diuji", fmt_num(record["n_sku"])), ("MAPE", "hanya titik aktual > 0"), ("WAPE", "Σ|aktual − prediksi| ÷ Σ aktual"), ("Bias", "Σ(prediksi − aktual) ÷ Σ aktual"),
    ])
    frame = record_frame(record)
    show_table(frame, kinds={c: "dec" for c in METRIC_COLUMNS})
    st.caption(f"Faktor koreksi bias ensemble {fmt_num(record.get('faktor_koreksi_bias', 1.0), 3)} (bias sebelum koreksi {fmt_pct(record.get('bias_sebelum_koreksi'))}).")
    for note in record.get("notes") or []:
        st.caption(note)
    c1, c2 = st.columns(2)
    with c1:
        metric = st.selectbox("Metrik grafik", ["WAPE (%)", "MAPE agregat (%)", "MAPE (%)", "Bias (%)", "RMSE"], key="eval-res-metric")
        part = frame.dropna(subset=[metric]).sort_values(metric)
        fig = go.Figure(go.Bar(x=part["Model"], y=part[metric], marker_color=[H.color_of(m) for m in part["Model"]], text=[fmt_num(v, 1) for v in part[metric]], textposition="outside"))
        if "MAPE" in metric:
            fig.add_hline(y=MAPE_TARGET_PCT, line_dash="dash", line_color="#a16207", annotation_text=f"Target {MAPE_TARGET_PCT:.0f}%")
        fig.update_layout(yaxis_title=metric, title=f"{metric} per model · horizon {HORIZON_LABELS[horizon].lower()}", showlegend=False)
        _plot(fig, "eval-res-bar")
        _caption_figure("9", "Oranye = model produksi (ensemble per segmen); hijau tua = MA28 pembanding; abu-abu = metode lama.")
    with c2:
        axes = ["WAPE (%)", "MAPE agregat (%)", "MAPE (%)", "RMSE"]
        sub = frame.set_index("Model")[axes].astype(float)
        norm = (sub.max() - sub) / (sub.max() - sub.min()).replace(0, 1)
        top50 = pd.Series({info["label"]: info.get("top50_tepat") for info in record["models"].values()}).astype(float)
        norm["Top 50"] = ((top50 - top50.min()) / max(top50.max() - top50.min(), 1e-9)).reindex(norm.index)
        fig = go.Figure()
        for model in norm.index:
            values = norm.loc[model].fillna(0).tolist()
            fig.add_scatterpolar(r=values + values[:1], theta=list(norm.columns) + [norm.columns[0]], name=model, line=dict(color=H.color_of(model)),
                                 fill="toself" if model == MODEL_SEGMENT else None, opacity=.85)
        fig.update_layout(polar=dict(radialaxis=dict(range=[0, 1], showticklabels=False)), title="Profil kinerja (1 = terbaik di metrik itu)")
        _plot(fig, "eval-radar", height=460)
        _caption_figure("10", "Makin luas area, makin seimbang kinerja model di semua metrik.")
    rows = []
    for name in HORIZONS:
        rec = records.get(name) or {}
        for info in (rec.get("models") or {}).values():
            rows.append({"Horizon": HORIZON_LABELS[name], "Model": info["label"], "WAPE (%)": info.get("wape"), "MAPE agregat (%)": info.get("mape_agregat")})
    long = pd.DataFrame(rows)
    c3, c4 = st.columns(2)
    with c3:
        if not long.empty:
            pivot = long.pivot_table(index="Model", columns="Horizon", values="WAPE (%)").reindex(columns=[HORIZON_LABELS[h] for h in HORIZONS if HORIZON_LABELS[h] in long["Horizon"].values])
            fig = go.Figure(go.Heatmap(z=pivot.values, x=list(pivot.columns), y=list(pivot.index), colorscale="RdYlBu_r", text=np.round(pivot.values, 1),
                                       texttemplate="%{text}", colorbar=dict(title="WAPE %")))
            fig.update_layout(title="WAPE model × horizon")
            _plot(fig, "eval-heat", height=420, legend_below=False)
            _caption_figure("11", "Horizon pendek (hari) paling sulit per SKU; agregasi ke bulan menurunkan galat.")
    with c4:
        classes = [{"Model": info["label"], "Kelas": c, "MAPE (%)": (info.get("mape_per_kelas_ABC") or {}).get(c)} for info in record["models"].values() for c in "ABC"]
        cls = pd.DataFrame(classes).dropna()
        fig = go.Figure()
        for c, color in zip("ABC", ("#1d4ed8", "#60a5fa", "#cbd5e1")):
            part = cls.loc[cls["Kelas"] == c]
            fig.add_bar(x=part["Model"], y=part["MAPE (%)"], name=f"Kelas {c}", marker_color=color)
        fig.update_layout(barmode="group", yaxis_title="MAPE (%)", title="MAPE per kelas ABC")
        _plot(fig, "eval-abc")
        _caption_figure("12", "Kelas A = SKU penyumbang 80% QTY; fokus keputusan stok.")
    c5, c6 = st.columns(2)
    with c5:
        weights = {k: v for k, v in (record.get("weights") or {}).items() if not str(k).startswith("_") and v}
        if weights:
            fig = go.Figure(go.Pie(labels=list(weights), values=list(weights.values()), hole=.45, marker_colors=[H.color_of(k) for k in weights]))
            fig.update_layout(title="Bobot ensemble (1/WAPE)")
            _plot(fig, "eval-weights", height=380)
            _caption_figure("13", "Hanya model yang mengalahkan MA28 yang mendapat bobot.")
    with c6:
        seg = record.get("model_per_segmen") or {}
        if seg:
            frame_seg = pd.DataFrame([{"Segmen": k, "Model dipakai": v["model"], "WAPE model (%)": v["wape_model"], "WAPE ensemble (%)": v["wape_ensemble"]} for k, v in seg.items()])
            fig = go.Figure()
            fig.add_bar(x=frame_seg["Segmen"], y=frame_seg["WAPE ensemble (%)"], name="Ensemble", marker_color="#f6a58f")
            fig.add_bar(x=frame_seg["Segmen"], y=frame_seg["WAPE model (%)"], name="Model per segmen", marker_color="#ee4d2d",
                        text=frame_seg["Model dipakai"], textposition="outside")
            fig.update_layout(barmode="group", yaxis_title="WAPE (%)", title="Model terbaik per segmen ABC-XYZ")
            _plot(fig, "eval-seg", height=380)
            _caption_figure("14", "Segmen tempat ensemble kalah memakai model tunggal terbaiknya.")
    return {f"Hasil uji {horizon}": frame, "Metrik semua horizon": long}


# ---------------------------------------------------------------- 5. Kurva aktual vs prediksi

def _detail(run_folder: Path | None, base_history: pd.DataFrame | None, weights: dict) -> dict | None:
    if run_folder is None or base_history is None or base_history.empty:
        return None
    cache = st.session_state.setdefault("eval-detail-cache", {})
    key = str(run_folder)
    if key in cache:
        return cache[key]
    detail = H.load_detail(run_folder)
    if detail is None:
        with st.spinner("Mereplikasi lipatan walk-forward untuk kurva (sekali per analisa, ±15 detik)..."):
            detail = H.compute_detail(base_history, weights)
        H.save_detail(run_folder, detail)
    cache.clear()
    cache[key] = detail
    return detail


def _curves(detail: dict | None, records: dict) -> dict:
    if not detail or not detail.get("folds"):
        st.info("Kurva butuh hasil analisa tersimpan dengan riwayat harian. Buka atau jalankan analisa terlebih dahulu.")
        return {}
    horizons = sorted({f["days"] for f in detail["folds"]})
    days = st.radio("Horizon kurva", horizons, index=len(horizons) - 1, horizontal=True, format_func=lambda d: f"{d} hari", key="eval-curve-days")
    totals = H.fold_totals(detail, days)
    models = [c for c in totals.columns if c not in ("Lipatan", "Aktual")]
    default = [m for m in (MODEL_SEGMENT, H.BASELINE_LABEL, MODEL_LEVEL) if m in models]
    picked = st.multiselect("Model dibandingkan", models, default=default, key="eval-curve-models")
    fig = go.Figure()
    fig.add_scatter(x=totals["Lipatan"], y=totals["Aktual"], name="Aktual", mode="lines+markers", line=dict(color="#0f172a", width=3))
    for model in picked:
        fig.add_scatter(x=totals["Lipatan"], y=totals[model], name=model, mode="lines+markers", line=dict(color=H.color_of(model), dash="solid" if model == MODEL_SEGMENT else "dot"))
    fig.update_layout(xaxis_title="Titik potong lipatan", yaxis_title=f"QTY total {days} hari", title="Total toko: aktual vs prediksi per lipatan")
    _plot(fig, "eval-curve-total")
    _caption_figure("15", "Selisih garis = kesalahan total toko (dasar MAPE agregat).")
    model = st.selectbox("Model untuk analisa per SKU", models, index=models.index(MODEL_SEGMENT) if MODEL_SEGMENT in models else 0, key="eval-curve-model")
    pairs = H.sku_pairs(detail, days, model)
    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        for c, color in zip("ABC", ("#1d4ed8", "#60a5fa", "#cbd5e1")):
            part = pairs.loc[pairs["Kelas ABC"] == c]
            fig.add_scatter(x=part["Aktual"] + 1, y=part["Prediksi"] + 1, mode="markers", name=f"Kelas {c}", marker=dict(color=color, size=5, opacity=.55),
                            hovertemplate="aktual %{customdata[0]:.0f} · prediksi %{customdata[1]:.1f}<extra></extra>", customdata=part[["Aktual", "Prediksi"]].values)
        top = float(max(pairs["Aktual"].max(), pairs["Prediksi"].max()) + 1) if not pairs.empty else 10
        fig.add_scatter(x=[1, top], y=[1, top], mode="lines", line=dict(dash="dash", color="#ee4d2d"), name="Prediksi = aktual")
        fig.update_layout(xaxis_type="log", yaxis_type="log", xaxis_title="Aktual + 1 (log)", yaxis_title="Prediksi + 1 (log)", title=f"Aktual vs prediksi per SKU · {model}")
        _plot(fig, "eval-scatter", height=460)
        _caption_figure("16", "Titik di atas garis = prediksi berlebih; di bawah = kurang. Kelas A sebaiknya rapat di garis.")
    with c2:
        clip = pairs["Galat"].clip(pairs["Galat"].quantile(.01), pairs["Galat"].quantile(.99)) if not pairs.empty else pairs["Galat"]
        fig = go.Figure(go.Histogram(x=clip, nbinsx=60, marker_color="#1b3da6"))
        fig.add_vline(x=0, line_color="#ee4d2d", line_dash="dash")
        fig.add_vline(x=float(pairs["Galat"].mean()) if not pairs.empty else 0, line_color="#0f172a", annotation_text="rata-rata")
        fig.update_layout(xaxis_title="Galat = prediksi − aktual (unit)", yaxis_title="SKU × lipatan", title="Sebaran galat (residual)", showlegend=False)
        _plot(fig, "eval-resid", height=460)
        _caption_figure("17", "Puncak di 0 = sebagian besar tepat; ekor kiri panjang = kekurangan prediksi pada lonjakan permintaan.")
    c3, c4 = st.columns(2)
    with c3:
        fig = go.Figure()
        for name in picked or [model]:
            curve = H.error_curve(H.sku_pairs(detail, days, name))
            fig.add_scatter(x=curve["Batas galat (%)"], y=curve["% SKU"], mode="lines", name=name, line=dict(color=H.color_of(name), width=3 if name == MODEL_SEGMENT else 2))
        fig.add_vline(x=MAPE_TARGET_PCT, line_dash="dash", line_color="#a16207", annotation_text=f"{MAPE_TARGET_PCT:.0f}%")
        fig.update_layout(xaxis_title="Galat absolut relatif ≤ x%", yaxis_title="% SKU-lipatan (aktual > 0)", title="Kurva akurasi kumulatif")
        _plot(fig, "eval-cum", height=420)
        _caption_figure("18", "Kurva lebih tinggi = lebih banyak SKU dengan galat kecil.")
    with c4:
        part = pairs.loc[pairs["Aktual"] > 0].copy()
        part["Galat relatif (%)"] = (part["Galat"] / part["Aktual"] * 100).clip(-200, 300)
        fig = go.Figure()
        for c, color in zip("ABC", ("#1d4ed8", "#60a5fa", "#94a3b8")):
            fig.add_box(y=part.loc[part["Kelas ABC"] == c, "Galat relatif (%)"], name=f"Kelas {c}", marker_color=color, boxmean=True)
        fig.add_hline(y=0, line_dash="dash", line_color="#ee4d2d")
        fig.update_layout(yaxis_title="Galat relatif (%)", title="Galat relatif per kelas ABC", showlegend=False)
        _plot(fig, "eval-box", height=420)
        _caption_figure("19", "Kotak = kuartil; garis putus = rata-rata. Kelas C paling lebar karena permintaan kecil.")
    scores = H.model_scores(detail, days)
    rec_name = {7: "minggu", 30: "bulan"}.get(days)
    if rec_name and records.get(rec_name):
        ref = record_frame(records[rec_name])[["Model", "WAPE (%)"]].rename(columns={"WAPE (%)": "WAPE analisa (%)"})
        scores = scores.merge(ref, on="Model", how="left")
    st.markdown("**Metrik dari replikasi lipatan** (pembanding konsistensi dengan hasil analisa)")
    show_table(scores, kinds={c: "dec" for c in scores.columns if c != "Model"})
    st.caption("Replikasi memakai riwayat & bobot run yang sama; selisih kecil dengan kolom analisa bisa terjadi karena penanda stok kosong terbaru tidak ikut disimpan.")
    return {f"Total per lipatan {days} hari": totals, f"Pasangan SKU {model}": pairs, "Metrik replikasi": scores}


# ---------------------------------------------------------------- 6. Uji maju

def _forward(features, orders: pd.DataFrame | None) -> dict:
    st.caption("Uji maju = prediksi yang disimpan saat analisa dibandingkan dengan penjualan yang benar-benar terjadi sesudahnya (data yang belum dilihat model). "
               "Ini bukti terkuat untuk tesis dan bertambah setiap kali data transaksi baru diunggah.")
    if features is None or orders is None or orders.empty:
        st.info("Butuh data transaksi dan prediksi tersimpan.")
        return {}
    from sqlalchemy import func, select

    from src.core.feature_store import prediction_snapshot as snap

    try:
        with features.engine.connect() as conn:
            rows = conn.execute(select(snap.c.run_id, snap.c.target_date, func.sum(snap.c.pred_qty), func.min(snap.c.created_at)).group_by(snap.c.run_id, snap.c.target_date)).all()
    except Exception as exc:
        st.info(f"Prediksi tersimpan belum bisa dibaca: {exc}")
        return {}
    frame = pd.DataFrame(rows, columns=["run_id", "target_date", "pred_qty", "created_at"])
    if frame.empty:
        st.info("Belum ada prediksi tersimpan.")
        return {}
    runs = frame.groupby("run_id", as_index=False)["created_at"].min().rename(columns={"run_id": "id", "created_at": "run_at"})
    stamps = pd.to_datetime(orders["order_time"])
    actual = orders.assign(d=stamps.dt.normalize()).groupby("d")["qty"].sum()
    last_day = stamps.max().normalize()
    if stamps.max().hour < 23:
        actual = actual.loc[actual.index < last_day]
    result = H.forward_test(frame, actual, runs)
    if result.empty:
        st.info(f"Belum ada tanggal sesudah analisa yang sudah punya data aktual lengkap (transaksi s.d. {_short_day(str(stamps.max().date()))}). "
                "Unggah transaksi hari berikutnya; uji maju terisi otomatis.")
        return {}
    total_pred, total_act = result["Prediksi"].sum(), result["Aktual"].sum()
    k = st.columns(3)
    card(k[0], "Hari teruji", fmt_num(result["Tanggal"].nunique()), hint=f"{fmt_num(result['run_id'].nunique())} analisa")
    err = (total_pred - total_act) / total_act * 100 if total_act else np.nan
    card(k[1], "Selisih total", fmt_pct(err, 1, signed=True), hint=f"prediksi {fmt_num(total_pred)} vs aktual {fmt_num(total_act)} unit")
    card(k[2], "MAPE harian toko", fmt_pct(float(result["Galat (%)"].abs().mean()), 1), hint="rata-rata |galat| per hari")
    fig = go.Figure()
    act = result.groupby("Tanggal")["Aktual"].first()
    fig.add_bar(x=act.index, y=act.values, name="Aktual", marker_color="#cbd5e1")
    for run_id, part in result.groupby("run_id"):
        fig.add_scatter(x=part["Tanggal"], y=part["Prediksi"], mode="lines+markers", name=f"Prediksi analisa #{run_id}")
    fig.update_layout(yaxis_title="QTY per hari", title="Uji maju: prediksi tersimpan vs aktual")
    _plot(fig, "eval-forward")
    _caption_figure("20", "Batang = aktual; garis = prediksi tiap analisa untuk tanggal sesudah analisa dibuat.")
    show_table(result.rename(columns={"run_id": "Analisa"}), kinds={"Prediksi": "dec", "Aktual": "count", "Galat (%)": "dec"})
    return {"Uji maju": result}


# ---------------------------------------------------------------- 7. Riwayat analisa

def _history(summary: pd.DataFrame, long: pd.DataFrame) -> dict:
    if summary.empty:
        st.info("Belum ada riwayat analisa tersimpan.")
        return {}
    key_cols = ["Hari riwayat", "SKU dievaluasi", "WAPE (%)", "MAPE (%)", "Lipatan terakhir"]
    dup = summary[key_cols].astype(str).agg("|".join, axis=1).duplicated()
    hide = st.toggle("Sembunyikan analisa dengan data & hasil identik", value=True, key="eval-hist-dedupe")
    view = summary.loc[~dup] if hide else summary
    st.caption(f"{fmt_num(len(summary))} analisa tersimpan di server" + (f", {fmt_num(int(dup.sum()))} identik disembunyikan" if hide and dup.any() else "")
               + ". Analisa lama dihapus otomatis setelah 90 hari.")
    long_view = long.loc[long["_folder"].isin(view["_folder"])]
    x = view["Waktu analisa"].dt.strftime("%d %b %H:%M") + " · " + view["Run"]
    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        for col, color in (("WAPE (%)", "#1b3da6"), ("MAPE agregat (%)", "#ee4d2d"), ("WAPE MA28 (%)", "#0f766e")):
            fig.add_scatter(x=x, y=view[col], name=col.replace("(%)", "").strip(), mode="lines+markers", line=dict(color=color, dash="dot" if "MA28" in col else "solid"))
        fig.add_hline(y=MAPE_TARGET_PCT, line_dash="dash", line_color="#a16207", annotation_text=f"Target {MAPE_TARGET_PCT:.0f}%")
        fig.update_layout(yaxis_title="%", title="Tren akurasi model terpilih (horizon bulan)")
        _plot(fig, "eval-hist-trend")
        _caption_figure("21", "Garis datar = metode stabil saat data bertambah; turun = model membaik.")
    with c2:
        fig = go.Figure()
        fig.add_bar(x=x, y=view["Skill vs MA28"] * 100, marker_color=[UP if v > 0 else DOWN for v in view["Skill vs MA28"].fillna(0)], name="Skill vs MA28")
        fig.add_scatter(x=x, y=view["Bias (%)"], name="Bias (%)", mode="lines+markers", line=dict(color="#f59e0b"), yaxis="y2")
        fig.update_layout(yaxis_title="Skill (%)", yaxis2=dict(title="Bias (%)", overlaying="y", side="right"), title="Skill terhadap MA28 & bias tiap analisa")
        _plot(fig, "eval-hist-skill")
        _caption_figure("22", "Batang biru = model terpilih lebih baik dari pembanding baku.")
    month = long_view.loc[long_view["Horizon"] == "Bulan"]
    c3, c4 = st.columns(2)
    with c3:
        if not month.empty:
            labels = month["Waktu analisa"].dt.strftime("%d %b %H:%M") + " · " + month["Run"]
            pivot = month.assign(x=labels).pivot_table(index="Model", columns="x", values="WAPE (%)", sort=False)
            fig = go.Figure(go.Heatmap(z=pivot.values, x=list(pivot.columns), y=list(pivot.index), colorscale="RdYlBu_r", text=np.round(pivot.values, 1), texttemplate="%{text}"))
            fig.update_layout(title="WAPE tiap model di tiap analisa (bulan)")
            _plot(fig, "eval-hist-heat", height=420, legend_below=False)
            _caption_figure("23", "Peringkat model yang konsisten antar analisa menunjukkan pemilihan model tidak kebetulan.")
    with c4:
        weights = pd.DataFrame([{**{"x": xx}, **w} for xx, w in zip(x, view["_weights"])]).set_index("x").fillna(0) if len(view) else pd.DataFrame()
        if not weights.empty:
            fig = go.Figure()
            for col in weights.columns:
                fig.add_bar(x=weights.index, y=weights[col], name=col, marker_color=H.color_of(col))
            fig.update_layout(barmode="stack", yaxis_title="Bobot", title="Bobot ensemble tiap analisa")
            _plot(fig, "eval-hist-weights", height=420)
            _caption_figure("24", "Perubahan bobot menunjukkan model mana yang makin dipercaya seiring data bertambah.")
    seg = pd.DataFrame([{**{"Analisa": xx}, **s} for xx, s in zip(x, view["_segments"])]).fillna("ensemble")
    if len(seg.columns) > 1:
        st.markdown("**Model terpilih per segmen ABC-XYZ tiap analisa**")
        show_table(seg)
    shown = view.drop(columns=[c for c in view.columns if c.startswith("_")])
    st.markdown("**Daftar analisa**")
    show_table(shown, kinds={c: "dec" for c in ("WAPE (%)", "MAPE agregat (%)", "MAPE (%)", "Bias (%)", "RMSE", "WAPE MA28 (%)", "Faktor koreksi bias", "Tingkat layanan simulasi (%)")}
               | {"Skill vs MA28": "dec", "Prediksi QTY ensemble": "count"})
    return {"Riwayat analisa": shown, "Riwayat metrik model": long_view.drop(columns=["_folder"])}


# ---------------------------------------------------------------- 8. Fitur & segmen

def _features(base_history: pd.DataFrame | None) -> dict:
    if base_history is None or base_history.empty:
        st.info("Riwayat harian belum tersedia.")
        return {}
    stamp = (len(base_history), str(base_history["period_start"].max()))
    cached = st.session_state.get("_feat-imp")
    if isinstance(cached, tuple) and cached[0] == stamp:
        imp, method = cached[1], cached[2]
    else:
        with st.spinner("Menghitung kepentingan fitur..."):
            try:
                imp, method = feature_importance(build_demand_matrix(base_history))
            except Exception as exc:
                imp, method = pd.DataFrame(), f"gagal: {exc}"
        st.session_state["_feat-imp"] = (stamp, imp, method)
    st.markdown(f"**Kepentingan fitur model global** · {method}")
    if imp.empty:
        return {}
    fig = go.Figure(go.Bar(x=imp["Kepentingan"], y=imp["Fitur"], orientation="h", marker_color="#1b3da6", text=[fmt_pct(v, 1) for v in imp["Kepentingan"]], textposition="outside"))
    fig.update_layout(yaxis=dict(autorange="reversed"), xaxis_title="Kepentingan (%)", title="Fitur yang paling memengaruhi prediksi")
    _plot(fig, "eval-imp", height=460, legend_below=False)
    _caption_figure("25", "Fitur lag/rolling dominan = permintaan terbaru paling informatif; fitur promo menangkap lonjakan tanggal kembar.")
    return {"Kepentingan fitur": imp}


# ---------------------------------------------------------------- utama

def show_evaluation(
    outcome,
    *,
    comparison: pd.DataFrame,
    enriched: pd.DataFrame,
    orders: pd.DataFrame,
    period: str,
    today: date,
    params: dict,
    base_history: pd.DataFrame | None = None,
    is_super: bool = False,
    repo=None,
    run_id: int = 0,
    features=None,
) -> None:
    st.subheader("Evaluasi model")
    st.caption("Bahan tesis: apakah algoritma & metode peramalan sudah sesuai, dibuktikan dengan uji walk-forward, uji maju, dan riwayat seluruh analisa.")
    records = _records(outcome)
    db_runs, run_folder = {}, None
    if repo is not None:
        try:
            for rec in repo.list_runs(500):
                if rec.result_path:
                    db_runs[str(Path(rec.result_path).resolve())] = {"id": rec.id, "run_by": rec.run_by}
            current = repo.get(int(run_id)) if run_id else None
            run_folder = repo.folder_of(current) if current is not None and repo.available(current) else None
        except Exception:
            pass
    root = getattr(repo, "runs_root", None)
    summary, long = H.history_frame(root, db_runs) if root is not None else (pd.DataFrame(), pd.DataFrame())
    choice = st.segmented_control("Bagian", TABS, default=TABS[0], key="eval-section") if hasattr(st, "segmented_control") else st.radio("Bagian", TABS, horizontal=True)
    choice = choice or TABS[0]
    tables: dict[str, pd.DataFrame] = {}
    try:
        if choice == TABS[0]:
            framework = _framework(outcome, enriched, params, today, records.get("bulan"))
            checks = _summary(outcome, records, summary, framework)
            tables.update({"Uji kesesuaian metode": checks, "Kerangka pengujian": framework})
            if isinstance(comparison, pd.DataFrame) and not comparison.empty:
                with st.expander("Uji total toko (hold-out 7 hari, metode lama)"):
                    show_table(comparison)
        elif choice == TABS[1]:
            _methodology(outcome, records, period, is_super)
        elif choice == TABS[2]:
            tables.update(_data_profile(base_history, records))
        elif choice == TABS[3]:
            tables.update(_results(records, period))
        elif choice == TABS[4]:
            weights = dict(getattr(outcome, "weights", None) or {})
            tables.update(_curves(_detail(run_folder, base_history, weights), records))
        elif choice == TABS[5]:
            tables.update(_forward(features, orders))
        elif choice == TABS[6]:
            tables.update(_history(summary, long))
        elif choice == TABS[7]:
            tables.update(_features(base_history))
        else:
            _appendix(outcome, records, summary, long, base_history, enriched, params, today, run_folder)
    except Exception as exc:
        st.warning(f"Bagian ini belum bisa ditampilkan: {exc}")
    if tables and choice != TABS[8]:
        download_excel({k[:31]: v for k, v in tables.items() if isinstance(v, pd.DataFrame) and not v.empty}, f"evaluasi_model_{choice.split()[0].lower()}.xlsx",
                       key=f"xl-eval-{TABS.index(choice)}", label="Unduh tabel bagian ini (Excel)")


def _appendix(outcome, records, summary, long, base_history, enriched, params, today, run_folder) -> None:
    st.markdown("**Lampiran tesis** · satu file Excel berisi semua tabel evaluasi")
    st.caption("Isi: uji kesesuaian metode, kerangka pengujian, hasil uji keempat horizon, riwayat analisa, profil permintaan, segmen, dan metrik replikasi lipatan (bila sudah dihitung).")
    if st.button("Susun lampiran", key="eval-appendix", type="primary"):
        with st.spinner("Menyusun lampiran..."):
            sheets: dict[str, pd.DataFrame] = {}
            record = records.get("bulan") or {}
            if record:
                sheets["Uji kesesuaian metode"] = H.method_checks(record, summary if not summary.empty else None)
            sheets["Kerangka pengujian"] = _framework(outcome, enriched, params, today, record or None)
            for name in HORIZONS:
                if (records.get(name) or {}).get("models"):
                    sheets[f"Uji {name}"] = record_frame(records[name])
            if not summary.empty:
                sheets["Riwayat analisa"] = summary.drop(columns=[c for c in summary.columns if c.startswith("_")])
                sheets["Riwayat metrik model"] = long.drop(columns=["_folder"])
            if base_history is not None and not base_history.empty:
                profile, _daily, seg = _profile(base_history)
                sheets["Profil permintaan"] = profile
                sheets["Segmen ABC-XYZ"] = seg
            detail = H.load_detail(run_folder) if run_folder is not None else None
            if detail:
                for days in sorted({f["days"] for f in detail["folds"]}):
                    sheets[f"Lipatan {days} hari"] = H.fold_totals(detail, days)
                    sheets[f"Metrik replikasi {days}h"] = H.model_scores(detail, days)
            st.session_state["eval-appendix-data"] = sheets
    sheets = st.session_state.get("eval-appendix-data")
    if sheets:
        st.success(f"{len(sheets)} lembar siap: " + ", ".join(sheets))
        download_excel({k[:31]: v for k, v in sheets.items() if not v.empty}, "lampiran_evaluasi_model.xlsx", key="xl-eval-appendix", label="Unduh lampiran (Excel)")
