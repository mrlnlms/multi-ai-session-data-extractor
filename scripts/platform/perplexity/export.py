"""Export Perplexity via /rest/ API.

IMPORTANTE: default e headless=False (janela visivel) porque Cloudflare challenge
bloqueia headless. Use --headless se quiser tentar em bg (provavelmente falha).

Uso: python scripts/perplexity-export.py [--full] [--smoke N] [--headless]
"""

import argparse
import asyncio

from src.extractors.perplexity.orchestrator import run_export


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--smoke", type=int, default=None)
    parser.add_argument("--account", type=str, default="default")
    parser.add_argument("--headless", action="store_true",
                        help="Tenta headless (geralmente falha por Cloudflare)")
    args = parser.parse_args()
    asyncio.run(run_export(
        full=args.full, smoke_limit=args.smoke,
        account=args.account, headless=args.headless,
    ))
