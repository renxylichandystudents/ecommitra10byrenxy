"""Expander "Pengaturan bisnis": parameter yang tidak ada di data Shopee, disimpan per pengguna."""

from __future__ import annotations

import copy
from pathlib import Path

import streamlit as st

from src.core.config import changed_from_default, default_params, save_params
from src.ui.common import DEFAULT_NOTE

FIELDS = (
    # (path, label, min, max, step, keterangan)
    ("lead_time.lokal_hari", "Lead time lokal (hari)", 0, 120, 1, "DC Cikupa ke pembeli, dipakai pada safety stock dan ROP."),
    ("lead_time.lokal_sigma_hari", "Variasi lead time lokal (hari)", 0, 60, 1, "0 = lead time stabil. Di atas 0 memakai rumus SS umum."),
    ("lead_time.impor_rata_hari", "Lead time impor rata-rata (hari)", 1, 365, 1, "Dipakai bila impor aktif."),
    ("lead_time.impor_maks_hari", "Lead time impor maksimum (hari)", 1, 365, 1, "SS impor = (maks − rata-rata) × permintaan harian."),
    ("gudang.kapasitas_unit", "Kapasitas gudang (unit)", 0, 10_000_000, 100, "Batas optimasi pembelian."),
    ("gudang.moq_unit", "MOQ pemasok (unit)", 1, 100_000, 1, "Jumlah minimum sekali pesan."),
    ("gudang.biaya_simpan_pct_tahun", "Biaya simpan (% harga per tahun)", 0, 100, 1, "Biaya kelebihan stok pada rekomendasi safety stock."),
    ("gudang.biaya_kehabisan_pct", "Biaya kehabisan stok (% harga)", 0, 200, 1, "Penalti kehilangan pembeli saat kosong."),
    ("margin.hpp_pct_harga", "HPP (% harga jual bersih)", 1, 100, 1, "Modal yang tertahan di stok."),
    ("margin.margin_min_pct", "Margin minimum (%)", 0, 100, 1, "Batas bawah harga flash sale dan markdown."),
    ("target.sales_bulanan_rp", "Target sales bulanan (Rp)", 0, 100_000_000_000, 1_000_000, "0 = memakai prediksi sebagai target."),
    ("iklan.target_roas", "Target ROAS", 1, 100, 1, "Dipakai rekomendasi iklan."),
    ("iklan.budget_maks_rp", "Budget iklan maksimum (Rp)", 0, 10_000_000_000, 100_000, "Batas alokasi budget per periode."),
)


def _get(params: dict, path: str):
    current = params
    for part in path.split("."):
        current = current.get(part, {}) if isinstance(current, dict) else {}
    return current


def _set(params: dict, path: str, value) -> None:
    parts = path.split(".")
    current = params
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def show_business_settings(params: dict, user_root: Path) -> dict:
    """Tampilkan expander dan simpan perubahan ke folder pengguna. Mengembalikan parameter terbaru."""
    with st.expander("Pengaturan bisnis"):
        st.caption("Parameter di luar laporan Shopee. Nilai yang belum diubah ditandai " f"“{DEFAULT_NOTE}”.")
        draft = copy.deepcopy(params)
        cols = st.columns(2)
        for index, (path, label, lo, hi, step, hint) in enumerate(FIELDS):
            value = _get(params, path)
            note = "" if changed_from_default(params, path) else f" · {DEFAULT_NOTE}"
            with cols[index % 2]:
                new = st.number_input(f"{label}{note}", min_value=lo, max_value=hi, value=int(value or 0), step=step, help=hint, key=f"bp-{path}")
            _set(draft, path, int(new))
        impor = st.checkbox("Ada SKU impor (lead time panjang)", value=bool(_get(params, "lead_time.impor_aktif")), key="bp-impor")
        _set(draft, "lead_time.impor_aktif", bool(impor))
        left, right = st.columns(2)
        if left.button("Simpan pengaturan", key="bp-save", type="primary"):
            save_params(draft, user_root)
            st.success("Pengaturan disimpan. Jalankan analisis lagi agar angka mengikuti pengaturan baru.")
            return draft
        if right.button("Kembalikan ke default", key="bp-reset"):
            fresh = default_params()
            save_params(fresh, user_root)
            for path, *_rest in FIELDS:
                st.session_state.pop(f"bp-{path}", None)
            st.session_state.pop("bp-impor", None)
            st.rerun()
    return params
