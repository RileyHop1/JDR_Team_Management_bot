"""Reject unsafe configuration without leaking credentials."""

import pytest
from pydantic import ValidationError

from jdr_bot.config import Settings


def test_invalid_settings_hide_secret_values(settings):
    values = settings.model_dump()
    values["database_url"] = "invalid-secret-password"
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **values)
    assert "invalid-secret-password" not in str(error.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("discord_bot_token", ""),
        ("discord_bot_token", "replace-with-test-bot-token"),
        ("discord_guild_id", 0),
        ("discord_operator_role_id", -1),
        ("bot_timezone", "Mars/Olympus"),
        ("database_url", "sqlite:///local.db"),
    ],
)
def test_rejects_invalid_configuration(settings, field, value):
    values = settings.model_dump()
    values[field] = value
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_valid_timezone(settings):
    values = settings.model_dump()
    values["bot_timezone"] = "America/Los_Angeles"
    assert Settings(_env_file=None, **values).bot_timezone == "America/Los_Angeles"
