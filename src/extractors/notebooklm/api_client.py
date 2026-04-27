"""Client NotebookLM — wraps batchexecute com metodos semanticos.

Os payloads dos rpcids foram observados empiricamente. Se algo quebrar,
investigar no DevTools e ajustar.
"""

from playwright.async_api import BrowserContext

from src.extractors.notebooklm.batchexecute import call_rpc


RPC_LIST_NOTEBOOKS = "wXbhsf"       # "My Notebooks" — payload [null,1,null,[2]]
RPC_LIST_FEATURED = "ub2Bae"        # Featured/Explore (sample notebooks) — payload [[2]]
RPC_METADATA = "rLM1Ne"              # metadata basica + sources list
RPC_GUIDE = "VfAZjd"                 # guide (summary + questoes)
RPC_CHAT = "khqZz"                   # chat history
RPC_NOTES = "cFji9"                  # notes + briefs + mind map UUIDs
RPC_ARTIFACTS = "gArtLc"             # lista TODOS os artifacts (audio, video, slide deck, blog, flashcards, quiz, data table, infographic)
RPC_ARTIFACT_FETCH = "v9rmvd"        # fetch individual de artifact (flashcards, quiz, blog, data table, etc) por UUID
RPC_MIND_MAP_FETCH = "CYK0Xb"        # fetch mind map estrutura (arvore JSON)
RPC_SOURCE_CONTENT = "hizoJc"        # source content extraido
RPC_MIND_MAP_UUID = "hPTbtc"         # mind map UUID (legacy — hoje tambem em cFji9)

# Alias retrocompat
RPC_AUDIOS = RPC_ARTIFACTS
RPC_MIND_MAP = RPC_MIND_MAP_UUID


class NotebookLMClient:
    def __init__(self, context: BrowserContext, session: dict, hl: str = "en"):
        """hl: 'en' pra conta hello, 'pt-BR' pra marloon (afeta labels de metadata)."""
        self.context = context
        self.session = session
        self.hl = hl
        self._reqid = 0

    def _next_reqid(self) -> int:
        self._reqid += 1
        return self._reqid

    async def _call(self, rpcid: str, payload, source_path: str | None = None):
        return await call_rpc(
            self.context, self.session, rpcid, payload,
            reqid=self._next_reqid(), source_path=source_path, hl=self.hl,
        )

    # --- Discovery ---

    async def list_notebooks(self) -> list[dict]:
        """Lista 'My Notebooks' via wXbhsf. Payload [null,1,null,[2]] = todos.

        Extrai timestamps de nb[5][5] (update) e nb[5][8] (create) — formato
        [epoch_seconds, nanos]. Sao usados pelo reconciler pra decidir refetch.
        """
        data = await self._call(RPC_LIST_NOTEBOOKS, [None, 1, None, [2]])
        if not data or not isinstance(data, list):
            return []
        notebooks = data[0] if isinstance(data[0], list) else []
        parsed = []
        for nb in notebooks:
            if not isinstance(nb, list) or len(nb) < 3:
                continue
            title = nb[0] if isinstance(nb[0], str) else ""
            uuid = nb[2] if len(nb) > 2 and isinstance(nb[2], str) else None
            if not uuid:
                continue
            # Timestamps em nb[5] — lista de atributos do notebook
            update_time = None
            create_time = None
            if len(nb) > 5 and isinstance(nb[5], list):
                attrs = nb[5]
                if len(attrs) > 5 and isinstance(attrs[5], list) and len(attrs[5]) >= 1:
                    update_time = attrs[5][0]  # epoch seconds
                if len(attrs) > 8 and isinstance(attrs[8], list) and len(attrs[8]) >= 1:
                    create_time = attrs[8][0]
            parsed.append({
                "uuid": uuid,
                "title": title,
                "emoji": nb[3] if len(nb) > 3 and isinstance(nb[3], str) else "",
                "update_time": update_time,
                "create_time": create_time,
                "raw": nb,
            })
        return parsed

    # --- Per-notebook fetches ---

    async def fetch_metadata(self, notebook_uuid: str) -> dict | None:
        """rLM1Ne — metadata + sources list."""
        return await self._call(
            RPC_METADATA, [notebook_uuid, None, [2], None, 0],
            source_path=f"/notebook/{notebook_uuid}",
        )

    async def fetch_guide(self, notebook_uuid: str) -> dict | None:
        """VfAZjd — guide (summary + sugestao de perguntas)."""
        return await self._call(
            RPC_GUIDE, [notebook_uuid, [2]],
            source_path=f"/notebook/{notebook_uuid}",
        )

    async def fetch_chat(self, notebook_uuid: str) -> dict | None:
        """khqZz — chat history."""
        return await self._call(
            RPC_CHAT, [notebook_uuid, None, None, [2]],
            source_path=f"/notebook/{notebook_uuid}",
        )

    async def fetch_notes(self, notebook_uuid: str) -> dict | None:
        """cFji9 — notes + briefs."""
        return await self._call(
            RPC_NOTES, [notebook_uuid, None, None, [2]],
            source_path=f"/notebook/{notebook_uuid}",
        )

    async def fetch_artifacts(self, notebook_uuid: str) -> dict | None:
        """gArtLc — lista TODOS os artifacts do notebook:
        type=1 Audio Overview, type=2 Blog/Report, type=3 Video Overview (mp4),
        type=4 Flashcards/Quiz, type=7 Data Table, type=8 Slide Deck (PDF+PPTX),
        type=9 Infographic.
        """
        payload = [
            [2, None, None,
             [1, None, None, None, None, None, None, None, None, None, [1]],
             [[1, 4, 2, 3, 6]]],
            notebook_uuid,
            'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"',
        ]
        return await self._call(
            RPC_ARTIFACTS, payload,
            source_path=f"/notebook/{notebook_uuid}",
        )

    # Retro-compat
    fetch_audios = fetch_artifacts

    async def fetch_artifact(self, notebook_uuid: str, artifact_uuid: str) -> dict | None:
        """v9rmvd — fetch conteudo de um artifact (texto, JSON etc) por UUID.

        Usado pra types 2, 4, 7, 9 que nao tem URL direta de binario —
        conteudo vem no response. Response inclui titulo, sources e texto/json.
        """
        payload = [
            artifact_uuid,
            [2, None, None,
             [1, None, None, None, None, None, None, None, None, None, [1]],
             [[1, 4, 2, 3, 6, 5]]],
        ]
        return await self._call(
            RPC_ARTIFACT_FETCH, payload,
            source_path=f"/notebook/{notebook_uuid}",
        )

    async def fetch_mind_map_tree(self, notebook_uuid: str, mind_map_uuid: str) -> dict | None:
        """CYK0Xb — fetch a arvore JSON do mind map (nodes + children)."""
        payload = [mind_map_uuid]
        return await self._call(
            RPC_MIND_MAP_FETCH, payload,
            source_path=f"/notebook/{notebook_uuid}",
        )

    async def fetch_mind_map(self, notebook_uuid: str) -> dict | None:
        """hPTbtc — legacy (so retornava UUID). Hoje mind map UUID vem em cFji9.
        Mantido por retrocompat.
        """
        return await self._call(
            RPC_MIND_MAP_UUID, [[], None, notebook_uuid, 20],
            source_path=f"/notebook/{notebook_uuid}",
        )

    async def fetch_source_content(self, notebook_uuid: str, source_uuid: str) -> dict | None:
        """hizoJc — source content (texto extraido + URLs de paginas renderizadas).

        Retorna o payload bruto. Parse da estrutura fica em asset_downloader/fetcher.
        """
        return await self._call(
            RPC_SOURCE_CONTENT, [[source_uuid], [2], [2]],
            source_path=f"/notebook/{notebook_uuid}",
        )

    # --- Asset download ---

    async def download_asset(self, url: str, timeout_ms: int = 120000) -> bytes | None:
        """Baixa binario (audio/page image) via fetch direto. Usa cookies do context.

        URLs do tipo lh3.googleusercontent.com/notebooklm/{token} redirecionam 2x
        ate chegar em googlevideo.com/videoplayback (audio) ou conteudo final.
        Timeout 120s pra audios grandes.
        """
        clean = url.replace("\\u003d", "=").replace("\\u0026", "&")
        resp = await self.context.request.get(clean, timeout=timeout_ms)
        if not resp.ok:
            return None
        return await resp.body()
