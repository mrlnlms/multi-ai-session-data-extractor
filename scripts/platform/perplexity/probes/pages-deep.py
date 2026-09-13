"""Inspecao profunda do DOM em volta dos pages do Bookmarks pra
descobrir o seletor/atributo que liga ao recurso da page."""

import asyncio
import json
import re
from src.extractors.perplexity.auth import load_context

BOOKMARKS_SLUG = "bookmarks-9XLOIIv8SZeZI.gC9.47Ww"


async def main():
    ctx = await load_context(headless=False)
    page = await ctx.new_page()
    await page.goto(f"https://www.perplexity.ai/spaces/{BOOKMARKS_SLUG}", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(8000)

    # Pega o HTML inteiro e procura por estrutura em volta de cada page title
    html = await page.content()
    print(f"HTML len: {len(html)}\n")

    titles = ["Brain Stores Memories", "Microplastics Found", "Teens Invent", "Startup Turns Air"]
    for t in titles:
        idx = html.find(t)
        if idx < 0:
            continue
        # Pega 800 chars antes e 200 depois pra ver estrutura
        start = max(0, idx - 800)
        end = min(len(html), idx + 200)
        chunk = html[start:end]
        # Procurar atributos potencialmente uteis: href, data-*, id
        hrefs = re.findall(r'href="([^"]+)"', chunk)
        data_attrs = re.findall(r'(data-[a-z\-]+)="([^"]+)"', chunk)
        ids = re.findall(r' id="([^"]+)"', chunk)
        print(f"=== {t!r} ===")
        print(f"  hrefs in window: {hrefs[-5:]}")
        print(f"  data-attrs in window: {data_attrs[-10:]}")
        print(f"  ids in window: {ids[-5:]}")
        # Mostra os 400 chars antes do titulo
        print(f"  chunk antes ({chunk[:400]!r})")
        print()

    # Estrategia alternativa: clicar num row de Page e ver pra onde leva
    print("=== Tentando clicar no row 'Brain Stores Memories' ===")
    try:
        await page.get_by_text("Brain Stores Memories", exact=False).first.click(timeout=5000)
        await page.wait_for_timeout(3000)
        new_url = page.url
        print(f"  Nova URL apos click: {new_url}")
    except Exception as e:
        print(f"  click falhou: {e}")

    await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
