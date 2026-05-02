"""Probe schema de pin/share no listing do Gemini.

Inspeciona o raw `c` (tupla retornada pelo MaZiqc) pra cada conv,
focando no chat pinado (98c60a18de056385) pra ver quais campos diferem
de um chat normal. Tambem testa endpoints alternativos pra pinned/shared.
"""

import asyncio
import json

from src.extractors.gemini.auth import load_context
from src.extractors.gemini.api_client import GeminiAPIClient
from src.extractors.gemini.batchexecute import call_rpc, load_session


PINNED_ID = "c_98c60a18de056385"
RENAMED_ID = "c_dc5c683537a19cd1"


async def main():
    context = await load_context(account=1, headless=True)
    try:
        session = await load_session(context)
        client = GeminiAPIClient(context, session)

        # 1. Listing inteiro com schema completo
        print("=== Listing schema (MaZiqc) ===")
        data = await call_rpc(context, session, "MaZiqc", [], reqid=1)
        if not data or len(data) < 3:
            print("  empty data")
            return
        convs_raw = data[2] if isinstance(data[2], list) else []
        print(f"  total: {len(convs_raw)} convs")

        # Encontra pinned + renamed
        pinned = None
        renamed = None
        first_normal = None
        for c in convs_raw:
            if not isinstance(c, list) or len(c) < 2:
                continue
            cid = c[0]
            if cid == PINNED_ID:
                pinned = c
            elif cid == RENAMED_ID:
                renamed = c
            elif first_normal is None:
                first_normal = c

        # Mostra schema de cada (todos os indices)
        for label, c in [("PINNED", pinned), ("RENAMED", renamed), ("NORMAL", first_normal)]:
            print(f"\n=== {label} schema (len={len(c) if c else 0}) ===")
            if not c:
                print("  not found in listing")
                continue
            for i, item in enumerate(c):
                if item is None:
                    print(f"  [{i}]: None")
                elif isinstance(item, list):
                    s = json.dumps(item, ensure_ascii=False)
                    print(f"  [{i}]: list({len(item)}) {s[:200]}")
                elif isinstance(item, dict):
                    print(f"  [{i}]: dict {list(item.keys())[:5]}")
                else:
                    s = str(item)
                    print(f"  [{i}]: {type(item).__name__} {s[:100]!r}")

        # 2. Probe endpoints alternativos
        print("\n=== Probing alternative RPC ids ===")
        # rpcids candidatos pra pinned/share. Sem documentacao, tentando nomes comuns
        candidates = [
            ("EaipR", "pinned chats?"),    # nome ad-hoc
            ("yQzmHb", "shared chats?"),   # nome ad-hoc
            ("VhQOs", "filter pinned?"),   # nome ad-hoc
            # Estes sao chutes — em geral nao temos como saber sem inspecionar trafego do front
        ]
        for rpcid, label in candidates:
            try:
                resp = await call_rpc(context, session, rpcid, [], reqid=99)
                print(f"  {rpcid} ({label}): {type(resp).__name__} = {str(resp)[:100]}")
            except Exception as e:
                print(f"  {rpcid} ({label}): ERR {str(e)[:80]}")

        # 3. MaZiqc com payloads diferentes (filtragem)
        print("\n=== MaZiqc com payloads diferentes ===")
        payloads = [
            [None, None, None, "pinned"],
            [True],
            [None, "pinned"],
            ["pinned"],
        ]
        for p in payloads:
            try:
                resp = await call_rpc(context, session, "MaZiqc", p, reqid=99)
                if resp:
                    sub = resp[2] if len(resp) > 2 else None
                    n = len(sub) if isinstance(sub, list) else 0
                    print(f"  payload {p}: total={n}")
            except Exception as e:
                print(f"  payload {p}: ERR {str(e)[:80]}")
    finally:
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
