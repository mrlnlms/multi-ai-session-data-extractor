"""Final probe pra Pages: extrai slugs do DOM + descobre endpoint REST proprio."""

import asyncio
import re
from src.extractors.perplexity.auth import load_context

BOOKMARKS_SLUG = "bookmarks-9XLOIIv8SZeZI.gC9.47Ww"


async def main():
    ctx = await load_context(headless=False)
    page = await ctx.new_page()

    # Capturar XHRs ao longo do probe
    rest_calls = []
    def _on_resp(r):
        if "perplexity.ai/rest/" in r.url.lower():
            rest_calls.append({"url": r.url, "status": r.status, "method": r.request.method})
    page.on("response", _on_resp)

    await page.goto(f"https://www.perplexity.ai/spaces/{BOOKMARKS_SLUG}", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(8000)

    # Procura slugs no HTML com varios patterns (literal, escape JSON, hex)
    html = await page.content()
    patterns = [
        r'/page/([a-zA-Z0-9\-]+)',
        r'page\\u002F([a-zA-Z0-9\\-]+)',
        r'pageUrl"\s*:\s*"[^"]*?/page/([a-zA-Z0-9\-]+)',
        r'"slug"\s*:\s*"([a-z0-9-]+-[a-zA-Z0-9_]{20,})"',  # slug com hash final
    ]
    for p in patterns:
        m = re.findall(p, html)
        if m:
            print(f"Pattern {p[:50]}: {len(set(m))} unique matches: {list(set(m))[:5]}")

    # Estrategia: clicar numa Page e capturar XHRs disparados
    print("\n=== Clicando numa Page e capturando XHRs ===")
    rest_calls.clear()
    try:
        await page.get_by_text("Brain Stores Memories", exact=False).first.click(timeout=5000)
        await page.wait_for_timeout(8000)
        new_url = page.url
        print(f"Nova URL: {new_url}")
        m = re.search(r'/page/([a-zA-Z0-9\-]+)', new_url)
        test_slug = m.group(1) if m else None
        print(f"Slug extraido: {test_slug}")
    except Exception as e:
        print(f"click falhou: {e}")
        test_slug = None

    print(f"\nXHRs disparados durante click ({len(rest_calls)}):")
    seen = set()
    for c in rest_calls:
        path = c["url"].split("?")[0].split("/rest/", 1)[-1]
        if path in seen:
            continue
        seen.add(path)
        print(f"  [{c['status']}] {c['method']:5} {path}")

    if not test_slug:
        print("\nsem slug — saindo")
        await ctx.close()
        return
    test_uuid_pattern = re.search(r'-([a-zA-Z0-9_]{20,})$', test_slug)
    print(f"\nTestando endpoints com slug: {test_slug}")

    # Probas REST
    candidates = [
        f"/rest/page/{test_slug}",
        f"/rest/pages/{test_slug}",
        f"/rest/page/get?page_slug={test_slug}",
        f"/rest/pages/get?page_slug={test_slug}",
        f"/rest/page/get_page?page_slug={test_slug}",
        f"/rest/pages/get_page?page_slug={test_slug}",
        f"/rest/page/{test_slug}?version=2.18&source=default",
        f"/rest/pages/{test_slug}?version=2.18&source=default",
        # Talvez page_id ao inves de slug
        f"/rest/page?slug={test_slug}",
        f"/rest/pages?slug={test_slug}",
        # Talvez via thread/get com slug
        f"/rest/thread/{test_slug}",
    ]
    for path in candidates:
        try:
            r = await page.evaluate(
                """async (path) => {
                    const res = await fetch(path);
                    return {status: res.status, body: (await res.text()).slice(0, 400)};
                }""",
                path,
            )
            ok = "✓" if 200 <= r["status"] < 300 else " "
            print(f"  {ok} {path[:90]} -> {r['status']}", flush=True)
            if 200 <= r["status"] < 300:
                print(f"    body: {r['body'][:300]}", flush=True)
        except Exception as e:
            print(f"    {path[:90]} ERROR {str(e)[:60]}", flush=True)

    # Estrategia 2: capturar XHRs ao navegar pra uma page
    print(f"\nNavegando pra /page/{test_slug} pra capturar XHRs...")
    rest_calls = []
    page.on("response", lambda r: rest_calls.append({
        "url": r.url, "status": r.status, "method": r.request.method
    }) if "perplexity.ai/rest/" in r.url.lower() else None)

    await page.goto(f"https://www.perplexity.ai/page/{test_slug}", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(8000)

    # Endpoints unicos chamados
    seen = set()
    for c in rest_calls:
        path = c["url"].split("?")[0].split("/rest/", 1)[-1]
        if path in seen:
            continue
        seen.add(path)
        print(f"  [{c['status']}] {c['method']:5} {path}")

    await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
