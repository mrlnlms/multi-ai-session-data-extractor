# src/extractors/cli/sanitize.py
"""Sanitiza arquivos de config dos CLIs antes de gravar em data/external/.

Cada funcao recebe content bruto (str), retorna content sanitizado (str)
ou None se nao conseguir parsear (caller ignora arquivo).
"""

from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_REDACT_KEY_PATTERNS = ("KEY", "SECRET", "TOKEN", "PASSWORD")


def _is_secret_key(name: str) -> bool:
    upper = name.upper()
    return any(p in upper for p in _REDACT_KEY_PATTERNS)


def _redact_env_dict(env: dict) -> dict:
    return {
        k: ("<redacted>" if _is_secret_key(k) else v)
        for k, v in env.items()
    }


def sanitize_claude_settings(raw: str) -> Optional[str]:
    """Redact chaves secretas (KEY/SECRET/TOKEN/PASSWORD) em env e mcpServers[*].env."""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"sanitize_claude_settings: invalid json — skipping ({e})")
        return None

    if "env" in obj and isinstance(obj["env"], dict):
        obj["env"] = _redact_env_dict(obj["env"])

    if "mcpServers" in obj and isinstance(obj["mcpServers"], dict):
        for _, server_cfg in obj["mcpServers"].items():
            if isinstance(server_cfg, dict) and isinstance(server_cfg.get("env"), dict):
                server_cfg["env"] = _redact_env_dict(server_cfg["env"])

    return json.dumps(obj, indent=2, ensure_ascii=False)
