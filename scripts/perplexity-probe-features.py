"""Probe Perplexity: mapeia endpoints reais navegando por
Library / Spaces / Computer / Scheduled / History via sidebar e captura
todos os XHRs /rest/*.

Tambem inclui probe explicito de pinned threads (HTTP 400 conhecido)
testando variacoes de version/method.

Uso: python scripts/perplexity-probe-features.py
Output: /tmp/perplexity-features-probe.json + sumario no stdout
"""

import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import Request, Response

from src.extractors.perplexity.auth import load_context


OUTPUT = Path("/tmp/perplexity-features-probe.json")
WAIT_AFTER_NAV = 6  # segundos pra SPA disparar XHRs

SECTIONS = [
    # (label, sidebar_text_to_click_or_None, fallback_url)
    ("library",   None,         "https://www.perplexity.ai/library"),
    ("spaces",    "Spaces",     "https://www.perplexity.ai/spaces"),
    ("computer",  "Computer",   "https://www.perplexity.ai/computer"),
    ("history",   "History",    "https://www.perplexity.ai/history"),
    ("scheduled", "Scheduled",  "https://www.perplexity.ai/scheduled"),
]


def _is_rest(url: str) -> bool:
    return "perplexity.ai/rest/" in url.lower()


def _is_static(url: str) -> bool:
    return bool(re.search(r"\.(png|jpg|jpeg|gif|svg|ico|webp|woff2?|ttf|otf|css|js|map)($|\?)", url, re.I))


def _capture(url: str) -> bool:
    if _is_static(url):
        return False
    if _is_rest(url):
        return True
    if "perplexity" in url.lower():
        return True
    return False


async def _nav_section(page, label: str, click_text: str | None, fallback_url: str):
    """Tenta clicar no link da sidebar. Se falhar, vai por URL direta."""
    if click_text:
        try:
            link = page.get_by_role("link", name=click_text, exact=True)
            if await link.count() > 0:
                print(f"  [{label}] click sidebar '{click_text}'", flush=True)
                await link.first.click(timeout=5000)
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                return f"click:{click_text}"
        except Exception as e:
            print(f"  [{label}] click falhou ({str(e)[:60]}), tentando URL direta", flush=True)

    print(f"  [{label}] goto {fallback_url}", flush=True)
    try:
        await page.goto(fallback_url, wait_until="domcontentloaded", timeout=20000)
        return f"goto:{fallback_url}"
    except Exception as e:
        print(f"  [{label}] goto falhou: {str(e)[:80]}", flush=True)
        return f"failed:{e}"


async def _probe_pinned_variations(page) -> list[dict]:
    """Testa variacoes do endpoint /rest/thread/list_pinned_ask_threads."""
    variations = [
        {"path": "/rest/thread/list_pinned_ask_threads?version=2.18&source=default", "method": "GET", "body": None},
        {"path": "/rest/thread/list_pinned_ask_threads?version=2.18&source=default", "method": "POST", "body": {}},
        {"path": "/rest/thread/list_pinned_ask_threads?version=2.18&source=default", "method": "POST",
         "body": {"limit": 20, "offset": 0, "ascending": False, "search_term": "", "exclude_asi": False}},
        {"path": "/rest/thread/list_pinned_ask_threads?source=default", "method": "GET", "body": None},
        {"path": "/rest/thread/list_pinned_ask_threads", "method": "GET", "body": None},
        {"path": "/rest/thread/list_pinned_ask_threads?version=2.19&source=default", "method": "GET", "body": None},
        {"path": "/rest/thread/list_pinned_ask_threads?version=2.20&source=default", "method": "GET", "body": None},
    ]
    results = []
    for v in variations:
        try:
            r = await page.evaluate(
                """async ({path, method, body}) => {
                    const res = await fetch(path, {
                        method,
                        headers: {'Content-Type': 'application/json'},
                        body: body !== null ? JSON.stringify(body) : undefined,
                    });
                    const txt = await res.text();
                    return {status: res.status, body: txt.slice(0, 500)};
                }""",
                v,
            )
            results.append({**v, "status": r["status"], "body_preview": r["body"]})
            print(f"    [{v['method']} {v['path'][:70]}] -> {r['status']}", flush=True)
        except Exception as e:
            results.append({**v, "error": str(e)[:200]})
            print(f"    [{v['method']} {v['path'][:70]}] ERROR {str(e)[:80]}", flush=True)
    return results


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
            "response_preview": body[:2500] if body else None,
            "response_length": len(body) if body else 0,
        })

    page.on("request", on_request)
    page.on("response", on_response)

    # Warmup
    print("[warmup] home + library...", flush=True)
    await page.goto("https://www.perplexity.ai/", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4000)
    title = await page.title()
    if "moment" in title.lower() or "checking" in title.lower():
        print("  Cloudflare detectado, aguardando 12s...", flush=True)
        await page.wait_for_timeout(12000)

    # Navegar por todas as secoes capturando endpoints
    for label, click_text, fallback_url in SECTIONS:
        current_section["name"] = label
        print(f"\n[nav] {label}", flush=True)
        nav_method = await _nav_section(page, label, click_text, fallback_url)
        await page.wait_for_timeout(WAIT_AFTER_NAV * 1000)
        in_section = [c for c in captured if c.get("section") == label]
        rest_in_section = [c for c in in_section if "/rest/" in c.get("url", "")]
        unique_rest = set(c["url"].split("?")[0] for c in rest_in_section)
        print(f"  [{label}] {len(in_section)} events, {len(rest_in_section)} REST, {len(unique_rest)} endpoints unicos", flush=True)

    # Probe pinned
    print("\n[probe] variacoes de pinned...", flush=True)
    current_section["name"] = "_pinned_probe"
    pinned_results = await _probe_pinned_variations(page)

    OUTPUT.write_text(json.dumps({
        "captured": captured,
        "pinned_probe": pinned_results,
    }, ensure_ascii=False, indent=2))
    print(f"\n{len(captured)} events + {len(pinned_results)} pinned variations -> {OUTPUT}", flush=True)

    # Sumario por secao
    print("\n=== Endpoints REST por secao ===", flush=True)
    for label, _, _ in SECTIONS:
        items = [c for c in captured if c.get("section") == label and "/rest/" in c.get("url", "")]
        urls = {}
        for c in items:
            key = c["url"].split("?")[0].split("/rest/", 1)[-1]
            urls[key] = urls.get(key, {"GET": 0, "POST": 0, "statuses": set()})
            urls[key][c.get("method", "?")] = urls[key].get(c.get("method", "?"), 0) + 1
            if c.get("phase") == "response":
                urls[key]["statuses"].add(c.get("status"))
        print(f"\n  [{label}] {len(urls)} endpoints REST unicos:", flush=True)
        for path, info in sorted(urls.items()):
            stats = info.pop("statuses", set())
            print(f"    {path}", flush=True)
            print(f"      methods: {dict((k, v) for k, v in info.items() if v)}, statuses: {stats}", flush=True)

    print("\n=== Pinned probe results ===", flush=True)
    for r in pinned_results:
        if "error" in r:
            print(f"  {r['method']:5} {r['path'][:80]} -> ERROR {r['error'][:60]}", flush=True)
        else:
            ok = "✓" if 200 <= r["status"] < 300 else " "
            print(f"  {ok} {r['method']:5} {r['path'][:80]} -> {r['status']}", flush=True)

    await context.close()


if __name__ == "__main__":
    asyncio.run(main())
