"""Sync manual saves — roda os 3 parsers e agrupa por plataforma destino.

Estrutura input:  data/external/manual-saves/{clippings-obsidian,copypaste-web,terminal-claude-code}/
Estrutura output:
    data/processed/<Plataforma>/<source>_manual_<table>.parquet
Onde:
    <Plataforma> = 'ChatGPT' / 'Claude.ai' / 'Claude Code' / etc
    <source>     = 'chatgpt' / 'claude_ai' / 'claude_code' / etc
    <table>      = conversations / messages / tool_events / branches

capture_method da Conversation indica origem do clip:
    'manual_clipping_obsidian', 'manual_copypaste', 'manual_terminal_cc'

Uso: PYTHONPATH=. .venv/bin/python scripts/manual-saves-sync.py
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.parsers.manual.clippings_obsidian import ClippingsObsidianParser
from src.parsers.manual.copypaste_web import CopypasteWebParser
from src.parsers.manual.terminal_claude_code import TerminalClaudeCodeParser
from src.schema.models import (
    branches_to_df,
    conversations_to_df,
    messages_to_df,
    tool_events_to_df,
)


logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXT_DIR = PROJECT_ROOT / "data" / "external" / "manual-saves"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


# Source canonico → nome da pasta data/processed/<X>/
SOURCE_TO_FOLDER = {
    "chatgpt": "ChatGPT",
    "claude_ai": "Claude.ai",
    "gemini": "Gemini",
    "qwen": "Qwen",
    "deepseek": "DeepSeek",
    "perplexity": "Perplexity",
    "notebooklm": "NotebookLM",
    "claude_code": "Claude Code",
    "codex": "Codex",
    "gemini_cli": "Gemini CLI",
}


def main() -> int:
    started_at = datetime.now(timezone.utc)
    parsers_run = []

    # 1. Clippings Obsidian
    p = EXT_DIR / "clippings-obsidian"
    if p.exists():
        parser = ClippingsObsidianParser()
        parser.parse(p)
        parsers_run.append(("clippings_obsidian", parser))
        logger.info(f"  clippings-obsidian: {len(parser.conversations)} convs")

    # 2. Copypaste Web
    p = EXT_DIR / "copypaste-web"
    if p.exists():
        parser = CopypasteWebParser()
        parser.parse(p)
        parsers_run.append(("copypaste_web", parser))
        logger.info(f"  copypaste-web: {len(parser.conversations)} convs")

    # 3. Terminal Claude Code
    p = EXT_DIR / "terminal-claude-code"
    if p.exists():
        parser = TerminalClaudeCodeParser()
        parser.parse(p)
        parsers_run.append(("terminal_cc", parser))
        logger.info(f"  terminal-claude-code: {len(parser.conversations)} convs")

    # Consolida tudo em listas globais (capture_method ja setado em Conversation)
    all_convs = []
    all_msgs = []
    all_events = []
    all_branches = []
    for label, parser in parsers_run:
        all_convs.extend(parser.conversations)
        all_msgs.extend(parser.messages)
        all_events.extend(parser.events)
        all_branches.extend(parser.branches)

    # Agrupa por source destino
    convs_by_src: dict[str, list] = {}
    msgs_by_src: dict[str, list] = {}
    events_by_src: dict[str, list] = {}
    branches_by_src: dict[str, list] = {}

    for c in all_convs:
        convs_by_src.setdefault(c.source, []).append(c)
    for m in all_msgs:
        msgs_by_src.setdefault(m.source, []).append(m)
    for e in all_events:
        events_by_src.setdefault(e.source, []).append(e)
    for b in all_branches:
        branches_by_src.setdefault(b.source, []).append(b)

    # Escreve <source>_manual_<table>.parquet por plataforma
    sources_seen = set(convs_by_src.keys())
    print()
    print("=== STATS por plataforma destino ===")
    for source in sorted(sources_seen):
        folder = SOURCE_TO_FOLDER.get(source, source.title())
        out_dir = PROCESSED_DIR / folder
        out_dir.mkdir(parents=True, exist_ok=True)

        n_c = len(convs_by_src.get(source, []))
        n_m = len(msgs_by_src.get(source, []))
        n_e = len(events_by_src.get(source, []))
        n_b = len(branches_by_src.get(source, []))

        conversations_to_df(convs_by_src.get(source, [])).to_parquet(
            out_dir / f"{source}_manual_conversations.parquet", index=False)
        messages_to_df(msgs_by_src.get(source, [])).to_parquet(
            out_dir / f"{source}_manual_messages.parquet", index=False)
        tool_events_to_df(events_by_src.get(source, [])).to_parquet(
            out_dir / f"{source}_manual_tool_events.parquet", index=False)
        branches_to_df(branches_by_src.get(source, [])).to_parquet(
            out_dir / f"{source}_manual_branches.parquet", index=False)

        print(f"  {folder:20} {n_c:>3} convs, {n_m:>5} msgs, {n_e:>4} events, {n_b:>3} branches → {out_dir.name}/")

    finished_at = datetime.now(timezone.utc)
    duration = (finished_at - started_at).total_seconds()
    print(f"\nTotal: {len(all_convs)} convs / {len(all_msgs)} msgs / {len(all_events)} events / {len(all_branches)} branches")
    print(f"Duracao: {duration:.1f}s")

    # Capture log central pra dashboard detectar last sync
    EXT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = EXT_DIR / "capture_log.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": duration,
            "totals": {
                "conversations": len(all_convs),
                "messages": len(all_msgs),
                "tool_events": len(all_events),
                "branches": len(all_branches),
                "platforms_touched": sorted(sources_seen),
            },
        }) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
