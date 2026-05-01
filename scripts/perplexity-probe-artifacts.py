"""Probe /library?tab=artifacts e tab=threads pra mapear endpoints proprios."""

import asyncio
import json
from pathlib import Path
from playwright.async_api import Request, Response

from src.extractors.perplexity.auth import load_context

OUTPUT = Path("/tmp/perplexity-artifacts-probe.json")


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
            "body": (body or "")[:3000],
            "len": len(body) if body else 0,
        })

    page.on("response", on_resp)

    # Warmup
    await page.goto("https://www.perplexity.ai/", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(4000)

    for tab in ["artifacts", "threads"]:
        section["name"] = f"library_{tab}"
        url = f"https://www.perplexity.ai/library?tab={tab}"
        print(f"\n[nav] {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(7000)
        except Exception as e:
            print(f"  ERRO: {str(e)[:120]}")
            continue

        in_sec = [c for c in captured if c.get("section") == section["name"]]
        unique = sorted(set(c["url"].split("?")[0].split("/rest/", 1)[-1] for c in in_sec if "/rest/" in c["url"]))
        print(f"  {len(in_sec)} XHRs REST, {len(unique)} unicos:")
        for u in unique:
            matches = [c for c in in_sec if c["url"].split("?")[0].endswith(u)]
            statuses = sorted(set(c["status"] for c in matches))
            print(f"    [{statuses}] {u}")

    # Procurar endpoints chutados de artifacts
    print(f"\n[probe] endpoints chutados pra artifacts...")
    candidates = [
        "/rest/artifacts/list",
        "/rest/artifacts/list_user_artifacts",
        "/rest/artifact/list",
        "/rest/library/artifacts",
        "/rest/user/artifacts",
    ]
    for path in candidates:
        try:
            r = await page.evaluate(
                """async (p) => {
                    const res = await fetch(p);
                    return {status: res.status, body: (await res.text()).slice(0, 500)};
                }""", path
            )
            ok = "✓" if 200 <= r["status"] < 300 else " "
            print(f"  {ok} GET  {path[:80]} -> {r['status']}")
            if 200 <= r["status"] < 300:
                print(f"    body: {r['body'][:300]}")
        except Exception as e:
            print(f"    GET  {path[:80]} ERROR {str(e)[:60]}")

    OUTPUT.write_text(json.dumps(captured, ensure_ascii=False, indent=2))
    print(f"\nDump em {OUTPUT}")
    await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
