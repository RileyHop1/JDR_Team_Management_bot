"""Local schedule validation, including daylight-saving gaps and overlaps."""

from datetime import UTC, datetime

import pytest

from jdr_bot.domain import MeetingError, plan_meeting

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def plan(**overrides: str) -> object:
    values = {
        "title": "Design review",
        "start_text": "2026-06-01 17:00",
        "timezone_name": "America/Los_Angeles",
        "offsets_text": "60,15",
    }
    values.update(overrides)
    return plan_meeting(now=NOW, **values)


def test_spring_forward_offset_is_absolute_not_wall_clock():
    planned = plan_meeting(
        now=NOW,
        title="Design review",
        start_text="2026-03-08 03:30",
        timezone_name="America/Los_Angeles",
        offsets_text="120",
    )
    assert planned.starts_at == datetime(2026, 3, 8, 10, 30, tzinfo=UTC)
    assert planned.reminders[0].due_at == datetime(2026, 3, 8, 8, 30, tzinfo=UTC)
    # Subtracting two hours from the wall clock would land on 01:30 PST, which is 09:30 UTC.
    assert planned.reminders[0].due_at != datetime(2026, 3, 8, 9, 30, tzinfo=UTC)


def test_fall_back_offset_is_absolute_not_wall_clock():
    planned = plan_meeting(
        now=NOW,
        title="Retro",
        start_text="2026-11-01 03:00",
        timezone_name="America/Los_Angeles",
        offsets_text="180",
    )
    assert planned.starts_at == datetime(2026, 11, 1, 11, 0, tzinfo=UTC)
    assert planned.reminders[0].due_at == datetime(2026, 11, 1, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("start_text", "timezone_name", "match"),
    [
        ("2026-03-08 02:30", "America/Los_Angeles", "does not exist"),
        ("2026-10-04 02:30", "Australia/Sydney", "does not exist"),
        ("2026-11-01 01:30", "America/Los_Angeles", "happens twice"),
        ("2026-04-05 02:30", "Australia/Sydney", "happens twice"),
    ],
)
def test_daylight_saving_transitions_are_rejected(start_text, timezone_name, match):
    with pytest.raises(MeetingError, match=match):
        plan_meeting(
            now=NOW,
            title="Design review",
            start_text=start_text,
            timezone_name=timezone_name,
            offsets_text="15",
        )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("start_text", "2026-06-01 17:00:00", "YYYY-MM-DD"),
        ("start_text", "June 1 2026 5pm", "YYYY-MM-DD"),
        ("timezone_name", "Mars/Olympus", "IANA"),
        ("timezone_name", "", "IANA"),
        ("offsets_text", "", "comma-separated"),
        ("offsets_text", "60,60", "unique"),
        ("offsets_text", "0,15", "1 to 10080"),
        ("offsets_text", "-5", "positive whole"),
        ("offsets_text", "15.5", "positive whole"),
        ("offsets_text", "1,2,3,4,5,6", "at most 5"),
        ("offsets_text", "10081", "10080"),
        ("title", "   ", "title"),
        ("title", "x" * 101, "title"),
    ],
)
def test_rejects_invalid_schedule_fields(field, value, match):
    with pytest.raises(MeetingError, match=match):
        plan(**{field: value})


def test_rejects_past_start_and_past_reminder():
    with pytest.raises(MeetingError, match="in the future"):
        plan_meeting(
            now=datetime(2026, 6, 2, tzinfo=UTC),
            title="Design review",
            start_text="2026-06-01 17:00",
            timezone_name="UTC",
            offsets_text="15",
        )
    with pytest.raises(MeetingError, match="60-minute reminder"):
        plan_meeting(
            now=datetime(2026, 6, 1, 16, 30, tzinfo=UTC),
            title="Design review",
            start_text="2026-06-01 17:00",
            timezone_name="UTC",
            offsets_text="60,15",
        )


def test_offset_order_does_not_change_the_plan():
    first = plan(offsets_text="15,60")
    second = plan(offsets_text="60, 15")
    assert [(item.offset_minutes, item.due_at) for item in first.reminders] == [
        (item.offset_minutes, item.due_at) for item in second.reminders
    ]


def test_naive_clock_is_rejected():
    with pytest.raises(MeetingError, match="timezone-aware"):
        plan_meeting(
            now=datetime(2026, 1, 1),
            title="Design review",
            start_text="2026-06-01 17:00",
            timezone_name="UTC",
            offsets_text="15",
        )
