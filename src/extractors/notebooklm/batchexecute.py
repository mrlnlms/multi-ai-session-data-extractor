"""Helpers pra falar com /_/LabsTailwindUi/data/batchexecute do NotebookLM.

Mesmo protocolo Google batchexecute do Gemini, mas URL base diferente.
"""

import json
import re
import urllib.parse
from typing import Any

from playwright.async_api import BrowserContext


BASE_URL = "https://notebooklm.google.com"
BATCH_URL = f"{BASE_URL}/_/LabsTailwindUi/data/batchexecute"


async def extract_session_params(page) -> dict:
    """Extrai at (SNlM0e), bl (cfb2h) e f.sid (FdrFJe) do HTML."""
    html = await page.content()
    params: dict[str, str] = {}
    for key, pat in [
        ("at", r'"SNlM0e":"([^"]+)"'),
        ("bl", r'"cfb2h":"([^"]+)"'),
        ("f_sid", r'"FdrFJe":"(-?\d+)"'),
    ]:
        m = re.search(pat, html)
        if m:
            params[key] = m.group(1)
    if "at" not in params:
        raise RuntimeError(
            "Nao consegui extrair SNlM0e do HTML NotebookLM. "
            "Sessao pode ter expirado — rode scripts/notebooklm-login.py"
        )
    return params


async def load_session(context: BrowserContext, notebook_uuid: str | None = None) -> dict:
    """Carrega pagina e extrai session params. Use notebook_uuid pra call RPCs scoped."""
    path = f"/notebook/{notebook_uuid}" if notebook_uuid else "/"
    url = f"{BASE_URL}{path}"
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        return await extract_session_params(page)
    finally:
        await page.close()


def parse_response(raw: bytes) -> list[dict]:
    """Parse envelope batchexecute. Retorna [{rpcid, data}, ...]."""
    text = raw.decode("utf-8", errors="replace")
    if text.startswith(")]}'"):
        text = text[4:].lstrip()

    results: list[dict] = []
    pos = 0
    while pos < len(text):
        while pos < len(text) and text[pos] in "\r\n \t":
            pos += 1
        if pos >= len(text):
            break
        m = re.match(r"\d+", text[pos:])
        if not m:
            break
        pos += len(m.group()) + 1

        depth = 0
        start = pos
        in_str = False
        esc = False
        while pos < len(text):
            ch = text[pos]
            if esc:
                esc = False
            elif ch == "\\" and in_str:
                esc = True
            elif ch == '"':
                in_str = not in_str
            elif not in_str:
                if ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        pos += 1
                        break
            pos += 1

        try:
            block = json.loads(text[start:pos])
        except Exception:
            break

        for item in block:
            if isinstance(item, list) and len(item) >= 3 and item[0] == "wrb.fr":
                rpcid = item[1]
                inner_str = item[2]
                try:
                    inner = json.loads(inner_str) if inner_str else None
                except Exception:
                    inner = inner_str
                results.append({"rpcid": rpcid, "data": inner})
    return results


async def call_rpc(
    context: BrowserContext,
    session: dict,
    rpcid: str,
    payload: Any,
    reqid: int = 1,
    source_path: str | None = None,
    hl: str = "en",
) -> Any | None:
    """Chama rpcid com payload. source_path scopa request ex: '/notebook/{uuid}'.

    hl: language param — afeta labels em metadata (ex: audio type names).
        Conteudo do user nao muda com isso.
    """
    sep = (",", ":")
    payload_str = json.dumps(payload, separators=sep)
    f_req = json.dumps([[[rpcid, payload_str, None, "generic"]]], separators=sep)
    body = urllib.parse.urlencode({"f.req": f_req, "at": session["at"]})

    url = f"{BATCH_URL}?rpcids={rpcid}&hl={hl}&rt=c&_reqid={reqid}"
    if source_path:
        url += f"&source-path={urllib.parse.quote(source_path, safe='/')}"
    if session.get("bl"):
        url += f"&bl={session['bl']}"
    if session.get("f_sid"):
        url += f"&f.sid={session['f_sid']}"

    resp = await context.request.post(
        url,
        headers={
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Same-Domain": "1",
        },
        data=body,
    )
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status} calling {rpcid}: {(await resp.text())[:200]}")

    raw = await resp.body()
    blocks = parse_response(raw)
    for b in blocks:
        if b["rpcid"] == rpcid:
            return b["data"]
    return None
