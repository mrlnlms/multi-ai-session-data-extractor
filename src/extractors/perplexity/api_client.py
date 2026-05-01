"""Client Perplexity - wraps /rest/ via page.evaluate(fetch).

Endpoints confirmados via probe 24/abr/2026:
  POST /rest/thread/list_ask_threads?version=2.18&source=default
        body: {limit, ascending, offset, search_term, exclude_asi}
  GET  /rest/thread/{uuid}?with_parent_info=true&with_schematized_response=true&version=2.18&source=default
  GET  /rest/thread/list_pinned_ask_threads?version=2.18&source=default

Auth: cookies + Next.js session (auth/session). fetch() dentro do page context
herda cookies automaticamente — sem Bearer token externo.

Cloudflare challenge ativo: headless=True e frequentemente bloqueado (403
"Just a moment..."). Default do extractor e headless=False.
"""

import json

from playwright.async_api import BrowserContext, Page


API_BASE = "https://www.perplexity.ai"
HOME_URL = f"{API_BASE}/"
LIBRARY_URL = f"{API_BASE}/library"


class PerplexityAPIClient:
    def __init__(self, context: BrowserContext, page: Page):
        self.context = context
        self.page = page

    async def _fetch(self, path: str, method: str = "GET", body: dict | None = None) -> dict | list:
        script = """async ({path, method, body}) => {
            const res = await fetch(path, {
                method,
                headers: {'Content-Type': 'application/json'},
                body: body ? JSON.stringify(body) : undefined,
            });
            const text = await res.text();
            return {status: res.status, body: text};
        }"""
        result = await self.page.evaluate(script, {"path": path, "method": method, "body": body})
        if result["status"] >= 400:
            raise RuntimeError(f"HTTP {result['status']} on {method} {path}: {result['body'][:300]}")
        try:
            return json.loads(result["body"])
        except Exception as e:
            raise RuntimeError(f"Bad JSON from {path}: {e}: {result['body'][:200]}")

    async def list_threads_page(self, offset: int, limit: int = 20) -> list[dict]:
        path = f"{API_BASE}/rest/thread/list_ask_threads?version=2.18&source=default"
        body = {
            "limit": limit,
            "ascending": False,
            "offset": offset,
            "search_term": "",
            "exclude_asi": False,
        }
        data = await self._fetch(path, method="POST", body=body)
        return data if isinstance(data, list) else []

    async def list_pinned_threads(self) -> list[dict]:
        # POST + body vazio. GET (versao antiga) retorna 400. Confirmado via probe 2026-04-29.
        path = f"{API_BASE}/rest/thread/list_pinned_ask_threads?version=2.18&source=default"
        try:
            data = await self._fetch(path, method="POST", body={})
            return data if isinstance(data, list) else []
        except Exception as e:
            print(f"  warn: pinned failed: {str(e)[:100]}")
            return []

    async def list_user_collections(self) -> list[dict]:
        """Lista todas as collections (Spaces na UI) do user."""
        path = f"{API_BASE}/rest/collections/list_user_collections?version=2.18&source=default"
        data = await self._fetch(path)
        return data if isinstance(data, list) else []

    async def list_user_pinned_spaces(self) -> list[dict]:
        """Spaces pinados pelo user (sidebar). Retorna o mesmo schema de collection."""
        path = f"{API_BASE}/rest/spaces/user-pins?version=2.18&source=default"
        data = await self._fetch(path)
        return data if isinstance(data, list) else []

    async def list_user_assets(self, limit: int = 50) -> list[dict]:
        """Lista assets (UI: 'Artifacts') do user. Tipicamente imagens geradas
        pela IA, visualizations, e outros artifacts gerados em threads.
        Endpoint descoberto via probe 2026-05-01 em /library?tab=artifacts.
        Schema: {assets: [...], next_token}. Paginacao via next_token."""
        all_assets: list[dict] = []
        token: str | None = None
        while True:
            qs = f"limit={limit}&version=2.18&source=default"
            if token:
                qs += f"&next_token={token}"
            path = f"{API_BASE}/rest/assets/?{qs}"
            data = await self._fetch(path)
            if not isinstance(data, dict):
                break
            batch = data.get("assets") or []
            all_assets.extend(batch)
            token = data.get("next_token")
            if not token or not batch:
                break
        return all_assets

    async def get_user_info(self) -> dict:
        """Status do user (is_enterprise, is_student, etc)."""
        path = f"{API_BASE}/rest/user/info?version=2.18&source=default"
        data = await self._fetch(path)
        return data if isinstance(data, dict) else {}

    async def get_user_settings(self) -> dict:
        """Limites do user (pages_limit, upload_limit, connector_limits)."""
        path = f"{API_BASE}/rest/user/settings?version=2.18&source=default"
        data = await self._fetch(path)
        return data if isinstance(data, dict) else {}

    async def get_user_ai_profile(self) -> dict:
        """AI profile (bio, location, language preferences). Pode estar disabled."""
        path = f"{API_BASE}/rest/user/get_user_ai_profile?version=2.18&source=default"
        data = await self._fetch(path)
        return data if isinstance(data, dict) else {}

    async def list_user_pinned_assets(self, limit: int = 50) -> list[dict]:
        """Assets pinados pelo user. Mesmo schema que list_user_assets."""
        path = f"{API_BASE}/rest/assets/pins?limit={limit}&version=2.18&source=default"
        data = await self._fetch(path)
        if isinstance(data, dict):
            return data.get("assets") or []
        return []

    async def get_collection(self, slug: str) -> dict:
        """Metadata completa de 1 collection. API usa slug, nao uuid."""
        path = f"{API_BASE}/rest/collections/get_collection?collection_slug={slug}&version=2.18&source=default"
        data = await self._fetch(path)
        if not isinstance(data, dict):
            raise RuntimeError(f"get_collection retornou nao-dict: {type(data).__name__}")
        return data

    async def list_collection_threads(
        self, slug: str, limit: int = 50, offset: int = 0, filter_by_user: bool = False
    ) -> list[dict]:
        """Threads dentro de uma collection. filter_by_user=False inclui threads
        de outros users com acesso (collections compartilhadas)."""
        path = (
            f"{API_BASE}/rest/collections/list_collection_threads"
            f"?collection_slug={slug}&limit={limit}&offset={offset}"
            f"&filter_by_user={'true' if filter_by_user else 'false'}"
        )
        data = await self._fetch(path)
        return data if isinstance(data, list) else []

    async def list_all_collection_threads(self, slug: str, page_size: int = 50) -> list[dict]:
        """Pagina list_collection_threads ate esgotar."""
        all_threads: list[dict] = []
        seen: set[str] = set()
        offset = 0
        while True:
            batch = await self.list_collection_threads(slug, limit=page_size, offset=offset)
            if not batch:
                break
            new = 0
            for t in batch:
                uid = t.get("uuid")
                if uid and uid not in seen:
                    seen.add(uid)
                    all_threads.append(t)
                    new += 1
            if new == 0 or len(batch) < page_size:
                break
            offset += page_size
        return all_threads

    async def fetch_article(self, slug: str) -> dict:
        """Fetcha 1 Perplexity Page (UI Page = API article). Endpoint descoberto
        via probe 2026-05-01 (XHR disparado em /page/{slug})."""
        path = f"{API_BASE}/rest/article/{slug}"
        data = await self._fetch(path)
        if not isinstance(data, dict):
            raise RuntimeError(f"fetch_article retornou nao-dict: {type(data).__name__}")
        return data

    async def list_collection_files(self, uuid: str, limit: int = 50) -> list[dict]:
        """Files anexados a uma collection. Body precisa de file_repository_info."""
        path = f"{API_BASE}/rest/file-repository/list-files?version=2.18&source=default"
        body = {
            "file_repository_info": {"file_repository_type": "COLLECTION", "owner_id": uuid},
            "limit": limit,
            "offset": 0,
            "search_term": "",
            "file_states_in_filter": ["COMPLETE"],
        }
        data = await self._fetch(path, method="POST", body=body)
        if isinstance(data, dict):
            return data.get("files", []) if isinstance(data.get("files"), list) else []
        return []

    async def list_collection_skills(self, uuid: str) -> list[dict]:
        """Skills de uma collection (Computer Skills, feature Pro/Enterprise).
        Endpoint descoberto via probe 2026-05-01: /rest/skills?scope=collection&scope_id=<UUID>.
        Schema: id, name, description, file_url, scope, created_at, updated_at, tags, enabled.
        Retorna [] em conta sem skill ou sem Pro. 404 se file repository nao existir."""
        path = f"{API_BASE}/rest/skills?scope=collection&scope_id={uuid}"
        try:
            data = await self._fetch(path)
        except Exception as e:
            # 404 quando space nao tem file repository (sem skills/files)
            if "404" in str(e):
                return []
            raise
        if isinstance(data, dict):
            return data.get("skills") or []
        return []

    async def list_user_skills(self) -> list[dict]:
        """Skills individuais do user (nao em collection).
        Endpoint: /rest/skills?scope=individual."""
        path = f"{API_BASE}/rest/skills?scope=individual"
        data = await self._fetch(path)
        if isinstance(data, dict):
            return data.get("skills") or []
        return []

    async def list_all_threads(self, page_size: int = 50) -> list[dict]:
        all_threads: list[dict] = []
        seen: dict[str, dict] = {}
        offset = 0
        while True:
            batch = await self.list_threads_page(offset=offset, limit=page_size)
            if not batch:
                break
            new = 0
            for t in batch:
                uid = t.get("uuid")
                if uid and uid not in seen:
                    seen[uid] = t
                    all_threads.append(t)
                    new += 1
            if new == 0 or len(batch) < page_size:
                break
            offset += page_size
        # Pinned threads vem com `is_pinned: true` extra. Se thread ja apareceu em
        # list_ask_threads, propagar a flag (e qualquer outro campo extra). Se for
        # nova (nao apareceu no listing principal), append.
        for t in await self.list_pinned_threads():
            uid = t.get("uuid")
            if not uid:
                continue
            if uid in seen:
                seen[uid].update({k: v for k, v in t.items() if k not in seen[uid] or k == "is_pinned"})
            else:
                seen[uid] = t
                all_threads.append(t)
        return all_threads

    async def fetch_thread(self, uuid: str) -> dict:
        path = f"{API_BASE}/rest/thread/{uuid}?with_parent_info=true&with_schematized_response=true&version=2.18&source=default"
        data = await self._fetch(path)
        if not isinstance(data, dict):
            raise RuntimeError(f"fetch_thread retornou nao-dict: {type(data).__name__}")
        return data

    async def warmup(self):
        """Carrega home + espera eventual Cloudflare challenge resolver."""
        await self.page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        await self.page.wait_for_timeout(5000)
        # Se challenge, navegar pra library tambem dispara resolucao
        title = await self.page.title()
        if "moment" in title.lower() or "checking" in title.lower():
            await self.page.wait_for_timeout(10000)
        await self.page.goto(LIBRARY_URL, wait_until="domcontentloaded", timeout=60000)
        await self.page.wait_for_timeout(3000)
