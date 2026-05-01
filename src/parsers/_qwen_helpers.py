"""Helpers do parser Qwen v3. Funcoes puras."""

from __future__ import annotations

import json
from typing import Optional


# Mapeamento chat_type → mode canonico (VALID_MODES em schema/models.py).
# chat_type observados em probe 2026-05-01 (Qwen API):
#   t2t (default) | search | deep_research | t2i | t2v | artifacts | learn | None
CHAT_TYPE_TO_MODE = {
    "t2t": "chat",
    "search": "search",
    "deep_research": "research",
    "t2i": "dalle",         # text-to-image
    "t2v": "dalle",         # text-to-video — sem mode dedicado, agrupa em dalle
    "artifacts": "chat",    # mode chat com artifacts feature
    "learn": "chat",        # mode chat com learn feature
}


# Mapeamento chat_type → categoria pra ToolEvent quando tools sao detectados.
CHAT_TYPE_TO_TOOL_CATEGORY = {
    "search": "search",
    "deep_research": "research",
    "t2i": "image_generation",
    "t2v": "video_generation",
    "artifacts": "artifact",
    "learn": "learn",
}


def collect_text_from_content_list(content_list: list) -> str:
    """Concat de blocks `content_list[*].content` em string unica.

    Qwen msg tem `content` (string crua) E `content_list` (list de blocks
    com timestamp). Pra texto consolidado, usa `content_list` se existe;
    fallback pra `content`.
    """
    if not content_list or not isinstance(content_list, list):
        return ""
    parts = []
    for b in content_list:
        if not isinstance(b, dict):
            continue
        t = b.get("content") or ""
        if t:
            parts.append(t)
    return "\n\n".join(parts)


def block_time_bounds(content_list: list) -> tuple[Optional[float], Optional[float]]:
    """Retorna (min_ts, max_ts) dos blocks. Qwen usa epoch int em `timestamp`."""
    if not content_list or not isinstance(content_list, list):
        return None, None
    starts = []
    for b in content_list:
        if not isinstance(b, dict):
            continue
        ts = b.get("timestamp")
        if ts:
            starts.append(ts)
    if not starts:
        return None, None
    return min(starts), max(starts)


def extract_search_results(msg: dict) -> Optional[list[dict]]:
    """Search results moram em `info` ou em campos especificos do msg.

    Schemas observados:
      - msg.info.search_results: list[dict]
      - msg.extra.web_search.results: list[dict]
      - msg.annotation.citations: list[dict]
    """
    info = msg.get("info") or {}
    if isinstance(info, dict) and isinstance(info.get("search_results"), list):
        return info["search_results"]
    extra = msg.get("extra") or {}
    if isinstance(extra, dict):
        ws = extra.get("web_search") or {}
        if isinstance(ws, dict) and isinstance(ws.get("results"), list):
            return ws["results"]
    annotation = msg.get("annotation") or {}
    if isinstance(annotation, dict) and isinstance(annotation.get("citations"), list):
        return annotation["citations"]
    return None


def collect_file_names(files: list) -> list[str]:
    """Nomes dos files anexados a uma msg."""
    out = []
    for f in files or []:
        if not isinstance(f, dict):
            continue
        n = f.get("name") or f.get("file_name") or ""
        if n:
            out.append(n)
    return out


def serialize_settings(meta: dict, feature_config: dict) -> Optional[str]:
    """Serializa meta + feature_config (per-conv settings) em JSON.

    Captura tags do user, flags de features (web_search, artifacts, etc).
    """
    out = {}
    if isinstance(meta, dict) and meta:
        out["meta"] = meta
    if isinstance(feature_config, dict) and feature_config:
        out["feature_config"] = feature_config
    if not out:
        return None
    return json.dumps(out, ensure_ascii=False)


def build_branches_qwen(
    conv_id: str,
    messages_dict: dict,
    current_id: Optional[str],
) -> tuple[dict[str, str], list[dict]]:
    """Identifica branches do Qwen (DAG plano via parentId/childrenIds).

    `messages_dict` = chat.history.messages (keyed por id).
    `current_id` = data.currentId (leaf da branch ativa).

    Retorna (msg_id -> branch_id, list[Branch records]).
    """
    if not messages_dict:
        return {}, []

    main_branch_id = f"{conv_id}_main"
    msg_to_branch: dict[str, str] = {}
    branches: list[dict] = []

    # 1. Main branch: trace current_id ate root
    main_path = []
    if current_id and current_id in messages_dict:
        node = current_id
        guard = 0
        while node and guard < 100000:
            main_path.append(node)
            parent = messages_dict[node].get("parentId")
            if not parent or parent not in messages_dict:
                break
            node = parent
            guard += 1
        main_path.reverse()

    if not main_path:
        # Fallback: pega root (parentId=None) e desce
        roots = [mid for mid, m in messages_dict.items() if m.get("parentId") is None]
        if roots:
            node = roots[0]
            guard = 0
            while node and guard < 100000:
                main_path.append(node)
                children = messages_dict[node].get("childrenIds") or []
                if not children:
                    break
                node = children[-1]
                guard += 1

    main_set = set(main_path)
    for mid in main_path:
        msg_to_branch[mid] = main_branch_id

    if main_path:
        branches.append({
            "branch_id": main_branch_id,
            "root_message_id": main_path[0],
            "leaf_message_id": main_path[-1],
            "is_active": True,
            "parent_branch_id": None,
            "created_at": messages_dict[main_path[0]].get("timestamp"),
        })

    # 2. Branches secundarias
    visited = set(main_set)
    for mid, mdata in messages_dict.items():
        if mid in visited:
            continue
        # Sobe ate achar parent em main_set ou root
        path_up = []
        node = mid
        while node and node not in main_set:
            path_up.append(node)
            parent = messages_dict.get(node, {}).get("parentId")
            if not parent or parent not in messages_dict:
                break
            node = parent
        branch_root = path_up[-1] if path_up else mid
        branch_id = f"{conv_id}_branch_{mid[:8]}"

        # DFS descendentes
        stack = [branch_root]
        branch_msgs = []
        while stack:
            n = stack.pop()
            if n in main_set or n in visited:
                continue
            visited.add(n)
            branch_msgs.append(n)
            msg_to_branch[n] = branch_id
            for c in messages_dict.get(n, {}).get("childrenIds") or []:
                if c not in main_set:
                    stack.append(c)

        if branch_msgs:
            parent_of_root = messages_dict[branch_root].get("parentId")
            parent_branch = main_branch_id if parent_of_root in main_set else None
            leaf = branch_msgs[0]
            for cand in branch_msgs:
                kids = [c for c in (messages_dict.get(cand, {}).get("childrenIds") or []) if c in branch_msgs]
                if not kids:
                    leaf = cand
                    break
            branches.append({
                "branch_id": branch_id,
                "root_message_id": branch_root,
                "leaf_message_id": leaf,
                "is_active": False,
                "parent_branch_id": parent_branch,
                "created_at": messages_dict[branch_root].get("timestamp"),
            })

    return msg_to_branch, branches
