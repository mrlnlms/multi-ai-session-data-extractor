"""Playwright login persistente pra ChatGPT.

Pattern espelha -m src.platforms.gemini.commands.login — launch_persistent_context mantem
cookies no profile, login feito 1x dura ate expirar no servidor.
"""

from pathlib import Path

from playwright.async_api import async_playwright
from src.browser_profile_runtime import launch_persistent_profile, resolve_platform_browser_target


def get_profile_dir(profile_name: str = "default") -> Path:
    """Path do diretorio de profile pra esse account."""
    return resolve_platform_browser_target(
        "ChatGPT", profile_name, legacy_path=Path(f".storage/chatgpt-profile-{profile_name}"),
    ).path


async def login(profile_name: str = "default") -> None:
    """Abre browser com profile persistente, espera usuario logar e fechar."""
    profile_dir = get_profile_dir(profile_name)
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"Abrindo browser (profile={profile_name})...")
    print("Faca login no ChatGPT e feche o browser quando terminar.")

    async with async_playwright() as p:
        context = await launch_persistent_profile(p,
            str(profile_dir),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        await page.goto("https://chatgpt.com", timeout=0)

        await context.wait_for_event("close", timeout=0)

    print(f"Browser fechado. Sessao salva em {profile_dir}")
    print("Agora rode: PYTHONPATH=. .venv/bin/python -m src.platforms.chatgpt.commands.export")
