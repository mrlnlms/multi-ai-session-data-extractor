"""Gera parquets chatgpt_v2 em paralelo aos chatgpt_* antigos — sem substituir.

Le merged mais recente em data/merged/ChatGPT/<date>/chatgpt_merged.json,
roda o parser minimal v2, salva em data/processed/chatgpt_v2_{conversations,messages}.parquet.

NAO toca:
- parsers/chatgpt.py (antigo)
- data/processed/chatgpt_*.parquet (antigos)
- data/unified/
- run_pipeline.py

Uso:
    PYTHONPATH=. python scripts/build_chatgpt_v2.py
    PYTHONPATH=. python scripts/build_chatgpt_v2.py --merged-path data/merged/ChatGPT/2026-04-23/chatgpt_merged.json
"""

import argparse
import logging
from pathlib import Path

from src.parsers.chatgpt_v2 import ChatGPTV2Parser
from src.parsers.chatgpt import ChatGPTParser


def find_latest_merged(base: Path) -> Path:
    candidates = sorted(base.glob("*/chatgpt_merged.json"))
    if not candidates:
        raise FileNotFoundError(f"Nenhum chatgpt_merged.json encontrado em {base}/*/")
    return candidates[-1]


def find_dalle_zip() -> Path | None:
    """Localiza o zip DALL-E do export oficial OpenAI (se ainda existir)."""
    candidates = sorted(Path("data/raw").glob("ChatGPT Data*/**/Dall-E__*.zip"))
    return candidates[0] if candidates else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged-path", type=Path, default=None,
                    help="Override do merged (default: mais recente em data/merged/ChatGPT/*)")
    ap.add_argument("--dalle-zip", type=Path, default=None,
                    help="Override do zip DALL-E (default: auto-detect no export oficial). "
                         "Traz as 8 entradas legadas (6 convs deletadas pre-captura + 2 DALL-E Labs standalone).")
    ap.add_argument("--no-dalle", action="store_true",
                    help="Nao roda parse_dalle legado. V2 fica so com o merged novo.")
    ap.add_argument("--output-dir", type=Path, default=Path("data/processed"),
                    help="Diretorio de output (default: data/processed)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger(__name__)

    merged_path = args.merged_path or find_latest_merged(Path("data/merged/ChatGPT"))
    log.info(f"Input merged: {merged_path}")

    parser = ChatGPTV2Parser()
    parser.parse(merged_path)
    log.info(f"Merged parseado: {len(parser.conversations)} convs, {len(parser.messages)} msgs")

    # Legado DALL-E: roda parse_dalle do parser antigo com source_name="chatgpt_v2"
    if not args.no_dalle:
        dalle_zip = args.dalle_zip or find_dalle_zip()
        if dalle_zip and dalle_zip.exists():
            log.info(f"Input DALL-E legado: {dalle_zip}")
            dalle_parser = ChatGPTParser()
            dalle_parser.source_name = "chatgpt_v2"  # override instance
            dalle_parser.parse_dalle(dalle_zip)
            # Re-tagga source + reescreve titulos "conversa perdida" pra termo neutro
            # (convs ausentes do servidor, mas imagens preservadas no ZIP oficial OpenAI).
            for c in dalle_parser.conversations:
                c.source = "chatgpt_v2"
                if c.title and "conversa perdida" in c.title:
                    n = c.title.split("—")[-1].strip().rstrip("]")
                    c.title = f"[DALL-E ausente no servidor — {n}, preservadas no ZIP OpenAI]"
            for m in dalle_parser.messages:
                m.source = "chatgpt_v2"
            # Evita conflito com convs do merged (qualquer id que ja existe do merged ganha)
            existing_ids = {c.conversation_id for c in parser.conversations}
            new_convs = [c for c in dalle_parser.conversations if c.conversation_id not in existing_ids]
            new_msgs = [m for m in dalle_parser.messages if m.conversation_id not in existing_ids]
            parser.conversations.extend(new_convs)
            parser.messages.extend(new_msgs)
            log.info(f"DALL-E legado adicionado: +{len(new_convs)} convs, +{len(new_msgs)} msgs")
        else:
            log.warning("Nenhum zip DALL-E encontrado; pulando parse_dalle legado.")

    log.info(f"Total final: {len(parser.conversations)} convs, {len(parser.messages)} msgs")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    parser.save(args.output_dir)

    log.info(f"Salvo: {args.output_dir}/chatgpt_v2_conversations.parquet")
    log.info(f"Salvo: {args.output_dir}/chatgpt_v2_messages.parquet")


if __name__ == "__main__":
    main()
