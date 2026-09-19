"""Durable, source-agnostic storage for preserved asset records and bytes."""

from .models import (
    AssetScope,
    AssetState,
    CaptureBatch,
    RecordEnvelope,
    VerificationReport,
)
from .contracts import AssetEvidenceAdapter, ProjectionReport, SourceInputs
from .cli_incremental import CLIAssetCaptureSession, CLIAssetObservation
from .incremental import (
    AssetObservation,
    WebAssetCaptureSession,
    commit_web_asset_capture,
)
from .projection import AssetProjection, project_assets
from .reader import (
    AssetReader,
    VaultAssetReader,
    apply_asset_projection,
    combine_asset_projections,
)
from .runtime import AssetMode, AssetRuntime, load_asset_runtime, runtime_account_id
from .vault import AssetVault, AssetVaultError, AssetVaultLockedError, IntegrityError

__all__ = [
    "AssetScope",
    "AssetState",
    "AssetProjection",
    "AssetReader",
    "AssetEvidenceAdapter",
    "AssetObservation",
    "AssetVault",
    "AssetVaultError",
    "AssetVaultLockedError",
    "CLIAssetCaptureSession",
    "CLIAssetObservation",
    "CaptureBatch",
    "IntegrityError",
    "ProjectionReport",
    "RecordEnvelope",
    "VerificationReport",
    "VaultAssetReader",
    "AssetMode",
    "AssetRuntime",
    "load_asset_runtime",
    "runtime_account_id",
    "WebAssetCaptureSession",
    "SourceInputs",
    "commit_web_asset_capture",
    "apply_asset_projection",
    "combine_asset_projections",
    "project_assets",
]
