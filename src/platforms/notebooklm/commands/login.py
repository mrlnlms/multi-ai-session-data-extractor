"""Thin wrapper pra login NotebookLM com profile persistente.

Contas ativas definidas pelo extractor. A conta historica inacessivel e
preservada por snapshots e nao requer login.
"""

import argparse
import asyncio

from src.platforms.notebooklm.extractor.auth import login, VALID_ACCOUNTS


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True, choices=list(VALID_ACCOUNTS))
    args = parser.parse_args()
    asyncio.run(login(args.account))
