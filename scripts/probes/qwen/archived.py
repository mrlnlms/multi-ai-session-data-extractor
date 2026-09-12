"""Probe endpoints possiveis pra archived flag em Qwen.

Lista candidatos (chats/archived, ?archived=true, ?show_archived=true) e
inspeciona body do chat especifico que o user arquivou (75924b8e) por
qualquer field que possa indicar archived state.
"""

import asyncio
import json

from src.extractors.qwen.auth import load_context
from src.extractors.qwen.api_client import QwenAPIClient, API_BASE


ARCHIVED_CHAT_ID = "75924b8e-a9af-4217-8c77-7465ac2e76a0"


async def main():
    ctx = await load_context(headless=True)
    page = await ctx.new_page()
    client = QwenAPIClient(ctx, page)
    await client.warmup()

    # 1. Endpoints candidatos
    candidates = [
        f"{API_BASE}/v2/chats/archived",
        f"{API_BASE}/v2/chats/?archived=true",
        f"{API_BASE}/v2/chats/?show_archived=true",
        f"{API_BASE}/v2/chats/?archived_only=true",
        f"{API_BASE}/v2/chats/all",
        f"{API_BASE}/v2/user/preferences",
        f"{API_BASE}/v2/user/settings",
    ]
    print("=== Probing endpoints ===")
    for url in candidates:
        try:
            resp = await client._fetch(url)
            ok = resp.get("success") if isinstance(resp, dict) else None
            data = resp.get("data") if isinstance(resp, dict) else None
            sample = ""
            if isinstance(data, list):
                sample = f"len={len(data)}"
                # Procura archived chat na resposta
                ids = {c.get("id") for c in data if isinstance(c, dict)}
                if ARCHIVED_CHAT_ID in ids:
                    sample += " — INCLUI archived chat!"
            elif isinstance(data, dict):
                sample = f"keys={list(data.keys())[:5]}"
            print(f"  [{'OK' if ok else '?'}] {url} → {sample}")
        except Exception as e:
            print(f"  [ERR] {url} → {str(e)[:80]}")

    # 2. Fetch novo do chat archived especificamente
    print()
    print(f"=== Fetch direto: {ARCHIVED_CHAT_ID} ===")
    obj = await client.fetch_conversation(ARCHIVED_CHAT_ID)
    data = obj.get("data", {})
    # Imprime TODOS os campos top-level
    for k, v in sorted(data.items()):
        if isinstance(v, (list, dict)):
            print(f"  {k}: <{type(v).__name__} len={len(v)}>")
        else:
            print(f"  {k}: {v!r}")

    # 3. Chama listing com diferentes querystrings + lê estrutura completa
    print()
    print("=== Page 1 com querystrings ===")
    for qs in ["", "?show_archived=1", "?include_archived=true", "?type=archived"]:
        url = f"{API_BASE}/v2/chats/{qs}" if qs else f"{API_BASE}/v2/chats/?page=1"
        if qs and "page" not in qs:
            url = f"{API_BASE}/v2/chats/?page=1&{qs.lstrip('?')}"
        try:
            resp = await client._fetch(url)
            data = resp.get("data") if isinstance(resp, dict) else None
            if isinstance(data, list):
                ids = {c.get("id") for c in data if isinstance(c, dict)}
                has_archived = ARCHIVED_CHAT_ID in ids
                print(f"  {url} → len={len(data)} contem_archived={has_archived}")
                # Mostra fields do primeiro item
                if data:
                    print(f"    fields: {sorted(data[0].keys())[:15]}")
        except Exception as e:
            print(f"  {url} → ERR {str(e)[:80]}")

    await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
