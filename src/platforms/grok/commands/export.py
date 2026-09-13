"""Captura conversas Grok.

Uso:
  PYTHONPATH=. .venv/bin/python -m src.platforms.grok.commands.export             # incremental
  PYTHONPATH=. .venv/bin/python -m src.platforms.grok.commands.export --full      # ignora estado anterior, refetcha tudo
  PYTHONPATH=. .venv/bin/python -m src.platforms.grok.commands.export --smoke 5   # apenas 5 convs (smoke test)
  PYTHONPATH=. .venv/bin/python -m src.platforms.grok.commands.export --headed    # abre browser visivel
"""

import argparse
import asyncio

from src.platforms.grok.extractor.orchestrator import run_export


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
