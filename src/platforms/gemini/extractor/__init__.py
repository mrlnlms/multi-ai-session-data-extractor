"""Extractor proprietario Gemini via batchexecute RPC.

Endpoints (descobertos empiricamente 24/abr/2026):
  POST /_/BardChatUi/data/batchexecute?rpcids=<id>&bl=<build>&f.sid=<session>&hl=en&rt=c

rpcids mapeados:
  MaZiqc(payload=[]) → lista de convs [conv_id, title, ..., [epoch_secs, nanos], ...]
  hNvQHb(payload=[conv_id, 10, null, 1, [0], [4], null, 1]) → arvore da conv + image URLs

Imagens vem como URLs lh3.googleusercontent.com/gg/... presigned — baixar logo.
Session params (at/bl/f.sid) extraidos do HTML da home.
"""
