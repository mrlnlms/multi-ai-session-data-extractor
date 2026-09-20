from __future__ import annotations

import hashlib
import importlib
import inspect

from src.assets.models import AssetScope, CaptureBatch, RecordEnvelope
from src.assets.projection import AssetProjection
from src.assets.reader import (
    VaultAssetReader,
    apply_asset_projection,
    combine_asset_projections,
)
from src.assets.vault import AssetVault
from src.schema.models import Message


ACCOUNT_ID = "11111111-1111-4111-8111-111111111111"

PARSERS = {
    "chatgpt": "ChatGPTParser",
    "claude_ai": "ClaudeAIParser",
    "gemini": "GeminiParser",
    "notebooklm": "NotebookLMParser",
    "qwen": "QwenParser",
    "deepseek": "DeepSeekParser",
    "perplexity": "PerplexityParser",
    "grok": "GrokParser",
    "kimi": "KimiParser",
    "claude_code": "ClaudeCodeParser",
    "codex": "CodexParser",
    "gemini_cli": "GeminiCLIParser",
    "antigravity_cli": "AntigravityCLIParser",
}

RECONCILERS = (
    "claude_ai", "gemini", "notebooklm", "qwen", "deepseek", "perplexity",
    "grok", "kimi",
)


def _record(record_type, capture_id, **payload):
    return RecordEnvelope(record_type, 1, capture_id, True, payload)


def test_all_parsers_and_binary_reconcilers_require_explicit_reader_injection():
    for source, class_name in PARSERS.items():
        parser = getattr(importlib.import_module(f"src.platforms.{source}.parser"), class_name)
        parameter = inspect.signature(parser).parameters["asset_reader"]
        assert parameter.default is None

    for source in RECONCILERS:
        reconcile = importlib.import_module(
            f"src.platforms.{source}.reconciler"
        ).run_reconciliation
        parameters = inspect.signature(reconcile).parameters
        assert parameters["asset_reader"].default is None
        assert parameters["asset_account_id"].default is None


def test_vault_reader_projects_only_the_explicit_scope(tmp_path):
    payload = b"reader payload"
    digest = hashlib.sha256(payload).hexdigest()
    vault = AssetVault(tmp_path / "data" / "assets", runtime_root=tmp_path / "runtime")
    capture_id = "capture-1"
    scope = AssetScope("gemini", ACCOUNT_ID)
    records = (
        _record("capture", capture_id, captured_at="2026-09-17T12:00:00Z"),
        _record(
            "delivery", capture_id, delivery_id="asset-1", object_id="native-1",
            representation_kind="user_attachment", file_name="one.bin",
            mime_type="application/octet-stream", size_bytes=len(payload), sha256=digest,
            availability="available",
        ),
        _record(
            "appearance", capture_id, appearance_id="appearance-1",
            delivery_id="asset-1", object_type="message", object_id="message-1",
            conversation_id="conversation-1", message_id="message-1", project_id=None,
            role="input", ordinal=0, content_block_index=2, position_confidence="exact",
        ),
        _record("blob", capture_id, sha256=digest, size_bytes=len(payload)),
        _record(
            "observation", capture_id, observation_id="observation-1",
            delivery_id="asset-1", status="available",
        ),
    )
    vault.commit(CaptureBatch(scope, capture_id, records, {digest: payload}))

    projection = VaultAssetReader(vault, tmp_path / "data").projection_for(
        "gemini", ACCOUNT_ID
    )

    assert [asset.asset_id for asset in projection.assets] == ["asset-1"]
    assert [link.message_id for link in projection.links] == ["message-1"]
    assert projection.message_paths["message-1"] == (
        f"assets/blobs/sha256/{digest[:2]}/{digest}",
    )


def test_apply_asset_projection_clears_legacy_paths_not_in_reader(tmp_path):
    vault = AssetVault(tmp_path / "data" / "assets", runtime_root=tmp_path / "runtime")
    projection = VaultAssetReader(vault, tmp_path / "data").projection_for(
        "gemini_cli", None
    )
    message = Message(
        message_id="message-1", conversation_id="conversation-1", source="gemini_cli",
        sequence=1, role="user", content="hello", model=None, created_at=None,
        asset_paths=["raw/legacy.bin"],
    )

    apply_asset_projection([message], projection)

    assert message.asset_paths is None


def test_combined_scopes_do_not_repeat_the_same_message_path():
    class Reader:
        def projection_for(self, source, account_id):
            return AssetProjection((), (), {"message-1": ("assets/shared.bin",)})

    projection = combine_asset_projections(
        Reader(), "chatgpt", (ACCOUNT_ID, "22222222-2222-4222-8222-222222222222")
    )

    assert projection.message_paths == {"message-1": ("assets/shared.bin",)}


def test_combined_projection_preserves_repeated_positions_within_one_scope():
    class Reader:
        def projection_for(self, source, account_id):
            return AssetProjection(
                (), (), {"message-1": ("assets/shared.bin", "assets/shared.bin")}
            )

    projection = combine_asset_projections(Reader(), "chatgpt", (ACCOUNT_ID,))

    assert projection.message_paths == {
        "message-1": ("assets/shared.bin", "assets/shared.bin")
    }
