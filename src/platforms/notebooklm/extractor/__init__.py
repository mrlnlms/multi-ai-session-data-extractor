"""Extractor proprietario NotebookLM via batchexecute RPC.

Endpoint base: POST /_/LabsTailwindUi/data/batchexecute (diferente do Gemini /_/BardChatUi/).

rpcids mapeados (24/abr/2026):
  ub2Bae  - lista notebooks da conta
  rLM1Ne  - metadata basica do notebook
  wXbhsf  - metadata + sources list
  VfAZjd  - guide (summary + questoes)
  khqZz   - chat history
  cFji9   - notes + briefs
  gArtLc  - audio overviews + URLs presigned
  hizoJc  - source content (texto extraido chunk-by-chunk + imagens por pagina)
  hPTbtc  - mind map UUID
"""
