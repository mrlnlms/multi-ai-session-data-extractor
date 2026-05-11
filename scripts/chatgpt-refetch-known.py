"""Refetch state-only de convs ja conhecidas (escape hatch quando discovery flakey).

Pega IDs do `chatgpt_raw.json` atual, fetcha em batches via /conversations/batch
diretamente via page.evaluate (fetch nativo do browser — passa por todas as
mitigacoes de Cloudflare/auth automaticamente).

Usa quando `chatgpt-sync.py` aborta porque /conversations listing tá retornando
total errado (ex: glitch upstream que retorna total=2 quando user tem 1168).
Convs INDIVIDUAIS continuam acessiveis via /conversation/{id} ou batch.

Uso:
  PYTHONPATH=. .venv/bin/python scripts/chatgpt-refetch-known.py [--account default]
                                                                 [--batch-size 10]

Nota: limite upstream do /conversations/batch eh 10 entries por request
(validado via 422 "conversation_ids must contain at most 10 entries" em
2026-05-11). Defaults antigos (50) viram 100% erros.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

from src.extractors.chatgpt.auth import get_profile_dir


async def fetch_batch(page, ids: list[str]) -> tuple[list[dict], str | None]:
    """Fetch batch via page.evaluate (fetch nativo). Retorna (results, error_msg)."""
    payload = json.dumps({"ids": ids})
    result = await page.evaluate(
        """async ({payload}) => {
            const sess = await fetch('/api/auth/session', {credentials: 'include'});
            const tok = (await sess.json()).accessToken;
            const ids = JSON.parse(payload).ids;
            const r = await fetch('/backend-api/conversations/batch', {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'Authorization': 'Bearer ' + tok,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({conversation_ids: ids}),
            });
            const txt = await r.text();
            return {status: r.status, body: txt};
        }""",
        {"payload": payload},
    )
    if result["status"] == 200:
        return json.loads(result["body"]), None
    return [], f"HTTP {result['status']}: {result['body'][:200]}"


async def refetch(account: str, batch_size: int = 50) -> None:
    raw_dir = Path("data/raw/ChatGPT")
    raw_path = raw_dir / "chatgpt_raw.json"
    if not raw_path.exists():
        print(f"raw nao existe: {raw_path}")
        sys.exit(1)

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    conv_ids = list(raw["conversations"].keys())
    total = len(conv_ids)
    print(f"Refetching {total} convs em batches de {batch_size} (page.evaluate)...")
    started_at = datetime.now(timezone.utc)

    profile_dir = get_profile_dir(account)
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = await context.new_page()
            await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)

            updated = 0
            errors = 0
            for i in range(0, total, batch_size):
                batch = conv_ids[i : i + batch_size]
                results, err = await fetch_batch(page, batch)
                if err:
                    print(f"  batch [{i}..{i+len(batch)}] FAILED: {err[:120]}")
                    errors += len(batch)
                    await asyncio.sleep(2)  # backoff em erro
                    continue
                by_id = {r.get("id"): r for r in results if isinstance(r, dict) and r.get("id")}
                for cid in batch:
                    if cid not in by_id:
                        errors += 1
                        continue
                    new = by_id[cid]
                    existing = raw["conversations"].get(cid, {})
                    aux = {k: v for k, v in existing.items() if k.startswith("_")}
                    new.update(aux)
                    raw["conversations"][cid] = new
                    updated += 1
                done = i + len(batch)
                print(f"  [{done}/{total}] updated={updated} errors={errors}", flush=True)
                await asyncio.sleep(0.3)
        finally:
            await context.close()

    raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    finished_at = datetime.now(timezone.utc)
    duration = (finished_at - started_at).total_seconds()

    # Append no capture_log.jsonl pro dashboard ver a captura
    log_entry = {
        "run_started_at": started_at.isoformat(),
        "run_finished_at": finished_at.isoformat(),
        "duration_seconds": duration,
        "mode": "refetch_known",
        "discovery": {"total": total},
        "fetch": {"attempted": total, "succeeded": updated},
        "errors": [],
    }
    log_path = raw_dir / "capture_log.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

    # LAST_CAPTURE.md humano
    last_md = raw_dir / "LAST_CAPTURE.md"
    last_md.write_text(
        f"# Last capture (refetch_known)\n\n"
        f"- **Quando:** {started_at.isoformat()}\n"
        f"- **Duracao:** {duration:.1f}s\n"
        f"- **Modo:** refetch_known (state-only refresh de IDs conhecidas)\n"
        f"- **Convs atualizadas:** {updated}/{total}\n"
        f"- **Errors:** {errors}\n",
        encoding="utf-8",
    )

    print(f"\nDone. Updated {updated}/{total}, errors={errors}")
    print(f"Raw atualizado: {raw_path}")
    print(f"capture_log.jsonl atualizado")
    print("\nProximo passo:")
    print("  PYTHONPATH=. .venv/bin/python scripts/chatgpt-reconcile.py data/raw/ChatGPT")
    print("  PYTHONPATH=. .venv/bin/python scripts/chatgpt-parse.py")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="default")
    ap.add_argument("--batch-size", type=int, default=10)
    args = ap.parse_args()
    asyncio.run(refetch(args.account, args.batch_size))
