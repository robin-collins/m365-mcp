from typing import NamedTuple, Any
from .graph import _request


class BatchRequest(NamedTuple):
    id: str
    method: str
    url: str
    body: dict[str, Any] | None = None
    headers: dict[str, str] | None = None


class BatchResponse(NamedTuple):
    id: str
    status: int
    body: dict[str, Any] | None
    headers: dict[str, str] | None


def _create_batch_payload(requests: list[BatchRequest]) -> dict[str, Any]:
    return {
        "requests": [
            {
                "id": req.id,
                "method": req.method,
                "url": req.url,
                "body": req.body,
                "headers": req.headers,
            }
            for req in requests
        ]
    }


def _parse_batch_response(response: dict[str, Any]) -> list[BatchResponse]:
    return [
        BatchResponse(
            id=resp["id"],
            status=resp["status"],
            body=resp.get("body"),
            headers=resp.get("headers"),
        )
        for resp in response.get("responses", [])
    ]


def execute_batch(
    requests: list[BatchRequest], account_id: str | None = None
) -> list[BatchResponse]:
    if not requests:
        return []

    if len(requests) > 20:
        raise ValueError("Batch requests are limited to 20 items")

    payload = _create_batch_payload(requests)
    response = _request("POST", "/$batch", account_id=account_id, data=payload)

    if not response:
        return []

    return _parse_batch_response(response)
