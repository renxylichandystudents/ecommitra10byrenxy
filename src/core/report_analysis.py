"""Analisa laporan: SWOT dan diagram fishbone (tulang ikan) yang disusun dari angka aplikasi.

Semua butir berasal dari fakta terukur pada rentang laporan (`facts`, lihat `laporan.build_snapshot`): penjualan,
target, margin (Kalkulator), iklan, performa toko, ranking kompetitor, stok & gudang, transaksi, dan akurasi model.
Butir yang datanya belum ada tidak ditulis (tidak ada angka karangan).

Fishbone memakai 6 tulang seperti kerangka 4P + proses + lingkungan:
Produk · Harga & Promosi · Tempat / Saluran · Pemasaran & Pengguna · Proses · Lingkungan / Eksternal.
Tiap butir punya tingkat: "masalah" (menyumbang ke masalah utama), "waspada", atau "aman" (sudah baik, sebagai pembanding).
"""

from __future__ import annotations

import math

from src.utils.format import desimal, persen

FISHBONE_BONES = ("Produk", "Harga & Promosi", "Tempat / Saluran", "Pemasaran & Pengguna", "Proses", "Lingkungan / Eksternal")
LEVELS = ("masalah", "waspada", "aman")
MAX_ITEMS = 5


def _ok(value) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(float(value))


def _pct(value, digits: int = 1, signed: bool = False) -> str:
    text = persen(abs(value) if signed else value, digits)
    return (("+" if value >= 0 else "−") + text) if signed else text


def _rp(value) -> str:
    """Rupiah ringkas: Rp 81,5 jt / Rp 1,40 M."""
    if not _ok(value):
        return "–"
    number = abs(float(value))
    sign = "−" if float(value) < 0 else ""
    if number >= 1e9:
        return f"{sign}Rp {desimal(number / 1e9, 2)} M"
    if number >= 1e6:
        return f"{sign}Rp {desimal(number / 1e6, 1)} jt"
    if number >= 1e3:
        return f"{sign}Rp {desimal(number / 1e3, 1)} rb"
    return f"{sign}Rp {desimal(number, 0)}"


def _num(value) -> str:
    return f"{int(round(float(value))):,}".replace(",", ".")


# ---------------------------------------------------------------- masalah utama (kepala ikan)

def problem_statement(f: dict) -> str:
    """Masalah utama yang dianalisa: penurunan sales, target belum tercapai, atau hambatan pertumbuhan."""
    growth, reach = f.get("growth"), f.get("target_pct")
    if _ok(growth) and growth < 0:
        return f"Sales bersih turun {_pct(abs(growth))}"
    if _ok(reach) and reach < 100:
        return f"Sales bersih baru {_pct(reach)} dari target"
    return "Hambatan pertumbuhan sales Shopee"


# ---------------------------------------------------------------- fishbone

def fishbone(f: dict) -> dict[str, list[dict]]:
    """{tulang: [{"text", "level"}]} — masalah dulu, lalu waspada, lalu aman; maks 5 butir per tulang."""
    bones: dict[str, list[dict]] = {b: [] for b in FISHBONE_BONES}

    def add(bone: str, text: str, level: str) -> None:
        bones[bone].append({"text": text, "level": level})

    # Produk
    if _ok(f.get("top50_short")) and _ok(f.get("top50_n")):
        n = int(f["top50_short"])
        add("Produk", f"{n} SKU Top 50 stok di bawah kebutuhan", "masalah" if n >= 5 else ("waspada" if n else "aman"))
    if _ok(f.get("zero_stock")):
        n = int(f["zero_stock"])
        add("Produk", f"{n} SKU stok 0 di Site 10037", "masalah" if n >= 10 else ("waspada" if n else "aman"))
    if _ok(f.get("dead_stock")) and f["dead_stock"] > 0:
        add("Produk", f"{int(f['dead_stock'])} SKU slow/dead stock menahan modal", "waspada")
    if _ok(f.get("poor_names")) and f["poor_names"] > 0:
        add("Produk", f"{int(f['poor_names'])} nama/deskripsi berskor Kurang", "waspada")
    if _ok(f.get("nonaktif_untung")) and f["nonaktif_untung"] > 0:
        add("Produk", f"{int(f['nonaktif_untung'])} SKU nonaktif dulu untung (±{_rp(f.get('nonaktif_hilang_rp', 0))}/bln)", "waspada")
    if _ok(f.get("retur_unit")) and _ok(f.get("qty_bersih")) and f["qty_bersih"] > 0:
        rate = f["retur_unit"] / (f["qty_bersih"] + f["retur_unit"]) * 100
        add("Produk", f"Retur {_num(f['retur_unit'])} unit ({_pct(rate)} QTY)", "masalah" if rate > 3 else ("waspada" if rate > 1 else "aman"))

    # Harga & Promosi
    if _ok(f.get("sku_rugi")):
        n = int(f["sku_rugi"])
        add("Harga & Promosi", f"{n} SKU rugi setelah potongan (−{_rp(f.get('rugi_rp', 0))})", "masalah" if n else "aman")
    if _ok(f.get("sku_rendah")) and f["sku_rendah"] > 0:
        add("Harga & Promosi", f"{int(f['sku_rendah'])} SKU margin di bawah {_pct(f.get('acuan_pct', 0))}", "waspada")
    if _ok(f.get("shopee_pct")):
        add("Harga & Promosi", f"Potongan Shopee {_pct(f['shopee_pct'])} dari harga jual", "waspada" if f["shopee_pct"] > 15 else "aman")
    if _ok(f.get("roas")) and _ok(f.get("target_roas")):
        add("Harga & Promosi", f"ROAS iklan {desimal(f['roas'], 1)} vs target {desimal(f['target_roas'], 1)}",
            "aman" if f["roas"] >= f["target_roas"] else ("waspada" if f["roas"] >= f["target_roas"] * 0.75 else "masalah"))
    if _ok(f.get("voucher_shopee_pct")):
        add("Harga & Promosi", f"Voucher Shopee/koin {_pct(f['voucher_shopee_pct'])} sales produk", "aman")

    # Tempat / Saluran
    if _ok(f.get("visitors_change")):
        v = f["visitors_change"]
        add("Tempat / Saluran", f"Pengunjung toko {_pct(v, signed=True)} vs periode lalu", "masalah" if v <= -10 else ("waspada" if v < 0 else "aman"))
    if _ok(f.get("conv")):
        prev = f.get("conv_prev")
        drop = _ok(prev) and prev > 0 and f["conv"] < prev
        add("Tempat / Saluran", f"Konversi {_pct(f['conv'], 2)}" + (f" (lalu {_pct(prev, 2)})" if _ok(prev) else ""),
            "masalah" if drop and f["conv"] < prev * 0.85 else ("waspada" if drop else "aman"))
    if _ok(f.get("rank_far")) and _ok(f.get("rank_cats")) and f["rank_cats"] > 0:
        far = int(f["rank_far"])
        add("Tempat / Saluran", f"{far} dari {int(f['rank_cats'])} kategori ranking > 50", "masalah" if far > f["rank_cats"] / 2 else ("waspada" if far else "aman"))
    if _ok(f.get("rank_down")) and f["rank_down"] > 0:
        add("Tempat / Saluran", f"{int(f['rank_down'])} kategori ranking turun", "masalah")
    if _ok(f.get("rank_missing")) and f["rank_missing"] > 0:
        add("Tempat / Saluran", f"{int(f['rank_missing'])} kategori tanpa produk kita di daftar", "waspada")

    # Pemasaran & Pengguna
    if _ok(f.get("belum_bayar")) and f["belum_bayar"] > 0:
        add("Pemasaran & Pengguna", f"{_num(f['belum_bayar'])} pesanan batal belum bayar", "masalah" if f["belum_bayar"] >= 100 else "waspada")
    if _ok(f.get("ads_share")):
        add("Pemasaran & Pengguna", f"Omzet atribusi iklan {_pct(f['ads_share'])} sales produk", "waspada" if f["ads_share"] < 20 else "aman")
    if _ok(f.get("ads_cost_pct")):
        add("Pemasaran & Pengguna", f"Biaya iklan {_pct(f['ads_cost_pct'])} sales produk", "waspada" if f["ads_cost_pct"] > 10 else "aman")
    if _ok(f.get("new_buyers")):
        add("Pemasaran & Pengguna", f"{_num(f['new_buyers'])} pembeli baru", "aman")
    if _ok(f.get("campaigns_n")):
        n = int(f["campaigns_n"])
        add("Pemasaran & Pengguna", f"{n} campaign tersimpan di rentang ini", "aman" if n else "waspada")

    # Proses
    if _ok(f.get("cancel_pct")):
        c = f["cancel_pct"]
        add("Proses", f"Tingkat batal {_pct(c)} pesanan", "masalah" if c > 10 else ("waspada" if c > 5 else "aman"))
    for name, count in (f.get("cancel_cats") or {}).items():
        if count and name == "Pembeli":
            add("Proses", f"Dibatalkan pembeli: {_num(count)} pesanan (ubah pesanan/alamat/voucher)", "waspada")
        elif count and name != "Belum bayar":
            add("Proses", f"Batal oleh {str(name).lower()}: {_num(count)} pesanan", "masalah" if name == "Penjual" and count >= 20 else "waspada")
    if _ok(f.get("outstanding_stale")) and f["outstanding_stale"] > 0:
        add("Proses", f"{int(f['outstanding_stale'])} SKU outstanding > 7 hari", "masalah")
    if _ok(f.get("restock_no_os")) and f["restock_no_os"] > 0:
        add("Proses", f"{int(f['restock_no_os'])} SKU perlu isi ulang tanpa PO/TR/TO", "masalah")

    # Lingkungan / Eksternal
    if _ok(f.get("demand_change")):
        d = f["demand_change"]
        add("Lingkungan / Eksternal", f"Permintaan berubah {_pct(d, signed=True)} dalam 30 hari ({f.get('demand_month', '')})".replace(" ()", ""),
            "waspada" if abs(d) >= 25 else "aman")
    if _ok(f.get("model_bias")):
        b = f["model_bias"]
        add("Lingkungan / Eksternal", f"Bias prediksi {_pct(b, signed=True)} (permintaan sulit ditebak)", "waspada" if abs(b) > 10 else "aman")
    if f.get("top_shop"):
        add("Lingkungan / Eksternal", f"Toko #1 kategori utama: {str(f['top_shop'])[:28]}", "waspada")
    if _ok(f.get("top10_share")):
        s = f["top10_share"]
        add("Lingkungan / Eksternal", f"10 produk teratas = {_pct(s)} sales", "waspada" if s > 50 else "aman")
    if _ok(f.get("promo_days")):
        add("Lingkungan / Eksternal", f"{int(f['promo_days'])} tanggal kampanye (kembar/gajian)", "aman")

    order = {lvl: i for i, lvl in enumerate(LEVELS)}
    return {b: sorted(items, key=lambda x: order[x["level"]])[:MAX_ITEMS] for b, items in bones.items()}


# ---------------------------------------------------------------- SWOT

def swot(f: dict) -> dict[str, list[str]]:
    """SWOT dari angka nyata; tiap kuadran maks 5 butir, urut dari yang paling berdampak."""
    s, w, o, t = [], [], [], []
    growth = f.get("growth")
    if _ok(growth):
        (s if growth >= 0 else w).append(f"Sales bersih {'naik' if growth >= 0 else 'turun'} {_pct(abs(growth))} dibanding periode lalu "
                                          f"({_rp(f.get('sales_bersih', 0))})")
    reach = f.get("target_pct")
    if _ok(reach):
        (s if reach >= 100 else w).append(f"Pencapaian target {_pct(reach)}" + ("" if reach >= 100 else f" (kurang {_rp(f.get('target_gap', 0))})"))
    if _ok(f.get("margin_pct")):
        (s if f["margin_pct"] > 0 else w).append(f"Margin bersih SKU aktif {_pct(f['margin_pct'])} ({_rp(f.get('margin_rp', 0))}) setelah potongan Shopee & iklan")
    if _ok(f.get("sku_tinggi")) and f["sku_tinggi"] > 0:
        s.append(f"{int(f['sku_tinggi'])} SKU margin tinggi menyumbang {_pct(f.get('tinggi_porsi', 0))} sales produk")
    if _ok(f.get("sku_rugi")) and f["sku_rugi"] > 0:
        w.append(f"{int(f['sku_rugi'])} SKU rugi setelah potongan (−{_rp(f.get('rugi_rp', 0))}) dan {int(f.get('sku_rendah') or 0)} SKU margin rendah")
    if _ok(f.get("roas")) and _ok(f.get("target_roas")):
        (s if f["roas"] >= f["target_roas"] else w).append(f"ROAS iklan {desimal(f['roas'], 1)} (target {desimal(f['target_roas'], 1)})")
    if _ok(f.get("cancel_pct")):
        (w if f["cancel_pct"] > 5 else s).append(f"Tingkat batal {_pct(f['cancel_pct'])} dari {_num(f.get('pesanan', 0))} pesanan")
    if _ok(f.get("rank_top10")) and f["rank_top10"] > 0:
        s.append(f"Top 10 di {int(f['rank_top10'])} kategori ranking kompetitor ({f.get('rank_period', '')})".replace(" ()", ""))
    if _ok(f.get("mape_agg")):
        (s if f["mape_agg"] <= 15 else w).append(f"Prediksi total toko meleset {_pct(f['mape_agg'])} (MAPE agregat, model {f.get('model', '')})".replace(", model )", ")"))
    if _ok(f.get("top50_short")) and f["top50_short"] > 0:
        w.append(f"{int(f['top50_short'])} SKU Top 50 stoknya di bawah prediksi + safety stock")
    if _ok(f.get("conv")) and _ok(f.get("conv_prev")) and f["conv_prev"] > 0:
        (s if f["conv"] >= f["conv_prev"] else w).append(f"Konversi toko {_pct(f['conv'], 2)} (periode lalu {_pct(f['conv_prev'], 2)})")
    if _ok(f.get("outstanding_stale")) and f["outstanding_stale"] > 0:
        w.append(f"{int(f['outstanding_stale'])} SKU outstanding PO/TR/TO lewat 7 hari belum diterima")

    if _ok(f.get("belum_bayar")) and f["belum_bayar"] > 0:
        o.append(f"{_num(f['belum_bayar'])} pesanan batal belum bayar ({_num(f.get('belum_bayar_akun', 0))} akun) bisa dikejar lewat chat")
    if _ok(f.get("rank_near")) and f["rank_near"] > 0:
        o.append(f"{int(f['rank_near'])} kategori di peringkat 11–50: paling cepat masuk Top 10" + (f" ({f['rank_near_names']})" if f.get("rank_near_names") else ""))
    if _ok(f.get("sku_rendah")) and f["sku_rendah"] > 0 and _ok(f.get("selisih_rp")):
        o.append(f"Menaikkan {int(f['sku_rendah'])} SKU margin rendah ke {_pct(f.get('acuan_pct', 0))} menambah ±{_rp(f['selisih_rp'])}")
    if _ok(f.get("nonaktif_untung")) and f["nonaktif_untung"] > 0:
        o.append(f"{int(f['nonaktif_untung'])} SKU nonaktif dulu untung: potensi ±{_rp(f.get('nonaktif_hilang_rp', 0))}/bulan bila diaktifkan")
    if _ok(f.get("roas")) and _ok(f.get("target_roas")) and f["roas"] >= f["target_roas"] * 1.2:
        o.append(f"ROAS {desimal(f['roas'], 1)} jauh di atas target: ruang menambah budget iklan pada SKU stok aman & margin tinggi")
    if _ok(f.get("promo_days")) and f["promo_days"] > 0:
        o.append(f"{int(f['promo_days'])} tanggal kampanye (tanggal kembar/gajian) di rentang ini untuk flash sale & voucher")
    if _ok(f.get("poor_names")) and f["poor_names"] > 0:
        o.append(f"{int(f['poor_names'])} nama produk berskor Kurang bisa diperbaiki untuk pencarian")

    if _ok(f.get("rank_down")) and f["rank_down"] > 0:
        t.append(f"{int(f['rank_down'])} kategori ranking turun dibanding periode sebelumnya")
    if _ok(f.get("rank_far")) and f["rank_far"] > 0:
        t.append(f"{int(f['rank_far'])} kategori masih di peringkat > 50 (kompetitor mendominasi)")
    if _ok(f.get("demand_change")) and abs(f["demand_change"]) >= 25:
        t.append(f"Permintaan berubah {_pct(f['demand_change'], signed=True)} dalam sebulan ({f.get('demand_month', '')}): lonjakan kampanye/proyek sulit diprediksi")
    if _ok(f.get("top10_share")) and f["top10_share"] > 40:
        t.append(f"Ketergantungan pada 10 produk teratas ({_pct(f['top10_share'])} sales produk)")
    if _ok(f.get("shopee_pct")) and f["shopee_pct"] > 12:
        t.append(f"Potongan Shopee {_pct(f['shopee_pct'])} dari harga jual menekan margin")
    if _ok(f.get("dead_stock")) and f["dead_stock"] > 0:
        t.append(f"{int(f['dead_stock'])} SKU slow-moving/dead stock menahan modal")
    if _ok(f.get("zero_stock")) and f["zero_stock"] > 0:
        t.append(f"{int(f['zero_stock'])} SKU stok kosong di Site 10037: pembeli pindah ke kompetitor")

    for bucket, fallback in ((s, "Data belum cukup untuk kekuatan"), (w, "Belum ada kelemahan menonjol dari data"),
                             (o, "Peluang belum terlihat dari data"), (t, "Ancaman belum terlihat dari data")):
        if not bucket:
            bucket.append(fallback)
    return {"Strength": s[:6], "Weakness": w[:6], "Opportunity": o[:6], "Threat": t[:6]}
