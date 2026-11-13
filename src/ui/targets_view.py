"""Target sales bulanan: unggah di Upload data › Target, dan baris pencapaian untuk kartu sales aktual."""

from __future__ import annotations

import html
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src.core import targets as T
from src.core.fmt import fmt_date
from src.ui.common import download_excel, file_check, fmt_idr, fmt_pct, mark_upload_done, set_upload_notice, show_upload_notice

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


def achievement_line(actual: float, start: date | None, end: date | None, features=None, *, targets: dict | None = None,
                     orders: pd.DataFrame | None = None) -> str:
    """Satu baris HTML: target periode, % tercapai (biru ≥ 100%, merah di bawah), dan target bulan penuh.

    Dengan `orders`, aturannya sama dengan Pantauan harian: target dibagi per tanggal menurut pola hari, dan bila
    rentang memuat hari data yang belum penuh (< 23:00), pencapaian dinilai s.d. hari penuh terakhir."""
    if start is None or end is None:
        return ""
    targets = monthly_targets(features) if targets is None else targets
    weight, cutoff = (None, None)
    if orders is not None and not orders.empty:
        from src.ui.month_track_view import target_pattern

        weight, cutoff = target_pattern(orders)
    upto = ""
    if cutoff is not None and start <= cutoff < end:
        from src.core.metrics import order_metrics

        actual = float(order_metrics(orders, start, cutoff)["sales_bersih"])
        upto = (f" · sales bersih {fmt_date(start)} – {fmt_date(cutoff)} {fmt_idr(actual)} "
                f"(hari penuh terakhir; {fmt_date(cutoff + timedelta(days=1))} belum penuh, tidak dihitung) =")
        end = cutoff
    elif cutoff is not None and end > cutoff:
        return ""
    result, missing = T.achievement(actual, start, end, targets, weight)
    if result is None:
        names = ", ".join(T.month_label(m) for m in missing[:3]) or "periode ini"
        return f"<span style='color:#94a3b8'>Target {html.escape(names)} belum diunggah (Upload data › Target)</span>"
    pct = f"<b style='color:{_tone(result.pct)}'>{fmt_pct(result.pct, 1)}</b>"
    if result.single_month and not result.full_months:
        month_pct = f"<b style='color:{_tone(result.month_pct)}'>{fmt_pct(result.month_pct, 1)}</b>"
        basis = "target berjalan (pola hari)" if weight is not None else f"target {result.days}/{result.month_days} hari"
        if upto:
            basis += f" s.d. {fmt_date(end)}"
        return (
            f"Pencapaian{upto} {month_pct} dari target {T.month_label(result.single_month)} {fmt_idr(result.month_target)} · "
            f"{basis} {fmt_idr(result.target)} → {pct}"
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
    """Target ROAS bulan itu dari Rekomendasi › Iklan; bila belum disimpan, bulan sebelumnya terdekat yang punya target ROAS,
    lalu bulan sesudahnya terdekat (satu acuan untuk Laporan dan Iklan, bukan parameter lama)."""
    try:
        frame = features.read("sales_target")
    except Exception:
        return None
    import json

    if frame.empty:
        return None
    saved = {}
    for key, raw in zip(frame["periode"].astype(str), frame["budget_json"]):
        try:
            value = (json.loads(raw or "{}") or {}).get("target_roas")
        except (TypeError, ValueError, AttributeError):
            value = None
        if value:
            saved[key] = float(value)
    before = [k for k in saved if k <= periode]
    if before:
        return saved[max(before)]
    after = [k for k in saved if k > periode]
    return saved[min(after)] if after else None


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
    show_upload_notice("target")
    tab_edit, tab_upload = st.tabs(["Lihat & koreksi target", "Unggah file target"])
    with tab_edit:
        _target_editor(features, saved, username=username)
    with tab_upload:
        _target_upload(features, saved, username=username, today=today)


ACTION_LABELS = {"Baru": "Baru", "Diubah": "Diubah", "Tetap": "Tidak berubah", "Dihapus": "Dihapus"}


def _summary_text(changes: pd.DataFrame) -> str:
    parts = []
    for action, verb in (("Baru", "ditambah"), ("Diubah", "diubah"), ("Dihapus", "dihapus")):
        months = changes.loc[changes["aksi"] == action, "periode"].map(T.month_label).tolist()
        if months:
            parts.append(f"{len(months)} bulan {verb} ({', '.join(months[:12])}{'…' if len(months) > 12 else ''})")
    return "; ".join(parts)


def _save_changes(features, changes: pd.DataFrame, *, username: str, action: str) -> None:
    """Simpan bulan Baru/Diubah/Dihapus. Dihapus = target 0, sehingga setelan iklan bulan itu tetap tersimpan."""
    from auth.ui import require

    require("rekomendasi", "edit")
    todo = changes.loc[changes["aksi"].isin(["Baru", "Diubah", "Dihapus"])]
    if todo.empty:
        set_upload_notice("target", True, "Tidak ada perubahan target; target tersimpan tetap sama.")
        st.rerun()
    try:
        existing = features.read("sales_target")
        keep = {str(r["periode"]): r for r in existing.to_dict("records")} if not existing.empty else {}
        rows = []
        for item in todo.to_dict("records"):
            old = keep.get(item["periode"], {})
            rows.append({
                "periode": item["periode"], "target_sales_bersih": float(item["baru"]) if item["aksi"] != "Dihapus" else 0.0,
                "margin_min_pct": float(old.get("margin_min_pct", 0) or 0), "strategi": old.get("strategi", "") or "",
                "budget_json": old.get("budget_json", "{}") or "{}", "set_by": username,
            })
        features.replace("sales_target", rows, keys=["periode"], username=username, action=action)
    except Exception as exc:  # noqa: BLE001 - gagal simpan ditampilkan, app tidak berhenti
        set_upload_notice("target", False, f"Target bulanan gagal disimpan: {exc}")
    else:
        from src.ui.feature_data import bump

        bump(st.session_state)
        mark_upload_done("sales_target")
        remaining = len(changes) - int((changes["aksi"] == "Dihapus").sum())
        set_upload_notice("target", True, f"Target bulanan tersimpan: {_summary_text(changes)}. Sekarang {remaining} bulan bertarget.")
    for key in ("tgt-upload-round", "tgt-edit-round"):
        st.session_state[key] = int(st.session_state.get(key, 0)) + 1
    st.rerun()


def _target_editor(features, saved: dict[str, float], *, username: str) -> None:
    st.caption(
        "Ubah angka langsung di tabel. Centang **Hapus** untuk membuang target bulan yang salah, atau tambah baris baru di bawah "
        "(Bulan seperti Jan 2027 atau 2027-01). Tekan **Simpan koreksi** setelah selesai."
    )
    round_no = int(st.session_state.get("tgt-edit-round", 0))
    base = pd.DataFrame({
        "Bulan": [T.month_label(k) for k in sorted(saved)],
        "Target (Rp)": [float(saved[k]) for k in sorted(saved)],
        "Hapus": [False] * len(saved),
    })
    edited = st.data_editor(
        base, hide_index=True, width="stretch", num_rows="dynamic", key=f"tgt-editor-{round_no}",
        column_config={
            "Bulan": st.column_config.TextColumn(required=True, help="mis. Nov 2026 atau 2026-11"),
            "Target (Rp)": st.column_config.NumberColumn(min_value=0, step=1_000_000, format="localized", help="Target sales bersih bulan itu"),
            "Hapus": st.column_config.CheckboxColumn(help="Centang untuk menghapus target bulan ini"),
        },
    )
    new: dict[str, float] = {}
    bad: list[str] = []
    for row in edited.to_dict("records"):
        text = str(row.get("Bulan") or "").strip()
        if not text:
            continue
        key = T.parse_month(text)
        if key is None:
            bad.append(text)
            continue
        value = pd.to_numeric(row.get("Target (Rp)"), errors="coerce")
        if bool(row.get("Hapus")) or pd.isna(value) or float(value) <= 0:
            continue
        new[key] = float(value)
    if bad:
        st.error(f"Bulan tidak dikenali: {', '.join(bad[:5])}. Tulis seperti Nov 2026 atau 2026-11.")
        return
    changes = T.plan_changes(saved, new, replace_all=True)
    summary = _summary_text(changes)
    if summary:
        st.info(f"Belum disimpan: {summary}.")
    if st.button("Simpan koreksi", type="primary", key=f"tgt-edit-save-{round_no}", disabled=not summary):
        _save_changes(features, changes, username=username, action="koreksi:target_bulanan")


def _target_upload(features, saved: dict[str, float], *, username: str, today: date) -> None:
    left, right = st.columns([1, 2])
    with left:
        download_excel(T.template_frame(today, saved), "template_target_bulanan.xlsx", key="tgt-template", label="Unduh template")
        st.caption("Template berisi Januari tahun ini s.d. Desember tahun depan; target tersimpan sudah terisi.")
    round_no = int(st.session_state.get("tgt-upload-round", 0))
    upload = right.file_uploader("Unggah target bulanan (xlsx/csv)", type=["xlsx", "xls", "csv"], key=f"tgt-upload-{round_no}")
    if upload is None:
        return
    try:
        raw = pd.read_csv(upload, dtype=object) if upload.name.lower().endswith(".csv") else pd.read_excel(upload, dtype=object)
        parsed = T.parse_target_file(raw)
    except Exception as exc:  # noqa: BLE001
        file_check(False, f"{upload.name} tidak bisa dibaca sebagai target bulanan: {exc}")
        return
    if parsed.empty:
        file_check(False, f"{upload.name}: tidak ada bulan yang berisi target. Isi kolom Target (Rp) pada template.")
        return
    file_check(True, f"{upload.name}: {len(parsed)} bulan berisi target.")
    modes = ["Ganti semua target dengan isi file", "Perbarui hanya bulan yang ada di file"]
    mode = st.radio(
        "Cara menyimpan", modes, key=f"tgt-upload-mode-{round_no}", horizontal=True,
        help="Ganti semua: bulan tersimpan yang tidak ada (atau kosong) di file dihapus. Perbarui: bulan lain tetap tersimpan.",
    )
    changes = T.plan_changes(saved, dict(zip(parsed["periode"], parsed["target"])), replace_all=mode == modes[0])
    preview = pd.DataFrame({
        "Bulan": changes["periode"].map(T.month_label),
        "Target lama (Rp)": changes["lama"].map(lambda v: fmt_idr(v) if v is not None and pd.notna(v) else "–"),
        "Target baru (Rp)": changes["baru"].map(lambda v: fmt_idr(v) if v is not None and pd.notna(v) else "–"),
        "Perubahan": changes["aksi"].map(ACTION_LABELS),
    })
    removed = int((changes["aksi"] == "Dihapus").sum())
    st.markdown(f"Setelah disimpan: **{len(changes) - removed} bulan bertarget**" + (f", **{removed} bulan dihapus**." if removed else "."))
    st.dataframe(preview, hide_index=True, width="stretch", height=min(38 + 35 * len(preview), 420))
    if st.button("Simpan target bulanan", type="primary", key=f"tgt-upload-save-{round_no}"):
        _save_changes(features, changes, username=username, action="unggah:target_bulanan")
