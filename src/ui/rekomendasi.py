"""Tab Rekomendasi: Nama & deskripsi, Iklan, Flash sale toko, Exposure media sosial.

Semua sub-tab membaca tabel keputusan yang sama dengan Ringkasan/Prediksi.
"""

from __future__ import annotations

import html
import re
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from src.core.nlp_competitor import build_name_recommendations, clean_text
from src.ui.common import batched_view, button_tabs, card, download_excel, fmt_num, reset_batches
from src.utils.format import show_table

STATUS_TONES = {"Poor": "#fee2e2", "Standard": "#fef9c3", "Excellence": "#dcfce7"}
# Nilai tersimpan tetap Poor/Standard/Excellence; tampilan memakai label Indonesia.
SCORE_DISPLAY = {"Poor": "Kurang", "Standard": "Cukup", "Excellence": "Sangat baik"}


def _cancel_reason_map(table: pd.DataFrame) -> dict[str, list[str]]:
    if table is None or table.empty or "alasan_batal" not in table.columns:
        return {}
    return {str(k): list(v or []) for k, v in zip(table["item_key"], table["alasan_batal"])}


def _product_frame(table: pd.DataFrame, frames) -> pd.DataFrame:
    """Satu baris per produk aktif (Kode Produk di unggahan stok terakhir), varian SKU digabung; penjualan dari tabel analisa.

    Nama & deskripsi di Shopee melekat pada produk (bukan per SKU varian), jadi penilaian SEO dihitung per produk."""
    from src.core.margin_file import sku_key

    stock = getattr(frames, "stock", pd.DataFrame())
    if stock is None or stock.empty or not {"product_code", "sku", "product_name"} <= set(stock.columns):
        base = table.copy()
        base["product_code"] = ""
        base["n_sku"] = 1
        base["variants"] = [[] for _ in range(len(base))]
        return base
    if "_submitted_at" in stock.columns:
        stock = stock.loc[stock["_submitted_at"].astype(str).eq(stock["_submitted_at"].astype(str).max())]
    work = stock.assign(
        product_code=stock["product_code"].astype(str).str.strip(),
        key=stock["sku"].astype(str).map(sku_key),
        variation=stock.get("variation", pd.Series("", index=stock.index)).fillna("").astype(str),
    )
    sales = pd.DataFrame()
    if table is not None and not table.empty:
        base = table if "harga_bersih" in table.columns else table.assign(harga_bersih=0.0)
        sales = base.assign(key=base["sku"].astype(str).map(sku_key)).groupby("key").agg(qty_total=("qty_total", "sum"), harga_bersih=("harga_bersih", "mean"))
    work = work.join(sales, on="key") if not sales.empty else work.assign(qty_total=0.0, harga_bersih=0.0)
    grouped = work.groupby("product_code", sort=False).agg(
        product_name=("product_name", "first"), sku=("key", "first"), skus=("key", list), variants=("variation", lambda v: [x for x in v if x.strip()]),
        n_sku=("key", "nunique"), qty_total=("qty_total", "sum"), harga_bersih=("harga_bersih", "mean"),
    ).reset_index()
    grouped["item_key"] = grouped["product_code"]
    grouped["variasi_tampil"] = ""
    return grouped.sort_values("qty_total", ascending=False, kind="mergesort").reset_index(drop=True)


def _name_recs(table: pd.DataFrame, frames, params: dict) -> tuple[pd.DataFrame, str]:
    products = _product_frame(table, frames)
    stamp = (len(products), float(pd.to_numeric(products.get("qty_total"), errors="coerce").fillna(0).sum()), len(frames.descriptions), len(frames.competitors), "v2")
    cached = st.session_state.get("_name-recs")
    if isinstance(cached, tuple) and cached[0] == stamp:
        return cached[1], cached[2]
    reasons: dict[str, list[str]] = {}
    if "skus" in products.columns and table is not None and "alasan_batal" in table.columns:
        from src.core.margin_file import sku_key

        by_sku = {sku_key(s): list(v or []) for s, v in zip(table["sku"].astype(str), table["alasan_batal"])}
        reasons = {code: sum((by_sku.get(k, []) for k in skus), []) for code, skus in zip(products["item_key"], products["skus"])}
    else:
        reasons = _cancel_reason_map(table)
    with st.spinner("Membandingkan nama & deskripsi semua produk dengan daftar peringkat kompetitor..."):
        recs, note = build_name_recommendations(products, frames.descriptions, frames.competitors, reasons, params)
    if not recs.empty and "qty_total" in products.columns:
        recs["Terjual"] = recs["item_key"].map(dict(zip(products["item_key"], products["qty_total"]))).fillna(0)
    st.session_state["_name-recs"] = (stamp, recs, note)
    return recs, note


def _similar_name_rules(table: pd.DataFrame) -> pd.DataFrame:
    """Kelompok cadangan bila association rules kosong: dua kata pertama nama yang sama."""
    heads = table.assign(_head=table["product_name"].map(lambda n: " ".join(clean_text(n).split()[:2])))
    rows = []
    for _head, part in heads.groupby("_head"):
        keys = part["item_key"].astype(str).tolist()
        for a, c in zip(keys, keys[1:]):
            rows.append({"antecedent": a, "consequent": c})
    return pd.DataFrame(rows, columns=["antecedent", "consequent"])


def _rank_text(row) -> str:
    if not row.get("Daftar kompetitor"):
        return "–"
    pos = row.get("Peringkat kita")
    if pos == pos and pos is not None and pos != "":
        change = row.get("Perubahan peringkat")
        move = f" ({'+' if change > 0 else ''}{int(change)})" if change == change and change is not None and change != 0 else ""
        return f"Daftar {row['Daftar kompetitor']} · #{int(pos)}{move}"
    return f"Daftar {row['Daftar kompetitor']} · belum masuk"


def _data_stamp(frames) -> str:
    """Penanda versi data: waktu unggah deskripsi produk terakhir | data stok terakhir."""
    parts = []
    for frame in (getattr(frames, "descriptions", None), getattr(frames, "stock", None)):
        if isinstance(frame, pd.DataFrame) and not frame.empty and "_submitted_at" in frame.columns:
            parts.append(str(frame["_submitted_at"].astype(str).max()))
        else:
            parts.append("-")
    return "|".join(parts)


def _history(features, recs: pd.DataFrame, frames) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Simpan snapshot penilaian untuk data saat ini (sekali per versi data) lalu bandingkan dengan penilaian sebelumnya."""
    from src.core import seo_history as sh

    if features is None or recs.empty:
        return pd.DataFrame(), pd.DataFrame()
    stamp = _data_stamp(frames)
    cache_key = (stamp, len(recs), st.session_state.get("_feature-version", 0))
    cached = st.session_state.get("_seo-history")
    if isinstance(cached, tuple) and cached[0] == cache_key:
        return cached[1], cached[2]
    try:
        history = features.read("seo_snapshot")
        if history.empty or not history["data_stamp"].astype(str).eq(stamp).any():
            features.insert("seo_snapshot", sh.snapshot_rows(recs, stamp), username="sistem", action="simpan:penilaian_seo")
            features.prune_snapshots("seo_snapshot", sh.KEEP_SNAPSHOTS, column="snapshot_at")
            history = features.read("seo_snapshot")
    except Exception:
        return pd.DataFrame(), pd.DataFrame()
    changes = sh.compare(recs, sh.previous_snapshot(history, stamp))
    st.session_state["_seo-history"] = (cache_key, changes, history)
    return changes, history


def _names_tab(table: pd.DataFrame, frames, params: dict, features=None) -> pd.DataFrame:
    from src.core import seo_history as sh

    recs, note = _name_recs(table, frames, params)
    if recs.empty:
        st.write("Belum ada produk untuk dinilai.")
        return recs
    changes, history = _history(features, recs, frames)
    if not changes.empty:
        recs = recs.merge(changes, on="item_key", how="left")
    if frames.competitors.empty:
        st.caption("Data Produk kompetitor belum diunggah: kata kunci dibaca dari nama produk sendiri.")
    n_sku = int(pd.to_numeric(recs.get("Jumlah SKU"), errors="coerce").fillna(1).sum())
    ranked = int(recs["Peringkat kita"].notna().sum()) if "Peringkat kita" in recs.columns else 0
    similar = int((recs.get("Kemiripan deskripsi", pd.Series(dtype=float)) > 60).sum())
    st.caption(
        f"Dinilai semua {fmt_num(len(recs))} produk aktif ({fmt_num(n_sku)} SKU varian) dari unggahan stok terakhir · "
        f"{fmt_num(ranked)} produk kita masuk daftar peringkat kompetitor · {fmt_num(similar)} deskripsi masih mirip produk lain (>60%).",
        help=f"Metode: {note}. Nama & deskripsi Shopee melekat pada produk, jadi varian (SKU) satu produk dinilai sekali.",
    )
    if "perubahan" in recs.columns and recs["tanggal_lalu"].notna().any():
        last = pd.to_datetime(recs["tanggal_lalu"]).max()
        cnt = recs["perubahan"].value_counts()
        before, after = recs["skor_lalu"].mean(), recs["skor_kini"].mean()
        k = st.columns(4)
        card(k[0], "Mengikuti rekomendasi", fmt_num(int(cnt.get("Mengikuti rekomendasi", 0))), hint="nama/deskripsi diubah sesuai saran")
        card(k[1], "Diubah di luar rekomendasi", fmt_num(int(cnt.get("Diubah di luar rekomendasi", 0))), hint="berubah, tetapi bukan dari saran")
        card(k[2], "Belum diubah", fmt_num(int(cnt.get("Belum diubah", 0))), hint=f"sama seperti penilaian {last:%d/%m/%Y}")
        card(k[3], "Skor SEO listing", f"{before:.0f} → {after:.0f}".replace(".", ","), hint=f"rata-rata, dibanding penilaian {last:%d/%m/%Y %H:%M}")
    elif features is not None:
        st.caption("Riwayat penilaian mulai disimpan hari ini. Setelah deskripsi/stok diunggah ulang dan analisa dijalankan, "
                   "perubahan (mengikuti rekomendasi atau di luar rekomendasi) akan terlihat di sini.")
    counts = recs["Status skor"].value_counts()
    current = st.session_state.get("name-filter", "Semua")
    cols = st.columns(4)
    for column, status in zip(cols, ("Semua", "Poor", "Standard", "Excellence")):
        total = len(recs) if status == "Semua" else int(counts.get(status, 0))
        if column.button(f"{SCORE_DISPLAY.get(status, status)} · {fmt_num(total)}", key=f"name-filter-{status}", type="primary" if current == status else "secondary", use_container_width=True):
            st.session_state["name-filter"] = status
            st.rerun()
    view = recs if current == "Semua" else recs.loc[recs["Status skor"].eq(current)]
    page = view.reset_index(drop=True)
    display = pd.DataFrame({
        "Kode produk": page["Kode produk"].where(page["Kode produk"].astype(str).str.len() > 0, page["SKU"]),
        "Nama produk saat ini": page["Nama produk saat ini"],
        "SKU varian": page.get("Jumlah SKU", 1),
        "Perubahan": page["perubahan"].map(lambda v: sh.ICON.get(v, "–")) if "perubahan" in page.columns else "–",
        "Status skor": page["Status skor"].map(lambda v: SCORE_DISPLAY.get(str(v), v)),
        "SEO saat ini": page.get("Skor SEO saat ini"),
        "SEO rekomendasi": page.get("Skor SEO"),
        "Rekomendasi nama baru": page["Rekomendasi nama baru"],
        "Kata kunci utama": page["Kata kunci utama"],
        "Peringkat kompetitor": [_rank_text(r) for r in page.to_dict("records")],
        "Keunikan deskripsi": 100 - page.get("Kemiripan deskripsi", 0),
        "USP utama": page["USP"].map(lambda items: ("⭐ " if items and items[0][1] else "") + (items[0][0].split(" — ")[0] if items else "–")),
    })
    if st.session_state.get("name-filter-was") != current:
        st.session_state["name-filter-was"] = current
        reset_batches("names")
        st.session_state.pop("name-picked", None)

    def _render_names(lo: int, hi: int) -> None:
        event = show_table(
            display.iloc[lo:hi],
            kinds={"SEO saat ini": "count", "SEO rekomendasi": "count", "SKU varian": "count", "Keunikan deskripsi": "pct"},
            on_select="rerun",
            selection_mode="single-row",
            key=f"name-table-{current}-{hi}",
            column_config={"USP utama": st.column_config.TextColumn(width="medium", help="Keunggulan paling menonjol; ⭐ = jarang disebut produk pembanding"),
                           "SEO saat ini": st.column_config.Column(help="% kaidah SEO yang dipenuhi nama & deskripsi yang sedang tayang"),
                           "SEO rekomendasi": st.column_config.Column(help="% kaidah SEO yang dipenuhi nama & deskripsi rekomendasi (rincian di bawah tabel)"),
                           "Keunikan deskripsi": st.column_config.Column(help="100% − kemiripan tertinggi dengan deskripsi produk lain; di bawah 40% berisiko dianggap duplikat")},
        )
        rows = getattr(getattr(event, "selection", None), "rows", []) or []
        if rows:
            st.session_state["name-picked"] = lo + int(rows[0])

    def _export() -> pd.DataFrame:
        out = page[["Kode produk", "SKU", "Jumlah SKU", "Nama produk saat ini", "Rekomendasi nama baru", "Kata kunci utama", "Kata kunci pendukung",
                    "Rekomendasi deskripsi"]].copy()
        out.insert(4, "Skor SEO saat ini", page.get("Skor SEO saat ini"))
        out.insert(5, "Skor SEO rekomendasi", page.get("Skor SEO"))
        out["Peringkat kompetitor"] = display["Peringkat kompetitor"]
        out["Keunikan deskripsi (%)"] = display["Keunikan deskripsi"].round(0)
        out["USP"] = page["USP"].map(lambda items: "; ".join(t for t, _u in (items or [])))
        if "perubahan" in page.columns:
            out["Perubahan"] = page["perubahan"]
            out["Keterangan perubahan"] = page["keterangan"]
        return out

    batched_view(
        len(display),
        key="names",
        render=_render_names,
        noun="produk",
        fragment=False,  # pilihan baris menampilkan rincian di bawah tabel (rerun penuh)
        download=lambda: download_excel(_export(), "rekomendasi_nama_deskripsi.xlsx", key="xl-names"),
    )
    picked_row = st.session_state.get("name-picked")
    with st.container(border=True):
        if picked_row is not None and 0 <= int(picked_row) < len(page):
            _name_detail(page.iloc[int(picked_row)], history)
        else:
            st.caption("Pilih satu baris untuk melihat nama rekomendasi, USP, pembanding kompetitor, cek SEO, dan deskripsi lengkap.")
    return recs


def _keyword_chips(text: str) -> str:
    words = [w.strip() for w in str(text or "").split(",") if w.strip()]
    return "".join(
        f"<span style='display:inline-block;margin:2px 4px 2px 0;padding:2px 10px;border-radius:999px;background:#eef2ff;color:#3730a3;font-size:var(--fs-xs)'>{html.escape(w)}</span>"
        for w in words
    )


def _description_html(text: str) -> str:
    """Paragraf + poin: baris "- x" jadi bullet, baris huruf kapital jadi subjudul tebal."""
    parts: list[str] = []
    bullets: list[str] = []

    def flush() -> None:
        if bullets:
            parts.append("<ul style='margin:.2rem 0 .5rem 1.1rem;padding:0'>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    for raw in str(text or "").split("\n"):
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("- ") or re.match(r"^\d+\.\s", line):
            bullets.append(html.escape(re.sub(r"^(- |\d+\.\s)", "", line)))
            continue
        flush()
        if line.isupper() and len(line) < 60:
            parts.append(f"<div style='font-weight:700;margin-top:.5rem'>{html.escape(line.title())}</div>")
        else:
            parts.append(f"<p style='margin:.2rem 0'>{html.escape(line)}</p>")
    flush()
    return "<div style='font-size:var(--fs-sm);line-height:1.5'>" + "".join(parts) + "</div>"


def _name_detail(item: pd.Series, history: pd.DataFrame | None = None) -> None:
    with st.container(border=True):
        if item.get("perubahan") == item.get("perubahan") and item.get("perubahan"):
            from src.core import seo_history as sh

            st.markdown(f"<div style='font-size:var(--fs-sm);margin-bottom:.3rem'><b>{html.escape(sh.ICON.get(item['perubahan'], item['perubahan']))}</b> · "
                        f"{html.escape(str(item.get('keterangan', '')))}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:var(--fs-xs);color:#64748b'>Nama saat ini · skor {html.escape(SCORE_DISPLAY.get(str(item['Status skor']), str(item['Status skor'])))} ({item['Poin skor']}/8)</div>"
                    f"<div style='font-size:var(--fs-sm)'>{html.escape(str(item['Nama produk saat ini']))}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:var(--fs-xs);color:#64748b;margin-top:.5rem'>Nama rekomendasi · skor {html.escape(SCORE_DISPLAY.get(str(item['Skor nama baru']), str(item['Skor nama baru'])))}</div>"
                    f"<div style='font-weight:700'>{html.escape(str(item['Rekomendasi nama baru']))}</div>", unsafe_allow_html=True)
        st.markdown(_keyword_chips(item["Kata kunci utama"]) + _keyword_chips(item["Kata kunci pendukung"]), unsafe_allow_html=True)
        checks = item["Kriteria"] if isinstance(item["Kriteria"], dict) else {}
        if checks:
            st.caption(" · ".join(f"{'✅' if ok else '❌'} {name}" for name, ok in checks.items()))
        usp = item.get("USP") or []
        left, right = st.columns(2)
        with left:
            st.markdown("<div style='font-weight:700;margin-top:.4rem'>Keunggulan (USP)</div>", unsafe_allow_html=True)
            if usp:
                st.markdown("".join(f"<div style='font-size:var(--fs-sm)'>{'⭐ ' if unique else '• '}{html.escape(t)}</div>" for t, unique in usp)
                            + "<div style='font-size:var(--fs-xs);color:#64748b;margin-top:.2rem'>⭐ = jarang disebut produk pembanding (pembeda utama)</div>",
                            unsafe_allow_html=True)
            else:
                st.caption("Belum ada fakta pembeda di nama/deskripsi produk ini.")
            comps = item.get("Pembanding teratas") or []
            st.markdown(f"<div style='font-weight:700;margin-top:.6rem'>Pembanding · {html.escape(_rank_text(item.to_dict()))}</div>", unsafe_allow_html=True)
            if comps:
                st.markdown("".join(f"<div style='font-size:var(--fs-sm)'>#{int(r) if r == r else '–'} · {html.escape(str(n)[:90])} <span style='color:#64748b'>({html.escape(str(shop))})</span></div>"
                                    for n, r, shop in comps), unsafe_allow_html=True)
                st.caption(str(item.get("Sumber pembanding", "")))
            else:
                st.caption("Tidak ada produk kompetitor serupa di data peringkat.")
        with right:
            st.markdown(f"<div style='font-weight:700;margin-top:.4rem'>Cek SEO · {int(item.get('Skor SEO', 0) or 0)}%</div>", unsafe_allow_html=True)
            for label, checks in (("Judul", item.get("SEO judul") or {}), ("Deskripsi", item.get("SEO deskripsi") or {})):
                st.markdown(f"<div style='font-size:var(--fs-xs);color:#64748b;margin-top:.2rem'>{label}</div>"
                            + "".join(f"<div style='font-size:var(--fs-sm)'>{'✅' if ok else '❌'} {html.escape(name)}</div>" for name, ok in checks.items()),
                            unsafe_allow_html=True)
            sim = item.get("Kemiripan deskripsi", 0) or 0
            if sim > 60:
                st.caption(f"Deskripsi {fmt_num(sim, 0)}% mirip dengan: {str(item.get('Paling mirip dengan', ''))[:80]}. Tambahkan detail khas produk ini (ukuran, kode, warna, kegunaan khusus).")
        if not item["Ada deskripsi lama"]:
            st.caption("Deskripsi lama belum diunggah; deskripsi baru disusun dari nama, variasi, dan kata kunci.")
        if history is not None and not history.empty:
            mine = history.loc[history["product_code"].astype(str) == str(item["item_key"])].sort_values("snapshot_at", ascending=False)
            if len(mine) > 1:
                with st.expander(f"Riwayat penilaian · {len(mine)} kali"):
                    show_table(pd.DataFrame({
                        "Tanggal": pd.to_datetime(mine["snapshot_at"]).dt.strftime("%d/%m/%Y %H:%M"), "Nama saat itu": mine["nama"],
                        "Skor nama": mine["status_nama"].map(lambda v: SCORE_DISPLAY.get(str(v), v)), "Skor SEO listing": mine["skor_seo"],
                        "Rekomendasi saat itu": mine["rek_nama"],
                    }), kinds={"Skor SEO listing": "count"}, max_height=10_000,
                        column_config={"Nama saat itu": st.column_config.TextColumn(width="large"), "Rekomendasi saat itu": st.column_config.TextColumn(width="large")})
        with st.container(height=360):
            st.markdown(_description_html(item["Rekomendasi deskripsi"]), unsafe_allow_html=True)
        st.caption("Salin deskripsi lengkap (ikon salin di pojok kanan kotak):")
        st.code(item["Rekomendasi deskripsi"], language=None, wrap_lines=True)


SUB_TABS = (
    ("nama-deskripsi", "Nama & deskripsi"),
    ("iklan", "Iklan"),
    ("flash-sale", "Flash sale toko"),
    ("exposure", "Exposure media sosial"),
    ("ranking-kategori", "Ranking kategori"),
)


def show_recommendations(
    table: pd.DataFrame,
    *,
    orders: pd.DataFrame,
    orders_all: pd.DataFrame,
    frames,
    params: dict,
    today: date,
    user_root: Path,
    features=None,
    data=None,
    window_start: date | None = None,
    username: str = "",
    can_edit: bool = False,
) -> None:
    from src.ui import rekomendasi_plus as plus

    st.subheader("Rekomendasi")
    if table is None or table.empty:
        st.write("Jalankan analisa terlebih dahulu.")
        return
    slugs = [slug for slug, _label in SUB_TABS]
    current = st.session_state.get("rek-sub") or slugs[0]
    if current not in slugs:
        current = slugs[0]
    st.session_state["rek-sub"] = current
    clicked = button_tabs(list(SUB_TABS), current, key="rek-sub-btn")
    if clicked and clicked != current:
        st.session_state["rek-sub"] = clicked
        st.rerun()
    picked = current
    window_start = window_start or today
    try:
        if picked == "nama-deskripsi":
            _names_tab(table, frames, params, features)
        elif picked == "iklan":
            plus.show_ads_strategy(table, features=features, data=data, params=params, window_start=window_start, username=username, can_edit=can_edit, frames=frames,
                                  orders=orders_all if isinstance(orders_all, pd.DataFrame) and not orders_all.empty else orders)
        elif picked == "flash-sale":
            plus.show_flash_sale(table, data=data, today=today, orders=orders, features=features, username=username, can_edit=can_edit)
        elif picked == "exposure":
            plus.show_exposure(table, features=features, data=data, orders=orders, frames=frames, today=today, username=username, can_edit=can_edit)
        elif picked == "ranking-kategori":
            plus.show_ranking(table, features=features, frames=frames, username=username, can_edit=can_edit)
    except Exception as exc:
        st.warning("Bagian ini belum bisa ditampilkan. Coba muat ulang halaman; bila tetap muncul, periksa data yang diunggah terakhir "
                   "(laporan iklan, stok, atau file margin).")
        with st.expander("Detail teknis"):
            st.code(f"{type(exc).__name__}: {exc}")
