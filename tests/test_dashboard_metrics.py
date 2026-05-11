"""Tests do dashboard.metrics — foco em discovery_drop_flag.

Bug historico (2026-05-11): discovery_drop_flag misturava runs de contas
diferentes em plataformas multi-conta (Gemini/NotebookLM). Comparava
acc-1=46 vs acc-2=33 e disparava falso positivo. Fix segmenta por account
antes de comparar.
"""
from datetime import datetime, timezone

from dashboard.data import CaptureRun, PlatformState
from dashboard.metrics import discovery_drop_flag


def _run(started: datetime, total: int, mode: str = "incremental", account: str | None = None) -> CaptureRun:
    return CaptureRun(
        started_at=started,
        finished_at=started,
        duration_seconds=1.0,
        discovery_total=total,
        fetch_attempted=0,
        fetch_succeeded=0,
        mode=mode,
        account=account,
    )


def _state(name: str, runs: list[CaptureRun]) -> PlatformState:
    return PlatformState(name=name, raw_dir=None, merged_dir=None, capture_runs=runs)


def test_drop_flag_false_when_single_account_stable():
    runs = [
        _run(datetime(2026, 5, 1, tzinfo=timezone.utc), 1168),
        _run(datetime(2026, 5, 11, tzinfo=timezone.utc), 1168),
    ]
    assert discovery_drop_flag(_state("ChatGPT", runs)) is False


def test_drop_flag_true_when_real_drop():
    runs = [
        _run(datetime(2026, 5, 1, tzinfo=timezone.utc), 1168),
        _run(datetime(2026, 5, 11, tzinfo=timezone.utc), 700),  # 40% drop
    ]
    assert discovery_drop_flag(_state("ChatGPT", runs)) is True


def test_drop_flag_false_for_multiaccount_with_different_volumes():
    """Gemini scenario: acc-1=46 estavel, acc-2=33 estavel — sem drop em
    nenhuma conta. Pre-fix: misturava runs e comparava 33 (acc-2 latest)
    contra 47 (acc-1 max), disparava drop falso.
    """
    runs = [
        _run(datetime(2026, 5, 2, 9, tzinfo=timezone.utc), 47, account="1"),
        _run(datetime(2026, 5, 2, 10, tzinfo=timezone.utc), 46, account="1"),
        _run(datetime(2026, 5, 2, 11, tzinfo=timezone.utc), 33, account="2"),
        _run(datetime(2026, 5, 11, 20, 36, 3, tzinfo=timezone.utc), 46, account="1"),
        _run(datetime(2026, 5, 11, 20, 36, 16, tzinfo=timezone.utc), 33, account="2"),
    ]
    assert discovery_drop_flag(_state("Gemini", runs)) is False


def test_drop_flag_true_when_one_account_drops_in_multi():
    """Se UMA conta de plataforma multi-conta sofre drop real, dispara."""
    runs = [
        _run(datetime(2026, 5, 1, tzinfo=timezone.utc), 100, account="1"),
        _run(datetime(2026, 5, 1, tzinfo=timezone.utc), 50, account="2"),
        _run(datetime(2026, 5, 11, tzinfo=timezone.utc), 100, account="1"),
        _run(datetime(2026, 5, 11, tzinfo=timezone.utc), 30, account="2"),  # acc-2 drop 40%
    ]
    assert discovery_drop_flag(_state("Gemini", runs)) is True


def test_drop_flag_ignores_refetch_known_modes():
    """refetch_known/refetch_known_fallback nao representam discovery global."""
    runs = [
        _run(datetime(2026, 5, 1, tzinfo=timezone.utc), 1168),
        _run(datetime(2026, 5, 11, tzinfo=timezone.utc), 138, mode="refetch_known_fallback"),
        _run(datetime(2026, 5, 11, tzinfo=timezone.utc), 1168, mode="refetch_known"),
    ]
    assert discovery_drop_flag(_state("ChatGPT", runs)) is False
