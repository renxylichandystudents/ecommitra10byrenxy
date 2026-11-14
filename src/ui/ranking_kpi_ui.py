"""Rekomendasi › Ranking kategori: simpan ranking kompetitor per periode, rekap KPI (bulan/kuartal/semester/tahun) per
kategori Home & Living dan Elektronik, serta data periode untuk analisa peluang Top 10."""

from __future__ import annotations

import html
from datetime import datetime

import pandas as pd
import streamlit as st

from src.core import ranking_kpi as K
from src.ui.common import batched_view, card, download_excel, explain, file_check, fmt_num
from src.utils.format import show_table

INDEX_KEY = "ranking-kompetitor:index"
DATA_KEY = "ranking-kompetitor:data:"
MASTER_KEY = "ranking-kompetitor:kategori"
LEGACY = "lama"
ICON = {"Sudah Top 10": "🟦", "Dekat": "🟩", "Menengah": "🟧", "Jauh": "🟥"}
TEMPLATE_COLUMNS = ["Periode", "Kategori", "Dasar Ranking", "Ranking", "Change of Rank", "Nama Toko", "Nama Produk", "Toko sendiri", "Sales", "Qty", "Views"]


# ---------------------------------------------------------------- penyimpanan


def _version() -> tuple:
    return st.session_state.get("_feature-version", 0), st.session_state.get("_rk-version", 0)


def _bump() -> None:
    st.session_state["_rk-version"] = int(st.session_state.get("_rk-version", 0)) + 1


def _get(features, key: str, default):
    if features is None:
        return default
    try:
        value = features.get_json(key, None)
    except Exception:
        return default
    return default if value is None else value


def load_index(features) -> dict:
    cached = st.session_state.get("_rk-index")
    if isinstance(cached, tuple) and cached[0] == _version():
        return cached[1]
    index = _get(features, INDEX_KEY, {}) or {}
    st.session_state["_rk-index"] = (_version(), index)
    return index


def _frame(records) -> pd.DataFrame:
    frame = pd.DataFrame(records or [], columns=K.ROW_COLUMNS)
    if frame.empty:
        return frame
    frame["rank"] = pd.to_numeric(frame["rank"], errors="coerce")
    frame = frame.dropna(subset=["rank"])
    frame["rank"] = frame["rank"].astype(int)
    frame["daftar"] = pd.to_numeric(frame["daftar"], errors="coerce").fillna(0).astype(int)
    frame["ours"] = frame["ours"].astype(bool)
    for column in ("sales", "qty", "views"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in ("periode", "kategori", "grup", "dasar", "change", "shop", "product"):
        frame[column] = frame[column].fillna("").astype(str)
    return frame


def load_all(features) -> pd.DataFrame:
    """Semua baris ranking yang tersimpan (semua periode)."""
    cached = st.session_state.get("_rk-rows")
    if isinstance(cached, tuple) and cached[0] == _version():
        return cached[1]
    parts = []
    for pid in load_index(features):
        saved = _get(features, DATA_KEY + pid, {}) or {}
        part = _frame(saved.get("rows"))
        if not part.empty:
            part["periode"] = pid
            parts.append(part)
    rows = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=K.ROW_COLUMNS)
    st.session_state["_rk-rows"] = (_version(), rows)
    return rows


def load_master(features) -> pd.DataFrame:
    saved = _get(features, MASTER_KEY, None)
    if not saved:
        return K.default_master()
    frame = pd.DataFrame(saved, columns=["Grup", "Kategori", "Kata kunci", "Ada produk kita"])
    frame["Ada produk kita"] = frame["Ada produk kita"].fillna(False).astype(bool)
    frame[["Grup", "Kategori", "Kata kunci"]] = frame[["Grup", "Kategori", "Kata kunci"]].fillna("").astype(str)
    return frame.loc[frame["Kategori"].str.strip() != ""].reset_index(drop=True)


def _records(rows: pd.DataFrame) -> list[dict]:
    clean = rows[K.ROW_COLUMNS].copy()
    return clean.astype(object).where(clean.notna(), None).to_dict("records")


def save_period(features, pid: str, rows: pd.DataFrame, *, username: str, file: str, mode: str) -> int:
    """Simpan baris satu periode. mode "ganti" menimpa periode itu; "tambah" menambah daftar baru (daftar dengan
    kategori & dasar yang sama diganti)."""
    rows = rows.copy()
    rows["periode"] = pid
    if mode == "tambah":
        old = _frame((_get(features, DATA_KEY + pid, {}) or {}).get("rows"))
        if not old.empty:
            keys = set(zip(rows["kategori"], rows["dasar"]))
            old = old.loc[[(k, d) not in keys or not k for k, d in zip(old["kategori"], old["dasar"])]]
            offset = int(old["daftar"].max()) if not old.empty else 0
            rows["daftar"] = rows["daftar"].astype(int) + offset
            rows = pd.concat([old, rows], ignore_index=True)
    features.set_json(DATA_KEY + pid, {"rows": _records(rows)}, username=username)
    index = dict(_get(features, INDEX_KEY, {}) or {})
    files = list((index.get(pid) or {}).get("file", "").split(", ")) if mode == "tambah" and pid in index else []
    index[pid] = {"diunggah": datetime.now().strftime("%Y-%m-%d %H:%M"), "oleh": username,
                  "file": ", ".join(f for f in dict.fromkeys(files + [file]) if f), "baris": int(len(rows)),
                  "daftar": int(rows["daftar"].nunique())}
    features.set_json(INDEX_KEY, index, username=username)
    _bump()
    return int(len(rows))


def delete_period(features, pid: str, *, username: str) -> None:
    index = dict(_get(features, INDEX_KEY, {}) or {})
    index.pop(pid, None)
    features.set_json(INDEX_KEY, index, username=username)
    try:
        features.remove("kv_setting", {"key": DATA_KEY + pid}, username=username)
    except Exception:
        features.set_json(DATA_KEY + pid, {"rows": []}, username=username)
    _bump()


def periods(features) -> list[str]:
    return sorted(load_index(features), key=K.end_key)


def opportunity_input(rows: pd.DataFrame) -> tuple[pd.DataFrame, dict, dict]:
    """Baris satu periode → (frame berbentuk data Kompetitor untuk analisa peluang, nama kategori per daftar, grup per daftar)."""
    comp = pd.DataFrame({"Daftar": rows["daftar"].astype(int), "rank": rows["rank"].astype(str), "rank_change": rows["change"],
                         "shop_name": rows["shop"], "product_name": rows["product"], "own_shop": rows["ours"]})
    first = rows.drop_duplicates("daftar")
    labels = {int(d): (k + (f" · {b}" if b else "")) for d, k, b in zip(first["daftar"], first["kategori"], first["dasar"]) if k}
    groups = {int(d): g for d, g in zip(first["daftar"], first["grup"]) if g}
    return comp, labels, groups


# ---------------------------------------------------------------- rekap KPI


def _cell(value, status: str) -> str:
    if status == K.NO_DATA:
        return "–"
    if value is None or value != value:
        return "⬜ tidak ada"
    return f"{ICON.get(status, '')} #{int(value)}"


def show_recap(features, *, frames=None) -> None:
    rows = load_all(features)
    master = load_master(features)
    available = periods(features)
    if rows.empty:
        st.info("Belum ada data ranking berperiode. Buka **Unggah & periode** untuk mengunggah ranking kompetitor per bulan / kuartal / "
                "semester / tahun" + (", atau simpan data Kompetitor lama sebagai periode (mis. Q3 2026)." if _has_legacy(frames) else "."))
        _recap_guide()
        return
    summary = K.list_summary(rows)
    years = sorted({int(p[:4]) for p in available}, reverse=True)
    bases = [b for b in (K.ANY_BASIS, *K.BASES) if b in set(summary["dasar"])]
    c1, c2, c3, c4 = st.columns([1.6, 0.8, 1.1, 1.5])
    level = c1.segmented_control("Rekap per", list(K.LEVELS), default="Kuartal", key="rk-level") or "Kuartal"
    year = c2.selectbox("Tahun", years, key="rk-year")
    dasar = c3.selectbox("Dasar ranking", bases, key="rk-basis",
                         help="Ranking yang dinilai dari Sales, Qty, atau Views. 'Ranking unggahan' = unggahan tanpa kolom Dasar Ranking.")
    group_pick = c4.multiselect("Grup", list(K.GROUPS), default=list(K.GROUPS),
                                key="rk-groups", placeholder="Semua grup")
    wide, long = K.recap(summary, master, level, int(year), dasar)
    if group_pick:
        wide, long = wide.loc[wide["Grup"].isin(group_pick)], long.loc[long["Grup"].isin(group_pick)]
    targets = [K.short_label(t) for t in K.periods_in_year(level, int(year))]
    with_data = [t for t in targets if (long.loc[long["Periode"] == t, "Status"] != K.NO_DATA).any()] if not long.empty else []
    if not with_data:
        st.info(f"Belum ada data ranking untuk {level.lower()} di {year}. Periode tersimpan: " + ", ".join(K.period_label(p) for p in available) + ".")
        return
    coarse = [p for p in available if K.LEVELS.index(K.level_of(p)) > K.LEVELS.index(level) and int(p[:4]) == int(year)]
    if coarse:
        st.caption("Data " + ", ".join(K.short_label(p) for p in coarse) + f" diunggah per {K.level_of(coarse[0]).lower()} sehingga tidak bisa dipecah ke "
                   f"{level.lower()}; lihat rekap per {K.level_of(coarse[0]).lower()} atau yang lebih besar.")
    focus = st.select_slider("Periode yang dibahas", options=with_data, value=with_data[-1], key=f"rk-focus-{level}-{year}") if len(with_data) > 1 else with_data[0]
    part = long.loc[long["Periode"] == focus]
    status = part["Status"].value_counts().to_dict()
    hl_total = int((part["Grup"] == K.HL).sum())
    hl_data = int(((part["Grup"] == K.HL) & (part["Status"] != K.NO_DATA)).sum())
    k = st.columns(5)
    card(k[0], f"Kategori dipantau · {focus}", fmt_num(len(part)),
         hint=f"Home & Living {fmt_num(hl_data)}/{fmt_num(hl_total)} ada data · Elektronik {fmt_num(int((part['Grup'] == K.EL).sum()))}")
    card(k[1], "Sudah Top 10", fmt_num(status.get("Sudah Top 10", 0)), hint="kategori dengan produk kita di peringkat ≤ 10")
    card(k[2], "Dekat (11–50)", fmt_num(status.get("Dekat", 0)), hint="peluang tercepat masuk Top 10")
    card(k[3], "Menengah / Jauh", fmt_num(status.get("Menengah", 0) + status.get("Jauh", 0)), hint="peringkat 51–500 / > 500")
    card(k[4], "Belum ada data", fmt_num(status.get(K.NO_DATA, 0) + status.get(K.NOT_LISTED, 0)),
         hint=f"{fmt_num(status.get(K.NOT_LISTED, 0))} kategori tanpa produk kita di daftar")
    focus_pid = next(t for t in K.periods_in_year(level, int(year)) if K.short_label(t) == focus)
    notes = K.insights(summary, master, focus_pid, dasar, available)
    if group_pick:
        notes = [n for n in notes if not (K.HL not in group_pick and n.startswith(K.HL))]
    if notes:
        items = "".join(f"<li>{html.escape(n)}</li>" for n in notes)
        st.markdown("<div style='border:1px solid #e2e8f0;border-left:5px solid #ee4d2d;border-radius:12px;background:#fff;padding:.6rem 1rem;"
                    f"margin:.4rem 0 .7rem;font-size:.92rem;line-height:1.55'><b>Catatan analisa · {html.escape(focus)}</b><ul style='margin:.3rem 0 0'>{items}</ul></div>",
                    unsafe_allow_html=True)

    st.markdown(f"**Peringkat terbaik produk Mitra10 per kategori · per {level.lower()} {year}**")
    grid = wide[["Grup", "Kategori"]].copy()
    lookup = {(r["Periode"], r["Grup"], r["Kategori"]): r for r in long.to_dict("records")}
    for t in targets:
        grid[t] = [_cell(lookup.get((t, g, c), {}).get("Peringkat"), lookup.get((t, g, c), {}).get("Status", K.NO_DATA))
                   for g, c in zip(wide["Grup"], wide["Kategori"])]
    trend = []
    for g, c in zip(wide["Grup"], wide["Kategori"]):
        vals = [lookup.get((t, g, c), {}).get("Peringkat") for t in targets]
        vals = [v for v in vals if v is not None and v == v]
        trend.append("–" if len(vals) < 2 else ("▲ naik" if vals[-1] < vals[-2] else ("▼ turun" if vals[-1] > vals[-2] else "= tetap")))
    grid["Tren"] = trend
    show_table(grid, max_height=10_000, column_config={"Kategori": st.column_config.TextColumn(width="medium")})
    st.caption("🟦 Top 10 · 🟩 11–50 · 🟧 51–500 · 🟥 > 500 · ⬜ kategori ada datanya tetapi produk kita tidak ada di daftar · – belum ada data. "
               "Periode tanpa unggahan langsung disusun dari periode di dalamnya (lihat kolom Sumber di tabel detail).")

    st.markdown(f"**Detail KPI · {focus}**")
    detail = part.copy()
    detail["Status"] = [f"{ICON.get(s, '')} {s}".strip() for s in detail["Status"]]
    order = {s: i for i, s in enumerate(K.STATUS_ORDER)}
    detail = detail.assign(_o=part["Status"].map(order).fillna(9), _p=pd.to_numeric(part.get("Peringkat"), errors="coerce").fillna(1e9)).sort_values(["Grup", "_o", "_p"]).drop(columns=["_o", "_p"])
    metric_cols = [c for c in detail.columns if c.endswith(" kita") or c.endswith(" #10")]
    empty_metrics = [c for c in metric_cols if pd.to_numeric(detail[c], errors="coerce").isna().all()]
    shown = detail.drop(columns=empty_metrics + ["Periode"], errors="ignore")
    for column in ("Sumber", "Cakupan", "Produk terbaik", "Toko #1"):
        if column in shown.columns:
            shown[column] = shown[column].fillna("–").replace({"": "–"})
    kinds = {c: "count" for c in ("Peringkat", "Terbaik", "Produk kita", "Di Top 10", "Di Top 50")}
    kinds.update({c: "dec" for c in ("Rata-rata",)})
    kinds.update({c: ("idr" if c.startswith("Sales") else "count") for c in metric_cols})
    batched_view(
        len(shown), key="rk-kpi", noun="kategori",
        render=lambda lo, hi: show_table(shown.iloc[lo:hi], kinds=kinds, max_height=10_000, dash_missing=True,
                                         column_config={"Produk terbaik": st.column_config.TextColumn(width="large"),
                                                        "Sumber": st.column_config.Column(help="unggahan periode itu, atau rekap dari periode lebih kecil di dalamnya"),
                                                        "Cakupan": st.column_config.Column(help="bulan yang tercakup data dibanding panjang periode")}),
        download=lambda: download_excel({"Rekap": grid, "Detail semua periode": long, "Data ranking": rows}, f"kpi_ranking_{level.lower()}_{year}.xlsx", key="xl-rk-kpi"),
    )
    if empty_metrics:
        st.caption("Sales/Qty/Views belum ada di unggahan periode ini, jadi kolomnya disembunyikan. Tambahkan kolom itu di file berikutnya "
                   "agar selisih ke peringkat #10 ikut dihitung.")
    _recap_guide()


def _recap_guide() -> None:
    with st.expander("Cara membaca rekap KPI"):
        explain([
            ("Sumber data", "unggahan ranking kompetitor per periode (menu Unggah & periode). Tiap daftar = satu ranking kategori Shopee"),
            ("Kategori dipantau", "Home & Living: semua kategori (yang belum diunggah tampil '–'); Elektronik: hanya kategori yang memuat produk Mitra10"),
            ("Peringkat", "peringkat terbaik produk Mitra10 di kategori itu. Bila satu kategori diunggah lebih dari satu daftar dengan dasar sama, diambil yang terbaik"),
            ("Bulan → kuartal → semester → tahun", "pakai unggahan periode itu bila ada; kalau tidak, disusun dari periode di dalamnya: peringkat = periode terakhir, "
                                                   "ditambah peringkat terbaik dan rata-rata. Kolom Cakupan menunjukkan berapa bulan yang tercakup"),
            ("Dasar ranking", "Sales, Qty, atau Views sesuai kolom Dasar Ranking di file; Sales/Qty/Views kita dibandingkan dengan produk peringkat #10"),
            ("Tren", "perbandingan dua periode terakhir yang ada datanya pada baris itu (▲ = peringkat membaik)"),
        ])


# ---------------------------------------------------------------- unggah


def _has_legacy(frames) -> bool:
    comp = getattr(frames, "competitors", None)
    return comp is not None and not comp.empty


def _period_picker(key: str, default: str | None = None) -> str:
    default = default or K.period_id("Bulan", datetime.now().year, datetime.now().month)
    level0 = K.level_of(default)
    c1, c2, c3 = st.columns([1.6, 0.8, 1.2])
    level = c1.segmented_control("Jenis periode", list(K.LEVELS), default=level0, key=f"{key}-lvl") or level0
    this_year = datetime.now().year
    year = c2.selectbox("Tahun", list(range(this_year + 1, this_year - 4, -1)), index=list(range(this_year + 1, this_year - 4, -1)).index(int(default[:4])), key=f"{key}-yr")
    options = K.periods_in_year(level, int(year))
    start = options.index(default) if default in options else len(options) - 1
    if len(options) == 1:
        c3.markdown(f"<div style='margin-top:1.9rem'><b>{K.period_label(options[0])}</b></div>", unsafe_allow_html=True)
        return options[0]
    return c3.selectbox("Periode", options, index=start, format_func=K.period_label, key=f"{key}-pid-{level}-{year}")


def _mapping_editor(rows: pd.DataFrame, master: pd.DataFrame, *, key: str) -> pd.DataFrame:
    table = K.list_table(rows, master)
    categories = sorted(set(master["Kategori"]) | {k for k in table["Kategori"] if k})
    st.caption("Pastikan tiap daftar sudah ber-Grup dan ber-Kategori Shopee. Kategori terisi otomatis dari kolom Kategori / nama sheet di file, "
               "atau ditebak dari nama produk (cek ulang). Pilihan kategori diatur di 'Daftar kategori dipantau'.")
    edited = st.data_editor(
        table, key=key, hide_index=True, use_container_width=True, row_height=35, height=min(35 * (len(table) + 1) + 3, 420),
        disabled=["Daftar", "Isi daftar (kata terbanyak)", "Contoh produk #1", "Produk kita", "Peringkat terbaik kita"],
        column_config={"Grup": st.column_config.SelectboxColumn("Grup", options=list(K.GROUPS), required=True, width="small"),
                       "Kategori": st.column_config.SelectboxColumn("Kategori Shopee", options=categories, width="medium"),
                       "Dasar": st.column_config.SelectboxColumn("Dasar ranking", options=["", *K.BASES], width="small"),
                       "Contoh produk #1": st.column_config.TextColumn(width="large")},
    )
    return edited


def _save_block(features, rows: pd.DataFrame, mapping: pd.DataFrame, pid: str, *, file: str, username: str, key: str, can_edit: bool, require) -> None:
    exists = pid in load_index(features)
    mode = "ganti"
    if exists:
        pick = st.radio(f"{K.period_label(pid)} sudah ada datanya", ["Tambahkan ke periode ini (kategori lain)", "Ganti seluruh data periode ini"],
                        key=f"{key}-mode", horizontal=True,
                        help="Tambahkan: daftar dengan kategori & dasar ranking yang sama diganti, kategori lain tetap.")
        mode = "tambah" if pick.startswith("Tambah") else "ganti"
    unmapped = int((mapping["Grup"] == K.UNMAPPED).sum()) + int((mapping["Kategori"].fillna("") == "").sum())
    if unmapped:
        st.caption(f"⚠️ {fmt_num(unmapped)} daftar belum lengkap Grup/Kategori-nya; tetap bisa disimpan dan dipetakan nanti (tampil sebagai 'Belum dipetakan').")
    if st.button(f"Simpan ranking {K.period_label(pid)}", type="primary", key=f"{key}-save", disabled=not can_edit):
        require("rekomendasi", "edit")
        final = K.apply_mapping(rows, mapping)
        try:
            n = save_period(features, pid, final, username=username, file=file, mode=mode)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Gagal menyimpan: {exc}")
            return
        st.session_state["rk-up-round"] = int(st.session_state.get("rk-up-round", 0)) + 1
        st.session_state["rk-notice"] = f"Ranking {K.period_label(pid)} tersimpan ({fmt_num(n)} baris). Rekap KPI sudah memakai data ini."
        st.rerun()


def show_upload(features, *, frames, username: str, can_edit: bool) -> None:
    from auth.ui import require

    master = load_master(features)
    notice = st.session_state.pop("rk-notice", None)
    if notice:
        st.success(notice)
    st.markdown("<div class='field-hint'>Unggah hasil ranking kompetitor per periode (bulan, kuartal, semester, atau tahun). Format yang terbaca: "
                "<b>ekspor ranking Shopee</b> (Ranking, Change of Rank, Shop Name, Products Name, baris My Shop) atau <b>tabel biasa</b> sesuai template. "
                "Tambahkan kolom <b>Kategori</b> (atau satu sheet per kategori, nama sheet = kategori), <b>Sales</b>, <b>Qty</b>, <b>Views</b>, dan bila "
                "ranking dinilai per metrik, kolom <b>Dasar Ranking</b> (Sales / Qty / Views). Kolom <b>Periode</b> opsional; tanpa itu periode dipilih di bawah.</div>",
                unsafe_allow_html=True)
    if not can_edit:
        st.caption("Hanya pengguna dengan hak ubah Rekomendasi yang bisa mengunggah.")
    t1, t2 = st.columns([3, 1])
    round_no = int(st.session_state.get("rk-up-round", 0))
    upload = t1.file_uploader("File ranking (.xlsx / .csv)", type=["xlsx", "xls", "csv"], key=f"rk-file-{round_no}", disabled=not can_edit)
    with t2:
        download_excel(pd.DataFrame(columns=TEMPLATE_COLUMNS), "template_ranking_kompetitor.xlsx", key="xl-rk-tpl", label="Unduh template")
    if upload is not None:
        try:
            rows = K.parse_upload(upload.getvalue(), upload.name)
        except Exception as exc:  # noqa: BLE001
            file_check(False, f"{upload.name}: {exc}")
            rows = pd.DataFrame()
        if rows.empty:
            file_check(False, f"{upload.name}: kolom Ranking dan nama produk tidak ditemukan.")
        else:
            metrics = [b for b in K.BASES if rows[b.lower()].notna().any()]
            file_check(True, f"{upload.name}: {fmt_num(len(rows))} baris · {fmt_num(rows['daftar'].nunique())} daftar · "
                             f"{fmt_num(int(rows['ours'].sum()))} baris produk Mitra10 · metrik: {', '.join(metrics) or 'belum ada Sales/Qty/Views'}.")
            parsed = {p: K.parse_period(p) for p in rows["periode"].unique() if str(p).strip()}
            known = sorted({v for v in parsed.values() if v}, key=K.end_key)
            if known and all(parsed.get(p) for p in rows["periode"].unique()):
                st.caption("Periode dari kolom Periode di file: " + ", ".join(K.period_label(p) for p in known))
                rows = rows.assign(periode=rows["periode"].map(parsed))
            else:
                pid = _period_picker(f"rk-up-{round_no}")
                rows = rows.assign(periode=pid)
                known = [pid]
            mapping = _mapping_editor(rows, master, key=f"rk-map-up-{round_no}")
            for pid in known:
                part = rows.loc[rows["periode"] == pid]
                _save_block(features, part, mapping.loc[mapping["Daftar"].isin(part["daftar"].unique())], pid, file=upload.name,
                            username=username, key=f"rk-up-{round_no}-{pid}", can_edit=can_edit, require=require)

    index = load_index(features)
    if _has_legacy(frames) and not any(str(m.get("file", "")).startswith("Data Kompetitor") for m in index.values()):
        comp = frames.competitors
        stamp = pd.to_datetime(comp.get("_submitted_at"), errors="coerce").max() if "_submitted_at" in comp.columns else None
        with st.expander(f"Data Kompetitor lama (unggahan {stamp:%d/%m/%Y}) → simpan sebagai periode" if stamp is not None and pd.notna(stamp)
                         else "Data Kompetitor lama → simpan sebagai periode", expanded=not index):
            st.caption("Data ranking yang sudah diunggah di menu Kompetitor belum punya periode dan nama kategori. Pilih periodenya "
                       "(mis. Kuartal 3) dan petakan tiap daftar ke kategori Shopee, lalu simpan agar masuk rekap KPI.")
            legacy = K.from_legacy(comp)
            pid = _period_picker("rk-legacy", default=K.period_id("Kuartal", datetime.now().year, 3))
            mapping = _mapping_editor(legacy, master, key="rk-map-legacy")
            _save_block(features, legacy, mapping, pid, file="Data Kompetitor (menu Upload data)", username=username, key="rk-legacy",
                        can_edit=can_edit, require=require)

    st.markdown("**Periode tersimpan**")
    if not index:
        st.caption("Belum ada periode tersimpan.")
    else:
        rows = load_all(features)
        listing = []
        for pid in periods(features):
            meta, part = index[pid], rows.loc[rows["periode"] == pid]
            listing.append({"Periode": K.period_label(pid), "Jenis": K.level_of(pid), "Daftar": meta.get("daftar"), "Baris": meta.get("baris"),
                            "Kategori terpetakan": int(part.loc[part["grup"] != "", "kategori"].nunique()),
                            "Daftar belum dipetakan": int(part.loc[part["grup"] == "", "daftar"].nunique()),
                            "Produk kita": int(part.loc[part["ours"], "product"].nunique()),
                            "Metrik": ", ".join(b for b in K.BASES if part[b.lower()].notna().any()) or "–",
                            "Diunggah": meta.get("diunggah"), "Oleh": meta.get("oleh"), "File": meta.get("file")})
        show_table(pd.DataFrame(listing), kinds={"Daftar": "count", "Baris": "count", "Kategori terpetakan": "count", "Daftar belum dipetakan": "count", "Produk kita": "count"},
                   column_config={"File": st.column_config.TextColumn(width="medium")})
        with st.expander("Ubah pemetaan kategori / hapus periode"):
            pid = st.selectbox("Periode", periods(features), index=len(index) - 1, format_func=K.period_label, key="rk-edit-pid")
            part = rows.loc[rows["periode"] == pid]
            ver = int(st.session_state.get("rk-edit-ver", 0))
            mapping = _mapping_editor(part, master, key=f"rk-map-edit-{pid}-{ver}")
            b1, b2, _sp = st.columns([1.2, 1.4, 2])
            if b1.button("Simpan pemetaan", type="primary", key="rk-edit-save", disabled=not can_edit):
                require("rekomendasi", "edit")
                save_period(features, pid, K.apply_mapping(part, mapping), username=username, file=index[pid].get("file", ""), mode="ganti")
                st.session_state["rk-edit-ver"] = ver + 1
                st.session_state["rk-notice"] = f"Pemetaan kategori {K.period_label(pid)} disimpan."
                st.rerun()
            sure = b2.checkbox(f"Yakin hapus {K.short_label(pid)}", key=f"rk-del-sure-{pid}")
            if st.button(f"Hapus data {K.period_label(pid)}", key="rk-del", disabled=not (can_edit and sure)):
                require("rekomendasi", "edit")
                delete_period(features, pid, username=username)
                st.session_state["rk-notice"] = f"Data {K.period_label(pid)} dihapus."
                st.rerun()

    with st.expander("Daftar kategori dipantau (Home & Living & Elektronik)"):
        st.caption("Home & Living: semua kategori di daftar ini masuk rekap KPI (termasuk yang belum ada datanya). Elektronik: masuk rekap bila dicentang "
                   "'Ada produk kita' atau produk Mitra10 muncul di ranking kategori itu. Samakan nama dengan kategori di Seller Centre. "
                   "Kata kunci dipakai untuk menebak kategori daftar yang tidak memuat nama kategori.")
        ver = int(st.session_state.get("rk-master-ver", 0))
        edited = st.data_editor(master, key=f"rk-master-{ver}", num_rows="dynamic", hide_index=True, use_container_width=True, row_height=35,
                                column_config={"Grup": st.column_config.SelectboxColumn("Grup", options=[K.HL, K.EL], required=True, width="small"),
                                               "Kategori": st.column_config.TextColumn(required=True, width="medium"),
                                               "Kata kunci": st.column_config.TextColumn(width="large"),
                                               "Ada produk kita": st.column_config.CheckboxColumn(width="small")})
        m1, m2, _sp = st.columns([1.2, 1.2, 2])
        if m1.button("Simpan daftar kategori", type="primary", key="rk-master-save", disabled=not can_edit):
            require("rekomendasi", "edit")
            clean = edited.dropna(subset=["Kategori"])
            clean = clean.loc[clean["Kategori"].astype(str).str.strip() != ""]
            features.set_json(MASTER_KEY, clean.astype(object).where(clean.notna(), None).to_dict("records"), username=username)
            st.session_state["rk-master-ver"] = ver + 1
            _bump()
            st.session_state["rk-notice"] = "Daftar kategori dipantau disimpan."
            st.rerun()
        if m2.button("Kembalikan daftar awal", key="rk-master-reset", disabled=not can_edit):
            require("rekomendasi", "edit")
            features.set_json(MASTER_KEY, [], username=username)
            st.session_state["rk-master-ver"] = ver + 1
            _bump()
            st.rerun()
