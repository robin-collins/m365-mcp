"""Tests for opaque pagination cursors (task U2.6)."""

from __future__ import annotations

import base64
import json

import pytest

from src.m365_mcp.cursors import (
    CURSOR_TTL_SECONDS,
    CursorCodec,
    PagePosition,
    request_hash,
)
from src.m365_mcp.validators import ValidationError

MISMATCH = (
    "Invalid cursor: it does not match this request. "
    "Expected: repeat the call without cursor"
)
EXPIRED = (
    "Invalid cursor: it is more than 24 hours old. "
    "Expected: repeat the call without cursor"
)
NEXT_LINK = (
    "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
    "?$top=20&$skiptoken=abc"
)
REQUEST = {"resource": "email", "folder_id": "inbox", "limit": 20}


class FakeClock:
    """Controllable wall clock."""

    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def codec(clock: FakeClock) -> CursorCodec:
    return CursorCodec(key=b"k" * 32, clock=clock)


def _raw(token: str) -> bytes:
    return base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))


def test_round_trip_next_link(codec: CursorCodec) -> None:
    token = codec.encode("acc-1", "email", REQUEST, next_link=NEXT_LINK)

    decoded = codec.decode(token, "acc-1", "email", REQUEST)

    assert decoded.next_link == NEXT_LINK
    assert decoded.offset is None
    assert decoded.sub_cursors is None


def test_round_trip_offset(codec: CursorCodec) -> None:
    token = codec.encode("acc-1", "drive_item", {"max_depth": 3}, offset=40)

    decoded = codec.decode(token, "acc-1", "drive_item", {"max_depth": 3})

    assert decoded.offset == 40
    assert decoded.next_link is None


def test_round_trip_sub_cursors(codec: CursorCodec) -> None:
    request = {"query": "tax", "resources": ["email", "drive_item"]}
    subs = {
        "email": PagePosition(next_link=NEXT_LINK),
        "drive_item": PagePosition(offset=20),
    }

    token = codec.encode("acc-1", "search", request, sub_cursors=subs)
    decoded = codec.decode(token, "acc-1", "search", request)

    assert decoded.sub_cursors == subs
    assert decoded.next_link is None and decoded.offset is None


def test_token_is_base64url_and_hides_account_id(codec: CursorCodec) -> None:
    token = codec.encode("someone@example.com", "email", REQUEST, next_link=NEXT_LINK)

    assert set(token) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    assert b"someone@example.com" not in _raw(token)


def test_cursor_and_account_id_do_not_change_request_hash() -> None:
    base = request_hash(REQUEST)

    assert request_hash({**REQUEST, "cursor": "abc"}) == base
    assert request_hash({**REQUEST, "account_id": "x"}) == base
    assert request_hash({**REQUEST, "unread": None}) == base
    assert request_hash({**REQUEST, "limit": 50}) != base


def test_tampered_token_is_rejected(codec: CursorCodec) -> None:
    token = codec.encode("acc-1", "email", REQUEST, offset=20)
    raw = bytearray(_raw(token))
    raw[-3] ^= 0x01
    forged = base64.urlsafe_b64encode(bytes(raw)).decode().rstrip("=")

    with pytest.raises(ValidationError) as exc:
        codec.decode(forged, "acc-1", "email", REQUEST)
    assert str(exc.value) == MISMATCH


def test_token_from_other_key_is_rejected(clock: FakeClock) -> None:
    other = CursorCodec(key=b"z" * 32, clock=clock)
    token = other.encode("acc-1", "email", REQUEST, offset=20)

    with pytest.raises(ValidationError, match="does not match"):
        CursorCodec(key=b"k" * 32, clock=clock).decode(token, "acc-1", "email", REQUEST)


@pytest.mark.parametrize("token", ["not base64 !!", "abc", "", "AAAA"])
def test_malformed_token_is_rejected(codec: CursorCodec, token: str) -> None:
    with pytest.raises(ValidationError) as exc:
        codec.decode(token, "acc-1", "email", REQUEST)
    assert str(exc.value) == MISMATCH


def test_wrong_request_is_rejected(codec: CursorCodec) -> None:
    token = codec.encode("acc-1", "email", REQUEST, next_link=NEXT_LINK)

    with pytest.raises(ValidationError) as exc:
        codec.decode(token, "acc-1", "email", {**REQUEST, "limit": 5})
    assert str(exc.value) == MISMATCH


def test_wrong_resource_is_rejected(codec: CursorCodec) -> None:
    token = codec.encode("acc-1", "email", REQUEST, next_link=NEXT_LINK)

    with pytest.raises(ValidationError, match="does not match"):
        codec.decode(token, "acc-1", "event", REQUEST)


def test_wrong_account_is_rejected(codec: CursorCodec) -> None:
    token = codec.encode("acc-1", "email", REQUEST, next_link=NEXT_LINK)

    with pytest.raises(ValidationError, match="does not match"):
        codec.decode(token, "acc-2", "email", REQUEST)


def test_cursor_expires_after_24_hours(codec: CursorCodec, clock: FakeClock) -> None:
    token = codec.encode("acc-1", "email", REQUEST, next_link=NEXT_LINK)

    clock.now += CURSOR_TTL_SECONDS
    assert codec.decode(token, "acc-1", "email", REQUEST).next_link

    clock.now += 1
    with pytest.raises(ValidationError) as exc:
        codec.decode(token, "acc-1", "email", REQUEST)
    assert str(exc.value) == EXPIRED


@pytest.mark.parametrize(
    "link",
    [
        "https://evil.example.com/v1.0/me/messages?$skiptoken=1",
        "http://graph.microsoft.com/v1.0/me/messages?$skiptoken=1",
        "https://graph.microsoft.com.evil.com/v1.0/me/messages",
    ],
)
def test_next_link_outside_graph_is_rejected(codec: CursorCodec, link: str) -> None:
    token = codec.encode("acc-1", "email", REQUEST, next_link=link)

    with pytest.raises(ValidationError) as exc:
        codec.decode(token, "acc-1", "email", REQUEST)
    message = str(exc.value)
    assert message.startswith("Invalid cursor:")
    assert "repeat the call without cursor" in message
    assert "evil" not in message


def test_sub_cursor_next_link_host_is_checked(codec: CursorCodec) -> None:
    subs = {"email": PagePosition(next_link="https://evil.example.com/x")}
    token = codec.encode("acc-1", "search", {"q": 1}, sub_cursors=subs)

    with pytest.raises(ValidationError, match="Invalid cursor"):
        codec.decode(token, "acc-1", "search", {"q": 1})


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"next_link": NEXT_LINK, "offset": 1},
        {"offset": -1},
        {"sub_cursors": {"email": PagePosition()}},
    ],
)
def test_encode_requires_exactly_one_position(codec: CursorCodec, kwargs: dict) -> None:
    with pytest.raises(ValueError):
        codec.encode("acc-1", "email", REQUEST, **kwargs)


def test_key_from_environment_survives_restart(
    monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    monkeypatch.setenv("M365_MCP_CURSOR_KEY", "shared-secret")
    token = CursorCodec(clock=clock).encode("a", "email", REQUEST, offset=1)

    assert CursorCodec(clock=clock).decode(token, "a", "email", REQUEST).offset == 1


def test_random_key_without_environment(
    monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    monkeypatch.delenv("M365_MCP_CURSOR_KEY", raising=False)
    token = CursorCodec(clock=clock).encode("a", "email", REQUEST, offset=1)

    with pytest.raises(ValidationError):
        CursorCodec(clock=clock).decode(token, "a", "email", REQUEST)


def test_payload_fields(codec: CursorCodec, clock: FakeClock) -> None:
    token = codec.encode("acc-1", "email", REQUEST, next_link=NEXT_LINK)
    payload = json.loads(_raw(token)[16:])

    assert payload["v"] == 1
    assert payload["r"] == "email"
    assert payload["t"] == int(clock.now)
    assert payload["n"] == NEXT_LINK
    assert payload["q"] == request_hash(REQUEST)
    assert "acc-1" not in json.dumps(payload)
