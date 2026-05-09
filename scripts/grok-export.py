"""Captura conversas Grok.

Uso:
  python scripts/grok-export.py             # incremental
  python scripts/grok-export.py --full      # ignora estado anterior, refetcha tudo
  python scripts/grok-export.py --smoke 5   # apenas 5 convs (smoke test)
  python scripts/grok-export.py --headed    # abre browser visivel
"""

import argparse
import asyncio

from src.extractors.grok.orchestrator import run_export


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--full", action="store_true", help="Refetcha tudo")
    p.add_argument("--smoke", type=int, default=None, help="Limita N convs")
    p.add_argument("--account", default="default")
    p.add_argument("--headed", action="store_true", help="Browser visivel")
    args = p.parse_args()
    asyncio.run(
        run_export(
            full=args.full,
            smoke_limit=args.smoke,
            account=args.account,
            headless=not args.headed,
        )
    )
