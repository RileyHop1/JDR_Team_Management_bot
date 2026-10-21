"""Operator guild configuration: permissions, validation, fallback, and brief wiring."""

import logging
from types import SimpleNamespace

import pytest

from jdr_bot.config import Settings
from jdr_bot.domain import ChannelFacts, ChannelKind
from jdr_bot.guild_commands import ConfigCommands
from jdr_bot.guild_config import (
    EnvGuildDefaults,
    GuildBriefScheduleSource,
    GuildConfigChange,
    GuildConfigService,
    StoredGuildConfig,
    describe,
    format_guild_config,
)
from jdr_bot.ports import ChannelDirectoryError
from jdr_bot.storage import GuildConfiguration
from tests.guild_fakes import MemoryGuildConfigStore
from tests.support import StaticChannels
from tests.test_bot import interaction


def text_channel(channel_id: int, guild_id: int = 123, *, can_send: bool = True) -> ChannelFacts:
    return ChannelFacts(
        channel_id=channel_id,
        guild_id=guild_id,
        kind=ChannelKind.TEXT,
        can_view=True,
        can_send=can_send,
    )


def service_for(store: MemoryGuildConfigStore | None = None) -> GuildConfigService:
    channels = StaticChannels({10: text_channel(10), 12: text_channel(12, can_send=False)})
    defaults = EnvGuildDefaults(
        timezone_name="UTC",
        meetings_channel_id=None,
        brief_channel_id=42,
        brief_time="09:00",
    )
    return GuildConfigService(store or MemoryGuildConfigStore(), channels, defaults)


def commands_for(settings, guild_config: GuildConfigService) -> ConfigCommands:
    return ConfigCommands(SimpleNamespace(settings=settings, guild_config=guild_config))


def test_configuration_columns_do_not_include_credentials():
    names = set(GuildConfiguration.__table__.columns.keys())
    assert names == {
        "guild_id",
        "created_at",
        "meetings_channel_id",
        "brief_channel_id",
        "timezone",
        "brief_time",
    }
    assert not any("jira" in name or "token" in name or "email" in name for name in names)


def test_missing_row_uses_environment_defaults():
    view = describe(
        None,
        EnvGuildDefaults(
            timezone_name="America/Los_Angeles",
            meetings_channel_id=8,
            brief_channel_id=None,
            brief_time=None,
        ),
    )
    rendered = format_guild_config(view)
    assert "Time zone: America/Los_Angeles (environment)" in rendered
    assert "Meetings channel: 8 (environment)" in rendered
    assert "Brief channel: not set" in rendered
    assert "Brief time: not set" in rendered
    assert "token" not in rendered


async def test_config_commands_require_the_operator_role(settings):
    class Unused:
        async def get(self, guild_id: int) -> StoredGuildConfig | None:
            raise AssertionError(guild_id)

        async def apply(self, guild_id: int, change: GuildConfigChange) -> StoredGuildConfig:
            raise AssertionError((guild_id, change))

    guild_config = GuildConfigService(Unused(), StaticChannels({}), settings.guild_defaults())
    group = commands_for(settings, guild_config)
    request = interaction()
    await group.view_config(request)
    request.response.send_message.assert_awaited_once_with(
        "Operator role required.", ephemeral=True
    )
    request.response.defer.assert_not_awaited()
    outsider = interaction(guild_id=999, roles=[456])
    await group.set_config(outsider, timezone="UTC")
    outsider.response.send_message.assert_awaited_once_with(
        "Operator role required.", ephemeral=True
    )


async def test_operator_can_set_view_and_clear(settings, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO)
    store = MemoryGuildConfigStore()
    guild_config = service_for(store)
    group = commands_for(settings, guild_config)
    before = interaction(roles=[456])
    await group.view_config(before)
    initial = before.followup.send.await_args.args[0]
    assert "Time zone: UTC (environment)" in initial
    assert "Brief channel: 42 (environment)" in initial
    assert "Brief time: 09:00 (environment)" in initial
    assert "Meetings channel: not set" in initial

    saved = interaction(roles=[456])
    await group.set_config(
        saved,
        meetings_channel=SimpleNamespace(id=10),
        timezone="America/Los_Angeles",
        brief_time="09:30",
    )
    text = saved.followup.send.await_args.args[0]
    assert "Guild configuration saved." in text
    assert "future brief jobs" in text
    assert "Time zone: America/Los_Angeles (stored)" in text
    assert "Meetings channel: 10 (stored)" in text
    assert "Brief time: 09:30 (stored)" in text
    assert "Brief channel: 42 (environment)" in text
    assert "America/Los_Angeles" not in caplog.text
    assert "guild_config_updated" in caplog.text
    assert "fields=meetings_channel,timezone,brief_time" in caplog.text
    assert await guild_config.timezone_name(123) == "America/Los_Angeles"

    cleared = interaction(roles=[456])
    await group.set_config(cleared, clear="timezone")
    assert "Time zone: UTC (environment)" in cleared.followup.send.await_args.args[0]
    assert "Brief time: 09:30 (stored)" in cleared.followup.send.await_args.args[0]
    assert await guild_config.timezone_name(123) == "UTC"


async def test_invalid_zone_time_and_channel_are_rejected(
    settings, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.INFO)
    store = MemoryGuildConfigStore()
    group = commands_for(settings, service_for(store))
    zone = interaction(roles=[456])
    await group.set_config(zone, timezone="synthetic-secret-zone")
    assert "IANA" in zone.followup.send.await_args.args[0]
    assert "synthetic-secret-zone" not in zone.followup.send.await_args.args[0]
    assert "synthetic-secret-zone" not in caplog.text
    assert store.rows == {}

    clock = interaction(roles=[456])
    await group.set_config(clock, brief_time="25:00")
    assert "HH:MM" in clock.followup.send.await_args.args[0]
    missing = interaction(roles=[456])
    await group.set_config(missing, meetings_channel=SimpleNamespace(id=99))
    assert "view and send" in missing.followup.send.await_args.args[0]
    other_guild = interaction(roles=[456])
    foreign = StaticChannels({10: text_channel(10, guild_id=999)})
    foreign_service = GuildConfigService(store, foreign, settings.guild_defaults())
    await commands_for(settings, foreign_service).set_config(
        other_guild, meetings_channel=SimpleNamespace(id=10)
    )
    assert "view and send" in other_guild.followup.send.await_args.args[0]
    muted = interaction(roles=[456])
    await group.set_config(muted, brief_channel=SimpleNamespace(id=12))
    assert "view and send" in muted.followup.send.await_args.args[0]
    assert store.rows == {}


async def test_channel_lookup_errors_stay_safe(settings):
    class Forbidden:
        async def describe_channel(self, guild_id: int, channel_id: int) -> None:
            del guild_id, channel_id
            raise ChannelDirectoryError("channel_forbidden")

    class Unavailable:
        async def describe_channel(self, guild_id: int, channel_id: int) -> None:
            del guild_id, channel_id
            raise ChannelDirectoryError("channel_lookup_unavailable")

    store = MemoryGuildConfigStore()
    defaults = settings.guild_defaults()
    forbidden = commands_for(settings, GuildConfigService(store, Forbidden(), defaults))
    denied = interaction(roles=[456])
    await forbidden.set_config(denied, meetings_channel=SimpleNamespace(id=10))
    assert denied.followup.send.await_args.args[0] == "The bot cannot view that channel."
    unavailable = commands_for(settings, GuildConfigService(store, Unavailable(), defaults))
    failed = interaction(roles=[456])
    await unavailable.set_config(failed, brief_channel=SimpleNamespace(id=10))
    assert failed.followup.send.await_args.args[0] == (
        "Could not verify the channel. Try again shortly."
    )
    assert store.rows == {}


async def test_empty_and_conflicting_updates_do_not_write(settings):
    store = MemoryGuildConfigStore()
    group = commands_for(settings, service_for(store))
    empty = interaction(roles=[456])
    await group.set_config(empty)
    assert "at least one" in empty.followup.send.await_args.args[0]
    conflict = interaction(roles=[456])
    await group.set_config(conflict, timezone="UTC", clear="timezone")
    assert "either a new value or clear" in conflict.followup.send.await_args.args[0]
    assert store.rows == {}


async def test_unexpected_failure_hides_the_exception(settings, caplog: pytest.LogCaptureFixture):
    class Boom:
        async def get(self, guild_id: int) -> StoredGuildConfig | None:
            del guild_id
            raise RuntimeError("synthetic-secret")

        async def apply(self, guild_id: int, change: GuildConfigChange) -> StoredGuildConfig:
            del guild_id, change
            raise RuntimeError("synthetic-secret")

    group = commands_for(
        settings, GuildConfigService(Boom(), StaticChannels({}), settings.guild_defaults())
    )
    request = interaction(roles=[456])
    await group.view_config(request)
    assert request.followup.send.await_args.args[0] == (
        "The config command could not be completed. Contact a maintainer."
    )
    assert "synthetic-secret" not in caplog.text
    assert "config_command_failed" in caplog.text


def test_set_options_are_optional(settings):
    group = commands_for(settings, service_for())
    set_command = group.get_command("set")
    view_command = group.get_command("view")
    assert set_command is not None
    assert view_command is not None
    assert [parameter.name for parameter in view_command.parameters] == []
    required = {parameter.name: parameter.required for parameter in set_command.parameters}
    assert required == {name: False for name in required}
    assert set(required) == {
        "meetings_channel",
        "brief_channel",
        "timezone",
        "brief_time",
        "clear",
    }


async def test_invalid_stored_zone_pauses_the_brief_without_logging_it(settings, caplog):
    caplog.set_level(logging.INFO)
    values = settings.model_dump()
    values.update(
        {
            "brief_channel_id": 10,
            "brief_time": "09:00",
            "jira_base_url": "https://example.atlassian.net",
            "jira_project_key": "JDR",
            "jira_status_names": "In Progress",
            "jira_user_email": "person@example.com",
            "jira_api_token": "synthetic-jira-token",
        }
    )
    configured = Settings(_env_file=None, **values)
    store = MemoryGuildConfigStore()
    store.rows[123] = StoredGuildConfig(
        guild_id=123,
        meetings_channel_id=None,
        brief_channel_id=10,
        timezone_name="synthetic-secret-zone",
        brief_time="09:00",
    )
    source = GuildBriefScheduleSource(123, store, configured.brief_schedule)
    assert await source.current_schedule() is None
    assert await source.current_schedule() is None
    assert caplog.text.count("brief_schedule_invalid") == 1
    assert "synthetic-secret-zone" not in caplog.text
    assert "synthetic-jira-token" not in caplog.text
    store.rows[123] = StoredGuildConfig(
        guild_id=123,
        meetings_channel_id=None,
        brief_channel_id=55,
        timezone_name="UTC",
        brief_time="10:15",
    )
    schedule = await source.current_schedule()
    assert schedule is not None
    assert schedule.channel_id == 55
    assert schedule.hour == 10
    assert schedule.minute == 15
    assert not hasattr(schedule, "api_token")
