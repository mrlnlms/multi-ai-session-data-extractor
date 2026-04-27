"""Probe: captura TODOS os requests batchexecute enquanto voce gera cada tipo de output.

Uso:
    PYTHONPATH=. python scripts/notebooklm-probe-generators.py \\
        --account hello --notebook 86b0d03b-95c7-4394-8be0-433ce10b84e8

Workflow:
1. Abre o notebook headful
2. Voce clica em "Generate" em cada tipo: Mind Map, Slide Deck, Reports, Flashcards,
   Quiz, Infographic, Data Table — UM POR VEZ, esperando cada um terminar
3. Tem 5min (300s) de captura
4. Ao final, tudo salvo em .tmp/notebooklm-generators-probe-<ts>.json
"""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.notebooklm.auth import load_context, VALID_ACCOUNTS


async def main(account: str, notebook_uuid: str, minutes: int):
    out_dir = Path(".tmp")
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_path = out_dir / f"notebooklm-generators-probe-{ts}.json"

    context = await load_context(account, headless=False)
    try:
        page = await context.new_page()
        captured: list[dict] = []

        async def on_response(res):
            url = res.url
            if "notebooklm.google.com" not in url or "batchexecute" not in url:
                return
            try:
                post = res.request.post_data or ""
            except Exception:
                post = ""
            try:
                body = await res.text()
            except Exception:
                body = ""
            captured.append({
                "seq": len(captured),
                "timestamp": datetime.now().isoformat(),
                "url": url[:300],
                "method": res.request.method,
                "status": res.status,
                "post": post[:6000],
                "response": body[:10000],
            })

        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        print(f"\n>>> Abrindo notebook {notebook_uuid[:8]}...")
        await page.goto(
            f"https://notebooklm.google.com/notebook/{notebook_uuid}",
            wait_until="domcontentloaded",
        )
        await page.wait_for_timeout(3000)

        total_secs = minutes * 60
        print(f"\n{'='*60}")
        print(f"PROBE ATIVO por {minutes}min ({total_secs}s).")
        print(f"Clique em cada 'Generate' UM POR VEZ, espere terminar antes do proximo.")
        print(f"Ordem sugerida: Mind Map -> Slide Deck -> Reports ->")
        print(f"                Flashcards -> Quiz -> Infographic -> Data Table")
        print(f"Saida: {out_path}")
        print(f"{'='*60}\n")

        # Mostra contagem no terminal a cada 30s
        for i in range(minutes * 2):
            await page.wait_for_timeout(30000)
            remaining = total_secs - (i + 1) * 30
            print(f"  [{(i+1)*30}s/{total_secs}s] capturados {len(captured)} requests, {remaining}s restantes")

        out_path.write_text(json.dumps(captured, indent=2, ensure_ascii=False))
        print(f"\n>>> Fim. {len(captured)} requests capturados em {out_path}")

        # Lista rpcids com contagem
        from collections import Counter
        rpcids = Counter()
        for c in captured:
            url = c["url"]
            if "rpcids=" in url:
                for r in url.split("rpcids=")[1].split("&")[0].split(","):
                    rpcids[r] += 1
        print(f"\nrpcids vistos ({len(rpcids)}):")
        for r, c in rpcids.most_common():
            print(f"  {c:3}x  {r}")
    finally:
        await context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True, choices=list(VALID_ACCOUNTS))
    parser.add_argument("--notebook", required=True, help="UUID do notebook")
    parser.add_argument("--minutes", type=int, default=5, help="Duracao do probe (default 5min)")
    args = parser.parse_args()
    asyncio.run(main(args.account, args.notebook, args.minutes))
