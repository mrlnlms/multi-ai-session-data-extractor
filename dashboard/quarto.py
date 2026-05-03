"""Integração Streamlit ↔ Quarto (Fase 3.2 do dashboard-plan).

Helpers pra:
- detectar Quarto instalado
- localizar .qmd e HTML rendirizado
- detectar HTML stale (parquet mais novo que último render)
- disparar `quarto render` via subprocess
- expor HTML rendirizado via Streamlit static serving

Streamlit serve arquivos em PROJECT_ROOT/static/ via path /app/static/<file>.
Por isso copiamos o HTML pra static/quarto/<source>.html após render.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from dashboard.data import PROJECT_ROOT

NOTEBOOKS_DIR = PROJECT_ROOT / "notebooks"
QUARTO_OUTPUT_DIR = NOTEBOOKS_DIR / "_output"
STATIC_DIR = PROJECT_ROOT / "static"
QUARTO_STATIC_SUBDIR = "quarto"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


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
    """Lista de (account_label, qmd_path) pros .qmd per-account existentes.

    Convencao: notebooks/<slug>-acc-{N}.qmd. Retorna so os que existem.
    Plataformas multi-account hoje: Gemini (acc-1, acc-2), NotebookLM (acc-1, acc-2).
    """
    base = _slug(platform)
    out = []
    for cand in sorted(NOTEBOOKS_DIR.glob(f"{base}-acc-*.qmd")):
        label = cand.stem[len(base) + 1:]  # ex: 'acc-1'
        out.append((label, cand))
    return out


def html_output_path(platform: str) -> Path:
    """Path do HTML rendirizado pelo Quarto."""
    return QUARTO_OUTPUT_DIR / f"{_slug(platform)}.html"


def html_output_path_for_qmd(qmd: Path) -> Path:
    """Path do HTML rendirizado pra um .qmd qualquer (consolidado ou per-account)."""
    return QUARTO_OUTPUT_DIR / f"{qmd.stem}.html"


def html_static_path(platform: str) -> Path:
    """Path do HTML servido pelo Streamlit (em static/)."""
    return STATIC_DIR / QUARTO_STATIC_SUBDIR / f"{_slug(platform)}.html"


def html_static_path_for_qmd(qmd: Path) -> Path:
    """Path do HTML servido pelo Streamlit pra um .qmd qualquer."""
    return STATIC_DIR / QUARTO_STATIC_SUBDIR / f"{qmd.stem}.html"


def streamlit_static_url(platform: str) -> str:
    """URL relativa do HTML servido pelo Streamlit.

    Streamlit serve PROJECT_ROOT/static/ via /app/static/. Link relativo
    funciona dentro do dashboard.
    """
    return f"/app/static/{QUARTO_STATIC_SUBDIR}/{_slug(platform)}.html"


def streamlit_static_url_for_qmd(qmd: Path) -> str:
    """URL relativa pra qmd qualquer (consolidado ou per-account)."""
    return f"/app/static/{QUARTO_STATIC_SUBDIR}/{qmd.stem}.html"


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
        raise FileNotFoundError(f"QMD nao existe: {qmd}")
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


def copy_to_static(platform: str) -> Path:
    """Copia HTML rendirizado (consolidado) pra static/quarto/."""
    src = html_output_path(platform)
    if not src.exists():
        raise FileNotFoundError(f"HTML rendirizado nao existe: {src}")
    dst = html_static_path(platform)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def copy_to_static_for_qmd(qmd: Path) -> Path:
    """Copia HTML de um .qmd qualquer (consolidado ou per-account) pra static/."""
    src = html_output_path_for_qmd(qmd)
    if not src.exists():
        raise FileNotFoundError(f"HTML rendirizado nao existe: {src}")
    dst = html_static_path_for_qmd(qmd)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def render_and_publish(platform: str) -> tuple[bool, Optional[str]]:
    """Render + copy do consolidado.

    Returns: (success, error_message_se_falhou).
    """
    try:
        result = render_qmd(platform)
    except FileNotFoundError as e:
        return False, str(e)
    if result.returncode != 0:
        tail = (result.stderr or "")[-500:]
        return False, f"quarto render falhou (exit {result.returncode}):\n{tail}"
    try:
        copy_to_static(platform)
    except Exception as e:
        return False, f"render OK mas copy_to_static falhou: {e}"
    return True, None


def render_and_publish_qmd(qmd: Path) -> tuple[bool, Optional[str]]:
    """Render + copy de um .qmd qualquer (per-account)."""
    try:
        result = _render_qmd_path(qmd)
    except FileNotFoundError as e:
        return False, str(e)
    if result.returncode != 0:
        tail = (result.stderr or "")[-500:]
        return False, f"quarto render falhou (exit {result.returncode}):\n{tail}"
    try:
        copy_to_static_for_qmd(qmd)
    except Exception as e:
        return False, f"render OK mas copy_to_static falhou: {e}"
    return True, None


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
