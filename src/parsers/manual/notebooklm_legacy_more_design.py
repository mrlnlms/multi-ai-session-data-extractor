"""Parser pra captura legacy do NotebookLM (conta `more.design`, mar/2026).

Formato legacy de extractor antigo:
    <notebook_uuid>/
      notebook.json   {uuid, title, emoji, sources[{uuid, name}], guide{summary, questions[3]}}
      chat.json       (opcional) [{id, timestamp, role, content}, ...]
      audio/
        *.m4a              audio podcasts
        *.mp4              video podcasts
        *.pdf              slide decks (apresentacoes)
        unnamed.png        infographics
        <uuid>_brief.md    briefings/relatorios

Conta legacy extinta antes do canonico assumir, dado preservado em
data/external/notebooklm-snapshots/.

source = 'notebooklm', account = '3', capture_method = 'legacy_notebooklm_more_design'
"""

from __future__ import annotations

import json
import logging
import uuid as uuid_lib
from pathlib import Path
from typing import Optional

import pandas as pd

from src.parsers.base import BaseParser
from src.schema.models import (
    Branch,
    Conversation,
    Message,
    NotebookLMGuideQuestion,
    NotebookLMNote,
    NotebookLMOutput,
    ProjectDoc,
    VALID_OUTPUT_TYPES,
)

logger = logging.getLogger(__name__)

SOURCE = "notebooklm"
ACCOUNT = "3"
CAPTURE_METHOD = "legacy_notebooklm_more_design"

EXT_TO_OUTPUT = {
    ".m4a": (1, "audio_overview"),
    ".mp4": (3, "video_overview"),
    ".pdf": (8, "slide_deck"),
    ".png": (9, "infographic"),
}


class NotebookLMLegacyMoreDesignParser(BaseParser):
    source_name = "notebooklm_legacy_more_design"

    def __init__(self):
        super().__init__(account=ACCOUNT)
        self.branches: list[Branch] = []
        self.sources: list[ProjectDoc] = []
        self.notes: list[NotebookLMNote] = []
        self.outputs: list[NotebookLMOutput] = []
        self.guide_questions: list[NotebookLMGuideQuestion] = []

    def reset(self):
        super().reset()
        self.branches = []
        self.sources = []
        self.notes = []
        self.outputs = []
        self.guide_questions = []

    def parse(self, input_path: Path) -> None:
        input_path = Path(input_path)
        for nb_dir in sorted(input_path.iterdir()):
            if not nb_dir.is_dir():
                continue
            nb_json = nb_dir / "notebook.json"
            if not nb_json.exists():
                continue
            try:
                self._parse_notebook(nb_dir, nb_json)
            except Exception as e:
                logger.warning(f"  {nb_dir.name}: falha {e}")

    def _parse_notebook(self, nb_dir: Path, nb_json_path: Path) -> None:
        data = json.loads(nb_json_path.read_text(encoding="utf-8"))
        nb_uuid = data.get("uuid") or nb_dir.name
        title = data.get("title") or nb_uuid
        guide = data.get("guide") or {}
        if isinstance(guide, list):
            guide = guide[0] if guide else {}
        if not isinstance(guide, dict):
            guide = {}
        summary = guide.get("summary") if isinstance(guide.get("summary"), str) else None
        questions = guide.get("questions") or []
        sources_meta = data.get("sources") or []

        conv_id = f"account-{ACCOUNT}_{nb_uuid}"
        branch_id = f"{conv_id}_main"
        mtime = pd.Timestamp(nb_json_path.stat().st_mtime, unit="s", tz="UTC")

        # === Messages: system summary + chat turns ===
        msgs_local: list[Message] = []
        seq = 0
        first_msg_id: Optional[str] = None

        if summary:
            mid = f"{conv_id}_guide_summary"
            msgs_local.append(Message(
                message_id=mid, conversation_id=conv_id, source=SOURCE,
                sequence=seq, role="system", content=summary,
                model="gemini", created_at=mtime, account=ACCOUNT,
                branch_id=branch_id,
            ))
            first_msg_id = mid
            seq += 1

        last_msg_id = first_msg_id
        chat_path = nb_dir / "chat.json"
        if chat_path.exists():
            try:
                chat_data = json.loads(chat_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"  {nb_dir.name}/chat.json: {e}")
                chat_data = []
            if isinstance(chat_data, list):
                for turn in chat_data:
                    if not isinstance(turn, dict):
                        continue
                    role = turn.get("role")
                    if role not in ("user", "assistant", "system"):
                        continue
                    content = turn.get("content", "") or ""
                    tid = turn.get("id") or str(uuid_lib.uuid4())
                    ts_raw = turn.get("timestamp")
                    try:
                        created = pd.Timestamp(ts_raw, tz="UTC") if ts_raw else mtime
                    except Exception:
                        created = mtime
                    msgs_local.append(Message(
                        message_id=tid, conversation_id=conv_id, source=SOURCE,
                        sequence=seq, role=role, content=content,
                        model="gemini", created_at=created, account=ACCOUNT,
                        branch_id=branch_id,
                    ))
                    if first_msg_id is None:
                        first_msg_id = tid
                    last_msg_id = tid
                    seq += 1

        # === Branch ===
        self.branches.append(Branch(
            branch_id=branch_id, conversation_id=conv_id, source=SOURCE,
            root_message_id=first_msg_id or "",
            leaf_message_id=last_msg_id or first_msg_id or "",
            is_active=True, created_at=mtime,
        ))

        # === Sources (so metadata, sem content) ===
        for s in sources_meta:
            if not isinstance(s, dict):
                continue
            src_uuid = s.get("uuid")
            if not src_uuid:
                continue
            self.sources.append(ProjectDoc(
                doc_id=src_uuid, project_id=conv_id, source=SOURCE,
                file_name=s.get("name") or "",
                content="", content_size=0, estimated_token_count=0,
                created_at=mtime,
            ))

        # === Outputs + Notes (briefs) — varre audio/ ===
        audio_dir = nb_dir / "audio"
        if audio_dir.exists():
            for f in sorted(audio_dir.iterdir()):
                if not f.is_file() or f.name.startswith("."):
                    continue
                ext = f.suffix.lower()
                stem = f.stem

                if ext == ".md" and f.name.endswith("_brief.md"):
                    note_uuid = stem.replace("_brief", "")
                    try:
                        content = f.read_text(encoding="utf-8")
                    except Exception:
                        content = ""
                    title_brief = None
                    for line in content.split("\n", 6):
                        if line.startswith("# "):
                            title_brief = line[2:].strip()
                            break
                    self.notes.append(NotebookLMNote(
                        note_id=note_uuid, conversation_id=conv_id, source=SOURCE,
                        account=ACCOUNT, title=title_brief, content=content,
                        kind="brief", source_refs_json=None,
                        created_at=pd.Timestamp(f.stat().st_mtime, unit="s", tz="UTC"),
                    ))
                elif ext in EXT_TO_OUTPUT:
                    out_type, out_name = EXT_TO_OUTPUT[ext]
                    title_out = stem if stem != "unnamed" else None
                    self.outputs.append(NotebookLMOutput(
                        output_id=str(uuid_lib.uuid4()), conversation_id=conv_id,
                        source=SOURCE, account=ACCOUNT,
                        output_type=out_type, output_type_name=out_name,
                        title=title_out, status="completed",
                        asset_path=[str(f)],
                        content=None, source_refs_json=None,
                        created_at=pd.Timestamp(f.stat().st_mtime, unit="s", tz="UTC"),
                    ))

        # === Guide questions ===
        if isinstance(questions, list):
            for i, q in enumerate(questions):
                if not isinstance(q, str):
                    continue
                self.guide_questions.append(NotebookLMGuideQuestion(
                    question_id=f"{conv_id}_q{i}", conversation_id=conv_id,
                    source=SOURCE, account=ACCOUNT,
                    question_text=q, full_prompt=q, order=i,
                ))

        # === Conversation ===
        self.conversations.append(Conversation(
            conversation_id=conv_id, source=SOURCE, title=title,
            created_at=mtime, updated_at=mtime,
            message_count=len(msgs_local), model="gemini", account=ACCOUNT,
            mode="chat", url=f"https://notebooklm.google.com/notebook/{nb_uuid}",
            summary=summary, capture_method=CAPTURE_METHOD,
        ))
        self.messages.extend(msgs_local)
