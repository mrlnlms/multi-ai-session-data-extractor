"""Script one-shot pra inspecionar DOM do voice mode do ChatGPT.

Objetivo: capturar HTML + classes CSS de uma conv voice real, pra derivar
seletores estaveis pra dom_voice.py.

Uso:
    python scripts/dev/inspect-chatgpt-voice-dom.py <conv_id>

Requer login persistente via scripts/chatgpt-login.py antes.

Output:
    - tests/extractors/chatgpt/fixtures/voice_bubble.html (HTML da timeline)
    - logs no terminal com classes CSS dos elementos relevantes
"""

import argparse
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from src.extractors.chatgpt.auth import get_profile_dir

FIXTURE_PATH = Path("tests/extractors/chatgpt/fixtures/voice_bubble.html")


async def inspect(conv_id: str):
    profile_dir = get_profile_dir()
    if not profile_dir.exists():
        print("ERRO: profile nao encontrado. Rode 'python scripts/chatgpt-login.py' primeiro.")
        sys.exit(1)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
        )
        page = await context.new_page()
        url = f"https://chatgpt.com/c/{conv_id}"
        print(f"Navegando pra {url}...")
        await page.goto(url, wait_until="domcontentloaded")

        await page.wait_for_selector("[data-message-author-role]", timeout=30000)
        print("Timeline carregou. Aguardando mais 5s pra lazy loading...")
        await page.wait_for_timeout(5000)

        # Scroll to top pra garantir todas msgs carregadas
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(2000)

        # Extrair HTML da area de mensagens
        html = await page.evaluate("""() => {
            const main = document.querySelector('main');
            return main ? main.outerHTML : document.body.innerHTML;
        }""")

        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_text(html, encoding="utf-8")
        print(f"HTML salvo em {FIXTURE_PATH}")

        # Log classes CSS dos elementos relevantes
        print("\n=== Classes CSS de interesse ===")
        classes = await page.evaluate("""() => {
            const result = {};
            const containers = document.querySelectorAll('[data-message-author-role]');
            result.num_messages = containers.length;
            result.sample_container_classes = containers.length > 0 ? containers[0].className : null;

            // Procura icones/svgs que podem ser mic
            const svgs = document.querySelectorAll('svg');
            result.sample_svg_classes = Array.from(svgs).slice(0, 5).map(s => s.getAttribute('class'));

            // Aria labels
            const ariaElements = document.querySelectorAll('[aria-label]');
            result.sample_aria_labels = Array.from(ariaElements).slice(0, 10).map(e => e.getAttribute('aria-label'));

            return result;
        }""")
        for k, v in classes.items():
            print(f"  {k}: {v}")

        print("\nAbra o HTML no browser ou editor e identifique:")
        print("  - Seletor CSS do balao de mensagem")
        print("  - Seletor CSS do icone de microfone")
        print("  - Seletor CSS do tempo (ex: '00:08')")
        print("  - Seletor CSS do texto da mensagem")
        print("\nPopule SELECTORS em src/extractors/chatgpt/dom_voice.py com esses valores.\n")

        await context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("conv_id", help="ID de uma conv com voice mode confirmado")
    args = parser.parse_args()
    asyncio.run(inspect(args.conv_id))
