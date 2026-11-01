from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DEFAULT_PARAMS_PATH = CONFIG_DIR / "business_params.yaml"
RULES_PATH = CONFIG_DIR / "rules.yaml"
LOCAL_PARAMS_NAME = "business_params.local.json"

_FALLBACK_PARAMS: dict[str, Any] = {
    "lead_time": {"lokal_hari": 7, "lokal_sigma_hari": 0, "impor_aktif": False, "impor_rata_hari": 60, "impor_maks_hari": 90},
    "gudang": {"kapasitas_unit": 100000, "moq_unit": 1, "biaya_simpan_pct_tahun": 20, "biaya_pesan_rp": 150000, "biaya_kehabisan_pct": 30},
    "margin": {"hpp_pct_harga": 80, "margin_min_pct": 8},
    "target": {"sales_bulanan_rp": 0},
    "iklan": {"target_roas": 8, "budget_maks_rp": 5000000, "porsi_sales_iklan_default_pct": 30, "roas_default": 6},
    "label": {"terlaris_top_n": 10, "populer_top_pct": 10, "diminati_top_pct": 10, "perlu_perhatian_batal_pct": 15, "perlu_perhatian_kali_median": 2},
    "shopee": {
        "judul_maks_karakter": 120,
        "judul_min_karakter": 25,
        "deskripsi_maks_karakter": 3000,
        "flash_sale_diskon_pct": [10, 15, 20],
        "flash_sale_kuota_pct_surplus": 50,
        "flash_sale_template_kolom": ["Tanggal", "SKU", "Nama Produk", "Harga Normal", "Harga Flash Sale", "Stok Flash Sale", "Batas Pembelian"],
    },
    "merek": ["mitra10"],
}


def _load_yaml(path: Path) -> Any:
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def default_params() -> dict[str, Any]:
    loaded = _load_yaml(DEFAULT_PARAMS_PATH)
    return _merge(_FALLBACK_PARAMS, loaded if isinstance(loaded, dict) else {})


def load_params(user_root: Path | None = None) -> dict[str, Any]:
    params = default_params()
    if user_root is None:
        return params
    local = Path(user_root) / LOCAL_PARAMS_NAME
    if local.exists():
        try:
            params = _merge(params, json.loads(local.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return params


def save_params(params: dict[str, Any], user_root: Path) -> None:
    root = Path(user_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / LOCAL_PARAMS_NAME).write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")


def changed_from_default(params: dict[str, Any], path: str) -> bool:
    """True bila parameter (mis. "lead_time.lokal_hari") sudah diubah user."""
    current: Any = params
    base: Any = default_params()
    for part in path.split("."):
        current = current.get(part) if isinstance(current, dict) else None
        base = base.get(part) if isinstance(base, dict) else None
    return current != base


def get(params: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = params
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def load_rules() -> list[dict[str, Any]]:
    loaded = _load_yaml(RULES_PATH)
    if isinstance(loaded, dict) and isinstance(loaded.get("rules"), list):
        return [rule for rule in loaded["rules"] if isinstance(rule, dict)]
    return []
