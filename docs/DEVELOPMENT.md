# Development and operations

## Install

Use Python **3.12.14**, uv **0.12.23**, and PostgreSQL **16**. The Python patch is pinned in `.python-version`; `uv.lock` pins runtime and development dependencies. The initial executable supports Linux/macOS signal handling; Windows users should use WSL or a Linux container.

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

Wait for `accepting connections` before migrating. Use `docker start jdr-dev-postgres` after stopping this container. Without an explicit volume, deleting the container deletes its database; production needs durable storage and backups. Do not expose this test password or database outside loopback.

Copy `.env.example` to a new ignored `.env` without overwriting any existing configuration. Set actual test-server IDs, an operator role ID, and a securely stored bot token. Environment variables take precedence over `.env`. The example token is intentionally rejected.

```sh
uv run --env-file .env alembic upgrade head
uv run jdr-bot
```

Migrations require only `DATABASE_URL`. Never run migrations against an unknown database. Generate future migrations with `uv run --env-file .env alembic revision --autogenerate -m "description"`, inspect the generated SQL/Python, and update the application's expected schema revision. Back up deployed databases before schema changes; downgrade may delete data.

## Discord smoke check (required before issue #5 is complete)

1. Install a dedicated test bot in a private test guild with `bot` and `applications.commands` scopes. Permit viewing the test channel and sending messages; no Administrator or privileged intents are required for these commands.
2. Set `DISCORD_GUILD_ID` and `DISCORD_OPERATOR_ROLE_ID` to the test guild and its dedicated operator role. Grant yourself that role.
3. Start the migrated application. Startup verifies the schema before syncing `/ping` and `/status` to that guild only. Guild sync replaces that application's existing commands in the selected guild; use a dedicated bot during development.
4. Run `/ping` and expect an ephemeral `Pong!`. As an operator, run `/status` and expect `Database ready.`
5. As a member without the configured role, run `/status` and expect `Operator role required.` Administrators also need the configured role.
6. Send SIGTERM or press Ctrl-C. Confirm the process exits and the bot disconnects. Restart it and repeat `/ping`.

A successful offline test is not evidence that this live check passed. Record the result in the PR without publishing tokens or personal server content.

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

Run `createdb` only once. The integration test upgrades and downgrades the schema, temporarily changes the migration version, and verifies rollback and constraints. Do not point it at a shared or valuable database; the name guard is only a safeguard. Do not run concurrent integration suites against the same database. CI provisions a fresh PostgreSQL service and sets the test URL so this check executes.

## Troubleshooting and limits

- `invalid_configuration`: inspect the named fields against `.env.example`; the process deliberately omits submitted values.
- `startup_failed`: verify the database is reachable and migrated, the bot token is valid, and the bot is installed in the configured guild. Raw exceptions are intentionally not printed because providers may include credentials.
- Missing slash commands: check guild ID, installation scopes, and successful startup; commands are never registered globally.
- Failed `/status`: inspect database health and migration revision. Queries and connection attempts have bounded timeouts.
- This foundation does not schedule jobs, access Jira, receive voice audio, or record/transcribe meetings.
- discord.py currently emits an upstream Python `audioop` deprecation warning; the project stays on Python 3.12 pending a tested upgrade.
