"""Thin wrapper pra login NotebookLM com profile persistente.

Contas ativas definidas pelo extractor. A conta historica inacessivel e
preservada por snapshots e nao requer login.
"""

import argparse
import asyncio
from src.accounts import capturable_account_key

from src.platforms.notebooklm.extractor.auth import login


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", type=capturable_account_key, required=True)
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    asyncio.run(login(args.account))
