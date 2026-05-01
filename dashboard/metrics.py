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


def compute_processed_stats(parquet_path: Path) -> MergedStats:
    """Le stats do conversations.parquet (canonico cross-platform).
    Preferir sobre compute_merged_stats: schema uniforme entre plataformas."""
    import duckdb
    con = duckdb.connect()
    p = str(parquet_path)
    stats = MergedStats()
    row = con.execute(f"""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE NOT is_preserved_missing) AS active,
            COUNT(*) FILTER (WHERE is_preserved_missing) AS preserved,
            COUNT(*) FILTER (WHERE is_archived) AS archived,
            COUNT(*) FILTER (WHERE project_id IS NOT NULL) AS in_proj,
            COUNT(*) FILTER (WHERE project_id IS NULL) AS standalone,
            COUNT(DISTINCT project_id) FILTER (WHERE project_id IS NOT NULL) AS distinct_proj,
            SUM(message_count) AS total_msgs,
            MIN(created_at) AS oldest,
            MAX(updated_at) AS newest
        FROM '{p}'
    """).fetchone()
    stats.total_convs = row[0] or 0
    stats.active = row[1] or 0
    stats.preserved_missing = row[2] or 0
    stats.archived = row[3] or 0
    stats.in_projects = row[4] or 0
    stats.standalone = row[5] or 0
    stats.distinct_projects = row[6] or 0
    stats.total_messages_estimated = int(row[7] or 0)
    if row[8]:
        ot = row[8] if isinstance(row[8], datetime) else datetime.fromisoformat(str(row[8]))
        stats.oldest_create_time = ot if ot.tzinfo else ot.replace(tzinfo=timezone.utc)
    if row[9]:
        nt = row[9] if isinstance(row[9], datetime) else datetime.fromisoformat(str(row[9]))
        stats.newest_update_time = nt if nt.tzinfo else nt.replace(tzinfo=timezone.utc)

    # Models top
    for model, n in con.execute(f"SELECT model, COUNT(*) FROM '{p}' WHERE model IS NOT NULL GROUP BY model").fetchall():
        stats.models[model] = n
    # Per-project
    for pid, n in con.execute(f"SELECT project_id, COUNT(*) FROM '{p}' WHERE project_id IS NOT NULL GROUP BY project_id").fetchall():
        stats.convs_per_project[pid] = n
    for pid, pname in con.execute(f"SELECT project_id, ANY_VALUE(project) FROM '{p}' WHERE project_id IS NOT NULL AND project IS NOT NULL GROUP BY project_id").fetchall():
        if pname:
            stats.project_names[pid] = pname
    # Preserved titles
    for cid, title in con.execute(f"SELECT conversation_id, title FROM '{p}' WHERE is_preserved_missing").fetchall():
        stats.preserved_titles.append((cid, title or "(sem titulo)"))
    # Creation by month
    for month, n in con.execute(f"SELECT strftime(created_at, '%Y-%m'), COUNT(*) FROM '{p}' WHERE created_at IS NOT NULL GROUP BY 1 ORDER BY 1").fetchall():
        stats.creation_by_month[month] = n
    return stats


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
    # Preferir parquet canonico; fallback pro merged JSON (schema ChatGPT-only)
    parquet_path = state.conversations_parquet_path
    if parquet_path is not None:
        metrics.merged = compute_processed_stats(parquet_path)
    else:
        merged_path = state.merged_json_path
        if merged_path is not None:
            metrics.merged = compute_merged_stats(merged_path)
    return metrics


def discovery_drop_flag(state: PlatformState, threshold: float = 0.20) -> bool:
    """True se a discovery mais recente caiu mais que o threshold vs a maior historica.

    Modos `refetch_known` sao ignorados — eles capturam um subset proposital
    (ex: 1 conv que errou na run anterior), nao representam discovery do
    listing global.
    """
    full_runs = [r for r in state.capture_runs if r.mode != "refetch_known"]
    totals = [r.discovery_total for r in full_runs if r.discovery_total]
    if len(totals) < 2:
        return False
    max_known = max(totals)
    latest = totals[-1]
    return latest < max_known * (1 - threshold)
