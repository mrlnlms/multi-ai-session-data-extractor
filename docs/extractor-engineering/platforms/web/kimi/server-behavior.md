# Kimi — server behavior

## Origin migration — 2026-08-30

Kimi's public web origin moved from `www.kimi.com` to `kimi.ai`. In a
read-only authenticated comparison after Google SSO, the existing
`localStorage.access_token` was present on the new origin and the established
`POST /apiv2/kimi.chat.v1.ChatService/ListChats` request returned HTTP 200.
Its response retained the `chats` and `nextPageToken` top-level fields.

This validates an origin-only migration for the current collector. The former
gRPC/Connect-style endpoint paths and response envelope remain in use; no
selector or broad API rewrite is justified without contrary evidence from a
future controlled run.

The subsequent incremental run confirmed the full contract, not merely the
one-row probe: `ListChats` discovered 51 chats, `GetChat`/`ListMessages`
fetched 40 new bodies with no errors, and both skill endpoints returned their
expected collections. Asset `signUrl` values remain ephemeral; one was
unavailable during this run while existing local files were preserved.

## Historical contract — 2026-05-09

- Chat discovery: `POST /apiv2/kimi.chat.v1.ChatService/ListChats` with
  cursor `pageToken`.
- Chat detail: `GetChat` plus `ListMessages`.
- Skills: `ListOfficialSkills` and `ListInstalledSkills`.
- Auth: cookies plus Bearer token sourced by the page from
  `localStorage.access_token`; cookies alone were insufficient.
- Assets use expiring inline `signUrl` values and are preserved locally once
  downloaded.
