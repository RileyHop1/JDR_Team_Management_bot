"""Reject unsafe configuration without leaking credentials."""

import pytest
from pydantic import ValidationError

from jdr_bot.config import Settings
from jdr_bot.guild_config import StoredGuildConfig
from jdr_bot.startup import InvalidJiraConfiguration


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
    with pytest.raises(InvalidJiraConfiguration) as error:
        Settings(_env_file=None, **values)
    message = str(error.value)
    assert error.value.category == "invalid_jira_configuration"
    assert "brief_channel_id" in error.value.fields
    assert "jira_api_token" in error.value.fields
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
    with pytest.raises(InvalidJiraConfiguration) as error:
        Settings(_env_file=None, **values)
    assert error.value.fields == ("jira_base_url",)
    assert "secret-pass" not in str(error.value)
    assert "synthetic-jira-token" not in str(error.value)
    assert error.value.__cause__ is not None
    assert "secret-pass" not in str(error.value.__cause__)
    assert "synthetic-jira-token" not in str(error.value.__cause__)

    values["jira_base_url"] = "https://example.atlassian.net"
    values["jira_api_token"] = "replace-with-jira-api-token"
    with pytest.raises(InvalidJiraConfiguration) as replaced:
        Settings(_env_file=None, **values)
    assert replaced.value.fields == ("jira_api_token",)
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
    assert "synthetic-jira-token" not in repr(schedule)

    stored = StoredGuildConfig(
        guild_id=configured.discord_guild_id,
        meetings_channel_id=15,
        brief_channel_id=77,
        timezone_name="Europe/Paris",
        brief_time="11:11",
    )
    overridden = configured.brief_schedule(stored)
    assert overridden is not None
    assert overridden.channel_id == 77
    assert overridden.hour == 11
    assert overridden.minute == 11
    assert overridden.timezone_name == "Europe/Paris"
    assert overridden.jql == schedule.jql
    assert "synthetic-jira-token" not in repr(overridden)

    partial = StoredGuildConfig(
        guild_id=configured.discord_guild_id,
        meetings_channel_id=None,
        brief_channel_id=None,
        timezone_name=None,
        brief_time="08:15",
    )
    mixed = configured.brief_schedule(partial)
    assert mixed is not None
    assert mixed.channel_id == 10
    assert mixed.hour == 8
    assert mixed.minute == 15
    assert mixed.timezone_name == configured.bot_timezone

    other_guild = StoredGuildConfig(
        guild_id=999,
        meetings_channel_id=5,
        brief_channel_id=77,
        timezone_name="Europe/Paris",
        brief_time="11:11",
    )
    ignored = configured.brief_schedule(other_guild)
    assert ignored is not None
    assert ignored.channel_id == 10
    assert ignored.hour == 9
    assert ignored.timezone_name == configured.bot_timezone

    invalid = StoredGuildConfig(
        guild_id=configured.discord_guild_id,
        meetings_channel_id=None,
        brief_channel_id=77,
        timezone_name="synthetic-secret-zone",
        brief_time="11:11",
    )
    with pytest.raises(ValueError) as rejected:
        configured.brief_schedule(invalid)
    assert "synthetic-secret-zone" not in str(rejected.value)
    assert "synthetic-jira-token" not in str(rejected.value)


def test_meetings_channel_does_not_enable_the_brief(settings):
    values = settings.model_dump()
    values["meetings_channel_id"] = ""
    assert Settings(_env_file=None, **values).meetings_channel_id is None
    values["meetings_channel_id"] = 10
    configured = Settings(_env_file=None, **values)
    assert configured.meetings_channel_id == 10
    assert configured.brief_schedule() is None
    values["meetings_channel_id"] = 0
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **values)
    assert "meetings_channel_id" in str(error.value)
