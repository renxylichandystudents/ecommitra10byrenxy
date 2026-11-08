"""Setting › Kapasitas gudang (Site 10037): denah, data replenishment harian, dan analisa kapasitas."""

from __future__ import annotations

import html
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st

from src.core import gudang
from src.ui.common import batched_view, card, download_excel, explain, fmt_num, fmt_pct
from src.utils.format import show_table

STATUS_ICON = {"Kosong": "🔴 Kosong", "Di bawah ROP": "🟠 Di bawah ROP", "Lebih dari Max": "🟣 Lebih dari Max", "Aman": "🟢 Aman"}
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
    return frame, dates[0], dates


def _table_maps(table: pd.DataFrame | None) -> tuple[dict, dict, dict]:
    stock, names, pred = {}, {}, {}
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
    return stock, names, pred


def cached_view(features, table: pd.DataFrame | None) -> dict | None:
    """Analisa gudang (disimpan di sesi; dihitung ulang bila snapshot replenishment/tabel berubah)."""
    repl, snap, _dates = load_replenishment(features)
    locations = load_locations(features)
    denah = load_denah(features)
    stamp = (gudang.snapshot_stamp(snap), len(repl), 0 if table is None else len(table), len(locations), 0 if denah is None else len(denah["cells"]))
    cache = st.session_state.get("_gudang_view")
    if cache and cache[0] == stamp:
        return cache[1]
    stock, names, pred = _table_maps(table)
    view = gudang.build_view(locations, repl, stock=stock, names=names, pred_daily=pred)
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
                    lines.append(f"⚠ {int(bay['masalah'])} SKU kosong / di bawah ROP")
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
        items = [("Tidak ada", "#f1f5f9"), ("1 SKU kosong / di bawah ROP", "#fecaca"), ("≥ 2 SKU", "#f87171")]
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
    extra = "" if mode != "Keterisian" else "<span style='font-size:.8rem;color:#b91c1c;margin-left:4px'>▢ garis merah = ada SKU kosong / di bawah ROP</span>"
    return f"<div style='margin:4px 0 8px'>{chips}{extra}</div>"


# --------------------------------------------------------------------------- halaman


def show_capacity(features, table: pd.DataFrame, *, may_upload: bool, username: str, require) -> None:
    st.markdown(f"**Kapasitas gudang · Site {gudang.SITE} {gudang.SITE_NAME}**")
    view = cached_view(features, table)
    loc = view["locations"]
    _upload_box(features, may_upload=may_upload, username=username, require=require, expanded=loc.empty or not view.get("has_repl"))
    if loc.empty:
        st.info(
            "Denah gudang belum ada. Unggah file **LAYOUT_ECOM** (berisi sheet LAY OUT dan Location) sekali di kotak "
            "**Perbarui data replenishment (harian) atau denah** di atas. Setelah itu cukup unggah replenishment harian."
        )
        return
    racks = loc.loc[loc["area"] == "Racking"]
    gondolas = loc.loc[loc["area"] == "Gondola"]
    snap = view.get("snapshot")
    st.caption(
        f"Denah: {fmt_num(len(loc))} lokasi · Racking R01–R04 {fmt_num(len(racks))} lokasi (barang Besar) · "
        f"Gondola G01–G03 {fmt_num(len(gondolas))} lokasi (barang Kecil, pick location). "
        + (f"Replenishment: {snap:%d/%m/%Y}." if snap else "Replenishment belum diunggah.")
        + (" Stok: data stok Site 10037 yang diunggah." if view.get("has_stock") else " Stok: Stock On Hand dari replenishment (data stok 10037 belum ada di analisa).")
    )
    if not view.get("has_repl"):
        st.info("Unggah laporan **Replenishment Calculation by Date** (Site 10037) agar isi lokasi dan status stok tampil di denah. Denah kosong di bawah memakai lokasi bawaan.")

    items = view["items"]
    cats = view["categories"]
    if view.get("has_repl"):
        value, note = gudang.capacity_card(view)
        cols = st.columns(4)
        card(cols[0], "Lokasi terpakai", value, hint=note)
        card(cols[1], "Gondola terisi", f"{fmt_num(int(gondolas['terisi'].sum()))} / {fmt_num(len(gondolas))}",
             hint=f"{fmt_num(int((items['pick_location'] != '').sum()))} SKU kecil punya pick location · {fmt_num(int((loc['n_sku'] > 1).sum()))} lokasi dipakai >1 SKU")
        need = items.loc[items["status"].isin(["Kosong", "Di bawah ROP"])]
        card(cols[2], "Perlu replenish", fmt_num(len(need)), hint=f"{fmt_num(int((items['status'] == 'Kosong').sum()))} kosong · {fmt_num(int((items['status'] == 'Di bawah ROP').sum()))} di bawah ROP/Min")
        over = items.loc[items["status"] == "Lebih dari Max"]
        over_units = float((over["stok"] - over["max_stock"]).sum())
        card(cols[3], "Lebih dari Max", fmt_num(len(over)), hint=f"kelebihan {fmt_num(over_units)} unit memakan ruang")
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
                + ". Pertimbangkan menambah lokasi, memindah SKU lambat, atau menahan replenish SKU yang lebih dari Max.",
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


def _upload_box(features, *, may_upload: bool, username: str, require, expanded: bool = False) -> None:
    with st.expander("Perbarui data replenishment (harian) atau denah", expanded=expanded):
        if not may_upload:
            st.caption("Role Anda hanya melihat. Unggahan oleh Team DC atau Super user.")
        st.markdown(
            "<div class='field-hint'>Unggah laporan <b>Replenishment Calculation by Date</b> Site 10037 dari sistem (xlsx/csv) setiap hari. "
            "Yang dipakai: Item No, Item Category, Spesifikasi Barang (Besar/Kecil), Pick Location, Min/Max/ROP, Stock On Hand, Outstanding PO/TR. "
            "File LAYOUT_ECOM lengkap juga bisa diunggah: sheet Location memperbarui daftar lokasi, sheet replenishment ikut tersimpan.</div>",
            unsafe_allow_html=True,
        )
        upload = st.file_uploader("File replenishment / layout", type=["xlsx", "xls", "csv"], key="gudang-upload", disabled=not may_upload)
        if upload is None or not may_upload:
            return
        try:
            if upload.name.lower().endswith(".csv"):
                raw = pd.read_csv(upload, header=None, dtype=object)
                repl, snap = gudang.parse_replenishment(raw)
                found = {"denah": None, "locations": None, "repl": repl, "snapshot": snap}
            else:
                found = gudang.read_layout_workbook(upload.getvalue())
        except Exception as exc:  # noqa: BLE001 - tampilkan pesan yang bisa dibaca
            st.error(f"File tidak bisa dibaca: {exc}")
            return
        repl, locations, denah = found["repl"], found["locations"], found["denah"]
        if repl is None and locations is None and denah is None:
            st.error("Tidak ditemukan tabel replenishment (kolom Item No), sheet Location, maupun sheet LAY OUT.")
            return
        snap = found["snapshot"] or datetime.now().date()
        parts = []
        if denah is not None:
            parts.append(f"denah ({fmt_num(sum(1 for c in denah['cells'] if c.get('k')))} bay)")
        if locations is not None:
            parts.append(f"{fmt_num(len(locations))} lokasi")
        if repl is not None:
            parts.append(f"replenishment {fmt_num(len(repl))} SKU tanggal {snap:%d/%m/%Y} ({fmt_num(int((repl['pick_location'] != '').sum()))} punya pick location)")
        st.markdown("Terbaca: " + " · ".join(parts))
        if st.button("Simpan", type="primary", key="gudang-save"):
            import json

            require("setting_kapasitas_gudang", "upload")
            if denah is not None:
                features.insert("warehouse_denah", [{"created_at": datetime.now(), "uploaded_by": username, "content": json.dumps(denah)}], username=username, action="unggah:denah_gudang")
            if locations is not None:
                keep = locations[["lokasi", "rak", "lorong", "bay", "level", "slot", "kategori"]]
                features.replace("warehouse_location", keep, keys=["lokasi"], username=username, action="unggah:lokasi_gudang")
            if repl is not None:
                rows = repl.assign(snapshot_date=snap, uploaded_by=username, uploaded_at=datetime.now())
                features.remove("warehouse_replenishment", {"snapshot_date": snap}, username=username, action="ganti:replenishment")
                features.insert("warehouse_replenishment", rows, username=username, action="unggah:replenishment")
                features.prune_snapshots("warehouse_replenishment", keep=60)
            st.session_state.pop("_gudang_view", None)
            st.success("Tersimpan.")
            st.rerun()


def _lane_detail(view: dict) -> None:
    st.markdown("<div class='section-title'>Isi lokasi per lorong</div>", unsafe_allow_html=True)
    loc = view["locations"]
    items = view["items"]
    lanes = sorted(loc["lorong_kode"].unique(), key=lambda s: (s[0] != "G", s))
    c1, c2 = st.columns([1, 2], vertical_alignment="bottom")
    lane = c1.selectbox("Lorong", lanes, key="gudang-lane", format_func=lambda s: f"{'Gondola' if s.startswith('G') else 'Racking'} {s}")
    part = loc.loc[loc["lorong_kode"] == lane].sort_values(["bay", "level"])
    if lane.startswith("G"):
        joined = part.merge(items, left_on="lokasi", right_on="pick_location", how="left", suffixes=("", "_sku"))
        frame = pd.DataFrame({
            "Lokasi": joined["lokasi"], "Bay": joined["bay"], "Level": joined["level"], "Kategori lokasi": joined["kategori"].str.title(),
            "SKU": joined["sku"].fillna(""), "Nama": joined["nama"].fillna("— kosong —"), "Stok 10037": joined["stok_sku"] if "stok_sku" in joined else joined["stok"],
            "Min": joined["min_stock"], "ROP": joined["rop"], "Max": joined["max_stock"],
            "Status": joined["status"].map(lambda v: STATUS_ICON.get(v, "⚪ Lokasi kosong") if isinstance(v, str) else "⚪ Lokasi kosong"),
            "Saran": joined["saran"].fillna("Lokasi kosong — bisa dipakai SKU kecil tanpa pick location"),
        })
        c2.markdown(
            f"<div class='field-hint'>{fmt_num(int(part['terisi'].sum()))} dari {fmt_num(len(part))} lokasi terisi · "
            f"{fmt_num(int((~part['terisi']).sum()))} lokasi kosong</div>",
            unsafe_allow_html=True,
        )
    else:
        cats = sorted(set(part["kategori"]))
        big = items.loc[items["kategori"].isin(cats) & items["spesifikasi"].str.lower().eq("besar")].sort_values("stok", ascending=False)
        frame = pd.DataFrame({
            "SKU": big["sku"], "Nama": big["nama"], "Kategori": big["kategori"].str.title(), "Stok 10037": big["stok"],
            "Min": big["min_stock"], "ROP": big["rop"], "Max": big["max_stock"],
            "Status": big["status"].map(lambda v: STATUS_ICON.get(v, v)), "Saran": big["saran"],
        })
        c2.markdown(
            f"<div class='field-hint'>Racking {lane}: {fmt_num(len(part))} lokasi, zona {', '.join(c.title() for c in cats)}. "
            "Barang Besar tidak punya pick location di sistem, jadi daftar di bawah = SKU Besar pada kategori zona ini.</div>",
            unsafe_allow_html=True,
        )
    frame = frame.reset_index(drop=True)
    batched_view(
        len(frame), key=f"gudang-lane-{lane}", noun="baris",
        render=lambda lo, hi: show_table(frame.iloc[lo:hi], kinds={"Stok 10037": "count", "Min": "count", "ROP": "count", "Max": "count"}),
        download=lambda: download_excel(frame, f"isi_lorong_{lane}.xlsx", key=f"xl-lane-{lane}"),
    )


def _category_table(view: dict) -> None:
    st.markdown("<div class='section-title'>Kapasitas per kategori</div>", unsafe_allow_html=True)
    cats = view["categories"].copy()
    explain([
        ("Rak", "SKU Besar yang masih berstok ÷ lokasi racking kategori itu (perkiraan 1 SKU ≈ 1 lokasi). Di atas 100% = barang melebihi lokasi rak yang disediakan"),
        ("Gondola", "lokasi gondola yang punya pick location ÷ lokasi gondola kategori itu"),
        ("Lebih dari Max", "Σ (stok − Max) untuk SKU yang stoknya di atas Maximum Stock: ruang yang bisa dibebaskan"),
    ])
    frame = pd.DataFrame({
        "Kategori": cats["kategori"].str.title(),
        "Lokasi rak": cats["lokasi_rak"], "SKU besar berstok": cats["sku_besar_berstok"], "Rak terpakai": cats["rak_pct"].where(cats["rak_pct"] < 999),
        "Lokasi gondola": cats["lokasi_gondola"], "Gondola terisi": cats["gondola_terisi"], "Gondola terpakai": cats["gondola_pct"],
        "SKU kecil tanpa lokasi": cats["kecil_tanpa_lokasi"], "Stok 10037": cats["stok"], "Unit lebih dari Max": cats["over_unit"],
        "SKU perlu replenish": cats["perlu_replenish"],
    }).sort_values("Rak terpakai", ascending=False, na_position="last").reset_index(drop=True)
    total = {
        "Kategori": "Total", "Lokasi rak": frame["Lokasi rak"].sum(), "SKU besar berstok": frame["SKU besar berstok"].sum(),
        "Lokasi gondola": frame["Lokasi gondola"].sum(), "Gondola terisi": frame["Gondola terisi"].sum(),
        "SKU kecil tanpa lokasi": frame["SKU kecil tanpa lokasi"].sum(), "Stok 10037": frame["Stok 10037"].sum(),
        "Unit lebih dari Max": frame["Unit lebih dari Max"].sum(), "SKU perlu replenish": frame["SKU perlu replenish"].sum(),
    }
    total["Rak terpakai"] = total["SKU besar berstok"] / total["Lokasi rak"] * 100 if total["Lokasi rak"] else np.nan
    total["Gondola terpakai"] = total["Gondola terisi"] / total["Lokasi gondola"] * 100 if total["Lokasi gondola"] else np.nan
    full = pd.concat([pd.DataFrame([total]), frame], ignore_index=True)
    show_table(full, bold_label="Total", kinds={"Rak terpakai": "pct", "Gondola terpakai": "pct", "Stok 10037": "count", "Unit lebih dari Max": "count"}, max_height=10_000)
    no_rack = cats.loc[(cats["lokasi_rak"] == 0) & (cats["sku_besar_berstok"] > 0), "kategori"].tolist()
    if no_rack:
        st.caption("Kategori dengan SKU Besar berstok tetapi tanpa lokasi racking di denah: " + ", ".join(c.title() for c in no_rack) + ".")


def _sku_table(view: dict) -> None:
    st.markdown("<div class='section-title'>SKU di gudang 10037 & tindakan</div>", unsafe_allow_html=True)
    items = view["items"]
    if items.empty:
        st.caption("Belum ada data replenishment.")
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
    order = {"Kosong": 0, "Di bawah ROP": 1, "Lebih dari Max": 2, "Aman": 3}
    gap = np.where(work["status"].eq("Lebih dari Max"), work["stok"] - work["max_stock"], work["max_stock"] - work["stok"])
    work = work.assign(_o=work["status"].map(order), _g=gap).sort_values(["_o", "_g"], ascending=[True, False])
    frame = pd.DataFrame({
        "SKU": work["sku"], "Nama": work["nama"], "Kategori": work["kategori"].str.title(), "Barang": work["spesifikasi"].str.title(),
        "Pick location": work["pick_location"].replace("", "—"), "Stok 10037": work["stok"], "Sumber stok": work["sumber_stok"],
        "Min": work["min_stock"], "ROP": work["rop"], "Max": work["max_stock"], "PO/TR jalan": work["out_po"] + work["out_tr"],
        "Prediksi 30 hari": work["pred_30"].round(0), "Status": work["status"].map(lambda v: STATUS_ICON.get(v, v)), "Saran": work["saran"],
    }).reset_index(drop=True)
    explain([
        ("Urutan", "Kosong → Di bawah ROP → Lebih dari Max → Aman; dalam tiap status, selisih terbesar di atas"),
        ("Prediksi 30 hari", "dari analisa aplikasi (laju harian × 30), dibandingkan dengan Max untuk menyarankan Max dinaikkan/diturunkan"),
    ])
    batched_view(
        len(frame), key="gudang-sku", noun="SKU",
        render=lambda lo, hi: show_table(frame.iloc[lo:hi], kinds={"Stok 10037": "count", "Min": "count", "ROP": "count", "Max": "count", "PO/TR jalan": "count", "Prediksi 30 hari": "count"}),
        download=lambda: download_excel(frame, "gudang_10037_sku.xlsx", key="xl-gudang-sku"),
    )
