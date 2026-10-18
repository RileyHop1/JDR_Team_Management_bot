"""In-memory meeting store and fakes. The store mirrors SqlMeetingStore's job rules."""

from datetime import datetime, timedelta
from uuid import uuid4

from jdr_bot.domain import (
    ChannelFacts,
    ChannelKind,
    ClaimedReminder,
    JobRecord,
    JobState,
    MeetingRecord,
    MeetingState,
    MeetingWrite,
    NewJob,
    NewMeeting,
    as_utc,
)
from jdr_bot.ports import (
    DeliveryError,
    DeliveryReceipt,
    MeetingConflict,
    MeetingNotEditable,
    MeetingNotFound,
    ReminderInProgress,
    ReminderNotice,
)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.current = as_utc(now)

    def now(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int = 0, minutes: int = 0) -> None:
        self.current += timedelta(seconds=seconds, minutes=minutes)

    def set(self, now: datetime) -> None:
        self.current = as_utc(now)


class StaticChannels:
    def __init__(self, channels: dict[int, ChannelFacts]) -> None:
        self.channels = channels

    async def describe_channel(self, guild_id: int, channel_id: int) -> ChannelFacts | None:
        del guild_id
        return self.channels.get(channel_id)


class FakeDelivery:
    def __init__(self) -> None:
        self.sent: list[ReminderNotice] = []
        self.failures: list[DeliveryError] = []

    async def send_reminder(self, notice: ReminderNotice) -> DeliveryReceipt:
        if self.failures:
            raise self.failures.pop(0)
        self.sent.append(notice)
        return DeliveryReceipt(message_id=f"msg-{notice.job_id}-{len(self.sent)}")


def team_channels(guild_id: int = 123) -> StaticChannels:
    return StaticChannels(
        {
            10: ChannelFacts(
                channel_id=10,
                guild_id=guild_id,
                kind=ChannelKind.TEXT,
                can_view=True,
                can_send=True,
            ),
            11: ChannelFacts(
                channel_id=11,
                guild_id=guild_id,
                kind=ChannelKind.VOICE,
                can_view=True,
                can_send=False,
            ),
        }
    )


class _Job:
    def __init__(self, job_id: int, meeting_id: int, draft: NewJob) -> None:
        self.id = job_id
        self.meeting_id = meeting_id
        self.offset_minutes = draft.offset_minutes
        self.due_at = as_utc(draft.due_at)
        self.state = JobState.SCHEDULED
        self.attempt_count = 0
        self.retry_at: datetime | None = None
        self.claim_token: str | None = None
        self.claimed_at: datetime | None = None
        self.delivery_receipt: str | None = None
        self.failure_category: str | None = None

    def record(self) -> JobRecord:
        return JobRecord(
            id=self.id,
            meeting_id=self.meeting_id,
            offset_minutes=self.offset_minutes,
            due_at=self.due_at,
            state=self.state,
            attempt_count=self.attempt_count,
            retry_at=self.retry_at,
            claim_token=self.claim_token,
            delivery_receipt=self.delivery_receipt,
            failure_category=self.failure_category,
        )


class _Meeting:
    def __init__(self, meeting_id: int, draft: NewMeeting) -> None:
        created_at = as_utc(draft.created_at)
        self.id = meeting_id
        self.guild_id = draft.guild_id
        self.title = draft.title
        self.text_channel_id = draft.text_channel_id
        self.voice_channel_id = draft.voice_channel_id
        self.starts_at = as_utc(draft.starts_at)
        self.timezone_name = draft.timezone_name
        self.organizer_id = draft.organizer_id
        self.state = MeetingState.SCHEDULED
        self.created_at = created_at
        self.updated_at = created_at

    def record(self, jobs: list[_Job]) -> MeetingRecord:
        ordered = sorted(jobs, key=lambda job: (job.due_at, job.id))
        return MeetingRecord(
            id=self.id,
            guild_id=self.guild_id,
            title=self.title,
            text_channel_id=self.text_channel_id,
            voice_channel_id=self.voice_channel_id,
            starts_at=self.starts_at,
            timezone_name=self.timezone_name,
            organizer_id=self.organizer_id,
            state=self.state,
            created_at=self.created_at,
            updated_at=self.updated_at,
            jobs=tuple(job.record() for job in ordered),
        )


class MemoryMeetingStore:
    """Single-process stand-in for SqlMeetingStore. Mutations do not await."""

    def __init__(self) -> None:
        self.meetings: dict[int, _Meeting] = {}
        self.jobs: dict[int, _Job] = {}
        self._next_id = 1

    def _allocate(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value

    def _jobs_for(self, meeting_id: int) -> list[_Job]:
        return [job for job in self.jobs.values() if job.meeting_id == meeting_id]

    def _check_invariants(self) -> None:
        active: set[tuple[int, int]] = set()
        occurrences: set[tuple[int, int, datetime]] = set()
        for job in self.jobs.values():
            if job.state in {JobState.SCHEDULED, JobState.CLAIMED}:
                key = (job.meeting_id, job.offset_minutes)
                if key in active:
                    raise MeetingConflict
                active.add(key)
            if job.state is not JobState.CANCELLED:
                occurrence = (job.meeting_id, job.offset_minutes, job.due_at)
                if occurrence in occurrences:
                    raise MeetingConflict
                occurrences.add(occurrence)

    async def insert_meeting(
        self, draft: NewMeeting, jobs: list[NewJob] | tuple[NewJob, ...]
    ) -> MeetingRecord:
        meeting_id = self._allocate()
        meeting = _Meeting(meeting_id, draft)
        self.meetings[meeting_id] = meeting
        created = [_Job(self._allocate(), meeting_id, job) for job in jobs]
        for job in created:
            self.jobs[job.id] = job
        self._check_invariants()
        return meeting.record(created)

    async def get_meeting(self, guild_id: int, meeting_id: int) -> MeetingRecord | None:
        meeting = self.meetings.get(meeting_id)
        if meeting is None or meeting.guild_id != guild_id:
            return None
        return meeting.record(self._jobs_for(meeting_id))

    async def list_meetings(
        self, guild_id: int, state: MeetingState | None, limit: int
    ) -> list[MeetingRecord]:
        meetings = [
            meeting
            for meeting in self.meetings.values()
            if meeting.guild_id == guild_id and (state is None or meeting.state is state)
        ]
        meetings.sort(key=lambda meeting: (meeting.starts_at, meeting.id))
        return [meeting.record(self._jobs_for(meeting.id)) for meeting in meetings[:limit]]

    async def update_meeting(
        self, guild_id: int, meeting_id: int, write: MeetingWrite
    ) -> MeetingRecord:
        meeting = self._editable(guild_id, meeting_id)
        jobs = self._jobs_for(meeting_id)
        if write.replace_jobs and any(job.state is JobState.CLAIMED for job in jobs):
            raise ReminderInProgress
        meeting.title = write.title
        meeting.text_channel_id = write.text_channel_id
        meeting.voice_channel_id = write.voice_channel_id
        meeting.starts_at = as_utc(write.starts_at)
        meeting.timezone_name = write.timezone_name
        meeting.updated_at = as_utc(write.updated_at)
        if write.replace_jobs:
            cancel_ids = set(write.rewrite.cancel_ids)
            for job in jobs:
                if job.id in cancel_ids and job.state is JobState.SCHEDULED:
                    job.state = JobState.CANCELLED
                    job.claim_token = None
                    job.retry_at = None
            for draft in write.rewrite.new_jobs:
                job = _Job(self._allocate(), meeting_id, draft)
                self.jobs[job.id] = job
        self._check_invariants()
        return meeting.record(self._jobs_for(meeting_id))

    async def cancel_meeting(
        self, guild_id: int, meeting_id: int, updated_at: datetime
    ) -> MeetingRecord:
        meeting = self._editable(guild_id, meeting_id)
        jobs = self._jobs_for(meeting_id)
        if any(job.state is JobState.CLAIMED for job in jobs):
            raise ReminderInProgress
        meeting.state = MeetingState.CANCELLED
        meeting.updated_at = as_utc(updated_at)
        for job in jobs:
            if job.state is JobState.SCHEDULED:
                job.state = JobState.CANCELLED
                job.claim_token = None
                job.retry_at = None
        return meeting.record(jobs)

    async def skip_missed(self, *, due_before: datetime) -> int:
        cutoff = as_utc(due_before)
        changed = 0
        for job in self.jobs.values():
            if job.state is not JobState.SCHEDULED or job.due_at >= cutoff:
                continue
            if job.attempt_count == 0:
                job.state = JobState.SKIPPED
                job.failure_category = "missed_window"
            else:
                job.state = JobState.FAILED
                if job.failure_category is None:
                    job.failure_category = "retry_window_elapsed"
            job.retry_at = None
            job.claim_token = None
            changed += 1
        return changed

    async def unreconcile_claims(self, *, due_before: datetime) -> int:
        cutoff = as_utc(due_before)
        changed = 0
        for job in self.jobs.values():
            if job.state is not JobState.CLAIMED or job.due_at >= cutoff:
                continue
            job.state = JobState.UNRECONCILED
            job.failure_category = "receipt_unknown"
            job.claim_token = None
            job.claimed_at = None
            job.retry_at = None
            changed += 1
        return changed

    async def claim_due(
        self, *, now: datetime, due_after: datetime, limit: int
    ) -> list[ClaimedReminder]:
        current = as_utc(now)
        earliest = as_utc(due_after)
        candidates = []
        for job in self.jobs.values():
            meeting = self.meetings[job.meeting_id]
            if job.state is not JobState.SCHEDULED or meeting.state is not MeetingState.SCHEDULED:
                continue
            if job.due_at < earliest or job.due_at > current:
                continue
            if job.retry_at is not None and job.retry_at > current:
                continue
            candidates.append(job)
        candidates.sort(key=lambda job: (job.due_at, job.id))
        claimed: list[ClaimedReminder] = []
        for job in candidates[:limit]:
            meeting = self.meetings[job.meeting_id]
            token = uuid4().hex
            job.state = JobState.CLAIMED
            job.claim_token = token
            job.claimed_at = current
            job.attempt_count += 1
            job.retry_at = None
            claimed.append(
                ClaimedReminder(
                    job_id=job.id,
                    claim_token=token,
                    attempt_count=job.attempt_count,
                    meeting_id=meeting.id,
                    guild_id=meeting.guild_id,
                    title=meeting.title,
                    text_channel_id=meeting.text_channel_id,
                    voice_channel_id=meeting.voice_channel_id,
                    starts_at=meeting.starts_at,
                    timezone_name=meeting.timezone_name,
                    offset_minutes=job.offset_minutes,
                    meeting_state=meeting.state,
                )
            )
        return claimed

    async def mark_delivered(self, job_id: int, claim_token: str, receipt: str) -> bool:
        job = self.jobs.get(job_id)
        if job is None or job.claim_token != claim_token or job.state is not JobState.CLAIMED:
            return False
        job.state = JobState.DELIVERED
        job.delivery_receipt = receipt[:64]
        job.claim_token = None
        job.failure_category = None
        return True

    async def mark_claim_cancelled(self, job_id: int, claim_token: str) -> None:
        job = self.jobs.get(job_id)
        if job is None or job.claim_token != claim_token or job.state is not JobState.CLAIMED:
            return
        job.state = JobState.CANCELLED
        job.claim_token = None
        job.retry_at = None

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
        job = self.jobs.get(job_id)
        if job is None or job.claim_token != claim_token or job.state is not JobState.CLAIMED:
            return
        job.claim_token = None
        job.failure_category = category[:64]
        terminal = (not transient) or retry_at is None or job.attempt_count >= max_attempts
        if terminal:
            job.state = JobState.FAILED
            job.retry_at = None
        else:
            job.state = JobState.SCHEDULED
            job.claimed_at = None
            job.retry_at = as_utc(retry_at) if retry_at is not None else None

    def _editable(self, guild_id: int, meeting_id: int) -> _Meeting:
        meeting = self.meetings.get(meeting_id)
        if meeting is None or meeting.guild_id != guild_id:
            raise MeetingNotFound
        if meeting.state is not MeetingState.SCHEDULED:
            raise MeetingNotEditable(meeting.state)
        return meeting


class ReceiptFailureStore:
    """Delegates to a store but fails the first receipt write."""

    def __init__(self, inner: MemoryMeetingStore) -> None:
        self.inner = inner
        self.fail_receipts = 1

    async def mark_delivered(self, job_id: int, claim_token: str, receipt: str) -> bool:
        if self.fail_receipts > 0:
            self.fail_receipts -= 1
            raise RuntimeError("synthetic-token-should-not-be-logged")
        return await self.inner.mark_delivered(job_id, claim_token, receipt)

    def __getattr__(self, name: str) -> object:
        return getattr(self.inner, name)
