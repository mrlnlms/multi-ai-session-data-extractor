"""Login persistente DeepSeek (1x por profile, expira depois de periodo grande).

Uso: PYTHONPATH=. .venv/bin/python scripts/platform/deepseek/login.py
"""

import argparse
import asyncio

from src.extractors.deepseek.auth import login


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", type=str, default="default")
    args = parser.parse_args()
    asyncio.run(login(args.account))
