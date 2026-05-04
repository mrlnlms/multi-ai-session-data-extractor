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
    "yellow": "warning",
    "red": "overdue",
    "gray": "never ran",
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
        return "now"
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}min ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    days = seconds // 86400
    if days < 60:
        return f"{days}d ago"
    months = days // 30
    if months < 24:
        return f"{months}mo ago"
    return f"{days // 365}y ago"


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
