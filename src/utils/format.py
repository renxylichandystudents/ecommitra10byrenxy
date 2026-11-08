"""Format angka Indonesia, tabel tanpa baris kosong, input rupiah, dan Excel numerik."""

from __future__ import annotations

import hashlib
import io
import re
from collections import OrderedDict
from typing import Iterable

import numpy as np
import pandas as pd

EMPTY = "–"
ROW_PX = 35
MONEY_HINTS = ("sales", "omzet", "biaya", "rp", "budget", "nilai", "harga", "alokasi", "gmv", "penjualan", "modal", "target")
PCT_HINTS = ("%", "persen", "porsi", "tingkat", "kontribusi", "ctr", "acos", "konversi (%)")
DECIMAL_HINTS = ("roas", "mape", "rmse", "wape", "bias", "mae", "rasio", "efektivitas", "efektifitas", "skor", "bobot")
COUNT_HINTS = ("qty", "unit", "pesanan", "jumlah", "terjual", "stok", "klik", "dilihat", "peringkat", "no", "baris", "sku dengan")


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _group(number: float, decimals: int) -> str:
    text = f"{number:,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def angka(value: object) -> str:
    """8162 -> "8.162"."""
    number = _number(value)
    return EMPTY if number is None else _group(round(number), 0)


def rupiah(value: object) -> str:
    """1431776359 -> "Rp 1.431.776.359"; negatif -> "−Rp 5.000"."""
    number = _number(value)
    if number is None:
        return EMPTY
    sign = "−" if number < 0 else ""
    return f"{sign}Rp {_group(abs(round(number)), 0)}"


def desimal(value: object, n: int = 2) -> str:
    """21.0812 -> "21,08"."""
    number = _number(value)
    return EMPTY if number is None else _group(number, n)


def persen(value: object, n: int = 1) -> str:
    """22.6 -> "22,6%". Nilai sudah dalam persen (bukan pecahan)."""
    number = _number(value)
    return EMPTY if number is None else f"{_group(number, n)}%"


def tanggal(value: object, *, jam: bool = False) -> str:
    """Satu format tanggal tabel: 07/11/2026 (atau 07/11/2026 07:28). ISO, "07-11-2026", datetime → sama."""
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return EMPTY
    text = str(value).strip()
    if not text or text in {"-", EMPTY, "NaT", "None", "nan"}:
        return EMPTY
    dayfirst = bool(re.match(r"^\d{1,2}[-/]\d{1,2}[-/]\d{4}", text))
    try:
        stamp = pd.Timestamp(pd.to_datetime(text, dayfirst=dayfirst))
    except (TypeError, ValueError):
        return text
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("Asia/Jakarta").tz_localize(None)
    return stamp.strftime("%d/%m/%Y %H:%M" if jam else "%d/%m/%Y")


def parse_rupiah(text: object) -> int:
    """"Rp 250.000.000" / "250000000" / "250.000.000,50" -> 250000000."""
    raw = str(text or "").strip()
    raw = raw.split(",")[0]
    digits = re.sub(r"[^0-9]", "", raw)
    return int(digits) if digits else 0


def column_kind(name: object) -> str:
    """Jenis format kolom dari namanya: money, pct, dec, atau count."""
    label = str(name).strip().lower()
    if any(hint in label for hint in PCT_HINTS):
        return "pct"
    if any(hint in label for hint in DECIMAL_HINTS):
        return "dec"
    if any(hint in label for hint in COUNT_HINTS) and not any(hint in label for hint in ("sales", "omzet", "biaya", "nilai")):
        return "count"
    if any(re.search(rf"\b{re.escape(hint)}\b", label) for hint in MONEY_HINTS):
        return "money"
    return "count"


def formatter_for(kind: str, series: pd.Series):
    if kind == "money":
        return rupiah
    if kind == "pct":
        return persen
    if kind == "dec":
        return desimal
    values = pd.to_numeric(series, errors="coerce").dropna()
    integral = values.empty or bool(np.allclose(values, np.round(values)))
    return angka if integral else desimal


def table_height(rows: int, max_height: int = 600, row_px: int = ROW_PX) -> int:
    rows = max(int(rows), 0)
    return int(min(max(max_height, row_px * 2 + ROW_PX), ROW_PX + rows * row_px + 3))


CHAR_PX = 7.2  # lebar rata-rata satu huruf di tabel (px)
CELL_PAD_PX = 18
TEXT_MAX_PX = 400
NAMED_WIDTH_PX = {"small": 75, "medium": 200, "large": 400}
LINE_PX = 20
MAX_LINES = 6


def _text_columns(frame: pd.DataFrame) -> dict[str, int]:
    """Kolom teks → panjang teks terpanjang (sampel 300 baris)."""
    out: dict[str, int] = {}
    for column in frame.columns:
        series = frame[column]
        if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
            continue
        sample = series.head(300).astype(str)
        out[str(column)] = int(sample.str.len().max() or 0)
    return out


def wrap_layout(frame: pd.DataFrame, column_config: dict | None = None) -> tuple[int, dict]:
    """Lebar kolom teks panjang dikunci (px) sehingga jumlah baris teks bisa dihitung pasti;
    tinggi baris = baris teks terbanyak. Teks tidak terpotong dan tinggi tidak berlebih.

    st.dataframe (Streamlit 1.50) hanya membungkus teks bila row_height > 64 px."""
    config = dict(column_config or {})
    if frame is None or frame.empty:
        return ROW_PX, config
    import streamlit as st

    lines_needed = 1
    for column, longest in _text_columns(frame).items():
        own = config.get(column)
        own_width = own.get("width") if isinstance(own, dict) else None
        if isinstance(own_width, str):
            width = NAMED_WIDTH_PX.get(own_width, 200)
        elif isinstance(own_width, (int, float)) and not isinstance(own_width, bool):
            width = int(own_width)
        else:
            natural = longest * CHAR_PX + CELL_PAD_PX
            if natural <= TEXT_MAX_PX:
                continue  # muat satu baris dengan lebar otomatis
            width = TEXT_MAX_PX
            config[column] = {**own, "width": width} if isinstance(own, dict) else st.column_config.Column(width=width)
        per_line = max(int((width - CELL_PAD_PX) / CHAR_PX), 8)
        lines_needed = max(lines_needed, -(-longest // per_line))
    if lines_needed <= 1:
        return ROW_PX, config
    lines = min(lines_needed, MAX_LINES)
    # Minimal 65 px agar Streamlit membungkus teks; tambahan 8 px untuk jarak atas-bawah sel.
    return max(65, lines * LINE_PX + 8), config


def wrap_row_height(frame: pd.DataFrame) -> int:
    return wrap_layout(frame)[0]


BLANK_CELLS = {"", "-", "–", "—", "nan", "none", "nat", "<na>"}


def drop_blank_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Buang baris yang semua selnya kosong (NaN/None/""/"-")."""
    if frame is None or frame.empty or not len(frame.columns):
        return frame
    candidate = pd.Series(True, index=range(len(frame)))
    for i in range(len(frame.columns)):
        rows = candidate.to_numpy().nonzero()[0]
        if not len(rows):
            return frame
        column = frame.iloc[rows, i]
        missing = column.isna().to_numpy(dtype=bool)
        blank = missing.copy()
        if not (pd.api.types.is_numeric_dtype(column) or pd.api.types.is_datetime64_any_dtype(column)):
            text = [str(value).strip().lower() for value in column.astype(object).tolist()]
            blank |= np.fromiter((value in BLANK_CELLS for value in text), dtype=bool, count=len(text))
        candidate.iloc[rows] = blank
    return frame.iloc[~candidate.to_numpy()]


def style_frame(
    frame: pd.DataFrame,
    *,
    kinds: dict[str, str] | None = None,
    skip: Iterable[str] = (),
    bold_label: str | None = None,
):
    """Styler format tampilan saja; nilai sel tetap numerik agar sort benar."""
    kinds = dict(kinds or {})
    skip = set(skip)
    formats = {}
    for column in frame.columns:
        if column in skip or not pd.api.types.is_numeric_dtype(frame[column]) or pd.api.types.is_bool_dtype(frame[column]):
            continue
        formats[column] = formatter_for(kinds.get(column) or column_kind(column), frame[column])
    styler = frame.style.format(formats, na_rep=EMPTY)
    # Angka negatif selalu merah (rugi, minus, selisih turun).
    numeric = [c for c in formats if c in frame.columns]
    if numeric:
        def _neg(value) -> str:
            try:
                return "color:#dc2626" if value is not None and float(value) < 0 else ""
            except (TypeError, ValueError):
                return ""

        painter = getattr(styler, "map", None) or styler.applymap
        styler = painter(_neg, subset=numeric)
    if bold_label is not None and len(frame.columns):
        first = frame.columns[0]
        label_column = next((c for c in frame.columns if frame[c].astype(str).eq(bold_label).any()), first)
        mask = frame[label_column].astype(str).eq(bold_label)
        styler = styler.apply(lambda row: ["font-weight:700" if mask.loc[row.name] else "" for _ in row], axis=1)
    return styler


def _has_own_format(cfg: object) -> bool:
    """Kolom progress/format khusus dibiarkan; kolom yang hanya berisi help tetap diformat Styler."""
    if not isinstance(cfg, dict):
        return False
    type_config = cfg.get("type_config") or {}
    own = type_config.get("format") not in (None, "", "localized")
    return own or type_config.get("type") == "progress"


def help_columns(tips: dict[str, str], frame: pd.DataFrame, labels: dict[str, str] | None = None) -> dict:
    """column_config berisi tooltip saja (format angka tetap dari Styler)."""
    import streamlit as st

    labels = labels or {}
    return {name: st.column_config.Column(labels.get(name), help=text) for name, text in tips.items() if name in frame.columns}


def _numeric_objects(frame: pd.DataFrame) -> pd.DataFrame:
    """Kolom object yang isinya hanya angka/kosong (mis. setelah baris Total disisipkan) → numerik, agar tidak tampil "None"."""
    import numbers

    out = frame
    for column in frame.columns:
        series = frame[column]
        if series.dtype != object:
            continue
        values = series.dropna()
        if values.empty or not values.map(lambda v: isinstance(v, numbers.Number) and not isinstance(v, bool)).all():
            continue
        if out is frame:
            out = frame.copy()
        out[column] = pd.to_numeric(series, errors="coerce")
    return out


def show_table(
    frame: pd.DataFrame,
    max_height: int = 600,
    *,
    kinds: dict[str, str] | None = None,
    bold_label: str | None = None,
    column_config: dict | None = None,
    styled: bool = True,
    **kwargs,
):
    """st.dataframe dengan tinggi pas isi (tanpa baris kosong) dan format angka Indonesia.

    Baris yang seluruh selnya kosong (NaN, "", "-") dibuang. Tabel kosong → "Belum ada data".
    Tinggi baris dikunci ROW_PX agar rumus tinggi tetap pas walau ukuran font browser berbeda.
    """
    import streamlit as st

    if frame is None:
        frame = pd.DataFrame()
    if "on_select" not in kwargs:
        frame = drop_blank_rows(frame)
    if frame.empty or not len(frame.columns):
        st.info("Belum ada data")
        return None
    frame = _numeric_objects(frame)
    config = dict(column_config or {})
    preformatted = [name for name, cfg in config.items() if _has_own_format(cfg)]
    data = style_frame(frame, kinds=kinds, skip=preformatted, bold_label=bold_label) if styled else frame
    fixed_row = kwargs.pop("row_height", None)
    wrapped_row, config = wrap_layout(frame, config)
    row_px = fixed_row or wrapped_row
    if row_px > ROW_PX:
        max_height = max(max_height, 720)
    return st.dataframe(
        data,
        height=table_height(len(frame), max_height, row_px),
        row_height=row_px,
        hide_index=kwargs.pop("hide_index", True),
        use_container_width=kwargs.pop("use_container_width", True),
        column_config=config or None,
        **kwargs,
    )


def input_rupiah(label: str, value: int | float, key: str, *, help: str | None = None) -> int:
    """text_input tampil "250.000.000"; terima ketikan dengan/tanpa titik; kembalikan int."""
    import streamlit as st

    if key not in st.session_state:
        st.session_state[key] = angka(value)

    def _reformat() -> None:
        st.session_state[key] = angka(parse_rupiah(st.session_state.get(key)))

    text = st.text_input(f"{label} (Rp)", key=key, on_change=_reformat, help=help)
    return parse_rupiah(text)


def input_angka(label: str, value: int | float, key: str, *, lo: int = 0, hi: int | None = None, help: str | None = None) -> int:
    """text_input bilangan bulat bertitik ribuan ("100.000"), dibatasi lo..hi."""
    import streamlit as st

    def _clamp(number: int) -> int:
        number = max(lo, number)
        return min(hi, number) if hi is not None else number

    if key not in st.session_state:
        st.session_state[key] = angka(_clamp(int(value or 0)))

    def _reformat() -> None:
        st.session_state[key] = angka(_clamp(parse_rupiah(st.session_state.get(key))))

    text = st.text_input(label, key=key, on_change=_reformat, help=help)
    return _clamp(parse_rupiah(text))


def _excel_ready(frame: pd.DataFrame) -> pd.DataFrame:
    clean = frame.copy()
    for column in clean.columns:
        if clean[column].dtype == object and clean[column].map(lambda v: isinstance(v, (list, dict, set, tuple))).any():
            clean[column] = clean[column].astype(str)
    return clean


_EXCEL_CACHE: "OrderedDict[str, bytes]" = OrderedDict()
_EXCEL_CACHE_SIZE = 16
_EXCEL_CACHE_MAX_ROWS = 20000


def _frames_key(frames: dict[str, pd.DataFrame]) -> str | None:
    if sum(len(frame) for frame in frames.values()) > _EXCEL_CACHE_MAX_ROWS:
        return None
    digest = hashlib.sha1()
    try:
        for name, frame in frames.items():
            digest.update(str(name).encode())
            digest.update(repr([(str(c), str(t)) for c, t in frame.dtypes.items()]).encode())
            digest.update(pd.util.hash_pandas_object(frame.astype(str), index=False).values.tobytes())
    except Exception:
        return None
    return digest.hexdigest()


def excel_bytes(frames: dict[str, pd.DataFrame] | pd.DataFrame) -> bytes:
    """Excel dengan angka asli + number format '#,##0' / '0.00' (bukan teks).

    Tombol unduh membuat file pada setiap rerun; isi yang sama diambil dari memo agar halaman tidak lambat.
    """
    if isinstance(frames, pd.DataFrame):
        frames = {"Data": frames}
    key = _frames_key(frames)
    if key is not None and key in _EXCEL_CACHE:
        _EXCEL_CACHE.move_to_end(key)
        return _EXCEL_CACHE[key]
    data = _build_excel(frames)
    if key is not None:
        _EXCEL_CACHE[key] = data
        while len(_EXCEL_CACHE) > _EXCEL_CACHE_SIZE:
            _EXCEL_CACHE.popitem(last=False)
    return data


def _build_excel(frames: dict[str, pd.DataFrame]) -> bytes:
    from openpyxl.utils import get_column_letter

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in frames.items():
            clean = _excel_ready(frame)
            sheet = str(name)[:31] or "Data"
            clean.to_excel(writer, sheet_name=sheet, index=False)
            ws = writer.sheets[sheet]
            for position, column in enumerate(clean.columns, start=1):
                series = clean[column]
                if not pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
                    continue
                values = pd.to_numeric(series, errors="coerce").dropna()
                integral = values.empty or bool(np.allclose(values, np.round(values)))
                kind = column_kind(column)
                fmt = "0.00" if (kind in {"dec", "pct"} or not integral) else "#,##0"
                letter = get_column_letter(position)
                for cell in ws[letter][1:]:
                    cell.number_format = fmt
                ws.column_dimensions[letter].width = max(12, min(40, len(str(column)) + 4))
    return buffer.getvalue()


def parse_angka(text: object) -> float:
    """Kebalikan dari angka(): "Rp 1.250.000" / "1.250.000" / 1250000 → 1250000.0 (kosong → 0)."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text) if text == text else 0.0
    digits = re.sub(r"[^0-9,\-]", "", str(text or "")).replace(",", ".")
    try:
        return float(digits) if digits not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0
