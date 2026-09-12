"""Captura ChatGPT em Python.

Uso:
    python scripts/chatgpt-export.py [--output-dir PATH] [--no-voice-pass] [--dry-run] [--full]

Modos (auto-detectados):
    Primeira run (sem captura anterior): brute force — fetcha todas as convs
    Rodadas seguintes: incremental — so fetcha convs novas ou com update_time maior
                       que o run_started_at da ultima captura. Base = ultimo
                       data/raw/ChatGPT Data */ com capture_log.json + chatgpt_raw.json.
    --full: forca brute force mesmo tendo captura anterior (sanity check periodico).

Requer login previo via:
    python scripts/chatgpt-login.py
"""

import argparse
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from src.extractors.chatgpt.models import CaptureOptions
from src.extractors.chatgpt.orchestrator import run_capture


def _default_output_dir() -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    return Path(f"data/raw/ChatGPT Data {today}")


def main():
    parser = argparse.ArgumentParser(description="Captura convs do ChatGPT via Python")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--no-voice-pass", action="store_true", help="Pula DOM voice pass")
    parser.add_argument("--dry-run", action="store_true", help="So descoberta, nao baixa")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Forca brute force (fetcha todas as convs) mesmo tendo captura anterior. "
             "Use pra sanity check periodico. Default: incremental se tiver captura anterior.",
    )
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

    report = asyncio.run(run_capture(output_dir, options))
    print("\n" + report.summary())


if __name__ == "__main__":
    main()
