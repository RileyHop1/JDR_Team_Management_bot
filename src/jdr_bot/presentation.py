"""Operator-facing meeting text. Mentions are suppressed by the Discord client."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jdr_bot.domain import JobRecord, JobState, MeetingList, MeetingRecord, as_utc
from jdr_bot.ports import ReminderNotice


def format_meeting(meeting: MeetingRecord) -> str:
    """Render one meeting, including reminder outcomes and hiding cancelled rows."""
    lines = [
        f"Meeting {meeting.id}: {meeting.title}",
        f"Status: {meeting.state.value}",
        f"Starts: {zoned_stamp(meeting.starts_at, meeting.timezone_name)}",
        f"Text channel: {meeting.text_channel_id}",
        f"Voice channel: {meeting.voice_channel_id}",
        f"Organizer: {meeting.organizer_id}",
        "Reminders:",
    ]
    visible = [job for job in meeting.jobs if job.state is not JobState.CANCELLED]
    if not visible:
        lines.append("- none")
    else:
        lines.extend(f"- {_job_line(job)}" for job in visible)
    return "\n".join(lines)


def format_meeting_list(listing: MeetingList) -> str:
    """Render the scheduled-meeting list."""
    if not listing.meetings:
        return "No scheduled meetings."
    lines = ["Scheduled meetings:"]
    for meeting in listing.meetings:
        lines.append(
            f"- {meeting.id}: {meeting.title} at "
            f"{zoned_stamp(meeting.starts_at, meeting.timezone_name)}"
        )
    if listing.truncated:
        lines.append(f"Showing the next {len(listing.meetings)} scheduled meetings.")
    return "\n".join(lines)


def reminder_message(notice: ReminderNotice) -> str:
    """Build the channel message for one reminder. The zone must already be valid."""
    zone = ZoneInfo(notice.timezone_name)
    local = notice.starts_at.astimezone(zone)
    return (
        f"Meeting {notice.meeting_id} reminder: {notice.title} "
        f"starts at {local.strftime('%Y-%m-%d %H:%M')} ({notice.timezone_name}), "
        f"{notice.offset_minutes} minutes before start. "
        f"Voice channel: <#{notice.voice_channel_id}>."
    )


def zoned_stamp(instant: datetime, timezone_name: str) -> str:
    """Show the local wall time and the UTC instant."""
    utc_text = as_utc(instant).astimezone(UTC).strftime("%Y-%m-%d %H:%M")
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return f"{utc_text} UTC"
    local = instant.astimezone(zone)
    return f"{local.strftime('%Y-%m-%d %H:%M')} {timezone_name} ({utc_text} UTC)"


def _job_line(job: JobRecord) -> str:
    due = as_utc(job.due_at).strftime("%Y-%m-%d %H:%M")
    detail = job.state.value
    if job.failure_category:
        detail = f"{detail} ({job.failure_category})"
    if job.delivery_receipt:
        detail = f"{detail}, message {job.delivery_receipt}"
    return f"{job.offset_minutes} min before: {detail}, due {due} UTC"
