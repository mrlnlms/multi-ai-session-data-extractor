"""Sync Antigravity CLI — copy + parse + log em 1 comando."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.cli.copy import copy_source as _copy_source
from src.parsers.antigravity_cli import AntigravityCLIParser


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "Antigravity CLI"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed" / "Antigravity CLI"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--full", action="store_true", help="Forca re-parse sem descartar o raw preservado")
    ap.add_argument("--no-binaries", action="store_true", help="(no-op: containers locais sao preservados no raw)")
    ap.add_argument("--no-reconcile", action="store_true", help="(no-op: preservation e implicita na copia CLI)")
    ap.add_argument("--dry-run", action="store_true", help="Lista conversas e trajetorias sem copiar nem parsear")
    args = ap.parse_args()
    started_at = datetime.now(timezone.utc)

    if args.dry_run:
        from src.extractors.cli.copy import SOURCES
        src = SOURCES["antigravity_cli"]["src"]
        raw_containers = sum(1 for p in (src / "conversations").glob("*") if p.suffix in (".db", ".pb")) if src.exists() else 0
        trajectories = sum(1 for _ in (src / "brain").glob("*/.system_generated/logs/transcript.jsonl")) if src.exists() else 0
        print("=" * 60)
        print("  Dry-run — Antigravity CLI (copy + parse pulados)")
        print("=" * 60)
        print(f"  source ({src}): {raw_containers} containers, {trajectories} readable trajectories")
        print(f"  destino ({RAW_DIR}): {sum(1 for _ in RAW_DIR.glob('conversations/*')) if RAW_DIR.exists() else 0} containers")
        return 0

    print("=" * 60)
    print("  Etapa 1/2 — Copy ~/.gemini/antigravity-cli/ → data/raw/Antigravity CLI/")
    print("=" * 60)
    copy_result = _copy_source("antigravity_cli")

    print()
    print("=" * 60)
    print("  Etapa 2/2 — Parse trajectories → data/processed/Antigravity CLI/")
    print("=" * 60)
    parser = AntigravityCLIParser()
    parser.parse(RAW_DIR)
    stats = parser.write_parquets(PROCESSED_DIR)

    finished_at = datetime.now(timezone.utc)
    duration = (finished_at - started_at).total_seconds()
    log_entry = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": duration,
        "totals": {
            "files_new": len(copy_result["new"]),
            "files_updated": len(copy_result["updated"]),
            **stats,
        },
    }
    log_path = RAW_DIR / "capture_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

    print("\n=== STATS ===")
    for key, value in stats.items():
        print(f"  {key}: {value:,}")
    print(f"  duration: {duration:.1f}s, files: {len(copy_result['new'])} new + {len(copy_result['updated'])} updated")
    print(f"\nParquets em: {PROCESSED_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
