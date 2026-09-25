import email.utils
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import httpx

from .auth import get_token
from .errors import DeadlineExceeded, GraphAPIError

BASE_URL = "https://graph.microsoft.com/v1.0"
# 15 x 320 KiB = 4,915,200 bytes
UPLOAD_CHUNK_SIZE = 15 * 320 * 1024
MAX_RETRY_WAIT_SECONDS = 60
# Per-call budget for all attempts and waits; transfers are exempt.
READ_DEADLINE_SECONDS = 45
WRITE_DEADLINE_SECONDS = 60
BATCH_MAX_REQUESTS = 20

# Methods that are safe to resend when the outcome of an attempt is unknown.
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_client = httpx.Client(timeout=30.0, follow_redirects=True)
# Injectable monotonic clock for the deadline budget (tests use a fake).
_clock: Callable[[], float] = time.monotonic


def _retry_after_seconds(response: httpx.Response, default: float) -> float:
    """Return the server-requested retry delay, capped, or ``default``.

    Retry-After may be delta-seconds or an HTTP date.
    """
    value = response.headers.get("Retry-After")
    if not value:
        return min(default, MAX_RETRY_WAIT_SECONDS)
    try:
        delay = float(value)
    except ValueError:
        try:
            retry_at = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            retry_at = None
        if retry_at is not None and retry_at.tzinfo is not None:
            delay = (retry_at - datetime.now(UTC)).total_seconds()
        else:
            delay = default
    return min(max(delay, 0.0), MAX_RETRY_WAIT_SECONDS)


def _deadline_for(methods: list[str]) -> int:
    """Return the budget: the read budget only if every method reads."""
    if all(method in _READ_METHODS for method in methods):
        return READ_DEADLINE_SECONDS
    return WRITE_DEADLINE_SECONDS


def _check_deadline(started: float, budget: float | None, delay: float) -> None:
    """Raise if waiting ``delay`` more seconds would exceed the budget.

    Args:
        started: Clock reading when the call began.
        budget: Budget in seconds, or ``None`` for exempt transfers.
        delay: Seconds the next wait would take (0 for an immediate retry).

    Raises:
        DeadlineExceeded: If the retry would not fit in the budget.
    """
    if budget is not None and _clock() - started + delay > budget:
        raise DeadlineExceeded(delay)


def _should_retry_status(method: str, status_code: int) -> bool:
    """Decide whether an error status is worth retrying.

    429 and 503 mean the request was not processed. Other 5xx responses may
    arrive after a write took effect, so they are only retried for
    idempotent methods (never, for example, a POST that sends an email).
    """
    if status_code in (429, 503):
        return True
    return status_code >= 500 and method in _IDEMPOTENT_METHODS


def _should_retry_transport(method: str, exc: httpx.TransportError) -> bool:
    """Decide whether a network error is worth retrying.

    Connection failures mean the request never reached Graph. Timeouts and
    dropped connections may happen after Graph acted, so they are only
    retried for idempotent methods.
    """
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return True
    return method in _IDEMPOTENT_METHODS


def _send(
    method: str,
    url: str,
    account_id: str | None,
    headers: dict[str, str] | None = None,
    max_retries: int = 3,
    authenticate: bool = True,
    transfer: bool = False,
    **kwargs: Any,
) -> httpx.Response:
    """Send an HTTP request with auth, retries and backoff.

    A token is fetched for every attempt, so long throttling waits never
    reuse an expired token. A 401 triggers one forced token refresh.

    Every retry and wait is checked against a per-call budget
    (``READ_DEADLINE_SECONDS`` for GET/HEAD/OPTIONS, otherwise
    ``WRITE_DEADLINE_SECONDS``) measured from the first attempt, so a tool
    call cannot hang on repeated throttling.

    Args:
        method: HTTP method.
        url: Absolute URL.
        account_id: Account whose token authorises the request.
        headers: Extra request headers.
        max_retries: Retries for throttling, server and network errors.
        authenticate: Add a bearer token. Disable for pre-authenticated
            upload session URLs.
        transfer: Exempt an upload or download chunk from the deadline
            budget.
        **kwargs: Passed through to ``httpx.Client.request``.

    Returns:
        The successful response.

    Raises:
        GraphAPIError: If the final response is an error status (a
            subclass of ``httpx.HTTPStatusError``).
        DeadlineExceeded: If another retry would exceed the budget.
        httpx.TransportError: If the network error cannot be retried.
    """
    method = method.upper()
    budget = None if transfer else _deadline_for([method])
    started = _clock()
    retry_count = 0
    force_refresh = False
    refreshed_after_401 = False

    while True:
        request_headers = dict(headers or {})
        if authenticate:
            token = get_token(account_id, force_refresh=force_refresh)
            request_headers["Authorization"] = f"Bearer {token}"
            force_refresh = False

        try:
            response = _client.request(
                method=method, url=url, headers=request_headers, **kwargs
            )
        except httpx.TransportError as exc:
            if retry_count < max_retries and _should_retry_transport(method, exc):
                delay = 2**retry_count
                try:
                    _check_deadline(started, budget, delay)
                except DeadlineExceeded as deadline:
                    raise deadline from exc
                time.sleep(delay)
                retry_count += 1
                continue
            raise

        if response.status_code == 401 and authenticate and not refreshed_after_401:
            # The access token was rejected (revoked or expired early);
            # redeem the refresh token once and try again.
            _check_deadline(started, budget, 0)
            force_refresh = True
            refreshed_after_401 = True
            continue

        if retry_count < max_retries and _should_retry_status(
            method, response.status_code
        ):
            delay = _retry_after_seconds(response, 2**retry_count)
            _check_deadline(started, budget, delay)
            time.sleep(delay)
            retry_count += 1
            continue

        if not response.is_success:
            retry_after = (
                _retry_after_seconds(response, 0)
                if "Retry-After" in response.headers
                else None
            )
            raise GraphAPIError.from_response(response, retry_after=retry_after)
        return response


def _query_headers(
    method: str, params: dict[str, Any] | None
) -> tuple[dict[str, str], dict[str, Any] | None]:
    """Build Graph query headers and the params to send.

    Returns a copy of ``params`` so the caller's dict is never mutated.
    """
    params = dict(params) if params else params
    headers: dict[str, str] = {}

    if (
        method == "GET"
        and params
        and ("$search" in params or "body" in params.get("$select", ""))
    ):
        headers["Prefer"] = 'outlook.body-content-type="text"'

    if params and (
        "$search" in params
        or "contains(" in params.get("$filter", "")
        or "/any(" in params.get("$filter", "")
    ):
        headers["ConsistencyLevel"] = "eventual"
        params.setdefault("$count", "true")

    return headers, params


def request(
    method: str,
    path: str,
    account_id: str | None = None,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    data: bytes | None = None,
    max_retries: int = 3,
    headers: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    request_headers, params = _query_headers(method, params)
    if method != "GET":
        request_headers["Content-Type"] = (
            "application/json" if json else "application/octet-stream"
        )
    if headers:
        request_headers.update(headers)

    response = _send(
        method,
        f"{BASE_URL}{path}",
        account_id,
        headers=request_headers,
        max_retries=max_retries,
        params=params,
        json=json,
        content=data,
    )
    if response.content:
        return response.json()
    return None


def request_paginated(
    path: str,
    account_id: str | None = None,
    params: dict[str, Any] | None = None,
    limit: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Make paginated requests following @odata.nextLink.

    The nextLink already encodes the query, but the headers the first page
    needed (plain-text bodies, eventual consistency) must be sent again.
    """
    page_headers, _ = _query_headers("GET", params)
    items_returned = 0
    next_link = None

    while True:
        if next_link:
            result = request(
                "GET",
                next_link.replace(BASE_URL, ""),
                account_id,
                headers=page_headers,
            )
        else:
            result = request("GET", path, account_id, params=params)

        if not result:
            break

        if "value" in result:
            for item in result["value"]:
                if limit and items_returned >= limit:
                    return
                yield item
                items_returned += 1

        next_link = result.get("@odata.nextLink")
        if not next_link:
            break


def _batch_envelope(index: int, item: dict[str, Any]) -> dict[str, Any]:
    """Build one ``$batch`` request entry; its id is the input index."""
    entry: dict[str, Any] = {
        "id": str(index),
        "method": item["method"].upper(),
        "url": item["url"],
    }
    headers = dict(item.get("headers") or {})
    if "body" in item:
        entry["body"] = item["body"]
        headers.setdefault("Content-Type", "application/json")
    if headers:
        entry["headers"] = headers
    return entry


def batch(
    requests: list[dict[str, Any]],
    account_id: str | None = None,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    """Run requests through Graph JSON batching (``POST /$batch``).

    Requests are sent at most ``BATCH_MAX_REQUESTS`` (20) per call. Item
    failures do not raise; each result carries its own status. Throttled
    (429) and 5xx items are resent after the longest Retry-After among
    them, but only for idempotent methods (GET, HEAD, OPTIONS, PUT,
    DELETE). POST and PATCH items are never resent, even on 429, so a
    batched write can never be applied twice; their error is returned for
    the caller to handle. Retries stop at ``max_retries`` or when the next
    wait would exceed the deadline budget; the last item results are then
    returned as they are.

    Args:
        requests: Items with ``method``, ``url`` (relative to the Graph
            version root, e.g. ``/me/messages/1``), and optional ``body``,
            ``headers`` and ``id``.
        account_id: Account whose token authorises the batch.
        max_retries: Retry rounds for throttled idempotent items.

    Returns:
        One dict per input request, in input order, with ``id`` (the
        caller's id, or the input index as a string), ``status``,
        ``headers`` and ``body``.

    Raises:
        GraphAPIError: If a ``$batch`` call itself fails.
        DeadlineExceeded: If a ``$batch`` call runs out of budget.
    """
    results: list[dict[str, Any] | None] = [None] * len(requests)
    methods = [item["method"].upper() for item in requests]
    budget = _deadline_for(methods)
    started = _clock()
    pending = list(range(len(requests)))
    retry_count = 0

    while pending:
        retry: dict[int, httpx.Response] = {}
        for start in range(0, len(pending), BATCH_MAX_REQUESTS):
            chunk = pending[start : start + BATCH_MAX_REQUESTS]
            response = _send(
                "POST",
                f"{BASE_URL}/$batch",
                account_id,
                headers={"Content-Type": "application/json"},
                json={"requests": [_batch_envelope(i, requests[i]) for i in chunk]},
            )
            for item in response.json().get("responses", []):
                index = int(item["id"])
                status = int(item.get("status") or 0)
                headers = item.get("headers") or {}
                results[index] = {
                    "id": str(requests[index].get("id", index)),
                    "status": status,
                    "headers": headers,
                    "body": item.get("body"),
                }
                method = methods[index]
                if method in _IDEMPOTENT_METHODS and _should_retry_status(
                    method, status
                ):
                    retry[index] = httpx.Response(status, headers=headers)

        if not retry or retry_count >= max_retries:
            break
        delay = max(
            _retry_after_seconds(item, 2**retry_count) for item in retry.values()
        )
        try:
            _check_deadline(started, budget, delay)
        except DeadlineExceeded:
            break
        time.sleep(delay)
        retry_count += 1
        pending = sorted(retry)

    return [result for result in results if result is not None]


def download_raw(
    path: str, account_id: str | None = None, max_retries: int = 3
) -> bytes:
    response = _send(
        "GET",
        f"{BASE_URL}{path}",
        account_id,
        max_retries=max_retries,
        transfer=True,
    )
    return response.content


def _do_chunked_upload(upload_url: str, data: bytes) -> dict[str, Any]:
    """Upload data to a pre-authenticated upload session URL in chunks.

    The upload URL embeds its own credential; Microsoft documents that
    sending an Authorization header to it can cause 401 responses.
    """
    file_size = len(data)

    for chunk_start in range(0, file_size, UPLOAD_CHUNK_SIZE):
        chunk_end = min(chunk_start + UPLOAD_CHUNK_SIZE, file_size)
        chunk = data[chunk_start:chunk_end]

        chunk_headers = {
            "Content-Length": str(len(chunk)),
            "Content-Range": f"bytes {chunk_start}-{chunk_end - 1}/{file_size}",
        }
        response = _send(
            "PUT",
            upload_url,
            None,
            headers=chunk_headers,
            authenticate=False,
            transfer=True,
            content=chunk,
        )

        if response.status_code in (200, 201):
            # Mail attachment sessions finish with an empty 201 body.
            return response.json() if response.content else {}

    raise ValueError("Upload completed but no final response received")


def create_upload_session(
    path: str,
    account_id: str | None = None,
    item_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an upload session for large files"""
    payload = {"item": item_properties or {}}
    result = request("POST", f"{path}/createUploadSession", account_id, json=payload)
    if not result:
        raise ValueError("Failed to create upload session")
    return result


def upload_large_file(
    path: str,
    data: bytes,
    account_id: str | None = None,
    item_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Upload a large file using upload sessions"""
    file_size = len(data)

    if file_size <= UPLOAD_CHUNK_SIZE:
        result = request("PUT", f"{path}/content", account_id, data=data)
        if not result:
            raise ValueError("Failed to upload file")
        return result

    session = create_upload_session(path, account_id, item_properties)
    return _do_chunked_upload(session["uploadUrl"], data)


def create_mail_upload_session(
    message_id: str,
    attachment_item: dict[str, Any],
    account_id: str | None = None,
) -> dict[str, Any]:
    """Create an upload session for large mail attachments"""
    result = request(
        "POST",
        f"/me/messages/{message_id}/attachments/createUploadSession",
        account_id,
        json={"AttachmentItem": attachment_item},
    )
    if not result:
        raise ValueError("Failed to create mail attachment upload session")
    return result


def upload_large_mail_attachment(
    message_id: str,
    name: str,
    data: bytes,
    account_id: str | None = None,
    content_type: str = "application/octet-stream",
) -> dict[str, Any]:
    """Upload a large mail attachment using upload sessions"""
    file_size = len(data)

    attachment_item = {
        "attachmentType": "file",
        "name": name,
        "size": file_size,
        "contentType": content_type,
    }

    session = create_mail_upload_session(message_id, attachment_item, account_id)
    return _do_chunked_upload(session["uploadUrl"], data)


def search_query(
    query: str,
    entity_types: list[str],
    account_id: str | None = None,
    limit: int = 50,
    fields: list[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Use the modern /search/query API endpoint"""
    payload = {
        "requests": [
            {
                "entityTypes": entity_types,
                "query": {"queryString": query},
                "size": min(limit, 25),
                "from": 0,
            }
        ]
    }

    if fields:
        payload["requests"][0]["fields"] = fields

    items_returned = 0

    while True:
        result = request("POST", "/search/query", account_id, json=payload)

        if not result or "value" not in result:
            break

        for response in result["value"]:
            if "hitsContainers" in response:
                for container in response["hitsContainers"]:
                    if "hits" in container:
                        for hit in container["hits"]:
                            if limit and items_returned >= limit:
                                return
                            yield hit["resource"]
                            items_returned += 1

        if "@odata.nextLink" in result:
            break

        has_more = False
        for response in result.get("value", []):
            for container in response.get("hitsContainers", []):
                if container.get("moreResultsAvailable"):
                    has_more = True
                    break

        if not has_more:
            break

        payload["requests"][0]["from"] += payload["requests"][0]["size"]
