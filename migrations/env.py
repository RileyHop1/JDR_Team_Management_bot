"""Migration runner; needs only DATABASE_URL, not Discord credentials."""

import asyncio
import os

from alembic import context
from sqlalchemy.engine import Connection

from jdr_bot.storage import Base, create_engine


def migrate(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def online() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=os.environ["DATABASE_URL"], target_metadata=Base.metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
