"""Read-only Antigravity delivered-artifact backfill adapter."""

from src.platforms._asset_backfill import ProjectionEvidenceAdapter

ADAPTER = ProjectionEvidenceAdapter("antigravity_cli", "cli_inline")
