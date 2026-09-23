import asyncio
from unittest.mock import AsyncMock

from src.platforms.gemini.extractor import api_client


def test_list_instructions_preserves_native_response(monkeypatch):
    native = [[[
        "native-instruction-id",
        "synthetic instruction",
        [1_700_000_000, 123],
        None,
        [1_700_000_100, 456],
        None,
        None,
        None,
        None,
        1,
        2,
    ]], "page-token"]
    call_rpc = AsyncMock(return_value=native)
    monkeypatch.setattr(api_client, "call_rpc", call_rpc)
    client = api_client.GeminiAPIClient(context=object(), session={"at": "token"})

    result = asyncio.run(client.list_instructions())

    assert result == native
    call_rpc.assert_awaited_once_with(
        client.context,
        client.session,
        "ZKcapf",
        [100],
        reqid=1,
    )


def test_list_instructions_normalizes_missing_response(monkeypatch):
    monkeypatch.setattr(api_client, "call_rpc", AsyncMock(return_value=None))
    client = api_client.GeminiAPIClient(context=object(), session={"at": "token"})

    assert asyncio.run(client.list_instructions()) == []
