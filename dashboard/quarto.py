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


def qmd_path(platform: str) -> Path:
    """Path do .qmd da plataforma. Convencao: notebooks/<lowercase>.qmd."""
    return NOTEBOOKS_DIR / f"{platform.lower()}.qmd"


def html_output_path(platform: str) -> Path:
    """Path do HTML rendirizado pelo Quarto."""
    return QUARTO_OUTPUT_DIR / f"{platform.lower()}.html"


def html_static_path(platform: str) -> Path:
    """Path do HTML servido pelo Streamlit (em static/)."""
    return STATIC_DIR / QUARTO_STATIC_SUBDIR / f"{platform.lower()}.html"


def streamlit_static_url(platform: str) -> str:
    """URL relativa do HTML servido pelo Streamlit.

    Streamlit serve PROJECT_ROOT/static/ via /app/static/. Link relativo
    funciona dentro do dashboard.
    """
    return f"/app/static/{QUARTO_STATIC_SUBDIR}/{platform.lower()}.html"


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
    """Renderiza o .qmd via subprocess bloqueante.

    Usa o Python do venv local (QUARTO_PYTHON env). Retorna o
    CompletedProcess pra caller decidir o que fazer com returncode/stderr.
    """
    qmd = qmd_path(platform)
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
    """Copia HTML rendirizado pra static/quarto/ pra Streamlit servir.

    Returns: path no static.
    """
    src = html_output_path(platform)
    if not src.exists():
        raise FileNotFoundError(f"HTML rendirizado nao existe: {src}")
    dst = html_static_path(platform)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def render_and_publish(platform: str) -> tuple[bool, Optional[str]]:
    """Render + copy pra static em um passo.

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
