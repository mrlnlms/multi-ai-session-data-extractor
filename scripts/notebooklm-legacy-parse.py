"""Parse legacy NotebookLM more.design snapshot → 7 parquets canonicos.

Input:  data/external/notebooklm-snapshots/more-design-2026-03-30/
Output: data/processed/NotebookLM/notebooklm_manual_*.parquet

Sufixo `_manual_` reusa o setup_views_with_manual nos quartos consolidados —
not really "manual save" mas "captura externa nao-extractor", que segue o
mesmo padrao de UNION ALL BY NAME.

Uso: PYTHONPATH=. .venv/bin/python scripts/notebooklm-legacy-parse.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from src.parsers.manual.notebooklm_legacy_more_design import (
    NotebookLMLegacyMoreDesignParser,
)
from src.schema.models import (
    branches_to_df,
    conversations_to_df,
    messages_to_df,
    notebooklm_guide_questions_to_df,
    notebooklm_notes_to_df,
    notebooklm_outputs_to_df,
    project_docs_to_df,
    tool_events_to_df,
)


logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "data" / "external" / "notebooklm-snapshots" / "more-design-2026-03-30"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "NotebookLM"


def main() -> int:
    if not INPUT_DIR.exists():
        logger.error(f"Input nao existe: {INPUT_DIR}")
        return 1

    parser = NotebookLMLegacyMoreDesignParser()
    parser.parse(INPUT_DIR)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 7 parquets — sufixo _manual_ pra cair no setup_views_with_manual
    conversations_to_df(parser.conversations).to_parquet(
        OUTPUT_DIR / "notebooklm_manual_conversations.parquet", index=False)
    messages_to_df(parser.messages).to_parquet(
        OUTPUT_DIR / "notebooklm_manual_messages.parquet", index=False)
    tool_events_to_df([]).to_parquet(
        OUTPUT_DIR / "notebooklm_manual_tool_events.parquet", index=False)
    branches_to_df(parser.branches).to_parquet(
        OUTPUT_DIR / "notebooklm_manual_branches.parquet", index=False)
    project_docs_to_df(parser.sources).to_parquet(
        OUTPUT_DIR / "notebooklm_manual_sources.parquet", index=False)
    notebooklm_notes_to_df(parser.notes).to_parquet(
        OUTPUT_DIR / "notebooklm_manual_notes.parquet", index=False)
    notebooklm_outputs_to_df(parser.outputs).to_parquet(
        OUTPUT_DIR / "notebooklm_manual_outputs.parquet", index=False)
    notebooklm_guide_questions_to_df(parser.guide_questions).to_parquet(
        OUTPUT_DIR / "notebooklm_manual_guide_questions.parquet", index=False)

    print()
    print("=== STATS ===")
    print(f"  conversations:    {len(parser.conversations):>4}")
    print(f"  messages:         {len(parser.messages):>4}")
    print(f"  branches:         {len(parser.branches):>4}")
    print(f"  sources:          {len(parser.sources):>4}")
    print(f"  notes (briefs):   {len(parser.notes):>4}")
    print(f"  outputs:          {len(parser.outputs):>4}")
    print(f"  guide_questions:  {len(parser.guide_questions):>4}")
    print(f"\nOutput: {OUTPUT_DIR}/notebooklm_manual_*.parquet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
