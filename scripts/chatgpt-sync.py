"""Sync ChatGPT — captura raw e ja reconcilia em sequencia.

Uso:
    python scripts/chatgpt-sync.py [--no-voice-pass] [--full] [--no-reconcile]

Fluxo:
    1. Captura raw (mesmo comportamento de chatgpt-export.py — incremental se tem
       base anterior, brute force se nao; fail-fast se discovery cai >20%).
    2. Se sucesso, reconcilia automaticamente: raw recem-criado + merged anterior
       (auto-detectado) -> novo merged em data/merged/ChatGPT/<data>/.

Output unificado: counts da captura + counts da reconciliacao.

Pra rodar so um passo, use os scripts standalone:
    python scripts/chatgpt-export.py
    python scripts/chatgpt-reconcile.py "data/raw/<dir>"

Requer login previo:
    python scripts/chatgpt-login.py
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

from src.extractors.chatgpt.models import CaptureOptions
from src.extractors.chatgpt.orchestrator import run_capture
from src.reconcilers.chatgpt import run_reconciliation


def _default_output_dir() -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    return Path(f"data/raw/ChatGPT Data {today}")


def main():
    parser = argparse.ArgumentParser(
        description="Captura + reconcilia ChatGPT em uma rodada"
    )
    parser.add_argument("--output-dir", type=Path, default=None,
                       help="Override do dir de output do raw")
    parser.add_argument("--no-voice-pass", action="store_true",
                       help="Pula DOM voice pass")
    parser.add_argument("--dry-run", action="store_true",
                       help="So descoberta, nao baixa, nao reconcilia")
    parser.add_argument("--full", action="store_true",
                       help="Forca brute force na captura")
    parser.add_argument("--no-reconcile", action="store_true",
                       help="So captura, pula reconciliacao (equivalente a chatgpt-export.py)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")

    output_dir = args.output_dir or _default_output_dir()
    options = CaptureOptions(
        skip_voice=args.no_voice_pass,
        dry_run=args.dry_run,
        full=args.full,
    )

    # 1. Captura
    print("=" * 60)
    print("ETAPA 1/2: Captura")
    print("=" * 60)
    capture_report = asyncio.run(run_capture(output_dir, options))
    print("\n" + capture_report.summary())

    if args.dry_run:
        print("\n[dry-run: pulando reconciliacao]")
        return

    if args.no_reconcile:
        print("\n[--no-reconcile: pulando reconciliacao]")
        return

    # output_dir pode ter sido alterado pelo orchestrator (sufixo de hora)
    # — pega o real do report ou re-resolve
    actual_raw_dir = _resolve_actual_raw_dir(output_dir)

    # 2. Reconciler
    print("\n" + "=" * 60)
    print("ETAPA 2/2: Reconciliacao")
    print("=" * 60)
    merged_base = Path("data/merged/ChatGPT")
    reconcile_report = run_reconciliation(actual_raw_dir, merged_base)

    if reconcile_report.aborted:
        print(f"\nRECONCILER ABORTOU: {reconcile_report.abort_reason}")
        sys.exit(1)

    print("\n" + reconcile_report.summary())

    # Resumo final
    print("\n" + "=" * 60)
    print("RESUMO")
    print("=" * 60)
    print(f"Raw:    {actual_raw_dir}")
    print(f"Merged: data/merged/ChatGPT/{datetime.now().strftime('%Y-%m-%d')}/")


def _resolve_actual_raw_dir(intended: Path) -> Path:
    """Acha o dir de raw real criado.

    Orchestrator adiciona sufixo de hora se intended ja existir. Esse helper
    procura o dir mais recente que comeca com o nome de intended.
    """
    if intended.exists() and (intended / "chatgpt_raw.json").exists():
        return intended
    # Procura variantes com sufixo
    parent = intended.parent
    base_name = intended.name
    candidates = sorted(
        [d for d in parent.iterdir()
         if d.is_dir() and d.name.startswith(base_name)
         and (d / "chatgpt_raw.json").exists()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError(f"Nao achou raw dir pra {intended}")
    return candidates[0]


if __name__ == "__main__":
    main()
