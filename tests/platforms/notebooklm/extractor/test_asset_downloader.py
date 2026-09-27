import asyncio
import json

from src.assets.incremental import _known_deliveries
from src.assets.models import AssetScope
from src.assets.vault import AssetVault
from src.platforms.notebooklm.extractor.asset_downloader import (
    _extract_audio_overviews,
    fetch_text_artifacts,
)


def test_audio_extraction_preserves_comma_bearing_media_suffix():
    url = "https://lh3.googleusercontent.com/notebooklm/token=mm,140"
    artifact = ["audio-id", "Overview", 1, None, None, None, [None, None, url]]

    assert _extract_audio_overviews([[artifact]]) == [
        {
            "id": "audio-id",
            "title": "Overview",
            "type": 1,
            "url": url,
        }
    ]


def test_changed_text_artifact_preserves_both_vault_versions(tmp_path):
    account_id = "00000000-0000-4000-8000-000000000001"
    raw_dir = tmp_path / "raw"
    nb_dir = raw_dir / "notebooks"
    nb_dir.mkdir(parents=True)
    (nb_dir / "nb-1.json").write_text(json.dumps({
        "uuid": "nb-1",
        "audios": [[["art-1", "example", 4, None, None]]],
    }))
    vault = AssetVault(tmp_path / "vault")
    scope = AssetScope("notebooklm", account_id)

    class Client:
        content = ["first"]

        async def fetch_artifact(self, _nb_uuid, _art_id):
            return self.content

    client = Client()
    asyncio.run(fetch_text_artifacts(client, raw_dir, asset_vault=vault, account_id=account_id))
    first = _known_deliveries(vault, scope)["text-artifact:art-1"]
    first_digest = first["sha256"]

    client.content = ["revised"]
    asyncio.run(fetch_text_artifacts(client, raw_dir, asset_vault=vault, account_id=account_id))
    known = _known_deliveries(vault, scope)
    assert known["text-artifact:art-1"]["sha256"] == first_digest
    revised_id = next(key for key in known if key.startswith("text-artifact:art-1:sha256:"))
    assert known[revised_id]["sha256"] != first_digest
    assert vault.blob_path(first_digest).is_file()
    assert vault.blob_path(known[revised_id]["sha256"]).is_file()

    asyncio.run(fetch_text_artifacts(client, raw_dir, asset_vault=vault, account_id=account_id))
    assert set(_known_deliveries(vault, scope)) == {"text-artifact:art-1", revised_id}
