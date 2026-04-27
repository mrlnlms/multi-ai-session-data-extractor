"""Probe que captura todos os batchexecute requests do Gemini e classifica os rpcids.

Roda Playwright com profile logado, hooka request events, faz acoes tipicas
(carregar sidebar, abrir conversa), coleta rpcids + size + payload preview.

Saida: .tmp/gemini-rpcids-<ts>.json com mapa de {rpcid: {count, sizes, sample_payload}}.

Uso: python scripts/gemini-probe-rpcids.py [--account 1]
"""

import argparse
import asyncio
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright


RPC_RE = re.compile(r"rpcids=([^&]+)")


async def probe(account: int, hold_seconds: int = 20):
    profile_dir = f".storage/gemini-profile-{account}"
    if not Path(profile_dir).exists():
        print(f"Profile nao existe: {profile_dir}")
        print("Rode scripts/gemini-login.py --account", account)
        return

    # Armazena observacoes
    observations: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "sizes": [], "sample_post_body": None, "sample_response": None, "urls": []}
    )
    all_batchexecute: list[dict] = []

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            profile_dir,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()

        # Hook em requests
        def on_request(req):
            url = req.url
            if "batchexecute" in url:
                m = RPC_RE.search(url)
                if m:
                    rpcids = m.group(1).split(",")
                    body = req.post_data
                    for rid in rpcids:
                        obs = observations[rid]
                        obs["count"] += 1
                        obs["urls"].append(url[:200])
                        if obs["sample_post_body"] is None and body:
                            obs["sample_post_body"] = body[:2000]

        async def on_response(resp):
            url = resp.url
            if "batchexecute" in url:
                m = RPC_RE.search(url)
                if m:
                    rpcids = m.group(1).split(",")
                    try:
                        body = await resp.body()
                        size = len(body)
                        body_preview = body[:2000].decode("utf-8", errors="replace")
                        for rid in rpcids:
                            obs = observations[rid]
                            obs["sizes"].append(size)
                            # Guarda o MAIOR response sample por rpcid
                            if not obs.get("sample_response") or size > obs.get("_largest_size", 0):
                                obs["sample_response"] = body_preview
                                obs["_largest_size"] = size
                    except Exception:
                        pass
                    all_batchexecute.append({
                        "rpcids": rpcids,
                        "url": url[:200],
                        "status": resp.status,
                    })

        page.on("request", on_request)
        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        # Acoes: carregar gemini
        print("Navegando pra https://gemini.google.com/app ...")
        await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=60000)
        print(f"Aguardando {hold_seconds}s pra capturar requests da sidebar/home...")
        await page.wait_for_timeout(hold_seconds * 1000)

        # Tenta clicar em uma conversa (se houver)
        try:
            conv_links = await page.evaluate(
                """() => {
                    const items = document.querySelectorAll('a[data-test-id="conversation"]');
                    return Array.from(items).slice(0, 3).map(a => a.getAttribute('href'));
                }"""
            )
            if conv_links:
                print(f"Achou {len(conv_links)} convs. Abrindo a primeira...")
                await page.goto(f"https://gemini.google.com{conv_links[0]}", timeout=30000)
                await page.wait_for_timeout(10 * 1000)
                if len(conv_links) > 1:
                    print("Abrindo segunda conv...")
                    await page.goto(f"https://gemini.google.com{conv_links[1]}", timeout=30000)
                    await page.wait_for_timeout(5 * 1000)
        except Exception as e:
            print(f"Erro navegando convs: {e}")

        await context.close()

    # Salva relatorio
    outdir = Path(".tmp")
    outdir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    outpath = outdir / f"gemini-rpcids-{ts}.json"

    # Ordena por count desc
    sorted_obs = sorted(observations.items(), key=lambda x: -x[1]["count"])

    report = {
        "captured_at": ts,
        "account": account,
        "total_batchexecute_requests": len(all_batchexecute),
        "unique_rpcids": len(observations),
        "rpcids": {rid: {**obs, "urls": obs["urls"][:3]} for rid, obs in sorted_obs},
    }
    outpath.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nRelatorio salvo em {outpath}")

    # Resumo bonito
    print(f"\n=== {len(observations)} rpcids unicos em {len(all_batchexecute)} requests ===")
    for rid, obs in sorted_obs[:20]:
        avg_size = sum(obs["sizes"]) / len(obs["sizes"]) if obs["sizes"] else 0
        max_size = max(obs["sizes"]) if obs["sizes"] else 0
        print(f"  {rid}: {obs['count']}x | avg {avg_size:.0f}B max {max_size:.0f}B")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", type=int, default=1, choices=[1, 2])
    parser.add_argument("--hold", type=int, default=20, help="Seconds to wait on homepage")
    args = parser.parse_args()
    asyncio.run(probe(args.account, args.hold))
