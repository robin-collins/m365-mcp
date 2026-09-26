"""Hold the object that reports cache warming status."""

from __future__ import annotations

from typing import Any, Protocol

__all__ = [
    "WarmingStatusProvider",
    "get_warming_status_provider",
    "set_warming_status_provider",
]


class WarmingStatusProvider(Protocol):
    """Object capable of reporting cache warming status."""

    def get_warming_status(self) -> dict[str, Any]:
        """Return the current cache warming status."""
        ...


_provider: WarmingStatusProvider | None = None


def set_warming_status_provider(provider: WarmingStatusProvider | None) -> None:
    """Set the object that owns cache warming status.

    Args:
        provider: A cache warmer or background worker, or ``None`` to clear.
    """
    global _provider
    _provider = provider


def get_warming_status_provider() -> WarmingStatusProvider | None:
    """Return the current warming status provider.

    Returns:
        The registered provider, or ``None`` when warming is inactive.
    """
    return _provider
