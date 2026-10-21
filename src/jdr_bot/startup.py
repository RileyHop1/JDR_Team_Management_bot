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

# Logged when a brief error does not carry one of the known setting names.
UNKNOWN_BRIEF_FIELD = "jira_configuration"
# A zone failure is core configuration, not an invalid Jira brief setting.
ZONE_FIELD = "bot_timezone"
_BRIEF_ERROR_FIELDS = JIRA_SETTING_FIELDS | {ZONE_FIELD}


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


class DatabasePermissionDenied(StartupFailure):
    """The role can connect but cannot read the schema. The driver message is omitted."""

    category: ClassVar[str] = "database_permission_denied"
    hint: ClassVar[str] = (
        "the database role can connect but cannot read the schema; grant it access to the tables"
    )


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


class BriefSettingError(ValueError):
    """A brief setting was rejected. ``field`` is a fixed name, not the value.

    An unknown name is stored as ``jira_configuration`` so a value cannot
    become the logged field. The message is for developers and is not logged.
    """

    def __init__(self, field: str, message: str) -> None:
        self.field = field if field in _BRIEF_ERROR_FIELDS else UNKNOWN_BRIEF_FIELD
        super().__init__(message)


def failure_for_brief_setting(error: Exception) -> StartupFailure:
    """Map a brief validation error using the field carried on the error.

    ``bot_timezone`` is ``invalid_configuration``. A known brief field is
    ``invalid_jira_configuration``. Any other error, including a ``ValueError``
    that does not carry a field, uses ``fields=jira_configuration`` and does
    not copy the exception message.
    """
    if isinstance(error, BriefSettingError):
        if error.field == ZONE_FIELD:
            return InvalidConfiguration((ZONE_FIELD,))
        if error.field in JIRA_SETTING_FIELDS:
            return InvalidJiraConfiguration((error.field,))
    return InvalidJiraConfiguration((UNKNOWN_BRIEF_FIELD,))


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
