"""Disparo de sync por plataforma via subprocess.

ChatGPT tem orquestrador (chatgpt-sync.py). As outras 6 plataformas
ainda nao tem sync orquestrador implementado: o botao mostra fallback
"so login + export individual" pra deixar explicito.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from dashboard.data import PROJECT_ROOT, SCRIPT_PREFIX

# Env vars que impedem subprocess de prompter quando credentials faltam.
# Sem isso, `git push` / `dvc push` podem pendurar pra sempre esperando
# entrada de TTY que o Streamlit nao tem. NAO mexer em DISPLAY: Chromium
# headed do ChatGPT/Perplexity herda essa env, e em Linux DISPLAY="" quebra.
_NONINTERACTIVE_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "/bin/true",
    "SSH_ASKPASS": "/bin/true",
}

SCRIPTS_DIR = PROJECT_ROOT / "scripts"
LOCK_PATH = PROJECT_ROOT / ".update-all.lock"

# Pastas versionadas via DVC (espelha CLAUDE.md "Rotina pos-captura").
# Atualizar AQUI quando adicionar plataforma com diretorio externo novo.
DVC_PATHS: list[str] = [
    "data/raw",
    "data/merged",
    "data/processed",
    "data/unified",
    "data/external/manual-saves",
    "data/external/deep-research-md",
    "data/external/perplexity-orphan-threads",
    "data/external/deepseek-snapshots",
    "data/external/chatgpt-extension-snapshot",
    "data/external/claude-ai-snapshots",
    "data/external/notebooklm-snapshots",
    "data/external/openai-gdpr-export",
    "data/external/claude-code-config-snapshots",
    "data/external/codex-config-snapshots",
    "data/external/gemini-config-snapshots",
    "data/external/grok-snapshots",
]


def _safe_env() -> dict[str, str]:
    return dict(os.environ)


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


def run_sync_streaming(
    platform: str,
    on_line,
    tail_size: int = 30,
    timeout: Optional[float] = 3600.0,
) -> tuple[int, str]:
    """Roda sync da plataforma com stdout streaming (line-by-line).

    `on_line(str)` eh chamado pra cada linha do stdout (stderr merged).
    Retorna (returncode, ultimas tail_size linhas concatenadas) — util pra
    montar mensagem de erro sem precisar reabrir log. `timeout` em segundos
    (default 1h) mata o processo se exceder — protege contra prompts/hang.
    """
    cmd = sync_command(platform)
    if cmd is None:
        raise RuntimeError(f"No sync or export script found for {platform}")
    return _stream(cmd, on_line, tail_size=tail_size, timeout=timeout)


def run_unify(capture_output: bool = True) -> subprocess.CompletedProcess:
    """Roda scripts/unify-parquets.py — materializa data/unified/ a partir
    de data/processed/<plat>/. Idempotente, sem args. Bloqueante."""
    cmd = [sys.executable, str(SCRIPTS_DIR / "unify-parquets.py")]
    return subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=capture_output,
        text=True,
        env={**_safe_env(), "PYTHONPATH": str(PROJECT_ROOT)},
    )


def run_unify_streaming(
    on_line: Callable[[str], None],
    timeout: float = 30 * 60.0,
) -> tuple[int, str]:
    """Versao streaming do unify pro pipeline. UI uniforme com os outros stages."""
    cmd = [sys.executable, str(SCRIPTS_DIR / "unify-parquets.py")]
    return _stream(cmd, on_line, tail_size=30, timeout=timeout)


def _stream(
    cmd: list[str],
    on_line: Callable[[str], None],
    tail_size: int = 20,
    timeout: Optional[float] = None,
    extra_env: Optional[dict[str, str]] = None,
) -> tuple[int, str]:
    """Roda comando, streaming stdout (stderr merged) linha a linha via callback.
    Retorna (returncode, ultimas `tail_size` linhas concatenadas).

    - `stdin=DEVNULL` + env nao-interativa: nunca penduram em prompts.
    - `timeout` (segundos): mata o processo se exceder. Sem timeout = sem
      cap (perigoso pra subcomandos que podem hang silencioso).
    - `extra_env`: vars adicionais (ex: QUARTO_PYTHON pro `quarto render`).
    """
    env = {**_safe_env(), "PYTHONPATH": str(PROJECT_ROOT), **_NONINTERACTIVE_ENV}
    if extra_env:
        env.update(extra_env)
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        env=env,
    )
    timer: Optional[threading.Timer] = None
    timed_out = {"v": False}
    if timeout is not None:
        def _kill():
            timed_out["v"] = True
            try:
                proc.kill()
            except Exception:
                pass
        timer = threading.Timer(timeout, _kill)
        timer.start()

    tail: list[str] = []
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            tail.append(line)
            if len(tail) > tail_size:
                tail = tail[-tail_size:]
            try:
                on_line(line)
            except Exception:
                pass  # callback do Streamlit nao deve interromper o subprocess
        proc.wait()
    finally:
        if timer is not None:
            timer.cancel()
    if timed_out["v"]:
        msg = f"TIMEOUT: process killed after {timeout}s"
        tail.append(msg)
        try:
            on_line(msg)
        except Exception:
            pass
        # subprocess foi killed -> returncode reflete o sinal (negativo);
        # forcamos um codigo nao-zero distinguivel pra UI.
        return 124, "\n".join(tail)
    return proc.returncode, "\n".join(tail)


# ===================== Pipeline lock =====================


def acquire_pipeline_lock() -> Optional[str]:
    """Tenta adquirir lock pra rodar Update all. Retorna None em sucesso,
    string de erro se outro processo ainda esta vivo.

    Lock stale (PID morto) eh removido automaticamente — robusto contra
    crash do Streamlit no meio do pipeline.
    """
    if LOCK_PATH.exists():
        try:
            old_pid = int(LOCK_PATH.read_text().strip())
        except (OSError, ValueError):
            old_pid = None
        if old_pid is not None:
            try:
                os.kill(old_pid, 0)
                return f"Pipeline already running (PID {old_pid}). Wait or remove {LOCK_PATH.name} manually if stuck."
            except (ProcessLookupError, PermissionError):
                pass  # stale lock, prossegue
        try:
            LOCK_PATH.unlink()
        except OSError:
            pass
    try:
        LOCK_PATH.write_text(str(os.getpid()))
    except OSError as e:
        return f"Could not create lockfile {LOCK_PATH}: {e}"
    return None


def release_pipeline_lock() -> None:
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


# ===================== DVC / git state =====================


def _dvc_working_dir_clean() -> bool:
    """True se `dvc status` reporta working dir sincronizado com .dvc files.

    Quando True, podemos pular `dvc add` (re-hash caro) + commit fantasma.
    """
    venv_dvc = PROJECT_ROOT / ".venv" / "bin" / "dvc"
    if not venv_dvc.exists():
        return False
    try:
        result = subprocess.run(
            [str(venv_dvc), "status"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
            env={**_safe_env(), **_NONINTERACTIVE_ENV},
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    if result.returncode != 0:
        return False
    # `dvc status` (working) imprime "Data and pipelines are up to date." quando limpo.
    out = (result.stdout + result.stderr).lower()
    return "up to date" in out


def _git_commits_ahead() -> int:
    """Numero de commits locais nao pushed pra upstream. 0 se nada a pushar."""
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "@{u}..HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return 0
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip() or "0")
    except ValueError:
        return 0


# ===================== Publish =====================


def run_publish_streaming(
    on_line: Callable[[str], None],
    commit_msg: Optional[str] = None,
) -> tuple[int, str]:
    """Pipeline pos-captura: pre-check -> dvc add -> git add -> commit ->
    dvc push -> git push. Para no primeiro erro.

    Pre-check evita commit fantasma `chore: refresh .dvc hashes` quando
    nao ha captura nova. Se working dir DVC limpo E sem commits ahead,
    retorna (0, 'nothing to publish'). Se so ha commits ahead, faz apenas
    `dvc push` + `git push` (idempotentes).

    Imprime markers `[step/N]` pra UI parsear progresso.
    """
    venv_dvc = PROJECT_ROOT / ".venv" / "bin" / "dvc"
    if not venv_dvc.exists():
        on_line(f"ERROR: {venv_dvc} not found. Setup .venv first.")
        return 1, "dvc binary missing"

    # Pre-check: evita commit fantasma quando nada mudou
    on_line("[pre] checking dvc status + git ahead…")
    dvc_clean = _dvc_working_dir_clean()
    git_ahead = _git_commits_ahead()
    on_line(f"[pre] dvc_clean={dvc_clean} git_commits_ahead={git_ahead}")

    if dvc_clean and git_ahead == 0:
        on_line("[skip] nothing to publish (dvc + git already in sync)")
        return 0, "nothing to publish (dvc working dir clean, no commits ahead)"

    # Timeouts generosos por step. Re-hash de raw inteiro pode levar
    # tempo; upload pra gdrive idem. Sem timeout = risco de UI travada
    # pra sempre. Com timeout = falha visivel.
    T_ADD = 60 * 60       # dvc add — re-hash pode demorar
    T_GIT = 5 * 60        # git add / commit / push de .dvc files (texto pequeno)
    T_PUSH = 2 * 60 * 60  # dvc push — pode mandar GBs

    if dvc_clean:
        # Caso: previous run commitou mas push falhou. So executa pushes.
        on_line(f"[1/2] dvc push — uploading any missing blobs (idempotent)")
        rc, tail = _stream([str(venv_dvc), "push"], on_line, timeout=T_PUSH)
        if rc != 0:
            return rc, f"dvc push failed (rc={rc}):\n{tail}"
        on_line(f"[2/2] git push — {git_ahead} commits ahead")
        rc, tail = _stream(["git", "push"], on_line, timeout=T_GIT)
        if rc != 0:
            return rc, f"git push failed (rc={rc}):\n{tail}"
        return 0, f"pushed {git_ahead} commits (no new dvc add needed)"

    # Caso comum: dvc working dir mudou — pipeline completo.
    existing_dvc_paths = [p for p in DVC_PATHS if (PROJECT_ROOT / p).exists()]

    # [1/5] dvc add
    on_line(f"[1/5] dvc add — {len(existing_dvc_paths)} paths")
    rc, tail = _stream([str(venv_dvc), "add", *existing_dvc_paths], on_line, timeout=T_ADD)
    if rc != 0:
        return rc, f"dvc add failed (rc={rc}):\n{tail}"

    # [2/5] git add  — paths concretos (sem glob shell)
    dvc_files = sorted(
        list(PROJECT_ROOT.glob("data/*.dvc"))
        + list(PROJECT_ROOT.glob("data/external/*.dvc"))
    )
    gitignores = [
        p for p in (
            PROJECT_ROOT / "data" / ".gitignore",
            PROJECT_ROOT / "data" / "external" / ".gitignore",
        ) if p.exists()
    ]
    git_add_targets = [str(p.relative_to(PROJECT_ROOT)) for p in dvc_files + gitignores]
    on_line(f"[2/5] git add — {len(git_add_targets)} files")
    if git_add_targets:
        rc, tail = _stream(["git", "add", *git_add_targets], on_line, timeout=T_GIT)
        if rc != 0:
            return rc, f"git add failed (rc={rc}):\n{tail}"

    # [3/5] commit (skip if nothing staged)
    staged_check = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
    )
    if staged_check.returncode == 0:
        on_line("[3/5] commit — nothing staged, skipping")
    else:
        commit_script = Path.home() / ".claude" / "scripts" / "commit.sh"
        if not commit_script.exists():
            on_line(f"ERROR: {commit_script} not found")
            return 1, "commit.sh missing"
        msg = commit_msg or f"data: dashboard sync ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})"
        on_line(f"[3/5] commit — {msg!r}")
        rc, tail = _stream([str(commit_script), msg], on_line, timeout=T_GIT)
        if rc != 0:
            return rc, f"commit failed (rc={rc}):\n{tail}"

    # [4/5] dvc push
    on_line("[4/5] dvc push — uploading blobs to gdrive")
    rc, tail = _stream([str(venv_dvc), "push"], on_line, timeout=T_PUSH)
    if rc != 0:
        return rc, f"dvc push failed (rc={rc}):\n{tail}"

    # [5/5] git push
    on_line("[5/5] git push — pushing rev_lock")
    rc, tail = _stream(["git", "push"], on_line, timeout=T_GIT)
    if rc != 0:
        return rc, f"git push failed (rc={rc}):\n{tail}"

    return 0, "all publish steps ok"


def quarto_installed() -> bool:
    return shutil.which("quarto") is not None


def discover_qmds() -> list[Path]:
    """Lista notebooks Quarto pra renderizar (notebooks/*.qmd, excluindo
    templates `_template*.qmd`). Ordenacao: overview qmds (00-*) primeiro,
    depois per-source alfabetico."""
    notebooks_dir = PROJECT_ROOT / "notebooks"
    if not notebooks_dir.exists():
        return []
    qmds = [p for p in notebooks_dir.glob("*.qmd") if not p.name.startswith("_")]
    # 00-overview*.qmd primeiro, depois resto alfabetico
    return sorted(qmds, key=lambda p: (not p.name.startswith("00-"), p.name))


def run_quarto_streaming(
    on_line: Callable[[str], None],
    timeout_per_qmd: float = 900.0,
) -> tuple[int, str]:
    """Renderiza todos qmds em notebooks/*.qmd (exceto templates).

    Imprime markers `[i/N] rendering <name>` pra UI parsear progresso.
    Continua nos proximos qmds se um falhar; rc final reflete agregado.
    """
    if not quarto_installed():
        on_line("ERROR: quarto CLI not in PATH — `brew install quarto-cli`")
        return 1, "quarto not installed"

    qmds = discover_qmds()
    if not qmds:
        on_line("WARNING: no qmds found in notebooks/")
        return 0, "no qmds"

    quarto_python = str(PROJECT_ROOT / ".venv" / "bin" / "python")
    extra_env = {"QUARTO_PYTHON": quarto_python}

    on_line(f"Found {len(qmds)} notebooks to render")
    failures: list[str] = []
    for i, qmd in enumerate(qmds, 1):
        on_line(f"[{i}/{len(qmds)}] rendering {qmd.name}")
        rel = str(qmd.relative_to(PROJECT_ROOT))
        rc, _tail = _stream(
            ["quarto", "render", rel],
            on_line,
            timeout=timeout_per_qmd,
            extra_env=extra_env,
        )
        if rc != 0:
            failures.append(f"{qmd.name} (rc={rc})")
            on_line(f"  ❌ {qmd.name} failed (rc={rc})")
        else:
            on_line(f"  ✅ {qmd.name} ok")

    summary = f"{len(qmds) - len(failures)}/{len(qmds)} qmds rendered"
    if failures:
        return 1, f"{summary}; failures: {', '.join(failures)}"
    return 0, summary
