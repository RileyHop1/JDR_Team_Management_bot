"""Per-guild settings: validation, environment fallback, and operator updates.

No Discord or database I/O in the pure helpers. The service receives those
through its constructor. See docs/decisions/0004-guild-configuration.md.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jdr_bot.brief import BriefSchedule, parse_brief_time
from jdr_bot.domain import MeetingError, require_text_channel
from jdr_bot.policy import MAX_TIMEZONE_LENGTH
from jdr_bot.ports import ChannelDirectory, ChannelDirectoryError

logger = logging.getLogger(__name__)

# Discord snowflakes and PostgreSQL bigint both fit below this bound.
_MAX_DISCORD_ID = 2**63

_CHANNEL_REJECTED = (
    "Choose a text channel in this server that the bot can view and send messages in."
)
_ZONE_REJECTED = "Use an IANA time zone such as America/Los_Angeles."
_TIME_REJECTED = "Use HH:MM in 24-hour time, for example 09:00."


class ConfigError(Exception):
    """A safe message for the operator. Do not put secrets or driver text here."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class StoredGuildConfig:
    """One guild row. Null fields are unset, not a blank string."""

    guild_id: int
    meetings_channel_id: int | None
    brief_channel_id: int | None
    timezone_name: str | None
    brief_time: str | None


@dataclass(frozen=True)
class EnvGuildDefaults:
    """Environment values used when the stored field is null or the row is missing."""

    timezone_name: str
    meetings_channel_id: int | None
    brief_channel_id: int | None
    brief_time: str | None


@dataclass(frozen=True)
class GuildConfigChange:
    """Fields to write. None leaves a field unchanged unless its clear flag is set."""

    meetings_channel_id: int | None = None
    brief_channel_id: int | None = None
    timezone_name: str | None = None
    brief_time: str | None = None
    clear_meetings_channel: bool = False
    clear_brief_channel: bool = False
    clear_timezone: bool = False
    clear_brief_time: bool = False

    def conflicts(self) -> bool:
        return (
            (self.meetings_channel_id is not None and self.clear_meetings_channel)
            or (self.brief_channel_id is not None and self.clear_brief_channel)
            or (self.timezone_name is not None and self.clear_timezone)
            or (self.brief_time is not None and self.clear_brief_time)
        )

    def is_empty(self) -> bool:
        return (
            self.meetings_channel_id is None
            and self.brief_channel_id is None
            and self.timezone_name is None
            and self.brief_time is None
            and not self.clear_meetings_channel
            and not self.clear_brief_channel
            and not self.clear_timezone
            and not self.clear_brief_time
        )

    def changed_fields(self) -> tuple[str, ...]:
        names: list[str] = []
        if self.meetings_channel_id is not None or self.clear_meetings_channel:
            names.append("meetings_channel")
        if self.brief_channel_id is not None or self.clear_brief_channel:
            names.append("brief_channel")
        if self.timezone_name is not None or self.clear_timezone:
            names.append("timezone")
        if self.brief_time is not None or self.clear_brief_time:
            names.append("brief_time")
        return tuple(names)


@dataclass(frozen=True)
class ConfigField:
    label: str
    value: str | None
    source: str


@dataclass(frozen=True)
class GuildConfigView:
    fields: tuple[ConfigField, ...]


class GuildConfigStore(Protocol):
    async def get(self, guild_id: int) -> StoredGuildConfig | None:
        """Return the stored row, or None when this guild has no row."""

    async def apply(self, guild_id: int, change: GuildConfigChange) -> StoredGuildConfig:
        """Insert or update one guild. Other fields stay as they were."""


def merge_change(current: StoredGuildConfig, change: GuildConfigChange) -> StoredGuildConfig:
    """Apply a validated change. Callers reject empty and conflicting changes first."""
    meetings = current.meetings_channel_id
    if change.clear_meetings_channel:
        meetings = None
    elif change.meetings_channel_id is not None:
        meetings = change.meetings_channel_id
    brief_channel = current.brief_channel_id
    if change.clear_brief_channel:
        brief_channel = None
    elif change.brief_channel_id is not None:
        brief_channel = change.brief_channel_id
    timezone_name = current.timezone_name
    if change.clear_timezone:
        timezone_name = None
    elif change.timezone_name is not None:
        timezone_name = change.timezone_name
    brief_time = current.brief_time
    if change.clear_brief_time:
        brief_time = None
    elif change.brief_time is not None:
        brief_time = change.brief_time
    return StoredGuildConfig(
        guild_id=current.guild_id,
        meetings_channel_id=meetings,
        brief_channel_id=brief_channel,
        timezone_name=timezone_name,
        brief_time=brief_time,
    )


def prepare_change(change: GuildConfigChange) -> GuildConfigChange:
    """Canonicalize a zone and brief time, or raise ConfigError with a fixed message."""
    if change.conflicts():
        raise ConfigError("Choose either a new value or clear for each setting.")
    timezone_name = change.timezone_name
    if timezone_name is not None:
        timezone_name = validated_timezone(timezone_name)
    brief_time = change.brief_time
    if brief_time is not None:
        brief_time = validated_brief_time(brief_time)
    prepared = GuildConfigChange(
        meetings_channel_id=change.meetings_channel_id,
        brief_channel_id=change.brief_channel_id,
        timezone_name=timezone_name,
        brief_time=brief_time,
        clear_meetings_channel=change.clear_meetings_channel,
        clear_brief_channel=change.clear_brief_channel,
        clear_timezone=change.clear_timezone,
        clear_brief_time=change.clear_brief_time,
    )
    if prepared.is_empty():
        raise ConfigError("Provide at least one setting to change.")
    return prepared


def validated_timezone(value: str) -> str:
    """Return an IANA name, or raise ConfigError without echoing the input."""
    name = value.strip()
    if not name or len(name) > MAX_TIMEZONE_LENGTH:
        raise ConfigError(_ZONE_REJECTED)
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(_ZONE_REJECTED) from None
    return name


def validated_brief_time(value: str) -> str:
    """Return canonical HH:MM, or raise ConfigError without echoing the input."""
    try:
        hour, minute = parse_brief_time(value)
    except ValueError:
        raise ConfigError(_TIME_REJECTED) from None
    return f"{hour:02d}:{minute:02d}"


def change_from_command(
    *,
    meetings_channel_id: int | None,
    brief_channel_id: int | None,
    timezone_name: str | None,
    brief_time: str | None,
    clear: str | None,
) -> GuildConfigChange:
    """Build a change from slash-command options. ``clear`` is one field name or None."""
    if clear is not None and clear not in {
        "meetings_channel",
        "brief_channel",
        "timezone",
        "brief_time",
    }:
        raise ConfigError("Clear one of: meetings_channel, brief_channel, timezone, brief_time.")
    return GuildConfigChange(
        meetings_channel_id=meetings_channel_id,
        brief_channel_id=brief_channel_id,
        timezone_name=timezone_name,
        brief_time=brief_time,
        clear_meetings_channel=clear == "meetings_channel",
        clear_brief_channel=clear == "brief_channel",
        clear_timezone=clear == "timezone",
        clear_brief_time=clear == "brief_time",
    )


def describe(stored: StoredGuildConfig | None, defaults: EnvGuildDefaults) -> GuildConfigView:
    """Show the effective value and whether it came from the row or the environment."""
    return GuildConfigView(
        fields=(
            _field(
                "Time zone",
                None if stored is None else stored.timezone_name,
                defaults.timezone_name,
            ),
            _field(
                "Meetings channel",
                _channel_text(None if stored is None else stored.meetings_channel_id),
                _channel_text(defaults.meetings_channel_id),
            ),
            _field(
                "Brief channel",
                _channel_text(None if stored is None else stored.brief_channel_id),
                _channel_text(defaults.brief_channel_id),
            ),
            _field(
                "Brief time",
                None if stored is None else stored.brief_time,
                defaults.brief_time,
            ),
        )
    )


def format_guild_config(view: GuildConfigView) -> str:
    """Render a view. Sources are ``stored``, ``environment``, or ``not set``."""
    lines: list[str] = []
    for field in view.fields:
        if field.source == "not_set" or field.value is None:
            lines.append(f"{field.label}: not set")
        else:
            lines.append(f"{field.label}: {field.value} ({field.source})")
    return "\n".join(lines)


class GuildConfigService:
    """View and update one guild. Authorization stays in the command layer."""

    def __init__(
        self, store: GuildConfigStore, channels: ChannelDirectory, defaults: EnvGuildDefaults
    ) -> None:
        self._store = store
        self._channels = channels
        self._defaults = defaults

    async def view(self, guild_id: int) -> GuildConfigView:
        if guild_id <= 0:
            raise ConfigError("Guild configuration is not available.")
        stored = await self._store.get(guild_id)
        return describe(stored, self._defaults)

    async def timezone_name(self, guild_id: int) -> str:
        """Stored IANA zone, or the environment default when the row or field is missing."""
        stored = await self._store.get(guild_id)
        if stored is not None and stored.timezone_name:
            return stored.timezone_name
        return self._defaults.timezone_name

    async def update(self, guild_id: int, change: GuildConfigChange) -> GuildConfigView:
        if guild_id <= 0:
            raise ConfigError("Guild configuration is not available.")
        prepared = prepare_change(change)
        await self._require_postable(guild_id, prepared.meetings_channel_id)
        await self._require_postable(guild_id, prepared.brief_channel_id)
        stored = await self._store.apply(guild_id, prepared)
        logger.info(
            "guild_config_updated guild_id=%s fields=%s",
            guild_id,
            ",".join(prepared.changed_fields()),
        )
        return describe(stored, self._defaults)

    async def _require_postable(self, guild_id: int, channel_id: int | None) -> None:
        if channel_id is None:
            return
        if channel_id <= 0 or channel_id >= _MAX_DISCORD_ID:
            raise ConfigError(_CHANNEL_REJECTED)
        try:
            facts = await self._channels.describe_channel(guild_id, channel_id)
        except ChannelDirectoryError as error:
            if error.category == "channel_forbidden":
                raise ConfigError("The bot cannot view that channel.") from None
            raise ConfigError("Could not verify the channel. Try again shortly.") from None
        try:
            require_text_channel(facts, guild_id)
        except MeetingError as error:
            raise ConfigError(error.message) from None


ScheduleBuilder = Callable[[StoredGuildConfig | None], BriefSchedule | None]


class GuildBriefScheduleSource:
    """Reload non-secret brief settings on each poll. Credentials stay outside this type."""

    def __init__(self, guild_id: int, store: GuildConfigStore, build: ScheduleBuilder) -> None:
        self._guild_id = guild_id
        self._store = store
        self._build = build
        self._reported_invalid = False

    async def current_schedule(self) -> BriefSchedule | None:
        stored = await self._store.get(self._guild_id)
        try:
            schedule = self._build(stored)
        except ValueError:
            if not self._reported_invalid:
                logger.info("brief_schedule_invalid")
                self._reported_invalid = True
            return None
        self._reported_invalid = False
        return schedule


def _field(label: str, stored_value: str | None, env_value: str | None) -> ConfigField:
    if stored_value is not None:
        return ConfigField(label, stored_value, "stored")
    if env_value is not None:
        return ConfigField(label, env_value, "environment")
    return ConfigField(label, None, "not_set")


def _channel_text(channel_id: int | None) -> str | None:
    if channel_id is None:
        return None
    return str(channel_id)
