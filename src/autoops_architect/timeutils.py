"""Time helpers."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """
    Return the current UTC time as a naive datetime.

    Stored timestamps are naive UTC, so new ones stay naive to remain comparable
    with existing history.
    """
    return datetime.now(UTC).replace(tzinfo=None)
