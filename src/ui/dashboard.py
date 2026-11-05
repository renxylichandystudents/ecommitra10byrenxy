"""Ringkasan › Dashboard prioritas (Revisi Final 4A), di atas konten Ringkasan lama."""

from __future__ import annotations

import html
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src.core import warehouse
from src.core.access import ROLE_LABELS, setting_tabs
from src.core.decision_table import stock_shortage
from src.core.fmt import fmt_date
from src.core.periods import prediction_window, short_date
from src.core.promo import promo_eligible
from src.core.restock import restock_priority
from src.ui.common import badge, card, download_excel, fmt_num, sku_cards, status_key
from src.ui.feature_data import FeatureData
from src.utils.format import show_table

STEP = 10


def status_badges(frame: pd.DataFrame, column: str = "Status") -> pd.DataFrame:
    """Status sebagai label berikon agar terbaca seperti badge di st.dataframe."""
    icons = {"Kosong": "🔴 Kosong", "Kurang": "🟠 Kurang", "Aman": "🟢 Aman", "Tanpa data stok": "⚪ Tanpa data stok"}
    out = frame.copy()
    if column in out.columns:
        out[column] = out[column].map(lambda v: icons.get(status_key(v), str(v)))
    return out


def capacity_summary(features, table: pd.DataFrame) -> tuple[str, str]:
    """(nilai kartu, keterangan) Kapasitas DC dari layout + dimensi karton."""
    if features is None:
        return "–", "Layout gudang belum diunggah"
    try:
        racks = features.read("warehouse_rack")
        cartons = features.read("carton_dimension")
    except Exception:
        return "–", "Layout gudang belum diunggah"
    if racks.empty:
        return "–", "Layout gudang belum diunggah (Setting › Kapasitas gudang)"
    latest = racks.loc[racks["layout_version"] == racks["layout_version"].max()]
    capacity = warehouse.zone_capacity(latest)
    used, missing = warehouse.zone_usage(table, warehouse.unit_volume(cartons), list(capacity.index))
    total_cap = float(capacity.sum())
    pct = float(used.sum()) / total_cap * 100 if total_cap > 0 else float("nan")
    note = f"{fmt_num(used.sum(), 1)} dari {fmt_num(total_cap, 1)} m³"
    if not missing.empty:
        note += f" · {fmt_num(len(missing))} SKU belum ada dimensi karton"
    return (f"{fmt_num(pct, 1)}%" if pd.notna(pct) else "–"), note


def last_actual(orders: pd.DataFrame | None, keys: list[str], today: date) -> tuple[float, date | None]:
    """QTY Top 50 pada hari penuh terakhir sebelum `today`; hari ini masih berjalan sehingga tidak dipakai."""
    if orders is None or orders.empty:
        return 0.0, None
    days = pd.to_datetime(orders["order_time"], errors="coerce").dt.date
    full = days[days < today]
    if full.empty:
        return 0.0, None
    last = full.max()
    part = orders.loc[(days == last) & orders["item_key"].astype(str).isin(set(keys))]
    return float(part["qty"].sum()), last


def actual_hint(predicted: float, actual: float, day: date | None, today: date) -> str:
    if day is None:
        return "Belum ada transaksi hari penuh"
    when = "kemarin" if day == today - timedelta(days=1) else "transaksi terakhir"
    text = f"Aktual {when} ({short_date(day)}): {fmt_num(actual)}"
    if actual > 0:
        gap = (predicted - actual) / actual * 100
        text += f" · selisih {'+' if gap >= 0 else '−'}{fmt_num(abs(gap), 1)}%"
    return text


def show_priority_dashboard(
    table: pd.DataFrame,
    *,
    today: date,
    orders: pd.DataFrame | None,
    features,
    data: FeatureData,
    role: str,
    window_label: str,
    window_start: date,
    fresh_period: bool,
    metric: str = "qty",
) -> None:
    st.markdown("<div class='section-title'>Dashboard prioritas</div>", unsafe_allow_html=True)
    if table is None or table.empty:
        st.write("Belum ada SKU untuk ditampilkan.")
        return
    top = table.head(50)
    keys = top["item_key"].astype(str).tolist()
    actual_qty, actual_day = last_actual(orders, keys, today)
    predicted_today = float(top["d_qty"].sum())
    shortage = stock_shortage(top)
    cols = st.columns(4)
    card(
        cols[0],
        "Prediksi QTY hari ini · Top 50",
        fmt_num(predicted_today),
        hint=actual_hint(predicted_today, actual_qty, actual_day, today),
    )
    fresh = " " + badge("periode baru", "info") if fresh_period else ""
    lo, hi = prediction_window("bulan", window_start)
    card(
        cols[1],
        f"Kebutuhan stok {window_label} · Top 50",
        fmt_num(top["m_butuh"].sum()) + fresh,
        hint=f"Prediksi (unit utuh) + safety stock · {short_date(lo)} – {short_date(hi)}",
    )
    gaps = [f"{fmt_num(shortage['kosong'])} kosong (stok 0)", f"{fmt_num(shortage['di_bawah_ss'])} di bawah SS"]
    if shortage["tanpa_data"]:
        gaps.append(f"{fmt_num(shortage['tanpa_data'])} tanpa data stok")
    card(cols[2], "SKU Top 50 stok kurang", fmt_num(shortage["kurang"]), hint="Stok di bawah prediksi + SS · " + " · ".join(gaps))
    cap_value, cap_note = capacity_summary(features, table)
    card(cols[3], "Kapasitas DC", cap_value, hint=cap_note)

    priority = restock_priority(top, today, po=data.po)
    basis = "Sales volume" if metric == "sales" else "QTY terjual"
    left, right = st.columns([3, 1.25], gap="medium")
    with left:
        st.markdown(f"**Kebutuhan restock prioritas · Top 50 {basis}**")
        st.caption(
            f"SKU = Top 50 menurut {basis} (kolom Peringkat); angka prediksi QTY sama untuk kedua parameter. "
            "Restock = max(0, prediksi + SS − stok DC). Stok habis = hari ini + stok ÷ prediksi harian. Urut stok habis paling cepat, lalu restock terbesar."
        )
        if priority.empty:
            st.info("Data stok Top 50 belum diunggah, jadi kebutuhan restock belum bisa dihitung.")
        else:
            limit = int(st.session_state.get("dash-limit", STEP))
            view = restock_view(priority)
            display = status_badges(view.head(limit))
            if not display["Inbound"].astype(str).str.strip().any():
                display = display.drop(columns="Inbound")
            with st.container(key="desktop-dash-restock"):
                show_table(display, kinds={"Peringkat": "count", "Stok DC": "count", "Prediksi": "count", "SS": "count", "Restock": "count"}, column_config={"Status": st.column_config.TextColumn(width="small")})
            sku_cards(
                [
                    {
                        "sku": r.get("SKU"),
                        "produk": r.get("Produk"),
                        "varian": r.get("Varian"),
                        "status": r.get("Status"),
                        "nums": [("Peringkat", fmt_num(r.get("Peringkat"))), ("Stok DC", fmt_num(r.get("Stok DC"))), ("Prediksi", fmt_num(r.get("Prediksi"))), ("SS", fmt_num(r.get("SS"))), ("Restock", fmt_num(r.get("Restock"))), ("Stok habis", r.get("Stok habis", "–"))],
                    }
                    for r in view.head(limit).to_dict("records")
                ],
                key="dash-restock",
            )
            b1, b2 = st.columns([1, 1])
            if limit < len(priority) and b1.button("Muat 10 SKU lagi", key="dash-more"):
                st.session_state["dash-limit"] = limit + STEP
                st.rerun()
            with b2:
                download_excel(view, "restock_prioritas.xlsx", key="xl-dash-restock")
    with right:
        _insight_cards(table, priority, data, role)


def restock_view(priority: pd.DataFrame) -> pd.DataFrame:
    out = priority.rename(columns={"sku": "SKU"}).copy()
    out["Stok habis"] = [
        short_date(day) if day else ("Tidak habis · prediksi 0" if rate <= 0 else "–")
        for day, rate in zip(out["Stok habis"], out["_pred_harian"])
    ]
    return out[["Peringkat", "SKU", "Produk", "Varian", "Stok DC", "Prediksi", "SS", "Restock", "Stok habis", "Status", "Inbound"]]


def _insight_cards(table: pd.DataFrame, priority: pd.DataFrame, data: FeatureData, role: str) -> None:
    lines = []
    if not priority.empty:
        empty = int((priority["Status"] == "Kosong").sum())
        total = float(priority["Restock"].sum())
        lines.append(f"<b>{fmt_num(empty)}</b> SKU Top 50 kosong · total restock Top 50 <b>{fmt_num(total)}</b> unit.")
        first = priority.iloc[0]
        po = data.po.get(str(first["sku"]))
        if po:
            eta = fmt_date(po["eta"]) if po.get("eta") else "ETA belum ada"
            lines.append(f"SKU teratas {html.escape(str(first['sku']))} punya PO impor {html.escape(po['no_po'])} ({fmt_num(po['qty'])} unit, {eta}).")
        elif data.po:
            lines.append(f"{fmt_num(len(data.po))} SKU punya PO impor terbuka (lihat kolom Inbound).")
    held = 0
    if "biaya_iklan" in table.columns:
        spending = table.loc[table["biaya_iklan"].fillna(0) > 0]
        for _, row in spending.iterrows():
            ok, _reasons, _decision = promo_eligible(row, excluded=data.excluded, margin_pct=data.margin_pct.get(str(row["sku"])), cancel_pct=row.get("batal_pct"))
            held += 0 if ok else 1
    if held:
        lines.append(f"<b>{fmt_num(held)}</b> SKU yang sedang beriklan sebaiknya ditahan (stok kurang, margin, atau batal tinggi).")
    body = "".join(f"<div style='margin:.25rem 0;font-size:var(--fs-sm)'>{line}</div>" for line in lines) or "<div class='field-hint'>Belum ada insight.</div>"
    st.markdown(f"<div class='stat-card'><div class='readable-metric-label'>Insight</div>{body}</div>", unsafe_allow_html=True)
    if role in ("team_dc", "team_icmd"):
        tabs = [label for _slug, label, _menu in setting_tabs(role)]
        st.markdown(
            "<div class='stat-card' style='margin-top:.6rem'><div class='readable-metric-label'>Akses role Anda</div>"
            f"<div style='font-size:var(--fs-sm)'>{html.escape(ROLE_LABELS.get(role, role))}: Ringkasan & Prediksi (lihat), "
            f"Setting › {html.escape(', '.join(tabs))}.</div></div>",
            unsafe_allow_html=True,
        )

