"""Halaman login, ubah password, kelola user, dan bar user di header."""

from __future__ import annotations

import html
import os
import time
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from auth.permissions import ROLES, SUPER_USER, can, role_label
from auth import session_cookie
from auth.repository import LOCK_MINUTES, SESSION_HOURS, AuthError, User, UserRepository
from auth.security import PASSWORD_RULE
from src.core.access import MENU_LABELS, access_matrix_rows, allowed
from src.core.db import database_url, make_engine
from src.core.feature_store import FeatureStore
from src.ui.confirm import confirm_action
from src.utils.format import show_table

SESSION_KEY = "auth-user"
PAGE_KEY = "auth-page"
TOKEN_KEY = "auth-token"
LOGGED_OUT_KEY = "_auth-logged-out"
EXPIRES_KEY = "auth-expires"
FLASH_KEY = "_users-flash"


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


@st.cache_resource(show_spinner=False)
def _features(url: str) -> FeatureStore:
    return FeatureStore(_engine(url))


def get_features() -> FeatureStore:
    """Tabel fitur baru (terpisah dari 9 sumber data latih) + audit_log."""
    return _features(database_url(_secrets_obj()))


def audit(action: str, detail: str = "") -> None:
    user = current_user()
    try:
        get_features().audit(user.username if user else "-", action, detail)
    except Exception:
        pass


@st.cache_resource(show_spinner=False)
def _repo(url: str, username: str, password: str) -> UserRepository:
    repo = UserRepository(_engine(url))
    repo.ensure_initial_superuser(username, password)
    return repo


def get_repo() -> UserRepository:
    """Satu repository per proses: skema tabel user/sesi dibuat sekali, bukan pada setiap rerun."""
    return _repo(database_url(_secrets_obj()), _secret("INITIAL_SUPERUSER_USERNAME"), _secret("INITIAL_SUPERUSER_PASSWORD"))


def database_error_text(exc: BaseException) -> str:
    """Baris pertama pesan driver, tanpa password yang mungkin ikut di URL."""
    import re

    raw = str(getattr(exc, "orig", None) or exc).strip().splitlines()
    first = raw[0] if raw else type(exc).__name__
    return re.sub(r"://([^:/@\s]+):[^@\s]*@", r"://\1:***@", first)[:300]


def _database_down(exc: BaseException) -> None:
    _hide_chrome()
    text = database_error_text(exc)
    hint = "Periksa `DATABASE_URL` di Secrets: satu baris, diapit tanda kutip, tanpa spasi."
    lower = text.lower()
    if "password authentication failed" in lower:
        hint = "Password di `DATABASE_URL` tidak cocok dengan password Neon. Salin ulang connection string terbaru dari Neon (Connect) ke Secrets."
    elif "could not translate host name" in lower or "name or service not known" in lower:
        hint = "Nama host di `DATABASE_URL` salah ketik atau terpotong. Salin ulang connection string dari Neon (Connect)."
    elif "does not exist" in lower:
        hint = "Nama database atau user di `DATABASE_URL` tidak ada di Neon. Salin ulang connection string dari Neon (Connect)."
    elif "timeout" in lower or "timed out" in lower:
        hint = "Database tidak menjawab. Cek project Neon masih aktif, lalu Reboot app."
    st.error(f"Aplikasi belum bisa tersambung ke database.\n\n{hint}\n\nPesan dari database: `{text}`")
    st.stop()


def ephemeral_database() -> bool:
    """True bila aplikasi berjalan di server dengan SQLite lokal (user & sesi hilang saat server restart/redeploy)."""
    from src.core.userspace import deploy_mode

    return deploy_mode() == "server" and database_url(_secrets_obj()).startswith("sqlite")


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


def require(menu: str, need: str = "view") -> User:
    """Guard server-side: hentikan halaman/aksi bila role tidak punya level `need` di menu `menu`."""
    user = current_user()
    if user is None or not allowed(user.role, menu, need):
        label = MENU_LABELS.get(menu, menu)
        st.error(f"Anda tidak punya akses ke {label}. Hubungi super user bila perlu akses.")
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
                "Belum ada user. Isi INITIAL_SUPERUSER_USERNAME dan INITIAL_SUPERUSER_PASSWORD (min. 10 karakter) "
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
                try:
                    get_features().audit(username.strip() or "-", "login_gagal", str(exc))
                except Exception:
                    pass
            else:
                _start_session(repo, user)
                st.rerun()
        st.caption(
            f"Akun dibuat oleh super user. Setelah 5 kali gagal, akun dikunci {LOCK_MINUTES} menit. "
            "Lupa password? Minta super user mereset password Anda."
        )


def _password_form(repo: UserRepository, user: User, *, forced: bool) -> None:
    st.markdown("### Ubah password")
    if forced:
        st.info("Ganti password sebelum memakai aplikasi (login pertama, password direset, atau pembaruan keamanan).")
    st.caption(PASSWORD_RULE)
    with st.form("password-form"):
        old = st.text_input("Password lama / sementara", type="password")
        new = st.text_input("Password baru", type="password")
        again = st.text_input("Ulangi password baru", type="password")
        submitted = st.form_submit_button("Simpan password", type="primary")
    if submitted:
        if new != again:
            st.error("Ulangan password baru tidak sama.")
            return
        try:
            repo.change_password(user.username, old, new)
            audit("ubah_password", user.username)
            _start_session(repo, repo.get(user.username))
            st.session_state.pop(PAGE_KEY, None)
            st.success("Password tersimpan.")
            st.rerun()
        except AuthError as exc:
            st.error(str(exc))


def _session_hours() -> float:
    """Masa berlaku sesi (jam) dari secrets SESSION_TTL_HOURS; default 12, dibatasi 1–168."""
    try:
        hours = float(_secret("SESSION_TTL_HOURS") or SESSION_HOURS)
    except ValueError:
        hours = SESSION_HOURS
    return min(max(hours, 1.0), 168.0)


def _start_session(repo: UserRepository, user: User) -> None:
    hours = _session_hours()
    st.session_state[SESSION_KEY] = user
    st.session_state[TOKEN_KEY] = repo.create_session(user, hours=hours)
    st.session_state[EXPIRES_KEY] = datetime.now().replace(microsecond=0) + timedelta(hours=hours)
    st.session_state.pop(LOGGED_OUT_KEY, None)


def _drop_session() -> None:
    for key in (SESSION_KEY, TOKEN_KEY, EXPIRES_KEY):
        st.session_state.pop(key, None)
    st.session_state[LOGGED_OUT_KEY] = True


def logout() -> None:
    repo = get_repo()
    audit("logout")
    repo.delete_session(st.session_state.get(TOKEN_KEY) or session_cookie._server_token())
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.session_state[LOGGED_OUT_KEY] = True
    st.query_params.clear()
    st.rerun()


def login_gate() -> User:
    """Panggil di awal app. Mengembalikan user yang sudah login; selain itu halaman berhenti.

    Refresh / tab baru membuat sesi Streamlit baru: login dipulihkan dari cookie token selama sesi
    server belum kedaluwarsa, belum dicabut (logout, ubah/reset password, ganti role, nonaktif), dan
    user masih aktif. Role dibaca ulang dari tabel users. Query param ?page= tidak disentuh.
    """
    jar = session_cookie.box()
    try:
        repo = get_repo()
    except Exception as exc:  # noqa: BLE001
        _database_down(exc)
    user = current_user()
    if user is not None:
        token = st.session_state.get(TOKEN_KEY)
        try:
            found = repo.session_for_token(token)
        except Exception:
            # Database sedang sibuk/terputus sesaat: sesi di memori tetap dipakai, jangan paksa login ulang.
            found = (user, st.session_state.get(EXPIRES_KEY) or datetime.now(), datetime.now())
        if found is None:
            _drop_session()
            user = None
        else:
            user, expires, seen = found
            st.session_state[SESSION_KEY] = user
            try:
                slid = repo.touch_session(token, hours=_session_hours(), last_seen=seen)
            except Exception:
                slid = None
            st.session_state[EXPIRES_KEY] = slid or expires
    if user is None and not st.session_state.get(LOGGED_OUT_KEY):
        token, ready = session_cookie.read_token(jar)
        if not ready and session_cookie.may_wait():
            _hide_chrome()
            with st.spinner("Memeriksa sesi login…"):
                time.sleep(session_cookie.WAIT_SECONDS)
            st.rerun()
        try:
            found = repo.session_for_token(token) if token else None
        except Exception:
            found = None
            token = None
        if found is not None:
            user, expires, _seen = found
            st.session_state[SESSION_KEY] = user
            st.session_state[TOKEN_KEY] = token
            st.session_state[EXPIRES_KEY] = expires
        elif token:
            st.session_state[LOGGED_OUT_KEY] = True
    if user is not None:
        session_cookie.write(jar, st.session_state[TOKEN_KEY], st.session_state[EXPIRES_KEY])
    elif st.session_state.get(LOGGED_OUT_KEY):
        session_cookie.clear(jar)
    if user is None:
        _login_page(repo)
        st.stop()
    st.session_state.pop(LOGGED_OUT_KEY, None)
    st.session_state.pop(session_cookie.WAIT_KEY, None)
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
    st.markdown("### Kelola user")
    users_panel(repo, user)


def users_panel(repo: UserRepository, user: User) -> None:
    require("kelola_user", "edit")
    if ephemeral_database():
        st.warning(
            "Database user dan sesi login memakai SQLite di disk server sementara. Setiap kali server restart "
            "atau redeploy (misalnya setelah git push), user tambahan dan sesi login hilang sehingga semua orang "
            "harus login ulang. Isi `DATABASE_URL` (Postgres, mis. Neon/Supabase) di Secrets agar tersimpan permanen."
        )
    flash = st.session_state.pop(FLASH_KEY, None)
    if flash:
        st.success(flash)
    users = repo.list_users()
    frame = pd.DataFrame(
        [
            {
                "Username": u.username,
                "Role": role_label(u.role),
                "Status": "Nonaktif" if not u.is_active else ("Wajib ganti password" if u.must_change_password else "Aktif"),
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
            temp = st.text_input("Password sementara", type="password", help=PASSWORD_RULE)
            if st.form_submit_button("Tambah", type="primary"):
                try:
                    repo.create(name, temp, role, created_by=user.username, must_change=True)
                    audit("tambah_user", f"{name} · {role}")
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
                audit("ubah_role", f"{target} → {new_role}")
                st.session_state[FLASH_KEY] = f"Role {target} diperbarui menjadi {role_label(new_role)}."
                st.rerun()
            except AuthError as exc:
                st.error(str(exc))
        toggle = "Nonaktifkan" if chosen.is_active else "Aktifkan"
        if c2.button(toggle, key=f"user-toggle-{target}", use_container_width=True):

            def _apply(active: bool = not chosen.is_active) -> str | None:
                try:
                    repo.set_active(target, active)
                except AuthError as exc:
                    return str(exc)
                audit("aktifkan_user" if active else "nonaktifkan_user", target)
                st.session_state[FLASH_KEY] = (
                    f"User {target} diaktifkan." if active else f"User {target} dinonaktifkan; semua sesi login-nya dihapus."
                )
                return None

            if chosen.is_active:
                confirm_action(
                    "Nonaktifkan user?",
                    f"User **{html.escape(target)}** tidak bisa login lagi dan semua sesinya dihapus. Lanjutkan?",
                    _apply,
                    confirm_label="Ya, nonaktifkan",
                )
            else:
                problem = _apply()
                if problem:
                    st.error(problem)
                else:
                    st.rerun()
        temp = st.text_input("Password sementara baru", type="password", key=f"user-reset-{target}", help=PASSWORD_RULE)
        if st.button("Reset password", key=f"user-reset-btn-{target}"):
            try:
                repo.reset_password(target, temp)
                audit("reset_password", target)
                st.session_state[FLASH_KEY] = f"Password {target} direset; semua sesi login-nya dihapus. Ia wajib menggantinya saat login berikutnya."
                st.rerun()
            except AuthError as exc:
                st.error(str(exc))
    if not any(u.role == SUPER_USER and u.is_active for u in users):
        st.warning("Tidak ada super user aktif.")
    with st.expander("Matriks hak akses per role (hanya baca)"):
        show_table(pd.DataFrame(access_matrix_rows()))


def show_auth_page(user: User) -> bool:
    """Tampilkan halaman Ubah password / Kelola user bila sedang dibuka. True = halaman lain tidak dirender."""
    page = st.session_state.get(PAGE_KEY)
    if page not in {"password", "users"}:
        return False
    repo = get_repo()
    if page == "password":
        require("ubah_password")
        _password_form(repo, user, forced=False)
    else:
        _users_page(repo, user)
    return True
