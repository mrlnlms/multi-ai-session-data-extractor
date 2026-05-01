"""Mapeia DOM de items dentro de um Space (Bookmarks) pra distinguir
threads de pages e descobrir como extrair URL/slug/uuid de cada page.

Output: /tmp/perplexity-pages-dom.json com lista de items + estrutura.
"""

import asyncio
import json
from pathlib import Path
from src.extractors.perplexity.auth import load_context

BOOKMARKS_SLUG = "bookmarks-9XLOIIv8SZeZI.gC9.47Ww"
OUTPUT = Path("/tmp/perplexity-pages-dom.json")


async def main():
    ctx = await load_context(headless=False)
    page = await ctx.new_page()
    await page.goto(f"https://www.perplexity.ai/spaces/{BOOKMARKS_SLUG}", wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(5000)

    # Estrategia: ler todos os <a> hrefs + texto dos rows na lista principal
    # Pages tem URL diferente de threads. /page/{slug} ou /search/{uuid}
    items = await page.evaluate(
        """() => {
            // Tenta achar a lista de items (tabela/grid de threads+pages)
            const rows = Array.from(document.querySelectorAll('[role="row"]'));
            const out = [];
            for (const r of rows) {
                const links = Array.from(r.querySelectorAll('a[href]'));
                const txt = r.innerText.replace(/\\s+/g, ' ').trim().slice(0, 200);
                const hrefs = links.map(a => a.getAttribute('href'));
                // tipo: presenca de label visivel "Deep research" / "Page"
                const labels = Array.from(r.querySelectorAll('span, div'))
                    .map(e => e.textContent.trim())
                    .filter(t => t === 'Deep research' || t === 'Page' || t === 'Pro' || t === 'Concise' || t === 'Copilot');
                out.push({ text: txt, hrefs, labels });
            }
            return out;
        }"""
    )
    print(f"Rows encontrados: {len(items)}")
    for i, it in enumerate(items[:20]):
        print(f"  [{i}] labels={it['labels']} hrefs={it['hrefs']} text={it['text'][:80]!r}")

    # Tambem tenta seletor mais especifico: links pra /page/ ou /search/
    page_links = await page.evaluate(
        """() => {
            const all = Array.from(document.querySelectorAll('a[href*="/page/"], a[href*="/search/"]'));
            return all.map(a => ({
                href: a.getAttribute('href'),
                text: a.innerText.replace(/\\s+/g, ' ').trim().slice(0, 200),
            }));
        }"""
    )
    print(f"\nLinks /page/ ou /search/: {len(page_links)}")
    pages_only = [l for l in page_links if '/page/' in l['href']]
    threads_only = [l for l in page_links if '/search/' in l['href']]
    print(f"  pages: {len(pages_only)}, threads: {len(threads_only)}")
    print("\n  Pages encontrados:")
    seen = set()
    for p in pages_only:
        if p['href'] in seen:
            continue
        seen.add(p['href'])
        print(f"    href={p['href']!r} text={p['text'][:80]!r}")

    OUTPUT.write_text(json.dumps({"rows": items, "links": page_links}, ensure_ascii=False, indent=2))
    print(f"\nDump em {OUTPUT}")
    await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
