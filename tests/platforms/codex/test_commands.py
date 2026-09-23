from types import SimpleNamespace

from src.capture.cli.copy import SOURCES
from src.platforms.codex.commands import sync


def test_dry_run_reports_sessions_and_memories(tmp_path, monkeypatch, capsys):
    codex_root = tmp_path / ".codex"
    sessions = codex_root / "sessions"
    memories = codex_root / "memories"
    raw = tmp_path / "raw" / "Codex"
    (sessions / "2026" / "09" / "22").mkdir(parents=True)
    memories.mkdir(parents=True)
    (raw / "memories").mkdir(parents=True)

    (sessions / "2026" / "09" / "22" / "rollout-a.jsonl").write_text("{}\n")
    (memories / "MEMORY.md").write_text("# memory\n")
    (memories / "nested").mkdir()
    (memories / "nested" / "detail.md").write_text("# detail\n")
    (raw / "rollout-old.jsonl").write_text("{}\n")
    (raw / "capture_log.jsonl").write_text("{}\n")
    (raw / "memories" / "MEMORY.md").write_text("# memory\n")

    monkeypatch.setitem(SOURCES["codex"], "src", sessions)
    monkeypatch.setattr(sync, "RAW_DIR", raw)
    monkeypatch.setattr(
        sync,
        "load_asset_runtime",
        lambda _source: SimpleNamespace(vault=None, reader=None),
    )
    monkeypatch.setattr("sys.argv", ["sync", "--dry-run"])

    assert sync.main() == 0
    output = capsys.readouterr().out
    assert f"source ({sessions}): 1 JSONLs" in output
    assert f"destino ({raw}): 1 JSONLs" in output
    assert f"memories source ({memories}): 2 Markdown files" in output
    assert f"memories destino ({raw / 'memories'}): 1 Markdown files" in output
