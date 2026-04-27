"""Playwright login persistente pra ChatGPT.

Pattern espelha scripts/gemini-login.py — launch_persistent_context mantem
cookies no profile, login feito 1x dura ate expirar no servidor.
"""

from pathlib import Path

from playwright.async_api import async_playwright


def get_profile_dir(profile_name: str = "default") -> Path:
    """Path do diretorio de profile pra esse account."""
    return Path(f".storage/chatgpt-profile-{profile_name}")


async def login(profile_name: str = "default") -> None:
    """Abre browser com profile persistente, espera usuario logar e fechar."""
    profile_dir = get_profile_dir(profile_name)
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"Abrindo browser (profile={profile_name})...")
    print("Faca login no ChatGPT e feche o browser quando terminar.")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        await page.goto("https://chatgpt.com", timeout=0)

        await context.wait_for_event("close", timeout=0)

    print(f"Browser fechado. Sessao salva em {profile_dir}")
    print("Agora rode: python scripts/chatgpt-export.py")
