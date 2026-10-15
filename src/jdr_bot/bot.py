"""Discord boundaries: guild-scoped commands and resource ownership."""

import logging

import discord
from discord import app_commands
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from jdr_bot.authorization import can_manage
from jdr_bot.config import Settings
from jdr_bot.storage import check_database

logger = logging.getLogger(__name__)


class TeamBot(discord.Client):
    """Single-guild bot with no message-content or privileged member intent."""

    def __init__(self, settings: Settings, engine: AsyncEngine) -> None:
        intents = discord.Intents.none()
        # Member.roles resolves IDs through the guild role cache, populated by this intent.
        intents.guilds = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.settings = settings
        self.engine = engine
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

    async def setup_hook(self) -> None:
        """Fail startup on database errors; register commands only in the selected guild."""
        await check_database(self.engine)
        await self.tree.sync(guild=self.guild)
        logger.info("guild_commands_registered")

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
