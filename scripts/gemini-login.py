"""Abre browser com perfil persistente pra login no Gemini.

Uso: python scripts/gemini-login.py [--account 2]
Faz login, fecha o browser. Perfil salvo em .storage/gemini-profile-{N}/.

Para 2 contas Gmail, rode uma vez pra cada:
  python scripts/gemini-login.py --account 1
  python scripts/gemini-login.py --account 2
"""

import argparse
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright


def get_profile_dir(account: int) -> str:
    return f".storage/gemini-profile-{account}"


async def login(account: int):
    profile_dir = get_profile_dir(account)
    Path(profile_dir).mkdir(parents=True, exist_ok=True)

    print(f"Abrindo browser (conta {account})...")
    print("Faca login no Gemini e feche o browser quando terminar.")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            profile_dir,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        await page.goto("https://gemini.google.com/app", timeout=0)

        await context.wait_for_event("close", timeout=0)

    print(f"Browser fechado. Sessao da conta {account} salva!")
    print(f"Agora rode: python scripts/gemini-export.py --account {account}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", type=int, default=1, choices=[1, 2])
    args = parser.parse_args()
    asyncio.run(login(args.account))
