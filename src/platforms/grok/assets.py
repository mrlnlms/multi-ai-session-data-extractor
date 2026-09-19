"""Read-only Grok manifest/tree asset backfill adapter."""

from src.platforms._asset_backfill import ProjectionEvidenceAdapter

ADAPTER = ProjectionEvidenceAdapter("grok", "manifest_tree_web")
