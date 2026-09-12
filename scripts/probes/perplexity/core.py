"""Probe autonomo Perplexity: headless com profile logado, captura XHRs.

Endpoint de listing ja conhecido pelo legacy script:
  POST /rest/thread/list_ask_threads?version=2.18&source=default

Este probe:
  1. Chama list_ask_threads via page.evaluate pra pegar uma thread uuid + slug
  2. Abre /search/<slug> pra capturar fetch da thread
  3. Dumpa em /tmp/perplexity-probe.json
"""

import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import Request, Response

from src.extractors.perplexity.auth import load_context, HOME_URL


OUTPUT = Path("/tmp/perplexity-probe.json")
WAIT_AFTER_LIST = 5
WAIT_AFTER_THREAD = 10


def should_capture(url: str) -> bool:
    ignore = [
        r"\.(png|jpg|jpeg|gif|svg|ico|webp|woff2?|ttf|otf|css|js|map)($|\?)",
        r"/_next/static/",
        r"google|sentry|datadog|segment|amplitude|hotjar|mixpanel",
        r"/favicon",
    ]
    for pat in ignore:
        if re.search(pat, url, flags=re.IGNORECASE):
            return False
    return "perplexity" in url.lower()


async def main():
    context = await load_context(headless=True)
    page = await context.new_page()
    captured: list[dict] = []
    in_flight: dict[int, dict] = {}

    async def on_request(req: Request):
        if not should_capture(req.url):
            return
        try:
            post_data = req.post_data
        except Exception:
            post_data = None
        entry = {
            "method": req.method,
            "url": req.url,
            "resource_type": req.resource_type,
            "headers": {k: v for k, v in req.headers.items()
                        if k.lower() in {"content-type", "authorization", "x-client-locale",
                                          "x-requested-with", "x-client-version"}},
            "post_data": post_data[:3000] if post_data else None,
        }
        in_flight[id(req)] = entry

    async def on_response(resp: Response):
        req = resp.request
        if not should_capture(req.url):
            return
        entry = in_flight.pop(id(req), None) or {
            "method": req.method,
            "url": req.url,
            "resource_type": req.resource_type,
            "headers": {},
            "post_data": None,
        }
        entry["status"] = resp.status
        try:
            body = await resp.text()
            entry["response_preview"] = body[:5000]
            entry["response_length"] = len(body)
        except Exception as e:
            entry["response_preview"] = None
            entry["response_error"] = str(e)[:200]
        captured.append(entry)

    page.on("request", on_request)
    page.on("response", on_response)

    print("[1/3] Abrindo library pra pegar cookies/headers...")
    await page.goto("https://www.perplexity.ai/library", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(WAIT_AFTER_LIST * 1000)

    # Usa page.evaluate pra chamar list_ask_threads dentro do context do SPA
    print("[2/3] Chamando list_ask_threads via fetch inline...")
    try:
        first_batch = await page.evaluate(
            """async () => {
                const res = await fetch('/rest/thread/list_ask_threads?version=2.18&source=default', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({limit: 5, ascending: false, offset: 0, search_term: '', exclude_asi: false})
                });
                const txt = await res.text();
                return {status: res.status, body: txt.slice(0, 8000)};
            }"""
        )
        print(f"       status={first_batch['status']} len={len(first_batch['body'])}")
        captured.append({
            "_manual_probe": "list_ask_threads",
            "url": "/rest/thread/list_ask_threads",
            "status": first_batch["status"],
            "response_preview": first_batch["body"],
        })
        # Tenta achar slug no body
        m = re.search(r'"slug"\s*:\s*"([^"]+)"', first_batch["body"])
        slug = m.group(1) if m else None
    except Exception as e:
        print(f"       ERROR: {e}")
        slug = None

    if slug:
        url = f"https://www.perplexity.ai/search/{slug}"
        print(f"[3/3] Abrindo thread /search/{slug} pra capturar fetch individual...")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(WAIT_AFTER_THREAD * 1000)
    else:
        print("[3/3] Sem slug. Dumpando oq tem.")

    OUTPUT.write_text(json.dumps(captured, ensure_ascii=False, indent=2))
    print(f"\n{len(captured)} entries em {OUTPUT}")

    urls: dict[str, int] = {}
    for c in captured:
        key = (c.get("url") or "").split("?")[0]
        urls[key] = urls.get(key, 0) + 1
    print("\nEndpoints unicos:")
    for url, count in sorted(urls.items(), key=lambda x: -x[1]):
        print(f"  [{count}x] {url}")

    await context.close()


if __name__ == "__main__":
    asyncio.run(main())
