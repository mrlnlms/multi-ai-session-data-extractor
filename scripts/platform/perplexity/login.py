"""Abre browser com perfil persistente pra login no Perplexity.

Uso: PYTHONPATH=. .venv/bin/python scripts/platform/perplexity/login.py [--account account-2]
Faz login, fecha o browser. Cada conta usa seu proprio perfil em `.storage/`.
"""

import argparse
import asyncio

from src.extractors.perplexity.auth import login


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", default="default")
    args = parser.parse_args()
    asyncio.run(login(args.account))
