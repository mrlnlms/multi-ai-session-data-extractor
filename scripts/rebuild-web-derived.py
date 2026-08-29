#!/usr/bin/env python3
"""Rebuild web processed Parquets and unified outputs in a separate tree.

This recovery helper intentionally runs parsers only: no sync, browser,
authentication, DVC, Git, or publication command is invoked. CLI parsers are
excluded because their syncs already produced current processed outputs and
their preservation flags depend on live HOME state.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


WEB_PARSE_SCRIPTS = [
    "chatgpt-parse.py",
    "claude-parse.py",
    "gemini-parse.py",
    "notebooklm-parse.py",
    "qwen-parse.py",
    "deepseek-parse.py",
    "perplexity-parse.py",
    "grok-parse.py",
    "kimi-parse.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    source_root = Path(__file__).resolve().parent.parent
    project_root = args.project_root.resolve()
    if project_root == source_root:
        raise ValueError("refusing to rebuild the frozen source worktree")
    if not (project_root / "data" / "raw").is_dir():
        raise FileNotFoundError("target project has no data/raw baseline")

    results: list[dict[str, object]] = []
    commands = [
        (name.removesuffix("-parse.py"), [sys.executable, str(project_root / "scripts" / name)])
        for name in WEB_PARSE_SCRIPTS
    ]
    commands.append(("unify", [sys.executable, str(project_root / "scripts" / "unify-parquets.py")]))

    for index, (name, command) in enumerate(commands, 1):
        print(f"[{index}/{len(commands)}] {name}", flush=True)
        started = datetime.now(timezone.utc)
        result = subprocess.run(
            command,
            cwd=project_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONPATH": str(project_root)},
        )
        output = result.stdout or ""
        print(output[-4000:], flush=True)
        results.append(
            {
                "step": name,
                "returncode": result.returncode,
                "started_at": started.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "tail": output[-10000:],
            }
        )
        if result.returncode != 0:
            break

    report = {
        "project_root": str(project_root),
        "python": sys.executable,
        "results": results,
        "valid": len(results) == len(commands) and all(r["returncode"] == 0 for r in results),
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
