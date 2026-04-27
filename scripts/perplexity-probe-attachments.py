"""Probe endpoint de attachments do Perplexity: abre 6 threads em sequencia
automaticamente, captura XHRs. Se o SPA faz fetch dos attachments no load,
pegamos a URL real.

Uso: python scripts/perplexity-probe-attachments.py
"""

import asyncio
import json
from pathlib import Path
from playwright.async_api import Request, Response

from src.extractors.perplexity.auth import load_context


OUTPUT = Path("/tmp/perplexity-attachments-probe.json")
WAIT_PER_THREAD = 12  # segundos

# Threads com attachments (do raw)
THREADS = [
    ("c4d20df9-38fe-4b69-abf5-b7b386f04224", "eu fiz uma analise (image.jpg)"),
    ("c78e3e1b-a1de-4677-baa9-0b1dc6ac1a34", "Mapa-de-empatia.pdf"),
    ("ab861684-0104-42c6-8258-1fac227f2125", "Analise critica pesquisa (paste.txt)"),
    ("a8d7542c-7c65-471a-bb8d-0c3ae2a4dc15", "Avaliacao critica artigo (paste.txt)"),
    ("a4cc1b81-ea31-4b44-8d4b-7634b4f78ba2", "Analise levantamento (paste.txt)"),
    ("7b991f75-091f-4592-a26f-096401a4ff19", "Organizar referencias (3x directory_list.txt)"),
]


def _interesting(url: str) -> bool:
    """Captura qualquer coisa que pode ser attachment/file/upload."""
    u = url.lower()
    if "perplexity" in u and any(k in u for k in ["file", "attachment", "upload", "download", "asset"]):
        return True
    if any(k in u for k in ["ppl-ai-file-upload", "pplx-res.cloudinary", "s3.amazonaws"]):
        return True
    return False


async def main():
    context = await load_context(headless=False)
    page = await context.new_page()
    captured: list[dict] = []
    current_thread = {"uuid": None, "label": None}

    async def on_request(req: Request):
        if not _interesting(req.url):
            return
        try:
            post_data = req.post_data
        except Exception:
            post_data = None
        captured.append({
            "thread_uuid": current_thread["uuid"],
            "thread_label": current_thread["label"],
            "phase": "request",
            "method": req.method,
            "url": req.url,
            "headers": {k: v for k, v in req.headers.items()
                        if k.lower() in {"content-type", "authorization", "referer"}},
            "post_data": post_data[:1000] if post_data else None,
        })

    async def on_response(resp: Response):
        if not _interesting(resp.url):
            return
        try:
            body = await resp.text()
        except Exception:
            body = None
        captured.append({
            "thread_uuid": current_thread["uuid"],
            "thread_label": current_thread["label"],
            "phase": "response",
            "url": resp.url,
            "status": resp.status,
            "response_headers": dict(resp.headers),
            "body": body[:2000] if body else None,
        })

    page.on("request", on_request)
    page.on("response", on_response)

    # Warmup pra passar Cloudflare
    print("[warmup] home + library...", flush=True)
    await page.goto("https://www.perplexity.ai/", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(5000)
    await page.goto("https://www.perplexity.ai/library", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3000)

    for i, (uuid, label) in enumerate(THREADS, 1):
        current_thread["uuid"] = uuid
        current_thread["label"] = label
        url = f"https://www.perplexity.ai/search/{uuid}"
        print(f"[{i}/{len(THREADS)}] {label}", flush=True)
        print(f"         {url}", flush=True)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"         ERRO goto: {e}", flush=True)
            continue
        await page.wait_for_timeout(WAIT_PER_THREAD * 1000)
        c = sum(1 for x in captured if x.get("thread_uuid") == uuid)
        print(f"         {c} XHRs capturadas", flush=True)

    OUTPUT.write_text(json.dumps(captured, ensure_ascii=False, indent=2))
    print(f"\nTotal: {len(captured)} events em {OUTPUT}", flush=True)

    # Resumo
    print("\nResumo por thread:")
    for uuid, label in THREADS:
        items = [c for c in captured if c.get("thread_uuid") == uuid]
        urls = set(c["url"].split("?")[0] for c in items)
        print(f"  [{uuid[:12]}] {label[:50]} — {len(items)} events, {len(urls)} endpoints unicos")
        for u in list(urls)[:5]:
            print(f"      {u[:140]}")

    await context.close()


if __name__ == "__main__":
    asyncio.run(main())
