"""Brief delivery, recovery, and failure handling with a fake clock."""

import logging
from datetime import UTC, date, datetime

import pytest

from jdr_bot.brief import EMPTY_BRIEF_LINE, NewBriefJob
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
