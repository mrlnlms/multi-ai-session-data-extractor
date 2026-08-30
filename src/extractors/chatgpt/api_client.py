"""HTTP client pras APIs internas do ChatGPT.

Usa playwright.async_api.APIRequestContext — cookies da sessao logada via
auth.py sao enviados automaticamente.
"""

import asyncio
import json as _json
import logging
from typing import Any

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.extractors.chatgpt.models import ConversationMeta, ProjectMeta

logger = logging.getLogger(__name__)

BASE_URL = "https://chatgpt.com/backend-api"
TOKEN_URL = "https://chatgpt.com/api/auth/session"

# Rate limit config (conservador, ajustar empiricamente)
RATE_LIMIT_WAIT_SECONDS = 30
MAX_RETRIES_429 = 3
BACKOFF_MULTIPLIER = 2
REQUEST_TIMEOUT_MS = 60_000


class _PageResponse:
    """Small APIResponse-compatible wrapper for browser-page fetches."""

    def __init__(self, status: int, ok: bool, text: str):
        self.status = status
        self.ok = ok
        self._text = text

    async def json(self) -> dict | list:
        return _json.loads(self._text)


class ChatGPTAPIClient:
    """Client pras APIs internas do ChatGPT via Playwright request context."""

    def __init__(self, request_context, *, page=None):
        """
        Args:
            request_context: instancia de playwright.async_api.APIRequestContext
                             (geralmente vem de browser_context.request).
        """
        self._ctx = request_context
        self._page = page
        self._cached_token: str | None = None

    async def _page_fetch(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        params: dict | None = None,
        metadata_only: bool = False,
    ) -> _PageResponse:
        """Run an authenticated fetch inside the visible browser page.

        The browser context's APIRequestContext can hang before its first
        response on current ChatGPT sessions. Page fetch preserves the same
        cookies and Cloudflare state while keeping the request in-browser.
        """
        if params:
            from urllib.parse import urlencode

            url = f"{url}?{urlencode(params)}"
        effective_headers = dict(headers or {})
        if json is not None:
            effective_headers.setdefault("Content-Type", "application/json")
        result = await self._page.evaluate(
            """async ({url, method, headers, body, timeoutMs, metadataOnly}) => {
                const controller = new AbortController();
                const timer = setTimeout(() => controller.abort(), timeoutMs);
                try {
                    const response = await fetch(url, {
                        method,
                        headers,
                        body,
                        credentials: "include",
                        signal: controller.signal,
                    });
                    const text = await response.text();
                    if (metadataOnly && response.ok) {
                        try {
                            const payload = JSON.parse(text);
                            const items = (payload.items || []).map((item) => ({
                                id: item.id,
                                conversation_id: item.conversation_id,
                                title: item.title,
                                create_time: item.create_time,
                                update_time: item.update_time,
                                gizmo_id: item.gizmo_id,
                                is_archived: item.is_archived,
                            }));
                            return {status: response.status, ok: response.ok, text: JSON.stringify({items})};
                        } catch (_) {
                            return {status: response.status, ok: false, text: ""};
                        }
                    }
                    return {
                        status: response.status,
                        ok: response.ok,
                        text,
                    };
                } catch (error) {
                    return {error: error.name};
                } finally {
                    clearTimeout(timer);
                }
            }""",
            {
                "url": url,
                "method": method,
                "headers": effective_headers,
                "body": _json.dumps(json) if json is not None else None,
                "timeoutMs": REQUEST_TIMEOUT_MS,
                "metadataOnly": metadata_only,
            },
        )
        if result.get("error"):
            raise RuntimeError(
                f"Timeout ou erro de rede em {method} {url}: {result['error']}"
            )
        return _PageResponse(result["status"], result["ok"], result["text"])

    async def _get_token(self) -> str:
        """Busca accessToken via /api/auth/session (cacheado).

        Replica getToken() do migrate.js (linhas 285-300). Cookies do profile
        logado sao enviados automaticamente pelo APIRequestContext.
        """
        if self._cached_token:
            return self._cached_token
        if self._page is not None:
            response = await self._page_fetch("GET", TOKEN_URL)
        else:
            try:
                response = await self._ctx.get(TOKEN_URL, timeout=REQUEST_TIMEOUT_MS)
            except PlaywrightTimeoutError as exc:
                raise RuntimeError(
                    f"Timeout apos {REQUEST_TIMEOUT_MS // 1000}s ao autenticar em {TOKEN_URL}. "
                    "Confirme a sessao headed do ChatGPT e tente novamente."
                ) from exc
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
            try:
                if self._page is not None:
                    response = await self._page_fetch(
                        method,
                        url,
                        headers=headers,
                        json=json,
                        params=params,
                    )
                elif method == "GET":
                    response = await self._ctx.get(
                        url,
                        params=params,
                        headers=headers,
                        timeout=REQUEST_TIMEOUT_MS,
                    )
                elif method == "POST":
                    # Playwright APIRequestContext.post: `data=dict` vira form-encoded.
                    # Pra JSON proper (com content-type application/json), usar `data=`
                    # com STRING (json.dumps) ou parametro `multipart=False` + headers
                    # explicitos. Forma mais confiavel: dump pra string e header.
                    if json is not None:
                        response = await self._ctx.post(
                            url,
                            data=_json.dumps(json),
                            headers={**headers, "Content-Type": "application/json"},
                            timeout=REQUEST_TIMEOUT_MS,
                        )
                    else:
                        response = await self._ctx.post(
                            url,
                            headers=headers,
                            timeout=REQUEST_TIMEOUT_MS,
                        )
                else:
                    raise ValueError(f"Metodo HTTP nao suportado: {method}")
            except PlaywrightTimeoutError as exc:
                raise RuntimeError(
                    f"Timeout apos {REQUEST_TIMEOUT_MS // 1000}s em {method} {url}. "
                    "Confirme a sessao headed do ChatGPT e tente novamente."
                ) from exc

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
        """Lista a sidebar principal com os filtros observados na UI.

        Sem esses filtros, o backend pode misturar fontes da sidebar e nao
        encerrar a paginacao por ``offset`` de forma confiavel.
        """
        url = f"{BASE_URL}/conversations"
        params = {
            "offset": offset,
            "limit": limit,
            "order": "updated",
            "is_archived": "false",
            "is_starred": "false",
            "hide_snorlax": "true",
        }
        if self._page is not None:
            token = await self._get_token()
            response = await self._page_fetch(
                "GET", url,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                metadata_only=True,
            )
            if not response.ok:
                raise RuntimeError(f"HTTP {response.status} em GET {url}")
            data = await response.json()
        else:
            data = await self._request_with_retry(
                "GET", url, params=params
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

        Endpoint `/conversations/batch` aceita NO MAXIMO 10 IDs por request
        (descoberto empiricamente 2026-05-01: 50 IDs retorna 422 com mensagem
        "conversation_ids must contain at most 10 entries"). Se vier mais que 10,
        chunkamos internamente e concatenamos os resultados.

        Se alguma conv vier com _mapping_node_count > 0 mas 0 msgs extraidas,
        re-fetch via single endpoint e substitui no resultado.
        """
        url = f"{BASE_URL}/conversations/batch"
        BATCH_LIMIT = 10
        all_convs: list[dict] = []
        for i in range(0, len(conv_ids), BATCH_LIMIT):
            chunk = conv_ids[i : i + BATCH_LIMIT]
            data = await self._request_with_retry(
                "POST", url, json={"conversation_ids": chunk}
            )
            # API pode retornar list direto OU dict com "conversations"
            if isinstance(data, list):
                all_convs.extend(data)
            elif isinstance(data, dict):
                all_convs.extend(data.get("conversations", []))
        convs = all_convs

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
        """Lista convs arquivadas com o mesmo contrato da sidebar."""
        url = f"{BASE_URL}/conversations"
        params = {
            "offset": offset,
            "limit": limit,
            "order": "updated",
            "is_archived": "true",
            "is_starred": "false",
            "hide_snorlax": "true",
        }
        if self._page is not None:
            token = await self._get_token()
            response = await self._page_fetch(
                "GET", url,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                metadata_only=True,
            )
            if not response.ok:
                raise RuntimeError(f"HTTP {response.status} em GET {url}")
            data = await response.json()
        else:
            data = await self._request_with_retry(
                "GET", url,
                params=params,
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
        if self._page is not None:
            token = await self._get_token()
            response = await self._page_fetch(
                "GET", url,
                params={"offset": offset, "limit": limit},
                headers={"Authorization": f"Bearer {token}"},
                metadata_only=True,
            )
            if not response.ok:
                raise RuntimeError(f"HTTP {response.status} em GET {url}")
            data = await response.json()
        else:
            data = await self._request_with_retry(
                "GET", url, params={"offset": offset, "limit": limit}
            )
        return [_meta_from_shared_item(item) for item in data.get("items", [])]

    async def list_pinned_gizmos(self) -> list[dict]:
        """Lista GPTs (gizmos) pinados na sidebar do user.

        Endpoint descoberto via probe direto no Chrome MCP (2026-05-01):
        `GET /backend-api/gizmos/pinned`. Schema: `{items: [...], cursor}`.
        ChatGPT NAO tem pin de conversation (`/conversations/pinned` retorna
        404), so de gizmo. Equivalente conceitual ao `is_pinned` em
        `Conversation` do Perplexity, mas em entidade diferente."""
        url = f"{BASE_URL}/gizmos/pinned"
        data = await self._request_with_retry("GET", url)
        return data.get("items") or []

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
        """Lista projetos pelo indice paginado que alimenta a sidebar atual.

        Tenta:
          1. /backend-api/gizmos/snorlax/sidebar (contrato observado 2026-08-30)
          2. endpoints legados, somente como compatibilidade

        O indice Snorlax retorna ``{items: [{gizmo: ...}], cursor}`` quando
        chamado sem parametros e pagina por cursor. Ele e a fonte que a UI usa
        para a secao Projects; evita depender de ``Show more`` e de DOM.
        """
        # Tentativa 1: indice atual da sidebar, com paginacao por cursor.
        try:
            projects: list[ProjectMeta] = []
            seen_cursors: set[str] = set()
            cursor: str | None = None
            while True:
                params = {"cursor": cursor} if cursor else None
                data = await self._request_with_retry(
                    "GET", f"{BASE_URL}/gizmos/snorlax/sidebar", params=params
                )
                for item in data.get("items", []):
                    gizmo = item.get("gizmo", {})
                    project_id = gizmo.get("id", "")
                    if not project_id.startswith("g-p-"):
                        continue
                    display = gizmo.get("display") or {}
                    projects.append(ProjectMeta(
                        id=project_id,
                        name=display.get("name") or gizmo.get("name") or "(unknown)",
                        discovered_via="snorlax_sidebar",
                    ))
                cursor = data.get("cursor")
                if not cursor or cursor in seen_cursors:
                    return projects
                seen_cursors.add(cursor)
        except RuntimeError as exc:
            if not any(f"HTTP {status}" in str(exc) for status in (404, 405)):
                raise
            logger.info("/gizmos/snorlax/sidebar indisponivel (404/405), usando compatibilidade")

        # Tentativa 2: /projects (legado)
        try:
            data = await self._request_with_retry("GET", f"{BASE_URL}/projects")
            return [
                ProjectMeta(id=p["id"], name=p["name"], discovered_via="projects_api")
                for p in data.get("projects", [])
            ]
        except RuntimeError as exc:
            if not any(f"HTTP {status}" in str(exc) for status in (404, 405)):
                raise
            logger.info("/projects indisponivel (404/405), fallback pra /gizmos/discovery/mine")

        # Tentativa 3: /gizmos/discovery/mine (legado)
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
            if not any(f"HTTP {status}" in str(exc) for status in (404, 405)):
                raise
            logger.info("/gizmos/discovery/mine indisponivel (404/405) — caller faz DOM fallback")

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
