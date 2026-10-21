"""PostgreSQL round-trip, constraints, and migration 0004 downgrade."""

import asyncio
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError

from jdr_bot.domain import NewJob, NewMeeting
from jdr_bot.guild_config import GuildConfigChange
from jdr_bot.guild_storage import SqlGuildConfigStore
from jdr_bot.storage import SCHEMA_REVISION, SqlMeetingStore, check_database, create_engine

UTC_TZ = UTC


async def migrate(url: str, direction: str = "upgrade", revision: str = "head") -> None:
    environment = {**os.environ, "DATABASE_URL": url}
    process = await asyncio.create_subprocess_exec("alembic", direction, revision, env=environment)
    assert await process.wait() == 0


async def disposable_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL to a disposable PostgreSQL database ending in _test")
    assert (make_url(url).database or "").endswith("_test"), "refusing a non-test database"
    await migrate(url)
    engine = create_engine(url)
    await clear_rows(engine)
    return url, engine


async def clear_rows(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM brief_jobs"))
        await connection.execute(text("DELETE FROM reminder_jobs"))
        await connection.execute(text("DELETE FROM meetings"))
        await connection.execute(text("DELETE FROM guild_configurations"))


@pytest.mark.integration
async def test_postgres_guild_configuration_roundtrip_and_constraints():
    url, engine = await disposable_engine()
    del url
    try:
        await check_database(engine)
        store = SqlGuildConfigStore(engine)
        assert await store.get(123) is None
        saved = await store.apply(
            123,
            GuildConfigChange(
                meetings_channel_id=10,
                brief_channel_id=11,
                timezone_name="America/Los_Angeles",
                brief_time="09:30",
            ),
        )
        assert saved == await store.get(123)
        assert saved.timezone_name == "America/Los_Angeles"
        assert saved.brief_time == "09:30"
        updated = await store.apply(123, GuildConfigChange(brief_time="10:00"))
        assert updated.meetings_channel_id == 10
        assert updated.brief_channel_id == 11
        assert updated.timezone_name == "America/Los_Angeles"
        assert updated.brief_time == "10:00"
        cleared = await store.apply(123, GuildConfigChange(clear_timezone=True))
        assert cleared.timezone_name is None
        assert cleared.brief_time == "10:00"
        async with engine.connect() as connection:
            created = await connection.scalar(
                text("SELECT created_at FROM guild_configurations WHERE guild_id = 123")
            )
        assert created is not None
        assert created.tzinfo is not None

        created_at = datetime(2026, 6, 1, 12, tzinfo=UTC_TZ)
        await SqlMeetingStore(engine).insert_meeting(
            NewMeeting(
                guild_id=123,
                title="Design review",
                text_channel_id=10,
                voice_channel_id=11,
                starts_at=datetime(2026, 6, 1, 18, tzinfo=UTC_TZ),
                timezone_name="UTC",
                organizer_id=7,
                created_at=created_at,
            ),
            (NewJob(offset_minutes=60, due_at=datetime(2026, 6, 1, 17, tzinfo=UTC_TZ)),),
        )
        preserved = await store.get(123)
        assert preserved is not None
        assert preserved.brief_time == "10:00"
        assert preserved.meetings_channel_id == 10
        assert preserved.timezone_name is None

        invalid_sql = (
            "UPDATE guild_configurations SET brief_time = '25:00' WHERE guild_id = 123",
            "UPDATE guild_configurations SET brief_time = '9:00' WHERE guild_id = 123",
            "UPDATE guild_configurations SET meetings_channel_id = -1 WHERE guild_id = 123",
            "UPDATE guild_configurations SET timezone = '' WHERE guild_id = 123",
        )
        for statement in invalid_sql:
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(text(statement))
        with pytest.raises(DataError):
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE guild_configurations SET timezone = :zone WHERE guild_id = 123"),
                    {"zone": "x" * 65},
                )
        intact = await store.get(123)
        assert intact is not None
        assert intact.brief_time == "10:00"
        assert intact.meetings_channel_id == 10
    finally:
        await clear_rows(engine)
        await engine.dispose()


@pytest.mark.integration
async def test_postgres_guild_configuration_downgrade_drops_stored_values():
    url, engine = await disposable_engine()
    try:
        await SqlGuildConfigStore(engine).apply(
            123,
            GuildConfigChange(
                timezone_name="Europe/Paris", brief_time="08:15", brief_channel_id=11
            ),
        )
        await migrate(url, "downgrade", "0003")
        with pytest.raises(ProgrammingError):
            async with engine.connect() as connection:
                await connection.execute(
                    text("SELECT meetings_channel_id FROM guild_configurations")
                )
        async with engine.connect() as connection:
            guild_id = await connection.scalar(
                text("SELECT guild_id FROM guild_configurations WHERE guild_id = 123")
            )
            await connection.execute(text("SELECT id FROM brief_jobs"))
        assert guild_id == 123
        with pytest.raises(RuntimeError, match="schema is outdated"):
            await check_database(engine)
        await migrate(url, "upgrade", "head")
        await check_database(engine)
        restored = await SqlGuildConfigStore(engine).get(123)
        assert restored is not None
        assert restored.timezone_name is None
        assert restored.brief_time is None
        assert restored.brief_channel_id is None
        async with engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == SCHEMA_REVISION
    finally:
        await migrate(url, "upgrade", "head")
        await clear_rows(engine)
        await engine.dispose()
