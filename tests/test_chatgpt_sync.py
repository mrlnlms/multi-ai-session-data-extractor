"""Testes do scripts/chatgpt-sync.py.

Antes do refactor pasta-unica (2026-04-27), este arquivo cobria
hardlink_existing_binaries — funcao removida quando o sync passou a mutar
a pasta unica data/raw/ChatGPT/ in-place. Hardlink nao faz mais sentido:
a pasta nunca muda, os binarios estao sempre la.

Smoke tests do main() ficam como TODO se forem necessarios — fluxo end-to-end
ja eh validado pelo smoke run manual em vez de teste unitario, dada a
dependencia em Playwright + auth.
"""
