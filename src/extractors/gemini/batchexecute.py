"""Helpers pra falar com o endpoint batchexecute do Gemini.

Formato Google batchexecute:
  POST body: f.req=<JSON-encoded>&at=<XSRF_TOKEN>
  Response: )]}'\\n<length>\\n<JSON>\\n<length>\\n<JSON>\\n...

O JSON interno e um array de "response blocks", cada bloco:
  ["wrb.fr", "<rpcid>", "<inner_json_as_string>", null, null, null, "generic"]
"""

import json
import re
import urllib.parse
from typing import Any

from playwright.async_api import BrowserContext


BASE_URL = "https://gemini.google.com"
BATCH_URL = f"{BASE_URL}/_/BardChatUi/data/batchexecute"
HOME_URL = f"{BASE_URL}/app"


async def extract_session_params(page) -> dict:
    """Extrai at (SNlM0e), bl (cfb2h) e f.sid (FdrFJe) do HTML da pagina.

    Page precisa estar ja carregada em /app ou similar. Retorna dict com
    chaves at, bl, f_sid — at e obrigatorio, outros sao opcionais.
    """
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
            "Nao consegui extrair SNlM0e (XSRF token) do HTML do Gemini. "
            "Sessao pode estar expirada — rode scripts/gemini-login.py"
        )
    return params


async def load_session(context: BrowserContext) -> dict:
    """Carrega /app em uma page temp e extrai session params."""
    page = await context.new_page()
    try:
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2000)
        return await extract_session_params(page)
    finally:
        await page.close()


def parse_response(raw: bytes) -> list[dict]:
    """Parse do envelope batchexecute. Retorna lista de {rpcid, data}.

    data ja vem parseado do JSON interno (string escapada).
    """
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
        pos += len(m.group()) + 1  # +1 pelo newline

        # Extrai o proximo array JSON (bracket-matched, respeitando strings)
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

        # block = [["wrb.fr", rpcid, inner_json_str, null, null, null, "generic"], ...]
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
) -> dict | None:
    """Chama um rpcid com payload via batchexecute. Retorna data do bloco ou None se erro.

    Google e picky com JSON formatting — usa separators=(',', ':') pra bater com o UI.
    """
    sep = (",", ":")
    payload_str = json.dumps(payload, separators=sep)
    f_req = json.dumps([[[rpcid, payload_str, None, "generic"]]], separators=sep)
    body = urllib.parse.urlencode({"f.req": f_req, "at": session["at"]})

    url = f"{BATCH_URL}?rpcids={rpcid}&source-path=/app&hl=en&rt=c&_reqid={reqid}"
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
    # Retorna data do primeiro bloco que casa com rpcid
    for b in blocks:
        if b["rpcid"] == rpcid:
            return b["data"]
    return None
