"""Inspeciona profundamente a row inteira de uma Page no Bookmarks
pra achar onde fica o slug/identifier (data-attribute, key, etc).
Tambem dispara fetch programatico do <a> via JS pra ver se ha onClick."""

import asyncio
import re
from src.extractors.perplexity.auth import load_context

BOOKMARKS_SLUG = "bookmarks-9XLOIIv8SZeZI.gC9.47Ww"


async def main():
    ctx = await load_context(headless=False)
    page = await ctx.new_page()
    await page.goto(f"https://www.perplexity.ai/spaces/{BOOKMARKS_SLUG}", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(8000)

    # Scroll pra forcar render
    await page.evaluate("window.scrollTo(0, 200)")
    await page.wait_for_timeout(1000)

    # 1. Inspecionar row inteira de uma page
    info = await page.evaluate(
        """() => {
            // Acha o icone de page e sobe pra row
            const svgs = Array.from(document.querySelectorAll('svg'));
            const pageSvgs = svgs.filter(s => {
                const use = s.querySelector('use');
                return use && use.getAttribute('xlink:href') === '#pplx-icon-custom-perplexity-page';
            });

            return pageSvgs.map(svg => {
                const row = svg.closest('[role="row"]');
                if (!row) return null;
                // Pega outerHTML ate 4000 chars
                const outerHTML = row.outerHTML.slice(0, 4000);
                // Pega todos atributos da row
                const rowAttrs = {};
                for (const a of row.attributes) rowAttrs[a.name] = a.value;
                // Pega atributos dos descendentes (data-*, id, key)
                const descAttrs = [];
                row.querySelectorAll('*').forEach(el => {
                    for (const a of el.attributes) {
                        if (a.name.startsWith('data-') || a.name === 'id' || a.name === 'key') {
                            descAttrs.push({tag: el.tagName, name: a.name, value: a.value});
                        }
                    }
                });
                // Pega texto do title pra identificar
                const title = (row.querySelector('.text-sm.text-foreground') || {}).textContent || '';
                return {title: title.slice(0, 60), rowAttrs, descAttrs: descAttrs.slice(0, 30), outerHTML};
            }).filter(x => x);
        }"""
    )
    print(f"Pages encontradas: {len(info)}\n")
    for i, p in enumerate(info):
        print(f"=== Page #{i}: {p['title']!r} ===")
        print(f"Row attrs: {p['rowAttrs']}")
        print(f"Desc attrs ({len(p['descAttrs'])}):")
        for a in p['descAttrs']:
            print(f"  {a['tag']}.{a['name']}={a['value'][:80]!r}")
        # Procurar slug pattern no outerHTML
        slugs = re.findall(r'/page/([a-zA-Z0-9\-]+)', p['outerHTML'])
        print(f"slugs no outerHTML: {slugs}")
        # Procurar UUIDs
        uuids = re.findall(r'\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b', p['outerHTML'])
        print(f"uuids no outerHTML: {set(uuids)}")
        print()

    # 2. Listar EventListeners via DevTools API (Chromium)
    # Tenta cdp session
    print("=== Tentando interceptar router via window.next.router ou similar ===")
    try:
        router_info = await page.evaluate(
            """() => {
                const keys = [];
                if (window.__NEXT_ROUTER) keys.push('__NEXT_ROUTER');
                if (window.__NEXT_DATA__) keys.push('__NEXT_DATA__');
                if (window.next) keys.push('next');
                if (window.__remixContext) keys.push('__remixContext');
                if (window.__staticRouterHydrationData) keys.push('__staticRouterHydrationData');
                // Procura algo com 'router' ou 'page' no global
                const globals = Object.keys(window).filter(k => /router|page|article/i.test(k));
                return {found_keys: keys, globals_with_match: globals.slice(0, 30)};
            }"""
        )
        print(f"  Globais relevantes: {router_info}")
    except Exception as e:
        print(f"  err: {e}")

    await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
