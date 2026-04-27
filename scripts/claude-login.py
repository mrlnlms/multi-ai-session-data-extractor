"""Thin wrapper pra src/extractors/claude_ai/auth.py:login()."""

import argparse
import asyncio

from src.extractors.claude_ai.auth import login

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Login persistente no Claude.ai")
    parser.add_argument(
        "--profile",
        default="default",
        help="Nome do profile (default: 'default'). Use outros pra multiplas contas.",
    )
    args = parser.parse_args()
    asyncio.run(login(args.profile))
