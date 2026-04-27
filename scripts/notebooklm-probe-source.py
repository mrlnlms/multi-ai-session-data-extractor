"""Probe focado: qual RPC busca source guide (brief + tags) + conteudo extraido.

Estrategia:
  1. Carrega notebook conhecido, espera RPCs iniciais
  2. Marca timestamp de "fim da carga inicial"
  3. CLICA num source pela primeira vez
  4. Registra os RPCs que aparecem APOS o clique (os mais interessantes)

Saida lista todos os RPCs em ordem cronologica com marcador de fase.
"""

import asyncio
import json
import re
import time
from pathlib import Path

from playwright.async_api import async_playwright


STORAGE = Path.home() / ".notebooklm" / "storage_state.json"
TARGET_UUID = "03009b16-b3b0-4c8b-98e9-e8dd1cc5d686"  # Data Synthesis for Everyone


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
        depth = 0; start = pos; in_str = False; esc = False
        while pos < len(body):
            ch = body[pos]
            if esc: esc = False
            elif ch == "\\" and in_str: esc = True
            elif ch == '"': in_str = not in_str
            elif not in_str:
                if ch == "[": depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0: pos += 1; break
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

        # Log em ordem temporal com fase
        timeline: list[dict] = []
        current_phase = {"name": "initial-load"}

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
                timeline.append({
                    "ts": time.time(),
                    "phase": current_phase["name"],
                    "rpcid": rpcid,
                    "size": size,
                    "data_preview": json.dumps(data, ensure_ascii=False, default=str)[:800] if data else None,
                    "post_body": (post or "")[:300],
                })

        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        url = f"https://notebooklm.google.com/notebook/{TARGET_UUID}"
        print(f"[phase=initial-load] Abrindo: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(10000)
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
        await page.wait_for_timeout(3000)

        initial_count = len(timeline)
        print(f"\n[phase=initial-load done] {initial_count} RPCs capturados\n")

        # Pede pro user clicar manualmente
        current_phase["name"] = "click-source"
        print("\n" + "=" * 60)
        print("AGORA CLIQUE EM QUALQUER SOURCE NO NOTEBOOK.")
        print("Você tem 40 segundos. Eu capturo os RPCs novos.")
        print("=" * 60)
        await page.wait_for_timeout(40000)

        click_count = len(timeline) - initial_count
        print(f"\n[click-source done] {click_count} novos RPCs capturados\n")

        # Relatorio: agrupa por phase + rpcid
        print("=" * 70)
        print("TIMELINE POR RPCID")
        print("=" * 70)
        by_phase_rpc: dict = {}
        for t in timeline:
            k = (t["phase"], t["rpcid"])
            if k not in by_phase_rpc or t["size"] > by_phase_rpc[k]["size"]:
                by_phase_rpc[k] = t

        # Print por phase
        for phase in ("initial-load", "click-source"):
            print(f"\n--- phase: {phase} ---")
            phase_rpcs = [(k, v) for k, v in by_phase_rpc.items() if k[0] == phase]
            phase_rpcs.sort(key=lambda x: -x[1]["size"])
            for (_, rid), info in phase_rpcs:
                print(f"  {rid} ({info['size']}B)")
                if info["size"] > 100:
                    print(f"    post: {info['post_body'][:120]!r}")
                    print(f"    resp: {(info['data_preview'] or '?')[:220]!r}")

        outp = Path(".tmp") / f"notebooklm-source-probe-{int(time.time())}.json"
        outp.parent.mkdir(exist_ok=True)
        outp.write_text(json.dumps(timeline, ensure_ascii=False, indent=2, default=str))
        print(f"\nTimeline salvo em: {outp}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
