from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Dict

import pytest

from src.microsoft_mcp.tools import search as search_tools
from src.microsoft_mcp.validators import ValidationError


@pytest.mark.parametrize(
    ("callable_fn", "kwargs"),
    [
        (
            search_tools.search_files.fn,
            {"query": "report", "account_id": "acc", "limit": 0},
        ),
        (
            search_tools.search_emails.fn,
            {"query": "report", "account_id": "acc", "limit": 0},
        ),
        (
            search_tools.search_contacts.fn,
            {"query": "user", "account_id": "acc", "limit": 0},
        ),
        (
            search_tools.search_unified.fn,
            {"query": "report", "account_id": "acc", "limit": 0},
        ),
    ],
)
def test_search_limits_reject_invalid_input(
    callable_fn: Callable[..., Any],
    kwargs: Dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        callable_fn(**kwargs)


def test_search_events_rejects_invalid_days(mock_account_id: str) -> None:
    with pytest.raises(ValidationError):
        search_tools.search_events.fn(
            query="meeting",
            account_id=mock_account_id,
            days_back=-1,
        )


def test_search_events_filters_by_range(
    monkeypatch: pytest.MonkeyPatch,
    mock_account_id: str,
) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    inside_start = (now - dt.timedelta(hours=1)).isoformat()
    inside_end = (now + dt.timedelta(hours=1)).isoformat()
    outside_start = (now - dt.timedelta(days=10)).isoformat()
    outside_end = (now - dt.timedelta(days=9, hours=20)).isoformat()

    def fake_search_query(
        query: str,
        entity_types: list[str],
        account_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        assert limit == 50
        return [
            {"start": {"dateTime": inside_start}, "end": {"dateTime": inside_end}},
            {"start": {"dateTime": outside_start}, "end": {"dateTime": outside_end}},
            {"start": {}, "end": {}},
        ]

    monkeypatch.setattr(search_tools.graph, "search_query", fake_search_query)

    results = search_tools.search_events.fn(
        query="meeting",
        account_id=mock_account_id,
        days_back=1,
        days_ahead=1,
        limit=50,
    )

    assert len(results) == 1
    assert results[0]["start"]["dateTime"] == inside_start
