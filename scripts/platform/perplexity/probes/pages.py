"""Probe focado: Pages dentro de Spaces + Skills + Links + user-pins.

Estrategia: abrir Bookmarks (que tem 4 pages visiveis), capturar XHRs,
procurar endpoints novos. Tambem probra variacoes chutadas.
"""

import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import Request, Response

from src.extractors.perplexity.auth import load_context


OUTPUT = Path("/tmp/perplexity-pages-probe.json")
BOOKMARKS_SLUG = "bookmarks-9XLOIIv8SZeZI.gC9.47Ww"
BOOKMARKS_UUID = "f572ce20-8bfc-4997-9923-e802f7ee3b5b"


def _capture(url: str) -> bool:
    return "perplexity.ai/rest/" in url.lower()


async def main():
    context = await load_context(headless=False)
    page = await context.new_page()
    captured: list[dict] = []
    current_section = {"name": "init"}

    async def on_request(req: Request):
        if not _capture(req.url):
            return
        try:
            post_data = req.post_data
        except Exception:
            post_data = None
        captured.append({
            "section": current_section["name"],
            "phase": "request",
            "method": req.method,
            "url": req.url,
            "post_data": post_data[:1500] if post_data else None,
        })

    async def on_response(resp: Response):
        if not _capture(resp.url):
            return
        try:
            body = await resp.text()
        except Exception:
            body = None
        captured.append({
            "section": current_section["name"],
            "phase": "response",
            "method": resp.request.method,
            "url": resp.url,
            "status": resp.status,
            "response_preview": body[:4000] if body else None,
            "response_length": len(body) if body else 0,
        })

    page.on("request", on_request)
    page.on("response", on_response)

    print("[warmup] home...", flush=True)
    await page.goto("https://www.perplexity.ai/", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4000)

    # Abrir Bookmarks (deve disparar todos os XHRs pra renderizar pages e threads)
    current_section["name"] = "bookmarks_open"
    print(f"[1] Abrindo Bookmarks space...", flush=True)
    await page.goto(
        f"https://www.perplexity.ai/spaces/{BOOKMARKS_SLUG}",
        wait_until="domcontentloaded", timeout=20000,
    )
    await page.wait_for_timeout(8000)
    in_section = [c for c in captured if c.get("section") == "bookmarks_open"]
    rest_unique = sorted(set(c["url"].split("?")[0].split("/rest/", 1)[-1] for c in in_section if "/rest/" in c.get("url", "")))
    print(f"   {len(in_section)} events, {len(rest_unique)} unique REST endpoints:", flush=True)
    for u in rest_unique:
        print(f"     {u}", flush=True)

    # Tentar trocar de tab dentro do Bookmarks (Pages/Threads/Files etc)
    # As tabs aparecem na UI — vou tentar clicar em "Pages" se houver
    print(f"\n[2] Tentando clicar em tabs internas...", flush=True)
    for tab_name in ["Pages", "Files", "Threads"]:
        current_section["name"] = f"tab_{tab_name}"
        try:
            tab = page.get_by_role("tab", name=tab_name, exact=True)
            if await tab.count() > 0:
                print(f"   click tab '{tab_name}'", flush=True)
                await tab.first.click(timeout=5000)
                await page.wait_for_timeout(4000)
            else:
                # Tenta como link/button
                btn = page.get_by_text(tab_name, exact=True).first
                if await btn.count() > 0:
                    print(f"   click text '{tab_name}'", flush=True)
                    await btn.click(timeout=5000)
                    await page.wait_for_timeout(4000)
                else:
                    print(f"   tab '{tab_name}' nao encontrada", flush=True)
        except Exception as e:
            print(f"   tab '{tab_name}' falhou: {str(e)[:80]}", flush=True)

    # Probes chutados
    print(f"\n[3] Probing endpoints chutados...", flush=True)
    candidates = [
        # Pages
        ("GET", f"/rest/collections/list_collection_pages?collection_slug={BOOKMARKS_SLUG}", None),
        ("GET", f"/rest/collections/list_collection_pages?collection_slug={BOOKMARKS_SLUG}&limit=20", None),
        ("GET", f"/rest/collections/list_pages?collection_slug={BOOKMARKS_SLUG}", None),
        ("GET", f"/rest/page/list?collection_slug={BOOKMARKS_SLUG}", None),
        ("GET", f"/rest/pages/list?collection_slug={BOOKMARKS_SLUG}", None),
        ("GET", f"/rest/spaces/{BOOKMARKS_UUID}/pages", None),
        ("GET", f"/rest/spaces/{BOOKMARKS_UUID}/pages?version=2.18&source=default", None),
        # Variant
        ("GET", f"/rest/collections/list_collection_threads?collection_slug={BOOKMARKS_SLUG}&limit=20&filter_by_user=false&include_pages=true", None),
        ("GET", f"/rest/collections/list_collection_threads?collection_slug={BOOKMARKS_SLUG}&limit=20&filter_by_user=false&variant=page", None),
        ("GET", f"/rest/collections/list_collection_threads?collection_slug={BOOKMARKS_SLUG}&limit=20&filter_by_user=false&variant=all", None),
        # Skills
        ("GET", f"/rest/spaces/{BOOKMARKS_UUID}/skills", None),
        ("GET", f"/rest/spaces/{BOOKMARKS_UUID}/skills?version=2.18&source=default", None),
        ("GET", f"/rest/collections/skills?collection_slug={BOOKMARKS_SLUG}", None),
        ("GET", f"/rest/skills?collection_uuid={BOOKMARKS_UUID}", None),
        # Links
        ("GET", f"/rest/spaces/{BOOKMARKS_UUID}/links", None),
        ("GET", f"/rest/collections/links?collection_slug={BOOKMARKS_SLUG}", None),
        ("GET", f"/rest/collections/list_links?collection_slug={BOOKMARKS_SLUG}", None),
        # User-pins (de spaces)
        ("GET", f"/rest/spaces/user-pins", None),
        ("GET", f"/rest/spaces/user-pins?version=2.18&source=default", None),
    ]
    probe_results = []
    for method, path, body in candidates:
        try:
            r = await page.evaluate(
                """async ({path, method, body}) => {
                    const opts = {method};
                    if (body !== null) {
                        opts.headers = {'Content-Type': 'application/json'};
                        opts.body = JSON.stringify(body);
                    }
                    const res = await fetch(path, opts);
                    return {status: res.status, body: (await res.text()).slice(0, 1500)};
                }""",
                {"path": path, "method": method, "body": body},
            )
            probe_results.append({"method": method, "path": path, "status": r["status"], "preview": r["body"]})
            ok = "✓" if 200 <= r["status"] < 300 else " "
            sample = r["body"][:80] if 200 <= r["status"] < 300 else ""
            print(f"  {ok} {method:5} {path[:80]} -> {r['status']} {sample}", flush=True)
        except Exception as e:
            probe_results.append({"method": method, "path": path, "error": str(e)[:200]})
            print(f"    {method:5} {path[:80]} ERROR {str(e)[:60]}", flush=True)

    OUTPUT.write_text(json.dumps({"captured": captured, "probe_results": probe_results}, ensure_ascii=False, indent=2))
    print(f"\nDump em {OUTPUT}", flush=True)
    await context.close()


if __name__ == "__main__":
    asyncio.run(main())
