"""PostgreSQL persistence for non-secret guild settings."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from jdr_bot.guild_config import GuildConfigChange, StoredGuildConfig, merge_change
from jdr_bot.storage import GuildConfiguration


class SqlGuildConfigStore:
    """Transactional guild-configuration persistence."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def get(self, guild_id: int) -> StoredGuildConfig | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(GuildConfiguration).where(GuildConfiguration.guild_id == guild_id)
            )
        if row is None:
            return None
        return _stored(row)

    async def apply(self, guild_id: int, change: GuildConfigChange) -> StoredGuildConfig:
        async with self._sessions() as session, session.begin():
            await session.execute(
                pg_insert(GuildConfiguration)
                .values(guild_id=guild_id)
                .on_conflict_do_nothing(index_elements=[GuildConfiguration.guild_id])
            )
            row = await session.scalar(
                select(GuildConfiguration)
                .where(GuildConfiguration.guild_id == guild_id)
                .with_for_update()
            )
            if row is None:
                raise RuntimeError("guild configuration row was not created")
            merged = merge_change(_stored(row), change)
            row.meetings_channel_id = merged.meetings_channel_id
            row.brief_channel_id = merged.brief_channel_id
            row.timezone_name = merged.timezone_name
            row.brief_time = merged.brief_time
            await session.flush()
            return _stored(row)


def _stored(row: GuildConfiguration) -> StoredGuildConfig:
    return StoredGuildConfig(
        guild_id=row.guild_id,
        meetings_channel_id=row.meetings_channel_id,
        brief_channel_id=row.brief_channel_id,
        timezone_name=row.timezone_name,
        brief_time=row.brief_time,
    )
