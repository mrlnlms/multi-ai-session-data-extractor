"""Probe abrangente: tabs do topo (Discover/Finance/Health/Academic/Patents)
+ endpoints /rest/user/*. Mapeia tudo que pode ser captured."""

import asyncio
import json
from pathlib import Path
from playwright.async_api import Request, Response
from src.extractors.perplexity.auth import load_context

OUTPUT = Path("/tmp/perplexity-tabs-user-probe.json")


def _capture(url: str) -> bool:
    return "perplexity.ai/rest/" in url.lower()


async def main():
    ctx = await load_context(headless=False)
    page = await ctx.new_page()
    captured: list[dict] = []
    section = {"name": "init"}

    async def on_resp(r):
        if not _capture(r.url):
            return
        try:
            body = await r.text()
        except Exception:
            body = None
        captured.append({
            "section": section["name"],
            "method": r.request.method,
            "url": r.url,
            "status": r.status,
            "body": (body or "")[:2500],
            "len": len(body) if body else 0,
        })

    page.on("response", on_resp)

    # Warmup
    await page.goto("https://www.perplexity.ai/", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(4000)

    # Tabs do topo
    for tab in ["discover", "finance", "health", "academic", "patents"]:
        section["name"] = f"tab_{tab}"
        url = f"https://www.perplexity.ai/{tab}"
        print(f"\n[nav] {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(6000)
        except Exception as e:
            print(f"  ERRO: {str(e)[:100]}")
            continue

        in_sec = [c for c in captured if c.get("section") == section["name"]]
        unique = sorted(set(c["url"].split("?")[0].split("/rest/", 1)[-1] for c in in_sec if "/rest/" in c["url"]))
        print(f"  {len(in_sec)} XHRs, {len(unique)} unicos:")
        for u in unique:
            matches = [c for c in in_sec if c["url"].split("?")[0].endswith(u)]
            statuses = sorted(set(c["status"] for c in matches))
            print(f"    [{statuses}] {u}")

    # Probas de user endpoints
    section["name"] = "user_endpoints"
    print(f"\n[probe] user endpoints chutados...")
    candidates = [
        "/rest/user/info",
        "/rest/user/settings",
        "/rest/user/get_user_ai_profile",
        "/rest/user/notifications",
        "/rest/user/billing/credits",
        "/rest/user/preferences",
        "/rest/user/saved_searches",
        "/rest/user/memory",
        "/rest/user/history",
        "/rest/user/exports",
    ]
    for path in candidates:
        try:
            r = await page.evaluate(
                """async (p) => {
                    const res = await fetch(p);
                    return {status: res.status, body: (await res.text()).slice(0, 600)};
                }""", path
            )
            ok = "✓" if 200 <= r["status"] < 300 else " "
            print(f"  {ok} GET  {path[:60]} -> {r['status']}")
            if 200 <= r["status"] < 300 and r['body'] != '[]' and r['body'] != '{}':
                print(f"    body: {r['body'][:200]}")
        except Exception as e:
            print(f"    GET  {path[:60]} ERROR {str(e)[:60]}")

    OUTPUT.write_text(json.dumps(captured, ensure_ascii=False, indent=2))
    print(f"\nDump em {OUTPUT}")
    await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
