"""Migration runner; needs only DATABASE_URL, not Discord credentials.

Alembic does not load ``.env``. ``require_database_url`` stops with a fixed
hint when the variable is missing instead of raising ``KeyError``.
"""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection

from jdr_bot.brief_storage import BriefJobRow
from jdr_bot.startup import require_database_url
from jdr_bot.storage import Base, create_engine


def migrate(connection: Connection) -> None:
    if BriefJobRow.__tablename__ not in Base.metadata.tables:
        raise RuntimeError("brief job table is not registered")
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def online(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()


database_url = require_database_url()
if context.is_offline_mode():
    context.configure(url=database_url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online(database_url))
