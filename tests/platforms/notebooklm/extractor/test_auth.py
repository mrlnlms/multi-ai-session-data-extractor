from pathlib import Path

from src.platforms.notebooklm.extractor.auth import VALID_ACCOUNTS, get_profile_dir


def test_third_notebooklm_account_can_use_a_shared_profile(mocker):
    assert "3" in VALID_ACCOUNTS
    resolved = mocker.patch(
        "src.platforms.notebooklm.extractor.auth.resolve_platform_browser_target",
        return_value=mocker.Mock(path=Path(".storage/shared-notebooklm")),
    )
    assert get_profile_dir("3") == Path(".storage/shared-notebooklm")
    resolved.assert_called_once_with(
        "NotebookLM", "3", legacy_path=Path(".storage/notebooklm-profile-3"),
        legacy_channel="chrome",
    )
