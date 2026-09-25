"""Client Gemini — wraps batchexecute com metodos semanticos.

Uso:
  context = await load_context(account=1)
  session = await load_session(context)
  client = GeminiAPIClient(context, session)
  convs = await client.list_conversations()
  conv = await client.fetch_conversation(conv_id)
"""

import re
from typing import Iterator

from playwright.async_api import BrowserContext

from src.platforms.gemini.extractor.batchexecute import call_rpc, load_session


# rpcids confirmados empiricamente 24/abr/2026
RPC_LIST = "MaZiqc"
RPC_FETCH = "hNvQHb"
RPC_INSTRUCTIONS = "ZKcapf"


class GeminiAPIClient:
    def __init__(self, context: BrowserContext, session: dict):
        self.context = context
        self.session = session
        self._reqid = 0

    def _next_reqid(self) -> int:
        self._reqid += 1
        return self._reqid

    async def refresh_session(self):
        """Re-extrai session params (XSRF pode expirar em runs longos)."""
        self.session = await load_session(self.context)

    async def list_conversations(self) -> list[dict]:
        """Lista TODAS as convs da conta. Payload vazio retorna lista inteira.

        Retorna [{uuid, title, created_at_epoch_secs, created_at_nanos, raw}, ...]
        """
        data = await call_rpc(
            self.context, self.session, RPC_LIST, [], reqid=self._next_reqid()
        )
        if not data or not isinstance(data, list):
            return []
        # Schema observado (10 fields por conv):
        #   [0]=conv_id, [1]=title, [2]=pinned (True ou None),
        #   [5]=[secs, nanos], [9]=int (sempre 2 nos casos vistos)
        # Confirmado empirico em 2026-05-02 via probe pin-share.
        convs_raw = data[2] if len(data) > 2 and isinstance(data[2], list) else []
        parsed = []
        for c in convs_raw:
            if not isinstance(c, list) or len(c) < 2:
                continue
            ts = c[5] if len(c) > 5 and isinstance(c[5], list) else [None, None]
            pinned = bool(c[2]) if len(c) > 2 else False
            parsed.append({
                "uuid": c[0],
                "title": c[1] or "",
                "pinned": pinned,
                "created_at_secs": ts[0] if len(ts) > 0 else None,
                "created_at_nanos": ts[1] if len(ts) > 1 else None,
                "raw": c,
            })
        return parsed

    async def fetch_conversation(self, conv_uuid: str) -> dict | None:
        """Fetch arvore completa de uma conv. Retorna dict com raw data.

        Inclui turns com user+model messages + image URLs embedded.
        """
        # Payload observado (funcional): [conv_id, 10, null, 1, [0], [4], null, 1]
        payload = [conv_uuid, 10, None, 1, [0], [4], None, 1]
        data = await call_rpc(
            self.context, self.session, RPC_FETCH, payload, reqid=self._next_reqid()
        )
        if data is None:
            return None
        return {"uuid": conv_uuid, "raw": data}

    async def list_instructions(self) -> list:
        """Return the native account-level Instructions response.

        The payload was observed on the ``/saved-info`` surface.  Keep the
        positional response intact here; parsing and durable persistence are
        separate concerns.
        """
        data = await call_rpc(
            self.context,
            self.session,
            RPC_INSTRUCTIONS,
            [100],
            reqid=self._next_reqid(),
        )
        validate_instructions_envelope(data)
        return data


    async def download_asset(self, url: str) -> bytes | None:
        """Baixa binario de uma URL (lh3.googleusercontent.com / gstatic).

        Retorna None em HTTP error. Context cookies sao enviados se necessario.
        """
        # Limpa escapes eventuais
        clean = url.replace("\\u003d", "=").replace("\\u0026", "&")
        resp = await self.context.request.get(clean)
        if not resp.ok:
            return None
        return await resp.body()


def validate_instructions_envelope(data: object) -> list[list]:
    """Accept only an observed, complete Instructions list shape.

    ``None`` or a changed RPC shape must not become an empty observation: that
    would incorrectly mark previously captured instructions as removed.
    """
    if data == []:
        return []
    if not isinstance(data, list) or len(data) != 2 or not isinstance(data[0], list):
        raise ValueError("Unexpected Gemini Instructions response shape")
    items = data[0]
    if not items or len(items) >= 100 or not isinstance(data[1], str):
        raise ValueError("Incomplete Gemini Instructions response")
    seen: set[str] = set()
    for item in items:
        if (not isinstance(item, list) or len(item) < 11
                or not isinstance(item[0], str) or not item[0]
                or not isinstance(item[1], str)
                or item[0] in seen):
            raise ValueError("Malformed Gemini Instructions item")
        for index in (2, 4):
            value = item[index]
            if (not isinstance(value, list) or len(value) != 2
                    or any(not isinstance(part, int) or isinstance(part, bool) for part in value)):
                raise ValueError("Malformed Gemini Instructions timestamp")
        seen.add(item[0])
    return items


IMAGE_URL_RE = re.compile(
    r'https://[^"\\,\s\'<>]+(?:googleusercontent|gstatic)[^"\\,\s\'<>]*'
)

# Padroes excluidos: favicons (decoracao, nao conteudo), logos de produto
EXCLUDE_PATTERNS = [
    "faviconV2",         # t0-t3.gstatic.com/faviconV2?url=... — favicons de citacoes
    "/lamda/images/",    # logos de tools (SynthID etc)
    "/branding/",        # logos Google (calendar, keep etc)
    "fonts.gstatic.com", # CSS fonts
]


def extract_image_urls(raw_data) -> list[str]:
    """Extrai URLs de imagem de CONTEUDO (user uploads + model generated).

    Exclui favicons de citacoes e logos de produtos. Retorna URLs unicos
    preservando ordem.
    """
    import json as _json
    serialized = _json.dumps(raw_data, ensure_ascii=False)
    urls = IMAGE_URL_RE.findall(serialized)
    seen: set[str] = set()
    result: list[str] = []
    for u in urls:
        clean = u.replace("\\u003d", "=").replace("\\u0026", "&")
        if any(pat in clean for pat in EXCLUDE_PATTERNS):
            continue
        if clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result
