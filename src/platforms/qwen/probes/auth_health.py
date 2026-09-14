"""Read-only authentication probe for qwen."""

from src.platforms._auth_probe import probe_with_existing_client


async def probe(profile_key: str):
    return await probe_with_existing_client("qwen", profile_key)
