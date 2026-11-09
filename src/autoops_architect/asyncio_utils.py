"""Helpers for the synchronous wrappers around async APIs."""

import asyncio


def ensure_no_running_loop(caller: str, alternative: str) -> None:
    """
    Raise if called from inside a running event loop.

    asyncio.run() fails there too, but only after the coroutine has been created
    and with a message that does not say which API to call instead.

    Args:
        caller: Name of the synchronous wrapper.
        alternative: Name of the coroutine to await instead.

    Raises:
        RuntimeError: If an event loop is running in this thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return

    raise RuntimeError(
        f"{caller}() cannot be called from an async context. Use await {alternative}() instead."
    )
