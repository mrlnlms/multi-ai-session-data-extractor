import json

import pytest

from pathlib import Path

from src.accounts import account_data_dir, account_email, load_account_registry


def test_load_account_registry_returns_profile_email_mapping(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"chatgpt": {"default": "name@example.com"}}))

    assert load_account_registry(path) == {"chatgpt": {"default": "name@example.com"}}
    assert account_email("chatgpt", "default", path) == "name@example.com"


def test_missing_registry_leaves_account_unset(tmp_path):
    path = tmp_path / "missing.json"

    assert load_account_registry(path) == {}
    assert account_email("chatgpt", "default", path) is None


def test_account_data_dir_keeps_default_and_accepts_both_account_key_forms():
    base = Path("data/raw/ChatGPT")

    assert account_data_dir(base, "default") == base
    assert account_data_dir(base, "2") == base / "account-2"
    assert account_data_dir(base, "account-2") == base / "account-2"


@pytest.mark.parametrize("content", ["[]", '{"chatgpt": []}', '{"chatgpt": {"default": ""}}'])
def test_invalid_registry_is_rejected(tmp_path, content):
    path = tmp_path / "accounts.json"
    path.write_text(content)

    with pytest.raises(ValueError):
        load_account_registry(path)
