"""Testes de discovery.py — orquestracao completa de descoberta de IDs."""

import pytest

from src.extractors.chatgpt.discovery import discover_all
from src.extractors.chatgpt.models import ConversationMeta, ProjectMeta


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
