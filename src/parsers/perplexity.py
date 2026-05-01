"""Parser canonico Perplexity v3 — consome data/merged/Perplexity/ (pasta unica)
e gera 4 parquets em data/processed/Perplexity/.

Cobertura:
- Threads (CONCISE, COPILOT/Deep Research, ASI/Computer) -> Conversations + Messages
- Pages (UI Pages = API article) dentro de spaces -> Conversations
- Artifacts (assets/_index.json) -> ToolEvents tipo 'asset_generation'
- Threads em spaces -> Conversation.project = space_uuid
- Search sources -> ToolEvents tipo 'search_result'
- Media items (refs externas) -> ToolEvents tipo 'media_reference'
- Attachments URLs -> Message.asset_paths (path no manifest se baixado)
- Featured_images -> Message.asset_paths
- Preservation: is_preserved_missing + last_seen_in_server
- Branches: 1 por thread (Perplexity e linear)

Output: data/processed/Perplexity/{conversations,messages,tool_events,branches}.parquet

Backup do parser v2 (formato extracted_messages legado):
_backup-temp/parser-perplexity-v2-promocao-2026-05-01.py.bak
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from src.parsers.base import BaseParser
from src.schema.models import (
    Branch,
    Conversation,
    Message,
    ToolEvent,
    branches_to_df,
    conversations_to_df,
    messages_to_df,
    tool_events_to_df,
)

logger = logging.getLogger(__name__)


# Mapping de mode da API Perplexity pra VALID_MODES do schema canonico
_MODE_MAP = {
    "CONCISE": "concise",
    "COPILOT": "copilot",     # Deep Research (legacy name)
    "ASI": "research",         # Computer mode (Pro)
    "ARTICLE": "research",     # Pages — geradas via processo similar
    # lowercase tb (alguns threads vem assim)
    "concise": "concise",
    "copilot": "copilot",
    "asi": "research",
    "article": "research",
}


def _to_ts(s: Optional[str]) -> pd.Timestamp:
    if not s:
        return pd.Timestamp.now(tz="UTC")
    try:
        ts = pd.Timestamp(s)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts
    except Exception:
        return pd.Timestamp.now(tz="UTC")


def _block_text(block: dict) -> str:
    """Extrai texto de 1 block. Blocks tem varios sub-tipos."""
    if not isinstance(block, dict):
        return ""
    for key in ("answer", "markdown", "text", "content"):
        v = block.get(key)
        if isinstance(v, str):
            return v
    return ""


def _entry_answer_text(entry: dict) -> str:
    """Concatena texto de todos os blocks da entry."""
    blocks = entry.get("blocks") or []
    parts = []
    for b in blocks:
        t = _block_text(b)
        if t:
            parts.append(t)
    if parts:
        return "\n\n".join(parts)
    fa = entry.get("first_answer")
    if isinstance(fa, str) and fa:
        try:
            obj = json.loads(fa)
            if isinstance(obj, dict) and obj.get("answer"):
                return str(obj["answer"])
        except Exception:
            pass
    return ""


def _attachment_paths(entry: dict, manifest: dict) -> list[str]:
    paths = []
    for url in entry.get("attachments") or []:
        if not isinstance(url, str):
            continue
        h = hashlib.sha1(url.encode()).hexdigest()[:16]
        info = manifest.get(h)
        if info and info.get("relpath") and info.get("status") != "failed_upstream_deleted":
            paths.append(f"thread_attachments/{info['relpath']}")
        else:
            paths.append(url[:200])
    return paths


def _featured_image_paths(entry: dict, manifest: dict) -> list[str]:
    paths = []
    for fi in entry.get("featured_images") or []:
        u = fi if isinstance(fi, str) else (fi.get("url") if isinstance(fi, dict) else None)
        if not u:
            continue
        h = hashlib.sha1(u.encode()).hexdigest()[:16]
        info = manifest.get(h)
        if info and info.get("relpath") and info.get("status") != "failed_upstream_deleted":
            paths.append(f"thread_attachments/{info['relpath']}")
        else:
            paths.append(u[:200])
    return paths


class PerplexityParser(BaseParser):
    source_name = "perplexity"

    def __init__(self, account: Optional[str] = None, merged_root: Optional[Path] = None):
        super().__init__(account)
        self.merged_root = Path(merged_root) if merged_root else Path("data/merged/Perplexity")

    def reset(self):
        super().reset()
        self.branches: list[Branch] = []
        self.tool_events: list[ToolEvent] = []

    def parse(self, *_, **__) -> None:
        """Parse threads + pages + assets do merged. merged_root setado no init."""
        self.reset()

        # Carrega manifest de attachments
        att_manifest: dict = {}
        for candidate in [
            Path("data/raw/Perplexity/thread_attachments_manifest.json"),
            self.merged_root / "thread_attachments_manifest.json",
        ]:
            if candidate.exists():
                try:
                    att_manifest = json.loads(candidate.read_text(encoding="utf-8"))
                except Exception:
                    pass
                break

        # threads_discovery.json — preservation flags
        disc_data: dict = {}
        disc_path = self.merged_root / "threads_discovery.json"
        if disc_path.exists():
            try:
                arr = json.loads(disc_path.read_text(encoding="utf-8"))
                disc_data = {e["uuid"]: e for e in arr if isinstance(e, dict) and e.get("uuid")}
            except Exception:
                pass

        # spaces -> mapping uuid -> space_uuid
        thread_to_space: dict[str, str] = {}
        spaces_dir = self.merged_root / "spaces"
        if spaces_dir.exists():
            for sd in spaces_dir.iterdir():
                if not sd.is_dir():
                    continue
                ti = sd / "threads_index.json"
                if not ti.exists():
                    continue
                try:
                    arr = json.loads(ti.read_text(encoding="utf-8"))
                    for t in arr:
                        if t.get("uuid"):
                            thread_to_space[t["uuid"]] = sd.name
                except Exception:
                    continue

        # 1) THREADS
        threads_dir = self.merged_root / "threads"
        if threads_dir.exists():
            for jp in sorted(threads_dir.glob("*.json")):
                try:
                    self._parse_thread_file(jp, disc_data, thread_to_space, att_manifest)
                except Exception as e:
                    logger.warning(f"thread {jp.name}: {e}")

        # 2) PAGES (em spaces/<uuid>/pages/<slug>.json)
        if spaces_dir.exists():
            for sd in spaces_dir.iterdir():
                pages_dir = sd / "pages"
                if not pages_dir.is_dir():
                    continue
                for pp in sorted(pages_dir.glob("*.json")):
                    if pp.name == "_index.json":
                        continue
                    try:
                        self._parse_page_file(pp, sd.name)
                    except Exception as e:
                        logger.warning(f"page {pp.name}: {e}")

        # 3) ASSETS (artifacts) -> ToolEvents
        assets_idx_path = self.merged_root / "assets" / "_index.json"
        if assets_idx_path.exists():
            try:
                assets = json.loads(assets_idx_path.read_text(encoding="utf-8"))
                for a in assets:
                    self._parse_asset(a)
            except Exception as e:
                logger.warning(f"assets: {e}")

    def _parse_thread_file(
        self,
        path: Path,
        disc_data: dict,
        thread_to_space: dict[str, str],
        att_manifest: dict,
    ) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        uid = path.stem
        entries = data.get("entries") or []
        if not entries:
            return

        first_entry = entries[0]
        thread_title = first_entry.get("thread_title") or first_entry.get("query_str") or ""
        mode_raw = first_entry.get("mode")
        mode_canonical = _MODE_MAP.get(mode_raw, "chat")
        display_model = first_entry.get("display_model")

        disc = disc_data.get(uid, {})
        last_query = disc.get("last_query_datetime") or first_entry.get("entry_updated_datetime")
        first_query = first_entry.get("entry_created_datetime")
        last_seen = data.get("_last_seen_in_server")
        is_preserved = bool(disc.get("_preserved_missing"))

        space_uuid = thread_to_space.get(uid)

        seq = 0
        msg_count = 0
        first_msg_id = None
        last_msg_id = None
        for entry in entries:
            entry_uuid = entry.get("uuid") or entry.get("backend_uuid") or f"{uid}_{seq}"
            entry_ts = _to_ts(entry.get("entry_created_datetime"))
            entry_attachments = _attachment_paths(entry, att_manifest)
            entry_featured = _featured_image_paths(entry, att_manifest)

            seq += 1
            user_msg_id = f"{entry_uuid}_user"
            self.messages.append(Message(
                message_id=user_msg_id,
                conversation_id=uid,
                source=self.source_name,
                sequence=seq,
                role="user",
                content=entry.get("query_str") or "",
                model=None,
                created_at=entry_ts,
                account=self.account,
                content_types="text",
                asset_paths=entry_attachments or None,
            ))
            msg_count += 1
            if not first_msg_id:
                first_msg_id = user_msg_id
            last_msg_id = user_msg_id

            seq += 1
            asst_msg_id = f"{entry_uuid}_asst"
            self.messages.append(Message(
                message_id=asst_msg_id,
                conversation_id=uid,
                source=self.source_name,
                sequence=seq,
                role="assistant",
                content=_entry_answer_text(entry),
                model=entry.get("display_model") or display_model,
                created_at=entry_ts,
                account=self.account,
                content_types="text",
                asset_paths=entry_featured or None,
            ))
            msg_count += 1
            last_msg_id = asst_msg_id

            # Search results em blocks[*].web_result_block.web_results
            src_idx = 0
            for b in entry.get("blocks") or []:
                if not isinstance(b, dict):
                    continue
                wrb = b.get("web_result_block")
                if not isinstance(wrb, dict):
                    continue
                for src in (wrb.get("web_results") or [])[:50]:
                    if not isinstance(src, dict):
                        continue
                    url = src.get("url") or src.get("link") or ""
                    title = (src.get("name") or src.get("title") or "")[:200]
                    snippet = (src.get("snippet") or "")[:300]
                    self.tool_events.append(ToolEvent(
                        event_id=f"{entry_uuid}_src_{src_idx}",
                        conversation_id=uid,
                        message_id=asst_msg_id,
                        source=self.source_name,
                        event_type="search_result",
                        tool_name="web_search",
                        metadata_json=json.dumps({
                            "url": url, "title": title, "snippet": snippet,
                            "timestamp": src.get("timestamp"),
                        }, ensure_ascii=False),
                    ))
                    src_idx += 1

            for i, m in enumerate((entry.get("media_items") or [])[:20]):
                if not isinstance(m, dict):
                    continue
                self.tool_events.append(ToolEvent(
                    event_id=f"{entry_uuid}_media_{i}",
                    conversation_id=uid,
                    message_id=asst_msg_id,
                    source=self.source_name,
                    event_type="media_reference",
                    tool_name=m.get("source") or "external_media",
                    metadata_json=json.dumps({
                        "url": m.get("url"),
                        "image": m.get("image"),
                        "name": m.get("name"),
                        "medium": m.get("medium"),
                    }, ensure_ascii=False),
                ))

        self.conversations.append(Conversation(
            conversation_id=uid,
            source=self.source_name,
            title=thread_title[:500] if thread_title else None,
            created_at=_to_ts(first_query),
            updated_at=_to_ts(last_query),
            message_count=msg_count,
            model=display_model,
            account=self.account,
            mode=mode_canonical,
            project=space_uuid,
            url=f"https://www.perplexity.ai/search/{uid}",
            project_id=space_uuid,
            is_preserved_missing=is_preserved,
            last_seen_in_server=_to_ts(last_seen) if last_seen else None,
        ))

        if first_msg_id and last_msg_id:
            self.branches.append(Branch(
                branch_id=f"{uid}_main",
                conversation_id=uid,
                source=self.source_name,
                root_message_id=first_msg_id,
                leaf_message_id=last_msg_id,
                is_active=True,
                created_at=_to_ts(first_query),
            ))

    def _parse_page_file(self, path: Path, space_uuid: str) -> None:
        """Pages (article) viram Conversations especiais."""
        data = json.loads(path.read_text(encoding="utf-8"))
        slug = path.stem
        entries = data.get("entries") or []
        if not entries:
            return

        first_entry = entries[0]
        page_title = first_entry.get("thread_title")
        info_str = first_entry.get("article_info")
        article_info: dict = {}
        if isinstance(info_str, str):
            try:
                article_info = json.loads(info_str)
            except Exception:
                pass
        elif isinstance(info_str, dict):
            article_info = info_str
        title = article_info.get("title") or page_title or slug
        author = first_entry.get("author_username")

        page_id = f"page:{slug}"
        first_ts = _to_ts(first_entry.get("entry_created_datetime"))
        last_ts = _to_ts(entries[-1].get("entry_updated_datetime") or first_entry.get("entry_updated_datetime"))

        seq = 0
        msg_count = 0
        first_msg_id = None
        last_msg_id = None
        for entry in entries:
            entry_uuid = entry.get("uuid") or entry.get("backend_uuid") or f"{slug}_{seq}"
            entry_ts = _to_ts(entry.get("entry_created_datetime"))

            seq += 1
            uid_msg = f"{entry_uuid}_query"
            self.messages.append(Message(
                message_id=uid_msg,
                conversation_id=page_id,
                source=self.source_name,
                sequence=seq,
                role="user",
                content=entry.get("query_str") or "",
                model=None,
                created_at=entry_ts,
                account=self.account,
                content_types="text",
            ))
            if not first_msg_id:
                first_msg_id = uid_msg
            last_msg_id = uid_msg
            msg_count += 1

            seq += 1
            asst_id = f"{entry_uuid}_answer"
            self.messages.append(Message(
                message_id=asst_id,
                conversation_id=page_id,
                source=self.source_name,
                sequence=seq,
                role="assistant",
                content=_entry_answer_text(entry),
                model=entry.get("display_model"),
                created_at=entry_ts,
                account=self.account,
                content_types="text",
            ))
            last_msg_id = asst_id
            msg_count += 1

        self.conversations.append(Conversation(
            conversation_id=page_id,
            source=self.source_name,
            title=title[:500] if title else None,
            created_at=first_ts,
            updated_at=last_ts,
            message_count=msg_count,
            model=first_entry.get("display_model"),
            account=self.account,
            mode="research",
            project=space_uuid,
            url=f"https://www.perplexity.ai/page/{slug}",
            project_id=space_uuid,
            interaction_type="ai_ai" if author and author != "marlonlemes" else "human_ai",
        ))

        if first_msg_id and last_msg_id:
            self.branches.append(Branch(
                branch_id=f"{page_id}_main",
                conversation_id=page_id,
                source=self.source_name,
                root_message_id=first_msg_id,
                leaf_message_id=last_msg_id,
                is_active=True,
                created_at=first_ts,
            ))

    def _parse_asset(self, asset: dict) -> None:
        slug = asset.get("asset_slug")
        if not slug:
            return
        entry_uuid = asset.get("entry_uuid")
        conv_id = entry_uuid or slug
        msg_id = f"{entry_uuid}_asst" if entry_uuid else f"asset:{slug}"

        self.tool_events.append(ToolEvent(
            event_id=f"asset:{slug}",
            conversation_id=conv_id,
            message_id=msg_id,
            source=self.source_name,
            event_type="asset_generation",
            tool_name=asset.get("asset_type"),
            file_path=f"assets/files/{slug}",
            metadata_json=json.dumps({
                "caption": asset.get("caption"),
                "preview_image_url": asset.get("preview_image_url"),
                "is_pinned": asset.get("is_pinned", False),
                "media_type": asset.get("media_type"),
                "_preserved_missing": asset.get("_preserved_missing", False),
            }, ensure_ascii=False),
        ))

    def write(self, output_dir: Optional[Path] = None) -> dict:
        out = Path(output_dir) if output_dir else Path("data/processed/Perplexity")
        out.mkdir(parents=True, exist_ok=True)

        conversations_to_df(self.conversations).to_parquet(out / "conversations.parquet", index=False)
        messages_to_df(self.messages).to_parquet(out / "messages.parquet", index=False)
        tool_events_to_df(self.tool_events).to_parquet(out / "tool_events.parquet", index=False)
        branches_to_df(self.branches).to_parquet(out / "branches.parquet", index=False)

        return {
            "conversations": len(self.conversations),
            "messages": len(self.messages),
            "tool_events": len(self.tool_events),
            "branches": len(self.branches),
            "output_dir": str(out),
        }
