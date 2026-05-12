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
    quarto_installed,
    run_publish_streaming,
    run_quarto_streaming,
    run_sync,
    run_sync_streaming,
    run_unify,
    sync_command,
)


STAGE_NAMES = [
    "Sync platforms",
    "Unify parquets",
    "Quarto render",
    "Publish (DVC + git)",
]


def _stages_markdown(status: list[str], current_idx: Optional[int]) -> str:
    badges = {
        "pending": "⚪",
        "running": "⏳",
        "done": "✅",
        "failed": "❌",
        "skipped": "➖",
    }
    lines = ["**Pipeline progress**", ""]
    for i, name in enumerate(STAGE_NAMES):
        marker = "▶" if i == current_idx else " "
        lines.append(f"{marker} {badges[status[i]]} Stage {i+1}/4 — {name}")
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
    session_state). Aparece apos o rerun forcado por _run_update_all."""
    summary = st.session_state.get("update_all_summary")
    if not summary:
        return
    stage_status = summary.get("stage_status", [])
    stage_names = summary.get("stage_names", STAGE_NAMES)
    results = summary.get("results", [])
    any_fail = any(s in ("failed", "error") for s in stage_status)
    header = "Last Update all — completed with errors" if any_fail else "Last Update all — completed"
    icon = "⚠️" if any_fail else "✅"
    badges = {
        "ok": "✅", "failed": "❌", "error": "❌",
        "skipped": "➖", "done": "✅", "pending": "⚪", "running": "⏳",
    }
    with st.expander(f"{icon} {header}", expanded=any_fail):
        # Painel macro: 4 stages
        st.markdown("**Pipeline progress**")
        for i, (name, status) in enumerate(zip(stage_names, stage_status)):
            st.write(f"{badges.get(status, '•')} Stage {i+1}/4 — {name}")
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
                    badge = badges.get(r["status"], "•")
                    detail = f" — {r['detail']}" if r.get("detail") else ""
                    st.write(f"{badge} {r['step']}{detail}")
        col1, _ = st.columns([1, 5])
        if col1.button("Dismiss", key="dismiss_update_summary"):
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
        st.cache_data.clear()
        st.rerun()


def _run_update_all_inner(
    states: list[PlatformState],
    targets: list[PlatformState],
    publish_after: bool,
) -> None:
    warning_box = st.empty()
    warning_box.warning("⚠️ Pipeline running (4 stages) — don't close this tab.")

    # Estado das 4 stages — atualizado in-place via stages_box.markdown
    stage_status: list[str] = ["pending"] * 4
    if not publish_after:
        stage_status[3] = "skipped"
    stages_box = st.empty()
    stages_box.markdown(_stages_markdown(stage_status, current_idx=None))

    # results: lista plana de itens individuais, cada um com tag de stage
    results: list[dict] = []

    def _set_stage(idx: int, status: str) -> None:
        stage_status[idx] = status
        stages_box.markdown(_stages_markdown(stage_status, current_idx=idx if status == "running" else None))

    # =================== Stage 1/4 — Sync platforms ===================
    _set_stage(0, "running")
    st.markdown(f"### Stage 1/4 — {STAGE_NAMES[0]}")
    stage1_bar = st.progress(0.0, text=f"0 / {len(targets)} platforms")
    any_sync_fail = False
    for i, s in enumerate(targets):
        st.markdown(f"**{s.name}**")
        sub_bar = st.progress(0.0, text=f"{s.name}: starting…")
        tail_box = st.empty()
        recent: list[str] = []

        def _on_line(line: str, _sub=sub_bar, _box=tail_box, _recent=recent, _name=s.name):
            _recent.append(line)
            del _recent[:-6]
            _box.code("\n".join(_recent), language=None)
            p = parse_progress(line)
            if p is not None:
                done, total = p
                pct = min(done / total, 1.0)
                _sub.progress(pct, text=f"{_name}: {done} / {total} ({int(pct*100)}%)")

        try:
            rc, tail = run_sync_streaming(s.name, on_line=_on_line)
        except Exception as e:  # noqa: BLE001
            sub_bar.empty(); tail_box.empty()
            st.error(f"❌ {s.name}: {e}")
            results.append({"stage": "1/4 Sync", "step": s.name, "status": "error", "detail": str(e)})
            any_sync_fail = True
            stage1_bar.progress((i + 1) / len(targets), text=f"{i+1} / {len(targets)} platforms")
            continue
        sub_bar.empty(); tail_box.empty()
        if rc != 0:
            st.error(f"❌ {s.name} failed (exit {rc}). tail:\n```\n{tail[-800:]}\n```")
            results.append({"stage": "1/4 Sync", "step": s.name, "status": "failed", "detail": f"exit {rc}"})
            any_sync_fail = True
        else:
            st.success(f"✅ {s.name} ok")
            results.append({"stage": "1/4 Sync", "step": s.name, "status": "ok", "detail": ""})
        stage1_bar.progress((i + 1) / len(targets), text=f"{i+1} / {len(targets)} platforms")
    stage1_bar.empty()
    _set_stage(0, "failed" if any_sync_fail else "done")

    # =================== Stage 2/4 — Unify parquets ===================
    _set_stage(1, "running")
    st.markdown(f"### Stage 2/4 — {STAGE_NAMES[1]}")
    unify_box = st.empty()
    unify_box.text("running…")
    try:
        unify_result = run_unify()
    except Exception as e:  # noqa: BLE001
        unify_box.empty()
        st.error(f"❌ unify: {e}")
        results.append({"stage": "2/4 Unify", "step": "unify-parquets", "status": "error", "detail": str(e)})
        _set_stage(1, "failed")
    else:
        unify_box.empty()
        if unify_result.returncode != 0:
            st.error(
                f"❌ unify failed (exit {unify_result.returncode}). "
                f"stderr: {(unify_result.stderr or '')[-500:]}"
            )
            results.append({"stage": "2/4 Unify", "step": "unify-parquets", "status": "failed", "detail": f"exit {unify_result.returncode}"})
            _set_stage(1, "failed")
        else:
            st.success("✅ unify ok")
            results.append({"stage": "2/4 Unify", "step": "unify-parquets", "status": "ok", "detail": ""})
            _set_stage(1, "done")

    # =================== Stage 3/4 — Quarto render ===================
    if not quarto_installed():
        st.markdown(f"### Stage 3/4 — {STAGE_NAMES[2]}")
        st.info("Quarto CLI not in PATH — skipping render. Install: `brew install quarto-cli`.")
        results.append({"stage": "3/4 Quarto", "step": "quarto-render", "status": "skipped", "detail": "quarto CLI not installed"})
        _set_stage(2, "skipped")
    else:
        _set_stage(2, "running")
        st.markdown(f"### Stage 3/4 — {STAGE_NAMES[2]}")
        q_bar = st.progress(0.0, text="quarto: starting…")
        q_box = st.empty()
        q_recent: list[str] = []

        def _q_on_line(line: str, _bar=q_bar, _box=q_box, _recent=q_recent):
            _recent.append(line)
            del _recent[:-10]
            _box.code("\n".join(_recent), language=None)
            p = parse_progress(line)
            if p is not None:
                done, total = p
                pct = min(done / total, 1.0)
                _bar.progress(pct, text=f"quarto: {done} / {total} qmds ({int(pct*100)}%)")

        try:
            rc, q_summary = run_quarto_streaming(_q_on_line)
        except Exception as e:  # noqa: BLE001
            q_bar.empty(); q_box.empty()
            st.error(f"❌ quarto: {e}")
            results.append({"stage": "3/4 Quarto", "step": "quarto-render", "status": "error", "detail": str(e)})
            _set_stage(2, "failed")
        else:
            q_bar.empty(); q_box.empty()
            if rc != 0:
                st.error(f"❌ quarto render had failures: {q_summary}")
                results.append({"stage": "3/4 Quarto", "step": "quarto-render", "status": "failed", "detail": q_summary[:300]})
                _set_stage(2, "failed")
            else:
                st.success(f"✅ quarto ok — {q_summary}")
                results.append({"stage": "3/4 Quarto", "step": "quarto-render", "status": "ok", "detail": q_summary})
                _set_stage(2, "done")

    # =================== Stage 4/4 — Publish (DVC + git) ===================
    if not publish_after:
        st.markdown(f"### Stage 4/4 — {STAGE_NAMES[3]}")
        st.info("Publish skipped (checkbox unchecked). Pai project won't see new data via `dvc import` until you run it.")
        results.append({"stage": "4/4 Publish", "step": "publish", "status": "skipped", "detail": "checkbox unchecked"})
    else:
        _set_stage(3, "running")
        st.markdown(f"### Stage 4/4 — {STAGE_NAMES[3]}")
        pub_bar = st.progress(0.0, text="publish: starting…")
        pub_box = st.empty()
        pub_recent: list[str] = []

        def _pub_on_line(line: str, _bar=pub_bar, _box=pub_box, _recent=pub_recent):
            _recent.append(line)
            del _recent[:-10]
            _box.code("\n".join(_recent), language=None)
            p = parse_progress(line)
            if p is not None:
                done, total = p
                pct = min(done / total, 1.0)
                _bar.progress(pct, text=f"publish: step {done} / {total}")

        try:
            rc, pub_summary = run_publish_streaming(_pub_on_line)
        except Exception as e:  # noqa: BLE001
            pub_bar.empty(); pub_box.empty()
            st.error(f"❌ publish: {e}")
            results.append({"stage": "4/4 Publish", "step": "publish", "status": "error", "detail": str(e)})
            _set_stage(3, "failed")
        else:
            pub_bar.empty(); pub_box.empty()
            if rc != 0:
                st.error(f"❌ publish failed:\n```\n{pub_summary[-800:]}\n```")
                results.append({"stage": "4/4 Publish", "step": "publish", "status": "failed", "detail": pub_summary[:200]})
                _set_stage(3, "failed")
            else:
                st.success("✅ publish ok (DVC + git push)")
                results.append({"stage": "4/4 Publish", "step": "publish", "status": "ok", "detail": ""})
                _set_stage(3, "done")

    warning_box.empty()

    st.session_state["update_all_summary"] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "stage_status": list(stage_status),
        "stage_names": list(STAGE_NAMES),
        "results": results,
        "publish": publish_after,
    }
