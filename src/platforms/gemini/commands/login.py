"""Abre browser com perfil persistente pra login no Gemini.

Uso: PYTHONPATH=. .venv/bin/python -m src.platforms.gemini.commands.login [--account 2]
Faz login, fecha o browser. Perfil salvo em .storage/gemini-profile-{N}/.

Para cada conta Google, rode uma vez com seu numero:
  PYTHONPATH=. .venv/bin/python -m src.platforms.gemini.commands.login --account 1
  PYTHONPATH=. .venv/bin/python -m src.platforms.gemini.commands.login --account 2
  PYTHONPATH=. .venv/bin/python -m src.platforms.gemini.commands.login --account 3
"""

import argparse
import asyncio

from src.accounts import capturable_account_key
from src.platforms.gemini.extractor.auth import get_profile_dir, login


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", type=capturable_account_key, default="1")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    asyncio.run(login(args.account))
