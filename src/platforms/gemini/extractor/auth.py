"""Playwright login persistente pra Gemini.

Pattern espelha chatgpt/claude_ai auth — launch_persistent_context mantem cookies.

Multi-account: cada chave usa seu diretorio legado ate ser associada a um
grupo de navegador compartilhado.
"""

from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext

from src.account_catalog import validate_technical_key
from src.accounts import account_keys
from src.browser_profile_runtime import launch_persistent_profile, resolve_platform_browser_target


VALID_ACCOUNTS = account_keys("Gemini")


def get_profile_dir(account: str = "1") -> Path:
    account = validate_technical_key(str(account), allow_archive=False)
    return resolve_platform_browser_target(
        "Gemini", account, legacy_path=Path(f".storage/gemini-profile-{account}"),
    ).path


async def login(account: str = "1") -> None:
    """Abre browser com profile persistente, espera usuario logar e fechar."""
    profile_dir = get_profile_dir(account)
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"Abrindo browser (conta {account})...")
    print("Faca login no Gemini e feche o browser quando terminar.")

    async with async_playwright() as p:
        context = await launch_persistent_profile(p,
            str(profile_dir),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        await page.goto("https://gemini.google.com/app", timeout=0)
        await context.wait_for_event("close", timeout=0)

    print(f"Browser fechado. Sessao da conta {account} salva em {profile_dir}")
    print(f"Agora rode: PYTHONPATH=. .venv/bin/python -m src.platforms.gemini.commands.export --account {account}")


async def load_context(account: str = "1", headless: bool = True) -> BrowserContext:
    """Carrega context persistente autenticado pra uso pelo api_client."""
    profile_dir = get_profile_dir(account)
    if not profile_dir.exists():
        raise RuntimeError(
            f"Profile nao existe: {profile_dir}. Rode python -m src.platforms.gemini.commands.login --account {account}"
        )
    pw = await async_playwright().start()
    context = await launch_persistent_profile(pw,
        str(profile_dir),
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
    )
    return context
