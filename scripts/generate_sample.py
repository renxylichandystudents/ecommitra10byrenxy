from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PRODUCTS = [
    ("SKU-TUMBLER-500", "Tumbler Stainless 500ml", "Hitam", 89000),
    ("SKU-TUMBLER-500P", "Tumbler Stainless 500ml", "Pink", 89000),
    ("SKU-SERUM-NIA", "Serum Niacinamide 10%", "30ml", 65000),
    ("SKU-SERUM-VITC", "Serum Vitamin C 15%", "30ml", 72000),
    ("SKU-MASKER-50", "Masker Medis 3 Ply", "50pcs", 28000),
    ("SKU-HEADSET", "Headset Bluetooth TWS", "Putih", 129000),
    ("SKU-CHARGER", "Charger Fast 33W", "Type-C", 45000),
    ("SKU-KAOS-M", "Kaos Oversize Cotton", "M / Hitam", 79000),
    ("SKU-KAOS-L", "Kaos Oversize Cotton", "L / Hitam", 79000),
    ("SKU-LIP-RED", "Lip Tint Velvet", "Red Velvet", 39000),
    ("SKU-LIP-NUDE", "Lip Tint Velvet", "Nude Peach", 39000),
    ("SKU-PANCI", "Panci Listrik Mini 1.5L", "Putih", 155000),
    ("SKU-LAMPU", "Lampu Meja LED", "Warm White", 52000),
    ("SKU-SNACK", "Keripik Singkong Balado", "200g", 18000),
    ("SKU-SABUN", "Sabun Muka Acne Care", "100g", 35000),
]


def seasonal_multiplier(month: int, sku: str) -> float:
    if "SERUM" in sku or "LIP" in sku or "SABUN" in sku:
        return 1.35 if month in (3, 4, 12) else 1.0
    if "KAOS" in sku or "TUMBLER" in sku:
        return 1.4 if month in (6, 7, 12) else 0.95
    if "PANCI" in sku or "SNACK" in sku:
        return 1.5 if month in (3, 4) else 1.0
    if "HEADSET" in sku or "CHARGER" in sku:
        return 1.3 if month in (11, 12) else 1.0
    return 1.0


def main() -> None:
    rng = np.random.default_rng(42)
    start = pd.Timestamp("2024-01-01")
    end = pd.Timestamp("2025-06-30")
    rows = []
    order_no = 100000
    day = start
    while day <= end:
        weekday_boost = 1.2 if day.weekday() >= 5 else 1.0
        for sku, name, variant, price in PRODUCTS:
            base = {
                "SKU-TUMBLER-500": 6,
                "SKU-TUMBLER-500P": 4,
                "SKU-SERUM-NIA": 8,
                "SKU-SERUM-VITC": 5,
                "SKU-MASKER-50": 3,
                "SKU-HEADSET": 2,
                "SKU-CHARGER": 4,
                "SKU-KAOS-M": 5,
                "SKU-KAOS-L": 4,
                "SKU-LIP-RED": 7,
                "SKU-LIP-NUDE": 6,
                "SKU-PANCI": 1.5,
                "SKU-LAMPU": 2,
                "SKU-SNACK": 9,
                "SKU-SABUN": 4,
            }[sku]
            lam = base * seasonal_multiplier(day.month, sku) * weekday_boost / 8
            qty = int(rng.poisson(lam))
            if qty <= 0:
                continue
            order_no += 1
            discount = rng.choice([0, 0.05, 0.1], p=[0.6, 0.3, 0.1])
            unit = round(price * (1 - discount), 0)
            status = rng.choice(["Selesai", "Perlu Dikirim", "Batal"], p=[0.88, 0.08, 0.04])
            hour = int(rng.integers(8, 23))
            minute = int(rng.integers(0, 60))
            created = day + pd.Timedelta(hours=hour, minutes=minute)
            rows.append(
                {
                    "No. Pesanan": f"SHP{order_no}",
                    "Status Pesanan": status,
                    "Waktu Pesanan Dibuat": created.strftime("%Y-%m-%d %H:%M"),
                    "SKU Induk": sku,
                    "Nama Produk": name,
                    "Nomor Referensi SKU": sku,
                    "Nama Variasi": variant,
                    "Harga Awal": price,
                    "Harga Setelah Diskon": int(unit),
                    "Jumlah": qty,
                    "Total Harga": int(unit * qty),
                }
            )
        day += pd.Timedelta(days=1)

    out = Path(__file__).resolve().parents[1] / "data" / "sample_shopee_orders.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"Wrote {len(rows)} rows -> {out}")


if __name__ == "__main__":
    main()
