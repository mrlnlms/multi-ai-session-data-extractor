"""Playwright login persistente pra Claude.ai.

Pattern espelha src/extractors/chatgpt/auth.py — launch_persistent_context mantem
cookies no profile, login feito 1x dura ate expirar no servidor.

org_id (cookie lastActiveOrg) e extraido lazy pelo load_context() quando
precisar, e cached em {profile}/org_id.txt.
"""

from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext


def get_profile_dir(profile_name: str = "default") -> Path:
    """Path do diretorio de profile pra esse account."""
    return Path(f".storage/claude-ai-profile-{profile_name}")


async def _extract_org_id(context: BrowserContext) -> str | None:
    """Extrai org_id dos cookies da sessao (cookie lastActiveOrg)."""
    cookies = await context.cookies("https://claude.ai")
    for c in cookies:
        if c.get("name") == "lastActiveOrg":
            return c.get("value")
    return None


async def login(profile_name: str = "default") -> None:
    """Abre browser com profile persistente, espera usuario logar e fechar."""
    profile_dir = get_profile_dir(profile_name)
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"Abrindo browser (profile={profile_name})...")
    print("Faca login no Claude.ai e feche o browser quando terminar.")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        await page.goto("https://claude.ai", timeout=0)

        await context.wait_for_event("close", timeout=0)

    print(f"Browser fechado. Sessao salva em {profile_dir}")
    print("Agora rode: python scripts/claude-export.py")


async def load_context(profile_name: str = "default", headless: bool = True) -> tuple[BrowserContext, str]:
    """Carrega context persistente ja autenticado + retorna org_id.

    Usado pelo api_client pra fazer requests autenticados passando Cloudflare.
    Caller e responsavel por fechar o context (await context.close()).
    """
    profile_dir = get_profile_dir(profile_name)
    if not profile_dir.exists():
        raise RuntimeError(
            f"Profile nao existe: {profile_dir}. Rode scripts/claude-login.py primeiro."
        )

    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        str(profile_dir),
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
    )

    # org_id: tenta do cache, senao navega pra claude.ai e re-extrai dos cookies
    org_id_cache = profile_dir / "org_id.txt"
    if org_id_cache.exists():
        org_id = org_id_cache.read_text().strip()
    else:
        # Precisa dar um hit em claude.ai pra cookies aparecerem no context
        page = await context.new_page()
        await page.goto("https://claude.ai", wait_until="domcontentloaded", timeout=30000)
        org_id = await _extract_org_id(context)
        await page.close()
        if not org_id:
            await context.close()
            raise RuntimeError(
                "Nao foi possivel capturar org_id (cookie lastActiveOrg ausente). "
                "Faca login novamente: scripts/claude-login.py"
            )
        org_id_cache.write_text(org_id)

    return context, org_id
