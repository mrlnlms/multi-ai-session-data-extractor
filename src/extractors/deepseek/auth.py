"""Playwright login persistente pra DeepSeek.

Pattern espelha gemini/chatgpt — launch_persistent_context mantem cookies.
Single-account por enquanto (profile em .storage/deepseek-profile-default/).
"""

from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext


HOME_URL = "https://chat.deepseek.com/"


def get_profile_dir(account: str = "default") -> Path:
    return Path(f".storage/deepseek-profile-{account}")


async def login(account: str = "default") -> None:
    profile_dir = get_profile_dir(account)
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"Abrindo browser (DeepSeek, profile={account})...")
    print("Faca login em chat.deepseek.com e feche o browser quando terminar.")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
            ignore_https_errors=True,
            bypass_csp=True,
        )
        page = await context.new_page()
        await page.goto(HOME_URL, timeout=0)
        await context.wait_for_event("close", timeout=0)

    print(f"Sessao salva em {profile_dir}")


async def load_context(account: str = "default", headless: bool = True) -> BrowserContext:
    profile_dir = get_profile_dir(account)
    if not profile_dir.exists():
        raise RuntimeError(
            f"Profile nao existe: {profile_dir}. Rode scripts/deepseek-login.py"
        )
    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        str(profile_dir),
        headless=headless,
        channel="chrome",
        args=["--disable-blink-features=AutomationControlled"],
        ignore_https_errors=True,
        bypass_csp=True,
    )
    return context
