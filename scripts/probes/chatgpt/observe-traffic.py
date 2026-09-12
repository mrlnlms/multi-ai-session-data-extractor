"""Observa o contrato de rede do ChatGPT sem coletar conteudo de conversas.

O script mantem todos os eventos apenas em memoria e, quando o navegador e
fechado, imprime e salva em arquivo temporario somente metodo, caminho
redigido, status, formato do JSON e o tipo de rota da pagina. Nunca imprime
cookies, headers, query strings, tokens, textos, titulos ou IDs.

Uso:
    PYTHONPATH=. .venv/bin/python scripts/dev/observe-chatgpt-traffic.py
"""

import asyncio
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from playwright.async_api import Response, async_playwright

from src.extractors.chatgpt.auth import get_profile_dir


OUTPUT_DIR = Path(".storage/chatgpt-probe")


def _redact_api_path(path: str) -> str:
    """Mantem o endpoint reconhecivel sem divulgar IDs dinamicos."""
    path = re.sub(r"/gizmos/g-p-[^/]+", "/gizmos/{project}", path)
    path = re.sub(r"/conversation/[^/]+", "/conversation/{conversation}", path)
    path = re.sub(r"/conversations/[^/]+", "/conversations/{resource}", path)
    return path


def _route_kind(url: str) -> str:
    """Classifica a rota visivel sem retornar seus identificadores."""
    path = urlparse(url).path
    if re.match(r"^/g/g-p-[^/]+/project", path):
        return "project_home"
    if path.startswith("/c/"):
        return "conversation"
    if path == "/":
        return "home"
    return "other"


def _json_shape(payload) -> dict:
    """Resume estrutura sem preservar qualquer valor de usuario."""
    if isinstance(payload, list):
        return {"type": "list", "count": len(payload)}
    if not isinstance(payload, dict):
        return {"type": type(payload).__name__}

    shape = {"type": "object", "keys": sorted(payload)[:30]}
    for key in ("items", "projects", "conversations", "cursor"):
        value = payload.get(key)
        if isinstance(value, list):
            shape[f"{key}_count"] = len(value)
            if value and isinstance(value[0], dict):
                shape[f"{key}_item_keys"] = sorted(value[0])[:30]
        elif key == "cursor":
            shape["has_cursor"] = value is not None
    return shape


async def observe_response(
    response: Response, events: list[dict], started_at: float
) -> None:
    request = response.request
    parsed = urlparse(response.url)
    if parsed.netloc != "chatgpt.com":
        return
    if not (parsed.path.startswith("/backend-api/") or parsed.path == "/api/auth/session"):
        return

    event = {
        "t_seconds": round(time.monotonic() - started_at, 1),
        "method": request.method,
        "path": _redact_api_path(parsed.path),
        "status": response.status,
        "resource_type": request.resource_type,
        "route_kind": _route_kind(request.frame.url),
        "query_keys": sorted(key for key, _ in parse_qsl(parsed.query)),
    }
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        try:
            event["shape"] = _json_shape(await response.json())
        except Exception:
            event["shape"] = {"type": "unreadable_json"}
    else:
        event["content_type"] = content_type.split(";", 1)[0] or "unknown"
    events.append(event)


async def main() -> None:
    events: list[dict] = []
    route_events: list[dict] = []
    started_at = time.monotonic()
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(get_profile_dir()),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        page.on(
            "response",
            lambda response: asyncio.create_task(
                observe_response(response, events, started_at)
            ),
        )
        page.on(
            "framenavigated",
            lambda frame: route_events.append({
                "t_seconds": round(time.monotonic() - started_at, 1),
                "route_kind": _route_kind(frame.url),
            }) if frame == page.main_frame else None,
        )
        await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60_000)

        print("Browser aberto. Explore chats da sidebar e Projects normalmente.")
        print("Ao terminar, feche o browser; nenhum dado sera gravado.")
        await context.wait_for_event("close", timeout=0)

    await asyncio.sleep(1)  # deixa handlers de response terminarem
    unique_events = []
    seen = set()
    for event in events:
        fingerprint = json.dumps(event, sort_keys=True)
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique_events.append(event)

    summary = {
        "network_timeline": events,
        "unique_response_shapes": unique_events,
        "navigation_timeline": route_events,
        "counts": Counter(
            f"{event['method']} {event['path']} -> {event['status']}" for event in events
        ),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / (
        "traffic-observation-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=dict), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=dict))
    print(f"Resumo redigido salvo em {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
