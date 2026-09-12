from src.extractors.notebooklm.auth import VALID_ACCOUNTS, get_profile_dir


def test_third_notebooklm_account_has_its_own_profile_directory():
    assert "3" in VALID_ACCOUNTS
    assert get_profile_dir("3").name == "notebooklm-profile-3"
