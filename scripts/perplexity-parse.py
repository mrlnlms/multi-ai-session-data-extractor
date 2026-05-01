"""Parser canonico Perplexity v3 — merged -> 4 parquets.

Le data/merged/Perplexity/ e escreve data/processed/Perplexity/{
  conversations, messages, tool_events, branches}.parquet.

Idempotente: rodar 2x produz mesmos bytes.
Uso: python scripts/perplexity-parse.py
"""

from pathlib import Path
from src.parsers.perplexity import PerplexityParser


if __name__ == "__main__":
    parser = PerplexityParser()
    parser.parse()
    stats = parser.write()
    print("=== Perplexity parse done ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
