"""Manual saves parsers — clippings, copy-paste, terminal renders.

Cada parser adota source = plataforma original (chatgpt/claude_ai/etc) e
capture_method = string especifica (manual_clipping_obsidian, manual_copypaste,
manual_terminal_cc).

Output via `src.workflows.manual_saves` (exposed operationally by
`scripts/workflows/manual-saves-sync.py`): groups by source
destino e escreve `<source>_manual_<table>.parquet` em cada
`data/processed/<Plataforma>/`.

Frozen extractor snapshots are not manual saves. Platform-specific historical
format adapters live beside the canonical platform parsers.
"""
