import json
import os
from datetime import datetime, timedelta, timezone

from src.application import platforms
from src.application.platforms import CaptureRun, PlatformState, _load_capture_log


def _capture(*, days_ago: int = 0, errors: int = 0) -> CaptureRun:
    return CaptureRun(
        started_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        finished_at=None,
        duration_seconds=None,
        discovery_total=None,
        fetch_attempted=None,
        fetch_succeeded=None,
        errors_count=errors,
    )


def _state_with_parquet(tmp_path, *, name="ChatGPT", capture=None):
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    raw.mkdir()
    processed.mkdir()
    parquet = processed / "conversations.parquet"
    parquet.touch()
    return PlatformState(
        name=name,
        raw_dir=raw,
        merged_dir=None,
        processed_dir=processed,
        capture_runs=[capture or _capture()],
    ), raw, parquet


def test_recent_capture_with_errors_is_not_green():
    state = PlatformState(
        name="Perplexity",
        raw_dir=None,
        merged_dir=None,
        capture_runs=[CaptureRun(
            started_at=datetime.now(timezone.utc), finished_at=None,
            duration_seconds=None, discovery_total=None, fetch_attempted=None,
            fetch_succeeded=None, errors_count=1,
        )],
    )

    assert state.status() == "yellow"
    assert state.health().reason == "Last capture completed with 1 error"


def test_old_capture_can_be_healthy(tmp_path):
    state, raw, parquet = _state_with_parquet(tmp_path, capture=_capture(days_ago=45))
    source = raw / "conversation.json"
    source.touch()
    os.utime(source, (parquet.stat().st_mtime - 10, parquet.stat().st_mtime - 10))

    assert state.status() == "green"
    assert state.health().reason == "Processed data is up to date"


def test_missing_parquet_is_failed(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    state = PlatformState("ChatGPT", raw, None, tmp_path / "missing", [_capture()])

    assert state.status() == "red"
    assert state.health().reason == "Processed conversations Parquet is missing"


def test_newer_relevant_input_is_failed(tmp_path):
    state, raw, parquet = _state_with_parquet(tmp_path, name="Codex")
    source = raw / "rollout-example.jsonl"
    source.touch()
    os.utime(source, (parquet.stat().st_mtime + 10, parquet.stat().st_mtime + 10))

    assert state.status() == "red"
    assert "newer than the processed Parquet" in state.health().reason


def test_irrelevant_file_does_not_make_parquet_stale(tmp_path):
    state, raw, parquet = _state_with_parquet(tmp_path, name="Codex")
    irrelevant = raw / "notes.txt"
    irrelevant.touch()
    os.utime(irrelevant, (parquet.stat().st_mtime + 10, parquet.stat().st_mtime + 10))

    assert state.status() == "green"


def test_never_run_is_gray():
    state = PlatformState("ChatGPT", None, None)

    assert state.status() == "gray"
    assert state.health().reason == "No capture has been recorded"


def test_parser_skips_are_attention_even_with_current_parquet(tmp_path):
    state, _raw, _parquet = _state_with_parquet(
        tmp_path,
        name="Codex",
        capture=_capture(),
    )
    state.capture_runs[0].files_seen = 10
    state.capture_runs[0].files_parsed = 9
    state.capture_runs[0].files_skipped = 1

    assert state.status() == "yellow"
    assert state.health().reason == "Parser skipped 1 session file"


def test_capture_log_loads_optional_parser_coverage(tmp_path):
    log = tmp_path / "capture_log.jsonl"
    log.write_text(json.dumps({
        "started_at": "2026-09-12T12:00:00Z",
        "totals": {"files_seen": 251, "files_parsed": 251, "files_skipped": 0},
    }) + "\n")

    run = _load_capture_log(log)[0]

    assert run.files_seen == 251
    assert run.files_parsed == 251
    assert run.files_skipped == 0


def test_platform_state_exposes_read_only_account_inventory(tmp_path, monkeypatch):
    storage = tmp_path / ".storage"
    raw_root = tmp_path / "raw"
    merged_root = tmp_path / "merged"
    storage.mkdir()
    (storage / "chatgpt-profile-local").mkdir()
    historical = merged_root / "ChatGPT" / "account-historical"
    historical.mkdir(parents=True)

    monkeypatch.setattr(platforms, "STORAGE_ROOT", storage)
    monkeypatch.setattr(platforms, "DATA_RAW", raw_root)
    monkeypatch.setattr(platforms, "DATA_MERGED", merged_root)

    state = platforms.load_platform_state("ChatGPT")
    by_key = {account.key: account for account in state.accounts}

    assert isinstance(state.accounts, tuple)
    assert by_key["local"].evidence.profile_present
    assert by_key["historical"].evidence.merged_present
    assert by_key["historical"].authentication == "not_configured"


def test_platform_state_includes_notebooklm_external_archive(tmp_path, monkeypatch):
    storage = tmp_path / ".storage"
    external = tmp_path / "external"
    storage.mkdir()
    archive = external / "notebooklm-snapshots" / "former-work-2026-01-02"
    archive.mkdir(parents=True)

    monkeypatch.setattr(platforms, "STORAGE_ROOT", storage)
    monkeypatch.setattr(platforms, "DATA_RAW", tmp_path / "raw")
    monkeypatch.setattr(platforms, "DATA_MERGED", tmp_path / "merged")
    monkeypatch.setattr(platforms, "DATA_EXTERNAL", external)

    state = platforms.load_platform_state("NotebookLM")
    by_key = {account.key: account for account in state.accounts}

    assert by_key["archive:former-work-2026-01-02"].evidence.historical_path == archive
