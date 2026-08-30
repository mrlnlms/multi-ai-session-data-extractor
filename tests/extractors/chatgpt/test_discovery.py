"""Testes de discovery.py — orquestracao completa de descoberta de IDs."""

import pytest

from src.extractors.chatgpt.discovery import (
    _expand_projects_section,
    _project_meta_from_home_url,
    discover_all,
)
from src.extractors.chatgpt.models import ConversationMeta, ProjectMeta


async def test_expand_projects_section_clicks_current_show_more(mocker):
    page = mocker.Mock()
    trigger = mocker.Mock()
    trigger.count = mocker.AsyncMock(return_value=1)
    trigger.first = mocker.AsyncMock()
    project_buttons = mocker.Mock()
    project_buttons.count = mocker.AsyncMock(
        side_effect=[20, 40, 49, 49, 49, 49, 49]
    )
    page.get_by_role.return_value = trigger
    page.get_by_label.return_value = project_buttons
    page.wait_for_timeout = mocker.AsyncMock()

    assert await _expand_projects_section(page) is True

    page.get_by_role.assert_called_once()
    trigger.first.click.assert_awaited_once_with(timeout=5_000)
    assert page.wait_for_timeout.await_count == 6


async def test_expand_projects_section_is_noop_without_show_more(mocker):
    page = mocker.Mock()
    trigger = mocker.Mock()
    trigger.count = mocker.AsyncMock(return_value=0)
    page.get_by_role.return_value = trigger

    assert await _expand_projects_section(page) is False


def test_project_meta_from_current_project_home_url():
    meta = _project_meta_from_home_url(
        "https://chatgpt.com/g/g-p-69f0ce46f2dc8191beb21ab316b6c97d-projeto-de-teste/project"
    )

    assert meta == ProjectMeta(
        id="g-p-69f0ce46f2dc8191beb21ab316b6c97d",
        name="projeto de teste",
        discovered_via="dom_navigation",
    )


def test_project_meta_ignores_non_project_route():
    assert _project_meta_from_home_url("https://chatgpt.com/c/example") is None


async def test_discover_all_combines_sources_deduplicated(mocker):
    """Main + archived + projects (vazio) deve ser deduplicado no final."""
    mock_client = mocker.AsyncMock()

    main_convs = [
        ConversationMeta(id="a", title="A", create_time=1.0, update_time=2.0, project_id=None, archived=False),
        ConversationMeta(id="b", title="B", create_time=1.0, update_time=2.0, project_id=None, archived=False),
    ]
    archived_convs = [
        ConversationMeta(id="c", title="C", create_time=1.0, update_time=2.0, project_id=None, archived=True),
    ]
    # b tambem aparece em archived — teste de dedup
    archived_convs.append(main_convs[1])

    mock_client.list_conversations.side_effect = [main_convs, []]  # paginacao: 2 items, depois 0
    mock_client.list_archived.side_effect = [archived_convs, []]
    mock_client.list_projects.return_value = []
    mock_client.list_shared.side_effect = [[], []]

    metas, project_names = await discover_all(mock_client)

    ids = [m.id for m in metas]
    assert sorted(ids) == ["a", "b", "c"]  # b nao duplicou
    assert len(metas) == 3
    assert project_names == {}  # sem projects nesse cenario
    mock_client.list_conversations.assert_awaited_once_with(offset=0, limit=100)
    mock_client.list_archived.assert_awaited_once_with(offset=0, limit=100)
    mock_client.list_shared.assert_awaited_once_with(offset=0, limit=100)


async def test_discover_all_fetches_project_conversations(mocker):
    """Se ha projects, chama list_project_conversations pra cada um.

    NOTA: list_project_conversations retorna TUPLA (metas, next_cursor) —
    assinatura confirmada pela pesquisa do Task 0.1 (response.cursor, int, None termina).
    """
    mock_client = mocker.AsyncMock()
    mock_client.list_conversations.side_effect = [[], []]
    mock_client.list_archived.side_effect = [[], []]
    mock_client.list_shared.side_effect = [[], []]
    mock_client.list_projects.return_value = [
        ProjectMeta(id="g-p-1", name="Studies", discovered_via="projects_api"),
    ]
    # Tuple return: (list_of_metas, next_cursor). None cursor termina paginacao.
    mock_client.list_project_conversations.side_effect = [
        (
            [ConversationMeta(id="pc1", title="Project conv", create_time=1.0, update_time=2.0,
                             project_id="g-p-1", archived=False)],
            None,  # next_cursor = None → termina
        ),
    ]

    metas, project_names = await discover_all(mock_client)

    assert len(metas) == 1
    assert metas[0].id == "pc1"
    assert metas[0].project_id == "g-p-1"
    assert project_names == {"g-p-1": "Studies"}
