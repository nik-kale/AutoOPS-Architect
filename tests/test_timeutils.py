"""Tests for the UTC timestamp helper."""

from datetime import UTC, datetime, timedelta

from autoops_architect.models.goal import Goal
from autoops_architect.timeutils import utcnow


def test_utcnow_is_naive_and_in_utc() -> None:
    now = utcnow()

    assert now.tzinfo is None
    assert abs(now - datetime.now(UTC).replace(tzinfo=None)) < timedelta(seconds=5)


def test_new_timestamps_compare_with_stored_history() -> None:
    stored = datetime.fromisoformat("2025-01-01T00:00:00")

    assert Goal(description="A goal long enough to be valid").created_at > stored
