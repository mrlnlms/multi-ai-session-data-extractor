"""Playwright login persistente pra NotebookLM.

2 contas ativas: account-1 (en, original "hello") e account-2 (pt-BR, original
"marloon"). more.design foi perdida (raw antigo preservado no projeto pai).
"""

from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext


VALID_ACCOUNTS = ("1", "2")

# Lang (hl param) por conta — afeta labels em metadata de RPCs (ex: "Deep Dive" vs "Aprofundar").
# Conteudo do user (chat, notes, source text) eh na lingua que foi escrito, independente do hl.
ACCOUNT_LANG = {
    "1": "en",
    "2": "pt-BR",
}


def get_profile_dir(account: str) -> Path:
    if account not in VALID_ACCOUNTS:
        raise ValueError(f"Account invalido: {account!r}. Use um de {VALID_ACCOUNTS}")
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
            f"Rode scripts/notebooklm-login.py --account {account}"
        )
    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        str(profile_dir),
        headless=headless,
        channel="chrome",
        args=["--disable-blink-features=AutomationControlled"],
    )
    return context
