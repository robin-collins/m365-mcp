from typing import NamedTuple, Any


class RecurrencePattern(NamedTuple):
    type: str  # "daily", "weekly", "absoluteMonthly", "relativeMonthly", "absoluteYearly", "relativeYearly"
    interval: int
    days_of_week: list[str] | None = None
    day_of_month: int | None = None
    first_day_of_week: str = "sunday"


class RecurrenceRange(NamedTuple):
    type: str  # "endDate", "noEnd", "numbered"
    start_date: str
    end_date: str | None = None
    number_of_occurrences: int | None = None


class EventReminder(NamedTuple):
    minutes_before_start: int
    is_reminder_on: bool = True


def _build_recurrence_data(
    pattern: RecurrencePattern, range_info: RecurrenceRange
) -> dict[str, Any]:
    recurrence = {
        "pattern": {
            "type": pattern.type,
            "interval": pattern.interval,
            "firstDayOfWeek": pattern.first_day_of_week,
        },
        "range": {
            "type": range_info.type,
            "startDate": range_info.start_date,
        },
    }

    if pattern.days_of_week:
        recurrence["pattern"]["daysOfWeek"] = pattern.days_of_week

    if pattern.day_of_month:
        recurrence["pattern"]["dayOfMonth"] = pattern.day_of_month

    if range_info.end_date:
        recurrence["range"]["endDate"] = range_info.end_date

    if range_info.number_of_occurrences:
        recurrence["range"]["numberOfOccurrences"] = range_info.number_of_occurrences

    return recurrence


def build_event_payload(
    subject: str,
    start_datetime: str,
    end_datetime: str,
    timezone: str = "UTC",
    location: str | None = None,
    body_content: str | None = None,
    attendees: list[str] | None = None,
    reminders: list[EventReminder] | None = None,
    recurrence: tuple[RecurrencePattern, RecurrenceRange] | None = None,
    is_all_day: bool = False,
) -> dict[str, Any]:
    event = {
        "subject": subject,
        "start": {"dateTime": start_datetime, "timeZone": timezone},
        "end": {"dateTime": end_datetime, "timeZone": timezone},
        "isAllDay": is_all_day,
    }

    if location:
        event["location"] = {"displayName": location}

    if body_content:
        event["body"] = {"contentType": "Text", "content": body_content}

    if attendees:
        event["attendees"] = [
            {"emailAddress": {"address": addr}, "type": "required"}
            for addr in attendees
        ]

    if reminders:
        event["isReminderOn"] = True
        event["reminderMinutesBeforeStart"] = reminders[0].minutes_before_start
    else:
        event["isReminderOn"] = False

    if recurrence:
        pattern, range_info = recurrence
        event["recurrence"] = _build_recurrence_data(pattern, range_info)

    return event
