"""Read-only ChatGPT asset backfill adapter."""

from src.platforms._asset_backfill import ProjectionEvidenceAdapter

ADAPTER = ProjectionEvidenceAdapter("chatgpt", "chatgpt")
