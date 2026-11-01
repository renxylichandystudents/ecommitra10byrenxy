"""Routing halaman lewat ?page= (dan ?tab= untuk menu hasil analisa).

Setiap pindah halaman menulis query param, sehingga Streamlit menambah entri riwayat browser.
Tombol back browser memicu rerun dengan URL lama; rute dari URL itu diterapkan ke session_state.
"""

from __future__ import annotations

from collections.abc import MutableMapping

FEATURE_ID = "prediksi-item-terlaris"
PAGE_HOME = "beranda"
PAGE_INPUT = "data-latih"
PAGE_RESULT = "analisa"
PAGE_USERS = "kelola-user"
PAGE_PASSWORD = "ubah-password"
PAGES = (PAGE_HOME, PAGE_INPUT, PAGE_RESULT, PAGE_USERS, PAGE_PASSWORD)
AUTH_PAGES = {PAGE_USERS: "users", PAGE_PASSWORD: "password"}
LAST_ROUTE = "_route"


def slug(name: str) -> str:
    return "-".join(str(name).lower().split())


def route_from_state(state: MutableMapping, sheets) -> tuple[str, str]:
    """Rute yang sedang tampil menurut session_state."""
    auth_page = state.get("auth-page")
    for page, value in AUTH_PAGES.items():
        if auth_page == value:
            return page, ""
    if state.get("active-feature") != FEATURE_ID:
        return PAGE_HOME, ""
    if state.get("editing-input", "analysis" not in state):
        return PAGE_INPUT, ""
    sheet = str(state.get("active-sheet", sheets[0] if sheets else ""))
    return PAGE_RESULT, slug(sheet) if sheet in sheets else ""


def apply_route(state: MutableMapping, route: tuple[str, str], sheets) -> None:
    """Terapkan rute dari URL (back/forward/refresh) ke session_state."""
    page, tab = route
    if page in AUTH_PAGES:
        state["auth-page"] = AUTH_PAGES[page]
        return
    state.pop("auth-page", None)
    if page == PAGE_HOME or page not in PAGES:
        state["active-feature"] = ""
        return
    state["active-feature"] = FEATURE_ID
    if page == PAGE_INPUT:
        state["editing-input"] = True
        return
    state["editing-input"] = False
    by_slug = {slug(name): name for name in sheets}
    if tab in by_slug:
        state["active-sheet"] = by_slug[tab]


def read_route(params) -> tuple[str, str]:
    page = str(params.get("page", "") or PAGE_HOME)
    return (page if page in PAGES else PAGE_HOME), str(params.get("tab", "") or "")


def sync_route(state: MutableMapping, params, sheets) -> bool:
    """Selaraskan URL ↔ session_state. Kembali True bila halaman berganti (isi lama perlu dibersihkan)."""
    url_route = read_route(params)
    last = state.get(LAST_ROUTE)
    if last is None or tuple(last) != url_route:
        # Sesi baru (refresh / login dipulihkan) atau URL berubah karena tombol back/forward.
        apply_route(state, url_route, sheets)
    current = route_from_state(state, sheets)
    raw = (str(params.get("page", "") or PAGE_HOME), str(params.get("tab", "") or ""))
    if current != raw:
        _write_params(params, current)
    changed = last is not None and tuple(last) != current
    state[LAST_ROUTE] = current
    return changed


def _write_params(params, route: tuple[str, str]) -> None:
    """Tulis URL sekaligus: tiap perubahan query param terpisah menambah satu entri riwayat browser."""
    page, tab = route
    target = {"page": page, **({"tab": tab} if tab else {})}
    if hasattr(params, "from_dict"):
        params.from_dict(target)
        return
    params.clear()
    params.update(target)
