"""Probe se Pages vem via SSR (server-side rendered no HTML inicial)
ou se ha algum endpoint XHR que ainda nao mapeei."""

import asyncio
import re
from src.extractors.perplexity.auth import load_context

BOOKMARKS_SLUG = "bookmarks-9XLOIIv8SZeZI.gC9.47Ww"
PAGES_TITLES = [
    "Brain Stores Memories",
    "Microplastics Found",
    "Teens Invent",
    "Startup Turns Air",
]


async def main():
    context = await load_context(headless=False)
    page = await context.new_page()
    print("Abrindo Bookmarks space...", flush=True)
    await page.goto(f"https://www.perplexity.ai/spaces/{BOOKMARKS_SLUG}", wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(5000)

    html = await page.content()
    print(f"HTML len: {len(html)}")
    for t in PAGES_TITLES:
        idx = html.find(t)
        if idx >= 0:
            print(f"  ACHADO no HTML: {t!r} (idx={idx})")
            print(f"    contexto: ...{html[max(0,idx-150):idx+250]}...")
        else:
            print(f"  NAO encontrado: {t!r}")

    # Procurar __NEXT_DATA__ (Next.js SSR payload)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if m:
        next_data = m.group(1)
        print(f"\n__NEXT_DATA__ found, len={len(next_data)}")
        for t in PAGES_TITLES:
            if t in next_data:
                print(f"  ACHADO em __NEXT_DATA__: {t!r}")

    await context.close()


if __name__ == "__main__":
    asyncio.run(main())
