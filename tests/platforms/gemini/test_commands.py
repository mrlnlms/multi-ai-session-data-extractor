import argparse
import asyncio
from pathlib import Path
import pytest

from src.platforms.gemini.commands import login as login_command
from src.platforms.gemini.commands import download_assets, reconcile
from src.platforms.gemini.commands import sync
from src.platforms.gemini.extractor.auth import get_profile_dir


def test_login_defaults_to_account_one_with_current_choices():
    args = login_command.build_parser().parse_args([])

    assert args.account == "1"
    assert login_command.build_parser().parse_args(["--account", "work"]).account == "work"
    with pytest.raises(SystemExit):
        login_command.build_parser().parse_args(["--account", "../work"])


def test_sync_requires_explicit_account_even_for_programmatic_calls():
    args = argparse.Namespace(
        account=None, dry_run=True, full=False, no_binaries=False,
        no_reconcile=False, smoke=None,
    )

    with pytest.raises(ValueError, match="explicit account"):
        asyncio.run(sync.main(args))


def test_gemini_profile_and_data_paths_are_unchanged():
    assert get_profile_dir("2").as_posix() == ".storage/gemini-profile-2"
    assert (sync.MERGED_BASE / "account-2").as_posix() == "data/merged/Gemini/account-2"


def test_sync_accepts_dynamic_explicit_account(capsys):
    args = argparse.Namespace(account="work", dry_run=True, full=False, no_binaries=False,
                              no_reconcile=False, smoke=None)
    assert asyncio.run(sync.main(args)) == 0
    assert "Account work:" in capsys.readouterr().out


def test_auxiliary_commands_find_current_canonical_raw_tree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    capture = Path("data/raw/Gemini/account-2")
    capture.mkdir(parents=True)

    assert download_assets._find_latest_raw(2) == capture
    assert reconcile._find_latest_raw(2) == capture


def test_operational_commands_do_not_duplicate_account_choices():
    commands = Path("src/platforms/gemini/commands")
    for name in ("login.py", "sync.py", "export.py", "download_assets.py", "reconcile.py", "merge_timestamps.py"):
        assert "choices=[1, 2, 3]" not in (commands / name).read_text()


def test_only_historical_timestamp_tool_references_legacy_gemini_data_tree():
    commands = Path("src/platforms/gemini/commands")
    matches = {
        path.name for path in commands.glob("*.py") if "Gemini Data" in path.read_text()
    }

    assert matches == {"merge_timestamps.py"}
