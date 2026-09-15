from pathlib import Path

from src.operations.local_freshness import inspect_archive


def _touch(path: Path, timestamp_ns: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fixture")
    path.touch()
    import os

    os.utime(path, ns=(timestamp_ns, timestamp_ns))


def test_current_local_archive(tmp_path: Path) -> None:
    _touch(tmp_path / "data/merged/ChatGPT/conversations/a.json", 1_000_000_000)
    _touch(tmp_path / "data/processed/ChatGPT/chatgpt_conversations.parquet", 2_000_000_000)
    _touch(tmp_path / "data/unified/conversations.parquet", 3_000_000_000)

    report = inspect_archive(tmp_path, platforms=("ChatGPT",))

    assert report.status == "current"
    assert report.checked_sources == 1
    assert report.checked_tables == 1


def test_stale_processed_and_unified(tmp_path: Path) -> None:
    _touch(tmp_path / "data/merged/ChatGPT/conversations/a.json", 3_000_000_000)
    _touch(tmp_path / "data/processed/ChatGPT/chatgpt_conversations.parquet", 2_000_000_000)
    _touch(tmp_path / "data/unified/conversations.parquet", 1_000_000_000)

    report = inspect_archive(tmp_path, platforms=("ChatGPT",))

    assert report.status == "stale"
    assert "ChatGPT" in report.stale_sources
    assert "conversations" in report.stale_tables


def test_missing_processed_is_unknown_not_green(tmp_path: Path) -> None:
    _touch(tmp_path / "data/raw/Codex/session.jsonl", 1_000_000_000)

    report = inspect_archive(tmp_path, platforms=("Codex",))

    assert report.status == "incomplete"
    assert report.missing_sources == ("Codex",)


def test_every_processed_table_is_checked(tmp_path: Path) -> None:
    _touch(tmp_path / "data/raw/Codex/session.jsonl", 1_000_000_000)
    _touch(tmp_path / "data/processed/Codex/codex_conversations.parquet", 3_000_000_000)
    _touch(tmp_path / "data/processed/Codex/codex_messages.parquet", 2_000_000_000)
    _touch(tmp_path / "data/unified/conversations.parquet", 4_000_000_000)
    _touch(tmp_path / "data/unified/messages.parquet", 1_000_000_000)

    report = inspect_archive(tmp_path, platforms=("Codex",))

    assert report.status == "stale"
    assert report.stale_tables == ("messages",)


def test_manual_import_is_not_compared_to_web_capture(tmp_path: Path) -> None:
    _touch(tmp_path / "data/merged/Qwen/conversations/a.json", 2_000_000_000)
    _touch(tmp_path / "data/processed/Qwen/qwen_manual_messages.parquet", 1_000_000_000)
    _touch(tmp_path / "data/processed/Qwen/qwen_messages.parquet", 3_000_000_000)
    _touch(tmp_path / "data/unified/messages.parquet", 4_000_000_000)

    report = inspect_archive(tmp_path, platforms=("Qwen",))

    assert report.status == "current"
