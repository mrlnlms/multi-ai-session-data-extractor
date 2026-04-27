"""V2: Captura TODOS os requests (nao so batchexecute) durante click em source.

Tambem faz o click programaticamente via JS (mais confiavel que Playwright selector).
"""

import asyncio
import json
import re
import time
from pathlib import Path

from playwright.async_api import async_playwright


STORAGE = Path.home() / ".notebooklm" / "storage_state.json"
TARGET_UUID = "03009b16-b3b0-4c8b-98e9-e8dd1cc5d686"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            storage_state=str(STORAGE),
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        current_phase = {"name": "initial"}
        all_requests: list[dict] = []

        async def on_response(resp):
            url = resp.url
            # Filtra apenas APIs (nao CSS/JS/img genericos)
            # Mas captura batchexecute E qualquer endpoint notebooklm.google.com/_*
            is_api = (
                "batchexecute" in url
                or "/notebooklm.google.com/_" in url
                or "/notebooklm-pa" in url
                or "/api/" in url
            )
            if not is_api:
                return
            try:
                size = int(resp.headers.get("content-length") or 0)
                if size == 0:
                    body = await resp.body()
                    size = len(body)
            except Exception:
                size = 0
            all_requests.append({
                "ts": time.time(),
                "phase": current_phase["name"],
                "method": resp.request.method,
                "url": url[:250],
                "status": resp.status,
                "size": size,
                "content_type": resp.headers.get("content-type", ""),
            })

        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        url = f"https://notebooklm.google.com/notebook/{TARGET_UUID}"
        print(f"[initial] Abrindo: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(12000)
        initial_count = len(all_requests)
        print(f"[initial done] {initial_count} requests")

        # Tenta descobrir seletor dos sources inspecionando DOM
        current_phase["name"] = "click-source"
        print("\n[click-source] descobrindo sources via DOM inspection...")
        sources_info = await page.evaluate("""() => {
            // Busca todos elementos que podem ser source items
            const results = [];
            // Tenta varios locators: role=listitem em sidebar
            const possible = document.querySelectorAll('[role="listitem"], [role="row"], label');
            for (const el of possible) {
                const text = el.innerText?.trim() || '';
                if (text && (text.includes('.md') || text.includes('.pdf') || text.includes('.txt'))) {
                    results.push({
                        text: text.substring(0, 100),
                        tag: el.tagName,
                        role: el.getAttribute('role'),
                        className: el.className?.substring(0, 80),
                    });
                }
                if (results.length >= 5) break;
            }
            return results;
        }""")
        print(f"  achou {len(sources_info)} possiveis sources:")
        for s in sources_info[:3]:
            print(f"    {s}")

        # Clica no primeiro
        if sources_info:
            print(f"\n  Clicando via JS...")
            click_result = await page.evaluate("""() => {
                const possible = document.querySelectorAll('[role="listitem"], [role="row"], label');
                for (const el of possible) {
                    const text = el.innerText?.trim() || '';
                    if (text.includes('.md') || text.includes('.pdf')) {
                        el.click();
                        return {clicked: true, text: text.substring(0, 80)};
                    }
                }
                return {clicked: false};
            }""")
            print(f"  Click result: {click_result}")
            await page.wait_for_timeout(8000)

        click_count = len(all_requests) - initial_count
        print(f"\n[click-source done] {click_count} novos requests\n")

        # Relatorio
        print("=" * 70)
        print("NOVOS REQUESTS NA FASE click-source")
        print("=" * 70)
        click_requests = [r for r in all_requests if r["phase"] == "click-source"]
        click_requests.sort(key=lambda x: -x["size"])
        for r in click_requests[:20]:
            path = r["url"].replace("https://notebooklm.google.com", "")
            print(f"  {r['status']} {r['method']} {path[:100]} ({r['size']}B, {r['content_type']})")

        outp = Path(".tmp") / f"notebooklm-allreqs-{int(time.time())}.json"
        outp.write_text(json.dumps(all_requests, ensure_ascii=False, indent=2))
        print(f"\nSalvo em: {outp}")

        # Deixa browser aberto por 5s pra user confirmar visualmente
        print("\nEsperando 5s antes de fechar...")
        await page.wait_for_timeout(5000)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
