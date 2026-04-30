"""Generic async retry utility with exponential backoff and jitter."""

from __future__ import annotations

import asyncio
import functools
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger: logging.Logger = logging.getLogger(__name__)
T = TypeVar("T")

RETRYABLE_DEFAULTS: tuple[type[Exception], ...] = (OSError,)


class RetryExhausted(Exception):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, operation: str, attempts: int, last_exception: Exception) -> None:
        self.operation = operation
        self.attempts = attempts
        self.last_exception = last_exception
        super().__init__(f"{operation} failed after {attempts} attempts: {last_exception}")


async def retry_async(
    fn: Callable[..., Awaitable[T]],
    *args: object,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    retryable: tuple[type[Exception], ...] = RETRYABLE_DEFAULTS,
    **kwargs: object,
) -> T:
    """Retry an async callable with exponential backoff.

    Args:
        fn: The async callable to invoke.
        max_retries: Maximum number of retry attempts (excludes the initial try).
        base_delay: Starting delay in seconds, doubled each retry.
        max_delay: Cap on delay in seconds.
        retryable: Tuple of exception types that trigger a retry.

    Raises:
        RetryExhausted: After all attempts fail (wraps the last exception).

    Returns:
        The return value of fn.
    """
    last_exception: Exception | None = None
    total_attempts: int = max_retries + 1

    for attempt in range(total_attempts):
        try:
            return await fn(*args, **kwargs)
        except retryable as exc:
            last_exception = exc
            if attempt < max_retries:
                delay: float = min(base_delay * (2**attempt), max_delay)
                delay *= 1.0 + random.random() * 0.1
                logger.warning(
                    "Retry attempt %d/%d for %s: %s — retrying in %.2fs",
                    attempt + 1,
                    max_retries,
                    getattr(fn, "__name__", str(fn)),
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "All %d attempts exhausted for %s: %s",
                    total_attempts,
                    getattr(fn, "__name__", str(fn)),
                    exc,
                )

    raise RetryExhausted(
        operation=getattr(fn, "__name__", str(fn)),
        attempts=total_attempts,
        last_exception=last_exception,  # type: ignore[arg-type]
    )


async def retry_sync(
    fn: Callable[..., T],
    *args: object,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    retryable: tuple[type[Exception], ...] = RETRYABLE_DEFAULTS,
    **kwargs: object,
) -> T:
    """Run a sync callable via asyncio.to_thread with retry.

    Args:
        fn: The synchronous callable to invoke in a thread.
        max_retries: Maximum number of retry attempts (excludes the initial try).
        base_delay: Starting delay in seconds, doubled each retry.
        max_delay: Cap on delay in seconds.
        retryable: Tuple of exception types that trigger a retry.

    Raises:
        RetryExhausted: After all attempts fail (wraps the last exception).

    Returns:
        The return value of fn.
    """
    last_exception: Exception | None = None
    total_attempts: int = max_retries + 1

    for attempt in range(total_attempts):
        try:
            partial = functools.partial(fn, *args, **kwargs)
            return await asyncio.to_thread(partial)
        except retryable as exc:
            last_exception = exc
            if attempt < max_retries:
                delay: float = min(base_delay * (2**attempt), max_delay)
                delay *= 1.0 + random.random() * 0.1
                logger.warning(
                    "Retry attempt %d/%d for %s: %s — retrying in %.2fs",
                    attempt + 1,
                    max_retries,
                    getattr(fn, "__name__", str(fn)),
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "All %d attempts exhausted for %s: %s",
                    total_attempts,
                    getattr(fn, "__name__", str(fn)),
                    exc,
                )

    raise RetryExhausted(
        operation=getattr(fn, "__name__", str(fn)),
        attempts=total_attempts,
        last_exception=last_exception,  # type: ignore[arg-type]
    )


__all__: list[str] = ["RetryExhausted", "retry_async", "retry_sync"]
