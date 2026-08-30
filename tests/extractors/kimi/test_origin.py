from src.extractors.kimi.api_client import HOME_URL as API_HOME_URL
from src.extractors.kimi.asset_downloader import HOME_URL as ASSET_HOME_URL
from src.extractors.kimi.auth import HOME_URL as AUTH_HOME_URL


def test_kimi_runtime_uses_current_public_origin():
    assert {AUTH_HOME_URL, API_HOME_URL, ASSET_HOME_URL} == {"https://kimi.ai/"}
