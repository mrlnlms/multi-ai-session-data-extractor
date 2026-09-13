"""Login persistente Qwen (1x por profile).

Uso: PYTHONPATH=. .venv/bin/python -m src.platforms.qwen.commands.login
"""

import argparse
import asyncio

from src.platforms.qwen.extractor.auth import login


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", type=str, default="default")
    args = parser.parse_args()
    asyncio.run(login(args.account))
