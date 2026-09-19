from __future__ import annotations

import base64
import importlib
import inspect
import json

import pytest

from src.assets.models import AssetScope
from src.assets.incremental import AssetObservation, WebAssetCaptureSession
from src.assets.vault import AssetVault
from src.platforms.grok.extractor.asset_downloader import download_assets


WEB_SOURCES = (
    "chatgpt",
    "claude_ai",
    "gemini",
    "notebooklm",
    "qwen",
    "deepseek",
    "perplexity",
    "grok",
    "kimi",
)

DOWNLOADER_MODULES = (
    "src.platforms.chatgpt.extractor.asset_downloader",
    "src.platforms.claude_ai.extractor.asset_downloader",
    "src.platforms.gemini.extractor.asset_downloader",
    "src.platforms.notebooklm.extractor.asset_downloader",
    "src.platforms.qwen.extractor.asset_downloader",
    "src.platforms.deepseek.extractor.asset_downloader",
    "src.platforms.perplexity.extractor.asset_downloader",
    "src.platforms.perplexity.extractor.artifact_downloader",
    "src.platforms.grok.extractor.asset_downloader",
    "src.platforms.kimi.extractor.asset_downloader",
)


@pytest.mark.parametrize("source", WEB_SOURCES)
def test_web_sync_keeps_asset_vault_an_explicit_opt_in(source):
    module = importlib.import_module(f"src.platforms.{source}.commands.sync")
    parameter = inspect.signature(module.main).parameters["asset_vault"]

    assert parameter.default is None


@pytest.mark.parametrize("module_name", DOWNLOADER_MODULES)
def test_web_downloaders_accept_explicit_asset_vault(module_name):
    module = importlib.import_module(module_name)
    function_name = "download_artifacts" if module_name.endswith("artifact_downloader") else (
        "run_asset_download" if ".chatgpt." in module_name else "download_assets"
    )
    parameter = inspect.signature(getattr(module, function_name)).parameters["asset_vault"]

    assert parameter.default is None
    assert "WebAssetCaptureSession" in inspect.getsource(module)


@pytest.mark.parametrize("source", WEB_SOURCES)
def test_each_web_source_writes_an_isolated_temporary_scope(tmp_path, source):
    vault = AssetVault(tmp_path / "vault", runtime_root=tmp_path / "runtime")
    session = WebAssetCaptureSession(
        vault,
        source=source,
        account_id="account-one",
        evidence_path=tmp_path / source,
        capture_method="captured_response_fixture",
        max_batch_bytes=16,
    )
    session.observe(
        AssetObservation(
            delivery_id=f"{source}-asset",
            object_id=f"{source}-asset",
            representation_kind="delivery",
            payload=source.encode(),
        )
    )
    session.finish(complete_discovery=True)

    state = vault.load_state(AssetScope(source, "account-one"))
    assert len(state.by_type["delivery"]) == 1
    assert vault.verify(state.scope).blob_count == 1


class _FakePage:
    async def goto(self, *args, **kwargs):
        return None

    async def wait_for_timeout(self, *args, **kwargs):
        return None

    async def evaluate(self, script, url):
        return base64.b64encode(b"captured response bytes").decode()


class _FakeContext:
    async def new_page(self):
        return _FakePage()


@pytest.mark.asyncio
async def test_grok_captured_response_writes_legacy_and_committed_vault(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "assets.json").write_text(
        json.dumps(
            [
                {
                    "assetId": "asset-native-1",
                    "key": "users/u/asset-native-1/content",
                    "mimeType": "image/png",
                    "fileName": "capture.png",
                }
            ]
        ),
        encoding="utf-8",
    )
    vault = AssetVault(tmp_path / "vault", runtime_root=tmp_path / "runtime")

    stats = await download_assets(
        _FakeContext(),
        raw_dir,
        asset_vault=vault,
        account_id="account-one",
        complete_discovery=True,
    )

    legacy = raw_dir / "assets" / "asset-native-1.png"
    assert stats["downloaded"] == 1
    assert legacy.read_bytes() == b"captured response bytes"
    state = vault.load_state(AssetScope("grok", "account-one"))
    assert state.committed_captures
    assert state.by_type["delivery"][0].payload["delivery_id"] == "asset-native-1"
    assert state.by_type["observation"][0].payload["status"] == "available"
    assert vault.verify(state.scope).blob_count == 1
