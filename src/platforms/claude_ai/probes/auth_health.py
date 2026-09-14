"""Read-only authentication probe for claude_ai."""

from src.platforms._auth_probe import probe_with_existing_client


async def probe(profile_key: str):
    return await probe_with_existing_client("claude_ai", profile_key)
