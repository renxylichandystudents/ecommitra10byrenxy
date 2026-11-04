"""Tab Evaluasi model: strategi, pemodelan, hasil testing, perbandingan model, kesimpulan."""

from __future__ import annotations

import time
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.core.decision_table import PERIOD_LABELS, build_decision_table
from src.core.ensemble import MODEL_ENSEMBLE, MODEL_LEVEL, build_demand_matrix, feature_importance
from src.core.evaluation import MAPE_TARGET_PCT
from src.core.expert_system import action_steps, evaluate_rules, sku_facts
from src.core.optimization import optimize_restock
from src.core.libstatus import library_status
from src.models.evaluate import HORIZON_LABELS, HORIZONS, PERIOD_TO_HORIZON, record_frame
from src.utils.format import show_table
from src.ui.common import download_excel, fmt_num, fmt_pct

METRIC_COLUMNS = ("MAPE (%)", "MAPE agregat (%)", "WAPE (%)", "Bias (%)", "RMSE", "MAPE kelas A (%)", "MAPE kelas C (%)")
UPLOAD_MENUS = (
    "Transaksi",
    "Performance produk",
    "Iklan produk otomatis",
    "Iklan produk grup",
    "Keseluruhan iklan",
    "Iklan pencarian",
    "Stok",
    "Produk deskripsi",
    "Produk kompetitor",
)


def _records(outcome) -> dict:
    return dict(getattr(outcome, "eval_records", None) or {}) if outcome is not None else {}


def _pick_horizon(records: dict, period: str, key: str) -> str | None:
    ready = [name for name in HORIZONS if records.get(name, {}).get("models")]
    if not ready:
        return None
    default = PERIOD_TO_HORIZON.get(period, "bulan")
    index = ready.index(default) if default in ready else len(ready) - 1
    return st.selectbox("Horizon uji", ready, index=index, format_func=lambda h: f"{HORIZON_LABELS[h]} ({HORIZONS[h]} hari)", key=key)


def _strategy() -> None:
    steps = (
        ("Data", "9 menu upload: " + ", ".join(UPLOAD_MENUS).lower() + ". Duplikat dibuang, snapshot stok disimpan per tanggal unggah."),
        ("Prapemrosesan", "Kalender harian per SKU, hari tanpa pesanan = 0, hari stok kosong = tidak teramati (permintaan tersensor), harga bersih 4 minggu, penanda promo (tanggal kembar, gajian, Harbolnas)."),
        ("Segmentasi", "ABC (kontribusi sales), XYZ (variasi permintaan), label produktivitas, association rules untuk kelompok iklan."),
        ("Forecasting", "Level terkini, Moving Average 28, Exponential Smoothing, XGBoost & LightGBM global, Prophet → ensemble berbobot 1/WAPE (hanya model yang mengalahkan MA28) + koreksi bias dari walk-forward 6 lipatan."),
        ("Safety stock & optimisasi", "SS = Z × σ permintaan × √lead time (lokal); rumus umum bila lead time bervariasi; (Lmaks − Lrata) × D untuk impor. ROP, Monte Carlo, MILP restock (PuLP) dengan fallback heuristik."),
        ("Sistem pakar", "Aturan JIKA–MAKA di config/rules.yaml: stok, iklan, batal, listing, tren; maksimal 3 langkah terukur, iklan tidak dinaikkan bila stok kurang."),
        ("Rekomendasi", "Nama & deskripsi (NLP kompetitor), iklan, flash sale, exposure, laporan & panduan kerja."),
    )
    cols = st.columns(len(steps))
    for column, (name, text) in zip(cols, steps):
        column.markdown(
            f"<div style='border:1px solid #e2e8f0;border-radius:10px;padding:8px;min-height:190px'><b>{name}</b>"
            f"<div style='font-size:.78rem;color:#475569;margin-top:4px'>{text}</div></div>",
            unsafe_allow_html=True,
        )


def _modeling(outcome, period: str, *, is_super: bool = False) -> None:
    st.markdown(
        "- **Target**: QTY terjual per SKU per hari, dijumlahkan ke horizon bergulir periode prediksi "
        f"({PERIOD_LABELS[period]}). Sales = prediksi QTY × harga bersih rata-rata 4 minggu terakhir.\n"
        "- **Data latih**: bulan yang dicentang pada halaman input; QTY bersih bila Kecualikan batal & retur aktif.\n"
        "- **Fitur model global**: lag 1, rata-rata 7/14/28/90 hari, rata-rata 28 hari sebelumnya, variasi 28 hari, porsi hari aktif, "
        "status stok kemarin, porsi hari promo ke depan, bulan, perubahan level.\n"
        "- **Hari stok kosong**: tidak dihitung sebagai permintaan nol (dikeluarkan dari latih & evaluasi), karena penjualan 0 saat stok 0 bukan berarti tidak ada permintaan.\n"
        "- **Agregasi**: laju harian × jumlah hari pada jendela prediksi.\n"
        "- **Uji**: walk-forward 6 lipatan (titik potong tanggal 1 tiap bulan, Mei–Okt 2026 bila data cukup) untuk horizon hari, minggu, bulan, kuartal."
    )
    if is_super:
        with st.expander("Status library (hanya super user)"):
            show_table(pd.DataFrame(library_status()))
    if outcome is None:
        st.info("Model tambahan belum dijalankan: prediksi memakai Level terkini saja.")
        return
    rows = [{"Algoritma": name, "Status": "Aktif", "Keterangan": note} for name, note in outcome.availability.active.items()]
    if is_super:
        rows += [{"Algoritma": name, "Status": "Dilewati", "Keterangan": note} for name, note in outcome.availability.skipped.items()]
    show_table(pd.DataFrame(rows))
    if outcome.censored_skus:
        st.caption(f"{fmt_num(outcome.censored_skus)} SKU punya hari stok kosong yang diperlakukan sebagai permintaan tersensor.")


def _testing(outcome, table: pd.DataFrame, params: dict, today: date, period: str) -> dict:
    results: dict = {}
    records = _records(outcome)
    horizon = _pick_horizon(records, period, "eval-test-horizon")
    if horizon is None:
        st.info("Hasil uji walk-forward belum tersedia (riwayat harian terlalu pendek, atau hasil analisa lama). Jalankan analisa ulang.")
    else:
        record = records[horizon]
        results["record"] = record
        st.caption(
            f"Walk-forward {len(record['fold_dates'])} lipatan, titik potong "
            + ", ".join(record["fold_dates"])
            + f"; {fmt_num(record['n_sku'])} SKU aktif. MAPE dihitung hanya pada titik aktual > 0; "
            "WAPE = Σ|aktual − prediksi| / Σ aktual; bias = Σ(prediksi − aktual) / Σ aktual."
        )
        frame = record_frame(record)
        show_table(frame, kinds={c: "dec" for c in METRIC_COLUMNS})
        download_excel(frame, f"eval_{horizon}.xlsx", key=f"xl-eval-{horizon}")
        st.caption(
            f"Faktor koreksi bias ensemble: {fmt_num(record.get('faktor_koreksi_bias', 1.0), 3)} "
            f"(bias sebelum koreksi {fmt_pct(record.get('bias_sebelum_koreksi'))})."
        )
        if record.get("model_per_segmen"):
            st.markdown("**Model terbaik per segmen ABC-XYZ (ensemble kalah di segmen ini)**")
            seg = pd.DataFrame(
                [{"Segmen": k, "Model dipakai": v["model"], "WAPE model (%)": v["wape_model"], "WAPE ensemble (%)": v["wape_ensemble"]} for k, v in record["model_per_segmen"].items()]
            )
            show_table(seg, kinds={"WAPE model (%)": "dec", "WAPE ensemble (%)": "dec"})
        for note in record.get("notes") or []:
            st.caption(note)
        best = record["models"].get(record.get("best_model") or "", {})
        results["mape"] = best.get("mape") if best.get("mape") is not None else np.nan
        results["best_label"] = best.get("label")
        results["top50"] = best.get("top50_tepat")

    st.markdown("**Hasil kerangka pengujian (4.9)**")
    rows = []
    mape = results.get("mape", np.nan)
    rows.append(
        {
            "No": 1,
            "Komponen": "Demand forecasting",
            "Metode": f"Walk-forward 6 lipatan · model terbaik {results.get('best_label') or '-'}",
            "Target": f"MAPE ≤ {MAPE_TARGET_PCT:.0f}%",
            "Hasil": fmt_pct(mape) if np.isfinite(mape) else "belum tersedia",
            "Status": ("Tercapai" if mape <= MAPE_TARGET_PCT else "Belum tercapai") if np.isfinite(mape) else "-",
        }
    )
    if table is not None and not table.empty:
        top = table.head(50)
        demand = top["pred_harian"].astype(float)
        lead = params.get("lead_time", {})
        l_avg = float(lead.get("impor_rata_hari", 60))
        l_max = float(lead.get("impor_maks_hari", 90))
        ss_import = (l_max - l_avg) * demand
        short = int(((demand * l_max) > (demand * l_avg + ss_import + 1e-9)).sum())
        rows.append({"No": 2, "Komponen": "Safety stock multi-source", "Metode": "Stress test keterlambatan impor sampai Lmaks pada Top 50", "Target": "0% stockout", "Hasil": f"{fmt_pct(short / max(len(top), 1) * 100)} stockout", "Status": "Tercapai" if short == 0 else "Belum tercapai"})
        items = pd.DataFrame(
            {
                "item_key": top["item_key"],
                "kebutuhan": top["m_butuh"].astype(float),
                "current_stock": top["stok"].fillna(0).astype(float),
                "rop": top["rop"].astype(float),
            }
        )
        try:
            plan = optimize_restock(items, capacity=float(params.get("gudang", {}).get("kapasitas_unit", 100000)), moq=float(params.get("gudang", {}).get("moq_unit", 1)))
            status = str(plan["optimizer_status"].iloc[0]) if "optimizer_status" in plan.columns and not plan.empty else "-"
            ok = not plan.empty and "infeasible" not in status.lower()
        except Exception as exc:
            status, ok = f"gagal: {exc}", False
        rows.append({"No": 3, "Komponen": "Inventory optimization", "Metode": "MILP Big-M pada Top 50 (PuLP, warm start)", "Target": "0% infeasible", "Hasil": status, "Status": "Tercapai" if ok else "Belum tercapai"})
        errors, violations = 0, 0
        for _, row in top.iterrows():
            try:
                facts = sku_facts(row, today=today)
                steps = action_steps(evaluate_rules(facts), facts)
                if facts.get("status_stok") in {"Kosong", "Kurang", "Tipis"} and any("naikkan" in s.lower() and "iklan" in s.lower() for s in steps):
                    violations += 1
            except Exception:
                errors += 1
        rows.append({"No": 4, "Komponen": "Sistem pakar, NLP & SEO", "Metode": "Black-box pada Top 50 + uji unit", "Target": "100% berjalan, saran valid", "Hasil": f"{len(top) - errors}/{len(top)} berjalan, {violations} saran tidak valid", "Status": "Tercapai" if errors == 0 and violations == 0 else "Belum tercapai"})
        start = time.perf_counter()
        build_decision_table(table, period="bulan", today=today, horizon_days=30)
        elapsed = time.perf_counter() - start
        rows.append({"No": 5, "Komponen": "Web performance", "Metode": f"Waktu bangun tabel keputusan {fmt_num(len(table))} SKU", "Target": "< 3 detik (dengan cache)", "Hasil": f"{fmt_num(elapsed, 2)} detik", "Status": "Tercapai" if elapsed < 3 else "Belum tercapai"})
    show_table(pd.DataFrame(rows))
    if results.get("top50") is not None:
        st.caption(f"Akurasi Top 50: {fmt_num(results['top50'], 1)} dari 50 SKU prediksi teratas masuk Top 50 aktual pada lipatan uji (rata-rata).")
    return results


def _comparison(outcome, period: str) -> None:
    records = _records(outcome)
    horizon = _pick_horizon(records, period, "eval-horizon")
    if horizon is None:
        st.info("Perbandingan model membutuhkan hasil walk-forward.")
        return
    frame = record_frame(records[horizon])
    metric = st.selectbox("Metrik", ["MAPE (%)", "WAPE (%)", "MAPE agregat (%)", "Bias (%)", "RMSE"], key="eval-metric")
    part = frame.dropna(subset=[metric]).sort_values(metric)
    colors = ["#ee4d2d" if m == MODEL_ENSEMBLE else ("#64748b" if m == MODEL_LEVEL else "#1b3da6") for m in part["Model"]]
    fig = go.Figure(go.Bar(x=part["Model"], y=part[metric], marker_color=colors, text=[fmt_num(v, 2) for v in part[metric]], textposition="outside", name=metric, hovertemplate="%{x}<br>" + metric + ": %{y:.2f}<extra></extra>"))
    if "MAPE" in metric:
        fig.add_hline(y=MAPE_TARGET_PCT, line_dash="dash", line_color="#a16207", annotation_text=f"Target {MAPE_TARGET_PCT:.0f}%")
    fig.update_layout(height=420, yaxis_title=metric, margin=dict(l=40, r=20, t=30, b=40), showlegend=False)
    st.plotly_chart(fig, use_container_width=True, key="eval-bar")
    st.caption("Angka grafik = tabel Hasil testing horizon yang sama. Abu-abu = Level terkini (metode lama), oranye = ensemble, biru = model pembanding.")


def _conclusion(outcome, results: dict, base_history: pd.DataFrame | None, period: str) -> None:
    records = _records(outcome)
    for name in HORIZONS:
        record = records.get(name)
        if record and record.get("kesimpulan"):
            st.markdown(f"- **{HORIZON_LABELS[name]}** · {record['kesimpulan']}")
    month = records.get("bulan", {})
    sim = month.get("simulasi_ss") or {}
    strengths, weaknesses = [], []
    if sim.get("tingkat_layanan_pct") is not None:
        strengths.append(
            f"Tingkat layanan simulasi SS (horizon bulan): {fmt_pct(sim['tingkat_layanan_pct'])} SKU-lipatan dengan prediksi + SS ≥ permintaan aktual."
        )
    if sim.get("stok_kosong_tertangkap_pct") is not None:
        strengths.append(
            f"Hari stok kosong tertangkap: {fmt_pct(sim['stok_kosong_tertangkap_pct'])} dari {fmt_num(sim['sku_stok_kosong'])} SKU yang sempat kosong tetap diprediksi punya permintaan (tidak dianggap nol)."
        )
    best = month.get("models", {}).get(month.get("best_model") or "", {})
    classes = best.get("mape_per_kelas_ABC") or {}
    if classes.get("A") is not None:
        (strengths if classes["A"] <= MAPE_TARGET_PCT else weaknesses).append(f"MAPE kelas A (horizon bulan): {fmt_pct(classes['A'])}.")
    mape = results.get("mape", np.nan)
    if mape is not None and np.isfinite(mape) and mape > MAPE_TARGET_PCT:
        weaknesses.append(f"MAPE model terbaik {fmt_pct(mape)} masih di atas target {MAPE_TARGET_PCT:.0f}%.")
    weaknesses.append("MAPE per SKU tinggi pada SKU jarang laku; WAPE dan MAPE agregat lebih stabil untuk keputusan stok.")
    improve = [
        "Unggah snapshot stok DC Cikupa rutin (mingguan) agar hari kosong & lama kosong akurat.",
        "Lengkapi laporan iklan per Kode produk agar ROAS per SKU tidak memakai default.",
        "Tambah riwayat ≥ 12 bulan untuk menangkap musim renovasi (Kuartal/Semester/Tahun).",
    ]
    cols = st.columns(3)
    for column, (title, items) in zip(cols, (("Kekuatan", strengths), ("Kelemahan", weaknesses), ("Perbaikan data", improve))):
        with column.container(border=True):
            st.markdown(f"**{title}**")
            st.markdown("\n".join(f"- {i}" for i in items))
    if isinstance(base_history, pd.DataFrame) and not base_history.empty:
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
        if not imp.empty:
            fig = go.Figure(go.Bar(x=imp["Kepentingan"], y=imp["Fitur"], orientation="h", marker_color="#1b3da6", text=[f"{v:.1f}%" for v in imp["Kepentingan"]], textposition="outside", hovertemplate="%{y}: %{x:.1f}%<extra></extra>"))
            fig.update_layout(height=420, yaxis=dict(autorange="reversed"), xaxis_title="Kepentingan (%)", margin=dict(l=40, r=20, t=20, b=40))
            st.plotly_chart(fig, use_container_width=True, key="eval-imp")


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
) -> None:
    st.subheader("Evaluasi model")
    tabs = st.tabs(["Strategi sistem", "Pemodelan", "Hasil testing", "Perbandingan model", "Kesimpulan"])
    results: dict = {}
    with tabs[0]:
        _strategy()
    with tabs[1]:
        _modeling(outcome, period, is_super=is_super)
    with tabs[2]:
        try:
            results = _testing(outcome, enriched, params, today, period)
        except Exception as exc:
            st.warning(f"Hasil testing belum bisa ditampilkan: {exc}")
        if isinstance(comparison, pd.DataFrame) and not comparison.empty:
            with st.expander("Uji total toko (hold-out 7 hari, metode lama)"):
                show_table(comparison)
    with tabs[3]:
        _comparison(outcome, period)
    with tabs[4]:
        _conclusion(outcome, results, base_history, period)
