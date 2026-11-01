"""Halaman login, ubah password, kelola user, dan bar user di header."""

from __future__ import annotations

import html
import os

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from auth.permissions import ROLES, SUPER_USER, can, role_label
from auth.repository import AuthError, User, UserRepository
from src.core.db import database_url, make_engine
from src.utils.format import show_table

SESSION_KEY = "auth-user"
PAGE_KEY = "auth-page"
TOKEN_KEY = "auth-token"
LOGGED_OUT_KEY = "_auth-logged-out"
FLASH_KEY = "_users-flash"
COOKIE_NAME = "mitra10_session"


def _secret(name: str) -> str:
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.getenv(name, "") or "")


@st.cache_resource(show_spinner=False)
def _engine(url: str):
    return make_engine(url)


def _secrets_obj():
    try:
        return st.secrets
    except Exception:
        return None


def get_engine():
    """Engine bersama untuk tabel users dan analysis_runs."""
    return _engine(database_url(_secrets_obj()))


def get_repo() -> UserRepository:
    repo = UserRepository(get_engine())
    repo.ensure_initial_superuser(_secret("INITIAL_SUPERUSER_USERNAME"), _secret("INITIAL_SUPERUSER_PASSWORD"))
    return repo


def current_user() -> User | None:
    user = st.session_state.get(SESSION_KEY)
    return user if isinstance(user, User) else None


def require_role(permission: str) -> User:
    """Hentikan halaman bila role user tidak punya hak `permission`."""
    user = current_user()
    if user is None or not can(user.role, permission):
        st.error("Anda tidak punya akses ke halaman ini.")
        st.stop()
    return user


def _hide_chrome() -> None:
    st.markdown(
        "<style>section[data-testid='stSidebar'],[data-testid='stSidebarCollapsedControl']{display:none!important}</style>",
        unsafe_allow_html=True,
    )


def _login_page(repo: UserRepository) -> None:
    _hide_chrome()
    _left, mid, _right = st.columns([1, 1.2, 1])
    with mid:
        st.markdown("### Masuk")
        st.caption("Mitra10 × Shopee · Prediksi item terlaris")
        if repo.count() == 0:
            st.warning(
                "Belum ada user. Isi INITIAL_SUPERUSER_USERNAME dan INITIAL_SUPERUSER_PASSWORD (min. 8 karakter) "
                "di Secrets Streamlit (atau .streamlit/secrets.toml saat lokal), lalu muat ulang halaman."
            )
            return
        with st.form("login-form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Masuk", type="primary", use_container_width=True)
        if submitted:
            try:
                user = repo.authenticate(username, password)
            except AuthError as exc:
                st.error(str(exc))
            else:
                token = repo.create_session(user)
                st.session_state[SESSION_KEY] = user
                st.session_state[TOKEN_KEY] = token
                st.rerun()
        st.caption("Akun dibuat oleh super user. Lupa password? Minta super user mereset password Anda.")


def _password_form(repo: UserRepository, user: User, *, forced: bool) -> None:
    st.markdown("### Ubah password")
    if forced:
        st.info("Ini login pertama Anda (atau password baru direset). Ganti password sebelum memakai aplikasi.")
    with st.form("password-form"):
        old = st.text_input("Password lama / sementara", type="password")
        new = st.text_input("Password baru (min. 8 karakter)", type="password")
        again = st.text_input("Ulangi password baru", type="password")
        submitted = st.form_submit_button("Simpan password", type="primary")
    if submitted:
        if new != again:
            st.error("Ulangan password baru tidak sama.")
            return
        try:
            repo.change_password(user.username, old, new)
            st.session_state[SESSION_KEY] = repo.get(user.username)
            st.session_state.pop(PAGE_KEY, None)
            st.success("Password tersimpan.")
            st.rerun()
        except AuthError as exc:
            st.error(str(exc))


def _cookie_token() -> str | None:
    """Token dari cookie browser (dibaca server saat sesi Streamlit dibuat)."""
    try:
        value = st.context.cookies.get(COOKIE_NAME)
    except Exception:
        value = None
    return str(value) if value else None


def _cookie_script(op: tuple[str, str | None]) -> str:
    action, token = op
    if action == "set":
        value, age = token or "", 8 * 3600
    else:
        value, age = "", 0
    return (
        "<script>(function(){const d=window.parent.document;"
        "const secure=window.parent.location.protocol==='https:'?'; Secure':'';"
        f"d.cookie='{COOKIE_NAME}={value}; Max-Age={age}; Path=/; SameSite=Lax'+secure;"
        "})();</script>"
    )


def _sync_cookie(slot, token: str | None) -> None:
    """Samakan cookie browser dengan token sesi, lewat slot yang posisinya tetap (elemen lain tidak bergeser).

    st.context.cookies hanya berisi cookie saat sesi dibuat, jadi skrip ditulis ulang tiap run selama
    berbeda; isi yang sama tidak memuat ulang iframe.
    """
    cookie = _cookie_token()
    if token and cookie != token:
        op = ("set", token)
    elif not token and cookie:
        op = ("delete", None)
    else:
        slot.empty()
        return
    with slot:
        components.html(_cookie_script(op), height=0, width=0)


def _restore_from_cookie(repo: UserRepository) -> User | None:
    token = _cookie_token()
    user = repo.user_for_token(token)
    if user is not None:
        st.session_state[SESSION_KEY] = user
        st.session_state[TOKEN_KEY] = token
    return user


def logout() -> None:
    repo = get_repo()
    repo.delete_session(st.session_state.get(TOKEN_KEY) or _cookie_token())
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.session_state[LOGGED_OUT_KEY] = True
    st.query_params.clear()
    st.rerun()


def login_gate() -> User:
    """Panggil di awal app. Mengembalikan user yang sudah login; selain itu halaman berhenti.

    Login dipulihkan dari cookie token (back/refresh membuat sesi Streamlit baru), sampai Logout
    atau token dicabut (nonaktif / reset password) atau kedaluwarsa 8 jam.
    """
    slot = st.empty()
    repo = get_repo()
    user = current_user()
    if user is not None:
        token = st.session_state.get(TOKEN_KEY)
        fresh = repo.user_for_token(token) if token else repo.get(user.username)
        if fresh is None or not fresh.is_active:
            for key in (SESSION_KEY, TOKEN_KEY):
                st.session_state.pop(key, None)
            user = None
        else:
            st.session_state[SESSION_KEY] = user = fresh
    if user is None and not st.session_state.get(LOGGED_OUT_KEY):
        user = _restore_from_cookie(repo)
    _sync_cookie(slot, st.session_state.get(TOKEN_KEY) if user is not None else None)
    if user is None:
        _login_page(repo)
        st.stop()
    st.session_state.pop(LOGGED_OUT_KEY, None)
    if user.must_change_password:
        _hide_chrome()
        _password_form(repo, user, forced=True)
        st.stop()
    return user


def user_bar(user: User) -> None:
    info, pwd, admin, out = st.columns([6, 1.2, 1.2, 1])
    info.markdown(
        f"<div class='user-bar' style='font-size:.85rem;color:#475569;padding-top:.45rem'>👤 <b>{html.escape(user.username)}</b> · {role_label(user.role)}</div>",
        unsafe_allow_html=True,
    )
    if pwd.button("Ubah password", key="auth-pwd", use_container_width=True):
        st.session_state[PAGE_KEY] = "password"
        st.rerun()
    if can(user.role, "kelola_user") and admin.button("Kelola user", key="auth-users", use_container_width=True):
        st.session_state[PAGE_KEY] = "users"
        st.rerun()
    if out.button("Logout", key="auth-logout", use_container_width=True):
        logout()


def _users_page(repo: UserRepository, user: User) -> None:
    require_role("kelola_user")
    st.markdown("### Kelola user")
    flash = st.session_state.pop(FLASH_KEY, None)
    if flash:
        st.success(flash)
    users = repo.list_users()
    frame = pd.DataFrame(
        [
            {
                "Username": u.username,
                "Role": role_label(u.role),
                "Status": "Aktif" if u.is_active else "Nonaktif",
                "Wajib ganti password": "Ya" if u.must_change_password else "Tidak",
                "Dibuat": u.created_at,
                "Oleh": u.created_by,
                "Login terakhir": u.last_login_at or "-",
            }
            for u in users
        ]
    )
    show_table(frame)
    add, edit = st.columns(2)
    with add.container(border=True):
        st.markdown("**Tambah user**")
        with st.form("user-add", clear_on_submit=True):
            name = st.text_input("Username")
            role = st.selectbox("Role", ROLES, format_func=role_label)
            temp = st.text_input("Password sementara (min. 8 karakter)", type="password")
            if st.form_submit_button("Tambah", type="primary"):
                try:
                    repo.create(name, temp, role, created_by=user.username, must_change=True)
                    st.session_state[FLASH_KEY] = f"User {name} dibuat. Ia wajib mengganti password saat login pertama."
                    st.rerun()
                except AuthError as exc:
                    st.error(str(exc))
    with edit.container(border=True):
        st.markdown("**Ubah user**")
        if not users:
            return
        target = st.selectbox("User", [u.username for u in users], key="user-edit-target")
        chosen = next(u for u in users if u.username == target)
        new_role = st.selectbox("Role", ROLES, index=ROLES.index(chosen.role), format_func=role_label, key=f"user-role-{target}")
        c1, c2 = st.columns(2)
        if c1.button("Simpan role", key=f"user-save-role-{target}", use_container_width=True):
            try:
                repo.set_role(target, new_role)
                st.session_state[FLASH_KEY] = f"Role {target} diperbarui menjadi {role_label(new_role)}."
                st.rerun()
            except AuthError as exc:
                st.error(str(exc))
        toggle = "Nonaktifkan" if chosen.is_active else "Aktifkan"
        if c2.button(toggle, key=f"user-toggle-{target}", use_container_width=True):
            try:
                repo.set_active(target, not chosen.is_active)
                st.session_state[FLASH_KEY] = (
                    f"User {target} dinonaktifkan; semua sesi login-nya dihapus." if chosen.is_active else f"User {target} diaktifkan."
                )
                st.rerun()
            except AuthError as exc:
                st.error(str(exc))
        temp = st.text_input("Password sementara baru", type="password", key=f"user-reset-{target}")
        if st.button("Reset password", key=f"user-reset-btn-{target}"):
            try:
                repo.reset_password(target, temp)
                st.session_state[FLASH_KEY] = f"Password {target} direset; semua sesi login-nya dihapus. Ia wajib menggantinya saat login berikutnya."
                st.rerun()
            except AuthError as exc:
                st.error(str(exc))
    if not any(u.role == SUPER_USER and u.is_active for u in users):
        st.warning("Tidak ada super user aktif.")


def show_auth_page(user: User) -> bool:
    """Tampilkan halaman Ubah password / Kelola user bila sedang dibuka. True = halaman lain tidak dirender."""
    page = st.session_state.get(PAGE_KEY)
    if page not in {"password", "users"}:
        return False
    repo = get_repo()
    if page == "password":
        require_role("ubah_password")
        _password_form(repo, user, forced=False)
    else:
        _users_page(repo, user)
    return True
