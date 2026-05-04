"""Parser canonico v3 pra NotebookLM.

Le merged em data/merged/NotebookLM/account-{N}/ e gera 9 parquets em
data/processed/NotebookLM/:
- 4 canonicos (conversations, messages, tool_events, branches)
- 5 auxiliares (sources, notes, outputs, guide_questions, source_guides)

Schema canonico em src/schema/models.py.

Decisoes de design:
- guide.summary vira system message (sequence=0) em todo notebook — garante
  message_count >= 1 mesmo quando chat=None (a maioria dos notebooks tem
  chat=None empiricamente).
- 1 conversation por notebook
- 1 branch (main) por conversation — NotebookLM nao tem fork
- output_type=10 reservado pra mind_map
"""

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from src.schema.models import (
    Conversation, Message, ToolEvent, Branch, ProjectDoc,
    NotebookLMNote, NotebookLMOutput, NotebookLMGuideQuestion, NotebookLMSourceGuide,
    VALID_OUTPUT_TYPES,
    conversations_to_df, messages_to_df, tool_events_to_df, branches_to_df,
    project_docs_to_df,
    notebooklm_notes_to_df, notebooklm_outputs_to_df, notebooklm_guide_questions_to_df,
    notebooklm_source_guides_to_df,
)
from src.parsers._notebooklm_helpers import (
    extract_sources_from_metadata, extract_guide, extract_chat_turns,
    extract_notes, extract_artifacts_list, extract_artifact_content,
    extract_mind_map_tree, extract_source_guide, parse_source_content, parse_timestamp,
)


SOURCE = "notebooklm"


class NotebookLMParser:
    """Parser merged → 8 parquets canonicos+auxiliares."""

    source_name = SOURCE

    def parse(self, merged: dict, output_dir: Path) -> dict:
        """Parse merged dict, escreve 8 parquets em output_dir.

        merged dict format:
            {
                "notebooks": [
                    {
                        "uuid": str, "title": str, "account": str,
                        "metadata": <rLM1Ne raw>, "guide": <VfAZjd raw>,
                        "chat": <khqZz raw>, "notes": <cFji9 raw>,
                        "audios": <gArtLc raw>, "mind_map": <hPTbtc raw>,
                        "_artifacts_individual": {art_uuid: {raw}, ...},
                        "_mind_map_tree": {raw} or None,
                        "_preserved_missing": bool,
                        "_last_seen_in_server": str (date)
                    },
                    ...
                ],
                "sources": {
                    src_uuid: {"raw": <hizoJc raw>, ...},
                    ...
                }
            }

        Retorna stats {table_name: row_count}.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        convs: list[Conversation] = []
        msgs: list[Message] = []
        events: list[ToolEvent] = []
        branches: list[Branch] = []
        sources: list[ProjectDoc] = []
        notes: list[NotebookLMNote] = []
        outputs: list[NotebookLMOutput] = []
        questions: list[NotebookLMGuideQuestion] = []
        source_guides: list[NotebookLMSourceGuide] = []

        sources_raw = merged.get("sources", {})
        source_guides_raw = merged.get("source_guides", {})

        for nb in merged.get("notebooks", []):
            self._parse_notebook(
                nb, sources_raw, source_guides_raw,
                convs, msgs, events, branches,
                sources, notes, outputs, questions, source_guides,
            )

        # Write parquets (idempotente — overwrite)
        conversations_to_df(convs).to_parquet(
            output_dir / "notebooklm_conversations.parquet", index=False)
        messages_to_df(msgs).to_parquet(
            output_dir / "notebooklm_messages.parquet", index=False)
        tool_events_to_df(events).to_parquet(
            output_dir / "notebooklm_tool_events.parquet", index=False)
        branches_to_df(branches).to_parquet(
            output_dir / "notebooklm_branches.parquet", index=False)
        project_docs_to_df(sources).to_parquet(
            output_dir / "notebooklm_sources.parquet", index=False)
        notebooklm_notes_to_df(notes).to_parquet(
            output_dir / "notebooklm_notes.parquet", index=False)
        notebooklm_outputs_to_df(outputs).to_parquet(
            output_dir / "notebooklm_outputs.parquet", index=False)
        notebooklm_guide_questions_to_df(questions).to_parquet(
            output_dir / "notebooklm_guide_questions.parquet", index=False)
        notebooklm_source_guides_to_df(source_guides).to_parquet(
            output_dir / "notebooklm_source_guides.parquet", index=False)

        return {
            "conversations": len(convs),
            "messages": len(msgs),
            "tool_events": len(events),
            "branches": len(branches),
            "sources": len(sources),
            "notes": len(notes),
            "outputs": len(outputs),
            "guide_questions": len(questions),
            "source_guides": len(source_guides),
        }

    def _parse_notebook(
        self, nb: dict, sources_raw: dict, source_guides_raw: dict,
        convs: list, msgs: list, events: list, branches: list,
        sources: list, notes: list, outputs: list, questions: list,
        source_guides: list,
    ):
        account = str(nb.get("account", "1"))
        nb_uuid = nb["uuid"]
        conv_id = f"account-{account}_{nb_uuid}"

        # Timestamps from discovery (preferable) or metadata
        created_at = parse_timestamp(nb.get("create_time"))
        updated_at = parse_timestamp(nb.get("update_time"))
        if created_at is None:
            created_at = pd.Timestamp.now(tz="UTC")
        if updated_at is None:
            updated_at = created_at

        is_preserved = bool(nb.get("_preserved_missing", False))
        last_seen = nb.get("_last_seen_in_server")
        last_seen_ts = parse_timestamp(last_seen) if last_seen else None

        # Guide → summary + questions
        guide = extract_guide(nb.get("guide"))
        summary = guide.get("summary")

        # === Sources ===
        source_entries = extract_sources_from_metadata(nb.get("metadata"))
        for s in source_entries:
            src_raw_payload = sources_raw.get(s["uuid"])
            if src_raw_payload is None:
                continue
            content = parse_source_content(src_raw_payload.get("raw"))
            sources.append(ProjectDoc(
                doc_id=s["uuid"],
                project_id=conv_id,
                source=SOURCE,
                file_name=s.get("filename") or "",
                content=content or "",
                content_size=len(content or ""),
                estimated_token_count=(len(content or "") // 4) if content else 0,
                created_at=created_at,
            ))

            # Source guide (tr032e — summary + tags + questions)
            guide_payload = source_guides_raw.get(s["uuid"])
            if guide_payload is not None:
                g = extract_source_guide(guide_payload.get("raw"))
                if g.get("summary") or g.get("tags") or g.get("questions"):
                    source_guides.append(NotebookLMSourceGuide(
                        source_id=s["uuid"],
                        conversation_id=conv_id,
                        source=SOURCE,
                        account=account,
                        summary=g.get("summary"),
                        tags_json=json.dumps(g.get("tags", [])) if g.get("tags") else None,
                        questions_json=json.dumps(g.get("questions", [])) if g.get("questions") else None,
                    ))

        # === Messages: system summary + chat turns ===
        chat_turns = extract_chat_turns(nb.get("chat")) or []
        sequence = 0
        first_msg_id: Optional[str] = None

        if summary:
            msg_id = f"{conv_id}_guide_summary"
            msgs.append(Message(
                message_id=msg_id,
                conversation_id=conv_id,
                source=SOURCE,
                sequence=sequence,
                role="system",
                content=summary,
                model="gemini",
                created_at=created_at,
                account=account,
                branch_id=f"{conv_id}_main",
            ))
            first_msg_id = msg_id
            sequence += 1

        last_msg_id = first_msg_id
        for turn in chat_turns:
            tid = turn.get("id") or f"{conv_id}_turn_{sequence}"
            msgs.append(Message(
                message_id=tid,
                conversation_id=conv_id,
                source=SOURCE,
                sequence=sequence,
                role=turn.get("role", "user"),
                content=turn.get("content", ""),
                model="gemini",
                created_at=parse_timestamp(turn.get("created_at")) or created_at,
                account=account,
                branch_id=f"{conv_id}_main",
            ))
            if first_msg_id is None:
                first_msg_id = tid
            last_msg_id = tid
            sequence += 1

        # === Branch ===
        branches.append(Branch(
            branch_id=f"{conv_id}_main",
            conversation_id=conv_id,
            source=SOURCE,
            root_message_id=first_msg_id or "",
            leaf_message_id=last_msg_id or first_msg_id or "",
            is_active=True,
            created_at=created_at,
        ))

        # === Notes ===
        for n in extract_notes(nb.get("notes")):
            try:
                notes.append(NotebookLMNote(
                    note_id=n["uuid"],
                    conversation_id=conv_id,
                    source=SOURCE,
                    account=account,
                    title=n.get("title"),
                    content=n.get("content", ""),
                    kind=n.get("kind", "note"),
                    source_refs_json=json.dumps(n.get("source_refs", [])) if n.get("source_refs") else None,
                    created_at=parse_timestamp(n.get("created_at")),
                ))
            except ValueError:
                # kind invalido — skip silently (pra evitar quebra em edge cases)
                continue

        # === Outputs (artifacts + mind_map) ===
        artifacts_list = extract_artifacts_list(nb.get("audios"))
        individual = nb.get("_artifacts_individual", {})
        for art in artifacts_list:
            t = art["type"]
            if t not in VALID_OUTPUT_TYPES:
                continue
            content = None
            if t in {2, 4, 7, 9} and art["uuid"] in individual:
                content = extract_artifact_content(individual[art["uuid"]].get("raw"), t)
            outputs.append(NotebookLMOutput(
                output_id=art["uuid"],
                conversation_id=conv_id,
                source=SOURCE,
                account=account,
                output_type=t,
                output_type_name=VALID_OUTPUT_TYPES[t],
                title=art.get("title"),
                status=art.get("status"),
                asset_path=art.get("asset_paths"),
                content=content,
                source_refs_json=json.dumps(art.get("source_refs", [])) if art.get("source_refs") else None,
                created_at=parse_timestamp(art.get("created_at")),
            ))

        # Mind map (output type=10)
        mm_payload = nb.get("_mind_map_tree")
        if mm_payload:
            mm_uuid = mm_payload.get("mind_map_uuid", f"{nb_uuid}_mm")
            # Preferir 'tree' completa (asset) quando disponivel; fallback
            # pra serializacao de 'raw' (metadata do CYK0Xb).
            tree_full = mm_payload.get("tree")
            if tree_full:
                content_str = json.dumps(tree_full, ensure_ascii=False)
            else:
                content_str = extract_mind_map_tree(mm_payload.get("raw"))
            outputs.append(NotebookLMOutput(
                output_id=mm_uuid,
                conversation_id=conv_id,
                source=SOURCE,
                account=account,
                output_type=10,
                output_type_name="mind_map",
                title=None,
                status=None,
                asset_path=None,
                content=content_str or None,
                source_refs_json=None,
                created_at=created_at,
            ))

        # === Guide questions ===
        for q in guide.get("questions", []):
            i = q["order"]
            questions.append(NotebookLMGuideQuestion(
                question_id=f"{conv_id}_q{i}",
                conversation_id=conv_id,
                source=SOURCE,
                account=account,
                question_text=q["text"],
                full_prompt=q.get("prompt", ""),
                order=i,
            ))

        # === Conversation ===
        message_count = sum(1 for m in msgs if m.conversation_id == conv_id)
        title = nb.get("title")
        # rLM1Ne pode ter title atualizado em metadata[0][0]
        meta = nb.get("metadata")
        if meta and isinstance(meta, list) and meta and isinstance(meta[0], list):
            if meta[0] and isinstance(meta[0][0], str):
                title = meta[0][0]

        convs.append(Conversation(
            conversation_id=conv_id,
            source=SOURCE,
            title=title,
            created_at=created_at,
            updated_at=updated_at,
            message_count=message_count,
            model="gemini",
            account=account,
            mode="chat",
            url=f"https://notebooklm.google.com/notebook/{nb_uuid}",
            summary=summary,
            is_preserved_missing=is_preserved,
            last_seen_in_server=last_seen_ts,
        ))
