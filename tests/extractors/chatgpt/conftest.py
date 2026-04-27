"""Fixtures pytest compartilhadas pra testes de src/extractors/chatgpt/."""

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict | list:
    """Carrega fixture JSON por nome (sem extensao)."""
    path = FIXTURES_DIR / f"{name}.json"
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def mock_api_response(mocker):
    """Factory que cria mock response Playwright-like.

    Uso:
        response = mock_api_response(status=200, json_data={"items": []})
        mock_context.get.return_value = response
    """
    def _make(status: int = 200, json_data: dict | list | None = None, ok: bool | None = None):
        resp = mocker.AsyncMock()
        resp.status = status
        resp.ok = ok if ok is not None else (200 <= status < 300)
        if json_data is not None:
            resp.json = mocker.AsyncMock(return_value=json_data)
        return resp
    return _make


@pytest.fixture
def mock_request_context(mocker):
    """Mock de playwright.async_api.APIRequestContext."""
    ctx = mocker.AsyncMock()
    return ctx


@pytest.fixture(autouse=True)
def _patch_token(mocker):
    """Patcha ChatGPTAPIClient._get_token pra pular o token endpoint em testes.

    Sem isso, todo teste precisaria mockar /api/auth/session antes da chamada
    real. O token em si nao e testado aqui — so que os requests levam ele.
    """
    mocker.patch(
        "src.extractors.chatgpt.api_client.ChatGPTAPIClient._get_token",
        new_callable=mocker.AsyncMock,
        return_value="test-token",
    )
