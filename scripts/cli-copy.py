"""Copia incremental de dados CLI pra data/raw/<source>/.

Coleta:
- Claude Code:  ~/.claude/projects/<encoded-cwd>/*.jsonl + */subagents/*.jsonl
- Codex:        ~/.codex/sessions/<year>/<month>/<day>/rollout-*.jsonl
- Gemini CLI:   ~/.gemini/tmp/<hash>/chats/session-*.json + .project_root

Regras:
- Copia arquivos novos (nao existem no destino) ou modificados (mtime maior)
- NUNCA deleta do destino — dados locais que user apagou de ~ permanecem aqui
- Retorna {source: {new: [...], updated: [...]}}

Uso:
    PYTHONPATH=. .venv/bin/python scripts/cli-copy.py            # todos os 3
    PYTHONPATH=. .venv/bin/python scripts/cli-copy.py --source claude_code
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
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
            shutil.copy2(src_file, dst_file)
            new_files.append(dst_file)
        elif src_file.stat().st_mtime > dst_file.stat().st_mtime:
            shutil.copy2(src_file, dst_file)
            updated_files.append(dst_file)
    return {"new": new_files, "updated": updated_files}


def copy_claude_code() -> dict[str, list[Path]]:
    """Copia ~/.claude/projects/*.jsonl (raiz) + */subagents/*.jsonl (sem tool-results/)."""
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
                shutil.copy2(sub_file, dst_file)
                new_files.append(dst_file)
            elif sub_file.stat().st_mtime > dst_file.stat().st_mtime:
                shutil.copy2(sub_file, dst_file)
                updated_files.append(dst_file)

    return {"new": new_files, "updated": updated_files}


def copy_source(source: str) -> dict[str, list[Path]]:
    """Copia 1 source. Retorna {new, updated}."""
    cfg = SOURCES[source]
    label = cfg["label"]
    if source == "claude_code":
        result = copy_claude_code()
    else:
        if not cfg["src"].exists():
            logger.warning(f"  {label}: fonte nao encontrada em {cfg['src']}")
            return {"new": [], "updated": []}
        result = _sync_tree(cfg["src"], cfg["dst"])
    logger.info(f"  {label}: {len(result['new'])} novos, {len(result['updated'])} atualizados")
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=list(SOURCES.keys()), default=None,
                    help="Roda so 1 source (default: todos os 3)")
    args = ap.parse_args()

    sources = [args.source] if args.source else list(SOURCES.keys())

    logger.info("Copiando dados CLI pra data/raw/ (incremental)...")
    for s in sources:
        copy_source(s)
    logger.info("Done!")


if __name__ == "__main__":
    main()
