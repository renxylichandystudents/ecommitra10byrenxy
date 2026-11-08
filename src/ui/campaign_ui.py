"""Komponen bersama campaign tersimpan (Iklan, Flash sale toko, Exposure media sosial): periode, kunci, simpan/ganti/hapus."""

from __future__ import annotations

import html
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from src.core import campaigns as C
from src.core.fmt import fmt_date
from src.ui.common import date_range_picker
from src.utils.format import show_table

SAVED, NEW = "Campaign tersimpan", "Buat campaign baru"
STATUS_COLOR = {C.RUNNING: "#1d4ed8", C.SCHEDULED: "#1d4ed8", C.STOPPED: "#dc2626", C.DONE: "#64748b"}


def _month_end(day: date) -> date:
    return (pd.Timestamp(day) + pd.offsets.MonthEnd(0)).date()


def period_text(start, end) -> str:
    start, end = C.as_date(start), C.as_date(end)
    return f"{fmt_date(start)} – {fmt_date(end)} ({(end - start).days + 1} hari)"


def planning_presets(today: date, hi: date) -> list[tuple[str, date, date]]:
    tomorrow = today + timedelta(days=1)
    monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    next_month = _month_end(today) + timedelta(days=1)
    items = [
        ("Sisa bulan ini", today, _month_end(today)),
        ("Minggu ini (s.d. Minggu)", today, today + timedelta(days=6 - today.weekday())),
        ("Minggu depan (Sen–Min)", monday, monday + timedelta(days=6)),
        ("7 hari mulai besok", tomorrow, tomorrow + timedelta(days=6)),
        ("14 hari mulai besok", tomorrow, tomorrow + timedelta(days=13)),
        ("30 hari mulai besok", tomorrow, tomorrow + timedelta(days=29)),
        ("4 minggu mulai Senin", monday, monday + timedelta(days=27)),
        ("Bulan depan", next_month, _month_end(next_month)),
    ]
    return [(n, a, min(b, hi)) for n, a, b in items if a <= hi]


def period_picker(*, key: str, today: date, default: tuple[date, date], hi: date | None = None, label: str = "Periode campaign") -> tuple[date, date]:
    hi = hi or today + timedelta(days=90)
    return date_range_picker(key=key, lo=today, hi=hi, default=default, label=label, presets=planning_presets(today, hi))


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _require() -> None:
    from auth.ui import require

    require("rekomendasi", "edit")


def panel(kind: str, *, features, today: date, can_edit: bool, username: str, describe) -> tuple[str, dict | None]:
    """Kotak campaign acuan + riwayat (hentikan/hapus). Mengembalikan (mode tampilan, campaign acuan).

    describe(campaign) -> str HTML ringkas setelannya."""
    store = C.Store(features, kind)
    items = store.all()
    cur = C.current(items, today)
    mode_key = f"cmp-mode-{kind}-{cur['id']}" if cur is not None else ""
    pending = st.session_state.pop(f"cmp-pending-{kind}", None)
    if cur is not None:
        st.session_state[mode_key] = pending or st.session_state.get(mode_key) or SAVED
    if cur is not None:
        status = C.status_of(cur, today)
        st.markdown(
            f"<div style='border:1px solid #bfdbfe;border-left:5px solid #1d4ed8;border-radius:12px;background:#eff6ff;padding:.7rem 1rem;margin:.3rem 0 .5rem'>"
            f"<div style='font-weight:800;color:#1d4ed8'>🔒 Campaign #{cur['id']} · {html.escape(str(cur.get('nama') or C.KINDS[kind]))} · {status}</div>"
            f"<div style='font-size:.9rem;line-height:1.6;color:#1f2937'>Periode {period_text(cur['mulai'], cur['selesai'])} · disimpan "
            f"{html.escape(str(cur.get('dibuat_oleh') or '-'))} {html.escape(str(cur.get('dibuat') or ''))}<br>{describe(cur)}</div></div>",
            unsafe_allow_html=True,
        )
        st.segmented_control("Tampilan", [SAVED, NEW], key=mode_key, label_visibility="collapsed")
    else:
        st.markdown("<div class='field-hint'>Belum ada campaign tersimpan yang berjalan. Susun rencana di bawah, pilih periodenya, lalu simpan sebagai campaign "
                    "agar rencana terkunci dan menjadi acuan harian.</div>", unsafe_allow_html=True)
    if items:
        with st.expander(f"Riwayat campaign · {len(items)}"):
            frame = pd.DataFrame([{
                "#": c["id"], "Nama": c.get("nama", ""), "Periode": period_text(c["mulai"], c["selesai"]), "Status": C.status_of(c, today),
                "Disimpan oleh": c.get("dibuat_oleh", ""), "Disimpan": c.get("dibuat", ""),
                "Keterangan": (f"{c.get('alasan_berhenti', '')} ({c.get('dihentikan_oleh', '')} {c.get('dihentikan', '')})" if c.get("dihentikan") else ""),
            } for c in reversed(items)])
            show_table(frame, column_config={"Nama": st.column_config.TextColumn(width="medium"), "Keterangan": st.column_config.TextColumn(width="medium")})
            if can_edit:
                c1, c2, c3 = st.columns([2, 1, 1], vertical_alignment="bottom")
                pick = c1.selectbox("Pilih campaign", [c["id"] for c in reversed(items)], key=f"cmp-pick-{kind}",
                                    format_func=lambda i: next(f"#{c['id']} · {c.get('nama', '')} · {C.status_of(c, today)}" for c in items if c["id"] == i))
                chosen = next(c for c in items if c["id"] == pick)
                live = C.status_of(chosen, today) in (C.RUNNING, C.SCHEDULED)
                if c2.button("Hentikan", key=f"cmp-stop-{kind}", disabled=not live, use_container_width=True):
                    _require()
                    store.save(C.stop(items, pick, username=username, now=_now()), username=username)
                    st.rerun()
                confirm = c3.checkbox("Yakin hapus", key=f"cmp-del-ok-{kind}")
                if c3.button("Hapus", key=f"cmp-del-{kind}", disabled=not confirm, use_container_width=True):
                    _require()
                    store.save(C.remove(items, pick), username=username)
                    st.rerun()
    return ((st.session_state.get(mode_key) or SAVED) if cur is not None else NEW), cur


def switch_to_new(kind: str) -> None:
    """Callback tombol "Buat campaign baru dari saran"."""
    st.session_state[f"cmp-pending-{kind}"] = NEW


def save_controls(kind: str, *, features, today: date, start: date, end: date, payload: dict, default_name: str, cur: dict | None,
                  can_edit: bool, username: str, after_save=None) -> None:
    """Nama + tombol simpan. Bila periode bertabrakan dengan campaign acuan, wajib konfirmasi hentikan campaign lama."""
    store = C.Store(features, kind)
    with st.container(border=True):
        st.markdown(f"**Simpan sebagai campaign** · periode {period_text(start, end)}")
        name = st.text_input("Nama campaign", value=default_name, key=f"cmp-name-{kind}", max_chars=80)
        clash = cur is not None and C.overlaps(cur, {"mulai": start, "selesai": end})
        ok = True
        if clash:
            ok = st.checkbox(f"Hentikan campaign #{cur['id']} ({period_text(cur['mulai'], cur['selesai'])}) dan ganti dengan campaign ini",
                             key=f"cmp-replace-{kind}")
        label = f"Hentikan #{cur['id']} & simpan campaign baru" if clash else "Simpan campaign"
        if st.button(label, key=f"cmp-save-{kind}", type="primary", disabled=not (can_edit and ok and features is not None)):
            _require()
            items, stopped = C.add(store.all(), {**payload, "nama": name.strip() or default_name, "mulai": start, "selesai": end},
                                   today=today, username=username, now=_now())
            store.save(items, username=username)
            if after_save is not None:
                after_save(items[-1])
            st.session_state[f"cmp-flash-{kind}"] = (f"Campaign #{items[-1]['id']} disimpan" + (f"; campaign #{', #'.join(str(c['id']) for c in stopped)} dihentikan." if stopped else "."))
            st.rerun()
        if not can_edit:
            st.caption("Hanya pengguna dengan akses edit Rekomendasi yang bisa menyimpan campaign.")


def flash_message(kind: str) -> None:
    text = st.session_state.pop(f"cmp-flash-{kind}", None)
    if text:
        st.success(text)


def frame_of(records: list[dict], date_cols: tuple[str, ...] = ()) -> pd.DataFrame:
    frame = pd.DataFrame(records or [])
    for col in date_cols:
        if col in frame.columns:
            frame[col] = pd.to_datetime(frame[col], errors="coerce").map(lambda v: v.date() if pd.notna(v) else None)
    return frame


def records_of(frame: pd.DataFrame) -> list[dict]:
    if frame is None or frame.empty:
        return []
    out = frame.copy()
    for col in out.columns:
        if out[col].map(lambda v: isinstance(v, (date, pd.Timestamp))).any():
            out[col] = out[col].map(lambda v: v.isoformat()[:10] if isinstance(v, (date, pd.Timestamp)) else v)
    return out.astype(object).where(out.notna(), None).to_dict("records")
