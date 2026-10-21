"""Startup categories are actionable and never echo synthetic secrets."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError, ProgrammingError

from jdr_bot.__main__ import main, run
from jdr_bot.bot import TeamBot
from jdr_bot.config import Settings
from jdr_bot.startup import (
    MIGRATION_COMMAND,
    DatabaseUnreachable,
    DiscordLoginFailed,
    GuildSyncForbidden,
    InvalidConfiguration,
    InvalidJiraConfiguration,
    SchemaOutdated,
    StartupFailure,
    brief_field_for_message,
    configuration_failure,
    require_database_url,
)
from jdr_bot.storage import SCHEMA_REVISION, check_database, create_engine

SECRETS = (
    "synthetic-discord-token",
    "synthetic-db-password",
    "synthetic-jira-token",
)
SECRET_TEXT = " ".join(SECRETS)
ROOT = Path(__file__).resolve().parents[1]


def assert_no_secrets(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text


class RevisionConnection:
    def __init__(self, revision: str | None) -> None:
        self.revision = revision

    async def __aenter__(self) -> "RevisionConnection":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def scalar(self, _statement: object) -> str | None:
        return self.revision


class RevisionEngine:
    def __init__(self, revision: str | None) -> None:
        self.revision = revision

    def connect(self) -> RevisionConnection:
        return RevisionConnection(self.revision)


class ExplodingEngine:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def connect(self) -> None:
        raise self.error


class IdleScheduler:
    async def serve(self) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise


class SimpleEngine:
    def __init__(self) -> None:
        self.dispose = AsyncMock()


def driver_error(kind: type[OperationalError] | type[ProgrammingError]) -> Exception:
    return kind("SELECT version_num FROM alembic_version", {}, Exception(SECRET_TEXT))


def test_configuration_failure_uses_field_names_only():
    jira_error = ValidationError.from_exception_data(
        Settings.__name__,
        [
            {
                "type": "string_type",
                "loc": ("jira_api_token",),
                "input": "synthetic-jira-token",
            }
        ],
    )
    jira_failure = configuration_failure(jira_error)
    assert isinstance(jira_failure, InvalidJiraConfiguration)
    assert jira_failure.fields == ("jira_api_token",)
    assert jira_failure.exit_code == 2
    assert_no_secrets(str(jira_failure))

    mixed = ValidationError.from_exception_data(
        Settings.__name__,
        [
            {
                "type": "int_parsing",
                "loc": ("discord_guild_id",),
                "input": "synthetic-discord-token",
            },
            {
                "type": "string_type",
                "loc": ("database_url",),
                "input": "synthetic-db-password",
            },
        ],
    )
    config_failure = configuration_failure(mixed)
    assert isinstance(config_failure, InvalidConfiguration)
    assert config_failure.fields == ("database_url", "discord_guild_id")
    assert_no_secrets(str(config_failure))

    unnamed = ValidationError.from_exception_data(
        Settings.__name__,
        [
            {
                "type": "value_error",
                "loc": (),
                "input": SECRET_TEXT,
                "ctx": {"error": ValueError(SECRET_TEXT)},
            }
        ],
    )
    unnamed_failure = configuration_failure(unnamed)
    assert isinstance(unnamed_failure, InvalidConfiguration)
    assert unnamed_failure.fields == ()
    assert_no_secrets(str(unnamed_failure))


def test_brief_field_mapping_does_not_return_the_message():
    assert brief_field_for_message("JIRA_BASE_URL synthetic-jira-token") == "jira_base_url"
    assert brief_field_for_message("JIRA_JQL synthetic-jira-token") == "jira_jql"
    assert brief_field_for_message(f"rejected {SECRET_TEXT}") == "jira_configuration"
    assert_no_secrets(str(InvalidJiraConfiguration(("jira_configuration",))))


def test_require_database_url_names_the_env_file_command():
    with pytest.raises(SystemExit) as missing:
        require_database_url({})
    assert (
        missing.value.code == f"DATABASE_URL is not set. Run migrations with: {MIGRATION_COMMAND}"
    )
    with pytest.raises(SystemExit) as blank:
        require_database_url({"DATABASE_URL": "   "})
    assert_no_secrets(str(blank.value))
    url = "postgresql+psycopg://jdr:synthetic-db-password@127.0.0.1/jdr_test"
    assert require_database_url({"DATABASE_URL": url}) == url


def test_alembic_missing_database_url_is_explicit():
    environment = os_environ_without_database_url()
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "KeyError" not in output
    assert "DATABASE_URL is not set" in output
    assert MIGRATION_COMMAND in output
    assert_no_secrets(output)


def os_environ_without_database_url() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("DATABASE_URL", None)
    return environment


@pytest.mark.parametrize(
    ("failure", "category", "exit_code"),
    [
        (
            InvalidJiraConfiguration(("jira_api_token", "jira_base_url")),
            "invalid_jira_configuration",
            2,
        ),
        (SchemaOutdated(), "schema_outdated", 1),
        (DatabaseUnreachable(), "database_unreachable", 1),
        (DiscordLoginFailed(), "discord_login_failed", 1),
        (GuildSyncForbidden(), "guild_sync_forbidden", 1),
    ],
)
def test_main_logs_category_and_hides_cause(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    settings: Settings,
    failure: StartupFailure,
    category: str,
    exit_code: int,
) -> None:
    secret_error = RuntimeError(SECRET_TEXT)

    def load_settings() -> Settings:
        if isinstance(failure, InvalidJiraConfiguration):
            raise failure from secret_error
        return settings

    async def fail_run(_settings: Settings) -> None:
        raise failure from secret_error

    monkeypatch.setattr("jdr_bot.__main__.Settings", load_settings)
    monkeypatch.setattr("jdr_bot.__main__.run", fail_run)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == exit_code
    assert category in caplog.text
    assert "startup_failed" not in caplog.text
    if isinstance(failure, SchemaOutdated):
        assert MIGRATION_COMMAND in caplog.text
    assert_no_secrets(caplog.text)
    assert all(record.exc_info is None for record in caplog.records)


def test_main_unexpected_failure_logs_type_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, settings: Settings
) -> None:
    def load_settings() -> Settings:
        return settings

    async def fail_run(_settings: Settings) -> None:
        raise RuntimeError(SECRET_TEXT)

    monkeypatch.setattr("jdr_bot.__main__.Settings", load_settings)
    monkeypatch.setattr("jdr_bot.__main__.run", fail_run)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert "startup_failed error_type=RuntimeError" in caplog.text
    assert_no_secrets(caplog.text)
    assert all(record.exc_info is None for record in caplog.records)


def test_main_invalid_configuration_hides_submitted_values(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _set_core_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "synthetic-db-password")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "synthetic-discord-token")
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "invalid_configuration" in caplog.text
    assert "database_url" in caplog.text
    assert_no_secrets(caplog.text)


def test_main_invalid_jira_configuration_hides_tokens_and_query(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _set_core_env(monkeypatch)
    monkeypatch.setenv("BRIEF_CHANNEL_ID", "10")
    monkeypatch.setenv("BRIEF_TIME", "09:00")
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "JDR")
    monkeypatch.setenv("JIRA_STATUS_NAMES", "In Progress")
    monkeypatch.setenv("JIRA_USER_EMAIL", "person@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "synthetic-jira-token")
    monkeypatch.setenv("JIRA_JQL", 'summary ~ "synthetic-discord-token"\nsynthetic-jira-token')
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "invalid_jira_configuration" in caplog.text
    assert "jira_jql" in caplog.text
    assert "person@example.com" not in caplog.text
    assert_no_secrets(caplog.text)
    assert all(record.exc_info is None for record in caplog.records)


def test_main_partial_jira_group_names_missing_fields(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _set_core_env(monkeypatch)
    monkeypatch.setenv("JIRA_BASE_URL", "https://user:synthetic-jira-token@evil.example/secret")
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "invalid_jira_configuration" in caplog.text
    assert "brief_channel_id" in caplog.text
    assert "jira_api_token" in caplog.text
    assert "evil.example" not in caplog.text
    assert_no_secrets(caplog.text)


def _set_core_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "synthetic-discord-token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123")
    monkeypatch.setenv("DISCORD_OPERATOR_ROLE_ID", "456")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://jdr:synthetic-db-password@127.0.0.1:5432/jdr_test",
    )
    monkeypatch.setenv("BOT_TIMEZONE", "UTC")


async def test_outdated_revision_omits_the_stored_value():
    poisoned = f"0001-{SECRETS[2]}"
    with pytest.raises(SchemaOutdated) as caught:
        await check_database(RevisionEngine(poisoned))
    assert caught.value.category == "schema_outdated"
    assert MIGRATION_COMMAND in str(caught.value)
    assert poisoned not in str(caught.value)
    await check_database(RevisionEngine(SCHEMA_REVISION))


async def test_database_errors_drop_driver_text(caplog: pytest.LogCaptureFixture):
    caplog.set_level("DEBUG")
    with pytest.raises(SchemaOutdated) as missing:
        await check_database(ExplodingEngine(driver_error(ProgrammingError)))
    assert_no_secrets(str(missing.value))
    assert MIGRATION_COMMAND in str(missing.value)
    with pytest.raises(DatabaseUnreachable) as unreachable:
        await check_database(ExplodingEngine(driver_error(OperationalError)))
    assert unreachable.value.category == "database_unreachable"
    assert_no_secrets(str(unreachable.value))
    assert_no_secrets(caplog.text)


async def test_refused_connection_is_database_unreachable():
    engine = create_engine("postgresql+psycopg://jdr:synthetic-db-password@127.0.0.1:1/jdr_test")
    try:
        with pytest.raises(DatabaseUnreachable) as caught:
            await check_database(engine)
        assert_no_secrets(str(caught.value))
        assert caught.value.__cause__ is not None
    finally:
        await engine.dispose()


async def test_login_failure_is_classified_and_disposes_the_pool(settings: Settings, monkeypatch):
    engine = SimpleEngine()
    bot = MagicMock()
    bot.__aenter__ = AsyncMock(return_value=bot)
    bot.__aexit__ = AsyncMock(return_value=False)
    bot.start = AsyncMock(side_effect=discord.LoginFailure(SECRET_TEXT))
    bot.close = AsyncMock()
    monkeypatch.setattr("jdr_bot.__main__.create_engine", lambda _url: engine)
    monkeypatch.setattr("jdr_bot.__main__.TeamBot", lambda *_args: bot)
    with pytest.raises(DiscordLoginFailed) as caught:
        await run(settings)
    assert_no_secrets(str(caught.value))
    assert isinstance(caught.value.__cause__, discord.LoginFailure)
    bot.close.assert_awaited_once()
    engine.dispose.assert_awaited_once()


async def test_unauthorized_http_is_discord_login_failed(settings: Settings, monkeypatch):
    response = SimpleNamespace(status=401, reason=f"Unauthorized {SECRET_TEXT}")
    engine = SimpleEngine()
    bot = MagicMock()
    bot.__aenter__ = AsyncMock(return_value=bot)
    bot.__aexit__ = AsyncMock(return_value=False)
    bot.start = AsyncMock(side_effect=discord.HTTPException(response, SECRET_TEXT))
    bot.close = AsyncMock()
    monkeypatch.setattr("jdr_bot.__main__.create_engine", lambda _url: engine)
    monkeypatch.setattr("jdr_bot.__main__.TeamBot", lambda *_args: bot)
    with pytest.raises(DiscordLoginFailed) as caught:
        await run(settings)
    assert_no_secrets(str(caught.value))
    engine.dispose.assert_awaited_once()


async def test_forbidden_sync_stops_the_scheduler_without_the_body(settings: Settings, monkeypatch):
    monkeypatch.setattr("jdr_bot.bot.check_database", AsyncMock())
    scheduler = IdleScheduler()
    bot = TeamBot(settings, MagicMock(), scheduler=scheduler)
    response = SimpleNamespace(status=403, reason=f"Forbidden {SECRET_TEXT}")
    monkeypatch.setattr(
        bot.tree,
        "sync",
        AsyncMock(side_effect=discord.Forbidden(response, SECRET_TEXT)),
    )
    with pytest.raises(GuildSyncForbidden) as caught:
        await bot.setup_hook()
    assert caught.value.category == "guild_sync_forbidden"
    assert_no_secrets(str(caught.value))
    assert isinstance(caught.value.__cause__, discord.Forbidden)
    assert bot._scheduler_task is None
