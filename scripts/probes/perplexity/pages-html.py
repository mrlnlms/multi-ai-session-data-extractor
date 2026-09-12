"""Procura slugs de Pages no HTML do Bookmarks (sabemos que estao la
porque os titles aparecem). Investiga formatos escapados, JSON inline,
tags <script>, etc."""

import asyncio
import re
from src.extractors.perplexity.auth import load_context

BOOKMARKS_SLUG = "bookmarks-9XLOIIv8SZeZI.gC9.47Ww"
KNOWN_HASH = "SYcH2HZjQH6FQyly7e8keA"  # hash final do slug "Brain Stores Memories"


async def main():
    ctx = await load_context(headless=False)
    page = await ctx.new_page()
    await page.goto(f"https://www.perplexity.ai/spaces/{BOOKMARKS_SLUG}", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(8000)
    html = await page.content()
    print(f"HTML len: {len(html)}")

    # 1. Procurar o hash conhecido (SYcH2HZj) em qualquer formato
    locations = [m.start() for m in re.finditer(re.escape(KNOWN_HASH), html)]
    print(f"\n'{KNOWN_HASH}' encontrado em {len(locations)} lugares")
    for loc in locations[:3]:
        chunk = html[max(0, loc-150):loc+200]
        print(f"  [@{loc}] ...{chunk!r}...")
        print()

    # 2. Procurar todos os tokens base64-like com hifen no fim (slug completo)
    matches = re.findall(r'([a-z0-9-]{10,80}-[a-zA-Z0-9_]{20,28})\b', html)
    unique = sorted(set(matches))
    page_like = [m for m in unique if any(k in m.lower() for k in ["brain", "microplastic", "teens", "startup"])]
    print(f"\nTokens slug-like encontrados: {len(unique)} unicos, {len(page_like)} contem palavras chave")
    for m in page_like:
        print(f"  {m}")

    # 3. Procurar em <script> tags inline
    scripts = re.findall(r'<script[^>]*>(.+?)</script>', html, re.DOTALL)
    print(f"\n<script> tags inline: {len(scripts)}")
    for i, s in enumerate(scripts):
        if KNOWN_HASH in s or any(k in s for k in ["brain-stores", "Brain Stores"]):
            print(f"\n  Script #{i} (len={len(s)}) tem dado de page:")
            idx = s.find(KNOWN_HASH) if KNOWN_HASH in s else s.find("brain-stores")
            print(f"  Trecho: ...{s[max(0,idx-200):idx+300]!r}...")

    # 4. Tentar via page.evaluate - pegar de window.__NEXT_DATA__ ou React props
    try:
        next_data = await page.evaluate(
            """() => {
                const el = document.getElementById('__NEXT_DATA__');
                return el ? el.textContent.slice(0, 5000) : null;
            }"""
        )
        if next_data:
            print(f"\n__NEXT_DATA__ existe! len={len(next_data)}")
            if KNOWN_HASH in next_data:
                idx = next_data.find(KNOWN_HASH)
                print(f"  hash encontrado em __NEXT_DATA__: ...{next_data[max(0,idx-100):idx+200]}...")
        else:
            print("\n__NEXT_DATA__ NAO existe (esperado pra app RSC)")
    except Exception as e:
        print(f"\nerr next_data: {e}")

    # 5. Tentar via DOM: pegar o atributo `<a href>` ou onclick que leva a /page/
    page_links = await page.evaluate(
        """() => {
            const all = Array.from(document.querySelectorAll('a'));
            return all.filter(a => a.href.includes('/page/')).map(a => ({
                href: a.href, text: a.innerText.slice(0, 80), html: a.outerHTML.slice(0, 200)
            }));
        }"""
    )
    print(f"\n<a> com /page/ no DOM (via JS, nao HTML): {len(page_links)}")
    for l in page_links:
        print(f"  href={l['href']!r}")
        print(f"    text={l['text']!r}")

    await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
