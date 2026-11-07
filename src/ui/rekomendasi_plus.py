"""Rekomendasi › Iklan (target & strategi), Flash sale toko, Exposure media sosial, Ranking kategori (4C–4E)."""

from __future__ import annotations

import html
import json
from datetime import date

import numpy as np
import pandas as pd
import streamlit as st

from src.core import ads_plan, promo_calendar, ranking_score
from src.core import margin as margin_core
from src.core.decision_table import stock_need
from src.core.fmt import fmt_date
from src.core.product_features import features_from_description, hook_for
from src.core.promo import momentum_14d, product_label, promo_eligible
from src.ui.common import card, download_excel, explain, fmt_idr, fmt_num
from src.ui.feature_data import FeatureData, bump, product_frame
from src.core.ads import roas_estimate
from src.utils.format import input_rupiah, show_table, wrap_layout

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
        return fallback, False
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


def show_ads_strategy(table: pd.DataFrame, *, features, data: FeatureData, params: dict, window_start: date, username: str, can_edit: bool) -> None:
    st.markdown("<div class='section-title'>Target penjualan & strategi iklan</div>", unsafe_allow_html=True)
    if table is None or table.empty:
        st.write("Jalankan analisa terlebih dahulu.")
        return
    periode = _periode(window_start)
    saved = data.target or {}
    c1, c2, c3 = st.columns([1.6, 1, 1])
    with c1:
        target = float(input_rupiah(f"Target sales bersih {_bulan_label(window_start)}", int(saved.get("target_sales_bersih", 0) or 0), key=f"tgt-rp-{periode}"))
    margin_min = float(c2.number_input("Margin minimum (%)", min_value=0.0, max_value=60.0, value=float(saved.get("margin_min_pct", 8.0) or 8.0), step=0.5, key=f"tgt-margin-{periode}"))
    c3.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
    if c3.button("Simpan target", key="tgt-save", type="primary", disabled=not can_edit, use_container_width=True):
        from auth.ui import require

        require("rekomendasi", "edit")
        features.replace(
            "sales_target",
            [{"periode": periode, "target_sales_bersih": target, "margin_min_pct": margin_min, "strategi": saved.get("strategi", ""), "budget_json": saved.get("budget_json", "{}"), "set_by": username}],
            keys=["periode"],
            username=username,
            action="simpan:target_sales",
        )
        bump(st.session_state)
        st.success("Target disimpan. Laporan memakai target ini.")
        st.rerun()
    predicted = float(table["m_sales_exp"].sum() if "m_sales_exp" in table.columns else table["m_sales"].sum())
    if target <= 0:
        st.info(f"Isi target sales bersih untuk menghitung strategi. Prediksi sales semua SKU pada jendela ini {fmt_idr(predicted)}.")
        return
    gap = target - predicted
    roas_default = float(params.get("iklan", {}).get("target_roas", 8) or 8)
    cands, known = _candidates(table, data, margin_min, roas_default)
    predicted_margin = 0.0
    for _, row in table.iterrows():
        pct, _ok = _margin_of(data, str(row["sku"]), margin_min)
        predicted_margin += float(row["m_sales"]) * pct / 100
    cols = st.columns(3)
    card(cols[0], "Target", fmt_idr(target))
    card(cols[1], "Prediksi sales (pola iklan saat ini)", fmt_idr(predicted), hint="semua SKU, jendela prediksi")
    card(cols[2], "Gap", fmt_idr(max(gap, 0)) if gap > 0 else "Tercapai", hint="target − prediksi" if gap > 0 else f"prediksi di atas target {fmt_idr(-gap)}")
    if gap <= 0:
        st.success("Prediksi sudah menutup target. Tambahan budget tidak wajib; gunakan strategi Efisien bila tetap ingin menambah.")
    with st.spinner("Menghitung tiga strategi (greedy + bootstrap 200×)..."):
        frame, plans = ads_plan.strategy_rows(cands, target=target, predicted_sales=predicted, predicted_margin=predicted_margin)
    view = frame.copy()
    view["Rentang omzet (p10–p90)"] = view["Rentang omzet (p10–p90)"].map(lambda v: f"{fmt_idr(v[0])} – {fmt_idr(v[1])}")
    view["Rentang ROAS"] = view["Rentang ROAS"].map(lambda v: f"{fmt_num(v[0], 1)} – {fmt_num(v[1], 1)}" if np.isfinite(v[0]) else "–")
    show_table(view, kinds={"Budget tambahan": "money", "Omzet tambahan (p50)": "money", "ROAS tambahan": "dec", "% target": "pct", "Margin strategi (%)": "pct"})
    explain(
        [
            ("Tambahan budget", "hanya untuk SKU yang masih untung: Rp 1 iklan tambahan kembali minimal Rp 1 margin (ROAS marginal × margin ≥ 1)"),
            ("Batas per SKU", f"maksimal {fmt_num(ads_plan.EXTRA_MULTIPLE, 0)}× budget saat ini"),
            ("Budget saat ini", "biaya iklan per hari (dari laporan iklan) × 30"),
            ("ROAS dasar", "60% ROAS 30 hari terakhir + 40% ROAS 90 hari (riwayat iklan)"),
        ]
    )
    with st.expander("Metode perhitungan"):
        explain(
            [
                ("Kurva respons", "omzet iklan harian = a · ln(1 + biaya harian ÷ b), titik awal = biaya & ROAS saat ini"),
                ("Alokasi", "bertahap Rp 500.000/bulan ke ROAS marginal × margin tertinggi, berhenti di titik impas"),
                ("Rentang", "persentil 10–90 dari 200× bootstrap residual"),
                ("Catatan data", "laporan iklan Shopee berupa total per periode (bukan harian), jadi kurva belum di-fit per SKU"),
            ]
        )
    if not known.empty and not known["known_margin"].any():
        st.caption(f"Komponen biaya belum diunggah (Setting › Kalkulator biaya): margin semua SKU memakai margin minimum {fmt_num(margin_min, 1)}%.")
    choice = st.radio("Strategi", list(plans), index=list(plans).index("Efisien"), horizontal=True, key="tgt-strategy")
    plan = plans.get(choice, {})
    rows = []
    for cand in cands:
        extra = float(plan.get(cand.sku, 0.0))
        decision = cand.decision
        if decision in ("Iklankan", "Dibatasi stok") and extra <= 0 and not ads_plan.is_profitable(cand):
            decision = "Jangan tambah (di bawah titik impas)"
        rows.append(
            {
                "SKU · produk · varian": cand.label,
                "Keputusan": decision,
                "Budget saat ini / bulan": cand.daily_cost * ads_plan.DAYS,
                "Budget tambahan": float(plan.get(cand.sku, 0.0)),
                "ROAS marginal": cand.curve.marginal(cand.daily_cost + plan.get(cand.sku, 0.0) / ads_plan.DAYS),
                "_sku": cand.sku,
            }
        )
    alloc = pd.DataFrame(rows)
    alloc = alloc.sort_values(["Budget tambahan", "Budget saat ini / bulan"], ascending=False)
    limit = int(st.session_state.get("tgt-limit", STEP))
    page = alloc.head(limit)
    alloc_cfg = {
        "SKU · produk · varian": st.column_config.TextColumn(width="large"),
        "Budget saat ini / bulan": st.column_config.NumberColumn(format="localized"),
        "Budget tambahan": st.column_config.NumberColumn(format="localized", step=500_000, min_value=0),
        "ROAS marginal": st.column_config.NumberColumn(format="%.1f"),
    }
    alloc_row, alloc_cfg = wrap_layout(page.drop(columns="_sku"), alloc_cfg)
    edited = st.data_editor(
        page.drop(columns="_sku"),
        row_height=alloc_row,
        hide_index=True,
        use_container_width=True,
        disabled=["SKU · produk · varian", "Keputusan", "Budget saat ini / bulan", "ROAS marginal"],
        column_config=alloc_cfg,
        key=f"tgt-alloc-{choice}-{limit}",
    )
    if limit < len(alloc) and st.button("Muat 20 SKU lagi", key="tgt-more"):
        st.session_state["tgt-limit"] = limit + STEP
        st.rerun()
    final = dict(plan)
    for sku, value in zip(page["_sku"], edited["Budget tambahan"]):
        final[sku] = float(value or 0)
    strategy_budget = float(frame.set_index("Strategi").loc[choice, "Budget tambahan"])
    product_total = float(sum(final.values()))
    g1, g2 = st.columns([1, 2])
    with g1:
        group = float(input_rupiah("Iklan grup", 0, key="tgt-group"))
    total = product_total + group
    g2.markdown(
        "<div class='stat-card'><div class='readable-metric-label'>Rincian budget</div>"
        f"<div style='font-size:var(--fs-base)'>Iklan produk {fmt_idr(product_total)} + iklan grup {fmt_idr(group)} = <b>{fmt_idr(total)}</b><br>"
        f"Budget strategi {html.escape(choice)} {fmt_idr(strategy_budget)} · sisa <b>{fmt_idr(strategy_budget - total)}</b></div></div>",
        unsafe_allow_html=True,
    )
    if st.button("Kirim ke rencana iklan", key="tgt-send", type="primary", disabled=not can_edit):
        from auth.ui import require

        require("rekomendasi", "edit")
        budget = {"strategi": choice, "iklan_produk": {k: v for k, v in final.items() if v > 0}, "iklan_grup": group, "total": total}
        features.replace(
            "sales_target",
            [{"periode": periode, "target_sales_bersih": target, "margin_min_pct": margin_min, "strategi": choice, "budget_json": json.dumps(budget), "set_by": username}],
            keys=["periode"],
            username=username,
            action="kirim:rencana_iklan",
        )
        bump(st.session_state)
        st.success(f"Rencana iklan {choice} ({fmt_idr(total)}) disimpan untuk {periode}.")
    download_excel({"Strategi": view, "Alokasi": alloc.drop(columns="_sku")}, f"strategi_iklan_{periode}.xlsx", key="xl-tgt")


# ---------------------------------------------------------------- Flash sale (4D)


def show_flash_sale(table: pd.DataFrame, *, data: FeatureData, today: date) -> None:
    st.markdown("<div class='section-title'>Flash sale toko</div>", unsafe_allow_html=True)
    if table is None or table.empty:
        st.write("Jalankan analisa terlebih dahulu.")
        return
    products = product_frame(table).set_index("sku")
    candidates, skipped = [], []
    for _, row in table.head(CANDIDATE_LIMIT).iterrows():
        sku = str(row["sku"])
        price = float(products.loc[sku, "price"]) if sku in products.index and not isinstance(products.loc[sku, "price"], pd.Series) else float(row.get("harga_bersih", 0) or 0)
        comp = margin_core.effective_components(data.components, sku, on=today) if not data.components.empty else None
        ad = data.ad_per_unit.get(sku, 0.0)
        floor = margin_core.harga_minimal(comp, ad, 0.0) if comp else None
        flash = promo_calendar.flash_price(price, 0.10, floor)
        flash_margin = margin_core.unit_margin(flash, comp, ad)[1] if comp and flash > 0 else None
        ok, reasons, _decision = promo_eligible(row, excluded=data.excluded, margin_pct=data.margin_pct.get(sku), cancel_pct=row.get("batal_pct"), mode="flash", flash_margin_pct=flash_margin)
        stok = float(row["stok"]) if bool(row.get("ada_data_stok", False)) else 0.0
        quota = promo_calendar.flash_quota(stok, float(row["ss"]), float(row["pred_harian"]), float(row["m_qty"]))
        po = data.po.get(sku)
        quota_po = promo_calendar.flash_quota(stok + (po["qty"] if po else 0), float(row["ss"]), float(row["pred_harian"]), float(row["m_qty"]))
        if not ok and not (po and quota_po > 0 and reasons == ["Stok kurang"]):
            skipped.append({"SKU · produk · varian": _label(row), "Alasan": ", ".join(reasons)})
            continue
        if quota <= 0 and quota_po <= 0:
            skipped.append({"SKU · produk · varian": _label(row), "Alasan": "Kuota ≤ 0 setelah SS dan kebutuhan 7 hari"})
            continue
        candidates.append({"sku": sku, "label": _label(row), "kuota": quota, "kuota_setelah_po": quota_po, "harga": price, "harga_flash": flash, "skor": float(row["m_sales"])})
    explain(
        [
            ("Diskon", "awal 10%, tidak di bawah harga impas"),
            ("Slot", "2 jam di tanggal kembar, gajian (25), dan Harbolnas; maks. 2 SKU per slot"),
            ("Jeda", "SKU yang sama tidak dua kali dalam 7 hari"),
            ("Kuota", "min(stok − SS − prediksi harian × 7, 10% prediksi jendela); hanya SKU dengan stok sisa yang dijadwalkan"),
            "SKU yang tidak dijadwalkan dan alasannya ada di bawah tabel.",
        ]
    )
    po_eta = {sku: po["eta"] for sku, po in data.po.items() if po.get("eta")}
    schedule = promo_calendar.schedule_flash(pd.DataFrame(candidates, columns=["sku", "label", "kuota", "kuota_setelah_po", "harga", "harga_flash", "skor"]), today, po_eta=po_eta)
    if schedule.empty:
        st.info("Belum ada SKU yang lolos syarat flash sale (stok, margin flash ≥ 0, batal ≤ 15%).")
    else:
        view = schedule.copy()
        view["Tanggal"] = view["Tanggal"].map(fmt_date)
        show_table(view, kinds={"Harga normal": "money", "Harga flash": "money", "Kuota": "count"}, column_config={"SKU · produk · varian": st.column_config.TextColumn(width="large")})
        download_excel(schedule, "jadwal_flash_sale.xlsx", key="xl-flash-new")
    if skipped:
        with st.expander(f"Tidak dijadwalkan · {fmt_num(len(skipped))} SKU"):
            show_table(pd.DataFrame(skipped).head(200), column_config={"SKU · produk · varian": st.column_config.TextColumn(width="large")})


# ---------------------------------------------------------------- Exposure (4D)


def _ranked_for_exposure(table: pd.DataFrame, data: FeatureData, orders: pd.DataFrame | None, today: date) -> pd.DataFrame:
    momentum = momentum_14d(orders.assign(sku=orders["sku"].astype(str)) if orders is not None and not orders.empty and "sku" in orders.columns else None, today)
    rows = []
    for _, row in table.head(CANDIDATE_LIMIT).iterrows():
        sku = str(row["sku"])
        ok, _reasons, _decision = promo_eligible(row, excluded=data.excluded, margin_pct=data.margin_pct.get(sku), cancel_pct=row.get("batal_pct"))
        if not ok:
            continue
        margin_pct, _known = _margin_of(data, sku, 8.0)
        rows.append(
            {
                "sku": sku,
                "label": _label(row),
                "kategori": promo_calendar.category_of(row["product_name"]),
                "prioritas": float(row["m_sales"]) * max(margin_pct, 0.1) / 100 * (1 + momentum.get(sku, 0.0)),
            }
        )
    return pd.DataFrame(rows, columns=["sku", "label", "kategori", "prioritas"])


def show_exposure(table: pd.DataFrame, *, features, data: FeatureData, orders: pd.DataFrame | None, frames, today: date, username: str, can_edit: bool) -> None:
    st.markdown("<div class='section-title'>Exposure media sosial</div>", unsafe_allow_html=True)
    if table is None or table.empty:
        st.write("Jalankan analisa terlebih dahulu.")
        return
    ym = st.session_state.get("expo-ym") or (today.year, today.month)
    n1, n2, n3, n4 = st.columns([1, 1, 1, 3])
    if n1.button("‹ Bulan sebelumnya", key="expo-prev", use_container_width=True):
        st.session_state["expo-ym"] = promo_calendar.shift_month(*ym, -1)
        st.session_state.pop("expo-day", None)
        st.rerun()
    if n2.button("Hari ini", key="expo-today", use_container_width=True):
        st.session_state["expo-ym"] = (today.year, today.month)
        st.session_state.pop("expo-day", None)
        st.rerun()
    if n3.button("Bulan berikutnya ›", key="expo-next", use_container_width=True):
        st.session_state["expo-ym"] = promo_calendar.shift_month(*ym, 1)
        st.session_state.pop("expo-day", None)
        st.rerun()
    year, month = ym
    periode = f"{year:04d}-{month:02d}"
    past = (year, month) < (today.year, today.month)
    saved = features.read("exposure_schedule", {"periode": periode}) if features is not None else pd.DataFrame()
    slots = int(n4.number_input("Jumlah slot per bulan", min_value=5, max_value=60, value=20, step=1, key="expo-slots"))
    if not saved.empty:
        plan = saved
        source = "Jadwal tersimpan"
    elif past:
        plan = pd.DataFrame()
        source = "Belum ada jadwal tersimpan untuk bulan ini"
    else:
        plan = promo_calendar.exposure_calendar(_ranked_for_exposure(table, data, orders, today), year, month, slots=slots)
        source = "Usulan sistem"
    st.markdown(f"**{_month_name(month)} {year}** · {source}")
    st.caption(
        "Maks. 2 SKU per hari; SKU yang sama berjarak minimal 5 hari; tanggal spesial diisi SKU prioritas tertinggi. Klik tanggal untuk detail.",
        help="Prioritas = prediksi sales jendela × margin × (1 + momentum 14 hari). Tanggal round(k × jarak) mulai tanggal 3. Kanal bergilir per kategori.",
    )
    by_day: dict[date, list[dict]] = {}
    for _, row in plan.iterrows():
        by_day.setdefault(pd.Timestamp(row["tanggal"]).date(), []).append(row.to_dict())
    head = st.columns(7)
    for column, name in zip(head, WEEKDAYS):
        column.markdown(f"<div style='text-align:center;font-size:var(--fs-xs);color:#64748b;font-weight:700'>{name}</div>", unsafe_allow_html=True)
    picked = st.session_state.get("expo-day")
    for week in promo_calendar.month_grid(year, month):
        cols = st.columns(7)
        for column, day in zip(cols, week):
            if day is None:
                column.markdown("<div style='min-height:110px'></div>", unsafe_allow_html=True)
                continue
            items = by_day.get(day, [])
            with column.container(border=True):
                mark = " · hari ini" if day == today else ""
                if st.button(f"{day.day}{mark}", key=f"expo-d-{day.isoformat()}", use_container_width=True, type="primary" if picked == day.isoformat() else "secondary", disabled=not items):
                    st.session_state["expo-day"] = day.isoformat()
                    st.rerun()
                # Nama produk dipotong 3 baris (nama lengkap di tooltip dan di detail saat tanggal diklik).
                lines = "".join(
                    f"<div style='font-size:var(--fs-xs);line-height:1.3;margin-top:3px;word-break:break-word'><b>{html.escape(str(item['kanal']))}</b>"
                    f"<div title='{html.escape(str(item['label']))}' style='overflow-wrap:anywhere'>"
                    f"{html.escape(str(item['label']))}</div></div>"
                    for item in items
                )
                special = next((item.get("spesial") for item in items if item.get("spesial")), "")
                if special:
                    lines = f"<div style='font-size:var(--fs-xs);color:#b45309;font-weight:700'>{html.escape(special)}</div>" + lines
                st.markdown(lines or "<div style='font-size:var(--fs-xs);color:#cbd5e1'>–</div>", unsafe_allow_html=True)
    if picked:
        _exposure_detail(by_day.get(date.fromisoformat(picked), []), date.fromisoformat(picked), frames)
    b1, b2 = st.columns(2)
    if not plan.empty and saved.empty and not past and b1.button("Simpan jadwal bulan ini", key="expo-save", type="primary", disabled=not can_edit):
        from auth.ui import require

        require("rekomendasi", "edit")
        rows = plan.assign(periode=periode, saved_by=username)
        features.insert("exposure_schedule", rows, username=username, action="simpan:jadwal_exposure")
        st.success("Jadwal disimpan.")
        st.rerun()
    if not saved.empty and not past and b1.button("Susun ulang usulan", key="expo-reset", disabled=not can_edit):
        from auth.ui import require

        require("rekomendasi", "edit")
        features.remove("exposure_schedule", {"periode": periode}, username=username, action="hapus:jadwal_exposure")
        st.rerun()
    if not plan.empty:
        with b2:
            download_excel(plan, f"kalender_exposure_{periode}.xlsx", key="xl-expo-new")


def _month_name(month: int) -> str:
    from src.ui.common import ID_MONTHS

    return ID_MONTHS[month - 1]


def _exposure_detail(items: list[dict], day: date, frames) -> None:
    descriptions = getattr(frames, "descriptions", pd.DataFrame())
    lookup = {}
    if descriptions is not None and not descriptions.empty and "description" in descriptions.columns and "sku" in descriptions.columns:
        lookup = dict(zip(descriptions["sku"].astype(str).str.replace(r"\.0+$", "", regex=True), descriptions["description"]))
    st.markdown(f"**Detail {fmt_date(day)}**")
    for index, item in enumerate(items):
        with st.container(border=True):
            st.markdown(f"**{html.escape(str(item['kanal']))}** · {html.escape(str(item['label']))}")
            st.markdown(f"Hook ({html.escape(str(item['kategori']))}): _{html.escape(hook_for(str(item['kategori']), index))}_")
            feats = features_from_description(lookup.get(str(item["sku"]), ""))
            if feats:
                st.markdown("\n".join(f"- {html.escape(f)}" for f in feats))
            else:
                st.caption("Deskripsi produk belum diunggah atau tidak memuat fitur terukur.")


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


def show_ranking(table: pd.DataFrame, *, features, frames, username: str, can_edit: bool) -> None:
    st.markdown("<div class='section-title'>Ranking kategori</div>", unsafe_allow_html=True)
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
    limit = int(st.session_state.get("rank-limit", STEP))
    show_table(shown.head(limit), column_config={"Langkah prioritas": st.column_config.TextColumn(width="large")})
    if limit < len(frame) and st.button("Muat 20 SKU lagi", key="rank-more"):
        st.session_state["rank-limit"] = limit + STEP
        st.rerun()
    download_excel(frame, "skor_kesiapan_ranking.xlsx", key="xl-rank")

