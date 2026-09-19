"""Read-only Perplexity manifest/tree asset backfill adapter."""

from src.platforms._asset_backfill import ProjectionEvidenceAdapter

ADAPTER = ProjectionEvidenceAdapter("perplexity", "manifest_tree_web")
