"""Read-only Claude.ai manifest/tree asset backfill adapter."""

from src.platforms._asset_backfill import ProjectionEvidenceAdapter

ADAPTER = ProjectionEvidenceAdapter("claude_ai", "manifest_tree_web")
