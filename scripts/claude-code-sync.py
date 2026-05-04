"""Sync Claude Code — copy + parse + log em 1 comando.

Etapas:
    1. Copy:  ~/.claude/projects/ → data/raw/Claude Code/ (incremental)
    2. Parse: data/raw/Claude Code/ → data/processed/Claude Code/
    3. Log:   capture_log.jsonl per-source pra dashboard detectar last sync

Idempotente. Uso: PYTHONPATH=. .venv/bin/python scripts/claude-code-sync.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.cli.copy import copy_source as _copy_source
from src.parsers.claude_code import ClaudeCodeParser

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "Claude Code"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed" / "Claude Code"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true",
                    help="Forca re-parse mesmo sem arquivos novos (CLIs nao re-copiam — sem servidor pra refetch)")
    ap.add_argument("--no-binaries", action="store_true",
                    help="(no-op pra CLI: dado eh local, sem assets binarios separados)")
    ap.add_argument("--no-reconcile", action="store_true",
                    help="(no-op pra CLI: preservation eh implicita no cli-copy — nao deleta destino)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Lista o que seria copiado sem copiar nem parsear")
    args = ap.parse_args()

    started_at = datetime.now(timezone.utc)

    if args.dry_run:
        print("=" * 60)
        print("  Dry-run — Claude Code (copy + parse pulados)")
        print("=" * 60)
        from src.extractors.cli.copy import SOURCES
        cfg = SOURCES["claude_code"]
        src = cfg["src"]
        n_in_source = sum(1 for _ in src.rglob("*.jsonl")) if src.exists() else 0
        n_in_dst = sum(1 for _ in RAW_DIR.rglob("*.jsonl"))
        print(f"  source ({src}): {n_in_source} JSONLs")
        print(f"  destino ({RAW_DIR}): {n_in_dst} JSONLs")
        return 0

    print("=" * 60)
    print("  Etapa 1/2 — Copy ~/.claude/projects/ → data/raw/Claude Code/")
    print("=" * 60)
    copy_result = _copy_source("claude_code")
    n_new = len(copy_result["new"])
    n_upd = len(copy_result["updated"])

    print()
    print("=" * 60)
    print("  Etapa 2/2 — Parse → data/processed/Claude Code/")
    print("=" * 60)
    parser = ClaudeCodeParser()
    parser.parse(RAW_DIR)
    stats = parser.write_parquets(PROCESSED_DIR)

    finished_at = datetime.now(timezone.utc)
    duration = (finished_at - started_at).total_seconds()

    log_entry = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": duration,
        "totals": {
            "files_new": n_new,
            "files_updated": n_upd,
            "conversations": stats["conversations"],
            "messages": stats["messages"],
            "tool_events": stats["tool_events"],
            "branches": stats["branches"],
        },
    }
    log_path = RAW_DIR / "capture_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

    print()
    print("=== STATS ===")
    for k, v in stats.items():
        print(f"  {k}: {v:,}")
    print(f"  duration: {duration:.1f}s, files: {n_new} new + {n_upd} updated")
    print(f"\nParquets em: {PROCESSED_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
