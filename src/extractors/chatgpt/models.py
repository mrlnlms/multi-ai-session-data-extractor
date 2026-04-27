"""Dataclasses tipadas pro chatgpt extractor."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ConversationMeta:
    """Metadata leve de uma conv (vem da listagem, sem conteudo)."""
    id: str
    title: str | None
    create_time: float
    update_time: float
    project_id: str | None
    archived: bool


@dataclass
class ProjectMeta:
    """Metadata de um project do ChatGPT."""
    id: str
    name: str
    discovered_via: Literal[
        "conversation_scan",
        "projects_api",
        "gizmos_discovery",
        "dom_scrape",
        "next_data",
    ]


@dataclass
class VoiceMessage:
    """Mensagem capturada via DOM scrape (voice mode)."""
    dom_sequence: int
    role: Literal["user", "assistant"]
    text: str
    duration_seconds: int | None  # None pra assistant turns
    was_voice: bool  # False se nao tinha icone de mic (screenshot intercalado, nao voice)


@dataclass
class VoiceCapture:
    """Output do DOM voice pass pra uma conv."""
    conversation_id: str
    title: str | None
    messages: list[VoiceMessage]


@dataclass
class CaptureOptions:
    """Flags CLI do chatgpt-export.py."""
    skip_voice: bool = False
    dry_run: bool = False
    full: bool = False  # Forca brute force mesmo tendo captura anterior (sanity check)
    # NOTE: checkpoint/resume e funcionalidade declarada no spec mas NAO
    # implementada neste plano — fica pra plano futuro.


@dataclass
class CaptureReport:
    """Relatorio final da run."""
    run_started_at: str
    run_finished_at: str
    duration_seconds: float
    discovery_counts: dict[str, int] = field(default_factory=dict)
    fetch_counts: dict[str, int] = field(default_factory=dict)
    voice_pass_counts: dict[str, int] = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)

    def summary(self) -> str:
        """Resumo humano pra imprimir no fim da run."""
        return (
            f"Captura finalizada em {self.duration_seconds:.0f}s\n"
            f"  Discovery: {self.discovery_counts}\n"
            f"  Fetch: {self.fetch_counts}\n"
            f"  Voice pass: {self.voice_pass_counts}\n"
            f"  Errors: {len(self.errors)}"
        )
