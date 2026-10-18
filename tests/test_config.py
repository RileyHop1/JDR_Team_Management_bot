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
    configured = Settings(_env_file=None, **values)
    assert configured.bot_timezone == "America/Los_Angeles"
    assert configured.brief_schedule() is None


def test_brief_is_off_until_the_group_is_complete(settings):
    values = settings.model_dump()
    values["jira_base_url"] = "https://example.atlassian.net"
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **values)
    message = str(error.value)
    assert "brief_channel_id" in message
    assert "jira_api_token" in message
    assert "example.atlassian.net" not in message


def test_brief_settings_hide_token_and_build_a_schedule(settings):
    values = settings.model_dump()
    values.update(
        {
            "brief_channel_id": 10,
            "brief_time": "09:00",
            "jira_base_url": "https://user:secret-pass@evil.example",
            "jira_project_key": "JDR",
            "jira_status_names": "In Progress",
            "jira_user_email": "person@example.com",
            "jira_api_token": "synthetic-jira-token",
        }
    )
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **values)
    assert "secret-pass" not in str(error.value)
    assert "synthetic-jira-token" not in str(error.value)

    values["jira_base_url"] = "https://example.atlassian.net"
    values["jira_api_token"] = "replace-with-jira-api-token"
    with pytest.raises(ValidationError) as replaced:
        Settings(_env_file=None, **values)
    assert "replace-with-jira-api-token" not in str(replaced.value)

    values["jira_api_token"] = "synthetic-jira-token"
    values["jira_jql"] = 'project = "JDR" AND summary ~ "hidden-query-text"'
    configured = Settings(_env_file=None, **values)
    schedule = configured.brief_schedule()
    assert schedule is not None
    assert schedule.channel_id == 10
    assert schedule.hour == 9
    assert schedule.weekdays_only is True
    assert schedule.jql == 'project = "JDR" AND summary ~ "hidden-query-text"'
    assert schedule.status_names is None
    assert not hasattr(schedule, "api_token")
