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
    compute_project_sources_stats,
    discovery_drop_flag,
)
from dashboard.sync import has_sync_script, run_sync, sync_command


@st.cache_data(show_spinner=False)
def _cached_merged_stats(merged_path_str: str, mtime: float):
    return compute_merged_stats(Path(merged_path_str))


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
                "Inicio": format_datetime(r.started_at),
                "Duracao (s)": (
                    f"{r.duration_seconds:.0f}" if r.duration_seconds is not None else "—"
                ),
                "Discovery": str(r.discovery_total) if r.discovery_total is not None else "—",
                "Fetch ok": (
                    f"{r.fetch_succeeded}/{r.fetch_attempted}"
                    if r.fetch_attempted is not None
                    else "—"
                ),
                "Erros": r.errors_count,
            }
        )
    return pd.DataFrame(rows)


def _reconcile_log_df(state: PlatformState) -> pd.DataFrame:
    rows = []
    for r in reversed(state.reconcile_runs):
        rows.append(
            {
                "Quando": format_datetime(r.reconciled_at),
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
        title="Convs criadas por mes",
        height=320,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis_title=None,
        yaxis_title="Count",
    )
    return fig


def render(state: PlatformState) -> None:
    if st.button("← Voltar"):
        st.session_state["view"] = "overview"
        st.rerun()

    badge = STATUS_BADGES.get(state.status(), "⚪")
    st.title(f"{badge} {state.name}")
    st.caption(f"Status: {STATUS_LABEL.get(state.status(), state.status())}")

    if not state.has_data:
        st.info(
            f"Nenhuma captura encontrada para {state.name}. "
            f"Use o botao abaixo para rodar a primeira sync."
        )
        _render_sync_button(state)
        return

    _render_status_panel(state)

    st.divider()
    st.subheader("Acoes")
    _render_sync_button(state)
    _render_quarto_section(state)

    st.divider()
    _render_metrics(state)

    st.divider()
    _render_history(state)


def _render_status_panel(state: PlatformState) -> None:
    cols = st.columns(3)
    if state.last_capture:
        lc = state.last_capture
        cols[0].metric("Ultima captura", relative_time(lc.started_at))
        cols[0].caption(format_datetime(lc.started_at))
    else:
        cols[0].metric("Ultima captura", "—")
    if state.last_reconcile:
        lr = state.last_reconcile
        cols[1].metric("Ultimo reconcile", relative_time(lr.reconciled_at))
        cols[1].caption(format_datetime(lr.reconciled_at))
    else:
        cols[1].metric("Ultimo reconcile", "—")

    raw_size = _cached_dir_size(str(state.raw_dir), state.raw_dir.stat().st_mtime) if state.raw_dir else 0
    merged_size = (
        _cached_dir_size(str(state.merged_dir), state.merged_dir.stat().st_mtime)
        if state.merged_dir
        else 0
    )
    cols[2].metric("Storage local", format_size(raw_size + merged_size))
    cols[2].caption(f"raw {format_size(raw_size)} · merged {format_size(merged_size)}")

    if discovery_drop_flag(state):
        st.error(
            "🚨 Discovery drop detectado: ultima captura veio com menos de "
            "80% do total historico. Investigar antes de confiar no merged."
        )


def _render_sync_button(state: PlatformState) -> None:
    cmd = sync_command(state.name)
    if cmd is None:
        st.info(
            f"Nenhum script de sync ou export para {state.name} ainda. "
            f"Implementar `scripts/{state.name.lower()}-sync.py` libera o botao."
        )
        return

    label = (
        f"🔄 Sync {state.name}" if has_sync_script(state.name)
        else f"🔄 Export {state.name} (sem orquestrador ainda)"
    )
    if st.button(label, key=f"sync-{state.name}", type="primary"):
        with st.spinner(f"Rodando {' '.join(cmd[-2:])}..."):
            try:
                result = run_sync(state.name)
            except Exception as e:  # noqa: BLE001
                st.error(f"❌ {e}")
                return
        if result.returncode != 0:
            st.error(f"❌ Falhou (exit {result.returncode}).")
            with st.expander("stderr"):
                st.code(result.stderr or "(vazio)")
        else:
            st.success("✅ Sync concluido")
            with st.expander("stdout"):
                st.code((result.stdout or "")[-3000:])
            st.cache_data.clear()
            st.rerun()


def _render_quarto_section(state: PlatformState) -> None:
    """Botao + link pra abrir o data-profile Quarto da plataforma.

    Estados possiveis:
    - Quarto nao instalado → hint amigavel, sem botao
    - QMD nao existe pra plataforma → mensagem informativa
    - HTML existe e atualizado → link "Ver dados detalhados" (nova aba)
    - HTML existe mas stale → link + botao "Re-renderizar"
    - HTML nao existe → botao "Renderizar dados detalhados"
    """
    if not quarto.quarto_installed():
        st.caption(
            "ℹ️ Quarto não instalado — `brew install quarto` habilita visão "
            "descritiva detalhada (`notebooks/<plat>.qmd`)."
        )
        return

    qmd = quarto.qmd_path(state.name)
    if not qmd.exists():
        st.caption(
            f"📝 Notebook descritivo Quarto não existe pra {state.name} ainda. "
            f"Implementar `notebooks/{state.name.lower()}.qmd` (modelo: "
            f"`notebooks/chatgpt.qmd`)."
        )
        return

    html_src = quarto.html_output_path(state.name)
    static_dst = quarto.html_static_path(state.name)
    stale = quarto.is_html_stale(state.name)

    cols = st.columns([3, 1])

    with cols[0]:
        if html_src.exists() and not stale:
            # Garante que static/ tem cópia atualizada (idempotente — só copia
            # se mtime diferir)
            if not static_dst.exists() or static_dst.stat().st_mtime < html_src.stat().st_mtime:
                quarto.copy_to_static(state.name)
            url = quarto.streamlit_static_url(state.name)
            st.markdown(
                f'📊 **[Ver dados detalhados ({state.name})]({url})** — '
                f'HTML self-contained, abre em nova aba',
                unsafe_allow_html=True,
            )
        elif html_src.exists() and stale:
            st.warning(
                "⚠️ Dados detalhados desatualizados — parquet mais novo que último render. "
                "Use o botão pra re-renderizar."
            )
        else:
            st.caption("📊 Dados detalhados ainda não rendirizados.")

    with cols[1]:
        label = "🔄 Re-render" if html_src.exists() else "📊 Renderizar"
        if st.button(label, key=f"render-quarto-{state.name}"):
            with st.spinner(f"Renderizando {state.name}.qmd... (~20s)"):
                ok, err = quarto.render_and_publish(state.name)
            if ok:
                st.success("✅ Rendirizado e disponível")
                st.rerun()
            else:
                st.error("❌ Render falhou")
                with st.expander("stderr"):
                    st.code(err or "(vazio)")


def _render_metrics(state: PlatformState) -> None:
    st.subheader("Conteudo capturado")
    if state.merged_json_path is None:
        st.caption("Nenhum merged.json encontrado para esta plataforma.")
        return

    merged = _cached_merged_stats(str(state.merged_json_path), state.merged_json_path.stat().st_mtime)

    cols = st.columns(4)
    cols[0].metric("Total convs", f"{merged.total_convs:,}")
    cols[1].metric("Active", f"{merged.active:,}")
    cols[2].metric("Preserved missing", f"{merged.preserved_missing:,}")
    cols[3].metric("Archived", f"{merged.archived:,}")

    cols = st.columns(3)
    cols[0].metric("Em projects", f"{merged.in_projects:,}")
    cols[1].metric("Standalone", f"{merged.standalone:,}")
    cols[2].metric("Distinct projects", f"{merged.distinct_projects:,}")

    cols = st.columns(2)
    cols[0].metric("Conv mais antiga", format_datetime(merged.oldest_create_time))
    cols[1].metric("Atividade mais recente", format_datetime(merged.newest_update_time))

    st.metric("Mensagens estimadas", f"{merged.total_messages_estimated:,}")

    if merged.creation_by_month:
        st.plotly_chart(_creation_chart(merged), width="stretch")

    if merged.models:
        with st.expander("Modelos usados (top 10)"):
            df = pd.DataFrame(merged.models.most_common(10), columns=["Model", "Mensagens"])
            st.dataframe(df, hide_index=True, width="stretch")

    if merged.convs_per_project:
        with st.expander("Top projects por convs"):
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
        with st.expander(f"Convs preservadas (deletadas no servidor) — {len(merged.preserved_titles)}"):
            df = pd.DataFrame(merged.preserved_titles, columns=["ID", "Titulo"])
            st.dataframe(df, hide_index=True, width="stretch")

    if state.raw_dir is not None:
        ps = _cached_project_sources(str(state.raw_dir), state.raw_dir.stat().st_mtime)
        if ps.total_projects:
            st.divider()
            st.subheader("Project sources (knowledge files)")
            cols = st.columns(4)
            cols[0].metric("Projects", f"{ps.total_projects}")
            cols[1].metric("Com files", f"{ps.projects_with_files}")
            cols[2].metric("Vazios", f"{ps.projects_empty}")
            cols[3].metric("Tamanho", format_size(ps.total_size_bytes))
            cols = st.columns(3)
            cols[0].metric("Files active", f"{ps.total_files_active}")
            cols[1].metric("Files preserved", f"{ps.total_files_preserved}")
            cols[2].metric("Projects 100% preserved", f"{ps.projects_all_preserved}")


def _render_history(state: PlatformState) -> None:
    st.subheader("Historico")
    tab_capture, tab_reconcile = st.tabs(["Capturas", "Reconciles"])
    with tab_capture:
        if state.capture_runs:
            st.dataframe(_capture_log_df(state), hide_index=True, width="stretch")
        else:
            st.caption("Sem capturas registradas.")
    with tab_reconcile:
        if state.reconcile_runs:
            st.dataframe(_reconcile_log_df(state), hide_index=True, width="stretch")
        else:
            st.caption("Sem reconciles registrados.")
