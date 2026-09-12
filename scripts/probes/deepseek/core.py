"""Probe autonomo DeepSeek: abre headless com profile logado, carrega home,
abre 1-2 convs e dumpa XHR/fetch requests em /tmp/deepseek-probe.json.

Uso: python scripts/deepseek-probe-core.py
Requer profile logado previo (scripts/deepseek-login.py).

Estrategia:
  1. Carrega home (deepseek.com) -> listing chega via XHR
  2. Pesca conv ID do listing response
  3. Navega pra URL da conv -> fetch chega via XHR
  4. Dumpa tudo
"""

import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import Request, Response

from src.extractors.deepseek.auth import load_context, HOME_URL


OUTPUT = Path("/tmp/deepseek-probe.json")
WAIT_AFTER_LOAD = 8
WAIT_AFTER_CONV = 10

IGNORE_PATTERNS = [
    r"\.(png|jpg|jpeg|gif|svg|ico|webp|woff2?|ttf|otf|css|js|map)($|\?)",
    r"/_next/static/",
    r"google-analytics|googletagmanager|sentry|datadog|mixpanel|hotjar|segment|amplitude",
    r"/favicon",
    r"fonts\.",
]


def should_capture(url: str) -> bool:
    for pat in IGNORE_PATTERNS:
        if re.search(pat, url, flags=re.IGNORECASE):
            return False
    return "deepseek" in url.lower()


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
                                          "x-requested-with", "x-ds-pow-response",
                                          "x-app-version", "x-client-version"}},
            "post_data": post_data[:2000] if post_data else None,
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

    print(f"[1/3] Abrindo {HOME_URL}...")
    await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
    print(f"       Aguardando {WAIT_AFTER_LOAD}s pra SPA carregar listing...")
    await page.wait_for_timeout(WAIT_AFTER_LOAD * 1000)

    # Tenta achar um conv_id no que foi capturado ate agora
    conv_id = None
    for c in captured:
        body = c.get("response_preview") or ""
        m = re.search(r'"id"\s*:\s*"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"', body)
        if m and "chat_session" in c["url"].lower():
            conv_id = m.group(1)
            break
        if m and "session" in c["url"].lower():
            conv_id = m.group(1)
            break
    if not conv_id:
        for c in captured:
            body = c.get("response_preview") or ""
            m = re.search(r'"id"\s*:\s*"([0-9a-f\-]{36})"', body)
            if m:
                conv_id = m.group(1)
                break

    if conv_id:
        target = f"https://chat.deepseek.com/a/chat/s/{conv_id}"
        print(f"[2/3] Conv ID descoberto: {conv_id}. Abrindo {target}...")
        await page.goto(target, wait_until="domcontentloaded", timeout=60000)
        print(f"       Aguardando {WAIT_AFTER_CONV}s pra fetch chegar...")
        await page.wait_for_timeout(WAIT_AFTER_CONV * 1000)
    else:
        print("[2/3] Nao achou conv_id no listing. Dumpando o que tem.")

    OUTPUT.write_text(json.dumps(captured, ensure_ascii=False, indent=2))
    print(f"\n[3/3] {len(captured)} requests capturados em {OUTPUT}")

    urls: dict[str, int] = {}
    for c in captured:
        key = c["url"].split("?")[0]
        urls[key] = urls.get(key, 0) + 1
    print("\nEndpoints unicos:")
    for url, count in sorted(urls.items(), key=lambda x: -x[1]):
        print(f"  [{count}x] {url}")

    await context.close()


if __name__ == "__main__":
    asyncio.run(main())
