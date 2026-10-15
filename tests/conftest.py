"""Explicit, synthetic settings independent of a developer's local .env."""

import pytest

from jdr_bot.config import Settings


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        discord_bot_token="synthetic-test-token",
        discord_guild_id=123,
        discord_operator_role_id=456,
        database_url="postgresql+psycopg://jdr:jdr@localhost/jdr_test",
    )
