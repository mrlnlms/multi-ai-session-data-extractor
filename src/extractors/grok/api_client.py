"""Client Grok - wraps /rest/* via page.evaluate(fetch).

Endpoints confirmados via probe 2026-05-09 (ver docs/platforms/grok/recon.md):
  GET  /rest/app-chat/conversations?pageSize=N[&pageToken=T][&workspaceId=ID]
  GET  /rest/app-chat/conversations_v2/{cid}?includeWorkspaces=true&includeTaskResult=true
  GET  /rest/app-chat/conversations/{cid}/response-node?includeThreads=true
  POST /rest/app-chat/conversations/{cid}/load-responses  body: {responseIds: [...]}
  GET  /rest/conversations/files/list?conversationId={cid}&path=%2F
  GET  /rest/app-chat/share_links?pageSize=N&conversationId={cid}
  GET  /rest/workspaces?pageSize=N&orderBy=ORDER_BY_LAST_USE_TIME
  GET  /rest/workspaces/{wid}
  GET  /rest/assets?pageSize=N&orderBy=ORDER_BY_LAST_USE_TIME

Auth: cookies do profile (sem token em localStorage). fetch via
page.evaluate envia cookies automaticamente.
"""

import json
from urllib.parse import quote

from playwright.async_api import BrowserContext, Page


HOME_URL = "https://grok.com/"


class GrokAPIClient:
    def __init__(self, context: BrowserContext, page: Page):
        self.context = context
        self.page = page

    async def warmup(self):
        await self.page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        await self.page.wait_for_timeout(2000)

    async def _fetch(self, path: str, method: str = "GET", body: dict | None = None) -> dict:
        script = """async ({path, method, body}) => {
            const opts = {method, credentials: 'include', headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }};
            if (body !== null) opts.body = JSON.stringify(body);
            const res = await fetch(path, opts);
            const text = await res.text();
            return {status: res.status, body: text};
        }"""
        result = await self.page.evaluate(script, {"path": path, "method": method, "body": body})
        if result["status"] != 200:
            raise RuntimeError(f"HTTP {result['status']} on {method} {path}: {result['body'][:300]}")
        try:
            return json.loads(result["body"])
        except Exception as e:
            raise RuntimeError(f"Bad JSON from {path}: {e}: {result['body'][:200]}")

    async def list_conversations_page(
        self, page_size: int = 60, page_token: str | None = None,
        workspace_id: str | None = None, filter_starred: bool = False,
    ) -> dict:
        qs = f"pageSize={page_size}"
        if page_token:
            qs += f"&pageToken={quote(page_token)}"
        if workspace_id:
            qs += f"&workspaceId={workspace_id}"
        if filter_starred:
            qs += "&filterIsStarred=true"
        return await self._fetch(f"/rest/app-chat/conversations?{qs}")

    async def list_all_conversations(self, page_size: int = 60) -> list[dict]:
        """Pagina ate fim. Inclui convs em workspaces (campo 'workspaces' populado)."""
        all_convs: list[dict] = []
        seen: set[str] = set()
        token: str | None = None
        for _page in range(1, 500):
            resp = await self.list_conversations_page(page_size, token)
            batch = resp.get("conversations", []) or []
            new = 0
            for c in batch:
                cid = c.get("conversationId")
                if cid and cid not in seen:
                    seen.add(cid)
                    all_convs.append(c)
                    new += 1
            token = resp.get("nextPageToken") or None
            if not token or new == 0:
                break
        return all_convs

    async def get_conversation_v2(self, conv_id: str) -> dict:
        return await self._fetch(
            f"/rest/app-chat/conversations_v2/{conv_id}"
            f"?includeWorkspaces=true&includeTaskResult=true"
        )

    async def get_response_node(self, conv_id: str) -> dict:
        return await self._fetch(
            f"/rest/app-chat/conversations/{conv_id}/response-node?includeThreads=true"
        )

    async def load_responses(self, conv_id: str, response_ids: list[str]) -> dict:
        if not response_ids:
            return {"responses": []}
        return await self._fetch(
            f"/rest/app-chat/conversations/{conv_id}/load-responses",
            method="POST",
            body={"responseIds": response_ids},
        )

    async def list_conv_files(self, conv_id: str) -> dict:
        return await self._fetch(
            f"/rest/conversations/files/list?conversationId={conv_id}&path=%2F"
        )

    async def list_share_links(self, conv_id: str, page_size: int = 100) -> dict:
        return await self._fetch(
            f"/rest/app-chat/share_links?pageSize={page_size}&conversationId={conv_id}"
        )

    async def list_workspaces(self, page_size: int = 50) -> list[dict]:
        all_ws: list[dict] = []
        seen: set[str] = set()
        token: str | None = None
        for _page in range(1, 100):
            qs = f"pageSize={page_size}&orderBy=ORDER_BY_LAST_USE_TIME"
            if token:
                qs += f"&pageToken={quote(token)}"
            resp = await self._fetch(f"/rest/workspaces?{qs}")
            batch = resp.get("workspaces", []) or []
            new = 0
            for w in batch:
                wid = w.get("workspaceId")
                if wid and wid not in seen:
                    seen.add(wid)
                    all_ws.append(w)
                    new += 1
            token = resp.get("nextPageToken") or None
            if not token or new == 0:
                break
        return all_ws

    async def get_workspace(self, workspace_id: str) -> dict:
        return await self._fetch(f"/rest/workspaces/{workspace_id}")

    async def list_assets(self, page_size: int = 100) -> list[dict]:
        all_assets: list[dict] = []
        seen: set[str] = set()
        token: str | None = None
        for _page in range(1, 200):
            qs = f"pageSize={page_size}&orderBy=ORDER_BY_LAST_USE_TIME"
            if token:
                qs += f"&pageToken={quote(token)}"
            resp = await self._fetch(f"/rest/assets?{qs}")
            batch = resp.get("assets", []) or []
            new = 0
            for a in batch:
                aid = a.get("assetId")
                if aid and aid not in seen:
                    seen.add(aid)
                    all_assets.append(a)
                    new += 1
            token = resp.get("nextPageToken") or None
            if not token or new == 0:
                break
        return all_assets

    async def list_scheduled_tasks(self) -> dict:
        """Tasks (scheduled queries) ativas + inativas + usage.

        Schema: {tasks: [...], unreadResults: [...], unreadCounts: [...],
        taskUsage: {usage, limit, frequentUsage, frequentLimit, ...}} +
        inactive_tasks: [...] (do endpoint /rest/tasks/inactive).
        """
        active = await self._fetch("/rest/tasks")
        try:
            inactive = await self._fetch("/rest/tasks/inactive")
            inactive_list = inactive.get("tasks", []) or []
        except Exception:
            inactive_list = []
        return {
            "active": active.get("tasks", []) or [],
            "inactive": inactive_list,
            "unread_results": active.get("unreadResults", []) or [],
            "unread_counts": active.get("unreadCounts", []) or [],
            "usage": active.get("taskUsage") or {},
        }

    async def fetch_full_conversation(self, conv_id: str) -> dict:
        """Agrega meta + tree + responses + files + share_links em um envelope."""
        meta = await self.get_conversation_v2(conv_id)
        tree = await self.get_response_node(conv_id)
        response_ids = [n["responseId"] for n in (tree.get("responseNodes") or []) if n.get("responseId")]
        responses = await self.load_responses(conv_id, response_ids) if response_ids else {"responses": []}
        try:
            files = await self.list_conv_files(conv_id)
        except Exception as e:
            files = {"_error": str(e)[:200]}
        try:
            share_links = await self.list_share_links(conv_id)
        except Exception as e:
            share_links = {"_error": str(e)[:200]}
        return {
            "conversation_v2": meta,
            "response_node": tree,
            "responses": responses,
            "files": files,
            "share_links": share_links,
        }
