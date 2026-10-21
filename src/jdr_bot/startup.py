"""Fixed, secret-free startup failure categories.

Log lines are built from these categories and hints. Driver messages, tokens,
connection URLs, and the observed schema revision are not copied here.
"""

import os
from collections.abc import Mapping
from typing import ClassVar

from pydantic import ValidationError

MIGRATION_COMMAND = "uv run --env-file .env alembic upgrade head"

JIRA_SETTING_FIELDS = frozenset(
    {
        "brief_channel_id",
        "brief_time",
        "jira_base_url",
        "jira_project_key",
        "jira_status_names",
        "jira_jql",
        "jira_user_email",
        "jira_api_token",
    }
)

_BRIEF_FIELD_PREFIXES: tuple[tuple[str, str], ...] = (
    ("JIRA_BASE_URL", "jira_base_url"),
    ("JIRA_PROJECT_KEY", "jira_project_key"),
    ("JIRA_USER_EMAIL", "jira_user_email"),
    ("JIRA_JQL", "jira_jql"),
    ("JIRA_STATUS_NAMES", "jira_status_names"),
    ("BRIEF_TIME", "brief_time"),
    ("brief_channel_id", "brief_channel_id"),
    ("set JIRA_STATUS_NAMES", "jira_status_names"),
    ("use an IANA time zone", "bot_timezone"),
)


class StartupFailure(RuntimeError):
    """A known startup failure whose text is safe to log."""

    category: ClassVar[str] = "startup_failed"
    hint: ClassVar[str] = "check credentials, connectivity, permissions, and migrations"
    exit_code: ClassVar[int] = 1

    def __init__(self, fields: tuple[str, ...] = ()) -> None:
        self.fields = fields
        if fields:
            message = f"{self.category} fields={','.join(fields)}; {self.hint}"
        else:
            message = f"{self.category}; {self.hint}"
        super().__init__(message)


class InvalidConfiguration(StartupFailure):
    """Core settings were missing or rejected. Exit code 2."""

    category: ClassVar[str] = "invalid_configuration"
    hint: ClassVar[str] = "check .env.example"
    exit_code: ClassVar[int] = 2


class InvalidJiraConfiguration(StartupFailure):
    """The morning-brief group was partial or rejected. Exit code 2."""

    category: ClassVar[str] = "invalid_jira_configuration"
    hint: ClassVar[str] = "check .env.example"
    exit_code: ClassVar[int] = 2


class DatabaseUnreachable(StartupFailure):
    """PostgreSQL could not be used. The driver message is not included."""

    category: ClassVar[str] = "database_unreachable"
    hint: ClassVar[str] = "confirm PostgreSQL is running and the configured role can connect"


class SchemaOutdated(StartupFailure):
    """The database is reachable but not at the expected Alembic revision."""

    category: ClassVar[str] = "schema_outdated"
    hint: ClassVar[str] = f"the database schema is outdated; run {MIGRATION_COMMAND}"


class DiscordLoginFailed(StartupFailure):
    """Discord rejected the bot token. The token is not included."""

    category: ClassVar[str] = "discord_login_failed"
    hint: ClassVar[str] = "set DISCORD_BOT_TOKEN to the bot token from the Discord developer portal"


class GuildSyncForbidden(StartupFailure):
    """Guild command sync was forbidden. The response body is not included."""

    category: ClassVar[str] = "guild_sync_forbidden"
    hint: ClassVar[str] = (
        "install the bot in DISCORD_GUILD_ID with the bot and applications.commands scopes"
    )


def configuration_failure(error: ValidationError) -> StartupFailure:
    """Classify a settings error from field names only.

    Inputs and messages are ignored. They can contain tokens, URLs, and other
    submitted values. Brief-group failures that ``Settings`` raises directly
    are already ``InvalidJiraConfiguration``.
    """
    names: set[str] = set()
    for item in error.errors():
        location = item["loc"]
        if not location:
            continue
        names.add(str(location[0]))
    fields = tuple(sorted(names))
    if fields and all(name in JIRA_SETTING_FIELDS for name in fields):
        return InvalidJiraConfiguration(fields)
    return InvalidConfiguration(fields)


def brief_field_for_message(message: str) -> str:
    """Map one of our fixed validator messages to a setting name.

    The message itself is not returned. An unrecognized message becomes
    ``jira_configuration`` so a future message that includes a value cannot
    be copied into the log.
    """
    for prefix, field in _BRIEF_FIELD_PREFIXES:
        if message.startswith(prefix):
            return field
    return "jira_configuration"


def require_database_url(environment: Mapping[str, str] | None = None) -> str:
    """Return ``DATABASE_URL`` or stop before Alembic connects.

    Alembic does not load ``.env``. The URL is returned to the caller and is
    not included in the error.
    """
    values = os.environ if environment is None else environment
    database_url = values.get("DATABASE_URL")
    if database_url is None or not database_url.strip():
        raise SystemExit(f"DATABASE_URL is not set. Run migrations with: {MIGRATION_COMMAND}")
    return database_url
