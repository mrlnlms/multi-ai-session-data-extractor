"""Pagina inicial — visao cross-plataforma."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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
from dashboard.progress import parse_progress
from dashboard.sync import (
    acquire_pipeline_lock,
    quarto_installed,
    release_pipeline_lock,
    run_publish_streaming,
    run_quarto_streaming,
    run_sync,
    run_sync_streaming,
    run_unify,
    run_unify_streaming,
    sync_command,
)


STAGE_NAMES = [
    "Sync platforms",
    "Unify parquets",
    "Quarto render",
    "Publish (DVC + git)",
]

# Mapeamento centralizado pra evitar bugs de inconsistencia entre painel
# macro e summary expander. "aborted" = nao rodou por causa de falha anterior;
# "skipped" = pulou intencionalmente (sem prejuizo, ex: quarto nao instalado).
_BADGES: dict[str, str] = {
    "pending": "⚪",
    "running": "⏳",
    "done": "✅",
    "ok": "✅",
    "failed": "❌",
    "error": "❌",
    "skipped": "➖",
    "aborted": "⏭️",
}


def _stages_markdown(status: list[str], current_idx: Optional[int]) -> str:
    lines = ["**Pipeline progress**", ""]
    for i, name in enumerate(STAGE_NAMES):
        marker = "▶" if i == current_idx else " "
        lines.append(f"{marker} {_BADGES.get(status[i], '•')} Stage {i+1}/4 — {name}")
    return "\n\n".join(lines)


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
                "Platform": s.name,
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


def _render_last_run_summary() -> None:
    """Mostra resumo da ultima execucao do Update all (persistido via
    session_state). Aparece apos o pipeline terminar."""
    summary = st.session_state.get("update_all_summary")
    if not summary:
        return
    stage_status = summary.get("stage_status", [])
    stage_names = summary.get("stage_names", STAGE_NAMES)
    results = summary.get("results", [])
    any_fail = any(s in ("failed", "error", "aborted") for s in stage_status)
    header = "Last Update all — completed with errors" if any_fail else "Last Update all — completed"
    icon = "⚠️" if any_fail else "✅"
    with st.expander(f"{icon} {header}", expanded=any_fail):
        # Painel macro: 4 stages
        st.markdown("**Pipeline progress**")
        for i, (name, status) in enumerate(zip(stage_names, stage_status)):
            st.write(f"{_BADGES.get(status, '•')} Stage {i+1}/4 — {name}")
        # Detalhes por stage
        if results:
            st.markdown("---")
            st.caption("Details:")
            by_stage: dict[str, list[dict]] = {}
            for r in results:
                by_stage.setdefault(r.get("stage", "?"), []).append(r)
            for stage_key, items in by_stage.items():
                st.markdown(f"**{stage_key}**")
                for r in items:
                    badge = _BADGES.get(r["status"], "•")
                    detail = f" — {r['detail']}" if r.get("detail") else ""
                    st.write(f"{badge} {r['step']}{detail}")
                    tail = r.get("tail", "")
                    # Expander com tail so pra falhas/abortos — diagnostico
                    if tail and r["status"] in ("failed", "error"):
                        with st.expander(f"  ↳ tail of {r['step']}", expanded=False):
                            st.code(tail, language=None)
        col1, col2, _ = st.columns([1, 1, 4])
        if col1.button("🔄 Reload dashboard data", key="reload_after_pipeline"):
            st.cache_data.clear()
            st.session_state.pop("update_all_summary", None)
            st.rerun()
        if col2.button("Dismiss", key="dismiss_update_summary"):
            st.session_state.pop("update_all_summary", None)
            st.rerun()


def render(states: list[PlatformState]) -> None:
    st.title("AI Sessions Tracker")
    st.caption(
        "Cumulative capture of multi-platform AI sessions. "
        "Descriptive dashboard — counts and operational health."
    )

    _render_last_run_summary()

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

    if kpis["overdue"]:
        st.warning(f"⚠️ {len(kpis['overdue'])} platforms overdue: {', '.join(kpis['overdue'])}")

    drops = [s.name for s in states if discovery_drop_flag(s)]
    if drops:
        st.error(f"🚨 Discovery drop detected in: {', '.join(drops)}")

    st.divider()

    sync_disabled = not any(sync_command(s.name) for s in states)
    is_running = st.session_state.get("update_all_running", False)
    # Inicializa estado do checkbox antes do widget pra evitar warning
    # de "value + key" do Streamlit.
    st.session_state.setdefault("update_all_publish", True)
    btn_col, opt_col = st.columns([1, 3])
    publish_after = opt_col.checkbox(
        "Stage 4/4: Publish to DVC + git push",
        key="update_all_publish",
        disabled=is_running,
        help="Pipeline = 4 stages: (1) sync per platform → (2) unify parquets → "
             "(3) Quarto render → (4) publish (dvc add → git add → commit → dvc push → "
             "git push). Stage 4 is what `pai` project consumes via `dvc import`. "
             "Uncheck if you want to dry-run sync without pushing.",
    )
    if is_running:
        btn_col.button("🔄 Running…", disabled=True, type="primary", key="update_all_running_btn")
    elif btn_col.button("🔄 Update all", disabled=sync_disabled, type="primary"):
        st.session_state["update_all_running"] = True
        _run_update_all(states, publish_after=publish_after)

    st.divider()

    st.subheader("Platforms")
    df = _platform_table(states)
    st.dataframe(df, hide_index=True, width="stretch")

    st.caption("For details, pick a platform:")
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
    st.subheader("Capture timeline")
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
            # Garante copia em static/ pra Streamlit servir
            try:
                copy_to_static_for_qmd(qmd)
            except FileNotFoundError:
                pass
            url = f"/app/static/quarto/{qmd.stem}.html"
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


def _save_summary(stage_status: list[str], results: list[dict], publish_after: bool) -> None:
    st.session_state["update_all_summary"] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "stage_status": list(stage_status),
        "stage_names": list(STAGE_NAMES),
        "results": results,
        "publish": publish_after,
    }


def _run_update_all(states: list[PlatformState], publish_after: bool = True) -> None:
    targets = [s for s in states if sync_command(s.name)]
    if not targets:
        st.error("No sync available.")
        st.session_state["update_all_running"] = False
        return

    try:
        _run_update_all_inner(states, targets, publish_after)
    finally:
        st.session_state["update_all_running"] = False
        # NAO chamamos st.cache_data.clear()/st.rerun() aqui — preserva
        # output detalhado da pipeline. Summary expander tem botao
        # "Reload dashboard data" pra forcar refresh dos cards quando o
        # user quiser.


def _run_update_all_inner(
    states: list[PlatformState],
    targets: list[PlatformState],
    publish_after: bool,
) -> None:
    # Lock previne segunda execucao em paralelo (corromperia DVC lock,
    # racear browsers). Stale lock (PID morto) eh removido automaticamente.
    lock_err = acquire_pipeline_lock()
    if lock_err:
        st.error(f"❌ {lock_err}")
        return

    try:
        _execute_pipeline(targets, publish_after)
    finally:
        release_pipeline_lock()


def _execute_pipeline(targets: list[PlatformState], publish_after: bool) -> None:
    # Aviso explicito: ChatGPT/Perplexity abrem browser visivel — Update all
    # nao eh totalmente unattended.
    needs_browser = [s.name for s in targets if s.name in ("ChatGPT", "Perplexity")]
    if needs_browser:
        st.info(
            f"ℹ️ {', '.join(needs_browser)} vai abrir browser visivel "
            f"(Cloudflare). Acompanhe — pode precisar interacao manual."
        )

    warning_box = st.empty()
    warning_box.warning("⚠️ Pipeline running (4 stages) — don't close this tab.")

    stage_status: list[str] = ["pending"] * 4
    if not publish_after:
        stage_status[3] = "skipped"
    stages_box = st.empty()
    stages_box.markdown(_stages_markdown(stage_status, current_idx=None))

    results: list[dict] = []

    def _set_stage(idx: int, status: str) -> None:
        stage_status[idx] = status
        current = idx if status == "running" else None
        stages_box.markdown(_stages_markdown(stage_status, current_idx=current))

    # =================== Stage 1/4 — Sync platforms ===================
    st.markdown(f"### Stage 1/4 — {STAGE_NAMES[0]}")
    _set_stage(0, "running")
    stage1_bar = st.progress(0.0, text=f"0 / {len(targets)} platforms")
    current_plat_box = st.empty()

    sync_rows: list[dict] = []
    any_sync_ok = False
    any_sync_fail = False

    for i, s in enumerate(targets):
        tail_lines: list[str] = []

        def _on_line(line: str, _tail=tail_lines, _name=s.name, _box=current_plat_box):
            _tail.append(line)
            if len(_tail) > 15:
                del _tail[:-15]
            p = parse_progress(line)
            progress_str = ""
            if p is not None:
                done, total = p
                pct = int(min(done / total, 1.0) * 100)
                progress_str = f"\n\nProgress: {done} / {total} ({pct}%)"
            tail_text = "\n".join(_tail[-8:])
            _box.markdown(
                f"**Stage 1 — running:** `{_name}`{progress_str}\n\n```\n{tail_text}\n```"
            )

        try:
            rc, tail = run_sync_streaming(s.name, on_line=_on_line)
        except Exception as e:  # noqa: BLE001
            rc, tail = -1, f"exception: {e}"

        status = "ok" if rc == 0 else "failed"
        sync_rows.append({
            " ": _BADGES["ok"] if rc == 0 else _BADGES["failed"],
            "Platform": s.name,
            "Status": "ok" if rc == 0 else f"failed (rc={rc})",
        })
        results.append({
            "stage": "1/4 Sync",
            "step": s.name,
            "status": status,
            "detail": "" if rc == 0 else f"rc={rc}",
            "tail": tail[-2000:],
        })
        if rc == 0:
            any_sync_ok = True
        else:
            any_sync_fail = True

        stage1_bar.progress((i + 1) / len(targets), text=f"{i+1} / {len(targets)} platforms")

    current_plat_box.empty()
    stage1_bar.empty()

    # Resumo compacto do stage 1 (substitui os 12+ markdowns/success/error spam)
    st.markdown("**Stage 1 results**")
    st.dataframe(pd.DataFrame(sync_rows), hide_index=True, width="stretch")

    # Aborta pipeline so se TODAS plats falharam — falhas parciais sao
    # toleradas, parquets das plats OK ainda valem unify.
    if not any_sync_ok:
        _set_stage(0, "failed")
        st.error("❌ All platforms failed in Stage 1 — aborting Stages 2-4.")
        for idx, stage_name in [(1, "2/4 Unify"), (2, "3/4 Quarto")]:
            _set_stage(idx, "aborted")
            results.append({
                "stage": stage_name, "step": "abort", "status": "aborted",
                "detail": "all stage 1 platforms failed", "tail": "",
            })
        if publish_after:
            _set_stage(3, "aborted")
            results.append({
                "stage": "4/4 Publish", "step": "abort", "status": "aborted",
                "detail": "all stage 1 platforms failed", "tail": "",
            })
        warning_box.empty()
        _save_summary(stage_status, results, publish_after)
        return

    _set_stage(0, "failed" if any_sync_fail else "done")

    # =================== Stage 2/4 — Unify parquets ===================
    st.markdown(f"### Stage 2/4 — {STAGE_NAMES[1]}")
    _set_stage(1, "running")
    unify_box = st.empty()
    unify_tail: list[str] = []

    def _unify_on_line(line: str, _tail=unify_tail, _box=unify_box):
        _tail.append(line)
        if len(_tail) > 20:
            del _tail[:-20]
        tail_text = "\n".join(_tail[-12:])
        _box.markdown(f"**Stage 2 — unify-parquets**\n\n```\n{tail_text}\n```")

    try:
        rc, unify_full_tail = run_unify_streaming(_unify_on_line)
    except Exception as e:  # noqa: BLE001
        rc, unify_full_tail = -1, f"exception: {e}"
    unify_box.empty()

    if rc != 0:
        st.error(f"❌ unify failed (rc={rc}). tail:\n```\n{unify_full_tail[-800:]}\n```")
        results.append({
            "stage": "2/4 Unify", "step": "unify-parquets", "status": "failed",
            "detail": f"rc={rc}", "tail": unify_full_tail[-2000:],
        })
        _set_stage(1, "failed")
        # ABORTA stages 3-4 — quarto depende de data/unified/, publish nao deveria
        # commitar estado inconsistente.
        _set_stage(2, "aborted")
        results.append({
            "stage": "3/4 Quarto", "step": "quarto-render", "status": "aborted",
            "detail": "stage 2 unify failed", "tail": "",
        })
        if publish_after:
            _set_stage(3, "aborted")
            results.append({
                "stage": "4/4 Publish", "step": "publish", "status": "aborted",
                "detail": "stage 2 unify failed", "tail": "",
            })
        warning_box.empty()
        _save_summary(stage_status, results, publish_after)
        return

    st.success("✅ unify ok")
    results.append({
        "stage": "2/4 Unify", "step": "unify-parquets", "status": "ok",
        "detail": "", "tail": "",
    })
    _set_stage(1, "done")

    # =================== Stage 3/4 — Quarto render ===================
    st.markdown(f"### Stage 3/4 — {STAGE_NAMES[2]}")
    stage3_ok = True  # quarto-missing trata como skipped (nao bloqueia publish)
    if not quarto_installed():
        st.info("Quarto CLI not in PATH — skipping render. Install: `brew install quarto-cli`.")
        results.append({
            "stage": "3/4 Quarto", "step": "quarto-render", "status": "skipped",
            "detail": "quarto CLI not installed", "tail": "",
        })
        _set_stage(2, "skipped")
    else:
        _set_stage(2, "running")
        q_bar = st.progress(0.0, text="quarto: starting…")
        q_box = st.empty()
        q_tail: list[str] = []

        def _q_on_line(line: str, _bar=q_bar, _box=q_box, _tail=q_tail):
            _tail.append(line)
            if len(_tail) > 20:
                del _tail[:-20]
            tail_text = "\n".join(_tail[-12:])
            _box.markdown(f"**Stage 3 — quarto render**\n\n```\n{tail_text}\n```")
            p = parse_progress(line)
            if p is not None:
                done, total = p
                pct = min(done / total, 1.0)
                _bar.progress(pct, text=f"quarto: {done} / {total} qmds ({int(pct*100)}%)")

        try:
            rc, q_summary = run_quarto_streaming(_q_on_line)
        except Exception as e:  # noqa: BLE001
            rc, q_summary = -1, f"exception: {e}"
        q_bar.empty(); q_box.empty()

        if rc != 0:
            st.error(f"❌ quarto render had failures: {q_summary}")
            results.append({
                "stage": "3/4 Quarto", "step": "quarto-render", "status": "failed",
                "detail": q_summary[:300], "tail": q_summary[-2000:],
            })
            _set_stage(2, "failed")
            stage3_ok = False
        else:
            st.success(f"✅ quarto ok — {q_summary}")
            results.append({
                "stage": "3/4 Quarto", "step": "quarto-render", "status": "ok",
                "detail": q_summary, "tail": "",
            })
            _set_stage(2, "done")

    # =================== Stage 4/4 — Publish (DVC + git) ===================
    st.markdown(f"### Stage 4/4 — {STAGE_NAMES[3]}")
    if not publish_after:
        st.info(
            "Publish skipped (checkbox unchecked). Pai project won't see "
            "new data via `dvc import` until you run it."
        )
        results.append({
            "stage": "4/4 Publish", "step": "publish", "status": "skipped",
            "detail": "checkbox unchecked", "tail": "",
        })
    elif not stage3_ok:
        st.warning(
            "⏭️ Publish aborted — Quarto stage failed. Resolve quarto issues then re-run."
        )
        results.append({
            "stage": "4/4 Publish", "step": "publish", "status": "aborted",
            "detail": "stage 3 quarto failed", "tail": "",
        })
        _set_stage(3, "aborted")
    else:
        _set_stage(3, "running")
        pub_bar = st.progress(0.0, text="publish: starting…")
        pub_box = st.empty()
        pub_tail: list[str] = []

        def _pub_on_line(line: str, _bar=pub_bar, _box=pub_box, _tail=pub_tail):
            _tail.append(line)
            if len(_tail) > 20:
                del _tail[:-20]
            tail_text = "\n".join(_tail[-12:])
            _box.markdown(f"**Stage 4 — publish**\n\n```\n{tail_text}\n```")
            p = parse_progress(line)
            if p is not None:
                done, total = p
                pct = min(done / total, 1.0)
                _bar.progress(pct, text=f"publish: step {done} / {total}")

        try:
            rc, pub_summary = run_publish_streaming(_pub_on_line)
        except Exception as e:  # noqa: BLE001
            rc, pub_summary = -1, f"exception: {e}"
        pub_bar.empty(); pub_box.empty()

        if rc != 0:
            st.error(f"❌ publish failed:\n```\n{pub_summary[-800:]}\n```")
            results.append({
                "stage": "4/4 Publish", "step": "publish", "status": "failed",
                "detail": pub_summary[:200], "tail": pub_summary[-2000:],
            })
            _set_stage(3, "failed")
        else:
            st.success(f"✅ publish ok — {pub_summary}")
            results.append({
                "stage": "4/4 Publish", "step": "publish", "status": "ok",
                "detail": pub_summary, "tail": "",
            })
            _set_stage(3, "done")

    warning_box.empty()
    _save_summary(stage_status, results, publish_after)
