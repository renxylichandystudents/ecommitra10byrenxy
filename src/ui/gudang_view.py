"""Setting › Kapasitas gudang (Site 10037): denah, data replenishment harian, dan analisa kapasitas."""

from __future__ import annotations

import html
from datetime import date, datetime

import numpy as np
import pandas as pd
import streamlit as st

from src.core import gudang
from src.ui.common import batched_view, card, download_excel, explain, file_check, fmt_num, fmt_pct, set_upload_notice, show_upload_notice
from src.utils.format import show_table

STATUS_ICON = {"Kosong": "🔴 Kosong", "Hampir habis": "🟠 Hampir habis", "Stok berlebih": "🟣 Stok berlebih", "Aman": "🟢 Aman"}
CATEGORY_COLORS = [
    "#60a5fa", "#f59e0b", "#34d399", "#f472b6", "#a78bfa", "#fb7185",
    "#2dd4bf", "#facc15", "#818cf8", "#4ade80", "#fb923c", "#94a3b8",
]


# --------------------------------------------------------------------------- data


def load_locations(features) -> pd.DataFrame:
    """Lokasi denah dari file LAYOUT_ECOM yang sudah diunggah (kosong bila belum)."""
    try:
        saved = features.read("warehouse_location") if features is not None else pd.DataFrame()
    except Exception:
        saved = pd.DataFrame()
    if saved is None or saved.empty:
        return pd.DataFrame(columns=["rak", "lorong", "bay", "level", "slot", "lokasi", "kategori", "area", "lorong_kode", "bay_kode"])
    return gudang._prepare_locations(saved)


def load_denah(features) -> dict | None:
    """Denah terakhir yang diunggah (geometri sheet LAY OUT)."""
    import json

    try:
        frame = features.read("warehouse_denah") if features is not None else pd.DataFrame()
    except Exception:
        return None
    if frame.empty:
        return None
    latest = frame.sort_values("created_at").iloc[-1]
    return json.loads(latest["content"])


def load_replenishment(features) -> tuple[pd.DataFrame, object, list]:
    """Snapshot replenishment terbaru → (tabel, tanggal, semua tanggal)."""
    if features is None:
        return pd.DataFrame(), None, []
    try:
        dates = features.snapshot_dates("warehouse_replenishment")
    except Exception:
        return pd.DataFrame(), None, []
    if not dates:
        return pd.DataFrame(), None, []
    frame = features.read("warehouse_replenishment", {"snapshot_date": dates[0]})
    for column in gudang.NUMERIC:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    for column in ("nama", "kategori", "spesifikasi", "pick_location", "abc", "stock_out"):
        frame[column] = frame[column].fillna("").astype(str)
    frame = gudang.apply_master(frame, load_master(features, dates))
    return frame, dates[0], dates


def load_master(features, dates: list | None = None) -> pd.DataFrame:
    """Spesifikasi & Pick Location per SKU (definisi tim). Kosong → diisi sekali dari snapshot terbaru yang masih membawanya."""
    try:
        master = features.read("warehouse_item_master")
    except Exception as exc:
        st.warning(f"Data barang (Spesifikasi & Pick Location) belum bisa dibaca: {exc}")
        return pd.DataFrame(columns=["sku", "spesifikasi", "pick_location"])
    if not master.empty:
        return master
    for snap in dates or []:
        seed = gudang.master_from_repl(features.read("warehouse_replenishment", {"snapshot_date": snap}))
        if not seed.empty:
            try:
                save_master(features, seed, username="sistem", action="isi_awal:master_barang_gudang")
            except Exception:
                pass
            return seed
    return master


def save_master(features, rows: pd.DataFrame, *, username: str, action: str) -> int:
    keep = rows[["sku", "spesifikasi", "pick_location"]].assign(updated_by=username, updated_at=datetime.now())
    return features.replace("warehouse_item_master", keep, keys=["sku"], username=username, action=action)


def _table_maps(table: pd.DataFrame | None) -> tuple[dict, dict, dict, dict]:
    stock, names, pred, price = {}, {}, {}, {}
    if isinstance(table, pd.DataFrame) and not table.empty and "sku" in table.columns:
        skus = table["sku"].map(gudang.norm_sku)
        if "stok" in table.columns:
            has = table["ada_data_stok"].astype(bool) if "ada_data_stok" in table.columns else pd.Series(True, index=table.index)
            part = pd.DataFrame({"sku": skus, "stok": pd.to_numeric(table["stok"], errors="coerce"), "has": has})
            part = part.loc[part["has"] & part["stok"].notna()]
            stock = part.groupby("sku")["stok"].sum().to_dict()
        if "product_name" in table.columns:
            names = dict(zip(skus, table["product_name"].astype(str)))
        if "pred_harian" in table.columns:
            pred = pd.DataFrame({"sku": skus, "p": pd.to_numeric(table["pred_harian"], errors="coerce").fillna(0)}).groupby("sku")["p"].sum().to_dict()
        if "harga_bersih" in table.columns:
            price = pd.DataFrame({"sku": skus, "h": pd.to_numeric(table["harga_bersih"], errors="coerce")}).dropna().groupby("sku")["h"].max().to_dict()
    return stock, names, pred, price


def latest_prediction(features) -> tuple[dict, dict, object]:
    """Prediksi dari analisa terakhir yang tersimpan (tabel prediction_snapshot): laju QTY & omzet harian per SKU.

    Dipakai di Setting agar tim DC/IC/MD tetap melihat prediksi tanpa membuka analisa; mengembalikan (qty/hari, omzet/hari, waktu analisa)."""
    try:
        from sqlalchemy import func, select

        from src.core.feature_store import prediction_snapshot as snap

        with features.engine.connect() as conn:
            run = conn.execute(select(func.max(snap.c.run_id))).scalar()
            if run is None:
                return {}, {}, None
            rows = conn.execute(
                select(snap.c.sku, snap.c.target_date, snap.c.pred_qty, snap.c.pred_sales, snap.c.created_at).where(snap.c.run_id == run)
            ).all()
    except Exception:
        return {}, {}, None
    frame = pd.DataFrame(rows, columns=["sku", "tanggal", "q", "s", "at"])
    if frame.empty:
        return {}, {}, None
    days = max(frame["tanggal"].nunique(), 1)
    frame["sku"] = frame["sku"].map(gudang.norm_sku)
    grouped = frame.groupby("sku")[["q", "s"]].sum() / days
    return grouped["q"].to_dict(), grouped["s"].to_dict(), pd.Timestamp(frame["at"].min())


def cached_view(features, table: pd.DataFrame | None, orders: pd.DataFrame | None = None) -> dict | None:
    """Analisa gudang (disimpan di sesi; dihitung ulang bila snapshot replenishment/tabel berubah)."""
    repl, snap, _dates = load_replenishment(features)
    locations = load_locations(features)
    denah = load_denah(features)
    if orders is None:
        orders = st.session_state.get("_gudang_orders")
    else:
        st.session_state["_gudang_orders"] = orders
    stamp = (
        gudang.snapshot_stamp(snap), len(repl), _latest_run_id(features), 0 if table is None else len(table), len(locations),
        0 if denah is None else len(denah["cells"]), 0 if orders is None else len(orders),
    )
    cache = st.session_state.get("_gudang_view")
    if cache and cache[0] == stamp:
        return cache[1]
    stock, names, pred, price = _table_maps(table)
    pred_source = "analisa yang sedang dibuka" if pred else ""
    if not pred:
        # Setting dibuka tanpa analisa: pakai prediksi dari analisa terakhir yang tersimpan.
        pred_q, pred_s, run_at = latest_prediction(features)
        if pred_q:
            pred = pred_q
            price = {k: pred_s[k] / v for k, v in pred_q.items() if v and k in pred_s}
            pred_source = f"analisa terakhir ({run_at:%d/%m/%Y %H:%M})" if run_at is not None else "analisa terakhir"
    sales = gudang.sales_summary(orders)
    view = gudang.build_view(locations, repl, stock=stock, names=names, pred_daily=pred, price=price, sales=sales)
    view["sales_end"] = sales.attrs.get("end") if not sales.empty else None
    view["has_pred"] = bool(pred)
    view["pred_source"] = pred_source
    view["snapshot"] = snap
    view["has_repl"] = not repl.empty
    view["has_stock"] = bool(stock)
    view["denah"] = denah
    st.session_state["_gudang_view"] = (stamp, view)
    return view


def location_text(sku: str) -> str:
    """Untuk dialog analisa SKU: lokasi & batas stok di gudang 10037 (bila analisa gudang sudah dimuat)."""
    cache = st.session_state.get("_gudang_view")
    return gudang.location_of(cache[1] if cache else None, sku)


# --------------------------------------------------------------------------- denah


def _bay_fill(bay: pd.Series | None, mode: str, palette: dict[str, str]) -> tuple[str, str]:
    """(warna isi, warna garis tebal) untuk satu sel bay."""
    if bay is None:
        return "#f8fafc", ""
    if mode == "Kategori":
        return palette.get(str(bay["kategori"]).split(", ")[0], "#cbd5e1"), ""
    if mode == "Perlu tindakan":
        n = int(bay["masalah"])
        return ("#fecaca" if n == 1 else "#f87171" if n >= 2 else "#f1f5f9"), ""
    if bay["area"] == "Gondola":
        share = float(bay["terisi"]) / float(bay["lokasi"]) if bay["lokasi"] else 0
        fill = "#f1f5f9" if share == 0 else "#bbf7d0" if share < 0.5 else "#4ade80" if share < 1 else "#16a34a"
        return fill, ("#dc2626" if int(bay["masalah"]) else "")
    pct = bay["rak_pct"]
    if not np.isfinite(pct):
        return "#f1f5f9", ""
    return ("#bfdbfe" if pct < 75 else "#fbbf24" if pct <= 100 else "#f87171"), ""


def denah_svg(view: dict, *, mode: str, landscape: bool, width: int = 1100) -> str:
    denah = view.get("denah")
    if not denah:
        return "", {}, 0
    bays = view["bays"]
    loc = view["locations"]
    items = view["items"].set_index("pick_location") if not view["items"].empty else pd.DataFrame()
    categories = sorted(set(loc["kategori"]))
    palette = {c: CATEGORY_COLORS[i % len(CATEGORY_COLORS)] for i, c in enumerate(categories)}
    W, H = float(denah["w"]), float(denah["h"])
    vw, vh = (H, W) if landscape else (W, H)

    def place(x, y, w, h):
        return (y, W - x - w, h, w) if landscape else (x, y, w, h)

    parts = []
    for cell in denah["cells"]:
        x, y, w, h = place(cell["x"], cell["y"], cell["w"], cell["h"])
        key = cell.get("k")
        fill = cell.get("f")
        outline = ""
        tip = ""
        if cell.get("s") and fill:
            fill = "#e2e8f0"
        if key:
            bay = bays.loc[key] if key in bays.index else None
            fill, outline = _bay_fill(bay, mode, palette)
            if bay is not None:
                lines = [f"{key} · {bay['area']} · {str(bay['kategori']).title()}"]
                if bay["area"] == "Gondola":
                    lines.append(f"{int(bay['terisi'])}/{int(bay['lokasi'])} lokasi terisi · stok {fmt_num(bay['stok'])}")
                    for code in loc.loc[loc["bay_kode"] == key, "lokasi"]:
                        if not items.empty and code in items.index:
                            hit = items.loc[[code]]
                            for r in hit.itertuples():
                                lines.append(f"{code} L{code[6:8]}: {r.sku} {str(r.nama)[:40]} · stok {fmt_num(r.stok)} · {r.status}")
                        else:
                            lines.append(f"{code} L{code[6:8]}: kosong")
                else:
                    pct = bay["rak_pct"]
                    lines.append(f"{int(bay['lokasi'])} lokasi rak · zona kategori terisi ±{fmt_pct(pct, 0) if np.isfinite(pct) else '-'}")
                if int(bay["masalah"]):
                    lines.append(f"⚠ {int(bay['masalah'])} SKU kosong / hampir habis")
                tip = "<title>" + html.escape("\n".join(lines)) + "</title>"
        if fill:
            parts.append(f"<rect x='{x}' y='{y}' width='{w}' height='{h}' fill='{fill}'>{tip}</rect>")
        elif tip:
            parts.append(f"<rect x='{x}' y='{y}' width='{w}' height='{h}' fill='#ffffff'>{tip}</rect>")
        top, right, bottom, left = cell.get("b") or [0, 0, 0, 0]
        if landscape:  # sisi ikut berputar 90°: atas→kiri, kanan→atas, bawah→kanan, kiri→bawah
            top, right, bottom, left = right, bottom, left, top
        for width_, (x1, y1, x2, y2) in (
            (top, (x, y, x + w, y)), (right, (x + w, y, x + w, y + h)),
            (bottom, (x, y + h, x + w, y + h)), (left, (x, y, x, y + h)),
        ):
            if width_:
                parts.append(f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' stroke='#334155' stroke-width='{width_ * 0.8}'/>")
        if outline:
            parts.append(f"<rect x='{x + 1.5}' y='{y + 1.5}' width='{max(w - 3, 1)}' height='{max(h - 3, 1)}' fill='none' stroke='{outline}' stroke-width='3'/>")
        text = cell.get("t") or ""
        if text and not text.startswith("="):
            size = 12 if key else 13
            weight = 700 if not key else 500
            parts.append(
                f"<text x='{x + w / 2}' y='{y + h / 2}' font-size='{size}' font-weight='{weight}' text-anchor='middle' dominant-baseline='central' "
                f"fill='#0f172a' style='pointer-events:none'>{html.escape(text)}</text>"
            )
    height = int(width * vh / vw)
    return (
        f"<div style='overflow:auto;border:1px solid #e2e8f0;border-radius:12px;background:#fff;padding:6px'>"
        f"<svg viewBox='0 0 {vw} {vh}' width='100%' style='max-width:{width}px;height:auto;display:block;margin:auto;font-family:inherit' "
        f"xmlns='http://www.w3.org/2000/svg' role='img' aria-label='Denah gudang Site 10037'>{''.join(parts)}</svg></div>"
    ), palette, height


def _legend(mode: str, palette: dict[str, str]) -> str:
    if mode == "Kategori":
        items = [(c, color) for c, color in palette.items()]
    elif mode == "Perlu tindakan":
        items = [("Tidak ada", "#f1f5f9"), ("1 SKU kosong / hampir habis", "#fecaca"), ("≥ 2 SKU", "#f87171")]
    else:
        items = [
            ("Gondola kosong", "#f1f5f9"), ("Gondola < 50% terisi", "#bbf7d0"), ("Gondola 50–99%", "#4ade80"), ("Gondola penuh", "#16a34a"),
            ("Rak zona < 75%", "#bfdbfe"), ("Rak zona 75–100%", "#fbbf24"), ("Rak zona > 100% (melebihi lokasi)", "#f87171"),
        ]
    chips = "".join(
        f"<span style='display:inline-flex;align-items:center;gap:6px;margin:2px 12px 2px 0;font-size:.8rem;color:#334155'>"
        f"<span style='width:14px;height:14px;border-radius:3px;background:{color};border:1px solid #cbd5e1'></span>{html.escape(str(label).title() if mode == 'Kategori' else label)}</span>"
        for label, color in items
    )
    extra = "" if mode != "Keterisian" else "<span style='font-size:.8rem;color:#b91c1c;margin-left:4px'>▢ garis merah = ada SKU kosong / hampir habis</span>"
    return f"<div style='margin:4px 0 8px'>{chips}{extra}</div>"


# --------------------------------------------------------------------------- halaman


def show_capacity(features, table: pd.DataFrame, *, may_upload: bool, username: str, require, orders: pd.DataFrame | None = None,
                  may_upload_repl: bool = False) -> None:
    st.markdown(f"**Kapasitas gudang · Site {gudang.SITE} {gudang.SITE_NAME}**")
    view = cached_view(features, table, orders)
    loc = view["locations"]
    _upload_cards(features, view, may_upload=may_upload, may_upload_repl=may_upload_repl, username=username, require=require)
    if loc.empty:
        st.info("Mulai dengan mengunggah **denah gudang** di kotak kiri. Cukup sekali; unggah lagi hanya bila tata letak gudang berubah.")
        return
    if not view.get("has_repl"):
        st.info("Denah sudah ada. Unggah **data stok harian (replenishment)** di kotak kanan agar isi rak dan status stok terlihat.")
    if view.get("has_repl"):
        _master_section(features, view, may_edit=may_upload_repl, username=username, require=require)
    gondolas = loc.loc[loc["area"] == "Gondola"]
    st.caption(
        "Stok diambil dari data stok Site 10037 yang diunggah di aplikasi."
        if view.get("has_stock") else "Stok diambil dari data stok harian (data stok Site 10037 belum diunggah di aplikasi)."
    )

    items = view["items"]
    cats = view["categories"]
    if view.get("has_repl"):
        value, note = gudang.capacity_card(view)
        cols = st.columns(4)
        card(cols[0], "Lokasi terpakai", value, hint=note)
        card(cols[1], "Gondola terisi", f"{fmt_num(int(gondolas['terisi'].sum()))} / {fmt_num(len(gondolas))}",
             hint=f"{fmt_num(int((items['pick_location'] != '').sum()))} SKU kecil punya pick location · {fmt_num(int((loc['n_sku'] > 1).sum()))} lokasi dipakai >1 SKU")
        need = items.loc[items["status"].isin(["Kosong", "Hampir habis"])]
        card(cols[2], "Perlu diisi ulang", fmt_num(len(need)), hint=f"{fmt_num(int((items['status'] == 'Kosong').sum()))} kosong · {fmt_num(int((items['status'] == 'Hampir habis').sum()))} hampir habis (di bawah titik pesan ulang)")
        over = items.loc[items["status"] == "Stok berlebih"]
        over_units = float((over["stok"] - over["max_stock"]).sum())
        card(cols[3], "Stok berlebih", fmt_num(len(over)), hint=f"kelebihan {fmt_num(over_units)} unit memakan ruang")
        notes = []
        for r in cats.itertuples():
            bits = []
            if np.isfinite(r.rak_pct) and 100 < r.rak_pct < 999:
                bits.append(f"rak {fmt_pct(r.rak_pct, 0)}")
            if np.isfinite(r.gondola_pct) and r.gondola_pct >= 100:
                bits.append("gondola penuh")
            if bits:
                notes.append(f"{str(r.kategori).title()} ({', '.join(bits)})")
        if notes:
            st.warning(
                "Zona penuh / melebihi lokasi: " + "; ".join(notes)
                + ". Pertimbangkan menambah lokasi, memindah SKU lambat, atau menahan pengisian SKU yang stoknya berlebih.",
                icon=":material/warning:",
            )

    st.markdown("<div class='section-title'>Denah gudang</div>", unsafe_allow_html=True)
    c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
    mode = c1.segmented_control("Warnai menurut", ["Keterisian", "Kategori", "Perlu tindakan"], default="Keterisian", key="gudang-mode") or "Keterisian"
    orient = c2.segmented_control("Tampilan", ["Mendatar", "Tegak (sesuai file)"], default="Mendatar", key="gudang-orient") or "Mendatar"
    svg, palette, _height = denah_svg(view, mode=mode, landscape=orient == "Mendatar")
    if svg:
        st.markdown(_legend(mode, palette), unsafe_allow_html=True)
        st.markdown(svg, unsafe_allow_html=True)
        st.caption("Arahkan kursor ke kotak bay untuk melihat isi lokasi (SKU, stok, status). Angka di kotak = nomor bay.")
    else:
        st.caption("Gambar denah belum ada (unggah file LAYOUT_ECOM yang memuat sheet LAY OUT).")

    _lane_detail(view)
    _category_table(view)
    _sku_table(view)


def show_parameters(features, user_root, *, may_edit: bool) -> None:
    """Nilai yang dipakai algoritma stok & restock: sumbernya, dan di mana dipakai. Lead time lokal satu-satunya yang diisi manual."""
    from src.core.config import load_params, save_params
    from src.core.warehouse import lead_time_stats

    params = load_params(user_root)
    lead = params.get("lead_time", {}) or {}
    cfg = params.get("gudang", {}) or {}
    repl, snapshot, _dates = load_replenishment(features)
    room = gudang.restock_capacity(repl)
    try:
        notes = features.read("import_note") if features is not None else pd.DataFrame()
        stats = lead_time_stats(notes)
    except Exception:
        stats = None
    local = float(lead.get("lokal_hari", 7) or 7)
    sigma = float(lead.get("lokal_sigma_hari", 0) or 0)
    rows = [
        {"Parameter": "Lead time lokal", "Nilai": f"{fmt_num(local)} hari",
         "Sumber": "diisi tim (tidak ada di file unggahan) · ubah di bawah",
         "Dipakai untuk": "Safety stock = Z × σ permintaan harian × √(lead time + periode tinjau); titik pesan ulang (ROP) = prediksi harian × lead time + SS; simulasi stok di Laporan"},
        {"Parameter": "Variasi lead time lokal (σ)", "Nilai": f"{fmt_num(sigma)} hari", "Sumber": "nilai tetap",
         "Dipakai untuk": "0 = lead time dianggap stabil; bila > 0 safety stock memakai rumus umum (variasi permintaan + variasi lead time)"},
        {"Parameter": "Lead time impor",
         "Nilai": f"rata-rata {fmt_num(stats[0], 1)} · maks. {fmt_num(stats[1])} hari" if stats else "belum ada PO diterima",
         "Sumber": "Setting › Kedatangan impor (Diterima DC − tanggal PO)",
         "Dipakai untuk": "SS impor = (lead time maks − rata-rata) × permintaan harian; dipakai hanya bila mode impor aktif (saat ini nonaktif: semua SKU memakai lead time lokal)"},
        {"Parameter": "Kapasitas restock",
         "Nilai": f"{fmt_num(room['unit'])} unit" if room else f"{fmt_num(cfg.get('kapasitas_unit', 100000))} unit (bawaan)",
         "Sumber": (f"replenishment {snapshot}: Σ (Max − stok) per SKU · {fmt_num(room['sku_ada_ruang'])} dari {fmt_num(room['sku'])} SKU masih punya ruang "
                    f"· total Max {fmt_num(room['max_total'])} unit, stok {fmt_num(room['soh_total'])} unit") if room else "unggah data stok harian (replenishment) di atas",
         "Dipakai untuk": "Batas total unit pembelian pada optimasi restock MILP Top 50 (Evaluasi model)"},
        {"Parameter": "MOQ", "Nilai": f"{fmt_num(cfg.get('moq_unit', 1))} unit", "Sumber": "nilai tetap", "Dipakai untuk": "Pembelian minimal per SKU pada optimasi restock"},
        {"Parameter": "Biaya simpan · biaya kehabisan",
         "Nilai": f"{fmt_num(cfg.get('biaya_simpan_pct_tahun', 20))}%/tahun · {fmt_num(cfg.get('biaya_kehabisan_pct', 30))}% harga",
         "Sumber": "nilai tetap",
         "Dipakai untuk": "Rekomendasi service level = Cu ÷ (Cu + Co); Cu = margin + biaya kehabisan, Co = biaya simpan × hari periode ÷ 365"},
    ]
    with st.expander("Parameter perhitungan stok & restock", expanded=False):
        st.caption("Nilai di bawah dipakai oleh analisa safety stock, ROP, dan optimasi restock. Semua diambil dari data yang diunggah, kecuali lead time lokal.")
        show_table(pd.DataFrame(rows), max_height=10_000, column_config={
            "Sumber": st.column_config.TextColumn(width="large"), "Dipakai untuk": st.column_config.TextColumn(width="large")})
        if not may_edit:
            return
        c1, c2 = st.columns([1, 3], vertical_alignment="bottom")
        new = c1.number_input("Lead time lokal (hari)", min_value=1, max_value=120, value=int(local), step=1, key="gudang-lead-lokal",
                              help="Hari dari pesan ulang ke DC sampai barang siap dijual di Site 10037.")
        if c2.button("Simpan lead time", key="gudang-lead-save", disabled=int(new) == int(local)):
            params.setdefault("lead_time", {})["lokal_hari"] = int(new)
            save_params(params, user_root)
            st.success(f"Lead time lokal {int(new)} hari disimpan. Jalankan analisa lagi agar safety stock dan ROP memakai nilai baru.")


def _denah_info(features) -> tuple[str, str]:
    """(kapan, oleh siapa) denah terakhir diunggah."""
    try:
        frame = features.read("warehouse_denah")
    except Exception:
        return "", ""
    if frame.empty:
        return "", ""
    latest = frame.sort_values("created_at").iloc[-1]
    return pd.Timestamp(latest["created_at"]).strftime("%d/%m/%Y %H:%M"), str(latest["uploaded_by"] or "")


def _read_upload(upload) -> dict | None:
    try:
        if upload.name.lower().endswith(".csv"):
            repl, snap = gudang.parse_replenishment(pd.read_csv(upload, header=None, dtype=object))
            return {"denah": None, "locations": None, "repl": repl, "snapshot": snap}
        return gudang.read_layout_workbook(upload.getvalue())
    except Exception as exc:  # noqa: BLE001 - pesan yang bisa dibaca
        file_check(False, f"{upload.name} tidak bisa dibaca: {exc}")
        return None


def _save_denah(features, denah, locations, *, username: str, require, name: str) -> None:
    import json

    require("setting_kapasitas_gudang", "upload")
    try:
        with st.spinner("Menyimpan denah gudang..."):
            features.clear("warehouse_location", username=username, action="ganti:lokasi_gudang")
            keep = locations[["lokasi", "rak", "lorong", "bay", "level", "slot", "kategori"]]
            features.insert("warehouse_location", keep, username=username, action="unggah:lokasi_gudang")
            if denah is not None:
                features.insert("warehouse_denah", [{"created_at": datetime.now(), "uploaded_by": username, "content": json.dumps(denah)}],
                                username=username, action="unggah:denah_gudang")
    except Exception as exc:  # noqa: BLE001 - gagal simpan ditampilkan, app tidak berhenti
        set_upload_notice("denah", False, f"Denah {name} gagal disimpan: {exc}")
    else:
        set_upload_notice("denah", True, f"Denah {name} tersimpan: {fmt_num(len(locations))} lokasi"
                          + (" dan gambar denah." if denah is not None else ", tanpa gambar denah."))
        st.session_state["denah-round"] = int(st.session_state.get("denah-round", 0)) + 1
    st.session_state.pop("_gudang_view", None)
    st.rerun()


def _upload_cards(features, view: dict, *, may_upload: bool, may_upload_repl: bool, username: str, require) -> None:
    """Dua kotak terpisah: denah gudang (jarang berubah) dan data stok harian (replenishment)."""
    loc = view["locations"]
    left, right = st.columns(2)
    with left.container(border=True):
        when, who = _denah_info(features)
        st.markdown("**🗺️ Denah gudang**")
        if loc.empty:
            st.markdown("<div class='field-hint'>Belum ada denah. Unggah file tata letak gudang (LAYOUT_ECOM).</div>", unsafe_allow_html=True)
        else:
            racks = int((loc["area"] == "Racking").sum())
            st.markdown(
                f"<div class='field-hint'>✓ Terpasang: <b>{fmt_num(len(loc))} lokasi</b> · rak besar {fmt_num(racks)} · gondola {fmt_num(len(loc) - racks)}"
                + (f"<br>Diperbarui {when}" + (f" oleh {html.escape(who)}" if who else "") if when else "") + "</div>",
                unsafe_allow_html=True,
            )
        show_upload_notice("denah")
        round_no = int(st.session_state.get("denah-round", 0))
        picked = st.session_state.get(f"gudang-denah-upload-{round_no}") is not None
        with st.expander("Ganti denah" if not loc.empty else "Unggah denah", expanded=(loc.empty and may_upload) or picked):
            if not may_upload:
                st.caption("Hanya Team DC atau Super user yang bisa mengunggah.")
            st.markdown(
                "<div class='field-hint'>Pakai file tata letak gudang (Excel) yang berisi gambar denah dan daftar lokasi rak. "
                "Denah lama akan diganti seluruhnya.</div>",
                unsafe_allow_html=True,
            )
            denah_upload = st.file_uploader("File denah gudang", type=["xlsx"], key=f"gudang-denah-upload-{round_no}") if may_upload else None
            found = _read_upload(denah_upload) if denah_upload is not None else None
            if found is not None:
                denah, locations = found["denah"], found["locations"]
                if locations is None:
                    file_check(False, f"{denah_upload.name}: daftar lokasi rak tidak ditemukan. Pastikan file tata letak gudang berisi sheet Location "
                               "(file replenishment diunggah di kotak Data stok harian).")
                else:
                    bays = sum(1 for c in (denah or {}).get("cells", []) if c.get("k"))
                    file_check(True, f"{denah_upload.name}: {fmt_num(len(locations))} lokasi"
                               + (f" dan gambar denah ({fmt_num(bays)} bay) terbaca." if denah else " terbaca, tanpa gambar denah."))
                    if st.button("Simpan denah", type="primary", key=f"gudang-denah-save-{round_no}", use_container_width=True):
                        _save_denah(features, denah, locations, username=username, require=require, name=denah_upload.name)
    with right.container(border=True):
        snap = view.get("snapshot")
        st.markdown("**📦 Data stok harian (replenishment)**")
        if snap:
            age = (date.today() - (snap.date() if hasattr(snap, "date") else snap)).days
            mark = "✓" if age <= 1 else f"<span style='color:#dc2626'>⚠️ {age} hari lalu</span> ·"
            st.markdown(
                f"<div class='field-hint'>{mark} Data terakhir: <b>{snap:%d/%m/%Y}</b> · {fmt_num(len(view['items']))} SKU"
                "</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown("<div class='field-hint'>Belum ada data.</div>", unsafe_allow_html=True)
        show_upload_notice("replenishment")
        picked = st.session_state.get(f"gudang-repl-upload-{int(st.session_state.get('repl-round', 0))}") is not None
        with st.expander("Unggah data hari ini", expanded=(not loc.empty and not snap and may_upload_repl) or picked):
            if loc.empty:
                st.caption("Unggah denah gudang dulu.")
            else:
                replenishment_uploader(features, username=username, may_upload=may_upload_repl, require=require)


def replenishment_uploader(features, *, username: str, may_upload: bool, require) -> None:
    """Unggah laporan Replenishment Calculation by Date Site 10037 (hanya di Setting › Kapasitas gudang)."""
    st.markdown(
        f"<div class='field-hint'>File dari sistem: <i>Replenishment Calculation by Date</i> Site {gudang.SITE} (Excel atau CSV), "
        "diunggah setiap hari. Isinya dipakai untuk lokasi barang kecil di gondola, batas Min/Max, dan stok. "
        "Tanggal yang sama akan diganti.</div>",
        unsafe_allow_html=True,
    )
    if not may_upload:
        st.caption("Hanya Team DC, Team IC/MD, atau Super user yang bisa mengunggah.")
        return
    round_no = int(st.session_state.get("repl-round", 0))
    upload = st.file_uploader("File replenishment", type=["xlsx", "xls", "csv"], key=f"gudang-repl-upload-{round_no}")
    found = _read_upload(upload) if upload is not None else None
    if found is None:
        return
    repl = found["repl"]
    if repl is None:
        file_check(False, f"{upload.name}: tabel replenishment tidak ditemukan. Pastikan file berasal dari laporan "
                   "Replenishment Calculation by Date (kolom Item No, Stock On Hand, Min, Max).")
        return
    other = [code for code in repl.attrs.get("sites", []) if code != gudang.SITE]
    if other:
        file_check(False, f"{upload.name} berisi Site {', '.join(other)}, bukan Site {gudang.SITE}. Replenishment di sini khusus Site {gudang.SITE}; "
                   "stok DC 10062/10036 diunggah di Upload data › Stok.")
        return
    if repl.empty:
        file_check(False, f"{upload.name}: tabel replenishment terbaca tetapi tidak berisi SKU.")
        return
    snap_new = found["snapshot"] or datetime.now().date()
    file_check(True, f"{upload.name}: Replenishment Site {gudang.SITE}, {fmt_num(len(repl))} SKU, tanggal {snap_new:%d/%m/%Y}"
               + ("." if found["snapshot"] else " (tanggal tidak ada di file, dipakai tanggal hari ini)."))
    master = load_master(features, features.snapshot_dates("warehouse_replenishment"))
    new_skus = int((~repl["sku"].isin(set(master["sku"].map(gudang.norm_sku)))).sum()) if not master.empty else len(repl)
    if new_skus:
        st.info(
            f"{fmt_num(new_skus)} SKU belum punya Spesifikasi Barang / Pick Location di data barang. Setelah disimpan, "
            "lengkapi lewat **Lengkapi data barang** di bawah agar SKU itu ikut terhitung di kapasitas."
        )
    if st.button("Simpan data", type="primary", key=f"gudang-repl-save-{round_no}"):
        require("upload_replenishment", "upload")
        try:
            with st.spinner("Menyimpan data replenishment..."):
                rows = repl.assign(snapshot_date=snap_new, uploaded_by=username, uploaded_at=datetime.now())
                features.remove("warehouse_replenishment", {"snapshot_date": snap_new}, username=username, action="ganti:replenishment")
                features.insert("warehouse_replenishment", rows, username=username, action="unggah:replenishment")
                features.prune_snapshots("warehouse_replenishment", keep=60)
                carried = gudang.master_from_repl(repl)
                if not carried.empty:
                    save_master(features, carried, username=username, action="unggah:master_barang_gudang")
        except Exception as exc:  # noqa: BLE001 - gagal simpan ditampilkan, app tidak berhenti
            set_upload_notice("replenishment", False, f"Replenishment {upload.name} gagal disimpan: {exc}")
        else:
            set_upload_notice("replenishment", True, f"Replenishment Site {gudang.SITE} tanggal {snap_new:%d/%m/%Y} dari {upload.name} tersimpan "
                              f"({fmt_num(len(repl))} SKU). Kapasitas gudang sudah memakai data ini.")
            st.session_state["repl-round"] = round_no + 1
            st.session_state.pop("_gudang_view", None)
        st.rerun()


MASTER_LABELS = {"sku": "SKU", "nama": "Nama", "kategori": "Kategori", "spesifikasi": "Spesifikasi Barang", "pick_location": "Pick Location", "kurang": "Yang kurang"}


def _master_section(features, view: dict, *, may_edit: bool, username: str, require) -> None:
    """Spesifikasi Barang & Pick Location adalah definisi tim (tidak ada di ekspor replenishment): lengkapi per item atau lewat Excel."""
    items = view["items"]
    todo = gudang.incomplete_items(items)
    known = set(view["locations"]["lokasi"])
    show_upload_notice("master")
    if not todo.empty:
        no_spec = int(todo["kurang"].eq("Spesifikasi Barang").sum())
        no_pick = len(todo) - no_spec
        parts = ([f"{fmt_num(no_spec)} SKU belum punya Spesifikasi Barang (Besar/Kecil)"] if no_spec else []) + (
            [f"{fmt_num(no_pick)} barang Kecil belum punya Pick Location"] if no_pick else [])
        st.warning(
            " · ".join(parts) + ". Tanpa isian ini SKU tersebut tidak terhitung di kapasitas rak/gondola. "
            + ("Lengkapi di bawah (edit per item atau unggah Excel)." if may_edit else "Minta Team DC atau Team IC/MD melengkapinya."),
            icon=":material/edit_note:",
        )
    title = f"Lengkapi data barang · {fmt_num(len(todo))} SKU belum lengkap" if not todo.empty else "Data barang (Spesifikasi & Pick Location)"
    with st.expander(title, expanded=False):
        st.markdown(
            "<div class='field-hint'>Spesifikasi Barang (Besar = disimpan di rak, Kecil = diambil dari gondola) dan Pick Location "
            "ditentukan tim, tidak ikut di ekspor replenishment. Isian disimpan per SKU dan dipakai untuk semua data replenishment "
            "berikutnya; cukup diisi sekali untuk SKU baru.</div>",
            unsafe_allow_html=True,
        )
        if not may_edit:
            st.caption("Hanya Team DC, Team IC/MD, atau Super user yang bisa mengubah.")
        tab_edit, tab_upload = st.tabs(["Edit per item", "Unggah Excel"])
        with tab_edit:
            _master_editor(features, items, todo, known, may_edit=may_edit, username=username, require=require)
        with tab_upload:
            _master_upload(features, items, todo, known, may_edit=may_edit, username=username, require=require)


def _master_editor(features, items: pd.DataFrame, todo: pd.DataFrame, known: set, *, may_edit: bool, username: str, require) -> None:
    c1, c2 = st.columns([1, 2], vertical_alignment="bottom")
    options = [f"Belum lengkap ({fmt_num(len(todo))})", "Semua SKU"]
    scope = c1.segmented_control("Tampilkan", options, default=options[0] if not todo.empty else options[1], key="master-scope") or options[0]
    query = c2.text_input("Cari SKU / nama", key="master-search", placeholder="mis. 300002979 atau check valve").strip().lower()
    base = todo if scope == options[0] else items.assign(kurang="")[["sku", "nama", "kategori", "spesifikasi", "pick_location", "kurang"]]
    if query:
        base = base.loc[base["sku"].str.lower().str.contains(query, regex=False) | base["nama"].str.lower().str.contains(query, regex=False)]
    base = base.assign(spesifikasi=base["spesifikasi"].map(gudang.norm_spesifikasi).replace("", None)).reset_index(drop=True)
    if base.empty:
        st.caption("Semua SKU sudah lengkap." if scope == options[0] and not query else "Tidak ada SKU yang cocok.")
        return
    shown = base.head(300)
    if len(base) > 300:
        st.caption(f"Menampilkan 300 dari {fmt_num(len(base))} SKU. Persempit dengan pencarian atau pakai Unggah Excel.")
    columns = ["sku", "nama", "kategori", "spesifikasi", "pick_location"] + (["kurang"] if scope == options[0] else [])
    edited = st.data_editor(
        shown[columns].rename(columns=MASTER_LABELS),
        hide_index=True, use_container_width=True, key=f"master-editor-{scope}-{query}",
        disabled=["SKU", "Nama", "Kategori", "Yang kurang"] if may_edit else True,
        column_config={
            "Spesifikasi Barang": st.column_config.SelectboxColumn(options=list(gudang.SPESIFIKASI), help="Besar = rak, Kecil = gondola"),
            "Pick Location": st.column_config.TextColumn(help="Kode lokasi gondola di denah, mis. G010010401. Kosongkan untuk barang Besar.", max_chars=40),
        },
    )
    if not may_edit:
        return
    after = pd.DataFrame({
        "sku": shown["sku"],
        "spesifikasi": edited["Spesifikasi Barang"].map(gudang.norm_spesifikasi),
        "pick_location": edited["Pick Location"].map(gudang.norm_location),
    })
    before_spec = shown["spesifikasi"].map(gudang.norm_spesifikasi)
    before_pick = shown["pick_location"].map(gudang.norm_location)
    changed = after.loc[after["spesifikasi"].ne(before_spec) | after["pick_location"].ne(before_pick)]
    if st.button(f"Simpan perubahan ({fmt_num(len(changed))} SKU)", type="primary", key="master-save", disabled=changed.empty):
        require("upload_replenishment", "upload")
        _save_master_rows(features, changed, known, username=username, action="edit:master_barang_gudang")


def _master_upload(features, items: pd.DataFrame, todo: pd.DataFrame, known: set, *, may_edit: bool, username: str, require) -> None:
    st.markdown(
        "<div class='field-hint'>Unduh template, isi kolom <b>Spesifikasi Barang</b> (Besar/Kecil) dan <b>Pick Location</b>, lalu unggah kembali. "
        "Baris yang dibiarkan kosong di kedua kolom tidak mengubah isian lama.</div>",
        unsafe_allow_html=True,
    )
    template_cols = {"sku": "Item No", "nama": "Item Name", "kategori": "Item Category", "spesifikasi": "Spesifikasi Barang", "pick_location": "Pick Location"}
    c1, c2 = st.columns(2)
    with c1:
        download_excel(todo[list(template_cols)].rename(columns=template_cols), "lengkapi_data_barang_10037.xlsx",
                       key="master-tpl-todo", label="Template: SKU belum lengkap")
    with c2:
        download_excel(items[list(template_cols)].rename(columns=template_cols), "data_barang_10037.xlsx",
                       key="master-tpl-all", label="Template: semua SKU")
    if not may_edit:
        return
    round_no = int(st.session_state.get("master-round", 0))
    upload = st.file_uploader("File isian data barang", type=["xlsx", "csv"], key=f"master-upload-{round_no}")
    if upload is None:
        return
    try:
        raw = pd.read_csv(upload, header=None, dtype=object) if upload.name.lower().endswith(".csv") else pd.read_excel(upload, header=None, dtype=object)
        rows = gudang.parse_master_upload(raw)
    except Exception as exc:  # noqa: BLE001 - pesan yang bisa dibaca
        file_check(False, f"{upload.name} tidak bisa dibaca: {exc}")
        return
    rows = rows.loc[rows["spesifikasi"].ne("") | rows["pick_location"].ne("") | rows["spesifikasi_asli"].ne("")]
    unknown = int((~rows["sku"].isin(set(items["sku"]))).sum())
    if rows.empty:
        file_check(False, f"{upload.name}: tidak ada baris berisi Spesifikasi Barang atau Pick Location.")
        return
    file_check(True, f"{upload.name}: {fmt_num(len(rows))} SKU berisi isian"
               + (f" ({fmt_num(unknown)} SKU tidak ada di replenishment terbaru, tetap disimpan)." if unknown else "."))
    if st.button("Simpan isian", type="primary", key=f"master-upload-save-{round_no}", disabled=rows.empty):
        require("upload_replenishment", "upload")
        st.session_state["master-round"] = round_no + 1
        _save_master_rows(features, rows, known, username=username, action="unggah:master_barang_gudang")


def _save_master_rows(features, rows: pd.DataFrame, known: set, *, username: str, action: str) -> None:
    problems = gudang.master_problems(rows, known)
    good = rows.loc[~rows["sku"].isin(set(problems["sku"]))]
    if not problems.empty:
        st.error(f"{fmt_num(len(problems))} SKU tidak disimpan karena isiannya tidak valid:")
        show_table(problems.rename(columns={"sku": "SKU", "masalah": "Masalah"}), max_height=300)
    if good.empty:
        return
    try:
        save_master(features, good, username=username, action=action)
    except Exception as exc:  # noqa: BLE001 - gagal simpan ditampilkan, app tidak berhenti
        st.error(f"Data barang gagal disimpan: {exc}")
        return
    st.session_state.pop("_gudang_view", None)
    message = f"Data barang {fmt_num(len(good))} SKU tersimpan."
    if problems.empty:
        set_upload_notice("master", True, message)
        st.rerun()
    st.success(message + " Perbaiki baris di atas lalu simpan lagi; muat ulang halaman untuk melihat kapasitas terbaru.")


OMZET_KINDS = {
    "Terjual 30 hari (QTY)": "count", "Omzet 30 hari": "money", "Prediksi QTY 30 hari": "count", "Prediksi omzet 30 hari": "money",
    "Stok 10037": "count", "Min": "count", "Titik pesan ulang": "count", "Max": "count", "Barang dalam perjalanan": "count",
}


def _trend_text(value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "–"
    if np.isinf(value):
        return "▲ baru laku"
    arrow = "▲" if value > 0.5 else ("▼" if value < -0.5 else "＝")
    return f"{arrow} {fmt_pct(abs(value), 0)}"


def _days_text(value) -> str:
    if value is None or not np.isfinite(value):
        return "–"
    return "habis" if value <= 0 else f"{fmt_num(value, 0)} hari"


def _omzet_columns(src: pd.DataFrame) -> dict:
    """Kolom omzet & prediksi yang sama untuk tabel lorong dan tabel SKU."""
    return {
        "Terjual 30 hari (QTY)": src["qty_30"], "Omzet 30 hari": src["omzet_30"], "Tren omzet": src["tren_pct"].map(_trend_text),
        "Prediksi QTY 30 hari": src["pred_30"].round(0), "Prediksi omzet 30 hari": src["pred_omzet_30"].round(0),
        "Stok cukup untuk": src["hari_cukup"].map(_days_text),
    }


def _with_total(frame: pd.DataFrame, label_col: str, label: str) -> pd.DataFrame:
    frame = frame.copy()
    for column in OMZET_KINDS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(float)
    total = {c: (np.nan if pd.api.types.is_numeric_dtype(frame[c]) else "") for c in frame.columns}
    total[label_col] = label
    for column in ("Terjual 30 hari (QTY)", "Omzet 30 hari", "Prediksi QTY 30 hari", "Prediksi omzet 30 hari", "Stok 10037"):
        if column in frame.columns:
            total[column] = float(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())
    return pd.concat([pd.DataFrame([total], columns=frame.columns), frame], ignore_index=True)


def _latest_run_id(features):
    try:
        from sqlalchemy import func, select

        from src.core.feature_store import prediction_snapshot as snap

        with features.engine.connect() as conn:
            return conn.execute(select(func.max(snap.c.run_id))).scalar()
    except Exception:
        return None


def _omzet_note(view: dict) -> None:
    end = view.get("sales_end")
    bits = [f"Omzet & QTY 30 hari s.d. {end:%d/%m/%Y} (tanpa pesanan batal); tren = dibanding 30 hari sebelumnya." if end else "Data penjualan belum termuat, kolom omzet kosong."]
    if view.get("has_pred"):
        bits.append(f"Prediksi 30 hari dari {view.get('pred_source') or 'analisa terakhir'}.")
    else:
        bits.append("Prediksi belum ada: jalankan analisa sekali agar prediksi tersimpan.")
    st.markdown(f"<div class='field-hint'>{' '.join(bits)}</div>", unsafe_allow_html=True)


LANE_PRIORITY = {"Kosong": 0, "Hampir habis": 1, "Stok berlebih": 2, "Lokasi kosong": 3, "Aman": 4}


def _lane_detail(view: dict) -> None:
    st.markdown("<div class='section-title'>Isi lokasi per lorong</div>", unsafe_allow_html=True)
    loc = view["locations"]
    items = view["items"]
    lanes = sorted(loc["lorong_kode"].unique(), key=lambda s: (s[0] != "G", s))
    c1, c2, c3 = st.columns([1, 1.3, 1.7], vertical_alignment="bottom")
    lane = c1.selectbox("Lorong", lanes, key="gudang-lane", format_func=lambda s: f"{'Gondola' if s.startswith('G') else 'Racking'} {s}")
    part = loc.loc[loc["lorong_kode"] == lane].sort_values(["bay", "level"])
    if lane.startswith("G"):
        joined = part.merge(items, left_on="lokasi", right_on="pick_location", how="left", suffixes=("", "_sku"))
        status = joined["status"].where(joined["status"].notna(), "Lokasi kosong")
        stock = joined["stok_sku"] if "stok_sku" in joined else joined["stok"]
        frame = pd.DataFrame({
            "_status": status, "_impact": joined["dampak_omzet"].fillna(0.0),
            "Status": status.map(lambda v: STATUS_ICON.get(v, "⚪ Lokasi kosong")),
            "Lokasi": joined["lokasi"], "SKU": joined["sku"].fillna(""), "Nama": joined["nama"].fillna("— kosong —"),
            **_omzet_columns(joined),
            "Stok 10037": stock, "Min": joined["min_stock"], "Titik pesan ulang": joined["rop"], "Max": joined["max_stock"],
            "Saran": joined["saran"].fillna("Lokasi kosong — bisa dipakai barang kecil yang belum punya lokasi ambil"),
            "Kategori lokasi": joined["kategori"].str.title(), "Bay": joined["bay"], "Level": joined["level"],
        })
        note = (
            f"{fmt_num(int(part['terisi'].sum()))} dari {fmt_num(len(part))} lokasi terisi · "
            f"{fmt_num(int((~part['terisi']).sum()))} lokasi kosong"
        )
    else:
        cats = sorted(set(part["kategori"]))
        big = items.loc[items["kategori"].isin(cats) & items["spesifikasi"].str.lower().eq("besar")]
        frame = pd.DataFrame({
            "_status": big["status"], "_impact": big["dampak_omzet"].fillna(0.0),
            "Status": big["status"].map(lambda v: STATUS_ICON.get(v, v)),
            "SKU": big["sku"], "Nama": big["nama"], **_omzet_columns(big),
            "Stok 10037": big["stok"], "Min": big["min_stock"], "Titik pesan ulang": big["rop"], "Max": big["max_stock"],
            "Saran": big["saran"], "Kategori": big["kategori"].str.title(),
        })
        note = (
            f"Racking {lane}: {fmt_num(len(part))} lokasi, zona {', '.join(c.title() for c in cats)}. "
            "Barang besar tidak punya lokasi ambil di sistem, jadi daftar ini = barang besar pada kategori zona ini."
        )
    options = [s for s in LANE_PRIORITY if s in set(frame["_status"])]
    picked = c2.multiselect(
        "Status", options, key=f"gudang-lane-status-{lane}", placeholder="Semua status",
        format_func=lambda v: STATUS_ICON.get(v, "⚪ Lokasi kosong"),
    )
    counts = frame["_status"].value_counts()
    c3.markdown(
        f"<div class='field-hint'>{note}<br>"
        + " · ".join(f"{STATUS_ICON.get(k, '⚪ Lokasi kosong')} {fmt_num(int(counts[k]))}" for k in LANE_PRIORITY if k in counts)
        + "</div>",
        unsafe_allow_html=True,
    )
    if picked:
        frame = frame.loc[frame["_status"].isin(picked)]
    # Prioritas tindak lanjut: status dulu (Kosong → Hampir habis → Stok berlebih → Lokasi kosong → Aman),
    # lalu dampak omzet terbesar (prediksi omzet 30 hari; bila belum ada, omzet 30 hari terakhir).
    frame = (
        frame.assign(_p=frame["_status"].map(LANE_PRIORITY).fillna(9))
        .sort_values(["_p", "_impact"], ascending=[True, False], kind="mergesort")
        .drop(columns=["_p", "_impact", "_status"])
        .reset_index(drop=True)
    )
    st.markdown(
        "<div class='field-hint'>Urutan prioritas: 🔴 Kosong → 🟠 Hampir habis → 🟣 Stok berlebih → ⚪ Lokasi kosong → 🟢 Aman; "
        "dalam status yang sama, <b>omzet terbesar di atas</b> (prediksi omzet 30 hari, atau omzet 30 hari terakhir bila prediksi belum ada).</div>",
        unsafe_allow_html=True,
    )
    _omzet_note(view)
    frame = _with_total(frame, "Status", f"Total · {fmt_num(len(frame))} baris")
    key = f"gudang-lane-{lane}-{'-'.join(sorted(picked))}"
    batched_view(
        len(frame) - 1, key=key, noun="baris",
        render=lambda lo, hi: show_table(pd.concat([frame.iloc[:1], frame.iloc[1:].iloc[lo:hi]], ignore_index=True), bold_label=str(frame.iloc[0]["Status"]), kinds=OMZET_KINDS),
        download=lambda: download_excel(frame, f"isi_lorong_{lane}.xlsx", key=f"xl-lane-{lane}"),
    )


PRIORITY_LABEL = {0: "🔴 Tinggi", 1: "🟠 Sedang", 2: "🟢 Rendah"}


def _category_priority(r) -> tuple[int, str]:
    """(tingkat 0/1/2, daftar pekerjaan) per kategori — aturan ditulis juga di layar."""
    jobs, level = [], 2
    rak = r.rak_pct if np.isfinite(r.rak_pct) and r.rak_pct < 999 else np.nan
    if r.lokasi_rak == 0 and r.sku_besar_berstok > 0:
        level = 0
        jobs.append(f"{fmt_num(r.sku_besar_berstok)} SKU besar tanpa lokasi rak — siapkan lokasi rak untuk kategori ini")
    elif np.isfinite(rak) and rak > 100:
        level = 0
        jobs.append(f"Rak penuh ({fmt_pct(rak, 0)}): kurangi stok berlebih / pindahkan SKU lambat, atau tambah lokasi rak")
    elif np.isfinite(rak) and rak >= 75:
        level = min(level, 1)
        jobs.append(f"Rak hampir penuh ({fmt_pct(rak, 0)}): jangan tambah SKU besar baru")
    if np.isfinite(r.gondola_pct) and r.gondola_pct >= 100:
        level = min(level, 0 if r.kecil_tanpa_lokasi > 0 else 1)
        jobs.append("Gondola penuh: kosongkan lokasi SKU yang stoknya habis/lambat")
    if r.kecil_tanpa_lokasi > 0:
        level = min(level, 1)
        jobs.append(f"Tetapkan lokasi ambil untuk {fmt_num(r.kecil_tanpa_lokasi)} SKU kecil")
    if r.perlu_replenish >= 15:
        level = 0
    elif r.perlu_replenish >= 5:
        level = min(level, 1)
    if r.perlu_replenish > 0:
        jobs.append(f"Isi ulang {fmt_num(r.perlu_replenish)} SKU kosong / hampir habis")
    if r.stok > 0 and r.over_unit / r.stok >= 0.3:
        level = min(level, 1)
        jobs.append(f"Tahan pengisian: {fmt_num(r.over_unit)} unit berlebih ({fmt_pct(r.over_unit / r.stok * 100, 0)} stok)")
    return level, "; ".join(jobs) or "Tidak ada tindakan"


def _category_table(view: dict) -> None:
    st.markdown("<div class='section-title'>Kapasitas per kategori</div>", unsafe_allow_html=True)
    cats = view["categories"].copy()
    if cats.empty:
        st.caption("Belum ada data.")
        return
    levels = [_category_priority(r) for r in cats.itertuples(index=False)]
    cats["_lvl"] = [lv for lv, _ in levels]
    cats["_job"] = [job for _, job in levels]
    with st.container(border=True):
        st.markdown("**Cara membaca tabel ini**")
        st.markdown(
            "<div class='field-hint'>"
            "<b>1. Lihat kolom Prioritas</b> lalu kerjakan isi kolom <b>Yang perlu dikerjakan</b>, mulai dari 🔴 Tinggi.<br>"
            "<b>2. Rak terpakai</b> = SKU barang besar yang masih ada stoknya ÷ lokasi rak kategori itu (anggapan 1 SKU = 1 lokasi). "
            "Di atas 100% berarti barang lebih banyak daripada lokasi rak yang disediakan.<br>"
            "<b>3. Gondola terpakai</b> = lokasi gondola yang sudah ditempati barang kecil ÷ lokasi gondola kategori itu.<br>"
            "<b>4. Unit berlebih</b> = jumlah stok di atas batas Max: ruang yang bisa dibebaskan dengan menahan pengisian atau promo.<br>"
            "<b>5. SKU perlu diisi ulang</b> = SKU kosong atau hampir habis (di bawah titik pesan ulang).<br>"
            "<span style='color:#64748b'>Prioritas 🔴 Tinggi: rak > 100%, barang besar tanpa lokasi rak, gondola penuh sementara ada barang kecil tanpa lokasi, "
            "atau ≥ 15 SKU perlu diisi ulang. 🟠 Sedang: rak 75–100%, gondola penuh, barang kecil tanpa lokasi, 5–14 SKU perlu diisi ulang, "
            "atau unit berlebih ≥ 30% stok. Selain itu 🟢 Rendah.</span></div>",
            unsafe_allow_html=True,
        )
    groups = {lv: cats.loc[cats["_lvl"] == lv, "kategori"].str.title().tolist() for lv in (0, 1, 2)}
    st.markdown(
        "<div class='field-hint' style='margin:.2rem 0 .5rem'>"
        + " · ".join(f"<b>{PRIORITY_LABEL[lv]}</b> ({len(names)}): {', '.join(names) if names else '–'}" for lv, names in groups.items())
        + "</div>",
        unsafe_allow_html=True,
    )

    def pct(value) -> str:
        return "–" if not np.isfinite(value) or value >= 999 else fmt_pct(value, 0)

    cats = cats.sort_values("kategori").reset_index(drop=True)  # urut abjad
    # Omzet & prediksi per kategori (jumlah SKU di kategori itu).
    items = view["items"]
    money = items.groupby("kategori").agg(
        q30=("qty_30", "sum"), s30=("omzet_30", "sum"), pq=("pred_30", "sum"), ps=("pred_omzet_30", "sum"),
    ) if not items.empty else pd.DataFrame(columns=["q30", "s30", "pq", "ps"])
    prev = None
    if not items.empty and "tren_pct" in items.columns:
        base = items.assign(_prev=np.where(np.isfinite(items["tren_pct"]), items["omzet_30"] / (1 + items["tren_pct"] / 100), 0.0))
        prev = base.groupby("kategori")["_prev"].sum()
    money = money.reindex(cats["kategori"])
    trend = [
        (s30 - p) / p * 100 if prev is not None and p and p > 0 else np.nan
        for s30, p in zip(money["s30"].fillna(0), (prev.reindex(cats["kategori"]).fillna(0) if prev is not None else [0] * len(cats)))
    ]
    has_pred = bool(view.get("has_pred"))
    frame = pd.DataFrame({
        "Kategori": cats["kategori"].str.title(),
        "Prioritas": cats["_lvl"].map(PRIORITY_LABEL),
        "Yang perlu dikerjakan": cats["_job"],
        "Terjual 30 hari (QTY)": money["q30"].fillna(0).to_numpy(),
        "Omzet 30 hari": money["s30"].fillna(0).to_numpy(),
        "Tren omzet": [_trend_text(v) for v in trend],
        "Prediksi QTY 30 hari": money["pq"].to_numpy() if has_pred else np.nan,
        "Prediksi omzet 30 hari": money["ps"].to_numpy() if has_pred else np.nan,
        "Rak terpakai": cats["rak_pct"].map(pct),
        "Lokasi rak": cats["lokasi_rak"], "SKU besar berstok": cats["sku_besar_berstok"],
        "Gondola terpakai": cats["gondola_pct"].map(pct),
        "Lokasi gondola": cats["lokasi_gondola"], "Gondola terisi": cats["gondola_terisi"],
        "SKU kecil tanpa lokasi": cats["kecil_tanpa_lokasi"], "SKU perlu diisi ulang": cats["perlu_replenish"],
        "Unit berlebih": cats["over_unit"], "Stok 10037": cats["stok"],
    })
    rack_total, rack_sku = int(frame["Lokasi rak"].sum()), int(frame["SKU besar berstok"].sum())
    gon_total, gon_used = int(frame["Lokasi gondola"].sum()), int(frame["Gondola terisi"].sum())
    sales_now = float(frame["Omzet 30 hari"].sum())
    sales_prev = float(prev.sum()) if prev is not None else 0.0
    total = {
        "Kategori": "Total", "Prioritas": f"{len(groups[0])} tinggi · {len(groups[1])} sedang", "Yang perlu dikerjakan": "",
        "Terjual 30 hari (QTY)": frame["Terjual 30 hari (QTY)"].sum(), "Omzet 30 hari": sales_now,
        "Tren omzet": _trend_text((sales_now - sales_prev) / sales_prev * 100 if sales_prev > 0 else np.nan),
        "Prediksi QTY 30 hari": frame["Prediksi QTY 30 hari"].sum() if has_pred else np.nan,
        "Prediksi omzet 30 hari": frame["Prediksi omzet 30 hari"].sum() if has_pred else np.nan,
        "Rak terpakai": pct(rack_sku / rack_total * 100) if rack_total else "–", "Lokasi rak": rack_total, "SKU besar berstok": rack_sku,
        "Gondola terpakai": pct(gon_used / gon_total * 100) if gon_total else "–", "Lokasi gondola": gon_total, "Gondola terisi": gon_used,
        "SKU kecil tanpa lokasi": frame["SKU kecil tanpa lokasi"].sum(), "SKU perlu diisi ulang": frame["SKU perlu diisi ulang"].sum(),
        "Unit berlebih": frame["Unit berlebih"].sum(), "Stok 10037": frame["Stok 10037"].sum(),
    }
    full = pd.concat([pd.DataFrame([total]), frame], ignore_index=True)
    _omzet_note(view)
    kinds = {**OMZET_KINDS, "Unit berlebih": "count"}
    batched_view(
        len(frame), key="gudang-cat", noun="kategori",
        render=lambda lo, hi: show_table(
            pd.concat([full.iloc[:1], full.iloc[1:].iloc[lo:hi]], ignore_index=True), bold_label="Total", kinds=kinds, max_height=10_000,
            column_config={"Yang perlu dikerjakan": st.column_config.TextColumn(width="large")},
        ),
        download=lambda: download_excel(full, "kapasitas_per_kategori.xlsx", key="xl-gudang-cat"),
    )


def _sku_table(view: dict) -> None:
    st.markdown("<div class='section-title'>SKU di gudang 10037 & tindakan</div>", unsafe_allow_html=True)
    items = view["items"]
    if items.empty:
        st.caption("Belum ada data stok harian.")
        return
    f1, f2, f3, f4 = st.columns([1.6, 1.2, 1.2, 1])
    options = [f"{s} · {n}" for s, n in zip(items["sku"], items["nama"])]
    query = f1.selectbox("Cari SKU atau nama", options, index=None, placeholder="Ketik SKU atau nama…", key="gudang-sku-q")
    status_pick = f2.multiselect("Status", list(STATUS_ICON), key="gudang-sku-status", placeholder="Semua")
    cat_pick = f3.multiselect("Kategori", sorted(items["kategori"].unique()), key="gudang-sku-cat", placeholder="Semua", format_func=str.title)
    spec_pick = f4.multiselect("Barang", ["Besar", "Kecil"], key="gudang-sku-spec", placeholder="Semua")
    work = items
    if query:
        work = work.loc[work["sku"] == str(query).split(" · ")[0]]
    if status_pick:
        work = work.loc[work["status"].isin(status_pick)]
    if cat_pick:
        work = work.loc[work["kategori"].isin(cat_pick)]
    if spec_pick:
        work = work.loc[work["spesifikasi"].str.title().isin(spec_pick)]
    order = {"Kosong": 0, "Hampir habis": 1, "Stok berlebih": 2, "Aman": 3}
    work = work.assign(_o=work["status"].map(order)).sort_values(["_o", "dampak_omzet"], ascending=[True, False], kind="mergesort")
    frame = pd.DataFrame({
        "Status": work["status"].map(lambda v: STATUS_ICON.get(v, v)), "SKU": work["sku"], "Nama": work["nama"],
        **_omzet_columns(work),
        "Stok 10037": work["stok"], "Min": work["min_stock"], "Titik pesan ulang": work["rop"], "Max": work["max_stock"],
        "Barang dalam perjalanan": work["di_jalan"], "Saran": work["saran"],
        "Kategori": work["kategori"].str.title(), "Barang": work["spesifikasi"].str.title(),
        "Lokasi ambil (gondola)": work["pick_location"].replace("", "—"), "Sumber stok": work["sumber_stok"],
    }).reset_index(drop=True)
    explain([
        ("Urutan", "status dulu (Kosong → Hampir habis → Stok berlebih → Aman), lalu omzet terbesar di atas: prediksi omzet 30 hari, atau omzet 30 hari terakhir bila prediksi belum ada"),
        ("Tren omzet", "omzet 30 hari terakhir dibanding 30 hari sebelumnya (▲ naik, ▼ turun)"),
        ("Stok cukup untuk", "stok Site 10037 ÷ prediksi QTY harian"),
        ("Prediksi 30 hari", "dari analisa aplikasi; dibandingkan dengan Max untuk menyarankan Max dinaikkan/diturunkan"),
        ("Barang dalam perjalanan · Saran", "outstanding PO + TR + TO + TR dari toko lain (Replenishment Site 10037); isi ulang = Max − stok − barang dalam perjalanan"),
    ])
    _omzet_note(view)
    frame = _with_total(frame, "Status", f"Total · {fmt_num(len(frame))} SKU")
    batched_view(
        len(frame) - 1, key="gudang-sku", noun="SKU",
        render=lambda lo, hi: show_table(pd.concat([frame.iloc[:1], frame.iloc[1:].iloc[lo:hi]], ignore_index=True), bold_label=str(frame.iloc[0]["Status"]), kinds=OMZET_KINDS),
        download=lambda: download_excel(frame, "gudang_10037_sku.xlsx", key="xl-gudang-sku"),
    )
