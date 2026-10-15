"""Database lifecycle and schema readiness checks."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA_REVISION = "0001"


class Base(DeclarativeBase):
    """Shared migration metadata."""


class GuildConfiguration(Base):
    """Guild identity reserved for future persistent scheduling configuration."""

    __tablename__ = "guild_configurations"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def create_engine(database_url: str) -> AsyncEngine:
    """Create a bounded pool without connecting or exposing parameters in errors."""
    return create_async_engine(
        database_url,
        pool_size=5,
        max_overflow=0,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"connect_timeout": 10, "options": "-c statement_timeout=10000"},
    )


async def check_database(engine: AsyncEngine) -> None:
    """Verify connectivity and migration revision before registering commands."""
    async with engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != SCHEMA_REVISION:
            raise RuntimeError("database schema is outdated; run uv run alembic upgrade head")
