"""Snapshot blob de configs/skills/commands/hooks dos 3 CLIs.

Roda como passo final do cli-copy.py. Idempotente via content-hash:
se o conjunto sanitizado nao mudou desde o ultimo snapshot, no-op.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXTERNAL = PROJECT_ROOT / "data" / "external"


# --- file manifest per CLI ---

def _walk_dir(base: Path, prefix: str) -> dict[str, Path]:
    """Walk base recursively, return {relative_str: absolute_path}."""
    out: dict[str, Path] = {}
    if not base.exists():
        return out
    for p in base.rglob("*"):
        if p.is_file():
            rel = f"{prefix}/{p.relative_to(base)}" if prefix else str(p.relative_to(base))
            out[rel] = p
    return out


def _claude_code_manifest() -> dict[str, Path]:
    home = Path.home() / ".claude"
    out: dict[str, Path] = {}
    for fname in ("CLAUDE.md", "settings.json", "settings.local.json", "statusline-command.sh"):
        f = home / fname
        if f.exists():
            out[fname] = f
    for sub in ("skills", "commands", "hooks", "plugins"):
        out.update(_walk_dir(home / sub, sub))
    return out


def _codex_manifest() -> dict[str, Path]:
    home = Path.home() / ".codex"
    out: dict[str, Path] = {}
    for fname in ("config.toml", "version.json", "installation_id", "models_cache.json", ".codex-global-state.json"):
        f = home / fname
        if f.exists():
            out[fname] = f
    for sub in ("rules", "skills", "plugins"):
        out.update(_walk_dir(home / sub, sub))
    return out


def _gemini_manifest() -> dict[str, Path]:
    home = Path.home() / ".gemini"
    out: dict[str, Path] = {}
    for fname in ("settings.json", "projects.json", "state.json", "trustedFolders.json", "installation_id"):
        f = home / fname
        if f.exists():
            out[fname] = f
    return out


_MANIFESTS = {
    "claude_code": _claude_code_manifest,
    "codex": _codex_manifest,
    "gemini": _gemini_manifest,
}


def collect_files_for_snapshot(cli: str) -> dict[str, Path]:
    """Retorna {relative_path: absolute_path} dos arquivos a snapshotar."""
    if cli not in _MANIFESTS:
        raise ValueError(f"unknown cli '{cli}'. valid: {list(_MANIFESTS)}")
    return _MANIFESTS[cli]()
