"""In-memory brief store and fakes. The store mirrors SqlBriefStore's job rules."""

from dataclasses import replace
from datetime import date, datetime
from uuid import uuid4

from jdr_bot.brief import BriefJobRecord, BriefRefresh, BriefSchedule, ClaimedBrief, NewBriefJob
from jdr_bot.domain import JobState, as_utc
from jdr_bot.ports import (
    BriefMessage,
    BriefQueryError,
    DeliveryError,
    DeliveryReceipt,
    JiraPage,
    JiraSearchRequest,
)


class MemoryBriefStore:
    """Single-process stand-in. A repeated local date is ignored, not raised."""

    def __init__(self) -> None:
        self.jobs: dict[int, BriefJobRecord] = {}
        self._next_id = 1

    def _allocate(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value

    def only(self) -> BriefJobRecord:
        if len(self.jobs) != 1:
            raise AssertionError(f"expected one brief job, found {len(self.jobs)}")
        return next(iter(self.jobs.values()))

    async def list_relevant(self, guild_id: int, local_today: date) -> list[BriefJobRecord]:
        rows = [
            job
            for job in self.jobs.values()
            if job.guild_id == guild_id
            and (
                job.local_date >= local_today or job.state in {JobState.SCHEDULED, JobState.CLAIMED}
            )
        ]
        return sorted(rows, key=lambda job: (job.local_date, job.id))

    async def insert_job(self, draft: NewBriefJob) -> int | None:
        for job in self.jobs.values():
            if job.guild_id == draft.guild_id and job.local_date == draft.local_date:
                return None
        job_id = self._allocate()
        self.jobs[job_id] = BriefJobRecord(
            id=job_id,
            guild_id=draft.guild_id,
            channel_id=draft.channel_id,
            local_date=draft.local_date,
            due_at=as_utc(draft.due_at),
            timezone_name=draft.timezone_name,
            state=draft.state,
            attempt_count=0,
            retry_at=None,
            claim_token=None,
            delivery_receipt=None,
            failure_category=draft.failure_category,
            issue_count=None,
        )
        return job_id

    async def apply_skip(self, job_id: int, state: JobState, category: str) -> None:
        job = self.jobs.get(job_id)
        if job is None or job.state is not JobState.SCHEDULED:
            return
        self.jobs[job_id] = replace(
            job,
            state=state,
            failure_category=category[:64],
            retry_at=None,
            claim_token=None,
        )

    async def release_claim(self, job_id: int, claim_token: str) -> None:
        job = self.jobs.get(job_id)
        if job is None or job.state is not JobState.CLAIMED or job.claim_token != claim_token:
            return
        attempt_count = job.attempt_count - 1 if job.attempt_count > 0 else 0
        self.jobs[job_id] = replace(
            job,
            state=JobState.SCHEDULED,
            claim_token=None,
            attempt_count=attempt_count,
        )

    async def unreconcile_claims(self, guild_id: int) -> int:
        count = 0
        for job_id, job in list(self.jobs.items()):
            if job.guild_id != guild_id or job.state is not JobState.CLAIMED:
                continue
            self.jobs[job_id] = replace(
                job,
                state=JobState.UNRECONCILED,
                failure_category="receipt_unknown",
                claim_token=None,
                retry_at=None,
            )
            count += 1
        return count

    async def claim_due(
        self, *, guild_id: int, now: datetime, local_today: date, limit: int
    ) -> list[ClaimedBrief]:
        current = as_utc(now)
        eligible = [
            job
            for job in self.jobs.values()
            if job.guild_id == guild_id
            and job.state is JobState.SCHEDULED
            and job.local_date == local_today
            and job.due_at <= current
            and (job.retry_at is None or job.retry_at <= current)
        ]
        eligible.sort(key=lambda job: (job.due_at, job.id))
        claimed: list[ClaimedBrief] = []
        for job in eligible[:limit]:
            token = uuid4().hex
            updated = replace(
                job,
                state=JobState.CLAIMED,
                claim_token=token,
                attempt_count=job.attempt_count + 1,
                retry_at=None,
            )
            self.jobs[job.id] = updated
            claimed.append(
                ClaimedBrief(
                    job_id=updated.id,
                    claim_token=token,
                    attempt_count=updated.attempt_count,
                    guild_id=updated.guild_id,
                    channel_id=updated.channel_id,
                    local_date=updated.local_date,
                    due_at=updated.due_at,
                    timezone_name=updated.timezone_name,
                )
            )
        return claimed

    async def mark_delivered(
        self, job_id: int, claim_token: str, receipt: str, issue_count: int
    ) -> bool:
        job = self.jobs.get(job_id)
        if job is None or job.state is not JobState.CLAIMED or job.claim_token != claim_token:
            return False
        self.jobs[job_id] = replace(
            job,
            state=JobState.DELIVERED,
            delivery_receipt=receipt[:64],
            issue_count=issue_count,
            claim_token=None,
            failure_category=None,
        )
        return True

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
        job = self.jobs.get(job_id)
        if job is None or job.state is not JobState.CLAIMED or job.claim_token != claim_token:
            return
        terminal = (not transient) or retry_at is None or job.attempt_count >= max_attempts
        self.jobs[job_id] = replace(
            job,
            state=JobState.FAILED if terminal else JobState.SCHEDULED,
            failure_category=category[:64],
            claim_token=None,
            retry_at=None if terminal or retry_at is None else as_utc(retry_at),
            delivery_receipt=job.delivery_receipt if receipt is None else receipt[:64],
        )

    async def apply_refresh(self, refresh: BriefRefresh) -> bool:
        job = self.jobs.get(refresh.job_id)
        if job is None or job.state is not JobState.SCHEDULED or job.attempt_count != 0:
            return False
        failure = None if refresh.failure_category is None else refresh.failure_category[:64]
        self.jobs[refresh.job_id] = replace(
            job,
            channel_id=refresh.channel_id,
            due_at=as_utc(refresh.due_at),
            timezone_name=refresh.timezone_name,
            state=refresh.state,
            failure_category=failure,
            retry_at=None if refresh.state is JobState.SKIPPED else job.retry_at,
            claim_token=None if refresh.state is JobState.SKIPPED else job.claim_token,
        )
        return True

    async def redirect_channel(self, job_id: int, channel_id: int) -> bool:
        job = self.jobs.get(job_id)
        if job is None or job.state is not JobState.SCHEDULED or job.attempt_count <= 0:
            return False
        if job.channel_id == channel_id:
            return False
        self.jobs[job_id] = replace(job, channel_id=channel_id)
        return True


class FakeJira:
    def __init__(
        self, pages: list[JiraPage] | None = None, errors: list[BriefQueryError] | None = None
    ) -> None:
        self.pages = list(pages or [])
        self.errors = list(errors or [])
        self.requests: list[JiraSearchRequest] = []

    async def search(self, request: JiraSearchRequest) -> JiraPage:
        self.requests.append(request)
        if self.errors:
            raise self.errors.pop(0)
        if len(self.pages) > 1:
            return self.pages.pop(0)
        if self.pages:
            return self.pages[0]
        return JiraPage(issues=(), next_page_token=None, is_last=True)


class FakeBriefDelivery:
    def __init__(self) -> None:
        self.sent: list[tuple[str, ...]] = []
        self.failures: list[DeliveryError] = []

    async def send_brief(self, message: BriefMessage) -> DeliveryReceipt:
        if self.failures:
            raise self.failures.pop(0)
        self.sent.append(message.parts)
        return DeliveryReceipt(message_id=f"brief-{len(self.sent)}")


def utc_schedule(
    *,
    guild_id: int = 123,
    channel_id: int = 10,
    timezone_name: str = "UTC",
    hour: int = 9,
    minute: int = 0,
    project_key: str = "JDR",
    browse_base_url: str = "https://example.atlassian.net",
    jql: str = 'project = "JDR" AND status IN ("In Progress") ORDER BY key ASC',
    status_names: tuple[str, ...] | None = ("In Progress",),
    weekdays_only: bool = True,
) -> BriefSchedule:
    return BriefSchedule(
        guild_id=guild_id,
        channel_id=channel_id,
        timezone_name=timezone_name,
        hour=hour,
        minute=minute,
        project_key=project_key,
        browse_base_url=browse_base_url,
        jql=jql,
        status_names=status_names,
        weekdays_only=weekdays_only,
    )
