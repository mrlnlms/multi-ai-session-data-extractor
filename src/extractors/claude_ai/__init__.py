"""Extractor proprietario Claude.ai via Playwright.

API ao vivo expoe file_uuid + thinking + tool_use/result + MCPs + branches que
o export oficial filtra. Cloudflare bloqueia curl, Playwright resolve.

Endpoints:
- GET /api/{org}/chat_conversations_v2?limit=30&starred={bool}&consistency=eventual
- GET /api/{org}/chat_conversations/{uuid}?tree=True&rendering_mode=messages&render_all_tools=true
- GET /api/{org}/files/{file_uuid}/preview (ou /thumbnail)
"""
