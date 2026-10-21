# 0001: Single-guild Python foundation

Status: accepted for the initial implementation and merged in [PR #9](https://github.com/RileyHop1/JDR_Team_Management_bot/pull/9). Hosted CI passed ([workflow run](https://github.com/RileyHop1/JDR_Team_Management_bot/actions/runs/38816010204)). Live Discord validation is still pending. GitHub issue [#5](https://github.com/RileyHop1/JDR_Team_Management_bot/issues/5) stays open until that smoke check passes.

Use Python 3.12.14, uv with a committed lockfile, discord.py 2.x for guild-scoped slash commands, Pydantic Settings for configuration, SQLAlchemy/psycopg for asynchronous PostgreSQL access, and Alembic migrations. PostgreSQL 16 is the development/CI baseline.

Use Ruff for formatting/lint, strict mypy for production modules, and pytest with pytest-asyncio. CI runs these checks plus a real disposable PostgreSQL migration test. Role-based management authorization requires the configured operator role and guild, even for administrators. Basic `/ping` is available to members of the configured guild.

Start with no privileged gateway intents and no global commands. Deployment is single guild and single process on Linux/macOS; multi-guild administration and Windows signal integration need separate work. No voice receive library or transcription provider is selected by this decision: command support does not establish voice capture compatibility.
