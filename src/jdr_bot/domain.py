"""Meeting schedule rules. No Discord, database, or clock I/O."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jdr_bot.policy import (
    MAX_OFFSET_MINUTES,
    MAX_OFFSET_TEXT_LENGTH,
    MAX_REMINDER_OFFSETS,
    MAX_TIMEZONE_LENGTH,
    MAX_TITLE_LENGTH,
    MIN_OFFSET_MINUTES,
)

_LOCAL_START = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}\Z")


class MeetingError(Exception):
    """A safe message for the operator. Do not put secrets or driver text here."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class MeetingState(StrEnum):
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"


class JobState(StrEnum):
    SCHEDULED = "scheduled"
    CLAIMED = "claimed"
    DELIVERED = "delivered"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNRECONCILED = "unreconciled"


class ChannelKind(StrEnum):
    TEXT = "text"
    VOICE = "voice"
    OTHER = "other"


# Occurrences in these states are not scheduled again for the same due instant.
FINAL_JOB_STATES = frozenset(
    {
        JobState.DELIVERED,
        JobState.SKIPPED,
        JobState.FAILED,
        JobState.UNRECONCILED,
    }
)


def as_utc(value: datetime) -> datetime:
    """Convert an aware timestamp to UTC. Naive values are rejected."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise MeetingError("Meeting times must be timezone-aware UTC instants.")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class ChannelFacts:
    """What the meeting rules need to know about a Discord channel."""

    channel_id: int
    guild_id: int
    kind: ChannelKind
    can_view: bool
    can_send: bool


@dataclass(frozen=True)
class JobRecord:
    """One stored reminder occurrence."""

    id: int
    meeting_id: int
    offset_minutes: int
    due_at: datetime
    state: JobState
    attempt_count: int
    retry_at: datetime | None
    claim_token: str | None
    delivery_receipt: str | None
    failure_category: str | None


@dataclass(frozen=True)
class MeetingRecord:
    """A stored meeting and its reminder history."""

    id: int
    guild_id: int
    title: str
    text_channel_id: int
    voice_channel_id: int
    starts_at: datetime
    timezone_name: str
    organizer_id: int
    state: MeetingState
    created_at: datetime
    updated_at: datetime
    jobs: tuple[JobRecord, ...]


@dataclass(frozen=True)
class PlannedReminder:
    offset_minutes: int
    due_at: datetime


@dataclass(frozen=True)
class PlannedMeeting:
    title: str
    starts_at: datetime
    timezone_name: str
    reminders: tuple[PlannedReminder, ...]


@dataclass(frozen=True)
class NewMeeting:
    guild_id: int
    title: str
    text_channel_id: int
    voice_channel_id: int
    starts_at: datetime
    timezone_name: str
    organizer_id: int
    created_at: datetime


@dataclass(frozen=True)
class NewJob:
    offset_minutes: int
    due_at: datetime


@dataclass(frozen=True)
class JobRewrite:
    cancel_ids: tuple[int, ...]
    new_jobs: tuple[NewJob, ...]


@dataclass(frozen=True)
class MeetingWrite:
    title: str
    text_channel_id: int
    voice_channel_id: int
    starts_at: datetime
    timezone_name: str
    updated_at: datetime
    replace_jobs: bool
    rewrite: JobRewrite


@dataclass(frozen=True)
class ClaimedReminder:
    """Snapshot taken when a worker claims a job, before Discord is called."""

    job_id: int
    claim_token: str
    attempt_count: int
    meeting_id: int
    guild_id: int
    title: str
    text_channel_id: int
    voice_channel_id: int
    starts_at: datetime
    timezone_name: str
    offset_minutes: int
    meeting_state: MeetingState


@dataclass(frozen=True)
class MeetingList:
    meetings: tuple[MeetingRecord, ...]
    truncated: bool


def parse_title(value: str) -> str:
    """Collapse whitespace and reject empty or oversized titles."""
    title = " ".join(value.split())
    if not title or len(title) > MAX_TITLE_LENGTH:
        raise MeetingError("Provide a meeting title up to 100 characters.")
    if any(ord(char) < 32 for char in title):
        raise MeetingError("The meeting title contains unsupported characters.")
    return title


def parse_offsets(value: str) -> tuple[int, ...]:
    """Parse comma-separated positive minute offsets. Order does not matter."""
    text = value.strip()
    if not text or len(text) > MAX_OFFSET_TEXT_LENGTH:
        raise MeetingError(
            "Provide reminder offsets as comma-separated minutes, for example 1440,60,15."
        )
    parts = [part.strip() for part in text.split(",")]
    if any(not part.isdigit() for part in parts):
        raise MeetingError(
            "Reminder offsets must be positive whole minutes, for example 1440,60,15."
        )
    offsets = tuple(int(part) for part in parts)
    if len(offsets) > MAX_REMINDER_OFFSETS:
        raise MeetingError("Provide at most 5 reminder offsets.")
    if len(set(offsets)) != len(offsets):
        raise MeetingError("Reminder offsets must be unique.")
    for offset in offsets:
        if offset < MIN_OFFSET_MINUTES or offset > MAX_OFFSET_MINUTES:
            raise MeetingError("Each reminder offset must be from 1 to 10080 minutes (7 days).")
    return offsets


def parse_local_start(value: str) -> datetime:
    """Parse a naive local wall time. The IANA zone is supplied separately."""
    text = value.strip()
    if _LOCAL_START.fullmatch(text) is None:
        raise MeetingError("Use the start format YYYY-MM-DD HH:MM.")
    normalized = text.replace("T", " ")
    try:
        return datetime.strptime(normalized, "%Y-%m-%d %H:%M")
    except ValueError:
        raise MeetingError("Use the start format YYYY-MM-DD HH:MM.") from None


def resolve_local_start(naive: datetime, timezone_name: str) -> datetime:
    """Convert one local wall time to UTC.

    Both folds are checked. A gap (spring forward) and an overlap (fall back)
    are rejected so the bot does not guess which instant the operator meant.
    """
    if naive.tzinfo is not None:
        raise MeetingError(
            "Provide the start time without an offset; pass the time zone separately."
        )
    if not timezone_name or len(timezone_name) > MAX_TIMEZONE_LENGTH:
        raise MeetingError("Use an IANA time zone such as America/Los_Angeles.")
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise MeetingError("Use an IANA time zone such as America/Los_Angeles.") from None

    first_utc = naive.replace(tzinfo=zone, fold=0).astimezone(UTC)
    second_utc = naive.replace(tzinfo=zone, fold=1).astimezone(UTC)
    first_matches = first_utc.astimezone(zone).replace(tzinfo=None) == naive
    second_matches = second_utc.astimezone(zone).replace(tzinfo=None) == naive
    if first_matches and second_matches and first_utc != second_utc:
        raise MeetingError(
            "That local time happens twice because clocks fall back. "
            "Choose a time outside the overlap."
        )
    if not first_matches or not second_matches or first_utc != second_utc:
        raise MeetingError("That local time does not exist because clocks spring forward.")
    return first_utc


def plan_meeting(
    *,
    now: datetime,
    title: str,
    start_text: str,
    timezone_name: str,
    offsets_text: str,
) -> PlannedMeeting:
    """Validate a new schedule against an injected current instant."""
    current = as_utc(now)
    parsed_title = parse_title(title)
    starts_at = resolve_local_start(parse_local_start(start_text), timezone_name)
    if starts_at <= current:
        raise MeetingError("The meeting start must be in the future.")
    reminders: list[PlannedReminder] = []
    for offset in parse_offsets(offsets_text):
        due_at = starts_at - timedelta(minutes=offset)
        if due_at <= current:
            raise MeetingError(
                f"The {offset}-minute reminder would already be due. "
                "Choose a later start or a shorter offset."
            )
        reminders.append(PlannedReminder(offset_minutes=offset, due_at=due_at))
    reminders.sort(key=lambda item: (item.due_at, item.offset_minutes))
    return PlannedMeeting(
        title=parsed_title,
        starts_at=starts_at,
        timezone_name=timezone_name,
        reminders=tuple(reminders),
    )


def require_text_channel(facts: ChannelFacts | None, guild_id: int) -> ChannelFacts:
    if (
        facts is None
        or facts.guild_id != guild_id
        or facts.kind is not ChannelKind.TEXT
        or not facts.can_view
        or not facts.can_send
    ):
        raise MeetingError(
            "Choose a text channel in this server that the bot can view and send messages in."
        )
    return facts


def require_voice_channel(facts: ChannelFacts | None, guild_id: int) -> ChannelFacts:
    if (
        facts is None
        or facts.guild_id != guild_id
        or facts.kind is not ChannelKind.VOICE
        or not facts.can_view
    ):
        raise MeetingError("Choose a voice channel in this server that the bot can view.")
    return facts


def require_distinct_channels(text_channel_id: int, voice_channel_id: int) -> None:
    if text_channel_id == voice_channel_id:
        raise MeetingError("Choose different text and voice channels.")


def active_offsets(jobs: Sequence[JobRecord]) -> tuple[int, ...]:
    """Offsets still associated with the meeting, ignoring cancelled rows."""
    return tuple(
        sorted({job.offset_minutes for job in jobs if job.state is not JobState.CANCELLED})
    )


def rewrite_jobs(existing: Sequence[JobRecord], planned: Sequence[PlannedReminder]) -> JobRewrite:
    """Cancel pending reminders and add occurrences that have not already finished.

    Delivered, skipped, failed, and unreconciled rows for the same due instant stay
    in place so a schedule refresh does not send them again.
    """
    finished = {
        (job.offset_minutes, as_utc(job.due_at))
        for job in existing
        if job.state in FINAL_JOB_STATES
    }
    cancel_ids = tuple(job.id for job in existing if job.state is JobState.SCHEDULED)
    new_jobs = tuple(
        NewJob(offset_minutes=item.offset_minutes, due_at=as_utc(item.due_at))
        for item in planned
        if (item.offset_minutes, as_utc(item.due_at)) not in finished
    )
    return JobRewrite(cancel_ids=cancel_ids, new_jobs=new_jobs)
