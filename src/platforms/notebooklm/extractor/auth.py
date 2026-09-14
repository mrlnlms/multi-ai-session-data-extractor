"""Playwright login persistente pra NotebookLM.

Suporta multiplas contas via sufixo (account-1, account-2, etc). Cada conta
tem profile persistente em .storage/notebooklm-profile-<N>/ gerado via
``python -m src.platforms.notebooklm.commands.login``.
"""

from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext

from src.account_catalog import validate_technical_key
from src.accounts import account_keys


VALID_ACCOUNTS = account_keys("NotebookLM")

# Lang (hl param) por conta — afeta labels em metadata de RPCs (ex: "Deep Dive" vs "Aprofundar").
# Conteudo do user (chat, notes, source text) eh na lingua que foi escrito, independente do hl.
ACCOUNT_LANG = {
    "1": "en",
    "2": "pt-BR",
    "3": "pt-BR",
}


def get_profile_dir(account: str) -> Path:
    account = validate_technical_key(account, allow_archive=False)
    return Path(f".storage/notebooklm-profile-{account}")


async def login(account: str) -> None:
    profile_dir = get_profile_dir(account)
    profile_dir.mkdir(parents=True, exist_ok=True)
    print(f"Abrindo browser (conta {account})...")
    print("Faca login no NotebookLM e feche o browser quando terminar.")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            channel="chrome",  # Chrome real, evita bloqueio Google
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        await page.goto("https://notebooklm.google.com/", timeout=0)
        await context.wait_for_event("close", timeout=0)

    print(f"Sessao da conta {account} salva em {profile_dir}")


async def load_context(account: str, headless: bool = True) -> BrowserContext:
    profile_dir = get_profile_dir(account)
    if not profile_dir.exists():
        raise RuntimeError(
            f"Profile nao existe: {profile_dir}. "
            f"Rode python -m src.platforms.notebooklm.commands.login --account {account}"
        )
    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        str(profile_dir),
        headless=headless,
        channel="chrome",
        args=["--disable-blink-features=AutomationControlled"],
    )
    return context
