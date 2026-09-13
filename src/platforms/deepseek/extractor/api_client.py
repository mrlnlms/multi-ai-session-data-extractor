"""Client DeepSeek - wraps /api/v0/ via page.evaluate(fetch).

Endpoints confirmados via probe 24/abr/2026:
  GET /api/v0/chat_session/fetch_page?lte_cursor.pinned=false[&lte_cursor.updated_at=X&lte_cursor.id=Y]
  GET /api/v0/chat/history_messages?chat_session_id=<uuid>

Auth: Bearer token vem do localStorage/cookies do SPA, aplicado automaticamente
por fetch() dentro do page context — por isso toda chamada passa por
page.evaluate ao invés de context.request direto.

Envelope padrao da API:
  {"code": 0, "msg": "", "data": {"biz_code": 0, "biz_msg": "", "biz_data": {...}}}

PoW (create_pow_challenge) so e obrigatorio pra completion/upload, nao pra leitura.
"""

import json
from typing import Any

from playwright.async_api import BrowserContext, Page


API_BASE = "https://chat.deepseek.com/api/v0"
HOME_URL = "https://chat.deepseek.com/"


class DeepSeekAPIClient:
    def __init__(self, context: BrowserContext, page: Page):
        self.context = context
        self.page = page
        self.token: str | None = None

    async def _load_token(self):
        """Le localStorage.userToken pra aplicar Bearer em fetch()s."""
        raw = await self.page.evaluate("() => localStorage.getItem('userToken')")
        if not raw:
            raise RuntimeError("localStorage.userToken vazio — profile nao logado?")
        parsed = json.loads(raw)
        self.token = parsed.get("value")
        if not self.token:
            raise RuntimeError(f"userToken sem 'value': {raw[:200]}")

    async def _fetch(self, path: str, method: str = "GET", body: dict | None = None) -> dict:
        """Chama API via page.evaluate(fetch) com Bearer token explicito.

        Retorna biz_data desencapsulado, ou levanta RuntimeError em erro.
        """
        if not self.token:
            await self._load_token()
        script = """async ({path, method, body, token}) => {
            const res = await fetch(path, {
                method,
                headers: {
                    'Content-Type': 'application/json',
                    'authorization': 'Bearer ' + token,
                    'x-client-locale': 'en_US',
                    'x-app-version': '20241129.1',
                    'x-client-version': '1.8.0',
                },
                body: body ? JSON.stringify(body) : undefined,
            });
            const text = await res.text();
            return {status: res.status, body: text};
        }"""
        result = await self.page.evaluate(script, {"path": path, "method": method, "body": body, "token": self.token})
        if result["status"] != 200:
            raise RuntimeError(f"HTTP {result['status']} on {method} {path}: {result['body'][:300]}")
        try:
            parsed = json.loads(result["body"])
        except Exception as e:
            raise RuntimeError(f"Bad JSON from {path}: {e}: {result['body'][:200]}")
        if parsed.get("code") != 0:
            raise RuntimeError(f"API code={parsed.get('code')} msg={parsed.get('msg')}")
        data = parsed.get("data", {})
        if data.get("biz_code") != 0:
            raise RuntimeError(f"biz_code={data.get('biz_code')} biz_msg={data.get('biz_msg')}")
        return data.get("biz_data", {})

    async def list_conversations(self, page_size: int = 100) -> list[dict]:
        """Pagina fetch_page ate esgotar. Retorna todas as sessions.

        Cursor: ultima session do batch -> lte_cursor.updated_at + lte_cursor.id.
        """
        all_sessions: list[dict] = []
        seen: set[str] = set()
        cursor_params: dict[str, Any] | None = None

        while True:
            # Monta path com cursor
            params = ["lte_cursor.pinned=false"]
            if cursor_params:
                for k, v in cursor_params.items():
                    params.append(f"lte_cursor.{k}={v}")
            path = f"{API_BASE}/chat_session/fetch_page?" + "&".join(params)
            biz = await self._fetch(path)
            batch = biz.get("chat_sessions", []) or []
            if not batch:
                break

            new_count = 0
            last = None
            for s in batch:
                sid = s.get("id")
                if not sid or sid in seen:
                    continue
                seen.add(sid)
                all_sessions.append(s)
                last = s
                new_count += 1

            # Se nao veio nada novo, acabou (cursor bugado ou ultima pagina)
            if new_count == 0 or last is None:
                break

            # Avanca cursor pro proximo batch (menor updated_at)
            cursor_params = {"updated_at": last["updated_at"], "id": last["id"]}

            # Safety: se batch veio menor que pagesize esperado, provavelmente ultima pagina
            # DeepSeek API parece retornar ~100 por batch; se retornar <50, provavel fim
            if len(batch) < 20:
                break

        # Tambem pega as pinned (query separada)
        try:
            path_pinned = f"{API_BASE}/chat_session/fetch_page?lte_cursor.pinned=true"
            biz_p = await self._fetch(path_pinned)
            for s in biz_p.get("chat_sessions", []) or []:
                sid = s.get("id")
                if sid and sid not in seen:
                    seen.add(sid)
                    all_sessions.append(s)
        except Exception as e:
            # Se pinned falhar, ok — muitas contas nao tem nada pinado
            print(f"  warn: pinned fetch falhou: {str(e)[:100]}")

        return all_sessions

    async def fetch_conversation(self, conv_id: str) -> dict:
        """Fetch completo de uma conv. Retorna {chat_session, chat_messages}."""
        path = f"{API_BASE}/chat/history_messages?chat_session_id={conv_id}"
        return await self._fetch(path)

    async def warmup(self):
        """Carrega home pra popular cookies/localStorage e permitir fetch() com auth."""
        await self.page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        await self.page.wait_for_timeout(3000)
        await self._load_token()
