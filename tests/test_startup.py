"""Startup categories are actionable and never echo synthetic secrets."""

import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import psycopg.errors as pg_errors
import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.ext.asyncio import AsyncEngine

from jdr_bot.__main__ import main, run
from jdr_bot.bot import TeamBot
from jdr_bot.brief import compile_schedule
from jdr_bot.config import Settings
from jdr_bot.startup import (
    MIGRATION_COMMAND,
    BriefSettingError,
    DatabasePermissionDenied,
    DatabaseUnreachable,
    DiscordLoginFailed,
    GuildSyncForbidden,
    InvalidConfiguration,
    InvalidJiraConfiguration,
    SchemaOutdated,
    StartupFailure,
    configuration_failure,
    failure_for_brief_setting,
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


def test_brief_setting_error_carries_a_fixed_field():
    base_url = BriefSettingError("jira_base_url", f"JIRA_BASE_URL {SECRET_TEXT}")
    base_failure = failure_for_brief_setting(base_url)
    assert isinstance(base_failure, InvalidJiraConfiguration)
    assert base_failure.fields == ("jira_base_url",)
    assert_no_secrets(str(base_failure))

    jql_failure = failure_for_brief_setting(BriefSettingError("jira_jql", SECRET_TEXT))
    assert jql_failure.fields == ("jira_jql",)

    unknown = BriefSettingError(f"rejected-{SECRET_TEXT}", SECRET_TEXT)
    assert unknown.field == "jira_configuration"
    fallback = failure_for_brief_setting(unknown)
    assert isinstance(fallback, InvalidJiraConfiguration)
    assert fallback.fields == ("jira_configuration",)
    assert_no_secrets(str(fallback))
    assert_no_secrets(unknown.field)

    plain = failure_for_brief_setting(ValueError(SECRET_TEXT))
    assert plain.fields == ("jira_configuration",)
    assert SECRET_TEXT not in str(plain)

    zone = failure_for_brief_setting(
        BriefSettingError("bot_timezone", "use an IANA time zone such as America/Los_Angeles")
    )
    assert isinstance(zone, InvalidConfiguration)
    assert zone.category == "invalid_configuration"
    assert zone.fields == ("bot_timezone",)
    schedule_error = None
    try:
        compile_schedule(
            guild_id=1,
            channel_id=10,
            timezone_name="x" * 65,
            brief_time="09:00",
            base_url="https://example.atlassian.net",
            project_key="JDR",
            status_names="In Progress",
            custom_jql=None,
        )
    except BriefSettingError as error:
        schedule_error = error
    assert schedule_error is not None
    assert schedule_error.field == "bot_timezone"
    assert isinstance(failure_for_brief_setting(schedule_error), InvalidConfiguration)


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
        (DatabasePermissionDenied(), "database_permission_denied", 1),
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
    if isinstance(failure, DatabasePermissionDenied):
        assert MIGRATION_COMMAND not in caplog.text
        assert "grant it access" in caplog.text
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


def programming_error(original: BaseException) -> ProgrammingError:
    return ProgrammingError("SELECT version_num FROM alembic_version", {}, original)


async def test_database_errors_drop_driver_text(caplog: pytest.LogCaptureFixture):
    caplog.set_level("DEBUG")
    with pytest.raises(DatabaseUnreachable) as generic:
        await check_database(ExplodingEngine(driver_error(ProgrammingError)))
    assert generic.value.category == "database_unreachable"
    assert MIGRATION_COMMAND not in str(generic.value)
    assert_no_secrets(str(generic.value))
    with pytest.raises(DatabaseUnreachable) as unreachable:
        await check_database(ExplodingEngine(driver_error(OperationalError)))
    assert unreachable.value.category == "database_unreachable"
    assert_no_secrets(str(unreachable.value))
    assert_no_secrets(caplog.text)


@pytest.mark.parametrize(
    ("original", "expected", "sqlstate"),
    [
        (pg_errors.UndefinedTable(SECRET_TEXT), SchemaOutdated, "42P01"),
        (pg_errors.UndefinedColumn(SECRET_TEXT), SchemaOutdated, "42703"),
        (pg_errors.InsufficientPrivilege(SECRET_TEXT), DatabasePermissionDenied, "42501"),
        (pg_errors.SyntaxError(SECRET_TEXT), DatabaseUnreachable, "42601"),
    ],
)
async def test_programming_error_uses_sqlstate(
    original: pg_errors.Error,
    expected: type[StartupFailure],
    sqlstate: str,
) -> None:
    assert original.sqlstate == sqlstate
    with pytest.raises(expected) as caught:
        await check_database(ExplodingEngine(programming_error(original)))
    assert_no_secrets(str(caught.value))
    if expected is SchemaOutdated:
        assert MIGRATION_COMMAND in str(caught.value)
    else:
        assert MIGRATION_COMMAND not in str(caught.value)


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError(SECRET_TEXT),
        OSError(SECRET_TEXT),
        SATimeoutError(SECRET_TEXT),
    ],
)
async def test_timeout_and_oserror_are_database_unreachable(error: Exception) -> None:
    with pytest.raises(DatabaseUnreachable) as caught:
        await check_database(ExplodingEngine(error))
    assert caught.value.category == "database_unreachable"
    assert MIGRATION_COMMAND not in str(caught.value)
    assert_no_secrets(str(caught.value))


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


async def test_non_sync_forbidden_is_not_rewritten(settings: Settings, monkeypatch):
    response = SimpleNamespace(status=403, reason=f"Forbidden {SECRET_TEXT}")
    engine = SimpleEngine()
    bot = MagicMock()
    bot.__aenter__ = AsyncMock(return_value=bot)
    bot.__aexit__ = AsyncMock(return_value=False)
    bot.start = AsyncMock(side_effect=discord.Forbidden(response, SECRET_TEXT))
    bot.close = AsyncMock()
    monkeypatch.setattr("jdr_bot.__main__.create_engine", lambda _url: engine)
    monkeypatch.setattr("jdr_bot.__main__.TeamBot", lambda *_args: bot)
    with pytest.raises(discord.Forbidden) as caught:
        await run(settings)
    assert isinstance(caught.value, discord.Forbidden)
    engine.dispose.assert_awaited_once()


def test_main_non_sync_forbidden_is_startup_failed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, settings: Settings
) -> None:
    response = SimpleNamespace(status=403, reason=f"Forbidden {SECRET_TEXT}")

    def load_settings() -> Settings:
        return settings

    async def fail_run(_settings: Settings) -> None:
        raise discord.Forbidden(response, SECRET_TEXT)

    monkeypatch.setattr("jdr_bot.__main__.Settings", load_settings)
    monkeypatch.setattr("jdr_bot.__main__.run", fail_run)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert "startup_failed error_type=Forbidden" in caplog.text
    assert "guild_sync_forbidden" not in caplog.text
    assert_no_secrets(caplog.text)
    assert all(record.exc_info is None for record in caplog.records)


async def test_sync_http_error_stops_the_scheduler(settings: Settings, monkeypatch):
    monkeypatch.setattr("jdr_bot.bot.check_database", AsyncMock())
    scheduler = IdleScheduler()
    bot = TeamBot(settings, MagicMock(), scheduler=scheduler)
    response = SimpleNamespace(status=500, reason=SECRET_TEXT)
    monkeypatch.setattr(
        bot.tree,
        "sync",
        AsyncMock(side_effect=discord.HTTPException(response, SECRET_TEXT)),
    )
    with pytest.raises(discord.HTTPException):
        await bot.setup_hook()
    assert bot._scheduler_task is None


def require_test_database() -> tuple[str, str]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL to a disposable PostgreSQL database ending in _test")
    database = make_url(url).database or ""
    assert database.endswith("_test"), "refusing a non-test database"
    assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", database), (
        "refusing a database name that is not a simple identifier"
    )
    return url, database


async def alembic_upgrade(url: str) -> None:
    environment = {**os.environ, "DATABASE_URL": url}
    process = await asyncio.create_subprocess_exec("alembic", "upgrade", "head", env=environment)
    assert await process.wait() == 0


async def autocommit(
    engine: AsyncEngine, statement: str, parameters: dict[str, str] | None = None
) -> None:
    async with engine.connect() as connection:
        autocommit_connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit_connection.execute(text(statement), parameters or {})


def assert_driver_sqlstate(
    failure: StartupFailure, sqlstate: str, driver_type: type[pg_errors.Error]
) -> None:
    cause = failure.__cause__
    assert isinstance(cause, ProgrammingError)
    assert isinstance(cause.orig, driver_type)
    assert cause.orig.sqlstate == sqlstate
    assert_no_secrets(str(failure))


_DENIED_ROLE = "jdr_schema_denied"
_DENIED_PASSWORD = "synthetic-db-password"


@pytest.mark.integration
async def test_postgres_schema_sqlstates():
    url, database = require_test_database()
    await alembic_upgrade(url)
    engine = create_engine(url)
    denied_engine = None
    hidden_table = False
    hidden_column = False
    created_role = False
    revoked_public = False
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE alembic_version RENAME TO alembic_version_hidden")
            )
        hidden_table = True
        with pytest.raises(SchemaOutdated) as missing_table:
            await check_database(engine)
        assert missing_table.value.category == "schema_outdated"
        assert MIGRATION_COMMAND in str(missing_table.value)
        assert_driver_sqlstate(missing_table.value, "42P01", pg_errors.UndefinedTable)
        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE alembic_version_hidden RENAME TO alembic_version")
            )
        hidden_table = False

        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE alembic_version RENAME COLUMN version_num TO version_num_hidden")
            )
        hidden_column = True
        with pytest.raises(SchemaOutdated) as missing_column:
            await check_database(engine)
        assert MIGRATION_COMMAND in str(missing_column.value)
        assert_driver_sqlstate(missing_column.value, "42703", pg_errors.UndefinedColumn)
        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE alembic_version RENAME COLUMN version_num_hidden TO version_num")
            )
        hidden_column = False

        await autocommit(
            engine,
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = :role",
            {"role": _DENIED_ROLE},
        )
        await autocommit(engine, f"DROP ROLE IF EXISTS {_DENIED_ROLE}")
        await autocommit(
            engine,
            f"CREATE ROLE {_DENIED_ROLE} LOGIN PASSWORD '{_DENIED_PASSWORD}'",
        )
        created_role = True
        await autocommit(engine, f"GRANT CONNECT ON DATABASE {database} TO {_DENIED_ROLE}")
        await autocommit(engine, f"GRANT USAGE ON SCHEMA public TO {_DENIED_ROLE}")
        async with engine.connect() as connection:
            allowed = await connection.scalar(
                text("SELECT has_table_privilege(:role, 'alembic_version', 'SELECT')"),
                {"role": _DENIED_ROLE},
            )
        if allowed:
            await autocommit(engine, "REVOKE ALL ON TABLE alembic_version FROM PUBLIC")
            revoked_public = True
        denied_url = make_url(url).set(username=_DENIED_ROLE, password=_DENIED_PASSWORD)
        denied_engine = create_engine(denied_url.render_as_string(hide_password=False))
        with pytest.raises(DatabasePermissionDenied) as denied:
            await check_database(denied_engine)
        assert denied.value.category == "database_permission_denied"
        assert MIGRATION_COMMAND not in str(denied.value)
        assert "grant it access" in str(denied.value)
        assert_no_secrets(str(denied.value))
        assert_driver_sqlstate(denied.value, "42501", pg_errors.InsufficientPrivilege)
    finally:
        if denied_engine is not None:
            await denied_engine.dispose()
        if hidden_column:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "ALTER TABLE alembic_version "
                        "RENAME COLUMN version_num_hidden TO version_num"
                    )
                )
        if hidden_table:
            async with engine.begin() as connection:
                await connection.execute(
                    text("ALTER TABLE alembic_version_hidden RENAME TO alembic_version")
                )
        if revoked_public:
            await autocommit(
                engine,
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE alembic_version TO PUBLIC",
            )
        if created_role:
            await autocommit(
                engine,
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = :role",
                {"role": _DENIED_ROLE},
            )
            await autocommit(engine, f"REVOKE ALL ON DATABASE {database} FROM {_DENIED_ROLE}")
            await autocommit(engine, f"REVOKE ALL ON SCHEMA public FROM {_DENIED_ROLE}")
            await autocommit(engine, f"REVOKE ALL ON TABLE alembic_version FROM {_DENIED_ROLE}")
            await autocommit(engine, f"DROP ROLE IF EXISTS {_DENIED_ROLE}")
        await engine.dispose()
