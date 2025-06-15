import time
import httpx
from typing import Any, Callable
from .exceptions import RateLimitError, GraphAPIError
from .logging_config import setup_logging

logger = setup_logging()


def _exponential_backoff(attempt: int, base_delay: float = 1.0) -> float:
    return min(base_delay * (2**attempt), 60.0)


def retry_with_backoff(
    func: Callable[[], Any],
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> Any:
    last_error = None

    for attempt in range(max_attempts):
        try:
            return func()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                if attempt < max_attempts - 1:
                    delay = _exponential_backoff(attempt, base_delay)
                    logger.warning(f"Rate limit hit, retrying in {delay:.1f}s")
                    time.sleep(delay)
                    continue
                raise RateLimitError(
                    f"Rate limit exceeded after {max_attempts} attempts"
                )
            elif e.response.status_code >= 500:
                if attempt < max_attempts - 1:
                    delay = _exponential_backoff(attempt, base_delay)
                    logger.warning(
                        f"Server error {e.response.status_code}, retrying in {delay:.1f}s"
                    )
                    time.sleep(delay)
                    continue
            last_error = e
            raise GraphAPIError(f"HTTP {e.response.status_code}: {e.response.text}")
        except Exception as e:
            last_error = e
            if attempt == max_attempts - 1:
                raise

    raise last_error if last_error else GraphAPIError("Unknown error during retry")
