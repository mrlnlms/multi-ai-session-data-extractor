"""Probe targetado: chama MaZiqc (list) e hNvQHb (fetch) direto com context.request.

Estrategia:
  1. Abre a pagina Gemini (ganha cookies + sessao)
  2. Extrai token XSRF (at) e build label (bl) do codigo JS da pagina
  3. Chama MaZiqc com paginacao iterativa pra listar TODAS as convs
  4. Chama hNvQHb com uma conv_id real pra validar fetch

Saida em .tmp/gemini-core-probe-<ts>.json
"""

import asyncio
import json
import re
import urllib.parse
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright


GEMINI_URL = "https://gemini.google.com/app"
BATCH_URL = "https://gemini.google.com/_/BardChatUi/data/batchexecute"


def _parse_batchexecute_response(raw: bytes) -> list:
    """Parse do formato `)]}'` + length-prefixed chunks.

    Google batchexecute envelope:
      )]}'
      <len>
      [["wrb.fr","<rpcid>","<JSON-inside-string>",null,null,null,"generic"], ...]

    Retorna lista de blocos [rpcid, inner_json_parsed] com inner ja parseado.
    """
    text = raw.decode("utf-8", errors="replace")
    if text.startswith(")]}'"):
        text = text[4:].lstrip()
    # Split em chunks: cada chunk comeca com um numero de tamanho
    # Estrategia simples: parse ate achar JSON valido, pula ate proximo bloco
    results = []
    pos = 0
    while pos < len(text):
        # pula whitespace
        while pos < len(text) and text[pos] in "\r\n \t":
            pos += 1
        if pos >= len(text):
            break
        # Le um numero (length hint)
        m = re.match(r"\d+", text[pos:])
        if not m:
            break
        pos += len(m.group()) + 1  # +1 pelo \n
        # Tenta parse JSON a partir daqui
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
        # block e lista tipo [["wrb.fr", rpcid, inner_json_as_string, ...], ...]
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


async def _get_session_params(page) -> dict:
    """Extrai SNlM0e (at), cfb2h (bl build label), session_id etc do HTML."""
    html = await page.content()
    params = {}
    # XSRF token
    m = re.search(r'"SNlM0e":"([^"]+)"', html)
    if m:
        params["at"] = m.group(1)
    # Build label
    m = re.search(r'"cfb2h":"([^"]+)"', html)
    if m:
        params["bl"] = m.group(1)
    # Session id (FdrFJe ou similar)
    m = re.search(r'"FdrFJe":"(-?\d+)"', html)
    if m:
        params["f_sid"] = m.group(1)
    return params


async def _call_rpc(request_ctx, rpcid: str, payload: list, session: dict) -> tuple[list, bytes]:
    """Chama um rpcid com payload via batchexecute. Retorna (blocos, raw_body)."""
    # Google e picky com formatting — sem espacos, matching o UI verbatim
    sep = (",", ":")
    payload_str = json.dumps(payload, separators=sep)
    f_req = json.dumps([[[rpcid, payload_str, None, "generic"]]], separators=sep)
    body = urllib.parse.urlencode({
        "f.req": f_req,
        "at": session.get("at", ""),
    })

    url = BATCH_URL + "?rpcids=" + rpcid
    if session.get("bl"):
        url += "&bl=" + session["bl"]
    if session.get("f_sid"):
        url += "&f.sid=" + session["f_sid"]
    url += "&source-path=/app&hl=en&_reqid=12345&rt=c"

    resp = await request_ctx.post(
        url,
        headers={
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Same-Domain": "1",
        },
        data=body,
    )
    raw = await resp.body()
    if not resp.ok:
        print(f"  ERR {resp.status}: {raw[:200]}")
        return [], raw
    return _parse_batchexecute_response(raw), raw


async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            ".storage/gemini-profile-1",
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        print("Carregando Gemini home...")
        await page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)

        session = await _get_session_params(page)
        print(f"Session params: at={session.get('at', '?')[:20]}..., bl={session.get('bl', '?')}, f_sid={session.get('f_sid', '?')}")
        if not session.get("at"):
            print("ERRO: nao consegui extrair SNlM0e (XSRF token)")
            await context.close()
            return

        request_ctx = context.request

        # === LIST CONVS via MaZiqc ===
        # Payload observado: [13, null, [1, null, 1]]
        # Vamos iterar diferentes pages pra entender paginacao
        print("\n=== Testing MaZiqc (list) ===")
        collected_convs = []
        results_first, raw_first = await _call_rpc(
            request_ctx, "MaZiqc", [13, None, [1, None, 1]], session
        )
        print(f"  Retornou {len(results_first)} blocos")
        print(f"  Raw size: {len(raw_first)}B, preview:")
        print(f"  {raw_first[:600].decode('utf-8', errors='replace')}")
        for r in results_first:
            if r["rpcid"] == "MaZiqc" and r["data"]:
                d = r["data"]
                print(f"  data estrutura: len={len(d)}, tipos top: {[type(x).__name__ for x in d[:5]]}")
                # data[2] parece ter a lista de convs: [[conv_id, title, ...]]
                if len(d) > 2 and isinstance(d[2], list):
                    for c in d[2]:
                        if isinstance(c, list) and len(c) >= 2:
                            collected_convs.append({
                                "uuid": c[0],
                                "title": c[1],
                                "created_at_secs": c[5][0] if (len(c) > 5 and isinstance(c[5], list)) else None,
                            })
                # Se tem paginacao, data[1] pode ser cursor/token
                d1_preview = d[1] if not isinstance(d[1], str) or len(d[1]) < 80 else d[1][:80] + '...'
                print(f"  data[0]: {d[0]!r}, data[1]: {d1_preview!r}")
        print(f"  Coletadas {len(collected_convs)} convs no 1o batch")
        for c in collected_convs[:3]:
            print(f"    {c['uuid']}: {c['title'][:50]!r}")

        # === FETCH CONV via hNvQHb ===
        if collected_convs:
            target = collected_convs[0]["uuid"]
            print(f"\n=== Testing hNvQHb (fetch) pra {target} ===")
            # Payload observado: [conv_id, 10, null, 1, [0], [4], null, 1]
            results_fetch, _ = await _call_rpc(
                request_ctx, "hNvQHb", [target, 10, None, 1, [0], [4], None, 1], session
            )
            for r in results_fetch:
                if r["rpcid"] == "hNvQHb" and r["data"]:
                    d = r["data"]
                    print(f"  data estrutura top-level: len={len(d)}")
                    if len(d) > 0 and isinstance(d[0], list):
                        turns = d[0]
                        print(f"  Turns encontrados: {len(turns)}")
                        # Primeiro turn estrutura
                        if turns:
                            t = turns[0]
                            print(f"  turn[0] keys len: {len(t)}")
                            # Captura alguns campos uteis
                            print(f"  turn[0][0] (ids?): {t[0]!r}")

        # Salva tudo
        report = {
            "ts": datetime.now().isoformat(),
            "session": {k: (v[:40] + '...' if isinstance(v, str) and len(v) > 40 else v) for k, v in session.items()},
            "first_batch_convs": collected_convs,
            "maziqc_first_raw": results_first[0]["data"] if results_first else None,
        }
        outp = Path(".tmp") / f"gemini-core-{datetime.now():%Y%m%dT%H%M%S}.json"
        outp.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        print(f"\nRelatorio em {outp}")

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
