"""Parser canonico do Gemini — schema v3.

Consome merged em data/merged/Gemini/account-N/conversations/<uuid>.json
+ assets/. Schema raw eh posicional (Google batchexecute, sem keys).

Cobertura (probe 2026-05-02 em 80 convs):
- Multi-conta: itera as arvores `account-N`, namespace `{account}_{uuid}` em
  conversation_id pra evitar colisao
- Turn → user message + assistant message (par sequencial)
- Model name (turn[3][21], e.g. '2.5 Flash') → Message.model
- Thinking blocks (turn[3][0][0][37+]) → Message.thinking
- Image URLs (lh3.googleusercontent / gstatic, regex over JSON) → ToolEvent
  event_type='image_generation' + Message.asset_paths via manifest
- Deep Research markdown reports (extraidos offline pelo asset_downloader)
  → canonical Asset + exact message AssetLink when the sidecar path permits
- Locale em settings_json
- Preservation: _preserved_missing → Conversation.is_preserved_missing
- last_seen_in_server preservado

Limitacoes conhecidas:
- Gemini nao expoe updated_at — usa max(turn timestamps) como proxy
- Branches (drafts/regenerate alternativos via turn[1]): nao implementado
  na v3 (poucos casos detectados — adicionar quando aparecer dado real)
- Search/grounding citations: extraidas via extract_turn_citations
  (probe 2026-05-04). Detecta listas [favicon_url, source_url, title,
  snippet, ...] no schema posicional. Populadas em Message.citations_json
  + ToolEvents tipo 'search_result' (1 por citation, dedup por url).

Output: data/processed/Gemini/{conversations,messages,tool_events,assets,asset_links,
agent_memories,agent_memory_versions,agent_memory_temporal_evidence}.parquet
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Mapping, Optional

import pandas as pd

from src.account_catalog import legacy_fallback_key

from src.assets.reader import AssetReader
from src.platforms.gemini._parser_helpers import (
    conv_last_timestamp,
    conv_turns,
    extract_image_urls_from_turn,
    extract_turn_citations,
    turn_assistant_response_id,
    turn_assistant_text,
    turn_locale,
    turn_model_name,
    turn_response_id,
    turn_thinking_blocks,
    turn_timestamp_secs,
    turn_user_text,
)
from src.parsing.base import BaseParser
from src.schema.models import (
    Asset,
    AssetLink,
    Conversation,
    Message,
    ToolEvent,
    agent_memories_to_df,
    agent_memory_versions_to_df,
    agent_memory_temporal_evidence_to_df,
    asset_links_to_df,
    assets_to_df,
    make_asset_link_id,
)


logger = logging.getLogger(__name__)
SOURCE = "gemini"


def _raw_gemini_root(merged_root: Path) -> Path:
    """Resolve the sibling raw/Gemini tree for production and test roots."""
    if merged_root.parent.name == "merged":
        return merged_root.parent.parent / "raw" / merged_root.name
    return Path("data/raw/Gemini")


def _load_assets_manifest(merged_root: Path, account: str) -> dict[str, dict]:
    """Load the per-account image manifest keyed by its preserved URL.

    Manifest fica em data/raw/Gemini/account-{N}/assets_manifest.json
    (asset_downloader escreve no raw, nao no merged).
    """
    raw_dir = _raw_gemini_root(merged_root) / f"account-{account}"
    p = raw_dir / "assets_manifest.json"
    if not p.exists():
        return {}
    try:
        manifest = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

    url_map: dict[str, dict] = {}
    for hash_id, info in manifest.items():
        if not isinstance(info, dict):
            continue
        url = info.get("url")
        if url:
            url_map[url] = dict(info, manifest_key=hash_id)
    return url_map


def _contains_string(node: object, value: str) -> bool:
    if isinstance(node, str):
        return value in node
    if isinstance(node, list):
        return any(_contains_string(item, value) for item in node)
    if isinstance(node, dict):
        return any(_contains_string(item, value) for item in node.values())
    return False


def _report_location(source_path: str) -> tuple[int, str] | None:
    """Return the observed turn index and role encoded by extractor paths."""
    import re
    match = re.match(r"^\[0\]\[(\d+)\]\[(2|3)\]", source_path or "")
    if not match:
        return None
    return int(match.group(1)), "user" if match.group(2) == "2" else "assistant"


class GeminiParser(BaseParser):
    source_name = SOURCE

    def __init__(
        self,
        account: Optional[str] = None,
        merged_root: Optional[Path] = None,
        account_labels: Mapping[str, str] | None = None,
        account_ids: Mapping[str, str] | None = None,
        *,
        asset_reader: AssetReader | None = None,
    ):
        super().__init__(account, asset_reader=asset_reader)
        self.merged_root = Path(merged_root) if merged_root else Path("data/merged/Gemini")
        self.account_labels = dict(account_labels or {})
        self.account_ids = dict(account_ids or {})
        self.assets: list[Asset] = []
        self.asset_links: list[AssetLink] = []
        self.agent_memories = []
        self.agent_memory_versions = []
        self.agent_memory_temporal_evidence = []

    def parse(self, input_path: Path | None = None) -> None:
        """Itera merged/Gemini/account-{N}/conversations/.

        Se input_path for fornecido, le so dele. Senao usa self.merged_root.
        """
        root = input_path or self.merged_root
        if not root.exists():
            logger.warning(f"merged root nao existe: {root}")
            return

        account_dirs = []
        for acc_dir in root.glob("account-*"):
            account_dirs.append((acc_dir.name.removeprefix("account-"), acc_dir))
        for acc, acc_dir in sorted(account_dirs):
            self._parse_account(acc_dir, acc)
        self.apply_asset_reader(asset.account_id for asset in self.assets)

    def _parse_account(self, account_dir: Path, account: str) -> None:
        manifest = _load_assets_manifest(self.merged_root, account)
        account_label = self.account_labels.get(f"account-{account}", str(account))
        account_id = self.account_ids.get(str(account))
        conversation_namespace = (
            legacy_fallback_key("Gemini", account_id) if account_id else None
        ) or account
        conv_dir = account_dir / "conversations"
        if not conv_dir.exists():
            return

        # Descoberta titulada (titulos vivem em discovery_ids.json — nao no body).
        # Pinned tambem vem da discovery (campo c[2] do MaZiqc — confirmado em
        # 2026-05-02 via probe). Body nao expoe pinned status.
        titles: dict[str, str] = {}
        created_at_secs: dict[str, int] = {}
        pinned_set: set[str] = set()
        deleted_set: set[str] = set()
        disc_path = account_dir / "discovery_ids.json"
        if disc_path.exists():
            try:
                disc = json.loads(disc_path.read_text(encoding="utf-8"))
                for entry in disc:
                    if not isinstance(entry, dict):
                        continue
                    uid = entry.get("uuid")
                    if not uid:
                        continue
                    titles[uid] = entry.get("title") or ""
                    created_at_secs[uid] = entry.get("created_at_secs") or 0
                    if entry.get("pinned"):
                        pinned_set.add(uid)
                    if entry.get("_deleted_from_server"):
                        deleted_set.add(uid)
            except Exception as e:
                logger.warning(f"discovery parse fail account {account}: {e}")

        for jp in sorted(conv_dir.glob("*.json")):
            try:
                obj = json.loads(jp.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"skip {jp.name}: {e}")
                continue
            self._parse_conv(
                obj, account, conversation_namespace, account_label, account_id,
                titles, created_at_secs, pinned_set, manifest
            )
        self._append_manifest_catalog(account, account_id, manifest)
        self._canonicalize_image_message_paths(account, account_id)

    def _canonicalize_image_message_paths(
        self, account: int, account_id: str | None
    ) -> None:
        """Point message paths at the content-deduplicated image representation."""
        image_assets = {
            asset.asset_id: asset
            for asset in self.assets
            if asset.account_id == account_id
            and asset.asset_path is not None
            and asset.metadata_json == '{"representation": "hosted_image"}'
        }
        for message in self.messages:
            if message.account_id != account_id or not message.asset_paths:
                continue
            canonical_paths: list[str] = []
            for path_value in message.asset_paths:
                representation = (
                    self.merged_root / f"account-{account}" / "assets" /
                    Path(path_value).name
                )
                asset = image_assets.get(self._asset_id(representation, str(path_value)))
                if asset is not None and asset.asset_path is not None:
                    canonical_paths.append(asset.asset_path)
            message.asset_paths = canonical_paths or None

    def _parse_conv(
        self,
        obj: dict,
        account: str,
        conversation_namespace: str,
        account_label: str,
        account_id: str | None,
        titles: dict[str, str],
        created_at_secs: dict[str, int],
        pinned_set: set[str],
        manifest: dict[str, dict],
    ) -> None:
        uuid = obj.get("uuid")
        if not uuid:
            return

        raw = obj.get("raw")
        is_preserved = bool(obj.get("_preserved_missing"))
        last_seen = obj.get("_last_seen_in_server")

        # Namespace por account
        conv_id = f"account-{conversation_namespace}_{uuid}"

        title = titles.get(uuid) or ""
        created_secs = created_at_secs.get(uuid, 0) or 0
        last_secs = conv_last_timestamp(raw) or created_secs

        # Iterate turns → user + assistant messages
        turns = conv_turns(raw)

        msg_ids_in_order: list[str] = []
        seq = 0
        msg_count = 0
        models_seen: set[str] = set()
        first_locale: str | None = None

        for turn_idx, turn in enumerate(turns):
            ts_secs = turn_timestamp_secs(turn) or created_secs
            ts = self._ts(ts_secs)

            # User message
            user_text = turn_user_text(turn)
            if user_text is not None:
                seq += 1
                user_msg_id = f"{conv_id}_t{turn_idx}_user"
                self.messages.append(Message(
                    message_id=user_msg_id,
                    conversation_id=conv_id,
                    source=SOURCE,
                    account_id=account_id,
                    sequence=seq,
                    role="user",
                    content=user_text,
                    model=None,
                    created_at=ts,
                    account=account_label,
                    content_types="text",
                ))
                msg_ids_in_order.append(user_msg_id)
                msg_count += 1

            # Assistant message
            assistant_text = turn_assistant_text(turn)
            model_name = turn_model_name(turn)
            if model_name:
                models_seen.add(model_name)
            if first_locale is None:
                first_locale = turn_locale(turn)

            # Thinking blocks
            thinking = "\n\n---\n\n".join(turn_thinking_blocks(turn)) or None

            # Image URLs
            img_urls = extract_image_urls_from_turn(turn)
            asset_paths: list[str] = []
            for url in img_urls:
                info = manifest.get(url)
                if info:
                    asset_paths.append(
                        f"data/merged/Gemini/account-{account}/assets/{info['filename']}"
                    )

            # Search/Deep Research citations (probe 2026-05-04)
            citations = extract_turn_citations(turn)

            if assistant_text or thinking or img_urls:
                seq += 1
                asst_msg_id = f"{conv_id}_t{turn_idx}_asst"
                resp_id = turn_assistant_response_id(turn) or turn_response_id(turn)
                attachment_filenames = [u.split("/")[-1].split("?")[0] for u in img_urls]
                self.messages.append(Message(
                    message_id=asst_msg_id,
                    conversation_id=conv_id,
                    source=SOURCE,
                    account_id=account_id,
                    sequence=seq,
                    role="assistant",
                    content=assistant_text or "",
                    thinking=thinking,
                    model=model_name,
                    created_at=ts,
                    account=account_label,
                    content_types="text" if not img_urls else "text+image",
                    asset_paths=asset_paths or None,
                    attachment_names=json.dumps(attachment_filenames, ensure_ascii=False)
                        if attachment_filenames else None,
                    citations_json=json.dumps(citations, ensure_ascii=False)
                        if citations else None,
                ))
                msg_ids_in_order.append(asst_msg_id)
                msg_count += 1

                # ToolEvent pra geracao de imagem
                if img_urls:
                    for url_idx, url in enumerate(img_urls):
                        info = manifest.get(url)
                        local_path = (
                            f"data/merged/Gemini/account-{account}/assets/{info['filename']}"
                            if info else None
                        )
                        self.events.append(ToolEvent(
                            event_id=f"{asst_msg_id}_img_{url_idx}",
                            conversation_id=conv_id,
                            message_id=asst_msg_id,
                            source=SOURCE,
                            account_id=account_id,
                            event_type="image_generation",
                            tool_name="gemini_image",
                            metadata_json=json.dumps({
                                "url": url,
                                "local_path": local_path,
                                "response_id": resp_id,
                            }, ensure_ascii=False),
                        ))

                # ToolEvent por citation (Search/Deep Research)
                for cite_idx, cite in enumerate(citations):
                    self.events.append(ToolEvent(
                        event_id=f"{asst_msg_id}_cite_{cite_idx}",
                        conversation_id=conv_id,
                        message_id=asst_msg_id,
                        source=SOURCE,
                        account_id=account_id,
                        event_type="search_result",
                        tool_name="gemini_search",
                        result=cite.get("snippet"),
                        metadata_json=json.dumps(cite, ensure_ascii=False),
                    ))

        # Conversation
        url = f"https://gemini.google.com/app/{uuid.lstrip('c_')}"
        settings = {}
        if first_locale:
            settings["locale"] = first_locale
        if models_seen:
            settings["models_used"] = sorted(models_seen)

        self.conversations.append(Conversation(
            conversation_id=conv_id,
            source=SOURCE,
            account_id=account_id,
            title=title or None,
            created_at=self._ts(created_secs) if created_secs else pd.NaT,
            updated_at=self._ts(last_secs) if last_secs else pd.NaT,
            message_count=msg_count,
            model=sorted(models_seen)[-1] if models_seen else None,
            account=account_label,
            mode="chat",
            url=url,
            is_pinned=uuid in pinned_set,
            is_preserved_missing=is_preserved,
            last_seen_in_server=self._ts(last_seen) if last_seen else pd.NaT,
            settings_json=json.dumps(settings, ensure_ascii=False) if settings else None,
        ))

        self._append_image_assets_and_links(
            account, account_id, conv_id, turns, manifest
        )
        self._append_report_assets_and_links(account, account_id, uuid, conv_id)

    @staticmethod
    def _asset_id(path: Path, fallback: str) -> str:
        if path.is_file():
            return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        return f"manifest:{hashlib.sha256(fallback.encode()).hexdigest()}"

    def _append_manifest_catalog(
        self,
        account: int,
        account_id: str | None,
        manifest: dict[str, dict],
    ) -> None:
        """Retain downloaded manifest objects even when no current turn references them."""
        existing = {(asset.account_id, asset.asset_id) for asset in self.assets}
        entries: dict[str, tuple[Path, dict]] = {}
        for info in sorted(manifest.values(), key=lambda item: str(item.get("manifest_key", ""))):
            filename = info.get("filename")
            if not filename:
                continue
            path = self.merged_root / f"account-{account}" / "assets" / filename
            asset_id = self._asset_id(path, str(info.get("manifest_key", filename)))
            entries.setdefault(asset_id, (path, info))
        for asset_id, (path, info) in sorted(entries.items()):
            if (account_id, asset_id) in existing:
                continue
            self.assets.append(Asset(
                asset_id=asset_id, source=SOURCE, account_id=account_id,
                asset_kind="other", asset_origin="unknown", file_name=path.name,
                mime_type=info.get("content_type"),
                size_bytes=path.stat().st_size if path.is_file() else info.get("size"),
                asset_path=(
                    f"merged/Gemini/account-{account}/assets/{path.name}"
                    if path.is_file() else None
                ),
                is_model_generated=None, is_preserved_missing=False,
                is_binary_available=path.is_file(), created_at=None,
                metadata_json=json.dumps({"representation": "hosted_image"}, sort_keys=True),
            ))
            existing.add((account_id, asset_id))

    def _append_image_assets_and_links(
        self,
        account: int,
        account_id: str | None,
        conv_id: str,
        turns: list,
        manifest: dict[str, dict],
    ) -> None:
        uses: dict[str, list[tuple[str, str, int]]] = {}
        entries: dict[str, tuple[Path, dict]] = {}
        for turn_idx, turn in enumerate(turns):
            for ordinal, url in enumerate(extract_image_urls_from_turn(turn)):
                info = manifest.get(url)
                if not info:
                    continue
                path = self.merged_root / f"account-{account}" / "assets" / info["filename"]
                asset_id = self._asset_id(path, info.get("manifest_key", url))
                entries.setdefault(asset_id, (path, info))
                if _contains_string(turn[2] if len(turn) > 2 else None, url):
                    uses.setdefault(asset_id, []).append(("user", f"{conv_id}_t{turn_idx}_user", ordinal))
                if _contains_string(turn[3] if len(turn) > 3 else None, url):
                    uses.setdefault(asset_id, []).append(("assistant", f"{conv_id}_t{turn_idx}_asst", ordinal))

        existing = {(asset.account_id, asset.asset_id) for asset in self.assets}
        existing_links = {link.asset_link_id for link in self.asset_links}
        for asset_id, (path, info) in sorted(entries.items()):
            observed_roles = {role for role, _, _ in uses.get(asset_id, [])}
            if observed_roles == {"assistant"}:
                origin, kind, generated = "assistant", "generated", True
            elif observed_roles == {"user"}:
                origin, kind, generated = "user", "attachment", False
            else:
                origin, kind, generated = "unknown", "other", None
            if (account_id, asset_id) not in existing:
                self.assets.append(Asset(
                    asset_id=asset_id,
                    source=SOURCE,
                    account_id=account_id,
                    asset_kind=kind,
                    asset_origin=origin,
                    file_name=path.name,
                    mime_type=info.get("content_type"),
                    size_bytes=path.stat().st_size if path.is_file() else info.get("size"),
                    asset_path=(
                        f"merged/Gemini/account-{account}/assets/{path.name}"
                        if path.is_file() else None
                    ),
                    is_model_generated=generated,
                    is_preserved_missing=False,
                    is_binary_available=path.is_file(),
                    created_at=None,
                    metadata_json=json.dumps({"representation": "hosted_image"}, sort_keys=True),
                ))
                existing.add((account_id, asset_id))
            else:
                prior = next(
                    asset for asset in self.assets
                    if asset.account_id == account_id and asset.asset_id == asset_id
                )
                if prior.asset_origin != origin:
                    prior.asset_origin = "unknown"
                    prior.asset_kind = "other"
                    prior.is_model_generated = None
            # A stale manifest may retain a URL after its binary delivery has
            # disappeared. Keep the unavailable Asset row, but do not invent
            # semantic appearances for a delivery the vault never captured.
            if not path.is_file():
                continue
            for role, message_id, ordinal in uses.get(asset_id, []):
                link_role = "input" if role == "user" else "output"
                link_id = make_asset_link_id(
                    SOURCE, account_id, asset_id, "message", message_id, link_role, ordinal
                )
                if link_id in existing_links:
                    continue
                self.asset_links.append(AssetLink(
                    asset_link_id=link_id, source=SOURCE, account_id=account_id,
                    asset_id=asset_id, object_type="message", object_id=message_id,
                    conversation_id=conv_id, message_id=message_id, project_id=None,
                    role=link_role, ordinal=ordinal, content_block_index=None,
                    metadata_json=None,
                ))
                existing_links.add(link_id)

    def _append_report_assets_and_links(
        self,
        account: int,
        account_id: str | None,
        native_conv_id: str,
        conv_id: str,
    ) -> None:
        report_root = (
            self.merged_root / f"account-{account}" / "assets" /
            "deep_research" / native_conv_id
        )
        if not report_root.exists():
            return
        existing = {(asset.account_id, asset.asset_id) for asset in self.assets}
        existing_links = {link.asset_link_id for link in self.asset_links}
        for meta_path in sorted(report_root.glob("*.md.meta.json")):
            report_path = Path(str(meta_path).removesuffix(".meta.json"))
            if not report_path.is_file():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
            location = _report_location(meta.get("source_path", ""))
            asset_id = self._asset_id(report_path, str(report_path.relative_to(report_root)))
            role_name = location[1] if location else None
            if role_name == "assistant":
                origin, kind, generated = "assistant", "output", True
            elif role_name == "user":
                origin, kind, generated = "user", "attachment", False
            else:
                origin, kind, generated = "unknown", "output", None
            if (account_id, asset_id) not in existing:
                self.assets.append(Asset(
                    asset_id=asset_id, source=SOURCE, account_id=account_id,
                    asset_kind=kind, asset_origin=origin, file_name=report_path.name,
                    mime_type="text/markdown", size_bytes=report_path.stat().st_size,
                    asset_path=(
                        f"merged/Gemini/account-{account}/assets/deep_research/"
                        f"{native_conv_id}/{report_path.name}"
                    ),
                    is_model_generated=generated, is_preserved_missing=False,
                    is_binary_available=True, created_at=None,
                    metadata_json=json.dumps({
                        "representation": "deep_research_report",
                        "title": meta.get("title"),
                    }, ensure_ascii=False, sort_keys=True),
                ))
                existing.add((account_id, asset_id))
            else:
                prior = next(
                    asset for asset in self.assets
                    if asset.account_id == account_id and asset.asset_id == asset_id
                )
                if prior.asset_origin != origin:
                    prior.asset_origin = "unknown"
                    prior.asset_kind = "other"
                    prior.is_model_generated = None
            if not location:
                continue
            turn_idx, role_name = location
            suffix = "user" if role_name == "user" else "asst"
            message_id = f"{conv_id}_t{turn_idx}_{suffix}"
            link_role = "input" if role_name == "user" else "output"
            try:
                ordinal = int(report_path.name.split("_", 2)[1])
            except (ValueError, IndexError):
                ordinal = None
            link_id = make_asset_link_id(
                SOURCE, account_id, asset_id, "message", message_id, link_role, ordinal
            )
            if link_id not in existing_links:
                self.asset_links.append(AssetLink(
                    asset_link_id=link_id, source=SOURCE, account_id=account_id,
                    asset_id=asset_id, object_type="message", object_id=message_id,
                    conversation_id=conv_id, message_id=message_id, project_id=None,
                    role=link_role, ordinal=ordinal, content_block_index=None,
                    metadata_json=None,
                ))
                existing_links.add(link_id)

    def save(self, output_dir: Path) -> None:
        """Save canonical Gemini parquet tables."""
        output_dir.mkdir(parents=True, exist_ok=True)

        conv_df = self.conversations_df()
        if not conv_df.empty:
            conv_df.to_parquet(output_dir / f"{SOURCE}_conversations.parquet")

        msg_df = self.messages_df()
        if not msg_df.empty:
            msg_df["word_count"] = msg_df["content"].fillna("").str.split().str.len()
            msg_df.to_parquet(output_dir / f"{SOURCE}_messages.parquet")

        evt_df = self.events_df()
        if not evt_df.empty:
            evt_df.to_parquet(output_dir / f"{SOURCE}_tool_events.parquet")

        assets_to_df(self.assets).to_parquet(output_dir / f"{SOURCE}_assets.parquet")
        asset_links_to_df(self.asset_links).to_parquet(
            output_dir / f"{SOURCE}_asset_links.parquet"
        )
        agent_memories_to_df(self.agent_memories).to_parquet(
            output_dir / f"{SOURCE}_agent_memories.parquet", index=False
        )
        agent_memory_versions_to_df(self.agent_memory_versions).to_parquet(
            output_dir / f"{SOURCE}_agent_memory_versions.parquet", index=False
        )
        agent_memory_temporal_evidence_to_df(self.agent_memory_temporal_evidence).to_parquet(
            output_dir / f"{SOURCE}_agent_memory_temporal_evidence.parquet", index=False
        )

        logger.info(
            "Parseado: %d convs, %d msgs, %d tool_events",
            len(self.conversations),
            len(self.messages),
            len(self.events),
        )
