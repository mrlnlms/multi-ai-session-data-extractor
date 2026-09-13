"""Streamlit presentation adapter for the UI-neutral operational pipeline."""
from __future__ import annotations

import webbrowser
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import streamlit as st

from dashboard.progress import parse_progress
from dashboard.quarto import report_server_base_url
from src.application.platforms import PlatformState
from src.workflows.pipeline import (
    STAGE_NAMES,
    PipelineEvent,
    PipelineRequest,
    PipelineResult,
    recent_runs,
    run_pipeline,
)
from src.workflows.serve_reports import start_server

BADGES = {
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
    for index, name in enumerate(STAGE_NAMES):
        marker = "▶" if index == current_idx else " "
        lines.append(
            f"{marker} {BADGES.get(status[index], '•')} "
            f"Stage {index + 1}/4 — {name}"
        )
    return "\n\n".join(lines)


def _save_summary(result: PipelineResult, publish_after: bool, scope: str) -> None:
    st.session_state["pipeline_summary"] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "stage_status": list(result.stage_status),
        "stage_names": list(STAGE_NAMES),
        "results": list(result.results),
        "publish": publish_after,
        "scope": scope,
    }


def render_recent_runs_section(limit: int = 10) -> None:
    runs = recent_runs(limit)
    if not runs:
        return
    st.subheader("Recent pipeline runs")
    rows = [
        {
            "When": run.get("at", "")[:19].replace("T", " "),
            "Scope": run.get("scope", ""),
            "Stages": " ".join(
                BADGES.get(status, "•") for status in run.get("stage_status", [])
            ),
            "Publish": "✓" if run.get("publish") else "—",
        }
        for run in runs
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def render_last_run_summary() -> None:
    summary = st.session_state.get("pipeline_summary")
    if not summary:
        return
    statuses = summary.get("stage_status", [])
    scope = summary.get("scope", "all")
    failed = any(status in ("failed", "error", "aborted") for status in statuses)
    scope_label = "all platforms" if scope == "all" else scope.replace("platform:", "")
    ending, icon = ("completed with errors", "⚠️") if failed else ("completed", "✅")
    with st.expander(f"{icon} Last pipeline run ({scope_label}) — {ending}", expanded=failed):
        st.markdown("**Pipeline progress**")
        stage_rows = zip(summary.get("stage_names", STAGE_NAMES), statuses)
        for index, (name, status) in enumerate(stage_rows):
            st.write(f"{BADGES.get(status, '•')} Stage {index + 1}/4 — {name}")
        results = summary.get("results", [])
        if results:
            st.markdown("---")
            st.caption("Details:")
            grouped: dict[str, list[dict]] = {}
            for row in results:
                grouped.setdefault(row.get("stage", "?"), []).append(row)
            for stage, items in grouped.items():
                st.markdown(f"**{stage}**")
                for row in items:
                    detail = f" — {row['detail']}" if row.get("detail") else ""
                    st.write(f"{BADGES.get(row['status'], '•')} {row['step']}{detail}")
                    if row.get("tail") and row["status"] in ("failed", "error"):
                        with st.expander(f"  ↳ tail of {row['step']}", expanded=False):
                            st.code(row["tail"], language=None)
        col1, col2, _ = st.columns([1, 1, 4])
        if col1.button("🔄 Reload dashboard data", key="reload_after_pipeline"):
            st.cache_data.clear()
            st.session_state.pop("pipeline_summary", None)
            st.rerun()
        if col2.button("Dismiss", key="dismiss_pipeline_summary"):
            st.session_state.pop("pipeline_summary", None)
            st.rerun()


class _StreamlitPipelineView:
    """Translate workflow events into live Streamlit widgets."""

    def __init__(self, statuses: list[str], scope: str) -> None:
        self.statuses, self.scope = statuses, scope
        self.warning_box, self.stages_box = st.empty(), st.empty()
        self.boxes: dict[tuple[int, str], object] = {}
        self.tails: dict[tuple[int, str], list[str]] = {}
        self.bars: dict[int, object] = {}
        self.sync_rows: list[dict[str, str]] = []
        self.sync_bar = None

    def __call__(self, event: PipelineEvent) -> None:
        if event.kind == "lock_error":
            st.error(f"❌ {event.message}")
            return
        if event.kind == "started":
            self.warning_box.warning(
                "⚠️ Pipeline running (4 stages) — don't close this tab."
            )
            self.stages_box.markdown(_stages_markdown(self.statuses, None))
            count = event.total or 0
            suffix = "s" if count != 1 else ""
            st.markdown(f"### Stage 1/4 — Sync + parse ({count} platform{suffix})")
            self.sync_bar = st.progress(0.0, text=f"0 / {count} platforms")
            return
        if event.kind == "stage_started" and event.stage_index is not None:
            st.markdown(
                f"### Stage {event.stage_index + 1}/4 — {STAGE_NAMES[event.stage_index]}"
            )
            return
        if event.kind == "stage_status" and event.stage_index is not None:
            self.statuses[event.stage_index] = event.status or "pending"
            current = event.stage_index if event.status == "running" else None
            self.stages_box.markdown(_stages_markdown(self.statuses, current))
            return
        if event.kind == "output" and event.stage_index is not None:
            self._output(event)
            return
        if event.kind == "sync_progress" and self.sync_bar is not None:
            done, total = event.completed or 0, event.total or 1
            self.sync_bar.progress(done / total, text=f"{done} / {total} platforms")
            return
        if event.kind == "step_result":
            self._result(event)
            return
        if event.kind == "report_ready":
            try:
                start_server()
                webbrowser.open(_get_auto_open_url(self.scope))
            except Exception as exc:  # noqa: BLE001
                st.warning(f"⚠️ Quarto ok, but failed to auto-open browser: {exc}")
            return
        if event.kind == "finished":
            if self.sync_bar is not None:
                self.sync_bar.empty()
            if self.sync_rows:
                st.markdown("**Stage 1 results**")
                st.dataframe(
                    pd.DataFrame(self.sync_rows), hide_index=True, width="stretch"
                )
            for widget in (*self.boxes.values(), *self.bars.values()):
                widget.empty()
            self.warning_box.empty()

    def _output(self, event: PipelineEvent) -> None:
        label, stage = event.platform or "stage", event.stage_index or 0
        key = (stage, label)
        tail = self.tails.setdefault(key, [])
        tail.append(event.line or "")
        del tail[:-20]
        box = self.boxes.setdefault(key, st.empty())
        progress, progress_text = parse_progress(event.line or ""), ""
        if progress is not None:
            done, total = progress
            ratio = min(done / total, 1)
            progress_text = f"\n\nProgress: {done} / {total} ({int(ratio * 100)}%)"
            if stage in (2, 3):
                bar = self.bars.setdefault(
                    stage,
                    st.progress(0.0, text=f"stage {stage + 1}: starting…"),
                )
                bar.progress(ratio, text=f"stage {stage + 1}: {done} / {total}")
        tail_text = "\n".join(tail[-12:])
        box.markdown(
            f"**Stage {stage + 1} — running: `{label}`**{progress_text}"
            f"\n\n```\n{tail_text}\n```"
        )

    def _result(self, event: PipelineEvent) -> None:
        if event.stage_index == 0 and event.platform:
            ok = event.status == "ok"
            self.sync_rows.append(
                {
                    " ": BADGES["ok" if ok else "failed"],
                    "Platform": event.platform,
                    "Status": "ok" if ok else f"failed ({event.message})",
                }
            )
        elif event.status == "ok":
            st.success(f"✅ {STAGE_NAMES[event.stage_index or 0]} ok")
        elif event.status == "skipped":
            st.info(event.message or "Stage skipped")
        elif event.status == "aborted":
            st.warning(f"⏭️ {event.message}")
        elif event.status == "failed":
            st.error(f"❌ {event.message or 'Stage failed'}")


def run_full_pipeline(
    targets: list[PlatformState], publish_after: bool, scope: str = "all"
) -> None:
    headed = [
        state.name for state in targets if state.name in ("ChatGPT", "Perplexity")
    ]
    if headed:
        st.info(
            f"ℹ️ {', '.join(headed)} vai abrir browser visivel (Cloudflare). "
            "Acompanhe — pode precisar interacao manual."
        )
    statuses = ["pending"] * 4
    if not publish_after:
        statuses[3] = "skipped"
    result = run_pipeline(
        PipelineRequest(tuple(state.name for state in targets), publish_after, scope),
        emit=_StreamlitPipelineView(statuses, scope),
    )
    if result.lock_error is None:
        _save_summary(result, publish_after, scope)


def _get_auto_open_url(scope: str) -> str:
    base_url = report_server_base_url()
    if scope == "all":
        return f"{base_url}/00-overview.html"
    if scope.startswith("platform:"):
        slug = scope.split(":", 1)[1].lower().replace(".", "-").replace(" ", "-")
        return f"{base_url}/{slug}.html"
    return f"{base_url}/00-overview.html"
