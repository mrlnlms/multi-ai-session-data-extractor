"""Helpers puros do parser Gemini.

Schema raw eh **posicional** (Google batchexecute / protobuf-like) — sem
keys. Caminhos descobertos empiricamente em 2026-05-02 (probe via
scripts/gemini-probe-schema.py em 80 convs):

    raw                 — list[4] = [turns_wrapper, ?, None, ?]
    raw[0]              — list de turns
    raw[0][i]           — turn = [ids, response_ids, user_msg, response_data, ts]
    raw[0][i][0]        — [conv_id, response_id]
    raw[0][i][1]        — [conv_id, resp_id_a, resp_id_b] (alternativas/drafts)
    raw[0][i][2]        — user message: [[user_text], turn_seq, null, ...]
    raw[0][i][3]        — response data (25 fields)
    raw[0][i][3][0][0]  — main response: [resp_id, [text_chunks], null, ..., thinking_data, ...]
    raw[0][i][3][21]    — model name (e.g. '2.5 Flash')
    raw[0][i][4]        — [created_at_secs, microseconds]

Helpers fazem navegacao defensiva — se path nao existe ou tem tipo errado,
retorna default em vez de KeyError/IndexError.
"""

import re
from typing import Any


CITATION_FAVICON_HOST = "gstatic.com/faviconV2"
_EXTERNAL_EXCLUDE = (
    "googleusercontent", "gstatic.com", "fonts.gstatic",
    "ssl.gstatic", "lh.google.com", "google.com/url",
)


def _is_external_url(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    return not any(d in url for d in _EXTERNAL_EXCLUDE)


def extract_turn_citations(turn: Any) -> list[dict]:
    """Extrai citations de Search/Deep Research num turn assistant.

    Schema (probe 2026-05-04): Search/Deep Research embute citations como
    listas com forma fixa no positional schema:
        [favicon_url, source_url, title, snippet, ...]
    onde favicon_url contem 'gstatic.com/faviconV2', source_url eh URL
    externo, title e snippet sao strings.

    Walk recursivo procurando listas com essa forma. Dedup por url.
    Retorna: [{"url", "title", "snippet", "favicon"}, ...]
    """
    seen_urls: set[str] = set()
    out: list[dict] = []

    def walk(obj: Any, depth: int = 0) -> None:
        if depth > 15:
            return
        if isinstance(obj, list):
            if (len(obj) >= 4
                and isinstance(obj[0], str) and CITATION_FAVICON_HOST in obj[0]
                and isinstance(obj[1], str) and _is_external_url(obj[1])
                and isinstance(obj[2], str)
                and isinstance(obj[3], str)):
                url = obj[1]
                if url not in seen_urls:
                    seen_urls.add(url)
                    out.append({
                        "url": url,
                        "title": obj[2],
                        "snippet": obj[3],
                        "favicon": obj[0],
                    })
                return
            for item in obj:
                walk(item, depth + 1)
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v, depth + 1)

    walk(turn)
    return out


def _path(obj: Any, *idx: int, default: Any = None) -> Any:
    """Navega path posicional defensivo. _path(arr, 0, 1, 2) ~ arr[0][1][2]."""
    cur = obj
    for i in idx:
        if cur is None:
            return default
        if isinstance(cur, (list, tuple)):
            if not (-len(cur) <= i < len(cur)):
                return default
            cur = cur[i]
        else:
            return default
    return cur


# ============================================================
# Per-turn extractors
# ============================================================

def turn_response_id(turn: list) -> str | None:
    """raw[0][i][0][1] = response_id (rc_*)."""
    return _path(turn, 0, 1)


def turn_user_text(turn: list) -> str | None:
    """raw[0][i][2][0][0] = primary user text chunk."""
    chunks = _path(turn, 2, 0)
    if not isinstance(chunks, list) or not chunks:
        return None
    text = chunks[0]
    return text if isinstance(text, str) else None


def turn_assistant_text(turn: list) -> str | None:
    """raw[0][i][3][0][0][1] = list of response text chunks (joined)."""
    chunks = _path(turn, 3, 0, 0, 1)
    if not isinstance(chunks, list):
        return None
    parts = [c for c in chunks if isinstance(c, str)]
    return "\n".join(parts) if parts else None


def turn_assistant_response_id(turn: list) -> str | None:
    """raw[0][i][3][0][0][0] = response chunk id (rc_*)."""
    return _path(turn, 3, 0, 0, 0)


def turn_model_name(turn: list) -> str | None:
    """raw[0][i][3][21] = model display name (e.g. '2.5 Flash')."""
    name = _path(turn, 3, 21)
    return name if isinstance(name, str) else None


def turn_locale(turn: list) -> str | None:
    """raw[0][i][3][8] = locale code (e.g. 'BR')."""
    loc = _path(turn, 3, 8)
    return loc if isinstance(loc, str) else None


def turn_timestamp_secs(turn: list) -> int | None:
    """raw[0][i][4][0] = created_at_secs."""
    ts = _path(turn, 4, 0)
    return ts if isinstance(ts, int) else None


def turn_thinking_blocks(turn: list) -> list[str]:
    """Extrai thinking text blocks de raw[0][i][3][0][0][37].

    Schema observado: pos 37 contem array de thinking sequences. Estrutura
    nested e variavel — strategy: walk the subtree e coletar strings >= 200
    chars que NAO aparecem no main response_text (filtragem por exclusao).
    """
    thinking_root = _path(turn, 3, 0, 0, 37)
    if not isinstance(thinking_root, list):
        return []
    main_response = turn_assistant_text(turn) or ""

    blocks: list[str] = []
    seen: set[str] = set()

    def walk(node):
        if isinstance(node, str):
            if len(node) >= 200 and node not in main_response and node not in seen:
                # Heuristica: thinking blocks geralmente comecam com markdown
                # **Title** ou frases tipo "I'm now..." / "Initiating..." /
                # "Refining..." / "**Reflexao..."
                seen.add(node)
                blocks.append(node)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(thinking_root)
    return blocks


# ============================================================
# Image URL extraction (regex over json string)
# ============================================================

IMAGE_URL_RE = re.compile(
    r'https://[^"\\,\s\'<>\)]+(?:googleusercontent|gstatic)[^"\\,\s\'<>\)]*'
)

# Patterns excluidos (decoracao, nao conteudo)
EXCLUDE_PATTERNS = [
    "faviconV2",         # favicons de citacoes
    "/lamda/images/",    # logos de tools
    "/branding/",        # logos Google
]


def extract_image_urls_from_turn(turn: list) -> list[str]:
    """Extrai URLs de imagem (lh3.googleusercontent.com / gstatic) do turn."""
    import json as _json
    s = _json.dumps(turn, ensure_ascii=False)
    matches = IMAGE_URL_RE.findall(s)
    # Dedup + filtra excluded
    seen: set[str] = set()
    out: list[str] = []
    for m in matches:
        if any(p in m for p in EXCLUDE_PATTERNS):
            continue
        # Normaliza escapes
        clean = m.replace("\\u003d", "=").replace("\\u0026", "&")
        if clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


# ============================================================
# Whole-conversation extractors
# ============================================================

def conv_turns(raw_obj: Any) -> list:
    """raw[0] = list of turns. Retorna [] se vazio/None."""
    turns = _path(raw_obj, 0)
    if not isinstance(turns, list):
        return []
    return [t for t in turns if isinstance(t, list)]


def conv_last_timestamp(raw_obj: Any) -> int | None:
    """Maior timestamp_secs entre todos os turns."""
    turns = conv_turns(raw_obj)
    timestamps = [t for t in (turn_timestamp_secs(turn) for turn in turns) if t is not None]
    return max(timestamps) if timestamps else None


# ============================================================
# Path resolution for asset_paths (manifest-based)
# ============================================================

import hashlib


def url_to_local_path(url: str, manifest: dict) -> str | None:
    """Converte URL pra path local via manifest (hash-based filename)."""
    h = hashlib.sha1(url.encode()).hexdigest()[:16]
    if h in manifest:
        return manifest[h].get("local_path")
    return None
