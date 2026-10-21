"""Operator gate and command replies for meeting management."""

from datetime import UTC, datetime
from types import SimpleNamespace

from jdr_bot.config import Settings
from jdr_bot.guild_config import GuildConfigChange, GuildConfigService
from jdr_bot.meeting_commands import MeetingCommands
from jdr_bot.meeting_service import MeetingService
from tests.guild_fakes import MemoryGuildConfigStore
from tests.support import FakeClock, MemoryMeetingStore, team_channels
from tests.test_bot import interaction

START = "2026-06-01 14:00"
NOON = datetime(2026, 6, 1, 12, tzinfo=UTC)


def commands_for(settings, clock=None, guild_config=None):
    store = MemoryMeetingStore()
    channels = team_channels()
    meetings = MeetingService(store, channels, clock or FakeClock(NOON))
    if guild_config is None:
        guild_config = GuildConfigService(
            MemoryGuildConfigStore(), channels, settings.guild_defaults()
        )
    context = SimpleNamespace(settings=settings, meetings=meetings, guild_config=guild_config)
    return MeetingCommands(context), meetings, store


def channel(channel_id):
    return SimpleNamespace(id=channel_id)


async def test_meeting_commands_require_the_operator_role(settings):
    group, meetings, store = commands_for(settings)
    request = interaction()
    await group.create_meeting(
        request,
        title="Design review",
        start=START,
        text_channel=channel(10),
        voice_channel=channel(11),
        offsets="60,15",
    )
    request.response.send_message.assert_awaited_once_with(
        "Operator role required.", ephemeral=True
    )
    request.response.defer.assert_not_awaited()
    assert await store.list_meetings(123, None, 10) == []
    outsider = interaction(guild_id=999, roles=[456])
    await group.view_meeting(outsider, meeting_id=1)
    outsider.response.send_message.assert_awaited_once_with(
        "Operator role required.", ephemeral=True
    )
    del meetings


async def test_operator_can_create_and_sees_validation_errors(settings):
    clock = FakeClock(NOON)
    group, _, store = commands_for(settings, clock)
    request = interaction(roles=[456])
    await group.create_meeting(
        request,
        title="Design review",
        start=START,
        text_channel=channel(10),
        voice_channel=channel(11),
        offsets="60,15",
        timezone="",
    )
    request.response.defer.assert_awaited_once_with(ephemeral=True)
    message = request.followup.send.await_args.args[0]
    assert "Design review" in message
    assert "2026-06-01 14:00 UTC" in message
    assert "60 min before: scheduled" in message
    saved = await store.list_meetings(123, None, 10)
    assert saved[0].timezone_name == "UTC"

    rejected = interaction(roles=[456])
    await group.create_meeting(
        rejected,
        title="Design review",
        start="tomorrow",
        text_channel=channel(10),
        voice_channel=channel(11),
        offsets="15",
    )
    assert "YYYY-MM-DD" in rejected.followup.send.await_args.args[0]


async def test_omitted_zone_uses_the_stored_guild_zone(settings):
    service = GuildConfigService(
        MemoryGuildConfigStore(), team_channels(), settings.guild_defaults()
    )
    await service.update(123, GuildConfigChange(timezone_name="America/Los_Angeles"))
    clock = FakeClock(datetime(2026, 6, 1, 12, tzinfo=UTC))
    group, _, store = commands_for(settings, clock, guild_config=service)
    request = interaction(roles=[456])
    await group.create_meeting(
        request,
        title="Design review",
        start="2026-06-01 14:00",
        text_channel=channel(10),
        voice_channel=channel(11),
        offsets="60",
        timezone="",
    )
    saved = await store.list_meetings(123, None, 10)
    assert saved[0].timezone_name == "America/Los_Angeles"
    assert saved[0].starts_at == datetime(2026, 6, 1, 21, tzinfo=UTC)

    explicit = interaction(roles=[456])
    await group.create_meeting(
        explicit,
        title="Follow up",
        start="2026-06-01 18:00",
        text_channel=channel(10),
        voice_channel=channel(11),
        offsets="60",
        timezone="UTC",
    )
    meetings = await store.list_meetings(123, None, 10)
    follow_up = next(item for item in meetings if item.title == "Follow up")
    original = next(item for item in meetings if item.title == "Design review")
    assert follow_up.timezone_name == "UTC"
    assert follow_up.starts_at == datetime(2026, 6, 1, 18, tzinfo=UTC)
    assert original.timezone_name == "America/Los_Angeles"
    assert original.starts_at == datetime(2026, 6, 1, 21, tzinfo=UTC)


async def test_blank_timezone_uses_configured_zone(settings):
    values = settings.model_dump()
    values["bot_timezone"] = "America/Los_Angeles"
    configured = Settings(_env_file=None, **values)
    clock = FakeClock(datetime(2026, 3, 1, tzinfo=UTC))
    group, _, store = commands_for(configured, clock)
    request = interaction(roles=[456])
    await group.create_meeting(
        request,
        title="Design review",
        start="2026-03-08 03:30",
        text_channel=channel(10),
        voice_channel=channel(11),
        offsets="120",
    )
    saved = await store.list_meetings(123, None, 10)
    assert saved[0].timezone_name == "America/Los_Angeles"
    assert saved[0].starts_at == datetime(2026, 3, 8, 10, 30, tzinfo=UTC)


async def test_unexpected_storage_error_is_hidden(settings, caplog, monkeypatch):
    group, meetings, _ = commands_for(settings)

    async def explode(**kwargs):
        del kwargs
        raise RuntimeError("synthetic-secret")

    monkeypatch.setattr(meetings, "list_scheduled", explode)
    request = interaction(roles=[456])
    await group.list_meetings(request)
    text = request.followup.send.await_args.args[0]
    assert text == "The meeting command could not be completed. Contact a maintainer."
    assert "synthetic-secret" not in caplog.text
    assert "synthetic-secret" not in text


def test_optional_command_fields_are_not_required(settings):
    group, _, _ = commands_for(settings)
    create = group.get_command("create")
    update = group.get_command("update")
    assert create is not None
    assert update is not None
    create_required = {param.name: param.required for param in create.parameters}
    update_required = {param.name: param.required for param in update.parameters}
    assert create_required["timezone"] is False
    assert create_required["title"] is True
    assert update_required["meeting_id"] is True
    assert update_required["offsets"] is False
    assert update_required["text_channel"] is False


async def test_update_and_cancel_commands(settings):
    clock = FakeClock(NOON)
    group, _, _ = commands_for(settings, clock)
    created = interaction(roles=[456])
    await group.create_meeting(
        created,
        title="Design review",
        start=START,
        text_channel=channel(10),
        voice_channel=channel(11),
        offsets="60",
    )
    meeting_id = int(created.followup.send.await_args.args[0].split(":", 1)[0].split()[-1])
    updated = interaction(roles=[456])
    await group.update_meeting(updated, meeting_id=meeting_id, title="Renamed")
    assert "Renamed" in updated.followup.send.await_args.args[0]
    empty = interaction(roles=[456])
    await group.update_meeting(empty, meeting_id=meeting_id)
    assert "at least one field" in empty.followup.send.await_args.args[0]
    cancelled = interaction(roles=[456])
    await group.cancel_meeting(cancelled, meeting_id=meeting_id)
    assert "cancelled" in cancelled.followup.send.await_args.args[0]
