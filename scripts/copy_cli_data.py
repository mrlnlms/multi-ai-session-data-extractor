"""Copia incremental de dados CLI pra data/raw/ (snapshot acumulativo).

Regras:
- Copia arquivos novos (nao existem no destino)
- Atualiza arquivos modificados (mtime origem > mtime destino)
- NUNCA deleta do destino — dados arquivados pelo usuario permanecem
- Retorna dict estruturado {source: {new: [Path,...], updated: [Path,...]}}
  permitindo uso incremental por scripts como ingest_cli.py
"""

import shutil
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW = PROJECT_ROOT / "data/raw"


def _sync_tree(src: Path, dst: Path, glob_pattern: str = "**/*") -> dict[str, list[Path]]:
    """Copia arquivos novos/modificados de src pra dst.

    Retorna {"new": [dst_paths], "updated": [dst_paths]}.
    """
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


def copy_cli_data() -> dict[str, dict[str, list[Path]]]:
    """Executa cópia incremental e retorna estrutura dos arquivos afetados por fonte.

    Returns:
        {
            "claude_code": {"new": [Path, ...], "updated": [Path, ...]},
            "codex":       {"new": [...],       "updated": [...]},
            "gemini_cli":  {"new": [...],       "updated": [...]},
        }
    """
    result: dict[str, dict[str, list[Path]]] = {
        "claude_code": {"new": [], "updated": []},
        "codex": {"new": [], "updated": []},
        "gemini_cli": {"new": [], "updated": []},
    }

    # Gemini CLI: tudo de ~/.gemini/tmp/
    src = Path.home() / ".gemini" / "tmp"
    if src.exists():
        r = _sync_tree(src, RAW / "Gemini CLI Data")
        result["gemini_cli"] = r
        logger.info(f"  Gemini CLI: {len(r['new'])} novos, {len(r['updated'])} atualizados")
    else:
        logger.warning(f"  Gemini CLI: fonte nao encontrada em {src}")

    # Codex: tudo de ~/.codex/sessions/
    src = Path.home() / ".codex" / "sessions"
    if src.exists():
        r = _sync_tree(src, RAW / "Codex Data")
        result["codex"] = r
        logger.info(f"  Codex: {len(r['new'])} novos, {len(r['updated'])} atualizados")
    else:
        logger.warning(f"  Codex: fonte nao encontrada em {src}")

    # Claude Code: *.jsonl na raiz + {session}/subagents/*.jsonl (sem tool-results/)
    src = Path.home() / ".claude" / "projects"
    if src.exists():
        dst = RAW / "Claude Code Data"
        dst.mkdir(parents=True, exist_ok=True)
        new_files: list[Path] = []
        updated_files: list[Path] = []
        for project_dir in src.iterdir():
            if not project_dir.is_dir():
                continue
            dst_project = dst / project_dir.name
            dst_project.mkdir(parents=True, exist_ok=True)
            # Sessoes principais
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
        result["claude_code"] = {"new": new_files, "updated": updated_files}
        logger.info(f"  Claude Code: {len(new_files)} novos, {len(updated_files)} atualizados")
    else:
        logger.warning(f"  Claude Code: fonte nao encontrada em {src}")

    return result


if __name__ == "__main__":
    logger.info("Copiando dados CLI pra data/raw/ (incremental)...")
    copy_cli_data()
    logger.info("Done!")
