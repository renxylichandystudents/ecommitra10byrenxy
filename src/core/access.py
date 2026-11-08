"""Matriks hak akses per menu × role (Revisi Final Tahap 1C).

Level: "edit" | "view" | "upload" | "write_note" | None.
- "view" terpenuhi oleh level apa pun yang tidak None.
- "upload" terpenuhi oleh "edit" atau "upload"; "write_note" oleh "edit" atau "write_note".
"""

from __future__ import annotations

SUPER_USER = "super_user"
ECOMMERCE_SPECIALIST = "ecommerce_specialist"
TEAM_DC = "team_dc"
TEAM_ICMD = "team_icmd"
ROLES = (SUPER_USER, ECOMMERCE_SPECIALIST, TEAM_DC, TEAM_ICMD)
ROLE_LABELS = {
    SUPER_USER: "Super user",
    ECOMMERCE_SPECIALIST: "E-commerce specialist",
    TEAM_DC: "Team DC",
    TEAM_ICMD: "Team IC/MD",
}
LEGACY_ROLES = {
    "SUPER_USER": SUPER_USER,
    "ECOMMERCE_SPECIALIST": ECOMMERCE_SPECIALIST,
    "GUDANG": TEAM_DC,
    "IC": TEAM_ICMD,
    "TEAM_ISI": TEAM_DC,
    "team_isi": TEAM_DC,
}

LEVELS = ("edit", "view", "upload", "write_note")


def _row(super_user, ecommerce, dc, icmd) -> dict[str, str | None]:
    return {SUPER_USER: super_user, ECOMMERCE_SPECIALIST: ecommerce, TEAM_DC: dc, TEAM_ICMD: icmd}


ACCESS: dict[str, dict[str, str | None]] = {
    "beranda": _row("view", "view", "view", "view"),
    "riwayat_analisa": _row("edit", "view", "view", "view"),
    "ringkasan_prediksi": _row("edit", "edit", "view", "view"),
    "prediksi_vs_aktual": _row("view", "view", "view", "view"),
    "data": _row("edit", "edit", None, None),
    "folder_data": _row("edit", "edit", None, None),
    "rekomendasi": _row("edit", "edit", None, None),
    "laporan": _row("edit", "edit", None, None),
    "evaluasi_model": _row("edit", "view", None, None),
    "data_latih": _row("edit", "edit", None, None),
    "setting_sku_dikecualikan": _row("edit", "edit", None, None),
    "setting_kalkulator_biaya": _row("edit", "edit", None, None),
    "setting_laporan_margin": _row("view", "view", None, None),
    "setting_kapasitas_gudang": _row("edit", "view", "upload", "view"),
    "setting_kedatangan_impor": _row("edit", "view", "view", "write_note"),
    "kelola_user": _row("edit", None, None, None),
    "ubah_password": _row("edit", "edit", "edit", "edit"),
}

MENU_LABELS = {
    "ringkasan_prediksi": "Ringkasan & Prediksi",
    "prediksi_vs_aktual": "Prediksi vs aktual",
    "data": "Data",
    "folder_data": "Folder data",
    "rekomendasi": "Rekomendasi",
    "laporan": "Laporan",
    "evaluasi_model": "Evaluasi model",
    "data_latih": "Upload data & Jalankan analisa",
    "setting_sku_dikecualikan": "Setting › SKU dikecualikan",
    "setting_kalkulator_biaya": "Setting › Kalkulator biaya",
    "setting_laporan_margin": "Setting › Laporan margin",
    "setting_kapasitas_gudang": "Setting › Kapasitas gudang",
    "setting_kedatangan_impor": "Setting › Kedatangan impor",
    "kelola_user": "Kelola user",
}

SETTING_TABS = (
    ("sku-dikecualikan", "SKU dikecualikan", "setting_sku_dikecualikan"),
    ("kalkulator-biaya", "Kalkulator biaya", "setting_kalkulator_biaya"),
    ("laporan-margin", "Laporan margin", "setting_laporan_margin"),
    ("kapasitas-gudang", "Kapasitas gudang", "setting_kapasitas_gudang"),
    ("kedatangan-impor", "Kedatangan impor", "setting_kedatangan_impor"),
    ("kelola-user", "Kelola user", "kelola_user"),
)


def normalize_role(role: str | None) -> str:
    text = str(role or "").strip()
    return LEGACY_ROLES.get(text, text)


def level(role: str | None, menu: str) -> str | None:
    return ACCESS.get(menu, {}).get(normalize_role(role))


def allowed(role: str | None, menu: str, need: str = "view") -> bool:
    have = level(role, menu)
    if have is None:
        return False
    if need == "view":
        return True
    if have == "edit":
        return True
    return have == need


def setting_tabs(role: str | None) -> list[tuple[str, str, str]]:
    return [tab for tab in SETTING_TABS if allowed(role, tab[2])]


def access_matrix_rows() -> list[dict[str, str]]:
    """Matriks hak akses untuk ditampilkan (read-only) di Kelola user."""
    names = {"edit": "Ubah", "view": "Lihat", "upload": "Unggah", "write_note": "Tulis catatan", None: "—"}
    return [
        {"Menu": label, **{ROLE_LABELS[role]: names[ACCESS[menu][role]] for role in ROLES}}
        for menu, label in MENU_LABELS.items()
    ]
