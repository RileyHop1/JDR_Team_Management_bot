"""Operator commands for per-guild settings. Authorization and presentation only."""

import logging
from collections.abc import Awaitable
from typing import Literal, Protocol

import discord
from discord import app_commands

from jdr_bot.authorization import can_manage
from jdr_bot.config import Settings
from jdr_bot.guild_config import (
    ConfigError,
    GuildConfigService,
    change_from_command,
    format_guild_config,
)

logger = logging.getLogger(__name__)

_COMMAND_FAILED = "The config command could not be completed. Contact a maintainer."
_SAVED = (
    "Guild configuration saved.\n"
    "The next morning-brief poll uses the current brief channel, time, and time zone "
    "for future brief jobs. Meetings already scheduled keep their time zone and channels."
)
_ClearField = Literal["meetings_channel", "brief_channel", "timezone", "brief_time"]


class ConfigCommandContext(Protocol):
    settings: Settings
    guild_config: GuildConfigService


class ConfigCommands(app_commands.Group):
    """Operator commands that view and update non-secret guild settings."""

    def __init__(self, context: ConfigCommandContext) -> None:
        super().__init__(
            name="config",
            description="View and update guild schedule settings",
            guild_only=True,
        )
        self._context = context
        self.add_command(
            app_commands.Command(
                name="view",
                description="Show the guild time zone, channels, and brief time",
                callback=self.view_config,
            )
        )
        self.add_command(
            app_commands.Command(
                name="set",
                description="Update the guild time zone, channels, or brief time",
                callback=self.set_config,
            )
        )

    async def view_config(self, interaction: discord.Interaction[discord.Client]) -> None:
        if not await self._begin(interaction):
            return

        async def work() -> str:
            view = await self._context.guild_config.view(self._context.settings.discord_guild_id)
            return "Guild configuration\n" + format_guild_config(view)

        await self._finish(interaction, "view", work())

    @app_commands.describe(
        meetings_channel="Text channel for the meetings destination",
        brief_channel="Text channel that receives the morning brief",
        timezone="IANA time zone, such as America/Los_Angeles",
        brief_time="Local brief time as HH:MM in 24-hour time",
        clear="Remove one stored override and use the environment default again",
    )
    async def set_config(
        self,
        interaction: discord.Interaction[discord.Client],
        meetings_channel: discord.TextChannel | None = None,
        brief_channel: discord.TextChannel | None = None,
        timezone: str = "",
        brief_time: str = "",
        clear: _ClearField | None = None,
    ) -> None:
        if not await self._begin(interaction):
            return

        async def work() -> str:
            change = change_from_command(
                meetings_channel_id=None if meetings_channel is None else meetings_channel.id,
                brief_channel_id=None if brief_channel is None else brief_channel.id,
                timezone_name=_blank(timezone),
                brief_time=_blank(brief_time),
                clear=clear,
            )
            view = await self._context.guild_config.update(
                self._context.settings.discord_guild_id, change
            )
            return _SAVED + "\n" + format_guild_config(view)

        await self._finish(interaction, "set", work())

    async def _begin(self, interaction: discord.Interaction[discord.Client]) -> bool:
        user = interaction.user
        roles = [role.id for role in user.roles] if isinstance(user, discord.Member) else []
        allowed = can_manage(
            guild_id=interaction.guild_id,
            allowed_guild_id=self._context.settings.discord_guild_id,
            role_ids=roles,
            operator_role_id=self._context.settings.discord_operator_role_id,
        )
        if not allowed:
            await interaction.response.send_message("Operator role required.", ephemeral=True)
            return False
        await interaction.response.defer(ephemeral=True)
        return True

    async def _finish(
        self,
        interaction: discord.Interaction[discord.Client],
        command: str,
        work: Awaitable[str],
    ) -> None:
        try:
            message = await work
        except ConfigError as error:
            message = error.message
        except Exception as exc:
            logger.error(
                "config_command_failed command=%s error_type=%s", command, type(exc).__name__
            )
            message = _COMMAND_FAILED
        await interaction.followup.send(message, ephemeral=True)


def _blank(value: str) -> str | None:
    stripped = value.strip()
    if not stripped:
        return None
    return stripped
