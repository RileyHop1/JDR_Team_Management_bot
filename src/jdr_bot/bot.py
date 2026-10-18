"""Discord boundaries: guild-scoped commands and resource ownership."""

import asyncio
import logging

import discord
from discord import app_commands
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from jdr_bot.authorization import can_manage
from jdr_bot.config import Settings
from jdr_bot.discord_adapters import DiscordChannelDirectory, DiscordReminderDelivery
from jdr_bot.meeting_commands import MeetingCommands
from jdr_bot.meeting_service import MeetingService
from jdr_bot.ports import ReminderRunner, SystemClock
from jdr_bot.reminder_scheduler import ReminderScheduler
from jdr_bot.storage import SqlMeetingStore, check_database

logger = logging.getLogger(__name__)


class TeamBot(discord.Client):
    """Single-guild bot with no message-content or privileged member intent."""

    def __init__(
        self,
        settings: Settings,
        engine: AsyncEngine,
        *,
        meetings: MeetingService | None = None,
        scheduler: ReminderRunner | None = None,
    ) -> None:
        intents = discord.Intents.none()
        # Member.roles resolves IDs through the guild role cache, populated by this intent.
        intents.guilds = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.settings = settings
        self.engine = engine
        self._closing = False
        self._scheduler_task: asyncio.Task[None] | None = None
        store = SqlMeetingStore(engine)
        clock = SystemClock()
        self.meetings = (
            meetings
            if meetings is not None
            else MeetingService(store, DiscordChannelDirectory(self), clock)
        )
        self.scheduler = (
            scheduler
            if scheduler is not None
            else ReminderScheduler(store, DiscordReminderDelivery(self), clock)
        )
        self.tree = app_commands.CommandTree(self)
        self.guild = discord.Object(id=settings.discord_guild_id)
        self.tree.add_command(
            app_commands.Command(
                name="ping", description="Check bot responsiveness", callback=self.ping
            ),
            guild=self.guild,
        )
        self.tree.add_command(
            app_commands.Command(
                name="status",
                description="Check database readiness (operators)",
                callback=self.operator_status,
            ),
            guild=self.guild,
        )
        self.tree.add_command(MeetingCommands(self), guild=self.guild)

    async def setup_hook(self) -> None:
        """Fail startup on database errors; register commands only in the selected guild."""
        await check_database(self.engine)
        self._start_scheduler()
        try:
            await self.tree.sync(guild=self.guild)
        except Exception:
            await self._stop_scheduler()
            raise
        logger.info("guild_commands_registered")

    async def on_ready(self) -> None:
        """Restart the scheduler if it stopped while the gateway reconnects."""
        self._start_scheduler()

    async def close(self) -> None:
        """Cancel the reminder task before closing the Discord connection."""
        self._closing = True
        await self._stop_scheduler()
        await super().close()

    def _start_scheduler(self) -> None:
        if self._closing:
            return
        current = self._scheduler_task
        if current is not None and not current.done():
            return
        task = asyncio.create_task(self.scheduler.serve(), name="reminder-scheduler")
        task.add_done_callback(self._watch_scheduler)
        self._scheduler_task = task
        logger.info("reminder_scheduler_started")

    async def _stop_scheduler(self) -> None:
        task = self._scheduler_task
        if task is None:
            return
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self._scheduler_task = None

    def _watch_scheduler(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            logger.info("reminder_scheduler_stopped")
            return
        error = task.exception()
        if error is not None:
            logger.error("reminder_scheduler_stopped error_type=%s", type(error).__name__)

    async def ping(self, interaction: discord.Interaction[discord.Client]) -> None:
        """Reply privately to a guild-scoped responsiveness check."""
        if interaction.guild_id != self.settings.discord_guild_id:
            await interaction.response.send_message(
                "This server is not configured.", ephemeral=True
            )
            return
        await interaction.response.send_message("Pong!", ephemeral=True)

    async def operator_status(self, interaction: discord.Interaction[discord.Client]) -> None:
        """Authorize before touching storage; acknowledge before network work."""
        roles = (
            [role.id for role in interaction.user.roles]
            if isinstance(interaction.user, discord.Member)
            else []
        )
        if not can_manage(
            guild_id=interaction.guild_id,
            allowed_guild_id=self.settings.discord_guild_id,
            role_ids=roles,
            operator_role_id=self.settings.discord_operator_role_id,
        ):
            await interaction.response.send_message("Operator role required.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await check_database(self.engine)
        except (SQLAlchemyError, RuntimeError):
            # Never emit driver exceptions: connection details may contain credentials.
            logger.error("database_readiness_failed")
            await interaction.followup.send(
                "Database unavailable; contact a maintainer.", ephemeral=True
            )
        else:
            await interaction.followup.send("Database ready.", ephemeral=True)
