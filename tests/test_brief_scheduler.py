"""Brief delivery, recovery, and failure handling with a fake clock."""

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from jdr_bot.brief import EMPTY_BRIEF_LINE, BriefSchedule, NewBriefJob
from jdr_bot.brief_scheduler import BriefScheduler
from jdr_bot.brief_service import BriefService
from jdr_bot.domain import JobState
from jdr_bot.ports import BriefQueryError, DeliveryError, JiraIssue, JiraPage, PartialDelivery
from tests.brief_fakes import FakeBriefDelivery, FakeJira, MemoryBriefStore, utc_schedule
from tests.support import FakeClock

UTC_TZ = UTC


def issue(key: str = "JDR-1", summary: str = "synthetic-secret-title") -> JiraIssue:
    return JiraIssue(key, summary, "In Progress", "Ada Lovelace")


def page(*keys: str, summary: str = "synthetic-secret-title") -> JiraPage:
    chosen = keys or ("JDR-1",)
    return JiraPage(
        issues=tuple(issue(key, summary) for key in chosen),
        next_page_token=None,
        is_last=True,
    )


def scheduler(
    store: MemoryBriefStore,
    clock: FakeClock,
    reader: FakeJira,
    delivery: FakeBriefDelivery,
    **schedule_overrides: object,
):
    schedule = utc_schedule(**schedule_overrides) if schedule_overrides else utc_schedule()
    return BriefScheduler(store, delivery, BriefService(reader, schedule), clock, schedule)


async def test_future_brief_is_not_sent_and_same_day_recovery_sends_once(
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO)
    clock = FakeClock(datetime(2026, 6, 1, 8, tzinfo=UTC_TZ))
    store = MemoryBriefStore()
    delivery = FakeBriefDelivery()
    reader = FakeJira(pages=[page()])
    running = scheduler(
        store,
        clock,
        reader,
        delivery,
        jql='project = "JDR" AND summary ~ "hidden-query-text"',
        status_names=None,
    )
    await running.run_once()
    assert delivery.sent == []
    assert store.only().state is JobState.SCHEDULED
    clock.set(datetime(2026, 6, 1, 11, tzinfo=UTC_TZ))
    await BriefScheduler(
        store, delivery, BriefService(reader, running._schedule), clock, running._schedule
    ).run_once()
    assert len(delivery.sent) == 1
    assert "JDR-1" in delivery.sent[0][0]
    assert "hidden-query-text" not in delivery.sent[0][0]
    assert "Using the configured Jira query." in delivery.sent[0][0]
    saved = next(job for job in store.jobs.values() if job.local_date == date(2026, 6, 1))
    assert saved.state is JobState.DELIVERED
    assert saved.issue_count == 1
    await running.run_once()
    assert len(delivery.sent) == 1
    assert "synthetic-secret-title" not in caplog.text
    assert "hidden-query-text" not in caplog.text


async def test_restart_skips_a_missed_day_and_keeps_a_future_weekday():
    clock = FakeClock(datetime(2026, 6, 5, 8, tzinfo=UTC_TZ))
    store = MemoryBriefStore()
    await store.insert_job(
        NewBriefJob(
            guild_id=123,
            channel_id=10,
            local_date=date(2026, 6, 5),
            due_at=datetime(2026, 6, 5, 9, tzinfo=UTC_TZ),
            timezone_name="UTC",
            state=JobState.SCHEDULED,
            failure_category=None,
        )
    )
    clock.set(datetime(2026, 6, 8, 8, tzinfo=UTC_TZ))
    delivery = FakeBriefDelivery()
    await scheduler(store, clock, FakeJira(pages=[page()]), delivery).run_once()
    states = {job.local_date: job.state for job in store.jobs.values()}
    assert states[date(2026, 6, 5)] is JobState.SKIPPED
    assert states[date(2026, 6, 8)] is JobState.SCHEDULED
    assert delivery.sent == []


async def test_weekend_does_not_post_and_monday_is_scheduled():
    clock = FakeClock(datetime(2026, 6, 6, 12, tzinfo=UTC_TZ))
    store = MemoryBriefStore()
    delivery = FakeBriefDelivery()
    await scheduler(store, clock, FakeJira(pages=[page()]), delivery).run_once()
    assert delivery.sent == []
    assert [job.local_date for job in store.jobs.values()] == [date(2026, 6, 8)]


async def test_empty_query_is_delivered_and_access_denial_is_not(
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.ERROR)
    clock = FakeClock(datetime(2026, 6, 1, 9, tzinfo=UTC_TZ))
    empty_store = MemoryBriefStore()
    empty_delivery = FakeBriefDelivery()
    await scheduler(
        empty_store,
        clock,
        FakeJira(pages=[JiraPage(issues=(), next_page_token=None, is_last=True)]),
        empty_delivery,
    ).run_once()
    assert EMPTY_BRIEF_LINE in empty_delivery.sent[0][0]
    assert empty_store.only().state is JobState.DELIVERED
    assert empty_store.only().issue_count == 0

    denied_store = MemoryBriefStore()
    denied_delivery = FakeBriefDelivery()
    await scheduler(
        denied_store,
        clock,
        FakeJira(errors=[BriefQueryError("access_denied", transient=False)]),
        denied_delivery,
    ).run_once()
    assert "could not be loaded (access_denied)" in denied_delivery.sent[0][0]
    assert "JDR-1" not in denied_delivery.sent[0][0]
    assert EMPTY_BRIEF_LINE not in denied_delivery.sent[0][0]
    assert denied_store.only().state is JobState.FAILED
    await scheduler(
        denied_store,
        clock,
        FakeJira(errors=[BriefQueryError("access_denied", transient=False)]),
        denied_delivery,
    ).run_once()
    assert len(denied_delivery.sent) == 1
    assert "secret" not in caplog.text


@pytest.mark.parametrize("category", ["rate_limited", "timeout"])
async def test_transient_query_failure_retries_then_delivers(category: str):
    clock = FakeClock(datetime(2026, 6, 1, 9, 1, tzinfo=UTC_TZ))
    store = MemoryBriefStore()
    delivery = FakeBriefDelivery()
    reader = FakeJira(
        pages=[page()],
        errors=[BriefQueryError(category, transient=True)],
    )
    running = scheduler(store, clock, reader, delivery)
    await running.run_once()
    assert delivery.sent == []
    assert store.only().state is JobState.SCHEDULED
    assert store.only().attempt_count == 1
    clock.advance(seconds=15)
    await running.run_once()
    assert len(delivery.sent) == 1
    assert store.only().state is JobState.DELIVERED


async def test_three_transient_failures_become_terminal_without_issue_text():
    clock = FakeClock(datetime(2026, 6, 1, 9, tzinfo=UTC_TZ))
    store = MemoryBriefStore()
    delivery = FakeBriefDelivery()
    reader = FakeJira(
        errors=[
            BriefQueryError("rate_limited", transient=True),
            BriefQueryError("rate_limited", transient=True),
            BriefQueryError("rate_limited", transient=True),
        ]
    )
    running = scheduler(store, clock, reader, delivery)
    await running.run_once()
    clock.advance(seconds=15)
    await running.run_once()
    clock.advance(seconds=30)
    await running.run_once()
    assert len(delivery.sent) == 1
    assert "could not be loaded (rate_limited)" in delivery.sent[0][0]
    assert store.only().state is JobState.FAILED
    assert store.only().attempt_count == 3


async def test_discord_retry_then_permanent_failure():
    clock = FakeClock(datetime(2026, 6, 1, 9, tzinfo=UTC_TZ))
    store = MemoryBriefStore()
    delivery = FakeBriefDelivery()
    delivery.failures = [DeliveryError("discord_http", transient=True)]
    running = scheduler(store, clock, FakeJira(pages=[page()]), delivery)
    await running.run_once()
    assert delivery.sent == []
    clock.advance(seconds=15)
    await running.run_once()
    assert len(delivery.sent) == 1
    assert store.only().state is JobState.DELIVERED

    denied = FakeBriefDelivery()
    denied.failures = [DeliveryError("channel_forbidden", transient=False)]
    other = MemoryBriefStore()
    await scheduler(other, clock, FakeJira(pages=[page()]), denied).run_once()
    assert denied.sent == []
    assert other.only().state is JobState.FAILED
    assert other.only().failure_category == "channel_forbidden"


async def test_receipt_loss_and_partial_delivery_are_not_resent():
    clock = FakeClock(datetime(2026, 6, 1, 9, tzinfo=UTC_TZ))
    inner = MemoryBriefStore()
    delivery = FakeBriefDelivery()

    class LoseReceipt(MemoryBriefStore):
        def __init__(self) -> None:
            super().__init__()
            self.jobs = inner.jobs
            self._next_id = inner._next_id
            self.failed = False

        async def mark_delivered(
            self, job_id: int, claim_token: str, receipt: str, issue_count: int
        ) -> bool:
            if not self.failed:
                self.failed = True
                raise RuntimeError("synthetic-disk")
            return await inner.mark_delivered(job_id, claim_token, receipt, issue_count)

    losing = LoseReceipt()
    running = scheduler(losing, clock, FakeJira(pages=[page()]), delivery)
    await running.run_once()
    assert len(delivery.sent) == 1
    assert inner.jobs[1].state is JobState.CLAIMED
    await running.run_once()
    assert len(delivery.sent) == 1
    assert inner.jobs[1].state is JobState.UNRECONCILED
    assert inner.jobs[1].failure_category == "receipt_unknown"

    partial_store = MemoryBriefStore()
    partial = FakeBriefDelivery()
    partial.failures = [PartialDelivery("msg-partial")]
    await scheduler(partial_store, clock, FakeJira(pages=[page()]), partial).run_once()
    assert partial.sent == []
    assert partial_store.only().state is JobState.FAILED
    assert partial_store.only().delivery_receipt == "msg-partial"
    await scheduler(partial_store, clock, FakeJira(pages=[page()]), partial).run_once()
    assert partial.sent == []


async def test_gap_day_is_not_delivered():
    clock = FakeClock(datetime(2026, 3, 8, 12, tzinfo=UTC_TZ))
    store = MemoryBriefStore()
    delivery = FakeBriefDelivery()
    await scheduler(
        store,
        clock,
        FakeJira(pages=[page()]),
        delivery,
        timezone_name="America/Los_Angeles",
        hour=2,
        minute=30,
        weekdays_only=False,
    ).run_once()
    assert delivery.sent == []
    states = {job.local_date: (job.state, job.failure_category) for job in store.jobs.values()}
    assert states[date(2026, 3, 8)] == (JobState.SKIPPED, "dst_gap")
    assert states[date(2026, 3, 9)][0] is JobState.SCHEDULED
    assert states[date(2026, 3, 9)][1] is None


async def test_los_angeles_brief_waits_for_the_utc_instant():
    clock = FakeClock(datetime(2026, 3, 9, 15, 59, tzinfo=UTC_TZ))
    store = MemoryBriefStore()
    delivery = FakeBriefDelivery()
    running = scheduler(
        store,
        clock,
        FakeJira(pages=[page("JDR-9")]),
        delivery,
        timezone_name="America/Los_Angeles",
    )
    await running.run_once()
    assert delivery.sent == []
    clock.set(datetime(2026, 3, 9, 16, tzinfo=UTC_TZ))
    await running.run_once()
    assert len(delivery.sent) == 1
    due = next(job.due_at for job in store.jobs.values() if job.state is JobState.DELIVERED)
    assert due == datetime(2026, 3, 9, 16, tzinfo=UTC_TZ)


async def test_poll_before_retry_at_does_not_send():
    clock = FakeClock(datetime(2026, 6, 1, 9, tzinfo=UTC_TZ))
    store = MemoryBriefStore()
    delivery = FakeBriefDelivery()
    reader = FakeJira(
        pages=[page()],
        errors=[BriefQueryError("rate_limited", transient=True)],
    )
    running = scheduler(store, clock, reader, delivery)
    await running.run_once()
    assert delivery.sent == []
    assert store.only().retry_at == datetime(2026, 6, 1, 9, 0, 15, tzinfo=UTC_TZ)
    clock.advance(seconds=5)
    await running.run_once()
    assert delivery.sent == []
    assert store.only().attempt_count == 1
    clock.advance(seconds=10)
    await running.run_once()
    assert len(delivery.sent) == 1
    assert store.only().state is JobState.DELIVERED


async def test_retry_after_extends_the_wait():
    clock = FakeClock(datetime(2026, 6, 1, 9, tzinfo=UTC_TZ))
    store = MemoryBriefStore()
    delivery = FakeBriefDelivery()
    reader = FakeJira(
        pages=[page()],
        errors=[BriefQueryError("rate_limited", transient=True, retry_after=timedelta(seconds=90))],
    )
    running = scheduler(store, clock, reader, delivery)
    await running.run_once()
    clock.advance(seconds=15)
    await running.run_once()
    assert delivery.sent == []
    assert store.only().attempt_count == 1
    assert store.only().failure_category == "rate_limited"
    clock.advance(seconds=75)
    await running.run_once()
    assert len(delivery.sent) == 1


async def test_transient_failure_notice_retries_and_keeps_the_jira_category():
    clock = FakeClock(datetime(2026, 6, 1, 9, tzinfo=UTC_TZ))
    store = MemoryBriefStore()
    delivery = FakeBriefDelivery()
    delivery.failures = [DeliveryError("discord_http", transient=True)]
    reader = FakeJira(
        errors=[
            BriefQueryError("access_denied", transient=False),
            BriefQueryError("access_denied", transient=False),
        ]
    )
    running = scheduler(store, clock, reader, delivery)
    await running.run_once()
    assert delivery.sent == []
    assert store.only().state is JobState.SCHEDULED
    assert store.only().failure_category == "access_denied"
    clock.advance(seconds=5)
    await running.run_once()
    assert delivery.sent == []
    clock.advance(seconds=10)
    await running.run_once()
    assert "could not be loaded (access_denied)" in delivery.sent[0][0]
    assert "discord_http" not in delivery.sent[0][0]
    assert store.only().state is JobState.FAILED
    assert store.only().failure_category == "access_denied"


async def test_permanent_failure_notice_keeps_the_jira_category():
    clock = FakeClock(datetime(2026, 6, 1, 9, tzinfo=UTC_TZ))
    store = MemoryBriefStore()
    delivery = FakeBriefDelivery()
    delivery.failures = [DeliveryError("channel_forbidden", transient=False)]
    await scheduler(
        store,
        clock,
        FakeJira(errors=[BriefQueryError("access_denied", transient=False)]),
        delivery,
    ).run_once()
    assert delivery.sent == []
    assert store.only().state is JobState.FAILED
    assert store.only().failure_category == "access_denied"


async def test_cancel_during_jira_read_releases_the_claim_and_the_day_can_send():
    clock = FakeClock(datetime(2026, 6, 1, 9, tzinfo=UTC_TZ))
    store = MemoryBriefStore()
    delivery = FakeBriefDelivery()

    class Hang(FakeJira):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()

        async def search(self, request):
            self.requests.append(request)
            self.started.set()
            await asyncio.Event().wait()
            return page()

    reader = Hang()
    task = asyncio.create_task(scheduler(store, clock, reader, delivery).run_once())
    await reader.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.only().state is JobState.SCHEDULED
    assert store.only().claim_token is None
    assert store.only().attempt_count == 0
    await scheduler(store, clock, FakeJira(pages=[page()]), delivery).run_once()
    assert len(delivery.sent) == 1
    assert store.only().state is JobState.DELIVERED


async def test_cancel_during_send_keeps_the_claim():
    clock = FakeClock(datetime(2026, 6, 1, 9, tzinfo=UTC_TZ))
    store = MemoryBriefStore()

    class HangSend(FakeBriefDelivery):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()

        async def send_brief(self, message):
            del message
            self.started.set()
            await asyncio.Event().wait()
            raise AssertionError("send should stay cancelled")

    delivery = HangSend()
    task = asyncio.create_task(
        scheduler(store, clock, FakeJira(pages=[page()]), delivery).run_once()
    )
    await delivery.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.only().state is JobState.CLAIMED
    assert delivery.sent == []


class MutableSchedule:
    def __init__(self, schedule: BriefSchedule) -> None:
        self.schedule = schedule

    async def current_schedule(self) -> BriefSchedule | None:
        return self.schedule


def sourced(store, clock, reader, delivery, source: MutableSchedule):
    return BriefScheduler(
        store,
        delivery,
        BriefService(reader, source.schedule),
        clock,
        source.schedule,
        schedule_source=source,
    )


async def test_future_brief_picks_up_a_new_channel_and_time():
    clock = FakeClock(datetime(2026, 6, 1, 8, tzinfo=UTC_TZ))
    store = MemoryBriefStore()
    delivery = FakeBriefDelivery()
    source = MutableSchedule(utc_schedule())
    running = sourced(store, clock, FakeJira(pages=[page()]), delivery, source)
    await running.run_once()
    original = store.only()
    assert original.channel_id == 10
    assert original.due_at == datetime(2026, 6, 1, 9, tzinfo=UTC_TZ)
    source.schedule = utc_schedule(channel_id=20, hour=10, minute=30)
    await running.run_once()
    updated = store.only()
    assert updated.id == original.id
    assert updated.channel_id == 20
    assert updated.due_at == datetime(2026, 6, 1, 10, 30, tzinfo=UTC_TZ)
    assert updated.state is JobState.SCHEDULED
    assert delivery.sent == []
    clock.set(datetime(2026, 6, 1, 10, 30, tzinfo=UTC_TZ))
    await running.run_once()
    assert len(delivery.sent) == 1
    monday = next(job for job in store.jobs.values() if job.local_date == date(2026, 6, 1))
    assert monday.state is JobState.DELIVERED
    assert monday.channel_id == 20
    source.schedule = utc_schedule(channel_id=21, hour=10, minute=30)
    clock.set(datetime(2026, 6, 1, 10, 31, tzinfo=UTC_TZ))
    await running.run_once()
    assert len(delivery.sent) == 1
    monday = next(job for job in store.jobs.values() if job.local_date == date(2026, 6, 1))
    tuesday = next(job for job in store.jobs.values() if job.local_date == date(2026, 6, 2))
    assert monday.channel_id == 20
    assert monday.state is JobState.DELIVERED
    assert tuesday.channel_id == 21
    assert tuesday.state is JobState.SCHEDULED


async def test_retry_moves_channel_and_keeps_the_due_instant():
    clock = FakeClock(datetime(2026, 6, 1, 9, 1, tzinfo=UTC_TZ))
    store = MemoryBriefStore()
    await store.insert_job(
        NewBriefJob(
            guild_id=123,
            channel_id=10,
            local_date=date(2026, 6, 1),
            due_at=datetime(2026, 6, 1, 9, tzinfo=UTC_TZ),
            timezone_name="UTC",
            state=JobState.SCHEDULED,
            failure_category=None,
        )
    )
    job = store.only()
    store.jobs[job.id] = replace(
        job,
        attempt_count=1,
        retry_at=datetime(2026, 6, 1, 9, 5, tzinfo=UTC_TZ),
        failure_category="rate_limited",
    )
    source = MutableSchedule(utc_schedule(channel_id=20, hour=11))
    delivery = FakeBriefDelivery()
    await sourced(store, clock, FakeJira(pages=[page()]), delivery, source).run_once()
    saved = store.only()
    assert saved.channel_id == 20
    assert saved.due_at == datetime(2026, 6, 1, 9, tzinfo=UTC_TZ)
    assert saved.attempt_count == 1
    assert saved.retry_at == datetime(2026, 6, 1, 9, 5, tzinfo=UTC_TZ)
    assert delivery.sent == []


async def test_gap_after_a_time_change_is_not_sent():
    clock = FakeClock(datetime(2026, 3, 8, 12, tzinfo=UTC_TZ))
    store = MemoryBriefStore()
    delivery = FakeBriefDelivery()
    source = MutableSchedule(
        utc_schedule(timezone_name="America/Los_Angeles", hour=9, weekdays_only=False)
    )
    await sourced(store, clock, FakeJira(pages=[page()]), delivery, source).run_once()
    assert store.only().state is JobState.SCHEDULED
    source.schedule = utc_schedule(
        timezone_name="America/Los_Angeles", hour=2, minute=30, weekdays_only=False
    )
    await sourced(store, clock, FakeJira(pages=[page()]), delivery, source).run_once()
    states = {job.local_date: (job.state, job.failure_category) for job in store.jobs.values()}
    assert states[date(2026, 3, 8)] == (JobState.SKIPPED, "dst_gap")
    assert states[date(2026, 3, 9)][0] is JobState.SCHEDULED
    assert delivery.sent == []


async def test_unavailable_schedule_leaves_rows_unchanged(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO)
    clock = FakeClock(datetime(2026, 6, 1, 9, tzinfo=UTC_TZ))
    store = MemoryBriefStore()
    await store.insert_job(
        NewBriefJob(
            guild_id=123,
            channel_id=10,
            local_date=date(2026, 6, 1),
            due_at=datetime(2026, 6, 1, 9, tzinfo=UTC_TZ),
            timezone_name="UTC",
            state=JobState.SCHEDULED,
            failure_category=None,
        )
    )
    job = store.only()
    store.jobs[job.id] = replace(job, state=JobState.CLAIMED, claim_token="claim-token")

    class Unavailable:
        async def current_schedule(self) -> BriefSchedule | None:
            raise RuntimeError("synthetic-secret")

    delivery = FakeBriefDelivery()
    schedule = utc_schedule()
    await BriefScheduler(
        store,
        delivery,
        BriefService(FakeJira(pages=[page()]), schedule),
        clock,
        schedule,
        schedule_source=Unavailable(),
    ).run_once()
    assert delivery.sent == []
    assert store.only().state is JobState.CLAIMED
    assert store.only().channel_id == 10
    assert "synthetic-secret" not in caplog.text
    assert "brief_schedule_lookup_failed" in caplog.text
    assert "brief_schedule_unavailable" in caplog.text
