"""Tab Laporan: laporan per rentang tanggal (kalender), bisa disimpan lalu dibuka lagi tanpa menganalisa ulang.

Alur: pilih rentang → laporan dihitung dari data transaksi, iklan, performa toko, campaign tersimpan, margin (Kalkulator),
gudang 10037, ranking kompetitor, evaluasi model, dan hasil analisa aktif → (opsional) simpan dengan nama. Laporan
tersimpan berisi snapshot angka/tabel/grafik (src/core/report_data.py), jadi dibuka lagi persis sama.

Istilah angka (sama di semua menu):
- Sales bersih        = Total Pembayaran per pesanan − batal − Belum Bayar − retur (dasar target; kartu Ringkasan & Data)
- Sales produk bersih = Harga setelah diskon × QTY bersih (nilai barang sebelum voucher Shopee; dasar margin, iklan, produk)
- QTY bersih          = unit terjual tanpa batal & Belum Bayar, dikurangi unit retur
Jembatan keduanya: Sales produk bersih − voucher penjual − voucher Shopee/koin/kartu + ongkir dibayar pembeli ± lain-lain.
"""

from __future__ import annotations

import html
from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.core import report_analysis as RA
from src.core import report_data as R
from src.core import targets as T
from src.core.ads import ad_validation
from src.core.cancel_reasons import CATEGORIES, categorize_series, short_reason
from src.core.decision_table import PERIOD_LABELS, stock_shortage
from src.core.expert_system import FISHBONE_CATEGORIES, evaluate_rules, sku_facts, work_guide
from src.core.metrics import BRIDGE_PARTS, ads_metrics, sales_bridge
from src.core.optimization import monte_carlo_stock_scenarios
from src.core.periods import format_period_label, last_full_month
from src.core.preprocessing import promo_flag
from src.core.restock import recommendation_records, records_display
from src.ui.common import (cached_order_metrics, card, date_range_picker, download_excel, explain, fmt_date, fmt_idr, fmt_idr_short, fmt_num,
                           fmt_pct, fmt_qty, html_table, metric_card, range_label, status_key)
from src.ui.report_visuals import fishbone_legend, fishbone_svg, swot_html
from src.ui.targets_view import monthly_targets, target_roas_for

UP, DOWN = "#1d4ed8", "#dc2626"
ALL_SECTIONS = "Semua bagian (dibaca berurutan / dicetak)"
SECTIONS = (
    "1. Ringkasan eksekutif",
    "2. Target & tren penjualan",
    "3. Produk terlaris",
    "4. Margin & profitabilitas",
    "5. Prediksi & stok",
    "6. Akurasi model prediksi",
    "7. Gudang 10037 & outstanding",
    "8. Iklan",
    "9. Campaign & kegiatan",
    "10. Performa toko",
    "11. Ranking kompetitor",
    "12. Transaksi, batal & retur",
    "13. Analisa SWOT",
    "14. Analisa fishbone",
    "15. Rekomendasi",
    "16. Panduan kerja",
)
LIVE, SAVED = "Buat laporan", "Laporan tersimpan"
OLD = "Bagian ini belum ada pada laporan tersimpan versi lama. Buat laporan baru untuk periode yang sama agar terisi."
TERMS = [("Sales bersih", "Total Pembayaran per pesanan − batal − Belum Bayar − retur (sudah dipotong voucher; dasar target, sama dengan kartu Ringkasan & tab Data)"),
         ("Sales produk bersih", "Harga setelah diskon × QTY bersih (nilai barang sebelum voucher Shopee/koin; dasar margin, produk terlaris, porsi iklan)"),
         ("QTY bersih", "unit terjual tanpa batal & Belum Bayar, dikurangi unit retur"),
         ("Pesanan bersih", "pesanan selain batal & Belum Bayar")]


def _chip(text: str) -> str:
    return ("<span style='display:inline-block;margin:2px 6px 2px 0;padding:3px 10px;border-radius:999px;"
            f"background:#f1f5f9;color:#334155;font-size:var(--fs-xs);font-weight:600'>{html.escape(text)}</span>")


def _signed_pct(value) -> str:
    if value is None or not np.isfinite(value):
        return "–"
    return f"<b style='color:{UP if value >= 0 else DOWN}'>{fmt_pct(value, 1, signed=True)}</b>"


def _change(now, then) -> float:
    try:
        now, then = float(now), float(then)
    except (TypeError, ValueError):
        return float("nan")
    return (now - then) / then * 100 if np.isfinite(then) and then > 0 and np.isfinite(now) else float("nan")


def _plot(fig: go.Figure, key: str, height: int = 380) -> None:
    fig.update_layout(height=height, separators=",.", margin=dict(l=40, r=20, t=40, b=40), template="plotly_white", legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, use_container_width=True, key=key)


def _sub(text: str) -> None:
    st.markdown(f"<div style='font-weight:800;margin:.8rem 0 .35rem'>{html.escape(text)}</div>", unsafe_allow_html=True)


def _box(title: str, items: list[str], tone: str = "#ee4d2d", ordered: bool = False) -> str:
    tag = "ol" if ordered else "ul"
    body = "".join(f"<li>{t}</li>" for t in items) or "<li>–</li>"
    return (f"<div style='border:1px solid #e2e8f0;border-left:5px solid {tone};border-radius:12px;background:#fff;padding:.6rem 1rem;margin:.4rem 0 .7rem;"
            f"font-size:var(--fs-base);line-height:1.55;break-inside:avoid'><b>{html.escape(title)}</b><{tag} style='margin:.3rem 0 0 1.1rem;padding:0'>{body}</{tag}></div>")


def _frame(value) -> pd.DataFrame:
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _cancel_mask(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty or "status" not in frame.columns:
        return pd.Series(False, index=frame.index if frame is not None else [])
    from src.ingest import cancelled_status_mask

    return cancelled_status_mask(frame["status"])


def _cancel_reasons(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty or "cancel_reason" not in frame.columns:
        return pd.DataFrame(columns=["reason", "orders", "kategori"])
    part = frame.loc[_cancel_mask(frame)]
    if part.empty:
        return pd.DataFrame(columns=["reason", "orders", "kategori"])
    reason = part["cancel_reason"].fillna("").astype(str).str.strip().replace("", "Tanpa alasan")
    key = part["order_id"] if "order_id" in part.columns else part.index.to_series()
    out = pd.DataFrame({"reason": reason, "key": key}).drop_duplicates().groupby("reason").size().rename("orders").reset_index()
    out["kategori"] = categorize_series(out["reason"])
    out["reason"] = out["reason"].map(short_reason)
    out = out.groupby(["reason", "kategori"], as_index=False)["orders"].sum()
    return out.sort_values("orders", ascending=False).reset_index(drop=True)


def _top_advices(table: pd.DataFrame, today: date, limit: int = 8) -> pd.DataFrame:
    rows = []
    for _, row in table.head(50).iterrows():
        facts = sku_facts(row, today=today)
        short = facts.get("status_stok") in {"Kosong", "Kurang"}
        for advice in evaluate_rules(facts):
            if short and advice.action == "iklan" and advice.rule_id != "iklan_boros":
                continue
            rows.append({"Prioritas": advice.priority, "SKU": row["sku"], "Produk": row["product_name"], "Aksi": advice.action, "Rekomendasi": advice.text})
            break
    frame = pd.DataFrame(rows, columns=["Prioritas", "SKU", "Produk", "Aksi", "Rekomendasi"])
    return frame.sort_values(["Prioritas", "SKU"]).head(limit).reset_index(drop=True)


def _records(table: pd.DataFrame, today: date, data) -> pd.DataFrame:
    if table is None or table.empty:
        return pd.DataFrame()
    advice = {}
    adv = _top_advices(table, today, limit=50)
    for sku, text in zip(adv["SKU"].astype(str), adv["Rekomendasi"]):
        advice.setdefault(sku, str(text))
    return recommendation_records(table.head(50), today, po=getattr(data, "po", None), margin_pct=getattr(data, "margin_pct", None), advice=advice)


def _print_button() -> None:
    import streamlit.components.v1 as components

    components.html(
        "<button onclick='window.parent.print()' style='width:100%;padding:.5rem .75rem;border-radius:10px;"
        "border:1px solid #ee4d2d;background:#fff;color:#ee4d2d;font:600 14px sans-serif;cursor:pointer'>Cetak / Simpan PDF</button>",
        height=48,
    )
    st.caption("Di dialog cetak, pilih \"Simpan sebagai PDF\".")


# ---------------------------------------------------------------- bagian tambahan snapshot

def _bridge_frame(bridge: dict) -> pd.DataFrame:
    """Jembatan Sales produk bersih → Sales bersih (satu sumber dengan Kalkulator margin)."""
    notes = {"seller_voucher": "dibayar penjual", "shopee_side": "ditanggung Shopee; pembeli membayar lebih sedikit",
             "buyer_shipping": "ikut di Total Pembayaran"}
    rows = [{"Komponen": "Sales produk bersih", "Nilai": bridge["sales_produk"], "Keterangan": "Harga setelah diskon × QTY bersih"}]
    for key, label in BRIDGE_PARTS:
        sign = 1 if key == "buyer_shipping" else -1
        rows.append({"Komponen": ("+ " if sign > 0 else "− ") + label, "Nilai": sign * bridge[key], "Keterangan": notes.get(key, "")})
    rows.append({"Komponen": "± Lain-lain", "Nilai": bridge["lain"], "Keterangan": "biaya layanan, pembulatan, retur sebagian"})
    rows.append({"Komponen": "= Sales bersih", "Nilai": bridge["sales_bersih"], "Keterangan": "Total Pembayaran − retur (angka kartu Ringkasan)"})
    return pd.DataFrame(rows)


def _model_part(outcome, repo, params: dict) -> dict:
    """Akurasi model dari evaluasi walk-forward analisa aktif (sama dengan Evaluasi model › Ringkasan)."""
    from src.core import model_history as H
    from src.models.evaluate import HORIZON_LABELS, HORIZONS, ss_method
    from src.ui.evaluasi import _diagnosis, _fold_frame

    records = getattr(outcome, "eval_records", None) or (st.session_state.get("analysis") or {}).get("eval") or {}
    record = records.get("bulan") or next((r for r in records.values() if isinstance(r, dict) and r.get("models")), None)
    if not record or not record.get("models"):
        return {}
    history = pd.DataFrame()
    root = getattr(repo, "runs_root", None)
    if root is not None:
        try:
            db_runs = {}
            for rec in repo.list_runs(500):
                db_runs[str(repo.folder_of(rec).resolve())] = {"id": rec.id, "run_by": rec.run_by}
            history, _long = H.history_frame(root, db_runs)
        except Exception:
            history = pd.DataFrame()
    checks = H.method_checks(record, history if not history.empty else None, ss_method=ss_method(params))
    chosen = record.get("model_produksi") or record.get("best_model") or ""
    oos = (record.get("luar_sampel") or {}).get("models") or {}
    rows = []
    for key, info in record["models"].items():
        o = oos.get(key) or {}
        rows.append({"Model": info.get("label", key), "Peran": "✅ Produksi" if key == chosen else "Pembanding",
                     "WAPE luar sampel (%)": o.get("wape"), "MAPE agregat luar sampel (%)": o.get("mape_agregat"), "Bias luar sampel (%)": o.get("bias"),
                     "WAPE lipatan uji (%)": info.get("wape"), "MAPE agregat lipatan uji (%)": info.get("mape_agregat"), "Top 50 tepat": info.get("top50_tepat")})
    models = pd.DataFrame(rows)
    if not models.empty:
        models = models.assign(_o=pd.to_numeric(models["WAPE luar sampel (%)"], errors="coerce").fillna(
            pd.to_numeric(models["WAPE lipatan uji (%)"], errors="coerce"))).sort_values("_o").drop(columns="_o").reset_index(drop=True)
    best, best_oos = record["models"].get(chosen, {}), oos.get(chosen, {})
    strengths, weaknesses, actions = _diagnosis(record, checks)
    sim = record.get("simulasi_ss") or {}
    folds = [f for f in record.get("per_lipatan") or [] if f.get("perubahan_pct") is not None]
    last_fold = folds[-1] if folds else {}
    return {
        "model": best.get("label", chosen), "n_sku": record.get("n_sku"), "lipatan": len(record.get("fold_dates") or []),
        "horizon": HORIZON_LABELS.get(record.get("horizon"), ""),
        # Sama dengan kartu Evaluasi model › Ringkasan dan uji kesesuaian: MAPE & WAPE lipatan uji (luar sampel di keterangan), bias luar sampel.
        "mape": best.get("mape_agregat"), "wape": best.get("wape"), "mape_oos": best_oos.get("mape_agregat"), "wape_oos": best_oos.get("wape"),
        "bias": best_oos.get("bias", best.get("bias")), "top50": best.get("top50_tepat"),
        "layanan": sim.get("tingkat_layanan_pct"), "layanan_target": sim.get("target_layanan_pct"),
        "lulus": int(checks["Status"].astype(str).str.startswith("✅").sum()) if not checks.empty else 0, "uji": len(checks),
        "permintaan_terakhir": last_fold.get("perubahan_pct"),
        "bulan_terakhir": pd.Timestamp(last_fold["tanggal"]).strftime("%b %Y") if last_fold.get("tanggal") else "",
        "models": models, "checks": checks, "folds": _fold_frame(record),
        "kesimpulan": [f"{HORIZON_LABELS[h]}: {records[h]['kesimpulan']}" for h in HORIZONS if (records.get(h) or {}).get("kesimpulan")],
        "kekuatan": strengths, "kelemahan": weaknesses, "tindak": actions,
    }


def _gudang_part(features, table, orders_all) -> dict:
    """Ringkasan Gudang 10037: status stok, outstanding PO/TR/TO beserta umur & follow up (sama dengan menu Gudang)."""
    from src.ui import gudang_view as GV

    view = GV.cached_view(features, table, orders_all)
    items = (view or {}).get("items")
    if not isinstance(items, pd.DataFrame) or items.empty:
        return {}
    age = GV._outstanding_age(features)
    follow = [GV._follow_up(r, age) for r in items.itertuples(index=False)]
    texts = pd.Series([f[1] for f in follow], index=items.index)
    stale = texts.str.contains(f"lewat {GV.STALE_DAYS} hari")
    no_os = texts.str.startswith("Belum ada outstanding")
    has_os = pd.to_numeric(items["di_jalan"], errors="coerce").fillna(0) > 0
    counts = items["status"].value_counts().to_dict()
    order = {"Kosong": 0, "Hampir habis": 1, "Stok berlebih": 2, "Aman": 3}
    urgent = items.assign(_f=texts, _a=[f[0] for f in follow], _o=items["status"].map(order).fillna(9))
    urgent = urgent.loc[urgent["status"].isin(["Kosong", "Hampir habis"]) | stale].sort_values(["_o", "dampak_omzet"], ascending=[True, False])
    frame = pd.DataFrame({
        "Status": urgent["status"].map(lambda v: GV.STATUS_ICON.get(v, v)), "SKU": urgent["sku"], "Nama": urgent["nama"],
        "Stok 10037": urgent["stok"], "Max": urgent["max_stock"], "Outstanding": urgent["di_jalan"], "Umur outstanding": urgent["_a"],
        "Follow up": urgent["_f"], "Saran tindakan": urgent["saran"]}).head(25).reset_index(drop=True)
    snap = view.get("snapshot")
    return {"sku": int(len(items)), "kosong": int(counts.get("Kosong", 0)), "hampir": int(counts.get("Hampir habis", 0)),
            "berlebih": int(counts.get("Stok berlebih", 0)), "aman": int(counts.get("Aman", 0)),
            "os_sku": int(has_os.sum()), "os_unit": float(pd.to_numeric(items["di_jalan"], errors="coerce").fillna(0).sum()),
            "os_lama": int(stale.sum()), "tanpa_os": int(no_os.sum()),
            "snapshot": pd.Timestamp(snap).strftime("%d/%m/%Y") if snap is not None and pd.notna(pd.to_datetime(snap, errors="coerce")) else "",
            "batas_hari": GV.STALE_DAYS, "tabel": frame}


def _ranking_part(features, start: date, end: date) -> dict:
    """Ranking kompetitor: periode tersimpan yang paling cocok dengan rentang laporan (sama dengan Rekomendasi › Ranking kategori)."""
    from src.core import ranking_kpi as K
    from src.ui import ranking_kpi_ui as RU

    rows = RU.load_all(features)
    if rows is None or rows.empty:
        return {}
    master, available = RU.load_master(features), RU.periods(features)
    if not available:
        return {}
    months = {(p.year, p.month) for p in pd.period_range(start, end, freq="M")}
    overlap = [p for p in available if months & set(K.months_of(p))]
    pick = sorted(overlap or available, key=lambda p: (K.end_key(p)[0], K.end_key(p)[1], -K.LEVELS.index(K.level_of(p))))[-1]
    summary = K.list_summary(rows)
    bases = [b for b in (K.ANY_BASIS, *K.BASES) if b in set(summary["dasar"])]
    if not bases:
        return {}
    dasar = bases[0]
    level, year = K.level_of(pick), int(str(pick)[:4])
    _wide, long = K.recap(summary, master, level, year, dasar)
    label = K.short_label(pick)
    part = long.loc[long["Periode"] == label].copy()
    if part.empty:
        return {}
    status = part["Status"].value_counts().to_dict()
    prev = K.previous_period(pick, available)
    up = down = 0
    if prev:
        for g, k, now in zip(part["Grup"], part["Kategori"], part.get("Peringkat", pd.Series(np.nan, index=part.index))):
            before = K.value_for(summary, prev, g, k, dasar).get("peringkat", np.nan)
            if now == now and before == before and now != before:
                up, down = (up + 1, down) if now < before else (up, down + 1)
    icon = {"Sudah Top 10": "🟦", "Dekat": "🟩", "Menengah": "🟧", "Jauh": "🟥", K.NOT_LISTED: "⬜", K.NO_DATA: "⬜"}
    order = {s: i for i, s in enumerate(K.STATUS_ORDER)}
    groups = {g: i for i, g in enumerate(K.GROUPS)}
    part = part.assign(_g=part["Grup"].map(groups).fillna(9), _o=part["Status"].map(order).fillna(9),
                       _p=pd.to_numeric(part.get("Peringkat"), errors="coerce").fillna(1e9))
    part = part.sort_values(["_g", "_o", "_p"])
    keep = [c for c in ("Grup", "Kategori", "Status", "Peringkat", "Produk kita", "Di Top 10", "Produk terbaik", "Toko #1",
                        "Sales kita", "Sales #10", "Qty kita", "Qty #10", "Views kita", "Views #10") if c in part.columns]
    table = part[keep].copy()
    table["Status"] = [f"{icon.get(s, '')} {s}".strip() for s in table["Status"]]
    table = table.drop(columns=[c for c in table.columns if c.endswith(" kita") or c.endswith(" #10")
                                if pd.to_numeric(table[c], errors="coerce").isna().all()])
    near = part.loc[part["Status"] == "Dekat"].sort_values("_p")
    shop = part.loc[part["Toko #1"].astype(str).str.strip().ne("") & part["Status"].ne(K.NO_DATA), "Toko #1"] if "Toko #1" in part.columns else pd.Series(dtype=str)
    return {"periode": label, "periode_lengkap": K.period_label(pick), "pembanding": K.short_label(prev) if prev else "", "dasar": dasar,
            "cocok": bool(overlap), "kategori": int(len(part)), "top10": int(status.get("Sudah Top 10", 0)), "dekat": int(status.get("Dekat", 0)),
            "menengah": int(status.get("Menengah", 0)), "jauh": int(status.get("Jauh", 0)),
            "tanpa_produk": int(status.get(K.NOT_LISTED, 0)), "tanpa_data": int(status.get(K.NO_DATA, 0)), "naik": up, "turun": down,
            "dekat_nama": ", ".join(f"{k} #{int(r)}" for k, r in zip(near["Kategori"].head(3), near["_p"].head(3))),
            "toko_1": shop.value_counts().index[0] if not shop.empty else "",
            "catatan": K.insights(summary, master, pick, dasar, available), "tabel": table.reset_index(drop=True)}


def _safe(name: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — satu bagian gagal tidak boleh menggagalkan seluruh laporan
        return {"_galat": f"{name}: {exc}"}


# ---------------------------------------------------------------- menyusun snapshot

def build_snapshot(table, *, orders, orders_all, frames, params, today, period, metric, service, exclude, window_start, window_end, stock,
                   features, data, run_id: int, start: date, end: date, outcome=None, repo=None) -> dict:
    """Semua angka/tabel laporan untuk rentang [start, end]."""
    span = (end - start).days + 1
    prev = R.previous_range(start, end)
    data_until = pd.to_datetime(orders_all["order_time"]).max().date() if isinstance(orders_all, pd.DataFrame) and not orders_all.empty else None
    month_targets = monthly_targets(features)
    facts = cached_order_metrics(orders_all, start, end, exclude)
    prev_facts = cached_order_metrics(orders_all, prev[0], prev[1], exclude)
    bridge = sales_bridge(orders_all, start, end)
    prev_bridge = sales_bridge(orders_all, prev[0], prev[1])
    sales_now = float(facts["sales_bersih"])
    has_prev = prev_facts["pesanan_semua"] > 0
    sales_prev = float(prev_facts["sales_bersih"]) if has_prev else float("nan")
    growth = _change(sales_now, sales_prev)
    from src.ui.month_track_view import target_pattern

    weight, _cutoff = target_pattern(orders_all if isinstance(orders_all, pd.DataFrame) else None)
    reach, _missing = T.achievement(sales_now, start, end, month_targets, weight)
    roas_goal = (target_roas_for(features, f"{end.year:04d}-{end.month:02d}") if features is not None else None) or params.get("iklan", {}).get("target_roas", 8)

    daily = R.daily_orders(orders_all, start, end)
    month_lo = (pd.Timestamp(end) - pd.DateOffset(months=5)).replace(day=1).date()
    long_daily = R.daily_orders(orders_all, month_lo, end).assign(_m=lambda d: pd.to_datetime(d["Tanggal"]).dt.to_period("M"))
    months = []
    for stamp in pd.period_range(month_lo, end, freq="M"):
        a, b = max(stamp.start_time.date(), month_lo), min(stamp.end_time.date(), end)
        if data_until is not None and a > (_cutoff or data_until):
            continue
        b = min(b, _cutoff or data_until or b)
        m = cached_order_metrics(orders_all, a, b, exclude)
        key = str(stamp)
        seg = long_daily.loc[pd.to_datetime(long_daily["Tanggal"]).between(pd.Timestamp(a), pd.Timestamp(b))]
        # Bulan sebagian dinilai terhadap target prorata hari yang sama (sama dengan kartu Sales bersih).
        part, _miss = T.achievement(float(m["sales_bersih"]), a, b, month_targets, weight)
        months.append({"Bulan": T.month_label(key), "Kunci": key, "Sales produk bersih": float(seg["Sales produk bersih"].sum()),
                       "Sales bersih": float(m["sales_bersih"]), "QTY bersih": float(m["qty_bersih"]), "Pesanan bersih": float(m["pesanan_bersih"]),
                       "Target": float(month_targets.get(key, 0) or 0), "Sebagian": bool(b < stamp.end_time.date()),
                       "Target s.d. data": float(part.target) if part is not None else np.nan,
                       "Pencapaian (%)": float(part.pct) if part is not None else np.nan})
    monthly = pd.DataFrame(months)

    top_all = R.top_products(orders_all, start, end, prev, limit=100_000)
    top = top_all.head(30).reset_index(drop=True)

    ads = ads_metrics(frames.ads, frames.stock, orders_all, pd.Timestamp(start), pd.Timestamp(end))
    ad_result = ads["result"]
    warnings, notes = ad_validation(ad_result, float(ads["sales_produk_bersih"]))
    per_sku = pd.DataFrame()
    if ads["biaya_iklan"] > 0 and getattr(ad_result, "per_sku", None) is not None and not ad_result.per_sku.empty:
        names = orders_all.drop_duplicates("sku").set_index("sku")["product_name"] if orders_all is not None and not orders_all.empty else pd.Series(dtype=str)
        per_sku = ad_result.per_sku.loc[ad_result.per_sku["biaya_iklan"] > 0, ["sku", "biaya_iklan", "omzet_iklan"]].copy()
        per_sku["Produk"] = per_sku["sku"].map(names).fillna("")
        per_sku["ROAS"] = per_sku["omzet_iklan"] / per_sku["biaya_iklan"]
        per_sku = per_sku.sort_values("biaya_iklan", ascending=False).head(20).rename(columns={"sku": "SKU", "biaya_iklan": "Biaya", "omzet_iklan": "Omzet iklan"})
        per_sku = per_sku[["SKU", "Produk", "Biaya", "Omzet iklan", "ROAS"]]

    perf, perf_daily = R.performance_range(getattr(frames, "performance", None), start, end)
    report_all = orders_all
    if isinstance(orders_all, pd.DataFrame) and not orders_all.empty:
        stamps = pd.to_datetime(orders_all["order_time"]).dt.normalize()
        report_all = orders_all.loc[stamps.between(pd.Timestamp(start), pd.Timestamp(end))]
    reasons = _cancel_reasons(report_all)
    per_cat = reasons.groupby("kategori")["orders"].sum().reindex(list(CATEGORIES), fill_value=0) if not reasons.empty else pd.Series(dtype=float)
    campaigns = R.campaigns_in_range(features, start, end)

    month_col = "m_sales_exp" if table is not None and "m_sales_exp" in table.columns else "m_sales"
    month_pred = float(table[month_col].sum()) if table is not None and not table.empty and month_col in table.columns else 0.0
    pred_label = format_period_label("prediksi", window_start)
    top50 = table.head(50) if table is not None else pd.DataFrame()
    shortage = stock_shortage(top50) if not top50.empty else {"kurang": 0, "kosong": 0, "tanpa_data": 0}
    status_counts = top50["m_status"].map(status_key).value_counts().to_dict() if not top50.empty and "m_status" in top50.columns else {}
    mc_rows = []
    if not top50.empty and "m_status" in top50.columns:
        sigma_map = stock.set_index("item_key")["sigma_qty"].to_dict() if isinstance(stock, pd.DataFrame) and "sigma_qty" in stock.columns else {}
        from src.core.inventory import LMAX_PERCENTILE_Z, lead_time_days

        lead = params.get("lead_time", {})
        lead_mean = lead_time_days(params)
        if bool(lead.get("impor_aktif", False)):
            lead_sigma = max(float(lead.get("impor_maks_hari", 90) or 0) - lead_mean, 0.0) / LMAX_PERCENTILE_Z
        else:
            lead_sigma = float(lead.get("lokal_sigma_hari", 0) or 0)
        for _, row in top50.head(10).iterrows():
            mc = monte_carlo_stock_scenarios(
                demand_mean=float(row["pred_harian"]), demand_sigma=float(sigma_map.get(row["item_key"], row["pred_harian"] * 0.5)),
                lead_time_mean=lead_mean, lead_time_sigma=lead_sigma,
                current_stock=float(row["stok"]) if bool(row.get("ada_data_stok", False)) else 0.0, safety_stock=float(row["ss"]),
            ).set_index("Skenario")
            mc_rows.append({"SKU": row["sku"], "Produk": row["product_name"], "Stok": row["stok"] if bool(row.get("ada_data_stok", False)) else None,
                            "SS": row["ss"], "ROP": row["rop"], "Restock moderat": round(mc.loc["Moderat", "Restock disarankan"]),
                            "Restock pesimistis": round(mc.loc["Pesimistis", "Restock disarankan"]), "Risiko stockout (%)": round(mc.loc["Moderat", "Risiko stockout"], 1)})
    pred_cols = ["peringkat", "sku", "product_name", "qty_total", "sales_total", "m_qty", "m_sales", "label_text"]
    pred_top = top50[[c for c in pred_cols if c in top50.columns]].head(20).rename(columns={
        "peringkat": "Rank", "sku": "SKU", "product_name": "Produk", "qty_total": "QTY bersih (data latih)", "sales_total": "Sales produk bersih (data latih)",
        "m_qty": f"{pred_label} · QTY", "m_sales": f"{pred_label} · sales produk", "label_text": "Label"}) if not top50.empty else pd.DataFrame()
    records = _records(table, today, data)
    recs = records_display(records) if not records.empty else pd.DataFrame()

    from src.ui.kalkulator import margin_snapshot

    margin = _safe("margin", margin_snapshot, features, table, data, orders_all, start, end) if features is not None else {}
    model = _safe("model", _model_part, outcome, repo, params)
    gudang = _safe("gudang", _gudang_part, features, table, orders_all) if features is not None else {}
    ranking = _safe("ranking", _ranking_part, features, start, end) if features is not None else {}

    cancel_rate = float(facts["tingkat_batal"] * 100)
    promo_days = int(promo_flag(pd.Series(pd.date_range(start, end))).sum())
    names_state = st.session_state.get("_name-recs")
    poor = int((names_state[1].get("Status skor", pd.Series(dtype=str)) == "Poor").sum()) if names_state else None
    total_produk = float(bridge["sales_produk"]) or 1.0
    fact = {
        "growth": growth, "sales_bersih": sales_now, "pesanan": facts["pesanan_semua"],
        "target_pct": reach.pct if reach else None, "target_gap": max((reach.target - sales_now), 0.0) if reach else None,
        "roas": ads["roas"], "target_roas": roas_goal, "ads_share": float(ads["porsi_sales_iklan_pct"]),
        "ads_cost_pct": float(ads["biaya_iklan"]) / total_produk * 100 if ads["biaya_iklan"] > 0 else None,
        "cancel_pct": cancel_rate, "belum_bayar": int(facts["belum_bayar"]), "belum_bayar_akun": int(facts["belum_bayar_akun"]),
        "retur_unit": float(facts["retur_unit"]), "qty_bersih": float(facts["qty_bersih"]),
        "cancel_cats": {str(k): int(v) for k, v in per_cat.items()} if len(per_cat) else {},
        "voucher_shopee_pct": float(bridge["shopee_side"]) / total_produk * 100 if bridge["sales_produk"] else None,
        "top10_share": float(top_all["Sales produk bersih"].head(10).sum()) / total_produk * 100 if not top_all.empty else None,
        "promo_days": promo_days, "campaigns_n": int(len(campaigns)) if isinstance(campaigns, pd.DataFrame) else None,
        "top50_short": int(shortage["kurang"]) if not top50.empty else None, "top50_n": int(len(top50)) if not top50.empty else None,
        "zero_stock": int(table["m_status"].map(status_key).eq("Kosong").sum()) if table is not None and "m_status" in table.columns else None,
        "dead_stock": int(table.get("productivity_label", pd.Series(dtype=str)).astype(str).str.contains("Dead|Slow", regex=True).sum()) if table is not None else None,
        "poor_names": poor,
    }
    if perf:
        fact.update({"visitors_change": _change(perf.get("pengunjung"), perf.get("pengunjung_prev")), "conv": perf.get("konversi"),
                     "conv_prev": perf.get("konversi_prev"), "new_buyers": perf.get("pembeli_baru")})
    if margin.get("ada"):
        fact.update({"margin_pct": margin["overall_pct"], "margin_rp": margin["bersih_rp"], "sku_rugi": margin["rugi"], "sku_rendah": margin["rendah"],
                     "sku_tinggi": margin["tinggi"], "rugi_rp": margin["rugi_rp"], "selisih_rp": margin["selisih_rp"], "acuan_pct": margin["acuan_pct"],
                     "tinggi_porsi": margin["tinggi_porsi"], "shopee_pct": margin["shopee_pct"], "nonaktif_untung": margin["nonaktif_untung"],
                     "nonaktif_hilang_rp": margin["nonaktif_hilang_rp"]})
    if model.get("model"):
        fact.update({"mape_agg": model["mape"], "model": model["model"], "model_bias": model["bias"], "demand_change": model["permintaan_terakhir"],
                     "demand_month": model["bulan_terakhir"]})
    if gudang.get("sku"):
        fact.update({"outstanding_stale": gudang["os_lama"], "restock_no_os": gudang["tanpa_os"]})
    if ranking.get("kategori"):
        fact.update({"rank_cats": ranking["kategori"] - ranking["tanpa_data"], "rank_top10": ranking["top10"], "rank_near": ranking["dekat"],
                     "rank_far": ranking["menengah"] + ranking["jauh"], "rank_down": ranking["turun"], "rank_missing": ranking["tanpa_produk"],
                     "rank_period": ranking["periode"], "rank_near_names": ranking["dekat_nama"], "top_shop": ranking["toko_1"]})

    saved_target = getattr(data, "target", None) or {}
    from src.core.business import business_targets

    target_month = business_targets(params, saved_target).target_sales
    basis = target_month if target_month > 0 else month_pred
    guide = work_guide({"target_sales": basis, "target_text": fmt_idr(basis) if basis > 0 else "(target belum diunggah)",
                        "daily_target_text": fmt_idr(basis / pd.Timestamp(today).days_in_month) if basis > 0 else "(target belum diunggah)", "target_roas": roas_goal})
    qty_prev = float(prev_facts["qty_bersih"]) if has_prev else float("nan")
    produk_prev = float(prev_bridge["sales_produk"]) if has_prev else float("nan")

    return {
        "versi": 2,
        "meta": {"mulai": start, "selesai": end, "label": range_label(start, end), "hari": span, "data_sd": data_until, "run_id": run_id,
                 "periode_lalu": f"{fmt_date(prev[0], short=True)} – {fmt_date(prev[1], short=True)}",
                 "chips": [f"Periode prediksi: {PERIOD_LABELS.get(period, period)}", f"Prediksi: {fmt_date(window_start, short=True)} – {fmt_date(window_end)}",
                           f"Parameter: {'QTY terjual' if metric == 'qty' else 'Sales value'}", f"Safety stock: {service}%",
                           "Kecualikan batal & retur: " + ("aktif" if exclude else "nonaktif")]},
        "kpi": {"sales_bersih": sales_now, "sales_prev": sales_prev, "growth": growth, "pesanan": facts["pesanan_semua"], "pesanan_bersih": facts["pesanan_bersih"],
                "pesanan_prev": prev_facts["pesanan_semua"], "pesanan_bersih_prev": prev_facts["pesanan_bersih"] if has_prev else None,
                "batal": facts["pesanan_batal"], "tingkat_batal": cancel_rate, "retur_unit": facts["retur_unit"],
                "retur_penuh": facts["pesanan_retur_penuh"], "retur_pesanan": facts.get("pesanan_retur", 0), "belum_bayar": facts["belum_bayar"],
                "belum_bayar_akun": facts["belum_bayar_akun"], "belum_bayar_semua": facts.get("belum_bayar_semua"), "nominal_batal": facts["nominal_batal"], "nominal_retur": facts["nominal_retur"],
                "qty_bersih": facts["qty_bersih"], "qty_prev": qty_prev, "qty_batal": facts.get("qty_batal", 0),
                "sales_produk": float(bridge["sales_produk"]), "sales_produk_prev": produk_prev,
                "aov": sales_now / facts["pesanan_bersih"] if facts["pesanan_bersih"] else 0.0,
                "target": reach.target if reach else None, "target_pct": reach.pct if reach else None,
                "target_bulan": reach.month_target if reach else None, "target_bulan_pct": reach.month_pct if reach else None},
        "bridge": _bridge_frame(bridge),
        "daily": daily, "monthly": monthly, "top": top, "top_n": int(len(top_all)),
        "ads": {"biaya": ads["biaya_iklan"], "omzet": ads["omzet_iklan"], "roas": ads["roas"], "target_roas": roas_goal, "porsi": float(ads["porsi_sales_iklan_pct"]),
                "sales_produk": float(ads["sales_produk_bersih"]), "hari_iklan": int(ads.get("hari_iklan", 0) or 0), "peringatan": list(warnings), "catatan": list(notes),
                "per_sku": per_sku},
        "perf": perf, "perf_daily": perf_daily,
        "tx": {"reasons": reasons.rename(columns={"reason": "Alasan batal", "orders": "Pesanan", "kategori": "Kategori"}),
               "per_cat": pd.DataFrame({"Kategori": list(per_cat.index), "Pesanan": [int(v) for v in per_cat.values]})},
        "campaigns": campaigns,
        "margin": margin, "model": model, "gudang": gudang, "ranking": ranking,
        "fakta": {k: v for k, v in fact.items() if not isinstance(v, (pd.DataFrame,))},
        "swot": RA.swot(fact),
        "analisa": {"masalah": RA.problem_statement(fact), "tulang": RA.fishbone(fact)},
        "pred": {"month_pred": month_pred, "label": pred_label, "target": target_month, "kurang": int(shortage["kurang"]), "kosong": int(shortage["kosong"]),
                 "tanpa_data": int(shortage["tanpa_data"]), "status": {k: int(v) for k, v in status_counts.items()}, "mc": pd.DataFrame(mc_rows), "top": pred_top,
                 "window": f"{fmt_date(window_start, short=True)} – {fmt_date(window_end, short=True)}"},
        "recs": recs,
        "guide": {name: pd.DataFrame(tasks, columns=["Tugas", "Ukuran berhasil"]) for name, tasks in guide.items()},
    }


# ---------------------------------------------------------------- menampilkan snapshot

def _s_summary(s: dict) -> None:
    k, ads, pred = s["kpi"], s["ads"], s["pred"]
    margin, model = s.get("margin") or {}, s.get("model") or {}
    lalu = s["meta"]["periode_lalu"]
    explain(TERMS, title="Istilah angka di laporan ini")
    cols = st.columns(4)
    reach = f"<br>target {fmt_idr(k['target'])} · {_signed_pct(k['target_pct'] - 100)} dari target" if k.get("target") else ""
    metric_card(cols[0], "sales_bersih", fmt_idr(k["sales_bersih"]), hint=f"{_signed_pct(k['growth'])} vs {lalu}{reach}")
    if k.get("sales_produk") is not None:
        card(cols[1], "Sales produk bersih", fmt_idr(k["sales_produk"]),
             hint=f"{_signed_pct(_change(k['sales_produk'], k.get('sales_produk_prev')))} vs {lalu} · sebelum voucher Shopee/koin")
        card(cols[2], "QTY bersih", fmt_qty(k["qty_bersih"]), hint=f"{_signed_pct(_change(k['qty_bersih'], k.get('qty_prev')))} vs {lalu} · retur {fmt_qty(k['retur_unit'])} unit")
    else:
        card(cols[1], "QTY bersih", fmt_qty(k["qty_bersih"]), hint=f"retur {fmt_qty(k['retur_unit'])} unit")
        metric_card(cols[2], "roas", fmt_num(ads["roas"], 1), hint=f"target {fmt_num(ads['target_roas'], 1)}")
    card(cols[3], "Pesanan bersih", fmt_num(k["pesanan_bersih"]), hint=f"AOV {fmt_idr(k['aov'])} · batal {fmt_pct(k['tingkat_batal'], 1)} dari {fmt_num(k['pesanan'])}")
    cols = st.columns(4)
    if margin.get("ada"):
        card(cols[0], "Margin bersih SKU aktif", fmt_idr(margin["bersih_rp"]),
             hint=f"{fmt_pct(margin['overall_pct'], 1)} setelah PPN, potongan Shopee & iklan · {fmt_num(margin['rugi'])} SKU rugi")
    else:
        card(cols[0], "Margin bersih", "–", hint="butuh file harga beli / file margin")
    metric_card(cols[1], "roas", fmt_num(ads["roas"], 1), hint=f"target {fmt_num(ads['target_roas'], 1)} · biaya iklan {fmt_idr_short(ads['biaya'])}")
    if model.get("model"):
        card(cols[2], "Akurasi prediksi total toko", fmt_pct(model["mape"], 1),
             hint=f"MAPE agregat · {html.escape(str(model['model']))} · bias luar sampel {fmt_pct(model['bias'], 1, signed=True)}")
    else:
        card(cols[2], "Akurasi prediksi", "–", hint="jalankan analisa agar evaluasi model terisi")
    card(cols[3], "Top 50 stok kurang", fmt_num(pred["kurang"]), hint=f"{fmt_num(pred['kosong'])} stok 0 · dari analisa aktif")
    bridge = _frame(s.get("bridge"))
    if not bridge.empty:
        _sub("Dari Sales produk bersih ke Sales bersih (pesanan yang sama)")
        html_table(bridge, kinds={"Nilai": "money"}, widths={"Komponen": 260, "Nilai": 170}, total_label="= Sales bersih")
    daily = s["daily"]
    if not daily.empty:
        fig = go.Figure(go.Scatter(x=pd.to_datetime(daily["Tanggal"]), y=daily["Sales bersih"], fill="tozeroy", line=dict(color="#1b3da6"), name="Sales bersih"))
        fig.update_layout(title="Sales bersih harian", yaxis_title="Rp", showlegend=False)
        _plot(fig, f"rp-sum-{id(s)}", 260)
    lines = []
    if k.get("target"):
        lines.append(f"Sales bersih {fmt_idr(k['sales_bersih'])} = <b>{fmt_pct(k['target_pct'], 1)}</b> dari target periode {fmt_idr(k['target'])}.")
    if np.isfinite(k.get("growth") or np.nan):
        lines.append(f"Sales bersih {'naik' if k['growth'] >= 0 else 'turun'} <b>{fmt_pct(abs(k['growth']), 1)}</b> dibanding periode sebelumnya ({lalu}).")
    if margin.get("ada"):
        lines.append(f"Margin bersih SKU aktif {fmt_pct(margin['overall_pct'], 1)} ({fmt_idr(margin['bersih_rp'])}); {fmt_num(margin['rugi'])} SKU rugi "
                     f"(−{fmt_idr(margin['rugi_rp'])}) dan {fmt_num(margin['rendah'])} SKU margin di bawah {fmt_pct(margin['acuan_pct'], 1)}.")
    lines.append(f"ROAS iklan {fmt_num(ads['roas'], 1)} vs target {fmt_num(ads['target_roas'], 1)}; omzet atribusi iklan setara {fmt_pct(ads['porsi'], 1)} sales produk bersih "
                 "(atribusi Shopee ikut menghitung belanja produk lain setelah klik iklan, jadi bisa di atas 100%).")
    lines.append(f"Tingkat batal {fmt_pct(k['tingkat_batal'], 1)}; {fmt_num(k['belum_bayar'])} pesanan batal karena belum bayar bisa dikejar lewat chat.")
    lines.append(f"{fmt_num(pred['kurang'])} SKU Top 50 stoknya di bawah {pred['label']} + safety stock: prioritas restock sebelum menambah iklan.")
    gudang, ranking = s.get("gudang") or {}, s.get("ranking") or {}
    if gudang.get("sku"):
        lines.append(f"Gudang 10037: {fmt_num(gudang['kosong'])} SKU kosong, {fmt_num(gudang['hampir'])} hampir habis; "
                     f"{fmt_num(gudang['os_lama'])} SKU outstanding lewat {gudang['batas_hari']} hari perlu dikejar.")
    if ranking.get("kategori"):
        lines.append(f"Ranking kompetitor {ranking['periode']}: Top 10 di {fmt_num(ranking['top10'])} kategori, {fmt_num(ranking['dekat'])} kategori dekat (11–50).")
    if model.get("model"):
        lines.append(f"Model prediksi {html.escape(str(model['model']))}: {model['lulus']}/{model['uji']} uji kesesuaian terpenuhi.")
    st.markdown(_box("Poin utama", lines, "#1d4ed8"), unsafe_allow_html=True)
    if not s["recs"].empty:
        _sub("Rekomendasi utama")
        html_table(s["recs"].head(5), kinds={"Stok Site 10037": "count", "Kebutuhan": "count", "Restock": "count"}, widths={"Produk": 240, "Alasan": 280})


def _s_trend(s: dict) -> None:
    k, daily, monthly = s["kpi"], s["daily"], s["monthly"]
    if k.get("target"):
        pct = float(k["target_pct"])
        st.markdown(
            f"<div style='margin:.3rem 0 .8rem'><div style='display:flex;justify-content:space-between;font-size:.85rem'><b>Pencapaian target periode</b>"
            f"<span>{fmt_idr(k['sales_bersih'])} / {fmt_idr(k['target'])} · <b style='color:{UP if pct >= 100 else DOWN}'>{fmt_pct(pct, 1)}</b></span></div>"
            f"<div style='height:14px;background:#e2e8f0;border-radius:999px;overflow:hidden'><div style='width:{min(pct, 100):.1f}%;height:100%;"
            f"background:{UP if pct >= 100 else '#ee4d2d'}'></div></div></div>", unsafe_allow_html=True)
    if not daily.empty:
        x = pd.to_datetime(daily["Tanggal"])
        fig = go.Figure()
        fig.add_bar(x=x, y=daily["Sales bersih"], name="Sales bersih", marker_color="#93c5fd")
        if "Sales produk bersih" in daily:
            fig.add_scatter(x=x, y=daily["Sales produk bersih"], name="Sales produk bersih", line=dict(color="#94a3b8", width=1.5, dash="dot"))
        fig.add_scatter(x=x, y=daily["Sales bersih"].rolling(7, min_periods=1).mean(), name="Sales bersih · rata-rata 7 hari", line=dict(color="#1b3da6", width=3))
        if k.get("target"):
            fig.add_scatter(x=x, y=[k["target"] / len(daily)] * len(daily), name="Target harian", line=dict(color="#f59e0b", dash="dash"))
        fig.update_layout(title="Sales harian", yaxis_title="Rp")
        _plot(fig, f"rp-trend-d-{id(s)}")
        if k.get("target"):
            cum = daily["Sales bersih"].cumsum()
            fig = go.Figure()
            fig.add_scatter(x=x, y=cum, name="Aktual kumulatif", fill="tozeroy", line=dict(color="#1b3da6"))
            fig.add_scatter(x=x, y=np.linspace(k["target"] / len(daily), k["target"], len(daily)), name="Laju target", line=dict(color="#f59e0b", dash="dash"))
            fig.update_layout(title="Sales bersih kumulatif vs laju target", yaxis_title="Rp")
            _plot(fig, f"rp-trend-c-{id(s)}", 320)
    if not monthly.empty:
        fig = go.Figure()
        colors = ["#93a5d8" if p else "#1b3da6" for p in monthly["Sebagian"]]
        fig.add_bar(x=monthly["Bulan"], y=monthly["Sales bersih"], marker_color=colors, name="Sales bersih", text=[fmt_idr_short(v) for v in monthly["Sales bersih"]], textposition="outside")
        if "Sales produk bersih" in monthly:
            fig.add_scatter(x=monthly["Bulan"], y=monthly["Sales produk bersih"], name="Sales produk bersih", mode="lines+markers", line=dict(color="#94a3b8"))
        if (monthly["Target"] > 0).any():
            fig.add_scatter(x=monthly["Bulan"], y=monthly["Target"].where(monthly["Target"] > 0), name="Target bulanan", mode="lines+markers", line=dict(color="#f59e0b", dash="dash"))
        fig.update_layout(title="6 bulan terakhir (batang muda = bulan belum penuh)", yaxis_title="Rp")
        _plot(fig, f"rp-trend-m-{id(s)}")
        view = monthly.assign(Status=np.where(monthly["Target"] <= 0, "", np.where(monthly["Sales bersih"] >= monthly["Target"], "✅ Tercapai",
                                                                                 np.where(monthly["Sebagian"], "⏳ Berjalan", "❌ Tidak tercapai"))))
        view["Target"] = view["Target"].where(view["Target"] > 0)
        columns = ["Bulan", "Sales produk bersih", "Sales bersih", "QTY bersih", "Pesanan bersih", "Target", "Target s.d. data", "Pencapaian (%)", "Status"]
        html_table(view[[c for c in columns if c in view.columns]], status="Status",
                   kinds={"Sales produk bersih": "money", "Sales bersih": "money", "QTY bersih": "count", "Pesanan bersih": "count", "Target": "money",
                          "Target s.d. data": "money", "Pencapaian (%)": "pct"}, nowrap=("Bulan", "Status"))
    explain([("Sales bersih", "Total Pembayaran per pesanan − batal − Belum Bayar − retur; sudah dipotong voucher (sama dengan kartu Ringkasan, dasar target)"),
             ("Sales produk bersih", "Harga Setelah Diskon × QTY bersih (dasar prediksi, margin, produk terlaris & porsi iklan); "
              "lebih besar dari sales bersih karena belum dipotong voucher Shopee/koin (lihat jembatan di Ringkasan eksekutif)"),
             ("Target", "dari Upload data › Target sales bulanan, dibagi per tanggal menurut pola hari bila rentang tidak sebulan penuh"),
             ("Pencapaian", "sales bersih ÷ target s.d. data (bulan belum penuh: s.d. hari penuh terakhir, target berjalan menurut pola hari; sama dengan kartu Sales bersih)")])


def _s_products(s: dict) -> None:
    top = s["top"].rename(columns={"Sales": "Sales produk bersih", "QTY": "QTY bersih", "Sales periode lalu": "Sales produk bersih periode lalu"})
    if top.empty:
        st.write("Belum ada penjualan pada rentang ini.")
        return
    value = "Sales produk bersih"
    label = top["Rank"].astype(int).astype(str) + ". " + top["Produk"].astype(str).str.slice(0, 40)
    part = top.head(15).iloc[::-1]
    fig = go.Figure(go.Bar(x=part[value], y=label.loc[part.index], orientation="h", marker_color="#1b3da6",
                           text=[fmt_idr_short(v) for v in part[value]], textposition="outside", cliponaxis=False))
    fig.update_layout(title="15 produk terlaris (sales produk bersih)", xaxis_title="Rp", xaxis_range=[0, float(part[value].max()) * 1.18])
    _plot(fig, f"rp-top-{id(s)}", 480)
    fig = go.Figure(go.Treemap(ids=top["SKU"].astype(str), labels=label, parents=[""] * len(top), values=top[value], textinfo="label+percent root",
                               marker=dict(colors=top[value], colorscale="Blues")))
    fig.update_layout(title=f"Porsi sales {len(top)} produk teratas (persen dari total {len(top)} produk ini)")
    _plot(fig, f"rp-tree-{id(s)}", 380)
    total = float(s["kpi"].get("sales_produk") or 0)
    html_table(top, kinds={value: "money", "Sales produk bersih periode lalu": "money", "Porsi (%)": "pct", "Perubahan (%)": "pct", "QTY bersih": "count", "Rank": "count"},
               widths={"Produk": 380}, nowrap=("SKU",))
    note = f"Perubahan dibanding periode sebelumnya ({s['meta']['periode_lalu']}). Porsi = terhadap Sales produk bersih semua produk"
    if total:
        note += (f" ({fmt_idr(total)} dari {fmt_num(s.get('top_n', 0))} SKU terjual); {len(top)} produk ini = "
                 f"{fmt_pct(float(top[value].sum()) / total * 100, 1)}.")
    st.caption(note)


def _s_margin(s: dict) -> None:
    m = s.get("margin")
    if m is None:
        st.info(OLD)
        return
    if m.get("_galat"):
        st.warning(f"Margin belum bisa dihitung ({m['_galat']}).")
        return
    if not m.get("ada"):
        st.info("Belum ada SKU aktif terjual pada rentang ini" + ("" if m.get("file_margin") else ", dan file harga beli / file margin belum diunggah") + ".")
        return
    st.caption("Mesin hitung sama dengan Kalkulator margin › Ringkasan & prioritas, pada rentang laporan ini (SKU aktif = ada di unggahan stok terakhir).")
    k = st.columns(4)
    off = f" · + {fmt_idr(m['sales_nonaktif_periode'])} dari {fmt_num(m['sku_nonaktif_periode'])} SKU nonaktif" if m.get("sku_nonaktif_periode") else ""
    card(k[0], "Sales produk bersih SKU aktif", fmt_idr(m["sales_produk"]), hint=f"{fmt_num(m['sku_aktif'])} SKU · QTY bersih {fmt_qty(m['qty'])}{off}")
    card(k[1], "Margin kotor", fmt_idr(m["kotor_rp"]), hint=f"{fmt_pct(m['kotor_pct'], 1)} dari sales produk bersih · harga beli / file margin")
    card(k[2], "Margin bersih", fmt_idr(m["bersih_rp"]), hint=f"{fmt_pct(m['overall_pct'], 1)} setelah PPN, potongan Shopee {fmt_pct(m['shopee_pct'], 1)} & iklan {fmt_pct(m['iklan_pct'], 1)}")
    card(k[3], "Perlu ditindaklanjuti", fmt_num(m["rugi"] + m["rendah"]),
         hint=f"{fmt_num(m['rugi'])} rugi (−{fmt_idr(m['rugi_rp'])}) · {fmt_num(m['rendah'])} di bawah {fmt_pct(m['acuan_pct'], 1)} (+{fmt_idr(m['selisih_rp'])} bila naik)")
    total_produk = float(s["kpi"].get("sales_produk") or 0)
    if total_produk:
        both = m["sales_produk"] + float(m.get("sales_nonaktif_periode") or 0)
        st.caption(f"Cek konsistensi: SKU aktif {fmt_idr(m['sales_produk'])} + SKU nonaktif {fmt_idr(m.get('sales_nonaktif_periode') or 0)} = {fmt_idr(both)}; "
                   f"kartu Sales produk bersih {fmt_idr(total_produk)}" + (" ✓ sama." if abs(both - total_produk) <= max(1.0, total_produk * 1e-6) else f" (selisih {fmt_idr(both - total_produk)})."))
    _sub("Ringkasan per status margin")
    html_table(_frame(m.get("status")), status="Status", total_label="Total",
               kinds={"Jumlah SKU": "count", "QTY bersih": "count", "Sales produk bersih": "money", "Porsi sales (%)": "pct", "Margin bersih": "money"})
    st.caption(f"Rugi < 0% · Rendah = untung tetapi di bawah {fmt_pct(m['acuan_pct'], 1)} (rata-rata margin SKU yang untung) · Tinggi ≥ batas itu.")
    spread = _frame(m.get("sebaran"))
    if not spread.empty:
        colors = {"Tinggi": "#2563eb", "Rendah": "#f59e0b", "Rugi": "#dc2626"}
        fig = go.Figure()
        for status, part in spread.groupby("Status"):
            fig.add_scatter(x=part["Sales produk bersih"], y=part["Margin bersih (%)"], mode="markers", name=status, text=part["Nama"].astype(str).str.slice(0, 40),
                            marker=dict(color=colors.get(status, "#94a3b8"), size=8, opacity=.75), hovertemplate="%{text}<br>Rp %{x:,.0f} · %{y:.1f}%<extra></extra>")
        fig.add_hline(y=float(m["acuan_pct"]), line_dash="dash", line_color="#64748b", annotation_text="batas margin rendah")
        fig.add_hline(y=0, line_color="#dc2626", line_width=1)
        fig.update_layout(title="Sebaran SKU aktif: sales produk bersih vs margin bersih", xaxis_title="Sales produk bersih (Rp, skala log)", xaxis_type="log",
                          yaxis_title="Margin bersih (%)")
        _plot(fig, f"rp-margin-{id(s)}", 340)
    def compact(frame: pd.DataFrame) -> pd.DataFrame:
        """Gabung margin kotor / potongan Shopee / iklan jadi satu kolom agar tabel muat tanpa digulir (Excel tetap rinci)."""
        parts = [c for c in ("Margin kotor (%)", "Shopee (%)", "Potongan Shopee (%)", "Iklan (%)") if c in frame.columns]
        if frame.empty or len(parts) < 3:
            return frame
        text = [" / ".join("–" if pd.isna(v) else fmt_num(v, 1) for v in row) for row in frame[parts].itertuples(index=False)]
        out = frame.drop(columns=parts)
        out.insert(out.columns.get_loc("Margin bersih (%)"), "Kotor / Shopee / iklan (%)", text)
        return out

    fix = compact(_frame(m.get("perbaiki")))
    kinds = {"QTY bersih": "count", "Sales produk bersih": "money", "Margin kotor (%)": "pct", "Shopee (%)": "pct", "Potongan Shopee (%)": "pct", "Iklan (%)": "pct",
             "Margin bersih (%)": "pct", "Margin bersih": "money", "Margin bersih per bulan": "money", "Sales produk bersih per bulan": "money", "Bulan terjual": "count"}
    if not fix.empty:
        _sub(f"Prioritas perbaikan margin ({len(fix)} SKU teratas: rugi terbesar, lalu selisih ke batas)")
        html_table(fix, status="Status", kinds=kinds, widths={"Nama": 150}, nowrap=("SKU", "Status", "Kotor / Shopee / iklan (%)"))
    best = compact(_frame(m.get("terbaik")))
    if not best.empty:
        _sub("SKU margin tinggi dengan margin bersih terbesar (layak didorong)")
        html_table(best, status="Status", kinds=kinds, widths={"Nama": 150}, nowrap=("SKU", "Status", "Kotor / Shopee / iklan (%)"))
    off_sku = _frame(m.get("nonaktif"))
    if not off_sku.empty:
        _sub(f"SKU nonaktif · potensi margin yang hilang ({fmt_num(m['nonaktif_untung'])} SKU dulu untung, ±{fmt_idr(m['nonaktif_hilang_rp'])}/bulan)")
        html_table(off_sku, status="Status", kinds=kinds, widths={"Nama": 150}, nowrap=("SKU",))


def _s_stock(s: dict) -> None:
    pred = s["pred"]
    st.caption(f"Bagian ini dari hasil analisa aktif (prediksi {pred['window']}), bukan dari rentang laporan.")
    cols = st.columns(4)
    card(cols[0], pred["label"], fmt_idr(pred["month_pred"]),
         hint="sales produk 30 hari ke depan (bukan bulan kalender, belum dipotong voucher)"
         + (f" · target bulan (sales bersih) {fmt_idr(pred['target'])}" if pred["target"] else ""))
    for column, name in zip(cols[1:], ("Aman", "Kurang", "Kosong")):
        card(column, f"Top 50 · {name}", fmt_num(pred["status"].get(name, 0)), hint="status stok bulan ini")
    if pred["status"]:
        fig = go.Figure(go.Pie(labels=list(pred["status"]), values=list(pred["status"].values()), hole=.5,
                               marker_colors=[{"Aman": UP, "Kurang": "#f59e0b", "Kosong": DOWN}.get(n, "#94a3b8") for n in pred["status"]]))
        fig.update_layout(title="Status stok Top 50")
        _plot(fig, f"rp-stock-{id(s)}", 300)
    if not pred["top"].empty:
        _sub("20 produk teratas & prediksinya")
        html_table(pred["top"], widths={"Produk": 280}, nowrap=("SKU",))
    if not pred["mc"].empty:
        _sub("Skenario Monte Carlo (1.000 simulasi permintaan × lead time) 10 SKU teratas")
        html_table(pred["mc"], kinds={"SS": "count", "ROP": "count", "Stok": "count", "Restock moderat": "count", "Restock pesimistis": "count"},
                   widths={"Produk": 280}, nowrap=("SKU",))
        st.caption("Tiap simulasi mengacak lead time lalu permintaan selama lead time (rata-rata harian × L, sebaran σ × √L). "
                   "Restock moderat/pesimistis = kekurangan stok pada kuantil 50%/90%; risiko stockout = peluang permintaan lead time melebihi stok sekarang. "
                   "ROP = permintaan harian × lead time + SS.")


def _s_model(s: dict) -> None:
    m = s.get("model")
    if m is None:
        st.info(OLD)
        return
    if m.get("_galat") or not m.get("model"):
        st.info("Hasil uji walk-forward belum tersedia. Jalankan analisa agar evaluasi model terisi." + (f" ({m['_galat']})" if m.get("_galat") else ""))
        return
    st.caption(f"Dari evaluasi walk-forward analisa aktif: horizon {m['horizon'].lower()}, {m['lipatan']} lipatan bulanan, {fmt_num(m['n_sku'])} SKU. "
               "Kartu & uji kesesuaian sama dengan Evaluasi model › Ringkasan: MAPE & WAPE pada lipatan uji, bias luar sampel (bobot & koreksi "
               "disetel dari lipatan sebelumnya saja). Model produksi = WAPE luar sampel terkecil.")
    k = st.columns(4)
    card(k[0], "Model produksi", str(m["model"]), hint=f"{m['lulus']}/{m['uji']} uji kesesuaian terpenuhi")
    oos_m = f" · luar sampel {fmt_pct(m['mape_oos'], 1)}" if m.get("mape_oos") is not None else ""
    oos_w = f" · luar sampel {fmt_pct(m['wape_oos'], 1)}" if m.get("wape_oos") is not None else ""
    card(k[1], "MAPE agregat toko", fmt_pct(m["mape"], 1), hint=f"kesalahan total QTY toko per 30 hari · target ≤ 15%{oos_m}")
    card(k[2], "WAPE per SKU", fmt_pct(m["wape"], 1), hint=f"kesalahan per SKU ditimbang volume{oos_w} · Top 50 tepat {fmt_num(m['top50'], 1)}/50")
    card(k[3], "Bias", fmt_pct(m["bias"], 1, signed=True),
         hint="negatif = cenderung kurang prediksi" + (f" · layanan simulasi {fmt_pct(m['layanan'], 1)} (target {fmt_pct(m['layanan_target'], 0)})" if m.get("layanan") is not None else ""))
    pct = {c: "pct" for c in _frame(m.get("models")).columns if c.endswith("(%)")}
    _sub("Perbandingan model (urut dari WAPE luar sampel terkecil)")
    html_table(_frame(m.get("models")), status="Peran", kinds={**pct, "Top 50 tepat": "dec"}, widths={"Model": 190}, nowrap=("Peran",))
    _sub("Uji kesesuaian algoritma & metode")
    html_table(_frame(m.get("checks")), status="Status", widths={"Uji": 170, "Target": 110, "Hasil": 100, "Arti": 300}, nowrap=("Status",))
    folds = _frame(m.get("folds"))
    if not folds.empty:
        _sub("Galat total toko per lipatan")
        html_table(folds, kinds={"Aktual sebelumnya": "count", "Aktual": "count", "Prediksi model produksi": "count", "Prediksi MA28": "count",
                                 "Perubahan permintaan (%)": "pct", "Galat model produksi (%)": "pct", "Galat MA28 (%)": "pct"})
    if m.get("kesimpulan"):
        st.markdown(_box("Kesimpulan per horizon", [html.escape(t) for t in m["kesimpulan"]], "#0f172a"), unsafe_allow_html=True)
    for title, items, tone in (("Kekuatan", m.get("kekuatan") or [], "#047857"), ("Kelemahan & penyebabnya", m.get("kelemahan") or [], "#b45309"),
                               ("Tindak lanjut", m.get("tindak") or [], "#1d4ed8")):
        st.markdown(_box(title, [html.escape(t) for t in items], tone), unsafe_allow_html=True)


def _s_gudang(s: dict) -> None:
    g = s.get("gudang")
    if g is None:
        st.info(OLD)
        return
    if g.get("_galat") or not g.get("sku"):
        st.info("Data Replenishment Site 10037 belum diunggah (Setting › Gudang)." + (f" ({g['_galat']})" if g.get("_galat") else ""))
        return
    st.caption(f"Kondisi saat laporan dibuat: snapshot replenishment {g.get('snapshot') or '–'} (bukan rentang laporan). Sama dengan Gudang 10037 › SKU & tindakan.")
    k = st.columns(4)
    card(k[0], "SKU dipantau", fmt_num(g["sku"]), hint=f"{fmt_num(g['aman'])} aman · {fmt_num(g['berlebih'])} stok berlebih")
    card(k[1], "Kosong / hampir habis", f"{fmt_num(g['kosong'])} / {fmt_num(g['hampir'])}", hint="perlu isi ulang")
    card(k[2], "Outstanding PO/TR/TO", fmt_num(g["os_sku"]) + " SKU", hint=f"{fmt_qty(g['os_unit'])} unit dalam perjalanan")
    card(k[3], f"Outstanding > {g['batas_hari']} hari", fmt_num(g["os_lama"]), hint=f"{fmt_num(g['tanpa_os'])} SKU perlu isi ulang belum ada PO/TR/TO")
    tbl = _frame(g.get("tabel"))
    if not tbl.empty:
        _sub(f"SKU yang perlu tindakan ({len(tbl)} teratas: kosong & hampir habis menurut dampak sales, lalu outstanding lama)")
        html_table(tbl, status="Status", kinds={"Stok 10037": "count", "Max": "count", "Outstanding": "count"},
                   widths={"Nama": 130}, nowrap=("SKU",))


def _s_ads(s: dict) -> None:
    ads = s["ads"]
    for message in ads["peringatan"]:
        st.warning(message)
    cols = st.columns(4)
    metric_card(cols[0], "biaya_iklan", fmt_idr(ads["biaya"]))
    metric_card(cols[1], "omzet_iklan", fmt_idr(ads["omzet"]))
    metric_card(cols[2], "roas", fmt_num(ads["roas"], 1), hint=f"target {fmt_num(ads['target_roas'], 1)}")
    card(cols[3], "Omzet iklan ÷ sales produk bersih", fmt_pct(ads["porsi"]),
         hint=f"sales produk bersih {fmt_idr(ads['sales_produk'])} · biaya iklan {fmt_pct(ads['biaya'] / ads['sales_produk'] * 100 if ads['sales_produk'] else 0, 1)} dari sales · bisa > 100% karena atribusi Shopee")
    for message in ads["catatan"]:
        st.caption(message)
    if 0 < ads["hari_iklan"] < s["meta"]["hari"]:
        st.caption(f"Laporan iklan hanya mencakup {ads['hari_iklan']} dari {s['meta']['hari']} hari rentang ini.")
    per_sku = ads["per_sku"]
    if isinstance(per_sku, pd.DataFrame) and not per_sku.empty:
        part = per_sku.head(15).reset_index(drop=True)
        names = [f"{i + 1}. {str(n)[:22]}" for i, n in enumerate(part["Produk"])]
        fig = go.Figure()
        fig.add_bar(x=names, y=part["Biaya"], name="Biaya iklan", marker_color="#ee4d2d", text=[fmt_idr_short(v) for v in part["Biaya"]], textposition="outside")
        fig.add_scatter(x=names, y=part["ROAS"], name="ROAS", mode="markers+text", yaxis="y2", marker=dict(color="#1b3da6", size=11, symbol="diamond"),
                        text=[fmt_num(v, 1) for v in part["ROAS"]], textposition="top center")
        fig.add_hline(y=float(ads["target_roas"]), line_dash="dash", line_color="#f59e0b", yref="y2")
        fig.update_layout(title="15 produk dengan biaya iklan terbesar: biaya (batang) & ROAS (titik; garis = target)", yaxis_title="Rp",
                          yaxis2=dict(title="ROAS", overlaying="y", side="right", rangemode="tozero"), xaxis_tickangle=-30)
        _plot(fig, f"rp-ads-{id(s)}", 420)
        html_table(per_sku, kinds={"Biaya": "money", "Omzet iklan": "money", "ROAS": "dec"}, widths={"Produk": 320}, nowrap=("SKU",))
    elif ads["biaya"] <= 0:
        st.caption("Laporan iklan belum diunggah atau tidak ada pada rentang ini.")


def _s_campaigns(s: dict) -> None:
    camp = s["campaigns"]
    if camp is None or camp.empty:
        st.write("Tidak ada campaign tersimpan (iklan, flash sale, exposure) pada rentang ini.")
        return
    fig = go.Figure()
    colors = {"Iklan": "#ee4d2d", "Flash sale": "#1b3da6", "Exposure media sosial": "#0891b2"}
    for _, row in camp.iterrows():
        a, b = pd.Timestamp(row["Mulai"]), pd.Timestamp(row["Selesai"])
        fig.add_bar(y=[row["Campaign"]], x=[(b - a).days + 1], base=[a], orientation="h", marker_color=colors.get(row["Jenis"], "#94a3b8"), name=row["Jenis"],
                    hovertemplate=f"{row['Jenis']}: {row['Ringkasan']}<extra></extra>", showlegend=False)
    fig.add_vrect(x0=pd.Timestamp(s["meta"]["mulai"]), x1=pd.Timestamp(s["meta"]["selesai"]) + pd.Timedelta(days=1), fillcolor="#fde68a", opacity=.25, line_width=0)
    fig.update_layout(xaxis_type="date", title="Jadwal campaign (area kuning = rentang laporan)", yaxis=dict(autorange="reversed"))
    _plot(fig, f"rp-camp-{id(s)}", 120 + 40 * len(camp))
    view = camp.copy()
    for column in ("Mulai", "Selesai"):
        view[column] = pd.to_datetime(view[column], errors="coerce").dt.strftime("%d/%m/%Y")
    html_table(view, widths={"Campaign": 220, "Ringkasan": 360}, nowrap=("Mulai", "Selesai", "Jenis"))


def _s_perf(s: dict) -> None:
    perf, daily = s["perf"], s["perf_daily"]
    if not perf:
        st.write("Data performa toko belum diunggah.")
        return

    def delta(now, then):
        return _signed_pct(_change(now, then))

    cols = st.columns(4)
    card(cols[0], "Pengunjung", fmt_num(perf["pengunjung"]), hint=f"{delta(perf['pengunjung'], perf['pengunjung_prev'])} vs periode lalu")
    card(cols[1], "Pesanan (performa toko)", fmt_num(perf["pesanan"]), hint=f"{delta(perf['pesanan'], perf['pesanan_prev'])} vs periode lalu · versi Shopee, bisa beda dengan pesanan bersih")
    card(cols[2], "Konversi (tertimbang)", fmt_pct(perf["konversi"], 2), hint=f"periode lalu {fmt_pct(perf['konversi_prev'], 2)}")
    card(cols[3], "Pembeli baru", fmt_num(perf["pembeli_baru"]), hint=f"{perf['hari']} hari data performa")
    if isinstance(daily, pd.DataFrame) and not daily.empty:
        x = pd.to_datetime(daily["Tanggal"])
        fig = go.Figure()
        if "Pengunjung" in daily:
            fig.add_bar(x=x, y=daily["Pengunjung"], name="Pengunjung", marker_color="#cbd5e1")
        if "Konversi (%)" in daily:
            fig.add_scatter(x=x, y=daily["Konversi (%)"], name="Konversi (%)", yaxis="y2", line=dict(color="#ee4d2d", width=3))
        fig.update_layout(title="Pengunjung & konversi harian", yaxis_title="Pengunjung", yaxis2=dict(title="Konversi (%)", overlaying="y", side="right"))
        _plot(fig, f"rp-perf-{id(s)}")
        if {"Pengunjung", "Pesanan"} <= set(daily.columns):
            work = daily.assign(Minggu=x.dt.to_period("W-SUN").dt.start_time.dt.strftime("%d/%m/%Y"))
            has_conv = "Konversi (%)" in work.columns
            if has_conv:
                work = work.assign(_bobot=pd.to_numeric(work["Konversi (%)"], errors="coerce") * work["Pengunjung"])
            week = work.groupby("Minggu", sort=False).agg(Hari=("Pengunjung", "size"), Pengunjung=("Pengunjung", "sum"), Pesanan=("Pesanan", "sum"),
                                                          **({"_bobot": ("_bobot", "sum")} if has_conv else {})).reset_index()
            if has_conv:
                # Konversi Shopee = pembeli ÷ pengunjung; ditimbang pengunjung, sama dengan kartu Konversi (tertimbang).
                week["Konversi (%)"] = np.where(week["Pengunjung"] > 0, week.pop("_bobot") / week["Pengunjung"].replace(0, 1), np.nan)
            _sub("Ringkasan per minggu (mulai Senin)")
            html_table(week.rename(columns={"Minggu": "Minggu mulai"}), kinds={"Hari": "count", "Pengunjung": "count", "Pesanan": "count", "Konversi (%)": "dec"})


def _s_ranking(s: dict) -> None:
    r = s.get("ranking")
    if r is None:
        st.info(OLD)
        return
    if r.get("_galat") or not r.get("kategori"):
        st.info("Belum ada data ranking kompetitor berperiode (Rekomendasi › Ranking kategori › Unggah & periode)." + (f" ({r['_galat']})" if r.get("_galat") else ""))
        return
    st.caption(f"Periode ranking {r['periode_lengkap']} · dasar {r['dasar']}" + ("" if r.get("cocok") else " · periode terdekat yang tersedia (tidak beririsan dengan rentang laporan)")
               + (f" · pembanding {r['pembanding']}" if r.get("pembanding") else ""))
    k = st.columns(5)
    card(k[0], "Kategori dipantau", fmt_num(r["kategori"]), hint=f"{fmt_num(r['tanpa_data'])} belum ada data")
    card(k[1], "Sudah Top 10", fmt_num(r["top10"]), hint="produk kita di peringkat ≤ 10")
    card(k[2], "Dekat (11–50)", fmt_num(r["dekat"]), hint=r.get("dekat_nama") or "peluang tercepat masuk Top 10")
    card(k[3], "Menengah / Jauh", fmt_num(r["menengah"] + r["jauh"]), hint=f"{fmt_num(r['tanpa_produk'])} kategori tanpa produk kita di daftar")
    card(k[4], "Naik / turun", f"{fmt_num(r['naik'])} / {fmt_num(r['turun'])}", hint=f"dibanding {r['pembanding']}" if r.get("pembanding") else "belum ada periode pembanding")
    if r.get("catatan"):
        st.markdown(_box(f"Catatan analisa · {r['periode']}", [html.escape(n) for n in r["catatan"]]), unsafe_allow_html=True)
    tbl = _frame(r.get("tabel"))
    empty = tbl.loc[tbl["Status"].astype(str).str.contains("Belum ada data")] if not tbl.empty else tbl
    tbl = tbl.drop(index=empty.index) if not empty.empty else tbl
    if not tbl.empty:
        kinds = {c: ("money" if c.startswith("Sales") else "count") for c in tbl.columns if c.endswith(" kita") or c.endswith(" #10")}
        kinds.update({"Peringkat": "count", "Produk kita": "count", "Di Top 10": "count"})
        html_table(tbl, status="Status", kinds=kinds, widths={"Kategori": 130}, nowrap=("Status",))
        st.caption("🟦 Top 10 · 🟩 11–50 · 🟧 51–500 · 🟥 > 500 · ⬜ produk kita tidak ada di daftar.")
    if not empty.empty:
        st.caption(f"Belum ada data ranking ({len(empty)} kategori): " + ", ".join(f"{k} ({g})" for g, k in zip(empty["Grup"], empty["Kategori"])) + ".")


def _s_tx(s: dict) -> None:
    k, tx, daily = s["kpi"], s["tx"], s["daily"]
    cols = st.columns(4)
    metric_card(cols[0], "pesanan_semua", fmt_num(k["pesanan"]), hint=f"bersih {fmt_num(k['pesanan_bersih'])} · lalu {fmt_num(k['pesanan_prev'])}")
    metric_card(cols[1], "pesanan_batal", fmt_num(k["batal"]), hint=f"{fmt_pct(k['tingkat_batal'], 1)} · {fmt_idr_short(k['nominal_batal'])}")
    metric_card(cols[2], "retur_unit", fmt_qty(k["retur_unit"]), hint=f"{fmt_num(k['retur_penuh'])} pesanan diretur penuh · {fmt_idr_short(k['nominal_retur'])}")
    semua = k.get("belum_bayar_semua")
    metric_card(cols[3], "belum_bayar", fmt_num(k["belum_bayar"]),
                hint=f"{fmt_num(k['belum_bayar_akun'])} akun belum membeli ulang barang yang sama" + (f" · dari {fmt_num(semua)} pesanan batal belum bayar" if semua else ""))
    c1, c2 = st.columns(2)
    with c1:
        if not daily.empty:
            x = pd.to_datetime(daily["Tanggal"])
            fig = go.Figure()
            fig.add_bar(x=x, y=daily["Pesanan"], name="Pesanan", marker_color="#cbd5e1")
            fig.add_bar(x=x, y=daily["Pesanan batal"], name="Batal", marker_color=DOWN)
            fig.add_scatter(x=x, y=daily["Tingkat batal (%)"], name="Tingkat batal (%)", yaxis="y2", line=dict(color="#0f172a"))
            fig.update_layout(barmode="overlay", title="Pesanan & batal harian", yaxis2=dict(title="%", overlaying="y", side="right"))
            _plot(fig, f"rp-tx-{id(s)}")
    with c2:
        per_cat = tx["per_cat"]
        if not per_cat.empty and per_cat["Pesanan"].sum() > 0:
            fig = go.Figure(go.Pie(labels=per_cat["Kategori"], values=per_cat["Pesanan"], hole=.5))
            fig.update_layout(title="Alasan batal per kategori")
            _plot(fig, f"rp-txpie-{id(s)}")
    if not tx["reasons"].empty:
        _sub("15 alasan batal terbanyak")
        html_table(tx["reasons"][["Kategori", "Alasan batal", "Pesanan"]].head(15), kinds={"Pesanan": "count"}, widths={"Alasan batal": 360}, nowrap=("Kategori",))


def _s_swot(s: dict) -> None:
    meta = s["meta"]
    st.markdown(swot_html(s.get("swot") or {}, subtitle=f"{meta['label']} · dari angka laporan ini"), unsafe_allow_html=True)
    st.caption("Tiap butir dihitung dari bagian laporan ini (penjualan, target, margin, iklan, performa, ranking kompetitor, stok & gudang, transaksi, "
               "akurasi model). Butir yang datanya belum diunggah tidak ditulis.")


def _s_fishbone(s: dict) -> None:
    analysis = s.get("analisa")
    if analysis:
        st.markdown(fishbone_svg(analysis.get("masalah", ""), analysis.get("tulang") or {}), unsafe_allow_html=True)
        st.markdown(fishbone_legend(), unsafe_allow_html=True)
        st.caption("Kepala ikan = masalah utama periode ini; enam tulang = kelompok penyebab (4P + proses + lingkungan). Tiap butir adalah angka laporan ini; "
                   "merah = menyumbang ke masalah, kuning = perlu diwaspadai, hijau = sudah baik sebagai pembanding.")
    else:
        st.caption("Laporan tersimpan versi lama: fishbone berisi alasan batal per kategori.")
        bones = s.get("fishbone") or {}
        cols = st.columns(3)
        for index, category in enumerate(FISHBONE_CATEGORIES):
            with cols[index % 3].container(border=True):
                st.markdown(f"**{category}**")
                items = bones.get(category) or ["Tidak ada alasan pada kategori ini"]
                st.markdown("\n".join(f"- {item}" for item in items[:6]))
    per_cat = s["tx"]["per_cat"]
    if not per_cat.empty and per_cat["Pesanan"].sum() > 0:
        part = per_cat.sort_values("Pesanan")
        fig = go.Figure(go.Bar(x=part["Pesanan"], y=part["Kategori"], orientation="h", marker_color="#ee4d2d", text=part["Pesanan"], textposition="outside"))
        fig.update_layout(title="Rincian tulang Proses: pesanan batal per kategori alasan")
        _plot(fig, f"rp-fish-{id(s)}", 280)


def _s_recs(s: dict) -> None:
    if s["recs"].empty:
        st.write("Belum ada rekomendasi (jalankan analisa).")
        return
    st.caption("Dari analisa aktif. Restock = max(0, prediksi + SS − stok Site 10037); kekurangan diambil dulu dari Site 10062/10036, sisanya PO. PIC: restock lokal → Team DC; PO impor → Team IC/MD; harga/iklan → E-commerce.")
    html_table(s["recs"].head(30), kinds={"Stok Site 10037": "count", "Kebutuhan": "count", "Restock": "count"}, widths={"Produk": 240, "Alasan": 320}, nowrap=("SKU",))


def _s_guide(s: dict) -> None:
    for name, frame in (s["guide"] or {}).items():
        _sub(name)
        html_table(frame, widths={"Tugas": 420})


RENDER = dict(zip(SECTIONS, (_s_summary, _s_trend, _s_products, _s_margin, _s_stock, _s_model, _s_gudang, _s_ads, _s_campaigns, _s_perf, _s_ranking,
                             _s_tx, _s_swot, _s_fishbone, _s_recs, _s_guide)))


def _excel_sheets(s: dict) -> dict[str, pd.DataFrame]:
    m, model, g, r = s.get("margin") or {}, s.get("model") or {}, s.get("gudang") or {}, s.get("ranking") or {}
    swot = s.get("swot") or {}
    tulang = (s.get("analisa") or {}).get("tulang") or {}
    sheets = {"Jembatan sales": s.get("bridge"), "Harian": s["daily"], "Bulanan": s["monthly"], "Produk terlaris": s["top"],
              "Margin per status": m.get("status"), "Margin prioritas": m.get("perbaiki"), "Margin tertinggi": m.get("terbaik"), "SKU nonaktif": m.get("nonaktif"),
              "Prediksi Top 20": s["pred"]["top"], "Monte Carlo": s["pred"]["mc"],
              "Model perbandingan": model.get("models"), "Uji kesesuaian": model.get("checks"), "Galat per lipatan": model.get("folds"),
              "Gudang perlu tindakan": g.get("tabel"), "Iklan per produk": s["ads"]["per_sku"], "Campaign": s["campaigns"], "Performa harian": s["perf_daily"],
              "Ranking kompetitor": r.get("tabel"), "Alasan batal": s["tx"]["reasons"],
              "SWOT": pd.DataFrame([{"Kuadran": k, "Butir": t} for k, items in swot.items() for t in items]),
              "Fishbone": pd.DataFrame([{"Tulang": b, "Penyebab": i["text"], "Tingkat": i["level"]} for b, items in tulang.items() for i in items]),
              "Rekomendasi": s["recs"]}
    return {k: v for k, v in sheets.items() if isinstance(v, pd.DataFrame) and not v.empty}


def render(s: dict, *, key: str) -> None:
    meta = s["meta"]
    st.markdown("".join(_chip(c) for c in meta.get("chips") or [])
                + _chip(f"Data transaksi s.d. {fmt_date(pd.Timestamp(meta['data_sd']).date(), short=True)}" if meta.get("data_sd") else "")
                + (_chip(f"Analisa #{meta['run_id']}") if meta.get("run_id") else ""), unsafe_allow_html=True)
    nav, body = st.columns([1, 4.2])
    with nav:
        st.markdown("**Daftar isi**")
        options = (ALL_SECTIONS,) + SECTIONS
        section = st.radio("Daftar isi", options, index=1, key=f"{key}-section", label_visibility="collapsed",
                           format_func=lambda x: x.replace(". ", "\\. ", 1))
        if section == ALL_SECTIONS:
            _print_button()
        download_excel(_excel_sheets(s), f"laporan_{meta['mulai']}_{meta['selesai']}.xlsx", key=f"xl-{key}", label="Unduh semua tabel (Excel)")
    with body:
        for name in (SECTIONS if section == ALL_SECTIONS else (section,)):
            st.markdown(f"<div class='section-title'>{html.escape(name)}</div>", unsafe_allow_html=True)
            st.caption(f"Periode laporan: {meta['label']} ({meta['hari']} hari)")
            try:
                RENDER[name](s)
            except Exception as exc:
                st.warning(f"Bagian ini belum bisa ditampilkan: {exc}")


# ---------------------------------------------------------------- halaman

def show_report(table: pd.DataFrame, *, orders: pd.DataFrame, orders_all: pd.DataFrame, frames, params: dict, today: date, period: str, metric: str,
                service: int, exclude: bool, window_start: date, window_end: date, stock: pd.DataFrame | None = None, features=None, data=None,
                run_id: int = 0, username: str = "", can_edit: bool = False, outcome=None, repo=None) -> None:
    st.subheader("Laporan penjualan e-commerce Mitra10 × Shopee")
    store = R.ReportStore(features) if features is not None else None
    saved = store.all() if store is not None else []
    flash = st.session_state.pop("report-flash", None)
    if flash:
        st.success(flash)
    modes = [LIVE, f"{SAVED} ({len(saved)})"]
    pending = st.session_state.pop("report-mode-pending", None)
    if pending:
        st.session_state["report-mode"] = modes[1] if pending == SAVED else modes[0]
    if st.session_state.get("report-mode") not in modes:
        st.session_state["report-mode"] = modes[0]
    mode = st.segmented_control("Mode laporan", modes, key="report-mode", label_visibility="collapsed") if hasattr(st, "segmented_control") else st.radio("Mode", modes, horizontal=True)
    if mode == modes[1]:
        _saved_view(store, saved, username=username, can_edit=can_edit)
        return

    if orders_all is None or orders_all.empty:
        st.write("Belum ada transaksi untuk dilaporkan.")
        return
    stamps = pd.to_datetime(orders_all["order_time"], errors="coerce").dropna()
    lo, hi = stamps.min().date(), stamps.max().date()
    full_lo, full_hi = last_full_month(hi)
    default = (max(full_lo, lo), min(full_hi, hi)) if full_lo >= lo else (max(lo, hi.replace(day=1)), hi)
    with st.container(border=True):
        c1, c2 = st.columns([1.3, 2])
        with c1:
            start, end = date_range_picker(key="report-cal", lo=lo, hi=hi, default=default, label="Periode laporan")
        c2.markdown(f"<div class='field-hint' style='margin-top:1.9rem'>Semua angka, grafik & tabel mengikuti rentang ini. Bagian prediksi, stok, gudang, akurasi model "
                    f"& rekomendasi memakai analisa aktif{f' #{run_id}' if run_id else ''} dan data terbaru. Data transaksi tersedia {fmt_date(lo, short=True)} – "
                    f"{fmt_date(hi, short=True)}.</div>", unsafe_allow_html=True)
    versions = tuple(st.session_state.get(k, 0) for k in ("_feature-version", "_harga-beli-version", "_margin-version"))
    cache_key = (run_id, start, end, bool(exclude), len(orders_all), str(hi), versions, 2)
    cached = st.session_state.get("report-live")
    if not (isinstance(cached, tuple) and cached[0] == cache_key):
        with st.spinner(f"Menyusun laporan {range_label(start, end)}..."):
            snapshot = build_snapshot(table, orders=orders, orders_all=orders_all, frames=frames, params=params, today=today, period=period, metric=metric,
                                      service=service, exclude=exclude, window_start=window_start, window_end=window_end, stock=stock, features=features,
                                      data=data, run_id=run_id, start=start, end=end, outcome=outcome, repo=repo)
        st.session_state["report-live"] = (cache_key, snapshot)
    else:
        snapshot = cached[1]
    with st.container(border=True):
        s1, s2 = st.columns([3, 1])
        name = s1.text_input("Nama laporan", value=f"Laporan {range_label(start, end)}", key=f"report-name-{start}-{end}", max_chars=80)
        s2.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        if s2.button("Simpan laporan", key="report-save", type="primary", disabled=not (can_edit and store is not None), use_container_width=True):
            report_id = store.save(snapshot, name=name.strip() or f"Laporan {range_label(start, end)}", username=username, now=datetime.now())
            st.session_state["report-flash"] = f"Laporan #{report_id} disimpan. Buka kapan saja dari \"{SAVED}\" tanpa menganalisa ulang."
            st.session_state["report-open"] = report_id
            st.session_state["report-mode-pending"] = SAVED
            st.rerun()
        st.caption("Laporan tersimpan menyimpan semua angka, tabel & grafik saat ini; dibuka lagi persis sama walau data atau analisa sudah berubah.")
    render(snapshot, key="report-live")


def _saved_view(store, saved: list[dict], *, username: str, can_edit: bool) -> None:
    if not saved:
        st.info("Belum ada laporan tersimpan. Buat laporan, pilih periodenya, lalu tekan Simpan laporan.")
        return
    labels = {int(r["id"]): f"#{r['id']} · {r.get('nama', '')} · dibuat {str(r.get('dibuat', ''))[:16]} oleh {r.get('dibuat_oleh', '')}" for r in saved}
    ids = list(labels)
    wanted = st.session_state.pop("report-open", None)
    if wanted in ids:
        st.session_state["report-pick"] = wanted
    if st.session_state.get("report-pick") not in ids:
        st.session_state["report-pick"] = ids[0]
    c1, c2 = st.columns([4, 1])
    pick = c1.selectbox("Laporan tersimpan", ids, format_func=labels.get, key="report-pick")
    with c2:
        st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        with st.popover("Hapus", use_container_width=True, disabled=not can_edit):
            st.write(f"Hapus laporan #{pick}?")
            if st.button("Ya, hapus", key=f"report-del-{pick}", type="primary"):
                store.delete(pick, username=username)
                st.session_state["report-flash"] = f"Laporan #{pick} dihapus."
                st.session_state["report-mode-pending"] = SAVED
                st.rerun()
    with st.expander("Daftar semua laporan tersimpan"):
        html_table(pd.DataFrame(saved).rename(columns={"id": "No", "nama": "Nama", "mulai": "Mulai", "selesai": "Selesai", "dibuat": "Dibuat", "dibuat_oleh": "Oleh",
                                                       "run": "Analisa", "data_sd": "Data s.d."}), widths={"Nama": 260})
    cache = st.session_state.setdefault("report-saved-cache", {})
    if pick not in cache:
        cache.clear()
        cache[pick] = store.get(pick)
    snapshot = cache[pick]
    if not snapshot:
        st.warning("Isi laporan ini tidak ditemukan.")
        return
    meta = snapshot.get("meta") or {}
    st.markdown(f"<div class='field-hint'>Laporan tersimpan: <b>{html.escape(str(meta.get('nama', '')))}</b> · periode {html.escape(str(meta.get('label', '')))} · "
                f"dibuat {html.escape(str(meta.get('dibuat', ''))[:16])} oleh {html.escape(str(meta.get('dibuat_oleh', '')))}. Angka tidak dihitung ulang."
                + ("" if snapshot.get("versi") else " Dibuat dengan versi laporan lama: bagian margin, akurasi model, gudang & ranking belum ada.") + "</div>",
                unsafe_allow_html=True)
    render(snapshot, key=f"report-saved-{pick}")
