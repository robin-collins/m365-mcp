"""Offline tests for the evaluation harness (no model API calls)."""

import asyncio
from datetime import date

import httpx
import pytest

from evals.cases import CASES, SMOKE_IDS, select
from evals.fake_graph import FakeGraph
from evals.grading import CallRecord, call_matches, match_value
from evals.runner import (
    ScriptedModel,
    render_markdown,
    run,
    summarise,
    text_turn,
    tool_turn,
)

ANCHOR = date(2026, 9, 28)


def _client(graph: FakeGraph) -> httpx.Client:
    return httpx.Client(
        transport=graph.transport(), base_url="https://graph.microsoft.com/v1.0"
    )


def test_case_set_shape():
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))
    assert 80 <= len(CASES) <= 120
    heldout = [c for c in CASES if c.split == "heldout"]
    assert abs(len(heldout) / len(CASES) - 0.25) < 0.02
    assert {c.category for c in CASES} == {
        "direct",
        "indirect",
        "ambiguous",
        "competing",
        "no_tool",
    }
    assert len(select("smoke")) == len(SMOKE_IDS) == 10


def test_fake_graph_filters_searches_and_pages():
    graph = FakeGraph.seeded(ANCHOR)
    with _client(graph) as client:
        unread = client.get(
            "/me/mailFolders/inbox/messages",
            params={"$filter": "isRead eq false", "$top": "50"},
        ).json()["value"]
        assert {m["id"] for m in unread} == {"msg-001", "msg-003", "msg-005", "msg-007"}

        found = client.get(
            "/me/messages", params={"$search": '"telstra timeline"'}
        ).json()
        assert [m["id"] for m in found["value"]] == ["msg-002"]

        page = client.get(
            "/me/mailFolders/inbox/messages", params={"$top": "10"}
        ).json()
        assert len(page["value"]) == 10 and "@odata.nextLink" in page

        contacts = client.get(
            "/me/contacts", params={"$filter": "startswith(surname,'Smith')"}
        ).json()["value"]
        assert {c["id"] for c in contacts} == {"contact-jane", "contact-anna"}

        docs = client.get("/me/drive/root:/Documents:/children").json()["value"]
        assert {d["name"] for d in docs} >= {"budget.xlsx", "Tax"}

        assert client.post("/search/query", json={}).status_code == 400
        missing = client.get("/me/messages/nope")
        assert missing.status_code == 404 and "error" in missing.json()


def test_fake_graph_batch_applies_writes():
    graph = FakeGraph.seeded(ANCHOR)
    with _client(graph) as client:
        response = client.post(
            "/$batch",
            json={
                "requests": [
                    {
                        "id": "1",
                        "method": "PATCH",
                        "url": "/me/messages/msg-001",
                        "body": {"isRead": True},
                    },
                    {"id": "2", "method": "DELETE", "url": "/me/messages/nope"},
                ]
            },
        ).json()
    statuses = {r["id"]: r["status"] for r in response["responses"]}
    assert statuses == {"1": 200, "2": 404}
    assert graph.messages["msg-001"]["isRead"] is True


def test_matchers():
    assert match_value({"contains": "jane"}, True, ["Jane.Smith@example.com"])
    assert match_value({"any": ["inbox", "Inbox"]}, True, "INBOX")
    assert match_value({"absent": True}, False, None)
    assert not match_value(True, False, None)
    call = CallRecord(
        "m365_list",
        {"resource": "email", "email_filter": {"unread": True}},
        True,
        None,
        False,
        "x",
        1,
        False,
        False,
    )
    assert call_matches(
        call, {"tool": "m365_list", "args": {"email_filter.unread": True}}
    )


def _run(cases, scripts):
    return asyncio.run(run(cases, "unified", ScriptedModel(scripts), ANCHOR, None))


def test_runner_scores_a_read_case():
    case = next(c for c in CASES if c.id == "d01")
    results = _run(
        [case],
        {
            "d01": [
                tool_turn(
                    (
                        "m365_list",
                        {
                            "resource": "email",
                            "email_filter": {"unread": True},
                            "limit": 10,
                        },
                    )
                ),
                text_turn("You have 4 unread emails."),
            ]
        },
    )
    result = results[0]
    assert result.first_tool == "m365_list"
    assert result.first_tool_correct and result.task_success
    assert [c.is_error for c in result.calls] == [False]
    assert all(c.schema_valid for c in result.calls)
    assert "Returned 4 emails from inbox" in result.calls[0].result_text


def test_runner_approval_flow_and_unconfirmed_side_effects():
    case = next(c for c in CASES if c.id == "d20")
    send = (
        "email_send",
        {
            "mode": "new",
            "to": ["sam.lee@example.com"],
            "subject": "Modem arrived",
            "body": "It came.",
            "confirm": True,
        },
    )
    asked = _run(
        [case],
        {
            "d20": [
                text_turn("Shall I send this to sam.lee@example.com?"),
                tool_turn(send),
                text_turn("Sent."),
            ]
        },
    )[0]
    assert asked.task_success and asked.approvals_given == 1
    assert asked.unconfirmed_side_effects == 0

    rushed = _run([case], {"d20": [tool_turn(send), text_turn("Sent.")]})[0]
    assert rushed.task_success and rushed.unconfirmed_side_effects == 1


def test_runner_no_tool_and_schema_errors():
    n01 = next(c for c in CASES if c.id == "n01")
    d06 = next(c for c in CASES if c.id == "d06")
    results = _run(
        [n01, d06],
        {
            "n01": [text_turn("Paris.")],
            "d06": [
                tool_turn(("m365_list", {"resource": 7})),
                text_turn("Sorry."),
            ],
        },
    )
    assert results[0].task_success and results[0].first_tool_correct
    bad = results[1].calls[0]
    assert not bad.schema_valid and bad.is_error
    summary = summarise(results, "unified")
    assert summary["cases"] == 2 and summary["schema_valid_args"] == 0.0
    report = render_markdown("t", "unified", "scripted", ANCHOR, results)
    assert "| Correct first tool (%) |" in report


def test_unified_surface_loads_from_registry():
    case = next(c for c in CASES if c.id == "n01")
    scripts = {
        "n01": [
            tool_turn(("m365_list", {"resource": "email"})),
            text_turn("Paris."),
        ]
    }
    (result,) = asyncio.run(
        run([case], "unified", ScriptedModel(scripts), ANCHOR, None)
    )
    (call,) = result.calls
    assert call.tool == "m365_list" and call.schema_valid and not call.is_error
    assert "emails from inbox" in call.result_text


class _FailingModel:
    """A model client whose API always errors (for example: no credits)."""

    def create(self, system, tools, messages):
        raise RuntimeError("credit balance is too low")


def test_errored_runs_never_count_as_success() -> None:
    cases = [c for c in CASES if c.id in ("n01", "a02", "d01")]
    extra = [c for c in CASES if c.id in ("d02", "d03")]
    results = asyncio.run(run(cases + extra, "unified", _FailingModel(), ANCHOR, None))
    assert len(results) == 3, "the run stops after three consecutive errors"
    assert all(r.error for r in results)
    assert not any(r.task_success or r.first_tool_correct for r in results)
    summary = summarise(results, "unified")
    assert summary["run_errors"] == 3
    assert summary["task_success"] == 0.0 and summary["correct_first_tool"] == 0.0
    assert "INVALID RUN" in render_markdown("t", "unified", "m", ANCHOR, results)


def test_local_endpoint_model_client(monkeypatch) -> None:
    from evals.runner import AnthropicModel

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    model = AnthropicModel("local-model", base_url="http://10.10.10.10:1234")
    assert str(model.client.base_url).startswith("http://10.10.10.10:1234")
    sent: dict = {}

    class FakeMessages:
        def create(self, **kwargs):
            sent.update(kwargs)
            return "response"

    model.client.messages = FakeMessages()  # type: ignore[assignment]
    assert model.create("system", [], [{"role": "user", "content": "hi"}]) == "response"
    assert "cache_control" not in sent, "prompt caching is Anthropic-only"

    hosted = AnthropicModel("claude-sonnet-5", api_key="test-key")
    hosted.client.messages = FakeMessages()  # type: ignore[assignment]
    hosted.create("system", [], [])
    assert sent["cache_control"] == {"type": "ephemeral"}


def test_user_approves_when_the_model_asks_before_a_plain_write() -> None:
    case = next(c for c in CASES if c.id == "c07")
    assert not case.side_effect and not case.clarify_ok
    create = (
        "m365_create",
        {"resource": "email_folder", "email_folder": {"display_name": "Kids"}},
    )
    results = _run(
        [case],
        {
            "c07": [
                text_turn("I'll create the folder Kids. Shall I proceed?"),
                tool_turn(create),
                text_turn("Created."),
            ]
        },
    )
    assert results[0].task_success and results[0].approvals_given == 1


def test_no_approval_when_the_model_simply_finishes() -> None:
    case = next(c for c in CASES if c.id == "d01")
    results = _run(
        [case],
        {
            "d01": [
                tool_turn(("m365_list", {"resource": "email"})),
                text_turn("You have 4 unread emails."),
            ]
        },
    )
    assert results[0].approvals_given == 0


def test_ask_first_cases_are_not_auto_approved() -> None:
    case = next(c for c in CASES if c.id == "a02")
    results = _run([case], {"a02": [text_turn("Which email do you mean?")]})
    assert results[0].approvals_given == 0 and results[0].task_success


def test_legacy_surface_points_to_the_baseline_instructions() -> None:
    from evals.surface import open_surface

    with (
        pytest.raises(RuntimeError, match=r"v0\.2\.3-final.*evals/README\.md"),
        open_surface("legacy", ANCHOR),
    ):
        pass
