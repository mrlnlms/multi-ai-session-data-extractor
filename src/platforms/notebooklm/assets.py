"""Read-only NotebookLM current/historical asset backfill adapter."""

from src.platforms._asset_backfill import ProjectionEvidenceAdapter

ADAPTER = ProjectionEvidenceAdapter("notebooklm", "notebooklm_historical")
