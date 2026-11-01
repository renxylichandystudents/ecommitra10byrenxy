"""Satu matriks hak akses untuk seluruh aplikasi."""

from __future__ import annotations

SUPER_USER = "SUPER_USER"
ECOMMERCE_SPECIALIST = "ECOMMERCE_SPECIALIST"
IC = "IC"
GUDANG = "GUDANG"
ROLES = (SUPER_USER, ECOMMERCE_SPECIALIST, IC, GUDANG)
ROLE_LABELS = {
    SUPER_USER: "Super user",
    ECOMMERCE_SPECIALIST: "E-commerce specialist",
    IC: "IC",
    GUDANG: "Gudang",
}

_ALL = frozenset(ROLES)
_ECOM = frozenset({SUPER_USER, ECOMMERCE_SPECIALIST})
_SUPER = frozenset({SUPER_USER})

PERMISSIONS: dict[str, frozenset[str]] = {
    "beranda": _ALL,
    "riwayat_analisa": _ALL,
    "jalankan_analisa": _ALL,
    "ubah_data_latih": _ALL,
    "ringkasan": _ALL,
    "prediksi": _ALL,
    "ubah_password": _ALL,
    "data": _ECOM,
    "folder_data": _ECOM,
    "rekomendasi": _ECOM,
    "laporan": _ECOM,
    "evaluasi_model": _SUPER,
    "kelola_user": _SUPER,
    "hapus_riwayat": _SUPER,
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
    return bool(role) and role in PERMISSIONS.get(permission, frozenset())


def allowed_sheets(role: str | None, sheets) -> list[str]:
    return [name for name in sheets if can(role, SHEET_PERMISSIONS.get(name, ""))]


def role_label(role: str | None) -> str:
    return ROLE_LABELS.get(str(role or ""), str(role or "-"))
