"""Read-only Gemini manifest/tree asset backfill adapter."""

from src.platforms._asset_backfill import ProjectionEvidenceAdapter

ADAPTER = ProjectionEvidenceAdapter("gemini", "manifest_tree_web")
