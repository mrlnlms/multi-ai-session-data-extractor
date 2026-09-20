"""Parser canonico v3 pra NotebookLM.

Le merged em data/merged/NotebookLM/account-{N}/ e gera 11 parquets em
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
import mimetypes
import uuid as uuid_lib
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import pandas as pd

from src.assets.reader import (
    AssetReader,
    apply_asset_projection,
    combine_asset_projections,
)
from src.assets.appearances import commit_web_parser_appearances
from src.schema.models import (
    Conversation, Message, ToolEvent, Branch, ProjectDoc, Asset, AssetLink,
    NotebookLMNote, NotebookLMOutput, NotebookLMGuideQuestion, NotebookLMSourceGuide,
    VALID_OUTPUT_TYPES,
    conversations_to_df, messages_to_df, tool_events_to_df, branches_to_df,
    project_docs_to_df,
    notebooklm_notes_to_df, notebooklm_outputs_to_df, notebooklm_guide_questions_to_df,
    notebooklm_source_guides_to_df,
    assets_to_df, asset_links_to_df, make_asset_link_id,
)
from src.platforms.notebooklm._parser_helpers import (
    extract_sources_from_metadata, extract_guide, extract_chat_turns,
    extract_notes, extract_artifacts_list, extract_artifact_content,
    extract_mind_map_tree, extract_source_guide, parse_source_content, parse_timestamp,
)

if TYPE_CHECKING:
    from src.platforms.notebooklm.historical_parser import NotebookLMHistoricalResult


SOURCE = "notebooklm"
_ASSET_NAMESPACE = uuid_lib.UUID("0463b48b-99c2-4f22-a61d-35b76a67f012")


def _data_relative(path: Path) -> str:
    """Return a portable path below data/, as required by the asset contract."""
    resolved = path.resolve()
    parts = resolved.parts
    try:
        data_index = len(parts) - 1 - tuple(reversed(parts)).index("data")
    except ValueError:
        # Custom parser roots (notably tests) still publish paths in the same
        # logical data namespace as the production layout.
        if "snapshots" in parts:
            marker = parts.index("snapshots")
            return Path("external", "notebooklm-snapshots", *parts[marker + 1:]).as_posix()
        account_parts = [i for i, part in enumerate(parts) if part.startswith("account-")]
        if account_parts:
            marker = account_parts[-1]
            return Path("merged", "NotebookLM", *parts[marker:]).as_posix()
        raise ValueError(f"NotebookLM asset has no recognizable data layout: {path}")
    return Path(*parts[data_index + 1:]).as_posix()


def _child_asset_id(parent_id: str, relative_path: str) -> str:
    return str(uuid_lib.uuid5(_ASSET_NAMESPACE, f"{parent_id}\x1f{relative_path}"))


class NotebookLMParser:
    """Parser for current merged data plus optional historical rows."""

    source_name = SOURCE

    def __init__(self, *, asset_reader: AssetReader | None = None) -> None:
        self.web_asset_vault = None
        if asset_reader is None:
            from src.assets.runtime import load_asset_runtime

            runtime = load_asset_runtime(self.source_name)
            asset_reader = runtime.reader
            self.web_asset_vault = runtime.vault
        self.asset_reader = asset_reader

    def parse(
        self,
        merged: dict,
        output_dir: Path,
        historical: "NotebookLMHistoricalResult | None" = None,
    ) -> dict:
        """Parse the merged payload and write eleven Parquets to output_dir.

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
        assets: list[Asset] = []
        asset_links: list[AssetLink] = []

        sources_raw = merged.get("sources", {})
        source_guides_raw = merged.get("source_guides", {})

        for nb in merged.get("notebooks", []):
            self._parse_notebook(
                nb, sources_raw, source_guides_raw,
                convs, msgs, events, branches,
                sources, notes, outputs, questions, source_guides,
                assets, asset_links,
            )

        if historical is not None:
            convs.extend(historical.conversations)
            msgs.extend(historical.messages)
            events.extend(historical.tool_events)
            branches.extend(historical.branches)
            sources.extend(historical.sources)
            notes.extend(historical.notes)
            outputs.extend(historical.outputs)
            questions.extend(historical.guide_questions)
            assets.extend(historical.assets)
            asset_links.extend(historical.asset_links)

        if self.asset_reader is not None:
            if self.web_asset_vault is not None:
                commit_web_parser_appearances(
                    self.web_asset_vault,
                    source=self.source_name,
                    assets=assets,
                    links=asset_links,
                    messages=msgs,
                    evidence_path=output_dir,
                )
            projection = combine_asset_projections(
                self.asset_reader,
                self.source_name,
                (asset.account_id for asset in assets),
            )
            assets = list(projection.assets)
            asset_links = list(projection.links)
            apply_asset_projection(msgs, projection)

        # Enforce the published output PK at the parser boundary. NotebookLM's
        # artifact RPC can repeat an artifact row; keep the last representation,
        # matching the unifier's existing collision policy.
        outputs = list({
            (item.source, item.conversation_id, item.output_id): item
            for item in outputs
        }.values())

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
        assets_to_df(assets).to_parquet(
            output_dir / "notebooklm_assets.parquet", index=False)
        asset_links_to_df(asset_links).to_parquet(
            output_dir / "notebooklm_asset_links.parquet", index=False)

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
            "assets": len(assets),
            "asset_links": len(asset_links),
        }

    def _parse_notebook(
        self, nb: dict, sources_raw: dict, source_guides_raw: dict,
        convs: list, msgs: list, events: list, branches: list,
        sources: list, notes: list, outputs: list, questions: list,
        source_guides: list,
        assets: list, asset_links: list,
    ):
        account = str(nb.get("account", "1"))
        account_key = str(nb.get("account_key", account))
        account_id = nb.get("account_id")
        nb_uuid = nb["uuid"]
        conv_id = f"account-{account_key}_{nb_uuid}"

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
                account_id=account_id,
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
                        account_id=account_id,
                        account=account,
                        summary=g.get("summary"),
                        tags_json=json.dumps(g.get("tags", [])) if g.get("tags") else None,
                        questions_json=json.dumps(g.get("questions", [])) if g.get("questions") else None,
                    ))

            self._append_source_assets(
                nb, s["uuid"], conv_id, account_id, created_at, assets, asset_links,
            )

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
                account_id=account_id,
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
                account_id=account_id,
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
            account_id=account_id,
            root_message_id=first_msg_id or "",
            leaf_message_id=last_msg_id or first_msg_id or "",
            is_active=True,
            created_at=created_at,
        ))

        # === Notes ===
        parsed_notes = extract_notes(nb.get("notes"))
        for n in parsed_notes:
            try:
                notes.append(NotebookLMNote(
                    note_id=n["uuid"],
                    conversation_id=conv_id,
                    source=SOURCE,
                    account_id=account_id,
                    account=account,
                    title=n.get("title"),
                    content=n.get("content", ""),
                    kind=n.get("kind", "note"),
                    source_refs_json=json.dumps(n.get("source_refs", [])) if n.get("source_refs") else None,
                    created_at=parse_timestamp(n.get("created_at")),
                    origin=n.get("origin"),
                ))
                self._append_note_asset(
                    nb, n["uuid"], conv_id, account_id,
                    parse_timestamp(n.get("created_at")), n.get("origin"),
                    n.get("note_type"), assets, asset_links,
                )
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
            preserved_paths = self._append_output_assets(
                nb, art["uuid"], conv_id, account_id,
                parse_timestamp(art.get("created_at")), assets, asset_links,
            )
            outputs.append(NotebookLMOutput(
                output_id=art["uuid"],
                conversation_id=conv_id,
                source=SOURCE,
                account_id=account_id,
                account=account,
                output_type=t,
                output_type_name=VALID_OUTPUT_TYPES[t],
                title=art.get("title"),
                status=art.get("status"),
                asset_path=preserved_paths or art.get("asset_paths"),
                content=content,
                source_refs_json=json.dumps(art.get("source_refs", [])) if art.get("source_refs") else None,
                created_at=parse_timestamp(art.get("created_at")),
            ))

        # Mind map (output type=10)
        mm_payload = nb.get("_mind_map_tree")
        if mm_payload:
            mm_uuid = mm_payload.get("mind_map_uuid", f"{nb_uuid}_mm")
            mm_artifact = next(
                (art for art in artifacts_list if art["uuid"] == mm_uuid), {}
            )
            # Preferir 'tree' completa (asset) quando disponivel; fallback
            # pra serializacao de 'raw' (metadata do CYK0Xb).
            tree_full = mm_payload.get("tree")
            if tree_full:
                content_str = json.dumps(tree_full, ensure_ascii=False)
            else:
                content_str = extract_mind_map_tree(mm_payload.get("raw"))
            preserved_paths = self._append_mind_map_assets(
                nb, mm_uuid, conv_id, account, account_id, created_at,
                {art["uuid"]: art for art in artifacts_list},
                outputs, assets, asset_links,
            )
            outputs.append(NotebookLMOutput(
                output_id=mm_uuid,
                conversation_id=conv_id,
                source=SOURCE,
                account_id=account_id,
                account=account,
                output_type=10,
                output_type_name="mind_map",
                title=mm_artifact.get("title"),
                status=mm_artifact.get("status"),
                asset_path=preserved_paths or None,
                content=content_str or None,
                source_refs_json=(
                    json.dumps(mm_artifact.get("source_refs", []))
                    if mm_artifact.get("source_refs") else None
                ),
                created_at=(
                    parse_timestamp(mm_artifact.get("created_at")) or created_at
                ),
            ))

        # === Guide questions ===
        for q in guide.get("questions", []):
            i = q["order"]
            questions.append(NotebookLMGuideQuestion(
                question_id=f"{conv_id}_q{i}",
                conversation_id=conv_id,
                source=SOURCE,
                account_id=account_id,
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
            account_id=account_id,
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

    @staticmethod
    def _append_asset(
        path: Path, asset_id: str, account_id: str | None, kind: str,
        origin: str, generated: bool, created_at, metadata: dict,
        object_type: str, object_id: str, conversation_id: str,
        role: str, ordinal: int, assets: list, links: list,
    ) -> None:
        relative = _data_relative(path)
        assets.append(Asset(
            asset_id=asset_id, source=SOURCE, account_id=account_id,
            asset_kind=kind, asset_origin=origin, file_name=path.name,
            mime_type=mimetypes.guess_type(path.name)[0], size_bytes=path.stat().st_size,
            asset_path=relative, is_model_generated=generated,
            is_preserved_missing=False, is_binary_available=True,
            created_at=created_at,
            metadata_json=json.dumps(metadata, sort_keys=True),
        ))
        links.append(AssetLink(
            asset_link_id=make_asset_link_id(
                SOURCE, account_id, asset_id, object_type, object_id, role, ordinal,
            ),
            source=SOURCE, account_id=account_id, asset_id=asset_id,
            object_type=object_type, object_id=object_id,
            conversation_id=conversation_id, message_id=None,
            project_id=conversation_id, role=role, ordinal=ordinal,
            content_block_index=None, metadata_json=None,
        ))

    def _append_source_assets(
        self, nb: dict, source_id: str, conv_id: str, account_id: str | None,
        created_at, assets: list, links: list,
    ) -> None:
        account_dir = nb.get("_account_dir")
        if not account_dir:
            return
        page_dir = Path(account_dir) / "assets" / "source_pages" / source_id
        for ordinal, path in enumerate(sorted(p for p in page_dir.glob("*") if p.is_file())):
            relative = _data_relative(path)
            self._append_asset(
                path, _child_asset_id(source_id, relative), account_id,
                "artifact", "platform", False, created_at,
                {"representation": "rendered_source_page", "source_id": source_id},
                "source", source_id, conv_id, "context", ordinal, assets, links,
            )

    def _append_output_assets(
        self, nb: dict, output_id: str, conv_id: str, account_id: str | None,
        created_at, assets: list, links: list,
    ) -> list[str]:
        account_dir = nb.get("_account_dir")
        if not account_dir:
            return []
        root = Path(account_dir) / "assets"
        matches = []
        for subdir in ("audio_overviews", "video_overviews"):
            matches.extend(root.joinpath(subdir).glob(f"{nb['uuid']}_{output_id}.*"))
        matches.extend(root.joinpath("slide_decks", f"{nb['uuid']}_{output_id}").glob("*"))
        matches.extend(
            root.joinpath("text_artifacts").glob(
                f"{nb['uuid']}_{output_id}_type*.json"
            )
        )
        paths = sorted(p for p in matches if p.is_file())
        mind_map_path = root / "mind_maps" / f"{nb['uuid']}_{output_id}.json"
        representation_count = len(paths) + int(mind_map_path.is_file())
        for ordinal, path in enumerate(paths):
            relative = _data_relative(path)
            asset_id = (
                output_id if representation_count == 1
                else _child_asset_id(output_id, relative)
            )
            self._append_asset(
                path, asset_id, account_id, "output", "assistant", True, created_at,
                {"representation": "generated_output", "output_id": output_id},
                "output", output_id, conv_id, "output", ordinal, assets, links,
            )
        return [_data_relative(path) for path in paths]

    def _append_mind_map_assets(
        self, nb: dict, output_id: str, conv_id: str, account: str,
        account_id: str | None, created_at, artifacts_by_id: dict,
        outputs: list, assets: list, links: list,
    ) -> list[str]:
        account_dir = nb.get("_account_dir")
        if not account_dir:
            return []
        paths = sorted(
            p for p in (
                Path(account_dir) / "assets" / "mind_maps"
            ).glob(f"{nb['uuid']}_*.json") if p.is_file()
        )
        current_paths: list[str] = []
        for ordinal, path in enumerate(paths):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            preserved_id = payload.get("mind_map_uuid")
            if not isinstance(preserved_id, str) or not preserved_id:
                continue
            relative = _data_relative(path)
            text_matches = list(
                (Path(account_dir) / "assets" / "text_artifacts").glob(
                    f"{nb['uuid']}_{preserved_id}_type*.json"
                )
            )
            asset_id = (
                _child_asset_id(preserved_id, relative)
                if text_matches else preserved_id
            )
            self._append_asset(
                path, asset_id, account_id, "output", "assistant", True,
                created_at,
                {"representation": "generated_mind_map", "output_id": preserved_id},
                "output", preserved_id, conv_id, "output", 0, assets, links,
            )
            if preserved_id == output_id:
                current_paths.extend(_data_relative(p) for p in sorted(text_matches))
                current_paths.append(relative)
                continue
            artifact = artifacts_by_id.get(preserved_id, {})
            tree = payload.get("tree")
            outputs.append(NotebookLMOutput(
                output_id=preserved_id,
                conversation_id=conv_id,
                source=SOURCE,
                account_id=account_id,
                account=account,
                output_type=10,
                output_type_name="mind_map",
                title=artifact.get("title"),
                status=artifact.get("status") or "preserved_missing",
                asset_path=[
                    *(_data_relative(p) for p in sorted(text_matches)), relative,
                ],
                content=json.dumps(tree, ensure_ascii=False) if tree else None,
                source_refs_json=(
                    json.dumps(artifact.get("source_refs", []))
                    if artifact.get("source_refs") else None
                ),
                created_at=(
                    parse_timestamp(artifact.get("created_at"))
                    if artifact else None
                ),
            ))
        return current_paths

    def _append_note_asset(
        self, nb: dict, note_id: str, conv_id: str, account_id: str | None,
        created_at, origin: str | None, note_type: int | None,
        assets: list, links: list,
    ) -> bool:
        account_dir = nb.get("_account_dir")
        if not account_dir:
            return False
        path = (
            Path(account_dir) / "assets" / "notes" /
            f"{nb['uuid']}_{note_id}.md"
        )
        if not path.is_file():
            return False
        asset_origin = origin or "unknown"
        generated = True if origin == "assistant" else False if origin == "user" else None
        role = "output" if origin == "assistant" else "context" if origin == "user" else "unknown"
        self._append_asset(
            path, note_id, account_id, "artifact", asset_origin, generated,
            created_at,
            {"representation": "notebook_note", "note_id": note_id,
             "note_type": note_type},
            "note", note_id, conv_id, role, 0, assets, links,
        )
        return True
