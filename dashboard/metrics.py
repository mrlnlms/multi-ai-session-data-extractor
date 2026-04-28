"""Extracao de metricas a partir do merged.json e auxiliares.

Le sob demanda. Cache externo (st.cache_data) eh aplicado pelo caller pra
evitar reler 119MB de JSON a cada interacao do Streamlit.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dashboard.data import PlatformState, directory_size_bytes


@dataclass
class MergedStats:
    total_convs: int = 0
    active: int = 0
    preserved_missing: int = 0
    archived: int = 0
    in_projects: int = 0
    standalone: int = 0
    distinct_projects: int = 0
    total_messages_estimated: int = 0
    oldest_create_time: Optional[datetime] = None
    newest_update_time: Optional[datetime] = None
    models: Counter = field(default_factory=Counter)
    convs_per_project: Counter = field(default_factory=Counter)
    project_names: dict[str, str] = field(default_factory=dict)
    preserved_titles: list[tuple[str, str]] = field(default_factory=list)  # (id, title)
    creation_by_month: Counter = field(default_factory=Counter)


@dataclass
class ProjectSourcesStats:
    total_projects: int = 0
    projects_with_files: int = 0
    projects_empty: int = 0
    projects_all_preserved: int = 0
    total_files_active: int = 0
    total_files_preserved: int = 0
    total_size_bytes: int = 0


@dataclass
class PlatformMetrics:
    raw_size_bytes: int = 0
    merged_size_bytes: int = 0
    merged: Optional[MergedStats] = None
    project_sources: Optional[ProjectSourcesStats] = None


def _to_datetime(ts) -> Optional[datetime]:
    """Aceita epoch float ou string ISO (servidor ChatGPT retorna ISO)."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (ValueError, OverflowError):
            return None
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def _walk_messages_count(mapping: dict) -> int:
    """Conta nodes que tem `message` nao-nulo (heuristica leve)."""
    if not isinstance(mapping, dict):
        return 0
    count = 0
    for node in mapping.values():
        if isinstance(node, dict) and node.get("message"):
            count += 1
    return count


def _extract_models(mapping: dict, sink: Counter) -> None:
    """Heuristica: olha message.metadata.model_slug em cada node."""
    if not isinstance(mapping, dict):
        return
    for node in mapping.values():
        if not isinstance(node, dict):
            continue
        msg = node.get("message")
        if not isinstance(msg, dict):
            continue
        meta = msg.get("metadata") or {}
        model = meta.get("model_slug") or meta.get("default_model_slug")
        if model:
            sink[model] += 1


def compute_merged_stats(merged_json_path: Path) -> MergedStats:
    """Le e agrega stats do merged.json. Custo proporcional ao arquivo."""
    with merged_json_path.open() as f:
        data = json.load(f)
    convs = data.get("conversations") or {}
    if isinstance(convs, list):
        items = convs
    else:
        items = list(convs.values())

    stats = MergedStats(total_convs=len(items))

    today = datetime.now(timezone.utc).date().isoformat()

    for c in items:
        last_seen = c.get("_last_seen_in_server") or ""
        if last_seen.startswith(today):
            stats.active += 1
        else:
            stats.preserved_missing += 1
            stats.preserved_titles.append((c.get("id", ""), c.get("title", "(sem titulo)")))

        if c.get("_archived") or c.get("is_archived"):
            stats.archived += 1

        pid = c.get("_project_id")
        if pid:
            stats.in_projects += 1
            stats.convs_per_project[pid] += 1
            pname = c.get("_project_name")
            if pname and pid not in stats.project_names:
                stats.project_names[pid] = pname
        else:
            stats.standalone += 1

        mapping = c.get("mapping") or {}
        stats.total_messages_estimated += _walk_messages_count(mapping)
        _extract_models(mapping, stats.models)

        ct = _to_datetime(c.get("create_time"))
        if ct is not None:
            if stats.oldest_create_time is None or ct < stats.oldest_create_time:
                stats.oldest_create_time = ct
            stats.creation_by_month[ct.strftime("%Y-%m")] += 1

        ut = _to_datetime(c.get("update_time"))
        if ut is not None:
            if stats.newest_update_time is None or ut > stats.newest_update_time:
                stats.newest_update_time = ut

    stats.distinct_projects = len(stats.convs_per_project)
    return stats


def compute_project_sources_stats(raw_dir: Path) -> ProjectSourcesStats:
    """Varre raw/<plat>/project_sources/g-p-*/_files.json e binarios."""
    base = raw_dir / "project_sources"
    if not base.exists():
        return ProjectSourcesStats()

    stats = ProjectSourcesStats()
    for proj_dir in sorted(base.iterdir()):
        if not proj_dir.is_dir():
            continue
        stats.total_projects += 1
        files_index = proj_dir / "_files.json"
        active = 0
        preserved = 0
        if files_index.exists():
            try:
                entries = json.loads(files_index.read_text())
            except (json.JSONDecodeError, OSError):
                entries = []
            if isinstance(entries, list):
                for e in entries:
                    if isinstance(e, dict) and e.get("_preserved_missing"):
                        preserved += 1
                    else:
                        active += 1

        stats.total_files_active += active
        stats.total_files_preserved += preserved
        if active + preserved > 0:
            stats.projects_with_files += 1
            if active == 0:
                stats.projects_all_preserved += 1
        else:
            stats.projects_empty += 1

        for f in proj_dir.iterdir():
            if f.is_file() and f.name != "_files.json":
                try:
                    stats.total_size_bytes += f.stat().st_size
                except OSError:
                    continue

    return stats


def compute_platform_metrics(state: PlatformState) -> PlatformMetrics:
    metrics = PlatformMetrics()
    if state.raw_dir is not None:
        metrics.raw_size_bytes = directory_size_bytes(state.raw_dir)
        metrics.project_sources = compute_project_sources_stats(state.raw_dir)
    if state.merged_dir is not None:
        metrics.merged_size_bytes = directory_size_bytes(state.merged_dir)
    merged_path = state.merged_json_path
    if merged_path is not None:
        metrics.merged = compute_merged_stats(merged_path)
    return metrics


def discovery_drop_flag(state: PlatformState, threshold: float = 0.20) -> bool:
    """True se a discovery mais recente caiu mais que o threshold vs a maior historica."""
    totals = [r.discovery_total for r in state.capture_runs if r.discovery_total]
    if len(totals) < 2:
        return False
    max_known = max(totals)
    latest = totals[-1]
    return latest < max_known * (1 - threshold)
