"""Cliente HTTP autenticado para Claude.ai.

Usa context.request do Playwright (passa Cloudflare porque usa os cookies
cf_clearance/__cf_bm da sessao autenticada).

Endpoints confirmados empiricamente (24/abr/2026):
- GET /api/organizations/{org}/chat_conversations_v2?limit=N&starred={bool}&consistency=eventual
  (retorna {"data":[...]})
- GET /api/organizations/{org}/chat_conversations/{uuid}?tree=True&rendering_mode=messages&render_all_tools=true
- GET /api/organizations/{org}/projects (a confirmar no smoke test)
- GET /api/organizations/{org}/projects/{uuid} (a confirmar)
- GET /api/{org}/files/{uuid}/{preview|thumbnail}  (EXCECAO: sem /organizations/)
"""

from typing import Any

from playwright.async_api import BrowserContext


BASE_URL = "https://claude.ai"


class ClaudeAPIClient:
    def __init__(self, context: BrowserContext, org_id: str):
        self.context = context
        self.org_id = org_id
        self.request = context.request

    def _org_path(self, suffix: str) -> str:
        return f"/api/organizations/{self.org_id}/{suffix.lstrip('/')}"

    async def _get_json(self, path: str) -> Any:
        """GET com auth via context cookies. Retorna JSON parseado."""
        url = f"{BASE_URL}{path}"
        resp = await self.request.get(url)
        if not resp.ok:
            body = (await resp.text())[:300]
            raise RuntimeError(f"HTTP {resp.status} on {path}\n  body: {body}")
        return await resp.json()

    async def _get_bytes(self, path: str) -> bytes:
        """GET binario (imagens, etc)."""
        url = f"{BASE_URL}{path}"
        resp = await self.request.get(url)
        if not resp.ok:
            body = (await resp.text())[:300]
            raise RuntimeError(f"HTTP {resp.status} on {path}\n  body: {body}")
        return await resp.body()

    # --- Conversations ---

    async def list_conversations(self, starred: bool | None = None, limit: int = 500) -> list[dict]:
        """Lista convs do org. starred=True/False filtra; None retorna ambos (merge).

        chat_conversations_v2 retorna {"data": [...]}. Se precisar paginar, iterar
        aqui com cursor/offset quando API explicitar.
        """
        if starred is None:
            starred_convs = await self.list_conversations(starred=True, limit=limit)
            other_convs = await self.list_conversations(starred=False, limit=limit)
            seen = set()
            combined = []
            for c in starred_convs + other_convs:
                uid = c.get("uuid")
                if uid and uid not in seen:
                    seen.add(uid)
                    combined.append(c)
            return combined

        starred_str = "true" if starred else "false"
        path = self._org_path(
            f"chat_conversations_v2?limit={limit}&starred={starred_str}&consistency=eventual"
        )
        resp = await self._get_json(path)
        # v2 envelopa em {"data": [...]}. Absorver ambos os formatos por seguranca.
        if isinstance(resp, dict) and "data" in resp:
            return resp["data"]
        return resp

    async def fetch_conversation(self, conv_uuid: str) -> dict:
        """Arvore completa da conversa com mensagens, tools, files, thinking."""
        path = self._org_path(
            f"chat_conversations/{conv_uuid}"
            "?tree=True&rendering_mode=messages&render_all_tools=true&consistency=eventual"
        )
        return await self._get_json(path)

    # --- Projects ---

    async def list_projects(self) -> list[dict]:
        """Lista projects do org. Endpoint a confirmar empiricamente."""
        path = self._org_path("projects")
        resp = await self._get_json(path)
        if isinstance(resp, dict) and "data" in resp:
            return resp["data"]
        return resp

    async def fetch_project(self, project_uuid: str) -> dict:
        """Project metadata (NAO inclui docs — usar list_project_docs)."""
        path = self._org_path(f"projects/{project_uuid}")
        return await self._get_json(path)

    async def list_project_docs(self, project_uuid: str) -> list[dict]:
        """Docs (knowledge sources) do project com content extraido.

        Schema observado: {uuid, file_name, content, created_at}.
        NOTE: campo e `file_name`, NAO `filename` como no export oficial.
        """
        path = self._org_path(f"projects/{project_uuid}/docs")
        return await self._get_json(path)

    async def list_project_files(self, project_uuid: str) -> list[dict]:
        """Files do project (tipo diferente de docs — natureza a mapear).

        Endpoint existe e retorna array; schema e conteudo a confirmar com
        um project que tenha files_count > 0.
        """
        path = self._org_path(f"projects/{project_uuid}/files")
        return await self._get_json(path)

    # --- Memory (preferences/instructions remembered across sessions) ---

    async def get_memory(self) -> str:
        """Retorna texto da memory do org (campo unico em markdown).

        Endpoint: GET /api/organizations/{org}/memory → {"memory": "<markdown>"}.
        Vazio (memory desabilitada / sem conteudo): {"memory": ""}.
        """
        path = self._org_path("memory")
        data = await self._get_json(path)
        return data.get("memory", "") or ""

    # --- Assets ---

    async def download_file(self, file_uuid: str, variant: str = "preview") -> bytes:
        """Download binario. variant='preview' (maior) ou 'thumbnail' (400px).

        ATENCAO: este endpoint NAO tem /organizations/ no path (confirmado empirico).
        """
        path = f"/api/{self.org_id}/files/{file_uuid}/{variant}"
        return await self._get_bytes(path)
