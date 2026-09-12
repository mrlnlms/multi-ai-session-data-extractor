"""Probe drill-down de Spaces (collections):
1. Lista collections do user
2. Abre cada Space via URL pra capturar endpoints internos
3. Probra endpoints REST chutados (threads/pages/files)

Uso: python scripts/perplexity-probe-spaces.py
Output: /tmp/perplexity-spaces-probe.json
"""

import asyncio
import json
from pathlib import Path
from playwright.async_api import Request, Response

from src.extractors.perplexity.auth import load_context


OUTPUT = Path("/tmp/perplexity-spaces-probe.json")
WAIT_AFTER_NAV = 6


def _capture(url: str) -> bool:
    if "perplexity.ai/rest/" in url.lower():
        return True
    return False


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
            "post_data": post_data[:2000] if post_data else None,
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
            "response_preview": body[:3500] if body else None,
            "response_length": len(body) if body else 0,
        })

    page.on("request", on_request)
    page.on("response", on_response)

    # Warmup
    print("[warmup] home...", flush=True)
    await page.goto("https://www.perplexity.ai/", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4000)

    # Pega lista de collections
    print("[1] Buscando lista de collections...", flush=True)
    current_section["name"] = "list_collections"
    collections_resp = await page.evaluate(
        """async () => {
            const res = await fetch('/rest/collections/list_user_collections?version=2.18&source=default');
            return {status: res.status, body: await res.text()};
        }"""
    )
    print(f"   status={collections_resp['status']} len={len(collections_resp['body'])}", flush=True)
    try:
        collections = json.loads(collections_resp["body"])
    except Exception as e:
        print(f"   ERRO parse: {e}", flush=True)
        collections = []

    print(f"   {len(collections)} collections encontradas:", flush=True)
    targets = []
    for c in collections:
        slug = c.get("slug")
        uuid = c.get("uuid")
        title = c.get("title")
        thread_count = c.get("thread_count")
        page_count = c.get("page_count")
        file_count = c.get("file_count")
        print(f"     - {title!r} uuid={uuid[:12]} slug={slug[:30] if slug else None} threads={thread_count} pages={page_count} files={file_count}", flush=True)
        if slug and uuid:
            targets.append({"slug": slug, "uuid": uuid, "title": title})

    # Abre cada collection via varias URLs candidatas
    for tgt in targets[:3]:  # max 3
        slug = tgt["slug"]
        uuid = tgt["uuid"]
        title = tgt["title"]
        for url_pattern in [
            f"https://www.perplexity.ai/collections/{slug}",
            f"https://www.perplexity.ai/spaces/{slug}",
        ]:
            section = f"open_{title}_{url_pattern.split('/')[-2]}"
            current_section["name"] = section
            print(f"\n[2] {url_pattern}", flush=True)
            try:
                resp = await page.goto(url_pattern, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(WAIT_AFTER_NAV * 1000)
                final_url = page.url
                print(f"    final_url={final_url} status={resp.status if resp else '?'}", flush=True)
                events_in = [c for c in captured if c.get("section") == section]
                rest_in = [c for c in events_in if "/rest/" in c.get("url", "")]
                unique = set(c["url"].split("?")[0] for c in rest_in)
                print(f"    {len(events_in)} events, {len(unique)} unique REST", flush=True)
                if unique:
                    for u in sorted(unique):
                        print(f"      {u.split('/rest/', 1)[-1]}", flush=True)
                if final_url == url_pattern or "/library" in final_url or final_url == "https://www.perplexity.ai/":
                    # Se redirecionou pra library/home a URL pode estar errada
                    # Mas mantem o que capturou
                    pass
            except Exception as e:
                print(f"    ERRO: {str(e)[:120]}", flush=True)

    # Probe de endpoints REST chutados em cima de uma collection
    print("\n[3] Probing REST endpoints chutados...", flush=True)
    if targets:
        first = targets[0]
        uuid = first["uuid"]
        slug = first["slug"]
        candidates = [
            f"/rest/collections/{uuid}",
            f"/rest/collections/{uuid}/threads",
            f"/rest/collections/{uuid}/pages",
            f"/rest/collections/{uuid}/files",
            f"/rest/collections/{uuid}/info",
            f"/rest/collections/{uuid}/info?version=2.18&source=default",
            f"/rest/collections/info/{uuid}",
            f"/rest/collections/info/{uuid}?version=2.18&source=default",
            f"/rest/collections/get/{uuid}",
            f"/rest/collections/{slug}",
            f"/rest/spaces/{uuid}",
            f"/rest/spaces/{uuid}/threads",
            f"/rest/spaces/{uuid}/pages",
            f"/rest/spaces/{uuid}/files",
            f"/rest/spaces/info/{uuid}",
            f"/rest/spaces/{slug}",
            # Filtro de list_ask_threads por collection
            f"/rest/thread/list_ask_threads?version=2.18&source=default&collection_uuid={uuid}",
        ]
        results = []
        for path in candidates:
            try:
                # Tenta GET primeiro
                r = await page.evaluate(
                    """async (path) => {
                        const res = await fetch(path);
                        const txt = await res.text();
                        return {status: res.status, body: txt.slice(0, 600)};
                    }""",
                    path,
                )
                results.append({"method": "GET", "path": path, "status": r["status"], "preview": r["body"]})
                ok = "✓" if 200 <= r["status"] < 300 else " "
                print(f"  {ok} GET  {path[:80]} -> {r['status']}", flush=True)
            except Exception as e:
                results.append({"method": "GET", "path": path, "error": str(e)[:200]})
                print(f"    GET  {path[:80]} ERROR {str(e)[:60]}", flush=True)

        # Adicionalmente tenta POST com body padrao na collection_uuid
        post_paths = [
            f"/rest/thread/list_ask_threads?version=2.18&source=default",  # com body collection_uuid
        ]
        for p in post_paths:
            try:
                r = await page.evaluate(
                    """async ({path, body}) => {
                        const res = await fetch(path, {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify(body)
                        });
                        return {status: res.status, body: (await res.text()).slice(0, 600)};
                    }""",
                    {"path": p, "body": {"limit": 5, "ascending": False, "offset": 0, "search_term": "", "exclude_asi": False, "collection_uuid": uuid}},
                )
                results.append({"method": "POST_w_collection", "path": p, "status": r["status"], "preview": r["body"]})
                ok = "✓" if 200 <= r["status"] < 300 else " "
                print(f"  {ok} POST {p[:80]} (body+collection_uuid) -> {r['status']}", flush=True)
            except Exception as e:
                pass

    OUTPUT.write_text(json.dumps({
        "collections": collections,
        "captured": captured,
        "rest_probe_results": results if targets else [],
    }, ensure_ascii=False, indent=2))
    print(f"\nDump em {OUTPUT}", flush=True)
    await context.close()


if __name__ == "__main__":
    asyncio.run(main())
