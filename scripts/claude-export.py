"""Capture incremental do Claude.ai (convs + projects).

Modo default: incremental (re-fetcha so convs com updated_at novo).
Flags:
  --full           re-fetch tudo (ignora cutoff)
  --smoke N        fetcha so N convs (pra smoke test)
  --profile NAME   profile Playwright (default='default')
"""

import argparse
import asyncio

from src.extractors.claude_ai.orchestrator import run_export


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export Claude.ai (convs + projects)")
    parser.add_argument("--full", action="store_true", help="Re-fetch tudo")
    parser.add_argument("--smoke", type=int, default=None, help="Smoke: limita N convs")
    parser.add_argument("--profile", default="default")
    args = parser.parse_args()

    asyncio.run(run_export(profile_name=args.profile, full=args.full, smoke_limit=args.smoke))
