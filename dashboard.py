"""Entry point Streamlit do dashboard.

Roda com: `streamlit run dashboard.py`

Roteamento simples via st.session_state["view"]: "overview" (default) ou
"platform" + selected_platform.
"""
from __future__ import annotations

import subprocess
import webbrowser

import streamlit as st

from dashboard.data import PROJECT_ROOT, discover_platforms, load_platform_state
from dashboard.pages import overview, platform
from dashboard.sync import quarto_installed


def _sidebar() -> None:
    st.sidebar.title("AI Sessions Tracker")
    st.sidebar.caption("Cumulative multi-platform capture")
    if st.sidebar.button("🏠 Overview"):
        st.session_state["view"] = "overview"
        st.rerun()

    st.sidebar.divider()
    st.sidebar.caption("**Environment**")
    st.sidebar.write(f"Quarto: {'✅ installed' if quarto_installed() else '➖ missing (Phase 3)'}")
    st.sidebar.caption(
        "Logs: `capture_log.jsonl` in `data/raw/<plat>/`, "
        "`reconcile_log.jsonl` in `data/merged/<plat>/`."
    )

    st.sidebar.divider()
    if st.sidebar.button("🔁 Reload data"):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.divider()
    st.sidebar.subheader("🔌 Servers")

    # --- Quarto Server Control ---
    try:
        q_status_raw = subprocess.run(
            ["./scripts/serve-qmds.sh", "status"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False
        ).stdout
        is_q_up = "rodando" in q_status_raw.lower()
    except Exception:
        is_q_up = False

    q_col1, q_col2 = st.sidebar.columns([3, 1])
    q_col1.write(f"Quarto: {'🟢' if is_q_up else '🔴'}")

    if is_q_up:
        if q_col2.button("🛑", help="Stop Quarto Server", key="stop_q"):
            subprocess.run(["./scripts/serve-qmds.sh", "stop"], cwd=str(PROJECT_ROOT), check=False)
            st.rerun()
    else:
        if q_col2.button("▶️", help="Start Quarto Server & Open", key="start_q"):
            subprocess.run(["./scripts/serve-qmds.sh", "start"], cwd=str(PROJECT_ROOT), check=False)
            webbrowser.open("http://localhost:8765/00-overview.html")
            st.rerun()

    # --- Streamlit Server Control ---
    if st.sidebar.button("💀 Shutdown Dashboard", help="Stop this Streamlit server", use_container_width=True):
        st.sidebar.warning("Shutting down...")
        import os
        import signal
        os.kill(os.getpid(), signal.SIGINT)


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
