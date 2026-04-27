"""Probe focado nos rpcids novos descobertos + procura RPC de source download.

Interage com a UI do notebook pra disparar RPCs que so rodam em actions:
  - Clica num source pra ver se tem RPC de fetch/download
  - Clica em add source (sem confirmar)
  - Expande mind map se houver
"""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright


STORAGE = Path.home() / ".notebooklm" / "storage_state.json"
TARGET_UUID = "03009b16-b3b0-4c8b-98e9-e8dd1cc5d686"


def _parse(body: str) -> list:
    if body.startswith(")]}'"):
        body = body[4:].lstrip()
    results = []
    pos = 0
    while pos < len(body):
        while pos < len(body) and body[pos] in "\r\n \t":
            pos += 1
        if pos >= len(body): break
        m = re.match(r"\d+", body[pos:])
        if not m: break
        pos += len(m.group()) + 1
        depth = 0
        start = pos
        in_str = False; esc = False
        while pos < len(body):
            ch = body[pos]
            if esc: esc = False
            elif ch == "\\" and in_str: esc = True
            elif ch == '"': in_str = not in_str
            elif not in_str:
                if ch == "[": depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        pos += 1
                        break
            pos += 1
        try:
            block = json.loads(body[start:pos])
        except Exception:
            break
        for item in block:
            if isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr":
                try:
                    inner = json.loads(item[2]) if item[2] else None
                except Exception:
                    inner = item[2]
                results.append((item[1], inner))
    return results


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

        # Captura MAIOR payload por rpcid + url + post body
        captured: dict[str, dict] = {}

        async def on_response(resp):
            if "batchexecute" not in resp.url:
                return
            req = resp.request
            try:
                body = await resp.text()
                post = req.post_data
            except Exception:
                return
            rpcids_in_url = []
            m = re.search(r"rpcids=([^&]+)", resp.url)
            if m:
                rpcids_in_url = m.group(1).split(",")
            for rpcid, data in _parse(body):
                size = len(json.dumps(data, default=str)) if data else 0
                if rpcid not in captured or size > captured[rpcid]["size"]:
                    captured[rpcid] = {
                        "size": size,
                        "data_preview": json.dumps(data, ensure_ascii=False, default=str)[:1500] if data is not None else None,
                        "post_body": (post or "")[:400],
                        "url_rpcids": rpcids_in_url,
                    }

        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        url = f"https://notebooklm.google.com/notebook/{TARGET_UUID}"
        print(f"Abrindo: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(8000)

        # Expande Studio se colapsado
        try:
            studio = page.locator("section.studio-panel").first
            cls = await studio.get_attribute("class") if studio else ""
            if cls and "panel-collapsed" in cls:
                header = studio.locator(".panel-header").first
                if await header.is_visible():
                    await header.click()
                    await page.wait_for_timeout(5000)
        except Exception:
            pass

        # Tenta clicar num SOURCE (list item) pra disparar RPC de source fetch
        try:
            print("Tentando clicar em um source...")
            # Sources ficam na sidebar esquerda, geralmente panel-source
            source_items = page.locator('button[aria-label*="source" i], button[aria-label*="fonte" i]')
            n = await source_items.count()
            print(f"  Source buttons visiveis: {n}")
            if n > 0:
                await source_items.first.click()
                await page.wait_for_timeout(3000)
        except Exception as e:
            print(f"  clique em source falhou: {e}")

        # Tenta clicar em mind map (se existir)
        try:
            print("Tentando abrir mind map...")
            mind = page.locator('button[aria-label*="Mind map" i], button[aria-label*="Mapa mental" i]').first
            if await mind.is_visible():
                await mind.click()
                await page.wait_for_timeout(5000)
        except Exception:
            pass

        await page.wait_for_timeout(3000)

        # Relatorio
        known = {"rLM1Ne", "VfAZjd", "khqZz", "cFji9", "gArtLc", "wXbhsf"}
        print(f"\n=== {len(captured)} rpcids capturados ===\n")
        # Ordem por tamanho (payloads maiores sao mais interessantes)
        sorted_rpcids = sorted(captured.items(), key=lambda x: -x[1]["size"])

        print("JA CONHECIDOS:")
        for rid, info in sorted_rpcids:
            if rid in known:
                print(f"  {rid} ({info['size']}B): {info['data_preview'][:150]!r}...")
        print()
        print("NOVOS (investigar):")
        for rid, info in sorted_rpcids:
            if rid in known:
                continue
            print(f"  {rid} ({info['size']}B)")
            print(f"    post_body: {info['post_body'][:150]!r}")
            print(f"    response: {(info['data_preview'] or '?')[:300]!r}")
            print()

        # Salva relatorio completo pra inspeccao
        outdir = Path(".tmp")
        outdir.mkdir(exist_ok=True)
        outp = outdir / f"notebooklm-new-rpcids-{datetime.now():%Y%m%dT%H%M%S}.json"
        with open(outp, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in captured.items()}, f, ensure_ascii=False, indent=2, default=str)
        print(f"Relatorio: {outp}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
