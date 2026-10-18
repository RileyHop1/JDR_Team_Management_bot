"""PostgreSQL durability for meetings, reminder recovery, and constraints."""

import asyncio
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from jdr_bot.domain import JobState, MeetingState
from jdr_bot.meeting_service import MeetingService
from jdr_bot.reminder_scheduler import ReminderScheduler
from jdr_bot.storage import SqlMeetingStore, create_engine
from tests.support import FakeClock, FakeDelivery, ReceiptFailureStore, team_channels

UTC = UTC


async def migrate(url: str) -> None:
    environment = {**os.environ, "DATABASE_URL": url}
    process = await asyncio.create_subprocess_exec("alembic", "upgrade", "head", env=environment)
    assert await process.wait() == 0


async def disposable_store():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL to a disposable PostgreSQL database ending in _test")
    assert (make_url(url).database or "").endswith("_test"), "refusing a non-test database"
    await migrate(url)
    engine = create_engine(url)
    await clear_rows(engine)
    return engine, SqlMeetingStore(engine)


async def clear_rows(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM reminder_jobs"))
        await connection.execute(text("DELETE FROM meetings"))
        await connection.execute(text("DELETE FROM guild_configurations"))


@pytest.mark.integration
async def test_postgres_dst_instant_survives_a_new_store():
    engine, store = await disposable_store()
    try:
        clock = FakeClock(datetime(2026, 3, 8, 8, 29, tzinfo=UTC))
        meetings = MeetingService(store, team_channels(), clock)
        meeting = await meetings.create(
            guild_id=123,
            organizer_id=7,
            title="Design review",
            start_text="2026-03-08 03:30",
            timezone_name="America/Los_Angeles",
            text_channel_id=10,
            voice_channel_id=11,
            offsets_text="120",
        )
        reloaded = await SqlMeetingStore(engine).get_meeting(123, meeting.id)
        assert reloaded is not None
        assert reloaded.starts_at == datetime(2026, 3, 8, 10, 30, tzinfo=UTC)
        assert reloaded.jobs[0].due_at == datetime(2026, 3, 8, 8, 30, tzinfo=UTC)
        assert reloaded.starts_at.tzinfo is not None
        delivery = FakeDelivery()
        scheduler = ReminderScheduler(store, delivery, clock)
        await scheduler.run_once()
        assert delivery.sent == []
        clock.advance(minutes=1)
        await ReminderScheduler(SqlMeetingStore(engine), delivery, clock).run_once()
        assert len(delivery.sent) == 1
        saved = await store.get_meeting(123, meeting.id)
        assert saved is not None
        assert saved.jobs[0].state is JobState.DELIVERED
        assert saved.jobs[0].delivery_receipt
    finally:
        await clear_rows(engine)
        await engine.dispose()


@pytest.mark.integration
async def test_postgres_restart_skips_missed_and_delivers_future():
    engine, store = await disposable_store()
    try:
        clock = FakeClock(datetime(2026, 6, 1, 12, tzinfo=UTC))
        meeting = await MeetingService(store, team_channels(), clock).create(
            guild_id=123,
            organizer_id=7,
            title="Design review",
            start_text="2026-06-01 14:00",
            timezone_name="UTC",
            text_channel_id=10,
            voice_channel_id=11,
            offsets_text="60,15",
        )
        clock.set(datetime(2026, 6, 1, 13, 30, tzinfo=UTC))
        delivery = FakeDelivery()
        await ReminderScheduler(SqlMeetingStore(engine), delivery, clock).run_once()
        saved = await store.get_meeting(123, meeting.id)
        assert saved is not None
        states = {job.offset_minutes: job.state for job in saved.jobs}
        assert states[60] is JobState.SKIPPED
        assert states[15] is JobState.SCHEDULED
        assert delivery.sent == []
        clock.set(datetime(2026, 6, 1, 13, 45, tzinfo=UTC))
        await ReminderScheduler(SqlMeetingStore(engine), delivery, clock).run_once()
        assert [item.offset_minutes for item in delivery.sent] == [15]
    finally:
        await clear_rows(engine)
        await engine.dispose()


@pytest.mark.integration
async def test_postgres_receipt_loss_and_constraints():
    engine, store = await disposable_store()
    try:
        clock = FakeClock(datetime(2026, 6, 1, 12, tzinfo=UTC))
        wrapped = ReceiptFailureStore(store)
        meeting = await MeetingService(store, team_channels(), clock).create(
            guild_id=123,
            organizer_id=7,
            title="Design review",
            start_text="2026-06-01 14:00",
            timezone_name="UTC",
            text_channel_id=10,
            voice_channel_id=11,
            offsets_text="60",
        )
        clock.set(datetime(2026, 6, 1, 13, tzinfo=UTC))
        delivery = FakeDelivery()
        await ReminderScheduler(wrapped, delivery, clock).run_once()
        assert len(delivery.sent) == 1
        saved = await store.get_meeting(123, meeting.id)
        assert saved is not None
        assert saved.jobs[0].state is JobState.CLAIMED
        await ReminderScheduler(wrapped, delivery, clock).run_once()
        assert len(delivery.sent) == 1
        clock.advance(seconds=61)
        await ReminderScheduler(store, delivery, clock).run_once()
        saved = await store.get_meeting(123, meeting.id)
        assert saved is not None
        assert saved.jobs[0].state is JobState.UNRECONCILED

        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO meetings (guild_id, title, text_channel_id, "
                        "voice_channel_id, starts_at, timezone, organizer_id, state, "
                        "created_at, updated_at) VALUES (999, 'x', 1, 2, now(), 'UTC', "
                        "1, 'scheduled', now(), now())"
                    )
                )
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO reminder_jobs (meeting_id, offset_minutes, due_at, "
                        "state, attempt_count) VALUES (:meeting_id, 60, :due_at, "
                        "'scheduled', 0)"
                    ),
                    {"meeting_id": meeting.id, "due_at": saved.jobs[0].due_at},
                )
        async with engine.connect() as connection:
            state = await connection.scalar(
                text("SELECT state FROM meetings WHERE id = :meeting_id"),
                {"meeting_id": meeting.id},
            )
        assert state == MeetingState.SCHEDULED.value
    finally:
        await clear_rows(engine)
        await engine.dispose()
