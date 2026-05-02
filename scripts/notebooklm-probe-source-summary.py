"""Probe: descobre RPC que retorna source-level summary + tags.

Abre 1 notebook, clica num source via JS, captura TODOS os batchexecute
requests. Identifica RPCs novos vs ja mapeados em api_client.py.

Uso: PYTHONPATH=. .venv/bin/python scripts/notebooklm-probe-source-summary.py
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.notebooklm.auth import load_context


# Notebook + source pra abrir
NB_UUID = "cf11ac40-5aa4-47d3-bf4d-a38289730be8"
SRC_UUID = "05b6dec2-ead6-40a9-8acc-10f31ce5b6ef"


# RPCs ja conhecidos — pra filtrar e destacar novos
KNOWN_RPCS = {
    "wXbhsf", "ub2Bae", "rLM1Ne", "VfAZjd", "khqZz",
    "cFji9", "gArtLc", "v9rmvd", "CYK0Xb", "hPTbtc", "hizoJc",
}


async def main():
    out_dir = Path(".tmp")
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_path = out_dir / f"notebooklm-source-summary-probe-{ts}.json"

    # HEADED pra ver o que tá acontecendo + permitir click se JS falhar
    context = await load_context("1", headless=False)
    try:
        page = await context.new_page()
        captured: list[dict] = []
        phase = ["initial"]

        async def on_response(res):
            url = res.url
            if "notebooklm.google.com" not in url:
                return
            if "batchexecute" not in url:
                return
            try:
                post = res.request.post_data or ""
                body = await res.text()
            except Exception:
                return
            # Extrai rpcids do URL
            m = re.search(r"rpcids=([^&]+)", url)
            rpcids = m.group(1).split(",") if m else []
            entry = {
                "phase": phase[0],
                "rpcids": rpcids,
                "post_preview": post[:1500],
                "body_preview": body[:3000],
                "body_len": len(body),
            }
            captured.append(entry)

        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        print(f"Abrindo notebook {NB_UUID[:8]}...")
        phase[0] = "load_notebook"
        await page.goto(
            f"https://notebooklm.google.com/notebook/{NB_UUID}",
            wait_until="domcontentloaded",
        )
        # Espera carregar tudo
        await page.wait_for_timeout(5000)

        print(f"Clicando no source {SRC_UUID[:8]}...")
        phase[0] = "click_source"

        # Procura source pelo data-attribute ou texto
        # NotebookLM usa shadow DOM em alguns lugares — vamos tentar via JS
        js_click = """
        () => {
            // Procura qualquer elemento com texto/atributo do source
            const all = document.querySelectorAll('*');
            for (const el of all) {
                const text = el.textContent || '';
                const attrs = Array.from(el.attributes || []).map(a => a.value).join(' ');
                if (attrs.includes('05b6dec2') || (text.length < 200 && text.includes('Survey Analysis'))) {
                    el.click();
                    return el.tagName + ': ' + text.slice(0, 80);
                }
            }
            return 'NOT_FOUND';
        }
        """
        result = await page.evaluate(js_click)
        print(f"  Click result: {result}")

        # Espera 60s pra user clicar manualmente em um source (caso JS nao tenha funcionado)
        print("\n>>> AGORA: clica em UM source na sidebar esquerda do notebook")
        print(">>> Espera o painel do Source guide carregar (~3-5s) na sidebar direita")
        print(">>> Voce tem 60s...")
        await page.wait_for_timeout(60000)

        print(f"\nCaptured {len(captured)} responses")
        rpcs_seen = set()
        for c in captured:
            rpcs_seen.update(c["rpcids"])
        unknown = rpcs_seen - KNOWN_RPCS
        print(f"RPCs vistos: {sorted(rpcs_seen)}")
        print(f"RPCs NOVOS (nao mapeados): {sorted(unknown)}")

        # Salva pra analise
        out_path.write_text(json.dumps(captured, indent=2, ensure_ascii=False))
        print(f"\nSalvou em {out_path}")

        # Pra cada RPC novo, mostra preview
        for c in captured:
            for rpcid in c["rpcids"]:
                if rpcid in unknown:
                    print(f"\n=== RPC NOVO {rpcid} (phase={c['phase']}) ===")
                    print(f"POST: {c['post_preview'][:600]}")
                    print(f"BODY: {c['body_preview'][:600]}")

    finally:
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
