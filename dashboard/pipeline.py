"""Pipeline 4-stage: sync (1+ plats) -> unify -> quarto -> publish.

Reusado por:
- `pages/overview.py` — "Update all" com todas plataformas
- `pages/platform.py` — "Run full pipeline (this platform)" com 1 plat

Side-effects Streamlit (st.markdown, st.empty, etc) — chamar de dentro de
um render(). Lockfile (`.update-all.lock`) previne segunda execucao
concorrente. Gating: stages 2-4 abortam se anterior falhou (exceto Stage 3
quarto-missing = skipped benigno).

A unica diferenca entre "Update all" e "1 plat" eh o tamanho de `targets`.
Stages 2-4 rodam sempre que algum sync (>= 1) deu OK — porque eles
materializam `data/unified/`, renderizam Quarto e versionam via DVC, e
isso depende do estado agregado, nao da plat sincronizada.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

from dashboard.data import PROJECT_ROOT, PlatformState
from dashboard.progress import parse_progress
from dashboard.sync import (
    acquire_pipeline_lock,
    quarto_installed,
    release_pipeline_lock,
    run_publish_streaming,
    run_quarto_streaming,
    run_sync_streaming,
    run_unify_streaming,
    sync_command,
)

# Trilha persistente de runs — append-only jsonl, sobrevive a restart do
# Streamlit. Sem tails (so metadata) pra nao inflar; tails ficam no
# session_state ate o user clicar Dismiss.
RUNS_LOG = PROJECT_ROOT / ".pipeline-runs.jsonl"


STAGE_NAMES: list[str] = [
    "Sync platforms",
    "Unify parquets",
    "Quarto render",
    "Publish (DVC + git)",
]

# Mapeamento centralizado pra evitar bugs de inconsistencia entre painel
# macro e summary expander. "aborted" = nao rodou por causa de falha anterior;
# "skipped" = pulou intencionalmente (sem prejuizo, ex: quarto nao instalado).
BADGES: dict[str, str] = {
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
        lines.append(f"{marker} {BADGES.get(status[i], '•')} Stage {i+1}/4 — {name}")
    return "\n\n".join(lines)


def _save_summary(stage_status: list[str], results: list[dict], publish_after: bool, scope: str) -> None:
    """Persiste resumo da ultima execucao em session_state pra render
    posterior. `scope` = 'all' | 'platform:<name>' identifica origem.
    Tambem grava em .pipeline-runs.jsonl pra historico."""
    summary = {
        "at": datetime.now(timezone.utc).isoformat(),
        "stage_status": list(stage_status),
        "stage_names": list(STAGE_NAMES),
        "results": results,
        "publish": publish_after,
        "scope": scope,
    }
    st.session_state["pipeline_summary"] = summary
    persist_run(stage_status, results, publish_after, scope)


def persist_run(stage_status: list[str], results: list[dict], publish_after: bool, scope: str) -> None:
    """Append entry no `.pipeline-runs.jsonl` com metadata da run. Sem tails
    (estavam em session_state). Falha silenciosa — nao bloqueia pipeline."""
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "stage_status": list(stage_status),
        "publish": publish_after,
        "results": [
            {k: v for k, v in r.items() if k != "tail"}
            for r in results
        ],
    }
    try:
        with RUNS_LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def commit_msg_for_scope(scope: str) -> str:
    """Mensagem de commit pro Stage 4 baseada no scope da run.

    'all'              -> 'data: dashboard sync (all platforms, 2026-05-12)'
    'platform:Gemini'  -> 'data: dashboard sync (Gemini, 2026-05-12)'
    'cli:headless'     -> 'data: cli headless sync (2026-05-12)'

    Usado pra evitar commits genericos identicos quando se roda varios
    Update all / sync por plat no mesmo dia.
    """
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if scope == "all":
        return f"data: dashboard sync (all platforms, {date})"
    if scope.startswith("platform:"):
        plat = scope.split(":", 1)[1]
        return f"data: dashboard sync ({plat}, {date})"
    if scope.startswith("cli:"):
        kind = scope.split(":", 1)[1]
        return f"data: {kind} sync ({date})"
    return f"data: pipeline sync ({scope}, {date})"


def recent_runs(limit: int = 10) -> list[dict]:
    """Le ultimas N entries do .pipeline-runs.jsonl, mais recente primeiro."""
    if not RUNS_LOG.exists():
        return []
    entries: list[dict] = []
    try:
        with RUNS_LOG.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return entries[-limit:][::-1]


def render_recent_runs_section(limit: int = 10) -> None:
    """Renderiza tabela das ultimas N runs (overview/platform). Skip se vazio."""
    runs = recent_runs(limit)
    if not runs:
        return
    st.subheader("Recent pipeline runs")
    rows = []
    for r in runs:
        stages = " ".join(BADGES.get(s, "•") for s in r.get("stage_status", []))
        rows.append({
            "When": r.get("at", "")[:19].replace("T", " "),
            "Scope": r.get("scope", ""),
            "Stages": stages,
            "Publish": "✓" if r.get("publish") else "—",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def render_last_run_summary() -> None:
    """Mostra resumo da ultima execucao do pipeline (persistido via
    session_state). Aparece tanto em overview quanto em platform page."""
    summary = st.session_state.get("pipeline_summary")
    if not summary:
        return
    stage_status = summary.get("stage_status", [])
    stage_names = summary.get("stage_names", STAGE_NAMES)
    results = summary.get("results", [])
    scope = summary.get("scope", "all")
    any_fail = any(s in ("failed", "error", "aborted") for s in stage_status)
    scope_label = "all platforms" if scope == "all" else scope.replace("platform:", "")
    header_base = f"Last pipeline run ({scope_label})"
    header = f"{header_base} — completed with errors" if any_fail else f"{header_base} — completed"
    icon = "⚠️" if any_fail else "✅"
    with st.expander(f"{icon} {header}", expanded=any_fail):
        # Painel macro: 4 stages
        st.markdown("**Pipeline progress**")
        for i, (name, status) in enumerate(zip(stage_names, stage_status)):
            st.write(f"{BADGES.get(status, '•')} Stage {i+1}/4 — {name}")
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
                    badge = BADGES.get(r["status"], "•")
                    detail = f" — {r['detail']}" if r.get("detail") else ""
                    st.write(f"{badge} {r['step']}{detail}")
                    tail = r.get("tail", "")
                    # Expander com tail so pra falhas — diagnostico
                    if tail and r["status"] in ("failed", "error"):
                        with st.expander(f"  ↳ tail of {r['step']}", expanded=False):
                            st.code(tail, language=None)
        col1, col2, _ = st.columns([1, 1, 4])
        if col1.button("🔄 Reload dashboard data", key="reload_after_pipeline"):
            st.cache_data.clear()
            st.session_state.pop("pipeline_summary", None)
            st.rerun()
        if col2.button("Dismiss", key="dismiss_pipeline_summary"):
            st.session_state.pop("pipeline_summary", None)
            st.rerun()


def run_full_pipeline(
    targets: list[PlatformState],
    publish_after: bool,
    scope: str = "all",
) -> None:
    """Roda o pipeline completo: sync (1+ plats) -> unify -> quarto -> publish.

    - `targets`: 1 ou N plats com `sync_command` disponivel.
    - `publish_after`: liga/desliga Stage 4.
    - `scope`: 'all' ou 'platform:<name>' — pra summary saber o contexto.

    Lockfile protege contra duplo-run. Gating de stages aborta pipeline
    cedo se algo critico falhar — nao commita estado quebrado.
    """
    lock_err = acquire_pipeline_lock()
    if lock_err:
        st.error(f"❌ {lock_err}")
        return

    try:
        _execute_pipeline(targets, publish_after, scope)
    finally:
        release_pipeline_lock()


def _execute_pipeline(targets: list[PlatformState], publish_after: bool, scope: str) -> None:
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
    stage1_title = (
        f"### Stage 1/4 — Sync ({len(targets)} platform{'s' if len(targets) != 1 else ''})"
    )
    st.markdown(stage1_title)
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
            " ": BADGES["ok"] if rc == 0 else BADGES["failed"],
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
        _save_summary(stage_status, results, publish_after, scope)
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
        _save_summary(stage_status, results, publish_after, scope)
        return

    st.success("✅ unify ok")
    results.append({
        "stage": "2/4 Unify", "step": "unify-parquets", "status": "ok",
        "detail": "", "tail": "",
    })
    _set_stage(1, "done")

    # =================== Stage 3/4 — Quarto render ===================
    st.markdown(f"### Stage 3/4 — {STAGE_NAMES[2]}")
    stage3_ok = True
    # Filter incremental: sync de 1 plat re-renderiza so qmds dela + cross-
    # overview. Update all (scope='all') re-renderiza tudo.
    quarto_filter: Optional[list[str]] = (
        [t.name for t in targets] if scope.startswith("platform:") else None
    )
    if not quarto_installed():
        st.info("Quarto CLI not in PATH — skipping render. Install: `brew install quarto-cli`.")
        results.append({
            "stage": "3/4 Quarto", "step": "quarto-render", "status": "skipped",
            "detail": "quarto CLI not installed", "tail": "",
        })
        _set_stage(2, "skipped")
    else:
        _set_stage(2, "running")
        if quarto_filter:
            st.caption(
                f"Incremental: rendering qmds of `{', '.join(quarto_filter)}` + cross-overviews."
            )
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
            rc, q_summary = run_quarto_streaming(_q_on_line, platforms_filter=quarto_filter)
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
            rc, pub_summary = run_publish_streaming(
                _pub_on_line, commit_msg=commit_msg_for_scope(scope)
            )
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
    _save_summary(stage_status, results, publish_after, scope)
