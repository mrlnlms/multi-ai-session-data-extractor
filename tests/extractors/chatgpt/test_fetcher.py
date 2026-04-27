"""Testes do fetcher — iteracao + progresso + batch."""

import pytest

from src.extractors.chatgpt.fetcher import fetch_all


@pytest.fixture(autouse=True)
def _patch_sleep(mocker):
    """Patch asyncio.sleep no fetcher pra testes nao dormirem 3s."""
    mocker.patch("src.extractors.chatgpt.fetcher.asyncio.sleep", new_callable=mocker.AsyncMock)


async def test_fetch_all_small_batch(mocker):
    """Lista pequena de IDs — single request via batch."""
    mock_client = mocker.AsyncMock()
    mock_client.fetch_conversations_batch.return_value = [
        {"id": "a", "title": "A", "mapping": {}},
        {"id": "b", "title": "B", "mapping": {}},
    ]
    results = await fetch_all(mock_client, ["a", "b"])
    assert set(results.keys()) == {"a", "b"}
    mock_client.fetch_conversations_batch.assert_called_once_with(["a", "b"])


async def test_fetch_all_splits_into_batches_of_10(mocker):
    """25 IDs viram 3 batches: 10, 10, 5."""
    mock_client = mocker.AsyncMock()
    mock_client.fetch_conversations_batch.side_effect = [
        [{"id": f"c-{i}", "mapping": {}} for i in range(10)],
        [{"id": f"c-{i}", "mapping": {}} for i in range(10, 20)],
        [{"id": f"c-{i}", "mapping": {}} for i in range(20, 25)],
    ]
    ids = [f"c-{i}" for i in range(25)]
    results = await fetch_all(mock_client, ids)
    assert len(results) == 25
    assert mock_client.fetch_conversations_batch.call_count == 3


async def test_fetch_all_calls_on_progress(mocker):
    """Callback de progresso chamado a cada batch."""
    mock_client = mocker.AsyncMock()
    mock_client.fetch_conversations_batch.return_value = [{"id": "a", "mapping": {}}]
    progress_calls = []
    await fetch_all(mock_client, ["a"], on_progress=lambda n, total: progress_calls.append((n, total)))
    assert progress_calls == [(1, 1)]
