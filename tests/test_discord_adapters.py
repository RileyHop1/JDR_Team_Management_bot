"""Discord adapter error mapping and mention suppression."""

from datetime import UTC, datetime
from types import SimpleNamespace

import discord
import pytest

from jdr_bot.bot import TeamBot
from jdr_bot.discord_adapters import (
    DiscordBriefDelivery,
    DiscordChannelDirectory,
    DiscordReminderDelivery,
)
from jdr_bot.domain import ChannelKind
from jdr_bot.ports import BriefMessage, DeliveryError, PartialDelivery, ReminderNotice


def http_error(status: int, body: str) -> discord.HTTPException:
    response = SimpleNamespace(status=status, reason="synthetic")
    if status == 403:
        return discord.Forbidden(response, body)
    if status == 404:
        return discord.NotFound(response, body)
    return discord.HTTPException(response, body)


class LookupClient:
    def __init__(self, channel=None, fetch_error=None):
        self.channel = channel
        self.fetch_error = fetch_error

    def get_channel(self, channel_id: int):
        del channel_id
        return self.channel

    async def fetch_channel(self, channel_id: int):
        del channel_id
        if self.fetch_error is not None:
            raise self.fetch_error
        if self.channel is None:
            raise http_error(404, "synthetic-secret-body")
        return self.channel


def notice() -> ReminderNotice:
    return ReminderNotice(
        meeting_id=4,
        job_id=9,
        guild_id=123,
        text_channel_id=10,
        voice_channel_id=11,
        title="@everyone <@123> Design review",
        starts_at=datetime(2026, 6, 1, 14, tzinfo=UTC),
        timezone_name="UTC",
        offset_minutes=15,
    )


def text_channel(bot: TeamBot) -> discord.TextChannel:
    guild = discord.Guild(
        state=bot._connection,
        data={"id": "123", "name": "Synthetic", "roles": []},
    )
    return discord.TextChannel(
        state=bot._connection,
        guild=guild,
        data={"id": "10", "type": 0, "name": "meetings", "position": 0},
    )


async def test_delivery_suppresses_mentions_and_maps_errors(settings, monkeypatch):
    bot = TeamBot(settings, SimpleNamespace())
    channel = text_channel(bot)
    captured: dict[str, object] = {}

    async def fake_send(self, content=None, **kwargs):
        del self
        captured["content"] = content
        captured["allowed"] = kwargs["allowed_mentions"]
        return SimpleNamespace(id=555)

    monkeypatch.setattr(discord.TextChannel, "send", fake_send)
    delivery = DiscordReminderDelivery(LookupClient(channel))
    receipt = await delivery.send_reminder(notice())
    assert receipt.message_id == "555"
    assert "@everyone" in str(captured["content"])
    allowed = captured["allowed"]
    assert isinstance(allowed, discord.AllowedMentions)
    assert allowed.everyone is False
    assert allowed.users is False
    assert allowed.roles is False

    forbidden = DiscordReminderDelivery(
        LookupClient(fetch_error=http_error(403, "synthetic-secret-body"))
    )
    with pytest.raises(DeliveryError) as error:
        await forbidden.send_reminder(notice())
    assert error.value.category == "channel_forbidden"
    assert error.value.transient is False
    assert error.value.__cause__ is None
    assert "synthetic-secret-body" not in str(error.value)

    unavailable = DiscordReminderDelivery(
        LookupClient(channel=None, fetch_error=http_error(503, "synthetic-secret-body"))
    )
    # get_channel returns None, fetch raises 503.
    unavailable = DiscordReminderDelivery(
        LookupClient(fetch_error=http_error(503, "synthetic-secret-body"))
    )
    with pytest.raises(DeliveryError) as unavailable_error:
        await unavailable.send_reminder(notice())
    assert unavailable_error.value.category == "discord_http"
    assert unavailable_error.value.transient is True


async def test_channel_directory_fail_closed_and_classifies(settings):
    bot = TeamBot(settings, SimpleNamespace())
    channel = text_channel(bot)
    directory = DiscordChannelDirectory(LookupClient(channel))
    facts = await directory.describe_channel(123, 10)
    assert facts is not None
    assert facts.kind is ChannelKind.TEXT
    assert facts.can_send is False
    assert facts.can_view is False

    missing = DiscordChannelDirectory(LookupClient())
    assert await missing.describe_channel(123, 10) is None

    denied = DiscordChannelDirectory(
        LookupClient(fetch_error=http_error(403, "synthetic-secret-body"))
    )
    with pytest.raises(Exception) as error:
        await denied.describe_channel(123, 99)
    assert error.value.category == "channel_forbidden"
    assert error.value.__cause__ is None


async def test_brief_delivery_suppresses_mentions_and_reports_partial(settings, monkeypatch):
    bot = TeamBot(settings, SimpleNamespace())
    channel = text_channel(bot)
    sent: list[str] = []

    async def fake_send(self, content=None, **kwargs):
        del self
        assert kwargs["allowed_mentions"].everyone is False
        if sent:
            raise http_error(403, "synthetic-secret-body")
        sent.append(str(content))
        return SimpleNamespace(id=777)

    monkeypatch.setattr(discord.TextChannel, "send", fake_send)
    delivery = DiscordBriefDelivery(LookupClient(channel))
    with pytest.raises(PartialDelivery) as error:
        await delivery.send_brief(
            BriefMessage(guild_id=123, channel_id=10, parts=("Morning brief", "JDR-2 continues"))
        )
    assert error.value.message_id == "777"
    assert error.value.transient is False
    assert error.value.__cause__ is None
    assert sent == ["Morning brief"]
    assert "synthetic-secret-body" not in str(error.value)


async def test_brief_channel_must_belong_to_the_configured_guild(settings, monkeypatch):
    bot = TeamBot(settings, SimpleNamespace())
    channel = text_channel(bot)
    sent: list[str] = []

    async def fake_send(self, content=None, **kwargs):
        del self, kwargs
        sent.append(str(content))
        return SimpleNamespace(id=888)

    monkeypatch.setattr(discord.TextChannel, "send", fake_send)
    delivery = DiscordBriefDelivery(LookupClient(channel))
    with pytest.raises(DeliveryError) as error:
        await delivery.send_brief(
            BriefMessage(guild_id=999, channel_id=10, parts=("Morning brief",))
        )
    assert error.value.category == "channel_wrong_guild"
    assert error.value.transient is False
    assert sent == []
    receipt = await delivery.send_brief(
        BriefMessage(guild_id=123, channel_id=10, parts=("Morning brief",))
    )
    assert receipt.message_id == "888"
    assert sent == ["Morning brief"]
