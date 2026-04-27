"""HTTP client pras APIs internas do ChatGPT.

Usa playwright.async_api.APIRequestContext — cookies da sessao logada via
auth.py sao enviados automaticamente.
"""

import asyncio
import logging
from typing import Any

from src.extractors.chatgpt.models import ConversationMeta, ProjectMeta

logger = logging.getLogger(__name__)

BASE_URL = "https://chatgpt.com/backend-api"
TOKEN_URL = "https://chatgpt.com/api/auth/session"

# Rate limit config (conservador, ajustar empiricamente)
RATE_LIMIT_WAIT_SECONDS = 30
MAX_RETRIES_429 = 3
BACKOFF_MULTIPLIER = 2


class ChatGPTAPIClient:
    """Client pras APIs internas do ChatGPT via Playwright request context."""

    def __init__(self, request_context):
        """
        Args:
            request_context: instancia de playwright.async_api.APIRequestContext
                             (geralmente vem de browser_context.request).
        """
        self._ctx = request_context
        self._cached_token: str | None = None

    async def _get_token(self) -> str:
        """Busca accessToken via /api/auth/session (cacheado).

        Replica getToken() do migrate.js (linhas 285-300). Cookies do profile
        logado sao enviados automaticamente pelo APIRequestContext.
        """
        if self._cached_token:
            return self._cached_token
        response = await self._ctx.get(TOKEN_URL)
        if not response.ok:
            raise RuntimeError(
                f"Falha autenticacao em {TOKEN_URL} (HTTP {response.status}). "
                "Rode 'python scripts/chatgpt-login.py'."
            )
        data = await response.json()
        token = data.get("accessToken")
        if not token:
            raise RuntimeError(
                "Sessao sem accessToken. Refresh chatgpt.com no browser e "
                "rode 'python scripts/chatgpt-login.py' de novo."
            )
        self._cached_token = token
        return token

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        params: dict | None = None,
    ) -> dict | list:
        """Helper interno com retry em 429 + backoff.

        Raises:
            RuntimeError: se 401/403 (sessao expirou) — usuario deve re-login.
            RuntimeError: se 4xx persistente ou 5xx apos retries.
        """
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        retries = 0
        wait_seconds = RATE_LIMIT_WAIT_SECONDS

        while True:
            if method == "GET":
                response = await self._ctx.get(url, params=params, headers=headers)
            elif method == "POST":
                # Playwright APIRequestContext.post aceita `data=` pra JSON body
                # (converte internamente). Se body for None, envia sem payload.
                # Importante: NAO e form-encoded, e JSON com Content-Type application/json.
                if json is not None:
                    response = await self._ctx.post(url, data=json, headers=headers)
                else:
                    response = await self._ctx.post(url, headers=headers)
            else:
                raise ValueError(f"Metodo HTTP nao suportado: {method}")

            # NOTA: `response.ok` e property em Playwright APIResponse (confirmado em Task 0.1).
            if response.ok:
                return await response.json()

            if response.status in (401, 403):
                raise RuntimeError(
                    "Sessao ChatGPT expirou. Rode 'python scripts/chatgpt-login.py'."
                )

            if response.status == 429:
                if retries >= MAX_RETRIES_429:
                    raise RuntimeError(
                        f"Rate limit persistente apos {MAX_RETRIES_429} retries em {url}"
                    )
                logger.warning(
                    f"429 em {url}, aguardando {wait_seconds}s (retry {retries+1}/{MAX_RETRIES_429})"
                )
                await asyncio.sleep(wait_seconds)
                retries += 1
                wait_seconds *= BACKOFF_MULTIPLIER
                continue

            raise RuntimeError(
                f"HTTP {response.status} em {method} {url}"
            )

    async def list_conversations(
        self, offset: int = 0, limit: int = 100
    ) -> list[ConversationMeta]:
        """Lista convs paginadas do endpoint principal (main, nao archived)."""
        url = f"{BASE_URL}/conversations"
        data = await self._request_with_retry(
            "GET", url, params={"offset": offset, "limit": limit}
        )
        items = data.get("items", [])
        return [_meta_from_api_item(item) for item in items]

    async def fetch_conversation(self, conv_id: str) -> dict:
        """Fetch single — retorna raw completo com mapping tree intacta.

        Nao descarta nada: tether_quote, dalle, image_asset_pointer, metadata,
        tudo preservado exatamente como a API retorna.
        """
        url = f"{BASE_URL}/conversation/{conv_id}"
        return await self._request_with_retry("GET", url)

    async def fetch_conversations_batch(self, conv_ids: list[str]) -> list[dict]:
        """Batch fetch com truncation detection (fix v2.7).

        Se alguma conv vier com _mapping_node_count > 0 mas 0 msgs extraidas,
        re-fetch via single endpoint e substitui no resultado.
        """
        url = f"{BASE_URL}/conversations/batch"
        data = await self._request_with_retry(
            "POST", url, json={"conversation_ids": conv_ids}
        )
        # API pode retornar list direto OU dict com "conversations" — empirico confirmou list
        if isinstance(data, list):
            convs = data
        else:
            convs = data.get("conversations", [])

        result = []
        for conv in convs:
            if self._is_truncated(conv):
                logger.warning(
                    f"Batch truncation detected em conv {conv.get('id')}, re-fetching via single"
                )
                try:
                    full = await self.fetch_conversation(conv["id"])
                    full["_truncation_recovered"] = True
                    result.append(full)
                except Exception as exc:
                    logger.error(f"Re-fetch falhou pra {conv.get('id')}: {exc}")
                    conv["_truncation_recovered"] = False
                    result.append(conv)
            else:
                conv["_truncation_recovered"] = False
                result.append(conv)
        return result

    async def list_archived(
        self, offset: int = 0, limit: int = 100
    ) -> list[ConversationMeta]:
        """Lista convs arquivadas."""
        url = f"{BASE_URL}/conversations"
        data = await self._request_with_retry(
            "GET", url,
            params={"offset": offset, "limit": limit, "is_archived": "true"},
        )
        return [_meta_from_api_item(item) for item in data.get("items", [])]

    async def list_shared(
        self, offset: int = 0, limit: int = 100
    ) -> list[ConversationMeta]:
        """Lista convs compartilhadas publicamente pelo usuario.

        Cada item tem dois IDs: `id` (share_id, UUID do link publico) e
        `conversation_id` (conversation real). Usamos `conversation_id` pra
        dedup correto contra main/archived/projects — se usar `id`, fetch
        single dele retorna 404 e a conv vira duplicata fantasma.
        """
        url = f"{BASE_URL}/shared_conversations"
        data = await self._request_with_retry(
            "GET", url, params={"offset": offset, "limit": limit}
        )
        return [_meta_from_shared_item(item) for item in data.get("items", [])]

    async def fetch_memories(self) -> str:
        """Retorna memories como markdown. API retorna JSON, convertemos pra .md."""
        url = f"{BASE_URL}/memories"
        data = await self._request_with_retry(
            "GET", url, params={"include_memory_entries": "true"}
        )
        entries = data.get("memories") or data.get("memory_entries") or []
        lines = ["# ChatGPT Memories\n"]
        for entry in entries:
            content = entry.get("content", "")
            lines.append(f"- {content}")
        return "\n".join(lines)

    async def fetch_instructions(self) -> dict:
        """Retorna custom instructions + account settings.

        Endpoint confirmado no Chunk 0 Task 0.1 Step 1: /backend-api/user_system_messages.
        """
        url = f"{BASE_URL}/user_system_messages"
        return await self._request_with_retry("GET", url)


    async def list_projects(self) -> list[ProjectMeta]:
        """Lista projetos via API endpoints. DOM e NEXT_DATA fallback vivem em discovery.py.

        Tenta:
          1. /backend-api/projects
          2. /backend-api/gizmos/discovery/mine
        Retorna [] se ambos falham — caller (discovery.py) faz cascade com DOM.
        """
        # Tentativa 1: /projects
        try:
            data = await self._request_with_retry("GET", f"{BASE_URL}/projects")
            return [
                ProjectMeta(id=p["id"], name=p["name"], discovered_via="projects_api")
                for p in data.get("projects", [])
            ]
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
            logger.info("/projects retornou 404, fallback pra /gizmos/discovery/mine")

        # Tentativa 2: /gizmos/discovery/mine
        try:
            data = await self._request_with_retry(
                "GET", f"{BASE_URL}/gizmos/discovery/mine"
            )
            return [
                ProjectMeta(
                    id=item["resource"]["gizmo"]["id"],
                    name=item["resource"]["gizmo"]["display"]["name"],
                    discovered_via="gizmos_discovery",
                )
                for item in data.get("items", [])
                if item.get("resource", {}).get("gizmo", {}).get("id", "").startswith("g-p-")
            ]
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
            logger.info("/gizmos/discovery/mine retornou 404 — caller faz DOM fallback")

        return []

    async def list_project_conversations(
        self, project_id: str, cursor: int | str | None = None
    ) -> tuple[list[ConversationMeta], int | str | None]:
        """Lista convs de um projeto especifico (cursor-based pagination).

        Retorna tupla (metas, next_cursor). next_cursor é None quando nao ha mais paginas
        (formato confirmado via migrate.js — ver docs/superpowers/plans/_chatgpt-migrate-js-notes.md §2).
        """
        url = f"{BASE_URL}/gizmos/{project_id}/conversations"
        params = {}
        if cursor is not None:
            params["cursor"] = cursor
        data = await self._request_with_retry("GET", url, params=params or None)
        items = data.get("items", [])
        metas = [_meta_from_api_item(item) for item in items]
        next_cursor = data.get("cursor")
        return metas, next_cursor

    async def fetch_project_files(self, project_id: str) -> list[dict]:
        """Lista os knowledge files (sources) de um project.

        Endpoint: GET /backend-api/gizmos/{pid} — o response top-level tem
        `files: [...]` junto com `gizmo`, `tools`, `product_features`.
        Cada file tem: id, file_id, name, type (MIME), size, created_at.
        Retorna [] se o project nao tem files uploaded.
        """
        data = await self._request_with_retry(
            "GET", f"{BASE_URL}/gizmos/{project_id}"
        )
        return data.get("files", []) or []

    async def get_project_file_download_url(
        self, file_id: str, project_id: str
    ) -> str | None:
        """Pega presigned download_url pra um project knowledge file.

        Descoberta empirica (24/abr/2026): sem o query param ?gizmo_id=, o
        endpoint retorna permission_error. Com ele, retorna {"status":"success",
        "download_url": "/backend-api/estuary/content?..."} valido.

        Retorna None se o servidor rejeitar (ex: file expirado).
        """
        data = await self._request_with_retry(
            "GET", f"{BASE_URL}/files/download/{file_id}",
            params={"gizmo_id": project_id},
        )
        if data.get("status") != "success":
            return None
        return data.get("download_url")

    async def download_binary(self, url: str) -> bytes | None:
        """Baixa um binario via URL (ex: download_url presigned).

        Returna None em HTTP error. Auth nao e requerido se a URL ja tem sig.
        """
        # URLs internas do ChatGPT (ex: /backend-api/estuary/content?...)
        # precisam ser absolutas
        if url.startswith("/"):
            url = f"https://chatgpt.com{url}"
        resp = await self._ctx.get(url)
        if not resp.ok:
            return None
        return await resp.body()

    @staticmethod
    def _is_truncated(conv: dict) -> bool:
        """Heuristica v2.7: node_count > 0 mas mapping tem 0-1 nodes."""
        node_count = conv.get("_mapping_node_count", 0)
        mapping_size = len(conv.get("mapping") or {})
        return node_count > 5 and mapping_size <= 1


def _meta_from_api_item(item: dict) -> ConversationMeta:
    """Converte um item da listagem em ConversationMeta."""
    return ConversationMeta(
        id=item["id"],
        title=item.get("title"),
        create_time=item.get("create_time", 0.0),
        update_time=item.get("update_time", 0.0),
        project_id=item.get("gizmo_id"),
        archived=item.get("is_archived", False),
    )


def _meta_from_shared_item(item: dict) -> ConversationMeta:
    """Converte item de /shared_conversations usando o conversation_id real.

    O `id` do item e o share_id (UUID do link publico) e nao resolve em
    /conversation/{id}. O `conversation_id` e o ID da conv real — esse sim
    bate com main/archived/projects.
    """
    real_id = item.get("conversation_id") or item["id"]
    return ConversationMeta(
        id=real_id,
        title=item.get("title"),
        create_time=item.get("create_time", 0.0),
        update_time=item.get("update_time", 0.0),
        project_id=item.get("gizmo_id"),
        archived=item.get("is_archived", False),
    )
