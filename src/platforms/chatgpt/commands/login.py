"""Thin command wrapper for the ChatGPT authentication flow."""

import argparse
import asyncio

from src.platforms.chatgpt.extractor.auth import login

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Login persistente no ChatGPT")
    parser.add_argument(
        "--profile",
        default="default",
        help="Nome do profile (default: 'default'). Use outros pra multiplas contas.",
    )
    args = parser.parse_args()
    asyncio.run(login(args.profile))
