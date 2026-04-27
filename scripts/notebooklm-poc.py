"""POC: abre um notebook no NotebookLM e captura todos os payloads da API interna."""

import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

STORAGE_STATE = Path.home() / ".notebooklm" / "storage_state.json"
OUTPUT_DIR = Path("data/raw/notebooklm-poc")

# Notebook de teste — primeiro do inventario (hello.marlonlemes)
DEFAULT_UUID = "1858be29-9c27-4c14-a4ce-e463990c7044"


def main():
    uuid = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_UUID
    url = f"https://notebooklm.google.com/notebook/{uuid}"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=str(STORAGE_STATE))
        page = context.new_page()

        # Interceptar TODAS as responses
        def on_response(response):
            req_url = response.url
            status = response.status
            method = response.request.method

            # Capturar batchexecute e qualquer API relevante
            if any(kw in req_url for kw in ["batchexecute", "notebook", "audio", "source", "note"]):
                try:
                    body = response.text()
                except Exception:
                    body = "<binary or failed>"

                entry = {
                    "url": req_url,
                    "method": method,
                    "status": status,
                    "content_type": response.headers.get("content-type", ""),
                    "body_length": len(body) if isinstance(body, str) else 0,
                    "body_preview": body[:2000] if isinstance(body, str) else "",
                    "body": body if isinstance(body, str) else "",
                }
                captured.append(entry)
                print(f"  [{status}] {method} {req_url[:120]} ({entry['body_length']} bytes)")

        page.on("response", on_response)

        print(f"Abrindo {url} ...")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # Esperar requests iniciais carregarem
        page.wait_for_timeout(10000)

        # Tentar expandir sections (sources, notes, chat) se existirem
        # Clicar em tabs/buttons que possam carregar mais dados
        for label in ["Sources", "Fontes", "Chat", "Notes", "Notas", "Audio Overview"]:
            try:
                btn = page.get_by_text(label, exact=False).first
                if btn and btn.is_visible():
                    print(f"  Clicando em '{label}'...")
                    btn.click()
                    page.wait_for_timeout(3000)
            except Exception:
                pass

        # Scroll no painel principal pra provocar lazy loading
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
        except Exception:
            pass

        browser.close()

    # Salvar resultados
    out_file = OUTPUT_DIR / f"poc-{uuid[:8]}.json"
    with open(out_file, "w") as f:
        json.dump(captured, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"Capturadas {len(captured)} responses")
    print(f"Salvo em {out_file}")

    # Resumo por tipo
    print(f"\nResumo:")
    for entry in captured:
        ct = entry["content_type"].split(";")[0]
        print(f"  {entry['method']:4} {entry['status']} {ct:40} {entry['body_length']:>8} bytes  {entry['url'][:100]}")


if __name__ == "__main__":
    main()
