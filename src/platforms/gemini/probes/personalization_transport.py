"""Observe Gemini personalization transport without persisting response values.

The probe visits the account-level Personal Intelligence and Instructions
surfaces with an existing authenticated profile.  It records RPC identifiers,
response hashes and recursive container shapes, but never response scalar
values or request bodies.

Usage:
  PYTHONPATH=. .venv/bin/python -m \
    src.platforms.gemini.probes.personalization_transport --account 1
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.async_api import Response, async_playwright

from src.platforms.gemini.extractor.batchexecute import parse_response


SURFACES = (
    "https://gemini.google.com/personalization-settings",
    "https://gemini.google.com/saved-info",
)


def _shape(value, depth: int = 0):
    """Return container dimensions and scalar types, never scalar values."""
    if depth >= 5:
        return type(value).__name__
    if isinstance(value, list):
        samples = []
        seen = set()
        for item in value[:20]:
            shape = _shape(item, depth + 1)
            key = json.dumps(shape, sort_keys=True)
            if key not in seen:
                seen.add(key)
                samples.append(shape)
        return {"type": "list", "length": len(value), "item_shapes": samples}
    if isinstance(value, dict):
        return {
            "type": "dict",
            "keys": sorted(value),
            "value_shapes": {key: _shape(value[key], depth + 1) for key in sorted(value)},
        }
    return type(value).__name__


async def probe(account: str, wait_ms: int) -> Path:
    profile_dir = Path(f".storage/gemini-profile-{account}")
    if not profile_dir.exists():
        raise RuntimeError(f"Gemini profile does not exist: {profile_dir}")

    observations: dict[str, list[dict]] = defaultdict(list)
    surface = ""
    pending: set[asyncio.Task] = set()

    async def observe_response(response: Response, observed_surface: str) -> None:
        if "batchexecute" not in response.url:
            return
        rpcids = parse_qs(urlparse(response.url).query).get("rpcids", [])
        body = await response.body()
        body_text = body.decode("utf-8", errors="replace").lower()
        parsed = parse_response(body)
        parsed_by_rpc = {block["rpcid"]: block["data"] for block in parsed}
        for rpcid_group in rpcids:
            for rpcid in rpcid_group.split(","):
                observations[observed_surface].append(
                    {
                        "rpcid": rpcid,
                        "status": response.status,
                        "response_bytes": len(body),
                        "response_sha256": hashlib.sha256(body).hexdigest(),
                        "semantic_indicators": {
                            "memory": "memory" in body_text,
                            "past_chats": "past chats" in body_text,
                            "saved_info": "saved-info" in body_text,
                        },
                        "data_shape": _shape(parsed_by_rpc.get(rpcid)),
                    }
                )

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(profile_dir),
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()

        def schedule(response: Response) -> None:
            task = asyncio.create_task(observe_response(response, surface))
            pending.add(task)
            task.add_done_callback(pending.discard)

        page.on("response", schedule)
        surface_details = []
        for url in SURFACES:
            surface = url
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(wait_ms)
            links = await page.locator("a").evaluate_all(
                "els => els.map(a => ({text: (a.innerText || '').trim(), href: a.href}))"
            )
            surface_details.append(
                {
                    "surface": url,
                    "final_url": page.url,
                    "title": await page.title(),
                    "relevant_links": [
                        link
                        for link in links
                        if re.search(r"memory|activity|saved|instruction", link["text"], re.I)
                        or re.search(r"activity|saved-info|personalization", link["href"], re.I)
                    ],
                }
            )
        if pending:
            await asyncio.gather(*pending)
        await context.close()

    captured_at = datetime.now(timezone.utc).isoformat()
    report = {
        "captured_at": captured_at,
        "account": account,
        "privacy": "No response scalar values or request bodies persisted.",
        "surfaces": surface_details,
        "rpc_observations": observations,
    }
    outdir = Path(".runtime/probes")
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outpath = outdir / f"gemini-personalization-transport-{stamp}.json"
    outpath.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return outpath


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", default="1", choices=("1", "2", "3"))
    parser.add_argument("--wait-ms", type=int, default=5_000)
    args = parser.parse_args()
    print(asyncio.run(probe(args.account, args.wait_ms)))
