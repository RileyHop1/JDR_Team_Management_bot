"""Interfaces for storage, Discord, Jira, and the clock. Implementations are injected."""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from jdr_bot.brief import BriefJobRecord, BriefRefresh, BriefSchedule, ClaimedBrief, NewBriefJob
from jdr_bot.domain import (
    ChannelFacts,
    ClaimedReminder,
    JobState,
    MeetingRecord,
    MeetingState,
    MeetingWrite,
    NewJob,
    NewMeeting,
)


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current timezone-aware UTC instant."""


class SystemClock:
    """Production clock. Tests inject a fake instead of sleeping."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class ChannelDirectory(Protocol):
    async def describe_channel(self, guild_id: int, channel_id: int) -> ChannelFacts | None:
        """Return channel facts, or None when the channel does not exist.

        May raise ChannelDirectoryError. Must not include provider response bodies
        in that error.
        """


class ChannelDirectoryError(Exception):
    """A channel lookup failed. `category` is a short stable label, not a response body."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


class DeliveryReceipt:
    def __init__(self, message_id: str) -> None:
        self.message_id = message_id


class ReminderNotice:
    def __init__(
        self,
        *,
        meeting_id: int,
        job_id: int,
        guild_id: int,
        text_channel_id: int,
        voice_channel_id: int,
        title: str,
        starts_at: datetime,
        timezone_name: str,
        offset_minutes: int,
    ) -> None:
        self.meeting_id = meeting_id
        self.job_id = job_id
        self.guild_id = guild_id
        self.text_channel_id = text_channel_id
        self.voice_channel_id = voice_channel_id
        self.title = title
        self.starts_at = starts_at
        self.timezone_name = timezone_name
        self.offset_minutes = offset_minutes


class ReminderDelivery(Protocol):
    async def send_reminder(self, notice: ReminderNotice) -> DeliveryReceipt:
        """Send one reminder. Raise DeliveryError instead of a provider exception."""


class DeliveryError(Exception):
    """Delivery failed. `category` is safe to store and show to operators."""

    def __init__(self, category: str, *, transient: bool) -> None:
        self.category = category
        self.transient = transient
        super().__init__(category)


class MeetingNotFound(Exception):
    """The meeting id is unknown in this guild."""


class MeetingNotEditable(Exception):
    """The meeting is not in a state that accepts this change."""

    def __init__(self, state: MeetingState) -> None:
        self.state = state
        super().__init__(state.value)


class ReminderInProgress(Exception):
    """A reminder claim is in flight, so the meeting was left unchanged."""


class MeetingConflict(Exception):
    """A database constraint rejected the write. Details stay in the driver."""


class MeetingStore(Protocol):
    async def insert_meeting(self, draft: NewMeeting, jobs: Sequence[NewJob]) -> MeetingRecord:
        """Insert a meeting and its jobs in one transaction."""

    async def get_meeting(self, guild_id: int, meeting_id: int) -> MeetingRecord | None:
        """Return the meeting when it belongs to the guild."""

    async def list_meetings(
        self, guild_id: int, state: MeetingState | None, limit: int
    ) -> Sequence[MeetingRecord]:
        """Return meetings ordered by start time."""

    async def update_meeting(
        self, guild_id: int, meeting_id: int, write: MeetingWrite
    ) -> MeetingRecord:
        """Apply a meeting change. Lock rows so a claim cannot interleave."""

    async def cancel_meeting(
        self, guild_id: int, meeting_id: int, updated_at: datetime
    ) -> MeetingRecord:
        """Cancel the meeting and its scheduled reminders."""

    async def skip_missed(self, *, due_before: datetime) -> int:
        """Mark scheduled jobs due before the cutoff as skipped or failed."""

    async def unreconcile_claims(self, *, due_before: datetime) -> int:
        """Mark stale claims unreconciled without sending them again."""

    async def claim_due(
        self, *, now: datetime, due_after: datetime, limit: int
    ) -> Sequence[ClaimedReminder]:
        """Claim due scheduled jobs whose due time is still inside the window."""

    async def mark_delivered(self, job_id: int, claim_token: str, receipt: str) -> bool:
        """Store a receipt only when the claim token still matches."""

    async def mark_claim_cancelled(self, job_id: int, claim_token: str) -> None:
        """Cancel a claim when the meeting is no longer scheduled."""

    async def record_delivery_failure(
        self,
        job_id: int,
        claim_token: str,
        *,
        category: str,
        transient: bool,
        max_attempts: int,
        retry_at: datetime | None,
    ) -> None:
        """Retry a transient failure or record a terminal failure."""


class ReminderRunner(Protocol):
    async def serve(self) -> None:
        """Poll until cancelled."""


class BriefQueryError(Exception):
    """A Jira read failed. ``category`` is safe to store and show to operators."""

    def __init__(
        self, category: str, *, transient: bool, retry_after: timedelta | None = None
    ) -> None:
        self.category = category
        self.transient = transient
        self.retry_after = retry_after
        super().__init__(category)


class JiraIssue:
    """Fields required for the brief. Descriptions and comments are not read."""

    def __init__(
        self, key: str, summary: str, status_name: str, assignee_display_name: str | None
    ) -> None:
        self.key = key
        self.summary = summary
        self.status_name = status_name
        self.assignee_display_name = assignee_display_name


class JiraPage:
    def __init__(
        self, *, issues: tuple[JiraIssue, ...], next_page_token: str | None, is_last: bool
    ) -> None:
        self.issues = issues
        self.next_page_token = next_page_token
        self.is_last = is_last


class JiraSearchRequest:
    def __init__(
        self, *, jql: str, next_page_token: str | None, max_results: int, fields: tuple[str, ...]
    ) -> None:
        self.jql = jql
        self.next_page_token = next_page_token
        self.max_results = max_results
        self.fields = fields


class JiraReader(Protocol):
    async def search(self, request: JiraSearchRequest) -> JiraPage:
        """Read one search page. Must not create or edit Jira issues."""


class BriefMessage:
    def __init__(self, *, guild_id: int, channel_id: int, parts: tuple[str, ...]) -> None:
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.parts = parts


class PartialDelivery(DeliveryError):
    """An earlier chunk was accepted and a later chunk failed. Do not resend."""

    def __init__(self, message_id: str) -> None:
        super().__init__("partial_delivery", transient=False)
        self.message_id = message_id


class BriefDelivery(Protocol):
    async def send_brief(self, message: BriefMessage) -> DeliveryReceipt:
        """Send every part. Raise DeliveryError instead of a provider exception."""


class BriefScheduleSource(Protocol):
    async def current_schedule(self) -> BriefSchedule | None:
        """Return the schedule for this poll. None skips brief planning and delivery."""


class BriefStore(Protocol):
    async def list_relevant(self, guild_id: int, local_today: date) -> Sequence[BriefJobRecord]:
        """Return open jobs and jobs on or after the local date."""

    async def insert_job(self, draft: NewBriefJob) -> int | None:
        """Insert one occurrence. Return None when that local date already exists."""

    async def apply_skip(self, job_id: int, state: JobState, category: str) -> None:
        """Close a scheduled job that will not be sent."""

    async def unreconcile_claims(self, guild_id: int) -> int:
        """Mark leftover claims unreconciled without sending them again."""

    async def release_claim(self, job_id: int, claim_token: str) -> None:
        """Return a claim to scheduled when no message was sent.

        The attempt is not consumed. A claim that may already have reached Discord
        stays claimed so the next poll can mark it unreconciled instead.
        """

    async def claim_due(
        self, *, guild_id: int, now: datetime, local_today: date, limit: int
    ) -> Sequence[ClaimedBrief]:
        """Claim scheduled jobs that are due on the local date."""

    async def mark_delivered(
        self, job_id: int, claim_token: str, receipt: str, issue_count: int
    ) -> bool:
        """Store a receipt only when the claim token still matches."""

    async def record_failure(
        self,
        job_id: int,
        claim_token: str,
        *,
        category: str,
        transient: bool,
        max_attempts: int,
        retry_at: datetime | None,
        receipt: str | None,
    ) -> None:
        """Retry a transient failure or record a terminal failure."""

    async def apply_refresh(self, refresh: BriefRefresh) -> bool:
        """Update a never-attempted scheduled job. Return False if it was not scheduled."""

    async def redirect_channel(self, job_id: int, channel_id: int) -> bool:
        """Point a scheduled retry at another channel. Leave the due time unchanged."""
