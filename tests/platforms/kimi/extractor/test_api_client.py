from unittest.mock import AsyncMock

import pytest

from src.platforms.kimi.extractor.api_client import KimiAPIClient


@pytest.mark.asyncio
async def test_post_reloads_session_and_retries_once_after_401():
    page = AsyncMock()
    page.evaluate.side_effect = [
        {"status": 401, "body": "expired"},
        "fresh-token",
        {"status": 200, "body": '{"chats": []}'},
    ]
    client = KimiAPIClient(AsyncMock(), page)
    client.token = "stale-token"

    assert await client.list_chats_page() == {"chats": []}
    page.reload.assert_awaited_once_with(wait_until="networkidle", timeout=60000)
    assert client.token == "fresh-token"


@pytest.mark.asyncio
async def test_post_does_not_loop_when_refreshed_session_still_returns_401():
    page = AsyncMock()
    page.evaluate.side_effect = [
        {"status": 401, "body": "expired"},
        "fresh-token",
        {"status": 401, "body": "still rejected"},
    ]
    client = KimiAPIClient(AsyncMock(), page)
    client.token = "stale-token"

    with pytest.raises(RuntimeError, match="still rejected"):
        await client.list_chats_page()
    page.reload.assert_awaited_once()
