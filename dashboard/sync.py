"""Disparo de sync por plataforma via subprocess.

ChatGPT tem orquestrador (chatgpt-sync.py). As outras 6 plataformas
ainda nao tem sync orquestrador implementado: o botao mostra fallback
"so login + export individual" pra deixar explicito.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from dashboard.data import PROJECT_ROOT, SCRIPT_PREFIX

SCRIPTS_DIR = PROJECT_ROOT / "scripts"


def has_sync_script(platform: str) -> bool:
    prefix = SCRIPT_PREFIX.get(platform)
    if not prefix:
        return False
    return (SCRIPTS_DIR / f"{prefix}-sync.py").exists()


def has_export_script(platform: str) -> bool:
    prefix = SCRIPT_PREFIX.get(platform)
    if not prefix:
        return False
    return (SCRIPTS_DIR / f"{prefix}-export.py").exists()


def sync_command(platform: str) -> Optional[list[str]]:
    """Retorna o comando preferido pra capturar a plataforma.

    Prefere o sync orquestrador (so ChatGPT por enquanto). Cai no export
    standalone se nao houver sync. Retorna None se nem export existe.
    """
    prefix = SCRIPT_PREFIX.get(platform)
    if not prefix:
        return None
    python = sys.executable
    if has_sync_script(platform):
        cmd = [python, str(SCRIPTS_DIR / f"{prefix}-sync.py")]
        if platform == "ChatGPT":
            cmd.append("--no-voice-pass")
        return cmd
    if has_export_script(platform):
        return [python, str(SCRIPTS_DIR / f"{prefix}-export.py")]
    return None


def run_sync(platform: str, capture_output: bool = True) -> subprocess.CompletedProcess:
    """Executa sync da plataforma, bloqueante. Levanta se comando nao existe."""
    cmd = sync_command(platform)
    if cmd is None:
        raise RuntimeError(f"No sync or export script found for {platform}")
    env_pythonpath = str(PROJECT_ROOT)
    return subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=capture_output,
        text=True,
        env={**_safe_env(), "PYTHONPATH": env_pythonpath},
    )


def _safe_env() -> dict[str, str]:
    import os

    return {k: v for k, v in os.environ.items()}


def run_sync_streaming(
    platform: str,
    on_line,
    tail_size: int = 30,
) -> tuple[int, str]:
    """Roda sync da plataforma com stdout streaming (line-by-line).

    `on_line(str)` eh chamado pra cada linha do stdout (stderr merged).
    Retorna (returncode, ultimas tail_size linhas concatenadas) — util pra
    montar mensagem de erro sem precisar reabrir log.
    """
    cmd = sync_command(platform)
    if cmd is None:
        raise RuntimeError(f"No sync or export script found for {platform}")
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env={**_safe_env(), "PYTHONPATH": str(PROJECT_ROOT)},
    )
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip("\n")
        tail.append(line)
        if len(tail) > tail_size:
            tail = tail[-tail_size:]
        try:
            on_line(line)
        except Exception:
            pass  # callback do Streamlit nao deve interromper o sync
    proc.wait()
    return proc.returncode, "\n".join(tail)


def run_unify(capture_output: bool = True) -> subprocess.CompletedProcess:
    """Roda scripts/unify-parquets.py — materializa data/unified/ a partir
    de data/processed/<plat>/. Idempotente, sem args."""
    cmd = [sys.executable, str(SCRIPTS_DIR / "unify-parquets.py")]
    return subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=capture_output,
        text=True,
        env={**_safe_env(), "PYTHONPATH": str(PROJECT_ROOT)},
    )


def quarto_installed() -> bool:
    return shutil.which("quarto") is not None
