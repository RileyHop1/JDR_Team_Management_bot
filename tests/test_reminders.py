"""Meeting changes and reminder delivery with a fake clock and in-memory store."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest

from jdr_bot.domain import ChannelFacts, ChannelKind, JobState, MeetingError, MeetingState
from jdr_bot.meeting_service import MeetingService
from jdr_bot.policy import DELIVERY_GRACE
from jdr_bot.ports import ChannelDirectoryError, DeliveryError
from jdr_bot.reminder_scheduler import ReminderScheduler
from tests.support import (
    FakeClock,
    FakeDelivery,
    MemoryMeetingStore,
    ReceiptFailureStore,
    StaticChannels,
    team_channels,
)

UTC = UTC


def service(
    store: MemoryMeetingStore, clock: FakeClock, channels: StaticChannels | None = None
) -> MeetingService:
    return MeetingService(store, channels or team_channels(), clock)


async def create(store: MemoryMeetingStore, clock: FakeClock, **overrides: object) -> object:
    values: dict[str, object] = {
        "guild_id": 123,
        "organizer_id": 7,
        "title": "Design review",
        "start_text": "2026-06-01 14:00",
        "timezone_name": "UTC",
        "text_channel_id": 10,
        "voice_channel_id": 11,
        "offsets_text": "60,15",
    }
    values.update(overrides)
    return await service(store, clock).create(**values)


async def test_create_update_cancel_and_guild_scope():
    clock = FakeClock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    store = MemoryMeetingStore()
    meeting = await create(store, clock)
    assert meeting.starts_at == datetime(2026, 6, 1, 14, 0, tzinfo=UTC)
    assert meeting.created_at == clock.now()
    assert [job.offset_minutes for job in meeting.jobs] == [60, 15]
    assert all(job.due_at.tzinfo is not None for job in meeting.jobs)
    original_ids = [job.id for job in meeting.jobs]

    renamed = await service(store, clock).update(
        guild_id=123, meeting_id=meeting.id, title="  Weekly   sync  "
    )
    assert renamed.title == "Weekly sync"
    assert [job.id for job in renamed.jobs] == original_ids

    moved = await service(store, clock).update(
        guild_id=123, meeting_id=meeting.id, start_text="2026-06-01 15:00"
    )
    scheduled = [job for job in moved.jobs if job.state is JobState.SCHEDULED]
    cancelled = [job for job in moved.jobs if job.state is JobState.CANCELLED]
    assert [(job.offset_minutes, job.due_at) for job in scheduled] == [
        (60, datetime(2026, 6, 1, 14, 0, tzinfo=UTC)),
        (15, datetime(2026, 6, 1, 14, 45, tzinfo=UTC)),
    ]
    assert len(cancelled) == 2

    with pytest.raises(MeetingError, match="not found"):
        await service(store, clock).view(guild_id=999, meeting_id=meeting.id)

    cancelled_meeting = await service(store, clock).cancel(guild_id=123, meeting_id=meeting.id)
    assert cancelled_meeting.state is MeetingState.CANCELLED
    assert all(job.state is JobState.CANCELLED for job in cancelled_meeting.jobs)
    with pytest.raises(MeetingError, match="already cancelled"):
        await service(store, clock).cancel(guild_id=123, meeting_id=meeting.id)
    listing = await service(store, clock).list_scheduled(guild_id=123)
    assert listing.meetings == ()


async def test_channel_validation_and_lookup_errors():
    clock = FakeClock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    store = MemoryMeetingStore()
    denied = StaticChannels(
        {
            10: ChannelFacts(10, 123, ChannelKind.TEXT, can_view=True, can_send=False),
            11: ChannelFacts(11, 123, ChannelKind.VOICE, can_view=True, can_send=False),
        }
    )
    meetings = MeetingService(store, denied, clock)
    with pytest.raises(MeetingError, match="send messages"):
        await meetings.create(
            guild_id=123,
            organizer_id=7,
            title="Design review",
            start_text="2026-06-01 14:00",
            timezone_name="UTC",
            text_channel_id=10,
            voice_channel_id=11,
            offsets_text="15",
        )

    class Unavailable:
        async def describe_channel(self, guild_id: int, channel_id: int) -> None:
            del guild_id, channel_id
            raise ChannelDirectoryError("channel_lookup_unavailable")

    broken = MeetingService(store, Unavailable(), clock)
    with pytest.raises(MeetingError, match="Try again shortly"):
        await broken.create(
            guild_id=123,
            organizer_id=7,
            title="Design review",
            start_text="2026-06-01 14:00",
            timezone_name="UTC",
            text_channel_id=10,
            voice_channel_id=11,
            offsets_text="15",
        )
    assert await store.list_meetings(123, None, 10) == []


async def test_dst_reminder_is_delivered_at_utc_instant():
    clock = FakeClock(datetime(2026, 3, 8, 8, 29, tzinfo=UTC))
    store = MemoryMeetingStore()
    delivery = FakeDelivery()
    await create(
        store,
        clock,
        start_text="2026-03-08 03:30",
        timezone_name="America/Los_Angeles",
        offsets_text="120",
    )
    scheduler = ReminderScheduler(store, delivery, clock)
    await scheduler.run_once()
    assert delivery.sent == []
    clock.advance(minutes=1)
    await scheduler.run_once()
    assert len(delivery.sent) == 1
    assert delivery.sent[0].offset_minutes == 120
    assert delivery.sent[0].starts_at == datetime(2026, 3, 8, 10, 30, tzinfo=UTC)


async def test_restart_skips_missed_reminder_and_keeps_the_future_one():
    clock = FakeClock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    store = MemoryMeetingStore()
    delivery = FakeDelivery()
    meeting = await create(store, clock)
    clock.set(datetime(2026, 6, 1, 13, 30, tzinfo=UTC))
    restarted = ReminderScheduler(store, delivery, clock)
    await restarted.run_once()
    saved = await store.get_meeting(123, meeting.id)
    assert saved is not None
    states = {job.offset_minutes: job.state for job in saved.jobs}
    assert states[60] is JobState.SKIPPED
    assert states[15] is JobState.SCHEDULED
    assert delivery.sent == []
    clock.set(datetime(2026, 6, 1, 13, 45, tzinfo=UTC))
    await ReminderScheduler(store, delivery, clock).run_once()
    assert [notice.offset_minutes for notice in delivery.sent] == [15]


async def test_receipt_loss_does_not_send_a_duplicate(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO)
    clock = FakeClock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    inner = MemoryMeetingStore()
    store = ReceiptFailureStore(inner)
    delivery = FakeDelivery()
    meeting = await create(inner, clock, offsets_text="60", start_text="2026-06-01 14:00")
    clock.set(datetime(2026, 6, 1, 13, 0, tzinfo=UTC))
    scheduler = ReminderScheduler(store, delivery, clock)
    await scheduler.run_once()
    assert len(delivery.sent) == 1
    saved = await inner.get_meeting(123, meeting.id)
    assert saved is not None
    assert saved.jobs[0].state is JobState.CLAIMED
    await scheduler.run_once()
    assert len(delivery.sent) == 1
    clock.advance(seconds=int(DELIVERY_GRACE.total_seconds()) + 1)
    await scheduler.run_once()
    saved = await inner.get_meeting(123, meeting.id)
    assert saved is not None
    assert saved.jobs[0].state is JobState.UNRECONCILED
    assert saved.jobs[0].failure_category == "receipt_unknown"
    assert len(delivery.sent) == 1
    assert "synthetic-token-should-not-be-logged" not in caplog.text
    assert meeting.title not in caplog.text


async def test_transient_failure_retries_and_permanent_failure_stops():
    clock = FakeClock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    store = MemoryMeetingStore()
    delivery = FakeDelivery()
    delivery.failures = [
        DeliveryError("discord_http", transient=True),
        DeliveryError("discord_http", transient=True),
    ]
    meeting = await create(store, clock, offsets_text="60")
    clock.set(datetime(2026, 6, 1, 13, 0, tzinfo=UTC))
    scheduler = ReminderScheduler(store, delivery, clock)
    await scheduler.run_once()
    await scheduler.run_once()
    clock.advance(seconds=15)
    await scheduler.run_once()
    clock.advance(seconds=30)
    await scheduler.run_once()
    assert len(delivery.sent) == 1
    saved = await store.get_meeting(123, meeting.id)
    assert saved is not None
    assert saved.jobs[0].state is JobState.DELIVERED
    assert saved.jobs[0].delivery_receipt is not None

    clock.set(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    other = MemoryMeetingStore()
    denied = FakeDelivery()
    denied.failures = [DeliveryError("channel_forbidden", transient=False)]
    created = await create(other, clock, offsets_text="60")
    clock.set(datetime(2026, 6, 1, 13, 0, tzinfo=UTC))
    failing = ReminderScheduler(other, denied, clock)
    await failing.run_once()
    await failing.run_once()
    saved = await other.get_meeting(123, created.id)
    assert saved is not None
    assert saved.jobs[0].state is JobState.FAILED
    assert saved.jobs[0].failure_category == "channel_forbidden"
    assert denied.sent == []


async def test_cancelled_meeting_is_not_delivered_and_claim_blocks_update():
    clock = FakeClock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    store = MemoryMeetingStore()
    delivery = FakeDelivery()
    meeting = await create(store, clock, offsets_text="60")
    await service(store, clock).cancel(guild_id=123, meeting_id=meeting.id)
    clock.set(datetime(2026, 6, 1, 13, 0, tzinfo=UTC))
    await ReminderScheduler(store, delivery, clock).run_once()
    assert delivery.sent == []

    live_clock = FakeClock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    live = MemoryMeetingStore()
    current = await create(live, live_clock, offsets_text="60")
    live_clock.set(datetime(2026, 6, 1, 13, 0, tzinfo=UTC))
    await live.claim_due(
        now=live_clock.now(), due_after=live_clock.now() - timedelta(seconds=60), limit=5
    )
    with pytest.raises(MeetingError, match="currently being delivered"):
        await service(live, live_clock).update(
            guild_id=123, meeting_id=current.id, start_text="2026-06-01 16:00"
        )
    with pytest.raises(MeetingError, match="currently being delivered"):
        await service(live, live_clock).cancel(guild_id=123, meeting_id=current.id)


async def test_list_limit_and_empty_update():
    clock = FakeClock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    store = MemoryMeetingStore()
    meetings = MeetingService(store, team_channels(), clock, list_limit=1)
    first = await meetings.create(
        guild_id=123,
        organizer_id=7,
        title="First",
        start_text="2026-06-01 14:00",
        timezone_name="UTC",
        text_channel_id=10,
        voice_channel_id=11,
        offsets_text="15",
    )
    await meetings.create(
        guild_id=123,
        organizer_id=7,
        title="Second",
        start_text="2026-06-01 18:00",
        timezone_name="UTC",
        text_channel_id=10,
        voice_channel_id=11,
        offsets_text="15",
    )
    listing = await meetings.list_scheduled(guild_id=123)
    assert [meeting.title for meeting in listing.meetings] == ["First"]
    assert listing.truncated
    with pytest.raises(MeetingError, match="at least one field"):
        await meetings.update(guild_id=123, meeting_id=first.id)
    with pytest.raises(MeetingError, match="changing the time zone"):
        await meetings.update(guild_id=123, meeting_id=first.id, timezone_name="UTC")


async def test_grace_boundary_still_delivers_and_one_more_second_skips():
    clock = FakeClock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    store = MemoryMeetingStore()
    delivery = FakeDelivery()
    await create(store, clock, offsets_text="60")
    clock.set(datetime(2026, 6, 1, 13, 0, tzinfo=UTC))
    clock.advance(seconds=60)
    await ReminderScheduler(store, delivery, clock).run_once()
    assert len(delivery.sent) == 1

    late_clock = FakeClock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    late_store = MemoryMeetingStore()
    late_delivery = FakeDelivery()
    await create(late_store, late_clock, offsets_text="60")
    late_clock.set(datetime(2026, 6, 1, 13, 0, tzinfo=UTC))
    late_clock.advance(seconds=61)
    await ReminderScheduler(late_store, late_delivery, late_clock).run_once()
    assert late_delivery.sent == []


async def test_scheduler_loop_logs_error_type_only(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.ERROR)
    clock = FakeClock(datetime(2026, 6, 1, tzinfo=UTC))

    class BoomStore(MemoryMeetingStore):
        async def skip_missed(self, *, due_before: datetime) -> int:
            del due_before
            raise RuntimeError("synthetic-secret")

    async def stop(_: float) -> None:
        raise asyncio.CancelledError

    scheduler = ReminderScheduler(BoomStore(), FakeDelivery(), clock, sleeper=stop)
    with pytest.raises(asyncio.CancelledError):
        await scheduler.serve()
    assert "RuntimeError" in caplog.text
    assert "synthetic-secret" not in caplog.text
