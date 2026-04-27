"""Probe: captura requests ao clicar num mind map no NotebookLM.

Abre um notebook conhecido com mind map, clica no botao "Mind Map" na sidebar,
e dumpa todos os batchexecute + outros requests pra identificar o endpoint/rpcid.

Uso: PYTHONPATH=. python scripts/notebooklm-probe-mindmap.py --account hello
"""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.notebooklm.auth import load_context, VALID_ACCOUNTS


# Notebook UUID conhecido com mind map
NOTEBOOK_UUIDS = {
    "hello": "53bf6eff-8ca5-4f14-be09-d33b0bd95019",  # UXR & Hotjar
    "marloon": "03710081-d75b-4abf-9f18-c4a17c4ecb21",  # UX Evaluation: Internet Banking
}


async def main(account: str):
    out_dir = Path(".tmp")
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_path = out_dir / f"notebooklm-mindmap-probe-{ts}.json"

    nb_uuid = NOTEBOOK_UUIDS[account]
    context = await load_context(account, headless=False)  # HEADFULL pra interagir
    try:
        page = await context.new_page()
        captured: dict[str, dict] = {}  # key: id sequencial

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
            key = f"{len(captured):03d}"
            captured[key] = {
                "url": url[:300],
                "method": res.request.method,
                "post": post[:5000],
                "status": res.status,
                "response_preview": body[:3000],
            }

        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        print(f"Abrindo notebook {nb_uuid[:8]}...")
        await page.goto(f"https://notebooklm.google.com/notebook/{nb_uuid}", wait_until="domcontentloaded")
        print("\n>>> Clique no 'Mind Map' na sidebar direita (studio panel) AGORA.")
        print(">>> Depois clique em um no do mind map pra expandir.")
        print(">>> Voce tem 60s...")
        await page.wait_for_timeout(60000)

        # Salva captured
        out_path.write_text(json.dumps(captured, indent=2, ensure_ascii=False))
        print(f"\n{len(captured)} responses capturados em {out_path}")
        # Lista rpcids unicos
        rpcids = set()
        for c in captured.values():
            url = c["url"]
            if "rpcids=" in url:
                rpcids.update(url.split("rpcids=")[1].split("&")[0].split(","))
        print(f"rpcids vistos: {sorted(rpcids)}")
        # Mostra quais responses tem 'mind' ou o mm_uuid
        mm_uuid = "d045c2af"  # do nb 53bf6eff
        for key, c in captured.items():
            r = c.get("response_preview", "") or ""
            if "mind" in r.lower() or mm_uuid in r:
                rpc = c["url"].split("rpcids=")[1].split("&")[0] if "rpcids=" in c["url"] else "?"
                print(f"  [{key}] rpcid={rpc} — contem mind/mm_uuid (prev len: {len(r)})")
    finally:
        await context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True, choices=list(VALID_ACCOUNTS))
    args = parser.parse_args()
    asyncio.run(main(args.account))
