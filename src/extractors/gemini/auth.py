"""Playwright login persistente pra Gemini.

Pattern espelha chatgpt/claude_ai auth — launch_persistent_context mantem cookies.

Multi-account: profile por conta em .storage/gemini-profile-{N}/.
"""

from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext


def get_profile_dir(account: int = 1) -> Path:
    return Path(f".storage/gemini-profile-{account}")


async def login(account: int = 1) -> None:
    """Abre browser com profile persistente, espera usuario logar e fechar."""
    profile_dir = get_profile_dir(account)
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"Abrindo browser (conta {account})...")
    print("Faca login no Gemini e feche o browser quando terminar.")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        await page.goto("https://gemini.google.com/app", timeout=0)
        await context.wait_for_event("close", timeout=0)

    print(f"Browser fechado. Sessao da conta {account} salva em {profile_dir}")
    print(f"Agora rode: python scripts/gemini-export.py --account {account}")


async def load_context(account: int = 1, headless: bool = True) -> BrowserContext:
    """Carrega context persistente autenticado pra uso pelo api_client."""
    profile_dir = get_profile_dir(account)
    if not profile_dir.exists():
        raise RuntimeError(
            f"Profile nao existe: {profile_dir}. Rode scripts/gemini-login.py --account {account}"
        )
    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        str(profile_dir),
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
    )
    return context
