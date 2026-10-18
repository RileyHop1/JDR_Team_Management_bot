"""Exercise real command handlers with synthetic Discord interactions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from jdr_bot.authorization import can_manage
from jdr_bot.bot import TeamBot


@pytest.mark.parametrize(
    ("guild_id", "roles", "allowed"),
    [(123, [456], True), (123, [], False), (999, [456], False), (None, [456], False)],
)
def test_operator_policy(guild_id, roles, allowed):
    assert (
        can_manage(guild_id=guild_id, allowed_guild_id=123, role_ids=roles, operator_role_id=456)
        is allowed
    )


def interaction(guild_id=123, roles=None, user_id=7):
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.roles = [SimpleNamespace(id=role) for role in (roles or [])]
    return SimpleNamespace(
        guild_id=guild_id,
        user=member,
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )


async def test_ping_and_guild_isolation(settings):
    bot = TeamBot(settings, MagicMock())
    request = interaction()
    await bot.ping(request)
    request.response.send_message.assert_awaited_once_with("Pong!", ephemeral=True)
    outsider = interaction(guild_id=999)
    await bot.ping(outsider)
    outsider.response.send_message.assert_awaited_once_with(
        "This server is not configured.", ephemeral=True
    )
    assert bot.tree.get_commands() == []  # No global registration.
    assert {command.name for command in bot.tree.get_commands(guild=bot.guild)} == {
        "ping",
        "status",
        "meeting",
    }
    meeting = bot.tree.get_command("meeting", guild=bot.guild)
    assert meeting is not None
    assert {command.name for command in meeting.commands} == {
        "create",
        "list",
        "view",
        "update",
        "cancel",
    }
    assert bot.intents.guilds
    assert not bot.intents.members
    assert not bot.intents.message_content


async def test_denied_status_never_reads_database(settings, monkeypatch):
    check = AsyncMock()
    monkeypatch.setattr("jdr_bot.bot.check_database", check)
    bot = TeamBot(settings, MagicMock())
    request = interaction()
    await bot.operator_status(request)
    check.assert_not_awaited()
    request.response.send_message.assert_awaited_once_with(
        "Operator role required.", ephemeral=True
    )


@pytest.mark.parametrize("fails", [False, True])
async def test_operator_status_handles_database_result(settings, monkeypatch, fails, caplog):
    check = AsyncMock(side_effect=RuntimeError("sensitive-password") if fails else None)
    monkeypatch.setattr("jdr_bot.bot.check_database", check)
    bot = TeamBot(settings, MagicMock())
    request = interaction(roles=[456])
    await bot.operator_status(request)
    request.response.defer.assert_awaited_once_with(ephemeral=True)
    check.assert_awaited_once_with(bot.engine)
    message = "Database unavailable; contact a maintainer." if fails else "Database ready."
    request.followup.send.assert_awaited_once_with(message, ephemeral=True)
    assert "sensitive-password" not in caplog.text


class IdleScheduler:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.runs = 0

    async def serve(self) -> None:
        self.runs += 1
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise


async def test_scheduler_starts_once_and_stops_on_close(settings, monkeypatch):
    monkeypatch.setattr("jdr_bot.bot.check_database", AsyncMock())
    scheduler = IdleScheduler()
    bot = TeamBot(settings, MagicMock(), scheduler=scheduler)
    monkeypatch.setattr(bot.tree, "sync", AsyncMock())
    await bot.setup_hook()
    await scheduler.started.wait()
    await bot.on_ready()
    assert scheduler.runs == 1
    await bot.close()
    assert scheduler.started.is_set()
    assert bot._scheduler_task is None


async def test_startup_checks_schema_before_sync(settings, monkeypatch):
    check = AsyncMock(side_effect=RuntimeError("unmigrated"))
    monkeypatch.setattr("jdr_bot.bot.check_database", check)
    bot = TeamBot(settings, MagicMock())
    sync = AsyncMock()
    monkeypatch.setattr(bot.tree, "sync", sync)
    with pytest.raises(RuntimeError, match="unmigrated"):
        await bot.setup_hook()
    sync.assert_not_awaited()
    assert bot._scheduler_task is None


async def test_operator_role_resolves_from_real_discord_member(settings, monkeypatch):
    check = AsyncMock()
    monkeypatch.setattr("jdr_bot.bot.check_database", check)
    bot = TeamBot(settings, MagicMock())
    guild = discord.Guild(
        state=bot._connection,
        data={
            "id": "123",
            "name": "Synthetic test server",
            "roles": [
                {"id": "123", "name": "@everyone", "permissions": "0", "position": 0},
                {"id": "456", "name": "Operator", "permissions": "0", "position": 1},
            ],
        },
    )
    member = discord.Member(
        state=bot._connection,
        guild=guild,
        data={
            "user": {"id": "789", "username": "synthetic", "discriminator": "0", "avatar": None},
            "roles": ["456"],
            "joined_at": None,
            "flags": 0,
        },
    )
    request = interaction()
    request.user = member
    await bot.operator_status(request)
    check.assert_awaited_once()
    request.followup.send.assert_awaited_once_with("Database ready.", ephemeral=True)
