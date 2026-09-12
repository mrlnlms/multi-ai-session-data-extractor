"""Refetch das convs que estao na discovery mas nao no disco (gap fill).

Cenario tipico: claude-sync.py terminou OK mas N convs falharam por
timeout/HTTP transiente. Ficam na discovery_ids.json, nao no
conversations/<uuid>.json. Esta tool faz a mitigacao com retry+backoff.

NAO eh state-refresh — pra isso, rode `claude-sync.py --full`.

Uso:
    PYTHONPATH=. .venv/bin/python scripts/claude-refetch-known.py
    PYTHONPATH=. .venv/bin/python scripts/claude-refetch-known.py --profile default --retries 3

Proximos passos sugeridos no fim da run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.claude_ai.api_client import ClaudeAPIClient
from src.extractors.claude_ai.auth import load_context
from src.extractors.claude_ai.orchestrator import BASE_DIR


def _missing_ids(raw_dir: Path) -> list[dict]:
    """Convs em discovery mas sem arquivo correspondente em conversations/."""
    disc_path = raw_dir / "discovery_ids.json"
    if not disc_path.exists():
        return []
    disc = json.loads(disc_path.read_text(encoding="utf-8"))
    on_disk = {p.stem for p in (raw_dir / "conversations").glob("*.json")}
    return [c for c in disc.get("conversations", []) if c.get("uuid") not in on_disk]


async def _fetch_with_retry(
    client: ClaudeAPIClient,
    uuid: str,
    retries: int,
    backoff_base: float,
) -> tuple[dict | None, str | None]:
    """Tenta fetchar conv com exp backoff. Retorna (conv, err_msg)."""
    last_err = ""
    for attempt in range(retries + 1):
        try:
            conv = await client.fetch_conversation(uuid)
            return conv, None
        except Exception as e:
            last_err = str(e)[:200]
            if attempt < retries:
                wait = backoff_base * (2**attempt)
                print(f"    tentativa {attempt+1}/{retries+1} falhou ({last_err[:80]}); backoff {wait:.1f}s")
                await asyncio.sleep(wait)
    return None, last_err


async def main(args: argparse.Namespace) -> int:
    raw_dir = BASE_DIR
    if not (raw_dir / "discovery_ids.json").exists():
        print(f"ERRO: discovery_ids.json nao existe em {raw_dir}. Rode claude-sync.py primeiro.")
        return 1

    targets = _missing_ids(raw_dir)
    if not targets:
        print(f"Nada faltando em {raw_dir}/conversations/. Sem refetch necessario.")
        return 0

    print(f"Gap detectado: {len(targets)} conv(s) na discovery sem arquivo em disco.")
    for t in targets:
        upd = (t.get("updated_at") or "")[:10]
        print(f"  - {t['uuid']}  upd={upd}  name={(t.get('name') or '')[:60]!r}")

    if args.dry_run:
        print("\n[dry-run: nada feito]")
        return 0

    started_at = datetime.now(timezone.utc)
    context, org_id = await load_context(profile_name=args.profile, headless=True)
    client = ClaudeAPIClient(context, org_id)

    today = started_at.strftime("%Y-%m-%d")
    conv_dir = raw_dir / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)

    succeeded: list[str] = []
    errors: list[tuple[str, str]] = []
    try:
        for t in targets:
            uuid = t["uuid"]
            print(f"\nFetching {uuid}...")
            conv, err = await _fetch_with_retry(client, uuid, args.retries, args.backoff_base)
            if conv is not None:
                conv["_last_seen_in_server"] = today
                (conv_dir / f"{uuid}.json").write_text(
                    json.dumps(conv, ensure_ascii=False), encoding="utf-8"
                )
                msgs = len(conv.get("chat_messages") or [])
                print(f"  OK ({msgs} msgs)")
                succeeded.append(uuid)
            else:
                print(f"  FALHOU apos {args.retries+1} tentativas: {err[:120]}")
                errors.append((uuid, err))
    finally:
        await context.close()

    finished_at = datetime.now(timezone.utc)
    log_entry = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "mode": "refetch_known",
        "totals": {
            "conversations_discovered": len(targets),
            "conversations_fetched": len(succeeded),
            "conversations_errors": len(errors),
        },
        "errors": {"conversations": errors[:50]},
    }
    log_path = raw_dir / "capture_log.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    print()
    print("=" * 60)
    print(f"Refetch concluido: {len(succeeded)} ok / {len(errors)} erros")
    print(f"Duracao: {(finished_at - started_at).total_seconds():.1f}s")
    if errors:
        print("Erros remanescentes (precisa investigar):")
        for uuid, err in errors:
            print(f"  {uuid}: {err[:100]}")
    print()
    print("Proximos passos:")
    print("  PYTHONPATH=. .venv/bin/python scripts/claude-reconcile.py")
    print("  PYTHONPATH=. .venv/bin/python scripts/claude-parse.py")
    return 0 if not errors else 2


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default="default", help="Profile Playwright (default: 'default')")
    ap.add_argument("--retries", type=int, default=3, help="Tentativas extras por UUID (default: 3)")
    ap.add_argument("--backoff-base", type=float, default=2.0, help="Base do exp backoff em segundos (default: 2.0)")
    ap.add_argument("--dry-run", action="store_true", help="Lista o que faria, nao executa")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args)))
