"""Deterministic in-memory Microsoft Graph for the evaluation harness.

The fake answers HTTP requests at the transport layer
(``httpx.MockTransport``), so the real server code runs unchanged on both
the legacy and the unified tool surfaces. It keeps a small personal mailbox,
calendar, address book and OneDrive, applies writes to that state, and
records every request so graders can inspect side effects.

Only the query features the server uses are emulated: ``$top``, ``$skip``,
``$select`` (ignored), ``$orderby`` on date fields, simple ``$filter``
expressions, ``$search``, ``calendarView`` windows, OData nextLinks and
``$batch``. Unknown routes return a Graph-shaped 404 and are recorded in
``unhandled`` so gaps in the fake are visible in run reports.
"""

from __future__ import annotations

import copy
import json
import operator
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlsplit
from zoneinfo import ZoneInfo

import httpx

BASE = "https://graph.microsoft.com/v1.0"
ACCOUNT_ID = "00000000-0000-0000-0000-000000000001.9188040d-6c67-4c5b-b112-36a304b66dad"
ACCOUNT_EMAIL = "alex.morgan@outlook.com"
ACCOUNT_NAME = "Alex Morgan"

_COMPARE = {"ge": operator.ge, "gt": operator.gt, "le": operator.le, "lt": operator.lt}

WELL_KNOWN_FOLDERS = {
    "inbox": "inbox",
    "sentitems": "sentitems",
    "drafts": "drafts",
    "deleteditems": "deleteditems",
    "junkemail": "junkemail",
    "archive": "archive",
    "outbox": "outbox",
    "msgfolderroot": "msgfolderroot",
}


@dataclass
class RecordedCall:
    """One HTTP request the server sent to the fake Graph."""

    method: str
    path: str
    params: dict[str, str]
    body: Any
    status: int


@dataclass
class FakeGraph:
    """In-memory Graph state plus an ``httpx`` request handler."""

    anchor: date
    messages: dict[str, dict[str, Any]] = field(default_factory=dict)
    folders: dict[str, dict[str, Any]] = field(default_factory=dict)
    rules: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: dict[str, dict[str, Any]] = field(default_factory=dict)
    calendars: dict[str, dict[str, Any]] = field(default_factory=dict)
    contacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    contact_folders: dict[str, dict[str, Any]] = field(default_factory=dict)
    drive: dict[str, dict[str, Any]] = field(default_factory=dict)
    attachments: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    mailbox_settings: dict[str, Any] = field(
        default_factory=lambda: {
            "timeZone": "UTC",
            "workingHours": {
                "daysOfWeek": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                "startTime": "09:00:00.0000000",
                "endTime": "17:00:00.0000000",
                "timeZone": {"name": "UTC"},
            },
        }
    )
    calls: list[RecordedCall] = field(default_factory=list)
    unhandled: list[str] = field(default_factory=list)
    _seq: int = 0

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    @classmethod
    def seeded(cls, anchor: date) -> FakeGraph:
        """Build the standard evaluation dataset around ``anchor`` (today)."""
        from .fixtures import seed

        graph = cls(anchor=anchor)
        seed(graph)
        return graph

    def new_id(self, prefix: str) -> str:
        """Return a deterministic unique ID."""
        self._seq += 1
        return f"{prefix}-new-{self._seq:04d}"

    def transport(self) -> httpx.MockTransport:
        """Return an ``httpx`` transport served by this fake."""
        return httpx.MockTransport(self.handle)

    # ------------------------------------------------------------------
    # HTTP entry point
    # ------------------------------------------------------------------
    def handle(self, request: httpx.Request) -> httpx.Response:
        """Serve one HTTP request."""
        url = str(request.url)
        split = urlsplit(url)
        path = unquote(split.path)
        path = path.removeprefix("/v1.0")
        params = dict(parse_qsl(split.query, keep_blank_values=True))
        body: Any = None
        if request.content:
            try:
                body = json.loads(request.content)
            except (ValueError, UnicodeDecodeError):
                body = request.content
        if split.netloc != "graph.microsoft.com":
            # Pre-authenticated upload URLs and copy monitors.
            status, payload = self._external(request.method, url, body)
        else:
            status, payload = self.dispatch(request.method, path, params, body)
        self.calls.append(RecordedCall(request.method, path, params, body, status))
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload)
        if payload is None:
            return httpx.Response(status)
        headers = {}
        if isinstance(payload, dict) and "__headers__" in payload:
            headers = payload.pop("__headers__")
        return httpx.Response(status, json=payload, headers=headers)

    def dispatch(
        self, method: str, path: str, params: dict[str, str], body: Any
    ) -> tuple[int, Any]:
        """Route a Graph request to its handler."""
        method = method.upper()
        if path == "/$batch" and method == "POST":
            return self._batch(body)
        for pattern, handler in self._routes():
            match = re.fullmatch(pattern, path)
            if match:
                return handler(method, params, body, *match.groups())
        return self._not_found(f"{method} {path}")

    def _routes(self) -> list[tuple[str, Any]]:
        return [
            (r"/me", self._me),
            (r"/me/mailboxSettings", self._mailbox_settings),
            (r"/me/mailboxSettings/(\w+)", self._mailbox_setting),
            (r"/search/query", self._search_api),
            # mail folders
            (r"/me/mailFolders", self._folders_root),
            (r"/me/mailFolders/([^/]+)", self._folder_item),
            (r"/me/mailFolders/([^/]+)/childFolders", self._folder_children),
            (r"/me/mailFolders/([^/]+)/(move|copy)", self._folder_action),
            (r"/me/mailFolders/([^/]+)/messages", self._folder_messages),
            (r"/me/mailFolders/([^/]+)/messageRules", self._rules_root),
            (r"/me/mailFolders/([^/]+)/messageRules/([^/]+)", self._rule_item),
            # messages
            (r"/me/messages", self._messages_root),
            (r"/me/sendMail", self._send_mail),
            (r"/me/messages/([^/]+)", self._message_item),
            (r"/me/messages/([^/]+)/attachments", self._attachments_root),
            (
                r"/me/messages/([^/]+)/attachments/createUploadSession",
                self._attachment_upload_session,
            ),
            (r"/me/messages/([^/]+)/attachments/([^/]+)", self._attachment_item),
            (
                r"/me/messages/([^/]+)/attachments/([^/]+)/\$value",
                self._attachment_value,
            ),
            (r"/me/messages/([^/]+)/(\w+)", self._message_action),
            # calendars and events
            (r"/me/calendars", self._calendars_root),
            (r"/me/calendar", self._default_calendar),
            (r"/me/calendars/([^/]+)", self._calendar_item),
            (r"/me/calendarView", self._calendar_view_default),
            (r"/me/calendar/calendarView", self._calendar_view_default),
            (r"/me/calendars/([^/]+)/calendarView", self._calendar_view),
            (r"/me/events", self._events_root),
            (r"/me/calendar/events", self._events_root),
            (r"/me/calendars/([^/]+)/events", self._calendar_events),
            (r"/me/events/([^/]+)", self._event_item),
            (r"/me/events/([^/]+)/(\w+)", self._event_action),
            (r"/me/calendar/getSchedule", self._get_schedule),
            (r"/me/findMeetingTimes", self._find_meeting_times),
            # contacts
            (r"/me/contacts", self._contacts_root),
            (r"/me/contacts/([^/]+)", self._contact_item),
            (r"/me/contactFolders", self._contact_folders_root),
            (r"/me/contactFolders/([^/]+)", self._contact_folder_item),
            (r"/me/contactFolders/([^/]+)/contacts", self._contact_folder_contacts),
            (r"/me/contactFolders/([^/]+)/childFolders", self._contact_folder_children),
            # drive
            (r"/me/drive", self._drive_info),
            (r"/me/drive/root", self._drive_root),
            (r"/me/drive/root/children", self._drive_root_children),
            (r"/me/drive/root/search\(q='(.*)'\)", self._drive_search),
            (r"/me/drive/root:(/[^:]*):?", self._drive_path),
            (r"/me/drive/root:(/[^:]*):/children", self._drive_path_children),
            (r"/me/drive/root:(/[^:]*):/content", self._drive_path_content),
            (
                r"/me/drive/root:(/[^:]*):/createUploadSession",
                self._drive_path_upload_session,
            ),
            (r"/me/drive/items/([^/:]+)", self._drive_item),
            (r"/me/drive/items/([^/:]+)/children", self._drive_children),
            (r"/me/drive/items/([^/:]+)/content", self._drive_content),
            (r"/me/drive/items/([^/:]+):/(.+?):/content", self._drive_child_content),
            (
                r"/me/drive/items/([^/:]+):/(.+?):/createUploadSession",
                self._drive_child_upload_session,
            ),
            (r"/me/drive/items/([^/:]+)/(\w+)", self._drive_action),
        ]

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _error(status: int, code: str, message: str) -> tuple[int, Any]:
        return status, {
            "error": {
                "code": code,
                "message": message,
                "innerError": {"request-id": "fake-request-id"},
            }
        }

    def _not_found(self, what: str) -> tuple[int, Any]:
        self.unhandled.append(what)
        return self._error(404, "ResourceNotFound", f"Resource not found: {what}")

    def _missing(self, kind: str, item_id: str) -> tuple[int, Any]:
        return self._error(
            404, "ErrorItemNotFound", f"The specified {kind} '{item_id}' was not found."
        )

    @staticmethod
    def _page(
        items: list[dict[str, Any]], params: dict[str, str], path: str
    ) -> dict[str, Any]:
        top = int(params.get("$top", "10") or 10)
        skip = int(params.get("$skip", "0") or 0)
        page = items[skip : skip + top]
        result: dict[str, Any] = {"value": copy.deepcopy(page)}
        if "$count" in params:
            result["@odata.count"] = len(items)
        if skip + top < len(items):
            next_params = dict(params)
            next_params["$skip"] = str(skip + top)
            query = "&".join(f"{k}={v}" for k, v in next_params.items())
            result["@odata.nextLink"] = f"{BASE}{path}?{query}"
        return result

    def _resolve_folder(self, folder_id: str) -> str | None:
        key = WELL_KNOWN_FOLDERS.get(folder_id.lower(), folder_id)
        if key == "msgfolderroot":
            return key
        return key if key in self.folders else None

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        value = value.strip().strip("'")
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    def at(self, days: int, hour: int = 9, minute: int = 0) -> str:
        """Return an ISO UTC timestamp relative to the anchor date."""
        moment = datetime.combine(
            self.anchor + timedelta(days=days), time(hour, minute), tzinfo=UTC
        )
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    # ------------------------------------------------------------------
    # $filter / $search emulation
    # ------------------------------------------------------------------
    def _matches_filter(self, item: dict[str, Any], expression: str) -> bool:
        """Evaluate the small OData subset the server generates."""
        if not expression:
            return True
        # Split on top-level ' or ' first, then ' and '.
        or_parts = _split_top(expression, " or ")
        if len(or_parts) > 1:
            return any(self._matches_filter(item, p) for p in or_parts)
        and_parts = _split_top(expression, " and ")
        if len(and_parts) > 1:
            return all(self._matches_filter(item, p) for p in and_parts)
        clause = expression.strip()
        while clause.startswith("(") and clause.endswith(")"):
            clause = clause[1:-1].strip()
        if clause.startswith("not "):
            return not self._matches_filter(item, clause[4:])
        func = re.fullmatch(
            r"(startswith|contains|endswith)\((\S+?),\s*'(.*)'\)", clause, re.IGNORECASE
        )
        if func:
            name, prop, value = func.groups()
            actual = str(_get_path(item, prop) or "").lower()
            value = value.replace("''", "'").lower()
            if name.lower() == "startswith":
                return actual.startswith(value)
            if name.lower() == "endswith":
                return actual.endswith(value)
            return value in actual
        anyf = re.fullmatch(r"(\S+)/any\((\w+):\s*(.+)\)", clause)
        if anyf:
            prop, var, inner = anyf.groups()
            values = _get_path(item, prop) or []
            for value in values:
                wrapped = {var: value}
                if self._matches_filter(wrapped, inner):
                    return True
            return False
        comp = re.fullmatch(r"(\S+)\s+(eq|ne|ge|gt|le|lt)\s+(.+)", clause)
        if not comp:
            return True
        prop, op, raw = comp.groups()
        actual = _get_path(item, prop)
        raw = raw.strip()
        expected: Any
        if raw in ("true", "false"):
            expected = raw == "true"
        elif raw == "null":
            expected = None
        elif raw.startswith("'"):
            expected = raw[1:-1].replace("''", "'")
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*", raw):
            expected = self._parse_dt(raw)
            actual = self._parse_dt(actual) if actual else None
        else:
            try:
                expected = float(raw)
            except ValueError:
                expected = raw
        if isinstance(expected, str) and isinstance(actual, str):
            actual, expected = actual.lower(), expected.lower()
        if op == "eq":
            return actual == expected
        if op == "ne":
            return actual != expected
        if actual is None:
            return False
        try:
            return bool(_COMPARE[op](actual, expected))
        except TypeError:
            return False

    @staticmethod
    def _search_terms(raw: str) -> list[str]:
        raw = raw.strip().strip('"').strip("'")
        raw = re.sub(r"^\w+:", "", raw)
        return [t.lower() for t in re.findall(r"[\w@.\-]+", raw) if t]

    def _message_matches_search(self, msg: dict[str, Any], raw: str) -> bool:
        terms = self._search_terms(raw)
        haystack = " ".join(
            [
                msg.get("subject", ""),
                msg.get("bodyPreview", ""),
                msg.get("body", {}).get("content", ""),
                msg.get("from", {}).get("emailAddress", {}).get("address", ""),
                msg.get("from", {}).get("emailAddress", {}).get("name", ""),
            ]
        ).lower()
        return all(term in haystack for term in terms)

    def _query(
        self,
        items: list[dict[str, Any]],
        params: dict[str, str],
        default_order: str | None = None,
        search_fn: Any = None,
    ) -> list[dict[str, Any]]:
        result = [
            i for i in items if self._matches_filter(i, params.get("$filter", ""))
        ]
        if "$search" in params and search_fn:
            result = [i for i in result if search_fn(i, params["$search"])]
        order = params.get("$orderby", default_order)
        if order:
            field_name, _, direction = order.partition(" ")
            result.sort(
                key=lambda i: str(_get_path(i, field_name) or ""),
                reverse=direction.strip().lower() == "desc",
            )
        return result

    # ------------------------------------------------------------------
    # profile
    # ------------------------------------------------------------------
    def _me(self, method, params, body):
        return 200, {
            "id": "user-1",
            "displayName": ACCOUNT_NAME,
            "mail": ACCOUNT_EMAIL,
            "userPrincipalName": ACCOUNT_EMAIL,
        }

    def _mailbox_settings(self, method, params, body):
        return 200, copy.deepcopy(self.mailbox_settings)

    def _mailbox_setting(self, method, params, body, name):
        if name not in self.mailbox_settings:
            return self._not_found(f"{method} /me/mailboxSettings/{name}")
        value = copy.deepcopy(self.mailbox_settings[name])
        return 200, value if isinstance(value, dict) else {"value": value}

    def _search_api(self, method, params, body):
        return self._error(
            400, "BadRequest", "This API is not supported for MSA accounts."
        )

    # ------------------------------------------------------------------
    # mail folders
    # ------------------------------------------------------------------
    def _folder_list(self, parent: str, params: dict[str, str]) -> list[dict]:
        include_hidden = params.get("includeHiddenFolders") == "true"
        return [
            f
            for f in self.folders.values()
            if f["parentFolderId"] == parent
            and (include_hidden or not f.get("isHidden"))
        ]

    def _folders_root(self, method, params, body):
        if method == "GET":
            items = self._query(self._folder_list("msgfolderroot", params), params)
            return 200, self._page(items, params, "/me/mailFolders")
        if method == "POST":
            return 201, self._create_folder("msgfolderroot", body)
        return self._error(405, "MethodNotAllowed", method)

    def _create_folder(self, parent: str, body: dict[str, Any]) -> dict[str, Any]:
        folder_id = self.new_id("folder")
        folder = {
            "id": folder_id,
            "displayName": body.get("displayName", "New folder"),
            "parentFolderId": parent,
            "childFolderCount": 0,
            "unreadItemCount": 0,
            "totalItemCount": 0,
            "isHidden": False,
        }
        self.folders[folder_id] = folder
        if parent in self.folders:
            self.folders[parent]["childFolderCount"] += 1
        return copy.deepcopy(folder)

    def _folder_item(self, method, params, body, folder_id):
        key = self._resolve_folder(folder_id)
        if key is None or key == "msgfolderroot":
            if key == "msgfolderroot" and method == "GET":
                return 200, {
                    "id": "msgfolderroot",
                    "displayName": "Top of Information Store",
                }
            return self._missing("folder", folder_id)
        if method == "GET":
            return 200, copy.deepcopy(self.folders[key])
        if method == "PATCH":
            self.folders[key].update(body or {})
            return 200, copy.deepcopy(self.folders[key])
        if method == "DELETE":
            del self.folders[key]
            return 204, None
        return self._error(405, "MethodNotAllowed", method)

    def _folder_children(self, method, params, body, folder_id):
        key = self._resolve_folder(folder_id)
        if key is None:
            return self._missing("folder", folder_id)
        if method == "GET":
            items = self._query(self._folder_list(key, params), params)
            return 200, self._page(
                items, params, f"/me/mailFolders/{folder_id}/childFolders"
            )
        if method == "POST":
            return 201, self._create_folder(key, body)
        return self._error(405, "MethodNotAllowed", method)

    def _folder_action(self, method, params, body, folder_id, action):
        key = self._resolve_folder(folder_id)
        if key is None:
            return self._missing("folder", folder_id)
        dest = self._resolve_folder(str((body or {}).get("destinationId", "")))
        if dest is None:
            return self._missing("folder", str((body or {}).get("destinationId")))
        self.folders[key]["parentFolderId"] = dest
        return 201, copy.deepcopy(self.folders[key])

    def _folder_messages(self, method, params, body, folder_id):
        key = self._resolve_folder(folder_id)
        if key is None:
            return self._missing("folder", folder_id)
        if method == "GET":
            items = [m for m in self.messages.values() if m["parentFolderId"] == key]
            items = self._query(
                items,
                params,
                default_order="receivedDateTime desc",
                search_fn=self._message_matches_search,
            )
            return 200, self._page(
                items, params, f"/me/mailFolders/{folder_id}/messages"
            )
        if method == "POST":
            return 201, self._create_message(body or {}, key)
        return self._error(405, "MethodNotAllowed", method)

    # ------------------------------------------------------------------
    # rules
    # ------------------------------------------------------------------
    def _rules_root(self, method, params, body, folder_id):
        if method == "GET":
            items = sorted(self.rules.values(), key=lambda r: r.get("sequence", 0))
            return 200, {"value": copy.deepcopy(items)}
        if method == "POST":
            rule_id = self.new_id("rule")
            rule = {"id": rule_id, "isEnabled": True, **(body or {})}
            rule.setdefault(
                "sequence",
                max((r["sequence"] for r in self.rules.values()), default=0) + 1,
            )
            self.rules[rule_id] = rule
            return 201, copy.deepcopy(rule)
        return self._error(405, "MethodNotAllowed", method)

    def _rule_item(self, method, params, body, folder_id, rule_id):
        rule = self.rules.get(rule_id)
        if rule is None:
            return self._missing("rule", rule_id)
        if method == "GET":
            return 200, copy.deepcopy(rule)
        if method == "PATCH":
            rule.update(body or {})
            return 200, copy.deepcopy(rule)
        if method == "DELETE":
            del self.rules[rule_id]
            return 204, None
        return self._error(405, "MethodNotAllowed", method)

    # ------------------------------------------------------------------
    # messages
    # ------------------------------------------------------------------
    def _create_message(self, body: dict[str, Any], folder: str) -> dict[str, Any]:
        msg_id = self.new_id("msg")
        msg = {
            "id": msg_id,
            "conversationId": self.new_id("conv"),
            "subject": body.get("subject", ""),
            "body": body.get("body", {"contentType": "text", "content": ""}),
            "bodyPreview": str(body.get("body", {}).get("content", ""))[:255],
            "from": {"emailAddress": {"name": ACCOUNT_NAME, "address": ACCOUNT_EMAIL}},
            "toRecipients": body.get("toRecipients", []),
            "ccRecipients": body.get("ccRecipients", []),
            "bccRecipients": body.get("bccRecipients", []),
            "receivedDateTime": self.at(0, 12),
            "sentDateTime": None,
            "isRead": True,
            "isDraft": True,
            "hasAttachments": False,
            "importance": body.get("importance", "normal"),
            "flag": {"flagStatus": "notFlagged"},
            "categories": [],
            "parentFolderId": folder,
            "inferenceClassification": "focused",
            "webLink": f"https://outlook.live.com/mail/item/{msg_id}",
        }
        self.messages[msg_id] = msg
        return copy.deepcopy(msg)

    def _messages_root(self, method, params, body):
        if method == "GET":
            items = self._query(
                list(self.messages.values()),
                params,
                default_order="receivedDateTime desc",
                search_fn=self._message_matches_search,
            )
            return 200, self._page(items, params, "/me/messages")
        if method == "POST":
            return 201, self._create_message(body or {}, "drafts")
        return self._error(405, "MethodNotAllowed", method)

    def _send_mail(self, method, params, body):
        message = (body or {}).get("message", {})
        if not message.get("toRecipients"):
            return self._error(
                400, "ErrorInvalidRecipients", "At least one recipient is required."
            )
        sent = self._create_message(message, "sentitems")
        self.messages[sent["id"]]["isDraft"] = False
        return 202, None

    def _message_item(self, method, params, body, msg_id):
        msg = self.messages.get(msg_id)
        if msg is None:
            return self._missing("message", msg_id)
        if method == "GET":
            result = copy.deepcopy(msg)
            if params.get("$expand", "").startswith("attachments"):
                result["attachments"] = copy.deepcopy(self.attachments.get(msg_id, []))
            return 200, result
        if method == "PATCH":
            for key, value in (body or {}).items():
                msg[key] = value
            return 200, copy.deepcopy(msg)
        if method == "DELETE":
            del self.messages[msg_id]
            return 204, None
        return self._error(405, "MethodNotAllowed", method)

    def _message_action(self, method, params, body, msg_id, action):
        msg = self.messages.get(msg_id)
        if msg is None:
            return self._missing("message", msg_id)
        body = body or {}
        if action in ("move", "copy"):
            dest = self._resolve_folder(str(body.get("destinationId", "")))
            if dest is None:
                return self._missing("folder", str(body.get("destinationId")))
            new = copy.deepcopy(msg)
            new["id"] = self.new_id("msg")
            new["parentFolderId"] = dest
            self.messages[new["id"]] = new
            if action == "move":
                del self.messages[msg_id]
            return 201, copy.deepcopy(new)
        if action == "send":
            msg["isDraft"] = False
            msg["parentFolderId"] = "sentitems"
            return 202, None
        if action in ("reply", "replyAll", "forward"):
            if action == "forward" and not body.get("toRecipients"):
                return self._error(
                    400, "ErrorInvalidRecipients", "Recipients are required."
                )
            sent = self._create_message(
                {
                    "subject": ("Fw: " if action == "forward" else "Re: ")
                    + msg["subject"],
                    "toRecipients": body.get("toRecipients")
                    or [{"emailAddress": msg["from"]["emailAddress"]}],
                    "body": {
                        "contentType": "text",
                        "content": body.get("comment")
                        or body.get("message", {}).get("body", {}).get("content", ""),
                    },
                },
                "sentitems",
            )
            self.messages[sent["id"]]["isDraft"] = False
            return 202, None
        if action in ("createReply", "createReplyAll", "createForward"):
            draft = self._create_message(
                {
                    "subject": ("Fw: " if action == "createForward" else "Re: ")
                    + msg["subject"],
                    "toRecipients": []
                    if action == "createForward"
                    else [{"emailAddress": msg["from"]["emailAddress"]}],
                },
                "drafts",
            )
            return 201, draft
        return self._not_found(f"{method} /me/messages/{{id}}/{action}")

    def _attachments_root(self, method, params, body, msg_id):
        if msg_id not in self.messages:
            return self._missing("message", msg_id)
        if method == "GET":
            items = [
                {k: v for k, v in a.items() if k != "contentBytes"}
                for a in self.attachments.get(msg_id, [])
            ]
            return 200, {"value": items}
        if method == "POST":
            att = {"id": self.new_id("att"), **(body or {})}
            att.setdefault("size", len(str(att.get("contentBytes", ""))) * 3 // 4)
            self.attachments.setdefault(msg_id, []).append(att)
            self.messages[msg_id]["hasAttachments"] = True
            return 201, {k: v for k, v in att.items() if k != "contentBytes"}
        return self._error(405, "MethodNotAllowed", method)

    def _attachment_upload_session(self, method, params, body, msg_id):
        return 201, {
            "uploadUrl": f"https://upload.fake/attachment/{msg_id}",
            "expirationDateTime": self.at(1),
        }

    def _attachment_item(self, method, params, body, msg_id, att_id):
        for att in self.attachments.get(msg_id, []):
            if att["id"] == att_id:
                return 200, copy.deepcopy(att)
        return self._missing("attachment", att_id)

    def _attachment_value(self, method, params, body, msg_id, att_id):
        status, att = self._attachment_item(method, params, body, msg_id, att_id)
        if status != 200:
            return status, att
        import base64

        return 200, base64.b64decode(att.get("contentBytes", ""))

    # ------------------------------------------------------------------
    # calendars and events
    # ------------------------------------------------------------------
    def _calendars_root(self, method, params, body):
        if method == "GET":
            return 200, {"value": copy.deepcopy(list(self.calendars.values()))}
        if method == "POST":
            cal_id = self.new_id("cal")
            cal = {
                "id": cal_id,
                "name": (body or {}).get("name", "Calendar"),
                "isDefaultCalendar": False,
                "canEdit": True,
                "color": "auto",
                "owner": {"name": ACCOUNT_NAME, "address": ACCOUNT_EMAIL},
            }
            self.calendars[cal_id] = cal
            return 201, copy.deepcopy(cal)
        return self._error(405, "MethodNotAllowed", method)

    def _default_calendar(self, method, params, body):
        return self._calendar_item(method, params, body, "cal-default")

    def _calendar_item(self, method, params, body, cal_id):
        cal = self.calendars.get(cal_id)
        if cal is None:
            return self._missing("calendar", cal_id)
        if method == "GET":
            return 200, copy.deepcopy(cal)
        if method == "PATCH":
            cal.update(body or {})
            return 200, copy.deepcopy(cal)
        if method == "DELETE":
            if cal.get("isDefaultCalendar"):
                return self._error(
                    400,
                    "ErrorInvalidRequest",
                    "The default calendar cannot be deleted.",
                )
            del self.calendars[cal_id]
            return 204, None
        return self._error(405, "MethodNotAllowed", method)

    def _events_in_window(
        self, cal_id: str | None, params: dict[str, str]
    ) -> list[dict[str, Any]]:
        start = params.get("startDateTime") or params.get("startdatetime")
        end = params.get("endDateTime") or params.get("enddatetime")
        items = [
            e
            for e in self.events.values()
            if cal_id is None or e["calendarId"] == cal_id
        ]
        if start and end:
            window_start, window_end = self._parse_dt(start), self._parse_dt(end)
            items = [
                e
                for e in items
                if self._event_dt(e["start"]) < window_end
                and self._event_dt(e["end"]) > window_start
            ]
        return self._query(items, params, default_order="start/dateTime asc")

    def _event_dt(self, value: dict[str, Any]) -> datetime:
        """Parse a dateTimeTimeZone, honouring an IANA ``timeZone``."""
        parsed = self._parse_dt(value["dateTime"])
        zone = value.get("timeZone") or "UTC"
        if zone != "UTC" and "+" not in value["dateTime"][10:]:
            try:
                parsed = parsed.replace(tzinfo=ZoneInfo(zone))
            except (KeyError, ValueError):
                pass
        return parsed

    def _calendar_view_default(self, method, params, body):
        items = self._events_in_window("cal-default", params)
        return 200, self._page(items, params, "/me/calendarView")

    def _calendar_view(self, method, params, body, cal_id):
        if cal_id not in self.calendars:
            return self._missing("calendar", cal_id)
        items = self._events_in_window(cal_id, params)
        return 200, self._page(items, params, f"/me/calendars/{cal_id}/calendarView")

    def _create_event(self, body: dict[str, Any], cal_id: str) -> dict[str, Any]:
        event_id = self.new_id("evt")
        event = {
            "id": event_id,
            "subject": body.get("subject", ""),
            "start": body.get("start"),
            "end": body.get("end"),
            "isAllDay": body.get("isAllDay", False),
            "location": body.get("location", {"displayName": ""}),
            "body": body.get("body", {"contentType": "text", "content": ""}),
            "bodyPreview": str(body.get("body", {}).get("content", ""))[:255],
            "attendees": body.get("attendees", []),
            "organizer": {
                "emailAddress": {"name": ACCOUNT_NAME, "address": ACCOUNT_EMAIL}
            },
            "isOrganizer": True,
            "responseStatus": {"response": "organizer"},
            "showAs": body.get("showAs", "busy"),
            "calendarId": cal_id,
            "webLink": f"https://outlook.live.com/calendar/item/{event_id}",
            "type": "singleInstance",
        }
        self.events[event_id] = event
        return copy.deepcopy(event)

    def _events_root(self, method, params, body):
        if method == "GET":
            items = self._query(
                list(self.events.values()), params, default_order="start/dateTime asc"
            )
            return 200, self._page(items, params, "/me/events")
        if method == "POST":
            return 201, self._create_event(body or {}, "cal-default")
        return self._error(405, "MethodNotAllowed", method)

    def _calendar_events(self, method, params, body, cal_id):
        if cal_id not in self.calendars:
            return self._missing("calendar", cal_id)
        if method == "GET":
            items = [e for e in self.events.values() if e["calendarId"] == cal_id]
            return 200, self._page(
                self._query(items, params), params, f"/me/calendars/{cal_id}/events"
            )
        if method == "POST":
            return 201, self._create_event(body or {}, cal_id)
        return self._error(405, "MethodNotAllowed", method)

    def _event_item(self, method, params, body, event_id):
        event = self.events.get(event_id)
        if event is None:
            return self._missing("event", event_id)
        if method == "GET":
            return 200, copy.deepcopy(event)
        if method == "PATCH":
            event.update(body or {})
            return 200, copy.deepcopy(event)
        if method == "DELETE":
            del self.events[event_id]
            return 204, None
        return self._error(405, "MethodNotAllowed", method)

    def _event_action(self, method, params, body, event_id, action):
        event = self.events.get(event_id)
        if event is None:
            return self._missing("event", event_id)
        responses = {
            "accept": "accepted",
            "tentativelyAccept": "tentativelyAccepted",
            "decline": "declined",
        }
        if action in responses:
            event["responseStatus"] = {"response": responses[action]}
            return 202, None
        if action == "cancel":
            del self.events[event_id]
            return 202, None
        if action == "forward":
            if not (body or {}).get("toRecipients"):
                return self._error(
                    400, "ErrorInvalidRecipients", "Recipients are required."
                )
            return 202, None
        if action == "instances":
            return 200, {"value": [copy.deepcopy(event)]}
        return self._not_found(f"{method} /me/events/{{id}}/{action}")

    def _get_schedule(self, method, params, body):
        schedules = []
        for address in (body or {}).get("schedules", []):
            if address.lower() != ACCOUNT_EMAIL:
                schedules.append(
                    {
                        "scheduleId": address,
                        "error": {
                            "message": "Proxy web request failed.",
                            "responseCode": "ErrorProxyRequestProcessingFailed",
                        },
                    }
                )
                continue
            start = self._parse_dt(body["startTime"]["dateTime"])
            end = self._parse_dt(body["endTime"]["dateTime"])
            items = [
                {
                    "status": e["showAs"],
                    "start": e["start"],
                    "end": e["end"],
                }
                for e in self.events.values()
                if self._parse_dt(e["start"]["dateTime"]) < end
                and self._parse_dt(e["end"]["dateTime"]) > start
            ]
            schedules.append({"scheduleId": address, "scheduleItems": items})
        return 200, {"value": schedules}

    def _find_meeting_times(self, method, params, body):
        return self._error(
            400,
            "ErrorInvalidRequest",
            "This operation is not supported for this account.",
        )

    # ------------------------------------------------------------------
    # contacts
    # ------------------------------------------------------------------
    def _contact_search(self, contact: dict[str, Any], raw: str) -> bool:
        terms = self._search_terms(raw)
        hay = " ".join(
            [
                contact.get("displayName", ""),
                " ".join(
                    e.get("address", "") for e in contact.get("emailAddresses", [])
                ),
            ]
        ).lower()
        return all(t in hay for t in terms)

    def _contacts_root(self, method, params, body):
        if method == "GET":
            items = self._query(
                list(self.contacts.values()),
                params,
                default_order="displayName asc",
                search_fn=self._contact_search,
            )
            return 200, self._page(items, params, "/me/contacts")
        if method == "POST":
            return 201, self._create_contact(body or {}, "contacts-root")
        return self._error(405, "MethodNotAllowed", method)

    def _create_contact(self, body: dict[str, Any], folder: str) -> dict[str, Any]:
        contact_id = self.new_id("contact")
        given = body.get("givenName", "")
        surname = body.get("surname", "")
        contact = {
            "id": contact_id,
            "displayName": body.get("displayName") or f"{given} {surname}".strip(),
            "givenName": given,
            "surname": surname,
            "emailAddresses": body.get("emailAddresses", []),
            "mobilePhone": body.get("mobilePhone"),
            "businessPhones": body.get("businessPhones", []),
            "homePhones": body.get("homePhones", []),
            "companyName": body.get("companyName"),
            "jobTitle": body.get("jobTitle"),
            "department": body.get("department"),
            "parentFolderId": folder,
        }
        self.contacts[contact_id] = contact
        return copy.deepcopy(contact)

    def _contact_item(self, method, params, body, contact_id):
        contact = self.contacts.get(contact_id)
        if contact is None:
            return self._missing("contact", contact_id)
        if method == "GET":
            return 200, copy.deepcopy(contact)
        if method == "PATCH":
            contact.update(body or {})
            return 200, copy.deepcopy(contact)
        if method == "DELETE":
            del self.contacts[contact_id]
            return 204, None
        return self._error(405, "MethodNotAllowed", method)

    def _contact_folders_root(self, method, params, body):
        if method == "GET":
            return 200, {"value": copy.deepcopy(list(self.contact_folders.values()))}
        if method == "POST":
            folder_id = self.new_id("cfolder")
            folder = {
                "id": folder_id,
                "displayName": (body or {}).get("displayName", "Folder"),
                "parentFolderId": "contacts-root",
            }
            self.contact_folders[folder_id] = folder
            return 201, copy.deepcopy(folder)
        return self._error(405, "MethodNotAllowed", method)

    def _contact_folder_item(self, method, params, body, folder_id):
        folder = self.contact_folders.get(folder_id)
        if folder is None:
            return self._missing("contact folder", folder_id)
        if method == "GET":
            return 200, copy.deepcopy(folder)
        if method == "PATCH":
            folder.update(body or {})
            return 200, copy.deepcopy(folder)
        if method == "DELETE":
            del self.contact_folders[folder_id]
            return 204, None
        return self._error(405, "MethodNotAllowed", method)

    def _contact_folder_contacts(self, method, params, body, folder_id):
        if folder_id not in self.contact_folders:
            return self._missing("contact folder", folder_id)
        if method == "GET":
            items = [
                c for c in self.contacts.values() if c["parentFolderId"] == folder_id
            ]
            return 200, self._page(
                self._query(items, params),
                params,
                f"/me/contactFolders/{folder_id}/contacts",
            )
        if method == "POST":
            return 201, self._create_contact(body or {}, folder_id)
        return self._error(405, "MethodNotAllowed", method)

    def _contact_folder_children(self, method, params, body, folder_id):
        if method == "POST":
            if folder_id not in self.contact_folders:
                return self._missing("contact folder", folder_id)
            child_id = self.new_id("cfolder")
            child = {
                "id": child_id,
                "displayName": (body or {}).get("displayName", "Folder"),
                "parentFolderId": folder_id,
            }
            self.contact_folders[child_id] = child
            return 201, copy.deepcopy(child)
        items = [
            f for f in self.contact_folders.values() if f["parentFolderId"] == folder_id
        ]
        return 200, {"value": copy.deepcopy(items)}

    # ------------------------------------------------------------------
    # OneDrive
    # ------------------------------------------------------------------
    def _drive_path_of(self, item: dict[str, Any]) -> str:
        parts = []
        current = item
        while current and current["id"] != "root":
            parts.append(current["name"])
            current = self.drive.get(current["parentReference"]["id"])
        return "/" + "/".join(reversed(parts))

    def _drive_view(self, item: dict[str, Any]) -> dict[str, Any]:
        view = copy.deepcopy(item)
        view.pop("_content", None)
        if item["id"] != "root":
            parent_path = (
                self._drive_path_of(self.drive[item["parentReference"]["id"]])
                if item["parentReference"]["id"] != "root"
                else ""
            )
            view["parentReference"] = {
                "id": item["parentReference"]["id"],
                "driveId": "drive-1",
                "path": f"/drive/root:{parent_path}",
            }
        if "folder" in item:
            view["folder"] = {"childCount": len(self._drive_children_of(item["id"]))}
        else:
            view["@microsoft.graph.downloadUrl"] = (
                f"https://fake.1drv.com/download/{item['id']}"
            )
        return view

    def _drive_children_of(self, item_id: str) -> list[dict[str, Any]]:
        return [
            i
            for i in self.drive.values()
            if i["id"] != "root" and i["parentReference"]["id"] == item_id
        ]

    def _drive_by_path(self, path: str) -> dict[str, Any] | None:
        path = "/" + path.strip("/")
        if path == "/":
            return self.drive["root"]
        for item in self.drive.values():
            if (
                item["id"] != "root"
                and self._drive_path_of(item).lower() == path.lower()
            ):
                return item
        return None

    def _drive_info(self, method, params, body):
        return 200, {
            "id": "drive-1",
            "driveType": "personal",
            "quota": {"total": 5 * 1024**3, "used": 123456789},
        }

    def _drive_root(self, method, params, body):
        return 200, self._drive_view(self.drive["root"])

    def _drive_list(self, parent_id: str, params: dict[str, str], path: str):
        items = [self._drive_view(i) for i in self._drive_children_of(parent_id)]
        items = self._query(items, params, default_order="name asc")
        return 200, self._page(items, params, path)

    def _drive_root_children(self, method, params, body):
        if method == "POST":
            return self._drive_create_child("root", body or {})
        return self._drive_list("root", params, "/me/drive/root/children")

    def _drive_search(self, method, params, body, query):
        terms = self._search_terms(query.replace("''", "'"))
        items = [
            self._drive_view(i)
            for i in self.drive.values()
            if i["id"] != "root" and all(t in i["name"].lower() for t in terms)
        ]
        # The nextLink keeps the (encoded) query, as Graph's does.
        path = f"/me/drive/root/search(q='{quote(query, safe='')}')"
        return 200, self._page(items, params, path)

    def _drive_path(self, method, params, body, path):
        item = self._drive_by_path(path)
        if item is None:
            return self._missing("item", path)
        return self._drive_item(method, params, body, item["id"])

    def _drive_path_children(self, method, params, body, path):
        item = self._drive_by_path(path)
        if item is None:
            return self._missing("item", path)
        if method == "POST":
            return self._drive_create_child(item["id"], body or {})
        return self._drive_list(item["id"], params, f"/me/drive/root:{path}:/children")

    def _drive_path_content(self, method, params, body, path):
        parent_path, _, name = path.rstrip("/").rpartition("/")
        existing = self._drive_by_path(path)
        if method == "GET":
            if existing is None:
                return self._missing("item", path)
            return 200, existing.get("_content", b"")
        parent = self._drive_by_path(parent_path or "/")
        if parent is None:
            return self._missing("item", parent_path)
        return self._drive_put(parent["id"], name, body, existing)

    def _drive_put(self, parent_id, name, body, existing):
        content = body if isinstance(body, bytes) else json.dumps(body or "").encode()
        if existing is not None:
            existing["_content"] = content
            existing["size"] = len(content)
            return 200, self._drive_view(existing)
        item = self._new_drive_item(parent_id, name, file=True, size=len(content))
        item["_content"] = content
        return 201, self._drive_view(item)

    def _drive_path_upload_session(self, method, params, body, path):
        return 200, {
            "uploadUrl": f"https://upload.fake/drive{path}",
            "expirationDateTime": self.at(1),
        }

    def _new_drive_item(self, parent_id: str, name: str, file: bool, size: int = 0):
        item_id = self.new_id("item")
        item: dict[str, Any] = {
            "id": item_id,
            "name": name,
            "size": size,
            "createdDateTime": self.at(0, 12),
            "lastModifiedDateTime": self.at(0, 12),
            "parentReference": {"id": parent_id},
            "webUrl": f"https://onedrive.live.com/?id={item_id}",
        }
        if file:
            item["file"] = {"mimeType": "application/octet-stream"}
        else:
            item["folder"] = {"childCount": 0}
        self.drive[item_id] = item
        return item

    def _drive_create_child(self, parent_id: str, body: dict[str, Any]):
        name = body.get("name", "New folder")
        conflict = body.get("@microsoft.graph.conflictBehavior", "fail")
        clash = [
            c
            for c in self._drive_children_of(parent_id)
            if c["name"].lower() == name.lower()
        ]
        if clash and conflict == "fail":
            return self._error(
                409, "nameAlreadyExists", "An item with the same name already exists."
            )
        if clash and conflict == "rename":
            name = f"{name} 1"
        item = self._new_drive_item(parent_id, name, file="folder" not in body)
        return 201, self._drive_view(item)

    def _drive_item(self, method, params, body, item_id):
        item = self.drive.get(item_id)
        if item is None:
            return self._missing("item", item_id)
        if method == "GET":
            return 200, self._drive_view(item)
        if method == "PATCH":
            body = body or {}
            if "name" in body:
                item["name"] = body["name"]
            if "parentReference" in body:
                parent = body["parentReference"]
                parent_id = parent.get("id")
                if not parent_id and parent.get("path"):
                    target = self._drive_by_path(
                        parent["path"].split(":", 1)[-1] or "/"
                    )
                    parent_id = target["id"] if target else None
                if parent_id not in self.drive:
                    return self._missing("item", str(parent_id))
                item["parentReference"] = {"id": parent_id}
            return 200, self._drive_view(item)
        if method == "DELETE":
            if item_id == "root":
                return self._error(403, "accessDenied", "Cannot delete the root.")
            for child in self._drive_children_of(item_id):
                self.drive.pop(child["id"], None)
            del self.drive[item_id]
            return 204, None
        return self._error(405, "MethodNotAllowed", method)

    def _drive_children(self, method, params, body, item_id):
        if item_id not in self.drive:
            return self._missing("item", item_id)
        if method == "POST":
            return self._drive_create_child(item_id, body or {})
        return self._drive_list(item_id, params, f"/me/drive/items/{item_id}/children")

    def _drive_content(self, method, params, body, item_id):
        item = self.drive.get(item_id)
        if item is None:
            return self._missing("item", item_id)
        if method == "GET":
            return 200, item.get("_content", b"fake file content")
        return self._drive_put(item["parentReference"]["id"], item["name"], body, item)

    def _drive_child_content(self, method, params, body, parent_id, name):
        if parent_id not in self.drive:
            return self._missing("item", parent_id)
        existing = next(
            (
                c
                for c in self._drive_children_of(parent_id)
                if c["name"].lower() == name.lower()
            ),
            None,
        )
        conflict = params.get("@microsoft.graph.conflictBehavior", "replace")
        if existing is not None and conflict == "fail":
            return self._error(
                409, "nameAlreadyExists", "An item with the same name already exists."
            )
        if existing is not None and conflict == "rename":
            stem, dot, ext = name.rpartition(".")
            name = f"{stem} 1{dot}{ext}" if dot else f"{name} 1"
            existing = None
        return self._drive_put(parent_id, name, body, existing)

    def _drive_child_upload_session(self, method, params, body, parent_id, name):
        return 200, {
            "uploadUrl": f"https://upload.fake/drive/{parent_id}/{name}",
            "expirationDateTime": self.at(1),
        }

    def _drive_action(self, method, params, body, item_id, action):
        item = self.drive.get(item_id)
        if item is None:
            return self._missing("item", item_id)
        body = body or {}
        if action == "copy":
            parent = body.get("parentReference", {}).get(
                "id", item["parentReference"]["id"]
            )
            copied = self._new_drive_item(
                parent,
                body.get("name", item["name"]),
                file="file" in item,
                size=item.get("size", 0),
            )
            return 202, {
                "__headers__": {"Location": f"https://monitor.fake/copy/{copied['id']}"}
            }
        if action == "createLink":
            if item_id == "root":
                return self._error(403, "accessDenied", "Cannot share the root.")
            link_type = body.get("type", "view")
            return 201, {
                "id": f"perm-{item_id}-{link_type}",
                "roles": ["write" if link_type == "edit" else "read"],
                "link": {
                    "type": link_type,
                    "scope": body.get("scope", "anonymous"),
                    "webUrl": f"https://1drv.ms/x/s!{item_id}-{link_type}",
                },
            }
        if action == "invite":
            if item_id == "root":
                return self._error(403, "accessDenied", "Cannot share the root.")
            return 200, {
                "value": [
                    {
                        "id": f"perm-{item_id}-{i}",
                        "roles": body.get("roles", ["read"]),
                        "grantedTo": {"user": {"email": r.get("email")}},
                    }
                    for i, r in enumerate(body.get("recipients", []))
                ]
            }
        if action == "permissions":
            return 200, {"value": []}
        if action == "createUploadSession":
            return 200, {
                "uploadUrl": f"https://upload.fake/drive/items/{item_id}",
                "expirationDateTime": self.at(1),
            }
        return self._not_found(f"{method} /me/drive/items/{{id}}/{action}")

    # ------------------------------------------------------------------
    # batch and external URLs
    # ------------------------------------------------------------------
    def _batch(self, body: Any) -> tuple[int, Any]:
        responses = []
        for sub in (body or {}).get("requests", []):
            url = sub.get("url", "")
            split = urlsplit(url if url.startswith("/") else "/" + url)
            params = dict(parse_qsl(split.query, keep_blank_values=True))
            status, payload = self.dispatch(
                sub.get("method", "GET"), unquote(split.path), params, sub.get("body")
            )
            self.calls.append(
                RecordedCall(
                    sub.get("method", "GET"),
                    unquote(split.path),
                    params,
                    sub.get("body"),
                    status,
                )
            )
            entry: dict[str, Any] = {"id": sub.get("id"), "status": status}
            if payload is not None and not isinstance(payload, bytes):
                entry["body"] = payload
            responses.append(entry)
        return 200, {"responses": responses}

    def _external(self, method: str, url: str, body: Any) -> tuple[int, Any]:
        if url.startswith("https://monitor.fake/copy/"):
            item_id = url.rsplit("/", 1)[-1]
            return 200, {
                "status": "completed",
                "percentageComplete": 100,
                "resourceId": item_id,
            }
        if url.startswith("https://fake.1drv.com/download/"):
            item = self.drive.get(url.rsplit("/", 1)[-1])
            if item is None:
                return self._not_found(f"{method} {url}")
            return 200, item.get("_content", b"")
        if url.startswith("https://upload.fake/"):
            return 201, {"id": self.new_id("upload"), "name": url.rsplit("/", 1)[-1]}
        return self._not_found(f"{method} {url}")


def _split_top(expression: str, separator: str) -> list[str]:
    """Split on ``separator`` outside parentheses and quotes."""
    parts: list[str] = []
    depth = 0
    in_quote = False
    current = ""
    i = 0
    lower = expression.lower()
    while i < len(expression):
        char = expression[i]
        if char == "'":
            in_quote = not in_quote
        elif not in_quote and char == "(":
            depth += 1
        elif not in_quote and char == ")":
            depth -= 1
        if not in_quote and depth == 0 and lower.startswith(separator, i):
            parts.append(current)
            current = ""
            i += len(separator)
            continue
        current += char
        i += 1
    parts.append(current)
    return [p.strip() for p in parts if p.strip()]


def _get_path(item: Any, path: str) -> Any:
    """Read a slash-separated property path from a Graph object."""
    current = item
    for part in path.split("/"):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current
