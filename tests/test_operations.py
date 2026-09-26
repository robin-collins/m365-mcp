"""Tests for the drive_copy operation store (task U2.16)."""

from __future__ import annotations

import httpx
import pytest

from src.m365_mcp import graph, operations
from src.m365_mcp.operations import (
    OPERATION_TTL_SECONDS,
    OperationStatusError,
    OperationStore,
)
from src.m365_mcp.validators import ValidationError

MONITOR_URL = "https://api.onedrive.com/v1.0/monitor/4A3407B5?access_token=secret"
UNKNOWN = (
    "Invalid id: unknown operation. Expected: an operation_id returned by "
    "drive_copy in the last 24 hours"
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


class FakeMonitor:
    """Serve a scripted sequence of monitor responses."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []

    def __call__(self, url: str) -> httpx.Response:
        self.urls.append(url)
        return self.responses.pop(0)


def _status(body: dict, code: int = 202) -> httpx.Response:
    return httpx.Response(code, json=body)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def test_record_returns_opaque_id(clock: FakeClock) -> None:
    store = OperationStore(fetch=FakeMonitor(), clock=clock)

    op_id = store.record(MONITOR_URL, "acc-1")

    assert op_id.startswith("op_")
    assert "onedrive" not in op_id and "4A3407B5" not in op_id
    assert op_id != store.record(MONITOR_URL, "acc-1")


def test_in_progress_then_completed(clock: FakeClock) -> None:
    monitor = FakeMonitor(
        _status({"status": "notStarted"}),
        _status({"status": "inProgress", "percentageComplete": 42.5}),
        _status(
            {
                "status": "completed",
                "percentageComplete": 100.0,
                "resourceId": "01NEWITEM",
            },
            200,
        ),
    )
    store = OperationStore(fetch=monitor, clock=clock)
    op_id = store.record(MONITOR_URL, "acc-1")

    assert store.get_status(op_id, "acc-1") == {
        "operation_id": op_id,
        "status": "in_progress",
        "percent_complete": None,
        "resource_id": None,
        "error": None,
    }
    assert store.get_status(op_id, "acc-1")["percent_complete"] == 42.5
    assert store.get_status(op_id, "acc-1") == {
        "operation_id": op_id,
        "status": "completed",
        "percent_complete": 100.0,
        "resource_id": "01NEWITEM",
        "error": None,
    }
    assert monitor.urls == [MONITOR_URL] * 3


def test_in_progress_then_failed(clock: FakeClock) -> None:
    monitor = FakeMonitor(
        _status({"status": "inProgress", "percentageComplete": 10}),
        _status(
            {
                "status": "failed",
                "percentageComplete": 10,
                "error": {
                    "code": "nameAlreadyExists",
                    "message": "An item with this name already exists.",
                },
            },
            200,
        ),
    )
    store = OperationStore(fetch=monitor, clock=clock)
    op_id = store.record(MONITOR_URL, "acc-1")

    assert store.get_status(op_id, "acc-1")["status"] == "in_progress"
    result = store.get_status(op_id, "acc-1")

    assert result["status"] == "failed"
    assert result["error"] == "An item with this name already exists."
    assert result["resource_id"] is None


def test_failed_without_error_body_has_generic_message(
    clock: FakeClock,
) -> None:
    store = OperationStore(
        fetch=FakeMonitor(_status({"status": "failed"}, 200)), clock=clock
    )
    op_id = store.record(MONITOR_URL, "acc-1")

    assert store.get_status(op_id, "acc-1")["error"] == "The copy failed."


def test_see_other_redirect_means_completed(clock: FakeClock) -> None:
    redirect = httpx.Response(
        303,
        headers={"Location": "https://api.onedrive.com/v1.0/drives/abc/items/01NEW"},
    )
    store = OperationStore(fetch=FakeMonitor(redirect), clock=clock)
    op_id = store.record(MONITOR_URL, "acc-1")

    result = store.get_status(op_id, "acc-1")

    assert result["status"] == "completed"
    assert result["resource_id"] == "01NEW"
    assert result["percent_complete"] == 100


def test_terminal_status_is_not_polled_again(clock: FakeClock) -> None:
    monitor = FakeMonitor(_status({"status": "completed", "resourceId": "01X"}, 200))
    store = OperationStore(fetch=monitor, clock=clock)
    op_id = store.record(MONITOR_URL, "acc-1")

    first = store.get_status(op_id, "acc-1")
    assert store.get_status(op_id, "acc-1") == first
    assert len(monitor.urls) == 1


def test_monitor_url_never_in_result(clock: FakeClock) -> None:
    store = OperationStore(
        fetch=FakeMonitor(_status({"status": "inProgress"})), clock=clock
    )
    op_id = store.record(MONITOR_URL, "acc-1")

    assert "onedrive" not in repr(store.get_status(op_id, "acc-1"))


def test_unknown_id_is_rejected(clock: FakeClock) -> None:
    store = OperationStore(fetch=FakeMonitor(), clock=clock)

    with pytest.raises(ValidationError) as exc:
        store.get_status("op_nope", "acc-1")
    assert str(exc.value) == UNKNOWN


def test_other_account_cannot_read_operation(clock: FakeClock) -> None:
    store = OperationStore(fetch=FakeMonitor(), clock=clock)
    op_id = store.record(MONITOR_URL, "acc-1")

    with pytest.raises(ValidationError) as exc:
        store.get_status(op_id, "acc-2")
    assert str(exc.value) == UNKNOWN


def test_operation_expires_after_24_hours(clock: FakeClock) -> None:
    monitor = FakeMonitor(_status({"status": "inProgress"}))
    store = OperationStore(fetch=monitor, clock=clock)
    op_id = store.record(MONITOR_URL, "acc-1")

    clock.now += OPERATION_TTL_SECONDS
    store.get_status(op_id, "acc-1")

    clock.now += 1
    with pytest.raises(ValidationError) as exc:
        store.get_status(op_id, "acc-1")
    assert str(exc.value) == UNKNOWN
    assert len(monitor.urls) == 1


@pytest.mark.parametrize(
    "monitor_url",
    [
        "http://api.onedrive.com/monitor/1",
        "https://example.com/monitor/1",
        "https://user:password@api.onedrive.com/monitor/1",
    ],
)
def test_record_rejects_untrusted_monitor_urls(
    clock: FakeClock, monitor_url: str
) -> None:
    store = OperationStore(fetch=FakeMonitor(), clock=clock)

    with pytest.raises(ValidationError):
        store.record(monitor_url, "acc-1")


def test_default_fetch_sends_no_authorization_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, json={"status": "inProgress"})

    def fail_token(*args: object, **kwargs: object) -> str:
        raise AssertionError("no token may be requested for monitor polling")

    monkeypatch.setattr(
        graph, "_client", httpx.Client(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(graph, "get_token", fail_token)
    store = OperationStore()
    op_id = store.record(MONITOR_URL, "acc-1")

    assert store.get_status(op_id, "acc-1")["status"] == "in_progress"
    assert len(seen) == 1
    assert "authorization" not in {k.lower() for k in seen[0].headers}
    assert str(seen[0].url) == MONITOR_URL


def test_default_fetch_does_not_follow_completion_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            303,
            headers={"Location": "https://api.onedrive.com/v1.0/items/01NEW"},
        )

    monkeypatch.setattr(
        graph,
        "_client",
        httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True),
    )
    store = OperationStore()
    op_id = store.record(MONITOR_URL, "acc-1")

    assert store.get_status(op_id, "acc-1")["resource_id"] == "01NEW"
    assert len(seen) == 1


def test_module_store_exists() -> None:
    assert isinstance(operations.operation_store, OperationStore)


def test_monitor_failure_hides_url(clock: FakeClock) -> None:
    def fetch(url: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        response = httpx.Response(500, request=request)
        raise httpx.HTTPStatusError("boom " + url, request=request, response=response)

    store = OperationStore(fetch=fetch, clock=clock)
    op_id = store.record(MONITOR_URL, "acc-1")

    with pytest.raises(OperationStatusError) as exc:
        store.get_status(op_id, "acc-1")
    assert "HTTP 500" in str(exc.value)
    assert "secret" not in str(exc.value)
    assert exc.value.__cause__ is None
