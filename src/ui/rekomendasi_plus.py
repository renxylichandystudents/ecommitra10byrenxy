"""Rekomendasi › Iklan (target & strategi), Flash sale toko, Exposure media sosial, Ranking kategori (4C–4E)."""

from __future__ import annotations

import html
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
from src.ui.common import batched_view, download_excel, explain, fmt_num, table_toolbar
from src.ui.feature_data import FeatureData, product_frame
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
                spare = max(stok - float(r.get("pred_harian", 0) or 0) * days_left, 0.0)
                room[code] = room.get(code, 0.0) + spare * price / max(days_left, 1)
            rows.append({"product_code": code, "nama": r.get("product_name", ""), "omzet_harian": float(r.get("pred_harian", 0) or 0) * price, "stok": stok})
    contribution = {c: sum(v * w for v, w in vals) / sum(w for _v, w in vals) for c, vals in contrib.items()}
    A.attach_economics(units, members, contribution, room)
    products = (pd.DataFrame(rows).groupby(["product_code"], as_index=False).agg(nama=("nama", "first"), omzet_harian=("omzet_harian", "sum"), stok=("stok", lambda v: v.sum(min_count=1)))
                if rows else pd.DataFrame(columns=["product_code", "nama", "omzet_harian", "stok"]))
    products["stok_room"] = products["product_code"].map(room)
    running = [u for u in units if u.daily_cost > 0]
    store_roas = sum(u.daily_sales for u in running) / sum(u.daily_cost for u in running) if running else 8.0
    # Fokus kejar target: hanya iklan produk tunggal & grup; margin dan stok dicatat, tidak menyaring.
    units = [u for u in units if u.jenis in A.TARGET_KINDS]
    units += A.new_single_candidates(units, products, contribution, store_roas=store_roas, require_margin=False, require_stock=False)
    del latest
    return units, members, contribution, products


def show_ads_strategy(table: pd.DataFrame, *, features, data: FeatureData, params: dict, window_start: date, username: str, can_edit: bool,
                      frames=None, orders: pd.DataFrame | None = None) -> None:
    from src.ui.ads_target import show_target_strategy

    show_target_strategy(table, features=features, params=params, username=username, can_edit=can_edit, frames=frames, orders=orders,
                         inputs=_ads_inputs)


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
        if comp is None and sku in getattr(data, "margin_inputs", {}):
            from dataclasses import replace as _replace

            from src.core import shopee_fee as fee

            inp = data.margin_inputs[sku]
            floor = fee.min_price(inp, 0.0)
            flash = promo_calendar.flash_price(price, 0.10, floor if np.isfinite(floor) else None)
            flash_margin = fee.margin(_replace(inp, harga=flash))[1] if flash > 0 else None
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
        table_toolbar(lambda: download_excel(schedule, "jadwal_flash_sale.xlsx", key="xl-flash-new"), key="flash-new")
        show_table(view, kinds={"Harga normal": "money", "Harga flash": "money", "Kuota": "count"}, column_config={"SKU · produk · varian": st.column_config.TextColumn(width="large")})
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
        margin_pct, _known = _margin_of(data, sku, 0.0)
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
    batched_view(
        len(shown),
        key="rank",
        render=lambda lo, hi: show_table(shown.iloc[lo:hi], column_config={"Langkah prioritas": st.column_config.TextColumn(width="large")}),
        noun="SKU",
        download=lambda: download_excel(frame, "skor_kesiapan_ranking.xlsx", key="xl-rank"),
    )

