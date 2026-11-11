"""Rekomendasi › Iklan (target & strategi), Flash sale toko, Exposure media sosial, Ranking kategori (4C–4E)."""

from __future__ import annotations

import html
from datetime import date

import numpy as np
import pandas as pd
import streamlit as st

from src.core import ads_plan, ranking_score
from src.core import exposure as expo
from src.core import flash_sale as flash
from src.core import margin as margin_core
from src.core.campaigns import as_date
from src.core.decision_table import stock_need
from src.core.fmt import fmt_date
from src.core.product_features import features_from_description
from src.core.promo import momentum_14d, product_label, promo_eligible
from src.ui.common import batched_view, download_excel, explain, fmt_idr, fmt_num
from src.ui.feature_data import FeatureData
from src.core.ads import roas_estimate
from src.utils.format import show_table

STEP = 20
CANDIDATE_LIMIT = 300
WEEKDAYS = ("Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min")


def _label(row) -> str:
    return product_label(row["sku"], row["product_name"], row.get("variasi_tampil", ""))


def _periode(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _bulan_label(day: date) -> str:
    """Label bulan untuk tampilan: "November 2026" (kunci simpan tetap YYYY-MM)."""
    names = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember")
    return f"{names[day.month - 1]} {day.year}"


def _margin_of(data: FeatureData, sku: str, fallback: float) -> tuple[float, bool]:
    value = data.margin_pct.get(str(sku))
    if value is None or not np.isfinite(value):
        typical = getattr(data, "margin_fallback", None)
        return (float(typical) if typical is not None and np.isfinite(typical) else fallback), False
    return float(value), True


# ---------------------------------------------------------------- Iklan (4C)


def _candidates(table: pd.DataFrame, data: FeatureData, margin_min: float, roas_default: float) -> tuple[list[ads_plan.Candidate], pd.DataFrame]:
    rows, cands = [], []
    for _, row in table.head(CANDIDATE_LIMIT).iterrows():
        sku = str(row["sku"])
        margin_pct, known_margin = _margin_of(data, sku, margin_min)
        ok, reasons, decision = promo_eligible(row, excluded=data.excluded, margin_pct=data.margin_pct.get(sku), cancel_pct=row.get("batal_pct"), margin_min=margin_min)
        # Biaya harian = biaya iklan ÷ hari yang benar-benar tercakup laporan (bukan ÷ 30 untuk laporan 7 hari).
        daily = float(row.get("biaya_harian", 0) or 0)
        roas_now, _basis = roas_estimate(row, roas_default)
        curve = ads_plan.default_curve(daily, roas_now)
        stok = float(row["stok"]) if bool(row.get("ada_data_stok", False)) else 0.0
        extra_units = stok - stock_need(row)
        price = float(row.get("harga_bersih", 0) or 0)
        cap = ads_plan.unit_cap_to_cost(curve, daily, extra_units, price) if extra_units > 0 else 0.0
        cand = ads_plan.Candidate(sku, _label(row), margin_pct, daily, curve, cap, decision, reasons)
        cands.append(cand)
        rows.append({"sku": sku, "known_margin": known_margin})
    return cands, pd.DataFrame(rows)


def _ads_inputs(table: pd.DataFrame, features, frames, days_left: int):
    """Unit iklan + ekonomi per Kode Produk: kontribusi sebelum iklan (margin kotor − potongan Shopee) dan ruang stok (Rp/hari)."""
    from src.core import ads_strategy as A
    from src.core import shopee_fee as fee
    from src.core.margin_file import sku_key
    from src.ui.kalkulator import KEY_SKU_CAT, _category_fees, _programs
    from src.ui.margin_data import load_margin

    ads = list(getattr(frames, "ads", []) or [])
    auto, group, overall = (ads + [pd.DataFrame()] * 3)[:3]
    units, members = A.parse_units(group, overall, auto)
    if not units:
        return [], members, {}, pd.DataFrame()
    latest = max(p for u in units for p, _c, _s in u.history) if any(u.history for u in units) else ""
    recent = sorted({p for u in units for p, _c, _s in u.history})[-2:]
    units = [u for u in units if u.status.lower().startswith(("berjalan", "dijeda")) or (u.history and u.history[-1][0] in recent)]
    stock = getattr(frames, "stock", pd.DataFrame())
    code_of: dict[str, str] = {}
    if isinstance(stock, pd.DataFrame) and not stock.empty and {"sku", "product_code"} <= set(stock.columns):
        snap = stock.loc[stock["_submitted_at"].astype(str).eq(stock["_submitted_at"].astype(str).max())] if "_submitted_at" in stock.columns else stock
        code_of = {sku_key(s): str(c).strip() for s, c in zip(snap["sku"].astype(str), snap["product_code"])}
    md = load_margin(features)
    kotor = md.kotor_map() if md.ready else {}
    programs, order_fee, _ = _programs(features)
    fees = _category_fees(features)
    sku_cat = features.get_json(KEY_SKU_CAT, {}) or {} if features is not None else {}
    contrib: dict[str, list[tuple[float, float]]] = {}
    room: dict[str, float] = {}
    rows = []
    for r in table.to_dict("records"):
        key = sku_key(r.get("sku", ""))
        code = code_of.get(key, "")
        price = float(r.get("harga_bersih", 0) or 0)
        sales = float(r.get("sales_total", 0) or 0)
        if code and price > 0:
            k = kotor.get(key, md.store_kotor_pct if md.ready else np.nan)
            if k == k:
                inp = fee.Inputs(harga=price, admin_pct=fee.admin_for(r.get("sku", ""), r.get("product_name", ""), fees, sku_cat)[1],
                                 programs=programs, order_fee=order_fee, ukuran_khusus="packing kayu" in str(r.get("product_name", "")).lower())
                contrib.setdefault(code, []).append((k / 100 - fee.shopee_fees(inp) / price, max(sales, 1.0)))
            stok = float(r.get("stok", 0) or 0) if r.get("ada_data_stok", False) else np.nan
            if stok == stok:
                guard = float(r.get("ss", r.get("safety_stock", 0)) or 0)
                spare = max(stok - float(r.get("pred_harian", 0) or 0) * days_left - (guard if guard == guard else 0.0), 0.0)
                room[code] = room.get(code, 0.0) + spare * price / max(days_left, 1)
            rows.append({"product_code": code, "nama": r.get("product_name", ""), "omzet_harian": float(r.get("pred_harian", 0) or 0) * price, "stok": stok})
    contribution = {c: sum(v * w for v, w in vals) / sum(w for _v, w in vals) for c, vals in contrib.items()}
    A.attach_economics(units, members, contribution, room)
    products = (pd.DataFrame(rows).groupby(["product_code"], as_index=False).agg(nama=("nama", "first"), omzet_harian=("omzet_harian", "sum"), stok=("stok", lambda v: v.sum(min_count=1)))
                if rows else pd.DataFrame(columns=["product_code", "nama", "omzet_harian", "stok"]))
    products["stok_room"] = products["product_code"].map(room)
    # Fokus kejar target: hanya iklan produk tunggal & grup; iklan baru diusulkan oleh pemilihan produk (A.build_plan).
    units = [u for u in units if u.jenis in A.TARGET_KINDS]
    del latest
    return units, members, contribution, products


def show_ads_strategy(table: pd.DataFrame, *, features, data: FeatureData, params: dict, window_start: date, username: str, can_edit: bool,
                      frames=None, orders: pd.DataFrame | None = None) -> None:
    from src.ui.ads_target import show_target_strategy

    show_target_strategy(table, features=features, params=params, username=username, can_edit=can_edit, frames=frames, orders=orders,
                         inputs=_ads_inputs)


# ---------------------------------------------------------------- Flash sale (4D)


def _flash_floor(data: FeatureData, sku: str, today: date) -> float:
    """Harga impas (margin 0, tanpa biaya iklan) per unit untuk harga flash; NaN bila modal tidak diketahui."""
    comp = margin_core.effective_components(data.components, sku, on=today) if not data.components.empty else None
    if comp:
        return float(margin_core.harga_minimal(comp, 0.0, 0.0))
    inp = getattr(data, "margin_inputs", {}).get(sku)
    if inp is not None:
        from dataclasses import replace

        from src.core import shopee_fee as fee

        return float(fee.min_price(replace(inp, iklan=0.0), 0.0))
    return float("nan")


def _flash_items(table: pd.DataFrame, data: FeatureData, orders: pd.DataFrame | None, today: date) -> pd.DataFrame:
    momentum = momentum_14d(orders.assign(sku=orders["sku"].astype(str)) if orders is not None and not orders.empty and "sku" in orders.columns else None, today)
    recent = pd.Timestamp(today) - pd.Timedelta(days=90)
    rows = []
    for r in table.to_dict("records"):
        sku = str(r["sku"])
        dc = sum(float(r.get(c) or 0) for c in ("stok_10062", "stok_10036") if pd.notna(r.get(c)))
        last = pd.to_datetime(r.get("last_order"), errors="coerce")
        sold = float(r.get("qty_total", 0) or 0) or (1.0 if pd.notna(last) and last >= recent else 0.0)
        rows.append({
            "sku": sku, "label": product_label(sku, r.get("product_name", ""), r.get("variasi_tampil", "")), "nama": str(r.get("product_name", "")),
            "harga": float(r.get("harga_bersih", 0) or 0), "stok": r.get("stok"), "ada_stok": bool(r.get("ada_data_stok", False)),
            "ss": float(r.get("ss", 0) or 0), "harian": float(r.get("pred_harian", 0) or 0), "dc": dc, "terjual": sold,
            "m_sales": float(r.get("m_sales", 0) or 0), "batal_pct": r.get("batal_pct"), "floor": _flash_floor(data, sku, today),
            "momentum": momentum.get(sku, 0.0),
        })
    return pd.DataFrame(rows)


FLASH_ICON = {flash.DRIVER: "🔥", flash.CLEAR: "📦"}
def _clip(text: str, limit: int) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut if len(cut) >= limit // 2 else text[:limit]).rstrip(" ,·-") + "…"


FLASH_RULES = ("Prioritas omzet", "Tidak di bawah impas")


def _chip(icon: str, name: str, color: str, text: str) -> str:
    return (f"<span style='border:1px solid #e2e8f0;border-radius:999px;padding:.25rem .75rem;font-size:.85rem;background:#fff'>{icon} "
            f"<b style='color:{color}'>{name}</b> {text}</span>")


def _flash_render(plan: pd.DataFrame, skipped: pd.DataFrame, start: date, end: date, *, key: str) -> None:
    """Kartu, kalender, tabel, unduhan, transfer DC, dan SKU tidak dijadwalkan untuk satu jadwal flash sale."""
    from datetime import timedelta

    from src.ui.common import card

    days = (end - start).days + 1
    if plan.empty:
        st.warning("Belum ada SKU yang bisa dijadwalkan: semua SKU laku kehabisan stok di toko dan DC, atau harganya tidak memberi ruang diskon. "
                   "Lihat daftar alasan di bawah dan ajukan restock.")
    else:
        by_source = plan.drop_duplicates("SKU")["Sumber stok"].value_counts().to_dict()
        chips = [_chip(icon, name, color, f"{fmt_num(by_source.get(name, 0))} SKU")
                 for name, icon, color in ((flash.SRC_SITE, "✅", "#1d4ed8"), (flash.SRC_DC, "🚚", "#b45309"), (flash.SRC_THIN, "⚠️", "#b45309")) if by_source.get(name)]
        if skipped is not None and not skipped.empty:
            chips.append(_chip("⛔", "Tidak dijadwalkan", "#dc2626", f"{fmt_num(len(skipped))} SKU"))
        st.markdown("<div style='display:flex;flex-wrap:wrap;gap:.45rem;margin:.2rem 0 .6rem'>" + "".join(chips) + "</div>", unsafe_allow_html=True)
        moves = flash.transfers(plan)
        k = st.columns(4)
        card(k[0], "Slot flash sale", fmt_num(len(plan)), hint=f"{fmt_num(plan['SKU'].nunique())} SKU berbeda · {days} hari")
        margin = pd.to_numeric(plan.get("Margin/unit", pd.Series(dtype=float)), errors="coerce")
        loss = margin.fillna(0.0).clip(upper=0) * pd.to_numeric(plan["Kuota"], errors="coerce").fillna(0)
        below = int((margin < 0).sum())
        card(k[1], "Estimasi omzet maks.", fmt_idr(plan["Estimasi omzet maks."].sum()),
             hint="bila semua kuota terjual di harga flash" + (f" · <b style='color:#dc2626'>{fmt_num(below)} slot di bawah impas, rugi maks. {fmt_idr(-loss.sum())}</b>"
                                                              if below else ""))
        mix = plan["Tujuan"].value_counts().to_dict()
        card(k[2], "Komposisi", f"🔥 {fmt_num(mix.get(flash.DRIVER, 0))} · 📦 {fmt_num(mix.get(flash.CLEAR, 0))}", hint="pendorong omzet · habiskan stok lebih")
        card(k[3], "Transfer dari DC", f"{fmt_num(moves['Unit transfer'].sum() if not moves.empty else 0)} unit",
             hint=f"{fmt_num(len(moves))} SKU · kirim paling lambat {fmt_date(moves['Kirim paling lambat'].min())}" if not moves.empty else "tidak perlu transfer")
        st.markdown("**Kalender**")
        dates = [start + timedelta(days=i) for i in range(days)]
        for week_start in range(0, len(dates), 7):
            cols = st.columns(7)
            for column, day in zip(cols, dates[week_start:week_start + 7]):
                part = plan.loc[plan["Tanggal"] == day]
                moment = part["Momen"].iloc[0] if not part.empty and part["Momen"].iloc[0] != "Harian" else ""
                items = "".join(
                    f"<div title='{html.escape(str(p))}' style='font-size:var(--fs-xs);line-height:1.3;margin-top:3px;overflow-wrap:anywhere'>"
                    f"{FLASH_ICON.get(t, '')}{'🚚' if s == flash.SRC_DC else ''} {html.escape(_clip(n, 42))}</div>"
                    for p, n, t, s in zip(part["Produk"], part["Produk"].str.split(" · ").str[1].fillna(part["Produk"]), part["Tujuan"], part["Sumber stok"])
                )
                column.markdown(
                    f"<div style='border:1px solid #e2e8f0;border-radius:8px;padding:6px;min-height:130px;background:#fff'>"
                    f"<b>{day.day}/{day.month}</b> <span style='color:#64748b;font-size:var(--fs-xs)'>{WEEKDAYS[day.weekday()]}</span>"
                    + (f"<div style='font-size:var(--fs-xs);color:#b45309;font-weight:700'>{html.escape(moment)}</div>" if moment else "")
                    + items + "</div>", unsafe_allow_html=True)
        st.caption("🔥 pendorong omzet · 📦 habiskan stok lebih · 🚚 stok ditransfer dari DC")
        f1, f2 = st.columns(2)
        goal_pick = f1.multiselect("Tujuan", [flash.DRIVER, flash.CLEAR], key=f"{key}-goal", placeholder="Semua tujuan")
        src_pick = f2.multiselect("Sumber stok", [flash.SRC_SITE, flash.SRC_DC, flash.SRC_THIN], key=f"{key}-src", placeholder="Semua sumber")
        view = plan
        if goal_pick:
            view = view.loc[view["Tujuan"].isin(goal_pick)]
        if src_pick:
            view = view.loc[view["Sumber stok"].isin(src_pick)]
        view = view.assign(Tanggal=view["Tanggal"].map(fmt_date),
                           **{"Kirim dari DC paling lambat": view["Kirim dari DC paling lambat"].map(lambda d: fmt_date(d) if isinstance(d, date) else "")})
        batched_view(
            len(view), key=f"{key}-plan", noun="slot",
            render=lambda lo, hi: show_table(view.iloc[lo:hi], kinds={"Harga normal": "money", "Harga flash": "money", "Diskon (%)": "pct", "Kuota": "count",
                                                                     "Batas beli/pembeli": "count", "Estimasi omzet maks.": "money", "Margin/unit": "money"},
                                             max_height=10_000,
                                             column_config={"Produk": st.column_config.TextColumn(width="large"), "Alasan": st.column_config.TextColumn(width="large"),
                                                            "Margin/unit": st.column_config.Column(help="Harga flash − harga impas (File margin, tanpa biaya iklan); minus = rugi per unit")}),
            download=lambda: download_excel({"Jadwal": plan, "Transfer DC": moves, "Tidak dijadwalkan": skipped}, f"flash_sale_{start.isoformat()}.xlsx", key=f"xl-{key}"),
        )
        download_excel(flash.shopee_template(plan), f"template_flash_sale_shopee_{start.isoformat()}.xlsx", key=f"xl-{key}-tpl", label="Unduh template Shopee")
        if not moves.empty:
            st.markdown("**Transfer DC → toko (Site 10037)**")
            show_table(moves.assign(**{"Kirim paling lambat": moves["Kirim paling lambat"].map(fmt_date)}), kinds={"Unit transfer": "count", "Jumlah slot": "count"},
                       column_config={"Produk": st.column_config.TextColumn(width="large")})
            st.caption(f"Ajukan transfer dari DC 10062/10036 paling lambat {flash.TRANSFER_DAYS} hari sebelum slot; SKU dari DC tidak dijadwalkan di {flash.TRANSFER_DAYS} hari pertama.")
    if skipped is not None and not skipped.empty:
        with st.expander(f"Tidak dijadwalkan · {fmt_num(len(skipped))} SKU"):
            counts = skipped["Alasan"].astype(str).str.split(":").str[0].value_counts()
            st.caption(" · ".join(f"{name}: {fmt_num(n)}" for name, n in counts.items()))
            batched_view(
                len(skipped), key=f"{key}-skip", noun="SKU",
                render=lambda lo, hi: show_table(skipped.iloc[lo:hi], kinds={"Stok toko": "count", "Stok DC": "count"}, max_height=10_000,
                                                 column_config={"SKU · produk · varian": st.column_config.TextColumn(width="large"),
                                                                "Alasan": st.column_config.TextColumn(width="large")}),
                download=lambda: download_excel(skipped, f"flash_sale_tidak_dijadwalkan_{start.isoformat()}.xlsx", key=f"xl-{key}-skip",
                                                label="Unduh SKU tidak dijadwalkan"),
            )


def _flash_describe(c: dict) -> str:
    s = c.get("setelan", {}) or {}
    return (f"{fmt_num(s.get('per_hari', 0))} SKU/hari · porsi habiskan stok {fmt_num(float(s.get('porsi', 0)) * 100)}% · aturan harga {html.escape(str(s.get('aturan', '-')))}"
            f" · {fmt_num(len(c.get('jadwal') or []))} slot · estimasi omzet maks. {fmt_idr(sum(float(r.get('Estimasi omzet maks.') or 0) for r in c.get('jadwal') or []))}")


def show_flash_sale(table: pd.DataFrame, *, data: FeatureData, today: date, orders: pd.DataFrame | None = None, features=None,
                    username: str = "", can_edit: bool = False) -> None:
    from datetime import timedelta

    from src.ui import campaign_ui as cmp

    st.markdown("<div class='section-title'>Flash sale toko</div>", unsafe_allow_html=True)
    if table is None or table.empty:
        st.write("Jalankan analisa terlebih dahulu.")
        return
    st.caption("Jadwal flash sale toko Shopee yang tetap jalan walau stok terbatas: tiap SKU diberi sumber stok yang memungkinkan "
               "(stok toko → transfer DC → kuota kecil). Simpan sebagai campaign agar jadwal terkunci; tiap hari dicek ulang dengan stok terbaru.")
    cmp.flash_message("flash")
    mode, cur = cmp.panel("flash", features=features, today=today, can_edit=can_edit, username=username, describe=_flash_describe)
    items = _flash_items(table, data, orders, today)
    if mode == cmp.SAVED and cur is not None:
        start, end = as_date(cur["mulai"]), as_date(cur["selesai"])
        plan = cmp.frame_of(cur.get("jadwal"), ("Tanggal", "Kirim dari DC paling lambat"))
        skipped = cmp.frame_of(cur.get("tidak_dijadwalkan"))
        s = cur.get("setelan", {}) or {}
        cands, fresh_skipped = flash.candidates(items, excluded=data.excluded, below_floor=s.get("aturan", FLASH_RULES[0]) == FLASH_RULES[0])
        reasons = dict(zip(fresh_skipped["SKU · produk · varian"].astype(str).str.split(" · ").str[0], fresh_skipped["Alasan"])) if not fresh_skipped.empty else {}
        upcoming = plan.loc[plan["Tanggal"] >= today] if not plan.empty else plan
        bad = upcoming.loc[~upcoming["SKU"].astype(str).isin(set(cands["sku"].astype(str)))] if not upcoming.empty else upcoming
        if bad.empty:
            st.markdown(f"<div class='field-hint'>✅ <b>Campaign masih bisa dijalankan.</b> Dicek dengan data {fmt_date(today)}: "
                        f"{fmt_num(len(upcoming))} slot mendatang masih punya stok/sumber dan tidak melewati batas batal.</div>", unsafe_allow_html=True)
        else:
            st.warning(f"{fmt_num(len(bad))} dari {fmt_num(len(upcoming))} slot mendatang tidak bisa dijalankan dengan data {fmt_date(today)} "
                       "(stok habis, batal tinggi, atau harga). Ganti SKU di Shopee atau buat campaign baru dari saran.")
            show_table(bad.assign(Tanggal=bad["Tanggal"].map(fmt_date), **{"Kendala hari ini": bad["SKU"].astype(str).map(reasons).fillna("tidak lolos seleksi hari ini")})
                       [["Tanggal", "SKU", "Produk", "Kuota", "Kendala hari ini"]],
                       kinds={"Kuota": "count"}, column_config={"Produk": st.column_config.TextColumn(width="large"), "Kendala hari ini": st.column_config.TextColumn(width="large")})
            st.button("Buat campaign baru dari saran", key="fs-renew", on_click=cmp.switch_to_new, args=("flash",), type="primary")
        _flash_render(plan, skipped, start, end, key="fs-saved")
    else:
        tomorrow = today + timedelta(days=1)
        with st.container(border=True):
            start, end = cmp.period_picker(key="fs-period", today=today, default=(tomorrow, tomorrow + timedelta(days=13)))
            c2, c3, c4 = st.columns([1, 1.2, 1.4])
            per_day = int(c2.number_input("SKU per hari", min_value=2, max_value=20, value=5, step=1, key="fs-per-day",
                                          help="Tanggal kembar, gajian (25), dan Harbolnas mendapat +3 SKU."))
            share = c3.slider("Porsi slot untuk stok berlebih", 0, 70, 40, step=10, key="fs-share", format="%d%%",
                              help="Sisa slot diisi produk pendorong omzet (laris). Bila kandidat salah satu habis, slot diisi yang lain.") / 100
            rule = c4.radio("Aturan harga flash", FLASH_RULES, index=1, horizontal=True, key="fs-rule",
                            help="Tidak di bawah impas (bawaan): produk yang tidak punya ruang diskon ≥ 5% di atas harga impas tidak dijadwalkan. "
                                 "Prioritas omzet: produk itu tetap ikut dengan diskon minimal 5% dan rugi per unit dicatat di kolom Margin/unit.")
        cands, skipped = flash.candidates(items, excluded=data.excluded, below_floor=rule == FLASH_RULES[0])
        plan = flash.schedule(cands, start, today=today, days=(end - start).days + 1, per_day=per_day, clear_share=share)
        _flash_render(plan, skipped, start, end, key="fs-new")
        if not plan.empty and features is not None:
            cmp.save_controls("flash", features=features, today=today, start=start, end=end, cur=cur, can_edit=can_edit, username=username,
                              default_name=f"Flash sale {fmt_date(start)} – {fmt_date(end)}",
                              payload={"setelan": {"per_hari": per_day, "porsi": share, "aturan": rule},
                                       "jadwal": cmp.records_of(plan), "tidak_dijadwalkan": cmp.records_of(skipped)})
    with st.expander("Cara jadwal disusun"):
        explain([
            ("Campaign", "jadwal yang disimpan terkunci untuk periodenya dan menjadi acuan harian. Tiap hari slot mendatang dicek dengan stok & batal terbaru; "
                         "bila ada kendala, ganti SKU atau buat campaign baru (campaign lama otomatis dihentikan)"),
            ("Tujuan", f"habiskan stok lebih bila stok di atas SS cukup ≥ {flash.OVERSTOCK_DAYS} hari; selain itu pendorong omzet (urut prediksi omzet × tren 14 hari)"),
            ("Kuota", "pendorong: maks(3, 3 × prediksi harian); habiskan stok: 20% kelebihan stok 30 hari (5–100 unit)"),
            ("Sumber stok", "stok toko di atas SS + kebutuhan 7 hari → transfer DC 10062/10036 (H-3) → kuota kecil maks. separuh stok di atas SS"),
            ("Harga", "diskon terbesar yang masih ≥ harga impas (File margin, margin 0, tanpa biaya iklan): pendorong 10/7/5%, habiskan stok 20/15/10/5%. "
                      "Prioritas omzet: bila tidak ada ruang, diskon minimal 5% dan rugi per unit tampil di kolom Margin/unit"),
            ("Jadwal", "tiap hari, +3 SKU di tanggal kembar, gajian 25, Harbolnas; SKU sama berjarak ≥ 7 hari (≥ 3 hari bila kandidat kurang); "
                       "jam ramai 12.00–14.00 dan 20.00–22.00"),
            ("Batal", "batas = maks(15%, 1,5 × rata-rata batal toko tertimbang omzet), karena produk bulky wajar batal 25–35%; "
                      "SKU dengan batal > 15% diberi batas beli 1/pembeli dan perlu dikejar bayar"),
            ("Tidak dijadwalkan", "SKU jasa, tidak terjual 90 hari, batal di atas batas, stok 0 dan DC kosong, atau harga impas tanpa ruang diskon; unduh daftarnya untuk restock"),
        ])


# ---------------------------------------------------------------- Exposure (4D)


def _exposure_items(table: pd.DataFrame, data: FeatureData, orders: pd.DataFrame | None, frames, today: date) -> pd.DataFrame:
    items = _flash_items(table, data, orders, today)
    descriptions = getattr(frames, "descriptions", pd.DataFrame())
    lookup = {}
    if descriptions is not None and not descriptions.empty and {"sku", "description"} <= set(descriptions.columns):
        lookup = dict(zip(descriptions["sku"].astype(str).str.replace(r"\.0+$", "", regex=True), descriptions["description"]))
    extra = table[["sku"]].astype(str).assign(
        klik=pd.to_numeric(table.get("klik", 0), errors="coerce").fillna(0.0).to_numpy(),
        terjual_iklan=pd.to_numeric(table.get("terjual_iklan", 0), errors="coerce").fillna(0.0).to_numpy(),
    ).drop_duplicates("sku").set_index("sku")
    items["klik"] = items["sku"].map(extra["klik"]).fillna(0.0)
    items["terjual_iklan"] = items["sku"].map(extra["terjual_iklan"]).fillna(0.0)
    items["margin_pct"] = [_margin_of(data, s, np.nan)[0] for s in items["sku"]]
    items["poin_deskripsi"] = [features_from_description(lookup.get(s, "")) for s in items["sku"]]
    return items


SEGMENT_ICON = {expo.HERO: "⭐", expo.RISING: "📈", expo.OVERSTOCK: "📦", expo.LOW_CONV: "🎯"}


def _brief_picker(plan: pd.DataFrame, start: date, *, key: str) -> None:
    """Pilih konten untuk brief: saring per minggu, segmen, kategori, atau cari nama/SKU, lalu pilih dari daftar yang tersisa."""
    from datetime import timedelta

    st.markdown("**Brief konten**")
    monday = start - timedelta(days=start.weekday())
    week_no = plan["Tanggal"].map(lambda d: (d - monday).days // 7 + 1).astype(int)
    weeks = sorted(int(w) for w in week_no.unique())
    week_label = {w: f"Minggu {w} · {fmt_date(monday + timedelta(days=7 * (w - 1)))}" for w in weeks}
    f1, f2, f3, f4 = st.columns([1.1, 1.2, 1.2, 1.5])
    week = f1.selectbox("Minggu", [0] + weeks, key=f"{key}-week", format_func=lambda w: "Semua minggu" if w == 0 else week_label[w])
    segs = f2.multiselect("Segmen", [s for s in expo.SEGMENTS if (plan["Segmen"] == s).any()], key=f"{key}-seg", placeholder="Semua segmen",
                          format_func=lambda s: f"{SEGMENT_ICON.get(s, '')} {s}")
    cats = f3.multiselect("Kategori", sorted(plan["Kategori"].astype(str).unique()), key=f"{key}-cat", placeholder="Semua kategori")
    query = f4.text_input("Cari produk / SKU", key=f"{key}-q", placeholder="mis. kloset, FSA0089").strip().lower()
    mask = pd.Series(True, index=plan.index)
    if week:
        mask &= week_no == week
    if segs:
        mask &= plan["Segmen"].isin(segs)
    if cats:
        mask &= plan["Kategori"].astype(str).isin(cats)
    if query:
        mask &= (plan["Produk"].astype(str).str.lower().str.contains(query, regex=False) | plan["SKU"].astype(str).str.lower().str.contains(query, regex=False))
    options = plan.index[mask].tolist()
    if not options:
        st.info("Tidak ada konten yang cocok dengan saringan ini.")
        return
    chosen = st.selectbox(f"Pilih konten · {fmt_num(len(options))} cocok", options, key=f"{key}-pick",
                          format_func=lambda i: f"{SEGMENT_ICON.get(plan.loc[i, 'Segmen'], '')} {plan.loc[i, 'Hari']} {plan.loc[i, 'Tanggal'].day}/{plan.loc[i, 'Tanggal'].month} "
                                                f"{plan.loc[i, 'Jam tayang']} · {plan.loc[i, 'Produk']}")
    if chosen not in plan.index:
        chosen = options[0]
    row = plan.loc[chosen]
    with st.container(border=True):
        st.markdown(f"{SEGMENT_ICON.get(row['Segmen'], '')} **{html.escape(str(row['Segmen']))}** · {html.escape(str(row['Produk']))}")
        st.markdown(f"**Kenapa produk ini:** {html.escape(str(row['Alasan dipilih']))}  \n"
                    f"**Format:** {html.escape(str(row['Format']))}  \n"
                    f"**Tayang:** {row['Hari']} {fmt_date(row['Tanggal'])}, {row['Jam tayang']} (unggah ±1 jam sebelumnya)  \n"
                    f"**Hook:** _{html.escape(str(row['Hook']))}_  \n"
                    f"**Poin jual:** {html.escape(str(row['Poin jual']))}  \n"
                    f"**Ajakan:** {html.escape(str(row['Ajakan']))}  \n"
                    f"**Hashtag:** {html.escape(str(row['Hashtag']))}")
        st.caption("Naskah 30 detik (salin lewat ikon di pojok kanan):")
        st.code(str(row["Naskah 30 dtk"]) + "\n\n" + str(row["Hashtag"]), language=None, wrap_lines=True)


def _exposure_render(plan: pd.DataFrame, delayed: pd.DataFrame, start: date, end: date, *, key: str, per_week: int, peak: str) -> None:
    from datetime import timedelta

    from src.ui.common import card

    if plan.empty:
        st.warning("Belum ada produk yang siap dibuatkan konten di periode ini (terjual 90 hari terakhir dan stok ≥ 14 hari). Lihat daftar ditunda di bawah.")
    else:
        counts = plan.drop_duplicates("SKU")["Segmen"].value_counts().to_dict()
        chips = "".join(_chip(SEGMENT_ICON[s], s, "#0f172a", f"{fmt_num(counts.get(s, 0))} produk") for s in expo.SEGMENTS if counts.get(s))
        st.markdown("<div style='display:flex;flex-wrap:wrap;gap:.45rem;margin:.2rem 0 .6rem'>" + chips + "</div>", unsafe_allow_html=True)
        k = st.columns(4)
        card(k[0], "Konten terjadwal", fmt_num(len(plan)), hint=f"{(end - start).days + 1} hari · {per_week} per minggu")
        card(k[1], "Produk diangkat", fmt_num(plan["SKU"].nunique()), hint="tidak diulang dalam 14 hari")
        card(k[2], "Omzet 30 hari produknya", fmt_idr(plan.drop_duplicates("SKU")["Omzet 30 hari"].sum()), hint="prediksi analisa: yang dijaga & didorong konten")
        card(k[3], "Jam ramai toko", peak, hint="dari riwayat pesanan; unggah ±1 jam sebelumnya")
        st.markdown("**Kalender konten**")
        head = st.columns(7)
        for column, name in zip(head, expo.WEEKDAYS):
            column.markdown(f"<div style='text-align:center;font-size:var(--fs-xs);color:#64748b;font-weight:700'>{name}</div>", unsafe_allow_html=True)
        monday = start - timedelta(days=start.weekday())
        for week in range(((end - monday).days // 7) + 1):
            cols = st.columns(7)
            for offset, column in enumerate(cols):
                day = monday + timedelta(days=7 * week + offset)
                inside = start <= day <= end
                part = plan.loc[plan["Tanggal"] == day]
                lines = "".join(
                    f"<div title='{html.escape(str(p))}' style='font-size:var(--fs-xs);line-height:1.3;margin-top:4px;overflow-wrap:anywhere'>"
                    f"{SEGMENT_ICON.get(s, '')} <b>{html.escape(j)}</b><br>{html.escape(_clip(str(p).split(' · ')[1] if ' · ' in str(p) else p, 44))}</div>"
                    for p, s, j in zip(part["Produk"], part["Segmen"], part["Jam tayang"]))
                empty = "<div style='color:#cbd5e1;font-size:var(--fs-xs)'>–</div>"
                column.markdown(f"<div style='border:1px solid #e2e8f0;border-radius:8px;padding:6px;min-height:110px;background:{'#fff' if inside else '#f8fafc'};"
                                f"opacity:{1 if inside else .45}'><b>{day.day}/{day.month}</b>{lines or empty}</div>", unsafe_allow_html=True)
        st.caption("⭐ produk andalan · 📈 sedang naik · 📦 stok lebih · 🎯 banyak dilihat, jarang dibeli · tanggal pudar = di luar periode")
        _brief_picker(plan, start, key=key)
        shown = plan.assign(Tanggal=plan["Tanggal"].map(fmt_date)).drop(columns=["Naskah 30 dtk"])
        batched_view(
            len(shown), key=f"{key}-plan", noun="konten",
            render=lambda lo, hi: show_table(shown.iloc[lo:hi], kinds={"Omzet 30 hari": "money", "Stok siap (hari)": "count"}, max_height=10_000,
                                             column_config={"Produk": st.column_config.TextColumn(width="large"), "Format": st.column_config.TextColumn(width="large"),
                                                            "Hook": st.column_config.TextColumn(width="large"), "Poin jual": st.column_config.TextColumn(width="large")}),
            download=lambda: download_excel({"Brief konten": plan, "Ditunda (stok)": delayed}, f"brief_konten_{start.isoformat()}.xlsx", key=f"xl-{key}"),
        )
    if delayed is not None and not delayed.empty:
        with st.expander(f"Tidak dijadwalkan (ditunda karena stok) · {fmt_num(len(delayed))} produk"):
            st.caption("Konten untuk produk yang stoknya hampir habis justru membuang penonton: restock dulu, lalu jadwalkan.")
            batched_view(
                len(delayed), key=f"{key}-delay", noun="produk",
                render=lambda lo, hi: show_table(delayed.iloc[lo:hi], max_height=10_000, column_config={"SKU · produk · varian": st.column_config.TextColumn(width="large")}),
                download=lambda: download_excel(delayed, f"konten_tidak_dijadwalkan_{start.isoformat()}.xlsx", key=f"xl-{key}-delay", label="Unduh SKU tidak dijadwalkan"),
            )


def _exposure_describe(c: dict) -> str:
    rows = c.get("jadwal") or []
    s = c.get("setelan", {}) or {}
    return (f"{fmt_num(s.get('per_minggu', 0))} konten/minggu · {fmt_num(len(rows))} konten · "
            f"{fmt_num(len({r.get('SKU') for r in rows}))} produk")


def show_exposure(table: pd.DataFrame, *, features, data: FeatureData, orders: pd.DataFrame | None, frames, today: date, username: str, can_edit: bool) -> None:
    from datetime import timedelta

    from src.ui import campaign_ui as cmp

    st.markdown("<div class='section-title'>Exposure Shopee Video & media sosial</div>", unsafe_allow_html=True)
    if table is None or table.empty:
        st.write("Jalankan analisa terlebih dahulu.")
        return
    st.caption("Produk yang paling layak dibuatkan konten, jadwal tayang mengikuti jam ramai pesanan, dan brief siap pakai "
               "(hook, poin jual, ajakan, hashtag, naskah 30 detik). Hanya produk dengan stok siap ≥ 14 hari (toko + DC).")
    cmp.flash_message("exposure")
    mode, cur = cmp.panel("exposure", features=features, today=today, can_edit=can_edit, username=username, describe=_exposure_describe)
    items = _exposure_items(table, data, orders, frames, today)
    cands, delayed = expo.pick(items)
    cat_by_sku = dict(zip(items["sku"], items["nama"].map(expo.category_of)))
    times = expo.timing(orders.assign(sku=orders["sku"].astype(str)) if orders is not None and not orders.empty and "sku" in orders.columns else None, cat_by_sku)
    dow, hours = times["*"]
    peak = f"{expo.WEEKDAYS[dow]} {hours}"
    if mode == cmp.SAVED and cur is not None:
        start, end = as_date(cur["mulai"]), as_date(cur["selesai"])
        plan = cmp.frame_of(cur.get("jadwal"), ("Tanggal",))
        saved_delayed = cmp.frame_of(cur.get("ditunda"))
        upcoming = plan.loc[plan["Tanggal"] >= today] if not plan.empty else plan
        bad = upcoming.loc[~upcoming["SKU"].astype(str).isin(set(cands["sku"].astype(str)))] if not upcoming.empty else upcoming
        if bad.empty:
            st.markdown(f"<div class='field-hint'>✅ <b>Campaign masih sesuai.</b> Dicek dengan data {fmt_date(today)}: "
                        f"{fmt_num(len(upcoming))} konten mendatang produknya masih punya stok siap ≥ {expo.READY_DAYS} hari.</div>", unsafe_allow_html=True)
        else:
            st.warning(f"{fmt_num(len(bad))} dari {fmt_num(len(upcoming))} konten mendatang produknya kini stok siap < {expo.READY_DAYS} hari atau tidak terjual: "
                       "ganti produknya atau buat campaign baru dari saran.")
            show_table(bad.assign(Tanggal=bad["Tanggal"].map(fmt_date))[["Tanggal", "Jam tayang", "SKU", "Produk", "Segmen"]],
                       column_config={"Produk": st.column_config.TextColumn(width="large")})
            st.button("Buat campaign baru dari saran", key="ex-renew", on_click=cmp.switch_to_new, args=("exposure",), type="primary")
        _exposure_render(plan, saved_delayed, start, end, key="ex-saved", per_week=int((cur.get("setelan") or {}).get("per_minggu", 5)), peak=peak)
    else:
        next_monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
        with st.container(border=True):
            c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
            with c1:
                start, end = cmp.period_picker(key="ex-period", today=today, default=(next_monday, next_monday + timedelta(days=27)))
            per_week = int(c2.number_input("Konten per minggu", min_value=2, max_value=14, value=5, step=1, key="ex-per-week"))
        monday = start - timedelta(days=start.weekday())
        plan = expo.calendar(cands, monday, weeks=(end - monday).days // 7 + 1, per_week=per_week, times=times)
        if not plan.empty:
            plan = plan.loc[(plan["Tanggal"] >= start) & (plan["Tanggal"] <= end)].reset_index(drop=True)
        _exposure_render(plan, delayed, start, end, key="ex-new", per_week=per_week, peak=peak)
        if not plan.empty and features is not None:
            def _to_schedule(campaign: dict) -> None:
                rows = pd.DataFrame({"periode": plan["Tanggal"].map(_periode), "tanggal": plan["Tanggal"], "sku": plan["SKU"], "label": plan["Produk"].str[:400],
                                     "kanal": plan["Format"].str.split(":").str[0].str[:40], "kategori": plan["Kategori"], "spesial": plan["Segmen"].str[:60],
                                     "saved_by": username})
                for periode in rows["periode"].unique():
                    features.remove("exposure_schedule", {"periode": periode}, username=username, action="hapus:jadwal_exposure")
                features.insert("exposure_schedule", rows, username=username, action="simpan:jadwal_exposure")

            cmp.save_controls("exposure", features=features, today=today, start=start, end=end, cur=cur, can_edit=can_edit, username=username,
                              default_name=f"Konten {fmt_date(start)} – {fmt_date(end)}", after_save=_to_schedule,
                              payload={"setelan": {"per_minggu": per_week}, "jadwal": cmp.records_of(plan), "ditunda": cmp.records_of(delayed)})
    with st.expander("Cara produk & jadwal dipilih"):
        explain([
            ("Campaign", "jadwal konten yang disimpan terkunci untuk periodenya; tiap hari konten mendatang dicek dengan stok terbaru. "
                         "Buat campaign baru bila ada kendala (campaign lama otomatis dihentikan)"),
            ("Syarat", f"terjual 90 hari terakhir dan stok toko + DC cukup ≥ {expo.READY_DAYS} hari"),
            ("Segmen", "andalan = prediksi omzet top 30; sedang naik = tren 14 hari ≥ +30%; stok lebih = stok di atas SS ≥ 90 hari; "
                       "banyak dilihat jarang dibeli = klik iklan ≥ 50 dan konversi < 1%"),
            ("Skor", "40% peringkat prediksi omzet + 20% margin + 20% tren 14 hari + 10% kesiapan stok + 10% bonus segmen naik/stok lebih"),
            ("Jadwal", "tiap minggu bergilir antar segmen; hari & jam = waktu pesanan terbanyak untuk kategori produk itu; maks. 2 konten per hari; "
                       "produk sama tidak diulang dalam 14 hari"),
            ("Brief", "format & hook per kategori bahan bangunan, poin jual dari nama (garansi, packing kayu, material, ukuran) dan deskripsi produk"),
        ])


# ---------------------------------------------------------------- Ranking kategori (4E)


def _own_ratings(competitors: pd.DataFrame) -> dict[str, float]:
    if competitors is None or competitors.empty or not {"own_shop", "product_name", "rating"} <= set(competitors.columns):
        return {}
    own = competitors.loc[competitors["own_shop"].astype(str).str.lower().isin({"true", "1"})]
    rating = pd.to_numeric(own["rating"].astype(str).str.replace(",", "."), errors="coerce")
    return {str(n).strip().lower(): float(r) for n, r in zip(own["product_name"], rating) if pd.notna(r) and r <= 5}


def _competitor_median(competitors: pd.DataFrame, name: str) -> float | None:
    if competitors is None or competitors.empty or "price" not in competitors.columns:
        return None
    keyword = ranking_score.keyword_of(name)
    if not keyword:
        return None
    others = competitors
    if "own_shop" in others.columns:
        others = others.loc[~others["own_shop"].astype(str).str.lower().isin({"true", "1"})]
    first = keyword.split()[0]
    match = others.loc[others["product_name"].astype(str).str.lower().str.contains(first, regex=False)]
    prices = pd.to_numeric(match["price"].astype(str).str.replace(r"[^\d]", "", regex=True), errors="coerce").dropna().head(5)
    return float(prices.median()) if not prices.empty else None


def _rank_catalog(table: pd.DataFrame) -> pd.DataFrame:
    t = table.copy()
    t["_q"] = pd.to_numeric(t.get("pred_harian", 0), errors="coerce").fillna(0.0) * 30
    t["_o"] = t["_q"] * pd.to_numeric(t.get("harga_bersih", 0), errors="coerce").fillna(0.0)
    cost = pd.to_numeric(t.get("biaya_iklan_90", 0), errors="coerce").fillna(0.0) + pd.to_numeric(t.get("biaya_iklan", 0), errors="coerce").fillna(0.0)
    t["_ads"] = cost > 0
    t["_stok"] = pd.to_numeric(t.get("stok"), errors="coerce").where(t.get("ada_data_stok", False).fillna(False).astype(bool))
    return (t.groupby("product_name", as_index=False)
             .agg(sku=("sku", lambda v: ", ".join(dict.fromkeys(str(x) for x in v))), n_sku=("sku", "nunique"), qty_bulan=("_q", "sum"), omzet_bulan=("_o", "sum"), stok=("_stok", lambda v: v.sum(min_count=1)),
                  harga=("harga_bersih", "median"), iklan=("_ads", "any"))
             .assign(ada_stok=lambda f: f["stok"].notna())
             .rename(columns={"product_name": "nama"}))


TIER_COLOR = {"Sudah Top 10": "#1d4ed8", "Dekat": "#15803d", "Menengah": "#b45309", "Jauh": "#dc2626"}


def show_ranking(table: pd.DataFrame, *, features, frames, username: str, can_edit: bool) -> None:
    from src.core import category_rank as rk
    from src.ui.common import card

    st.markdown("<div class='section-title'>Ranking kategori · target Top 10</div>", unsafe_allow_html=True)
    competitors = getattr(frames, "competitors", pd.DataFrame())
    if competitors is None or competitors.empty:
        st.info("Data ranking kategori belum diunggah (Upload data › Kompetitor). Isinya: daftar ranking kategori Shopee, peringkat, toko, nama produk, dan baris toko sendiri.")
    elif table is not None and not table.empty:
        stamp = pd.to_datetime(competitors.get("_submitted_at"), errors="coerce").max() if "_submitted_at" in competitors.columns else None
        catalog = _rank_catalog(table)
        summary, opp = rk.analyze(competitors, catalog)
        products, missing = rk.by_product(competitors, catalog, summary, opp)
        n_sku = int(table["sku"].astype(str).nunique())
        in_rank = products.loc[products["Status"] != rk.UNRANKED]
        st.caption(f"Katalog saat ini {fmt_num(len(products))} produk ({fmt_num(n_sku)} SKU). {fmt_num(len(in_rank))} produk "
                   f"({fmt_num(int(in_rank['Jumlah SKU'].sum()))} SKU) muncul di {fmt_num(len(summary))} daftar ranking kategori Shopee"
                   + (f" (unggahan {fmt_date(stamp)})" if stamp is not None and pd.notna(stamp) else "") + ".")
        counts = products["Status"].value_counts().to_dict()
        skus = products.groupby("Status")["Jumlah SKU"].sum().to_dict()
        k = st.columns(5)
        card(k[0], "Sudah Top 10", fmt_num(counts.get("Sudah Top 10", 0)),
             hint=f"{fmt_num(skus.get('Sudah Top 10', 0))} SKU · {fmt_num(int((summary['Status'] == 'Sudah Top 10').sum()))} kategori · pertahankan")
        card(k[1], "Dekat (11–50)", fmt_num(counts.get("Dekat", 0)), hint=f"{fmt_num(skus.get('Dekat', 0))} SKU · peluang tercepat")
        card(k[2], "Menengah (51–500)", fmt_num(counts.get("Menengah", 0)), hint=f"{fmt_num(skus.get('Menengah', 0))} SKU · iklan + flash sale + judul")
        card(k[3], "Jauh (> 500)", fmt_num(counts.get("Jauh", 0)), hint=f"{fmt_num(skus.get('Jauh', 0))} SKU")
        card(k[4], rk.UNRANKED, fmt_num(counts.get(rk.UNRANKED, 0)), hint=f"{fmt_num(skus.get(rk.UNRANKED, 0))} SKU · tidak ada di daftar yang diunggah")

        st.markdown("**Peluang masuk Top 10 per produk**")
        groups = sorted(products["Kelompok"].astype(str).unique())
        f1, f2, f3, f4 = st.columns([1.1, 1.6, 1.3, 1.2])
        group_pick = f1.multiselect("Kelompok kategori", groups, key="rk-group", placeholder="Semua kelompok")
        base = products.loc[products["Kelompok"].isin(group_pick)] if group_pick else products
        pairs = sorted({(g, c) for g, c in zip(base["Kelompok"].astype(str), base["Kategori"].astype(str))})
        cat_pick = f2.multiselect("Kategori ranking", [f"{g} › {c}" for g, c in pairs], key="rk-cat", placeholder="Semua kategori")
        status_pick = f3.multiselect("Status", list(rk.STATUS_ORDER), default=["Sudah Top 10", "Dekat", "Menengah"], key="rk-tier", placeholder="Semua status")
        query = f4.text_input("Cari produk / SKU", key="rk-q").strip().lower()
        view = base
        if cat_pick:
            view = view.loc[(view["Kelompok"].astype(str) + " › " + view["Kategori"].astype(str)).isin(cat_pick)]
        if status_pick:
            view = view.loc[view["Status"].isin(status_pick)]
        if query:
            view = view.loc[view["Produk"].astype(str).str.lower().str.contains(query, regex=False) | view["SKU"].astype(str).str.lower().str.contains(query, regex=False)]
        view = view.sort_values(["Kelompok", "Kategori"], kind="stable").reset_index(drop=True)
        st.caption(f"{fmt_num(len(view))} produk · {fmt_num(int(view['Jumlah SKU'].sum()))} SKU sesuai saringan · urut kelompok › kategori › status › peringkat")
        batched_view(
            len(view), key="rk-opp", noun="produk",
            render=lambda lo, hi: show_table(view.iloc[lo:hi], kinds={"Penjualan/bulan": "count", "Perlu/bulan (perkiraan)": "count", "Kali lipat": "dec", "Stok": "count",
                                                                     "Peringkat": "count", "Daftar": "count", "Jumlah SKU": "count"}, max_height=10_000,
                                             column_config={"Produk": st.column_config.TextColumn(width="large"), "Langkah": st.column_config.TextColumn(width="large"),
                                                            "SKU": st.column_config.TextColumn(width="small"),
                                                            "Penjualan/bulan": st.column_config.Column(help="Prediksi unit per bulan dari analisa (semua SKU produk ini)"),
                                                            "Perlu/bulan (perkiraan)": st.column_config.Column(help="Perkiraan unit/bulan di peringkat 10: penjualan ≈ berbanding terbalik dengan peringkat (patokan produk kita yang sudah Top 10 di daftar yang sama bila ada)"),
                                                            "Kali lipat": st.column_config.Column(help="Berapa kali penjualan sekarang yang dibutuhkan untuk peringkat 10"),
                                                            "Daftar lain": st.column_config.Column(help="Peringkat produk ini di daftar ranking lain")}),
            download=lambda: download_excel({"Produk": products, "Ringkasan kategori": summary, "Di ranking, tidak di katalog": missing},
                                            "ranking_kategori_top10.xlsx", key="xl-rk"),
        )
        if not missing.empty:
            st.caption(f"{fmt_num(len(missing))} produk Mitra10 di data ranking tidak ditemukan di katalog analisa saat ini (nama berubah / tidak dijual lagi); ada di unduhan Excel.")

        st.markdown("**Detail kategori**")
        lists = summary.copy()
        if group_pick:
            lists = lists.loc[lists["Kelompok"].isin(group_pick)] if lists["Kelompok"].isin(group_pick).any() else lists
        lists = lists.sort_values(["Kelompok", "Kategori", "Daftar"]).reset_index(drop=True)
        options = lists["Daftar"].tolist()
        info = lists.set_index("Daftar")
        dekat = [d for d, s_ in zip(lists["Daftar"], lists["Status"]) if s_ == "Dekat"]
        first = dekat[0] if dekat else options[0]

        def _fmt(d: int) -> str:
            r = info.loc[d]
            best = f"produk kita terbaik #{int(r['Peringkat terbaik'])} ({r['Status']})" if pd.notna(r["Peringkat terbaik"]) else "belum ada produk kita"
            return f"{r['Kelompok']} › {r['Kategori']} · Daftar {d} · {best}"

        daftar = st.selectbox("Kategori", options, index=options.index(first), key="rk-list", format_func=_fmt)
        data = rk.prepare(competitors)
        part = data.loc[data["daftar"] == daftar].sort_values("rank")
        top = part.loc[part["rank"] <= rk.TOP]
        pat = rk.patterns(top if not top.empty else part.head(rk.TOP))
        tags = ", ".join(f"{label} {share * 100:.0f}%" for label, share in pat["tag"].items() if share > 0) or "–"
        st.markdown(
            "<div style='border:1px solid #e2e8f0;border-left:5px solid #ee4d2d;border-radius:12px;background:#fff;padding:.7rem 1rem;margin:.4rem 0;font-size:.92rem;line-height:1.6'>"
            f"<b>Pola Top 10</b> · official store {pat['official'] * 100:.0f}% · kata kunci di ≥ 30% judul: <b>{html.escape(', '.join(pat['kata'][:10]) or '–')}</b>"
            f" · tag di judul: {html.escape(tags)}</div>", unsafe_allow_html=True)
        c1, c2 = st.columns([1.1, 1])
        with c1:
            st.caption("Top 10 kategori ini")
            show_table(top.assign(Kita=top["ours"].map({True: "✓ Mitra10", False: ""}))
                       .rename(columns={"rank": "Peringkat", "change": "Perubahan", "shop": "Toko", "product": "Produk"})[["Peringkat", "Perubahan", "Toko", "Produk", "Kita"]],
                       kinds={"Peringkat": "count"}, column_config={"Produk": st.column_config.TextColumn(width="large")})
        with c2:
            st.caption("Produk kita di kategori ini (termasuk perkiraan yang belum masuk ranking)")
            mine = products.loc[products["Daftar"] == daftar, ["Status", "Peringkat", "Produk", "Jumlah SKU", "Penjualan/bulan", "Perlu/bulan (perkiraan)", "Kali lipat", "Langkah"]]
            show_table(mine, kinds={"Peringkat": "count", "Jumlah SKU": "count", "Penjualan/bulan": "count", "Perlu/bulan (perkiraan)": "count", "Kali lipat": "dec"},
                       column_config={"Produk": st.column_config.TextColumn(width="medium"), "Langkah": st.column_config.TextColumn(width="large")})
        with st.expander("Cara membaca"):
            explain([
                ("Sumber", "unggahan Kompetitor: tiap Daftar = satu ranking kategori Shopee (±20 teratas + produk toko sendiri)"),
                ("Jumlah produk", "satu baris per produk katalog analisa saat ini (varian digabung; kolom Jumlah SKU). Produk di beberapa daftar memakai peringkat terbaiknya"),
                ("Kelompok & kategori", "kelompok = jenis bahan bangunan dari nama produk; kategori = kata yang paling sering muncul di nama produk daftar itu "
                                        "(data tidak memuat nama kategori). Produk belum masuk ranking diberi kategori perkiraan dari kata kunci Top 10 yang paling cocok"),
                ("Status", "Sudah Top 10 (≤ 10) · Dekat (11–50) · Menengah (51–500) · Jauh (> 500) · Belum masuk ranking (tidak ada di daftar yang diunggah)"),
                ("Perlu/bulan", "perkiraan penjualan di peringkat 10 dengan pola penjualan ≈ 1/peringkat; bila ada produk kita yang sudah Top 10 di daftar itu, "
                                "penjualannya dipakai sebagai patokan. Angka perkiraan, bukan data Shopee"),
                ("Langkah", "urut: stok → iklan → flash sale → kata kunci judul yang dipakai ≥ 50% Top 10 → tag promo pesaing → konten"),
            ])
    with st.expander("Data lain: Brand Portal & skor kesiapan listing"):
        _brand_portal_and_readiness(table, features=features, frames=frames, username=username, can_edit=can_edit)


def _brand_portal_and_readiness(table: pd.DataFrame, *, features, frames, username: str, can_edit: bool) -> None:
    template = pd.DataFrame(columns=list(ranking_score.BRAND_COLUMNS))
    u1, u2 = st.columns([3, 1])
    upload = u1.file_uploader("Unggah ekspor Brand Portal (periode, kategori, brand, peringkat, pangsa)", type=["xlsx", "csv"], key="brand-upload", disabled=not can_edit)
    with u2:
        download_excel(template, "template_brand_portal.xlsx", key="xl-brand-tpl", label="Unduh template")
    if upload is not None and can_edit and st.button("Simpan data Brand Portal", key="brand-save", type="primary"):
        from auth.ui import require

        require("rekomendasi", "edit")
        raw = pd.read_csv(upload) if upload.name.lower().endswith(".csv") else pd.read_excel(upload)
        clean, problems = ranking_score.normalize_brand_portal(raw)
        if problems:
            st.error("; ".join(problems))
        else:
            for periode in clean["periode"].unique():
                features.remove("brand_portal", {"periode": periode}, username=username)
            features.insert("brand_portal", clean, username=username, action="unggah:brand_portal")
            st.success(f"{fmt_num(len(clean))} baris Brand Portal disimpan.")
    portal = features.read("brand_portal") if features is not None else pd.DataFrame()
    if portal.empty:
        st.caption("Data Brand Portal belum diunggah.")
    else:
        changes = ranking_score.brand_changes(portal)
        kategori = st.selectbox("Kategori", sorted(changes["kategori"].astype(str).unique()), key="brand-cat")
        part = changes.loc[changes["kategori"].astype(str) == kategori].rename(
            columns={"brand": "Brand", "peringkat": "Rank", "pangsa": "Pangsa (%)", "perubahan_peringkat": "Perubahan peringkat", "perubahan_pangsa": "Perubahan pangsa (poin)"}
        )
        show_table(part[[c for c in ("Brand", "Rank", "Pangsa (%)", "Perubahan peringkat", "Perubahan pangsa (poin)") if c in part.columns]])
    st.markdown("**Skor kesiapan ranking · Top 50 SKU**")
    st.caption("Shopee tidak memublikasikan bobot algoritma; skor ini indikator internal. Faktor tanpa data di sistem (atribut, video, ulasan berfoto, Gratis Ongkir) bernilai 0 dan ditandai –.")
    if table is None or table.empty:
        return
    competitors = getattr(frames, "competitors", pd.DataFrame())
    ratings = _own_ratings(competitors)
    rows = []
    for _, row in table.head(50).iterrows():
        rating = ratings.get(str(row["product_name"]).strip().lower())
        scores = ranking_score.readiness(row.to_dict(), rating=rating, competitor_median=_competitor_median(competitors, row["product_name"]))
        item = {"SKU": str(row["sku"]), "Produk": str(row["product_name"]), "Varian": str(row.get("variasi_tampil") or "")}
        for key, label, weight in ranking_score.FACTORS:
            value = scores[key]
            item[label.split(" (")[0]] = "–" if value is None else ("✓" if value >= weight else ("✗" if value == 0 else fmt_num(value, 1)))
        item["Skor"] = round(scores["skor"], 1)
        item["Langkah prioritas"] = ", ".join(ranking_score.priority_steps(scores, float(row.get("sales_total", 0) or 0)))
        rows.append(item)
    frame = pd.DataFrame(rows)
    # Kolom faktor yang seluruhnya "–" (belum ada data) disembunyikan dari tampilan; tetap ada di unduhan Excel.
    empty_cols = [c for c in frame.columns if c not in {"SKU", "Produk", "Varian", "Skor", "Langkah prioritas"} and frame[c].astype(str).eq("–").all()]
    shown = frame.drop(columns=empty_cols)
    if empty_cols:
        st.caption("Belum ada datanya, jadi tidak ditampilkan: " + ", ".join(empty_cols) + ".")
    batched_view(
        len(shown),
        key="rank",
        render=lambda lo, hi: show_table(shown.iloc[lo:hi], column_config={"Langkah prioritas": st.column_config.TextColumn(width="large")}),
        noun="SKU",
        download=lambda: download_excel(frame, "skor_kesiapan_ranking.xlsx", key="xl-rank"),
    )

