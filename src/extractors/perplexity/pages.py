"""Captura Pages dentro de Spaces (Perplexity Pages = articles internamente).

Pages NAO sao listadas por nenhum endpoint REST — Perplexity e SPA Vite
e os links sao gerados via onClick (router.push). Estrategia:

1. Abre /spaces/{slug}
2. Pra cada SVG com xlink:href='#pplx-icon-custom-perplexity-page',
   sobe pra row, click programatico, captura URL pos-nav (/page/{slug})
3. Volta pro space e itera

Pra cada slug descoberto, fetcha via /rest/article/{slug} e salva
em spaces/{uuid}/pages/{slug}.json.

Limitacoes: ~10s por page (click + nav + go_back). Aceitavel pra
volumes baixos (Bookmarks default tem ~4-10 pages tipico).
"""

import json
import re
from pathlib import Path

from playwright.async_api import Page

from src.extractors.perplexity.api_client import PerplexityAPIClient


PAGE_ICON_SELECTOR_JS = (
    "Array.from(document.querySelectorAll('svg use'))"
    ".filter(u => u.getAttribute('xlink:href') === '#pplx-icon-custom-perplexity-page')"
)


async def _count_pages_in_dom(page: Page) -> int:
    return await page.evaluate(f"() => {PAGE_ICON_SELECTOR_JS}.length")


async def _get_nth_page_meta(page: Page, idx: int) -> dict | None:
    """Pega title da i-esima page row sem clicar."""
    return await page.evaluate(
        f"""(i) => {{
            const uses = {PAGE_ICON_SELECTOR_JS};
            const u = uses[i];
            if (!u) return null;
            const row = u.closest('[role="row"]');
            if (!row) return null;
            const titleDiv = row.querySelector('.text-sm.text-foreground');
            const labelDiv = row.querySelector('.text-xs.text-quiet');
            return {{
                title: titleDiv ? titleDiv.textContent.trim() : null,
                label: labelDiv ? labelDiv.textContent.trim() : null,
            }};
        }}""",
        idx,
    )


async def _click_nth_page_and_get_slug(page: Page, idx: int, timeout_ms: int = 15000) -> str | None:
    """Click no i-esimo page row, espera navegacao, retorna slug.
    URL pode chegar truncada inicialmente (Perplexity faz redirect/update
    pos-domcontentloaded), entao aguardamos URL estabilizar."""
    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=timeout_ms):
            await page.evaluate(
                f"""(i) => {{
                    const uses = {PAGE_ICON_SELECTOR_JS};
                    const u = uses[i];
                    if (!u) throw new Error('no svg at idx');
                    const row = u.closest('[role="row"]');
                    if (!row) throw new Error('no row ancestor');
                    row.click();
                }}""",
                idx,
            )
    except Exception as e:
        print(f"      click-nav idx={idx} falhou: {str(e)[:120]}")
        return None

    # Aguarda URL estabilizar — Perplexity ocasionalmente faz update pos-DOMReady
    last_url = page.url
    for _ in range(6):  # ate 3s total (6 x 500ms)
        await page.wait_for_timeout(500)
        if page.url != last_url:
            last_url = page.url
    url = last_url
    m = re.search(r'/page/([a-zA-Z0-9\-_]+)', url)
    return m.group(1) if m else None


async def discover_pages_in_space(
    page: Page,
    space_slug: str,
    space_uuid: str,
    *,
    nav_timeout_ms: int = 30000,
    settle_ms: int = 6000,
) -> list[dict]:
    """Abre o space, descobre todas as pages (title + slug) via DOM-click."""
    space_url = f"https://www.perplexity.ai/spaces/{space_slug}"
    await page.goto(space_url, wait_until="domcontentloaded", timeout=nav_timeout_ms)
    await page.wait_for_timeout(settle_ms)

    total = await _count_pages_in_dom(page)
    if total == 0:
        return []

    print(f"    {total} pages no DOM, extraindo slugs via click-and-back...")
    pages: list[dict] = []
    for i in range(total):
        meta = await _get_nth_page_meta(page, i)
        if not meta or not meta.get("title"):
            print(f"      [{i+1}/{total}] sem title — skip")
            continue
        slug = await _click_nth_page_and_get_slug(page, i)
        if not slug:
            print(f"      [{i+1}/{total}] {meta['title']!r}: sem slug")
            await page.goto(space_url, wait_until="domcontentloaded", timeout=nav_timeout_ms)
            await page.wait_for_timeout(settle_ms)
            continue
        pages.append({"title": meta["title"], "label": meta.get("label"), "slug": slug})
        print(f"      [{i+1}/{total}] {meta['title']!r} -> {slug}")
        # Volta pro space pra proxima iteracao
        await page.goto(space_url, wait_until="domcontentloaded", timeout=nav_timeout_ms)
        await page.wait_for_timeout(settle_ms)
    return pages


async def fetch_pages_in_space(
    client: PerplexityAPIClient,
    space_uuid: str,
    pages_meta: list[dict],
    output_dir: Path,
) -> tuple[int, list[tuple[str, str]]]:
    """Pra cada page descoberta, fetcha /rest/article/{slug} e salva."""
    pages_dir = output_dir / "spaces" / space_uuid / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    # Salva indice antes do fetch (preservation)
    with open(pages_dir / "_index.json", "w", encoding="utf-8") as f:
        json.dump(pages_meta, f, ensure_ascii=False, indent=2)

    ok = 0
    errors: list[tuple[str, str]] = []
    for p in pages_meta:
        slug = p["slug"]
        out = pages_dir / f"{slug}.json"
        if out.exists():
            ok += 1
            continue
        try:
            data = await client.fetch_article(slug)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            ok += 1
        except Exception as e:
            errors.append((slug, str(e)[:200]))
    return ok, errors
