"""Target sales bulanan: unggah di Upload data › Target, dan baris pencapaian untuk kartu sales aktual."""

from __future__ import annotations

import html
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src.core import targets as T
from src.ui.common import download_excel, fmt_idr, fmt_pct

UP = "#1d4ed8"
DOWN = "#dc2626"


def monthly_targets(features) -> dict[str, float]:
    """{"YYYY-MM": target} dari tabel sales_target; hanya target > 0."""
    if features is None:
        return {}
    try:
        frame = features.read("sales_target")
    except Exception:
        return {}
    if frame.empty:
        return {}
    values = pd.to_numeric(frame["target_sales_bersih"], errors="coerce").fillna(0.0)
    return {str(p): float(v) for p, v in zip(frame["periode"], values) if float(v) > 0}


def _tone(pct: float) -> str:
    return UP if pct >= 100 else DOWN


def achievement_line(actual: float, start: date | None, end: date | None, features=None, *, targets: dict | None = None) -> str:
    """Satu baris HTML: target periode, % tercapai (biru ≥ 100%, merah di bawah), dan target bulan penuh."""
    if start is None or end is None:
        return ""
    targets = monthly_targets(features) if targets is None else targets
    result, missing = T.achievement(actual, start, end, targets)
    if result is None:
        names = ", ".join(T.month_label(m) for m in missing[:3]) or "periode ini"
        return f"<span style='color:#94a3b8'>Target {html.escape(names)} belum diunggah (Upload data › Target)</span>"
    pct = f"<b style='color:{_tone(result.pct)}'>{fmt_pct(result.pct, 1)}</b>"
    if result.single_month and not result.full_months:
        month_pct = f"<b style='color:{_tone(result.month_pct)}'>{fmt_pct(result.month_pct, 1)}</b>"
        return (
            f"Pencapaian {month_pct} dari target {T.month_label(result.single_month)} {fmt_idr(result.month_target)} · "
            f"target {result.days}/{result.month_days} hari {fmt_idr(result.target)} → {pct}"
        )
    scope = f"target {T.month_label(result.single_month)}" if result.single_month else "target periode"
    gap = result.actual - result.target
    gap_text = f"lebih {fmt_idr(gap)}" if gap >= 0 else f"kurang {fmt_idr(-gap)}"
    return f"Pencapaian {pct} dari {scope} {fmt_idr(result.target)} · {gap_text}"


def month_outlook(orders: pd.DataFrame | None, features, ref: date | None = None) -> dict:
    """Bulan acuan: sales bersih aktual tgl 1 s.d. hari penuh terakhir + prediksi sisa hari (bulan berjalan), atau aktual penuh (bulan lewat).

    Bulan berjalan memakai perhitungan yang sama dengan Prediksi › Pantauan harian (`month_track_view.month_state`):
    hari data yang belum penuh (< 23:00) ikut dihitung dari prediksi, prediksi per tanggal berpola hari × faktor
    sales bersih ÷ sales produk. Sales bersih = Total Pembayaran − batal − Belum Bayar − retur (sama dengan tab Data & Laporan)."""
    import calendar

    from src.core.metrics import net_sku_sales, normalize_lines, order_metrics

    stamp = pd.NaT
    if orders is not None and not orders.empty:
        stamp = pd.to_datetime(orders["order_time"], errors="coerce").max()
    data_last = stamp.date() if pd.notna(stamp) else date.today()
    running = ref is None or (ref.year, ref.month) == (data_last.year, data_last.month)
    first = data_last.replace(day=1) if running else pd.Timestamp(ref).date().replace(day=1)
    month_days = calendar.monthrange(first.year, first.month)[1]
    if running:
        from src.ui.month_track_view import full_day_cutoff

        cutoff = full_day_cutoff(stamp) if pd.notna(stamp) else data_last
        done = max((cutoff - first).days + 1, 0)  # hari penuh bulan ini (0 bila data tgl 1 belum penuh)
    else:
        done = month_days
    last = first + timedelta(days=max(done, 1) - 1)
    mtd, product, factor = 0.0, 0.0, 1.0
    if orders is not None and not orders.empty and done > 0:
        lines = normalize_lines(orders)
        mtd = float(order_metrics(lines, first, last, normalized=True)["sales_bersih"])
        product = float(net_sku_sales(lines, first, last, normalized=True)["sales"].sum())
        if product > 0 and mtd > 0:
            factor = float(min(max(mtd / product, 0.5), 1.2))
    if not running:
        return {"last": last, "running": False, "mtd": mtd, "mtd_produk": product, "faktor": factor, "rest": 0, "month_days": month_days,
                "pred_daily": 0.0, "projection": mtd, "periode": T.month_key(first)}

    rest = month_days - done
    state = {}
    if pd.notna(stamp):
        try:
            from src.ui.month_track_view import month_state

            state = month_state(features, orders, first)
        except Exception:
            state = {}
    open_days = state["table"].loc[~state["table"]["status_hari"].eq("Selesai")] if state else pd.DataFrame()
    if len(open_days) and open_days["prediksi"].notna().all():
        summary = state["summary"]
        rest, factor = int(summary["sisa_hari"]), float(state["factor"])
        ahead = float(summary["proyeksi"]) - float(summary["mtd"])
        projection = mtd + ahead
        pred_daily = ahead / rest if rest else 0.0
    else:
        # Belum ada snapshot prediksi untuk bulan ini: laju datar analisa terakhir × faktor.
        pred_daily = 0.0
        try:
            from src.ui.gudang_view import latest_prediction

            _q, sales_daily, _at = latest_prediction(features)
            pred_daily = float(sum(sales_daily.values())) * factor if sales_daily else 0.0
        except Exception:
            pred_daily = 0.0
        if pred_daily <= 0 and done:
            pred_daily = mtd / done
        projection = mtd + pred_daily * rest
    return {
        "last": last, "running": True, "mtd": mtd, "mtd_produk": product, "faktor": factor, "rest": rest, "month_days": month_days,
        "pred_daily": pred_daily, "projection": projection, "periode": T.month_key(first),
    }


def saved_plan(features, periode: str) -> dict:
    """Setelan rencana iklan yang disimpan untuk bulan itu (target ROAS, budget sisa, dll.); {} bila belum ada."""
    import json

    try:
        frame = features.read("sales_target", {"periode": periode})
        raw = frame["budget_json"].iloc[0] if not frame.empty else "{}"
        plan = json.loads(raw or "{}")
    except Exception:
        return {}
    return plan if isinstance(plan, dict) else {}


def target_roas_for(features, periode: str) -> float | None:
    """Target ROAS bulan itu dari Rekomendasi › Iklan; bila belum disimpan, bulan terakhir yang punya target ROAS."""
    try:
        frame = features.read("sales_target")
    except Exception:
        return None
    import json

    if frame.empty:
        return None
    for key, raw in sorted(zip(frame["periode"].astype(str), frame["budget_json"]), reverse=True):
        if key > periode:
            continue
        try:
            value = (json.loads(raw or "{}") or {}).get("target_roas")
        except (TypeError, ValueError, AttributeError):
            value = None
        if value:
            return float(value)
    return None


def target_upload_label(features) -> str:
    saved = monthly_targets(features)
    return f"Target sales bulanan · {len(saved)} bulan tersimpan" if saved else "Target sales bulanan · Kosong"


def show_target_uploader(features, *, username: str, today: date, title: bool = True) -> None:
    """Unggah target sales per bulan (Bulan, Target (Rp)); disimpan ke tabel sales_target per bulan."""
    if title:
        st.markdown("**Target sales bulanan**")
    st.caption(
        "Setiap bulan punya target sendiri. Pencapaian sales aktual di Ringkasan, Data, Laporan, Prediksi vs aktual, "
        "Folder data, dan Kalkulator biaya dihitung terhadap target bulan yang sama. Bulan tanpa target ditandai belum diunggah."
    )
    saved = monthly_targets(features)
    if saved:
        view = pd.DataFrame({"Bulan": [T.month_label(k) for k in sorted(saved)], "Target (Rp)": [fmt_idr(saved[k]) for k in sorted(saved)]})
        st.dataframe(view, hide_index=True, width="stretch", height=min(38 + 35 * len(view), 320))
    else:
        st.info("Belum ada target bulanan. Unduh template, isi target per bulan, lalu unggah.")
    left, right = st.columns([1, 2])
    with left:
        download_excel(T.template_frame(today, saved), "template_target_bulanan.xlsx", key="tgt-template", label="Unduh template")
        st.caption("Template berisi Januari tahun ini s.d. Desember tahun depan; target tersimpan sudah terisi. Isi bulan yang perlu, kosongkan yang tidak berubah.")
    flash = st.session_state.pop("tgt-flash", None)
    if flash:
        st.success(flash)
    round_no = int(st.session_state.get("tgt-upload-round", 0))
    upload = right.file_uploader("Unggah target bulanan (xlsx/csv)", type=["xlsx", "xls", "csv"], key=f"tgt-upload-{round_no}")
    if upload is None:
        return
    try:
        raw = pd.read_csv(upload, dtype=object) if upload.name.lower().endswith(".csv") else pd.read_excel(upload, dtype=object)
        parsed = T.parse_target_file(raw)
    except Exception as exc:  # noqa: BLE001
        st.error(f"File target tidak bisa dibaca: {exc}")
        return
    preview = pd.DataFrame({
        "Bulan": parsed["periode"].map(T.month_label),
        "Target baru (Rp)": parsed["target"].map(fmt_idr),
        "Target lama (Rp)": parsed["periode"].map(lambda k: fmt_idr(saved[k]) if k in saved else "–"),
    })
    st.markdown(f"Terbaca **{len(parsed)} bulan**. Bulan yang sama akan diganti.")
    st.dataframe(preview, hide_index=True, width="stretch")
    if st.button("Simpan target bulanan", type="primary", key="tgt-upload-save"):
        from auth.ui import require

        require("rekomendasi", "edit")
        existing = features.read("sales_target")
        keep = {str(r["periode"]): r for r in existing.to_dict("records")} if not existing.empty else {}
        rows = []
        for item in parsed.to_dict("records"):
            old = keep.get(item["periode"], {})
            rows.append({
                "periode": item["periode"], "target_sales_bersih": float(item["target"]),
                "margin_min_pct": float(old.get("margin_min_pct", 0) or 0), "strategi": old.get("strategi", "") or "",
                "budget_json": old.get("budget_json", "{}") or "{}", "set_by": username,
            })
        features.replace("sales_target", rows, keys=["periode"], username=username, action="unggah:target_bulanan")
        from src.ui.feature_data import bump

        bump(st.session_state)
        st.session_state["tgt-upload-round"] = round_no + 1
        st.session_state["tgt-flash"] = (
            f"✓ {len(rows)} target bulanan tersimpan: " + ", ".join(T.month_label(r["periode"]) for r in rows[:12]) + ("…" if len(rows) > 12 else "") + "."
        )
        st.rerun()
