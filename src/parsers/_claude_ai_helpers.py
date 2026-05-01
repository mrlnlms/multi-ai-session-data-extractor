"""Helpers do parser Claude.ai v3. Funcoes puras."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


# Tools built-in (nao MCP) observados empiricamente. Categorias alinhadas
# com o ChatGPT pra cross-platform consistency.
BUILTIN_TOOL_TYPE = {
    # Web / search
    "web_search": "search",
    "google_search": "search",
    "web_fetch": "search",
    "launch_extended_search_task": "research",
    "project_knowledge_search": "search",
    # Artifacts
    "artifacts": "artifact",
    # Code interpreter / REPL
    "repl": "code",
    "code_interpreter": "code",
    # File editing / Computer Use (Claude Code-style file tools)
    "str_replace": "code",
    "str_replace_editor": "code",
    "str_replace_based_edit_tool": "code",
    "create_file": "code",
    "view": "code",
    "file_read": "code",
    "present_files": "code",
    "bash": "code",
    "bash_tool": "code",
    # Computer Use (anthropic computer-use API)
    "computer": "computer_use",
    "computer_20241022": "computer_use",
    "computer_20250124": "computer_use",
    # Memory / chat history
    "memory": "memory",
    "memory_user_edits": "memory",
    "recent_chats": "memory",
}


def classify_tool_event(tool_name: Optional[str], is_mcp: bool) -> str:
    """Classifica tool_use.name em event_type canonico.

    MCPs ficam com prefixo 'mcp_' pra facilitar agregacoes downstream
    sem perder o nome real (que vai em metadata_json + tool_name).
    """
    if not tool_name:
        return "other"
    if is_mcp:
        # Heuristica pra subcategorizar MCPs
        n = tool_name.lower()
        if "search" in n or "list" in n or "find" in n:
            return "mcp_search"
        if "fetch" in n or "read" in n or "get" in n:
            return "mcp_fetch"
        if "create" in n or "write" in n or "update" in n or "edit" in n:
            return "mcp_write"
        return "mcp_other"
    return BUILTIN_TOOL_TYPE.get(tool_name, "other")


def concat_text_blocks(content_blocks: list) -> str:
    """Concatena blocks `text` em string unica (separador \\n\\n)."""
    parts = []
    for b in content_blocks or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text" and b.get("text"):
            parts.append(b["text"])
    return "\n\n".join(parts)


def concat_thinking_blocks(content_blocks: list) -> Optional[str]:
    """Concatena blocks `thinking` em string unica. None se nao tem."""
    parts = []
    for b in content_blocks or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "thinking" and b.get("thinking"):
            parts.append(b["thinking"])
    if not parts:
        return None
    return "\n\n".join(parts)


def collect_block_types(content_blocks: list) -> list[str]:
    """Lista de types unicos dos blocks (ordem nao importa, vai virar set)."""
    types = set()
    for b in content_blocks or []:
        if isinstance(b, dict) and b.get("type"):
            types.add(b["type"])
    return sorted(types)


def collect_citations(content_blocks: list) -> list[dict]:
    """Coleta `citations` aninhadas em blocks `text`. Achata em uma lista."""
    out = []
    for b in content_blocks or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text":
            cits = b.get("citations") or []
            if isinstance(cits, list):
                out.extend(c for c in cits if c)
    return out


def block_time_bounds(content_blocks: list) -> tuple[Optional[str], Optional[str]]:
    """Retorna (min start_timestamp, max stop_timestamp) entre todos os blocks.

    Util pra medir latencia: quanto tempo total Claude levou pra produzir
    a msg (incluindo thinking + tool calls + text). Strings ISO — caller
    converte pra Timestamp.
    """
    starts, stops = [], []
    for b in content_blocks or []:
        if not isinstance(b, dict):
            continue
        s = b.get("start_timestamp")
        e = b.get("stop_timestamp")
        if s:
            starts.append(s)
        if e:
            stops.append(e)
    return (min(starts) if starts else None, max(stops) if stops else None)


def is_mcp_tool_use(block: dict) -> bool:
    """Detecta MCP no tool_use checando os 3 sinais que a spec do projeto pai
    listou: integration_name, mcp_server_url, is_mcp_app."""
    if not isinstance(block, dict):
        return False
    return bool(
        block.get("integration_name")
        or block.get("mcp_server_url")
        or block.get("is_mcp_app")
    )


def serialize_attachments(attachments: list[dict]) -> list[dict]:
    """Serializa attachments preservando extracted_content (campo critico do
    schema do Claude.ai — 1.8k+ attachments com texto extraido inline)."""
    out = []
    for a in attachments or []:
        if not isinstance(a, dict):
            continue
        out.append({
            "id": a.get("id"),
            "file_name": a.get("file_name") or "",
            "file_type": a.get("file_type"),
            "file_size": a.get("file_size"),
            "extracted_content": a.get("extracted_content") or "",
            "created_at": a.get("created_at"),
        })
    return out


def resolve_file_assets(
    files: list[dict],
    assets_root: Path,
) -> Optional[list[str]]:
    """Resolve files (uploads binarios) pra paths em disco.

    Layout: <assets_root>/{file_uuid}_preview.webp (e/ou _thumbnail.webp).
    Retorna lista de paths relativos ao project root, ou None se vazio.
    """
    if not files:
        return None
    paths = []
    for f in files:
        if not isinstance(f, dict):
            continue
        fuuid = f.get("file_uuid")
        if not fuuid:
            continue
        # Tenta preview primeiro (maior), depois thumbnail
        for variant in ("preview", "thumbnail"):
            candidate = assets_root / f"{fuuid}_{variant}.webp"
            if candidate.exists():
                paths.append(str(candidate))
                break
    return paths or None


def collect_attachment_names(attachments: list[dict]) -> list[str]:
    """Lista de file_names dos attachments (ignora vazios)."""
    names = []
    for a in attachments or []:
        if not isinstance(a, dict):
            continue
        fn = a.get("file_name") or ""
        if fn:
            names.append(fn)
    return names


# UUID-zero usado pelo Claude pra root (parent_message_uuid de mensagens iniciais)
ROOT_PARENT = "00000000-0000-4000-8000-000000000000"


def is_root_message(msg: dict) -> bool:
    """True se msg eh raiz da arvore (parent eh o UUID-zero)."""
    return msg.get("parent_message_uuid") == ROOT_PARENT


def build_branches(
    conv_id: str,
    chat_messages: list[dict],
    current_leaf_uuid: Optional[str],
) -> tuple[dict[str, str], list[dict]]:
    """Identifica branches via DAG plano (parent_message_uuid + current_leaf).

    Algoritmo:
    1. Constroi adjacencia {parent_uuid: [child_uuids]}
    2. Trace `current_leaf` ate root → main path (msgs in main branch)
    3. Pra cada msg c/ multiplos children: 1 child eh main, outros viram
       branches secundarias (cada uma identificada pelo seu leaf)
    4. branch_id: conv_id + '_main' OR conv_id + '_branch_' + short_uuid

    Retorna (msg_uuid -> branch_id, list of branch records).
    """
    if not chat_messages:
        return {}, []

    # Indexa msgs por uuid
    by_uuid = {m["uuid"]: m for m in chat_messages if m.get("uuid")}

    # Adjacencia
    children: dict[str, list[str]] = {}
    for m in chat_messages:
        parent = m.get("parent_message_uuid")
        if parent and parent != ROOT_PARENT:
            children.setdefault(parent, []).append(m["uuid"])

    # Find root(s): parent eh ROOT_PARENT ou nao existe no by_uuid
    roots = [
        m["uuid"] for m in chat_messages
        if (m.get("parent_message_uuid") == ROOT_PARENT
            or m.get("parent_message_uuid") not in by_uuid)
    ]

    main_branch_id = f"{conv_id}_main"
    msg_to_branch: dict[str, str] = {}
    branch_records: list[dict] = []

    # 1. Main branch: current_leaf → root (ou primeiro root)
    main_path = []
    if current_leaf_uuid and current_leaf_uuid in by_uuid:
        node = current_leaf_uuid
        guard = 0
        while node and guard < 100000:
            main_path.append(node)
            parent = by_uuid[node].get("parent_message_uuid")
            if not parent or parent == ROOT_PARENT or parent not in by_uuid:
                break
            node = parent
            guard += 1
        main_path.reverse()

    if not main_path and roots:
        # Fallback: pega primeira cadeia root → folha (caso current_leaf nao
        # bata). Sem isso convs sem leaf valido perdem todas as msgs do main.
        node = roots[0]
        guard = 0
        while node and guard < 100000:
            main_path.append(node)
            kids = children.get(node, [])
            if not kids:
                break
            node = kids[0]
            guard += 1

    main_set = set(main_path)
    for uid in main_path:
        msg_to_branch[uid] = main_branch_id

    if main_path:
        branch_records.append({
            "branch_id": main_branch_id,
            "root_message_id": main_path[0],
            "leaf_message_id": main_path[-1],
            "is_active": True,
            "parent_branch_id": None,
            "created_at": by_uuid[main_path[0]].get("created_at"),
        })

    # 2. Branches secundarias: msgs nao em main_set
    visited = set(main_set)
    branch_count = 0
    for m in chat_messages:
        uid = m["uuid"]
        if uid in visited:
            continue
        # DFS pra coletar a sub-branch a partir desta msg ate sua leaf
        # Sobe ate achar parent que esta em main_set ou root
        path_up = []
        node = uid
        while node and node not in main_set:
            path_up.append(node)
            parent = by_uuid.get(node, {}).get("parent_message_uuid")
            if not parent or parent == ROOT_PARENT or parent not in by_uuid:
                break
            node = parent
        # Agora desce de path_up[-1] (mais antigo da branch) ate uma folha
        # via primeiro child (heuristica simples — preserva content)
        branch_root = path_up[-1] if path_up else uid
        branch_id_short = uid[:8]
        branch_count += 1
        branch_id = f"{conv_id}_branch_{branch_id_short}"

        # Coleta todas as msgs descendentes deste branch_root que nao estao em main
        stack = [branch_root]
        branch_msgs = []
        while stack:
            n = stack.pop()
            if n in main_set or n in visited:
                continue
            visited.add(n)
            branch_msgs.append(n)
            msg_to_branch[n] = branch_id
            for c in children.get(n, []):
                if c not in main_set:
                    stack.append(c)

        # Determina parent branch — eh main se branch_root tem parent em main_set
        parent_of_root = by_uuid[branch_root].get("parent_message_uuid")
        parent_branch = main_branch_id if parent_of_root in main_set else None

        if branch_msgs:
            # Leaf = msg sem children (ou todos os children fora dela)
            leaf = branch_msgs[0]
            for cand in branch_msgs:
                kids = [c for c in children.get(cand, []) if c in branch_msgs]
                if not kids:
                    leaf = cand
                    break

            branch_records.append({
                "branch_id": branch_id,
                "root_message_id": branch_root,
                "leaf_message_id": leaf,
                "is_active": False,
                "parent_branch_id": parent_branch,
                "created_at": by_uuid[branch_root].get("created_at"),
            })

    return msg_to_branch, branch_records
