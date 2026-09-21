from __future__ import annotations

from pathlib import Path


def test_terminal_pipeline_defaults_to_all_known_platforms():
    from src.platforms.registry import KNOWN_PLATFORMS
    from src.workflows import headless

    assert headless.PIPELINE_DEFAULT == KNOWN_PLATFORMS


def test_headless_defaults_to_vault_and_canonical_roots(monkeypatch):
    from src.workflows import headless

    calls = []
    persisted = []
    monkeypatch.setattr(
        headless,
        "run_sync_streaming",
        lambda platform, on_line, **kwargs: (calls.append((platform, kwargs)) or (0, "ok")),
    )
    monkeypatch.setattr(headless, "run_unify_streaming", lambda on_line: (0, "ok"))
    monkeypatch.setattr(headless, "quarto_installed", lambda: False)
    monkeypatch.setattr(
        headless,
        "persist_run",
        lambda *args, **kwargs: persisted.append(kwargs["asset_modes"]),
    )

    result = headless._run(
        ["Codex"],
        False,
        asset_vault_root=Path("data/assets"),
        asset_data_root=Path("data"),
    )

    assert result == 0
    assert calls == [
        (
            "Codex",
            {
                "asset_mode": "vault",
                "vault_root": Path("data/assets"),
                "data_root": Path("data"),
            },
        )
    ]
    assert persisted == [{"Codex": "vault"}]


def test_headless_keeps_explicit_legacy_rollback(monkeypatch):
    from src.workflows import headless

    calls = []
    monkeypatch.setattr(
        headless,
        "run_sync_streaming",
        lambda platform, on_line, **kwargs: (calls.append(kwargs) or (0, "ok")),
    )
    monkeypatch.setattr(headless, "run_unify_streaming", lambda on_line: (0, "ok"))
    monkeypatch.setattr(headless, "quarto_installed", lambda: False)
    monkeypatch.setattr(headless, "persist_run", lambda *args, **kwargs: None)

    result = headless._run(
        ["Codex"],
        False,
        asset_modes={"Codex": "legacy"},
        asset_vault_root=Path("data/assets"),
        asset_data_root=Path("data"),
    )

    assert result == 0
    assert calls == [
        {
            "asset_mode": "legacy",
            "vault_root": Path("data/assets"),
            "data_root": Path("data"),
        }
    ]
