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

from src.accounts import AccountState, discover_accounts
from src.platforms.registry import KNOWN_PLATFORMS, SCRIPT_PREFIX
from src.runtime.project import find_project_root

PROJECT_ROOT = find_project_root(Path(__file__))
DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_MERGED = PROJECT_ROOT / "data" / "merged"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
DATA_EXTERNAL = PROJECT_ROOT / "data" / "external"
STORAGE_ROOT = PROJECT_ROOT / ".storage"

PARSER_INPUT_SUFFIXES: dict[str, frozenset[str]] = {
    "Claude Code": frozenset({".jsonl"}),
    "Codex": frozenset({".jsonl"}),
    "Gemini CLI": frozenset({".json"}),
    "Antigravity CLI": frozenset({".db", ".jsonl", ".pb"}),
}
DEFAULT_PARSER_INPUT_SUFFIXES = frozenset({".json"})


@dataclass(frozen=True)
class HealthStatus:
    color: str
    label: str
    reason: str


@dataclass
class CaptureRun:
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    duration_seconds: Optional[float]
    discovery_total: Optional[int]
    fetch_attempted: Optional[int]
    fetch_succeeded: Optional[int]
    errors_count: int = 0
    files_seen: Optional[int] = None
    files_parsed: Optional[int] = None
    files_skipped: Optional[int] = None
    mode: Optional[str] = None  # 'full' | 'incremental' | 'refetch_known' | None
    account: Optional[str] = None  # multi-conta (Gemini/NotebookLM); None pra single


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
    accounts: tuple[AccountState, ...] = ()
    _health_cache: Optional[HealthStatus] = field(default=None, init=False, repr=False)

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
        quando disponivel — schema uniforme entre plataformas.

        Aceita 3 convencoes de naming, em ordem de prioridade:
        - `<source>_conversations.parquet` (parser v3 canonico)
        - `conversations.parquet` (estilo legacy ChatGPT)
        - `<source>_manual_conversations.parquet` (manual saves / legacy
          accounts) — fallback so quando nao ha canonico"""
        if self.processed_dir is None:
            return None
        # Prioriza canonico v3 (exclui _manual_ — esses sao agregados via
        # setup_views_with_manual nos quartos consolidados)
        candidates = sorted(self.processed_dir.glob("*_conversations.parquet"))
        for cand in candidates:
            if "_manual_" not in cand.name:
                return cand
        # Fallback: legacy ChatGPT-style
        cand = self.processed_dir / "conversations.parquet"
        if cand.exists():
            return cand
        # Ultimo recurso: so ha _manual_
        return candidates[0] if candidates else None

    def newest_parser_input(self) -> Optional[Path]:
        """Arquivo de entrada mais recente que pode alimentar o parser.

        Fontes web preferem o reconciliado; CLIs, que nao possuem essa etapa,
        usam o raw. Logs e outros metadados ficam fora pela extensao.
        """
        suffixes = PARSER_INPUT_SUFFIXES.get(self.name, DEFAULT_PARSER_INPUT_SUFFIXES)
        for root in (self.merged_dir, self.raw_dir):
            if root is None or not root.exists():
                continue
            candidates = (
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in suffixes
                and path.name not in {"capture_log.jsonl", "reconcile_log.jsonl"}
            )
            newest = max(candidates, key=lambda path: path.stat().st_mtime, default=None)
            if newest is not None:
                return newest
        return None

    def health(self) -> HealthStatus:
        """Saude da pipeline, independente da idade da ultima captura."""
        if self._health_cache is not None:
            return self._health_cache
        if self.last_capture is None:
            result = HealthStatus("gray", "never ran", "No capture has been recorded")
        elif self.last_capture.errors_count:
            count = self.last_capture.errors_count
            noun = "error" if count == 1 else "errors"
            result = HealthStatus(
                "yellow",
                "attention",
                f"Last capture completed with {count} {noun}",
            )
        elif self.last_capture.files_skipped:
            count = self.last_capture.files_skipped
            noun = "session file" if count == 1 else "session files"
            result = HealthStatus(
                "yellow",
                "attention",
                f"Parser skipped {count} {noun}",
            )
        elif self.conversations_parquet_path is None:
            result = HealthStatus(
                "red",
                "failed",
                "Processed conversations Parquet is missing",
            )
        else:
            parquet = self.conversations_parquet_path
            newest_input = self.newest_parser_input()
            if newest_input and parquet and parquet.stat().st_mtime < newest_input.stat().st_mtime:
                result = HealthStatus(
                    "red",
                    "failed",
                    f"{newest_input.name} is newer than the processed Parquet",
                )
            else:
                result = HealthStatus("green", "OK", "Processed data is up to date")
        self._health_cache = result
        return result

    def status(self, now: Optional[datetime] = None) -> str:
        """Compatibilidade: retorna green | yellow | red | gray.

        `now` e mantido na assinatura para callers antigos; recencia nao faz
        mais parte da cor de saude.
        """
        return self.health().color


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
            # ChatGPT schema:    run_started_at, discovery.total, fetch.{attempted,succeeded}
            # Perplexity schema: started_at, totals.{threads_discovered,threads_fetched}
            # Claude.ai schema:  started_at, totals.{conversations_discovered,conversations_fetched}
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
                    mode=d.get("mode"),
                    discovery_total=(
                        discovery.get("total")
                        or totals.get("threads_discovered")
                        or totals.get("conversations_discovered")
                        or totals.get("notebooks_discovered")
                    ),
                    fetch_attempted=(
                        fetch.get("attempted")
                        or totals.get("threads_fetched")
                        or totals.get("conversations_fetched")
                        or totals.get("notebooks_fetched")
                    ),
                    fetch_succeeded=(
                        fetch.get("succeeded")
                        or totals.get("threads_fetched")
                        or totals.get("conversations_fetched")
                        or totals.get("notebooks_fetched")
                    ),
                    errors_count=errors_count,
                    files_seen=totals.get("files_seen"),
                    files_parsed=totals.get("files_parsed"),
                    files_skipped=totals.get("files_skipped"),
                    account=(str(d["account"]) if "account" in d and d["account"] is not None else None),
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
            # Schemas:
            #  - ChatGPT:    added/updated/copied/preserved_missing (top-level)
            #  - Perplexity: threads_added/_updated/_copied/_preserved_missing
            #  - Claude.ai:  convs_added/_updated/_copied/_preserved_missing
            runs.append(
                ReconcileRun(
                    reconciled_at=_parse_iso(d.get("reconciled_at")),
                    added=(
                        d.get("added")
                        or d.get("threads_added")
                        or d.get("convs_added")
                        or 0
                    ),
                    updated=(
                        d.get("updated")
                        or d.get("threads_updated")
                        or d.get("convs_updated")
                        or 0
                    ),
                    copied=(
                        d.get("copied")
                        or d.get("threads_copied")
                        or d.get("convs_copied")
                        or 0
                    ),
                    preserved_missing=(
                        d.get("preserved_missing")
                        or d.get("threads_preserved_missing")
                        or d.get("convs_preserved_missing")
                        or 0
                    ),
                    warnings_count=len(d.get("warnings") or []),
                )
            )
    return runs


def _collect_logs(base: Optional[Path], filename: str) -> list[Path]:
    """Coleta logs do nome filename. Suporta layout flat (`base/filename`) E
    multi-account (`base/account-*/filename`). Multi-account vira agregado."""
    if base is None or not base.exists():
        return []
    direct = base / filename
    if direct.exists():
        return [direct]
    # Multi-account: rglob limitado a 1 nivel (subpastas direto)
    paths = []
    for sub in base.iterdir():
        if sub.is_dir():
            cand = sub / filename
            if cand.exists():
                paths.append(cand)
    return sorted(paths)


def load_platform_state(name: str) -> PlatformState:
    raw_dir = DATA_RAW / name
    merged_dir = DATA_MERGED / name
    processed_dir = DATA_PROCESSED / name
    raw_dir = raw_dir if raw_dir.exists() else None
    merged_dir = merged_dir if merged_dir.exists() else None
    processed_dir = processed_dir if processed_dir.exists() else None

    capture_runs: list[CaptureRun] = []
    for p in _collect_logs(raw_dir, "capture_log.jsonl"):
        capture_runs.extend(_load_capture_log(p))
    capture_runs.sort(key=lambda r: r.started_at or datetime.min.replace(tzinfo=timezone.utc))

    reconcile_runs: list[ReconcileRun] = []
    for p in _collect_logs(merged_dir, "reconcile_log.jsonl"):
        reconcile_runs.extend(_load_reconcile_log(p))
    reconcile_runs.sort(key=lambda r: r.reconciled_at or datetime.min.replace(tzinfo=timezone.utc))

    return PlatformState(
        name=name,
        raw_dir=raw_dir,
        merged_dir=merged_dir,
        processed_dir=processed_dir,
        capture_runs=capture_runs,
        reconcile_runs=reconcile_runs,
        accounts=discover_accounts(
            name,
            storage_root=STORAGE_ROOT,
            raw_root=DATA_RAW,
            merged_root=DATA_MERGED,
            external_root=DATA_EXTERNAL,
            registry_path=STORAGE_ROOT / "accounts.json",
        ),
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
