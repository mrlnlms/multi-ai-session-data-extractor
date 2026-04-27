"""Export DeepSeek via API interna.

Uso: python scripts/deepseek-export.py [--full] [--smoke N]

Default: incremental (compara updated_at com dump anterior).
"""

import argparse
import asyncio

from src.extractors.deepseek.orchestrator import run_export


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="Re-fetch tudo")
    parser.add_argument("--smoke", type=int, default=None, help="Smoke: limita N convs")
    parser.add_argument("--account", type=str, default="default")
    args = parser.parse_args()

    asyncio.run(run_export(full=args.full, smoke_limit=args.smoke, account=args.account))
