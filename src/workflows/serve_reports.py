"""Serve rendered Quarto reports from ``notebooks/_output``.

Usage::

    python -m src.workflows.serve_reports start
    python -m src.workflows.serve_reports status
    python -m src.workflows.serve_reports open
    python -m src.workflows.serve_reports stop
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from src.runtime.project import find_project_root


PROJECT_ROOT = find_project_root(Path(__file__))
RUNTIME_DIR = PROJECT_ROOT / ".runtime"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "notebooks" / "_output"
DEFAULT_PORT = 8765


def _pid_file() -> Path:
    return RUNTIME_DIR / "pids" / "serve-reports.pid"


def _log_file() -> Path:
    return RUNTIME_DIR / "logs" / "serve-reports.log"


def _read_pid() -> int | None:
    try:
        return int(_pid_file().read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def is_running() -> bool:
    pid = _read_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True


def start_server(*, port: int = DEFAULT_PORT, output_dir: Path = DEFAULT_OUTPUT_DIR) -> int:
    """Start the detached report server and return its PID."""
    if not output_dir.is_dir():
        raise FileNotFoundError(
            f"{output_dir} does not exist; render a Quarto notebook first"
        )
    if is_running():
        assert (pid := _read_pid()) is not None
        return pid

    pid_file = _pid_file()
    log_file = _log_file()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("ab") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port), "--directory", str(output_dir)],
            cwd=PROJECT_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pid_file.write_text(f"{process.pid}\n")
    time.sleep(0.2)
    if process.poll() is not None:
        pid_file.unlink(missing_ok=True)
        raise RuntimeError(f"report server failed to start; see {log_file}")
    return process.pid


def stop_server() -> int | None:
    """Stop the detached report server and return the former PID."""
    pid = _read_pid()
    if pid is not None and is_running():
        os.kill(pid, signal.SIGTERM)
    _pid_file().unlink(missing_ok=True)
    return pid


def report_urls(*, port: int = DEFAULT_PORT, output_dir: Path = DEFAULT_OUTPUT_DIR) -> list[str]:
    return [f"http://localhost:{port}/{path.name}" for path in sorted(output_dir.glob("*.html"))]


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("command", nargs="?", default="start", choices=("start", "stop", "restart", "status", "open"))
    cli.add_argument("--port", type=int, default=int(os.environ.get("PORT", DEFAULT_PORT)))
    cli.add_argument("--output-dir", type=Path, default=Path(os.environ.get("OUTPUT_DIR", DEFAULT_OUTPUT_DIR)))
    return cli


def main() -> int:
    args = parser().parse_args()
    if args.command == "stop":
        pid = stop_server()
        print(f"stopped (pid {pid})" if pid else "already stopped")
        return 0
    if args.command == "restart":
        stop_server()
    if args.command == "status":
        pid = _read_pid()
        print(f"running (pid {pid}, port {args.port})" if is_running() else "stopped")
        return 0 if is_running() else 1

    pid = start_server(port=args.port, output_dir=args.output_dir)
    print(f"running (pid {pid}, port {args.port})")
    print(f"http://localhost:{args.port}/")
    if args.command == "open":
        for url in report_urls(port=args.port, output_dir=args.output_dir):
            webbrowser.open(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
