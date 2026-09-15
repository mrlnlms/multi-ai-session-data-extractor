"""Pagina inicial — visao cross-plataforma."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import (
    STATUS_BADGES,
    format_datetime,
    relative_time,
)
from src.application.platforms import PlatformState
from src.application.profiles import compute_merged_stats, discovery_drop_flag
from dashboard.pipeline import (
    render_last_run_summary,
    render_recent_runs_section,
    run_full_pipeline,
)
from src.workflows.execution import sync_command


@st.cache_data(show_spinner=False)
def _cached_merged_stats(merged_path_str: str, mtime: float):
    return compute_merged_stats(Path(merged_path_str))


@st.cache_data(show_spinner=False)
def _cached_processed_stats(parquet_path_str: str, mtime: float):
    from src.application.profiles import compute_processed_stats
    return compute_processed_stats(Path(parquet_path_str))


@st.cache_data(show_spinner=False)
def _cached_asset_graph_stats(assets_path_str: str, links_path_str: str, mtimes: tuple):
    assets = pd.read_parquet(assets_path_str, columns=["source", "is_binary_available"])
    links = pd.read_parquet(links_path_str, columns=["asset_link_id"])
    return {
        "assets": len(assets),
        "links": len(links),
        "sources": assets["source"].nunique(),
        "available": int(assets["is_binary_available"].fillna(False).sum()),
    }


def _quick_stats(state: PlatformState) -> tuple[int, int, int, "datetime | None"]:
    """Retorna (total, active, preserved, newest_update_time) — None/0 se sem dados.
    Prefere parquet canonico; fallback pro merged JSON (legacy ChatGPT)."""
    parquet = state.conversations_parquet_path
    if parquet is not None:
        stats = _cached_processed_stats(str(parquet), parquet.stat().st_mtime)
        return (stats.total_convs, stats.active, stats.preserved_missing, stats.newest_update_time)
    merged = state.merged_json_path
    if merged is None:
        return (0, 0, 0, None)
    stats = _cached_merged_stats(str(merged), merged.stat().st_mtime)
    return (stats.total_convs, stats.active, stats.preserved_missing, stats.newest_update_time)


def _global_kpis(states: list[PlatformState]) -> dict:
    total = active = preserved = 0
    last_sync = None
    most_outdated_name = None
    most_outdated_when = None
    failed = []
    for s in states:
        t, a, p, _ = _quick_stats(s)
        total += t
        active += a
        preserved += p
        if s.last_capture and s.last_capture.started_at:
            ts = s.last_capture.started_at
            if last_sync is None or ts > last_sync[0]:
                last_sync = (ts, s.name)
            if most_outdated_when is None or ts < most_outdated_when:
                most_outdated_when = ts
                most_outdated_name = s.name
            if s.status() == "red":
                failed.append(s.name)
    return {
        "total_convs": total,
        "active": active,
        "preserved": preserved,
        "last_sync": last_sync,
        "failed": failed,
        "most_outdated": (most_outdated_name, most_outdated_when),
    }


def _platform_table(states: list[PlatformState]) -> pd.DataFrame:
    rows = []
    for s in states:
        total, active, preserved, newest_update = _quick_stats(s)
        health = s.health()
        rows.append(
            {
                " ": STATUS_BADGES.get(health.color, "⚪"),
                "Platform": s.name,
                "Health": health.reason,
                "Last capture": (
                    relative_time(s.last_capture.started_at) if s.last_capture else "—"
                ),
                "Last conv touched (server)": (
                    relative_time(newest_update) if newest_update else "—"
                ),
                "Total": f"{total:,}" if total else "—",
                "Active": f"{active:,}" if active else "—",
                "Preserved": f"{preserved:,}" if preserved else "—",
            }
        )
    return pd.DataFrame(rows)


def _timeline_figure(states: list[PlatformState]) -> go.Figure:
    """Plot cumulativo: discovery_total ao longo do tempo, por plataforma."""
    fig = go.Figure()
    has_data = False
    for s in states:
        runs = [(r.started_at, r.discovery_total) for r in s.capture_runs if r.started_at]
        if not runs:
            continue
        runs.sort()
        xs = [t for t, _ in runs]
        ys = [v if v is not None else 0 for _, v in runs]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name=s.name))
        has_data = True
    fig.update_layout(
        title="Discovery total per capture",
        xaxis_title="Date",
        yaxis_title="Convs discovered",
        height=320,
        margin=dict(l=10, r=10, t=40, b=10),
    )
    if not has_data:
        fig.add_annotation(
            text="No captures yet — run a sync to populate this chart.",
            showarrow=False,
            font=dict(size=14),
        )
    return fig


def render(states: list[PlatformState]) -> None:
    st.title("AI Sessions Tracker")
    st.caption(
        "Cumulative capture of multi-platform AI sessions. "
        "Descriptive dashboard — counts and operational health."
    )

    render_last_run_summary()

    kpis = _global_kpis(states)

    cols = st.columns(4)
    cols[0].metric("Total captured", f"{kpis['total_convs']:,}")
    cols[1].metric("Active", f"{kpis['active']:,}")
    cols[2].metric("Preserved missing", f"{kpis['preserved']:,}")
    cols[3].metric(
        "Platforms with data",
        f"{sum(1 for s in states if s.has_data)}/{len(states)}",
    )

    if kpis["last_sync"]:
        ts, name = kpis["last_sync"]
        st.markdown(f"**Last global sync:** {relative_time(ts)} ({name}, {format_datetime(ts)})")

    if kpis["failed"]:
        st.error(f"🚨 {len(kpis['failed'])} platforms failed: {', '.join(kpis['failed'])}")

    drops = [s.name for s in states if discovery_drop_flag(s)]
    if drops:
        st.error(f"🚨 Discovery drop detected in: {', '.join(drops)}")

    st.divider()

    sync_disabled = not any(sync_command(s.name) for s in states)
    is_running = st.session_state.get("pipeline_running", False)
    st.session_state.setdefault("update_all_publish", True)
    btn_col, opt_col = st.columns([1, 3])
    publish_after = opt_col.checkbox(
        "Stage 4/4: Publish to DVC + git push",
        key="update_all_publish",
        disabled=is_running,
        help="Pipeline = 4 stages: (1) sync per platform → (2) unify parquets → "
             "(3) Quarto render → (4) publish (dvc add → git add → commit → dvc push → "
             "git push). Stage 4 publishes the data consumed by AI Interaction Analysis. "
             "Uncheck if you want to dry-run sync without pushing.",
    )
    if is_running:
        btn_col.button("🔄 Running…", disabled=True, type="primary", key="update_all_running_btn")
    elif btn_col.button("🔄 Update all", disabled=sync_disabled, type="primary"):
        st.session_state["pipeline_running"] = True
        _run_update_all(states, publish_after=publish_after)

    st.divider()

    st.subheader("Platforms")
    df = _platform_table(states)
    st.dataframe(df, hide_index=True, width="stretch")

    project_root = Path(__file__).resolve().parents[2]
    assets_path = project_root / "data" / "unified" / "assets.parquet"
    links_path = project_root / "data" / "unified" / "asset_links.parquet"
    if assets_path.is_file() and links_path.is_file():
        asset_stats = _cached_asset_graph_stats(
            str(assets_path), str(links_path),
            (assets_path.stat().st_mtime, links_path.stat().st_mtime),
        )
        st.caption(
            "Canonical asset graph: "
            f"{asset_stats['assets']:,} assets · {asset_stats['links']:,} links · "
            f"{asset_stats['available']:,} local binaries · "
            f"{asset_stats['sources']}/9 web sources. Coverage is partial."
        )

    st.caption("For details, pick a platform:")
    cols = st.columns(min(len(states), 4))
    for i, s in enumerate(states):
        col = cols[i % len(cols)]
        health = s.health()
        if col.button(
            f"{STATUS_BADGES.get(health.color, '⚪')} {s.name}",
            key=f"goto-{s.name}",
            help=health.reason,
        ):
            st.session_state["view"] = "platform"
            st.session_state["selected_platform"] = s.name
            st.rerun()

    st.divider()
    _render_overview_qmds_section()

    st.divider()
    render_recent_runs_section()

    st.divider()
    st.subheader("Capture timeline")
    st.plotly_chart(_timeline_figure(states), width="stretch")


def _render_overview_qmds_section() -> None:
    """Lista os qmds de overview cross-plataforma disponiveis (data/unified).

    Renderizam HTML self-contained de `notebooks/_template_overview.qmd`
    com filtros diferentes (todas / web / cli / rag).
    """
    from dashboard.quarto import (
        html_output_path_for_qmd,
        overview_qmds,
        report_url_for_qmd,
        render_and_publish_qmd,
    )

    qmds = overview_qmds()
    if not qmds:
        return

    st.subheader("Cross-platform views")
    st.caption(
        "Consolidated comparisons from `data/unified/` — pivot table, "
        "stacked bars per platform, cross temporal distribution, "
        "cross models, capture method, preservation."
    )

    cols = st.columns(min(len(qmds), 4))
    for i, (label, qmd) in enumerate(qmds):
        col = cols[i % len(cols)]
        html_out = html_output_path_for_qmd(qmd)
        if html_out.exists():
            url = report_url_for_qmd(qmd)
            col.markdown(
                f"📊 **{label}**  \n[View detailed data]({url}){{target=\"_blank\"}}"
            )
        else:
            if col.button(f"🔄 Render {label}", key=f"render-overview-{qmd.stem}"):
                with st.spinner(f"Render {label}..."):
                    success, err = render_and_publish_qmd(qmd)
                if success:
                    st.success(f"✅ {label} rendered")
                    st.rerun()
                else:
                    st.error(f"❌ {label}: {err}")


def _run_update_all(states: list[PlatformState], publish_after: bool = True) -> None:
    targets = [s for s in states if sync_command(s.name)]
    if not targets:
        st.error("No sync available.")
        st.session_state["pipeline_running"] = False
        return
    try:
        run_full_pipeline(targets, publish_after, scope="all")
    finally:
        st.session_state["pipeline_running"] = False
