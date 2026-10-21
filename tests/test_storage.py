"""Real PostgreSQL migration, constraints, and transaction isolation checks."""

import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, ProgrammingError

from jdr_bot.startup import MIGRATION_COMMAND, SchemaOutdated
from jdr_bot.storage import SCHEMA_REVISION, check_database, create_engine


@pytest.mark.integration
async def test_postgres_migration_roundtrip_and_isolation():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL to a disposable PostgreSQL database ending in _test")
    assert (make_url(url).database or "").endswith("_test"), "refusing a non-test database"
    environment = {**os.environ, "DATABASE_URL": url}

    async def migrate(direction, revision):
        process = await asyncio.create_subprocess_exec(
            "alembic", direction, revision, env=environment
        )
        assert await process.wait() == 0

    engine = create_engine(url)
    try:
        await migrate("upgrade", "head")
        await migrate("upgrade", "head")  # Repeated setup must be safe.
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM brief_jobs"))
            await connection.execute(text("DELETE FROM reminder_jobs"))
            await connection.execute(text("DELETE FROM meetings"))
            await connection.execute(text("DELETE FROM guild_configurations"))
        await check_database(engine)
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text("INSERT INTO guild_configurations (guild_id) VALUES (123)")
            )
            created = await connection.scalar(
                text("SELECT created_at FROM guild_configurations WHERE guild_id = 123")
            )
            assert created.tzinfo is not None
            async with connection.begin_nested() as nested:
                with pytest.raises(IntegrityError):
                    await connection.execute(
                        text("INSERT INTO guild_configurations (guild_id) VALUES (123)")
                    )
                await nested.rollback()
            await transaction.rollback()
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM guild_configurations")) == 0
            await connection.execute(text("UPDATE alembic_version SET version_num = 'obsolete'"))
            await connection.commit()
        with pytest.raises(SchemaOutdated) as outdated:
            await check_database(engine)
        assert MIGRATION_COMMAND in str(outdated.value)
        assert "obsolete" not in str(outdated.value)
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE alembic_version SET version_num = :revision"),
                {"revision": SCHEMA_REVISION},
            )
        await migrate("downgrade", "base")
        with pytest.raises(ProgrammingError):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT * FROM guild_configurations"))
        with pytest.raises(ProgrammingError):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT * FROM meetings"))
        with pytest.raises(ProgrammingError):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT * FROM brief_jobs"))
        await migrate("upgrade", "head")
        await check_database(engine)
    finally:
        await engine.dispose()
