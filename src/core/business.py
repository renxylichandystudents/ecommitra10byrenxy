"""Satu sumber untuk target bisnis: margin minimum, margin kotor (perkiraan), target penjualan bulanan.

Urutan sumber (sama di semua menu):
- Target penjualan: target yang disimpan untuk periode itu (Rekomendasi › Target penjualan) → bila belum ada,
  Target sales bulanan di Pengaturan bisnis → bila 0, belum ada target (memakai prediksi).
- Margin minimum: nilai yang disimpan bersama target periode → bila belum ada, Pengaturan bisnis.
- Margin kotor = 100 − perkiraan HPP rata-rata (% harga jual) di Pengaturan bisnis. HPP per SKU tidak dipakai.
- Batas total potongan Shopee + iklan = margin kotor − margin minimum: di atas batas ini margin bersih < margin minimum.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Targets:
    margin_min_pct: float
    margin_kotor_pct: float
    target_sales: float
    target_source: str
    margin_source: str

    @property
    def cost_limit_pct(self) -> float:
        return max(self.margin_kotor_pct - self.margin_min_pct, 0.0)

    @property
    def hpp_pct(self) -> float:
        return 100.0 - self.margin_kotor_pct


def business_targets(params: dict | None, saved_target: dict | None = None) -> Targets:
    params = params or {}
    margin_cfg = params.get("margin", {}) or {}
    hpp_pct = float(margin_cfg.get("hpp_pct_harga", 80) or 80)
    saved = saved_target or {}
    saved_sales = float(saved.get("target_sales_bersih", 0) or 0)
    params_sales = float((params.get("target", {}) or {}).get("sales_bulanan_rp", 0) or 0)
    if saved_sales > 0:
        sales, source = saved_sales, "target periode (Rekomendasi)"
    elif params_sales > 0:
        sales, source = params_sales, "Pengaturan bisnis"
    else:
        sales, source = 0.0, "belum diisi"
    if saved.get("margin_min_pct") not in (None, "") and saved_sales > 0:
        margin_min, margin_source = float(saved["margin_min_pct"]), "target periode (Rekomendasi)"
    else:
        margin_min, margin_source = float(margin_cfg.get("margin_min_pct", 8) or 8), "Pengaturan bisnis"
    return Targets(margin_min, 100.0 - hpp_pct, sales, source, margin_source)
