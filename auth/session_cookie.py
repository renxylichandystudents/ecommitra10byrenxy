"""Cookie token sesi di browser lewat komponen CookieManager (extra-streamlit-components).

Cookie hanya berisi token acak; username dan role tidak pernah disimpan di cookie atau URL.
Komponen membaca/menulis document.cookie dari iframe ber-origin sama dengan aplikasi, jadi tidak
bergantung pada cookie yang diteruskan proxy ke koneksi websocket (st.context.cookies).
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

COOKIE_NAME = "mitra10_session"
BOX_KEY = "auth-cookies"
WAIT_KEY = "_auth-cookie-wait"
WAIT_ROUNDS = 12
WAIT_SECONDS = 0.4

try:
    from extra_streamlit_components.CookieManager import _component_func as _cookie_component
except Exception:
    _cookie_component = None


def box():
    """Wadah tersembunyi untuk iframe komponen cookie (tidak menggeser elemen lain)."""
    container = st.container(key=BOX_KEY)
    container.markdown(f"<style>.st-key-{BOX_KEY}{{display:none !important}}</style>", unsafe_allow_html=True)
    return container


def _server_token() -> str | None:
    try:
        value = st.context.cookies.get(COOKIE_NAME)
    except Exception:
        value = None
    return str(value) if value else None


def read_token(container) -> tuple[str | None, bool]:
    """(token, siap). siap=False berarti komponen browser belum mengirim isi cookie."""
    token = _server_token()
    if token:
        return token, True
    if _cookie_component is None:
        return None, True
    with container:
        cookies = _cookie_component(method="getAll", key="auth-cookie-get", default=None)
    if not isinstance(cookies, dict):
        return None, False
    value = cookies.get(COOKIE_NAME)
    return (str(value) if value else None), True


def may_wait() -> bool:
    """Boleh menunggu satu putaran lagi (rerun singkat) sebelum menampilkan form login."""
    rounds = int(st.session_state.get(WAIT_KEY, 0))
    if rounds >= WAIT_ROUNDS:
        return False
    st.session_state[WAIT_KEY] = rounds + 1
    return True


def _https() -> bool:
    try:
        headers = st.context.headers
        proto = str(headers.get("X-Forwarded-Proto", "") or "")
        host = str(headers.get("Host", "") or "")
    except Exception:
        return True
    if proto:
        return proto.split(",")[0].strip().lower() == "https"
    return not host.startswith(("localhost", "127.0.0.1", "[::1]"))


def write(container, token: str, expires: datetime) -> None:
    """Pasang cookie sampai `expires` (waktu server). Argumen stabil antar-run, jadi iframe tidak dimuat ulang."""
    if _cookie_component is None or not token:
        return
    options = {"path": "/", "expires": expires.astimezone().isoformat(), "sameSite": "lax"}
    if _https():
        options["secure"] = True
    with container:
        _cookie_component(method="set", cookie=COOKIE_NAME, value=token, options=options, key="auth-cookie-set", default=False)


def clear(container) -> None:
    if _cookie_component is None:
        return
    with container:
        _cookie_component(method="delete", cookie=COOKIE_NAME, key="auth-cookie-del", default=False)
