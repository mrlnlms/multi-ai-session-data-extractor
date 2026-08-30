from datetime import datetime, timezone

from dashboard.data import CaptureRun, PlatformState


def test_recent_capture_with_errors_is_not_green():
    state = PlatformState(
        name="Perplexity",
        raw_dir=None,
        merged_dir=None,
        capture_runs=[CaptureRun(
            started_at=datetime.now(timezone.utc), finished_at=None,
            duration_seconds=None, discovery_total=None, fetch_attempted=None,
            fetch_succeeded=None, errors_count=1,
        )],
    )

    assert state.status() == "yellow"
