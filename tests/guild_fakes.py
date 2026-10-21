"""In-memory guild configuration store. It uses the same merge rules as PostgreSQL."""

from jdr_bot.guild_config import GuildConfigChange, StoredGuildConfig, merge_change


class MemoryGuildConfigStore:
    def __init__(self) -> None:
        self.rows: dict[int, StoredGuildConfig] = {}

    async def get(self, guild_id: int) -> StoredGuildConfig | None:
        return self.rows.get(guild_id)

    async def apply(self, guild_id: int, change: GuildConfigChange) -> StoredGuildConfig:
        current = self.rows.get(guild_id)
        if current is None:
            current = StoredGuildConfig(
                guild_id=guild_id,
                meetings_channel_id=None,
                brief_channel_id=None,
                timezone_name=None,
                brief_time=None,
            )
        merged = merge_change(current, change)
        self.rows[guild_id] = merged
        return merged
