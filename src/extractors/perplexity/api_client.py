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
        path = f"{API_BASE}/rest/thread/list_pinned_ask_threads?version=2.18&source=default"
        try:
            data = await self._fetch(path)
            return data if isinstance(data, list) else []
        except Exception as e:
            print(f"  warn: pinned failed: {str(e)[:100]}")
            return []

    async def list_all_threads(self, page_size: int = 50) -> list[dict]:
        all_threads: list[dict] = []
        seen: set[str] = set()
        offset = 0
        while True:
            batch = await self.list_threads_page(offset=offset, limit=page_size)
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
        # Pinned (merge, nao sobrescreve)
        for t in await self.list_pinned_threads():
            uid = t.get("uuid")
            if uid and uid not in seen:
                seen.add(uid)
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
