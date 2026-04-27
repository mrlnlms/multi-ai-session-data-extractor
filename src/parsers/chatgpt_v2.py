"""Parser v2 do ChatGPT — consome raw novo da API interna (data/merged/ChatGPT/<date>/).

MVP minimal: mesmo shape do parser antigo (Conversation + Message), mas:
- Caminha current_node -> root (linear, ignora branches off-path)
- Filtra system invisiveis (is_visually_hidden_from_conversation=true)
- Pega audio_transcription.text de parts dict (voice mode de graca)
- Skipa outros parts dict (images, multimodal asset pointers, etc)
- Skipa role tool/system
- Model por conv = ultimo model_slug do assistant no path
- Project = _project_name (enrichment do orchestrator)

Porting rico (branches, tools estruturadas como ToolEvents, tether_quote,
thoughts/reasoning, DALL-E inline) no parser #29.

Roda em paralelo ao parser antigo (source_name='chatgpt_v2') — nao substitui
nada por enquanto.
"""

import json
from pathlib import Path

from src.parsers.base import BaseParser
from src.schema.models import Conversation, Message


class ChatGPTV2Parser(BaseParser):
    source_name = "chatgpt_v2"

    def parse(self, input_path: Path) -> None:
        """Input: data/merged/ChatGPT/<date>/chatgpt_merged.json (ou chatgpt_raw.json)."""
        with open(input_path, encoding="utf-8") as f:
            raw = json.load(f)

        convs = raw.get("conversations") or {}
        if not isinstance(convs, dict):
            raise ValueError(
                f"Esperado dict em 'conversations', recebido {type(convs).__name__}. "
                "Parser v2 consome raw novo (API interna) — nao o antigo GPT2Claude."
            )

        for conv_id, conv_data in convs.items():
            messages, last_model = self._extract_messages(conv_id, conv_data)
            if not messages:
                continue

            self.conversations.append(Conversation(
                conversation_id=conv_id,
                source=self.source_name,
                title=conv_data.get("title") or None,
                created_at=self._ts(conv_data.get("create_time")),
                updated_at=self._ts(conv_data.get("update_time")),
                message_count=len(messages),
                model=last_model,
                account=self.account,
                mode="chat",
                project=conv_data.get("_project_name") or None,
                url=f"https://chatgpt.com/c/{conv_id}",
            ))
            self.messages.extend(messages)

    def _extract_messages(self, conv_id: str, conv_data: dict) -> tuple[list[Message], str | None]:
        mapping = conv_data.get("mapping") or {}
        current = conv_data.get("current_node")

        path_ids = []
        cur = current
        seen = set()
        while cur and cur in mapping and cur not in seen:
            seen.add(cur)
            path_ids.append(cur)
            cur = mapping[cur].get("parent")
        path_ids.reverse()

        messages: list[Message] = []
        last_assistant_model: str | None = None
        seq = 0

        for node_id in path_ids:
            node = mapping.get(node_id) or {}
            msg = node.get("message")
            if not msg:
                continue

            meta = msg.get("metadata") or {}
            if meta.get("is_visually_hidden_from_conversation"):
                continue

            author = msg.get("author") or {}
            role = author.get("role")
            if role not in ("user", "assistant"):
                continue

            content = msg.get("content") or {}
            text = self._extract_text(content)
            if not text:
                continue

            ctype = content.get("content_type") or "text"
            parts = content.get("parts") or []
            has_voice = any(
                isinstance(p, dict) and p.get("content_type") == "audio_transcription"
                for p in parts
            )
            has_dalle = any(
                isinstance(p, dict)
                and p.get("content_type") == "image_asset_pointer"
                and (p.get("metadata") or {}).get("dalle")
                for p in parts
            )
            markers = [ctype]
            if has_voice:
                markers.append("audio_transcription")
            if has_dalle:
                markers.append("dalle")
            content_types = ",".join(markers)

            model_slug = meta.get("model_slug")
            if role == "assistant" and model_slug:
                last_assistant_model = model_slug

            seq += 1
            messages.append(Message(
                message_id=msg.get("id") or f"{conv_id}_{seq}",
                conversation_id=conv_id,
                source=self.source_name,
                sequence=seq,
                role=role,
                content=text,
                model=model_slug if role == "assistant" else None,
                created_at=self._ts(msg.get("create_time")),
                account=self.account,
                content_types=content_types,
            ))

        return messages, last_assistant_model

    @staticmethod
    def _extract_text(content: dict) -> str:
        """Extrai texto de content. Shapes suportados:

        - content_type='text' com parts (str ou dict audio_transcription)
        - content_type='code' / 'tether_quote' com text direto
        - content_type='multimodal_text' com parts mistas (str + dicts)
        - content_type='thoughts' com lista de {summary, content} (reasoning do o1/o3/gpt-5)
        - content_type='reasoning_recap' com content string ("Thought for N seconds")
        - qualquer outro: tenta parts, senao retorna ''.
        """
        ctype = content.get("content_type", "")
        if ctype in ("code", "tether_quote") and "text" in content:
            return content.get("text") or ""
        if ctype == "reasoning_recap":
            return content.get("content") or ""
        if ctype == "thoughts":
            thoughts = content.get("thoughts") or []
            out: list[str] = []
            for t in thoughts:
                if not isinstance(t, dict):
                    continue
                summary = t.get("summary") or ""
                body = t.get("content") or ""
                if summary and body:
                    out.append(f"**{summary}**\n\n{body}")
                elif body:
                    out.append(body)
                elif summary:
                    out.append(summary)
            return "\n\n".join(out)

        parts = content.get("parts") or []
        out = []
        for p in parts:
            if isinstance(p, str):
                if p:
                    out.append(p)
            elif isinstance(p, dict):
                if p.get("content_type") == "audio_transcription":
                    t = p.get("text")
                    if t:
                        out.append(t)
        return "\n\n".join(out)
