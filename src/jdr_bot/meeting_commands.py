"""Guild meeting slash commands. Authorization and presentation only."""

import logging
from collections.abc import Awaitable
from typing import Protocol

import discord
from discord import app_commands

from jdr_bot.authorization import can_manage
from jdr_bot.config import Settings
from jdr_bot.domain import MeetingError
from jdr_bot.meeting_service import MeetingService
from jdr_bot.presentation import format_meeting, format_meeting_list

logger = logging.getLogger(__name__)

_COMMAND_FAILED = "The meeting command could not be completed. Contact a maintainer."


class MeetingCommandContext(Protocol):
    settings: Settings
    meetings: MeetingService


class MeetingCommands(app_commands.Group):
    """Operator commands for meetings and reminder offsets."""

    def __init__(self, context: MeetingCommandContext) -> None:
        super().__init__(
            name="meeting",
            description="Create and manage meeting reminders",
            guild_only=True,
        )
        self._context = context
        self.add_command(
            app_commands.Command(
                name="create",
                description="Schedule a meeting and its reminders",
                callback=self.create_meeting,
            )
        )
        self.add_command(
            app_commands.Command(
                name="list",
                description="List scheduled meetings",
                callback=self.list_meetings,
            )
        )
        self.add_command(
            app_commands.Command(
                name="view",
                description="Show one meeting and its reminder states",
                callback=self.view_meeting,
            )
        )
        self.add_command(
            app_commands.Command(
                name="update",
                description="Change a scheduled meeting or its reminders",
                callback=self.update_meeting,
            )
        )
        self.add_command(
            app_commands.Command(
                name="cancel",
                description="Cancel a meeting and its pending reminders",
                callback=self.cancel_meeting,
            )
        )

    @app_commands.describe(
        title="Short meeting name, up to 100 characters",
        start="Local start time as YYYY-MM-DD HH:MM",
        text_channel="Text channel that receives reminders",
        voice_channel="Voice channel where the meeting is held",
        offsets="Comma-separated minutes before start, such as 1440,60,15",
        timezone="IANA time zone. Defaults to the configured bot time zone",
    )
    async def create_meeting(
        self,
        interaction: discord.Interaction[discord.Client],
        title: str,
        start: str,
        text_channel: discord.TextChannel,
        voice_channel: discord.VoiceChannel,
        offsets: str,
        timezone: str = "",
    ) -> None:
        if not await self._begin(interaction):
            return
        zone = timezone.strip() or self._context.settings.bot_timezone

        async def work() -> str:
            meeting = await self._context.meetings.create(
                guild_id=self._context.settings.discord_guild_id,
                organizer_id=interaction.user.id,
                title=title,
                start_text=start,
                timezone_name=zone,
                text_channel_id=text_channel.id,
                voice_channel_id=voice_channel.id,
                offsets_text=offsets,
            )
            logger.info("meeting_created meeting_id=%s", meeting.id)
            return format_meeting(meeting)

        await self._finish(interaction, "create", work())

    async def list_meetings(self, interaction: discord.Interaction[discord.Client]) -> None:
        if not await self._begin(interaction):
            return

        async def work() -> str:
            listing = await self._context.meetings.list_scheduled(
                guild_id=self._context.settings.discord_guild_id
            )
            return format_meeting_list(listing)

        await self._finish(interaction, "list", work())

    @app_commands.describe(meeting_id="Meeting id from /meeting list")
    async def view_meeting(
        self, interaction: discord.Interaction[discord.Client], meeting_id: int
    ) -> None:
        if not await self._begin(interaction):
            return

        async def work() -> str:
            meeting = await self._context.meetings.view(
                guild_id=self._context.settings.discord_guild_id, meeting_id=meeting_id
            )
            return format_meeting(meeting)

        await self._finish(interaction, "view", work())

    @app_commands.describe(
        meeting_id="Meeting id to change",
        title="New title. Omit to keep the current title",
        start="New local start as YYYY-MM-DD HH:MM. Omit to keep it",
        timezone="New IANA time zone. Also provide start",
        offsets="Replacement minute offsets, such as 60,15. Omit to keep them",
        text_channel="New reminder channel. Omit to keep it",
        voice_channel="New voice channel. Omit to keep it",
    )
    async def update_meeting(
        self,
        interaction: discord.Interaction[discord.Client],
        meeting_id: int,
        title: str = "",
        start: str = "",
        timezone: str = "",
        offsets: str = "",
        text_channel: discord.TextChannel | None = None,
        voice_channel: discord.VoiceChannel | None = None,
    ) -> None:
        if not await self._begin(interaction):
            return

        async def work() -> str:
            meeting = await self._context.meetings.update(
                guild_id=self._context.settings.discord_guild_id,
                meeting_id=meeting_id,
                title=_blank(title),
                start_text=_blank(start),
                timezone_name=_blank(timezone),
                offsets_text=_blank(offsets),
                text_channel_id=None if text_channel is None else text_channel.id,
                voice_channel_id=None if voice_channel is None else voice_channel.id,
            )
            logger.info("meeting_updated meeting_id=%s", meeting.id)
            return format_meeting(meeting)

        await self._finish(interaction, "update", work())

    @app_commands.describe(meeting_id="Meeting id to cancel")
    async def cancel_meeting(
        self, interaction: discord.Interaction[discord.Client], meeting_id: int
    ) -> None:
        if not await self._begin(interaction):
            return

        async def work() -> str:
            meeting = await self._context.meetings.cancel(
                guild_id=self._context.settings.discord_guild_id, meeting_id=meeting_id
            )
            logger.info("meeting_cancelled meeting_id=%s", meeting.id)
            return format_meeting(meeting)

        await self._finish(interaction, "cancel", work())

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
        except MeetingError as error:
            message = error.message
        except Exception as exc:
            logger.error(
                "meeting_command_failed command=%s error_type=%s", command, type(exc).__name__
            )
            message = _COMMAND_FAILED
        await interaction.followup.send(message, ephemeral=True)


def _blank(value: str) -> str | None:
    stripped = value.strip()
    if not stripped:
        return None
    return stripped
