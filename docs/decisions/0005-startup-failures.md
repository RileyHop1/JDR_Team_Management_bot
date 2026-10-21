# 0005: Startup failure categories

Status: accepted for this implementation. Merged in [PR #18](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/18). Hosted CI passed ([workflow run](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39537651270)). GitHub issue [#10](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/10) is closed. This record does not leave a separate team-confirmation step open. No live Discord check was required.

`main` maps startup failures to fixed categories and exits non-zero. Invalid core configuration and an incomplete or rejected Jira morning-brief group exit 2. An unreachable database, a role that can connect but cannot read the schema, an outdated schema, Discord login failure, forbidden guild command sync, and unexpected failures exit 1.

The log line is the category plus a fixed hint. Configuration lines also name the fields. The process does not log exception messages, driver text, SQLSTATE codes, the revision value read from `alembic_version`, tokens, database URLs, Jira email, or JQL. That revision is omitted because the column is data, not a constant. The original exception stays attached as the cause for a debugger that already has the secret, and it is not written to the log.

Command sync forbidden is the Discord 403 raised by guild command sync. A Discord 403 from anywhere else stays `startup_failed` with `error_type` set to the exception class. `LoginFailure` or HTTP 401 from the Discord client is `discord_login_failed`. At the schema check, PostgreSQL SQLSTATE 42P01 (undefined table) and 42703 (undefined column), or a revision other than the application constant, are `schema_outdated` and name the migration command. SQLSTATE 42501 (insufficient privilege) is `database_permission_denied`: the hint says to grant the role access to the tables and does not name the migration command. Every other database error at that check, including any other SQLSTATE, is `database_unreachable`, so the operator is not told to migrate. Any other exception is `startup_failed` with `error_type` set to the class name.

Brief validators raise `BriefSettingError` with a fixed field name. `bot_timezone` is `invalid_configuration`. A known brief field is `invalid_jira_configuration`. A name that is not one of those fields, or a `ValueError` that carries no field, is logged as `fields=jira_configuration`. The validator message is not copied. `Settings` rejects `bot_timezone` before `compile_schedule` checks the zone length, so process startup does not reach that branch. The field is still `bot_timezone` if another caller does.

`migrations/env.py` reads `DATABASE_URL` through a guard. Alembic does not load `.env`. A missing or blank variable exits before a connection and names `uv run --env-file .env alembic upgrade head`. The URL is not printed.

Stored guild settings are not validated at process start. An unusable stored zone or brief time remains `brief_schedule_invalid` on the brief poll.
