"""Export Gemini via API batchexecute (substitui o scraper DOM antigo).

Uso: PYTHONPATH=. .venv/bin/python -m src.platforms.gemini.commands.export --account 1 [--full] [--smoke N]

Modo default: incremental — compara created_at_secs com dump anterior.
"""

import argparse
import asyncio
from src.accounts import capturable_account_key

from src.platforms.gemini.extractor.orchestrator import run_export


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", type=capturable_account_key, default="1")
    parser.add_argument("--full", action="store_true", help="Re-fetch tudo")
    parser.add_argument("--smoke", type=int, default=None, help="Smoke: limita N convs")
    args = parser.parse_args()

    asyncio.run(run_export(
        account=args.account, full=args.full, smoke_limit=args.smoke
    ))
