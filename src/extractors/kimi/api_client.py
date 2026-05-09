"""Client Kimi - wraps /apiv2/* (gRPC-Web/Connect) via page.evaluate(fetch).

Endpoints confirmados via probe 2026-05-09 (ver docs/platforms/kimi/recon.md):
  POST /apiv2/kimi.chat.v1.ChatService/ListChats     body {pageSize, pageToken?}
  POST /apiv2/kimi.chat.v1.ChatService/GetChat       body {chatId}
  POST /apiv2/kimi.chat.v1.ChatService/ListMessages  body {chatId}

Auth: cookies + `Authorization: Bearer <access_token>` (token em
localStorage.access_token, ~563 chars JWT-like). Cookies sozinhos
retornam 401.
"""

import json

from playwright.async_api import BrowserContext, Page


HOME_URL = "https://www.kimi.com/"
API_BASE = "/apiv2"


class KimiAPIClient:
    def __init__(self, context: BrowserContext, page: Page):
        self.context = context
        self.page = page
        self.token: str | None = None

    async def warmup(self):
        await self.page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        await self.page.wait_for_timeout(2000)
        await self._load_token()

    async def _load_token(self) -> None:
        tok = await self.page.evaluate("localStorage.getItem('access_token')")
        if not tok:
            raise RuntimeError(
                "access_token nao encontrado em localStorage. "
                "Profile pode estar deslogado — rode scripts/kimi-login.py"
            )
        self.token = tok

    async def _post(self, path: str, body: dict | None = None) -> dict:
        if self.token is None:
            await self._load_token()
        body = body or {}
        result = await self.page.evaluate(
            """async ({path, body, token}) => {
                const r = await fetch(path, {
                    method: 'POST', credentials: 'include',
                    headers: {
                        'content-type': 'application/json',
                        'authorization': 'Bearer ' + token,
                    },
                    body: JSON.stringify(body),
                });
                const text = await r.text();
                return {status: r.status, body: text};
            }""",
            {"path": path, "body": body, "token": self.token},
        )
        if result["status"] != 200:
            raise RuntimeError(
                f"HTTP {result['status']} on POST {path}: {result['body'][:300]}"
            )
        try:
            return json.loads(result["body"])
        except Exception as e:
            raise RuntimeError(f"Bad JSON from {path}: {e}: {result['body'][:200]}")

    async def list_chats_page(
        self, page_size: int = 100, page_token: str | None = None
    ) -> dict:
        body: dict = {"pageSize": page_size}
        if page_token:
            body["pageToken"] = page_token
        return await self._post(f"{API_BASE}/kimi.chat.v1.ChatService/ListChats", body)

    async def list_all_chats(self, page_size: int = 100) -> list[dict]:
        all_chats: list[dict] = []
        seen: set[str] = set()
        token: str | None = None
        for _page in range(1, 500):
            resp = await self.list_chats_page(page_size, token)
            batch = resp.get("chats", []) or []
            new = 0
            for c in batch:
                cid = c.get("id")
                if cid and cid not in seen:
                    seen.add(cid)
                    all_chats.append(c)
                    new += 1
            token = resp.get("nextPageToken") or None
            if not token or new == 0:
                break
        return all_chats

    async def get_chat(self, chat_id: str) -> dict:
        return await self._post(
            f"{API_BASE}/kimi.chat.v1.ChatService/GetChat", {"chatId": chat_id}
        )

    async def list_messages(self, chat_id: str) -> dict:
        return await self._post(
            f"{API_BASE}/kimi.chat.v1.ChatService/ListMessages",
            {"chatId": chat_id},
        )

    async def fetch_full_chat(self, chat_id: str) -> dict:
        meta = await self.get_chat(chat_id)
        msgs = await self.list_messages(chat_id)
        return {
            "chat": meta.get("chat") or meta,
            "messages": msgs.get("messages") or [],
        }

    async def list_official_skills(self) -> dict:
        return await self._post(
            f"{API_BASE}/kimi.gateway.skill.v1.SkillService/ListOfficialSkills"
        )

    async def list_installed_skills(self) -> dict:
        return await self._post(
            f"{API_BASE}/kimi.gateway.skill.v1.SkillService/ListInstalledSkills"
        )
