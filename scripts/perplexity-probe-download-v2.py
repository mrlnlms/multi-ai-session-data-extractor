"""Probe interativo Perplexity: abre 1 thread com PDF, voce clica no file, captura TUDO.

Sem filtros agressivos — pega request, response, download events, iframes.
Captura por 120s depois que thread carrega.

Uso: python scripts/perplexity-probe-download-v2.py
"""

import asyncio
import json
from pathlib import Path
from playwright.async_api import Request, Response, Download

from src.extractors.perplexity.auth import load_context


# Thread do Mapa-de-empatia.pdf (PDF que o user disse que abriu)
TARGET = "c78e3e1b-a1de-4677-baa9-0b1dc6ac1a34"
TARGET_URL = f"https://www.perplexity.ai/search/{TARGET}"

OUTPUT = Path("/tmp/perplexity-download-v2-probe.json")
WAIT_SECONDS = 120


async def main():
    context = await load_context(headless=False)
    # Accept downloads
    page = await context.new_page()

    events: list[dict] = []

    async def on_request(req: Request):
        try:
            post = req.post_data
        except Exception:
            post = None
        events.append({
            "type": "request",
            "method": req.method,
            "url": req.url,
            "resource_type": req.resource_type,
            "headers": dict(req.headers),
            "post_data": post[:2000] if post else None,
        })

    async def on_response(resp: Response):
        try:
            body = await resp.text()
        except Exception:
            body = None
        events.append({
            "type": "response",
            "url": resp.url,
            "status": resp.status,
            "response_headers": dict(resp.headers),
            "body": body[:3000] if body else None,
        })

    async def on_download(dl: Download):
        events.append({
            "type": "download",
            "url": dl.url,
            "suggested_filename": dl.suggested_filename,
        })

    async def on_popup(p):
        events.append({"type": "popup", "url": p.url})
        p.on("request", on_request)
        p.on("response", on_response)
        p.on("download", on_download)

    page.on("request", on_request)
    page.on("response", on_response)
    page.on("download", on_download)
    page.on("popup", on_popup)

    # Warmup + Cloudflare
    print("[warmup] home...", flush=True)
    await page.goto("https://www.perplexity.ai/", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(5000)

    print(f"[target] {TARGET_URL}", flush=True)
    print(f"INSTRUCOES:", flush=True)
    print(f"  1. Espera thread carregar", flush=True)
    print(f"  2. Clica no attachment (Mapa-de-empatia.pdf)", flush=True)
    print(f"  3. Se baixar ou abrir preview, deixa fazer", flush=True)
    print(f"  4. Script fecha em {WAIT_SECONDS}s sozinho", flush=True)
    print(flush=True)

    await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(WAIT_SECONDS * 1000)

    OUTPUT.write_text(json.dumps(events, ensure_ascii=False, indent=2))
    print(f"\n{len(events)} events em {OUTPUT}", flush=True)

    # Resumo: endpoints REST/S3 interessantes
    print("\n=== Endpoints interessantes ===", flush=True)
    seen = set()
    for e in events:
        u = e.get("url", "")
        if not u:
            continue
        # Ignora estatico
        if any(u.lower().endswith(x) for x in [".css", ".js", ".svg", ".woff2", ".woff", ".map", ".ico"]):
            continue
        if "/_spa/assets/" in u or "/static/" in u or "fonts.gstatic" in u:
            continue
        if "datadoghq" in u or "singular.net" in u or "eppo" in u:
            continue
        # Interesse
        if any(k in u.lower() for k in ["/rest/", "s3.amazonaws", "ppl-ai-file", "pplx-res", "file-repo", "attachment", "download", "upload"]):
            base = u.split("?")[0]
            if base in seen:
                continue
            seen.add(base)
            tag = e.get("type", "?")[:4]
            status = e.get("status")
            print(f"  [{tag}{f' {status}' if status else ''}] {base[:150]}", flush=True)

    await context.close()


if __name__ == "__main__":
    asyncio.run(main())
