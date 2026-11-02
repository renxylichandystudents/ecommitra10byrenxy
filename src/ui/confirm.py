"""Dialog konfirmasi untuk aksi yang menghapus atau menonaktifkan."""

from __future__ import annotations

from typing import Callable

import streamlit as st


def confirm_action(
    title: str,
    message: str,
    on_confirm: Callable[[], str | None],
    *,
    confirm_label: str = "Ya, lanjutkan",
) -> None:
    """Buka st.dialog. `on_confirm` mengembalikan pesan galat (str) atau None bila berhasil."""

    @st.dialog(title)
    def _dialog() -> None:
        st.markdown(message)
        yes, no = st.columns(2)
        if yes.button(confirm_label, type="primary", use_container_width=True, key="confirm-yes"):
            problem = on_confirm()
            if problem:
                st.error(problem)
                return
            st.rerun()
        if no.button("Batal", use_container_width=True, key="confirm-no"):
            st.rerun()

    _dialog()
