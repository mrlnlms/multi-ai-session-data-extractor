"""Login persistente Qwen (1x por profile).

Uso: python scripts/qwen-login.py
"""

import argparse
import asyncio

from src.extractors.qwen.auth import login


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", type=str, default="default")
    args = parser.parse_args()
    asyncio.run(login(args.account))
