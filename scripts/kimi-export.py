"""Captura conversas Kimi.

Uso:
  python scripts/kimi-export.py             # incremental
  python scripts/kimi-export.py --full      # ignora estado anterior
  python scripts/kimi-export.py --smoke 3   # apenas 3 chats
  python scripts/kimi-export.py --headed
"""

import argparse
import asyncio

from src.extractors.kimi.orchestrator import run_export


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--full", action="store_true")
    p.add_argument("--smoke", type=int, default=None)
    p.add_argument("--account", default="default")
    p.add_argument("--headed", action="store_true")
    args = p.parse_args()
    asyncio.run(
        run_export(
            full=args.full,
            smoke_limit=args.smoke,
            account=args.account,
            headless=not args.headed,
        )
    )
