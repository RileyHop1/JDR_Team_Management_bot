"""Validated process configuration; secret values must never be logged."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    """Initial single-guild deployment settings, read from environment or local .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    discord_bot_token: SecretStr
    discord_guild_id: int = Field(gt=0)
    discord_operator_role_id: int = Field(gt=0)
    database_url: SecretStr
    bot_timezone: str = "UTC"

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
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("use an IANA time zone such as America/Los_Angeles") from None
        return value
