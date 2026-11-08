"""Expander "Pengaturan bisnis": parameter yang tidak ada di data Shopee, disimpan per pengguna."""

from __future__ import annotations

import copy
from pathlib import Path

import streamlit as st

from src.core.config import changed_from_default, default_params, save_params
from src.ui.common import DEFAULT_NOTE
from src.utils.format import input_angka

FIELDS = (
    # (path, label, min, max, step, keterangan)
    ("lead_time.lokal_hari", "Lead time lokal (hari)", 0, 120, 1, "Site 10037 ke pembeli, dipakai pada safety stock dan ROP."),
    ("gudang.kapasitas_unit", "Kapasitas gudang (unit)", 0, 10_000_000, 100, "Batas optimasi pembelian."),
    ("iklan.target_roas", "Target ROAS bawaan", 1, 100, 1, "Nilai awal di Rekomendasi › Iklan sebelum target ROAS bulan itu disimpan."),
)

# Tidak tampil di form; selalu memakai nilai config/business_params.yaml.
HIDDEN = (
    # Margin tidak lagi diatur di sini: margin per SKU dari File margin (Setting › Kalkulator biaya / Laporan margin).
    "margin.hpp_pct_harga",
    "margin.margin_min_pct",
    # Target sales tidak lagi satu angka untuk semua bulan: diunggah per bulan (tabel sales_target).
    "target.sales_bulanan_rp",
    # Budget iklan diatur per bulan di Rekomendasi › Iklan.
    "iklan.budget_maks_rp",
    "lead_time.lokal_sigma_hari",
    "lead_time.impor_rata_hari",
    "lead_time.impor_maks_hari",
    "lead_time.impor_aktif",
    "gudang.moq_unit",
    "gudang.biaya_simpan_pct_tahun",
    "gudang.biaya_kehabisan_pct",
)


def _get(params: dict, path: str):
    current = params
    for part in path.split("."):
        current = current.get(part, {}) if isinstance(current, dict) else {}
    return current


def _key(path: str, hi: int) -> str:
    return f"bp-txt-{path}" if hi >= 10_000 else f"bp-{path}"


def _set(params: dict, path: str, value) -> None:
    parts = path.split(".")
    current = params
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def show_business_settings(params: dict, user_root: Path, *, features=None, username: str = "", today=None) -> dict:
    """Tampilkan expander dan simpan perubahan ke folder pengguna. Mengembalikan parameter terbaru."""
    with st.expander("Pengaturan bisnis"):
        if features is not None:
            from datetime import date

            from src.ui.targets_view import show_target_uploader

            show_target_uploader(features, username=username, today=today or date.today())
            st.divider()
        st.caption("Parameter di luar laporan Shopee. Nilai yang belum diubah ditandai " f"“{DEFAULT_NOTE}”.")
        draft = copy.deepcopy(params)
        cols = st.columns(2)
        for index, (path, label, lo, hi, step, hint) in enumerate(FIELDS):
            value = _get(params, path)
            note = "" if changed_from_default(params, path) else f" · {DEFAULT_NOTE}"
            with cols[index % 2]:
                if hi >= 10_000:
                    new = input_angka(f"{label}{note}", value, key=_key(path, hi), lo=lo, hi=hi, help=hint)
                else:
                    new = st.number_input(f"{label}{note}", min_value=lo, max_value=hi, value=int(value or 0), step=step, help=hint, key=_key(path, hi))
            _set(draft, path, int(new))
        defaults = default_params()
        for path in HIDDEN:
            _set(draft, path, _get(defaults, path))
        left, right = st.columns(2)
        if left.button("Simpan pengaturan", key="bp-save", type="primary"):
            save_params(draft, user_root)
            st.success("Pengaturan disimpan. Jalankan analisa lagi agar angka mengikuti pengaturan baru.")
            return draft
        if right.button("Kembalikan ke default", key="bp-reset"):
            fresh = default_params()
            save_params(fresh, user_root)
            for path, _label, _lo, hi, *_rest in FIELDS:
                st.session_state.pop(_key(path, hi), None)
            st.rerun()
    return params
