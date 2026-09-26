"""Tests for the unified ``m365_search`` tool (task U3.3)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from m365_mcp.tool_specs import load_tool_spec
from tests.unified_harness import UnifiedHarness

TOOL = "m365_search"


def _ids(result: dict[str, Any]) -> list[str]:
    return [entry["item"]["id"] for entry in result["items"]]


def _seed_message(
    harness: UnifiedHarness,
    msg_id: str,
    subject: str,
    days: int,
    folder: str = "inbox",
) -> None:
    fake = harness.fake
    fake.messages[msg_id] = {
        "id": msg_id,
        "conversationId": f"conv-{msg_id}",
        "subject": subject,
        "body": {"contentType": "text", "content": subject},
        "bodyPreview": subject,
        "from": {"emailAddress": {"name": "Sender", "address": "s@example.com"}},
        "toRecipients": [],
        "ccRecipients": [],
        "receivedDateTime": fake.at(days),
        "isRead": True,
        "hasAttachments": False,
        "importance": "normal",
        "flag": {"flagStatus": "notFlagged"},
        "categories": [],
        "parentFolderId": folder,
    }


def _seed_drive_file(
    harness: UnifiedHarness,
    item_id: str,
    name: str,
    parent: str,
    modified: str,
    size: int = 10,
    mime: str = "text/plain",
) -> None:
    harness.fake.drive[item_id] = {
        "id": item_id,
        "name": name,
        "size": size,
        "createdDateTime": modified,
        "lastModifiedDateTime": modified,
        "parentReference": {"id": parent},
        "webUrl": f"https://onedrive.live.com/?id={item_id}",
        "file": {"mimeType": mime},
    }


# ----------------------------------------------------------------------
# email
# ----------------------------------------------------------------------


def test_email_uses_server_side_search_over_whole_mailbox(
    harness: UnifiedHarness,
) -> None:
    result = harness.ok(TOOL, {"query": "telstra migration", "resources": ["email"]})

    calls = harness.graph_calls("GET", "/me/messages")
    assert len(calls) == 1
    assert calls[0].params["$search"] == '"telstra migration"'
    assert "$filter" not in calls[0].params
    assert set(_ids(result)) == {"msg-001", "msg-002"}
    assert all(entry["resource"] == "email" for entry in result["items"])
    assert result["query"] == "telstra migration"
    assert result["has_more"] is False
    assert result["next_cursor"] is None


def test_email_finds_old_message_beyond_the_newest_50(
    harness: UnifiedHarness,
) -> None:
    for n in range(60):
        _seed_message(harness, f"msg-news-{n:02d}", f"Newsletter {n}", -n % 7)
    _seed_message(harness, "msg-ancient", "The zebracorn report", -800, "archive")
    newest = sorted(
        harness.fake.messages.values(),
        key=lambda m: m["receivedDateTime"],
        reverse=True,
    )[:50]
    assert "msg-ancient" not in {m["id"] for m in newest}

    result = harness.ok(TOOL, {"query": "zebracorn", "resources": ["email"]})

    assert _ids(result) == ["msg-ancient"]


def test_email_folder_alias_restricts_the_search(harness: UnifiedHarness) -> None:
    result = harness.ok(
        TOOL,
        {"query": "tax return", "resources": ["email"], "email_folder_id": "archive"},
    )

    calls = harness.graph_calls("GET", "/me/mailFolders/archive/messages")
    assert len(calls) == 1
    assert calls[0].params["$search"] == '"tax return"'
    assert not harness.graph_calls("GET", "/me/messages")
    assert _ids(result) == ["msg-011"]


def test_email_pages_through_graph_next_links(harness: UnifiedHarness) -> None:
    for n in range(60):
        _seed_message(harness, f"msg-bulletin-{n:02d}", f"Bulletin {n}", -1 - n)
    args = {"query": "bulletin", "resources": ["email"], "limit": 50}

    first = harness.ok(TOOL, args)
    assert len(first["items"]) == 50
    assert first["has_more"] is True
    assert first["next_cursor"]

    harness.clear_calls()
    second = harness.ok(TOOL, {**args, "cursor": first["next_cursor"]})
    assert len(second["items"]) == 10
    assert second["has_more"] is False
    assert second["next_cursor"] is None
    assert harness.graph_calls("GET", "/me/messages")[0].params["$skip"] == "50"
    assert set(_ids(first)) | set(_ids(second)) == {
        f"msg-bulletin-{n:02d}" for n in range(60)
    }


def test_email_partial_pages_resume_without_gaps_or_duplicates(
    harness: UnifiedHarness,
) -> None:
    for n in range(7):
        _seed_message(harness, f"msg-quokka-{n}", f"Quokka sighting {n}", -1 - n)
    args: dict[str, Any] = {"query": "quokka", "resources": ["email"], "limit": 3}

    seen: list[str] = []
    while True:
        page = harness.ok(TOOL, args)
        seen += _ids(page)
        if not page["has_more"]:
            break
        args = {**args, "cursor": page["next_cursor"]}

    assert seen == [f"msg-quokka-{n}" for n in range(7)]


# ----------------------------------------------------------------------
# events
# ----------------------------------------------------------------------


def test_event_search_uses_calendar_view_and_matches_fields(
    harness: UnifiedHarness,
) -> None:
    by_subject = harness.ok(TOOL, {"query": "DENTIST", "resources": ["event"]})
    assert _ids(by_subject) == ["evt-dentist"]

    calls = harness.graph_calls("GET", "/me/calendarView")
    assert calls
    start = datetime.fromisoformat(calls[0].params["startDateTime"])
    end = datetime.fromisoformat(calls[0].params["endDateTime"])
    assert 89 <= (datetime.now(start.tzinfo) - start).days <= 91
    assert 364 <= (end - datetime.now(end.tzinfo)).days <= 366

    by_location = harness.ok(TOOL, {"query": "cafe roma", "resources": ["event"]})
    assert _ids(by_location) == ["evt-planning"]
    by_preview = harness.ok(TOOL, {"query": "agenda", "resources": ["event"]})
    assert _ids(by_preview) == ["evt-sync"]
    by_organiser = harness.ok(TOOL, {"query": "priya", "resources": ["event"]})
    assert _ids(by_organiser) == ["evt-sync"]
    assert by_organiser["items"][0]["resource"] == "event"


def test_event_search_uses_the_given_window(harness: UnifiedHarness) -> None:
    result = harness.ok(
        TOOL,
        {
            "query": "car service",
            "resources": ["event"],
            "event_start": "2026-09-01T00:00:00+00:00",
            "event_end": "2026-10-01T00:00:00+00:00",
        },
    )

    params = harness.graph_calls("GET", "/me/calendarView")[0].params
    assert params["startDateTime"] == "2026-09-01T00:00:00+00:00"
    assert params["endDateTime"] == "2026-10-01T00:00:00+00:00"
    assert _ids(result) == ["evt-car"]


# ----------------------------------------------------------------------
# contacts and drive
# ----------------------------------------------------------------------


def test_contact_search_filters_by_name_prefix(harness: UnifiedHarness) -> None:
    result = harness.ok(TOOL, {"query": "Jane", "resources": ["contact"]})

    params = harness.graph_calls("GET", "/me/contacts")[0].params
    assert params["$filter"] == (
        "startswith(displayName,'Jane') or startswith(givenName,'Jane') "
        "or startswith(surname,'Jane')"
    )
    assert _ids(result) == ["contact-jane"]
    assert result["items"][0]["item"]["emails"] == ["jane.smith@example.com"]


def test_contact_search_matches_email_address(harness: UnifiedHarness) -> None:
    result = harness.ok(
        TOOL, {"query": "sam.lee@example.com", "resources": ["contact"]}
    )

    params = harness.graph_calls("GET", "/me/contacts")[0].params
    assert params["$filter"].endswith(
        " or emailAddresses/any(a:a/address eq 'sam.lee@example.com')"
    )
    assert _ids(result) == ["contact-sam"]


def test_drive_search_uses_drive_root_search(harness: UnifiedHarness) -> None:
    result = harness.ok(TOOL, {"query": "tax", "resources": ["drive_item"]})

    assert harness.graph_calls("GET", "/me/drive/root/search(q='tax')")
    assert set(_ids(result)) == {"item-tax", "item-taxreturn"}
    assert all(entry["resource"] == "drive_item" for entry in result["items"])


def test_drive_search_follows_next_links(harness: UnifiedHarness) -> None:
    for n in range(55):
        _seed_drive_file(
            harness,
            f"item-wombat-{n:02d}",
            f"wombat-{n:02d}.txt",
            "root",
            harness.fake.at(-1 - n),
        )
    args: dict[str, Any] = {"query": "wombat", "resources": ["drive_item"]}

    first = harness.ok(TOOL, {**args, "limit": 50})
    second = harness.ok(TOOL, {**args, "limit": 50, "cursor": first["next_cursor"]})

    assert len(first["items"]) == 50 and len(second["items"]) == 5
    assert second["has_more"] is False


# ----------------------------------------------------------------------
# multi-resource
# ----------------------------------------------------------------------


def test_default_resources_search_all_four(harness: UnifiedHarness) -> None:
    harness.ok(TOOL, {"query": "priya"})

    assert harness.graph_calls("GET", "/me/messages")
    assert harness.graph_calls("GET", "/me/calendarView")
    assert harness.graph_calls("GET", "/me/contacts")
    assert harness.graph_calls("GET", "/me/drive/root/search(q='priya')")


def test_multi_resource_results_interleave_by_recency(
    harness: UnifiedHarness,
) -> None:
    result = harness.ok(
        TOOL, {"query": "tax", "resources": ["email", "drive_item"], "limit": 10}
    )

    # item-tax (-30 days); msg-011 and item-taxreturn tie at -200 days,
    # so the resource order (email first) breaks the tie.
    assert _ids(result) == ["item-tax", "msg-011", "item-taxreturn"]
    assert result["summary"] == "Returned 3 matches (email: 1, drive_item: 2)."
    assert result["has_more"] is False


def test_multi_resource_limit_is_total_and_cursor_resumes_each_resource(
    harness: UnifiedHarness,
) -> None:
    full = harness.ok(TOOL, {"query": "priya", "limit": 50})
    assert len(full["items"]) >= 3
    resources = {entry["resource"] for entry in full["items"]}
    assert {"email", "event", "contact"} <= resources

    args: dict[str, Any] = {"query": "priya", "limit": 2}
    paged: list[tuple[str, str]] = []
    while True:
        page = harness.ok(TOOL, args)
        assert len(page["items"]) <= 2
        paged += [(e["resource"], e["item"]["id"]) for e in page["items"]]
        if not page["has_more"]:
            assert page["next_cursor"] is None
            break
        args = {**args, "cursor": page["next_cursor"]}

    assert paged == [(e["resource"], e["item"]["id"]) for e in full["items"]]


def test_cursor_from_another_request_is_rejected(harness: UnifiedHarness) -> None:
    for n in range(3):
        _seed_message(harness, f"msg-emu-{n}", f"Emu {n}", -1 - n)
    first = harness.ok(TOOL, {"query": "emu", "resources": ["email"], "limit": 1})

    text = harness.error(
        TOOL,
        {
            "query": "other",
            "resources": ["email"],
            "limit": 1,
            "cursor": first["next_cursor"],
        },
    )

    assert text.startswith("Invalid cursor: it does not match this request.")


# ----------------------------------------------------------------------
# query escaping (injection)
# ----------------------------------------------------------------------


def test_search_quoting_escapes_double_quotes(harness: UnifiedHarness) -> None:
    harness.ok(TOOL, {"query": 'report" OR from:evil\\', "resources": ["email"]})

    params = harness.graph_calls("GET", "/me/messages")[0].params
    assert params["$search"] == '"report\\" OR from:evil\\\\"'


def test_odata_literals_double_single_quotes(harness: UnifiedHarness) -> None:
    harness.fake.contacts["contact-obrien"] = {
        "id": "contact-obrien",
        "displayName": "O'Brien Pat",
        "givenName": "Pat",
        "surname": "O'Brien",
        "emailAddresses": [],
        "parentFolderId": "contacts-root",
    }
    _seed_drive_file(
        harness, "item-obrien", "O'Brien notes.txt", "root", harness.fake.at(-1)
    )

    result = harness.ok(
        TOOL, {"query": "O'Brien", "resources": ["contact", "drive_item"]}
    )

    contact_filter = harness.graph_calls("GET", "/me/contacts")[0].params["$filter"]
    assert "startswith(displayName,'O''Brien')" in contact_filter
    assert "startswith(surname,'O''Brien')" in contact_filter
    assert harness.graph_calls("GET", "/me/drive/root/search(q='O''Brien')")
    assert set(_ids(result)) == {"contact-obrien", "item-obrien"}


def test_injection_attempt_stays_inside_the_literal(harness: UnifiedHarness) -> None:
    query = "x') or true or startswith(displayName,'"
    result = harness.ok(TOOL, {"query": query, "resources": ["contact"]})

    contact_filter = harness.graph_calls("GET", "/me/contacts")[0].params["$filter"]
    assert "startswith(displayName,'x'') or true or startswith(displayName,''')" in (
        contact_filter
    )
    assert result["items"] == []


def test_drive_query_with_url_characters_is_encoded(harness: UnifiedHarness) -> None:
    harness.ok(TOOL, {"query": "a/b?c#d&e", "resources": ["drive_item"]})

    assert harness.graph_calls("GET", "/me/drive/root/search(q='a/b?c#d&e')")
    assert not harness.fake.unhandled


# ----------------------------------------------------------------------
# validation rules
# ----------------------------------------------------------------------


def test_rule_email_folder_requires_email(harness: UnifiedHarness) -> None:
    text = harness.error(
        TOOL,
        {"query": "x", "resources": ["drive_item"], "email_folder_id": "inbox"},
    )
    assert text == "Invalid email_folder_id: only valid when resources includes 'email'"


def test_rule_event_window_requires_event(harness: UnifiedHarness) -> None:
    for param in ("event_start", "event_end"):
        text = harness.error(
            TOOL,
            {"query": "x", "resources": ["email"], param: "2026-09-01T00:00:00Z"},
        )
        assert text == f"Invalid {param}: only valid when resources includes 'event'"


def test_rule_event_end_after_start_within_731_days(
    harness: UnifiedHarness,
) -> None:
    expected = "Invalid event_end: must be after event_start and within 731 days"
    reversed_window = {
        "query": "x",
        "resources": ["event"],
        "event_start": "2026-09-02T00:00:00Z",
        "event_end": "2026-09-01T00:00:00Z",
    }
    too_long = {
        **reversed_window,
        "event_start": "2024-01-01T00:00:00Z",
        "event_end": "2026-01-02T00:00:00Z",
    }
    assert harness.error(TOOL, reversed_window) == expected
    assert harness.error(TOOL, too_long) == expected
    assert not harness.graph_calls()

    at_limit = {**too_long, "event_end": "2026-01-01T00:00:00Z"}
    harness.ok(TOOL, at_limit)


def test_spec_rules_are_all_covered() -> None:
    rules = load_tool_spec(TOOL)["validation_rules"]
    assert [r["error"] for r in rules] == [
        "Invalid email_folder_id: only valid when resources includes 'email'",
        "Invalid event_end: must be after event_start and within 731 days",
        "(no error; injection-safe by construction)",
    ]


# ----------------------------------------------------------------------
# spec example
# ----------------------------------------------------------------------


def test_spec_example_search_mail_and_files(harness: UnifiedHarness) -> None:
    example = load_tool_spec(TOOL)["examples"][0]
    expected = example["output"]["items"][0]["item"]
    harness.fake.drive["01ABCDEF0001"] = {
        "id": "01ABCDEF0001",
        "name": "Tax",
        "size": 0,
        "createdDateTime": harness.fake.at(-400),
        "lastModifiedDateTime": harness.fake.at(-400),
        "parentReference": {"id": "item-documents"},
        "webUrl": "https://onedrive.live.com/?id=01ABCDEF0001",
        "folder": {"childCount": 0},
    }
    _seed_drive_file(
        harness,
        "01ABCDEF2345",
        "Tax return 2026.pdf",
        "01ABCDEF0001",
        "2026-08-30T00:30:00Z",
        size=482113,
        mime="application/pdf",
    )

    result = harness.ok(TOOL, example["input"])

    assert result["query"] == example["output"]["query"]
    assert result["has_more"] is True and result["next_cursor"]
    assert result["summary"] == example["output"]["summary"]
    assert [e["resource"] for e in result["items"]] == ["drive_item"]
    item = result["items"][0]["item"]
    for key in ("modified_at", "created_at"):
        assert datetime.fromisoformat(item[key]) == datetime.fromisoformat(
            expected[key]
        )
    assert {k: v for k, v in item.items() if not k.endswith("_at")} == {
        k: v for k, v in expected.items() if not k.endswith("_at")
    }
