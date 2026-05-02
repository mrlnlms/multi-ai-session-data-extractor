"""Helpers puros pro parser NotebookLM v3.

Schema posicional (Google batchexecute) — caminhos descobertos via probe
empirico em 2026-05-02. Estruturas:

- metadata (rLM1Ne):  [[title, [sources_list], uuid, emoji, ...]]
                      sources_list[i]: [[uuid], filename, [meta], [tags]]
- guide (VfAZjd):     [[summary_str, [[[questions]]], ...]]
                      questions[i]: [question_text, full_prompt]
- chat (khqZz):       None na maioria (so populado quando user usa)
- notes (cFji9):      [[[uuid, [uuid, content_or_metadata, ...]], ...], ts]
- artifacts (gArtLc): [[[uuid, title, type, source_refs, status, ...]]]
- mind_map (hPTbtc):  [[[uuid]]]
- artifact (v9rmvd):  [[uuid, title, type, source_refs, status, null, null, [content_md]]]
- source (hizoJc):    [[[uuids], filename, [meta], [flags]], None, None, [chunks]]
                      chunks: [start, end, [[[start, end, [text]]]]]
"""

import json
from typing import Optional

import pandas as pd


# === Timestamps ===

def parse_timestamp(epoch_or_array) -> Optional[pd.Timestamp]:
    """Aceita epoch int OR [epoch, nanos] OR ISO string. Retorna pd.Timestamp UTC."""
    if epoch_or_array is None:
        return None
    if isinstance(epoch_or_array, (int, float)):
        try:
            return pd.Timestamp(epoch_or_array, unit="s", tz="UTC")
        except Exception:
            return None
    if isinstance(epoch_or_array, list) and epoch_or_array:
        # [epoch, nanos]
        if isinstance(epoch_or_array[0], (int, float)):
            try:
                return pd.Timestamp(epoch_or_array[0], unit="s", tz="UTC")
            except Exception:
                return None
    if isinstance(epoch_or_array, str):
        try:
            return pd.Timestamp(epoch_or_array, tz="UTC")
        except Exception:
            return None
    return None


# === Sources (metadata + content) ===

def extract_sources_from_metadata(metadata_raw) -> list[dict]:
    """Extrai sources do rLM1Ne. Retorna [{uuid, filename, size_bytes}]."""
    if not isinstance(metadata_raw, list) or not metadata_raw:
        return []
    outer = metadata_raw[0] if isinstance(metadata_raw[0], list) else None
    if not outer or len(outer) < 2 or not isinstance(outer[1], list):
        return []
    out = []
    for s in outer[1]:
        if not (isinstance(s, list) and s and isinstance(s[0], list) and s[0]):
            continue
        uid = s[0][0]
        if not isinstance(uid, str):
            continue
        filename = s[1] if len(s) > 1 and isinstance(s[1], str) else ""
        size = None
        if len(s) > 2 and isinstance(s[2], list) and len(s[2]) > 1 and isinstance(s[2][1], int):
            size = s[2][1]
        out.append({"uuid": uid, "filename": filename, "size_bytes": size})
    return out


def parse_source_content(source_raw) -> str:
    """Extrai texto extraido do hizoJc raw.

    Schema: raw[3][0] = list de chunks. Cada chunk:
        [start, end, [[[start, end, [text_str]]]]]
    Concatena todos os text_str em ordem.
    """
    if not isinstance(source_raw, list) or len(source_raw) < 4:
        return ""
    chunks_container = source_raw[3]
    if not isinstance(chunks_container, list) or not chunks_container:
        return ""
    chunks = chunks_container[0] if isinstance(chunks_container[0], list) else None
    if not isinstance(chunks, list):
        return ""
    parts: list[str] = []
    for chunk in chunks:
        if not isinstance(chunk, list) or len(chunk) < 3:
            continue
        inner = chunk[2]
        if not (isinstance(inner, list) and inner and isinstance(inner[0], list)):
            continue
        for sub in inner[0]:
            if not (isinstance(sub, list) and len(sub) >= 3):
                continue
            text_container = sub[2]
            if isinstance(text_container, list) and text_container and isinstance(text_container[0], str):
                parts.append(text_container[0])
    return "".join(parts)


# === Guide ===

def extract_guide(guide_raw) -> dict:
    """Extrai summary + questions do VfAZjd.

    Schema: guide_raw[0] = [[summary], [[[question_pairs]]], ...]
    questions[i]: [question_text, full_prompt]
    """
    out = {"summary": None, "questions": []}
    if not isinstance(guide_raw, list) or not guide_raw:
        return out
    g0 = guide_raw[0] if isinstance(guide_raw[0], list) else None
    if not g0:
        return out
    # Summary
    if (g0 and isinstance(g0[0], list) and g0[0]
            and isinstance(g0[0][0], str)):
        out["summary"] = g0[0][0]
    # Questions
    if len(g0) > 1 and isinstance(g0[1], list) and g0[1]:
        q_container = g0[1][0] if isinstance(g0[1][0], list) else []
        for i, q in enumerate(q_container):
            if isinstance(q, list) and len(q) >= 2 and isinstance(q[0], str):
                out["questions"].append({
                    "text": q[0],
                    "prompt": q[1] if isinstance(q[1], str) else "",
                    "order": i,
                })
    return out


# === Chat ===

def extract_chat_turns(chat_raw) -> list[dict]:
    """Extrai chat turns do khqZz.

    Empirical: na maioria dos notebooks chat=None. Schema posicional a
    descobrir empirically quando chat estiver populado. Por enquanto
    retorna [] em casos None — refinar quando smoke real tiver chat.
    """
    if chat_raw is None:
        return []
    # TODO: refinar quando capturar chat real (smoke nao teve)
    return []


# === Notes ===

def extract_notes(notes_raw) -> list[dict]:
    """Extrai notes/briefs do cFji9.

    Schema: notes_raw[0] = lista de items. Cada item: [uuid, [uuid, content_str_or_metadata, ...]]
    Items podem ser:
      - Note real: [uuid, [uuid, content_str, list, ...]] — content em [1][1]
      - Mind map ref: [uuid, [uuid, mind_map_uuid, list, ...]] — segundo str eh outro UUID
    Filtra so notes reais (content longo, nao UUID).
    """
    out = []
    if not isinstance(notes_raw, list) or not notes_raw:
        return out
    items = notes_raw[0] if isinstance(notes_raw[0], list) else []
    for item in items:
        if not (isinstance(item, list) and len(item) >= 2 and isinstance(item[0], str)):
            continue
        uuid = item[0]
        meta = item[1] if isinstance(item[1], list) else None
        if not meta or len(meta) < 2:
            continue
        # meta[1] eh content (str longo) OU mind_map_uuid (str 36-char com 4 hifens)
        content = meta[1] if isinstance(meta[1], str) else ""
        # Filtra refs ao mind_map (content vazio ou eh UUID)
        is_uuid_ref = (len(content) == 36 and content.count("-") == 4)
        if not content or is_uuid_ref:
            continue
        # Heuristica: se content comeca com "Com base" ou ":" eh um brief; senao note
        kind = "brief" if (content.startswith(("Com base", "Based", "**", "#"))) else "note"
        out.append({
            "uuid": uuid,
            "title": None,
            "content": content,
            "kind": kind,
            "source_refs": [],
            "created_at": None,
        })
    return out


# === Artifacts ===

def extract_artifacts_list(artifacts_raw) -> list[dict]:
    """Extrai lista de artifacts do gArtLc.

    Schema: artifacts_raw[0] = lista. Cada item: [uuid, title, type, source_refs_lists, status, ...]
    Retorna [{uuid, title, type, status, source_refs, asset_paths(=None inicial)}].
    """
    out = []
    if not isinstance(artifacts_raw, list) or not artifacts_raw:
        return out
    items = artifacts_raw[0] if isinstance(artifacts_raw[0], list) else []
    for it in items:
        if not (isinstance(it, list) and len(it) >= 3):
            continue
        uid = it[0] if isinstance(it[0], str) else None
        if not uid:
            continue
        title = it[1] if isinstance(it[1], str) else None
        ttype = it[2] if isinstance(it[2], int) else None
        status = it[4] if len(it) > 4 and isinstance(it[4], str) else None
        # Source refs: it[3] eh lista de [[uuid]]
        source_refs = []
        if len(it) > 3 and isinstance(it[3], list):
            for ref in it[3]:
                if isinstance(ref, list) and ref and isinstance(ref[0], list) and ref[0]:
                    if isinstance(ref[0][0], str):
                        source_refs.append(ref[0][0])
        out.append({
            "uuid": uid,
            "title": title,
            "type": ttype,
            "status": status,
            "source_refs": source_refs,
            "asset_paths": None,
            "created_at": None,
        })
    return out


def extract_artifact_content(artifact_raw, artifact_type: int) -> Optional[str]:
    """Extrai conteudo de artifact individual (v9rmvd).

    Schema observado pra type=2 (blog): raw[0][0] = [uuid, title, type, source_refs,
    status, null, null, [content_md_str]]. Content em [0][0][7][0].
    Tipos 4/7/9 podem ter schema diferente — refinar empirically.
    """
    if not isinstance(artifact_raw, list) or not artifact_raw:
        return None
    inner = artifact_raw[0] if isinstance(artifact_raw[0], list) else None
    if not inner or len(inner) < 8:
        # Schema diferente — serializar JSON inteiro como fallback
        return json.dumps(artifact_raw, ensure_ascii=False)
    content_container = inner[7] if len(inner) > 7 else None
    if isinstance(content_container, list) and content_container and isinstance(content_container[0], str):
        return content_container[0]
    # Fallback: serializar
    return json.dumps(artifact_raw, ensure_ascii=False)


# === Mind map ===

def extract_mind_map_tree(tree_raw) -> str:
    """Extrai arvore do CYK0Xb. Atual response so retorna metadata —
    estrutura completa de nodes ainda nao mapeada. Serializa pra preservar.

    TODO: investigar empirically se ha outro RPC que retorna tree de nodes.
    """
    if tree_raw is None:
        return ""
    return json.dumps(tree_raw, ensure_ascii=False)
