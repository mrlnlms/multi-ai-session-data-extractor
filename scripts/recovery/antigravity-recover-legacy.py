"""Recover selected opaque Antigravity CLI legacy conversations.

This is intentionally *not* part of ``antigravity-cli-sync.py``.  Legacy
``.pb`` containers may be encrypted; when an ``agy`` process is running, its
local loopback daemon can load a named trajectory and return its already
decrypted JSON.  This script asks that daemon only over ``127.0.0.1``, stores
the resulting sidecar under the project's raw preservation area, and records
source/output hashes in a recovery manifest.  A successful matching entry is
skipped on subsequent executions.

It never modifies ``~/.gemini/antigravity-cli`` and never sends data to a
remote service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = Path.home() / ".gemini" / "antigravity-cli"
RAW_ROOT = PROJECT_ROOT / "data" / "raw" / "Antigravity CLI"
RECOVERED_DIR = RAW_ROOT / "recovered"
MANIFEST_PATH = RECOVERED_DIR / "recovery_manifest.jsonl"
PORT_RE = re.compile(r"Language server listening on random port at (\d+) for HTTP")
RPC_PREFIX = "/exa.language_server_pb.LanguageServerService/"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def daemon_ports() -> list[int]:
    """Return recently logged loopback daemon ports, newest log first."""
    log_dir = SOURCE_ROOT / "log"
    ports: list[int] = []
    for log in sorted(log_dir.glob("cli-*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
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
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        f"http://127.0.0.1:{port}{RPC_PREFIX}{method}",
        data=body,
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


def load_successes() -> dict[str, dict[str, Any]]:
    """Read the last successful recovery record for each conversation."""
    successes: dict[str, dict[str, Any]] = {}
    if not MANIFEST_PATH.exists():
        return successes
    with MANIFEST_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and entry.get("status") == "recovered" and isinstance(entry.get("conversation_id"), str):
                successes[entry["conversation_id"]] = entry
    return successes


def opaque_ids() -> list[str]:
    """Find legacy PB containers without a copied readable JSONL trajectory."""
    conversation_dir = RAW_ROOT / "conversations"
    ids: list[str] = []
    for pb in sorted(conversation_dir.glob("*.pb")):
        conversation_id = pb.stem
        transcript = RAW_ROOT / "brain" / conversation_id / ".system_generated" / "logs" / "transcript.jsonl"
        if not transcript.exists():
            ids.append(conversation_id)
    return ids


def source_pb(conversation_id: str) -> Path:
    source = SOURCE_ROOT / "conversations" / f"{conversation_id}.pb"
    raw = RAW_ROOT / "conversations" / f"{conversation_id}.pb"
    if not raw.exists():
        raise RuntimeError(f"{conversation_id}: raw PB absent; execute antigravity-cli-sync.py first")
    if not source.exists():
        raise RuntimeError(f"{conversation_id}: source PB absent from {SOURCE_ROOT}")
    source_hash = sha256(source)
    if source_hash != sha256(raw):
        raise RuntimeError(f"{conversation_id}: raw PB differs from local source; execute antigravity-cli-sync.py first")
    return raw


def write_json_atomically(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(encoded)
    temp.replace(path)
    return hashlib.sha256(encoded).hexdigest()


def append_manifest(entry: dict[str, Any]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--conversation-id", action="append", help="Legacy PB UUID to recover (repeatable)")
    group.add_argument("--all-opaque", action="store_true", help="Recover every copied PB without a readable JSONL trajectory")
    parser.add_argument("--port", type=int, action="append", help="Loopback daemon port (normally autodetected)")
    parser.add_argument("--dry-run", action="store_true", help="Validate targets and show the intended work without calling agy")
    parser.add_argument("--force", action="store_true", help="Re-fetch even when source hash and recovered sidecar already match")
    args = parser.parse_args()

    ids = args.conversation_id or opaque_ids()
    if not ids:
        print("No opaque legacy PB containers found.")
        return 0
    successes = load_successes()
    ports = args.port or daemon_ports()
    recovered = skipped = failed = 0

    for conversation_id in ids:
        try:
            raw_pb = source_pb(conversation_id)
            source_hash = sha256(raw_pb)
            output = RECOVERED_DIR / f"{conversation_id}.trajectory.json"
            prior = successes.get(conversation_id, {})
            if not args.force and prior.get("source_sha256") == source_hash and output.exists() and sha256(output) == prior.get("trajectory_sha256"):
                print(f"SKIP {conversation_id}: recovered sidecar matches source hash")
                skipped += 1
                continue
            if args.dry_run:
                print(f"PLAN {conversation_id}: {raw_pb.name} -> {output.relative_to(RAW_ROOT)}")
                continue
            trajectory, port = fetch_trajectory(conversation_id, ports)
            output_hash = write_json_atomically(output, trajectory)
            append_manifest({
                "conversation_id": conversation_id,
                "method": "local_agy_daemon",
                "port": port,
                "recovered_at": datetime.now(timezone.utc).isoformat(),
                "source_path": str(raw_pb.relative_to(RAW_ROOT)),
                "source_sha256": source_hash,
                "trajectory_path": str(output.relative_to(RAW_ROOT)),
                "trajectory_sha256": output_hash,
                "status": "recovered",
            })
            step_count = len(trajectory.get("steps", [])) if isinstance(trajectory.get("steps"), list) else 0
            print(f"RECOVERED {conversation_id}: {step_count} trajectory steps")
            recovered += 1
        except (OSError, RuntimeError, ValueError) as error:
            print(f"FAILED {conversation_id}: {error}", file=sys.stderr)
            failed += 1

    print(f"Summary: {recovered} recovered, {skipped} skipped, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
