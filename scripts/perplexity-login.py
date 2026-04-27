"""Abre browser com perfil persistente pra login no Perplexity.

Uso: python scripts/perplexity-login.py
Faz login, fecha o browser. Perfil salvo em .storage/perplexity-profile/.
"""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

PROFILE_DIR = ".storage/perplexity-profile"


async def login():
    Path(PROFILE_DIR).mkdir(parents=True, exist_ok=True)

    print("Abrindo browser... Faca login no Perplexity e feche o browser quando terminar.")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        await page.goto("https://www.perplexity.ai/", timeout=0)

        # Espera usuario fechar o browser
        await context.wait_for_event("close", timeout=0)

    print("Browser fechado. Sessao salva! Agora rode: python scripts/perplexity-export.py")


if __name__ == "__main__":
    asyncio.run(login())
