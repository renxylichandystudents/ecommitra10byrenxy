"""File harga beli & bottom price (tim merchandising, per kuartal): simpan, baca dengan cache, dan kartu unggah."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st

from src.core import harga_beli as hb
from src.core.margin_file import sku_key
from src.ui.common import file_check, fmt_num, mark_upload_done, set_upload_notice, show_upload_notice

KEY = "harga-beli"
UPLOAD_KEY = "harga_beli"


@dataclass
class HargaBeli:
    periode: str = ""
    uploaded_at: str = ""
    uploaded_by: str = ""
    file: str = ""
    items: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=hb.ITEM_COLUMNS))

    @property
    def ready(self) -> bool:
        return not self.items.empty

    def _map(self, column: str) -> dict[str, float]:
        part = self.items.dropna(subset=[column]) if self.ready else self.items
        return {str(k): float(v) for k, v in zip(part["sku"], part[column]) if np.isfinite(float(v)) and float(v) > 0}

    def cost_map(self) -> dict[str, float]:
        return self._map("harga_beli")

    def bottom_map(self) -> dict[str, float]:
        return self._map("bottom_price")

    def cost(self, sku) -> float:
        return self.cost_map().get(sku_key(sku), float("nan"))

    def bottom(self, sku) -> float:
        return self.bottom_map().get(sku_key(sku), float("nan"))


def _load(features) -> HargaBeli:
    if features is None:
        return HargaBeli()
    try:
        saved = features.get_json(KEY, None) or {}
    except Exception:
        return HargaBeli()
    items = pd.DataFrame(saved.get("items") or [], columns=hb.ITEM_COLUMNS)
    if not items.empty:
        items["sku"] = items["sku"].astype(str)
        for column in ("harga_beli", "harga_jual_offline", "harga_jual_nett", "bottom_price", "promo_offline_pct"):
            items[column] = pd.to_numeric(items[column], errors="coerce")
    return HargaBeli(str(saved.get("periode", "")), str(saved.get("uploaded_at", "")), str(saved.get("uploaded_by", "")), str(saved.get("file", "")), items)


def load_harga_beli(features) -> HargaBeli:
    key = (st.session_state.get("_feature-version", 0), st.session_state.get("_harga-beli-version", 0))
    cached = st.session_state.get("_harga-beli")
    if isinstance(cached, tuple) and cached[0] == key:
        return cached[1]
    data = _load(features)
    st.session_state["_harga-beli"] = (key, data)
    return data


def status_line(data: HargaBeli) -> str:
    if not data.ready:
        return "File harga beli & bottom price belum diunggah"
    return (f"Harga beli & bottom price periode <b>{data.periode or '-'}</b> (diunggah {data.uploaded_at[:10] or '-'} oleh {data.uploaded_by or '-'}) · "
            f"{fmt_num(len(data.cost_map()))} SKU berharga beli · {fmt_num(len(data.bottom_map()))} SKU ber-bottom price")


def upload_card(features, *, username: str, may_edit: bool, require, key: str) -> None:
    data = load_harga_beli(features)
    st.markdown(
        f"<div class='field-hint'>{status_line(data)}.<br>File dari tim merchandising per kuartal (sheet <b>Marketplace</b>: Item No, H.Beli, "
        "Bottom Price). <b>Harga beli</b> dipakai sebagai modal untuk menghitung margin (SKU tanpa harga beli memakai estimasi File margin). "
        "<b>Bottom price</b> hanya dipakai untuk Flash sale toko dan Exposure media sosial. Unggahan baru mengganti data sebelumnya.</div>",
        unsafe_allow_html=True,
    )
    show_upload_notice(key)
    if not may_edit:
        st.caption("Hanya Super user atau E-commerce specialist yang bisa mengunggah file ini.")
        return
    round_no = int(st.session_state.get(f"{key}-round", 0))
    upload = st.file_uploader("File Bottom Price (.xlsx)", type=["xlsx", "xls"], key=f"{key}-file-{round_no}")
    if upload is None:
        return
    try:
        parsed = hb.read_workbook(upload.getvalue())
    except Exception as exc:  # noqa: BLE001
        file_check(False, f"{upload.name}: {exc}")
        return
    items = parsed["items"]
    n_cost, n_bottom = int(items["harga_beli"].notna().sum()), int(items["bottom_price"].notna().sum())
    file_check(True, f"{upload.name}: sheet {parsed['sheet']} terbaca, {fmt_num(len(items))} SKU · {fmt_num(n_cost)} berharga beli · "
                     f"{fmt_num(n_bottom)} ber-bottom price.")
    periode = st.text_input("Periode", value=parsed["periode"] or datetime.now().strftime("%m/%Y"), key=f"{key}-periode-{round_no}").strip()
    if st.button("Simpan harga beli & bottom price", type="primary", key=f"{key}-save-{round_no}", disabled=not periode):
        require("setting_kalkulator_biaya", "edit")
        payload = {"periode": periode, "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "uploaded_by": username, "file": upload.name,
                   "sheet": parsed["sheet"], "items": items.astype(object).where(items.notna(), None).to_dict("records")}
        try:
            features.set_json(KEY, payload, username=username)
        except Exception as exc:  # noqa: BLE001
            set_upload_notice(key, False, f"{upload.name} gagal disimpan: {exc}")
        else:
            st.session_state["_harga-beli-version"] = int(st.session_state.get("_harga-beli-version", 0)) + 1
            mark_upload_done(UPLOAD_KEY)
            set_upload_notice(key, True, f"{upload.name} periode {periode} tersimpan: {fmt_num(len(items))} SKU. Kalkulator biaya, Iklan, Flash sale, "
                                         "dan Exposure sudah memakai data ini.")
            st.session_state[f"{key}-round"] = round_no + 1
        st.rerun()
