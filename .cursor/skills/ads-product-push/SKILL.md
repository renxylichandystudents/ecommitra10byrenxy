---
name: ads-product-push
description: >-
  Rank Mitra10/Shopee product ads for push: transparent push_score (ROAS vs safe BEP,
  gap GMV, margin, stock, unoccupied), route tunggal vs grup, and Prioritize/Scale/Hold/Pause.
  Use when editing Rekomendasi › Iklan product selection, ads_strategy scoring, or Top-N push UI.
---

# Ads product push (Mitra10 / Shopee)

## When to use

- Changing how products are ranked for **Buat/Jadikan tunggal** vs **grup** toward monthly sales + ROAS targets.
- Extending `product_selection`, `build_plan`, or Rekomendasi sistem Top-N tables.
- Explaining why a SKU is Prioritize / Scale / Hold / Pause.

Do **not** use for Pantau Modal Harian live (TAM-1), keyword/`ads_search` engines, or replacing the Mitra10 monolith.

## Goals

1. **Primary:** ROAS aman di atas **safe BEP** per SKU (CM1 − fee → `1/contrib`; soft buffer ~15%).
2. **Secondary trigger:** close **gap_daily** GMV (prediksi omzet × ruang stok) — expand catalog when gap is large.
3. Seller-facing: skor 0–100, chip alasan 1 kalimat, rute tunggal/grup, aksi Prioritize / Scale (~+20%) / Hold / Pause.
4. Execution path stays **Unduh setelan Seller Center**.

## push_score (0–100, transparent)

Weighted components (sum of positive parts ≈ 100; CTR only subtracts):

| Component | Max | Source |
|---|---|---|
| Gap contribution | 30 | `min(prediksi_omzet, stok_room) / gap_daily` |
| ROAS vs safe BEP | 25 | hist ROAS vs `safe_bep = (1/contrib)×1.15`; no hist → mid score |
| Margin / not loss | 20 | positive CM; `ads_deepens_loss` → low |
| Stock cover | 15 | days cover `stok/qty_harian` (≥45 full, 21–45 mid, &lt;21 low) |
| Unoccupied bonus | 10 | code not in active `occupied` |
| CTR penalty | 0…−15 | **only if** `ctr` column present with values; never invent CTR |

Expose component fields when useful for tests/debug (`_gap`, `_roas_bep`, `_margin`, `_stock`, `_free`, `_ctr_pen`).

## Router tunggal vs grup

- **Tunggal:** CM tinggi, ROAS ≥ safe BEP (or strong gap hero), needs own ROAS/budget; saran family `Buat/Jadikan/Pertahankan iklan tunggal`.
- **Grup (2–30, similar margin/ROAS band):** mid-tier / catalog test; `Tambahkan/Pertahankan di grup` / `Pindahkan ke grup`. Do not mix underwater margin dogs into a shared high target.
- **Pause / jangan push:** margin underwater + ads deepen loss; stok tipis / 0; already `occupied` on another active GMV Max; `Biarkan dijeda` / `Sudah di iklan lain` / `Jeda sampai restock`.

## Actions

| Aksi | Kapan |
|---|---|
| **Prioritize** | Skor tinggi + rute tunggal + kontribusi gap material (katalog baru / andalan) |
| **Scale** | Sudah di iklan, ROAS ≥ safe BEP, skor baik → +~20% budget bila stok siap |
| **Hold** | Pertahankan / mid score — jangan thrash learning phase |
| **Pause** | Rugi diperdalam, stok kritis, occupied lain, sales kecil |

`% gap tertutup` = derived estimate from prediksi/stok vs `gap_daily`; label **(derived)** in UI.

## Degradasi budget (wajib eksplisit)

Jika `build_plan` mengubah **Buat iklan tunggal → Tambahkan ke grup** karena budget usulan 0, set flag/peringatan — jangan diam-diam. UI must show a warning chip.

## Hard rules

- **Never invent CTR** (or ACOS/konversi) when the upload column is missing/empty.
- **Do not wipe** Mitra10 auth, Supabase vault, margin vault, or locked prediction/safety-stock formulas.
- Port features only; keep Seller Center export as the primary execution path.
- Bahasa UI Indonesia, manajer-readable; tie numbers to stock/ads decisions and thesis evidence when relevant.

## Key files

- `src/core/ads_strategy.py` — `push_score`, `enrich_push_scores` / `product_selection`, `build_plan`
- `src/ui/ads_target.py` — Top N tables on Rekomendasi sistem
- `src/ui/rekomendasi_plus.py` — `_ads_inputs` (optional CTR passthrough only if real)
- Tests: `tests/test_ads_strategy.py`, `tests/test_ads_target.py`
