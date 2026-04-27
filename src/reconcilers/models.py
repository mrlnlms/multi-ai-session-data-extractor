"""Dataclasses do reconciler."""

from dataclasses import dataclass, field


@dataclass
class Plan:
    """Plano de reconciliacao: o que fazer com cada conv_id."""
    to_use_from_current: list[str]     # IDs do raw novo (novos ou update_time mais recente)
    to_copy_from_previous: list[str]   # IDs unchanged — copia do merged anterior
    missing_from_server: list[str]     # IDs no merged anterior mas nao na discovery atual


@dataclass
class ReconcileReport:
    """Relatorio da reconciliacao."""
    added: int = 0
    updated: int = 0
    copied: int = 0
    preserved_missing: int = 0
    validation_warnings: list[str] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""

    def summary(self) -> str:
        return (
            f"Reconciliacao: added={self.added}, updated={self.updated}, "
            f"copied={self.copied}, preserved_missing={self.preserved_missing}, "
            f"warnings={len(self.validation_warnings)}"
        )
