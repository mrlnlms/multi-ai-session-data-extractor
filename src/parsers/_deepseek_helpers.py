"""Helpers do parser DeepSeek v3. Funcoes puras."""

from __future__ import annotations

import json
from typing import Optional


def build_branches_deepseek(
    conv_id: str,
    chat_messages: list[dict],
    current_message_id: Optional[int],
) -> tuple[dict[str, str], list[dict]]:
    """Identifica branches DeepSeek (DAG plano via parent_id + current_message_id).

    `chat_messages` = list of dicts com `message_id` (int) + `parent_id` (int|None).
    `current_message_id` = leaf da branch ativa.

    message_id eh INT — branch_id sera string ('<conv>_main' ou '<conv>_branch_<int>').
    """
    if not chat_messages:
        return {}, []

    by_id = {m["message_id"]: m for m in chat_messages if m.get("message_id") is not None}
    children: dict[int, list[int]] = {}
    for m in chat_messages:
        parent = m.get("parent_id")
        if parent is not None:
            children.setdefault(parent, []).append(m["message_id"])

    main_branch_id = f"{conv_id}_main"
    msg_to_branch: dict[str, str] = {}
    branches: list[dict] = []

    # Main: trace current_message_id ate root (parent_id None)
    main_path: list[int] = []
    if current_message_id is not None and current_message_id in by_id:
        node = current_message_id
        guard = 0
        while node is not None and guard < 100000:
            main_path.append(node)
            parent = by_id[node].get("parent_id")
            if parent is None or parent not in by_id:
                break
            node = parent
            guard += 1
        main_path.reverse()

    if not main_path:
        # Fallback: pega root e desce
        roots = [m["message_id"] for m in chat_messages if m.get("parent_id") is None]
        if roots:
            node = roots[0]
            guard = 0
            while node is not None and guard < 100000:
                main_path.append(node)
                kids = children.get(node, [])
                if not kids:
                    break
                node = kids[-1]
                guard += 1

    main_set = set(main_path)
    for mid in main_path:
        msg_to_branch[str(mid)] = main_branch_id

    if main_path:
        branches.append({
            "branch_id": main_branch_id,
            "root_message_id": str(main_path[0]),
            "leaf_message_id": str(main_path[-1]),
            "is_active": True,
            "parent_branch_id": None,
            "created_at": by_id[main_path[0]].get("inserted_at"),
        })

    # Branches secundarias
    visited = set(main_set)
    for m in chat_messages:
        mid = m.get("message_id")
        if mid is None or mid in visited:
            continue
        # Sobe ate main_set
        path_up: list[int] = []
        node = mid
        while node is not None and node not in main_set:
            path_up.append(node)
            parent = by_id.get(node, {}).get("parent_id")
            if parent is None or parent not in by_id:
                break
            node = parent
        branch_root = path_up[-1] if path_up else mid
        branch_id = f"{conv_id}_branch_{mid}"

        stack = [branch_root]
        branch_msgs: list[int] = []
        while stack:
            n = stack.pop()
            if n in main_set or n in visited:
                continue
            visited.add(n)
            branch_msgs.append(n)
            msg_to_branch[str(n)] = branch_id
            for c in children.get(n, []):
                if c not in main_set:
                    stack.append(c)

        if branch_msgs:
            parent_of_root = by_id[branch_root].get("parent_id")
            parent_branch = main_branch_id if parent_of_root in main_set else None
            leaf = branch_msgs[0]
            for cand in branch_msgs:
                kids = [c for c in children.get(cand, []) if c in branch_msgs]
                if not kids:
                    leaf = cand
                    break
            branches.append({
                "branch_id": branch_id,
                "root_message_id": str(branch_root),
                "leaf_message_id": str(leaf),
                "is_active": False,
                "parent_branch_id": parent_branch,
                "created_at": by_id[branch_root].get("inserted_at"),
            })

    return msg_to_branch, branches


def normalize_status_to_finish_reason(status: Optional[str], incomplete: Optional[str]) -> Optional[str]:
    """DeepSeek tem status enum + incomplete_message. Mapeia pra finish_reason."""
    if incomplete:
        return "incomplete"
    if status == "FINISHED":
        return "stop"
    if status:
        return status.lower()
    return None
