"""Manual saves parsers — clippings, copy-paste, terminal renders.

Cada parser adota source = plataforma original (chatgpt/claude_ai/etc) e
capture_method = string especifica (manual_clipping_obsidian, manual_copypaste,
manual_terminal_cc).

Output via orquestrador `scripts/manual-saves-sync.py`: agrupa por source
destino e escreve `<source>_manual_<table>.parquet` em cada
`data/processed/<Plataforma>/`.
"""
