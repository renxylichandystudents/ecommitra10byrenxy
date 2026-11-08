"""Satu sumber untuk target bisnis: target penjualan bulanan dan margin minimum promo.

Urutan sumber (sama di semua menu):
- Target penjualan: target bulan itu (diunggah di Upload data › Target, atau disimpan di
  Rekomendasi › Target penjualan) → bila belum ada, belum ada target. Tidak ada satu angka untuk semua bulan.
- Margin minimum (syarat SKU boleh dipromosikan/diiklankan): nilai yang disimpan bersama target periode → bila belum ada, 0%
  (asal tidak rugi). Margin per SKU tidak lagi dari perkiraan HPP, melainkan dari File margin
  (Setting › Kalkulator biaya / Laporan margin).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Targets:
    margin_min_pct: float
    target_sales: float
    target_source: str
    margin_source: str


def business_targets(params: dict | None, saved_target: dict | None = None) -> Targets:
    params = params or {}
    saved = saved_target or {}
    saved_sales = float(saved.get("target_sales_bersih", 0) or 0)
    if saved_sales > 0:
        sales, source = saved_sales, "target bulanan"
    else:
        sales, source = 0.0, "belum diisi"
    if saved.get("margin_min_pct") not in (None, "") and saved_sales > 0:
        margin_min, margin_source = float(saved["margin_min_pct"]), "target bulanan"
    else:
        margin_min, margin_source = 0.0, "bawaan (asal tidak rugi)"
    return Targets(margin_min, sales, source, margin_source)
