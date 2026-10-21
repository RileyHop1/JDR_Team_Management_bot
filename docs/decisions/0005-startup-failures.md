# 0005: Startup failure categories

Status: accepted for this implementation.

`main` maps startup failures to fixed categories and exits non-zero. Invalid core configuration and an incomplete or rejected Jira morning-brief group exit 2. An unreachable database, an outdated schema, Discord login failure, forbidden guild command sync, and unexpected failures exit 1.

The log line is the category plus a fixed hint. Configuration lines also name the fields. The process does not log exception messages, driver text, the revision value read from `alembic_version`, tokens, database URLs, Jira email, or JQL. That revision is omitted because the column is data, not a constant. The original exception stays attached as the cause for a debugger that already has the secret, and it is not written to the log.

Command sync forbidden is the Discord 403 raised by guild command sync. `LoginFailure` or HTTP 401 from the Discord client is `discord_login_failed`. A missing schema relation, or a revision other than the application constant, is `schema_outdated`. Other database errors at that check are `database_unreachable`. Any other exception is `startup_failed` with `error_type` set to the class name.

`migrations/env.py` reads `DATABASE_URL` through a guard. Alembic does not load `.env`. A missing or blank variable exits before a connection and names `uv run --env-file .env alembic upgrade head`. The URL is not printed.

Stored guild settings are not validated at process start. An unusable stored zone or brief time remains `brief_schedule_invalid` on the brief poll.
