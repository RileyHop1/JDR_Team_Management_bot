"""Discord channel lookup and reminder delivery. Business rules stay in the service."""

from zoneinfo import ZoneInfoNotFoundError

import discord

from jdr_bot.domain import ChannelFacts, ChannelKind
from jdr_bot.ports import (
    ChannelDirectoryError,
    DeliveryError,
    DeliveryReceipt,
    ReminderNotice,
)
from jdr_bot.presentation import reminder_message

_MESSAGE_LIMIT = 2000


class DiscordChannelDirectory:
    """Read channel type and the bot's current permissions. Fail closed."""

    def __init__(self, client: discord.Client) -> None:
        self._client = client

    async def describe_channel(self, guild_id: int, channel_id: int) -> ChannelFacts | None:
        if guild_id <= 0 or channel_id <= 0:
            return None
        cached = self._client.get_channel(channel_id)
        if cached is None:
            fetched = await self._fetch(channel_id)
            if fetched is None:
                return None
            return _facts(fetched)
        if isinstance(cached, discord.abc.PrivateChannel):
            return None
        return _facts(cached)

    async def _fetch(self, channel_id: int) -> discord.abc.GuildChannel | discord.Thread | None:
        try:
            fetched = await self._client.fetch_channel(channel_id)
        except discord.NotFound:
            return None
        except discord.Forbidden:
            raise ChannelDirectoryError("channel_forbidden") from None
        except discord.HTTPException as exc:
            category = "channel_lookup_failed"
            if exc.status == 429 or exc.status >= 500:
                category = "channel_lookup_unavailable"
            raise ChannelDirectoryError(category) from None
        if isinstance(fetched, discord.abc.PrivateChannel):
            return None
        return fetched


class DiscordReminderDelivery:
    """Post a reminder with mentions suppressed. Provider errors become DeliveryError."""

    def __init__(self, client: discord.Client) -> None:
        self._client = client

    async def send_reminder(self, notice: ReminderNotice) -> DeliveryReceipt:
        channel = await self._text_channel(notice.text_channel_id)
        try:
            content = reminder_message(notice)
        except (ZoneInfoNotFoundError, ValueError):
            raise DeliveryError("invalid_timezone", transient=False) from None
        if len(content) > _MESSAGE_LIMIT:
            raise DeliveryError("message_too_long", transient=False)
        try:
            message = await channel.send(content, allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            raise DeliveryError("channel_forbidden", transient=False) from None
        except discord.NotFound:
            raise DeliveryError("channel_missing", transient=False) from None
        except discord.HTTPException as exc:
            transient = exc.status == 429 or exc.status >= 500
            raise DeliveryError("discord_http", transient=transient) from None
        return DeliveryReceipt(message_id=str(message.id))

    async def _text_channel(self, channel_id: int) -> discord.TextChannel:
        channel = self._client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self._client.fetch_channel(channel_id)
            except discord.NotFound:
                raise DeliveryError("channel_missing", transient=False) from None
            except discord.Forbidden:
                raise DeliveryError("channel_forbidden", transient=False) from None
            except discord.HTTPException as exc:
                transient = exc.status == 429 or exc.status >= 500
                raise DeliveryError("discord_http", transient=transient) from None
        if not isinstance(channel, discord.TextChannel):
            raise DeliveryError("channel_unavailable", transient=False)
        return channel


def _facts(
    channel: discord.abc.GuildChannel | discord.Thread | discord.abc.PrivateChannel,
) -> ChannelFacts | None:
    if isinstance(channel, discord.abc.PrivateChannel):
        return None
    if isinstance(channel, discord.Thread):
        return ChannelFacts(
            channel_id=channel.id,
            guild_id=channel.guild.id,
            kind=ChannelKind.OTHER,
            can_view=False,
            can_send=False,
        )
    if isinstance(channel, discord.TextChannel):
        can_view, can_send = _access(channel)
        return ChannelFacts(
            channel_id=channel.id,
            guild_id=channel.guild.id,
            kind=ChannelKind.TEXT,
            can_view=can_view,
            can_send=can_send,
        )
    if isinstance(channel, discord.VoiceChannel):
        can_view, can_send = _access(channel)
        return ChannelFacts(
            channel_id=channel.id,
            guild_id=channel.guild.id,
            kind=ChannelKind.VOICE,
            can_view=can_view,
            can_send=can_send,
        )
    can_view, can_send = _access(channel)
    return ChannelFacts(
        channel_id=channel.id,
        guild_id=channel.guild.id,
        kind=ChannelKind.OTHER,
        can_view=can_view,
        can_send=can_send,
    )


def _access(channel: discord.abc.GuildChannel) -> tuple[bool, bool]:
    """Return view and send flags. Missing member cache means no permission."""
    try:
        member = channel.guild.me
    except AttributeError:
        return False, False
    permissions = channel.permissions_for(member)
    return permissions.view_channel, permissions.send_messages
