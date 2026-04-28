"""Entry point Streamlit do dashboard.

Roda com: `streamlit run dashboard.py`

Roteamento simples via st.session_state["view"]: "overview" (default) ou
"platform" + selected_platform.
"""
from __future__ import annotations

import streamlit as st

from dashboard.data import discover_platforms, load_platform_state
from dashboard.pages import overview, platform
from dashboard.sync import quarto_installed


def _sidebar() -> None:
    st.sidebar.title("AI Sessions Tracker")
    st.sidebar.caption("Captura cumulativa multi-plataforma")
    if st.sidebar.button("🏠 Overview"):
        st.session_state["view"] = "overview"
        st.rerun()

    st.sidebar.divider()
    st.sidebar.caption("**Ambiente**")
    st.sidebar.write(f"Quarto: {'✅ instalado' if quarto_installed() else '➖ ausente (Fase 3)'}")
    st.sidebar.caption(
        "Logs: capture_log.jsonl em data/raw/&lt;plat&gt;, "
        "reconcile_log.jsonl em data/merged/&lt;plat&gt;."
    )

    st.sidebar.divider()
    if st.sidebar.button("🔁 Recarregar dados"):
        st.cache_data.clear()
        st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="AI Sessions Tracker",
        page_icon="📊",
        layout="wide",
    )

    if "view" not in st.session_state:
        st.session_state["view"] = "overview"

    _sidebar()

    states = discover_platforms()

    view = st.session_state.get("view", "overview")
    if view == "platform":
        name = st.session_state.get("selected_platform")
        if not name:
            st.session_state["view"] = "overview"
            st.rerun()
            return
        state = next((s for s in states if s.name == name), None)
        if state is None:
            state = load_platform_state(name)
        platform.render(state)
    else:
        overview.render(states)


if __name__ == "__main__":
    main()
