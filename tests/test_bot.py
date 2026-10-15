"""Exercise real command handlers with synthetic Discord interactions."""

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


def interaction(guild_id=123, roles=None):
    member = MagicMock(spec=discord.Member)
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


async def test_startup_checks_schema_before_sync(settings, monkeypatch):
    check = AsyncMock(side_effect=RuntimeError("unmigrated"))
    monkeypatch.setattr("jdr_bot.bot.check_database", check)
    bot = TeamBot(settings, MagicMock())
    sync = AsyncMock()
    monkeypatch.setattr(bot.tree, "sync", sync)
    with pytest.raises(RuntimeError, match="unmigrated"):
        await bot.setup_hook()
    sync.assert_not_awaited()


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
