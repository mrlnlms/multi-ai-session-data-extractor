"""Testes do ChatGPTAPIClient."""

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.extractors.chatgpt.api_client import ChatGPTAPIClient
from tests.extractors.chatgpt.conftest import load_fixture


async def test_request_simple_get_200(mock_request_context, mock_api_response):
    mock_request_context.get.return_value = mock_api_response(
        status=200, json_data={"ok": True}
    )
    client = ChatGPTAPIClient(mock_request_context)
    result = await client._request_with_retry("GET", "https://example.com/foo")
    assert result == {"ok": True}
    mock_request_context.get.assert_called_once()


async def test_request_429_retries_with_wait(mock_request_context, mock_api_response, mocker):
    """Apos 429, aguarda RATE_LIMIT_WAIT_SECONDS e retry."""
    # Primeiro call: 429. Segundo call: 200.
    mock_request_context.get.side_effect = [
        mock_api_response(status=429),
        mock_api_response(status=200, json_data={"ok": True}),
    ]
    mock_sleep = mocker.patch("src.extractors.chatgpt.api_client.asyncio.sleep", new_callable=mocker.AsyncMock)

    client = ChatGPTAPIClient(mock_request_context)
    result = await client._request_with_retry("GET", "https://example.com/foo")

    assert result == {"ok": True}
    assert mock_request_context.get.call_count == 2
    mock_sleep.assert_called_once_with(30)  # RATE_LIMIT_WAIT_SECONDS


async def test_request_401_raises_session_expired(mock_request_context, mock_api_response):
    """401 levanta RuntimeError instruindo re-login."""
    mock_request_context.get.return_value = mock_api_response(status=401, ok=False)
    client = ChatGPTAPIClient(mock_request_context)
    with pytest.raises(RuntimeError, match="Sessao ChatGPT expirou"):
        await client._request_with_retry("GET", "https://example.com/foo")


async def test_request_429_gives_up_after_max_retries(mock_request_context, mock_api_response, mocker):
    """Apos MAX_RETRIES_429, raise."""
    mock_request_context.get.return_value = mock_api_response(status=429, ok=False)
    mocker.patch("src.extractors.chatgpt.api_client.asyncio.sleep", new_callable=mocker.AsyncMock)

    client = ChatGPTAPIClient(mock_request_context)
    with pytest.raises(RuntimeError, match="Rate limit persistente"):
        await client._request_with_retry("GET", "https://example.com/foo")


async def test_auth_timeout_fails_with_actionable_error(mock_request_context, mocker):
    # The suite normally bypasses the token endpoint; restore the real method
    # here to cover the timeout at the actual first network boundary.
    mocker.stopall()
    mock_request_context.get.side_effect = PlaywrightTimeoutError("timed out")
    client = ChatGPTAPIClient(mock_request_context)

    with pytest.raises(RuntimeError, match="Timeout apos"):
        await client._get_token()


async def test_page_backed_client_uses_browser_fetch(mock_request_context, mocker):
    mocker.stopall()
    mock_page = mocker.AsyncMock()
    mock_page.evaluate.side_effect = [
        {"status": 200, "ok": True, "text": '{"accessToken": "page-token"}'},
        {"status": 200, "ok": True, "text": '{"ok": true}'},
    ]
    client = ChatGPTAPIClient(mock_request_context, page=mock_page)

    result = await client._request_with_retry("GET", "https://example.com/foo")

    assert result == {"ok": True}
    assert mock_page.evaluate.await_count == 2
    mock_request_context.get.assert_not_called()

async def test_list_conversations_returns_metas(mock_request_context, mock_api_response):
    """list_conversations retorna lista de ConversationMeta do fixture."""
    mock_request_context.get.return_value = mock_api_response(
        status=200,
        json_data=load_fixture("conversations_page_1"),
    )
    client = ChatGPTAPIClient(mock_request_context)
    metas = await client.list_conversations(offset=0, limit=100)

    assert len(metas) == 2
    assert metas[0].id == "abc-conv-1"
    assert metas[0].title == "Primeira conversa"
    assert metas[0].archived is False
    assert metas[0].project_id is None
    assert metas[1].project_id == "g-p-xyz"
    assert mock_request_context.get.call_args.kwargs["params"] == {
        "offset": 0,
        "limit": 100,
        "order": "updated",
        "is_archived": "false",
        "is_starred": "false",
        "hide_snorlax": "true",
    }


async def test_fetch_conversation_returns_full_raw(mock_request_context, mock_api_response):
    """fetch_conversation retorna dict cru com mapping tree completa."""
    fixture = load_fixture("conversation_simple")
    mock_request_context.get.return_value = mock_api_response(
        status=200, json_data=fixture
    )
    client = ChatGPTAPIClient(mock_request_context)
    raw = await client.fetch_conversation("conv-simple-id")

    assert "mapping" in raw
    assert len(raw["mapping"]) == 3  # root + 2 msgs
    assert raw["title"] == "Test conv"
    mock_request_context.get.assert_called_with(
        "https://chatgpt.com/backend-api/conversation/conv-simple-id",
        params=None,
        headers={"Authorization": "Bearer test-token"},
        timeout=60_000,
    )


async def test_batch_truncation_triggers_single_refetch(mock_request_context, mock_api_response):
    """Batch retorna conv com node_count>0 mas 0 msgs. Re-fetch via single."""
    batch_response = load_fixture("batch_truncated")
    single_response = load_fixture("batch_complete")

    mock_request_context.post.return_value = mock_api_response(
        status=200, json_data=batch_response
    )
    mock_request_context.get.return_value = mock_api_response(
        status=200, json_data=single_response
    )

    client = ChatGPTAPIClient(mock_request_context)
    raws = await client.fetch_conversations_batch(["conv-truncated"])

    assert len(raws) == 1
    # A que voltou foi a single (completa), nao a truncada
    assert len(raws[0]["mapping"]) == 2  # agora tem root+m1, nao so root
    assert raws[0].get("_truncation_recovered") is True


async def test_batch_healthy_no_refetch(mock_request_context, mock_api_response):
    """Batch saudavel — nao chama single endpoint."""
    batch_healthy = {
        "conversations": [
            {
                "id": "conv-ok",
                "title": "Ok",
                "_mapping_node_count": 3,
                "mapping": {
                    "root": {"id": "root", "parent": None, "children": ["m1"]},
                    "m1": {"id": "m1", "parent": "root", "children": ["m2"], "message": {"id": "m1"}},
                    "m2": {"id": "m2", "parent": "m1", "children": [], "message": {"id": "m2"}},
                },
            }
        ]
    }
    mock_request_context.post.return_value = mock_api_response(
        status=200, json_data=batch_healthy
    )
    client = ChatGPTAPIClient(mock_request_context)
    raws = await client.fetch_conversations_batch(["conv-ok"])

    assert len(raws) == 1
    assert raws[0]["_truncation_recovered"] is False
    mock_request_context.get.assert_not_called()


async def test_list_archived(mock_request_context, mock_api_response):
    mock_request_context.get.return_value = mock_api_response(
        status=200,
        json_data={"items": [
            {"id": "arch-1", "title": "Old", "create_time": 1.0, "update_time": 2.0,
             "gizmo_id": None, "is_archived": True}
        ]}
    )
    client = ChatGPTAPIClient(mock_request_context)
    metas = await client.list_archived(offset=0, limit=100)
    assert len(metas) == 1
    assert metas[0].archived is True
    mock_request_context.get.assert_called_with(
        "https://chatgpt.com/backend-api/conversations",
        params={
            "offset": 0,
            "limit": 100,
            "order": "updated",
            "is_archived": "true",
            "is_starred": "false",
            "hide_snorlax": "true",
        },
        headers={"Authorization": "Bearer test-token"},
        timeout=60_000,
    )


async def test_fetch_memories(mock_request_context, mock_api_response):
    mock_request_context.get.return_value = mock_api_response(
        status=200,
        json_data={"memories": [{"content": "fact 1"}, {"content": "fact 2"}]}
    )
    client = ChatGPTAPIClient(mock_request_context)
    memories = await client.fetch_memories()
    assert "fact 1" in memories
    assert "fact 2" in memories


async def test_fetch_instructions(mock_request_context, mock_api_response):
    mock_request_context.get.return_value = mock_api_response(
        status=200,
        json_data={"about_user_message": "I'm a researcher", "about_model_message": "Be concise"}
    )
    client = ChatGPTAPIClient(mock_request_context)
    instructions = await client.fetch_instructions()
    assert instructions["about_user_message"] == "I'm a researcher"


async def test_list_projects_via_api_success(mock_request_context, mock_api_response):
    """O indice atual da sidebar fornece projetos sem depender do DOM."""
    mock_request_context.get.return_value = mock_api_response(
        status=200,
        json_data={
            "items": [{"gizmo": {"id": "g-p-1", "display": {"name": "Studies"}}}],
            "cursor": None,
        },
    )
    client = ChatGPTAPIClient(mock_request_context)
    projects = await client.list_projects()
    assert len(projects) == 1
    assert projects[0].id == "g-p-1"
    assert projects[0].discovered_via == "snorlax_sidebar"


async def test_list_projects_snorlax_paginates(mock_request_context, mock_api_response):
    mock_request_context.get.side_effect = [
        mock_api_response(status=200, json_data={
            "items": [{"gizmo": {"id": "g-p-1", "display": {"name": "One"}}}],
            "cursor": "next-page",
        }),
        mock_api_response(status=200, json_data={
            "items": [{"gizmo": {"id": "g-p-2", "display": {"name": "Two"}}}],
            "cursor": None,
        }),
    ]
    client = ChatGPTAPIClient(mock_request_context)

    projects = await client.list_projects()

    assert [project.id for project in projects] == ["g-p-1", "g-p-2"]
    assert mock_request_context.get.call_count == 2
    assert mock_request_context.get.call_args_list[1].kwargs["params"] == {"cursor": "next-page"}


async def test_list_projects_404_fallback_to_gizmos(mock_request_context, mock_api_response):
    """Se o indice atual e /projects falham, tenta o legado gizmos/discovery."""
    mock_request_context.get.side_effect = [
        mock_api_response(status=404, ok=False),  # /gizmos/snorlax/sidebar
        mock_api_response(status=404, ok=False),  # /projects
        mock_api_response(status=200, json_data={"items": [{"resource": {"gizmo": {"id": "g-p-2", "display": {"name": "Work"}}}}]}),  # /gizmos/discovery/mine
    ]
    client = ChatGPTAPIClient(mock_request_context)
    projects = await client.list_projects()
    assert len(projects) == 1
    assert projects[0].id == "g-p-2"
    assert projects[0].discovered_via == "gizmos_discovery"


async def test_list_projects_both_404_returns_empty(mock_request_context, mock_api_response):
    """Se todos os indices falham, caller pode usar o fallback DOM."""
    mock_request_context.get.side_effect = [
        mock_api_response(status=404, ok=False),
        mock_api_response(status=404, ok=False),
        mock_api_response(status=404, ok=False),
    ]
    client = ChatGPTAPIClient(mock_request_context)
    projects = await client.list_projects()
    assert projects == []


async def test_list_projects_405_uses_dom_fallback(mock_request_context, mock_api_response):
    """Mudanca atual do backend: endpoints legados podem responder 405."""
    mock_request_context.get.side_effect = [
        mock_api_response(status=405, ok=False),
        mock_api_response(status=405, ok=False),
        mock_api_response(status=405, ok=False),
    ]
    client = ChatGPTAPIClient(mock_request_context)

    projects = await client.list_projects()

    assert projects == []


async def test_list_project_conversations(mock_request_context, mock_api_response):
    """list_project_conversations retorna tupla (metas, next_cursor)."""
    mock_request_context.get.return_value = mock_api_response(
        status=200,
        json_data={
            "items": [
                {"id": "pc-1", "title": "P1", "create_time": 1.0, "update_time": 2.0,
                 "gizmo_id": "g-p-abc", "is_archived": False}
            ],
            "cursor": 42,  # next page cursor
        }
    )
    client = ChatGPTAPIClient(mock_request_context)
    metas, next_cursor = await client.list_project_conversations("g-p-abc", cursor=None)
    assert len(metas) == 1
    assert metas[0].project_id == "g-p-abc"
    assert next_cursor == 42


async def test_list_project_conversations_pagination_end(mock_request_context, mock_api_response):
    """Cursor None no response → termina paginacao."""
    mock_request_context.get.return_value = mock_api_response(
        status=200,
        json_data={
            "items": [],
            "cursor": None,
        }
    )
    client = ChatGPTAPIClient(mock_request_context)
    metas, next_cursor = await client.list_project_conversations("g-p-abc", cursor=5)
    assert metas == []
    assert next_cursor is None
