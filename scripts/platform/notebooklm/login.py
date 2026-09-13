"""Thin wrapper pra login NotebookLM com profile persistente.

2 contas: 1 (en), 2 (pt-BR). more.design nao mais disponivel.
"""

import argparse
import asyncio

from src.extractors.notebooklm.auth import login, VALID_ACCOUNTS


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True, choices=list(VALID_ACCOUNTS))
    args = parser.parse_args()
    asyncio.run(login(args.account))
