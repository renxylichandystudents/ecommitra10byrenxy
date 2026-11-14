"""Data file margin (unggahan berkala): simpan, baca dengan cache, dan kartu unggah yang dipakai Kalkulator & Laporan margin."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st

from src.core import margin_file as mf
from src.ui.common import file_check, fmt_idr, fmt_num, fmt_pct, mark_upload_done, set_upload_notice, show_upload_notice

TABLE = "margin_item"


def cost_margin_pct(price: float, cost: float) -> float:
    """Margin kotor % harga jual Shopee (termasuk PPN) dari harga beli (belum termasuk PPN):
    harga jual = PPN + harga beli + margin kotor → margin kotor % = (harga × (1 − porsi PPN) − harga beli) ÷ harga."""
    return (price * (1 - mf.DEFAULT_TAX_SHARE) - cost) / price * 100


@dataclass
class MarginData:
    periode: str = ""
    uploaded_at: datetime | None = None
    shopee: pd.DataFrame = field(default_factory=pd.DataFrame)
    nasional: pd.DataFrame = field(default_factory=pd.DataFrame)
    lookup: pd.DataFrame = field(default_factory=pd.DataFrame)
    periods: list[str] = field(default_factory=list)
    harga_beli: dict = field(default_factory=dict)   # sku → harga beli per unit (file merchandising), prioritas di atas File margin
    harga_beli_periode: str = ""

    @property
    def ready(self) -> bool:
        return not self.lookup.empty or bool(self.harga_beli)

    @property
    def store_kotor_pct(self) -> float:
        """Margin kotor toko Shopee (% harga termasuk pajak); bila sheet Shopee kosong, pakai nasional."""
        value = mf.store_average(self.shopee)
        return value if np.isfinite(value) else mf.store_average(self.nasional)

    def kotor_map(self, prices: dict | None = None) -> dict[str, float]:
        """Margin kotor % per SKU. prices (sku → harga jual): SKU yang punya harga beli dihitung dari harga beli (PPN dari harga jual);
        SKU lain memakai File margin."""
        out: dict[str, float] = {}
        if not self.lookup.empty:
            frame = self.lookup.dropna(subset=["margin_kotor_pct"])
            out.update(dict(zip(frame["sku"], frame["margin_kotor_pct"].astype(float))))
        if prices and self.harga_beli:
            for sku, price in prices.items():
                cost = self.harga_beli.get(mf.sku_key(sku))
                if cost and price and price > 0:
                    out[mf.sku_key(sku)] = cost_margin_pct(float(price), cost)
        return out

    def row_at(self, sku: str, price: float | None) -> dict | None:
        """Seperti row(), tetapi bila SKU punya harga beli dan harga diketahui: margin dari harga beli (PPN dari harga jual Shopee)."""
        cost = self.harga_beli.get(mf.sku_key(sku))
        if cost and price and price > 0:
            return {"margin_kotor_pct": cost_margin_pct(float(price), cost), "porsi_pajak": mf.DEFAULT_TAX_SHARE,
                    "sumber": f"Harga beli {self.harga_beli_periode}".strip(), "harga_beli": float(cost)}
        return self.row(sku) if not self.lookup.empty else None

    def row(self, sku: str) -> dict | None:
        key = mf.sku_key(sku)
        hit = self.lookup.loc[self.lookup["sku"] == key]
        return hit.iloc[0].to_dict() if not hit.empty else None


def periods(features) -> list[str]:
    """Periode tersimpan, terbaru dulu (menurut waktu unggah)."""
    try:
        frame = features.read(TABLE) if features is not None else pd.DataFrame()
    except Exception:
        return []
    if frame.empty:
        return []
    order = frame.groupby("periode")["uploaded_at"].max().sort_values(ascending=False)
    return list(order.index)


def _with_cost(md: MarginData, features) -> MarginData:
    try:
        from src.ui.harga_beli_data import _load as load_cost

        cost = load_cost(features)
        md.harga_beli, md.harga_beli_periode = cost.cost_map(), cost.periode
    except Exception:
        pass
    return md


def _load(features, periode: str | None) -> MarginData:
    return _with_cost(_load_file(features, periode), features)


def _load_file(features, periode: str | None) -> MarginData:
    if features is None:
        return MarginData()
    try:
        frame = features.read(TABLE)
    except Exception:
        return MarginData()
    if frame.empty:
        return MarginData()
    order = list(frame.groupby("periode")["uploaded_at"].max().sort_values(ascending=False).index)
    chosen = periode if periode in order else order[0]
    part = frame.loc[frame["periode"] == chosen]
    shopee = part.loc[part["sumber"] == "shopee"].reset_index(drop=True)
    nasional = part.loc[part["sumber"] == "nasional"].reset_index(drop=True)
    if nasional.empty:
        # Sheet nasional boleh dari unggahan periode lain (cadangan untuk SKU yang tidak ada di sheet Shopee).
        others = frame.loc[frame["sumber"] == "nasional"]
        if not others.empty:
            latest = others.groupby("periode")["uploaded_at"].max().idxmax()
            nasional = others.loc[others["periode"] == latest].reset_index(drop=True)
    return MarginData(chosen, pd.to_datetime(part["uploaded_at"]).max(), shopee, nasional, mf.lookup(shopee, nasional), order)


def load_margin(features, periode: str | None = None) -> MarginData:
    """Dibaca sekali per perubahan data (cache di session)."""
    key = (st.session_state.get("_feature-version", 0), st.session_state.get("_margin-version", 0), st.session_state.get("_harga-beli-version", 0), periode or "")
    cached = st.session_state.get("_margin-data")
    if isinstance(cached, dict) and key in cached:
        return cached[key]
    data = _load(features, periode)
    st.session_state["_margin-data"] = {key: data}
    return data


def save_upload(features, parsed: dict, periode: str, username: str) -> int:
    stamp = datetime.now()
    total = 0
    for source, sheet in parsed["sheets"].items():
        features.remove(TABLE, {"sumber": source, "periode": periode}, username=username, action="ganti:file_margin")
        rows = sheet["items"].assign(sumber=source, periode=periode, uploaded_at=stamp, uploaded_by=username)
        total += features.insert(TABLE, rows, username=username, action="unggah:file_margin")
    st.session_state["_margin-version"] = int(st.session_state.get("_margin-version", 0)) + 1
    return total


def status_line(md: MarginData) -> str:
    if md.lookup.empty:
        return "File margin belum diunggah"
    when = md.uploaded_at.strftime("%d/%m/%Y") if md.uploaded_at is not None and pd.notna(md.uploaded_at) else "-"
    return (f"File margin periode <b>{md.periode}</b> (diunggah {when}) · Shopee {fmt_num(len(md.shopee))} item · "
            f"Nasional {fmt_num(len(md.nasional))} item · margin kotor toko {fmt_pct(md.store_kotor_pct, 1)}")


UPLOAD_HINT = "Unggah file margin di <b>Upload data › Target & margin › File margin</b>."


def upload_card(features, *, username: str, may_edit: bool, require, key: str) -> None:
    """Unggah file margin (sheet Margin Shopee & Margin Nasional). Periode yang sama akan diganti."""
    md = load_margin(features)
    st.markdown(
        f"<div class='field-hint'>{status_line(md)}. Unggah ulang setiap ada data baru; periode yang sama akan diganti, "
        "periode lain tetap tersimpan untuk perbandingan.</div>",
        unsafe_allow_html=True,
    )
    show_upload_notice(key)
    if not may_edit:
        st.caption("Hanya Super user atau E-commerce specialist yang bisa mengunggah file margin.")
        return
    round_no = int(st.session_state.get(f"{key}-round", 0))
    upload = st.file_uploader("File margin (.xlsx) berisi sheet Margin Shopee dan/atau Margin Nasional", type=["xlsx", "xls"], key=f"{key}-file-{round_no}")
    if upload is None:
        return
    try:
        parsed = mf.read_margin_workbook(upload.getvalue())
    except Exception as exc:  # noqa: BLE001
        file_check(False, f"{upload.name}: {exc}")
        return
    found = ", ".join(f"{mf.SOURCES[s]} ({fmt_num(len(sheet['items']))} item)" for s, sheet in parsed["sheets"].items())
    missing = [mf.SOURCES[s] for s in mf.SOURCES if s not in parsed["sheets"]]
    file_check(True, f"{upload.name}: sheet {found} terbaca" + (f"; sheet {', '.join(missing)} tidak ada di file." if missing else "."))
    lines = []
    for source, sheet in parsed["sheets"].items():
        items = mf.with_pct(sheet["items"])
        total = sheet["total"]
        pct = total["gm_value"] / total["sales_incl"] * 100 if total["sales_incl"] else float("nan")
        pct_file = total["gm_value"] / total["sales_excl"] * 100 if total["sales_excl"] else float("nan")
        lines.append(f"- **{mf.SOURCES[source]}** (sheet {sheet['sheet']}): {fmt_num(len(items))} item terjual, penjualan {fmt_idr(total['sales_incl'])} "
                     f"(termasuk pajak), margin kotor {fmt_idr(total['gm_value'])} = {fmt_pct(pct, 1)} dari harga termasuk pajak, dasar semua hitungan "
                     f"({fmt_pct(pct_file, 1)} dari harga tanpa pajak seperti di file); {fmt_num(int((~items['wajar']).sum()))} item marginnya tidak wajar")
    st.markdown("\n".join(lines))
    periode = st.text_input("Periode data", value=parsed["periode"] or datetime.now().strftime("%m/%Y"), key=f"{key}-periode-{round_no}",
                            help="Diisi otomatis dari file; ubah bila kurang tepat (mis. Oktober 2026).").strip()
    if st.button("Simpan file margin", type="primary", key=f"{key}-save-{round_no}", disabled=not periode):
        require("setting_kalkulator_biaya", "edit")
        try:
            with st.spinner("Menyimpan file margin..."):
                count = save_upload(features, parsed, periode, username)
        except Exception as exc:  # noqa: BLE001 - gagal simpan ditampilkan, app tidak berhenti
            set_upload_notice(key, False, f"File margin {upload.name} gagal disimpan: {exc}")
        else:
            mark_upload_done(TABLE)
            set_upload_notice(
                key, True,
                f"File margin {upload.name} periode {periode} berhasil disimpan: {fmt_num(count)} baris. "
                "Kalkulator biaya dan Laporan margin sudah memakai data ini.",
            )
            st.session_state[f"{key}-round"] = round_no + 1
        st.rerun()
