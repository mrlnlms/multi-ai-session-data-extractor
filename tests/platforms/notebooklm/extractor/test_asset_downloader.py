from src.platforms.notebooklm.extractor.asset_downloader import _extract_audio_overviews


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
