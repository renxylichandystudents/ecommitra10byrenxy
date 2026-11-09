"""Hak akses aplikasi. Sumber kebenaran: matriks `src.core.access.ACCESS`."""

from __future__ import annotations

from src.core.access import (
    ECOMMERCE_SPECIALIST,
    ROLE_LABELS,
    ROLES,
    SUPER_USER,
    TEAM_DC,
    TEAM_ICMD,
    allowed,
    normalize_role,
)

__all__ = [
    "ECOMMERCE_SPECIALIST", "ROLE_LABELS", "ROLES", "SUPER_USER", "TEAM_DC", "TEAM_ICMD",
    "PERMISSIONS", "SHEET_PERMISSIONS", "can", "allowed_sheets", "role_label",
]

# Nama izin lama → (menu di matriks, level yang dibutuhkan).
PERMISSIONS: dict[str, tuple[str, str]] = {
    "beranda": ("beranda", "view"),
    "riwayat_analisa": ("riwayat_analisa", "view"),
    "hapus_riwayat": ("riwayat_analisa", "edit"),
    "jalankan_analisa": ("data_latih", "edit"),
    "ubah_data_latih": ("data_latih", "edit"),
    "unggah_stok": ("upload_stok", "upload"),
    "ringkasan": ("ringkasan_prediksi", "view"),
    "prediksi": ("ringkasan_prediksi", "view"),
    "prediksi_vs_aktual": ("prediksi_vs_aktual", "view"),
    "ubah_password": ("ubah_password", "view"),
    "data": ("data", "view"),
    "folder_data": ("folder_data", "view"),
    "rekomendasi": ("rekomendasi", "view"),
    "laporan": ("laporan", "view"),
    "evaluasi_model": ("evaluasi_model", "view"),
    "kelola_user": ("kelola_user", "edit"),
}

SHEET_PERMISSIONS = {
    "Ringkasan": "ringkasan",
    "Prediksi": "prediksi",
    "Data": "data",
    "Folder data": "folder_data",
    "Rekomendasi": "rekomendasi",
    "Laporan": "laporan",
    "Evaluasi model": "evaluasi_model",
}


def can(role: str | None, permission: str) -> bool:
    rule = PERMISSIONS.get(permission)
    return bool(rule) and allowed(role, *rule)


def allowed_sheets(role: str | None, sheets) -> list[str]:
    return [name for name in sheets if can(role, SHEET_PERMISSIONS.get(name, ""))]


def role_label(role: str | None) -> str:
    key = normalize_role(role)
    return ROLE_LABELS.get(key, str(role or "-"))
