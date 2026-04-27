"""Download de conteudo completo dos notebooks do NotebookLM via Playwright.

Extrai chat, audio overviews, notes e metadados de cada notebook,
organizando por conta/uuid.

Uso:
    notebooklm login  # autenticar na conta Google
    python scripts/notebooklm-download.py --account more.design
    python scripts/notebooklm-download.py --account marloonlemes
    python scripts/notebooklm-download.py --account hello.marlonlemes
    python scripts/notebooklm-download.py --account more.design --uuid <uuid>  # um so
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

# Paths
STORAGE_STATE = Path.home() / ".notebooklm" / "storage_state.json"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "NotebookLM Data"
INVENTARIOS = {
    "more.design": PROJECT_ROOT / "docs" / "research" / "notebooklm-inventario-more-design.md",
    "marloonlemes": PROJECT_ROOT / "docs" / "research" / "notebooklm-inventario-marloonlemes.md",
    "hello.marlonlemes": PROJECT_ROOT / "docs" / "research" / "notebooklm-inventario.md",
}

# RPC type map
AUDIO_TYPES = {1: "deep-dive", 2: "brief", 3: "critique", 4: "debate", 7: "custom", 8: "custom"}

_UUID_RE = re.compile(r"/notebook/([0-9a-f-]{36})")


def extract_uuids(inventory_path: Path) -> list[str]:
    """Extrai UUIDs do inventario markdown."""
    uuids = []
    text = inventory_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        m = _UUID_RE.search(line)
        if m:
            uuids.append(m.group(1))
    return uuids


def parse_rpc_response(body: str) -> list:
    """Parseia response do batchexecute — retorna lista de payloads JSON."""
    if body.startswith(")]}'"):
        body = body[4:].lstrip()
    lines = body.split("\n")
    results = []
    i = 0
    while i < len(lines):
        if lines[i].strip().isdigit() and i + 1 < len(lines):
            try:
                chunk = json.loads(lines[i + 1].strip())
                if (
                    isinstance(chunk, list)
                    and len(chunk) > 0
                    and isinstance(chunk[0], list)
                    and len(chunk[0]) > 2
                ):
                    rpcid = chunk[0][1]
                    inner_str = chunk[0][2]
                    if isinstance(inner_str, str) and inner_str.startswith("["):
                        results.append((rpcid, json.loads(inner_str)))
            except Exception:
                pass
        i += 1
    return results


def extract_metadata(rpc_data: dict) -> dict:
    """Extrai metadados do notebook de rLM1Ne."""
    inner = rpc_data.get("rLM1Ne")
    if not inner:
        return {}

    # inner pode ser [[titulo, sources, uuid, emoji, ...]] ou [titulo, sources, ...]
    nb = inner[0] if isinstance(inner[0], list) else inner

    title = nb[0] if isinstance(nb[0], str) else str(nb[0])[:200] if nb[0] else ""
    sources = []

    if len(nb) > 1 and isinstance(nb[1], list):
        for s in nb[1]:
            if isinstance(s, list) and len(s) > 1:
                uuid = s[0][0] if isinstance(s[0], list) and s[0] else str(s[0])
                name = s[1] if isinstance(s[1], str) else ""
                sources.append({"uuid": uuid, "name": name})

    uuid = nb[2] if len(nb) > 2 and isinstance(nb[2], str) else ""
    emoji = nb[3] if len(nb) > 3 and isinstance(nb[3], str) else ""

    return {"title": title, "uuid": uuid, "emoji": emoji, "sources": sources}


def extract_guide(rpc_data: dict) -> dict | None:
    """Extrai notebook guide de VfAZjd."""
    inner = rpc_data.get("VfAZjd")
    if not inner:
        return None

    summary = ""
    questions = []

    try:
        if inner[0] and inner[0][0]:
            summary = inner[0][0][0] if isinstance(inner[0][0][0], str) else ""
        if len(inner[0]) > 1 and isinstance(inner[0][1], list):
            for q_group in inner[0][1]:
                if isinstance(q_group, list):
                    for q in q_group:
                        if isinstance(q, list) and len(q) > 0 and isinstance(q[0], str):
                            questions.append(q[0])
    except (IndexError, TypeError):
        pass

    if not summary and not questions:
        return None
    return {"summary": summary, "questions": questions}


def extract_chat(rpc_data: dict) -> list | None:
    """Extrai chat de khqZz."""
    inner = rpc_data.get("khqZz")
    if not inner or not inner[0] or not isinstance(inner[0], list) or len(inner[0]) == 0:
        return None

    messages = []
    for msg in inner[0]:
        if not isinstance(msg, list) or len(msg) < 3:
            continue

        msg_id = msg[0] if isinstance(msg[0], str) else ""
        timestamp = None
        if isinstance(msg[1], list) and len(msg[1]) >= 1 and isinstance(msg[1][0], int):
            timestamp = datetime.fromtimestamp(msg[1][0]).isoformat()

        role = "assistant" if msg[2] == 2 else "user"

        content = ""
        if len(msg) > 4 and isinstance(msg[4], list) and len(msg[4]) > 0:
            first = msg[4][0]
            if isinstance(first, list) and len(first) > 0 and isinstance(first[0], str):
                content = first[0]
            elif isinstance(first, str):
                content = first

        # User messages podem ter conteudo em campo 3
        if role == "user" and not content:
            if len(msg) > 3 and isinstance(msg[3], str) and len(msg[3]) > 0:
                content = msg[3]

        messages.append({
            "id": msg_id,
            "timestamp": timestamp,
            "role": role,
            "content": content,
        })

    if not messages:
        return None

    # Inverter pra ordem cronologica (payload vem mais recente primeiro)
    messages.reverse()
    return messages


def extract_notes(rpc_data: dict) -> list | None:
    """Extrai notes/mind maps de cFji9."""
    inner = rpc_data.get("cFji9")
    if not inner:
        return None

    # Filtrar o payload de timestamp (cFji9 tambem retorna [null, [timestamp]])
    notes = []
    for item in inner:
        if isinstance(item, list) and len(item) >= 2:
            for sub in item:
                if isinstance(sub, list) and len(sub) >= 2:
                    note_id = sub[0] if isinstance(sub[0], str) else ""
                    content = sub[1] if isinstance(sub[1], str) else ""
                    if note_id and content:
                        notes.append({"id": note_id, "content": content})

    return notes if notes else None


def extract_audios(rpc_data: dict) -> list:
    """Extrai audio overviews de gArtLc."""
    inner = rpc_data.get("gArtLc")
    if not inner or not inner[0] or not isinstance(inner[0], list):
        return []

    audios = []
    for ao in inner[0]:
        if not isinstance(ao, list) or len(ao) < 5:
            continue

        ao_id = ao[0] if isinstance(ao[0], str) else ""
        title = ao[1] if isinstance(ao[1], str) else ""
        ao_type = ao[2] if isinstance(ao[2], int) else 0
        type_name = AUDIO_TYPES.get(ao_type, f"type-{ao_type}")

        # Buscar URL de audio
        audio_url = None
        for fi in range(len(ao)):
            val = ao[fi]
            if isinstance(val, str) and "lh3.googleusercontent.com" in val:
                audio_url = val
                break
            if isinstance(val, list):
                urls = re.findall(
                    r"https://lh3\.googleusercontent\.com/notebooklm/[^\s'\"\\]+",
                    str(val),
                )
                if urls:
                    audio_url = urls[0]
                    break

        # Brief (tipo 2) tem markdown em [7][0]
        brief_content = None
        if ao_type == 2 and len(ao) > 7 and isinstance(ao[7], list) and len(ao[7]) > 0:
            if isinstance(ao[7][0], str):
                brief_content = ao[7][0]

        audios.append({
            "id": ao_id,
            "title": title,
            "type": ao_type,
            "type_name": type_name,
            "url": audio_url,
            "brief_content": brief_content,
        })

    return audios


def download_from_menu(page, more_btn, output_dir: Path, fallback_name: str) -> str | None:
    """Clica nos 3 pontos de um item, baixa se tiver opcao 'Baixar'.

    Retorna o path do arquivo salvo, ou None se falhou.
    Aceita qualquer variante: "Baixar", "Baixar documento PDF (.pdf)", etc.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        more_btn.click()
        page.wait_for_timeout(1000)

        # Procurar item de menu que contenha "aixar" (PT) ou "ownload" (EN)
        menu_items = page.locator('[role="menuitem"]').all()
        baixar = None
        for item in menu_items:
            try:
                text = item.inner_text()
                if item.is_visible() and ("aixar" in text or "ownload" in text):
                    baixar = item
                    break
            except Exception:
                continue

        if not baixar:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            return None

        # Clicar e esperar download
        with page.expect_download(timeout=60000) as download_info:
            baixar.click()

        download = download_info.value

        # Checar se o download falhou
        failure = download.failure()
        if failure:
            return None

        # Usar nome sugerido pelo browser, ou fallback
        suggested = download.suggested_filename or fallback_name
        fpath = output_dir / suggested
        download.save_as(str(fpath))
        page.wait_for_timeout(1000)
        return str(fpath)

    except Exception:
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except Exception:
            pass
        return None


def process_notebook(context, uuid: str, output_dir: Path) -> dict:
    """Processa um notebook: intercepta RPCs, extrai dados, salva arquivos."""
    url = f"https://notebooklm.google.com/notebook/{uuid}"
    rpc_data = {}

    page = context.new_page()

    def on_response(response):
        if "batchexecute" not in response.url:
            return
        try:
            body = response.text()
        except Exception:
            return
        for rpcid, payload in parse_rpc_response(body):
            # Guardar o maior payload de cada rpcid (gArtLc pode vir varias vezes)
            if rpcid not in rpc_data or len(str(payload)) > len(str(rpc_data.get(rpcid, ""))):
                rpc_data[rpcid] = payload

    page.on("response", on_response)

    # Abrir notebook
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(10000)

    # Expandir painel Studio se estiver colapsado (Playwright abre com state limpo)
    # Isso NAO gera audio — so expande o painel que ja existe
    try:
        studio_section = page.locator("section.studio-panel").first
        if studio_section:
            is_collapsed = "panel-collapsed" in (studio_section.get_attribute("class") or "")
            if is_collapsed:
                studio_header = studio_section.locator(".panel-header").first
                if studio_header and studio_header.is_visible():
                    studio_header.click()
                    # Esperar RPCs carregarem apos expandir
                    page.wait_for_timeout(8000)
    except Exception:
        pass

    page.wait_for_timeout(3000)

    # Extrair dados
    metadata = extract_metadata(rpc_data)
    guide = extract_guide(rpc_data)
    chat = extract_chat(rpc_data)
    notes = extract_notes(rpc_data)
    audios = extract_audios(rpc_data)

    # Salvar
    output_dir.mkdir(parents=True, exist_ok=True)

    # notebook.json — sempre
    nb_json = {
        "uuid": uuid,
        "title": metadata.get("title", ""),
        "emoji": metadata.get("emoji", ""),
        "sources": metadata.get("sources", []),
        "guide": guide,
    }
    (output_dir / "notebook.json").write_text(
        json.dumps(nb_json, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # chat.json — so se tiver
    if chat:
        (output_dir / "chat.json").write_text(
            json.dumps(chat, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # notes.json — so se tiver
    if notes:
        (output_dir / "notes.json").write_text(
            json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # Baixar items do Audio Overview via UI (audio, slides, PDFs — tudo na mesma lista)
    # Briefs com conteudo markdown ja foram salvos via RPC
    audio_downloaded = 0
    audio_failed = 0

    for ao in audios:
        if ao["brief_content"]:
            audio_dir = output_dir / "audio"
            audio_dir.mkdir(exist_ok=True)
            fname = f"{ao['id']}_{ao['type_name']}.md"
            (audio_dir / fname).write_text(
                f"# {ao['title']}\n\n{ao['brief_content']}", encoding="utf-8"
            )

    # Encontrar os "More"/"Mais" dos items gerados no painel Studio
    # A lista de items fica dentro de section.studio-panel
    item_mais = []
    try:
        studio = page.locator("section.studio-panel").first
        if studio:
            mais = studio.locator('button[aria-label="Mais"], button[aria-label="More"]').all()
            item_mais = [m for m in mais if m.is_visible()]
    except Exception:
        pass

    for idx, mais_btn in enumerate(item_mais):
        # Identificar pelo payload se possivel
        if idx < len(audios):
            ao = audios[idx]
            label = f"{ao['type_name']} ({ao['title'][:40]})"
            fallback = f"{ao['id']}_{ao['type_name']}"
        else:
            label = f"item #{idx+1}"
            fallback = f"item_{idx+1}"

        print(f"         {label}... ", end="", flush=True)
        result = download_from_menu(page, mais_btn, output_dir / "audio", fallback)
        if result:
            size_mb = Path(result).stat().st_size / 1024 / 1024
            print(f"OK ({size_mb:.1f}MB)")
            audio_downloaded += 1
        else:
            print("SKIP")
            audio_failed += 1

    page.close()

    stats = {
        "uuid": uuid,
        "title": metadata.get("title", ""),
        "has_chat": chat is not None,
        "chat_messages": len(chat) if chat else 0,
        "has_notes": notes is not None,
        "notes_count": len(notes) if notes else 0,
        "audio_count": len(audios),
        "audio_downloaded": audio_downloaded,
        "audio_failed": audio_failed,
    }
    return stats


def main():
    parser = argparse.ArgumentParser(description="Download conteudo do NotebookLM")
    parser.add_argument("--account", required=True, choices=list(INVENTARIOS.keys()))
    parser.add_argument("--uuid", help="UUID de um notebook especifico (debug)")
    args = parser.parse_args()

    inventory_path = INVENTARIOS[args.account]
    if not inventory_path.exists():
        print(f"Inventario nao encontrado: {inventory_path}")
        sys.exit(1)

    if not STORAGE_STATE.exists():
        print(f"Storage state nao encontrado: {STORAGE_STATE}")
        print("Execute: notebooklm login")
        sys.exit(1)

    # UUIDs
    if args.uuid:
        uuids = [args.uuid]
    else:
        uuids = extract_uuids(inventory_path)

    account_dir = RAW_DIR / args.account
    print(f"Conta: {args.account}")
    print(f"Notebooks: {len(uuids)}")
    print(f"Destino: {account_dir}")
    print()

    # Stats
    total = len(uuids)
    processed = 0
    skipped = 0
    with_chat = 0
    with_notes = 0
    audio_total = 0
    audio_downloaded = 0
    errors = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            storage_state=str(STORAGE_STATE),
            viewport={"width": 1920, "height": 1080},
        )

        # Aba vazia pra manter o browser aberto entre notebooks
        keep_alive_page = context.new_page()
        keep_alive_page.goto("about:blank")

        for i, uuid in enumerate(uuids):
            nb_dir = account_dir / uuid

            # Skip se ja existe
            if nb_dir.exists() and (nb_dir / "notebook.json").exists():
                print(f"[{i+1}/{total}] {uuid[:8]}... SKIP (ja existe)")
                skipped += 1
                continue

            print(f"[{i+1}/{total}] {uuid[:8]}... ", end="", flush=True)

            try:
                stats = process_notebook(context, uuid, nb_dir)

                parts = []
                if stats["has_chat"]:
                    parts.append(f"{stats['chat_messages']} msgs")
                    with_chat += 1
                if stats["has_notes"]:
                    parts.append(f"{stats['notes_count']} notes")
                    with_notes += 1
                if stats["audio_count"]:
                    parts.append(f"{stats['audio_count']} audios")
                    audio_total += stats["audio_count"]
                if stats["audio_downloaded"]:
                    parts.append(f"{stats['audio_downloaded']} baixados")
                    audio_downloaded += stats["audio_downloaded"]
                if stats["audio_failed"]:
                    parts.append(f"{stats['audio_failed']} falharam")

                title = stats["title"][:50]
                detail = ", ".join(parts) if parts else "metadados only"
                print(f"{title} [{detail}]")

                processed += 1

            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"ERRO: {e}")
                errors += 1

            # Rate limiting
            if i < total - 1:
                time.sleep(4)

        keep_alive_page.close()
        browser.close()

    # Resumo
    print(f"\n{'='*60}")
    print(f"Conta: {args.account}")
    print(f"Total: {total} notebooks")
    print(f"Processados: {processed} | Skipped: {skipped} | Erros: {errors}")
    print(f"Com chat: {with_chat} | Com notes: {with_notes}")
    print(f"Audios: {audio_total} encontrados, {audio_downloaded} baixados")


if __name__ == "__main__":
    main()
