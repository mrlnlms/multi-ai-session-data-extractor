import argparse
import asyncio

import pytest

from src.platforms.notebooklm.commands import login as login_command
from src.platforms.notebooklm.commands import sync
from src.platforms.notebooklm.extractor.auth import get_profile_dir


def test_login_requires_account_with_current_choices():
    with pytest.raises(SystemExit):
        login_command.build_parser().parse_args([])
    assert login_command.build_parser().parse_args(["--account", "work"]).account == "work"
    with pytest.raises(SystemExit):
        login_command.build_parser().parse_args(["--account", "archive:old"])


def test_sync_requires_explicit_account_even_for_programmatic_calls():
    args = argparse.Namespace(
        account=None, dry_run=True, full=False, no_binaries=False,
        no_reconcile=False, smoke=None,
    )

    with pytest.raises(ValueError, match="explicit account"):
        asyncio.run(sync.main(args))


def test_notebooklm_profile_and_data_paths_are_unchanged():
    assert get_profile_dir("2").as_posix() == ".storage/notebooklm-profile-2"
    assert (sync.MERGED_BASE / "account-2").as_posix() == "data/merged/NotebookLM/account-2"


def test_sync_accepts_dynamic_explicit_account(capsys):
    args = argparse.Namespace(account="work", dry_run=True, full=False, no_binaries=False,
                              no_reconcile=False, smoke=None)
    assert asyncio.run(sync.main(args)) == 0
    assert "Account work:" in capsys.readouterr().out
