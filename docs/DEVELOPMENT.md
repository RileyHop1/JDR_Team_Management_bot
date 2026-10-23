# Development and operations

## Current verification status

These behaviors are merged on `main`, and hosted CI passed on each pull request. Offline tests do not replace the live checks later in this page.

- Foundation, [PR #9](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/9) ([CI passed](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/38816010204)). The Discord smoke check below is still required before issue [#5](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/5) is complete.
- Meeting reminders, [PR #15](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/15) ([CI passed](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39085620688)). The reminder smoke check below has not been run. [Decision 0002](decisions/0002-meeting-reminders.md) needs team confirmation. Issue [#6](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/6) stays open.
- Jira morning brief, [PR #16](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/16) ([CI passed](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39097915833)). The brief smoke check below has not been run. [Decision 0003](decisions/0003-jira-morning-brief.md) needs team confirmation. Issue [#7](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/7) stays open.
- Guild configuration, [PR #17](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/17) ([CI passed](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39531857559)). Issue [#11](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/11) is closed. The `/config` smoke check below has not been run, and [decision 0004](decisions/0004-guild-configuration.md) still needs team confirmation.
- Startup failure categories, [PR #18](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/18) ([CI passed](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/39537651270)). Issue [#10](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/10) is closed. [Decision 0005](decisions/0005-startup-failures.md) is accepted for this implementation. No separate live Discord check was required.

[PR #4](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/4) merged the meeting-transcript planning document only; implementation has not started (issue [#8](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/8)). The retention period is approved in [decision 0007](decisions/0007-meeting-data-retention.md): meeting content is deleted within 30 days of capture end, with live copies purged at capture end plus 23 days and every dump file deleted before it is 7 days old. Issue [#8](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/8) stays open because capture is not implemented and voice UDP on the Pi has not been verified. The hosting choice and the production procedure are recorded in provisional [decision 0006](decisions/0006-raspberry-pi-hosting.md) and the [production runbook](operations/runbook.md). Live verification of a gateway session and of voice UDP on the Pi has not been run, so issue [#12](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/12) stays open. [PR #20](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/20) adds the GitHub issue and pull request templates ([`.github/ISSUE_TEMPLATE/feature_task.md`](../.github/ISSUE_TEMPLATE/feature_task.md) and [`.github/pull_request_template.md`](../.github/pull_request_template.md)) and closes issue [#14](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/14).

## Install

Use Python **3.12.14**, uv **0.12.23**, and PostgreSQL **16**. The Python patch is pinned in `.python-version`; `uv.lock` pins runtime and development dependencies. The executable supports Linux/macOS signal handling; Windows users should use WSL or a Linux container.

From the repository root:

```sh
uv python install
uv sync --locked
```

In a restricted cloud workspace where the default uv cache is read-only, set `UV_CACHE_DIR=/workspace/.cache/uv` before using uv. Use the existing checkout in isolated cloud tasks; do not create a worktree unless requested.

## Local database

For disposable development only (the password below is deliberately not a deployment credential):

```sh
docker run --detach --name jdr-dev-postgres \
  --publish 127.0.0.1:5432:5432 \
  --env POSTGRES_USER=jdr --env POSTGRES_PASSWORD=jdr \
  --env POSTGRES_DB=jdr postgres:16

docker exec jdr-dev-postgres pg_isready -U jdr -d jdr
```

Wait for `accepting connections` before migrating. Use `docker start jdr-dev-postgres` after stopping this container. Without an explicit volume, deleting the container deletes its database. Production storage, backups, and the PostgreSQL 16 package on the Pi are in the [production runbook](operations/runbook.md). Do not reuse this test password there. Do not expose this test password or database outside loopback.

Copy `.env.example` to a new ignored `.env` without overwriting any existing configuration. Set actual test-server IDs, an operator role ID, and a securely stored bot token. Environment variables take precedence over `.env`. The example token is intentionally rejected.

```sh
uv run --env-file .env alembic upgrade head
uv run jdr-bot
```

Migrations require only `DATABASE_URL`. Alembic does not read `.env` by itself; `uv run --env-file .env` loads it. If `DATABASE_URL` is missing or blank, the migration runner exits before connecting and prints that command. It does not raise `KeyError` and it does not print a URL. Never run migrations against an unknown database. Generate future migrations with `uv run --env-file .env alembic revision --autogenerate -m "description"`, inspect the generated SQL/Python, and update the application's expected schema revision. Revision `0004` adds nullable guild settings. Downgrading it deletes those stored values. Back up deployed databases before schema changes; downgrade may delete data.

## Discord smoke check (required before issue #5 is complete)

1. Install a dedicated test bot in a private test guild with `bot` and `applications.commands` scopes. Permit viewing the test channel and sending messages; no Administrator or privileged intents are required for these commands.
2. Set `DISCORD_GUILD_ID` and `DISCORD_OPERATOR_ROLE_ID` to the test guild and its dedicated operator role. Grant yourself that role.
3. Start the migrated application. Startup verifies the schema before syncing `/ping`, `/status`, `/meeting`, and `/config` to that guild only. Guild sync replaces that application's existing commands in the selected guild; use a dedicated bot during development.
4. Run `/ping` and expect an ephemeral `Pong!`. As an operator, run `/status` and expect `Database ready.`
5. As a member without the configured role, run `/status` and expect `Operator role required.` Administrators also need the configured role.
6. Send SIGTERM or press Ctrl-C. Confirm the process exits and the bot disconnects. Restart it and repeat `/ping`.

A successful offline test is not evidence that this live check passed. Record the result in the PR without publishing tokens or personal server content.

## Meeting reminder smoke check (required before issue #6 is complete)

This check has not been run. Offline tests do not replace it.

1. Complete the foundation smoke check above. Apply migrations through revision `0004` (`uv run --env-file .env alembic upgrade head`). The process rejects an older schema even when the morning brief is left unset. Downgrading from `0004` to `0003` drops stored guild settings.
2. As an operator, run `/meeting create` with a synthetic title, a start a few minutes ahead, `BOT_TIMEZONE` or an explicit IANA zone, a text channel the bot can post in, a different voice channel it can view, and offset `1`.
3. Confirm the ephemeral reply shows the meeting id, local start, UTC instant, and `1 min before: scheduled`. As a member without the operator role, confirm `/meeting list` returns `Operator role required.`
4. Wait until one minute before the start. Confirm one reminder appears in the text channel, with no user or role mentions, and that `/meeting view` shows `delivered` plus a message id.
5. Stop the process, start it again, and confirm a future reminder is still scheduled. A reminder whose due time is more than 60 seconds in the past should be `skipped (missed_window)` rather than sent late.
6. Cancel the meeting with `/meeting cancel` and confirm no further reminder is posted.

Do not put real meeting titles, attendance, or tokens in the PR. Say only whether each step passed.

## Jira morning brief smoke check (required before issue #7 is complete)

This check has not been run. Offline tests do not replace it. Use a Jira user that cannot edit issues, and a private Discord channel.

1. Complete the foundation smoke check. Apply migrations through revision `0004`. A stored brief channel, time, or time zone overrides the environment value. With no guild row, `BRIEF_CHANNEL_ID`, `BRIEF_TIME`, and `BOT_TIMEZONE` are used.
2. Set `BRIEF_CHANNEL_ID` to a text channel the bot can view and send in. Set `BRIEF_TIME` a few minutes ahead in `BOT_TIMEZONE`, on a weekday. Set `JIRA_BASE_URL`, `JIRA_PROJECT_KEY`, `JIRA_USER_EMAIL`, and `JIRA_API_TOKEN`. Set `JIRA_STATUS_NAMES` to the team's confirmed statuses, or set `JIRA_JQL` to the confirmed query.
3. Start the process. The log should include `brief_scheduler_enabled` and must not include the token, the email, or the JQL text.
4. At the local brief time, confirm one message in the brief channel. It should list issue key, title, assignee or `unassigned`, status, and a browse URL, with no user or role mentions. An assignee that Jira returns without a display name is `assignee name unavailable`, not `unassigned`. If the query matches nothing, the message includes the `Morning brief for …` header, either `Statuses: …` or `Using the configured Jira query.`, and the line `No issues match the configured Jira query.` It must not invent issues.
5. Restart the process the same day and confirm the brief is not posted a second time. A row whose local date has already passed should not be posted on a later day.

Do not put real issue titles, assignee names, JQL, or tokens in the PR. Say only whether each step passed.

## Guild configuration smoke check

This check has not been run. Offline tests do not replace it. [PR #17](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/17) merged the commands and closed issue [#11](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/11). The check is still outstanding, as is team confirmation of [decision 0004](decisions/0004-guild-configuration.md).

1. Complete the foundation smoke check. Apply migrations through revision `0004`.
2. As an operator, run `/config view`. With no stored row, the time zone should be `BOT_TIMEZONE` and marked `environment`. Meetings channel and brief time are `not set` unless those environment values are present.
3. Run `/config set` with a text channel the bot can view and send in, an IANA zone, and a brief time such as `09:30`. The reply should mark those values `stored`. As a member without the operator role, `/config view` returns `Operator role required.`
4. Run `/meeting create` and omit the zone. The meeting should use the stored zone. Set the zone explicitly on another meeting and confirm that meeting keeps the explicit zone.
5. If the brief is enabled, change the brief channel or time with `/config set`. The next poll should use the new channel and time for a future brief. A brief already delivered that day should not be posted again.
6. Run `/config set` with `clear` set to the time zone. `/config view` should show `BOT_TIMEZONE` as `environment` again.

Do not put tokens or private channel names in the PR. Say only whether each step passed.

## Quality checks

```sh
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -v
```

Without `TEST_DATABASE_URL`, the PostgreSQL integration test is explicitly skipped. To run all tests, provision a **dedicated disposable database whose name ends in `_test`**:

```sh
docker exec jdr-dev-postgres createdb -U jdr jdr_test
TEST_DATABASE_URL=postgresql+psycopg://jdr:jdr@localhost:5432/jdr_test uv run pytest -v
```

Run `createdb` only once. The integration tests upgrade the schema, and the foundation test also downgrades it, temporarily changes the migration version, and verifies rollback and constraints. They delete `brief_jobs` first, then `reminder_jobs`, `meetings`, and `guild_configurations`. The foreign key requires `brief_jobs` to go before `guild_configurations`. Do not point them at a shared or valuable database; the name guard is only a safeguard. Do not run concurrent integration suites against the same database. CI provisions a fresh PostgreSQL service and sets the test URL so this check executes.

## Troubleshooting and limits

Startup logs one fixed category and a fixed hint. It does not log exception text, driver messages, the observed migration revision, tokens, database URLs, Jira email, or JQL. Configuration failures exit 2. Every other startup failure exits 1. See [decision 0005](decisions/0005-startup-failures.md).

- `invalid_configuration`: a core setting is missing or rejected. The log names the fields, for example `discord_bot_token`, `database_url`, or `bot_timezone`. Compare them with `.env.example`. Submitted values are omitted.
- `invalid_jira_configuration`: the morning-brief group is only partly set, or a brief or Jira value was rejected. The log names fields such as `jira_api_token`, `jira_base_url`, `jira_user_email`, `jira_jql`, or `jira_status_names`. A token that still starts with `replace-` uses this category. `fields=jira_configuration` means the brief check failed without a known field name; the validator message is omitted so a value cannot become the field. Values are omitted. One field name can mean that setting is missing or that its value was rejected. See [Jira morning brief](features/jira-morning-brief.md).
- `database_unreachable`: PostgreSQL could not be used, or the schema check returned a SQLSTATE other than a missing table, a missing column, or insufficient privilege. Confirm the server is running and the role in `DATABASE_URL` can connect. The URL and the driver message are omitted. This category does not tell you to migrate.
- `database_permission_denied`: the role can connect, but it cannot read the schema (PostgreSQL SQLSTATE 42501). Grant that role access to the tables. The log does not include the driver message and does not tell you to migrate.
- `schema_outdated`: a schema object is missing (SQLSTATE 42P01 or 42703), or `alembic_version` is not the revision this process expects. Run `uv run --env-file .env alembic upgrade head`. The revision read from the database is omitted.
- `discord_login_failed`: Discord rejected the bot token, including HTTP 401. Set `DISCORD_BOT_TOKEN` from the developer portal. The token and the response body are omitted.
- `guild_sync_forbidden`: command sync was forbidden. Install the bot in `DISCORD_GUILD_ID` with the `bot` and `applications.commands` scopes. The Discord response body is omitted.
- `startup_failed`: an unexpected failure. The log includes `error_type` (the exception class name) and says to check credentials, connectivity, permissions, and migrations. The exception message is omitted. A Discord 403 that is not command sync uses this category.
- Migrations with `DATABASE_URL` unset stop before connecting. The message names `uv run --env-file .env alembic upgrade head`.
- A stored guild zone or brief time that cannot be validated does not fail startup. The next brief poll logs `brief_schedule_invalid` without the value. See [guild configuration](features/guild-configuration.md).
- Missing slash commands: check guild ID, installation scopes, and successful startup; commands are never registered globally.
- Failed `/status`: the reply stays `Database unavailable; contact a maintainer.` The log is `database_readiness_failed`, plus `category=schema_outdated`, `category=database_unreachable`, or `category=database_permission_denied` when the failure is one of those. Queries and connection attempts have bounded timeouts.
- Reminder jobs and, when configured, the morning brief run in one background task inside this process. Voice receive and transcription are not implemented. Two processes on the same database can deliver the same reminder or brief twice.
- A reminder older than 60 seconds is skipped, not sent late. See [meeting reminders](features/meeting-reminders.md) for command errors and job states.
- A morning brief is sent only on its local weekday, including later that same day. Older brief rows are not posted late. See [Jira morning brief](features/jira-morning-brief.md). The brief stays off until its environment group is complete. A stored brief channel, time, or zone overrides that environment on the next poll. See [guild configuration](features/guild-configuration.md).
- `/config` changes the guild defaults. It does not rewrite meetings that already exist. Clearing a stored field returns that field to the environment. `guild_config_updated` logs field names only.
- discord.py currently emits an upstream Python `audioop` deprecation warning; the project stays on Python 3.12 pending a tested upgrade.
