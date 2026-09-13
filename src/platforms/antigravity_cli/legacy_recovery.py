"""Recover readable trajectories from legacy Antigravity CLI ``.pb`` files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PORT_RE = re.compile(r"Language server listening on random port at (\d+) for HTTP")
RPC_PREFIX = "/exa.language_server_pb.LanguageServerService/"
TrajectoryFetcher = Callable[[str, list[int]], tuple[dict[str, Any], int]]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def daemon_ports(source_root: Path) -> list[int]:
    """Return recently logged loopback daemon ports, newest log first."""
    ports: list[int] = []
    logs = source_root / "log"
    for log in sorted(logs.glob("cli-*.log"), key=lambda path: path.stat().st_mtime, reverse=True):
        try:
            matches = PORT_RE.findall(log.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        for match in reversed(matches):
            port = int(match)
            if port not in ports:
                ports.append(port)
    return ports


def rpc(port: int, method: str, payload: dict[str, str]) -> dict[str, Any]:
    request = Request(
        f"http://127.0.0.1:{port}{RPC_PREFIX}{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=8) as response:  # nosec B310: fixed loopback endpoint
        decoded = json.loads(response.read().decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError(f"{method} returned a non-object JSON value")
    return decoded


def fetch_trajectory(conversation_id: str, ports: list[int]) -> tuple[dict[str, Any], int]:
    """Ask one active local daemon to load and return a trajectory."""
    failures: list[str] = []
    for port in ports:
        try:
            rpc(port, "LoadTrajectory", {"cascadeId": conversation_id})
            response = rpc(port, "GetCascadeTrajectory", {"cascadeId": conversation_id})
            trajectory = response.get("trajectory")
            if not isinstance(trajectory, dict):
                raise ValueError("GetCascadeTrajectory did not contain an object trajectory")
            return trajectory, port
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            failures.append(f"{port}: {error}")
    detail = "; ".join(failures) or "no daemon port found in cli logs"
    raise RuntimeError(f"no usable Antigravity local daemon ({detail})")


def load_successes(manifest_path: Path) -> dict[str, dict[str, Any]]:
    successes: dict[str, dict[str, Any]] = {}
    if not manifest_path.exists():
        return successes
    with manifest_path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and entry.get("status") == "recovered" and isinstance(entry.get("conversation_id"), str):
                successes[entry["conversation_id"]] = entry
    return successes


def legacy_ids_without_transcript(raw_root: Path) -> list[str]:
    """Find legacy PB containers that lack a current readable transcript."""
    ids: list[str] = []
    for pb in sorted((raw_root / "conversations").glob("*.pb")):
        conversation_id = pb.stem
        transcript = raw_root / "brain" / conversation_id / ".system_generated" / "logs" / "transcript.jsonl"
        if not transcript.exists():
            ids.append(conversation_id)
    return ids


def source_pb(conversation_id: str, source_root: Path, raw_root: Path) -> Path:
    source = source_root / "conversations" / f"{conversation_id}.pb"
    raw = raw_root / "conversations" / f"{conversation_id}.pb"
    if not raw.exists():
        raise RuntimeError(f"{conversation_id}: raw PB absent; execute python -m src.platforms.antigravity_cli.commands.sync first")
    if not source.exists():
        raise RuntimeError(f"{conversation_id}: source PB absent from {source_root}")
    if sha256(source) != sha256(raw):
        raise RuntimeError(f"{conversation_id}: raw PB differs from local source; execute python -m src.platforms.antigravity_cli.commands.sync first")
    return raw


def write_json_atomically(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)
    return hashlib.sha256(encoded).hexdigest()


def append_manifest(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def recover_conversations(
    conversation_ids: list[str], *, source_root: Path, raw_root: Path,
    ports: list[int], dry_run: bool = False, force: bool = False,
    fetch: TrajectoryFetcher = fetch_trajectory,
) -> dict[str, int]:
    recovered_dir = raw_root / "recovered"
    manifest_path = recovered_dir / "recovery_manifest.jsonl"
    successes = load_successes(manifest_path)
    recovered = skipped = failed = 0
    for conversation_id in conversation_ids:
        try:
            raw_pb = source_pb(conversation_id, source_root, raw_root)
            source_hash = sha256(raw_pb)
            output = recovered_dir / f"{conversation_id}.trajectory.json"
            prior = successes.get(conversation_id, {})
            if not force and prior.get("source_sha256") == source_hash and output.exists() and sha256(output) == prior.get("trajectory_sha256"):
                print(f"SKIP {conversation_id}: recovered sidecar matches source hash")
                skipped += 1
                continue
            if dry_run:
                print(f"PLAN {conversation_id}: {raw_pb.name} -> {output.relative_to(raw_root)}")
                continue
            trajectory, port = fetch(conversation_id, ports)
            output_hash = write_json_atomically(output, trajectory)
            append_manifest(manifest_path, {
                "conversation_id": conversation_id,
                "method": "local_agy_daemon",
                "port": port,
                "recovered_at": datetime.now(timezone.utc).isoformat(),
                "source_path": str(raw_pb.relative_to(raw_root)),
                "source_sha256": source_hash,
                "trajectory_path": str(output.relative_to(raw_root)),
                "trajectory_sha256": output_hash,
                "status": "recovered",
            })
            steps = trajectory.get("steps")
            print(f"RECOVERED {conversation_id}: {len(steps) if isinstance(steps, list) else 0} trajectory steps")
            recovered += 1
        except (OSError, RuntimeError, ValueError) as error:
            print(f"FAILED {conversation_id}: {error}", file=sys.stderr)
            failed += 1
    return {"recovered": recovered, "skipped": skipped, "failed": failed}


def main(project_root: Path, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--conversation-id", action="append", help="Legacy PB UUID to recover (repeatable)")
    group.add_argument("--all-opaque", action="store_true", help="Recover every copied PB without a readable JSONL trajectory")
    parser.add_argument("--port", type=int, action="append", help="Loopback daemon port (normally autodetected)")
    parser.add_argument("--dry-run", action="store_true", help="Validate targets without calling Antigravity")
    parser.add_argument("--force", action="store_true", help="Re-fetch an already matching sidecar")
    args = parser.parse_args(argv)
    source_root = Path.home() / ".gemini" / "antigravity-cli"
    raw_root = project_root / "data" / "raw" / "Antigravity CLI"
    conversation_ids = args.conversation_id or legacy_ids_without_transcript(raw_root)
    if not conversation_ids:
        print("No opaque legacy PB containers found.")
        return 0
    result = recover_conversations(
        conversation_ids, source_root=source_root, raw_root=raw_root,
        ports=args.port or daemon_ports(source_root), dry_run=args.dry_run, force=args.force,
    )
    print(f"Summary: {result['recovered']} recovered, {result['skipped']} skipped, {result['failed']} failed")
    return 1 if result["failed"] else 0
