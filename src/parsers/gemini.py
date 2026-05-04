"""Parser canonico do Gemini — schema v3.

Consome merged em data/merged/Gemini/account-{1,2}/conversations/<uuid>.json
+ assets/. Schema raw eh posicional (Google batchexecute, sem keys).

Cobertura (probe 2026-05-02 em 80 convs):
- Multi-conta: itera account-1 + account-2, namespace `{account}_{uuid}` em
  conversation_id pra evitar colisao
- Turn → user message + assistant message (par sequencial)
- Model name (turn[3][21], e.g. '2.5 Flash') → Message.model
- Thinking blocks (turn[3][0][0][37+]) → Message.thinking
- Image URLs (lh3.googleusercontent / gstatic, regex over JSON) → ToolEvent
  event_type='image_generation' + Message.asset_paths via manifest
- Deep Research markdown reports (extraidos offline pelo asset_downloader)
  → presente em assets/, surfaced via attachment_names
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

Output: data/processed/Gemini/{conversations,messages,tool_events}.parquet
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from src.parsers._gemini_helpers import (
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
from src.parsers.base import BaseParser
from src.schema.models import (
    Conversation,
    Message,
    ToolEvent,
)


logger = logging.getLogger(__name__)
SOURCE = "gemini"


def _load_assets_manifest(merged_root: Path, account: int) -> dict[str, str]:
    """Carrega assets_manifest.json e retorna dict {url -> local_path}.

    Manifest fica em data/raw/Gemini/account-{N}/assets_manifest.json
    (asset_downloader escreve no raw, nao no merged).
    """
    raw_dir = Path("data/raw/Gemini") / f"account-{account}"
    p = raw_dir / "assets_manifest.json"
    if not p.exists():
        return {}
    try:
        manifest = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

    url_map: dict[str, str] = {}
    for hash_id, info in manifest.items():
        if not isinstance(info, dict):
            continue
        url = info.get("url")
        rel = f"data/merged/Gemini/account-{account}/assets/{info.get('filename', hash_id)}"
        if url:
            url_map[url] = rel
    return url_map


class GeminiParser(BaseParser):
    source_name = SOURCE

    def __init__(
        self,
        account: Optional[str] = None,
        merged_root: Optional[Path] = None,
    ):
        super().__init__(account)
        self.merged_root = Path(merged_root) if merged_root else Path("data/merged/Gemini")

    def parse(self, input_path: Path | None = None) -> None:
        """Itera merged/Gemini/account-{1,2}/conversations/.

        Se input_path for fornecido, le so dele. Senao usa self.merged_root.
        """
        root = input_path or self.merged_root
        if not root.exists():
            logger.warning(f"merged root nao existe: {root}")
            return

        for acc in [1, 2]:
            acc_dir = root / f"account-{acc}"
            if not acc_dir.exists():
                continue
            self._parse_account(acc_dir, acc)

    def _parse_account(self, account_dir: Path, account: int) -> None:
        manifest = _load_assets_manifest(self.merged_root, account)
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
            self._parse_conv(obj, account, titles, created_at_secs, pinned_set, manifest)

    def _parse_conv(
        self,
        obj: dict,
        account: int,
        titles: dict[str, str],
        created_at_secs: dict[str, int],
        pinned_set: set[str],
        manifest: dict[str, str],
    ) -> None:
        uuid = obj.get("uuid")
        if not uuid:
            return

        raw = obj.get("raw")
        is_preserved = bool(obj.get("_preserved_missing"))
        last_seen = obj.get("_last_seen_in_server")

        # Namespace por account
        conv_id = f"account-{account}_{uuid}"

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
                    sequence=seq,
                    role="user",
                    content=user_text,
                    model=None,
                    created_at=ts,
                    account=str(account),
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
                local = manifest.get(url)
                if local:
                    asset_paths.append(local)

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
                    sequence=seq,
                    role="assistant",
                    content=assistant_text or "",
                    thinking=thinking,
                    model=model_name,
                    created_at=ts,
                    account=str(account),
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
                        local_path = manifest.get(url)
                        self.events.append(ToolEvent(
                            event_id=f"{asst_msg_id}_img_{url_idx}",
                            conversation_id=conv_id,
                            message_id=asst_msg_id,
                            source=SOURCE,
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
            title=title or None,
            created_at=self._ts(created_secs) if created_secs else pd.NaT,
            updated_at=self._ts(last_secs) if last_secs else pd.NaT,
            message_count=msg_count,
            model=sorted(models_seen)[-1] if models_seen else None,
            account=str(account),
            mode="chat",
            url=url,
            is_pinned=uuid in pinned_set,
            is_preserved_missing=is_preserved,
            last_seen_in_server=self._ts(last_seen) if last_seen else pd.NaT,
            settings_json=json.dumps(settings, ensure_ascii=False) if settings else None,
        ))

    def save(self, output_dir: Path) -> None:
        """Salva 3 parquets canonicos (overrides BaseParser pra usar tool_events naming)."""
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

        logger.info(
            "Parseado: %d convs, %d msgs, %d tool_events",
            len(self.conversations),
            len(self.messages),
            len(self.events),
        )
