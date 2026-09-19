from __future__ import annotations

import pytest

from src.assets.runtime import ASSET_MODE_ENV


@pytest.fixture(autouse=True)
def isolate_parser_unit_tests_from_the_canonical_vault(monkeypatch):
    """Keep parser fixtures local; vault-default behavior has dedicated tests."""
    monkeypatch.setenv(ASSET_MODE_ENV, "legacy")
