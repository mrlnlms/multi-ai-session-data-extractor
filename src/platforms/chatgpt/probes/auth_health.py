"""Read-only authentication probe for chatgpt."""

from src.platforms._auth_probe import probe_with_existing_client


async def probe(profile_key: str):
    return await probe_with_existing_client("chatgpt", profile_key)
