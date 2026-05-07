"""Snapshot blob de configs/skills/commands/hooks dos 3 CLIs.

Roda como passo final do cli-copy.py. Idempotente via content-hash:
se o conjunto sanitizado nao mudou desde o ultimo snapshot, no-op.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.extractors.cli.sanitize import sanitize_claude_settings

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


# --- sanitization dispatch ---

_SANITIZERS = {
    "claude_code": {
        "settings.json": sanitize_claude_settings,
        "settings.local.json": sanitize_claude_settings,
    },
    # codex/gemini: nenhum arquivo precisa de sanitize hoje
    # (auth.json/oauth_creds/google_accounts skip via manifest)
}


def _read_content(cli: str, rel: str, abs_path: Path) -> Optional[bytes]:
    """Le arquivo, aplica sanitizer se houver. Retorna bytes ou None se skip."""
    sanitizer = _SANITIZERS.get(cli, {}).get(rel)
    if sanitizer:
        raw = abs_path.read_text(encoding="utf-8")
        sanitized = sanitizer(raw)
        if sanitized is None:
            logger.warning(f"snapshot: skipping {cli}/{rel} (sanitize failed)")
            return None
        return sanitized.encode("utf-8")
    return abs_path.read_bytes()


def _content_hash(payload: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for rel in sorted(payload.keys()):
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(payload[rel])
        h.update(b"\x00")
    return h.hexdigest()


def _read_latest_meta(cli_root: Path) -> Optional[dict]:
    if not cli_root.exists():
        return None
    dirs = sorted([p for p in cli_root.iterdir() if p.is_dir()])
    if not dirs:
        return None
    meta_file = dirs[-1] / "_meta.json"
    if not meta_file.exists():
        return None
    try:
        return json.loads(meta_file.read_text())
    except Exception:
        return None


def _resolve_snapshot_dir(cli_root: Path, content_hash: str) -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    candidate = cli_root / today
    if not candidate.exists():
        return candidate
    return cli_root / f"{today}-{content_hash[:8]}"


_CLI_DIR_NAMES = {
    "claude_code": "claude-code-config-snapshots",
    "codex": "codex-config-snapshots",
    "gemini": "gemini-config-snapshots",
}


def _snapshot_one_cli(cli: str) -> None:
    manifest = collect_files_for_snapshot(cli)
    if not manifest:
        return  # cli not installed on this machine
    payload: dict[str, bytes] = {}
    for rel, abs_path in manifest.items():
        content = _read_content(cli, rel, abs_path)
        if content is not None:
            payload[rel] = content
    if not payload:
        return

    content_hash = _content_hash(payload)
    cli_root = EXTERNAL / _CLI_DIR_NAMES[cli]

    latest = _read_latest_meta(cli_root)
    if latest and latest.get("content_hash") == content_hash:
        logger.info(f"snapshot: {cli} unchanged, skipping")
        return

    snap_dir = _resolve_snapshot_dir(cli_root, content_hash)
    snap_dir.mkdir(parents=True, exist_ok=True)
    for rel, content in payload.items():
        dst = snap_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(content)
    meta = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": content_hash,
        "cli": cli,
        "file_count": len(payload),
    }
    (snap_dir / "_meta.json").write_text(json.dumps(meta, indent=2))
    logger.info(f"snapshot: {cli} → {snap_dir.name} ({len(payload)} files)")


def snapshot_configs() -> None:
    """Snapshot dos 3 CLIs em data/external/<cli>-config-snapshots/<date>/.

    Idempotente: hash do payload sanitizado vs ultimo snapshot. Se igual, no-op.
    Roda como passo final do cli-copy.py.
    """
    for cli in ("claude_code", "codex", "gemini"):
        try:
            _snapshot_one_cli(cli)
        except Exception as e:
            logger.error(f"snapshot {cli} failed: {e}", exc_info=True)
