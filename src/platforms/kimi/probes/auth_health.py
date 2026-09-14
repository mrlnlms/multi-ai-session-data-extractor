"""Read-only authentication probe for kimi."""

from src.platforms._auth_probe import probe_with_existing_client


async def probe(profile_key: str):
    return await probe_with_existing_client("kimi", profile_key)
