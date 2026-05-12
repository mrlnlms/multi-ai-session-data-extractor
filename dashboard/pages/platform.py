"""Drill-down por plataforma."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import (
    STATUS_BADGES,
    STATUS_LABEL,
    format_datetime,
    format_size,
    relative_time,
)
from dashboard import quarto
from dashboard.data import PlatformState, directory_size_bytes, load_platform_state
from dashboard.metrics import (
    compute_merged_stats,
    compute_processed_stats,
    compute_project_sources_stats,
    discovery_drop_flag,
)
from dashboard.pipeline import render_last_run_summary, run_full_pipeline
from dashboard.sync import has_sync_script, sync_command


@st.cache_data(show_spinner=False)
def _cached_merged_stats(merged_path_str: str, mtime: float):
    return compute_merged_stats(Path(merged_path_str))


@st.cache_data(show_spinner=False)
def _cached_processed_stats(parquet_path_str: str, mtime: float):
    return compute_processed_stats(Path(parquet_path_str))


@st.cache_data(show_spinner=False)
def _cached_project_sources(raw_dir_str: str, mtime: float):
    return compute_project_sources_stats(Path(raw_dir_str))


@st.cache_data(show_spinner=False)
def _cached_dir_size(path_str: str, mtime: float) -> int:
    return directory_size_bytes(Path(path_str))


def _capture_log_df(state: PlatformState) -> pd.DataFrame:
    rows = []
    for r in reversed(state.capture_runs):
        rows.append(
            {
                "Start": format_datetime(r.started_at),
                "Duration (s)": (
                    f"{r.duration_seconds:.0f}" if r.duration_seconds is not None else "—"
                ),
                "Discovery": str(r.discovery_total) if r.discovery_total is not None else "—",
                "Fetch ok": (
                    f"{r.fetch_succeeded}/{r.fetch_attempted}"
                    if r.fetch_attempted is not None
                    else "—"
                ),
                "Errors": r.errors_count,
            }
        )
    return pd.DataFrame(rows)


def _reconcile_log_df(state: PlatformState) -> pd.DataFrame:
    rows = []
    for r in reversed(state.reconcile_runs):
        rows.append(
            {
                "When": format_datetime(r.reconciled_at),
                "Added": r.added,
                "Updated": r.updated,
                "Copied": r.copied,
                "Preserved missing": r.preserved_missing,
                "Warnings": r.warnings_count,
            }
        )
    return pd.DataFrame(rows)


def _creation_chart(merged_stats) -> go.Figure:
    months = sorted(merged_stats.creation_by_month.items())
    xs = [m for m, _ in months]
    ys = [c for _, c in months]
    fig = go.Figure(go.Bar(x=xs, y=ys))
    fig.update_layout(
        title="Convs created per month",
        height=320,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis_title=None,
        yaxis_title="Count",
    )
    return fig


def render(state: PlatformState) -> None:
    if st.button("← Back"):
        st.session_state["view"] = "overview"
        st.rerun()

    badge = STATUS_BADGES.get(state.status(), "⚪")
    st.title(f"{badge} {state.name}")
    st.caption(f"Status: {STATUS_LABEL.get(state.status(), state.status())}")

    render_last_run_summary()

    if not state.has_data:
        st.info(
            f"No capture found for {state.name}. "
            f"Use the button below to run the first pipeline."
        )
        _render_pipeline_button(state)
        return

    _render_status_panel(state)

    st.divider()
    st.subheader("Actions")
    _render_pipeline_button(state)
    _render_quarto_section(state)

    st.divider()
    _render_metrics(state)

    st.divider()
    _render_history(state)


def _render_status_panel(state: PlatformState) -> None:
    cols = st.columns(3)
    if state.last_capture:
        lc = state.last_capture
        cols[0].metric("Last capture", relative_time(lc.started_at))
        cols[0].caption(format_datetime(lc.started_at))
    else:
        cols[0].metric("Last capture", "—")
    if state.last_reconcile:
        lr = state.last_reconcile
        cols[1].metric("Last reconcile", relative_time(lr.reconciled_at))
        cols[1].caption(format_datetime(lr.reconciled_at))
    else:
        cols[1].metric("Last reconcile", "—")

    raw_size = _cached_dir_size(str(state.raw_dir), state.raw_dir.stat().st_mtime) if state.raw_dir else 0
    merged_size = (
        _cached_dir_size(str(state.merged_dir), state.merged_dir.stat().st_mtime)
        if state.merged_dir
        else 0
    )
    cols[2].metric("Local storage", format_size(raw_size + merged_size))
    cols[2].caption(f"raw {format_size(raw_size)} · merged {format_size(merged_size)}")

    if discovery_drop_flag(state):
        st.error(
            "🚨 Discovery drop detected: last capture came with less than "
            "80% of the historical total. Investigate before trusting the merged."
        )


def _render_pipeline_button(state: PlatformState) -> None:
    """Botao de pipeline completo (4 stages) escopado pra esta plataforma.

    Mesmo fluxo do "Update all" do overview, mas com targets=[state]:
    sync (so esta plat) -> unify (todas plats no processed/) -> quarto
    (todos qmds) -> publish (DVC + git). Stages 2-4 nao sao filtraveis
    porque sao agregados — voce nao pode "unificar so 1 plat" sem
    quebrar `data/unified/`.
    """
    cmd = sync_command(state.name)
    if cmd is None:
        st.info(
            f"No sync or export script for {state.name} yet. "
            f"Implementing `scripts/{state.name.lower()}-sync.py` enables the button."
        )
        return

    is_running = st.session_state.get("pipeline_running", False)
    sync_label = (
        f"🔄 Run full pipeline ({state.name})"
        if has_sync_script(state.name)
        else f"🔄 Run full pipeline ({state.name} — export only, no orchestrator)"
    )

    publish_key = f"platform_publish_{state.name}"
    st.session_state.setdefault(publish_key, True)
    btn_col, opt_col = st.columns([1, 3])
    publish_after = opt_col.checkbox(
        "Stage 4/4: Publish to DVC + git push",
        key=publish_key,
        disabled=is_running,
        help=(
            f"Pipeline = 4 stages: (1) sync **{state.name}** → (2) unify "
            f"parquets (all plats in processed/) → (3) Quarto render (all qmds) "
            f"→ (4) publish (dvc add → commit → push). Uncheck Stage 4 to "
            f"dry-run without committing to DVC/git."
        ),
    )

    if is_running:
        btn_col.button(
            "🔄 Running…", disabled=True, type="primary",
            key=f"pipeline-running-{state.name}",
        )
        return

    if btn_col.button(sync_label, key=f"pipeline-{state.name}", type="primary"):
        st.session_state["pipeline_running"] = True
        try:
            run_full_pipeline([state], publish_after, scope=f"platform:{state.name}")
        finally:
            st.session_state["pipeline_running"] = False


def _render_quarto_section(state: PlatformState) -> None:
    """Botoes + links pra abrir os data-profile Quarto da plataforma.

    Suporta:
    - .qmd consolidado (`notebooks/<plat>.qmd`)
    - .qmd per-account (`notebooks/<plat>-acc-{N}.qmd`) — multi-conta
    """
    if not quarto.quarto_installed():
        st.caption(
            "ℹ️ Quarto not installed — `brew install quarto` enables detailed "
            "descriptive view (`notebooks/<plat>.qmd`)."
        )
        return

    consolidated = quarto.qmd_path(state.name)
    per_account = quarto.qmd_paths_per_account(state.name)

    if not consolidated.exists() and not per_account:
        st.caption(
            f"📝 Quarto descriptive notebook does not exist for {state.name} yet. "
            f"Implement `notebooks/{state.name.lower()}.qmd` (template: "
            f"`notebooks/chatgpt.qmd`)."
        )
        return

    # 1) Consolidado
    if consolidated.exists():
        _render_qmd_row(state, consolidated, label_suffix="(consolidated)")

    # 2) Per-account
    for acc_label, qmd in per_account:
        _render_qmd_row(state, qmd, label_suffix=f"({acc_label})")


def _render_qmd_row(state: PlatformState, qmd, label_suffix: str) -> None:
    """Linha pra 1 .qmd (consolidado ou per-account): link + botao re-render."""
    html_src = quarto.html_output_path_for_qmd(qmd)
    static_dst = quarto.html_static_path_for_qmd(qmd)
    stale = quarto.is_html_stale_for_qmd(state.name, qmd)

    cols = st.columns([3, 1])

    with cols[0]:
        if html_src.exists() and not stale:
            if not static_dst.exists() or static_dst.stat().st_mtime < html_src.stat().st_mtime:
                quarto.copy_to_static_for_qmd(qmd)
            url = quarto.streamlit_static_url_for_qmd(qmd)
            st.markdown(
                f'📊 **[View detailed data {label_suffix}]({url})** — '
                f'self-contained HTML, opens in a new tab',
                unsafe_allow_html=True,
            )
        elif html_src.exists() and stale:
            st.warning(
                f"⚠️ Detailed data {label_suffix} out of date — parquet newer than last render."
            )
        else:
            st.caption(f"📊 Detailed data {label_suffix} not rendered yet.")

    with cols[1]:
        label = "🔄 Re-render" if html_src.exists() else "📊 Render"
        if st.button(label, key=f"render-quarto-{qmd.stem}"):
            with st.spinner(f"Rendering {qmd.name}... (~20s)"):
                ok, err = quarto.render_and_publish_qmd(qmd)
            if ok:
                st.success("✅ Rendered and available")
                st.rerun()
            else:
                st.error("❌ Render failed")
                with st.expander("stderr"):
                    st.code(err or "(empty)")


def _render_metrics(state: PlatformState) -> None:
    st.subheader("Captured content")
    parquet = state.conversations_parquet_path
    if parquet is not None:
        merged = _cached_processed_stats(str(parquet), parquet.stat().st_mtime)
    elif state.merged_json_path is not None:
        merged = _cached_merged_stats(str(state.merged_json_path), state.merged_json_path.stat().st_mtime)
    else:
        st.caption("No parquet or merged.json found for this platform.")
        return

    cols = st.columns(4)
    cols[0].metric("Total convs", f"{merged.total_convs:,}")
    cols[1].metric("Active", f"{merged.active:,}")
    cols[2].metric("Preserved missing", f"{merged.preserved_missing:,}")
    cols[3].metric("Archived", f"{merged.archived:,}")

    cols = st.columns(3)
    cols[0].metric("In projects", f"{merged.in_projects:,}")
    cols[1].metric("Standalone", f"{merged.standalone:,}")
    cols[2].metric("Distinct projects", f"{merged.distinct_projects:,}")

    cols = st.columns(2)
    cols[0].metric("Oldest conv", format_datetime(merged.oldest_create_time))
    cols[1].metric("Most recent activity", format_datetime(merged.newest_update_time))

    st.metric("Estimated messages", f"{merged.total_messages_estimated:,}")

    if merged.creation_by_month:
        st.plotly_chart(_creation_chart(merged), width="stretch")

    if merged.models:
        with st.expander("Models used (top 10)"):
            df = pd.DataFrame(merged.models.most_common(10), columns=["Model", "Messages"])
            st.dataframe(df, hide_index=True, width="stretch")

    if merged.convs_per_project:
        with st.expander("Top projects by convs"):
            top = merged.convs_per_project.most_common(15)
            df = pd.DataFrame(
                [
                    {
                        "Project": merged.project_names.get(pid, pid),
                        "Convs": count,
                    }
                    for pid, count in top
                ]
            )
            st.dataframe(df, hide_index=True, width="stretch")

    if merged.preserved_titles:
        with st.expander(f"Preserved convs (deleted on server) — {len(merged.preserved_titles)}"):
            df = pd.DataFrame(merged.preserved_titles, columns=["ID", "Title"])
            st.dataframe(df, hide_index=True, width="stretch")

    if state.raw_dir is not None:
        ps = _cached_project_sources(str(state.raw_dir), state.raw_dir.stat().st_mtime)
        if ps.total_projects:
            st.divider()
            st.subheader("Project sources (knowledge files)")
            cols = st.columns(4)
            cols[0].metric("Projects", f"{ps.total_projects}")
            cols[1].metric("With files", f"{ps.projects_with_files}")
            cols[2].metric("Empty", f"{ps.projects_empty}")
            cols[3].metric("Size", format_size(ps.total_size_bytes))
            cols = st.columns(3)
            cols[0].metric("Files active", f"{ps.total_files_active}")
            cols[1].metric("Files preserved", f"{ps.total_files_preserved}")
            cols[2].metric("Projects 100% preserved", f"{ps.projects_all_preserved}")


def _render_history(state: PlatformState) -> None:
    st.subheader("History")
    tab_capture, tab_reconcile = st.tabs(["Captures", "Reconciles"])
    with tab_capture:
        if state.capture_runs:
            st.dataframe(_capture_log_df(state), hide_index=True, width="stretch")
        else:
            st.caption("No captures recorded.")
    with tab_reconcile:
        if state.reconcile_runs:
            st.dataframe(_reconcile_log_df(state), hide_index=True, width="stretch")
        else:
            st.caption("No reconciles recorded.")
