"""Probe: URL de audio do gArtLc baixa direto via fetch? Ou so via UI?

Carrega 1 notebook, intercepta gArtLc, extrai URL de audio, tenta 3 variantes de fetch:
  1. GET direto sem cookies
  2. GET com cookies do context
  3. GET com Referer do notebook

Se qualquer variante retornar audio/mpeg bytes > 10KB, extractor 100% API viavel.
"""

import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright


STORAGE = Path.home() / ".notebooklm" / "storage_state.json"
TARGET_UUID = "03009b16-b3b0-4c8b-98e9-e8dd1cc5d686"


def _parse_rpc_response(body: str) -> list:
    """Parse batchexecute envelope, extrai (rpcid, data)."""
    if body.startswith(")]}'"):
        body = body[4:].lstrip()
    results = []
    pos = 0
    while pos < len(body):
        while pos < len(body) and body[pos] in "\r\n \t":
            pos += 1
        if pos >= len(body):
            break
        m = re.match(r"\d+", body[pos:])
        if not m:
            break
        pos += len(m.group()) + 1
        depth = 0
        start = pos
        in_str = False
        esc = False
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
    if not STORAGE.exists():
        print(f"Storage state ausente: {STORAGE}. Precisa relogar.")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # Tentativa 1 headful (primeira run)
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            storage_state=str(STORAGE),
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        rpc_data: dict[str, object] = {}

        async def on_response(resp):
            if "batchexecute" not in resp.url:
                return
            try:
                body = await resp.text()
            except Exception:
                return
            for rpcid, data in _parse_rpc_response(body):
                # Guarda o MAIOR payload por rpcid
                if rpcid not in rpc_data or len(str(data)) > len(str(rpc_data[rpcid])):
                    rpc_data[rpcid] = data

        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        url = f"https://notebooklm.google.com/notebook/{TARGET_UUID}"
        print(f"Abrindo: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(10000)

        # Expandir Studio se colapsado
        try:
            studio = page.locator("section.studio-panel").first
            cls = await studio.get_attribute("class") if studio else ""
            if cls and "panel-collapsed" in cls:
                header = studio.locator(".panel-header").first
                if await header.is_visible():
                    await header.click()
                    await page.wait_for_timeout(8000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)

        print(f"\nRPCs capturados: {sorted(rpc_data.keys())}")

        # Extrai URL de audio de gArtLc
        gartlc = rpc_data.get("gArtLc")
        if not gartlc:
            print("gArtLc não apareceu — notebook pode estar sem Audio Overview renderizado")
            await browser.close()
            return

        # Serializa e busca URLs
        serialized = json.dumps(gartlc, ensure_ascii=False)
        urls = re.findall(
            r"https://lh3\.googleusercontent\.com/notebooklm/[^\s'\"\\,]+",
            serialized,
        )
        print(f"\nURLs de audio encontradas em gArtLc: {len(urls)}")
        if not urls:
            # Tenta padrao mais amplo
            urls = re.findall(r"https://[^\s'\"\\,]+(?:\.m4a|\.mp4|audio)[^\s'\"\\,]*", serialized)
            print(f"  (fallback pattern: {len(urls)} urls)")
        for u in urls[:3]:
            print(f"  {u[:200]}")

        if not urls:
            print("Nenhuma URL extraída — mostrando gArtLc bruto pra inspeção:")
            print(json.dumps(gartlc, indent=2, ensure_ascii=False)[:2000])
            await browser.close()
            return

        target_url = urls[0].replace("\\u003d", "=").replace("\\u0026", "&")
        print(f"\n=== TESTING DIRECT FETCH ===\nURL: {target_url[:150]}")

        # Variante 1: context.request.get (usa cookies do context)
        print("\n[1] context.request.get (com cookies):")
        r1 = await context.request.get(target_url)
        body1 = await r1.body() if r1.ok else b""
        print(f"    status={r1.status} content-type={r1.headers.get('content-type', '?')} size={len(body1)}B")
        if body1:
            print(f"    first 20 bytes: {body1[:20]!r}")

        # Variante 2: com Referer do notebook
        print("\n[2] context.request.get (com Referer do notebook):")
        r2 = await context.request.get(target_url, headers={"Referer": url})
        body2 = await r2.body() if r2.ok else b""
        print(f"    status={r2.status} content-type={r2.headers.get('content-type', '?')} size={len(body2)}B")

        # Variante 3: browser fetch via page.evaluate (mais parecido com UI)
        print("\n[3] page.evaluate(fetch):")
        try:
            result = await page.evaluate(
                """async (u) => {
                    const r = await fetch(u);
                    return {status: r.status, type: r.headers.get('content-type'), size: (await r.blob()).size};
                }""",
                target_url,
            )
            print(f"    {result}")
        except Exception as e:
            print(f"    ERRO: {e}")

        # Conclusao
        print("\n=== CONCLUSAO ===")
        if body1 and len(body1) > 10000 and b"audio" in r1.headers.get("content-type", "").encode():
            print("SUCESSO variante 1 — audio baixa direto com cookies do context")
        elif body2 and len(body2) > 10000:
            print("SUCESSO variante 2 — audio baixa com Referer")
        else:
            print("Nenhuma variante retornou audio real — precisa UI click")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
