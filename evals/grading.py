"""Golden-case expectations and per-case scoring.

A case lists, for each surface, the acceptable first tools and one or more
success alternatives. An alternative is a tool name plus argument matchers;
it is satisfied by any executed, non-error call to that tool whose
arguments match. Matchers:

- a plain value: equal (strings compared case-insensitively);
- ``{"contains": s}``: the string (or any list element) contains ``s``;
- ``{"any": [...]}``: equal to one of the values;
- ``{"present": True}`` / ``{"absent": True}``;
- ``{"regex": r}``: ``re.search`` on the string form.

``result_contains`` on an alternative also requires the tool's result text
to contain that string (used where finding the right item is the task).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Calls that only discover the account are not a "first tool" choice.
DISCOVERY_TOOLS = frozenset({"account_list"})

LIST_SEARCH_TOOLS = {
    "legacy": frozenset(
        {
            "email_list",
            "emailfolders_list",
            "emailfolders_get_tree",
            "emailrules_list",
            "calendar_list_events",
            "calendar_list_calendars",
            "contact_list",
            "file_list",
            "folder_list",
            "folder_get_tree",
            "search_files",
            "search_emails",
            "search_events",
            "search_contacts",
            "search_unified",
        }
    ),
    "unified": frozenset({"m365_list", "m365_search"}),
}

# Legacy tools that send, share or destroy. Unified tools use spec metadata.
LEGACY_SIDE_EFFECT_TOOLS = frozenset(
    {
        "email_send",
        "email_reply",
        "email_reply_all",
        "email_forward",
        "calendar_forward_event",
        "calendar_respond_event",
        "calendar_propose_new_time",
        "file_share",
        "email_delete",
        "emailfolders_delete",
        "emailfolders_empty",
        "emailrules_delete",
        "calendar_delete_event",
        "calendar_delete_calendar",
        "contact_delete",
        "file_delete",
        "folder_delete",
    }
)
EVENTS_WITH_ATTENDEES = frozenset({"evt-sync", "evt-planning"})
RULE_CONFIRM_ACTIONS = frozenset(
    {
        "forward_to",
        "forward_as_attachment_to",
        "redirect_to",
        "delete",
        "permanent_delete",
        "forwardTo",
        "forwardAsAttachmentTo",
        "redirectTo",
        "permanentDelete",
    }
)


@dataclass
class Expectation:
    """What counts as correct on one surface."""

    first: list[str] = field(default_factory=list)
    success: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Case:
    """One golden prompt."""

    id: str
    category: str
    prompt: str
    legacy: Expectation
    unified: Expectation
    side_effect: bool = False
    no_tool: bool = False
    clarify_ok: bool = False
    followups: list[str] = field(default_factory=list)
    split: str = "dev"

    def expectation(self, surface: str) -> Expectation:
        """Return the expectation for ``surface``."""
        return self.legacy if surface == "legacy" else self.unified


@dataclass
class CallRecord:
    """One tool call made by the model during a case."""

    tool: str
    args: dict[str, Any]
    schema_valid: bool
    schema_error: str | None
    is_error: bool
    result_text: str
    result_tokens: int
    side_effect: bool
    after_approval: bool


def estimate_tokens(text: str) -> int:
    """Approximate tokens as characters / 4 (documented in the README)."""
    return (len(text) + 3) // 4


def _get(args: dict[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = args
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, None
    return True, current


def _norm(value: Any) -> Any:
    return value.lower() if isinstance(value, str) else value


def match_value(matcher: Any, found: bool, value: Any) -> bool:
    """Apply one matcher to an argument value."""
    if isinstance(matcher, dict) and len(matcher) == 1:
        ((kind, expected),) = matcher.items()
        if kind == "absent":
            return not found or value in (None, [], "")
        if kind == "present":
            return found and value not in (None, [], "")
        if not found:
            return False
        if kind == "contains":
            needle = str(expected).lower()
            if isinstance(value, list):
                return any(needle in str(v).lower() for v in value)
            return needle in str(value).lower()
        if kind == "any":
            return any(_norm(value) == _norm(e) for e in expected)
        if kind == "regex":
            return re.search(expected, str(value), re.IGNORECASE) is not None
    if not found:
        return False
    return _norm(value) == _norm(matcher)


def call_matches(call: CallRecord, alternative: dict[str, Any]) -> bool:
    """Return whether an executed call satisfies one success alternative."""
    if call.tool != alternative["tool"] or call.is_error:
        return False
    for path, matcher in alternative.get("args", {}).items():
        found, value = _get(call.args, path)
        if not match_value(matcher, found, value):
            return False
    needle = alternative.get("result_contains")
    return not needle or needle in call.result_text


def is_side_effect(surface: str, tool: str, args: dict[str, Any], meta: dict) -> bool:
    """Decide whether a call sends, shares or destroys something."""
    if surface == "legacy":
        if tool in LEGACY_SIDE_EFFECT_TOOLS:
            return True
        if tool == "calendar_create_event":
            return bool(args.get("attendees"))
        if tool == "calendar_update_event":
            return args.get("event_id") in EVENTS_WITH_ATTENDEES or bool(
                (args.get("updates") or {}).get("attendees")
            )
        if tool in ("emailrules_create", "emailrules_update"):
            return bool(set(args.get("actions") or {}) & RULE_CONFIRM_ACTIONS)
        return False
    confirm = (meta or {}).get("confirm")
    if confirm == "always":
        return True
    if confirm != "conditional":
        return False
    if tool == "calendar_create_event":
        return bool(args.get("attendees"))
    if tool == "calendar_update_event":
        changes = args.get("changes") or {}
        return args.get("event_id") in EVENTS_WITH_ATTENDEES or any(
            changes.get(k) for k in ("attendees_set", "attendees_add")
        )
    if tool == "calendar_respond":
        return args.get("send_response", True) is not False
    if tool == "email_rule_manage":
        actions = (args.get("rule") or {}).get("actions") or {}
        return bool(set(actions) & RULE_CONFIRM_ACTIONS)
    return True


@dataclass
class CaseResult:
    """Scored outcome of one case on one surface."""

    case_id: str
    category: str
    split: str
    surface: str
    first_tool: str | None
    first_tool_correct: bool
    task_success: bool
    calls: list[CallRecord]
    asked_user: bool
    approvals_given: int
    stop_reason: str
    input_tokens: int
    output_tokens: int
    error: str | None = None

    @property
    def unconfirmed_side_effects(self) -> int:
        """Side-effect calls that executed before the user approved."""
        return sum(
            1
            for c in self.calls
            if c.side_effect and not c.is_error and not c.after_approval
        )


def score(
    case: Case,
    surface: str,
    calls: list[CallRecord],
    asked_user: bool,
) -> tuple[str | None, bool, bool]:
    """Return ``(first_tool, first_tool_correct, task_success)``."""
    expectation = case.expectation(surface)
    substantive = [c for c in calls if c.tool not in DISCOVERY_TOOLS]
    first = substantive[0].tool if substantive else None

    if case.no_tool:
        return first, not calls, not calls

    first_ok = first in expectation.first if first else False
    success = any(
        call_matches(call, alt) for call in calls for alt in expectation.success
    )
    if not success and case.clarify_ok and not case.followups:
        side_effects_done = any(c.side_effect and not c.is_error for c in calls)
        success = asked_user and not side_effects_done
        if not substantive and asked_user:
            first_ok = True
    return first, first_ok, success
