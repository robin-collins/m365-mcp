"""``calendar_find_availability``: busy blocks and free slots (U3.16).

Busy time comes from ``calendarView`` (``showAs`` busy, tentative, oof or
workingElsewhere) and working hours from ``mailboxSettings``. Free slots
are computed here: ``getSchedule`` and ``findMeetingTimes`` do not work
for other people on personal accounts.

All interval arithmetic runs on UTC instants. Working hours are built as
wall-clock times in their own zone for each calendar day, so days that
cross a daylight-saving change keep the right local hours.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ...services import calendar as cal
from ...untrusted import sanitize_text
from ..handlers import register_handler, register_validation_rule
from .calendar import (
    EN_DASH,
    check_time_zone,
    output_zone,
    parse_dt,
    plural,
    short_moment,
)
from .common import account, arg, check_rate, invalid

TOOL = "calendar_find_availability"
MAX_SPAN = timedelta(days=62)
BUSY_STATES = ("busy", "tentative", "oof", "workingElsewhere")
WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

Interval = tuple[datetime, datetime]


@register_validation_rule(TOOL)
def _availability_rules(args: dict[str, Any]) -> None:
    start, end = parse_dt(args["start"]), parse_dt(args["end"])
    if end <= start or end - start > MAX_SPAN:
        raise invalid("end", "must be after start and within 62 days")
    check_time_zone(args.get("time_zone"))


def _instant(value: dict[str, Any]) -> datetime:
    """Convert a Graph dateTimeTimeZone to an aware UTC datetime."""
    parsed = datetime.fromisoformat(value["dateTime"])
    if parsed.tzinfo is None:
        zone = cal.to_iana_time_zone(value.get("timeZone")) or "UTC"
        parsed = parsed.replace(tzinfo=ZoneInfo(zone))
    return parsed.astimezone(UTC)


def working_hours(
    raw: dict[str, Any] | None, fallback_zone: str
) -> dict[str, Any] | None:
    """Project Graph ``workingHours`` to the output record.

    Args:
        raw: Graph ``workingHours`` or ``None``.
        fallback_zone: IANA zone used when Graph's zone cannot be mapped.

    Returns:
        ``{days, start_time, end_time, time_zone}`` or ``None``.
    """
    if not raw:
        return None
    zone = (raw.get("timeZone") or {}).get("name")
    return {
        "days": [
            d.lower() for d in raw.get("daysOfWeek") or [] if d.lower() in WEEKDAYS
        ],
        "start_time": str(raw.get("startTime") or "00:00:00")[:8],
        "end_time": str(raw.get("endTime") or "00:00:00")[:8],
        "time_zone": cal.to_iana_time_zone(zone) or fallback_zone,
    }


def merge(intervals: list[Interval]) -> list[Interval]:
    """Merge overlapping or touching intervals."""
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def working_intervals(
    start: datetime, end: datetime, hours: dict[str, Any]
) -> list[Interval]:
    """Return the working-hour intervals that overlap ``[start, end)``.

    Args:
        start: Window start (aware).
        end: Window end (aware).
        hours: Working hours record from :func:`working_hours`.

    Returns:
        UTC intervals clipped to the window, in order.
    """
    zone = ZoneInfo(hours["time_zone"])
    days = set(hours["days"])
    day_start = time.fromisoformat(hours["start_time"])
    day_end = time.fromisoformat(hours["end_time"])
    result: list[Interval] = []
    day: date = start.astimezone(zone).date() - timedelta(days=1)
    last = end.astimezone(zone).date()
    while day <= last:
        if WEEKDAYS[day.weekday()] in days:
            end_day = day if day_end > day_start else day + timedelta(days=1)
            local_start = datetime.combine(day, day_start, tzinfo=zone)
            local_end = datetime.combine(end_day, day_end, tzinfo=zone)
            clipped_start = max(local_start.astimezone(UTC), start)
            clipped_end = min(local_end.astimezone(UTC), end)
            if clipped_start < clipped_end:
                result.append((clipped_start, clipped_end))
        day += timedelta(days=1)
    return merge(result)


def _subtract(window: Interval, blocked: list[Interval]) -> list[Interval]:
    free: list[Interval] = []
    cursor, end = window
    for block_start, block_end in blocked:
        if block_end <= cursor or block_start >= end:
            continue
        if block_start > cursor:
            free.append((cursor, block_start))
        cursor = max(cursor, block_end)
        if cursor >= end:
            break
    if cursor < end:
        free.append((cursor, end))
    return free


def free_slots(
    start: datetime,
    end: datetime,
    busy: list[Interval],
    *,
    slot: timedelta,
    gap: timedelta,
    hours: dict[str, Any] | None,
    max_slots: int,
) -> list[Interval]:
    """Suggest free slots of length ``slot`` in chronological order.

    Busy time is widened by ``gap`` on both sides. Each free stretch is
    filled with back-to-back slots from its start.

    Args:
        start: Window start (aware).
        end: Window end (aware).
        busy: Busy intervals (aware).
        slot: Slot length.
        gap: Buffer kept before and after busy time.
        hours: Working hours to stay inside, or ``None`` for any time.
        max_slots: Most slots to return.

    Returns:
        UTC ``(start, end)`` pairs.
    """
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    blocked = merge([(s - gap, e + gap) for s, e in busy])
    allowed = working_intervals(start, end, hours) if hours else [(start, end)]
    slots: list[Interval] = []
    for window in allowed:
        for free_start, free_end in _subtract(window, blocked):
            cursor = free_start
            while cursor + slot <= free_end:
                slots.append((cursor, cursor + slot))
                if len(slots) >= max_slots:
                    return slots
                cursor += slot
    return slots


def _slot_label(minutes: int) -> str:
    if minutes % 60 == 0:
        hours = minutes // 60
        return "hour" if hours == 1 else f"{hours}-hour slot"
    return f"{minutes}-minute slot"


@register_handler(TOOL)
def find_availability(args: dict[str, Any]) -> dict[str, Any]:
    """Return busy blocks, working hours and suggested free slots."""
    account_id = account(args)
    check_rate(account_id, "normal")
    start, end = parse_dt(args["start"]), parse_dt(args["end"])
    zone_name = output_zone(account_id, args.get("time_zone"))
    zone = ZoneInfo(zone_name)

    busy_records: list[dict[str, Any]] = []
    busy: list[Interval] = []
    for event in cal.calendar_view_busy(account_id, start=start, end=end):
        show_as = event.get("showAs")
        if show_as not in BUSY_STATES:
            continue
        block = (_instant(event["start"]), _instant(event["end"]))
        busy.append(block)
        busy_records.append(
            {
                "start": block[0].astimezone(zone).isoformat(),
                "end": block[1].astimezone(zone).isoformat(),
                "show_as": show_as,
                "subject": sanitize_text(event.get("subject")),
            }
        )
    hours = working_hours(cal.get_working_hours(account_id), zone_name)

    slot_minutes = args.get("slot_minutes")
    slots: list[Interval] = []
    if slot_minutes:
        slots = free_slots(
            start,
            end,
            busy,
            slot=timedelta(minutes=slot_minutes),
            gap=timedelta(minutes=arg(args, TOOL, "min_gap_minutes")),
            hours=hours if arg(args, TOOL, "working_hours_only") else None,
            max_slots=arg(args, TOOL, "max_slots"),
        )
    local_slots = [(s.astimezone(zone), e.astimezone(zone)) for s, e in slots]

    summary = plural(len(busy_records), "busy block")
    if slot_minutes:
        label = _slot_label(slot_minutes)
        if local_slots:
            first_start, first_end = local_slots[0]
            one_day = (
                start.astimezone(zone).date()
                == (end - timedelta(microseconds=1)).astimezone(zone).date()
            )
            begin = f"{first_start:%H:%M}" if one_day else short_moment(first_start)
            summary += f"; first free {label} {begin}{EN_DASH}{first_end:%H:%M}"
        else:
            summary += f"; no free {label} found"
    summary += "."
    return {
        "time_zone": zone_name,
        "busy": busy_records,
        "free_slots": [
            {"start": s.isoformat(), "end": e.isoformat()} for s, e in local_slots
        ],
        "working_hours": hours,
        "summary": summary,
    }
