"""Meta-tests: validam que cada fixture do parser v3 contem o feature
que promete pelo nome.

Sem isso, fixtures podem degradar silenciosamente em refactor (alguem
edita pra "limpar" e tira o feature alvo). Cada teste roda em <1s.
"""

import json
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent


def _load(name: str) -> dict:
    """Carrega fixture e retorna o conv (top-level eh wrapper {conversation_id, conversation})."""
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        wrapper = json.load(f)
    assert "conversation_id" in wrapper, f"{name} sem conversation_id"
    assert "conversation" in wrapper, f"{name} sem conversation"
    return wrapper["conversation"]


def _iter_messages(conv: dict):
    """Gera todas as msgs do mapping da conv."""
    mapping = conv.get("mapping") or {}
    for node_id, node in mapping.items():
        msg = node.get("message")
        if msg is not None:
            yield node_id, node, msg


# ============================================================
# branches: ≥1 node com ≥2 children
# ============================================================

def test_fixture_branches_has_fork():
    conv = _load("raw_with_branches.json")
    mapping = conv.get("mapping") or {}
    forks = [
        nid for nid, n in mapping.items()
        if len(n.get("children") or []) >= 2
    ]
    assert forks, "fixture branches deve ter ≥1 node com ≥2 children"


# ============================================================
# voice: ≥1 msg com audio_transcription em parts
# ============================================================

def test_fixture_voice_has_audio_transcription():
    conv = _load("raw_with_voice.json")
    found = False
    for _, _, msg in _iter_messages(conv):
        content = msg.get("content") or {}
        parts = content.get("parts") or []
        for p in parts:
            if isinstance(p, dict) and p.get("content_type") == "audio_transcription":
                found = True
                break
        if found:
            break
    assert found, "fixture voice deve ter ≥1 part audio_transcription"


# ============================================================
# dalle: ≥1 msg com image_asset_pointer marcado dalle
# ============================================================

def test_fixture_dalle_has_image_asset_pointer():
    conv = _load("raw_with_dalle.json")
    found = False
    for _, _, msg in _iter_messages(conv):
        content = msg.get("content") or {}
        parts = content.get("parts") or []
        for p in parts:
            if not isinstance(p, dict):
                continue
            if p.get("content_type") == "image_asset_pointer":
                meta = p.get("metadata") or {}
                if meta.get("dalle"):
                    found = True
                    break
        if found:
            break
    assert found, "fixture dalle deve ter ≥1 image_asset_pointer com metadata.dalle"


# ============================================================
# canvas: ≥1 msg com canvas marker (recipient canmore.* ou metadata.canvas)
# ============================================================

def test_fixture_canvas_has_canvas_marker():
    conv = _load("raw_with_canvas.json")
    found = False
    for _, _, msg in _iter_messages(conv):
        recipient = msg.get("recipient") or ""
        meta = msg.get("metadata") or {}
        if recipient.startswith("canmore.") or meta.get("canvas"):
            found = True
            break
        author = msg.get("author") or {}
        author_name = author.get("name") or ""
        if author_name.startswith("canmore."):
            found = True
            break
    assert found, "fixture canvas deve ter ≥1 marker canvas (recipient/author canmore.* ou metadata.canvas)"


# ============================================================
# deep_research: ≥1 msg com marker (model_slug research, deep_research_version, etc)
# ============================================================

def test_fixture_deep_research_has_marker():
    conv = _load("raw_with_deep_research.json")
    found = False
    for _, _, msg in _iter_messages(conv):
        meta = msg.get("metadata") or {}
        slug = (meta.get("model_slug") or "").lower()
        if "research" in slug:
            found = True
            break
        if meta.get("deep_research_version") or meta.get("research_done"):
            found = True
            break
        recipient = msg.get("recipient") or ""
        if "research" in recipient.lower():
            found = True
            break
    assert found, "fixture deep_research deve ter ≥1 marker research"


# ============================================================
# tether_quote: ≥1 msg com content_type=tether_quote
# ============================================================

def test_fixture_tether_quote_has_quote():
    conv = _load("raw_with_tether_quote.json")
    found = False
    for _, _, msg in _iter_messages(conv):
        content = msg.get("content") or {}
        if content.get("content_type") == "tether_quote":
            found = True
            break
        # alt: pode estar em metadata
        meta = msg.get("metadata") or {}
        if meta.get("tether_quote"):
            found = True
            break
    assert found, "fixture tether_quote deve ter ≥1 msg com content_type=tether_quote"


# ============================================================
# custom_gpt: conv tem gizmo_id setado
# ============================================================

def test_fixture_custom_gpt_has_gizmo_id():
    conv = _load("raw_with_custom_gpt.json")
    gid = conv.get("gizmo_id")
    assert gid, "fixture custom_gpt deve ter gizmo_id top-level"
    assert gid.startswith("g-"), f"gizmo_id deve comecar com 'g-': {gid!r}"
    # Validar consistencia: se algum msg.metadata tem gizmo_id, deve bater
    for _, _, msg in _iter_messages(conv):
        meta = msg.get("metadata") or {}
        msg_gid = meta.get("gizmo_id")
        if msg_gid:
            assert msg_gid == gid, f"gizmo_id inconsistente: conv={gid} vs msg={msg_gid}"


# ============================================================
# tools: ≥1 msg com author.role=tool
# ============================================================

def test_fixture_tools_has_tool_role():
    conv = _load("raw_with_tools.json")
    found = False
    for _, _, msg in _iter_messages(conv):
        author = msg.get("author") or {}
        if author.get("role") == "tool":
            found = True
            # tool name deve estar preservado (nao redactado) — eh nome do tool
            name = author.get("name")
            assert name and not name.startswith("[REDACTED"), \
                f"author.name de role=tool deve ser preservado: {name!r}"
            break
    assert found, "fixture tools deve ter ≥1 msg com author.role=tool"


# ============================================================
# Sanity geral: PII de title sempre redactada
# ============================================================

ALL_FIXTURES = [
    "raw_with_branches.json",
    "raw_with_voice.json",
    "raw_with_dalle.json",
    "raw_with_canvas.json",
    "raw_with_deep_research.json",
    "raw_with_tether_quote.json",
    "raw_with_custom_gpt.json",
    "raw_with_tools.json",
]


@pytest.mark.parametrize("fname", ALL_FIXTURES)
def test_fixture_title_is_redacted(fname):
    """PII: o title da conv (nome do chat) deve estar redactado em todos."""
    conv = _load(fname)
    title = conv.get("title")
    if title is None or title == "":
        return  # title vazio eh OK
    assert title.startswith("[REDACTED"), \
        f"{fname}: title deve estar redactado, esta {title!r}"


@pytest.mark.parametrize("fname", ALL_FIXTURES)
def test_fixture_has_required_top_level_keys(fname):
    """Toda fixture deve ter as keys minimas pro parser funcionar."""
    conv = _load(fname)
    required = {"id", "create_time", "update_time", "mapping", "current_node"}
    missing = required - set(conv.keys())
    assert not missing, f"{fname}: faltam keys top-level: {missing}"
