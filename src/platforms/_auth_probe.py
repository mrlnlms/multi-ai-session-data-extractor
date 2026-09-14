"""Shared mechanics for one minimal platform read; no refresh or persistence."""

from __future__ import annotations

import importlib

from src.auth_health import AuthStatus
from src.auth_probes import ProbeResult, classify_probe_exception


async def probe_with_existing_client(source: str, profile_key: str) -> ProbeResult:
    """Perform exactly one documented listing request using an existing client."""
    if source == "chatgpt":
        return ProbeResult(AuthStatus.UNKNOWN, "ChatGPT requires a visible Cloudflare-safe validation; adapter is conservative")
    context = None
    try:
        auth = importlib.import_module(f"src.platforms.{source}.extractor.auth")
        if source == "claude_ai":
            context, org_id = await auth.load_context(profile_key, headless=True)
            client_cls = importlib.import_module(f"src.platforms.{source}.extractor.api_client").ClaudeAPIClient
            await client_cls(context, org_id).list_conversations(starred=False, limit=1)
        elif source == "gemini":
            context = await auth.load_context(profile_key, headless=True)
            session = await importlib.import_module(
                "src.platforms.gemini.extractor.batchexecute"
            ).load_session(context)
            client_cls = importlib.import_module("src.platforms.gemini.extractor.api_client").GeminiAPIClient
            await client_cls(context, session).list_conversations()
        elif source == "notebooklm":
            context = await auth.load_context(profile_key, headless=True)
            session = await importlib.import_module(
                "src.platforms.notebooklm.extractor.batchexecute"
            ).load_session(context)
            client_cls = importlib.import_module("src.platforms.notebooklm.extractor.api_client").NotebookLMClient
            await client_cls(context, session, hl="en").list_notebooks()
        else:
            headed = source == "perplexity"
            context = await auth.load_context(profile_key, headless=not headed)
            page = await context.new_page()
            api = importlib.import_module(f"src.platforms.{source}.extractor.api_client")
            if source == "qwen":
                client = api.QwenAPIClient(context, page)
                await page.goto(api.HOME_URL, wait_until="domcontentloaded", timeout=60000)
                await client.list_chats_page(1)
            elif source == "deepseek":
                client = api.DeepSeekAPIClient(context, page)
                await page.goto(api.HOME_URL, wait_until="domcontentloaded", timeout=60000)
                await client.list_conversations(page_size=1)
            elif source == "perplexity":
                client = api.PerplexityAPIClient(context, page)
                await page.goto(api.LIBRARY_URL, wait_until="domcontentloaded", timeout=60000)
                await client.list_threads_page(0, limit=1)
            elif source == "grok":
                client = api.GrokAPIClient(context, page)
                await client.warmup()
                await client.list_conversations_page(page_size=1)
            elif source == "kimi":
                client = api.KimiAPIClient(context, page)
                await client.warmup()
                await client.list_chats_page(page_size=1)
            else:
                return ProbeResult(AuthStatus.UNKNOWN, "No reliable read endpoint is documented")
        return ProbeResult(AuthStatus.VALID, "Authenticated read succeeded")
    except Exception as exc:
        return classify_probe_exception(exc)
    finally:
        if context is not None:
            await context.close()
