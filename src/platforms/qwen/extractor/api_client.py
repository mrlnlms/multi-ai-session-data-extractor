"""Client Qwen - wraps /api/v2 via page.evaluate(fetch).

Endpoints confirmados via probe 24/abr/2026:
  GET /api/v2/chats/?page=N[&exclude_project=true] — lista chats
  GET /api/v2/chats/pinned — pinned
  GET /api/v2/chats/{id} — fetch individual
  GET /api/v2/projects/ — lista projects
  GET /api/v1/auths/ — user info (tb valida auth)

Envelope: {"success": bool, "request_id": "...", "data": [...]}
Auth: cookies do profile + Bearer token em localStorage.token (observado).

Headers: source=web, bx-v=2.5.36 — SPA injetaria; fetch() manual precisa repetir.
"""

import json

from playwright.async_api import BrowserContext, Page


API_BASE = "https://chat.qwen.ai/api"
HOME_URL = "https://chat.qwen.ai/"


class QwenAPIClient:
    def __init__(self, context: BrowserContext, page: Page):
        self.context = context
        self.page = page
        self.token: str | None = None

    async def _load_token(self):
        """Busca token em localStorage (Qwen armazena em 'token' ou 'access_token')."""
        raw = await self.page.evaluate("""() => {
            const keys = ['token', 'access_token', 'authToken', 'userToken', 'Authorization'];
            for (const k of keys) {
                const v = localStorage.getItem(k);
                if (v) return {key: k, value: v};
            }
            return null;
        }""")
        if raw:
            v = raw["value"]
            # Alguns sistemas armazenam JSON-encoded {value, version}, outros string crua
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict) and "value" in parsed:
                    self.token = parsed["value"]
                else:
                    self.token = v
            except Exception:
                self.token = v
        # Se nao achar, vamos confiar em cookies (Qwen parece permitir)

    async def _fetch(self, path: str, method: str = "GET") -> dict:
        if self.token is None:
            await self._load_token()
        token = self.token or ""
        script = """async ({path, method, token}) => {
            const headers = {'Content-Type': 'application/json', 'source': 'web', 'bx-v': '2.5.36'};
            if (token) headers['authorization'] = 'Bearer ' + token;
            const res = await fetch(path, {method, headers});
            const text = await res.text();
            return {status: res.status, body: text};
        }"""
        result = await self.page.evaluate(script, {"path": path, "method": method, "token": token})
        if result["status"] != 200:
            raise RuntimeError(f"HTTP {result['status']} on {method} {path}: {result['body'][:300]}")
        try:
            parsed = json.loads(result["body"])
        except Exception as e:
            raise RuntimeError(f"Bad JSON from {path}: {e}: {result['body'][:200]}")
        return parsed

    async def list_chats_page(self, page_num: int, include_projects: bool = True) -> list[dict]:
        """Retorna um page de chats. Com include_projects=True pega TUDO (sem filtro)."""
        qs = "" if include_projects else "&exclude_project=true"
        path = f"{API_BASE}/v2/chats/?page={page_num}{qs}"
        resp = await self._fetch(path)
        if not resp.get("success"):
            raise RuntimeError(f"list_chats page={page_num} failed: {resp}")
        return resp.get("data", []) or []

    async def list_chats_in_project(self, project_id: str) -> list[dict]:
        """Lista chats dentro de um project especifico (paginado)."""
        all_chats: list[dict] = []
        seen: set[str] = set()
        for page in range(1, 200):
            path = f"{API_BASE}/v2/chats/?page={page}&project_id={project_id}"
            resp = await self._fetch(path)
            if not resp.get("success"):
                break
            batch = resp.get("data", []) or []
            if not batch:
                break
            new = 0
            for c in batch:
                cid = c.get("id")
                if cid and cid not in seen:
                    seen.add(cid)
                    all_chats.append(c)
                    new += 1
            if new == 0:
                break
        return all_chats

    async def list_project_files(self, project_id: str) -> list[dict]:
        """Lista files anexados a um project (sources/knowledge)."""
        try:
            resp = await self._fetch(f"{API_BASE}/v2/projects/{project_id}/files")
            if not resp.get("success"):
                return []
            data = resp.get("data", {})
            return data.get("files", []) or []
        except Exception:
            return []

    async def list_all_chats(self) -> list[dict]:
        """Pagina ate retorno vazio. Inclui chats fora de project + dentro de cada project.

        /api/v2/chats/?page=N sem project_id filter retorna SO chats fora de project.
        Pra pegar chats em projects, precisa iterar projects e chamar com ?project_id=X.
        """
        all_chats: list[dict] = []
        seen: set[str] = set()
        # 1) Chats fora de project
        for page in range(1, 200):
            batch = await self.list_chats_page(page, include_projects=True)
            if not batch:
                break
            new = 0
            for c in batch:
                cid = c.get("id")
                if cid and cid not in seen:
                    seen.add(cid)
                    all_chats.append(c)
                    new += 1
            if new == 0:
                break
        # 2) Chats dentro de cada project
        projects = await self.list_projects()
        for proj in projects:
            pid = proj.get("id")
            if not pid:
                continue
            try:
                proj_chats = await self.list_chats_in_project(pid)
                for c in proj_chats:
                    cid = c.get("id")
                    if cid and cid not in seen:
                        seen.add(cid)
                        all_chats.append(c)
            except Exception as e:
                print(f"  warn: list project={pid[:8]} failed: {str(e)[:100]}")
        # 3) Pinned
        try:
            pinned_resp = await self._fetch(f"{API_BASE}/v2/chats/pinned")
            for c in pinned_resp.get("data", []) or []:
                cid = c.get("id")
                if cid and cid not in seen:
                    seen.add(cid)
                    all_chats.append(c)
        except Exception as e:
            print(f"  warn: pinned failed: {str(e)[:100]}")
        return all_chats

    async def fetch_conversation(self, conv_id: str) -> dict:
        """Fetch completo. Retorna envelope inteiro (success + data)."""
        path = f"{API_BASE}/v2/chats/{conv_id}"
        return await self._fetch(path)

    async def list_projects(self) -> list[dict]:
        try:
            resp = await self._fetch(f"{API_BASE}/v2/projects/")
            return resp.get("data", []) or []
        except Exception:
            return []

    async def warmup(self):
        await self.page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        await self.page.wait_for_timeout(3000)
        await self._load_token()
