"""Export NotebookLM via batchexecute API.

Uso:
    python scripts/notebooklm-export.py --account 1                        # todos
    python scripts/notebooklm-export.py --account 1 --notebook UUID        # só 1
    python scripts/notebooklm-export.py --account 1 --notebook UUID1,UUID2 # só esses
    python scripts/notebooklm-export.py --account 1 --smoke N              # primeiros N
"""

import argparse
import asyncio

from src.extractors.notebooklm.auth import VALID_ACCOUNTS
from src.extractors.notebooklm.orchestrator import run_export


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True, choices=list(VALID_ACCOUNTS))
    parser.add_argument("--notebook", default=None,
                        help="UUID(s) de notebook a fetchar (csv pra varios). Default: todos")
    parser.add_argument("--full", action="store_true", help="(Compat) ignora cutoff — orchestrator ja fetcha tudo por default")
    parser.add_argument("--smoke", type=int, default=None, help="Smoke test — limita N notebooks")
    args = parser.parse_args()

    only = None
    if args.notebook:
        only = {u.strip() for u in args.notebook.split(",") if u.strip()}

    asyncio.run(run_export(args.account, full=args.full, smoke_limit=args.smoke, only_notebooks=only))
