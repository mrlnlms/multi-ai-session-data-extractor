"""Cópia incremental de dados CLI locais → data/raw/<source>/.

Coleta:
- Claude Code:  ~/.claude/projects/<encoded-cwd>/*.jsonl + */subagents/*.jsonl + memory/*.md
- Codex:        ~/.codex/sessions/<year>/<month>/<day>/rollout-*.jsonl + ~/.codex/memories/**/*.md
- Gemini CLI:   ~/.gemini/tmp/<hash>/chats/session-*.json + .project_root

Regras:
- Copia arquivos novos (nao existem no destino) ou modificados (mtime maior)
- NUNCA deleta do destino — dados locais que user apagou de ~ permanecem aqui
- Retorna {"new": [...], "updated": [...]}
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
RAW = PROJECT_ROOT / "data" / "raw"


SOURCES = {
    "claude_code": {
        "src": Path.home() / ".claude" / "projects",
        "dst": RAW / "Claude Code",
        "label": "Claude Code",
    },
    "codex": {
        "src": Path.home() / ".codex" / "sessions",
        "dst": RAW / "Codex",
        "label": "Codex",
    },
    "gemini_cli": {
        "src": Path.home() / ".gemini" / "tmp",
        "dst": RAW / "Gemini CLI",
        "label": "Gemini CLI",
    },
    "antigravity_cli": {
        "src": Path.home() / ".gemini" / "antigravity-cli",
        "dst": RAW / "Antigravity CLI",
        "label": "Antigravity CLI",
    },
}


def _sync_tree(src: Path, dst: Path, glob_pattern: str = "**/*") -> dict[str, list[Path]]:
    """Copia arquivos novos/modificados de src pra dst (skip-existing por mtime)."""
    new_files: list[Path] = []
    updated_files: list[Path] = []
    dst.mkdir(parents=True, exist_ok=True)
    for src_file in src.glob(glob_pattern):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(src)
        dst_file = dst / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        if not dst_file.exists():
            try:
                os.link(src_file, dst_file)
            except OSError:
                shutil.copy2(src_file, dst_file)
            new_files.append(dst_file)
        elif src_file.stat().st_mtime > dst_file.stat().st_mtime:
            shutil.copy2(src_file, dst_file)
            updated_files.append(dst_file)
    return {"new": new_files, "updated": updated_files}


def copy_claude_code() -> dict[str, list[Path]]:
    """Copia ~/.claude/projects/*.jsonl (raiz) + */subagents/*.jsonl + memory/*.md."""
    src = SOURCES["claude_code"]["src"]
    dst = SOURCES["claude_code"]["dst"]
    if not src.exists():
        logger.warning(f"  Claude Code: fonte nao encontrada em {src}")
        return {"new": [], "updated": []}

    new_files: list[Path] = []
    updated_files: list[Path] = []
    dst.mkdir(parents=True, exist_ok=True)

    for project_dir in src.iterdir():
        if not project_dir.is_dir():
            continue
        dst_project = dst / project_dir.name
        dst_project.mkdir(parents=True, exist_ok=True)
        # Sessoes principais (raiz do project_dir)
        for jsonl_file in project_dir.glob("*.jsonl"):
            dst_file = dst_project / jsonl_file.name
            if not dst_file.exists():
                try:
                    os.link(jsonl_file, dst_file)
                except OSError:
                    shutil.copy2(jsonl_file, dst_file)
                new_files.append(dst_file)
            elif jsonl_file.stat().st_mtime > dst_file.stat().st_mtime:
                shutil.copy2(jsonl_file, dst_file)
                updated_files.append(dst_file)
        # Subagents
        for sub_file in project_dir.glob("*/subagents/*.jsonl"):
            rel = sub_file.relative_to(project_dir)
            dst_file = dst_project / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            if not dst_file.exists():
                try:
                    os.link(sub_file, dst_file)
                except OSError:
                    shutil.copy2(sub_file, dst_file)
                new_files.append(dst_file)
            elif sub_file.stat().st_mtime > dst_file.stat().st_mtime:
                shutil.copy2(sub_file, dst_file)
                updated_files.append(dst_file)
        # Memory files
        memory_dir = project_dir / "memory"
        if memory_dir.is_dir():
            for md in memory_dir.glob("*.md"):
                dst_file = dst_project / "memory" / md.name
                if not dst_file.exists():
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        os.link(md, dst_file)
                    except OSError:
                        shutil.copy2(md, dst_file)
                    new_files.append(dst_file)
                elif md.stat().st_mtime > dst_file.stat().st_mtime:
                    shutil.copy2(md, dst_file)
                    updated_files.append(dst_file)


    return {"new": new_files, "updated": updated_files}


def copy_codex_memories() -> dict[str, list[Path]]:
    """Copia ~/.codex/memories/**/*.md → data/raw/Codex/memories/.

    No-op se source nao existe ou esta vazio. Idempotente via mtime.
    """
    src_root = Path.home() / ".codex" / "memories"
    dst_root = RAW / "Codex" / "memories"
    new_files: list[Path] = []
    updated_files: list[Path] = []
    if not src_root.exists():
        return {"new": [], "updated": []}
    for src_file in src_root.rglob("*.md"):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(src_root)
        dst_file = dst_root / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        if not dst_file.exists():
            try:
                os.link(src_file, dst_file)
            except OSError:
                shutil.copy2(src_file, dst_file)
            new_files.append(dst_file)
        elif src_file.stat().st_mtime > dst_file.stat().st_mtime:
            shutil.copy2(src_file, dst_file)
            updated_files.append(dst_file)
    return {"new": new_files, "updated": updated_files}


def _copy_sqlite_snapshot(src_file: Path, dst_file: Path) -> None:
    """Copia uma conversa SQLite em um snapshot consistente.

    Antigravity pode manter mudancas no WAL enquanto a conversa esta aberta.
    O backup do SQLite incorpora esse estado sem copiar um par ``.db``/``-wal``
    potencialmente inconsistente. Bancos corrompidos ou em formato futuro caem
    para uma copia binaria, que ainda preserva o artefato original.
    """
    dst_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst_file.with_name(f".{dst_file.name}.{uuid.uuid4().hex}.tmp")
    try:
        source_uri = f"file://{src_file}?mode=ro"
        with sqlite3.connect(source_uri, uri=True, timeout=2) as source:
            with sqlite3.connect(tmp) as destination:
                source.backup(destination)
        os.replace(tmp, dst_file)
    except sqlite3.Error as e:
        tmp.unlink(missing_ok=True)
        logger.warning("  Antigravity CLI: SQLite snapshot failed for %s (%s); copying bytes", src_file.name, e)
        shutil.copy2(src_file, dst_file)


def _copy_antigravity_file(
    src_file: Path,
    src_root: Path,
    dst_root: Path,
    *,
    sqlite_snapshot: bool = False,
) -> tuple[Path, bool, bool]:
    """Copia 1 arquivo Antigravity e retorna ``(dst, new, updated)``."""
    rel = src_file.relative_to(src_root)
    dst_file = dst_root / rel
    is_new = not dst_file.exists()
    companion_mtimes = [src_file.stat().st_mtime]
    if sqlite_snapshot:
        for suffix in ("-wal", "-shm"):
            companion = src_file.with_name(src_file.name + suffix)
            if companion.exists():
                companion_mtimes.append(companion.stat().st_mtime)
    source_mtime = max(companion_mtimes)
    if dst_file.exists() and source_mtime <= dst_file.stat().st_mtime:
        return dst_file, False, False
    if sqlite_snapshot:
        _copy_sqlite_snapshot(src_file, dst_file)
    else:
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(src_file, dst_file)
        except OSError:
            shutil.copy2(src_file, dst_file)
    return dst_file, is_new, True


def copy_antigravity_cli() -> dict[str, list[Path]]:
    """Preserva conversas Antigravity sem copiar configs ou credenciais.

    Inclui os containers de conversa (SQLite atual e ``.pb`` legado), as
    trajetorias JSONL legiveis em ``brain/`` e os indices minimos usados para
    titulo/projeto. O parser usa ``transcript.jsonl``; ``transcript_full`` e
    os containers permanecem no raw como preservacao/fallback.
    """
    src = SOURCES["antigravity_cli"]["src"]
    dst = SOURCES["antigravity_cli"]["dst"]
    if not src.exists():
        logger.warning(f"  Antigravity CLI: fonte nao encontrada em {src}")
        return {"new": [], "updated": []}

    candidates: list[tuple[Path, bool]] = []
    conversations = src / "conversations"
    if conversations.is_dir():
        candidates.extend((p, p.suffix == ".db") for p in conversations.iterdir()
                          if p.is_file() and p.suffix in (".db", ".pb"))
    brain = src / "brain"
    if brain.is_dir():
        candidates.extend((p, False) for p in brain.glob("*/.system_generated/logs/transcript*.jsonl")
                          if p.is_file())
    for rel in ("history.jsonl", "conversation_summaries.db", "cache/conversation_metadata.json", "cache/last_conversations.json"):
        p = src / rel
        if p.is_file():
            candidates.append((p, p.suffix == ".db"))

    new_files: list[Path] = []
    updated_files: list[Path] = []
    for src_file, is_sqlite in candidates:
        rel = src_file.relative_to(src)
        dst_file = dst / rel
        existed = dst_file.exists()
        copied, _new, changed = _copy_antigravity_file(
            src_file, src, dst, sqlite_snapshot=is_sqlite,
        )
        if not changed:
            continue
        if existed:
            updated_files.append(copied)
        else:
            new_files.append(copied)
    return {"new": new_files, "updated": updated_files}


def current_source_files(source: str) -> set[str]:
    """Lista RELATIVE paths de arquivos atualmente no HOME do CLI.

    Util pra parsers detectarem `is_preserved_missing`: arquivos em
    `data/raw/<CLI>/` que ja nao estao no source HOME foram deletados
    pelo user (mas continuam preservados localmente pelo cli-copy).

    Returns: set de paths relativos ao `cfg['src']`. Vazio se source nao
    existir (ex: rodando em outra maquina sem o CLI instalado).
    """
    cfg = SOURCES.get(source)
    if not cfg or not cfg["src"].exists():
        return set()
    src = cfg["src"]
    if source == "claude_code":
        # Raiz: <encoded-cwd>/<id>.jsonl + subagents: <encoded-cwd>/<parent>/subagents/<sub>.jsonl
        # Memory: <encoded-cwd>/memory/<file>.md
        return {
            str(p.relative_to(src))
            for p in src.glob("**/*.jsonl")
        } | {
            str(p.relative_to(src))
            for p in src.glob("*/memory/*.md")
        }
    if source == "codex":
        # ~/.codex/sessions/<year>/<month>/<day>/rollout-*.jsonl
        sessions_root = src
        memories_root = Path.home() / ".codex" / "memories"
        out = {
            str(p.relative_to(sessions_root))
            for p in sessions_root.glob("**/rollout-*.jsonl")
        }
        if memories_root.exists():
            out |= {
                f"memories/{p.relative_to(memories_root)}"
                for p in memories_root.glob("**/*.md")
            }
        return out
    if source == "gemini_cli":
        # ~/.gemini/tmp/<hash>/chats/session-*.json
        return {
            str(p.relative_to(src))
            for p in src.glob("**/*.json")
        }
    if source == "antigravity_cli":
        out: set[str] = set()
        conversations = src / "conversations"
        if conversations.is_dir():
            out |= {
                str(p.relative_to(src))
                for p in conversations.iterdir()
                if p.is_file() and p.suffix in (".db", ".pb")
            }
        brain = src / "brain"
        if brain.is_dir():
            out |= {
                str(p.relative_to(src))
                for p in brain.glob("*/.system_generated/logs/transcript*.jsonl")
                if p.is_file()
            }
        for rel in ("history.jsonl", "conversation_summaries.db", "cache/conversation_metadata.json", "cache/last_conversations.json"):
            if (src / rel).is_file():
                out.add(rel)
        return out
    return set()


def copy_source(source: str) -> dict[str, list[Path]]:
    """Copia 1 source. Retorna {new, updated}."""
    cfg = SOURCES[source]
    label = cfg["label"]
    if source == "claude_code":
        result = copy_claude_code()
    elif source == "codex":
        sessions = _sync_tree(cfg["src"], cfg["dst"]) if cfg["src"].exists() else {"new": [], "updated": []}
        memories = copy_codex_memories()
        result = {
            "new": sessions["new"] + memories["new"],
            "updated": sessions["updated"] + memories["updated"],
        }
    elif source == "antigravity_cli":
        result = copy_antigravity_cli()
    else:
        if not cfg["src"].exists():
            logger.warning(f"  {label}: fonte nao encontrada em {cfg['src']}")
            return {"new": [], "updated": []}
        result = _sync_tree(cfg["src"], cfg["dst"])
    logger.info(f"  {label}: {len(result['new'])} novos, {len(result['updated'])} atualizados")
    return result
