"""Tabel berkelompok (judul kelompok di tengah & berwarna, kolom terkunci, urut, halaman, unduh Excel) memakai komponen
tabel Top 50 / Prediksi. Dipakai bila st.dataframe tidak cukup (judul kelompok st.dataframe rata kiri dan tidak bisa diwarnai)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from src.utils.format import EMPTY, column_kind, formatter_for

TONES = ("g1", "g5", "g2", "g3", "g4")


def _text(value, fmt) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return EMPTY
    if isinstance(value, str):
        return value or EMPTY
    try:
        return fmt(value)
    except Exception:  # noqa: BLE001
        return str(value)


def parts(frame: pd.DataFrame, *, groups: dict[str, tuple[str, ...]], kinds: dict[str, str] | None = None, total: dict | None = None,
          pin: tuple[str, ...] = (), widths: dict[str, int] | None = None, wrap: tuple[str, ...] = (), signed: tuple[str, ...] = (),
          rank: str | None = None) -> tuple[list[dict], list[dict], dict]:
    """(kolom, baris, baris Total) untuk komponen tabel. signed: kolom yang angka minusnya merah."""
    kinds, widths = kinds or {}, widths or {}
    group_of = {c: g for g, cols in groups.items() for c in cols}
    tone_of = {g: TONES[i % len(TONES)] for i, g in enumerate(groups)}
    columns, fmts = [], {}
    for c in frame.columns:
        kind = kinds.get(c) or column_kind(c)
        numeric = pd.api.types.is_numeric_dtype(frame[c]) and not pd.api.types.is_bool_dtype(frame[c])
        fmts[c] = formatter_for(kind, frame[c]) if numeric else str
        col = {"id": c, "label": c, "sort": True, "kind": "num" if numeric else ("name" if c in wrap else "")}
        if c in group_of:
            col["group"], col["tone"] = group_of[c], tone_of[group_of[c]]
        if c in pin:
            col["pin"] = True
        col["width"] = int(widths.get(c) or (300 if c in wrap else (140 if numeric else 150)))
        columns.append(col)
    rows = []
    for i, rec in enumerate(frame.to_dict("records")):
        cells = {}
        for c in frame.columns:
            v = rec[c]
            num = isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool)
            cell = {"v": (float(v) if np.isfinite(float(v)) else None) if num else ("" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v)),
                    "t": _text(v, fmts[c])}
            if c in signed and num and np.isfinite(float(v)) and float(v) < 0:
                cell["c"] = "neg"
            cells[c] = cell
        cells["rank"] = {"v": float(rec[rank]) if rank and pd.notna(rec.get(rank)) else float(i)}
        rows.append({"key": str(i), "cells": cells})
    tot = {}
    for c, v in (total or {}).items():
        if c in fmts:
            tot[c] = {"t": _text(v, fmts[c]) if not isinstance(v, str) else v}
    return columns, rows, tot


def show(frame: pd.DataFrame, *, key: str, filename: str | None = None, export: pd.DataFrame | None = None, noun: str = "baris",
         first: int = 5, height: int = 680, **kwargs) -> None:
    from src.ui.common import excel_payload
    from src.ui.decision_view import _TABLE

    if frame is None or frame.empty:
        st.info("Belum ada data")
        return
    columns, rows, total = parts(frame, **kwargs)
    _TABLE(columns=columns, rows=rows, total=total, selected="", height=height, limit=0,
           batch={"first": int(first), "step": 10, "noun": noun},
           download=excel_payload(export if export is not None else frame, filename) if filename else None,
           sort=None, key=key, default="")
