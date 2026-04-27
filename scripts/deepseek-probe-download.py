"""Probe endpoint de DOWNLOAD de file do DeepSeek.

Abre browser em uma conv com file, voce clica pra baixar, script captura a XHR.

Uso: python scripts/deepseek-probe-download.py
"""

import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import Request, Response

from src.extractors.deepseek.auth import load_context


# Conv com muitos files pra testar (Corrigir alcas — 8 files)
TARGET_CONV = "08115596-1546-4de3-93da-66903b1671cc"
TARGET_URL = f"https://chat.deepseek.com/a/chat/s/{TARGET_CONV}"

OUTPUT = Path("/tmp/deepseek-download-probe.json")
WAIT_SECONDS = 90


async def main():
    context = await load_context(headless=False)
    page = await context.new_page()
    captured: list[dict] = []

    async def on_request(req: Request):
        u = req.url
        if "deepseek" not in u:
            return
        # Interessa qualquer request que pode ser download de file
        if any(k in u.lower() for k in ["file", "download", "blob", "s3", "oss", "alicdn", "cos", "storage"]):
            try:
                post_data = req.post_data
            except Exception:
                post_data = None
            captured.append({
                "phase": "request",
                "method": req.method,
                "url": u,
                "headers": dict(req.headers),
                "post_data": post_data,
            })

    async def on_response(resp: Response):
        u = resp.url
        if "deepseek" not in u:
            return
        if any(k in u.lower() for k in ["file", "download", "blob", "s3", "oss", "alicdn", "cos", "storage"]):
            try:
                body = await resp.text()
            except Exception:
                body = None
            captured.append({
                "phase": "response",
                "url": u,
                "status": resp.status,
                "response_headers": dict(resp.headers),
                "body": body[:3000] if body else None,
            })

    page.on("request", on_request)
    page.on("response", on_response)

    print(f"Abrindo {TARGET_URL}")
    print(f"INSTRUCOES:")
    print(f"  1. Espere a conv carregar")
    print(f"  2. Clique em QUALQUER file (preview ou download) — idealmente um diferente de cada vez")
    print(f"  3. Se aparecer botao de download, clique")
    print(f"  4. Script captura por {WAIT_SECONDS}s e depois fecha sozinho")
    print()
    await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(WAIT_SECONDS * 1000)

    OUTPUT.write_text(json.dumps(captured, ensure_ascii=False, indent=2))
    print(f"\n{len(captured)} requests/responses capturados em {OUTPUT}")

    # Resume unico por endpoint
    urls = {}
    for c in captured:
        key = c["url"].split("?")[0]
        urls[key] = urls.get(key, 0) + 1
    print("\nEndpoints unicos:")
    for u, n in sorted(urls.items(), key=lambda x: -x[1]):
        print(f"  [{n}x] {u[:140]}")

    await context.close()


if __name__ == "__main__":
    asyncio.run(main())
