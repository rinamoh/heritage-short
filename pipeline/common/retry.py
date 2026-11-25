"""Retry helper with exponential backoff for transient timeouts and 5xx errors."""

from collections.abc import Callable
from dataclasses import dataclass
import time
from typing import Any, TypeVar

import requests

T = TypeVar("T")

DEFAULT_ATTEMPTS: int = 3
DEFAULT_BACKOFF_SECONDS: tuple[float, ...] = (2.0, 4.0, 8.0)


@dataclass(frozen=True)
class CallResult:
    """Outcome of a retried call, returning failure details instead of crashing."""

    ok: bool
    value: Any = None
    error: str | None = None
    attempts: int = 0
    status_code: int | None = None


def extract_status_code(exc: BaseException) -> int | None:
    """Extract an HTTP status code from an exception if one is attached."""
    response = getattr(exc, "response", None)
    if response is not None:
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return status_code

    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


def is_retryable_error(exc: BaseException) -> bool:
    """Return True only for timeouts and 5xx server errors; never retry 429 quota errors."""
    status_code = extract_status_code(exc)
    if status_code is not None:
        if status_code == 429:
            return False
        return 500 <= status_code < 600

    if isinstance(exc, (TimeoutError, requests.Timeout)):
        return True

    message = str(exc).lower()
    if "429" in message or "quota" in message or "resource_exhausted" in message:
        return False
    return False


def run_with_retry(
    fn: Callable[[], T],
    attempts: int = DEFAULT_ATTEMPTS,
    backoff_seconds: tuple[float, ...] = DEFAULT_BACKOFF_SECONDS,
    should_retry: Callable[[BaseException], bool] = is_retryable_error,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> CallResult:
    """Run a synchronous callable up to N attempts, returning a failed CallResult on error."""
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return CallResult(ok=True, value=fn(), attempts=attempt)
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts or not should_retry(exc):
                return CallResult(
                    ok=False,
                    value=None,
                    error=f"{type(exc).__name__}: {exc}",
                    attempts=attempt,
                    status_code=extract_status_code(exc),
                )
            delay = backoff_seconds[min(attempt - 1, len(backoff_seconds) - 1)]
            sleep_fn(delay)

    error_text = f"{type(last_exc).__name__}: {last_exc}" if last_exc else "Unknown error"
    return CallResult(ok=False, value=None, error=error_text, attempts=attempts)
