"""Validated process configuration; secret values must never be logged."""

from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from jdr_bot.brief import BriefSchedule, compile_schedule, validated_email
from jdr_bot.guild_config import EnvGuildDefaults, StoredGuildConfig
from jdr_bot.policy import MAX_TIMEZONE_LENGTH


class Settings(BaseSettings):
    """Initial single-guild deployment settings, read from environment or local .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    discord_bot_token: SecretStr
    discord_guild_id: int = Field(gt=0)
    discord_operator_role_id: int = Field(gt=0)
    database_url: SecretStr
    bot_timezone: str = "UTC"
    meetings_channel_id: int | None = None
    brief_channel_id: int | None = None
    brief_time: str | None = None
    jira_base_url: str | None = None
    jira_project_key: str | None = None
    jira_status_names: str | None = None
    jira_jql: str | None = None
    jira_user_email: str | None = None
    jira_api_token: SecretStr | None = None

    @field_validator("discord_bot_token")
    @classmethod
    def require_token(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip() or value.get_secret_value().startswith("replace-"):
            raise ValueError("set a real test bot token in secure configuration")
        return value

    @field_validator("database_url")
    @classmethod
    def require_postgres(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("use a valid PostgreSQL connection URL") from None
        if url.drivername != "postgresql+psycopg" or not url.database:
            raise ValueError("use postgresql+psycopg with an explicit database name")
        return value

    @field_validator("bot_timezone")
    @classmethod
    def require_timezone(cls, value: str) -> str:
        _require_zone(value)
        return value

    @field_validator("meetings_channel_id")
    @classmethod
    def require_meetings_channel(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value <= 0 or value >= 2**63:
            raise ValueError("meetings_channel_id must be a positive Discord channel id")
        return value

    @field_validator("brief_channel_id", "meetings_channel_id", mode="before")
    @classmethod
    def blank_channel(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "brief_time",
        "jira_base_url",
        "jira_project_key",
        "jira_status_names",
        "jira_jql",
        "jira_user_email",
        mode="before",
    )
    @classmethod
    def blank_optional(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("jira_api_token", mode="before")
    @classmethod
    def blank_token(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        if isinstance(value, SecretStr) and not value.get_secret_value().strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_brief_group(self) -> Self:
        """Require the whole brief group, or none of it. Messages omit values."""
        if not _brief_requested(self):
            return self
        missing = [
            name
            for name, present in (
                ("brief_channel_id", self.brief_channel_id is not None),
                ("brief_time", self.brief_time is not None),
                ("jira_base_url", self.jira_base_url is not None),
                ("jira_project_key", self.jira_project_key is not None),
                ("jira_user_email", self.jira_user_email is not None),
                ("jira_api_token", self.jira_api_token is not None),
            )
            if not present
        ]
        if self.jira_jql is None and self.jira_status_names is None:
            missing.append("jira_status_names")
        if missing:
            raise ValueError("missing brief settings: " + ", ".join(missing))
        token = self.jira_api_token
        channel_id = self.brief_channel_id
        brief_time = self.brief_time
        base_url = self.jira_base_url
        project_key = self.jira_project_key
        email = self.jira_user_email
        if (
            token is None
            or channel_id is None
            or brief_time is None
            or base_url is None
            or project_key is None
            or email is None
            or token.get_secret_value().startswith("replace-")
        ):
            raise ValueError("set a real Jira API token in secure configuration")
        validated_email(email)
        compile_schedule(
            guild_id=self.discord_guild_id,
            channel_id=channel_id,
            timezone_name=self.bot_timezone,
            brief_time=brief_time,
            base_url=base_url,
            project_key=project_key,
            status_names=self.jira_status_names,
            custom_jql=self.jira_jql,
        )
        return self

    def guild_defaults(self) -> EnvGuildDefaults:
        """Environment fallback for fields the guild row has not stored."""
        return EnvGuildDefaults(
            timezone_name=self.bot_timezone,
            meetings_channel_id=self.meetings_channel_id,
            brief_channel_id=self.brief_channel_id,
            brief_time=self.brief_time,
        )

    def brief_schedule(self, guild: StoredGuildConfig | None = None) -> BriefSchedule | None:
        """Build the brief schedule from stored non-secret fields, then the environment.

        A missing row, or a null field on that row, uses the environment value.
        A stored non-null field replaces only that field. A row for a different
        guild is ignored. Credentials stay in the environment and are not part
        of the schedule. None leaves the brief off.
        """
        channel_id = self.brief_channel_id
        brief_time = self.brief_time
        timezone_name = self.bot_timezone
        if guild is not None and guild.guild_id == self.discord_guild_id:
            if guild.brief_channel_id is not None:
                channel_id = guild.brief_channel_id
            if guild.brief_time is not None:
                brief_time = guild.brief_time
            if guild.timezone_name is not None:
                _require_zone(guild.timezone_name)
                timezone_name = guild.timezone_name
        base_url = self.jira_base_url
        project_key = self.jira_project_key
        email = self.jira_user_email
        if (
            channel_id is None
            or brief_time is None
            or base_url is None
            or project_key is None
            or email is None
            or self.jira_api_token is None
        ):
            return None
        return compile_schedule(
            guild_id=self.discord_guild_id,
            channel_id=channel_id,
            timezone_name=timezone_name,
            brief_time=brief_time,
            base_url=base_url,
            project_key=project_key,
            status_names=self.jira_status_names,
            custom_jql=self.jira_jql,
        )


def _require_zone(value: str) -> None:
    if not value or len(value) > MAX_TIMEZONE_LENGTH:
        raise ValueError("use an IANA time zone such as America/Los_Angeles")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("use an IANA time zone such as America/Los_Angeles") from None


def _brief_requested(settings: Settings) -> bool:
    token = settings.jira_api_token
    return any(
        (
            settings.brief_channel_id is not None,
            settings.brief_time is not None,
            settings.jira_base_url is not None,
            settings.jira_project_key is not None,
            settings.jira_status_names is not None,
            settings.jira_jql is not None,
            settings.jira_user_email is not None,
            token is not None and bool(token.get_secret_value().strip()),
        )
    )
