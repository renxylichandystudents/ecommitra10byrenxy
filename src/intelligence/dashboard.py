"""Dasbor uji model di menu Evaluasi model."""

from __future__ import annotations

import io

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.intelligence.benchmark import benchmark_cancel_risk, benchmark_daily_demand
from src.intelligence.preprocess import clean_frame

METHOD_LABELS = {
    "IQR": "iqr",
    "Z-score": "zscore",
    "Isolation Forest": "isolation_forest",
}


@st.cache_data(show_spinner=False)
def _cached_benchmark(history: pd.DataFrame, orders: pd.DataFrame, method: str):
    demand, demand_note = benchmark_daily_demand(history, method)
    cancel, cancel_note = benchmark_cancel_risk(orders, method)
    _cleaned, report = clean_frame(orders, method)
    return demand, demand_note, cancel, cancel_note, report


def show_intelligence_dashboard(orders: pd.DataFrame, history: pd.DataFrame) -> None:
    """Uji regresi dan risiko batal. Tidak menulis ulang prediksi stok."""
    st.subheader("I. Uji model pada salinan data")
    st.caption(
        "Regresi, pohon, tetangga terdekat, dan gradient boosting diuji di sini untuk bukti tesis. "
        "Pemenang uji tidak mengganti Level terkini pada menu Prediksi & stok."
    )
    method_label = st.radio(
        "Reduksi noise pada salinan uji",
        options=list(METHOD_LABELS),
        horizontal=True,
        key="noise-method",
    )
    method = METHOD_LABELS[method_label]
    with st.spinner("Membandingkan model pada salinan uji..."):
        demand, demand_note, cancel, cancel_note, report = _cached_benchmark(history, orders, method)
    cards = st.columns(4)
    cards[0].metric("Baris salinan", f"{report.rows_in:,}".replace(",", "."))
    cards[1].metric("Kosong diisi median", f"{report.missing_filled:,}".replace(",", "."))
    cards[2].metric("Lonjakan dipotong", f"{report.values_clipped:,}".replace(",", "."))
    cards[3].metric("Metode", method_label)
    st.caption(report.note)

    left, right = st.columns(2)
    with left:
        st.markdown("<div class='section-title'>Permintaan harian</div>", unsafe_allow_html=True)
        st.caption(demand_note)
        _chart_and_table(demand, "RMSE", "RMSE hari ujian", "permintaan_harian.xlsx")
    with right:
        st.markdown("<div class='section-title'>Risiko pesanan batal</div>", unsafe_allow_html=True)
        st.caption(cancel_note)
        _chart_and_table(cancel, "F1", "F1 kelas batal", "risiko_batal.xlsx")


def _chart_and_table(table: pd.DataFrame, column: str, title: str, filename: str) -> None:
    if table is None or table.empty or column not in table.columns:
        st.write("Uji ini belum terbentuk pada data yang sedang dibuka.")
        return
    ready = table[pd.to_numeric(table[column], errors="coerce").notna()].copy()
    if not ready.empty:
        ready = ready.sort_values(column, ascending=True)
        colors = ["#047857" if role == "Pemenang uji" else "#94a3b8" for role in ready["Peran"]]
        figure = go.Figure(
            go.Bar(
                x=ready[column],
                y=ready["Algoritma"],
                orientation="h",
                marker_color=colors,
                hovertemplate="%{y}: %{x}<extra></extra>",
            )
        )
        figure.update_layout(
            title=title,
            height=max(280, 36 * len(ready) + 80),
            margin=dict(l=8, r=8, t=42, b=8),
            xaxis_title=column,
            yaxis_title="",
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(figure, use_container_width=True)
    st.dataframe(table, hide_index=True, use_container_width=True)
    buffer = io.BytesIO()
    table.to_excel(buffer, index=False, engine="openpyxl")
    st.download_button(
        "Unduh Excel",
        data=buffer.getvalue(),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"excel-{filename}",
    )
