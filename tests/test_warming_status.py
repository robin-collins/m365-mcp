"""Tests for the warming-status provider registry."""

from __future__ import annotations

from typing import Any

from m365_mcp import warming_status


class _Provider:
    def get_warming_status(self) -> dict[str, Any]:
        return {"is_warming": False}


def test_provider_defaults_to_none() -> None:
    warming_status.set_warming_status_provider(None)
    assert warming_status.get_warming_status_provider() is None


def test_provider_round_trip_and_reset() -> None:
    provider = _Provider()
    warming_status.set_warming_status_provider(provider)
    try:
        assert warming_status.get_warming_status_provider() is provider
    finally:
        warming_status.set_warming_status_provider(None)
    assert warming_status.get_warming_status_provider() is None
