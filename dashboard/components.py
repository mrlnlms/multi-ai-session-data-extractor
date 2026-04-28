"""Componentes visuais reutilizaveis."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

STATUS_BADGES: dict[str, str] = {
    "green": "🟢",
    "yellow": "🟡",
    "red": "🔴",
    "gray": "⚫",
}

STATUS_LABEL: dict[str, str] = {
    "green": "OK",
    "yellow": "atencao",
    "red": "atrasado",
    "gray": "nunca rodou",
}


def status_badge(status: str) -> str:
    return f"{STATUS_BADGES.get(status, '⚪')} {STATUS_LABEL.get(status, status)}"


def relative_time(when: Optional[datetime], now: Optional[datetime] = None) -> str:
    if when is None:
        return "—"
    now = now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delta = now - when
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "agora"
    if seconds < 60:
        return f"{seconds}s atras"
    if seconds < 3600:
        return f"{seconds // 60}min atras"
    if seconds < 86400:
        return f"{seconds // 3600}h atras"
    days = seconds // 86400
    if days < 60:
        return f"{days}d atras"
    months = days // 30
    if months < 24:
        return f"{months}mes atras"
    return f"{days // 365}a atras"


def format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_datetime(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")
