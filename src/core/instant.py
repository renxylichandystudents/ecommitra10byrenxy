"""Performa penjualan instan: pesanan dengan opsi pengiriman Instant, Instant Prioritas, dan Same Day.

Dibaca langsung dari laporan pesanan Shopee (Opsi Pengiriman, Waktu Pembayaran Dilakukan, Waktu Pengiriman Diatur,
Waktu Pesanan Selesai). Sales bersih = Total Pembayaran pesanan tidak batal − nilai retur (Harga Setelah Diskon × Returned
quantity), sama dengan definisi di tab Data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.core.cancel_reasons import short_reason
from src.core.metrics import UNPAID_HINTS
from src.ingest import _exact_column, _parse_datetime, _parse_number, cancel_only_mask, clean_sku_series, clean_text_series, map_columns, normalize_status_series, open_unpaid_mask

INSTANT_GROUPS = ("Instant", "Instant Prioritas", "Same Day")
SERVICE_ORDER = ("Instant", "Instant Prioritas", "Same Day", "Next Day", "Reguler", "Hemat Kargo / Trucking", "Kirim toko", "Lainnya")
SLOW_HOURS = 2.0
LINE_COLUMNS = ["order_id", "order_time", "pay_time", "ship_time", "done_time", "status", "cancelled", "menunggu", "cancel_reason", "shipping", "layanan", "kurir",
                "instan", "city", "buyer", "sku", "product_name", "qty", "returned_qty", "net_price", "payment_total", "payment_method", "weight_kg",
                "ship_deadline"]


def service_of(option: str) -> str:
    text = str(option or "").lower()
    if "instant prioritas" in text:
        return "Instant Prioritas"
    if "instant" in text:
        return "Instant"
    if "same day" in text or "sameday" in text:
        return "Same Day"
    if "next day" in text or "yes" in text.split():
        return "Next Day"
    if "hemat kargo" in text or "trucking" in text or "jtr" in text or "kargo" in text:
        return "Hemat Kargo / Trucking"
    if "reguler" in text or "regular" in text:
        return "Reguler"
    if "kirim toko" in text:
        return "Kirim toko"
    return "Lainnya"


def courier_of(option: str) -> str:
    text = str(option or "").lower()
    for key, name in (("gosend", "GoSend"), ("grab", "GrabExpress"), ("spx", "SPX"), ("jne", "JNE"), ("j&t", "J&T"), ("sicepat", "SiCepat"),
                      ("anteraja", "AnterAja"), ("kirim toko", "Kurir toko")):
        if key in text:
            return name
    return "Belum ditentukan"


def instant_lines(source: pd.DataFrame) -> pd.DataFrame:
    """Baris pesanan + opsi pengiriman & waktu proses. Kosong bila kolom Opsi Pengiriman tidak ada."""
    if source is None or source.empty:
        return pd.DataFrame(columns=LINE_COLUMNS)
    table = source.drop(columns=["Nama file"], errors="ignore")
    table.columns = [str(c).strip() for c in table.columns]
    try:
        mapping = map_columns(table)
    except ValueError:
        return pd.DataFrame(columns=LINE_COLUMNS)
    shipping_col = mapping.get("shipping_option") or _exact_column(table, ("opsi pengiriman", "shipping option"))
    if not {"order_id", "order_time", "qty"} <= set(mapping) or not shipping_col:
        return pd.DataFrame(columns=LINE_COLUMNS)

    def when(aliases):
        column = _exact_column(table, aliases)
        return _parse_datetime(table[column]) if column else pd.Series(pd.NaT, index=table.index)

    extra = {"payment_total": ("total pembayaran", "total payment"), "net_price": ("harga setelah diskon", "net price"),
             "cancel_reason": ("alasan pembatalan", "cancel reason"), "buyer": ("username (pembeli)", "username pembeli"),
             "city": ("kota/kabupaten", "kota", "city"), "sku": ("nomor referensi sku", "sku"), "returned_qty": ("returned quantity", "jumlah retur"),
             "payment_method": ("metode pembayaran", "payment method"), "weight": ("total berat", "total weight")}

    def col(key):
        return mapping.get(key) or (_exact_column(table, extra[key]) if key in extra else None)

    def text(key):
        column = col(key)
        return clean_text_series(table[column]) if column else pd.Series("", index=table.index)

    def number(key):
        column = col(key)
        return _parse_number(table[column]).fillna(0).clip(lower=0) if column else pd.Series(0.0, index=table.index)

    frame = pd.DataFrame(index=table.index)
    frame["order_id"] = text("order_id")
    frame["order_time"] = _parse_datetime(table[mapping["order_time"]])
    frame["pay_time"] = when(("waktu pembayaran dilakukan",))
    frame["ship_time"] = when(("waktu pengiriman diatur",))
    frame["done_time"] = when(("waktu pesanan selesai",))
    frame["status"] = normalize_status_series(table[mapping["status"]]) if "status" in mapping else ""
    frame["cancelled"] = cancel_only_mask(frame["status"]) if "status" in mapping else False
    frame["menunggu"] = open_unpaid_mask(frame["status"]) if "status" in mapping else False
    frame["cancel_reason"] = text("cancel_reason")
    frame["shipping"] = clean_text_series(table[shipping_col])
    frame["layanan"] = frame["shipping"].map(service_of)
    frame["kurir"] = frame["shipping"].map(courier_of)
    frame["instan"] = frame["layanan"].isin(INSTANT_GROUPS)
    frame["city"] = text("city").str.upper().replace("", "TIDAK DIKETAHUI")
    frame["buyer"] = text("buyer")
    frame["sku"] = clean_sku_series(table[col("sku")]) if col("sku") else ""
    frame["product_name"] = text("product_name")
    frame["qty"] = number("qty")
    frame["returned_qty"] = number("returned_qty") if col("returned_qty") != mapping.get("qty") else 0.0
    frame["returned_qty"] = np.minimum(frame["returned_qty"], frame["qty"])
    frame["net_price"] = number("net_price")
    frame["payment_total"] = number("payment_total")
    frame["payment_method"] = text("payment_method").replace("", "Tidak diketahui")
    weight = col("weight")
    frame["weight_kg"] = (pd.to_numeric(table[weight].astype(str).str.extract(r"([\d.,]+)")[0].str.replace(",", ".", regex=False), errors="coerce") / 1000
                          if weight else np.nan)
    deadline = next((c for c in table.columns if c.lower().startswith("pesanan harus dikirimkan sebelum")), None)
    frame["ship_deadline"] = _parse_datetime(table[deadline]) if deadline else pd.NaT
    frame = frame.dropna(subset=["order_time"])
    frame = frame.loc[frame["order_id"].ne("")]
    return frame[LINE_COLUMNS].reset_index(drop=True)


def order_frame(lines: pd.DataFrame) -> pd.DataFrame:
    """Satu baris per pesanan: nilai, batal, retur, sales bersih, jam proses (bayar → pengiriman diatur)."""
    cols = ["order_id", "order_time", "day", "hour", "layanan", "kurir", "instan", "city", "buyer", "cancelled", "menunggu", "cancel_reason", "unpaid",
            "returned", "qty_bersih", "sales_bersih", "nilai", "proses_jam", "selesai_jam", "payment_method", "weight_kg", "ship_time", "ship_deadline", "terlambat"]
    if lines is None or lines.empty:
        return pd.DataFrame(columns=cols)
    work = lines.assign(return_value=lines["net_price"] * lines["returned_qty"], line_value=lines["net_price"] * lines["qty"],
                        qty_net=lines["qty"] - lines["returned_qty"])
    grouped = work.groupby("order_id", sort=False)
    out = grouped.agg(order_time=("order_time", "first"), pay_time=("pay_time", "first"), ship_time=("ship_time", "first"), done_time=("done_time", "first"),
                      layanan=("layanan", "first"), kurir=("kurir", "first"), instan=("instan", "first"), city=("city", "first"), buyer=("buyer", "first"),
                      cancelled=("cancelled", "any"), menunggu=("menunggu", "any"), cancel_reason=("cancel_reason", "first"), payment=("payment_total", "first"),
                      line_value=("line_value", "sum"), return_value=("return_value", "sum"), returned_qty=("returned_qty", "sum"), qty_net=("qty_net", "sum"),
                      payment_method=("payment_method", "first"), weight_kg=("weight_kg", "first"), ship_deadline=("ship_deadline", "first"))
    out["nilai"] = out["payment"].where(out["payment"] > 0, out["line_value"])
    out["returned"] = out["returned_qty"] > 0
    gone = out["cancelled"] | out["menunggu"]
    out["sales_bersih"] = np.where(gone, 0.0, out["nilai"] - out["return_value"])
    out["qty_bersih"] = np.where(gone, 0.0, out["qty_net"])
    out["unpaid"] = out["cancelled"] & out["cancel_reason"].str.lower().str.contains("|".join(UNPAID_HINTS), regex=True)
    hours = (out["ship_time"] - out["pay_time"]).dt.total_seconds() / 3600
    out["proses_jam"] = hours.where(hours >= 0)
    done = (out["done_time"] - out["order_time"]).dt.total_seconds() / 3600
    out["selesai_jam"] = done.where(done >= 0)
    out["terlambat"] = ~out["cancelled"] & (out["ship_time"] > out["ship_deadline"]) & out["ship_time"].notna() & out["ship_deadline"].notna()
    out["day"] = out["order_time"].dt.normalize()
    out["hour"] = out["order_time"].dt.hour
    return out.reset_index()[cols]


def _summary(part: pd.DataFrame) -> dict:
    n = len(part)
    active = part.loc[~part["cancelled"] & ~part["menunggu"]]
    net = active.loc[~(active["qty_bersih"] <= 0)]
    return {
        "invoice": n, "invoice_bersih": int(len(net)), "batal": int(part["cancelled"].sum()), "belum_bayar": int(part["unpaid"].sum()),
        "retur": int(part["returned"].sum()), "tingkat_batal": float(part["cancelled"].mean() * 100) if n else float("nan"),
        "sales_bersih": float(part["sales_bersih"].sum()), "qty_bersih": float(part["qty_bersih"].sum()),
        "aov": float(part["sales_bersih"].sum() / len(net)) if len(net) else float("nan"), "pembeli": int(part.loc[part["buyer"].ne(""), "buyer"].nunique()),
        "proses_median": float(active["proses_jam"].median()) if active["proses_jam"].notna().any() else float("nan"),
        "proses_lambat": int((active["proses_jam"] > SLOW_HOURS).sum()),
        "selesai_median": float(active["selesai_jam"].median()) if active["selesai_jam"].notna().any() else float("nan"),
    }


def compare(orders: pd.DataFrame) -> dict:
    """Ringkasan instan vs non-instan vs semua."""
    if orders is None or orders.empty:
        return {}
    return {"instan": _summary(orders.loc[orders["instan"]]), "lain": _summary(orders.loc[~orders["instan"]]), "semua": _summary(orders)}


def service_table(orders: pd.DataFrame) -> pd.DataFrame:
    """Per layanan pengiriman × kurir: invoice, batal, retur, sales bersih, AOV, kontribusi, median jam proses."""
    cols = ["Layanan", "Kurir", "Invoice", "Invoice batal", "% batal", "Invoice retur", "QTY bersih", "Sales bersih", "AOV", "Kontribusi sales (%)",
            "Median proses (jam)"]
    if orders is None or orders.empty:
        return pd.DataFrame(columns=cols)
    rows = []
    for (service, courier), part in orders.groupby(["layanan", "kurir"], sort=False):
        s = _summary(part)
        rows.append({"Layanan": service, "Kurir": courier, "Invoice": s["invoice"], "Invoice batal": s["batal"], "% batal": s["tingkat_batal"],
                     "Invoice retur": s["retur"], "QTY bersih": s["qty_bersih"], "Sales bersih": s["sales_bersih"], "AOV": s["aov"],
                     "Median proses (jam)": s["proses_median"]})
    out = pd.DataFrame(rows)
    total = float(out["Sales bersih"].sum()) or 1.0
    out["Kontribusi sales (%)"] = out["Sales bersih"] / total * 100
    out["_o"] = out["Layanan"].map({name: i for i, name in enumerate(SERVICE_ORDER)}).fillna(len(SERVICE_ORDER))
    return out.sort_values(["_o", "Invoice"], ascending=[True, False]).drop(columns="_o").reset_index(drop=True)[cols]


def daily_table(orders: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    """Per hari: invoice per layanan instan, total invoice semua layanan, porsi instan (%)."""
    if orders is None or orders.empty:
        return pd.DataFrame(columns=["Tanggal", *INSTANT_GROUPS, "Invoice semua", "Porsi instan (%)", "Sales bersih instan"])
    days = pd.date_range(start or orders["day"].min(), end or orders["day"].max(), freq="D")
    inst = orders.loc[orders["instan"]]
    per = inst.groupby(["day", "layanan"]).size().unstack(fill_value=0).reindex(index=days, columns=list(INSTANT_GROUPS), fill_value=0)
    per["Invoice semua"] = orders.groupby("day").size().reindex(days, fill_value=0)
    per["Porsi instan (%)"] = np.where(per["Invoice semua"] > 0, per[list(INSTANT_GROUPS)].sum(axis=1) / per["Invoice semua"].replace(0, 1) * 100, 0.0)
    per["Sales bersih instan"] = inst.groupby("day")["sales_bersih"].sum().reindex(days, fill_value=0)
    return per.rename_axis("Tanggal").reset_index()


def hourly_table(orders: pd.DataFrame) -> pd.DataFrame:
    """Jam pesanan dibuat (0–23): invoice instan, % batal instan, invoice lainnya."""
    hours = pd.RangeIndex(24)
    inst = orders.loc[orders["instan"]] if orders is not None and not orders.empty else pd.DataFrame(columns=["hour", "cancelled"])
    other = orders.loc[~orders["instan"]] if orders is not None and not orders.empty else pd.DataFrame(columns=["hour"])
    out = pd.DataFrame({"Jam": hours})
    out["Invoice instan"] = inst.groupby("hour").size().reindex(hours, fill_value=0).to_numpy()
    out["Batal instan"] = inst.groupby("hour")["cancelled"].sum().reindex(hours, fill_value=0).to_numpy() if not inst.empty else 0
    out["% batal instan"] = np.where(out["Invoice instan"] > 0, out["Batal instan"] / out["Invoice instan"].replace(0, 1) * 100, np.nan)
    out["Invoice lainnya"] = other.groupby("hour").size().reindex(hours, fill_value=0).to_numpy()
    return out


def top_products(lines: pd.DataFrame, limit: int = 30) -> pd.DataFrame:
    """Produk yang paling sering dibeli dengan pengiriman instan (tidak batal) + porsi instan dari sales SKU itu."""
    cols = ["Rank", "SKU", "Produk", "Invoice instan", "QTY instan", "Sales instan", "Porsi instan dari sales SKU (%)"]
    if lines is None or lines.empty:
        return pd.DataFrame(columns=cols)
    active = lines.loc[~lines["cancelled"]].assign(value=lambda f: f["net_price"] * (f["qty"] - f["returned_qty"]), qty_net=lambda f: f["qty"] - f["returned_qty"])
    inst = active.loc[active["instan"]]
    if inst.empty:
        return pd.DataFrame(columns=cols)
    out = inst.groupby("sku", as_index=False).agg(Produk=("product_name", "first"), inv=("order_id", "nunique"), qty=("qty_net", "sum"), sales=("value", "sum"))
    all_sales = active.groupby("sku")["value"].sum()
    out["Porsi instan dari sales SKU (%)"] = out["sales"] / out["sku"].map(all_sales).replace(0, np.nan) * 100
    out = out.sort_values(["sales", "inv"], ascending=False).head(limit).reset_index(drop=True)
    out.insert(0, "Rank", np.arange(1, len(out) + 1))
    return out.rename(columns={"sku": "SKU", "inv": "Invoice instan", "qty": "QTY instan", "sales": "Sales instan"})[cols]


def top_cities(orders: pd.DataFrame, limit: int = 15) -> pd.DataFrame:
    cols = ["Kota/Kabupaten", "Invoice instan", "% batal", "Sales bersih"]
    inst = orders.loc[orders["instan"]] if orders is not None and not orders.empty else pd.DataFrame()
    if inst.empty:
        return pd.DataFrame(columns=cols)
    inst = inst.assign(city=inst["city"].str.title().str.replace("Kab.", "Kab.", regex=False).str.replace("Dki", "DKI", regex=False))
    out = inst.groupby("city").agg(inv=("order_id", "size"), batal=("cancelled", "mean"), sales=("sales_bersih", "sum")).reset_index()
    out["batal"] = out["batal"] * 100
    out = out.sort_values(["inv", "sales"], ascending=False).head(limit)
    return out.rename(columns={"city": "Kota/Kabupaten", "inv": "Invoice instan", "batal": "% batal", "sales": "Sales bersih"})[cols].reset_index(drop=True)


def cities_total(orders: pd.DataFrame) -> pd.DataFrame:
    """Baris Total semua kota (bukan hanya kota yang tampil) untuk tabel Kota tujuan pesanan instan."""
    inst = orders.loc[orders["instan"]] if orders is not None and not orders.empty else pd.DataFrame()
    if inst.empty:
        return pd.DataFrame(columns=["Kota/Kabupaten", "Invoice instan", "% batal", "Sales bersih"])
    return pd.DataFrame([{
        "Kota/Kabupaten": "Total", "Invoice instan": float(len(inst)),
        "% batal": float(inst["cancelled"].mean() * 100), "Sales bersih": float(inst["sales_bersih"].sum()),
    }])


def cancel_reasons(orders: pd.DataFrame) -> pd.DataFrame:
    inst = orders.loc[orders["instan"] & orders["cancelled"]] if orders is not None and not orders.empty else pd.DataFrame()
    if inst.empty:
        return pd.DataFrame(columns=["Alasan batal", "Invoice"])
    reason = inst["cancel_reason"].replace("", "Tanpa alasan").map(short_reason)
    return reason.value_counts().rename_axis("Alasan batal").reset_index(name="Invoice")
