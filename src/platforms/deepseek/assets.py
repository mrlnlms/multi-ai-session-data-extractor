"""Read-only DeepSeek manifest/tree asset backfill adapter."""

from src.platforms._asset_backfill import ProjectionEvidenceAdapter

ADAPTER = ProjectionEvidenceAdapter("deepseek", "manifest_tree_web")
