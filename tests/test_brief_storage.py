"""PostgreSQL durability for brief jobs, recovery, and migration 0003."""

import asyncio
import os
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, ProgrammingError

from jdr_bot.brief import BriefRefresh, NewBriefJob
from jdr_bot.brief_scheduler import BriefScheduler
from jdr_bot.brief_service import BriefService
from jdr_bot.brief_storage import SqlBriefStore
from jdr_bot.domain import JobState
from jdr_bot.ports import BriefQueryError, JiraIssue, JiraPage, PartialDelivery
from jdr_bot.storage import create_engine
from tests.brief_fakes import FakeBriefDelivery, FakeJira, utc_schedule
from tests.support import FakeClock

UTC_TZ = UTC


async def migrate(url: str, direction: str = "upgrade", revision: str = "head") -> None:
    environment = {**os.environ, "DATABASE_URL": url}
    process = await asyncio.create_subprocess_exec("alembic", direction, revision, env=environment)
    assert await process.wait() == 0


async def disposable_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL to a disposable PostgreSQL database ending in _test")
    assert (make_url(url).database or "").endswith("_test"), "refusing a non-test database"
    await migrate(url)
    engine = create_engine(url)
    await clear_rows(engine)
    return url, engine


async def clear_rows(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM brief_jobs"))
        await connection.execute(text("DELETE FROM reminder_jobs"))
        await connection.execute(text("DELETE FROM meetings"))
        await connection.execute(text("DELETE FROM guild_configurations"))


@pytest.mark.integration
async def test_postgres_same_day_brief_survives_a_new_store():
    url, engine = await disposable_engine()
    del url
    try:
        clock = FakeClock(datetime(2026, 3, 9, 15, 59, tzinfo=UTC_TZ))
        schedule = utc_schedule(timezone_name="America/Los_Angeles")
        delivery = FakeBriefDelivery()
        reader = FakeJira(
            pages=[
                JiraPage(
                    issues=(JiraIssue("JDR-9", "Ship the brief", "In Progress", None),),
                    next_page_token=None,
                    is_last=True,
                )
            ]
        )
        store = SqlBriefStore(engine)
        scheduler = BriefScheduler(store, delivery, BriefService(reader, schedule), clock, schedule)
        await scheduler.run_once()
        assert delivery.sent == []
        clock.set(datetime(2026, 3, 9, 16, tzinfo=UTC_TZ))
        await BriefScheduler(
            SqlBriefStore(engine), delivery, BriefService(reader, schedule), clock, schedule
        ).run_once()
        assert len(delivery.sent) == 1
        assert "unassigned" in delivery.sent[0][0]
        saved = await SqlBriefStore(engine).list_relevant(123, date(2026, 3, 9))
        delivered = next(job for job in saved if job.state is JobState.DELIVERED)
        assert delivered.due_at == datetime(2026, 3, 9, 16, tzinfo=UTC_TZ)
        assert delivered.due_at.tzinfo is not None
        assert delivered.issue_count == 1
        assert delivered.delivery_receipt
        await BriefScheduler(
            SqlBriefStore(engine), delivery, BriefService(reader, schedule), clock, schedule
        ).run_once()
        assert len(delivery.sent) == 1
    finally:
        await clear_rows(engine)
        await engine.dispose()


@pytest.mark.integration
async def test_postgres_brief_constraints_and_downgrade():
    url, engine = await disposable_engine()
    try:
        clock = FakeClock(datetime(2026, 6, 6, 12, tzinfo=UTC_TZ))
        schedule = utc_schedule()
        delivery = FakeBriefDelivery()
        await BriefScheduler(
            SqlBriefStore(engine),
            delivery,
            BriefService(FakeJira(), schedule),
            clock,
            schedule,
        ).run_once()
        assert delivery.sent == []
        rows = await SqlBriefStore(engine).list_relevant(123, date(2026, 6, 6))
        assert [row.local_date for row in rows] == [date(2026, 6, 8)]
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO brief_jobs (guild_id, channel_id, local_date, due_at, "
                        "timezone, state, attempt_count) VALUES (123, 10, :local_date, now(), "
                        "'UTC', 'scheduled', 0)"
                    ),
                    {"local_date": date(2026, 6, 8)},
                )
        await migrate(url, "downgrade", "0002")
        with pytest.raises(ProgrammingError):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT * FROM brief_jobs"))
        async with engine.connect() as connection:
            await connection.execute(text("SELECT id FROM meetings"))
    finally:
        await migrate(url, "upgrade", "head")
        await clear_rows(engine)
        await engine.dispose()


@pytest.mark.integration
async def test_postgres_retry_waits_and_covers_unreconcile_and_partial():
    url, engine = await disposable_engine()
    del url
    try:
        clock = FakeClock(datetime(2026, 6, 1, 9, tzinfo=UTC_TZ))
        schedule = utc_schedule()
        delivery = FakeBriefDelivery()
        reader = FakeJira(
            pages=[
                JiraPage(
                    issues=(JiraIssue("JDR-1", "Ship the brief", "In Progress", "Ada"),),
                    next_page_token=None,
                    is_last=True,
                )
            ],
            errors=[BriefQueryError("rate_limited", transient=True)],
        )
        await BriefScheduler(
            SqlBriefStore(engine), delivery, BriefService(reader, schedule), clock, schedule
        ).run_once()
        assert delivery.sent == []
        clock.advance(seconds=5)
        await BriefScheduler(
            SqlBriefStore(engine), delivery, BriefService(reader, schedule), clock, schedule
        ).run_once()
        waiting = await SqlBriefStore(engine).list_relevant(123, date(2026, 6, 1))
        assert delivery.sent == []
        assert waiting[0].state is JobState.SCHEDULED
        assert waiting[0].attempt_count == 1
        assert waiting[0].failure_category == "rate_limited"
        clock.advance(seconds=10)
        await BriefScheduler(
            SqlBriefStore(engine), delivery, BriefService(reader, schedule), clock, schedule
        ).run_once()
        assert len(delivery.sent) == 1

        await clear_rows(engine)
        clock = FakeClock(datetime(2026, 6, 2, 9, tzinfo=UTC_TZ))
        lost = FakeBriefDelivery()

        class LoseReceipt(SqlBriefStore):
            def __init__(self) -> None:
                super().__init__(engine)
                self.failed = False

            async def mark_delivered(
                self, job_id: int, claim_token: str, receipt: str, issue_count: int
            ) -> bool:
                if not self.failed:
                    self.failed = True
                    raise RuntimeError("synthetic-disk")
                return await super().mark_delivered(job_id, claim_token, receipt, issue_count)

        lost_reader = FakeJira(
            pages=[
                JiraPage(
                    issues=(JiraIssue("JDR-2", "Ship the brief", "In Progress", "Ada"),),
                    next_page_token=None,
                    is_last=True,
                )
            ]
        )
        await BriefScheduler(
            LoseReceipt(), lost, BriefService(lost_reader, schedule), clock, schedule
        ).run_once()
        assert len(lost.sent) == 1
        await BriefScheduler(
            SqlBriefStore(engine), lost, BriefService(lost_reader, schedule), clock, schedule
        ).run_once()
        rows = await SqlBriefStore(engine).list_relevant(123, date(2026, 6, 2))
        original = next(row for row in rows if row.local_date == date(2026, 6, 2))
        assert original.state is JobState.UNRECONCILED
        assert original.failure_category == "receipt_unknown"
        assert len(lost.sent) == 1

        await clear_rows(engine)
        clock = FakeClock(datetime(2026, 6, 3, 9, tzinfo=UTC_TZ))
        partial = FakeBriefDelivery()
        partial.failures = [PartialDelivery("msg-partial")]
        partial_reader = FakeJira(
            pages=[
                JiraPage(
                    issues=(JiraIssue("JDR-3", "Ship the brief", "In Progress", "Ada"),),
                    next_page_token=None,
                    is_last=True,
                )
            ]
        )
        await BriefScheduler(
            SqlBriefStore(engine),
            partial,
            BriefService(partial_reader, schedule),
            clock,
            schedule,
        ).run_once()
        failed = await SqlBriefStore(engine).list_relevant(123, date(2026, 6, 3))
        assert failed[0].state is JobState.FAILED
        assert failed[0].failure_category == "partial_delivery"
        assert failed[0].delivery_receipt == "msg-partial"
        await BriefScheduler(
            SqlBriefStore(engine),
            partial,
            BriefService(partial_reader, schedule),
            clock,
            schedule,
        ).run_once()
        assert partial.sent == []
    finally:
        await clear_rows(engine)
        await engine.dispose()


@pytest.mark.integration
async def test_postgres_cancel_during_read_releases_the_claim():
    url, engine = await disposable_engine()
    del url
    try:
        clock = FakeClock(datetime(2026, 6, 4, 9, tzinfo=UTC_TZ))
        schedule = utc_schedule()

        class Hang(FakeJira):
            def __init__(self) -> None:
                super().__init__()
                self.started = asyncio.Event()

            async def search(self, request):
                self.requests.append(request)
                self.started.set()
                await asyncio.Event().wait()
                return JiraPage(issues=(), next_page_token=None, is_last=True)

        reader = Hang()
        delivery = FakeBriefDelivery()
        task = asyncio.create_task(
            BriefScheduler(
                SqlBriefStore(engine), delivery, BriefService(reader, schedule), clock, schedule
            ).run_once()
        )
        await reader.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        released = await SqlBriefStore(engine).list_relevant(123, date(2026, 6, 4))
        assert released[0].state is JobState.SCHEDULED
        assert released[0].attempt_count == 0
        assert released[0].claim_token is None
        follow = FakeJira(
            pages=[
                JiraPage(
                    issues=(JiraIssue("JDR-4", "Ship the brief", "In Progress", None),),
                    next_page_token=None,
                    is_last=True,
                )
            ]
        )
        await BriefScheduler(
            SqlBriefStore(engine), delivery, BriefService(follow, schedule), clock, schedule
        ).run_once()
        assert len(delivery.sent) == 1
        assert "unassigned" in delivery.sent[0][0]
    finally:
        await clear_rows(engine)
        await engine.dispose()


@pytest.mark.integration
async def test_postgres_refresh_leaves_claimed_rows_and_retry_due_instants():
    url, engine = await disposable_engine()
    del url
    try:
        store = SqlBriefStore(engine)
        claimed_due = datetime(2026, 6, 1, 9, tzinfo=UTC_TZ)
        retry_due = datetime(2026, 6, 2, 9, tzinfo=UTC_TZ)
        retry_wait = datetime(2026, 6, 2, 9, 5, tzinfo=UTC_TZ)
        fresh_due = datetime(2026, 6, 3, 9, tzinfo=UTC_TZ)
        claimed_id = await store.insert_job(
            NewBriefJob(
                guild_id=123,
                channel_id=10,
                local_date=date(2026, 6, 1),
                due_at=claimed_due,
                timezone_name="UTC",
                state=JobState.SCHEDULED,
                failure_category=None,
            )
        )
        retry_id = await store.insert_job(
            NewBriefJob(
                guild_id=123,
                channel_id=10,
                local_date=date(2026, 6, 2),
                due_at=retry_due,
                timezone_name="UTC",
                state=JobState.SCHEDULED,
                failure_category=None,
            )
        )
        fresh_id = await store.insert_job(
            NewBriefJob(
                guild_id=123,
                channel_id=10,
                local_date=date(2026, 6, 3),
                due_at=fresh_due,
                timezone_name="UTC",
                state=JobState.SCHEDULED,
                failure_category=None,
            )
        )
        assert claimed_id is not None
        assert retry_id is not None
        assert fresh_id is not None
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE brief_jobs SET state = 'claimed', attempt_count = 1, "
                    "claim_token = 'claim-token' WHERE id = :job_id"
                ),
                {"job_id": claimed_id},
            )
            await connection.execute(
                text(
                    "UPDATE brief_jobs SET attempt_count = 1, retry_at = :retry_at, "
                    "failure_category = 'rate_limited' WHERE id = :job_id"
                ),
                {"job_id": retry_id, "retry_at": retry_wait},
            )
        claimed_refresh = BriefRefresh(
            job_id=claimed_id,
            channel_id=20,
            due_at=datetime(2026, 6, 1, 8, tzinfo=UTC_TZ),
            timezone_name="America/Los_Angeles",
            state=JobState.SCHEDULED,
            failure_category=None,
        )
        retry_refresh = BriefRefresh(
            job_id=retry_id,
            channel_id=20,
            due_at=datetime(2026, 6, 2, 11, tzinfo=UTC_TZ),
            timezone_name="America/Los_Angeles",
            state=JobState.SCHEDULED,
            failure_category=None,
        )
        fresh_refresh = BriefRefresh(
            job_id=fresh_id,
            channel_id=22,
            due_at=datetime(2026, 6, 3, 10, 30, tzinfo=UTC_TZ),
            timezone_name="America/Los_Angeles",
            state=JobState.SCHEDULED,
            failure_category=None,
        )
        assert await store.apply_refresh(claimed_refresh) is False
        assert await store.redirect_channel(claimed_id, 20) is False
        assert await store.apply_refresh(retry_refresh) is False
        assert await store.redirect_channel(retry_id, 21) is True
        assert await store.apply_refresh(fresh_refresh) is True
        rows = {row.id: row for row in await store.list_relevant(123, date(2026, 6, 1))}
        claimed = rows[claimed_id]
        assert claimed.state is JobState.CLAIMED
        assert claimed.channel_id == 10
        assert claimed.due_at == claimed_due
        assert claimed.attempt_count == 1
        assert claimed.claim_token == "claim-token"
        assert claimed.timezone_name == "UTC"
        retry = rows[retry_id]
        assert retry.state is JobState.SCHEDULED
        assert retry.channel_id == 21
        assert retry.due_at == retry_due
        assert retry.retry_at == retry_wait
        assert retry.attempt_count == 1
        assert retry.failure_category == "rate_limited"
        assert retry.timezone_name == "UTC"
        fresh = rows[fresh_id]
        assert fresh.state is JobState.SCHEDULED
        assert fresh.channel_id == 22
        assert fresh.due_at == datetime(2026, 6, 3, 10, 30, tzinfo=UTC_TZ)
        assert fresh.timezone_name == "America/Los_Angeles"
        assert fresh.attempt_count == 0
        assert fresh.retry_at is None
    finally:
        await clear_rows(engine)
        await engine.dispose()
