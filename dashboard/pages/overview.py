"""Pagina inicial — visao cross-plataforma."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import (
    STATUS_BADGES,
    format_datetime,
    format_size,
    relative_time,
)
from dashboard.data import PlatformState, discover_platforms
from dashboard.metrics import compute_merged_stats, discovery_drop_flag
from dashboard.sync import run_sync, sync_command


@st.cache_data(show_spinner=False)
def _cached_merged_stats(merged_path_str: str, mtime: float):
    return compute_merged_stats(Path(merged_path_str))


@st.cache_data(show_spinner=False)
def _cached_processed_stats(parquet_path_str: str, mtime: float):
    from dashboard.metrics import compute_processed_stats
    return compute_processed_stats(Path(parquet_path_str))


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
    overdue = []
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
                overdue.append(s.name)
    return {
        "total_convs": total,
        "active": active,
        "preserved": preserved,
        "last_sync": last_sync,
        "overdue": overdue,
        "most_outdated": (most_outdated_name, most_outdated_when),
    }


def _platform_table(states: list[PlatformState]) -> pd.DataFrame:
    rows = []
    for s in states:
        total, active, preserved, newest_update = _quick_stats(s)
        rows.append(
            {
                " ": STATUS_BADGES.get(s.status(), "⚪"),
                "Plataforma": s.name,
                "Ultima captura": (
                    relative_time(s.last_capture.started_at) if s.last_capture else "—"
                ),
                "Ultima conv mexida (servidor)": (
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
        title="Discovery total por captura",
        xaxis_title="Data",
        yaxis_title="Convs descobertas",
        height=320,
        margin=dict(l=10, r=10, t=40, b=10),
    )
    if not has_data:
        fig.add_annotation(
            text="Sem capturas ainda — rode um sync para popular este grafico.",
            showarrow=False,
            font=dict(size=14),
        )
    return fig


def render(states: list[PlatformState]) -> None:
    st.title("AI Sessions Tracker")
    st.caption(
        "Captura cumulativa de sessoes AI multi-plataforma. "
        "Dashboard descritivo — counts e saude operacional."
    )

    kpis = _global_kpis(states)

    cols = st.columns(4)
    cols[0].metric("Total capturado", f"{kpis['total_convs']:,}")
    cols[1].metric("Active", f"{kpis['active']:,}")
    cols[2].metric("Preserved missing", f"{kpis['preserved']:,}")
    cols[3].metric(
        "Plataformas com dados",
        f"{sum(1 for s in states if s.has_data)}/{len(states)}",
    )

    if kpis["last_sync"]:
        ts, name = kpis["last_sync"]
        st.markdown(f"**Ultima sync global:** {relative_time(ts)} ({name}, {format_datetime(ts)})")

    if kpis["overdue"]:
        st.warning(f"⚠️ {len(kpis['overdue'])} plataformas atrasadas: {', '.join(kpis['overdue'])}")

    drops = [s.name for s in states if discovery_drop_flag(s)]
    if drops:
        st.error(f"🚨 Discovery drop detectado em: {', '.join(drops)}")

    st.divider()

    sync_disabled = not any(sync_command(s.name) for s in states)
    if st.button("🔄 Atualizar todas", disabled=sync_disabled, type="primary"):
        _run_update_all(states)

    st.divider()

    st.subheader("Plataformas")
    df = _platform_table(states)
    st.dataframe(df, hide_index=True, width="stretch")

    st.caption("Para detalhes, escolha uma plataforma:")
    cols = st.columns(min(len(states), 4))
    for i, s in enumerate(states):
        col = cols[i % len(cols)]
        if col.button(f"{STATUS_BADGES.get(s.status(), '⚪')} {s.name}", key=f"goto-{s.name}"):
            st.session_state["view"] = "platform"
            st.session_state["selected_platform"] = s.name
            st.rerun()

    st.divider()
    _render_overview_qmds_section()

    st.divider()
    st.subheader("Timeline de captura")
    st.plotly_chart(_timeline_figure(states), width="stretch")


def _render_overview_qmds_section() -> None:
    """Lista os qmds de overview cross-plataforma disponiveis (data/unified).

    Renderizam HTML self-contained de `notebooks/_template_overview.qmd`
    com filtros diferentes (todas / web / cli / rag).
    """
    from dashboard.quarto import (
        copy_to_static_for_qmd,
        html_output_path_for_qmd,
        overview_qmds,
        render_and_publish_qmd,
        streamlit_static_url_for_qmd,
    )

    qmds = overview_qmds()
    if not qmds:
        return

    st.subheader("Visões cross-plataforma")
    st.caption(
        "Comparativos consolidados de `data/unified/` — tabela pivot, "
        "stacked bars por plataforma, distribuição temporal cruzada, "
        "modelos cross, capture method, preservation."
    )

    cols = st.columns(min(len(qmds), 4))
    for i, (label, qmd) in enumerate(qmds):
        col = cols[i % len(cols)]
        html_out = html_output_path_for_qmd(qmd)
        if html_out.exists():
            # Garante copia em static/ pra Streamlit servir
            try:
                copy_to_static_for_qmd(qmd)
            except FileNotFoundError:
                pass
            url = f"/app/static/quarto/{qmd.stem}.html"
            col.markdown(
                f"📊 **{label}**  \n[Ver dados detalhados]({url}){{target=\"_blank\"}}"
            )
        else:
            if col.button(f"🔄 Render {label}", key=f"render-overview-{qmd.stem}"):
                with st.spinner(f"Render {label}..."):
                    success, err = render_and_publish_qmd(qmd)
                if success:
                    st.success(f"✅ {label} rendirizado")
                    st.rerun()
                else:
                    st.error(f"❌ {label}: {err}")


def _run_update_all(states: list[PlatformState]) -> None:
    targets = [s for s in states if sync_command(s.name)]
    if not targets:
        st.error("Nenhum sync disponivel.")
        return
    st.warning("⚠️ Sync em andamento — nao feche esta aba.")
    progress = st.progress(0.0)
    for i, s in enumerate(targets):
        with st.spinner(f"Sync {s.name}..."):
            try:
                result = run_sync(s.name)
            except Exception as e:  # noqa: BLE001 — superficie de erro pro usuario
                st.error(f"❌ {s.name}: {e}")
                continue
        if result.returncode != 0:
            st.error(
                f"❌ {s.name} falhou (exit {result.returncode}). "
                f"stderr: {(result.stderr or '')[-500:]}"
            )
        else:
            st.success(f"✅ {s.name} ok")
        progress.progress((i + 1) / len(targets))
    st.balloons()
    st.cache_data.clear()
