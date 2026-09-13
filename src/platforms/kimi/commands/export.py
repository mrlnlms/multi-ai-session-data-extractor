"""Captura conversas Kimi.

Uso:
  PYTHONPATH=. .venv/bin/python -m src.platforms.kimi.commands.export             # incremental
  PYTHONPATH=. .venv/bin/python -m src.platforms.kimi.commands.export --full      # ignora estado anterior
  PYTHONPATH=. .venv/bin/python -m src.platforms.kimi.commands.export --smoke 3   # apenas 3 chats
  PYTHONPATH=. .venv/bin/python -m src.platforms.kimi.commands.export --headed
"""

import argparse
import asyncio

from src.platforms.kimi.extractor.orchestrator import run_export


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
