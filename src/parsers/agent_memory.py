"""Parser de memory files (Claude Code per-project, Codex global).

Le markdown com frontmatter YAML opcional, classifica por kind, retorna
lista de AgentMemory pronta pra parquet.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from src.schema.models import AgentMemory, VALID_MEMORY_KINDS

logger = logging.getLogger(__name__)


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Retorna (dict_frontmatter, body). Frontmatter vazia/invalida -> ({}, content)."""
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content
    fm_text, body = m.group(1), m.group(2)
    try:
        fm = yaml.safe_load(fm_text)
        if not isinstance(fm, dict):
            return {}, content
        return fm, body
    except yaml.YAMLError as e:
        logger.warning(f"frontmatter parse failed: {e}")
        return {}, content


def _decode_kind(file_name: str, frontmatter: dict) -> str:
    if file_name == "MEMORY.md":
        return "index"
    t = frontmatter.get("type")
    if isinstance(t, str) and t in VALID_MEMORY_KINDS:
        return t
    return "other"


def parse_agent_memory_file(
    *,
    path: Path,
    source: str,
    project_path: Optional[str],
    project_key: Optional[str],
    is_preserved_missing: bool,
) -> AgentMemory:
    """Le 1 arquivo .md, retorna AgentMemory."""
    content = path.read_text(encoding="utf-8")
    fm, _body = parse_frontmatter(content)
    kind = _decode_kind(path.name, fm)
    name = fm.get("name") if isinstance(fm.get("name"), str) else None
    description = fm.get("description") if isinstance(fm.get("description"), str) else None

    stat = path.stat()
    mtime = pd.Timestamp.fromtimestamp(stat.st_mtime, tz="UTC")
    return AgentMemory(
        memory_id=f"{source}:{project_key or ''}:{path.name}",
        source=source,
        project_path=project_path,
        project_key=project_key,
        file_name=path.name,
        name=name,
        description=description,
        kind=kind,
        content=content,
        content_size=len(content.encode("utf-8")),
        created_at=mtime,
        updated_at=mtime,
        is_preserved_missing=is_preserved_missing,
    )


def decode_project_path(project_dir: Path) -> Optional[str]:
    """Resolve cwd real lendo primeiro jsonl com campo `cwd`.

    encoded-cwd substitui '/' por '-' mas e ambiguo quando dir tem '-' no nome
    (ex: -Users-x-Desktop-code-maker-v2 vs /Users/x/Desktop/code-maker-v2).
    Sessions Claude Code gravam o cwd real numa das primeiras linhas do jsonl.

    Retorna None se nao conseguir resolver (project_dir sem jsonl).
    """
    for jsonl in project_dir.glob("*.jsonl"):
        try:
            with jsonl.open() as f:
                for i, line in enumerate(f):
                    if i > 50:  # cap scan -- cwd geralmente nas primeiras linhas
                        break
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    cwd = obj.get("cwd")
                    if isinstance(cwd, str) and cwd:
                        return cwd
        except Exception as e:
            logger.warning(f"decode_project_path: {jsonl.name} read failed: {e}")
            continue
    return None


def parse_memories_for_source(
    raw_root: Path,
    source: str,
    home_files: set[str],
) -> list[AgentMemory]:
    """Le memory files de data/raw/<source>/ e retorna lista de AgentMemory.

    Args:
        raw_root: ex. data/raw/Claude Code/ ou data/raw/Codex/
        source: 'claude_code' ou 'codex'
        home_files: relative paths dos arquivos de memory presentes no HOME
            (gerado por current_source_files()) -- usado pra detectar preserved_missing
    """
    if source not in ("claude_code", "codex"):
        raise ValueError(f"agent_memory parser nao suporta source={source}")

    if not raw_root.exists():
        return []

    items: list[AgentMemory] = []

    if source == "claude_code":
        for project_dir in sorted(raw_root.iterdir()):
            if not project_dir.is_dir():
                continue
            mem_dir = project_dir / "memory"
            if not mem_dir.is_dir():
                continue
            project_path = decode_project_path(project_dir)
            project_key = project_dir.name
            for md in sorted(mem_dir.glob("*.md")):
                rel = f"{project_dir.name}/memory/{md.name}"
                preserved = rel not in home_files
                try:
                    items.append(parse_agent_memory_file(
                        path=md,
                        source=source,
                        project_path=project_path,
                        project_key=project_key,
                        is_preserved_missing=preserved,
                    ))
                except Exception as e:
                    logger.warning(f"agent_memory: failed to parse {md}: {e}")
                    continue
    elif source == "codex":
        mem_dir = raw_root / "memories"
        if mem_dir.is_dir():
            for md in sorted(mem_dir.rglob("*.md")):
                rel = f"memories/{md.relative_to(mem_dir)}"
                preserved = rel not in home_files
                try:
                    items.append(parse_agent_memory_file(
                        path=md,
                        source=source,
                        project_path=None,
                        project_key=None,
                        is_preserved_missing=preserved,
                    ))
                except Exception as e:
                    logger.warning(f"agent_memory: failed to parse {md}: {e}")
                    continue

    return items
