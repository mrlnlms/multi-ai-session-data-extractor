"""Playwright login persistente pra Perplexity.

Cada conta usa o diretorio legado em `.storage/` ate ser associada a um grupo.
"""

from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext
from src.browser_profile_runtime import launch_persistent_profile, resolve_platform_browser_target


HOME_URL = "https://www.perplexity.ai/"


def get_profile_dir(account: str = "default") -> Path:
    # The default account keeps the historical unsuffixed profile path.
    # Se o user ja rodou o login antigo, aproveita.
    if account == "default":
        legacy = Path(".storage/perplexity-profile")
        if legacy.exists():
            return resolve_platform_browser_target(
                "Perplexity", account, legacy_path=legacy, legacy_channel="chrome",
            ).path
    return resolve_platform_browser_target(
        "Perplexity", account, legacy_path=Path(f".storage/perplexity-profile-{account}"),
        legacy_channel="chrome",
    ).path


async def login(account: str = "default") -> None:
    profile_dir = get_profile_dir(account)
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"Abrindo browser (Perplexity, profile={account})...")
    print("Faca login em perplexity.ai e feche o browser quando terminar.")

    async with async_playwright() as p:
        context = await launch_persistent_profile(p,
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
            f"Profile nao existe: {profile_dir}. Rode python -m src.platforms.perplexity.commands.login"
        )
    pw = await async_playwright().start()
    context = await launch_persistent_profile(pw,
        str(profile_dir),
        headless=headless,
        channel="chrome",
        args=["--disable-blink-features=AutomationControlled"],
        ignore_https_errors=True,
        bypass_csp=True,
    )
    return context
