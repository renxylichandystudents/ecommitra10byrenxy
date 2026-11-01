from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

import pandas as pd


class SourceStatus(str, Enum):
    READY = "Siap"
    CHECK_COLUMNS = "Cek kolom"
    EMPTY = "Kosong"


@dataclass(frozen=True)
class SourceSpec:
    key: str
    label: str
    required: tuple[str, ...]
    aliases: dict[str, tuple[str, ...]]
    dedup_keys: tuple[str, ...]
    date_fields: tuple[str, ...] = ()
    sku_fields: tuple[str, ...] = ()
    utility: str = ""


def normalize_header(value: object) -> str:
    text = str(value).strip().lower().replace("_", " ")
    text = text.replace("/", " / ").replace(":", " : ")
    return " ".join(text.split())


def _alias(*names: str) -> tuple[str, ...]:
    return tuple(normalize_header(name) for name in names)


TRANSACTION_ALIASES = {
    "order_id": _alias("No. Pesanan", "No Pesanan", "Order ID", "Nomor Pesanan"),
    "status": _alias("Status Pesanan", "Order Status", "Status"),
    "cancel_reason": _alias("Alasan Pembatalan", "Cancel Reason", "Cancellation Reason"),
    "return_status": _alias(
        "Status Pembatalan/Pengembalian",
        "Status Pembatalan/ Pengembalian",
        "Status Pengembalian",
        "Return Status",
    ),
    "shipping_option": _alias("Opsi Pengiriman", "Shipping Option"),
    "payment_method": _alias("Metode Pembayaran", "Payment Method"),
    "order_time": _alias("Waktu Pesanan Dibuat", "Tanggal Pesanan", "Order Time", "Create Time", "Tanggal"),
    "sku": _alias("Nomor Referensi SKU", "SKU", "Seller SKU", "SKU Reference"),
    "variation": _alias("Variasi", "Nama Variasi", "Variation Name", "Variant"),
    "list_price": _alias("Harga Awal", "Original Price"),
    "net_price": _alias("Harga Setelah Diskon", "Harga", "Net Price"),
    "qty": _alias("Jumlah", "Quantity", "QTY", "Jumlah Produk Dipesan", "Jumlah Produk di Pesan"),
    "returned_qty": _alias("Returned Quantity", "Jumlah Dikembalikan", "Jumlah Retur"),
    "order_total": _alias("Total Pesanan", "Total Harga", "Subtotal"),
    "seller_discount": _alias("Diskon dari Penjual"),
    "shopee_discount": _alias("Diskon dari Shopee"),
    "seller_voucher": _alias("Voucher Ditanggung Penjual"),
    "coin_cashback": _alias("Cashback Koin"),
    "shopee_voucher": _alias("Voucher Ditanggung Shopee"),
    "coin_deduction": _alias("Potongan Koin Shopee"),
    "card_discount": _alias("Diskon Kartu Kredit"),
    "buyer_shipping": _alias("Ongkos Kirim Dibayar Pembeli", "Ongkos Kirim Dibayar oleh Pembeli"),
    "shipping_rebate": _alias("Estimasi Potongan Biaya Pengiriman"),
    "return_shipping": _alias("Ongkos Kirim Pengembalian Barang"),
    "payment_total": _alias("Total Pembayaran", "Total Payment"),
    "estimated_shipping": _alias("Perkiraan Ongkos Kirim"),
    "buyer": _alias("Username Pembeli", "Username (Pembeli)", "Nama Akun Pembeli", "Buyer Username"),
    "city": _alias("Kota/Kabupaten", "Kota", "City"),
    "province": _alias("Provinsi", "Province"),
    "product_name": _alias("Nama Produk", "Product Name", "Nama Barang"),
}

PERFORMANCE_ALIASES = {
    "date": _alias("Tanggal", "Date"),
    "orders": _alias("Total Pesanan"),
    "sales_per_order": _alias("Penjualan per Pesanan"),
    "product_clicks": _alias("Produk Diklik"),
    "visitors": _alias("Total Pengunjung"),
    "conversion_rate": _alias("Tingkat Konversi Pesanan"),
    "cancelled_orders": _alias("Pesanan Dibatalkan"),
    "cancelled_sales": _alias("Penjualan Dibatalkan"),
    "returned_sales": _alias("Penjualan Dikembalikan"),
    "buyers": _alias("Pembeli"),
    "new_buyers": _alias("Total Pembeli Baru"),
    "existing_buyers": _alias("Total Pembeli Saat Ini"),
    "potential_buyers": _alias("Total Potensi Pembeli"),
    "repeat_rate": _alias("Tingkat Pembelian Berulang"),
}

AD_PRODUCT_ALIASES = {
    "product_name": _alias("Nama Produk", "Product Name", "Nama Iklan/Produk", "Nama Iklan"),
    "product_code": _alias("Kode Produk", "Product Code", "Kode produk"),
    "cart_adds": _alias("Tambah ke Keranjang"),
    "views": _alias("Dilihat", "Impressions"),
    "clicks": _alias("Jumlah Klik", "Klik", "Clicks"),
    "ctr": _alias("Persentase Klik", "CTR"),
    "conversion": _alias("Konversi", "Conversion"),
    "cost_per_conversion": _alias("Biaya per Konversi"),
    "products_sold": _alias("Produk Terjual"),
    "direct_sold": _alias("Terjual Langsung"),
    "ad_sales": _alias("Omzet Penjualan", "Sales from Ads"),
    "cost": _alias("Biaya", "Cost"),
    "roas": _alias("Efektivitas Iklan", "Efektifitas Iklan", "ROAS"),
    "acos": _alias(
        "Persentase Biaya terhadap Penjualan",
        "Persentase Biaya Iklan terhadap Penjualan dari Iklan (ACOS)",
        "ACOS",
    ),
    "voucher_amount": _alias("Voucher Amount"),
    "voucher_sales": _alias("Voucher Sales"),
    "period": _alias("Periode Laporan", "Periode", "Tanggal"),
}

AD_SEARCH_ALIASES = {
    "product_name": _alias("Nama Iklan", "Nama Produk", "Product Name"),
    "product_code": _alias("Kode Produk", "Product Code"),
    "keyword": _alias("Kata Pencarian/Penempatan", "Kata Pencarian", "Keyword"),
    "placement": _alias("Penempatan Iklan", "Placement"),
    "views": _alias("Dilihat", "Impressions"),
    "clicks": _alias("Jumlah Klik", "Klik", "Clicks"),
    "ctr": _alias("Persentase Klik", "CTR"),
    "conversion": _alias("Konversi", "Conversion"),
    "products_sold": _alias("Produk Terjual"),
    "ad_sales": _alias("Omzet Penjualan", "Sales from Ads"),
    "cost": _alias("Biaya", "Cost"),
    "roas": _alias("Efektivitas Iklan", "Efektifitas Iklan", "ROAS"),
    "period": _alias("Periode Laporan", "Periode", "Tanggal"),
}

STOCK_ALIASES = {
    "product_name": _alias("Nama Produk", "Product Name"),
    "product_code": _alias("Kode Produk", "Product Code", "Kode Variasi", "Variation Code"),
    "variation_code": _alias("Kode Variasi", "Variation Code"),
    "variation": _alias("Nama Variasi", "Variation Name"),
    "sku": _alias("SKU", "Nomor Referensi SKU", "Seller SKU", "SKU Induk"),
    "price": _alias("Harga", "Price"),
    "stock_dc_cikupa": _alias("Stok: DC Cikupa", "Stok DC Cikupa", "DC Cikupa"),
}

DESCRIPTION_ALIASES = {
    "product_code": _alias("Kode Produk", "Product Code"),
    "sku": _alias("SKU", "Nomor Referensi SKU", "Seller SKU", "SKU Induk"),
    "product_name": _alias("Nama Produk", "Product Name", "Judul Produk", "Nama Barang"),
    "description": _alias("Deskripsi", "Deskripsi Produk", "Product Description", "Description"),
}

COMPETITOR_ALIASES = {
    "rank": _alias("Ranking", "Peringkat"),
    "rank_change": _alias("Change of Rank", "Perubahan Peringkat"),
    "own_shop": _alias("Toko sendiri"),
    "shop_name": _alias("Nama Toko", "Toko", "Shop Name", "Seller"),
    "product_name": _alias("Nama Produk", "Product Name", "Products Name", "Judul Produk"),
    "description": _alias("Deskripsi", "Deskripsi Produk", "Description"),
    "price": _alias("Harga", "Price"),
    "sold": _alias("Terjual", "Sold", "Jumlah Terjual"),
    "rating": _alias("Rating", "Ulasan", "Review", "Reviews"),
}

SOURCE_SPECS: dict[str, SourceSpec] = {
    "transactions": SourceSpec(
        key="transactions",
        label="Data transaksi",
        required=("order_id", "order_time", "sku", "variation", "qty"),
        aliases=TRANSACTION_ALIASES,
        dedup_keys=("order_id", "sku", "variation"),
        date_fields=("order_time",),
        sku_fields=("sku",),
        utility="Sumber utama prediksi permintaan, sales, batal, retur, dan perilaku pembeli.",
    ),
    "performance": SourceSpec(
        key="performance",
        label="Data performance",
        required=("date",),
        aliases=PERFORMANCE_ALIASES,
        dedup_keys=("date",),
        date_fields=("date",),
        utility="Fitur performa toko bersama: traffic, konversi, pembeli, batal, dan retur.",
    ),
    "ads_auto": SourceSpec(
        key="ads_auto",
        label="Data iklan produk otomatis",
        required=("product_code",),
        aliases=AD_PRODUCT_ALIASES,
        dedup_keys=("period", "product_code", "product_name"),
        date_fields=("period",),
        utility="Fitur iklan otomatis: dilihat, klik, konversi, biaya, ROAS, dan omzet iklan.",
    ),
    "ads_group": SourceSpec(
        key="ads_group",
        label="Data iklan produk grup",
        required=("product_code",),
        aliases=AD_PRODUCT_ALIASES,
        dedup_keys=("period", "product_code", "product_name"),
        date_fields=("period",),
        utility="Dasar rekomendasi iklan grup dan bundling produk.",
    ),
    "ads_overall": SourceSpec(
        key="ads_overall",
        label="Data keseluruhan iklan",
        required=("product_code",),
        aliases=AD_PRODUCT_ALIASES,
        dedup_keys=("period", "product_code", "product_name"),
        date_fields=("period",),
        utility="Kontrol total biaya iklan dan efektivitas iklan toko.",
    ),
    "ads_search": SourceSpec(
        key="ads_search",
        label="Data iklan pencarian",
        required=("views", "clicks"),
        aliases=AD_SEARCH_ALIASES,
        dedup_keys=("period", "product_name", "product_code", "keyword", "placement"),
        date_fields=("period",),
        utility="Fitur iklan pencarian dan pola permintaan dari exposure keyword.",
    ),
    "stock": SourceSpec(
        key="stock",
        label="Data stok",
        required=("sku", "stock_dc_cikupa"),
        aliases=STOCK_ALIASES,
        dedup_keys=("sku", "product_code", "variation"),
        sku_fields=("sku",),
        utility="Snapshot stok DC Cikupa untuk kebutuhan, selisih stok, hari cukup, dan lama kosong.",
    ),
    "product_descriptions": SourceSpec(
        key="product_descriptions",
        label="Data produk deskripsi",
        required=("product_name", "description"),
        aliases=DESCRIPTION_ALIASES,
        dedup_keys=("product_code", "sku"),
        sku_fields=("sku",),
        utility="SEO, rekomendasi nama/deskripsi, dan copywriting produk.",
    ),
    "competitors": SourceSpec(
        key="competitors",
        label="Data produk kompetitor",
        required=("shop_name", "product_name"),
        aliases=COMPETITOR_ALIASES,
        dedup_keys=("shop_name", "product_name"),
        utility="Benchmark harga, judul, keyword, rating/ulasan, dan market gap kompetitor.",
    ),
}


def source_menu() -> list[SourceSpec]:
    return list(SOURCE_SPECS.values())


def find_columns(columns: Iterable[object], spec: SourceSpec) -> dict[str, str]:
    normalized = {normalize_header(column): str(column) for column in columns}
    mapping: dict[str, str] = {}
    for canonical, aliases in spec.aliases.items():
        for alias in aliases:
            if alias in normalized:
                mapping[canonical] = normalized[alias]
                break
        if canonical in mapping:
            continue
        for alias in aliases:
            if len(alias) < 8:
                continue
            found = next((original for norm, original in normalized.items() if alias in norm or norm in alias), None)
            if found:
                mapping[canonical] = found
                break
    return mapping


def status_for_frame(frame: pd.DataFrame | None, spec: SourceSpec) -> SourceStatus:
    if frame is None or frame.empty:
        return SourceStatus.EMPTY
    mapping = find_columns(frame.columns, spec)
    missing = [name for name in spec.required if name not in mapping]
    return SourceStatus.CHECK_COLUMNS if missing else SourceStatus.READY


def validation_report(frame: pd.DataFrame | None, spec: SourceSpec) -> dict[str, object]:
    mapping = find_columns([] if frame is None else frame.columns, spec)
    missing = [name for name in spec.required if name not in mapping]
    return {
        "source_key": spec.key,
        "source_label": spec.label,
        "status": status_for_frame(frame, spec).value,
        "rows": 0 if frame is None else int(len(frame)),
        "columns": 0 if frame is None else int(len(frame.columns)),
        "found_required": [name for name in spec.required if name in mapping],
        "missing_required": missing,
        "mapping": mapping,
        "utility": spec.utility,
    }


CODE_FIELDS = ("order_id", "sku", "product_code", "variation_code")


def _blank(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).str.strip().isin({"", "nan", "None", "-"})


def clean_code(series: pd.Series) -> pd.Series:
    """Kode/SKU sebagai teks tanpa akhiran .0 dari Excel."""
    def one(value: object) -> object:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        text = str(value).strip()
        if text in {"", "nan", "None"}:
            return None
        if text.endswith(".0") and text[:-2].isdigit():
            text = text[:-2]
        return (text.lstrip("0") or "0") if text.isdigit() else text

    return series.map(one).astype(object)


def canonicalize_frame(frame: pd.DataFrame, spec: SourceSpec) -> tuple[pd.DataFrame, dict[str, str]]:
    mapping = find_columns(frame.columns, spec)
    out = frame.copy()
    normalized = {normalize_header(column): str(column) for column in out.columns}
    for canonical, original in mapping.items():
        if canonical in out.columns:
            continue
        values = out[original].copy()
        for alias in spec.aliases.get(canonical, ()):
            other = normalized.get(alias)
            if other is None or other == original:
                continue
            gaps = _blank(values)
            if not gaps.any():
                break
            values = values.where(~gaps, out[other])
        out[canonical] = clean_code(values) if canonical in CODE_FIELDS else values
    return out, mapping

