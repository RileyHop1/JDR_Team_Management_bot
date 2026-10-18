"""Interfaces for storage, Discord, and the clock. Implementations are injected."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

from jdr_bot.domain import (
    ChannelFacts,
    ClaimedReminder,
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
