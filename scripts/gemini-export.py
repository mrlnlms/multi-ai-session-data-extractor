"""Export Gemini via API batchexecute (substitui o scraper DOM antigo).

Uso: python scripts/gemini-export.py --account 1 [--full] [--smoke N]

Modo default: incremental — compara created_at_secs com dump anterior.
"""

import argparse
import asyncio

from src.extractors.gemini.orchestrator import run_export


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", type=int, default=1, choices=[1, 2])
    parser.add_argument("--full", action="store_true", help="Re-fetch tudo")
    parser.add_argument("--smoke", type=int, default=None, help="Smoke: limita N convs")
    args = parser.parse_args()

    asyncio.run(run_export(
        account=args.account, full=args.full, smoke_limit=args.smoke
    ))
