"""Discovery e leitura de estado das plataformas.

Varre `data/raw/<plat>/` e `data/merged/<plat>/`, le LAST_*.md e logs jsonl.
Lista canonica de KNOWN_PLATFORMS garante que plataformas conhecidas
aparecam mesmo sem captura ainda.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_MERGED = PROJECT_ROOT / "data" / "merged"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"

KNOWN_PLATFORMS: list[str] = [
    "ChatGPT",
    "Claude.ai",
    "Gemini",
    "NotebookLM",
    "Qwen",
    "DeepSeek",
    "Perplexity",
]

SCRIPT_PREFIX: dict[str, str] = {
    "ChatGPT": "chatgpt",
    "Claude.ai": "claude",
    "Gemini": "gemini",
    "NotebookLM": "notebooklm",
    "Qwen": "qwen",
    "DeepSeek": "deepseek",
    "Perplexity": "perplexity",
}


@dataclass
class CaptureRun:
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    duration_seconds: Optional[float]
    discovery_total: Optional[int]
    fetch_attempted: Optional[int]
    fetch_succeeded: Optional[int]
    errors_count: int = 0


@dataclass
class ReconcileRun:
    reconciled_at: Optional[datetime]
    added: int = 0
    updated: int = 0
    copied: int = 0
    preserved_missing: int = 0
    warnings_count: int = 0


@dataclass
class PlatformState:
    name: str
    raw_dir: Optional[Path]
    merged_dir: Optional[Path]
    processed_dir: Optional[Path] = None
    capture_runs: list[CaptureRun] = field(default_factory=list)
    reconcile_runs: list[ReconcileRun] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return bool(self.capture_runs or self.reconcile_runs or self.raw_dir or self.merged_dir)

    @property
    def last_capture(self) -> Optional[CaptureRun]:
        return self.capture_runs[-1] if self.capture_runs else None

    @property
    def last_reconcile(self) -> Optional[ReconcileRun]:
        return self.reconcile_runs[-1] if self.reconcile_runs else None

    @property
    def merged_json_path(self) -> Optional[Path]:
        if self.merged_dir is None:
            return None
        for cand in sorted(self.merged_dir.glob("*_merged.json")):
            return cand
        return None

    @property
    def conversations_parquet_path(self) -> Optional[Path]:
        """Parquet canonico (cross-platform). Preferir sobre merged_json_path
        quando disponivel — schema uniforme entre plataformas."""
        if self.processed_dir is None:
            return None
        cand = self.processed_dir / "conversations.parquet"
        return cand if cand.exists() else None

    def status(self, now: Optional[datetime] = None) -> str:
        """green | yellow | red | gray"""
        ref = self.last_capture.started_at if self.last_capture else None
        if ref is None:
            return "gray"
        now = now or datetime.now(timezone.utc)
        delta = (now - ref).total_seconds()
        if delta < 86400:
            return "green"
        if delta < 86400 * 3:
            return "yellow"
        return "red"


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _load_capture_log(path: Path) -> list[CaptureRun]:
    if not path.exists():
        return []
    runs: list[CaptureRun] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            # ChatGPT schema: run_started_at, discovery.total, fetch.{attempted,succeeded}
            # Perplexity schema: started_at, totals.{threads_discovered,threads_fetched}
            started = _parse_iso(d.get("run_started_at") or d.get("started_at"))
            finished = _parse_iso(d.get("run_finished_at") or d.get("finished_at"))
            duration = d.get("duration_seconds")
            if duration is None and started and finished:
                duration = (finished - started).total_seconds()
            discovery = d.get("discovery") or {}
            fetch = d.get("fetch") or {}
            totals = d.get("totals") or {}
            errors = d.get("errors")
            errors_count = (
                len(errors) if isinstance(errors, list)
                else sum(len(v) for v in errors.values() if isinstance(v, list)) if isinstance(errors, dict)
                else 0
            )
            runs.append(
                CaptureRun(
                    started_at=started,
                    finished_at=finished,
                    duration_seconds=duration,
                    discovery_total=discovery.get("total") or totals.get("threads_discovered"),
                    fetch_attempted=fetch.get("attempted") or totals.get("threads_fetched"),
                    fetch_succeeded=fetch.get("succeeded") or totals.get("threads_fetched"),
                    errors_count=errors_count,
                )
            )
    return runs


def _load_reconcile_log(path: Path) -> list[ReconcileRun]:
    if not path.exists():
        return []
    runs: list[ReconcileRun] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            runs.append(
                ReconcileRun(
                    reconciled_at=_parse_iso(d.get("reconciled_at")),
                    added=d.get("added") or 0,
                    updated=d.get("updated") or 0,
                    copied=d.get("copied") or 0,
                    preserved_missing=d.get("preserved_missing") or 0,
                    warnings_count=len(d.get("warnings") or []),
                )
            )
    return runs


def load_platform_state(name: str) -> PlatformState:
    raw_dir = DATA_RAW / name
    merged_dir = DATA_MERGED / name
    processed_dir = DATA_PROCESSED / name
    raw_dir = raw_dir if raw_dir.exists() else None
    merged_dir = merged_dir if merged_dir.exists() else None
    processed_dir = processed_dir if processed_dir.exists() else None

    capture_runs = _load_capture_log(raw_dir / "capture_log.jsonl") if raw_dir else []
    reconcile_runs = _load_reconcile_log(merged_dir / "reconcile_log.jsonl") if merged_dir else []

    return PlatformState(
        name=name,
        raw_dir=raw_dir,
        merged_dir=merged_dir,
        processed_dir=processed_dir,
        capture_runs=capture_runs,
        reconcile_runs=reconcile_runs,
    )


def discover_platforms() -> list[PlatformState]:
    """Une KNOWN_PLATFORMS com qualquer pasta extra encontrada em data/.
    Ignora pastas com espaco ou prefixos legacy (e.g. 'Perplexity Data')."""
    def _is_valid_extra(name: str) -> bool:
        # Ignora legacy: pastas com espaco, prefixos timestamp, etc
        if " " in name or name.startswith((".", "_")):
            return False
        return True

    found_raw = {p.name for p in DATA_RAW.iterdir() if p.is_dir()} if DATA_RAW.exists() else set()
    found_merged = {p.name for p in DATA_MERGED.iterdir() if p.is_dir()} if DATA_MERGED.exists() else set()
    extras = sorted((found_raw | found_merged) - set(KNOWN_PLATFORMS))
    extras = [n for n in extras if _is_valid_extra(n)]
    names = list(KNOWN_PLATFORMS) + extras
    return [load_platform_state(n) for n in names]


def directory_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                continue
    return total
