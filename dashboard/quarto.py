"""Integração do dashboard com os relatórios Quarto.

Helpers pra:
- detectar Quarto instalado
- localizar .qmd e HTML rendirizado
- detectar HTML stale (parquet mais novo que último render)
- disparar `quarto render` via subprocess
- gerar URLs pro servidor local dos relatórios

`notebooks/_output/` e a fonte unica dos HTMLs renderizados. O script
`src.workflows.serve_reports` serve esse diretorio diretamente; o dashboard apenas
gera URLs para esse servidor, sem copiar ou linkar arquivos em `static/`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from src.application.platforms import PROJECT_ROOT

NOTEBOOKS_DIR = PROJECT_ROOT / "notebooks"
QUARTO_OUTPUT_DIR = NOTEBOOKS_DIR / "_output"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DEFAULT_REPORT_SERVER_URL = "http://localhost:8765"


def quarto_installed() -> bool:
    """True se o binario `quarto` esta no PATH."""
    return shutil.which("quarto") is not None


def _slug(platform: str) -> str:
    """Normaliza nome da plataforma pra filename: lowercase + `.`/space → `-`.

    'ChatGPT' → 'chatgpt'
    'Claude.ai' → 'claude-ai'
    'Claude Code' → 'claude-code'
    'Gemini CLI' → 'gemini-cli'
    """
    return platform.lower().replace(".", "-").replace(" ", "-")


def qmd_path(platform: str) -> Path:
    """Path do .qmd consolidado da plataforma. Convencao: notebooks/<slug>.qmd."""
    return NOTEBOOKS_DIR / f"{_slug(platform)}.qmd"


def qmd_paths_per_account(platform: str) -> list[tuple[str, Path]]:
    """Lista de (account_label, qmd_path) pros .qmd per-account/sufixados existentes.

    Convencoes:
    - notebooks/<slug>-acc-{N}.qmd  (multi-account ativo)
    - notebooks/<slug>-legacy.qmd   (snapshot legacy de conta extinta)

    Retorna so os que existem.
    """
    base = _slug(platform)
    out = []
    for cand in sorted(NOTEBOOKS_DIR.glob(f"{base}-acc-*.qmd")):
        label = cand.stem[len(base) + 1:]  # ex: 'acc-1'
        out.append((label, cand))
    for cand in sorted(NOTEBOOKS_DIR.glob(f"{base}-legacy.qmd")):
        label = cand.stem[len(base) + 1:]  # 'legacy'
        out.append((label, cand))
    return out


def html_output_path(platform: str) -> Path:
    """Path do HTML rendirizado pelo Quarto."""
    return QUARTO_OUTPUT_DIR / f"{_slug(platform)}.html"


def html_output_path_for_qmd(qmd: Path) -> Path:
    """Path do HTML rendirizado pra um .qmd qualquer (consolidado ou per-account)."""
    return QUARTO_OUTPUT_DIR / f"{qmd.stem}.html"


def report_server_base_url() -> str:
    """Base URL do servidor que expoe `notebooks/_output/`."""
    return os.environ.get("QMD_REPORT_BASE_URL", DEFAULT_REPORT_SERVER_URL).rstrip("/")


def report_url(platform: str) -> str:
    """URL do relatorio consolidado de uma plataforma."""
    return f"{report_server_base_url()}/{_slug(platform)}.html"


def report_url_for_qmd(qmd: Path) -> str:
    """URL do relatorio de um QMD consolidado, por conta ou overview."""
    return f"{report_server_base_url()}/{qmd.stem}.html"


def is_html_stale(platform: str) -> bool:
    """True se algum parquet eh mais novo que o HTML rendirizado.

    Caso de stale: parser rodou de novo e gerou parquets atualizados, mas
    o HTML ainda eh do render anterior.
    """
    html = html_output_path(platform)
    if not html.exists():
        return True
    html_mtime = html.stat().st_mtime
    parquet_dir = PROCESSED_DIR / platform
    if not parquet_dir.exists():
        return False
    return any(p.stat().st_mtime > html_mtime for p in parquet_dir.glob("*.parquet"))


def render_qmd(platform: str) -> subprocess.CompletedProcess:
    """Renderiza o .qmd consolidado via subprocess bloqueante.

    Usa o Python do venv local (QUARTO_PYTHON env). Retorna o
    CompletedProcess pra caller decidir o que fazer com returncode/stderr.
    """
    qmd = qmd_path(platform)
    return _render_qmd_path(qmd)


def _render_qmd_path(qmd: Path) -> subprocess.CompletedProcess:
    if not qmd.exists():
        raise FileNotFoundError(f"QMD does not exist: {qmd}")
    cmd = ["quarto", "render", str(qmd.relative_to(PROJECT_ROOT))]
    env = {
        **os.environ,
        "QUARTO_PYTHON": str(PROJECT_ROOT / ".venv" / "bin" / "python"),
    }
    return subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


def render_and_publish(platform: str) -> tuple[bool, Optional[str]]:
    """Renderiza o consolidado no diretorio servido por `serve_reports`.

    Returns: (success, error_message_se_falhou).
    """
    try:
        result = render_qmd(platform)
    except FileNotFoundError as e:
        return False, str(e)
    if result.returncode != 0:
        tail = (result.stderr or "")[-500:]
        return False, f"quarto render failed (exit {result.returncode}):\n{tail}"
    return True, None


def render_and_publish_qmd(qmd: Path) -> tuple[bool, Optional[str]]:
    """Renderiza um .qmd qualquer no diretorio servido por `serve_reports`."""
    try:
        result = _render_qmd_path(qmd)
    except FileNotFoundError as e:
        return False, str(e)
    if result.returncode != 0:
        tail = (result.stderr or "")[-500:]
        return False, f"quarto render failed (exit {result.returncode}):\n{tail}"
    return True, None


def qmds_for_platform(platform: str) -> list[Path]:
    """Lista de qmds da plat: consolidado + per-account/legacy quando existem.

    Usado pelo Stage 3 incremental — sync de 1 plat re-renderiza so os
    qmds dela + cross-overview (em vez de todos 22).
    """
    out: list[Path] = []
    consolidated = qmd_path(platform)
    if consolidated.exists():
        out.append(consolidated)
    for _, qmd in qmd_paths_per_account(platform):
        out.append(qmd)
    return out


def overview_qmd_paths() -> list[Path]:
    """Os 00-overview*.qmd cross-plataforma — sempre renderizar em qualquer
    pipeline (agregam todas plats em data/unified/)."""
    return [qmd for _, qmd in overview_qmds()]


def overview_qmds() -> list[tuple[str, Path]]:
    """Retorna [(label, qmd_path)] dos overviews cross-plataforma existentes.

    Convencao: notebooks/00-overview*.qmd. Filtra so os que tem .qmd no
    disco (label = parte apos `00-overview` ou 'Geral' pro `00-overview.qmd`
    sem sufixo).
    """
    out: list[tuple[str, Path]] = []
    for qmd in sorted(NOTEBOOKS_DIR.glob("00-overview*.qmd")):
        stem = qmd.stem
        if stem == "00-overview":
            label = "General (all)"
        else:
            # 00-overview-web -> 'Web Chat', 00-overview-cli -> 'CLI', etc
            tail = stem.replace("00-overview-", "")
            mapping = {
                "web": "Web Chat",
                "cli": "CLI",
                "rag": "RAG (NotebookLM)",
                "projects": "Projects (canonical)",
            }
            label = mapping.get(tail, tail.replace("-", " ").title())
        out.append((label, qmd))
    return out


def is_html_stale_for_qmd(platform: str, qmd: Path) -> bool:
    """True se algum parquet eh mais novo que o HTML rendirizado pra este qmd."""
    html = html_output_path_for_qmd(qmd)
    if not html.exists():
        return True
    html_mtime = html.stat().st_mtime
    parquet_dir = PROCESSED_DIR / platform
    if not parquet_dir.exists():
        return False
    return any(p.stat().st_mtime > html_mtime for p in parquet_dir.glob("*.parquet"))
