"""Helpers compartilhados pelo parser v3 do ChatGPT.

Funcoes puras (sem estado), faceis de testar isoladamente.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def is_project_gizmo_id(gizmo_id: Optional[str]) -> bool:
    """True se gizmo_id segue o prefixo de Project (g-p-*)."""
    return bool(gizmo_id) and gizmo_id.startswith("g-p-")


def is_custom_gpt_gizmo_id(gizmo_id: Optional[str]) -> bool:
    """True se gizmo_id segue o prefixo de Custom GPT real (g-* mas nao g-p-*)."""
    if not gizmo_id:
        return False
    return gizmo_id.startswith("g-") and not gizmo_id.startswith("g-p-")


def classify_event_type(tool_name: Optional[str]) -> str:
    """Mapeia tool_name pra categoria de event_type. Heuristica baseada
    nos achados empiricos (parser-v3-empirical-findings.md secao 8)."""
    if not tool_name:
        return "other"
    name = tool_name
    if "browser" in name or name in ("web", "web.run"):
        return "search"
    if name in ("python", "execution"):
        return "code"
    if name.startswith("canmore."):
        return "canvas"
    if name.startswith("research_kickoff_tool"):
        return "deep_research"
    if name.startswith("dalle"):
        return "image_generation"
    if name == "bio":
        return "memory"
    if name.startswith("file_search") or name == "myfiles_browser":
        return "file_search"
    if name.startswith("computer.") or name.startswith("container."):
        return "computer_use"
    if name.startswith("voice_mode."):
        return "voice"
    return "other"


def parse_asset_pointer(asset_pointer: Optional[str]) -> Optional[str]:
    """Extrai o file_id de um asset_pointer.

    Shapes observados:
        sediment://file_00000000e2fc61f9a1e7e724bc1b7373   (DALL-E)
        file-service://file-7SJH2UY6zbkn8U8ACPTiq3EX        (uploads)

    Retorna o segmento depois do `://` (ex: 'file_00000...' ou 'file-7SJH...').
    """
    if not asset_pointer or "://" not in asset_pointer:
        return None
    return asset_pointer.split("://", 1)[1]


def resolve_asset_path(
    asset_pointer: str,
    conv_id: str,
    assets_root: Path,
) -> Optional[str]:
    """Resolve um asset_pointer pra path em disco. Retorna string relativa
    ao project root ou None se nao encontrado.

    Estrutura esperada:
        <assets_root>/images/<conv_id>/<file_id>__<original>.<ext>
        <assets_root>/canvases/<conv_id>/...
        <assets_root>/deep_research/<conv_id>/...
    """
    file_id = parse_asset_pointer(asset_pointer)
    if not file_id:
        return None
    # Busca primeiro na pasta especifica da conv (por tipo)
    for subdir in ("images", "canvases", "deep_research"):
        conv_dir = assets_root / subdir / conv_id
        if not conv_dir.is_dir():
            continue
        matches = list(conv_dir.glob(f"{file_id}__*"))
        if matches:
            return str(matches[0])
        # Fallback: arquivo com nome exatamente igual ao file_id (sem __ suffix)
        exact = conv_dir / file_id
        if exact.is_file():
            return str(exact)
    return None


def detect_canvas_signal(msg: dict) -> bool:
    """True se a msg tem qualquer marker de Canvas (canmore.*)."""
    recipient = msg.get("recipient") or ""
    if recipient.startswith("canmore."):
        return True
    author = msg.get("author") or {}
    name = author.get("name") or ""
    if name.startswith("canmore."):
        return True
    meta = msg.get("metadata") or {}
    if (meta.get("model_slug") or "") == "gpt-4o-canmore":
        return True
    return False


def detect_deep_research_signal(msg: dict) -> bool:
    """True se a msg tem marker de Deep Research."""
    meta = msg.get("metadata") or {}
    slug = (meta.get("model_slug") or "").lower()
    if "research" in slug:
        return True
    if meta.get("deep_research_version") or meta.get("research_done"):
        return True
    recipient = msg.get("recipient") or ""
    if recipient.startswith("research_kickoff_tool"):
        return True
    author = msg.get("author") or {}
    name = author.get("name") or ""
    if name.startswith("research_kickoff_tool"):
        return True
    return False


def extract_text(content: dict) -> str:
    """Extrai texto de content. Cobre 13 content_types observados nos achados.

    Shapes suportados:
    - text / multimodal_text / user_editable_context: parts mistas (str + dict)
    - code / tether_quote / tether_browsing_display: campo `text`
    - reasoning_recap: campo `content`
    - thoughts: lista de {summary, content}
    - execution_output / computer_output: campo `text` ou parts
    - model_editable_context: campo `text` (system bridge)
    - system_error / super_widget: parts ou texto raw
    - audio_transcription (em parts): handled em parts loop
    """
    ctype = content.get("content_type", "")

    if ctype in ("code", "tether_quote", "tether_browsing_display"):
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

    if ctype in ("execution_output", "computer_output", "system_error", "super_widget"):
        if "text" in content:
            return content.get("text") or ""

    if ctype == "model_editable_context":
        # System bridge: tem 'model_set_context' e 'repository' como strings
        return (content.get("model_set_context") or "") + ("\n" + content.get("repository") if content.get("repository") else "")

    # Default: parts (mistas str + dict)
    parts = content.get("parts") or []
    out: list[str] = []
    for p in parts:
        if isinstance(p, str):
            if p:
                out.append(p)
        elif isinstance(p, dict):
            ptype = p.get("content_type")
            if ptype == "audio_transcription":
                t = p.get("text")
                if t:
                    out.append(t)
            elif ptype == "image_asset_pointer":
                # Placeholder — imagem inline
                meta = p.get("metadata") or {}
                if meta.get("dalle"):
                    prompt = (meta["dalle"].get("prompt") or "").strip()
                    if prompt:
                        out.append(f"[imagem gerada: {prompt}]")
                    else:
                        out.append("[imagem gerada]")
                else:
                    out.append("[imagem]")
    return "\n\n".join(out)


def extract_image_asset_pointers(content: dict) -> list[tuple[str, bool]]:
    """Retorna lista (asset_pointer, is_dalle) de image_asset_pointers em parts.

    is_dalle=True indica geracao via DALL-E (metadata.dalle truthy);
    is_dalle=False indica upload do user ou outro tipo.

    Empiricamente (achados): DALL-E aparece em role=tool, uploads em role=user.
    """
    pointers: list[tuple[str, bool]] = []
    for p in (content.get("parts") or []):
        if not isinstance(p, dict):
            continue
        if p.get("content_type") != "image_asset_pointer":
            continue
        ap = p.get("asset_pointer")
        if not ap:
            continue
        meta = p.get("metadata") or {}
        is_dalle = bool(meta.get("dalle"))
        pointers.append((ap, is_dalle))
    return pointers


def extract_finish_reason(metadata: dict) -> Optional[str]:
    """Extrai finish_reason de metadata.finish_details.type."""
    fd = metadata.get("finish_details") or {}
    return fd.get("type") if isinstance(fd, dict) else None


def detect_hidden(msg: dict) -> tuple[bool, Optional[str]]:
    """Determina se msg eh hidden e a razao.

    Razoes: 'visually_hidden', 'weight_zero', 'internal_recipient'.
    Retorna (is_hidden, hidden_reason).
    """
    meta = msg.get("metadata") or {}
    if meta.get("is_visually_hidden_from_conversation"):
        return True, "visually_hidden"
    weight = msg.get("weight")
    if isinstance(weight, (int, float)) and weight == 0:
        return True, "weight_zero"
    recipient = msg.get("recipient") or ""
    # 'all' eh o normal; recipients especificos sao chamadas internas (assistant -> tool)
    if recipient and recipient != "all":
        return True, "internal_recipient"
    return False, None


def detect_voice(content: dict) -> tuple[bool, Optional[str]]:
    """Detecta se a msg tem audio_transcription em parts. Retorna (is_voice, direction)."""
    for p in (content.get("parts") or []):
        if isinstance(p, dict) and p.get("content_type") == "audio_transcription":
            return True, p.get("direction")
    return False, None
